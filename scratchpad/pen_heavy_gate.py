"""Is `pen_heavy_1` real on the mid-inning curve? One season, then four.

    venv/bin/python -m scratchpad.pen_heavy_gate [SEASON ...]

QUESTION    `pen_heavy_1` — relievers who threw a HEAVY workload in the
            club's last game — measured -1.9 on the boundary curve and
            -3.0 on the mid-inning one (day seventeen, part six), with the
            pre-registered sign correct. It was never wired and, unlike
            `pen_back2` and `pen_rest`, NEVER PUT THROUGH THE FOUR-SEASON
            STABILITY GATE. The 8/8 gate in the notes covers those two only.

HYPOTHESIS  If it is availability rather than noise, the sign holds
            negative season by season: a pen whose arms were worked hard
            last night keeps the starter out there.

TEST        Coefficient and z on the mid-inning curve, conditional on every
            other shipped term, fitted WITHIN one season at a time. Reported
            for whatever seasons are asked for; a pass on one season is a
            screen and not a gate.

TRAIN ROWS ONLY within each season.
"""
from __future__ import annotations

import json
import sys

import numpy as np

from src.context import sim
from scratchpad.pen_state import build
from scratchpad.pitch_hazard import HOLDOUT_CUT, ROWS, other_terms


def fit(rows, col):
    """One-column logistic offset by Newton steps, on the shipped base."""
    h = sim.Hook()
    base = np.array([
        h.mid_intercept + h.late_mid_offset
        + h.late_mid_per_pitch * r["pitches"]
        + (h.high_pitch_mid
           if r["pitches"] >= h.high_pitch_threshold else 0.0)
        + other_terms(r, boundary=False) for r in rows])
    x = np.array([float(r[col]) for r in rows])
    x = x - x.mean()
    y = np.array([1.0 if r["removed"] else 0.0 for r in rows])
    b, c = 0.0, 0.0
    for _ in range(60):
        p = 1 / (1 + np.exp(-np.clip(base + c + b * x, -30, 30)))
        w = p * (1 - p)
        g = np.array([(y - p).sum(), ((y - p) * x).sum()])
        H = np.array([[w.sum(), (w * x).sum()],
                      [(w * x).sum(), (w * x * x).sum()]])
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        c += step[0]
        b += step[1]
        if abs(step[1]) < 1e-10:
            break
    se = float(np.sqrt(np.linalg.inv(H)[1, 1]))
    return b, se, b / se, len(rows)


def main(argv):
    seasons = [int(a) for a in argv if a.isdigit()] or [2025]
    feats = build()
    rows = json.load(open(ROWS))
    kept = []
    for r in rows:
        f = feats.get((r["game_id"], r["side"]))
        if not f:
            continue
        r.update(f)
        kept.append(r)
    mid = [r for r in kept if not r.get("ends_inning")]
    print(f"  {len(mid):,} mid-inning decisions with bullpen features\n")
    print(f"  {'season':<9}{'n':>10}{'coef':>10}{'se':>9}{'z':>8}  verdict")
    for yr in seasons:
        sub = [r for r in mid
               if (r.get("date") or "").startswith(str(yr))
               and (r.get("date") or "") < HOLDOUT_CUT]
        if len(sub) < 5000:
            print(f"  {yr:<9}{len(sub):>10,}   thin")
            continue
        b, se, z, n = fit(sub, "pen_heavy_1")
        v = ("holds" if z <= -2 else
             "weak" if z < 0 else "WRONG SIGN")
        print(f"  {yr:<9}{n:>10,}{b:>+10.4f}{se:>9.4f}{z:>+8.1f}  {v}")
    # HARNESS CHECK. The recorded -3.0 was a POOLED fit with every pen
    # column in together. If this harness cannot reproduce something like
    # it on the pooled sample, the per-season nulls are mine and not the
    # data's. CLAUDE.md rule 11.
    pooled = [r for r in mid if (r.get("date") or "") < HOLDOUT_CUT]
    for col in ("pen_heavy_1", "pen_back2", "pen_rest"):
        b, se, z, n = fit(pooled, col)
        print(f"  {'POOLED':<9}{n:>10,}{b:>+10.4f}{se:>9.4f}{z:>+8.1f}"
              f"  {col}")


if __name__ == "__main__":
    main(sys.argv[1:])
