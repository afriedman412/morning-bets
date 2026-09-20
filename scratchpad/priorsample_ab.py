"""Does the COUNTED prior sample reach what settles?

    venv/bin/python -m scratchpad.priorsample_ab [n_sims] [salts]

Paired; only `rates.USE_MEASURED_PRIOR_PA` differs. The B arm replaces both
shrink stages with ONE pooled shrink at `PRIOR_EFFECTIVE_PA` — 250 batters
faced for `k_pct` and `bb_pct`, counted by `scratchpad/priorsample.py` on
out-of-sample prediction of the rest of a pitcher's own season. `hr_pct`
and `babip` are UNRESOLVED and keep the shipped construction, so this is a
two-channel change.

THIS IS NOT `rawprior_ab`. That arm removed the first shrink and left the
prior at its RAW sample, which OVER-weights it (403 against a counted 250)
and lost at z +2.6. This one sits between the two errors instead of
swapping one for the other.

THE BAR IS NEUTRAL, and the counted value is not on trial here. The
measurement is a fact about predicting rates and stands on its own; this
asks the separate question of whether it reaches F5. A clear LOSS would
matter — it would say the double shrink is absorbing something else — but a
flat result is the expected outcome for a change this size and is not a
refutation. See CLAUDE.md on what a flat CRPS can and cannot resolve.
"""
from __future__ import annotations

import statistics as st
import sys

from src.context import calibrate as cal
from src.context import fitf5, sim
from src.context.sources import rates as rate_src

CUT = "2026-07-01"
ARMS = ((False, "double-shrunk (shipped)"), (True, "pooled at the counted m"))


def arm(flag, n_sims, salt):
    rate_src.USE_MEASURED_PRIOR_PA = flag
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
    orig = rate_src.USE_MEASURED_PRIOR_PA
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
        rate_src.USE_MEASURED_PRIOR_PA = orig
        rate_src._PRIOR, rate_src._PRIOR_FOR = {}, None
    fitf5.report_actual(res)
    a, b = got[False], got[True]
    d = [y - x for x, y in zip(a, b)]
    m, se = fitf5._mean_se(d)
    print(f"\n  per salt, shipped:     " + " ".join(f"{x:.5f}" for x in a))
    print(f"  per salt, counted m:   " + " ".join(f"{x:.5f}" for x in b))
    print(f"\n  paired CRPS difference, NEGATIVE = the counted m wins")
    print(f"    {m:+.5f} +/- {se:.5f}   z {m / se if se else 0:+.1f}")
    print(f"    noise floor {st.pstdev(a):.5f}")


if __name__ == "__main__":
    main(sys.argv[1:])
