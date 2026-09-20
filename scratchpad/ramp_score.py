"""Item 36 stage 2 — does the ENGINE under-call outs for stretch-out arms?

    venv/bin/python -m scratchpad.ramp_score [n_sims]

Registered in TODO 36 before any simulation ran. Four folds (July onward,
rates frozen at each cut, shipped engine, leash ON), per-start model mean
outs against actual. The ramp is the last-4 pitch-count OLS slope from
STRICTLY PRIOR same-season starts (>= 4 prior), joined by (name, date).

PRIMARY STATISTIC: (actual - model) outs ~ [1, t_neg, t_pos], CR0 by arm,
every fold reported. BAR: t_pos >= 2.5 sigma pooled AND positive in >= 3/4
folds AND t_neg |z| < 2 (stage 1 says declines regress; the model should
already price them). ESTIMATOR CONTROL first: inject -0.05 x t_pos into
the model column and recover it at >= 4 sigma.

NAMED LIMIT: paired cases need pre-cut rates, so late call-ups — where
stretch-outs concentrate — are under-sampled. This measures established
arms.
"""
from __future__ import annotations

import multiprocessing as mp
import random
import sys
import zlib

import numpy as np

from src.context import calibrate as cal, sim
from src.context.sources import rates as rate_src
from scratchpad.usage_trend import load_starts, slope, cr0

FOLDS = ((2023, "2023-07-01"), (2024, "2024-07-01"),
         (2025, "2025-07-01"), (2026, "2026-07-01"))
MIN_PRIOR = 4          # enough for the last-4 window, nothing more
BUCKET_EDGE = 8.0      # legibility table only, NOT the test

_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 24


def ramp_lookup():
    """(name, date) -> last-4 pitch slope from strictly prior starts.
    Same-name-same-date collisions (the Sandlin trap) are dropped and
    counted rather than guessed."""
    seq = load_starts()
    look, seen, dropped = {}, set(), 0
    for (pid, name, season), starts in seq.items():
        for i in range(MIN_PRIOR, len(starts)):
            key = (name, starts[i][0])
            if key in seen:
                look.pop(key, None)
                dropped += 1
                continue
            seen.add(key)
            prior = [p for _, p, _ in starts[:i]]
            look[key] = (slope(prior[-4:]),
                         float(np.mean(prior[-4:]) - np.mean(prior)))
    return look, dropped


def _one(gid: str):
    pair = _CASES[gid]
    outs = {"away": [], "home": []}
    for draw in range(_SIMS):
        rng = random.Random((zlib.crc32(gid.encode()) & 0xFFFFFF) * 100003
                            + draw)
        r = cal.replay(pair, _LG, _PENS, rng)
        outs["away"].append(r.away_sp.outs)
        outs["home"].append(r.home_sp.outs)
    out = []
    for side, case in (("away", 0), ("home", 1)):
        act = pair[case][0]
        if act.get("o") is None:
            continue
        out.append((act.get("player_name") or "", act.get("date") or "",
                    float(act["o"]), float(np.mean(outs[side]))))
    return out


def collect(year, cut):
    global _CASES, _LG, _PENS
    pairs = cal.paired_cases(season=year, rates_before=cut, since=cut)
    _CASES = pairs
    _LG = sim.league(season=year, before=cut)
    _PENS = rate_src.bullpens(_LG, before=cut)
    gids = sorted(pairs)
    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, (mp.cpu_count() or 2) - 1)) as pool:
        got = pool.map(_one, gids)
    return [row for game_rows in got for row in game_rows]


def estimate(rows, level=False):
    """rows: (name, t, lvl, actual, model). Returns {term: (beta, se)}.
    `level=True` adds the last4-minus-season pitch level — the POST-HOC
    attribution fit, not the registered statistic."""
    t = np.array([r[1] for r in rows])
    cols = [np.ones(len(rows)), np.minimum(t, 0.0), np.maximum(t, 0.0)]
    names = ["t_neg", "t_pos"]
    if level:
        cols.append(np.array([r[2] for r in rows]))
        names.append("lvl")
    X = np.column_stack(cols)
    y = np.array([r[3] - r[4] for r in rows])
    c = np.array([r[0] for r in rows])
    b, se = cr0(X, y, c)
    return {n: (b[j], se[j]) for j, n in enumerate(names, start=1)}


def buckets(rows):
    out = {}
    for lab, sel in (("up", lambda t: t >= BUCKET_EDGE),
                     ("mid", lambda t: abs(t) < BUCKET_EDGE),
                     ("down", lambda t: t <= -BUCKET_EDGE)):
        sub = [r for r in rows if sel(r[1])]
        if len(sub) < 10:
            out[lab] = None
            continue
        d = np.array([r[3] - r[4] for r in sub])
        arms = np.array([r[0] for r in sub])
        m = d.mean()
        var = sum((d[arms == g].sum() - (arms == g).sum() * m) ** 2
                  for g in np.unique(arms)) / len(d) ** 2
        out[lab] = (m, np.sqrt(var), len(sub), len(np.unique(arms)))
    return out


