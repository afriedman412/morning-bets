"""Does the boundary curve's pitch term need to be NON-LINEAR? Fit and compare.

    venv/bin/python -m scratchpad.fit_boundary_nl

WHY. The fitted boundary curve (2026-08-26) is a logistic whose logit is
LINEAR in pitch count, and the real hazard is not: at 100-110 pitches it
fires 0.596 where reality is 0.749, under-pulling exactly where 46% of
removals happen. RESUME's diagnosis was that this is a functional-form
limit rather than a training-set choice — restricting the rows was already
tried and made the simulation worse.

WHAT IS COMPARED. Four forms, all fitted the same way on the same 38,485
rows, all unregularised, all with `pitch_center` PINNED at the mean pitch
count of a real boundary decision so the intercept stays interpretable:

    linear      (pitches - c)/scale                        -- shipped
    quad        linear + q*(pitches/100)^2
    hinge90     linear + h*max(0, pitches - 90)
    hinge2      linear + h1*max(0,p-80) + h2*max(0,p-100)

THE TEST IS THE HAZARD TABLE, NOT THE AUC. AUC is nearly flat across these
because ordering barely changes — what changes is the LEVEL in the tail,
and the level is what the simulator integrates. Log loss is the honest
per-decision score; the bucket table is what the defect was stated in.

NOT SHIPPED FROM HERE. A form that wins per decision still has to be
validated on the simulated outs distribution, because the two hook curves
compete for the same exits (day-nine trap).
"""
from __future__ import annotations

import math
import statistics as st
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression

from src.context import removal
from scratchpad.fit_boundary import collect

BASE = ("pitches", "runs", "br", "inning", "margin")


def design(rows, extra):
    """(X, names) for the base features plus named non-linear pitch terms."""
    cols = [[float(r[f]) for r in rows] for f in BASE]
    names = list(BASE)
    for nm, fn in extra:
        cols.append([fn(float(r["pitches"])) for r in rows])
        names.append(nm)
    return np.array(cols).T, names


FORMS = {
    "linear": [],
    "quad": [("p2", lambda p: (p / 100.0) ** 2)],
    "hinge90": [("h90", lambda p: max(0.0, p - 90.0))],
    # Monotone by construction if both coefficients come out positive:
    # slope rises once at 60 and again at 90 and never falls. The quadratic
    # is convex everywhere, which means it is DEcreasing below its vertex —
    # and this curve is evaluated at every inning end, including a 15-pitch
    # first, so a form that is only right where the mass is is not enough.
    "hinge6090": [("h60", lambda p: max(0.0, p - 60.0)),
                  ("h90", lambda p: max(0.0, p - 90.0))],
    "hinge60": [("h60", lambda p: max(0.0, p - 60.0))],
}

EDGES = [(0, 20), (20, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 80),
         (80, 90), (90, 100), (100, 110), (110, 999)]


def main(argv):
    rows = collect(rebuild="--rebuild" in argv)
    y = np.array([1 if r["removed"] else 0 for r in rows])
    pitch_center = st.mean(r["pitches"] for r in rows)
    print(f"\n  {len(rows):,} boundary decisions   pull rate {y.mean():.4f}"
          f"   pitch_center pinned at {pitch_center:.2f}")

    fits = {}
    print(f"\n  {'form':<10}{'k':>4}{'AUC':>9}{'logloss':>10}{'BIC':>12}")
    for name, extra in FORMS.items():
        X, cols = design(rows, extra)
        m = LogisticRegression(max_iter=8000, C=1e6)
        m.fit(X, y)
        p = m.predict_proba(X)[:, 1]
        ll = removal.log_loss(y, p)
        k = X.shape[1] + 1
        bic = 2 * ll * len(rows) + k * math.log(len(rows))
        fits[name] = (m, cols, p, extra)
        print(f"  {name:<10}{k:>4}{removal.auc(y, p):>9.4f}{ll:>10.5f}"
              f"{bic:>12.1f}")

    print(f"\n  HAZARD BY PITCH COUNT — the level is the defect")
    hdr = f"  {'bucket':<11}{'n':>7}{'actual':>9}"
    for name in FORMS:
        hdr += f"{name:>9}"
    print(hdr)
    for lo, hi in EDGES:
        idx = [i for i, r in enumerate(rows) if lo <= r["pitches"] < hi]
        if len(idx) < 30:
            continue
        # float(), not the raw numpy int: statistics.mean coerces its result
        # back to the input type and an integer mean truncates to zero.
        act = st.mean(float(y[i]) for i in idx)
        line = f"  {f'{lo}-{hi}':<11}{len(idx):>7}{act:>9.3f}"
        for name in FORMS:
            p = fits[name][2]
            line += f"{st.mean(p[i] for i in idx):>9.3f}"
        print(line)

    # WHERE THE KNEE BELONGS. Scanned rather than asserted at 60 — a knee
    # picked to match a bucket boundary is a bucket boundary, not a finding.
    print("\n  SINGLE-KNEE SCAN (one hinge, knee fitted by log loss)")
    print(f"  {'knee':<8}{'logloss':>10}{'AUC':>9}{'slope<knee':>12}"
          f"{'slope>knee':>12}")
    for knee in (40, 45, 50, 55, 60, 65, 70, 75, 80):
        X, cols = design(rows, [("h", lambda p, k=knee: max(0.0, p - k))])
        m = LogisticRegression(max_iter=8000, C=1e6)
        m.fit(X, y)
        p = m.predict_proba(X)[:, 1]
        c = dict(zip(cols, m.coef_[0]))
        print(f"  {knee:<8}{removal.log_loss(y, p):>10.5f}"
              f"{removal.auc(y, p):>9.4f}{c['pitches']:>12.5f}"
              f"{c['pitches'] + c['h']:>12.5f}")

    print("\n  COEFFICIENTS")
    for name, (m, cols, _, _) in fits.items():
        coef = dict(zip(cols, m.coef_[0]))
        const = float(m.intercept_[0])
        icept = const + pitch_center * coef["pitches"]
        parts = [f"intercept {icept:+.4f}",
                 f"pitch_scale {1.0/coef['pitches']:.4f}",
                 f"per_run {coef['runs']:+.4f}",
                 f"per_br {coef['br']:+.4f}",
                 f"per_inning {coef['inning']:+.4f}",
                 f"per_margin {coef['margin']:+.4f}"]
        parts += [f"{c} {coef[c]:+.6f}" for c in cols if c not in BASE]
        print(f"    {name:<10}" + "  ".join(parts))


if __name__ == "__main__":
    main(sys.argv[1:])
