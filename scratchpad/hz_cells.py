"""DOES THE COUNTED TABLE HIT THE REAL RATE IN ITS OWN BUCKETS?

    venv/bin/python -m scratchpad.hz_cells [n_sims] [--hz]

QUESTION    The table fixes 60-85 pitches and overshoots past 95: starters
            run long and the o18.5/o20.5 lines go the wrong way. Is that
            because its TOP BUCKETS do not reproduce the real removal rate
            in our games, or because the overshoot is elsewhere?

WHY THIS AND NOT A RE-CENTRING. Re-centring on the model's own occupancy
would make the aggregate land while leaving the input wrong, and it would
bury a measurement of how far our game states are from real ones. The
standard is real data, cell by cell: fifteen buckets, fifteen real rates,
does it hit them. A constant cannot fake that.

TEST        Bucketed on `sim.pitch_hazard`'s OWN edges, because those are
            the cells that were solved. The model's expected hazard in a
            bucket is the mean probability the curve returns over the
            decisions it actually makes there — `game.py` fires on
            `rng.random() < p`, so averaging p is the realised rate. Real
            side is HOLDOUT rows.

READ THE TOP THREE ROWS. If 90/95/100 miss LOW, the table under-pulls there
and re-counting those buckets against our states is measurement, not
patching. If they hit, the long-line overshoot is not the table's fault and
the high-pitch branch is compensating for something unidentified — which
must be found before either ships.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import random
import sys
from collections import defaultdict

from src.context import sim

from src.context import calibrate as cal, game  # noqa: E402
from src.context.sources import rates as rate_src  # noqa: E402
from scratchpad.dispersion import perturb  # noqa: E402
from scratchpad.pitch_hazard import EDGES, HOLDOUT_CUT, ROWS  # noqa: E402

HOLDOUT = "2026-07-01"
MIN_REAL = 120
_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 10
_LOG: dict = {}


def bucket(p):
    for lo, hi in zip(EDGES, EDGES[1:]):
        if lo <= p < hi:
            return lo
    return EDGES[-2]


def _wrap():
    bnd, mid = sim.Hook.removal_p, sim.Hook.mid_removal_p

    def rp(self, pitches, *a, **k):
        p = bnd(self, pitches, *a, **k)
        _LOG.setdefault("bnd", []).append((bucket(pitches), p))
        return p

    def mp_(self, pitches, *a, **k):
        p = mid(self, pitches, *a, **k)
        _LOG.setdefault("mid", []).append((bucket(pitches), p))
        return p

    sim.Hook.removal_p, sim.Hook.mid_removal_p = rp, mp_


def _one(args):
    i, gid = args
    _LOG.clear()
    _wrap()
    v = _CASES[gid]
    home = next(x for x in v if x[0]["is_home"])
    away = next(x for x in v if not x[0]["is_home"])
    an, hn = cal.adjust_lineup(away[2], False), cal.adjust_lineup(home[2], True)
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
        game.simulate_game(A, H, _LG, rng)
    out = {}
    for k, rows in _LOG.items():
        agg = defaultdict(lambda: [0.0, 0])
        for b, p in rows:
            agg[b][0] += p
            agg[b][1] += 1
        out[k] = dict(agg)
    return out


def main(argv):
    global _CASES, _PENS, _LG, _SIMS
    pos = [a for a in argv if not a.startswith("-")]
    _SIMS = int(pos[0]) if pos else 10
    sim.USE_PITCH_HAZARD = "--hz" in argv
    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    gids = sorted(pairs)
    _CASES = {g: pairs[g] for g in gids}
    _LG = sim.league(before=HOLDOUT)
    _PENS = rate_src.bullpens(_LG, before=HOLDOUT)
    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, (mp.cpu_count() or 2) - 1)) as pool:
        got = pool.map(_one, list(enumerate(gids)))
    model = {"bnd": defaultdict(lambda: [0.0, 0]),
             "mid": defaultdict(lambda: [0.0, 0])}
    for g in got:
        for k, cells in g.items():
            for b, (s, n) in cells.items():
                model[k][b][0] += s
                model[k][b][1] += n

    rows = [r for r in json.load(open(ROWS))
            if (r.get("date") or "") >= HOLDOUT_CUT]
    real = {}
    for key, sel in (("bnd", True), ("mid", False)):
        agg = defaultdict(lambda: [0, 0])
        for r in rows:
            if bool(r.get("ends_inning")) != sel:
                continue
            agg[bucket(r["pitches"])][0] += bool(r.get("removed"))
            agg[bucket(r["pitches"])][1] += 1
        real[key] = agg

    print(f"  PITCH HAZARD {'ON' if sim.USE_PITCH_HAZARD else 'OFF'}   "
          f"{len(gids)} holdout games x {_SIMS} sims\n")
    for key, lab in (("bnd", "BOUNDARY"), ("mid", "MID-INNING")):
        print(f"  {lab}")
        print(f"    {'pitches':<10}{'model':>9}{'real':>9}{'gap':>9}"
              f"{'se':>8}{'n real':>9}")
        tot, cnt = 0.0, 0
        for b in EDGES[:-1]:
            rk, rn = real[key].get(b, [0, 0])
            if rn < MIN_REAL:
                continue
            ms, mn = model[key].get(b, [0.0, 0])
            if not mn:
                continue
            m, r = ms / mn, rk / rn
            se = (max(r, 1e-6) * (1 - r) / rn) ** 0.5
            flag = "  <<" if abs(m - r) > 2 * se else ""
            tot += abs(m - r)
            cnt += 1
            print(f"    {b:<10}{m:>9.4f}{r:>9.4f}{m - r:>+9.4f}"
                  f"{se:>8.4f}{rn:>9,}{flag}")
        print(f"    mean |gap| over {cnt} buckets: {tot / max(cnt, 1):.4f}\n")


if __name__ == "__main__":
    main(sys.argv[1:])
