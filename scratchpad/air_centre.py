"""Is `AIR_HR_PIT` centred on the population it actually fires in?

    venv/bin/python -m scratchpad.air_centre

THE FALSIFIER THAT FIRED. `sim.AIR_HR_PIT` was centred over the counting
sample's ball-in-play weights, where the five cells are equal fifths BY
CONSTRUCTION. The battery's own cell counts say the engine's population is
not that: fold 2023 put 4,023 starter balls in play in q1 against 7,796 in
q5. Fixed edges plus a differently-shaped population is a table whose
applied mean is not 1.0, and `hrshape.hr_per_club_game` rose by +0.014 to
+0.020 in ALL FOUR folds on the first battery run — a level move out of a
table that is only supposed to redistribute.

This measures the applied mean directly, weighted by batters faced, over
every arm each fold actually uses: the two starters of every paired game
and every arm in every bullpen. Rule 9's shape — fit a curve on the
population it fires in — applied to the centring rather than the slope.
"""
from __future__ import annotations

import sys
from collections import Counter

from src.context import calibrate as cal, sim
from src.context.sources import battedball, rates as rate_src

FOLDS = ((2023, "2023-07-01"), (2024, "2024-07-01"),
         (2025, "2025-07-01"), (2026, "2026-07-01"))


def _mult(v: float) -> float:
    return sim.AIR_HR_PIT[1][sum(v >= e for e in sim.AIR_HR_PIT[0])]


def main(argv):
    limit = int(argv[0]) if argv else None
    print(f"\n  applied mean of AIR_HR_PIT, weighted by batters faced\n")
    print(f"    {'fold':<6}{'starters':>12}{'pen arms':>12}"
          f"{'both':>10}{'q1..q5 share of bf':>34}")
    grand = [0.0, 0.0]
    for year, cut in FOLDS:
        pairs = cal.paired_cases(season=year, rates_before=cut, since=cut)
        gids = sorted(pairs)[:limit] if limit else sorted(pairs)
        air = battedball.air_pct_map("pit", year, cut)
        acc = {"sp": [0.0, 0.0], "pen": [0.0, 0.0]}
        cells: Counter = Counter()
        seen = set()
        for g in gids:
            for i in (0, 1):
                p = pairs[g][i][1]
                if p.air_pct is None:
                    continue
                m = _mult(p.air_pct)
                acc["sp"][0] += m * p.pa
                acc["sp"][1] += p.pa
                cells[sum(p.air_pct >= e for e in sim.AIR_HR_PIT[0])] += p.pa
        lg = sim.league(season=year, before=cut)
        pens = rate_src.bullpens(lg, season=year, before=cut)
        for team, arms in pens.items():
            for a in arms:
                v = a.get("air_pct")
                if v is None or (team, a["name"]) in seen:
                    continue
                seen.add((team, a["name"]))
                m = _mult(v)
                acc["pen"][0] += m * a["pa"]
                acc["pen"][1] += a["pa"]
                cells[sum(v >= e for e in sim.AIR_HR_PIT[0])] += a["pa"]
        sp = acc["sp"][0] / max(acc["sp"][1], 1)
        pn = acc["pen"][0] / max(acc["pen"][1], 1)
        both = ((acc["sp"][0] + acc["pen"][0])
                / max(acc["sp"][1] + acc["pen"][1], 1))
        grand[0] += acc["sp"][0] + acc["pen"][0]
        grand[1] += acc["sp"][1] + acc["pen"][1]
        tot = sum(cells.values())
        shares = "  ".join(f"{cells[q] / tot:.3f}" for q in range(5))
        print(f"    {year:<6}{sp:>12.4f}{pn:>12.4f}{both:>10.4f}"
              f"{shares:>34}")
    g = grand[0] / grand[1]
    print(f"\n    ALL FOLDS: {g:.4f}   "
          f"({'ADDS' if g > 1 else 'REMOVES'} {abs(g - 1):.2%} of the "
          "home run level)")
    print(f"    renormalised table: ("
          + ", ".join(f"{m / g:.4f}" for m in sim.AIR_HR_PIT[1]) + ")")


if __name__ == "__main__":
    main(sys.argv[1:])
