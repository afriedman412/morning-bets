"""Does a per-start DISPERSION term close the shape gap?

    venv/bin/python -m scratchpad.dispersion [n_sims]

THE DIAGNOSIS IT FOLLOWS FROM (`scratchpad/f5_decomp.py`): the model puts
exactly the right men on base (+0.0%), every event channel is inside 1.4%,
and it is 1.7% short on runs. The shape says why — reality has MORE shutouts
AND MORE blowups, and the model is bunched in the middle. Both tails thin at
once is clustering: plate appearances are resolved independently and real
ones arrive in bunches.

THE MECHANISM. One latent draw per start, scaling the pitcher's four rates
in the directions that travel together on a bad night: strikeouts down,
walks, home runs and contact up. It is NOT a prediction — nothing here knows
which start blows up, and it does not need to. It needs the right RATE of
blowups.

WHY THIS IS NOT `form.py`, WHICH IS PARKED. That asked whether nightly form
is PREDICTABLE IN ADVANCE and answered no, three ways. This asks whether the
model GENERATES ENOUGH BAD NIGHTS, which an unpredictable term answers just
as well. The dead list records HOW a thing was tried: form was tried as a
predictor. It has never been tried as a dispersion.

MEAN-PRESERVING ON THE RATES, NOT ON RUNS — and that is the point. Runs are
CONVEX in the rates, so a symmetric spread on the inputs RAISES mean runs.
If the shape gap and the level gap are one defect, one sigma should close
both at once. If sigma has to be pushed past what closes the shape in order
to close the level, they are two defects and this is the wrong fix.
"""
from __future__ import annotations

import math
import random
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

from dataclasses import replace

from src.context import fitf5, game, sim
from src.context.sources import rates as rate_src
from scratchpad.f5_decomp import actual_f5

#: How the four rates move together on a bad night, as multiples of the
#: latent draw. Signs are not fitted — they are which way a pitcher who does
#: not have it is worse. The magnitudes are equal because nothing measured
#: says otherwise and inventing a shape would be fitting.
LOAD = {"k_pct": -1.0, "bb_pct": 1.0, "hr_pct": 1.0, "babip": 1.0}


def perturb(p: sim.PitcherRates, z: float, sigma: float) -> sim.PitcherRates:
    """One start's latent quality, applied multiplicatively."""
    if not sigma:
        return p
    return replace(
        p,
        k_pct=p.k_pct * math.exp(LOAD["k_pct"] * sigma * z),
        bb_pct=p.bb_pct * math.exp(LOAD["bb_pct"] * sigma * z),
        hr_pct=p.hr_pct * math.exp(LOAD["hr_pct"] * sigma * z),
        babip=min(0.6, p.babip * math.exp(LOAD["babip"] * sigma * z)))


def main(argv):
    n_sims = int(argv[0]) if argv else 30
    lg = sim.league()
    cases = fitf5.side_cases()
    by_game = defaultdict(dict)
    for c in cases:
        by_game[c["game_id"]][("home" if c["is_home"] else "away")] = c
    gids = [g for g, v in by_game.items() if len(v) == 2]
    shorts = [g.split("-")[-1] for g in gids]
    act = {}
    with ProcessPoolExecutor(max_workers=8) as ex:
        for g, got in zip(gids, ex.map(actual_f5, shorts, chunksize=32)):
            if got and "away" in got and "home" in got:
                act[g] = got
    print(f"  {len(act):,} games, {n_sims} sims\n", flush=True)

    act_hist = defaultdict(int)
    act_runs = n_act = 0
    for g in act:
        for tag in ("away", "home"):
            a = act[g][tag]
            act_hist[min(a.get("runs", 0), 6)] += 1
            act_runs += a.get("runs", 0)
            n_act += 1
    ad = sum(act_hist.values())
    a_pct = {k: 100 * v / ad for k, v in act_hist.items()}

    pens = rate_src.bullpens(lg)
    print(f"  {'sigma':>7}{'mean runs':>11}{'vs actual':>11}"
          f"{'P(0)':>8}{'P(6+)':>8}{'shape err':>11}")
    print(f"  {'actual':>7}{act_runs / n_act:>11.4f}{'':>11}"
          f"{a_pct.get(0, 0):>8.2f}{a_pct.get(6, 0):>8.2f}{'':>11}")
    for sigma in (0.0, 0.10, 0.15, 0.20, 0.25, 0.30):
        hist = defaultdict(int)
        tot = n = 0
        for g in sorted(act):
            away, home = by_game[g]["away"], by_game[g]["home"]
            rng = random.Random(away["seed"])
            for _ in range(n_sims):
                za, zh = rng.gauss(0, 1), rng.gauss(0, 1)
                A = game.build_side(
                    perturb(away["pitcher"], za, sigma),
                    pens.get((away["team"] or "").upper(), []),
                    away["lineup"], None, rng)
                H = game.build_side(
                    perturb(home["pitcher"], zh, sigma),
                    pens.get((home["team"] or "").upper(), []),
                    home["lineup"], None, rng)
                game.simulate_game(A, H, lg, rng, stop_after=5)
                for sd in (A, H):
                    hist[min(sd.line.runs, 6)] += 1
                    tot += sd.line.runs
                    n += 1
        s_pct = {k: 100 * v / n for k, v in hist.items()}
        # Total absolute deviation across the seven buckets: one number for
        # "is the SHAPE right", which the mean cannot say.
        err = sum(abs(s_pct.get(k, 0) - a_pct.get(k, 0)) for k in range(7))
        gap = tot / n - act_runs / n_act
        print(f"  {sigma:>7.2f}{tot / n:>11.4f}{gap:>+11.4f}"
              f"{s_pct.get(0, 0):>8.2f}{s_pct.get(6, 0):>8.2f}{err:>11.2f}")
    print("\n  `shape err` is total absolute deviation over the seven run")
    print("  buckets. If one sigma minimises it AND zeroes the mean gap,")
    print("  the shape and level defects are the same thing.")


if __name__ == "__main__":
    main(sys.argv[1:])
