"""PAIRED PER-START BB CRPS, zone term off vs on — the velo precedent.

    venv/bin/python -m scratchpad.zone_paired [n_sims]

THE PRE-REGISTERED BAR, stated before the run: the zone->BB term ships
as a counted mechanism unless this check comes back WORSE at >= 2 sigma.
A flat result is the expected outcome for a term this size (0.003
bb_pct per sd against ~2 walks a start) and does not block it; a paired
improvement is confirmation. Same design as the velo term's decisive
check (velo_paired.log): holdout games, both starters, same seed both
arms — the kick is deterministic and consumes no variate, so every draw
is bit-paired and the difference has no simulation noise in it.
"""
from __future__ import annotations

import multiprocessing as mp
import random
import statistics as st
import sys
from collections import Counter

from src.context import calibrate as cal, game, sim, velo
from src.context.sources import rates as rate_src

HOLDOUT = "2026-07-01"
_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 120
TOP_BB = 12


def crps(dist: Counter, n: int, actual: int) -> float:
    c = tot = 0.0
    for v in range(TOP_BB + 1):
        c += dist.get(v, 0) / n
        tot += (c - (1.0 if v >= actual else 0.0)) ** 2
    return tot


def _one(args):
    i, gid = args
    v = _CASES[gid]
    home = next(x for x in v if x[0]["is_home"])
    away = next(x for x in v if not x[0]["is_home"])
    an = cal.adjust_lineup(away[2], False)
    hn = cal.adjust_lineup(home[2], True)
    park = None
    if cal.USE_PARK:
        d = (home[0].get("date") or "")
        park = cal.park_for(home[0].get("venue_id"),
                            int(d[:4]) if d[:4].isdigit() else None)
    dists = {arm: [Counter(), Counter()] for arm in (False, True)}
    for arm in (False, True):
        sim.USE_ZONE_BB = arm
        for draw in range(_SIMS):
            rng = random.Random(7 + i * 100003 + draw)
            A = game.build_side(away[1],
                                _PENS.get((away[0]["team"] or "").upper(),
                                          []),
                                hn, sim.Hook(), rng, team=away[0]["team"],
                                date=away[0].get("date"))
            H = game.build_side(home[1],
                                _PENS.get((home[0]["team"] or "").upper(),
                                          []),
                                an, sim.Hook(), rng, team=home[0]["team"],
                                date=home[0].get("date"))
            r = game.simulate_game(A, H, _LG, rng, park=park)
            dists[arm][0][r.away_sp.bb] += 1
            dists[arm][1][r.home_sp.bb] += 1
    out = []
    for j, act in enumerate((away[0], home[0])):
        if act.get("bb") is None:
            continue
        out.append((crps(dists[False][j], _SIMS, act["bb"]),
                    crps(dists[True][j], _SIMS, act["bb"])))
    return out


def main():
    global _SIMS
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        _SIMS = int(sys.argv[1])
    pairs = cal.paired_cases(season=2026, rates_before=HOLDOUT,
                             since=HOLDOUT)
    lg = sim.league(season=2026, before=HOLDOUT)
    pens = rate_src.bullpens(lg, before=HOLDOUT)
    _CASES.update(pairs)
    _LG.update(lg)
    _PENS.update(pens)
    print(f"{len(pairs)} holdout games x {_SIMS} draws, both starters")
    got = []
    with mp.get_context("fork").Pool(max(mp.cpu_count() - 2, 1)) as pool:
        for n, r in enumerate(pool.imap(_one,
                                        list(enumerate(sorted(pairs))),
                                        chunksize=4)):
            got.extend(r)
            if (n + 1) % 100 == 0:
                print(f"  {n + 1}/{len(pairs)}")
    diffs = [off - on for off, on in got]      # positive = term is better
    m, se = st.mean(diffs), st.pstdev(diffs) / len(diffs) ** 0.5
    print(f"\n{len(got)} starts, paired BB CRPS off-vs-on (same draws):")
    print(f"  zone term better by {m:+.5f} +/- {se:.5f}  "
          f"({m / se:+.1f} sigma)")
    print(f"  starts improved: {sum(d > 0 for d in diffs)}  "
          f"worsened: {sum(d < 0 for d in diffs)}")


if __name__ == "__main__":
    main()
