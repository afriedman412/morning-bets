"""CROSS-VALIDATE THE PITCH x INNING TABLE ACROSS FOUR SEASONS.

    venv/bin/python -m scratchpad.pxi_cv [n_sims]

QUESTION    Does the interaction improve cell-level fidelity in EVERY
            season, and is the uniform mid-inning offset a property of our
            simulator or of one stretch of games?

HYPOTHESIS  Real baseball replicates. If the boundary curve's cell error
            falls in all four folds the mechanism is real; if the +0.0185
            mid offset appears in all four it is ours and correcting it is
            bookkeeping; if it appears in one it was that sample and the
            "it is just a constant" reading dies.

TEST        Fold = July onward of one season. The table is REFITTED on
            every row outside the fold, so no fold is scored against a
            table that saw it. Simulate the fold, record the hazard each
            curve returns, compare against the real rate in the same cells.

ALL FOUR FOLDS ARE REPORTED. Choosing among them after the fact is the
failure this design exists to prevent, and with a change this marginal it
would find something every time.

NOT A CHANGE TO `HOLDOUT_CUT`. The shipped cutoff stays 2026-07-01 — one
cutoff for the project, per CLAUDE.md. This is a robustness check that
lives in the scratchpad.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import random
import sys
from collections import defaultdict

import numpy as np

from src.context import calibrate as cal, game, sim
from src.context.sources import rates as rate_src
from scratchpad.dispersion import perturb
from scratchpad.pitch_hazard import ROWS
from scratchpad.pxi import SHIP_FROM, band, base_logodds, inn_group, solve

FOLDS = ((2023, "2023-07-01"), (2024, "2024-07-01"),
         (2025, "2025-07-01"), (2026, "2026-07-01"))
MIN_CELL = 300
MIN_REAL = 150

_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 10
_LOG: dict = {}


def fit(rows, boundary):
    cells = {}
    for r in rows:
        b = band(r["pitches"])
        if b < SHIP_FROM:
            continue
        cells.setdefault((b, inn_group(r["inning"])), []).append(r)
    got = {k: solve(v, boundary) for k, v in cells.items()
           if len(v) >= MIN_CELL}
    tot = sum(v[3] for v in got.values())
    mean = sum(v[0] * v[3] for v in got.values()) / tot
    return {k: round(v[0] - mean, 4) for k, v in got.items()}


def _wrap():
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
        out[k] = dict(agg)
    return out


def run_fold(gids):
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
    return model


def real_cells(rows):
    out = {}
    for key, sel in (("bnd", True), ("mid", False)):
        agg = defaultdict(lambda: [0, 0])
        for r in rows:
            if bool(r.get("ends_inning")) != sel:
                continue
            agg[(band(r["pitches"]), inn_group(r["inning"]))][0] += \
                bool(r.get("removed"))
            agg[(band(r["pitches"]), inn_group(r["inning"]))][1] += 1
        out[key] = agg
    return out


def score(model, real):
    out = {}
    for key in ("bnd", "mid"):
        gaps = []
        for c, (rk, rn) in real[key].items():
            if c[0] < SHIP_FROM or rn < MIN_REAL:
                continue
            ms, mn = model[key].get(c, [0.0, 0])
            if not mn:
                continue
            gaps.append(ms / mn - rk / rn)
        if gaps:
            a = np.array(gaps)
            out[key] = (float(np.abs(a).mean()), float(a.mean()), len(gaps))
    return out


def main(argv):
    global _CASES, _PENS, _LG, _SIMS
    _SIMS = int(argv[0]) if argv else 10
    allrows = json.load(open(ROWS))
    print(f"  {len(allrows):,} decisions, {len(FOLDS)} folds, "
          f"{_SIMS} sims per game. Table REFIT per fold.\n")
    res = {}
    for yr, cut in FOLDS:
        infold = [r for r in allrows
                  if (r.get("date") or "") >= cut
                  and (r.get("date") or "")[:4] == str(yr)]
        outfold = [r for r in allrows if r not in ()
                   and not ((r.get("date") or "") >= cut
                            and (r.get("date") or "")[:4] == str(yr))]
        sim.PXI_BND = fit([r for r in outfold if r.get("ends_inning")], True)
        sim.PXI_MID = fit([r for r in outfold if not r.get("ends_inning")],
                          False)
        pairs = cal.paired_cases(season=yr, rates_before=cut, since=cut)
        gids = sorted(pairs)
        _CASES = {g: pairs[g] for g in gids}
        _LG = sim.league(season=yr, before=cut)
        _PENS = rate_src.bullpens(_LG, before=cut)
        real = real_cells(infold)
        print(f"  FOLD {yr}  ({len(gids)} games, {len(infold):,} real "
              f"decisions, table refit on {len(outfold):,})")
        for flag in (False, True):
            sim.USE_PITCH_X_INNING = flag
            s = score(run_fold(gids), real)
            res[(yr, flag)] = s
            tag = "ON " if flag else "off"
            for key in ("bnd", "mid"):
                if key in s:
                    a, m, n = s[key]
                    print(f"    {tag} {key}   mean|gap| {a:.4f}   "
                          f"signed {m:+.4f}   ({n} cells)")
        print()
    print("  SUMMARY — mean|gap|, off -> ON, every fold reported\n")
    print(f"  {'fold':<8}{'boundary':>22}{'mid-inning':>24}")
    for yr, _ in FOLDS:
        o, n = res.get((yr, False), {}), res.get((yr, True), {})
        b = (f"{o['bnd'][0]:.4f} -> {n['bnd'][0]:.4f}"
             if 'bnd' in o and 'bnd' in n else "-")
        m = (f"{o['mid'][0]:.4f} -> {n['mid'][0]:.4f}"
             if 'mid' in o and 'mid' in n else "-")
        print(f"  {yr:<8}{b:>22}{m:>24}")
    print(f"\n  {'fold':<8}{'mid SIGNED, off -> ON':>34}")
    for yr, _ in FOLDS:
        o, n = res.get((yr, False), {}), res.get((yr, True), {})
        if 'mid' in o and 'mid' in n:
            print(f"  {yr:<8}{o['mid'][1]:>+17.4f}{n['mid'][1]:>+17.4f}")


if __name__ == "__main__":
    main(sys.argv[1:])
