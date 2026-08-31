"""Four-fold outs-ladder CV with the counted table on the MID curve ONLY.

    venv/bin/python -m scratchpad.hz_cv_mid [n_sims]

QUESTION    The mid table hits its buckets (cell error 0.0203 -> 0.0144);
            the boundary table misses them (0.0265 -> 0.0314) and is what
            makes starters run long. Does taking the mid win alone beat
            taking both?

HYPOTHESIS  If the two curves were independent, mid-only keeps the
            middle-band gain and drops the overshoot. They are NOT
            independent — fixing the mid hook changes which starts survive
            to a boundary decision, and the parametric boundary curve is
            itself what over-pulls in the fourth. So this could get both
            wins or neither.

TEST        Same four folds and the same pre-registered bar as `hz_cv.py`:
            the middle band improves in all four. Reported against BOTH the
            shipped baseline and the both-curves version.
"""
import sys

from src.context import sim

sim.USE_PITCH_HAZARD_BND = False   # parametric boundary, counted mid

from scratchpad import hz_cv  # noqa: E402

if __name__ == "__main__":
    hz_cv.main(sys.argv[1:])
