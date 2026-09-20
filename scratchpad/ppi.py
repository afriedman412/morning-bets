"""PITCHES PER INNING — does the ratio carry what the two terms cannot?

    venv/bin/python -m scratchpad.ppi

QUESTION. Both hooks read cumulative `pitches` and they read `inning`, as
separate linear terms. Neither forms the RATIO, so a starter at 85 pitches
in the fifth and one at 85 in the seventh are the same row plus an inning
offset. The first is labouring and the second is cruising, and a manager
knows the difference. Is it information the curves do not already have?

TEST. Bucket every training decision by pitches/inning and solve the offset
each bucket needs conditional on every other shipped term, on BOTH curves.
Flat means the two linear terms already span it. A slope means the ratio is
a real missing interaction.

CONFOUND. Pitches per inning rises with traffic, and traffic is already
read. The solve holds it fixed, which is the whole point of solving rather
than tabulating.
"""
from __future__ import annotations

import json
import math

import numpy as np

from src.context import sim
from scratchpad.pitch_hazard import ROWS, other_terms, train_only

EDGES = (0, 13, 15, 17, 19, 22, 99)


def solve(rows, boundary):
    h = sim.Hook()
    base = []
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
        base.append(b + other_terms(r, boundary))
    base = np.array(base)
    y = np.array([1.0 if r["removed"] else 0.0 for r in rows])
    tgt = y.mean()
    lo, hi = -8.0, 8.0
    for _ in range(160):
        m = (lo + hi) / 2
        if (1 / (1 + np.exp(-np.clip(base + m, -30, 30)))).mean() < tgt:
            lo = m
        else:
            hi = m
    se = math.sqrt(max(tgt * (1 - tgt), 1e-12) / len(rows))
    return (lo + hi) / 2, se / max(tgt * (1 - tgt), 1e-9), tgt, len(rows)


def bucket(r):
    ppi = r["pitches"] / max(r["inning"], 1)
    for lo, hi in zip(EDGES, EDGES[1:]):
        if lo <= ppi < hi:
            return lo
    return EDGES[-2]


def run(rows, boundary, label):
    cells = {}
    for r in rows:
        cells.setdefault(bucket(r), []).append(r)
    got = {k: solve(v, boundary) for k, v in cells.items() if len(v) > 500}
    tot = sum(v[3] for v in got.values())
    mean = sum(v[0] * v[3] for v in got.values()) / tot
    print(f"  {label}")
    print(f"    {'pitch/inn':<11}{'n':>9}{'rate':>9}{'OFFSET':>10}{'se':>8}")
    ks = sorted(got)
    for k in ks:
        d, se, tgt, n = got[k]
        print(f"    {k:<11}{n:>9,}{tgt:>9.4f}{d - mean:>+10.3f}{se:>8.3f}")
    sp = (got[ks[-1]][0] - mean) - (got[ks[0]][0] - mean)
    se = (got[ks[-1]][1] ** 2 + got[ks[0]][1] ** 2) ** 0.5
    print(f"    top minus bottom: {sp:+.3f} log-odds ({sp / se:+.1f} sigma)\n")


def main():
    rows = train_only(json.load(open(ROWS)))
    mid = [r for r in rows if not r.get("ends_inning")]
    bnd = [r for r in rows if r.get("ends_inning")]
    print(f"  {len(mid):,} mid-inning, {len(bnd):,} boundary "
          f"TRAINING decisions\n")
    run(mid, False, "MID-INNING curve")
    run(bnd, True, "BOUNDARY curve")


if __name__ == "__main__":
    main()
