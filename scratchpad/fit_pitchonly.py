"""Fit BOTH hook curves on pitch count alone, and print them as Hook fields.

    venv/bin/python -m scratchpad.fit_pitchonly

THE QUESTION, and it is the user's: what if the hook were just pitch count?

THE CASE FOR ASKING. The 2026 boundary fit puts `per_run` at +0.008 and
`per_margin` at -0.013 — indistinguishable from zero on 38,949 decisions —
and `removal.py` already recorded that pitch count ALONE ranks removals at
AUC 0.901 against 0.914 for the full fourteen-feature model. So most of the
"the manager weighs the traffic and the score" story is not in the data. If
it is not earning anything on the quantity that settles either, it is a pile
of fitted parameters that has caused repeated trouble for nothing.

ZEROING THE TERMS IS NOT THE TEST, and this is the whole reason this file
exists rather than a dict of zeros in the scorer. Every dropped term carries
part of the LEVEL: `per_inning` is -0.109 and innings run 1-9, so deleting it
alone shifts the logit by most of a unit and the hook stops firing at
anything like the right rate. That would lose on a technicality and tell us
nothing about pitch count. The honest comparison is the BEST pitch-only
curve against the shipped one, so each is refitted on its own population
with only the pitch term present.

2025 AND 2026 ONLY. Day eleven measured the boundary curve on each season
alone and 2023/2024 are a different manager — `pitch_scale` 17.21 and 13.70
against 10.54 and 10.85. Fitting this on everything on disk would pool two
eras and hand the pitch-only arm a curve nobody used, which would rig the
comparison against it.

FITTING TO REMOVAL DECISIONS IS PERMITTED; the target is what the manager
did, not what the game settled at.
"""
from __future__ import annotations

import json
import statistics as st
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression

from src import db
from src.context import removal, sim
from scratchpad import fit_boundary as fb
from scratchpad import split_boundary as sb

ERA = ("2025", "2026")

OUT = "scratchpad/pitchonly_hook.json"


def _rows():
    """Every starter decision in the era, split by which curve owns it.

    BOTH curves, and they are fitted on their OWN rows. Pooling them is the
    mistake this project has made most often — 32,497 of the mid-inning rows
    sit under 60 pitches and swamp the late ones by count — and it is
    especially tempting here, where the two fits differ only by a filter.
    """
    import concurrent.futures as cf
    import glob
    import multiprocessing as mp
    import os
    season = sb._seasons()
    on_disk = {os.path.basename(f).split(".")[0]
               for f in glob.glob(".cache/pbp/*.json.gz")}
    gids = [g for g, s in season.items() if s in ERA and g in on_disk]
    print(f"  {len(gids):,} games in {'/'.join(ERA)}", flush=True)

    bnd, mid = [], []
    with cf.ProcessPoolExecutor(
            max_workers=max(1, (os.cpu_count() or 4) - 1),
            mp_context=mp.get_context("fork")) as pool:
        for got in pool.map(_decisions, gids, chunksize=32):
            for r in got:
                (bnd if r["ends_inning"] else mid).append(r)
    return bnd, mid


def _decisions(gid):
    from src.context import boundary
    try:
        return boundary.decisions(gid)
    except Exception:
        return []


def fit_one(rows, label):
    """Unregularised logistic on pitch count alone."""
    X = np.array([[float(r["pitches"])] for r in rows])
    y = np.array([1 if r["removed"] else 0 for r in rows])
    m = LogisticRegression(max_iter=5000, C=1e6)
    m.fit(X, y)
    p = m.predict_proba(X)[:, 1]
    print(f"  {label:<12}{len(rows):>9,} rows  pull {y.mean():.4f}  "
          f"AUC {removal.auc(y, p):.4f}  logloss {removal.log_loss(y, p):.4f}")
    return float(m.coef_[0][0]), float(m.intercept_[0])


def main(argv):
    bnd, mid = _rows()
    print()
    slope_b, const_b = fit_one(bnd, "boundary")
    slope_m, const_m = fit_one(mid, "mid-inning")

    cur = sim.Hook()
    # `pitch_center` is pinned at the mean of a real boundary decision and
    # the intercept solved from it, so the parameter stays interpretable
    # instead of drifting to an arbitrary partner of the intercept.
    center = st.mean(r["pitches"] for r in bnd)
    fields = {
        "intercept": const_b + center * slope_b,
        "pitch_center": center,
        "pitch_scale": 1.0 / slope_b,
        # EVERY OTHER BOUNDARY TERM OFF. This is the arm.
        "per_run": 0.0,
        "per_baserunner": 0.0,
        "per_inning": 0.0,
        "per_margin": 0.0,
        # `mid_intercept` is held at its shipped value and the offset takes
        # the rest, because only their sum is identified.
        "late_mid_offset": const_m - cur.mid_intercept,
        "late_mid_per_pitch": slope_m,
        "late_mid_per_inning_br": 0.0,
        "late_mid_per_run": 0.0,
        "late_mid_per_onbase": 0.0,
        "mid_per_margin": 0.0,
        "mid_per_inning_run": 0.0,
    }
    print(f"\n  {'parameter':<24}{'shipped':>11}{'pitch-only':>12}")
    for k, v in fields.items():
        print(f"  {k:<24}{getattr(cur, k):>11.4f}{v:>12.4f}")

    json.dump(fields, open(OUT, "w"), indent=2)
    print(f"\n  -> {OUT}")

    print("\n  HAZARD BY PITCH COUNT — boundary, counted against both curves")
    print(f"  {'bucket':<12}{'n':>8}{'actual':>9}{'shipped':>9}"
          f"{'pitch-only':>12}")
    po = sim.Hook(**fields)
    for lo, hi, n, act in fb.hazard(bnd):
        g = [r for r in bnd if lo <= r["pitches"] < hi]

        def mean_p(h):
            return st.mean(h.removal_p(r["pitches"], r["runs"], r["inning"],
                                       r["br"], r["margin"]) for r in g)
        print(f"  {f'{lo}-{hi}':<12}{n:>8,}{act:>9.3f}"
              f"{mean_p(cur):>9.3f}{mean_p(po):>12.3f}")
    assert db and json


if __name__ == "__main__":
    main(sys.argv[1:])
