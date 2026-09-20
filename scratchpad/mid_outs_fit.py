"""SOLVE the mid-inning out-count offsets, conditional on everything else.

    venv/bin/python -m scratchpad.mid_outs_fit

`scratchpad/mid_outs.py` counted the raw hazard by outs already recorded in
the half-inning: 1.63% / 2.25% / 5.96%, +29.6 sigma, surviving inside every
pitch and damage band. This turns that into the three numbers the hook can
carry.

THE DOUBLE-COUNTING TRAP, same one `pitch_hazard.py` documents. The raw rate
at two outs already contains the damage and traffic that come with a two-out
rally, and the hook reads those separately through `late_mid_per_inning_br`,
`late_mid_per_onbase` and `mid_per_inning_run`. Substituting the raw
log-odds would count them twice. So each cell is SOLVED: the offset that
makes the mean predicted probability match the observed rate given every
other shipped term, by bisection on a monotone function.

CENTRED, and this is the part that decides whether the change is a
mechanism or a level shift. The shipped mid curve is already calibrated on
the pooled population, so three uncentred offsets would move the overall
pull rate as well as its distribution across out counts. The offsets are
therefore re-centred on the row-weighted mean, which leaves the aggregate
level untouched and ships ONLY the shape. Anything else and this becomes a
second, undeclared way to tune how deep starters go.

TRAIN ROWS ONLY. `HOLDOUT_CUT` = 2026-07-01.
"""
from __future__ import annotations

import json
import math

import numpy as np

from src.context import sim
from scratchpad.pitch_hazard import HOLDOUT_CUT, ROWS, other_terms, train_only


def solve_cell(rows) -> tuple:
    """Offset making mean predicted p match the observed rate in this cell.

    The shipped mid intercept and pitch term are INCLUDED in `base`, unlike
    `pitch_hazard.solve` which replaces them — this is an offset ON TOP of a
    curve that stays, not a backbone that goes.
    """
    h = sim.Hook()
    base = np.array([
        h.mid_intercept + h.late_mid_offset
        + h.late_mid_per_pitch * r["pitches"]
        + (h.high_pitch_mid if r["pitches"] >= h.high_pitch_threshold else 0.0)
        + other_terms(r, boundary=False)
        for r in rows])
    y = np.array([1.0 if r["removed"] else 0.0 for r in rows])
    target = y.mean()
    lo, hi = -8.0, 8.0
    for _ in range(160):
        m = (lo + hi) / 2
        if (1 / (1 + np.exp(-np.clip(base + m, -30, 30)))).mean() < target:
            lo = m
        else:
            hi = m
    d = (lo + hi) / 2
    se_p = math.sqrt(max(target * (1 - target), 1e-12) / len(rows))
    return d, se_p / max(target * (1 - target), 1e-9), target, len(rows)


def main():
    rows = train_only(json.load(open(ROWS)))
    mid = [r for r in rows if not r.get("ends_inning")
           and r.get("outs_before") in (0, 1, 2)]
    print(f"  {len(mid):,} TRAINING mid-inning decisions "
          f"(before {HOLDOUT_CUT})\n")
    cells = {o: [r for r in mid if r["outs_before"] == o] for o in (0, 1, 2)}
    got = {o: solve_cell(v) for o, v in cells.items()}

    print(f"  {'outs':<6}{'n':>10}{'observed':>11}{'raw logodds':>13}"
          f"{'SOLVED':>10}{'se':>8}")
    for o in (0, 1, 2):
        d, se, tgt, n = got[o]
        raw = math.log(tgt / (1 - tgt))
        print(f"  {o:<6}{n:>10,}{tgt:>11.4f}{raw:>13.3f}{d:>10.4f}{se:>8.4f}")

    tot = sum(got[o][3] for o in (0, 1, 2))
    mean = sum(got[o][0] * got[o][3] for o in (0, 1, 2)) / tot
    centred = tuple(round(got[o][0] - mean, 4) for o in (0, 1, 2))
    print(f"\n  row-weighted mean offset {mean:+.4f}  (removed, so the "
          f"aggregate level is unchanged)")
    print(f"  CENTRED, ready to ship:  late_mid_inning_outs = {centred}")
    spread = centred[2] - centred[0]
    se2 = (got[0][1] ** 2 + got[2][1] ** 2) ** 0.5
    print(f"  two-out minus nought-out: {spread:+.3f} log-odds "
          f"({spread / se2:+.1f} sigma)")


if __name__ == "__main__":
    main()
