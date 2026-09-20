"""The simulator's pitches-per-out by pitcher K rate, against reality's.

    venv/bin/python -m scratchpad.pitch_cost_sim [n_sims]

QUESTION    Reality says a strikeout pitcher and a contact pitcher need the
            SAME pitches to record 18 outs — 98.2 to 101.1 across K
            quintiles, non-monotonic (`scratchpad/pitch_cost_spread.py`,
            73,506 pitcher-games). The extra pitches a strikeout costs are
            exactly repaid by needing fewer batters: outs per plate
            appearance climbs 0.690 -> 0.721 across the same quintiles.
            Does the SIMULATOR reproduce that cancellation?

WHY IT DECIDES ITEM 7. `PITCH_COST` is exonerated as a constant — its
flatness matches reality's flatness. But the simulator's selection still
runs backwards at the hook (mean-of-ratios k_rate 0.2002 against a real
0.2276). If the cancellation fails HERE, the cause is that the model's
outs-per-plate-appearance does not rise with strikeout rate as fast as
reality's does, and the pitch budget is a SYMPTOM of that rather than the
disease.

HYPOTHESIS  The simulator's pitches-per-out RISES with K rate where
            reality's is flat, because its high-K arms do not convert their
            strikeouts into the batter-count saving that pays for them.
            FALSIFIER: the simulated column is as flat as reality's, which
            would clear this channel too and send item 7 to the hook's
            boundary curve — the one input that took no in-game state in
            either fit today.

BUCKETED ON THE PITCHER'S MODELLED RATE, not on the realised start, so the
grouping variable cannot contain the outcome. That is the same leave-one-out
discipline the real-side table used.
"""
from __future__ import annotations

import multiprocessing as mp
import random
import sys

import numpy as np

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src

HOLDOUT = "2026-07-01"
_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 12

#: Reality, from `pitch_cost_spread.py`. Carried here so the comparison is
#: on one screen rather than across two runs.
REAL = [("Q1", 0.186, 0.690, 5.454), ("Q2", 0.217, 0.697, 5.513),
        ("Q3", 0.228, 0.701, 5.504), ("Q4", 0.253, 0.703, 5.616),
        ("Q5", 0.296, 0.721, 5.527)]


def _one(args):
    i, gid = args
    v = _CASES[gid]
    home = next(x for x in v if x[0]["is_home"])
    away = next(x for x in v if not x[0]["is_home"])
    an = cal.adjust_lineup(away[2], False)
    hn = cal.adjust_lineup(home[2], True)
    out = []
    for draw in range(_SIMS):
        rng = random.Random(7 + i * 100003 + draw)
        A = game.build_side(away[1],
                            _PENS.get((away[0]["team"] or "").upper(), []),
                            hn, sim.Hook(), rng, team=away[0]["team"])
        H = game.build_side(home[1],
                            _PENS.get((home[0]["team"] or "").upper(), []),
                            an, sim.Hook(), rng, team=home[0]["team"])
        r = game.simulate_game(A, H, _LG, rng)
        for rates, sp in ((away[1], r.away_sp), (home[1], r.home_sp)):
            out.append({"k_pct": float(getattr(rates, "k_pct", 0.0) or 0.0),
                        "k": sp.k, "bf": sp.batters, "outs": sp.outs,
                        "pitches": sp.pitches})
    return out


def main(argv):
    global _CASES, _PENS, _LG, _SIMS
    _SIMS = int(argv[0]) if argv else 12
    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    gids = sorted(pairs)
    _CASES = {g: pairs[g] for g in gids}
    _LG = sim.league(before=HOLDOUT)
    _PENS = rate_src.bullpens(_LG, before=HOLDOUT)
    with mp.get_context("fork").Pool(max(1, (mp.cpu_count() or 2) - 1)) as p:
        rows = [r for g in p.map(_one, list(enumerate(gids))) for r in g]
    rows = [r for r in rows if r["k_pct"] > 0 and r["bf"] > 0]
    print(f"  {len(rows):,} simulated starts, {len(gids)} games x {_SIMS}\n")

    kp = np.array([r["k_pct"] for r in rows])
    cuts = np.percentile(kp, [20, 40, 60, 80])
    bounds = [-1] + list(cuts) + [2]
    print(f"  {'quintile':<10}{'K rate':>9}{'outs/PA':>10}"
          f"{'pitches/out':>13}{'to 18 outs':>13}"
          f"{'| REAL outs/PA':>16}{'p/out':>9}{'to 18':>8}")
    for i in range(5):
        sub = [r for r in rows if bounds[i] < r["k_pct"] <= bounds[i + 1]]
        if not sub:
            continue
        bf = sum(r["bf"] for r in sub)
        o = sum(r["outs"] for r in sub)
        pi = sum(r["pitches"] for r in sub)
        k = sum(r["k"] for r in sub)
        _, rk, ro, rp = REAL[i]
        print(f"  {f'Q{i + 1}':<10}{k / bf:>9.3f}{o / bf:>10.3f}"
              f"{pi / o:>13.3f}{pi / o * 18:>13.1f}"
              f"{ro:>16.3f}{rp:>9.3f}{rp * 18:>8.1f}")

    print(f"\n  READ THE outs/PA COLUMN FIRST. It is the cancellation: if it "
          f"climbs\n  with K rate as fast as reality's does, the extra "
          f"pitches a strikeout\n  costs are repaid and pitches-per-out "
          f"stays flat.")


if __name__ == "__main__":
    main(sys.argv[1:])
