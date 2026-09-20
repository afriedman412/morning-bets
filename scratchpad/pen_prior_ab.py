"""Does the bullpen seeing the prior actually reach the runs?

    venv/bin/python -m scratchpad.pen_prior_ab [n_sims]

The rates MOVE — 401 of 435 relievers, Mason Miller 0.4091 -> 0.4418 — but
a rate moving is a plumbing result. This scores it.

The arms differ ONLY in whether `bullpens` consults the shared shrink
target. Starters see the prior in both, so what is isolated here is the
reliever half alone.
"""
from __future__ import annotations

import sys

from src.context import calibrate as cal
from src.context import fitf5, sim
from src.context.sources import rates as rate_src

CUT = "2026-07-01"
_REAL = rate_src.shrink_target


def _league_only(name, team, stat, lg, prior, dfn):
    return lg[stat]


def arm(pen_sees_prior, n_sims):
    rate_src.USE_PRIOR_SEASON = True
    rate_src._PRIOR, rate_src._PRIOR_FOR = {}, None
    # Both caches, or the second arm silently reuses the first one's rates.
    cal._CASES.clear()
    fitf5._SIDES.clear()
    sim._LEAGUE_CACHE.clear()
    lg = sim.league()
    cases = fitf5.side_cases(since=CUT, rates_before=CUT)
    # The starters are already built into `cases`; only the bullpen is drawn
    # at simulation time, so the switch goes here and affects relievers only.
    rate_src.shrink_target = _REAL if pen_sees_prior else _league_only
    try:
        return fitf5.evaluate(cases, None, n_sims=n_sims, lg=lg)
    finally:
        rate_src.shrink_target = _REAL


def main(argv):
    n = int(argv[0]) if argv else 25
    print(f"  {n} sims per side, cut {CUT}\n")
    print(fitf5.HEAD)
    res = None
    for flag, label in ((False, "pen: league only"), (True, "pen: prior")):
        res = arm(flag, n)
        fitf5.report(label, res)
    fitf5.report_actual(res)


if __name__ == "__main__":
    main(sys.argv[1:])
