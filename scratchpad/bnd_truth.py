"""THE MODEL'S BOUNDARY SHARE, BY THE EVENT AND NOT BY THE OUT COUNT.

    venv/bin/python -m scratchpad.bnd_truth [n_sims]

`shape.py` infers boundary from `outs % 3 == 0`, and on the holdout that
rule disagrees with the play-by-play removal event on 7.2% of real starts —
always the same way, because a starter who comes out for one more inning and
is chased before recording an out has an out count that still divides by
three (`scratchpad/bnd_rulers.py`). Real: 0.674 by the out count, 0.596 by
the event.

The simulator does not have to be inferred: `StartResult.pulled_mid_inning`
is the decision itself. This reports both rules on the model so the gap can
be read under a ruler that means the same thing on both sides.
"""
from __future__ import annotations

import multiprocessing as mp
import random
import statistics as st
import sys

from src.context import calibrate as cal, game, sim
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
    mid_flags, div3 = [], []
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
            mid_flags.append(1.0 if sp.pulled_mid_inning else 0.0)
            div3.append(1.0 if sp.outs % 3 == 0 else 0.0)
    return mid_flags, div3


def main(argv):
    global _CASES, _PENS, _LG, _SIMS
    pos = [a for a in argv if not a.startswith("-")]
    _SIMS = int(pos[0]) if pos else 20
    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    gids = sorted(pairs)
    _CASES = {g: pairs[g] for g in gids}
    _LG = sim.league(before=HOLDOUT)
    _PENS = rate_src.bullpens(_LG, before=HOLDOUT)
    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, (mp.cpu_count() or 2) - 1)) as pool:
        got = pool.map(_one, list(enumerate(gids)))
    mid = [v for g in got for v in g[0]]
    d3 = [v for g in got for v in g[1]]
    n_real = 2 * len(gids)
    print(f"  {len(gids)} holdout games, {_SIMS} sims each "
          f"({len(mid):,} simulated starts)\n")
    print(f"  {'':<34}{'model':>9}{'real':>9}{'gap':>9}")
    print(f"  {'boundary share, OUT-COUNT rule':<34}"
          f"{st.mean(d3):>9.3f}{0.674:>9.3f}{st.mean(d3) - 0.674:>+9.3f}")
    print(f"  {'boundary share, EVENT rule':<34}"
          f"{1 - st.mean(mid):>9.3f}{0.596:>9.3f}"
          f"{(1 - st.mean(mid)) - 0.596:>+9.3f}")
    se = (0.6 * 0.4 / n_real) ** 0.5
    print(f"\n  se on the real side ~{se:.4f} (n={n_real} real starts)")
    print(f"  out-count rule mislabels {st.mean(d3) - (1 - st.mean(mid)):.3f} "
          f"of MODEL starts; on real starts it is 0.078.")


if __name__ == "__main__":
    main(sys.argv[1:])
