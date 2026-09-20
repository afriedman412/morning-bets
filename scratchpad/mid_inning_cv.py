"""IS THE BY-INNING MID-EXIT PROFILE THE SAME IN EVERY SEASON?

    venv/bin/python -m scratchpad.mid_inning_cv [n_sims]

QUESTION    The model pulls starters mid-inning more than real managers do
            in all four seasons (+0.029 / +0.018 / +0.012 / +0.006, and
            note 2026 is the MILDEST). On 2026 that excess sits in innings
            3-5 with a SHORTFALL in the sixth. Is that shape the same
            everywhere, or is it one season's?

HYPOTHESIS  If it is the hook, it replicates. If the profile moves, then
            "we get twitchy in the fourth" is a 2026 fact and a fix aimed
            at the middle innings would be aimed at the wrong innings in
            three seasons out of four.

TEST        Model against real, mid-inning starter exits by inning as a
            share of ALL starts, on July onward of each season. Both sides
            by the removal EVENT — the model reports `pulled_mid_inning`,
            the real side reads `boundary.exits` out of the play-by-play.
            The `outs % 3` rule is not used; it mislabels 7.8% of real
            starts and would put the excess in the wrong inning.

NO FITTING HERE, so there is no fold to hold out — this is a description of
a defect, measured four times.
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

FOLDS = ((2023, "2023-07-01"), (2024, "2024-07-01"),
         (2025, "2025-07-01"), (2026, "2026-07-01"))
_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 10


def _one(args):
    i, gid = args
    v = _CASES[gid]
    home = next(x for x in v if x[0]["is_home"])
    away = next(x for x in v if not x[0]["is_home"])
    an, hn = cal.adjust_lineup(away[2], False), cal.adjust_lineup(home[2], True)
    cells, n = Counter(), 0
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
    _SIMS = int(argv[0]) if argv else 10
    rows = {}
    for yr, cut in FOLDS:
        pairs = cal.paired_cases(season=yr, rates_before=cut, since=cut)
        gids = sorted(pairs)
        _CASES = {g: pairs[g] for g in gids}
        _LG = sim.league(season=yr, before=cut)
        _PENS = rate_src.bullpens(_LG, before=cut)
        ctx = mp.get_context("fork")
        with ctx.Pool(max(1, (mp.cpu_count() or 2) - 1)) as pool:
            got = pool.map(_one, list(enumerate(gids)))
        mc, mn = Counter(), 0
        for c, n in got:
            mc.update(c)
            mn += n
        rc, rn, miss = Counter(), 0, 0
        for gid in gids:
            try:
                ex = {e.get("pitcher"): e for e in boundary.exits(gid)}
            except Exception:
                miss += 1
                continue
            for act, _r, _l in pairs[gid]:
                e = ex.get(roster.player_id(act.get("player_name")))
                if not e:
                    continue
                rn += 1
                if e.get("kind") == "mid":
                    rc[min(e.get("inning") or 1, 9)] += 1
        rows[yr] = (mc, mn, rc, rn, len(gids), miss)
        print(f"  {yr}: {len(gids)} games, {mn:,} simulated / {rn:,} real "
              f"starts matched{f', {miss} without pbp' if miss else ''}")

    print("\n  MID-INNING EXITS AS A SHARE OF ALL STARTS, BY INNING")
    print("  gap = model minus real; positive means WE pull more\n")
    hdr = "".join(f"{yr:>16}" for yr, _ in FOLDS)
    print(f"  {'inning':<8}{hdr}")
    for i in range(2, 9):
        cs = []
        for yr, _ in FOLDS:
            mc, mn, rc, rn, _g, _m = rows[yr]
            m, r = mc[i] / mn, (rc[i] / rn if rn else 0)
            se = (max(r, 1e-6) * (1 - r) / max(rn, 1)) ** 0.5
            star = "*" if abs(m - r) > 2 * se else " "
            cs.append(f"{m - r:>+15.3f}{star}")
        print(f"  {i:<8}" + "".join(cs))
    cs = []
    for yr, _ in FOLDS:
        mc, mn, rc, rn, _g, _m = rows[yr]
        cs.append(f"{sum(mc.values())/mn - sum(rc.values())/rn:>+15.3f} ")
    print(f"  {'TOTAL':<8}" + "".join(cs))
    print("\n  and the REAL profile, for reference\n")
    print(f"  {'inning':<8}{hdr}")
    for i in range(2, 9):
        cs = []
        for yr, _ in FOLDS:
            _mc, _mn, rc, rn, _g, _m = rows[yr]
            cs.append(f"{rc[i]/rn:>16.3f}")
        print(f"  {i:<8}" + "".join(cs))


if __name__ == "__main__":
    main(sys.argv[1:])
