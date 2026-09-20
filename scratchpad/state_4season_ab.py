"""The four-season state table against the 2026-only one it replaces.

    venv/bin/python -m scratchpad.state_4season_ab [n_sims]

QUESTION    `STATE_MULT` was rebuilt on 748,905 plate appearances over
            2023-2026 instead of 150,275 over 2026 alone. Every channel
            sharpened and home runs came back from a null. Does the run
            distribution move toward reality, and does the level hold?

HYPOTHESIS  This is MORE DATA MEASURED THE SAME WAY, so the expectation is
            a table that says the same thing more confidently — bigger
            multipliers where the effect was real, smaller where 2026 was
            noise. The feedback loop the state table creates should
            therefore get slightly stronger and the tails slightly fatter.
            FALSIFIER: the mean drifting UP means the frequency
            normalisation broke on the new basis and the table is adding
            offence rather than moving it around.

POWER, STATED FIRST. 537 holdout games, 21,480 simulated sides an arm.
Reality is 1,074 real sides, se ~0.013 on a share and ~0.071 on the F5
mean. The model-vs-model arms are paired on seeds and sharp; the comparison
to ACTUAL is not. This can establish the direction and size of the
movement between arms. It CANNOT establish that reality is now matched, and
the shape gaps being chased are themselves only 1-2 sigma.

THE THREE ARMS ARE OFF / 2026 / 2023-2026 rather than a synthetic control,
because the 2026 table IS the control: it is the same mechanism measured on
less data, so the OFF-to-2026 step sizes the mechanism and the 2026-to-4
step sizes what the extra data bought.
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

#: The table as it shipped from 2026 alone, kept verbatim so this A/B can be
#: re-run after the constant in `sim.py` has moved on again.
TABLE_2026 = {
    (0, 0): {"k_pct": 0.9870, "bb_pct": 0.9667, "babip": 0.9773,
             "hbp_pct": 0.9565},
    (0, 1): {"k_pct": 1.0331, "bb_pct": 0.9722, "babip": 0.9865,
             "hbp_pct": 0.9047},
    (0, 2): {"k_pct": 1.0509, "bb_pct": 1.0076, "babip": 0.9848,
             "hbp_pct": 1.0061},
    (1, 0): {"k_pct": 0.9411, "babip": 1.0376, "hbp_pct": 1.1416},
    (1, 1): {"k_pct": 0.9798, "bb_pct": 1.0380, "babip": 1.0549,
             "hbp_pct": 1.0050},
    (1, 2): {"k_pct": 0.9839, "bb_pct": 1.0688, "babip": 1.0039,
             "hbp_pct": 1.0331},
    (2, 0): {"k_pct": 0.9575, "bb_pct": 0.9876, "babip": 1.0484,
             "hbp_pct": 1.0871},
    (2, 1): {"k_pct": 0.9750, "bb_pct": 1.0035, "babip": 1.0392,
             "hbp_pct": 1.1029},
    (2, 2): {"k_pct": 1.0093, "bb_pct": 1.0246, "babip": 0.9662,
             "hbp_pct": 1.0930},
    (3, 0): {"k_pct": 0.9964, "bb_pct": 0.9698, "babip": 1.0211,
             "hbp_pct": 1.0261},
    (3, 1): {"k_pct": 0.9886, "bb_pct": 0.9466, "babip": 1.0787,
             "hbp_pct": 1.0456},
    (3, 2): {"k_pct": 0.9941, "bb_pct": 0.9824, "babip": 0.9658,
             "hbp_pct": 1.0446},
}


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
                    r.away_sp.k, r.away_sp.outs, r.away_sp.hr,
                    r.away_sp.bb))
    return out


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
          f"se ~{(0.2 * 0.8 / n_side) ** 0.5:.4f} on a share, "
          f"~{2.31 / n_side ** 0.5:.3f} on the F5 mean.\n")

    arms = (("OFF", False, {}),
            ("2026", True, TABLE_2026),
            ("2023-2026", True, shipped))
    got = {}
    for name, flag, table in arms:
        _ON, _TABLE = flag, table
        with mp.get_context("fork").Pool(
                max(1, (mp.cpu_count() or 2) - 1)) as p:
            rows = [r for g in p.map(_one, list(enumerate(gids))) for r in g]
        sides = [v for r in rows for v in (r[2], r[3]) if v is not None]
        got[name] = {
            "f5_mean": st.mean(sides),
            "f5_sd": st.pstdev(sides),
            "shutout": sum(1 for v in sides if v == 0) / len(sides),
            "five_plus": sum(1 for v in sides if v >= 5) / len(sides),
            "total": st.mean(r[0] + r[1] for r in rows),
            "k": st.mean(r[4] for r in rows),
            "outs": st.mean(r[5] for r in rows),
            "hr": st.mean(r[6] for r in rows),
            "bb": st.mean(r[7] for r in rows),
        }
    print(f"  {'':<20}" + "".join(f"{a[0]:>12}" for a in arms)
          + f"{'ACTUAL':>10}")
    for label, key, actual in (
            ("F5 runs / side", "f5_mean", 2.437),
            ("  sd", "f5_sd", 2.313),
            ("  shutout share", "shutout", 0.219),
            ("  five-plus share", "five_plus", 0.176),
            ("game total", "total", None),
            ("starter K", "k", 4.84),
            ("starter BB", "bb", None),
            ("starter HR", "hr", None),
            ("starter outs", "outs", 15.82)):
        a = f"{actual:>10.3f}" if actual is not None else f"{'':>10}"
        print(f"  {label:<20}"
              + "".join(f"{got[n[0]][key]:>12.3f}" for n in arms) + a)
    print("\n  READ THE TWO STEPS SEPARATELY: OFF -> 2026 sizes the")
    print("  MECHANISM, 2026 -> 2023-2026 sizes what the extra data bought.")
    sim.USE_FIELD_STATE, sim.STATE_MULT = True, shipped


if __name__ == "__main__":
    main(sys.argv[1:])
