"""The field-state A/B, scored on its PRE-REGISTERED falsifier.

    venv/bin/python -m scratchpad.state_ab [n_sims]

QUESTION    Does populating `sim.STATE_MULT` move the simulated run
            distribution's SHAPE toward reality? Quantity: F5 runs allowed
            per team-side and the share of sides at 0 and at 5+.
            Population: 537 holdout games, rates frozen before the cutoff.
            Unit of observation: one team-side.

HYPOTHESIS  The table creates a FEEDBACK LOOP — a baserunner improves the
            next plate appearance, which produces more baserunners — so it
            should fatten BOTH tails while the mean holds.
            FALSIFIER: mean up with flat tails means the multipliers do not
            average to one over the state distribution and this is just
            added offence. SECONDARY: if only the upper tail moves it is a
            level error, not clustering.

POWER, STATED FIRST AND WORSE THAN IT LOOKS. The model-vs-model arms are
paired on seeds and sharp — ~21,500 simulated sides each. Comparing to
REALITY is bound by 1,074 real sides, se ~0.013 on a share, and the gap
being chased is itself only ~1.6 sigma (15.8% five-plus against an actual
17.6%). So this can establish the DIRECTION AND SIZE of the movement and
cannot establish that reality is now matched. Both are reported and they
are not the same claim.

POSITIVE CONTROL: a third arm with the table amplified 3x away from
neutral. A mis-specified wiring and a real-but-small effect produce
identical output, and only the control separates them.
"""
from __future__ import annotations

import multiprocessing as mp
import random
import statistics as st
import sys

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src

HOLDOUT = "2026-07-01"
_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 20
_TABLE: dict = {}
_ON = True


def _one(args):
    i, gid = args
    sim.USE_FIELD_STATE = _ON
    sim.STATE_MULT = _TABLE
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
        r = game.simulate_game(A, H, _LG, rng, track=(5, 9))
        f5 = r.prefix_side.get(5)
        out.append((r.away, r.home,
                    f5[0] if f5 else None, f5[1] if f5 else None,
                    r.away_sp.k, r.away_sp.outs,
                    max(r.prefix) if r.prefix else 9))
    return out


def _amplify(table, factor):
    """Push every multiplier `factor` times further from 1.0."""
    return {c: {k: 1.0 + (v - 1.0) * factor for k, v in m.items()}
            for c, m in table.items()}


def main(argv):
    global _CASES, _PENS, _LG, _SIMS, _ON, _TABLE
    _SIMS = int(argv[0]) if argv else 20
    shipped = dict(sim.STATE_MULT)
    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    gids = sorted(pairs)
    _CASES = {g: pairs[g] for g in gids}
    _LG = sim.league(before=HOLDOUT)
    _PENS = rate_src.bullpens(_LG, before=HOLDOUT)
    n_side = 2 * len(gids)
    print(f"  {len(gids)} games x {_SIMS} sims  "
          f"({len(gids) * _SIMS * 2:,} simulated sides per arm)")
    print(f"  POWER: actual side is {n_side:,} real team-sides, "
          f"se ~{(0.2 * 0.8 / n_side) ** 0.5:.4f} on a share.")
    print(f"  The five-plus gap being chased is ~1.6 sigma to begin with.\n")

    arms = (("OFF", False, {}),
            ("ON", True, shipped),
            ("CONTROL x3", True, _amplify(shipped, 3.0)))
    got = {}
    for name, flag, table in arms:
        _ON, _TABLE = flag, table
        with mp.get_context("fork").Pool(max(1, (mp.cpu_count() or 2) - 1)) as p:
            rows = [r for g in p.map(_one, list(enumerate(gids))) for r in g]
        sides = [v for r in rows for v in (r[2], r[3]) if v is not None]
        got[name] = {
            "f5_mean": st.mean(sides),
            "f5_sd": st.pstdev(sides),
            "shutout": sum(1 for v in sides if v == 0) / len(sides),
            "five_plus": sum(1 for v in sides if v >= 5) / len(sides),
            "total": st.mean(r[0] + r[1] for r in rows),
            "tie9": sum(1 for r in rows if r[6] > 9) / len(rows),
            "k": st.mean(r[4] for r in rows),
            "outs": st.mean(r[5] for r in rows),
        }
    print(f"  {'':<20}" + "".join(f"{a[0]:>12}" for a in arms)
          + f"{'ACTUAL':>10}")
    for label, key, actual in (
            ("F5 runs / side", "f5_mean", 2.437),
            ("  sd", "f5_sd", 2.313),
            ("  shutout share", "shutout", 0.219),
            ("  five-plus share", "five_plus", 0.176),
            ("game total", "total", None),
            ("share past nine", "tie9", 0.083),
            ("starter K", "k", 4.84),
            ("starter outs", "outs", 15.82)):
        a = f"{actual:>10.3f}" if actual is not None else f"{'':>10}"
        print(f"  {label:<20}"
              + "".join(f"{got[n[0]][key]:>12.3f}" for n in arms) + a)
    sim.USE_FIELD_STATE, sim.STATE_MULT = True, shipped


if __name__ == "__main__":
    main(sys.argv[1:])
