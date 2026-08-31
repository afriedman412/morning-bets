"""WHERE IN THE GAME ARE THE EXTRA MID-INNING EXITS? Model against real.

    venv/bin/python -m scratchpad.mid_by_inning [n_sims]

The model pulls starters mid-inning on 43.4% of starts against a real 40.4%
(`scratchpad/bnd_truth.py`, read off the removal EVENT and not the out
count). This asks where the extra three points sit.

BOTH SIDES BY THE EVENT. The model reports `pulled_mid_inning` directly;
the real side reads `boundary.exits`, which reads the removal out of the
play-by-play. The out-count rule is not used anywhere here — it mislabels
7.8% of real starts and would put the excess in the wrong inning.

DENOMINATOR: all starts. A cell is "this share of starts ended with a
mid-inning pull in inning N", so the columns sum to the mid share and the
comparison is of one distribution against another rather than of six
independent rates.

HOLDOUT ONLY, rates frozen before it, shipped hook.
"""
from __future__ import annotations

import multiprocessing as mp
import random
import sys
from collections import Counter

from src import roster
from src.context import boundary, calibrate as cal, game, sim
from src.context.sources import rates as rate_src
from scratchpad.dispersion import perturb

HOLDOUT = "2026-07-01"
_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 20


def _one(args):
    i, gid = args
    v = _CASES[gid]
    home = next(x for x in v if x[0]["is_home"])
    away = next(x for x in v if not x[0]["is_home"])
    an, hn = cal.adjust_lineup(away[2], False), cal.adjust_lineup(home[2], True)
    cells = Counter()
    n = 0
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
        for sp in (r.away_sp, r.home_sp):
            n += 1
            if sp.pulled_mid_inning:
                cells[min(sp.innings_completed + 1, 9)] += 1
    return cells, n


def main(argv):
    global _CASES, _PENS, _LG, _SIMS
    _SIMS = int(argv[0]) if argv else 20
    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    gids = sorted(pairs)
    _CASES = {g: pairs[g] for g in gids}
    _LG = sim.league(before=HOLDOUT)
    _PENS = rate_src.bullpens(_LG, before=HOLDOUT)

    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, (mp.cpu_count() or 2) - 1)) as pool:
        got = pool.map(_one, list(enumerate(gids)))
    mcell, mn = Counter(), 0
    for c, n in got:
        mcell.update(c)
        mn += n

    rcell, rn = Counter(), 0
    for gid in gids:
        try:
            ex = {e.get("pitcher"): e for e in boundary.exits(gid)}
        except Exception:
            continue
        for act, _r, _l in pairs[gid]:
            e = ex.get(roster.player_id(act.get("player_name")))
            if not e:
                continue
            rn += 1
            if e.get("kind") == "mid":
                rcell[min(e.get("inning") or 1, 9)] += 1

    print(f"  {mn:,} simulated starts, {rn:,} real starts (holdout "
          f"{HOLDOUT}+)\n")
    print(f"  mid-inning exits as a share of ALL starts, by inning\n")
    print(f"  {'inning':<9}{'model':>9}{'real':>9}{'gap':>9}{'se':>8}")
    tm = tr = 0.0
    for i in range(1, 10):
        m, r = mcell[i] / mn, rcell[i] / rn
        tm += m
        tr += r
        se = (max(r, 1e-6) * (1 - r) / rn) ** 0.5
        flag = "  <<" if abs(m - r) > 2 * se else ""
        print(f"  {i:<9}{m:>9.3f}{r:>9.3f}{m - r:>+9.3f}{se:>8.3f}{flag}")
    print(f"  {'TOTAL':<9}{tm:>9.3f}{tr:>9.3f}{tm - tr:>+9.3f}")


if __name__ == "__main__":
    main(sys.argv[1:])
