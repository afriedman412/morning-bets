"""Persist the holdout WITH the counted pitch hazard on, for querying.

    venv/bin/python -m scratchpad.starts_dump_hz [n_sims] [OUT.json]

The parametric backbone pulls twice too many men between 60 and 85 pitches;
our fourth-inning over-pull sits at 45-75. Overlapping ranges, so they may
be one defect. If they are, the counted table should close the fourth
inning — and that comparison was never run.

Flag set in the PARENT before `starts_dump` forks.
"""
import sys

from src.context import sim

sim.USE_PITCH_HAZARD = True

from scratchpad import starts_dump  # noqa: E402

if __name__ == "__main__":
    argv = sys.argv[1:] or ["40", "scratchpad/starts_holdout_hz.json"]
    if len(argv) == 1:
        argv.append("scratchpad/starts_holdout_hz.json")
    starts_dump.main(argv)
