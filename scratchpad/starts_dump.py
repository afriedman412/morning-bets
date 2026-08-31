"""SIMULATE THE HOLDOUT ONCE AND KEEP THE STARTS. Everything else is a query.

    venv/bin/python -m scratchpad.starts_dump [n_sims] [OUT.json]

Every question asked on day twenty cost its own simulation run — the outs
ladder, the by-inning exit profile, the boundary share by two rules, the
cell hazards. They are all functions of the SAME draws and none of the
harnesses kept them: `shape.py` folds into Counters, `mid_by_inning.py`
recomputes exit innings and saves nothing.

This writes one row per simulated start:

    outs, k, pitches, exit inning, pulled mid-inning, runs allowed,
    plus the real outs/k for the same start so paired questions work.

`scratchpad/starts_query.py` reads it. Adding a new question should not
mean re-running the engine.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import random
import sys

from src.context import calibrate as cal, game, sim
from src.context.sources import rates as rate_src
from scratchpad.dispersion import perturb

HOLDOUT = "2026-07-01"
DEFAULT_OUT = "scratchpad/starts_holdout.json"
_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 40


def _one(args):
    i, gid = args
    v = _CASES[gid]
    home = next(x for x in v if x[0]["is_home"])
    away = next(x for x in v if not x[0]["is_home"])
    an, hn = cal.adjust_lineup(away[2], False), cal.adjust_lineup(home[2], True)
    out = []
    for draw in range(_SIMS):
        rng = random.Random(7 + i * 100003 + draw)
        za, zh = rng.gauss(0, 1), rng.gauss(0, 1)
        A = game.build_side(perturb(away[1], za, 0.0),
                            _PENS.get((away[0]["team"] or "").upper(), []),
                            hn, sim.Hook(), rng, team=away[0]["team"],
                            date=away[0].get("date"))
        H = game.build_side(perturb(home[1], zh, 0.0),
                            _PENS.get((home[0]["team"] or "").upper(), []),
                            an, sim.Hook(), rng, team=home[0]["team"],
                            date=home[0].get("date"))
        r = game.simulate_game(A, H, _LG, rng)
        for act, sp in ((away[0], r.away_sp), (home[0], r.home_sp)):
            out.append([
                act.get("player_name"), gid, draw,
                sp.outs, sp.k, round(sp.pitches, 1),
                sp.innings_completed + (1 if sp.pulled_mid_inning else 0),
                1 if sp.pulled_mid_inning else 0, sp.runs,
                act.get("o"), act.get("k"),
            ])
    return out


COLS = ("pitcher", "game_id", "draw", "outs", "k", "pitches",
        "exit_inning", "mid", "runs", "real_outs", "real_k")


def main(argv):
    global _CASES, _PENS, _LG, _SIMS
    pos = [a for a in argv if not a.startswith("-")]
    _SIMS = int(pos[0]) if pos else 40
    out_path = pos[1] if len(pos) > 1 else DEFAULT_OUT
    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    gids = sorted(pairs)
    _CASES = {g: pairs[g] for g in gids}
    _LG = sim.league(before=HOLDOUT)
    _PENS = rate_src.bullpens(_LG, before=HOLDOUT)
    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, (mp.cpu_count() or 2) - 1)) as pool:
        got = pool.map(_one, list(enumerate(gids)))
    rows = [r for g in got for r in g]
    with open(out_path, "w") as f:
        json.dump({"cols": COLS, "holdout": HOLDOUT, "sims": _SIMS,
                   "games": len(gids), "rows": rows}, f)
    print(f"  {len(gids)} games x {_SIMS} sims -> {len(rows):,} simulated "
          f"starts")
    print(f"  wrote {out_path}")


if __name__ == "__main__":
    main(sys.argv[1:])
