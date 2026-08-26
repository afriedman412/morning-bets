"""Fit the BOUNDARY curve on boundary decisions only, in the Hook's own form.

    venv/bin/python -m scratchpad.fit_boundary [n_games]

WHY THIS AND NOT A GLOBAL SWEEP. The hook is two curves fitted on two
populations. Day seven established that pooling them breaks: 26,693 early
decisions at a 0.65% pull rate swamped 20,994 late ones at 6.29% by sheer
count, and the late curve came out at 7.24% where reality is 33.80%. The
MID-INNING curve was then fitted directly as a logistic on its own rows —
`late_mid_offset`, `late_mid_per_pitch`, `late_mid_per_inning_br` are those
coefficients. The BOUNDARY curve never got the same treatment; its
parameters still trace to the commit that created the simulator.

A pooled coordinate descent over `calibrate.loss` was tried on 2026-08-26
and is the wrong tool for a recorded reason. `loss` weights the hazard curve
4x and the boundary SHARE 1x, so it bought hazard accuracy by pushing the
share from 0.643 to 0.620 against a measured 0.663 — trading a counted
quantity for a fitted one. `intercept` also belongs to the boundary curve
alone, so moving it silently paid one curve out of the other's pocket.

THE FORM IS ALREADY A LOGISTIC, which is what makes this direct rather than
a search:

    logit = intercept + (pitches - pitch_center)/pitch_scale
            + per_run*runs + per_baserunner*br + per_inning*innings
            + per_margin*margin

so an unregularised logistic regression on those five features returns the
parameters, no grid involved:

    per_pitch coefficient  -> 1 / pitch_scale
    runs, br, innings, margin -> per_run, per_baserunner, per_inning,
                                 per_margin
    the fitted constant    -> intercept, once pitch_center is pinned

`pitch_center` and `intercept` are not separately identified — only
`intercept - pitch_center/pitch_scale` is — so `pitch_center` is PINNED at
the mean pitch count of a real boundary decision and the intercept solved
from it. That keeps the parameter interpretable ("the count at which the
curve is centred") instead of letting it drift to an arbitrary partner of
the intercept, which is how it ended up pinned at a grid edge before.

FITTING TO REMOVAL DECISIONS IS PERMITTED AND FITTING TO RUNS IS NOT.
CLAUDE.md: "do not fit the hook AGAINST THE SETTLEMENT VALUE. Fitting it to
real removal DECISIONS is a different thing." The target here is what the
manager did.
"""
from __future__ import annotations

import glob
import json
import math
import os
import statistics as st
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression

from src.context import boundary, removal, sim

#: The features the shipped boundary curve actually reads, in its order.
FEATS = ("pitches", "runs", "br", "inning", "margin")

CACHE = "/tmp/boundary_rows.json"


def collect(limit=None, rebuild=False) -> list[dict]:
    if not rebuild and limit is None and os.path.exists(CACHE):
        return json.load(open(CACHE))
    files = sorted(glob.glob(".cache/pbp/*.json.gz"))
    gids = [os.path.basename(f).split(".")[0] for f in files]
    if limit:
        gids = gids[:limit]
    rows = []
    for i, g in enumerate(gids):
        try:
            rows += [r for r in boundary.decisions(g) if r["ends_inning"]]
        except Exception:
            continue
        if (i + 1) % 400 == 0:
            print(f"    {i+1}/{len(gids)} games, {len(rows):,} decisions",
                  flush=True)
    if limit is None:
        json.dump(rows, open(CACHE, "w"))
    return rows


def hazard(rows, key="pitches", edges=(60, 70, 80, 90, 100, 110)):
    """Observed pull rate by bucket — the thing the curve has to reproduce."""
    out = []
    lo = 0
    for hi in list(edges) + [999]:
        g = [r for r in rows if lo <= r[key] < hi]
        if len(g) >= 30:
            out.append((lo, hi, len(g),
                        sum(1 for r in g if r["removed"]) / len(g)))
        lo = hi
    return out


def main(argv):
    lim = int(argv[0]) if argv and argv[0].isdigit() else None
    rows = collect(lim, rebuild="--rebuild" in argv)
    print(f"\n  {len(rows):,} BOUNDARY decisions "
          f"(end-of-inning, starter still in)")
    print(f"  pull rate {st.mean(r['removed'] for r in rows):.4f}")

    X = np.array([[float(r[f]) for f in FEATS] for r in rows])
    y = np.array([1 if r["removed"] else 0 for r in rows])
    # UNREGULARISED. The coefficients ARE the shipped parameters, so shrinking
    # them toward zero would ship a hook that is deliberately too flat.
    m = LogisticRegression(max_iter=5000, C=1e6)
    m.fit(X, y)
    coef = dict(zip(FEATS, m.coef_[0]))
    const = float(m.intercept_[0])

    pitch_center = st.mean(r["pitches"] for r in rows)
    pitch_scale = 1.0 / coef["pitches"]
    intercept = const + pitch_center * coef["pitches"]

    p = m.predict_proba(X)[:, 1]
    print(f"  in-sample AUC {removal.auc(y, p):.4f}   "
          f"log loss {removal.log_loss(y, p):.4f}")

    cur = sim.Hook()
    print(f"\n  {'parameter':<18}{'shipped':>10}{'fitted':>10}")
    for name, val in (("intercept", intercept), ("pitch_center", pitch_center),
                      ("pitch_scale", pitch_scale),
                      ("per_run", coef["runs"]),
                      ("per_baserunner", coef["br"]),
                      ("per_inning", coef["inning"]),
                      ("per_margin", coef["margin"])):
        print(f"  {name:<18}{getattr(cur, name):>10.4f}{val:>10.4f}")

    print(f"\n  HAZARD BY PITCH COUNT — the curve has to reproduce this")
    print(f"  {'bucket':<12}{'n':>7}{'actual':>9}{'shipped':>9}{'fitted':>9}")
    fitted = sim.Hook(intercept=intercept, pitch_center=pitch_center,
                      pitch_scale=pitch_scale, per_run=coef["runs"],
                      per_baserunner=coef["br"], per_inning=coef["inning"],
                      per_margin=coef["margin"])
    for lo, hi, n, act in hazard(rows):
        g = [r for r in rows if lo <= r["pitches"] < hi]
        def mean_p(h):
            return st.mean(h.removal_p(r["pitches"], r["runs"], r["inning"],
                                       r["br"], r["margin"]) for r in g)
        print(f"  {f'{lo}-{hi}':<12}{n:>7}{act:>9.3f}"
              f"{mean_p(cur):>9.3f}{mean_p(fitted):>9.3f}")

    print(f"\n  HAZARD BY INNING")
    print(f"  {'inning':<12}{'n':>7}{'actual':>9}{'shipped':>9}{'fitted':>9}")
    for inn in range(3, 9):
        g = [r for r in rows if r["inning"] == inn]
        if len(g) < 30:
            continue
        act = sum(1 for r in g if r["removed"]) / len(g)
        def mean_p(h):
            return st.mean(h.removal_p(r["pitches"], r["runs"], r["inning"],
                                       r["br"], r["margin"]) for r in g)
        print(f"  {inn:<12}{len(g):>7}{act:>9.3f}"
              f"{mean_p(cur):>9.3f}{mean_p(fitted):>9.3f}")
    assert math and json


if __name__ == "__main__":
    main(sys.argv[1:])
