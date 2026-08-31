"""PITCH COUNT x INNING — the interaction neither curve has. Counted.

    venv/bin/python -m scratchpad.pxi [--control]

QUESTION    Is seventy pitches in the third a different removal decision
            from seventy in the fifth, beyond what the two curves already
            read?

HYPOTHESIS  It is. `removal_p` takes `pitches` and `innings` as separate
            ADDITIVE terms and `mid_removal_p` takes `pitches` and `inning`
            the same way, so neither can express "this many pitches, this
            early". Day seven counted it and never built it:

                P(pulled)   inn 3   inn 4   inn 5
                70 pitches   6.01%   2.22%   1.62%

            Same pitch count, a 3.7x span. Seventy in the third means the
            wheels came off; seventy in the fifth means he is cruising.

TEST        An offset per (pitch band x inning) cell, SOLVED conditional on
            every other shipped term, on each curve's own population.

WHY NOT PITCHES PER INNING, which is the obvious compression and was tried
on day seven and rejected: it FOLDS BACK ON ITSELF. High pitches-per-inning
early means FEW TOTAL pitches, so the measure is non-monotone (1.68% under
13, 4.77% at 19-21, 3.14% at 26+) against a monotone 75x span for raw pitch
count. A cell table has no such degeneracy because it never divides.

CENTRED on the row-weighted mean, so this ships SHAPE and not LEVEL. The
curves are already calibrated pooled; uncentred offsets would move how deep
starters go as a side effect, which is a second undeclared knob on the
quantity three other terms already control.

TRAIN ROWS ONLY. `HOLDOUT_CUT` = 2026-07-01.
"""
from __future__ import annotations

import json
import math
import random
import sys

import numpy as np

from src.context import sim
from scratchpad.pitch_hazard import HOLDOUT_CUT, ROWS, other_terms, train_only

#: Coarse on purpose. The interaction is a level effect within a band, and
#: the pitch BACKBONE already carries the within-band slope.
PITCH_BANDS = (0, 45, 60, 75, 90, 200)
#: Innings 1-3 pooled (few decisions, and the early tail is the mixture's
#: job), 7+ pooled (thin, and the decision is nearly deterministic there).
INNING_GROUPS = ((1, 3), (4, 4), (5, 5), (6, 6), (7, 9))
MIN_CELL = 300

#: THE SUB-45 BAND IS NOT THIS MECHANISM AND IS EXCLUDED FROM BOTH THE
#: TABLE AND THE CENTRING. Its cells solve to +0.9 and +1.1 on the boundary
#: curve, which is the disaster tail: a starter removed under 45 pitches was
#: chased or hurt, not out-managed. That population belongs to the
#: early-exit MIXTURE (`early_exit_p`), and `early_exit_floor` exists
#: precisely to stop the hook producing those starts on top of it. Day
#: seven's `early_innings` branches fixed the tail from inside the curve
#: and bought it with spread — outs SD 4.47 against a real 3.99 — and this
#: is the same trap wearing a different name.
SHIP_FROM = 45


def band(p):
    for lo, hi in zip(PITCH_BANDS, PITCH_BANDS[1:]):
        if lo <= p < hi:
            return lo
    return PITCH_BANDS[-2]


def inn_group(i):
    for lo, hi in INNING_GROUPS:
        if lo <= i <= hi:
            return lo
    return INNING_GROUPS[-1][0]


def base_logodds(rows, boundary):
    h = sim.Hook()
    out = []
    for r in rows:
        if boundary:
            b = (h.intercept
                 + (r["pitches"] - h.pitch_center) / h.pitch_scale
                 + h.per_pitch_over * max(0.0, r["pitches"] - h.pitch_knee)
                 + (h.high_pitch_bnd
                    if r["pitches"] >= h.high_pitch_threshold else 0.0))
        else:
            b = (h.mid_intercept + h.late_mid_offset
                 + h.late_mid_per_pitch * r["pitches"]
                 + (h.high_pitch_mid
                    if r["pitches"] >= h.high_pitch_threshold else 0.0))
        out.append(b + other_terms(r, boundary))
    return np.array(out)


