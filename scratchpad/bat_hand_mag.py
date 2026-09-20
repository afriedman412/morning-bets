"""How far does handedness ACTUALLY move a lineup? Magnitude before sign.

    venv/bin/python -m scratchpad.bat_hand_mag [workers]

`platoon_bat.py` reported the lineup-level adjustment at 0.64 K-points of
standard deviation, and the Toronto card against Noah Cameron was +3.00 —
nearly five deviations. One of the two is wrong and the correlation result
is worthless until it is known which.

THREE THINGS ARE SEPARATED HERE, because the Cameron figure compared
Savant's vs-LHP rate against the rate the MODEL feeds the simulator, and
that difference contains all three:

  hand      the batter's counted rate vs this hand, minus his counted
            overall rate. The real platoon effect, nothing else.
  shrink    what shrinking toward the league does to the level. A .300
            hitter with 90 plate appearances arrives at the simulator as
            something much closer to league average, and that gap is not
            handedness.
  who       WHICH nine. A card posted against a left-hander is not the
            club's average nine, and the projected lineup the model used
            may not be the card that was posted.

If the Cameron gap is mostly `shrink` or `who`, then handedness is not what
changed that game's prognosis and resurrecting it will not recover the edge.
"""
from __future__ import annotations

import json
import statistics as st
import sys

from src.context import sim
from src.context.sources import rates as rate_src
#: One loader, one cache. Keeping a second copy here is how the two scripts
#: would end up disagreeing about the shape of a counts cell.
from scratchpad.platoon_bat import load


def main(argv):
    by_year, starts = load(int(argv[0]) if argv else 8)
    cur = by_year.get(2026, {})
    lg = sim.league()
    kconst = rate_src.STABILISE_MEASURED["bat"]["k_pct"]

    # 1. The raw platoon effect, on EVERY batter the model would ever price,
    #    not only the 148 regulars with 120 plate appearances against each
    #    hand. Thresholding at 120 selects everyday players, who are exactly
    #    the hitters clubs do NOT platoon and whose splits are smallest.
    print(f"  {'min PA each hand':>18}{'n':>7}{'mean':>9}{'sd':>9}"
          f"{'|split|':>9}")
    for lo in (30, 60, 120, 200):
        d = []
        for (bid, h), c in cur.items():
            if h != "L":
                continue
            r = cur.get((bid, "R"))
            if not r or min(c[0], r[0]) < lo:
                continue
            d.append(c[1] / c[0] - r[1] / r[0])
        if d:
            print(f"  {lo:>18}{len(d):>7}{st.mean(d):>+9.4f}"
                  f"{st.pstdev(d):>9.4f}"
                  f"{st.mean(abs(x) for x in d):>9.4f}")

    # 2. Decompose one real start: the nine, their counted rates both ways,
    #    and what the model actually handed the simulator for each.
    br = rate_src.batter_rates(lg)
    by_id = {}
    for name, r in br.items():
        by_id.setdefault(name, r)

    print("\n  A LINEUP, decomposed. Pick the start with the largest"
          " handedness swing among scored starts:")
    rows = [r for r in json.load(open("scratchpad/ceiling_rows.json"))
            if not r.get("_team_row")]
    best, bx = None, 0.0
    for r in rows:
        s = starts.get((r["game_id"], r["player"]))
        if not s:
            continue
        hand, tot, n = s["hand"], 0.0, 0
        for bid, here in s["faced"].items():
            c = cur.get((str(bid), hand)) or cur.get((bid, hand))
            o = cur.get((str(bid), "L" if hand == "R" else "R")) \
                or cur.get((bid, "L" if hand == "R" else "R"))
            if not c or not o or c[0] < 40 or o[0] < 40:
                continue
            overall = (c[1] + o[1]) / (c[0] + o[0])
            tot += c[1] / c[0] - overall
            n += 1
        if n >= 7 and abs(tot / n) > abs(bx):
            best, bx = (r, s), tot / n
    if best:
        r, s = best
        print(f"    {r['player']} ({s['hand']}HP) vs {s['team']}"
              f" on {r['date']}: mean shift {bx:+.4f}")
        print(f"    {'batter':<8}{'vsHand':>9}{'overall':>9}{'hand dx':>9}"
              f"{'model':>9}{'shrink dx':>11}")
        for bid, here in sorted(s["faced"].items(),
                                key=lambda kv: -kv[1][0])[:9]:
            c = cur.get((str(bid), s["hand"])) or cur.get((bid, s["hand"]))
            o = cur.get((str(bid), "L" if s["hand"] == "R" else "R")) \
                or cur.get((bid, "L" if s["hand"] == "R" else "R"))
            if not c or not o or not c[0] or not (c[0] + o[0]):
                continue
            overall = (c[1] + o[1]) / (c[0] + o[0])
            vs = c[1] / c[0]
            w = c[0] / (c[0] + kconst)
            shr = w * vs + (1 - w) * overall
            print(f"    {str(bid):<8}{vs:>9.4f}{overall:>9.4f}"
                  f"{vs - overall:>+9.4f}{shr:>9.4f}{shr - vs:>+11.4f}")

    # 3. Shrinkage, sized against handedness on the same batters. If the
    #    model pulls a hitter further than his platoon split would move him,
    #    the split is not the biggest thing wrong with his rate.
    print("\n  SHRINK vs HAND, on the same hitters:")
    hs, ss = [], []
    for (bid, h), c in cur.items():
        if h != "L":
            continue
        r = cur.get((bid, "R"))
        if not r or min(c[0], r[0]) < 40:
            continue
        overall = (c[1] + r[1]) / (c[0] + r[0])
        for cell in (c, r):
            vs = cell[1] / cell[0]
            w = cell[0] / (cell[0] + kconst)
            hs.append(abs(vs - overall))
            ss.append(abs(w * vs + (1 - w) * overall
                          - rate_src._shrink(overall, lg["k_pct"],
                                             c[0] + r[0], "k_pct", "bat")))
    if hs:
        print(f"    mean |hand move|   {st.mean(hs):.4f}")
        print(f"    mean |league pull| {st.mean(ss):.4f}")


if __name__ == "__main__":
    main(sys.argv[1:])
