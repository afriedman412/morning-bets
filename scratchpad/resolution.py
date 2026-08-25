"""How much do our per-game PREDICTIONS actually differ from each other?

Calibration and resolution are different things and the PIT test only sees
the first. A model that hands every game the same distribution, centred in
the right place, produces perfectly uniform PITs and is useless for picking
between games.

Measured at F7 over 500 games: the simulator's per-game sd is 3.61 and the
sd of actual totals across games is 3.67, which leaves only
sqrt(3.67^2 - 3.61^2) = 0.66 runs of between-game variation. If the spread
of our own predicted means is smaller than that, we are under-resolving —
producing less game-to-game differentiation than really exists.

    venv/bin/python -m scratchpad.resolution [n_games]
"""
import random
import statistics as st
import sys

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import innings as inn_src
from src.context.sources import rates as rate_src


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    n_sims = 120
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
    print(f"{len(by)} games x {n_sims} draws", flush=True)

    pred = {n: [] for n in (3, 5, 7)}
    act = {n: [] for n in (3, 5, 7)}
    within = {n: [] for n in (3, 5, 7)}
    for i, (gid, v) in enumerate(by.items()):
        home = next(x for x in v if x[0]["is_home"])
        away = next(x for x in v if not x[0]["is_home"])
        an = cal.adjust_lineup(away[2], False)
        hn = cal.adjust_lineup(home[2], True)
        tot = {n: [] for n in (3, 5, 7)}
        for draw in range(n_sims):
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
            if len(tot[n]) < n_sims // 2:
                continue
            pred[n].append(st.mean(tot[n]))
            within[n].append(st.pstdev(tot[n]))
            act[n].append(actual[n][gid]["total"])
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}", flush=True)

    print(f"\n  {'':<6}{'our spread':>12}{'implied true':>14}{'share':>9}"
          f"{'corr w/ actual':>16}")
    for n in (3, 5, 7):
        p, a, w = pred[n], act[n], within[n]
        sp = st.pstdev(p)
        tot_v = st.pstdev(a) ** 2
        win_v = st.mean(x ** 2 for x in w)
        between = max(tot_v - win_v, 0) ** 0.5
        # correlation between our per-game prediction and the actual
        mp, ma = st.mean(p), st.mean(a)
        sa = st.pstdev(a)
        r = (sum((x - mp) * (y - ma) for x, y in zip(p, a))
             / (len(p) * sp * sa)) if sp and sa else 0.0
        print(f"  F{n:<5}{sp:>12.2f}{between:>14.2f}"
              f"{(sp / between if between else 0):>9.0%}{r:>16.3f}")
    print("\n  'our spread' is the sd of our per-game predicted means.")
    print("  'implied true' is sqrt(var(actual) - mean within-game var):")
    print("  how much game-to-game variation really exists.")
    print("  share < 100% means we under-differentiate games.")


if __name__ == "__main__":
    main()
