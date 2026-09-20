"""BETTING-LAYER correction for the model's outs distribution.

    venv/bin/python -m scratchpad.outs_adjust [DATE] [n_sims]

WHAT THIS IS AND WHAT IT IS NOT. This corrects a MEASURED, SIGNED, STABLE
bias in the simulator's outs distribution so that outs props can be priced.
It is a BETTING-LAYER adjustment and must never travel back into the model:
nothing here may be used to judge whether a mechanism helped, and the
simulator's own numbers stay uncorrected. CLAUDE.md keeps the betting layer
and the modelling loop apart for exactly this reason — a correction fitted
to make prices look right would absorb the defect and hide it.

THE DEFECT IT CORRECTS, and it is one thing with one cause. The simulator
ends starts MID-INNING where reality ends them at inning boundaries:
boundary share 0.631 against a real 0.668. The LEVEL is right (15.68
against 15.75) — it is placement that is wrong.

THE SPREAD IS NO LONGER RIGHT and that sentence used to say it was: 4.39
against a real 4.06, +0.33 as of 2026-09-09. It went out with the counted
boundary backbone, which fattens both tails at once — more very short
starts, and more that run deep. Recorded here because a correction table
is the wrong instrument for it: this table adjusts P(over) line by line
and cannot narrow a distribution.

WHY A CORRECTION RATHER THAN A FIX. Three well-powered mechanisms failed to
move the boundary share on 2026-08-29 — margin, strikeout dominance and
bullpen availability — all of them SPREAD terms where the defect is a LEVEL.
And a directly-fitted removal model, which beats `sim.Hook` on decision AUC
0.912 to 0.876, produces a boundary share of 0.341: far worse. So the fix is
not close, and the bias is meanwhile stable enough to price against.

THE TABLE IS MEASURED, NOT TUNED. Holdout, 1,224 real starts, rates frozen
before 2026-07-01, model P(over) against the observed frequency
(`scratchpad/shape.py 40`, output kept at `scratchpad/shape_0904_layoff.out`).

    line     model   actual     gap      se
    o12.5    0.772    0.806   -0.033   0.011
    o14.5    0.685    0.731   -0.047   0.013
    o15.5    0.494    0.536   -0.042   0.014
    o16.5    0.452    0.478   -0.026   0.014
    o17.5    0.393    0.411   -0.018   0.014
    o18.5    0.188    0.171   +0.018   0.011
    o20.5    0.130    0.118   +0.013   0.009

RE-MEASURED 2026-09-04, the day the LAYOFF TERM shipped (`sim.USE_LAYOFF`),
because a hook change moves the very thing this corrects and that is exactly
how a previous table went stale. The layoff is a hook term on both curves,
so it moves placement directly.

WHAT THE LAYOFF DID TO THE TABLE: almost nothing, which is the honest
result. The 12.5-17.5 band moved -0.026/-0.046/-0.040/-0.026/-0.018 to
-0.033/-0.047/-0.042/-0.026/-0.018 — every row inside one standard error of
where it was. That is expected: the term fires on 12.8% of holdout starts,
so it cannot move a pooled correction much. It is re-measured because the
rule is to re-measure after a hook change, not because a shift was
predicted.

**THE HOOK TOOK OVER A THIRD OF THE CORRECTION'S JOB.** Every row in the
12.5-17.5 band shrank: -0.036 to -0.026, -0.067 to -0.046, -0.052 to -0.040,
-0.040 to -0.026, -0.032 to -0.018. Mean |correction| across the band went
0.045 to 0.031. The simulator is doing work the table used to do, which is
the direction this project wants — the correction should be shrinking toward
nothing, not being tuned to keep prices right.

THE LONG LINES DRIFTED BACK OUT slightly, +0.011 -> +0.018 and +0.008 ->
+0.011, which is the counted table's known top-end permissiveness: it
under-pulls at 90+ pitches (-0.051 at the 90 bucket, measured against real
holdout rates) so a few too many starters go deep. Both are still inside
two standard errors and are not a signal in either direction.

READ THE SIGN BEFORE USING IT — SUPERSEDED 2026-09-09, see the bottom of
this docstring for the shipped numbers; kept because the shape of the
argument is still how to read the table. As of 2026-09-05 we UNDERSTATED
the over from 12.5 to 17.5 and very slightly OVERSTATED it at 18.5+, with
the crossover at 18 outs — exactly the mass the boundary defect misplaces
— so an outs UNDER in the band was flattered by 3-7 points and that is
where every large edge on a live board was showing up. The two long rows
were noise at that measurement (1.6 and 1.1 sigma) and were kept at their
measured values because this table COUNTS rather than models, and rounding
a measured 0.008 to zero would be a decision. **THEY ARE NO LONGER NOISE**
— they are 3.4 and 3.0 sigma now and the band has nearly closed, which
inverts the practical reading: the flattered side is now the long OVER,
not the band UNDER.

RE-MEASURED 2026-09-05, the day PARK shipped (`calibrate.USE_PARK` +
`NEUTRALISE_PARK`), because park moves traffic and traffic reaches the
hook. Every row moved by at most 0.004 — inside one standard error, the
expected result for a per-venue redistribution whose pooled effect nets
out — and the table now carries the values measured on the shipped
engine (`scratchpad/shape_0905_park.out`).

RE-MEASURED 2026-09-09, the day the counted BOUNDARY backbone shipped
(`sim.USE_PITCH_HAZARD_BND`, TODO 7a) — which the previous paragraph
predicted would move these rows, and it did, in both directions:

    line     model   actual     gap      was      se
    o12.5    0.789    0.805   -0.015   -0.033   0.011
    o14.5    0.696    0.728   -0.033   -0.047   0.012
    o15.5    0.532    0.533   -0.001   -0.042   0.014
    o16.5    0.485    0.477   +0.007   -0.026   0.014
    o17.5    0.420    0.411   +0.010   -0.018   0.014
    o18.5    0.206    0.172   +0.034   +0.018   0.010
    o20.5    0.147    0.120   +0.027   +0.010   0.009

**THE HOOK TOOK OVER MOST OF WHAT WAS LEFT IN THE BAND.** Mean
|correction| across 12.5-17.5 went 0.033 to 0.013, and o15.5 is now exact
to a thousandth. Together with the mid backbone's earlier third, the
band correction has gone 0.045 -> 0.031 -> 0.013 across three hook
changes. That is the direction this project wants: the correction should
be shrinking toward nothing rather than being kept alive to make prices
look right.

**AND THE TWO LONG LINES ARE NOW A SIGNAL, WHICH THEY WERE NOT BEFORE.**
+0.034 and +0.027 at se 0.010 and 0.009 is 3.4 and 3.0 sigma, where the
same rows were 1.6 and 1.1 sigma on 2026-09-05 and were explicitly
recorded as noise. The model now produces too MANY long starts. The cause
is measured and is not a mystery: the boundary table is fitted on a
May-September population that pulls at 0.0775 in the 50-78 buckets while
the July-onward scoring window pulls at 0.0853, so the hook is ~9% too
permissive exactly where the holdout lives. See `sim.PITCH_HAZARD_BND`.
Closing it needs a calendar term in the hook, not a bigger correction.

THE ACTUALS MOVED TOO, and it is the sample rather than baseball: the
holdout is 1,322 real starts here against 1,224 when this table was first
built, so the observed frequencies shift in the third decimal. Read the
`was` column as indicative, not as a paired difference.

IT WILL NEED MEASURING AGAIN on the next hook change. It costs 12 seconds
— `venv/bin/python -m scratchpad.shape 40` over 7 workers — so there is no
excuse for it going stale.

WHAT IT CANNOT DO. This is a POOLED correction across starts of every
projected length. It is right on average and is NOT conditioned on the
pitcher, so applying it to an arm whose projection sits far from the
holdout mean (15.68 outs) is an extrapolation. Flagged per row.
"""
from __future__ import annotations

