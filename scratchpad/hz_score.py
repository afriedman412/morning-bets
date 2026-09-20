"""Score the counted pitch hazard against the shipped parametric curve.

    venv/bin/python -m scratchpad.hz_score [n_sims]

Item 7 in `TODO.md`. PRE-REGISTERED: the 12.5-17.5 band improves, because
that is where the old curve is out by a factor of two (boundary 0.19 against
a real 0.10 at 70-78 pitches). FALSIFIER: it does not, which would mean the
boundary-share defect is not in the pitch term at all.

The flag is set in the PARENT before `shape` forks, which is why this is a
module and not a `-c`: a spawned child re-imports at default globals and the
flag reverts silently, which reads as "the mechanism does nothing".
"""
import sys

from src.context import sim

sim.USE_PITCH_HAZARD = True

from scratchpad import shape  # noqa: E402  (after the flag, deliberately)

if __name__ == "__main__":
    shape.main(sys.argv[1:])
