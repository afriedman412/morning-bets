"""THE holdout cutoff. One literal for the whole project, imported
everywhere a fit filters its rows.

Why this file exists: `HOLDOUT` was a string literal assigned in ~47
scratchpads under three different names (`HOLDOUT`, `HOLDOUT_CUT`,
`CUT`), and four of them carried a DIFFERENT date — "2026-05-15", an
older cut that never got updated. Two cutoffs is how one of them
drifts; rule 6 is mechanical precisely so it cannot be forgotten, and a
mechanical rule needs exactly one source of truth.

The historical scratchpads keep their local literals — they are
measurement RECORDS, and rewriting them would falsify what was run.
The live fitters import from here, and
`check_the_holdout_has_one_source_of_truth` keeps it that way: no
`train_only` may be defined anywhere else, and no holdout assignment
may appear under `src/`.

`shape.py`, `fitf5` and `calibrate.paired_cases(rates_before=...,
since=...)` already use this same date; the battery's per-fold cuts
(July of each season) are a different, deliberate thing and stay where
they are.
"""
from __future__ import annotations

HOLDOUT = "2026-07-01"


def train_only(rows):
    """Rows strictly before the holdout. Call it before ANY fit."""
    return [r for r in rows if r.get("date", "") < HOLDOUT]
