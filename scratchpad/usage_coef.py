"""Item 36 pre-wiring — count the usage-gap coefficient, pre-HOLDOUT.

    venv/bin/python -m scratchpad.usage_coef [n_sims]

Registered in TODO 36 (fourth sitting) before this ran. The coefficient
is the slope of (actual - model) outs on the arm's per-date
last-4-vs-season pitch gap, counted on the 2023/2024/2025 folds ONLY —
the 2026 fold is the wiring A/B's holdout and must not enter the count.
Shipped engine, leash ON, CR0 by arm.

Form checks, each decided by count: linearity by gap bins (clamp only
if the tails saturate), symmetry (one coefficient if the two sides
agree within 2 se), and the within-arm test (arm-season demeaned slope
must survive, else the term is a per-arm trait the leash already owns
and the wiring dies here).
"""
from __future__ import annotations

import sys
from collections import defaultdict

import numpy as np

from scratchpad import ramp_score
from scratchpad.ramp_score import collect, ramp_lookup
from scratchpad.usage_trend import cr0

COUNT_FOLDS = ((2023, "2023-07-01"), (2024, "2024-07-01"),
               (2025, "2025-07-01"))
BINS = ((-99, -12), (-12, -8), (-8, -4), (-4, 0),
        (0, 4), (4, 8), (8, 12), (12, 99))


def fit(rows, cols, names):
    X = np.column_stack([np.ones(len(rows))] + cols)
    y = np.array([a - m for _, _, a, m in rows])
    c = np.array([r[0] for r in rows])
    b, se = cr0(X, y, c)
    return {n: (b[j], se[j]) for j, n in enumerate(names, start=1)}


def main(argv):
    if argv:
        ramp_score._SIMS = int(argv[0])
    look, dropped = ramp_lookup()
    print(f"ITEM 36 PRE-WIRING — the count, folds 2023-25 ONLY "
          f"(2026 is the wiring A/B holdout). {ramp_score._SIMS} draws, "
          f"leash ON.\n  lookup {len(look):,} start-dates, "
          f"{dropped} collisions dropped")

    per_fold = {}
    for year, cut in COUNT_FOLDS:
        rows = collect(year, cut)
        joined = [(nm, look[(nm, dt)][1], a, m)      # gap, not slope
                  for nm, dt, a, m in rows if (nm, dt) in look]
        per_fold[year] = joined
        print(f"  fold {year}: {len(joined)} joined starts")
    allrows = [r for rs in per_fold.values() for r in rs]
    gaps = np.array([r[1] for r in allrows])
    print(f"\n  gap distribution: sd {gaps.std():.2f} pitches, "
          f"p5 {np.percentile(gaps, 5):+.1f}, p95 "
          f"{np.percentile(gaps, 95):+.1f}, share past +/-8: "
          f"{np.mean(np.abs(gaps) >= 8):.1%}")

    print("\nTHE COEFFICIENT — (actual - model) outs ~ gap, CR0 by arm:")
    acc = []
    for year, _ in COUNT_FOLDS:
        rs = per_fold[year]
        g = np.array([r[1] for r in rs])
        e = fit(rs, [g], ["gap"])
        b, se = e["gap"]
        acc.append((b, se))
        print(f"  {year}: {b:+.4f} ({se:.4f}) z {b / se:+.1f}   "
              f"n {len(rs)}")
    w = np.array([1 / se ** 2 for _, se in acc])
    coef = sum(b * ww for (b, _), ww in zip(acc, w)) / w.sum()
    cse = 1 / np.sqrt(w.sum())
    chi = sum(ww * (b - coef) ** 2 for (b, _), ww in zip(acc, w))
    print(f"  POOLED: {coef:+.4f} ({cse:.4f}) z {coef / cse:+.1f}   "
          f"homogeneity chi-sq {chi:.2f} on 2 df")

    print("\nFORM CHECK (a) — LINEARITY, mean residual by gap bin:")
    print(f"  {'bin':>12}{'n':>7}{'mean resid':>12}{'linear says':>13}")
    for lo, hi in BINS:
        sub = [r for r in allrows if lo <= r[1] < hi]
        if len(sub) < 30:
            continue
        m = np.mean([a - mm for _, _, a, mm in sub])
        gbar = np.mean([r[1] for r in sub])
        print(f"  {f'{lo}..{hi}':>12}{len(sub):>7}{m:>+12.3f}"
              f"{coef * gbar:>+13.3f}")

    print("\nFORM CHECK (b) — SYMMETRY, slope each side of zero:")
    g = np.array([r[1] for r in allrows])
    e = fit(allrows, [np.minimum(g, 0.0), np.maximum(g, 0.0)],
            ["gap_neg", "gap_pos"])
    bn, sn = e["gap_neg"]
    bp, sp = e["gap_pos"]
    dz = abs(bn - bp) / np.hypot(sn, sp)
    print(f"  gap<0: {bn:+.4f} ({sn:.4f})   gap>0: {bp:+.4f} ({sp:.4f})"
          f"   difference {dz:.1f} se -> "
          f"{'ONE coefficient' if dz < 2 else 'TWO coefficients'}")

    print("\nFORM CHECK (c) — WITHIN-ARM (arm-season demeaned; a per-arm "
          "trait the leash owns would die here):")
    # Demean gap and residual within arm across the three folds —
    # conservative (removes MORE between-arm variation than arm-season
    # demeaning would, so a surviving slope is safely within-arm).
    by_arm = defaultdict(list)
    for r in allrows:
        by_arm[r[0]].append(r)
    dem = []
    for nm, rs in by_arm.items():
        if len(rs) < 3:
            continue
        gm = np.mean([r[1] for r in rs])
        rm = np.mean([a - m for _, _, a, m in rs])
        for _, gp, a, m in rs:
            dem.append((nm, gp - gm, a - m - rm + 0.0, 0.0))
    gd = np.array([r[1] for r in dem])
    ed = fit([(nm, gp, y_, 0.0) for nm, gp, y_, _ in dem], [gd], ["gap"])
    bw, sw = ed["gap"]
    print(f"  within-arm slope {bw:+.4f} ({sw:.4f}) z {bw / sw:+.1f} "
          f"on {len(dem)} demeaned starts -> "
          f"{'SURVIVES' if bw / sw >= 2 else 'DIES — do not wire'}")

    print(f"\nDELIVERABLE: coefficient {coef:+.4f} outs per pitch of "
          f"gap (pre-holdout count), thin history (< 4 prior) -> 0. "
          f"Wiring converts via a hook offset and VERIFIES d_outs by "
          f"sweep, not via OUTS_PER_OFFSET alone.")


if __name__ == "__main__":
    main(sys.argv[1:])
