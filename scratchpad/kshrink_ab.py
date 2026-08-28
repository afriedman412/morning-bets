"""Does the corrected pitcher strikeout constant reach what SETTLES?

    venv/bin/python -m scratchpad.kshrink_ab [n_sims]

The constant moved on two measurements and a discrimination sweep — the
split-half (132), method of moments (98) and the holdout peak (131). None of
those is a quantity anybody bets. `calibrate.loss` targeting the outs
distribution is the standing example of what goes wrong when the upstream
proxy is the thing improved.

So this scores F5 runs allowed by one side across the full support of the run
distribution, which is the discrete CRPS, on starts AFTER the cutoff with
rates trained only before it. Paired: only `STABILISE_MEASURED["pit"]
["k_pct"]` differs between the two arms.

WHAT WOULD COUNT. The change is a MEASURED value replacing a stale one, so
the bar is NEUTRAL, not significant — CLAUDE.md's rule that a measurement
replacing a guess does not have to prove itself on the score, because a flat
result means the test could not resolve ~0.02 runs. A CLEAR LOSS would still
kill it: that would say the stale value was absorbing a real defect
somewhere else, which is worth knowing before shipping.
"""
from __future__ import annotations

import sys

from src.context import calibrate as cal
from src.context import fitf5, sim
from src.context.sources import rates as rate_src

CUT = "2026-07-01"
ARMS = ((57, "k_pct 57  (stale)"), (132, "k_pct 132 (measured)"))
#: `--bat` swaps the whole BATTER row instead. Same shape of claim: the
#: shipped values were measured on less data and `stabilise` reads higher
#: today, and higher means MORE shrinkage — which is the direction an
#: over-differentiated lineup asks for (`scratchpad/offense.py`).
BAT_ARMS = (({"k_pct": 32, "bb_pct": 80, "hr_pct": 160, "babip": 184},
             "bat shipped"),
            ({"k_pct": 51, "bb_pct": 122, "hr_pct": 193, "babip": 250},
             "bat measured"))
WHO = "pit"


def arm(k, n_sims, salt=0):
    if WHO == "bat":
        rate_src.STABILISE_MEASURED["bat"] = dict(k)
    else:
        rate_src.STABILISE_MEASURED["pit"]["k_pct"] = k
    # Every cache downstream of a rate has to go, or the second arm scores
    # the first arm's numbers. `_PRIOR` especially: it is built by
    # `pitcher_rates`, so it carries the shrinkage constant inside it.
    rate_src._PEN_LG.clear()
    rate_src._PRIOR, rate_src._PRIOR_FOR = {}, None
    cal._CASES.clear()
    fitf5._SIDES.clear()
    sim._LEAGUE_CACHE.clear()
    lg = sim.league()
    cases = fitf5.side_cases(since=CUT, rates_before=CUT)
    return fitf5.evaluate(cases, None, n_sims=n_sims, lg=lg, salt=salt)


def main(argv):
    global WHO, ARMS
    if "--bat" in argv:
        argv = [a for a in argv if a != "--bat"]
        WHO, ARMS = "bat", BAT_ARMS
    n = int(argv[0]) if argv else 25
    salts = list(range(int(argv[1]) if len(argv) > 1 else 4))
    orig = (dict(rate_src.STABILISE_MEASURED["bat"]) if WHO == "bat"
            else rate_src.STABILISE_MEASURED["pit"]["k_pct"])
    print(f"  {n} sims per side x {len(salts)} salts, cut {CUT},"
          f" shipped value {orig}\n")
    print(fitf5.HEAD)
    # ONE SALT CANNOT DECIDE THIS. `evaluate`'s own docstring says the
    # spread across salts IS the smallest difference this objective can
    # honestly resolve, and the first pass here read -0.0079 off a single
    # salt — a number with no error bar attached to it.
    got = {(k if WHO != "bat" else id(k)): [] for k, _ in ARMS}
    res = None
    try:
        for salt in salts:
            for k, label in ARMS:
                res = arm(k, n, salt)
                got[k if WHO != "bat" else id(k)].append(res["loss"])
                if salt == salts[0]:
                    fitf5.report(label, res)
    finally:
        if WHO == "bat":
            rate_src.STABILISE_MEASURED["bat"] = orig
        else:
            rate_src.STABILISE_MEASURED["pit"]["k_pct"] = orig
    fitf5.report_actual(res)
    a, b = [got[k if WHO != "bat" else id(k)] for k, _ in ARMS]
    d = [y - x for x, y in zip(a, b)]
    m, se = fitf5._mean_se(d)
    import statistics as st
    la, lb = ARMS[0][1], ARMS[1][1]
    print(f"\n  per salt, {la:<14}" + " ".join(f"{x:.5f}" for x in a))
    print(f"  per salt, {lb:<14}" + " ".join(f"{x:.5f}" for x in b))
    print(f"\n  paired CRPS difference ({lb} - {la}),"
          f" NEGATIVE = the second arm wins")
    print(f"    {m:+.5f} +/- {se:.5f}   z {m / se if se else 0:+.1f}")
    print(f"    noise floor (sd of a single arm across salts)"
          f" {st.pstdev(a):.5f}")


if __name__ == "__main__":
    main(sys.argv[1:])
