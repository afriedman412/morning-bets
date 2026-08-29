"""A THIRD HOOK BRANCH for high pitch counts, counted on real decisions.

    venv/bin/python -m scratchpad.late_branch [threshold]

QUESTION    Does the SHIPPED hook under-pull starters at high pitch counts,
            and by how much on each of its two branches? Unit of
            observation: one real starter removal decision. The quantity is
            a log-odds OFFSET to be applied above a pitch threshold.

WHY A THIRD BRANCH AND NOT A REFIT. CLAUDE.md records that refitting the
WHOLE boundary curve on late rows makes the simulation worse — mean outs
16.49 -> 16.74 — because that curve is evaluated at every pitch count and
calibrating it on late rows alone makes it under-pull early. The rule it
states is: "Fit on the restricted population only when the curve fires only
there and SOMETHING ELSE COVERS THE REST." A branch gated above a pitch
threshold, with the existing curves unchanged below it, is exactly that
configuration. It is also the same shape as the `early_innings` branch that
already exists at the other end of the start.

HYPOTHESIS  The shipped curves under-pull above ~90 pitches on BOTH
            branches, and by more on the boundary than mid-inning. Evidence
            that motivated it, from a learned logistic on holdout rows:
            boundary 95+ predicted 0.775 against a real 0.931, mid-inning
            0.249 against 0.329.
            PREDICTED CONSEQUENCE IN THE SIMULATION: fewer very long starts
            (the model over-produces them, o18.5 +0.035 and o20.5 +0.024),
            and a HIGHER boundary share, since the boundary correction is
            the larger of the two and therefore tilts exits toward the ends
            of innings.
            FALSIFIER: the shipped curves are already calibrated above the
            threshold, i.e. the offsets come out inside their own standard
            error. That would mean the learned model's miss is a property of
            the logistic and not of what ships, and this item dies.

TEST        Every real decision is scored through the SHIPPED `sim.Hook` —
            not through a refitted logistic — so the miss being measured is
            the one that actually ships. Predicted against observed pull
            rate, by pitch count, on each branch separately.

            THE LEASH IS OFF for this. `sim.for_start` adds a per-pitcher
            offset, and a population-level calibration that included it
            would be measuring the league curve plus a pitcher mix. The
            offsets are therefore corrections to the LEAGUE curve, which is
            what they are applied to.

            NAME THE DENOMINATOR: the pull rate here is PER DECISION — per
            plate appearance for the mid-inning branch and per completed
            inning for the boundary branch. These are different
            denominators and are never pooled.
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np

from src.context import sim

#: NEVER FIT ON ROWS THAT WILL BE SCORED ON. Same cutoff `shape.py` and
#: `fitf5` evaluate from — one cutoff for the whole project, because two is
#: how one of them drifts. See CLAUDE.md; this was got wrong on 2026-08-29.
HOLDOUT_CUT = "2026-07-01"


def train_only(rows):
    """Rows strictly before the holdout. Call it before ANY fit."""
    return [r for r in rows if r.get("date", "") < HOLDOUT_CUT]

ROWS = "/tmp/hook_rows.json"


def predicted(r, boundary: bool) -> float:
    """The SHIPPED hook's probability for one real decision row."""
    h = sim.Hook()
    if boundary:
        return h.removal_p(int(r["pitches"]), int(r["runs"]),
                           int(r["inning"]), int(r["br"]),
                           int(r["margin"]), inning_runs=int(r["inn_runs"]))
    return h.mid_removal_p(int(r["pitches"]), int(r["runs"]),
                           int(r["onbase"]), float(r["inn_dmg"]),
                           int(r["margin"]), inning_runs=int(r["inn_runs"]),
                           inning=int(r["inning"]),
                           inning_br=int(r["inn_br"]),
                           k_rate=r.get("k_rate"))


def offset(rows, boundary: bool) -> tuple:
    """One log-odds shift that equates predicted to observed on these rows.

    Solved rather than searched: the shift is the value that makes the mean
    predicted probability match the observed rate, found by bisection on a
    monotone function. No grid, so it cannot pin at an edge.
    """
    p = np.array([predicted(r, boundary) for r in rows])
    y = np.array([1.0 if r["removed"] else 0.0 for r in rows])
    target = y.mean()
    lo, hi = -3.0, 3.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lg = np.log(np.clip(p, 1e-9, 1 - 1e-9) / (1 - np.clip(p, 1e-9, 1 - 1e-9)))
        got = (1 / (1 + np.exp(-(lg + mid)))).mean()
        if got < target:
            lo = mid
        else:
            hi = mid
    # se on the observed rate -> se on the offset, via the logit slope.
    se_rate = math.sqrt(target * (1 - target) / len(rows))
    slope = target * (1 - target)
    return (lo + hi) / 2, se_rate / max(slope, 1e-9), p.mean(), target, len(rows)


def main(argv):
    thr = int(argv[0]) if argv else 90
    rows = json.load(open(ROWS))
    rows = train_only(rows)   # THE GUARD, ACTUALLY CALLED
    for name, boundary in (("BOUNDARY", True), ("MID-INNING", False)):
        pop = [r for r in rows if bool(r["ends_inning"]) == boundary]
        print(f"\n{'=' * 62}\n{name}   {len(pop):,} real decisions\n{'=' * 62}")
        print(f"  {'pitches':<12}{'n':>8}{'shipped':>10}{'actual':>9}"
              f"{'ratio':>8}")
        for lo, hi in ((0, 60), (60, 75), (75, 90), (90, 100), (100, 130)):
            sub = [r for r in pop if lo <= r["pitches"] < hi]
            if len(sub) < 100:
                continue
            p = np.mean([predicted(r, boundary) for r in sub])
            a = np.mean([1.0 if r["removed"] else 0.0 for r in sub])
            print(f"  {f'{lo}-{hi}':<12}{len(sub):>8,}{p:>10.4f}{a:>9.4f}"
                  f"{p / max(a, 1e-9):>8.2f}")
        late = [r for r in pop if r["pitches"] >= thr]
        off, se, pm, am, n = offset(late, boundary)
        print(f"\n  ABOVE {thr} PITCHES: n {n:,}  shipped {pm:.4f}  "
              f"actual {am:.4f}")
        print(f"  OFFSET {off:+.4f} +/- {se:.4f}   "
              f"({'REAL' if abs(off) > 3 * se else 'inside noise'})")
        # STABILITY GATE. A correction that does not repeat is not one.
        print("  per season:")
        for yr in ("2023", "2024", "2025", "2026"):
            sub = [r for r in late if r["date"][:4] == yr]
            if len(sub) < 300:
                continue
            o, s, _, _, k = offset(sub, boundary)
            print(f"    {yr}  n {k:>6,}  offset {o:>+8.4f} +/- {s:.4f}")


if __name__ == "__main__":
    main(sys.argv[1:])
