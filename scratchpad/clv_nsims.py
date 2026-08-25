"""Re-run the CLV tests at a higher n_sims, PAIRED on the same contracts.

Every recorded CLV number except F5 was taken at n_sims=250, which carries
~3.2 cents of Monte Carlo error against a ~3.7-cent median disagreement.
That ATTENUATES: noise in `ours` shrinks corr(ours-open, market-open) toward
zero and turns real opinions into fake five-cent disagreements. Re-running F5
at 1500 moved corr +0.456 -> +0.496 and 5c+ direction 56.3% -> 63.2%, and
dropped 145 of the 932 "disagreements" as simulation noise.

This does the same sweep for the markets that have NOT been corrected. The
only thing that moves between rows is n_sims — same dates, same seed, same
market filters — so the difference is attributable.

    venv/bin/python -m scratchpad.clv_nsims k       2026-06-01 2026-08-21
    venv/bin/python -m scratchpad.clv_nsims outs    2026-06-01 2026-08-21
    venv/bin/python -m scratchpad.clv_nsims total   2026-08-01 2026-08-21

The stat block is lifted from `f5_market.report` / `total_market.report`,
which carry identical CLV arithmetic, so the numbers stay comparable to what
is already recorded. Rows from all three collectors share the keys it needs
(`ours`, `market`, `open`, `won`).
"""
import datetime as dt
import random
import statistics as st
import sys


def _dates(start: str, end: str) -> list[str]:
    a = dt.date.fromisoformat(start)
    b = dt.date.fromisoformat(end)
    return [(a + dt.timedelta(days=i)).isoformat()
            for i in range((b - a).days + 1)]


def clv(rows: list[dict]) -> dict | None:
    """The CLV block from f5_market.report, as numbers rather than print."""
    rows = [r for r in rows if r.get("open") is not None]
    n = len(rows)
    if n < 30:
        return None

    def corr(xs, ys):
        mx, my = st.mean(xs), st.mean(ys)
        sx, sy = st.pstdev(xs), st.pstdev(ys)
        if sx == 0 or sy == 0:
            return 0.0
        return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n * sx * sy)

    ys = [r["market"] - r["open"] for r in rows]
    real = corr([r["ours"] - r["open"] for r in rows], ys)
    random.seed(0)
    cs = []
    for _ in range(200):
        sh = [r["ours"] for r in rows]
        random.shuffle(sh)
        cs.append(corr([s - r["open"] for s, r in zip(sh, rows)], ys))
    z = (real - st.mean(cs)) / max(st.pstdev(cs), 1e-9)

    def sq(pred):
        return sum((p - r["market"]) ** 2 for p, r in zip(pred, rows)) / n
    o = sq([r["open"] for r in rows])
    best = min((sq([r["open"] + lam * (r["ours"] - r["open"]) for r in rows]),
                lam) for lam in (0.1, 0.2, 0.25, 0.3, 0.4, 0.5))

    big = [r for r in rows if abs(r["ours"] - r["open"]) >= 0.05]
    direction = signed = None
    if big:
        direction = sum(1 for r in big
                        if (r["ours"] - r["open"])
                        * (r["market"] - r["open"]) > 0) / len(big)
        signed = st.mean([(1 if r["ours"] > r["open"] else -1)
                          * (r["market"] - r["open"]) for r in big]) * 100

    base = sum(1 for r in rows if r["won"]) / n
    bb = base * (1 - base)

    def brier(k):
        return sum((r[k] - (1 if r["won"] else 0)) ** 2 for r in rows) / n

    return {
        "n": n, "corr": real, "z": z,
        "blend": (o - best[0]) / o, "lam": best[1],
        "n_big": len(big), "direction": direction, "cents": signed,
        "brier_ours": brier("ours"), "brier_market": brier("market"),
        "skill_ours": (bb - brier("ours")) / bb,
        "skill_market": (bb - brier("market")) / bb,
    }


def sweep(which: str, dates: list[str], sims: list[int]) -> None:
    if which in ("k", "outs"):
        from src.context import versus_market as mod

        def collect(n):
            return mod.collect(dates, stat=which, n_sims=n, verbose=False)
    elif which == "total":
        from src.context import total_market as mod

        def collect(n):
            return mod.collect(dates, n_sims=n, verbose=False)
    elif which == "team":
        from src.context import team_market as mod

        def collect(n):
            return mod.collect(dates, n_sims=n, verbose=False)
    elif which == "f5":
        from src.context import f5_market as mod

        def collect(n):
            return mod.collect(dates, n_sims=n, verbose=False)
    else:
        raise SystemExit(f"unknown market {which!r}")

    print(f"{which} over {len(dates)} dates {dates[0]}..{dates[-1]}",
          flush=True)
    out = {}
    for n in sims:
        rows = collect(n)
        s = clv(rows)
        out[n] = s
        if s is None:
            print(f"  n_sims={n}: only {len(rows)} rows, not enough",
                  flush=True)
            continue
        d_txt = "--" if s["direction"] is None else f"{s['direction']:.1%}"
        c_txt = "--" if s["cents"] is None else f"{s['cents']:+.1f}c"
        print(f"  n_sims={n:<5} n={s['n']:<5} corr {s['corr']:+.3f}  "
              f"z {s['z']:+.1f}  blend {s['blend']:+.1%} (lam {s['lam']})  "
              f"5c+ n={s['n_big']} dir {d_txt}  {c_txt}", flush=True)

    good = {n: s for n, s in out.items() if s}
    if len(good) >= 2:
        lo, hi = min(good), max(good)
        a, b = good[lo], good[hi]
        print(f"\n  {lo} sims -> {hi} sims, paired on the same contracts:")
        print(f"    CLV corr      {a['corr']:+.3f} -> {b['corr']:+.3f}")
        print(f"    z             {a['z']:+.1f} -> {b['z']:+.1f}")
        print(f"    blend vs open {a['blend']:+.1%} -> {b['blend']:+.1%}")
        if a["direction"] and b["direction"]:
            print(f"    5c+ direction {a['direction']:.1%} -> "
                  f"{b['direction']:.1%}")
            print(f"    cents our way {a['cents']:+.1f}c -> "
                  f"{b['cents']:+.1f}c")
        print(f"    n disagreements {a['n_big']} -> {b['n_big']}")
        print(f"    Brier skill vs base: ours {a['skill_ours']:+.1%} -> "
              f"{b['skill_ours']:+.1%}   (market {b['skill_market']:+.1%})")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "k"
    start = sys.argv[2] if len(sys.argv) > 2 else "2026-06-01"
    end = sys.argv[3] if len(sys.argv) > 3 else "2026-08-21"
    sims = [int(x) for x in sys.argv[4].split(",")] if len(sys.argv) > 4 \
        else [250, 1500]
    sweep(which, _dates(start, end), sims)
