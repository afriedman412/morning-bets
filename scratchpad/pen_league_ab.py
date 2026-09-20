"""Does shrinking relievers toward the RELIEVER league reach the runs?

    venv/bin/python -m scratchpad.pen_league_ab [n_sims]

Paired, identical sides and seeds; only `rates.USE_RELIEVER_LEAGUE` differs.
"""
from __future__ import annotations

import sys

from src.context import calibrate as cal
from src.context import fitf5, sim
from src.context.sources import rates as rate_src

CUT = "2026-07-01"


def arm(flag, n_sims):
    rate_src.USE_RELIEVER_LEAGUE = flag
    rate_src._PEN_LG.clear()
    # BOTH case caches. Clearing one looks like it worked and is not.
    cal._CASES.clear()
    fitf5._SIDES.clear()
    sim._LEAGUE_CACHE.clear()
    lg = sim.league()
    cases = fitf5.side_cases(since=CUT, rates_before=CUT)
    return fitf5.evaluate(cases, None, n_sims=n_sims, lg=lg)


def main(argv):
    n = int(argv[0]) if argv else 25
    print(f"  {n} sims per side, cut {CUT}\n")
    print(fitf5.HEAD)
    res = None
    for flag, label in ((False, "starter league"), (True, "reliever league")):
        res = arm(flag, n)
        fitf5.report(label, res)
    fitf5.report_actual(res)


if __name__ == "__main__":
    main(sys.argv[1:])
