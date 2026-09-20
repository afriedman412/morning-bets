"""DOES THE MODEL HIT THE REAL PULL RATE IN EVERY SQUARE? Scored on holdout.

    venv/bin/python -m scratchpad.pxi_cells [n_sims] [--pxi]

QUESTION    With `PXI_*` on, does the simulator reproduce the real removal
            hazard CELL BY CELL — 70 pitches in the fourth, 95 in the sixth
            — rather than merely on an aggregate a constant could fake?

HYPOTHESIS  Hitting the cells while the aggregate drifts means the drift is
            a centring artifact and correcting it is honest bookkeeping.
            MISSING the cells means the table is not the problem and our
            game STATES are, which is the clustering defect and no centring
            saves it.

TEST        The model's expected hazard in a cell is the MEAN PROBABILITY
            the hook returns over the decisions it actually makes there —
            `game.py` fires on `rng.random() < p`, so averaging p is the
            realised rate without needing the draws. Both hooks wrapped.
            Real side is HOLDOUT rows (date >= HOLDOUT_CUT), which the
            table was never fitted on.

WHAT THIS CANNOT SEE, stated so the number is not over-read: pulls that
bypass the curves — `hard_pitch_cap` and the early-exit mixture. The cap
fires rarely and the mixture is off at `early_exit_p = 0.0`, so the gap is
small, but it is not zero and the model's true rate is slightly ABOVE what
is printed.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import random
import sys
from collections import defaultdict

from src.context import calibrate as cal, game, sim
from src.context.sources import rates as rate_src
from scratchpad.dispersion import perturb
from scratchpad.pitch_hazard import HOLDOUT_CUT, ROWS
from scratchpad.pxi import SHIP_FROM, band, inn_group

HOLDOUT = "2026-07-01"
_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 10
_LOG: dict = {}


def _wrap():
    """Record (cell, p) for every decision the two curves are asked for."""
    bnd, mid = sim.Hook.removal_p, sim.Hook.mid_removal_p

    def rp(self, pitches, runs, innings, *a, **k):
        p = bnd(self, pitches, runs, innings, *a, **k)
        _LOG.setdefault("bnd", []).append(
            (band(pitches), inn_group(innings), p))
        return p

    def mp_(self, pitches, runs, on_base, *a, **k):
        p = mid(self, pitches, runs, on_base, *a, **k)
        _LOG.setdefault("mid", []).append(
            (band(pitches), inn_group(k.get("inning", 0)), p))
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
        for b, g, p in rows:
            agg[(b, g)][0] += p
            agg[(b, g)][1] += 1
        out[k] = {c: (v2[0], v2[1]) for c, v2 in agg.items()}
    return out


def real_cells():
    rows = [r for r in json.load(open(ROWS))
            if (r.get("date") or "") >= HOLDOUT_CUT]
    out = {}
    for key, sel in (("bnd", True), ("mid", False)):
        agg = defaultdict(lambda: [0, 0])
        for r in rows:
            if bool(r.get("ends_inning")) != sel:
                continue
            c = (band(r["pitches"]), inn_group(r["inning"]))
            agg[c][0] += bool(r.get("removed"))
            agg[c][1] += 1
        out[key] = agg
    return out


def main(argv):
    global _CASES, _PENS, _LG, _SIMS
    pos = [a for a in argv if not a.startswith("-")]
    _SIMS = int(pos[0]) if pos else 10
    sim.USE_PITCH_X_INNING = "--pxi" in argv
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
            for c, (s, n) in cells.items():
                model[k][c][0] += s
                model[k][c][1] += n
    real = real_cells()

    print(f"  PXI {'ON' if sim.USE_PITCH_X_INNING else 'OFF'}   "
          f"{len(gids)} holdout games x {_SIMS} sims   real side is "
          f"HOLDOUT rows only\n")
    for key, lab in (("bnd", "BOUNDARY"), ("mid", "MID-INNING")):
        print(f"  {lab}")
        print(f"    {'cell':<16}{'model':>9}{'real':>9}{'gap':>9}"
              f"{'se':>8}{'n real':>9}")
        tot = 0.0
        cells = sorted(c for c in real[key]
                       if c[0] >= SHIP_FROM and real[key][c][1] >= 150)
        for c in cells:
            rk, rn = real[key][c]
            r = rk / rn
            ms, mn = model[key].get(c, [0.0, 0])
            if not mn:
                continue
            m = ms / mn
            se = (max(r, 1e-6) * (1 - r) / rn) ** 0.5
            flag = "  <<" if abs(m - r) > 2 * se else ""
            tot += abs(m - r)
            print(f"    {str(c):<16}{m:>9.4f}{r:>9.4f}{m - r:>+9.4f}"
                  f"{se:>8.4f}{rn:>9,}{flag}")
        print(f"    mean |gap| over {len(cells)} cells: "
              f"{tot / max(len(cells), 1):.4f}\n")


if __name__ == "__main__":
    main(sys.argv[1:])
