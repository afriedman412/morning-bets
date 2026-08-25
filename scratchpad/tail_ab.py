"""Does the current-inning-runs term restore the disaster tail?

Paired, common random numbers, one pass. Everything the change was
predicted to move, and the things it was not.
"""
import random
import statistics as st
from collections import Counter

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src


def desc(o, lbl, act=None):
    n = len(o)
    m = st.mean(o)
    c = Counter(o)
    sh = [x for x in o if x < 12]
    print(f"  {lbl:<20}mean {m:>5.2f}  sd {st.pstdev(o):>4.2f}  "
          f"<2inn {sum(1 for x in o if x < 6) / n:>5.2%}  "
          f"<4inn {len(sh) / n:>5.1%}  "
          f"var<4inn {sum((x - m) ** 2 for x in sh) / sum((x - m) ** 2 for x in o):>5.1%}  "
          f"bnd {sum(v for k, v in c.items() if k % 3 == 0) / n:>5.1%}")


def main():
    lg = sim.league()
    pens = rate_src.bullpens(lg)
    by = {}
    for s, p, l in cal.build_cases():
        by.setdefault(s["game_id"], []).append((s, p, l))
    by = {g: v for g, v in by.items()
          if len(v) == 2 and sum(bool(x[0]["is_home"]) for x in v) == 1}
    act = [s["o"] for v in by.values() for s, _, _ in v]
    print(f"{len(by)} games\n")
    desc(act, "ACTUAL")

    out = {}
    for coef, lbl in ((0,"early off"),(3,"early on"),):
        O = []
        hook = sim.Hook(early_innings=coef)
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
        out[lbl] = O
        desc(O, lbl)

    print(f"\n  left tail, share of starts")
    print(f"  {'outs':>7}{'ACTUAL':>10}" + "".join(f"{k[:12]:>16}" for k in out))
    for lo, hi, lbl in ((0, 4, "0-3"), (4, 7, "4-6"), (7, 10, "7-9"),
                        (10, 12, "10-11"), (12, 15, "12-14")):
        row = [f"{sum(1 for x in v if lo <= x < hi) / len(v):>9.2%}"
               for v in (act,) + tuple(out.values())]
        print(f"  {lbl:>7}{row[0]:>10}" + "".join(f"{r:>16}" for r in row[1:]))

    # Paired CRPS on the outs distribution, per start.
    print()
    for lbl, O in out.items():
        c = cal.loss({"actual": [{"o": x} for x in act],
                      "sim": [type("R", (), {"outs": x})() for x in O]})
        print(f"  calibrate.loss  {lbl:<20}{c:.5f}")


if __name__ == "__main__":
    main()
