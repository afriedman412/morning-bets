"""Are the simulated run distributions too WIDE or too NARROW?

The eye-test on six games says too wide — no resolution around the likely
numbers. The notes say the opposite, that the run distribution is COMPRESSED
(too many shutouts and too few crooked numbers at once). One of them is
wrong and six games cannot settle it.

THE TEST. For each real game, simulate it and ask where the actual total
lands inside the predicted distribution — the probability integral
transform. Across many games those should be UNIFORM if the widths are
right. Too wide and they pile up in the MIDDLE, because a distribution
hedging over everything makes the real answer look unremarkable. Too narrow
and they pile up at the ENDS.

Reported alongside: the sim's own average per-game standard deviation
against the standard deviation of the actual totals. The second contains
game-to-game differences in the true mean and so must be the LARGER of the
two; if the sim's per-game sd approaches or exceeds it, the sim is spending
spread on within-game noise that reality spends on matchups.

    venv/bin/python -m scratchpad.dispersion [n_games]
"""
import random
import statistics as st
import sys

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import innings as inn_src
from src.context.sources import rates as rate_src

N_SIMS = 300


def pit(vals, x):
    n = len(vals)
    below = sum(1 for v in vals if v < x)
    at = sum(1 for v in vals if v == x)
    return (below + at / 2) / n


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    lg = sim.league()
    pens = rate_src.bullpens(lg)
    by = {}
    for s, p, l in cal.build_cases():
        by.setdefault(s["game_id"], []).append((s, p, l))
    by = {g: v for g, v in by.items()
          if len(v) == 2 and sum(bool(x[0]["is_home"]) for x in v) == 1}
    actual = {n: inn_src.prefix_totals(n) for n in (3, 5, 7)}
    ok = [g for g in by if all(g in actual[n] for n in (3, 5, 7))]
    by = {g: by[g] for g in ok[:limit]}
    print(f"{len(by)} games x {N_SIMS} draws", flush=True)

    rows = {n: [] for n in (3, 5, 7)}
    sd_sim = {n: [] for n in (3, 5, 7)}
    act = {n: [] for n in (3, 5, 7)}
    for i, (gid, v) in enumerate(by.items()):
        home = next(x for x in v if x[0]["is_home"])
        away = next(x for x in v if not x[0]["is_home"])
        an = cal.adjust_lineup(away[2], False)
        hn = cal.adjust_lineup(home[2], True)
        tot = {n: [] for n in (3, 5, 7)}
        for draw in range(N_SIMS):
            rng = random.Random(11 + i * 100003 + draw)
            A = game.build_side(
                away[1], pens.get((away[0]["team"] or "").upper(), []),
                hn, None, rng)
            H = game.build_side(
                home[1], pens.get((home[0]["team"] or "").upper(), []),
                an, None, rng)
            r = game.simulate_game(A, H, lg, rng, track=(3, 5, 7))
            for n in (3, 5, 7):
                if n in r.prefix:
                    tot[n].append(r.prefix[n])
        for n in (3, 5, 7):
            if len(tot[n]) < N_SIMS // 2:
                continue
            a = actual[n][gid]["total"]
            rows[n].append(pit(tot[n], a))
            sd_sim[n].append(st.pstdev(tot[n]))
            act[n].append(a)
        if (i + 1) % 100 == 0:
            print(f"  {i + 1} games", flush=True)

    for n in (3, 5, 7):
        p = rows[n]
        if not p:
            continue
        print(f"\n  F{n} TOTAL RUNS — {len(p)} games")
        print(f"    where the actual landed in the predicted distribution")
        exp = len(p) / 10
        for lo in range(10):
            c = sum(1 for x in p if lo / 10 <= x < (lo + 1) / 10)
            bar = "#" * round(c / max(exp, 1) * 14)
            print(f"      {lo / 10:.1f}-{(lo + 1) / 10:.1f}{c:>6}"
                  f"{c / len(p):>8.1%}  {bar}")
        mid = sum(1 for x in p if 0.25 <= x < 0.75) / len(p)
        ends = sum(1 for x in p if x < 0.1 or x >= 0.9) / len(p)
        print(f"    middle half 0.25-0.75: {mid:.1%}   (uniform = 50.0%)")
        print(f"    outer tenths:          {ends:.1%}   (uniform = 20.0%)")
        v = "TOO WIDE" if mid > 0.56 else ("TOO NARROW" if mid < 0.44
                                           else "about right")
        print(f"    -> {v}")
        print(f"    sim per-game sd {st.mean(sd_sim[n]):.2f}   "
              f"actual across games sd {st.pstdev(act[n]):.2f}"
              f"   (the second MUST be larger)")


if __name__ == "__main__":
    main()
