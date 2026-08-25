"""Does the boundary hook fix the STARTER'S OUTS DISTRIBUTION?

The prefix ladder measured this change at 0.5 sigma and that is the right
answer to the wrong question. The ladder scores TOTAL RUNS, and moving a
hook from mid-inning to an inning boundary swaps a starter for a reliever
who is his equal in aggregate (K-BB 0.1333 against 0.1358) — it changes who
throws, not how many score.

What the fix changes is the starter's own line, so that is what is scored
here: the share of starts ending on a completed inning, the discrete CRPS
of the simulated outs distribution against the real one, and calibration at
the outs lines books actually hang.

    venv/bin/python -m scratchpad.score_outs [n_sims]
"""
import random
import statistics as st
import sys
from collections import Counter

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src

MAX_OUTS = 28


def crps(dist: Counter, n: int, actual: int) -> float:
    """Discrete CRPS over the full support — no book's lines involved."""
    tot, c = 0.0, 0.0
    for v in range(MAX_OUTS + 1):
        c += dist.get(v, 0) / n
        tot += (c - (1.0 if v >= actual else 0.0)) ** 2
    return tot


def main():
    n_sims = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    lg = sim.league()
    pens = rate_src.bullpens(lg)
    by = {}
    for s, p, l in cal.build_cases():
        by.setdefault(s["game_id"], []).append((s, p, l))
    by = {g: v for g, v in by.items()
          if len(v) == 2 and sum(bool(x[0]["is_home"]) for x in v) == 1}
    print(f"{len(by)} games, {len(by) * 2} starts, {n_sims} draws each",
          flush=True)

    out = {}
    for flag in (False, True):
        game.USE_BOUNDARY_HOOK = flag
        print(f"  USE_BOUNDARY_HOOK={flag} ...", flush=True)
        rows = []
        for i, (gid, v) in enumerate(by.items()):
            home = next(x for x in v if x[0]["is_home"])
            away = next(x for x in v if not x[0]["is_home"])
            an = cal.adjust_lineup(away[2], False)
            hn = cal.adjust_lineup(home[2], True)
            da, dh = Counter(), Counter()
            for draw in range(n_sims):
                rng = random.Random(7 + i * 100003 + draw)
                A = game.build_side(away[1],
                                    pens.get((away[0]["team"] or "").upper(), []),
                                    hn, None, rng)
                H = game.build_side(home[1],
                                    pens.get((home[0]["team"] or "").upper(), []),
                                    an, None, rng)
                r = game.simulate_game(A, H, lg, rng)
                da[r.away_sp.outs] += 1
                dh[r.home_sp.outs] += 1
            for act, d in ((away[0], da), (home[0], dh)):
                if act.get("outs") is None:
                    continue
                rows.append({"actual": act["outs"], "dist": d})
        out[flag] = rows

    real = [r["actual"] for r in out[True]]
    print(f"\n  {len(real):,} starts scored")
    print(f"  {'':<10}{'mean outs':>11}{'whole-inn':>11}{'CRPS':>9}"
          f"{'d CRPS':>9}{'sigma':>8}")
    print(f"  {'ACTUAL':<10}{st.mean(real):>11.2f}"
          f"{sum(1 for v in real if v % 3 == 0) / len(real):>11.1%}")
    base = None
    for flag in (False, True):
        rows = out[flag]
        sm = st.mean(sum(k * n for k, n in r["dist"].items())
                     / sum(r["dist"].values()) for r in rows)
        wh = st.mean(sum(n for k, n in r["dist"].items() if k % 3 == 0)
                     / sum(r["dist"].values()) for r in rows)
        cs = [crps(r["dist"], sum(r["dist"].values()), r["actual"])
              for r in rows]
        lbl = "boundary" if flag else "shipped"
        if base is None:
            base = cs
            print(f"  {lbl:<10}{sm:>11.2f}{wh:>11.1%}{st.mean(cs):>9.4f}")
        else:
            d = [a - b for a, b in zip(base, cs)]
            m = st.mean(d)
            se = st.pstdev(d) / len(d) ** 0.5
            print(f"  {lbl:<10}{sm:>11.2f}{wh:>11.1%}{st.mean(cs):>9.4f}"
                  f"{m:>+9.4f}{m / se if se else 0:>+8.1f}")
    print("\n  d CRPS > 0 means the boundary hook IMPROVED the distribution.")
    game.USE_BOUNDARY_HOOK = True


if __name__ == "__main__":
    main()
