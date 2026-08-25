"""Refit the early branch AT each cutoff, then score the distribution.

Applying an innings-1-3 fit to a cutoff of 4 or 5 tests the wrong thing —
the coefficients describe a population the branch is no longer handling. So
each cutoff gets its own fit before it gets scored.
"""
import random
import statistics as st
from collections import Counter

import numpy as np
from sklearn.linear_model import LogisticRegression

from src.context import boundary, calibrate as cal, game, removal, sim
from src.context.sources import pbp, rates as rate_src


def fit_at(mid, cutoff):
    sub = [r for r in mid if r["inning"] <= cutoff]
    X = np.array([[float(r["pitches"]), sim.inning_run_offset(r["inn_runs"]),
                   float(r["inn_br"])] for r in sub])
    y = np.array([1 if r["removed"] else 0 for r in sub])
    m = LogisticRegression(max_iter=3000, C=1.0).fit(X, y)
    p = m.predict_proba(X)[:, 1]
    b0 = float(m.intercept_[0])
    bp, bo, bb = [float(x) for x in m.coef_[0]]
    return {"cutoff": cutoff, "n": len(sub), "base": float(y.mean()),
            "auc": removal.auc(y, p), "offset": b0 - sim.Hook().mid_intercept,
            "per_pitch": bp, "per_run_offset": bo, "per_inning_br": bb}


def desc(o, lbl):
    n = len(o)
    m = st.mean(o)
    c = Counter(o)
    sh = [x for x in o if x < 12]
    return (f"  {lbl:<14}mean {m:>5.2f}  sd {st.pstdev(o):>4.2f}  "
            f"<2inn {sum(1 for x in o if x < 6) / n:>5.2%}  "
            f"<4inn {len(sh) / n:>5.1%}  "
            f"var<4 {sum((x - m) ** 2 for x in sh) / sum((x - m) ** 2 for x in o):>5.1%}  "
            f"bnd {sum(v for k, v in c.items() if k % 3 == 0) / n:>5.1%}")


def main():
    rows = []
    for gid in pbp.final_games():
        if not pbp.have(gid):
            continue
        try:
            rows.extend(boundary.decisions(gid))
        except Exception:
            continue
    mid = [r for r in rows if not r["ends_inning"]]
    fits = {c: fit_at(mid, c) for c in (3, 4, 5)}
    print("REFIT AT EACH CUTOFF")
    for c, f in fits.items():
        print(f"  cutoff {c}: n={f['n']:>6,}  base {f['base']:.3%}  "
              f"AUC {f['auc']:.4f}  offset {f['offset']:+.3f}  "
              f"per_pitch {f['per_pitch']:+.5f}  "
              f"per_br {f['per_inning_br']:+.4f}")

    lg = sim.league()
    pens = rate_src.bullpens(lg)
    by = {}
    for s, p, l in cal.build_cases():
        by.setdefault(s["game_id"], []).append((s, p, l))
    by = {g: v for g, v in by.items()
          if len(v) == 2 and sum(bool(x[0]["is_home"]) for x in v) == 1}
    act = [s["o"] for v in by.values() for s, _, _ in v]
    print(f"\n{len(by)} games")
    print(desc(act, "ACTUAL"))

    states = [("off", sim.Hook(early_innings=0))]
    for c, f in fits.items():
        states.append((f"cutoff {c}", sim.Hook(
            early_innings=c, early_offset=f["offset"],
            early_per_pitch=f["per_pitch"],
            early_per_run_offset=f["per_run_offset"],
            early_per_inning_br=f["per_inning_br"])))
    for lbl, hook in states:
        O = []
        for i, (gid, v) in enumerate(by.items()):
            home = next(x for x in v if x[0]["is_home"])
            away = next(x for x in v if not x[0]["is_home"])
            an = cal.adjust_lineup(away[2], False)
            hn = cal.adjust_lineup(home[2], True)
            for draw in range(6):
                rng = random.Random(7 + i * 100003 + draw)
                A = game.build_side(
                    away[1], pens.get((away[0]["team"] or "").upper(), []),
                    hn, hook, rng)
                H = game.build_side(
                    home[1], pens.get((home[0]["team"] or "").upper(), []),
                    an, hook, rng)
                r = game.simulate_game(A, H, lg, rng)
                O += [r.away_sp.outs, r.home_sp.outs]
        ls = cal.loss({"actual": [{"o": x} for x in act],
                       "sim": [type("R", (), {"outs": x})() for x in O]})
        print(desc(O, lbl) + f"  loss {ls:.5f}")


if __name__ == "__main__":
    main()
