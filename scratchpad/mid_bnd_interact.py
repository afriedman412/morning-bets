"""DO THE TWO HOOKS NEED TO SEE EACH OTHER? Counted.

    venv/bin/python -m scratchpad.mid_bnd_interact

QUESTION. `mid_removal_p` and `removal_p` are independent sigmoids evaluated
at different moments and neither takes the other's value. Should the
mid-inning decision know that the boundary decision is about to fire? A
manager who has already decided the man is done at the end of the inning
might stop interrupting it — or, the other way, might stop waiting.

HYPOTHESIS. The real mid-inning hazard falls as the boundary hazard rises,
because a starter who is certain to come out at the end of the frame is
allowed to finish it. If so, the two curves race on every start and the mid
curve wins too often, which is the shape of the standing defect: boundary
share 0.616 against a real 0.674.

TEST. For every training mid-inning decision, evaluate the SHIPPED boundary
curve at that same state, bucket by it, and solve the mid-inning offset each
bucket needs conditional on every other shipped mid term. A flat set of
offsets means the two decisions are independent and the split is not an
interaction. A falling set means the interaction is real and missing.

THE CONFOUND THIS HAS TO SURVIVE, and it is severe: the boundary hazard is
mostly PITCH COUNT, and so is the mid hazard. Both curves rise together for
reasons that have nothing to do with either knowing about the other. The
solve holds the mid curve's own pitch term fixed, so what is left is
whatever the boundary hazard knows that the mid curve does not.

TRAIN ROWS ONLY. Positive-controlled in `--control`.
"""
from __future__ import annotations

import json
import math
import random
import sys

import numpy as np

from src.context import sim
from scratchpad.pitch_hazard import ROWS, other_terms, train_only

#: Set by `--hazard`. Decides which backbone BOTH curves are read through,
#: because the question is whether the bend survives the counted table.
HAZARD = False


def solve_cell(rows):
    """Offset this cell needs, on top of whichever backbone is selected."""
    h = sim.Hook()
    base = []
    for r in rows:
        if HAZARD:
            b = (h.mid_intercept - sim.PITCH_HAZARD_MID_ANCHOR
                 + sim.pitch_hazard(r["pitches"], sim.PITCH_HAZARD_MID))
        else:
            b = (h.mid_intercept + h.late_mid_offset
                 + h.late_mid_per_pitch * r["pitches"]
                 + (h.high_pitch_mid
                    if r["pitches"] >= h.high_pitch_threshold else 0.0))
        base.append(b + other_terms(r, boundary=False))
    base = np.array(base)
    y = np.array([1.0 if r["removed"] else 0.0 for r in rows])
    target = y.mean()
    lo, hi = -8.0, 8.0
    for _ in range(160):
        m = (lo + hi) / 2
        if (1 / (1 + np.exp(-np.clip(base + m, -30, 30)))).mean() < target:
            lo = m
        else:
            hi = m
    se_p = math.sqrt(max(target * (1 - target), 1e-12) / len(rows))
    return ((lo + hi) / 2, se_p / max(target * (1 - target), 1e-9),
            target, len(rows))

#: Buckets on the shipped boundary probability at the same state.
EDGES = (0.0, 0.02, 0.05, 0.12, 0.25, 0.45, 1.01)


def boundary_p(r) -> float:
    h = sim.Hook()
    if HAZARD:
        lo = (h.intercept - sim.PITCH_HAZARD_BND_ANCHOR
              + sim.pitch_hazard(r["pitches"], sim.PITCH_HAZARD_BND)
              + other_terms(r, boundary=True))
        return 1 / (1 + math.exp(-max(-30.0, min(30.0, lo))))
    lo = (h.intercept
          + (r["pitches"] - h.pitch_center) / h.pitch_scale
          + h.per_pitch_over * max(0.0, r["pitches"] - h.pitch_knee)
          + (h.high_pitch_bnd if r["pitches"] >= h.high_pitch_threshold
             else 0.0)
          + other_terms(r, boundary=True))
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, lo))))


def bucket(p):
    for lo, hi in zip(EDGES, EDGES[1:]):
        if lo <= p < hi:
            return lo
    return EDGES[-2]


def run(mid, label):
    cells = {}
    for r in mid:
        cells.setdefault(bucket(r["_bp"]), []).append(r)
    got = {k: solve_cell(v) for k, v in cells.items() if len(v) > 400}
    tot = sum(v[3] for v in got.values())
    mean = sum(v[0] * v[3] for v in got.values()) / tot
    print(f"  {label}")
    print(f"    {'bnd P':<9}{'n':>9}{'mid rate':>11}{'OFFSET':>10}{'se':>8}")
    ks = sorted(got)
    for k in ks:
        d, se, tgt, n = got[k]
        print(f"    {k:<9.2f}{n:>9,}{tgt:>11.4f}{d - mean:>+10.3f}{se:>8.3f}")
    hi, lo = got[ks[-1]], got[ks[0]]
    sp = (hi[0] - mean) - (lo[0] - mean)
    se = (hi[1] ** 2 + lo[1] ** 2) ** 0.5
    print(f"    top minus bottom: {sp:+.3f} log-odds ({sp / se:+.1f} sigma)")
    return sp / se


def main(argv):
    global HAZARD
    HAZARD = "--hazard" in argv
    print(f"  backbone: {'COUNTED pitch hazard' if HAZARD else 'shipped parametric'}")
    rows = train_only(json.load(open(ROWS)))
    mid = [r for r in rows if not r.get("ends_inning")]
    for r in mid:
        r["_bp"] = boundary_p(r)
    print(f"  {len(mid):,} TRAINING mid-inning decisions\n")
    run(mid, "REAL — does the mid hazard bend with the boundary hazard?")

    if "--control" in argv:
        print("\n  POSITIVE CONTROL: relabel from the shipped model with a")
        print("  planted -1.0 log-odds on the top boundary bucket.\n")
        h = sim.Hook()
        rng = random.Random(13)
        base = np.array([
            h.mid_intercept + h.late_mid_offset
            + h.late_mid_per_pitch * r["pitches"]
            + (h.high_pitch_mid
               if r["pitches"] >= h.high_pitch_threshold else 0.0)
            + other_terms(r, boundary=False) for r in mid])
        plant = np.array([-1.0 if r["_bp"] >= EDGES[-2] else 0.0
                          for r in mid])
        p = 1 / (1 + np.exp(-np.clip(base + plant, -30, 30)))
        synth = []
        for r, pi in zip(mid, p):
            q = dict(r)
            q["removed"] = rng.random() < pi
            synth.append(q)
        run(synth, "SYNTHETIC — planted -1.0 on the top bucket")


if __name__ == "__main__":
    main(sys.argv[1:])
