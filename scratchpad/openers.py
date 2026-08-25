"""Is the leash gain real starters, or just openers slipping into the pool?"""
import statistics as st
from collections import defaultdict
from scratchpad.between import load
from src.context.leash import shrink_k

for src in ("scratchpad/ceiling_rows.json", "scratchpad/ceiling_holdout.json"):
    rows = sorted(load(src), key=lambda r: (r["date"], r["game_id"]))
    med = defaultdict(list)
    for r in rows:
        med[r["player"]].append(r["a_outs"])
    med = {p: st.median(v) for p, v in med.items()}
    print(f"\n=== {src} ({len(rows)} starts) ===")
    for name, keep in (("ALL", lambda p: True),
                       ("median outs >= 12 (real rotation)", lambda p: med[p] >= 12),
                       ("median outs >= 15", lambda p: med[p] >= 15),
                       ("median outs < 12 (openers/bulk)", lambda p: med[p] < 12)):
        sub = [r for r in rows if keep(r["player"])]
        if len(sub) < 100:
            print(f"  {name:<34} n={len(sub)} too small"); continue
        by = defaultdict(list)
        for r in sub:
            by[r["player"]].append(r["a_outs"] - r["m_outs"])
        k, betw, wit = shrink_k(by)
        hist, base, act, off = defaultdict(list), [], [], []
        for r in sub:
            h = hist[r["player"]]
            base.append(r["m_outs"]); act.append(r["a_outs"])
            off.append(st.mean(h) * len(h) / (len(h) + k) if len(h) >= 3 else 0.0)
            hist[r["player"]].append(r["a_outs"] - r["m_outs"])
        live = [i for i, v in enumerate(off) if v != 0.0]
        def sc(m, a):
            sm, sa = st.pstdev(m), st.pstdev(a)
            mm, ma = st.mean(m), st.mean(a)
            r = sum((x-mm)*(y-ma) for x, y in zip(m, a))/(len(a)*sm*sa) if sm and sa else 0
            return sm, r, st.mean((x-y)**2 for x, y in zip(m, a))**0.5
        a = [act[i] for i in live]
        b = sc([base[i] for i in live], a)
        o = sc([base[i]+off[i] for i in live], a)
        print(f"  {name:<34} n={len(live):>5} pitchers={len(by):>4} "
              f"K={k:>4.1f} betw={betw:.2f}")
        print(f"      base    spread {b[0]:.2f}  corr {b[1]:+.3f}  RMSE {b[2]:.3f}")
        print(f"      +leash  spread {o[0]:.2f}  corr {o[1]:+.3f}  RMSE {o[2]:.3f}")
