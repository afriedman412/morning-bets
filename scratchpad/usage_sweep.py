"""Item 36 wiring — verify the realized d_outs per pitch of gap.

    venv/bin/python -m scratchpad.usage_sweep [n_sims]

The wiring converts the counted +0.0571 outs/pitch through
`leash.offset_for`, whose table is ~0.85 of its claim on the long side
(2026-09-11). Registered rule: verify by sweep, don't trust the
constant. 2026 fold, flag off vs on, paired seeds; regress the model's
own outs shift on the gap. Target slope +0.0571; the known table wobble
brackets acceptance at 0.85-1.15 of target before any rescale is
considered.
"""
from __future__ import annotations

import sys

import numpy as np

from scratchpad import ramp_score
from scratchpad.ramp_score import collect, ramp_lookup
from src.context import sim
from src.context.usage import USAGE_OUTS_PER_PITCH


def main(argv):
    if argv:
        ramp_score._SIMS = int(argv[0])
    look, _ = ramp_lookup()
    got = {}
    for flag in (False, True):
        sim.USE_USAGE_GAP = flag
        rows = collect(2026, "2026-07-01")
        got[flag] = {(nm, dt): m for nm, dt, _a, m in rows}
    sim.USE_USAGE_GAP = False
    keys = [k for k in got[False] if k in got[True] and k in look]
    gap = np.array([look[k][1] for k in keys])
    d = np.array([got[True][k] - got[False][k] for k in keys])
    x = gap - gap.mean()
    slope = float(np.dot(x, d - d.mean()) / np.dot(x, x))
    resid = d - d.mean() - slope * x
    se = float(np.sqrt(np.sum(resid ** 2) / (len(d) - 2) / np.dot(x, x)))
    print(f"  {len(keys)} paired starts, {ramp_score._SIMS} draws")
    print(f"  realized d_outs per pitch of gap: {slope:+.4f} ({se:.4f})")
    print(f"  target (counted): {USAGE_OUTS_PER_PITCH:+.4f}   "
          f"ratio {slope / USAGE_OUTS_PER_PITCH:.2f}")
    print(f"  mean |shift|: {np.mean(np.abs(d)):.3f} outs; "
          f"largest {np.max(np.abs(d)):.2f}")


if __name__ == "__main__":
    main(sys.argv[1:])