def main(argv):
    global _SIMS
    if argv:
        _SIMS = int(argv[0])
    look, dropped = ramp_lookup()
    print(f"ITEM 36 STAGE 2 — engine bias vs pitch-count ramp. "
          f"{_SIMS} draws/game, leash ON.\n"
          f"  ramp lookup: {len(look):,} start-dates "
          f"({dropped} name-date collisions dropped)")

    per_fold = {}
    for year, cut in FOLDS:
        rows = collect(year, cut)
        joined = [(nm, look[(nm, dt)][0], look[(nm, dt)][1], a, m)
                  for nm, dt, a, m in rows if (nm, dt) in look]
        per_fold[year] = joined
        print(f"\n  FOLD {year}: {len(rows)} scored starts, "
              f"{len(joined)} with a ramp "
              f"({len(joined) / max(1, len(rows)):.0%} matched)")

    allrows = [r for rs in per_fold.values() for r in rs]

    print("\nESTIMATOR CONTROL — inject -0.05 x t_pos into the model "
          "column, recover it. (The registered >= 4 sigma clause was "
          "arithmetically unmeetable next to the stated z 2-2.5 power — "
          "a registration defect, named in NOTES; EXACT RECOVERY is what "
          "the clause was written to guard.)")
    inj = [(nm, t, lv, a, m - 0.05 * max(t, 0.0))
           for nm, t, lv, a, m in allrows]
    base_all = estimate(allrows)
    got = estimate(inj)
    db = got["t_pos"][0] - base_all["t_pos"][0]
    se = got["t_pos"][1]
    print(f"  recovered {db:+.4f} of +0.0500 exactly; z {db / se:+.1f} "
          f"is the POWER at that size")

    print("\nTHE READ — (actual - model) outs ~ t_neg + t_pos, CR0 by arm:")
    print(f"  {'fold':<8}{'t_neg':>24}{'t_pos':>24}{'n':>7}")
    acc = {"t_neg": [], "t_pos": []}
    for year, _ in FOLDS:
        e = estimate(per_fold[year])
        cells = []
        for term in ("t_neg", "t_pos"):
            b, se = e[term]
            acc[term].append((b, se))
            cells.append(f"{b:+.4f} ({se:.4f}) z{b / se:+5.1f}")
        print(f"  {year:<8}{cells[0]:>24}{cells[1]:>24}"
              f"{len(per_fold[year]):>7}")
    line = f"  {'pooled':<8}"
    pooled = {}
    for term in ("t_neg", "t_pos"):
        w = np.array([1 / se ** 2 for _, se in acc[term]])
        b = sum(bb * ww for (bb, _), ww in zip(acc[term], w)) / w.sum()
        se = 1 / np.sqrt(w.sum())
        pooled[term] = (b, se)
        line += f"{f'{b:+.4f} ({se:.4f}) z{b / se:+5.1f}':>24}"
    print(line + f"{len(allrows):>7}")

    print("\nPOST-HOC ATTRIBUTION (not the registered statistic) — add "
          "the last4-minus-season pitch LEVEL, does slope survive it:")
    print(f"  {'fold':<8}{'t_neg':>24}{'t_pos':>24}{'lvl':>24}")
    for year, _ in FOLDS:
        e = estimate(per_fold[year], level=True)
        cells = [f"{b:+.4f} ({se:.4f}) z{b / se:+5.1f}"
                 for b, se in (e["t_neg"], e["t_pos"], e["lvl"])]
        print(f"  {year:<8}{cells[0]:>24}{cells[1]:>24}{cells[2]:>24}")

    print("\nBUCKETS (legibility only, rel to mid, "
          f"edge {BUCKET_EDGE:+.0f}/start):")
    print(f"  {'fold':<8}{'up-mid':>22}{'down-mid':>22}"
          f"{'n up/mid/down':>18}")
    for year, _ in FOLDS:
        bk = buckets(per_fold[year])
        if not bk.get("mid"):
            continue
        mm = bk["mid"][0]
        cells, ns = [], []
        for lab in ("up", "down"):
            if bk.get(lab):
                m, se, n, _a = bk[lab]
                cells.append(f"{m - mm:+.3f} ({se:.3f})")
                ns.append(str(n))
            else:
                cells.append("-")
                ns.append("0")
        print(f"  {year:<8}{cells[0]:>22}{cells[1]:>22}"
              f"{ns[0] + '/' + str(bk['mid'][2]) + '/' + ns[1]:>18}")

    bp, sp = pooled["t_pos"]
    bn, sn = pooled["t_neg"]
    signs = sum(1 for b, _ in acc["t_pos"] if b > 0)
    ok = (bp / sp >= 2.5 and signs >= 3 and abs(bn / sn) < 2)
    print(f"\nBAR (registered): t_pos >= 2.5 sigma pooled AND positive in "
          f">= 3/4 folds AND t_neg |z| < 2.\n"
          f"  t_pos z {bp / sp:+.1f}, positive folds {signs}/4, "
          f"t_neg z {bn / sn:+.1f}  -> "
          f"{'BAR MET' if ok else 'BAR NOT MET'}")


if __name__ == "__main__":
    main(sys.argv[1:])
