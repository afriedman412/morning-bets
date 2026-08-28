"""Does the simulator now reproduce EXTRA INNINGS? Counted against 2026.

    venv/bin/python -m scratchpad.extras_cal [n_sims]

THE MEAN TOTAL IS THE WRONG TEST and reading it first cost a confused
minute. The automatic runner adds runs per half-inning AND ends games
sooner, so the two effects largely cancel on a game total. What it must get
right is the SHAPE of extras:

    how often a game goes past nine
    how long those games run
    how much a single extra half-inning scores

Real 2026, counted off the `games` line scores: 8.3%, 10.34 innings, 1.049
runs per extra half against a regulation 0.498.
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
_AUTO = True


def _one(args):
    i, gid = args
    game.USE_AUTO_RUNNER = _AUTO
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
        # `track` every inning nine and past, so runs after regulation are
        # readable. Inning 9 is NOT recorded when the home team leads after
        # the top of the ninth — the loop breaks first — but such a game
        # never reaches extras, so it cannot land in this sample.
        r = game.simulate_game(A, H, _LG, rng, track=tuple(range(9, 19)))
        tot = r.away + r.home
        through9 = r.prefix.get(9)
        if through9 is None:
            out.append((9, 0, 0))
            continue
        # `_track` now fires on EVERY exit path, so the last inning played
        # is genuinely the last key present. Before 2026-08-29 the deciding
        # inning was missing and this read one inning short on exactly the
        # games that ended on a walk-off — the highest-scoring ones.
        played = max(r.prefix)
        out.append((played, tot - through9, max(played - 9, 0)))
    return out


def main(argv):
    global _CASES, _PENS, _LG, _SIMS, _AUTO
    _SIMS = int(argv[0]) if argv and not argv[0].startswith("-") else 20
    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    gids = sorted(pairs)
    _CASES = {g: pairs[g] for g in gids}
    _LG = sim.league(before=HOLDOUT)
    _PENS = rate_src.bullpens(_LG, before=HOLDOUT)
    print(f"  {len(gids)} games x {_SIMS} sims\n")
    print(f"  {'':<22}{'auto OFF':>10}{'auto ON':>10}{'ACTUAL':>10}")
    got = {}
    for flag in (False, True):
        _AUTO = flag
        with mp.get_context("fork").Pool(max(1, (mp.cpu_count() or 2) - 1)) as p:
            rows = [r for g in p.map(_one, list(enumerate(gids))) for r in g]
        ex = [r for r in rows if r[0] > 9]
        got[flag] = {
            "share": len(ex) / len(rows),
            "innings": st.mean(r[0] for r in ex) if ex else 0.0,
            # Two halves an inning, and the bottom is not always played;
            # this is runs per EXTRA INNING, halved to compare like for like.
            "per_half": (sum(r[1] for r in ex)
                         / max(sum(r[2] for r in ex) * 2, 1)) if ex else 0.0,
        }
    for label, key, actual, fmt in (
            ("share past nine", "share", 0.083, "{:>10.3f}"),
            ("mean innings then", "innings", 10.34, "{:>10.2f}"),
            ("runs per extra half", "per_half", 1.049, "{:>10.3f}")):
        print(f"  {label:<22}" + fmt.format(got[False][key])
              + fmt.format(got[True][key]) + fmt.format(actual))
    game.USE_AUTO_RUNNER = True


if __name__ == "__main__":
    main(sys.argv[1:])
