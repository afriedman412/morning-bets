"""Does un-double-shrinking the prior reach what settles?

    venv/bin/python -m scratchpad.rawprior_ab [n_sims] [salts]

Paired; only `rates.USE_RAW_PRIOR` differs. See its docstring for the defect
— prior seasons come back from `pitcher_rates` already shrunk and
`shrink_target` shrinks them again with the same constant.

THE BAR IS NEUTRAL. This is a correctness change worth about 0.044 runs,
under the 0.05 leverage floor, so it cannot be expected to score. A CLEAR
LOSS would still kill it: that would say the double shrink was absorbing a
real defect somewhere else, which is worth knowing before shipping.
"""
from __future__ import annotations

import statistics as st
import sys

from src.context import calibrate as cal
from src.context import fitf5, sim
from src.context.sources import rates as rate_src

CUT = "2026-07-01"
ARMS = ((False, "double-shrunk (shipped)"), (True, "shrunk once"))


def arm(flag, n_sims, salt):
    rate_src.USE_RAW_PRIOR = flag
    rate_src._PEN_LG.clear()
    rate_src._PRIOR, rate_src._PRIOR_FOR = {}, None
    cal._CASES.clear()
    fitf5._SIDES.clear()
    sim._LEAGUE_CACHE.clear()
    lg = sim.league()
    cases = fitf5.side_cases(since=CUT, rates_before=CUT)
    return fitf5.evaluate(cases, None, n_sims=n_sims, lg=lg, salt=salt)


def main(argv):
    n = int(argv[0]) if argv else 25
    salts = list(range(int(argv[1]) if len(argv) > 1 else 4))
    orig = rate_src.USE_RAW_PRIOR
    print(f"  {n} sims per side x {len(salts)} salts, cut {CUT}\n")
    print(fitf5.HEAD)
    got = {f: [] for f, _ in ARMS}
    res = None
    try:
        for salt in salts:
            for flag, label in ARMS:
                res = arm(flag, n, salt)
                got[flag].append(res["loss"])
                if salt == salts[0]:
                    fitf5.report(label, res)
    finally:
        rate_src.USE_RAW_PRIOR = orig
        rate_src._PRIOR, rate_src._PRIOR_FOR = {}, None
    fitf5.report_actual(res)
    a, b = got[False], got[True]
    d = [y - x for x, y in zip(a, b)]
    m, se = fitf5._mean_se(d)
    print(f"\n  per salt, shipped:     " + " ".join(f"{x:.5f}" for x in a))
    print(f"  per salt, shrunk once: " + " ".join(f"{x:.5f}" for x in b))
    print(f"\n  paired CRPS difference, NEGATIVE = the fix wins")
    print(f"    {m:+.5f} +/- {se:.5f}   z {m / se if se else 0:+.1f}")
    print(f"    noise floor {st.pstdev(a):.5f}")


if __name__ == "__main__":
    main(sys.argv[1:])