import datetime
import statistics as st
import sys

from src.context import sim, slate as slate_src
from src.context.sources import rates as rate_src

#: line -> (model P(over), actual frequency) on the holdout. The correction
#: is actual - model, applied to P(over).
MEASURED = {
    12.5: (0.789, 0.805),
    14.5: (0.696, 0.728),
    15.5: (0.532, 0.533),
    16.5: (0.485, 0.477),
    17.5: (0.420, 0.411),
    18.5: (0.206, 0.172),
    20.5: (0.147, 0.120),
}
#: Nominal; the per-row figures run 0.010 to 0.015 and are in the docstring.
SE = 0.013

#: The date the table above was measured, and the engine it was measured on.
#: Both views print it, because a correction is only as current as the hook
#: underneath it and the last one went stale silently.
MEASURED_ON = "2026-09-09"

#: The holdout mean the correction was measured around. A projection far
#: from this is being extrapolated to, not interpolated.
#:
#: It is the MODEL's mean, not reality's 15.81, because what gets compared
#: against it is a model projection.
HOLDOUT_MEAN_OUTS = 15.68


def correction(line: float) -> float:
    """Additive adjustment to P(over `line`), linearly interpolated.

    Interpolated rather than fitted: a curve through seven measured points
    is a model of the bias, and the bias is not the sort of thing this
    project has earned the right to model. Outside the measured range the
    correction is held FLAT at the nearest endpoint rather than
    extrapolated, because the sign is not known to continue.
    """
    ks = sorted(MEASURED)
    if line <= ks[0]:
        m, a = MEASURED[ks[0]]
        return a - m
    if line >= ks[-1]:
        m, a = MEASURED[ks[-1]]
        return a - m
    for lo, hi in zip(ks, ks[1:]):
        if lo <= line <= hi:
            gl = MEASURED[lo][1] - MEASURED[lo][0]
            gh = MEASURED[hi][1] - MEASURED[hi][0]
            t = (line - lo) / (hi - lo)
            return gl + t * (gh - gl)
    return 0.0