def solve(rows, boundary):
    base = base_logodds(rows, boundary)
    y = np.array([1.0 if r["removed"] else 0.0 for r in rows])
    tgt = y.mean()
    lo, hi = -9.0, 9.0
    for _ in range(160):
        m = (lo + hi) / 2
        if (1 / (1 + np.exp(-np.clip(base + m, -30, 30)))).mean() < tgt:
            lo = m
        else:
            hi = m
    se = math.sqrt(max(tgt * (1 - tgt), 1e-12) / len(rows))
    return (lo + hi) / 2, se / max(tgt * (1 - tgt), 1e-9), tgt, len(rows)


def table(rows, boundary, label):
    cells = {}
    for r in rows:
        b = band(r["pitches"])
        if b < SHIP_FROM:
            continue
        cells.setdefault((b, inn_group(r["inning"])), []).append(r)
    got = {k: solve(v, boundary) for k, v in cells.items()
           if len(v) >= MIN_CELL}
    tot = sum(v[3] for v in got.values())
    mean = sum(v[0] * v[3] for v in got.values()) / tot
    print(f"  {label}   ({len(got)} cells over {tot:,} rows)")
    hdr = "".join(f"{f'inn {lo}' + ('' if lo == hi else f'-{hi}'):>12}"
                  for lo, hi in INNING_GROUPS)
    print(f"    {'pitches':<10}{hdr}")
    out = {}
    for b in [x for x in PITCH_BANDS[:-1] if x >= SHIP_FROM]:
        cs = []
        for lo, _hi in INNING_GROUPS:
            v = got.get((b, lo))
            if v is None:
                cs.append(f"{'-':>12}")
            else:
                d = v[0] - mean
                out[(b, lo)] = round(d, 4)
                star = "*" if abs(d) > 2 * v[1] else " "
                cs.append(f"{d:>+11.3f}{star}")
        print(f"    {b:<10}" + "".join(cs))
    print(f"    (* = more than 2 se from the centred mean)\n")
    return out


def control(rows, boundary, label):
    """Plant a known cell effect and confirm the solver returns it."""
    plant = {(60, 4): 0.8, (60, 5): -0.8}
    base = base_logodds(rows, boundary)
    add = np.array([plant.get((band(r["pitches"]), inn_group(r["inning"])),
                              0.0) for r in rows])
    p = 1 / (1 + np.exp(-np.clip(base + add, -30, 30)))
    rng = random.Random(17)
    synth = []
    for r, pi in zip(rows, p):
        q = dict(r)
        q["removed"] = rng.random() < pi
        synth.append(q)
    print(f"  POSITIVE CONTROL {label}: planted +0.8 at (60,inn4) and "
          f"-0.8 at (60,inn5)")
    got = table(synth, boundary, "recovered")
    for k, v in plant.items():
        print(f"    planted {v:+.2f} at {k} -> recovered "
              f"{got.get(k, float('nan')):+.3f}")
    print()


def main(argv):
    rows = train_only(json.load(open(ROWS)))
    mid = [r for r in rows if not r.get("ends_inning")]
    bnd = [r for r in rows if r.get("ends_inning")]
    print(f"  {len(mid):,} mid-inning, {len(bnd):,} boundary TRAINING "
          f"decisions (before {HOLDOUT_CUT})\n")
    b = table(bnd, True, "BOUNDARY curve")
    m = table(mid, False, "MID-INNING curve")
    print(f"  PXI_BND = {b}")
    print(f"  PXI_MID = {m}")
    if "--control" in argv:
        print()
        control(bnd, True, "BOUNDARY")


if __name__ == "__main__":
    main(sys.argv[1:])
