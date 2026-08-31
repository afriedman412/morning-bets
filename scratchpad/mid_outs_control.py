"""POSITIVE CONTROL for the out-count null. Can the solver see one at all?

    venv/bin/python -m scratchpad.mid_outs_control

`mid_outs_fit.py` returns a two-out contrast of -0.055 log-odds at -1.6
sigma once the other shipped terms are held. A mis-specified harness and an
absent effect produce identical output, so this injects an effect of a known
size and confirms it comes back.

METHOD. Relabel every training mid-inning row by the SHIPPED model plus a
planted out-count offset, then run the same solver on the synthetic labels.
The labels are drawn, not thresholded, so the recovered value carries the
same sampling noise the real fit does.
"""
from __future__ import annotations

import json
import random

import numpy as np

from src.context import sim
from scratchpad.mid_outs_fit import solve_cell
from scratchpad.pitch_hazard import ROWS, other_terms, train_only

PLANTED = (0.0, 0.25, 0.60)


def main():
    rows = train_only(json.load(open(ROWS)))
    mid = [r for r in rows if not r.get("ends_inning")
           and r.get("outs_before") in (0, 1, 2)]
    h = sim.Hook()
    base = np.array([
        h.mid_intercept + h.late_mid_offset
        + h.late_mid_per_pitch * r["pitches"]
        + (h.high_pitch_mid if r["pitches"] >= h.high_pitch_threshold else 0.0)
        + other_terms(r, boundary=False)
        for r in mid])
    planted = np.array([PLANTED[r["outs_before"]] for r in mid])
    p = 1 / (1 + np.exp(-np.clip(base + planted, -30, 30)))
    rng = random.Random(11)
    synth = []
    for r, pi in zip(mid, p):
        q = dict(r)
        q["removed"] = rng.random() < pi
        synth.append(q)

    got = {o: solve_cell([r for r in synth if r["outs_before"] == o])
           for o in (0, 1, 2)}
    tot = sum(got[o][3] for o in (0, 1, 2))
    mean = sum(got[o][0] * got[o][3] for o in (0, 1, 2)) / tot
    pmean = sum(PLANTED[o] * got[o][3] for o in (0, 1, 2)) / tot
    print(f"  {len(mid):,} rows relabelled from the shipped model plus a "
          f"planted offset\n")
    print(f"  {'outs':<6}{'planted':>10}{'recovered':>12}{'se':>8}")
    for o in (0, 1, 2):
        print(f"  {o:<6}{PLANTED[o] - pmean:>+10.3f}"
              f"{got[o][0] - mean:>+12.3f}{got[o][1]:>8.3f}")
    rec = (got[2][0] - mean) - (got[0][0] - mean)
    tru = PLANTED[2] - PLANTED[0]
    se = (got[0][1] ** 2 + got[2][1] ** 2) ** 0.5
    print(f"\n  two-out contrast: planted {tru:+.3f}, recovered {rec:+.3f} "
          f"({rec / se:+.1f} sigma)")
    print(f"  -> the harness resolves an effect of this size at "
          f"{tru / se:.0f} sigma. The real fit returned -1.6.")


if __name__ == "__main__":
    main()
