"""CROSS-VALIDATE THE COUNTED PITCH HAZARD ON THE OUTS LADDER. Four seasons.

    venv/bin/python -m scratchpad.hz_cv [n_sims]

QUESTION    The counted hazard halves the 12.5-17.5 band error and closes
            the fourth-inning over-pull. Both numbers are the 2026 fold.
            Does it hold in every season?

WHY THE BAR IS FOUR FOLDS. Day twenty measured the between-fold spread of
the baseline cell error at 0.0401 to 0.0590 — LARGER than the effect being
measured — and the pitch x inning table looked like a clear win on 2026 and
failed in 2023. One fold is not a weak version of this test; it is a coin
flip with a narrative attached.

PRE-REGISTERED. The middle band (o12.5 to o17.5) improves in ALL FOUR folds,
and the long lines (o18.5, o20.5) are expected to get WORSE — that is the
known overshoot, not a surprise. All four folds reported regardless.

NOT CROSS-VALIDATION OF A FIT. The table is COUNTED on training rows and
does not change per fold; what varies is the season it is scored on. The
holdout rule still binds: `pitch_hazard` was solved before 2026-07-01, so
the 2026 fold is genuinely unseen and 2023-2025 are not. Read the 2026
column as the clean one and the others as replication.
"""
from __future__ import annotations

import multiprocessing as mp
import random
import statistics as st
import sys

from src.context import sim

from src.context import calibrate as cal, game  # noqa: E402
from src.context.sources import rates as rate_src  # noqa: E402
from scratchpad.dispersion import perturb  # noqa: E402

FOLDS = ((2023, "2023-07-01"), (2024, "2024-07-01"),
         (2025, "2025-07-01"), (2026, "2026-07-01"))
LINES = (12.5, 14.5, 15.5, 16.5, 17.5, 18.5, 20.5)
BAND = (12.5, 14.5, 15.5, 16.5, 17.5)

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
    outs, real = [], []
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
        outs.append(r.away_sp.outs)
        outs.append(r.home_sp.outs)
    for act in (away[0], home[0]):
        if act.get("o") is not None:
            real.append(act["o"])
    return outs, real


def ladder(v):
    n = len(v)
    return {ln: sum(1 for x in v if x > ln) / n for ln in LINES}


def main(argv):
    global _CASES, _PENS, _LG, _SIMS
    _SIMS = int(argv[0]) if argv else 20
    res = {}
    for yr, cut in FOLDS:
        pairs = cal.paired_cases(season=yr, rates_before=cut, since=cut)
        gids = sorted(pairs)
        _CASES = {g: pairs[g] for g in gids}
        _LG = sim.league(season=yr, before=cut)
        _PENS = rate_src.bullpens(_LG, before=cut)
        for flag in (False, True):
            sim.USE_PITCH_HAZARD = flag
            ctx = mp.get_context("fork")
            with ctx.Pool(max(1, (mp.cpu_count() or 2) - 1)) as pool:
                got = pool.map(_one, list(enumerate(gids)))
            outs = [x for g in got for x in g[0]]
            real = [x for g in got for x in g[1]]
            m, a = ladder(outs), ladder(real)
            res[(yr, flag)] = ({ln: m[ln] - a[ln] for ln in LINES},
                               st.mean(outs), st.mean(real), len(real))
        d0, mo0, mr, n = res[(yr, False)]
        d1, mo1, _, _ = res[(yr, True)]
        b0 = sum(abs(d0[l]) for l in BAND) / len(BAND)
        b1 = sum(abs(d1[l]) for l in BAND) / len(BAND)
        print(f"  {yr}  {len(gids)} games, {n:,} real starts   band "
              f"{b0:.4f} -> {b1:.4f}   "
              f"{'IMPROVES' if b1 < b0 else 'WORSE'}")

    print("\n  MIDDLE BAND o12.5-o17.5, mean |gap|, off -> ON\n")
    print(f"  {'fold':<8}{'off':>10}{'ON':>10}{'change':>12}")
    for yr, _ in FOLDS:
        d0, *_ = res[(yr, False)]
        d1, *_ = res[(yr, True)]
        b0 = sum(abs(d0[l]) for l in BAND) / len(BAND)
        b1 = sum(abs(d1[l]) for l in BAND) / len(BAND)
        print(f"  {yr:<8}{b0:>10.4f}{b1:>10.4f}{b1 - b0:>+12.4f}")
    print("\n  LONG LINES o18.5/o20.5 (expected to get worse)\n")
    print(f"  {'fold':<8}{'off':>10}{'ON':>10}{'change':>12}")
    for yr, _ in FOLDS:
        d0, *_ = res[(yr, False)]
        d1, *_ = res[(yr, True)]
        l0 = sum(abs(d0[l]) for l in (18.5, 20.5)) / 2
        l1 = sum(abs(d1[l]) for l in (18.5, 20.5)) / 2
        print(f"  {yr:<8}{l0:>10.4f}{l1:>10.4f}{l1 - l0:>+12.4f}")
    print("\n  MEAN OUTS, model vs real\n")
    print(f"  {'fold':<8}{'off':>10}{'ON':>10}{'real':>10}")
    for yr, _ in FOLDS:
        _d0, mo0, mr, _n = res[(yr, False)]
        _d1, mo1, _, _ = res[(yr, True)]
        print(f"  {yr:<8}{mo0:>10.2f}{mo1:>10.2f}{mr:>10.2f}")


if __name__ == "__main__":
    main(sys.argv[1:])