def american(p: float) -> str:
    if p <= 0 or p >= 1:
        return "-"
    return f"{-100 * p / (1 - p):+.0f}" if p > 0.5 else f"{100 * (1 - p) / p:+.0f}"


def main(argv):
    d = argv[0] if argv else datetime.date.today().isoformat()
    n = int(argv[1]) if len(argv) > 1 else 20000
    lg = sim.league()
    pr, br = rate_src.pitcher_rates(lg), rate_src.batter_rates(lg)
    pens = rate_src.bullpens(lg)
    lb = sim.BatterRates(name="league", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
                         hr_pct=lg["hr_pct"], babip=lg["babip"])
    print(f"OUTS PROPS, BIAS-CORRECTED — {d}, {n:,} sims")
    print("  raw = the simulator. adj = after the measured boundary-share "
          "bias.")
    print("  the correction is POOLED; `far` flags a projection more than "
          "2 outs\n  from the 15.68 holdout mean, where it is an "
          "extrapolation.\n")
    print(f"  {'pitcher':<20}{'proj':>6}{'line':>7}{'raw ov':>8}{'adj ov':>8}"
          f"{'adj UN':>8}{'fair UN':>9}  note")
    for g in slate_src.slate(d):
        a, h = g.get("away") or {}, g.get("home") or {}
        if not (a.get("starter") and h.get("starter")):
            continue
        res, why = slate_src.simulate_slate_game(g, d, lg, pr, br, lb, pens,
                                             n_sims=n)
        if not res:
            continue
        for who, sp in (("away", "away_sp"), ("home", "home_sp")):
            side = a if who == "away" else h
            lines = [getattr(r, sp).outs for r in res]
            proj = st.mean(lines)
            for line in (12.5, 14.5, 15.5, 16.5, 17.5, 18.5, 20.5):
                raw = sum(1 for v in lines if v > line) / len(lines)
                if raw < 0.15 or raw > 0.85:
                    continue
                adj = min(max(raw + correction(line), 0.001), 0.999)
                far = "far" if abs(proj - HOLDOUT_MEAN_OUTS) > 2 else ""
                print(f"  {str(side.get('starter'))[:18]:<20}{proj:>6.1f}"
                      f"{line:>7.1f}{raw:>8.3f}{adj:>8.3f}{1 - adj:>8.3f}"
                      f"{american(1 - adj):>9}  {far}")


if __name__ == "__main__":
    main(sys.argv[1:])
