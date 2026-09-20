"""Does team defence in the BABIP shrink target reach the runs?

    venv/bin/python -m scratchpad.defence_ab [n_sims]

Paired: identical sides, identical seeds, only `rates.USE_TEAM_DEFENCE`
differs. Scored on F5 runs allowed by one side, which is what settles.
"""
from __future__ import annotations

import sys

from src.context import calibrate as cal
from src.context import fitf5, sim
from src.context.sources import rates as rate_src

CUT = "2026-07-01"


def arm(flag, n_sims):
    # CLEAR THE CASE CACHE OR THIS MEASURES NOTHING. `calibrate` memoises
    # built cases at module level, so the second arm reuses the first arm's
    # rates and the two columns come out identical to five decimals — which
    # is the recorded signature of plumbing, never a null. The first version
    # of this file cleared a `fitf5._CASES` that does not exist.
    rate_src.USE_TEAM_DEFENCE = flag
    rate_src._DEFENCE_CACHE.clear()
    sim._LEAGUE_CACHE.clear()
    cal._CASES.clear()
    # TWO caches, and clearing one is worse than clearing neither because
    # it looks like it worked. `fitf5` memoises its own side rows in
    # `_SIDES` on top of `calibrate._CASES`; with only the latter cleared
    # the arms STILL came out identical to five decimals.
    fitf5._SIDES.clear()
    lg = sim.league()
    cases = fitf5.side_cases(since=CUT, rates_before=CUT)
    res = fitf5.evaluate(cases, None, n_sims=n_sims, lg=lg)
    return cases, res


def main(argv):
    n = int(argv[0]) if argv else 25
    print(f"  {n} sims per side, cut {CUT}\n")
    print(fitf5.HEAD)
    for flag, label in ((False, "defence OFF"), (True, "defence ON")):
        cases, res = arm(flag, n)
        fitf5.report(label, res)
    fitf5.report_actual(res)


if __name__ == "__main__":
    main(sys.argv[1:])
