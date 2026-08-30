"""COUNT the removal hazard by pitch count, replacing the parametric term.

    venv/bin/python -m scratchpad.pitch_hazard

QUESTION    What is the real removal hazard at each pitch count, on each
            branch, conditional on everything else the hook already reads?
            Unit of observation: one real removal decision.

WHY A TABLE AND NOT ANOTHER BRANCH. The shipped pitch term is one smooth
logistic across 20 to 110 pitches, and CLAUDE.md already records that this
FORM CANNOT FIT: "A single smooth logistic cannot be bimodal: scanned over
centre 84-92, scale 6-15 and cap 105-112, no combination reaches mean 84 AND
median 89 AND 12.2% over 100." Every patch to it therefore moves mass into
the next bucket — the high-pitch branch shipped on 2026-08-29 fixed o18.5
and o20.5 and made o15.5/o16.5/o17.5 worse by about a point each. That is
whack-a-mole by construction, and one more branch is one more mole.

A counted table ends it because the buckets are INDEPENDENT: there is no
shared slope for a correction to travel along. It is also what this project
does everywhere else — `PITCH_COST`, the advancement rates and `STATE_MULT`
are all counted tables that replaced imported curves, and every one of them
found the curve was wrong.

WHAT IS AND IS NOT REPLACED. Only the PITCH BACKBONE — `intercept`,
`(pitches - pitch_center)/pitch_scale`, `per_pitch_over` and the
`high_pitch_*` branch. Everything else the hook reads (runs, baserunners,
inning, blowout, dominance, bullpen, the leash) is untouched and still
adjusts up or down from the counted baseline.

THE DOUBLE-COUNTING TRAP, AND IT IS WHY THIS IS NOT A MARGINAL RATE. The
raw pull rate in a bucket already contains the average effect of the runs
and traffic that happen to occur at that pitch count. Substituting it
directly would count those twice. So each bucket's value is SOLVED
CONDITIONAL on the other shipped terms: for every row the non-pitch part of
the shipped log-odds is computed, and the bucket intercept is the value that
makes the mean predicted probability match the observed rate. Bisection on a
monotone function, so nothing can pin at a grid edge.

TRAIN ROWS ONLY. `HOLDOUT_CUT` is applied before any fitting — the rule set
on 2026-08-29 after six constants were fitted on rows they were then scored
against.
"""
from __future__ import annotations

import json
import math

import numpy as np

from src.context import sim

ROWS = "/tmp/hook_rows.json"
HOLDOUT_CUT = "2026-07-01"

#: Edges in pitches. FINER THROUGH THE CLIFF, because that is where the
#: decision actually turns: the boundary hazard runs 0.44 at 85-90, 0.70 at
#: 90-95 and 0.91 at 95-100, so a 10-pitch bucket there would average over a
#: doubling. Smallest cell is 1,209 rows.
EDGES = (0, 25, 40, 50, 60, 70, 78, 85, 90, 95, 100, 200)


def train_only(rows):
    return [r for r in rows if r.get("date", "") < HOLDOUT_CUT]


def other_terms(r, boundary: bool) -> float:
    """The shipped log-odds MINUS the pitch backbone, for one row.

    Written out rather than obtained by zeroing fields on a `Hook`, so that
    what is being held fixed is visible and auditable. `team_offset`, the
    leash and `pen` are all left at neutral: this is a LEAGUE curve and the
    per-club and per-pitcher offsets ride on top of it exactly as before.
    """
    h = sim.Hook()
    if boundary:
        return (h.per_run * r["runs"]
                + h.per_baserunner * r["br"]
                + h.per_margin * r["margin"]
                + h.per_inning * r["inning"])
    kr = r.get("k_rate")
    dom = h.late_mid_per_k_rate * (
        (sim.K_RATE_BASELINE if kr is None else kr) - sim.K_RATE_BASELINE)
    return (h.late_mid_per_inning_br * r["inn_br"]
            + h.late_mid_per_run * r["runs"]
            + h.late_mid_per_onbase * r["onbase"]
            + h.mid_per_margin * r["margin"]
            + h.mid_per_abs_margin * abs(r["margin"])
            + dom
            + h.mid_per_inning_run * sim.inning_run_offset(r["inn_runs"]))


def solve(rows, boundary: bool) -> tuple:
    """The bucket intercept that reproduces the observed rate."""
    oth = np.array([other_terms(r, boundary) for r in rows])
    y = np.array([1.0 if r["removed"] else 0.0 for r in rows])
    target = y.mean()
    lo, hi = -14.0, 8.0
    for _ in range(120):
        mid = (lo + hi) / 2
        if (1 / (1 + np.exp(-np.clip(mid + oth, -30, 30)))).mean() < target:
            lo = mid
        else:
            hi = mid
    se = math.sqrt(max(target * (1 - target), 1e-12) / len(rows))
    return (lo + hi) / 2, se / max(target * (1 - target), 1e-9), target, len(rows)


def main():
    rows = train_only(json.load(open(ROWS)))
    print(f"{len(rows):,} TRAINING decisions (before {HOLDOUT_CUT})\n")
    out = {}
    for name, boundary in (("BOUNDARY", True), ("MID-INNING", False)):
        pop = [r for r in rows if bool(r["ends_inning"]) == boundary]
        print(f"{'=' * 68}\n{name}   {len(pop):,} rows\n{'=' * 68}")
        print(f"  {'bucket':<11}{'n':>8}{'real':>9}{'shipped':>9}"
              f"{'counted':>10}{'per season (sign check)':>28}")
        tbl = []
        for lo, hi in zip(EDGES, EDGES[1:]):
            sub = [r for r in pop if lo <= r["pitches"] < hi]
            if len(sub) < 200:
                continue
            c, se, real, n = solve(sub, boundary)
            h = sim.Hook()
            if boundary:
                shipped = np.mean([h.removal_p(int(r["pitches"]),
                                               int(r["runs"]),
                                               int(r["inning"]),
                                               int(r["br"]), 0,
                                               inning_runs=int(r["inn_runs"]))
                                   for r in sub])
            else:
                shipped = np.mean([h.mid_removal_p(int(r["pitches"]),
                                                   int(r["runs"]),
                                                   int(r["onbase"]),
                                                   float(r["inn_dmg"]), 0,
                                                   inning_runs=int(r["inn_runs"]),
                                                   inning=int(r["inning"]),
                                                   inning_br=int(r["inn_br"]),
                                                   k_rate=r.get("k_rate"))
                                   for r in sub])
            yrs = []
            for yr in ("2023", "2024", "2025"):
                s2 = [r for r in sub if r["date"][:4] == yr]
                yrs.append(f"{np.mean([1.0 if x['removed'] else 0.0 for x in s2]):.3f}"
                           if len(s2) > 80 else "  -  ")
            print(f"  {f'{lo}-{hi}':<11}{n:>8,}{real:>9.4f}{shipped:>9.4f}"
                  f"{c:>10.4f}   {' '.join(yrs):>24}")
            tbl.append((lo, round(float(c), 4)))
        out["bnd" if boundary else "mid"] = tbl
        print()
    print("PASTE INTO sim.py:")
    for k, v in out.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
