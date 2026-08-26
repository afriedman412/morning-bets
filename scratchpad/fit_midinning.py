"""Refit the MID-INNING curve on its own decisions, in the Hook's own form.

    venv/bin/python -m scratchpad.fit_midinning [--rebuild]

WHY. Its coefficients — `late_mid_offset`, `late_mid_per_pitch`,
`late_mid_per_inning_br` — were fitted on day seven against mid-inning
decisions generated under the OLD boundary curve, which fires at 0.293 where
reality is 0.074. That boundary curve was replaced on 2026-08-26 with one
fitted on 38,485 real end-of-inning decisions, so the state distribution the
mid-inning curve was calibrated against no longer exists.

The two curves compete for the same exits: a boundary curve that stops
over-pulling leaves starters in to face more batters, and every extra batter
is another mid-inning chance. Correcting one and not the other is what left
mean outs at 16.50 against a real 15.78.

THE FORM IS A LOGISTIC, so this is a fit and not a search:

    logit = mid_intercept + late_mid_offset
            + late_mid_per_pitch * pitches
            + late_mid_per_inning_br * inning_br
            + late_mid_per_run * runs
            + late_mid_per_onbase * on_base
            + mid_per_margin * margin
            + mid_per_inning_run * inning_run_offset(inning_runs)

`mid_intercept` and `late_mid_offset` are not separately identified — only
their sum is — so `mid_intercept` is HELD at its shipped -5.0 and the offset
takes the remainder. Same treatment `pitch_center` got on the boundary side.

`mid_per_inning_run` IS COUNTED, not fitted: it comes off the real per-run
hazard in the current half-inning, and the standing rule is that handing a
measured quantity back to a search is how it goes back to absorbing other
defects. It is fitted here ONLY to be compared against the counted value —
agreement is a validation, disagreement is a finding — and the counted value
is what would ship.
"""
from __future__ import annotations

import glob
import json
import os
import statistics as st
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression

from src.context import boundary, removal, sim

#: In the Hook's order. `inn_run_off` is the counted transform, carried so
#: its fitted coefficient can be compared with the shipped constant.
FEATS = ("pitches", "inn_br", "runs", "onbase", "margin", "inn_run_off")
CACHE = "/tmp/midinning_rows.json"


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
            rows += [r for r in boundary.decisions(g) if not r["ends_inning"]]
        except Exception:
            continue
        if (i + 1) % 500 == 0:
            print(f"    {i+1}/{len(gids)} games, {len(rows):,} decisions",
                  flush=True)
    for r in rows:
        r["inn_run_off"] = sim.inning_run_offset(r.get("inn_runs", 0) or 0)
    if limit is None:
        json.dump(rows, open(CACHE, "w"))
    return rows


def main(argv):
    rows = collect(rebuild="--rebuild" in argv)
    for r in rows:
        r.setdefault("inn_run_off",
                     sim.inning_run_offset(r.get("inn_runs", 0) or 0))
    print(f"\n  {len(rows):,} MID-INNING decisions (inning alive, starter in)")
    print(f"  pull rate {st.mean(r['removed'] for r in rows):.4f}")

    X = np.array([[float(r[f]) for f in FEATS] for r in rows])
    y = np.array([1 if r["removed"] else 0 for r in rows])
    m = LogisticRegression(max_iter=5000, C=1e6)
    m.fit(X, y)
    coef = dict(zip(FEATS, m.coef_[0]))
    const = float(m.intercept_[0])
    p = m.predict_proba(X)[:, 1]
    print(f"  in-sample AUC {removal.auc(y, p):.4f}   "
          f"log loss {removal.log_loss(y, p):.4f}")

    cur = sim.Hook()
    # mid_intercept held at its shipped value; the offset takes the rest.
    late_mid_offset = const - cur.mid_intercept
    print(f"\n  {'parameter':<26}{'shipped':>11}{'fitted':>11}")
    out = {
        "late_mid_offset": late_mid_offset,
        "late_mid_per_pitch": coef["pitches"],
        "late_mid_per_inning_br": coef["inn_br"],
        "late_mid_per_run": coef["runs"],
        "late_mid_per_onbase": coef["onbase"],
        "mid_per_margin": coef["margin"],
    }
    for k, v in out.items():
        print(f"  {k:<26}{getattr(cur, k):>11.4f}{v:>11.4f}")
    print(f"  {'mid_per_inning_run':<26}{cur.mid_per_inning_run:>11.4f}"
          f"{coef['inn_run_off']:>11.4f}   <- COUNTED; fitted shown only "
          f"for comparison")
    print(f"  {'mid_intercept (held)':<26}{cur.mid_intercept:>11.4f}"
          f"{cur.mid_intercept:>11.4f}")

    fitted = sim.Hook(**{**out, "mid_per_inning_run": cur.mid_per_inning_run})
    print(f"\n  HAZARD BY PITCH COUNT")
    print(f"  {'bucket':<12}{'n':>8}{'actual':>9}{'shipped':>9}{'fitted':>9}")
    lo = 0
    for hi in (60, 70, 80, 90, 100, 999):
        g = [r for r in rows if lo <= r["pitches"] < hi]
        if len(g) >= 200:
            act = sum(1 for r in g if r["removed"]) / len(g)

            def mp(h):
                return st.mean(
                    h.mid_removal_p(r["pitches"], r["runs"], r["onbase"],
                                    0.0, r["margin"],
                                    inning_runs=r.get("inn_runs", 0) or 0,
                                    inning=r["inning"],
                                    inning_br=r.get("inn_br", 0) or 0)
                    for r in g)
            print(f"  {f'{lo}-{hi}':<12}{len(g):>8}{act:>9.4f}"
                  f"{mp(cur):>9.4f}{mp(fitted):>9.4f}")
        lo = hi
    print("\n  " + json.dumps({k: round(v, 5) for k, v in out.items()}))


if __name__ == "__main__":
    main(sys.argv[1:])
