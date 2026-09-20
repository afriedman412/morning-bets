"""Is the simulated MARGIN distribution right? A runline settles on it.

    venv/bin/python -m scratchpad.margin_cal [n_sims]

A moneyline needs only P(win). A -1.5 needs the model to know how often a
win is by two or more, which is a SHAPE question about the margin and has
never been checked here. The recorded run-shape defect (reality has more
shutouts AND more blowups) does not translate into an obvious direction,
because a margin is a DIFFERENCE of two totals and the errors can cancel.

Holdout by construction, same as `shape.py`: rates and league frozen
before the cutoff, only games on or after it scored.
"""
from __future__ import annotations

import multiprocessing as mp
import random
import statistics as st
import sys
from collections import Counter

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src
from src import db

HOLDOUT = "2026-07-01"
_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 40


def _one(args):
    i, gid = args
    v = _CASES[gid]
    home = next(x for x in v if x[0]["is_home"])
    away = next(x for x in v if not x[0]["is_home"])
    an = cal.adjust_lineup(away[2], False)
    hn = cal.adjust_lineup(home[2], True)
    c = Counter()
    for draw in range(_SIMS):
        rng = random.Random(7 + i * 100003 + draw)
        A = game.build_side(away[1],
                            _PENS.get((away[0]["team"] or "").upper(), []),
                            hn, sim.Hook(), rng, team=away[0]["team"])
        H = game.build_side(home[1],
                            _PENS.get((home[0]["team"] or "").upper(), []),
                            an, sim.Hook(), rng, team=home[0]["team"])
        r = game.simulate_game(A, H, _LG, rng)
        c[r.home - r.away] += 1
    return gid, c


def main(argv):
    global _CASES, _PENS, _LG, _SIMS
    _SIMS = int(argv[0]) if argv and not argv[0].startswith("-") else 40
    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    gids = sorted(pairs)
    _CASES = {g: pairs[g] for g in gids}
    _LG = sim.league(before=HOLDOUT)
    _PENS = rate_src.bullpens(_LG, before=HOLDOUT)

    # ACTUAL margins for exactly these games — same population, or the
    # comparison is against a different slate.
    with db.connect() as c:
        real = {r["game_id"]: r["home_score"] - r["away_score"]
                for r in c.execute(
                    "select game_id, home_score, away_score from games "
                    "where sport='mlb' and status='Final' and date >= ?",
                    (HOLDOUT,))
                if r["home_score"] is not None}
    used = [g for g in gids if g in real]
    print(f"  holdout {HOLDOUT}+, {len(used)} games, {_SIMS} sims each")
    n = len(used)
    print(f"  POWER: se on a share is ~{(0.25 / n) ** 0.5:.4f}"
          f"  -> resolves {3 * (0.25 / n) ** 0.5:.3f} at 3 sigma\n")

    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, (mp.cpu_count() or 2) - 1)) as pool:
        got = dict(pool.map(_one, list(enumerate(gids))))

    sm = Counter()
    for g in used:
        sm.update(got[g])
    tot = sum(sm.values())
    rm = [real[g] for g in used]

    def share(pred, c, t):
        return sum(v for k, v in c.items() if pred(k)) / t

    print(f"  {'':<22}{'model':>9}{'actual':>9}{'gap':>9}{'se':>8}")
    rows = [
        ("|margin| = 1", lambda k: abs(k) == 1),
        ("|margin| = 2", lambda k: abs(k) == 2),
        ("|margin| >= 2", lambda k: abs(k) >= 2),
        ("|margin| >= 3", lambda k: abs(k) >= 3),
        ("|margin| >= 5", lambda k: abs(k) >= 5),
        ("home wins", lambda k: k > 0),
        ("home wins by 2+", lambda k: k >= 2),
        ("away wins by 2+", lambda k: k <= -2),
    ]
    for label, pred in rows:
        m = share(pred, sm, tot)
        a = sum(1 for v in rm if pred(v)) / n
        se = (a * (1 - a) / n) ** 0.5
        print(f"  {label:<22}{m:>9.3f}{a:>9.3f}{m - a:>+9.3f}{se:>8.3f}")
    print(f"\n  {'mean |margin|':<22}"
          f"{st.mean(abs(k) for k in sm.elements()):>9.2f}"
          f"{st.mean(abs(v) for v in rm):>9.2f}")
    print("\n  THE RUNLINE READ: a favourite -1.5 needs 'wins by 2+'. If the")
    print("  model's |margin|>=2 is HIGH, every -1.5 it prices is too")
    print("  generous and every +1.5 too cheap.")


if __name__ == "__main__":
    main(sys.argv[1:])
