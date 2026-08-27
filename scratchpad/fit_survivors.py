"""Split the start in two: an EARLY EXIT lump, and a hook for the rest.

    venv/bin/python -m scratchpad.fit_survivors [--floor 12]

THE PROBLEM THIS IS FOR, and it is already recorded as a dead end reached
from the other direction. Real starts are BIMODAL — a manager either lets a
starter cruise toward 95 pitches or knocks him out early — and `sim.Hook`'s
docstring records that a scan over centre, scale and cap found NO
combination reaching mean 84 pitches AND median 89 AND 12.2% over 100. That
is the project's own grid-edge signature: what is missing is a mechanism,
not a constant. The missing mechanism is the second mode.

Day seven then tried to add the disaster tail INSIDE the same curves
(`early_innings`). It worked on the tail — sub-two-inning starts 0.31% ->
3.16% against a real 2.68% — and widened outs SD to 4.47 where reality is
3.99, so it ships off. This is the same target approached as a MIXTURE
instead: draw the mode first, then simulate it.

    P(early exit)          a rate, drawn once per start
    outs | early exit      sampled from what actually happens
    outs | survives        the hook, refitted on survivors alone

WHY THIS IS ALLOWED TO RESTRICT THE TRAINING ROWS when day ten measured that
restricting the boundary curve's rows makes things WORSE. That trap has a
stated limit — "fit on the restricted population only when the curve fires
only there and something else covers the rest" — and this is exactly that
case. In the mixture the hook is never EVALUATED below the floor, because
the early-exit lump covers everything down there. Population and use match,
which is what the rule actually asks for.

WHAT IS DELIBERATELY NOT ATTEMPTED: predicting WHICH starts blow up. The
user's framing, and it is right — an early exit is noise with respect to how
long a pitcher should be expected to go, so the value here is REMOVING it
from the estimate, not forecasting it. The lump is a rate and a draw.

THE FLOOR IS 12 OUTS, four innings, and it sits BELOW the band that carries
the volume: outs lines hang at 14.5-17.5, 91.2% of the settled board. So
collapsing everything under it cannot cost anything at the lines.

2025 AND 2026 ONLY — day eleven measured 2023/2024 as a different manager.
"""
from __future__ import annotations

import concurrent.futures as cf
import glob
import json
import multiprocessing as mp
import os
import statistics as st
import sys
from collections import Counter

import numpy as np
from sklearn.linear_model import LogisticRegression

from src.context import removal, sim
from scratchpad import split_boundary as sb

ERA = ("2025", "2026")
FLOOR = 12

BND = ("pitches", "runs", "br", "inning", "margin")
MID = ("pitches", "inn_br", "runs", "onbase", "margin")

OUT = "scratchpad/survivor_hook.json"


def _one(gid):
    """Decisions for one game, each tagged with how long that start lasted."""
    from src.context import boundary
    try:
        rows = boundary.decisions(gid)
        ex = boundary.exits(gid)
    except Exception:
        return []
    # Total outs the starter recorded, from the state at his last plate
    # appearance. `exits` is keyed by side and carries the inning he left in.
    total = {e["side"]: ((e["inning"] - 1) * 3 + e["outs_after"]) for e in ex}
    for r in rows:
        r["start_outs"] = total.get(r["side"])
    return [r for r in rows if r["start_outs"] is not None]


def collect():
    season = sb._seasons()
    on_disk = {os.path.basename(f).split(".")[0]
               for f in glob.glob(".cache/pbp/*.json.gz")}
    gids = [g for g, s in season.items() if s in ERA and g in on_disk]
    print(f"  {len(gids):,} games in {'/'.join(ERA)}", flush=True)
    rows = []
    with cf.ProcessPoolExecutor(
            max_workers=max(1, (os.cpu_count() or 4) - 1),
            mp_context=mp.get_context("fork")) as pool:
        for got in pool.map(_one, gids, chunksize=32):
            rows += got
    return rows


def fit(rows, feats, label):
    X = np.array([[float(r[f]) for f in feats] for r in rows])
    y = np.array([1 if r["removed"] else 0 for r in rows])
    m = LogisticRegression(max_iter=5000, C=1e6)
    m.fit(X, y)
    p = m.predict_proba(X)[:, 1]
    print(f"  {label:<22}{len(rows):>9,} rows  pull {y.mean():.4f}  "
          f"AUC {removal.auc(y, p):.4f}")
    return dict(zip(feats, m.coef_[0])), float(m.intercept_[0])


def main(argv):
    floor = FLOOR
    if "--floor" in argv:
        floor = int(argv[argv.index("--floor") + 1])
    rows = collect()

    # One row per START, to get the mixture weight and the lump's shape.
    starts = {}
    for r in rows:
        starts[(r["game_id"], r["side"])] = r["start_outs"]
    lengths = list(starts.values())
    early = [o for o in lengths if o < floor]
    p_early = len(early) / len(lengths)
    print(f"\n  {len(lengths):,} starts, floor {floor} outs")
    print(f"  early exits {len(early):,} = {p_early:.4f}")
    print(f"  mean outs   all {st.mean(lengths):.2f}   "
          f"early {st.mean(early):.2f}   "
          f"survivors {st.mean([o for o in lengths if o >= floor]):.2f}")

    dist = Counter(early)
    print(f"\n  OUTS | EARLY EXIT — the lump, sampled not modelled")
    for o in sorted(dist):
        print(f"    {o:>3} outs {dist[o]:>6,}  {dist[o]/len(early):>6.3f}")

    surv = [r for r in rows if r["start_outs"] >= floor]
    print(f"\n  REFIT ON SURVIVORS ONLY")
    bnd = [r for r in surv if r["ends_inning"]]
    mid = [r for r in surv if not r["ends_inning"]]
    cb, kb = fit(bnd, BND, "boundary (survivors)")
    cm, km = fit(mid, MID, "mid-inning (survivors)")

    cur = sim.Hook()
    center = st.mean(r["pitches"] for r in bnd)
    fields = {
        "intercept": kb + center * cb["pitches"],
        "pitch_center": center,
        "pitch_scale": 1.0 / cb["pitches"],
        "per_run": cb["runs"],
        "per_baserunner": cb["br"],
        "per_inning": cb["inning"],
        "per_margin": cb["margin"],
        "late_mid_offset": km - cur.mid_intercept,
        "late_mid_per_pitch": cm["pitches"],
        "late_mid_per_inning_br": cm["inn_br"],
        "late_mid_per_run": cm["runs"],
        "late_mid_per_onbase": cm["onbase"],
        "mid_per_margin": cm["margin"],
        # THE MIXTURE. `early_exit_floor` also SUPPRESSES the hook below
        # itself, which is what stops the two modes overlapping and
        # double-counting short starts.
        "early_exit_p": p_early,
        "early_exit_floor": floor,
    }
    print(f"\n  {'parameter':<24}{'shipped':>11}{'survivor':>11}")
    for k, v in fields.items():
        print(f"  {k:<24}{getattr(cur, k, 0.0):>11.4f}{v:>11.4f}")

    json.dump({"fields": fields,
               "early_dist": {str(k): v for k, v in dist.items()}},
              open(OUT, "w"), indent=2)
    print(f"\n  -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
