"""F5 TEAM TOTAL calibration on a holdout — the stated product.

    venv/bin/python -m scratchpad.f5_cal [n_sims]

`fitf5` reports a CRPS that is only comparable to another CRPS. This asks
the operator's question instead: when the model says a side scores over
N.5 in the first five, how often does it? Same holdout construction as
`shape.py` — rates and league frozen before the cutoff.

Actual F5 comes from the final scores through five, taken off play-by-play
rather than from the boxscore, because the boxscore has no inning splits.
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
from src.context.sources import pbp

HOLDOUT = "2026-07-01"
LINES = (0.5, 1.5, 2.5, 3.5, 4.5)
_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 40


def _actual_f5(short):
    """(away team score, home team score) through five. None if unusable."""
    try:
        d = pbp.fetch(short)
        if not d:
            return None
        a = h = 0
        for play, _b, _o, ra, rh in pbp.plays(short, d):
            ab = play.get("about") or {}
            if (ab.get("inning") or 99) <= 5:
                a, h = ra, rh
        return a, h
    except Exception:
        return None


def _one(args):
    i, gid = args
    v = _CASES[gid]
    home = next(x for x in v if x[0]["is_home"])
    away = next(x for x in v if not x[0]["is_home"])
    an = cal.adjust_lineup(away[2], False)
    hn = cal.adjust_lineup(home[2], True)
    a_side, h_side = [], []
    for draw in range(_SIMS):
        rng = random.Random(7 + i * 100003 + draw)
        A = game.build_side(away[1],
                            _PENS.get((away[0]["team"] or "").upper(), []),
                            hn, sim.Hook(), rng, team=away[0]["team"])
        H = game.build_side(home[1],
                            _PENS.get((home[0]["team"] or "").upper(), []),
                            an, sim.Hook(), rng, team=home[0]["team"])
        r = game.simulate_game(A, H, _LG, rng, track=(5,), stop_after=5)
        if 5 in r.prefix_side:
            av, hv = r.prefix_side[5]
            a_side.append(av)
            h_side.append(hv)
    return gid, a_side, h_side


def main(argv):
    global _CASES, _PENS, _LG, _SIMS
    _SIMS = int(argv[0]) if argv else 40
    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    gids = sorted(pairs)
    _CASES = {g: pairs[g] for g in gids}
    _LG = sim.league(before=HOLDOUT)
    _PENS = rate_src.bullpens(_LG, before=HOLDOUT)

    shorts = [g.split("-")[-1] for g in gids]
    with mp.get_context("fork").Pool(8) as pool:
        acts = pool.map(_actual_f5, shorts)
    real = {g: a for g, a in zip(gids, acts) if a}
    used = [g for g in gids if g in real]

    with mp.get_context("fork").Pool(max(1, (mp.cpu_count() or 2) - 1)) as p:
        got = {g: (a, h) for g, a, h in
               p.map(_one, list(enumerate(gids)))}

    sides_m, sides_a = [], []
    for g in used:
        a, h = got[g]
        if not a:
            continue
        sides_m.append(a)
        sides_a.append(real[g][0])
        sides_m.append(h)
        sides_a.append(real[g][1])
    n = len(sides_a)
    print(f"  holdout {HOLDOUT}+, {len(used)} games / {n} team-sides, "
          f"{_SIMS} sims each")
    print(f"  POWER: se on a share ~{(0.25 / n) ** 0.5:.4f}, "
          f"se on the mean ~{st.pstdev(sides_a) / n ** 0.5:.3f}\n")
    flat = [v for s in sides_m for v in s]
    print(f"  {'':<16}{'model':>9}{'actual':>9}{'gap':>9}")
    print(f"  {'mean F5 runs':<16}{st.mean(flat):>9.3f}"
          f"{st.mean(sides_a):>9.3f}{st.mean(flat) - st.mean(sides_a):>+9.3f}")
    print(f"  {'sd':<16}{st.pstdev(flat):>9.3f}{st.pstdev(sides_a):>9.3f}"
          f"{st.pstdev(flat) - st.pstdev(sides_a):>+9.3f}")
    print(f"\n  {'line':<8}{'model':>9}{'actual':>9}{'gap':>9}{'se':>8}")
    for ln in LINES:
        m = st.mean(sum(1 for v in s if v > ln) / len(s) for s in sides_m)
        a = sum(1 for v in sides_a if v > ln) / n
        print(f"  o{ln:<7}{m:>9.3f}{a:>9.3f}{m - a:>+9.3f}"
              f"{(a * (1 - a) / n) ** 0.5:>8.3f}")
    print(f"\n  {'runs':<8}{'model':>9}{'actual':>9}{'gap':>9}")
    ra = Counter(sides_a)
    fm = Counter(flat)
    tot = sum(fm.values())
    for v in range(0, 8):
        print(f"  {v:<8}{fm[v] / tot:>9.3f}{ra[v] / n:>9.3f}"
              f"{fm[v] / tot - ra[v] / n:>+9.3f}")
    crps = st.mean(
        sum((sum(1 for x in s if x <= v) / len(s) - (1.0 if v >= a else 0.0)) ** 2
            for v in range(0, 16))
        for s, a in zip(sides_m, sides_a))
    print(f"\n  discrete CRPS (full support): {crps:.4f}")


if __name__ == "__main__":
    main(sys.argv[1:])
