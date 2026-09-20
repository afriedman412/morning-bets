"""Run ladder with the counted MID hazard on. The runs gate before shipping.

    venv/bin/python -m scratchpad.ladder_hz [--off] [--sims=N]

The mid-inning counted table is the ship candidate: the middle outs band
improves in all four folds by a consistent -0.016 to -0.018, the long lines
are untouched, and the mean outs error halves instead of flipping. It has
never been scored on RUNS, and it changes when the bullpen enters, so it can
move F5 and F7.

THE BAR, stated by the operator before running: ship unless the run ladder
moves a LOT. Outs is the metric that governs this defect and runs is the
lagging one — but "we never looked" is not the same as "it is fine".

HOLDOUT. Rates frozen before 2026-07-01, scored on starts from it, the same
window every other scoring run today used.

Flags set in the PARENT before anything forks.
"""
import sys

from src.context import sim

if "--off" not in sys.argv:
    sim.USE_PITCH_HAZARD = True
    sim.USE_PITCH_HAZARD_BND = False

from src.context import ladder  # noqa: E402

HOLDOUT = "2026-07-01"

if __name__ == "__main__":
    n = 40
    for a in sys.argv:
        if a.startswith("--sims="):
            n = int(a.split("=")[1])
    print(f"  MID HAZARD {'OFF (shipped)' if '--off' in sys.argv else 'ON'}"
          f"   holdout {HOLDOUT}+, {n} sims\n")
    # `before` and `since` together select starts both before and after
    # the cut, which is empty. Pass only `since`: `report` then sets
    # `rates_before = before or since`, so rates are frozen at the same
    # date and the starts scored are the unseen ones.
    ladder.report(since=HOLDOUT, n_sims=n)
