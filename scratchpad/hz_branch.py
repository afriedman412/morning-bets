"""Counted hazard WITH the high-pitch branch laid on top. Test, not a ship.

    venv/bin/python -m scratchpad.hz_branch [n_sims]

`sim.py` warns these must never both apply, because the branch is a
correction TO the parametric curve the table replaces. That warning is about
DOUBLE-COUNTING and it assumes the error runs the other way. It does not:
with the table alone the model exits at 100+ pitches on 18.2% of starts
against a real 13.4%, and under-pulls at 78-95 (`scratchpad/hz_states.py`).
The branch pulls MORE at 90+, which is the direction the miss points in.

So this is a directional probe of one question: is the counted table's high
end simply too permissive? If adding a measured +0.8550 at 90+ lands the
long lines, the table's top buckets are the problem. If it overshoots, they
are not and the miss is in the CONDITIONING instead.
"""
import sys

from src.context import sim

sim.USE_PITCH_HAZARD = True

#: The branch, re-expressed as an offset to the counted buckets it overlaps.
_BND_ADD, _MID_ADD, _AT = 0.8550, 0.2893, 90
sim.PITCH_HAZARD_BND = tuple(
    (p, v + (_BND_ADD if p >= _AT else 0.0)) for p, v in sim.PITCH_HAZARD_BND)
sim.PITCH_HAZARD_MID = tuple(
    (p, v + (_MID_ADD if p >= _AT else 0.0)) for p, v in sim.PITCH_HAZARD_MID)

from scratchpad import shape  # noqa: E402

if __name__ == "__main__":
    shape.main(sys.argv[1:])
