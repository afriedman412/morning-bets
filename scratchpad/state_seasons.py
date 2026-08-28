"""The field-state table on FOUR seasons, with a stability gate.

    venv/bin/python -m scratchpad.state_seasons --backfill   # scan, ~5 min
    venv/bin/python -m scratchpad.state_seasons              # from cache

`state_table.py` counted 2026 alone — 150,275 plate appearances — and the
thin cells are what hold the table back: `hbp_pct` keeps 36% of its raw
spread and `hr_pct` keeps none. All four seasons are already cached
locally (9,978 games), so this is compute, not network.

MULTIPLIERS ARE COMPUTED WITHIN A SEASON AND POOLED AFTERWARDS, and that
ordering is the whole design. The league run environment drifts — 2026
strikes out at a different rate than 2023 — so pooling the raw COUNTS and
taking one ratio would let a season's baseline leak into the cells through
whatever composition shift came with it. A ratio to that season's own
overall rate is the quantity that is comparable across years.

THE STABILITY GATE COMES FIRST AND IT IS NOT A FORMALITY. `advance.py`
gates per-club advancement this way and it FAILS, which is why the league
number ships. The question here is whether a cell's multiplier is the same
baseball every year or whether it is that year's noise. Pooling an
unstable quantity manufactures precision that is not there.

    reliability = correlation of the 12 cell multipliers between seasons,
                  averaged over the six season pairs

A channel that does not repeat across years should NOT be pooled to a
tighter number — it should stay where it is, or come out.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import statistics as st
import sys
from collections import defaultdict
from itertools import combinations

from src import db
from src.context.sources import pbp
from scratchpad.state_table import PA_EV, K_EV, HIT_EV, STATS, _rates

CACHE = "scratchpad/state_counts_4season.json"
CELLS = [(o, u) for o in (0, 1, 2, 3) for u in (0, 1, 2)]


def _one(args):
    gid, season = args
    out = defaultdict(lambda: defaultdict(int))
    try:
        for play, bases, outs, _a, _h in pbp.plays(gid):
            ev = (play.get("result") or {}).get("eventType") or ""
            if ev not in PA_EV:
                continue
            cell = (sum(1 for b in bases if b), outs)
            for key in (cell, "ALL"):
                c = out[key]
                c["pa"] += 1
                c["k"] += ev in K_EV
                c["bb"] += ev == "walk"
                c["hbp"] += ev == "hit_by_pitch"
                c["hr"] += ev == "home_run"
                c["h"] += ev in HIT_EV
    except Exception:
        return None
    return season, {str(k): dict(v) for k, v in out.items()}


def backfill():
    with db.connect() as c:
        rows = [(r["game_id"], r["date"][:4]) for r in c.execute(
            "select game_id, date from games where sport='mlb'"
            " and status='Final' order by date")]
    rows = [(g, s) for g, s in rows if pbp.have(g)]
    print(f"  {len(rows):,} cached games over "
          f"{len(set(s for _g, s in rows))} seasons", flush=True)
    with mp.get_context("fork").Pool(8) as p:
        got = [g for g in p.map(_one, rows, chunksize=16) if g]
    agg: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for season, cells in got:
        for cell, c in cells.items():
            for k, v in c.items():
                agg[season][cell][k] += v
    out = {s: {c: dict(v) for c, v in cells.items()}
           for s, cells in agg.items()}
    json.dump(out, open(CACHE, "w"), indent=1)
    print(f"  -> {CACHE}")
    return out


def _mults(cells):
    """Cell multipliers for ONE season: each cell's rate over that season's
    own overall rate. Normalised within the year, which is what makes two
    years comparable at all."""
    base = _rates(cells["ALL"])
    out = {}
    for cell in CELLS:
        c = cells.get(str(cell))
        if not c or c["pa"] < 500:
            continue
        r = _rates(c)
        out[cell] = {k: r[k] / base[k] for k in r}
    return out


def main(argv):
    data = backfill() if "--backfill" in argv else json.load(open(CACHE))
    seasons = sorted(data)
    per = {s: _mults(data[s]) for s in seasons}
    tot = sum(data[s]["ALL"]["pa"] for s in seasons)
    print(f"\n  {len(seasons)} seasons, {tot:,} plate appearances "
          f"({tot / 150275:.1f}x the shipped table)\n")
    print(f"  {'season':>8}{'PA':>10}" + "".join(f"{s[:-4]:>9}" for s in STATS))
    for s in seasons:
        b = _rates(data[s]["ALL"])
        print(f"  {s:>8}{data[s]['ALL']['pa']:>10,}"
              + "".join(f"{b[k]:>9.4f}" for k in STATS))

    # ── THE GATE ───────────────────────────────────────────────────────
    # Does a cell's multiplier repeat from year to year, or is it that
    # year's noise? Correlation over the twelve cells, averaged over the
    # six season pairs. A channel that does not repeat must not be pooled
    # to a tighter number.
    #
    # RUN TWICE, ON ALL TWELVE CELLS AND ON THE FAT ONES. An unweighted
    # correlation over twelve cells lets the three bases-loaded cells —
    # 3,149 plate appearances between them against 185,488 in the leadoff
    # cell — carry the same vote as the cell that decides the channel. Their
    # own noise then reads as a channel that does not repeat. The restricted
    # column is the one to believe when the two disagree, and the gap
    # between them says how much of the verdict was the thin cells.
    fat = [c for c in CELLS
           if sum(data[s].get(str(c), {}).get("pa", 0) for s in seasons)
           >= 30000]
    print("\n  STABILITY GATE — cell multipliers across seasons\n")
    print(f"  {'stat':<9}{'all 12':>9}{'range':>15}"
          f"{f'fat {len(fat)}':>9}{'range':>15}   verdict")
    rel = {}

    def _r(stat, cells):
        rs = []
        for a, b in combinations(seasons, 2):
            common = [c for c in cells if c in per[a] and c in per[b]]
            if len(common) < 3:
                continue
            rs.append(st.correlation([per[a][c][stat] for c in common],
                                     [per[b][c][stat] for c in common]))
        return rs

    for stat in STATS:
        rs, rf = _r(stat, CELLS), _r(stat, fat)
        rel[stat] = st.mean(rf) if rf else 0.0
        verdict = ("repeats" if rel[stat] > 0.5 else
                   "weak" if rel[stat] > 0.2 else "DOES NOT REPEAT")
        print(f"  {stat:<9}{st.mean(rs):>9.3f}{min(rs):>8.2f}{max(rs):>7.2f}"
              f"{st.mean(rf):>9.3f}{min(rf):>8.2f}{max(rf):>7.2f}   {verdict}")
    # A correlation over twelve points is itself imprecise: se ~0.27 at
    # r = 0.4, so "weak" and "repeats" are not sharply separated and the
    # six pairs are not independent. Read the DIRECTION, not the decimal.

    # ── POOLED ─────────────────────────────────────────────────────────
    # Weighted by each season's cell PA, over multipliers that were each
    # normalised within their own year.
    print(f"\n  {'on':>3}{'out':>5}{'n':>10}"
          + "".join(f"{s[:-4]:>13}" for s in STATS))
    table = {}
    for cell in CELLS:
        n = sum(data[s][str(cell)]["pa"] for s in seasons
                if str(cell) in data[s])
        if n < 500:
            continue
        m, se = {}, {}
        for stat in STATS:
            m[stat] = sum(per[s][cell][stat] * data[s][str(cell)]["pa"]
                          for s in seasons if cell in per[s]) / n
        # SE on the pooled multiplier: binomial noise on the pooled cell,
        # carried through the division by the overall rate. `babip` has its
        # own denominator — balls in play, not plate appearances.
        pooled = defaultdict(int)
        for s in seasons:
            for k, v in data[s].get(str(cell), {}).items():
                pooled[k] += v
        base = {k: st.mean(_rates(data[s]["ALL"])[k] for s in seasons)
                for k in STATS}
        r = _rates(pooled)
        bip = (pooled["pa"] - pooled["k"] - pooled["bb"] - pooled["hbp"]
               - pooled["hr"])
        for k, nn in (("k_pct", n), ("bb_pct", n), ("hr_pct", n),
                      ("babip", max(bip, 1)), ("hbp_pct", n)):
            se[k] = ((r[k] * (1 - r[k]) / nn) ** 0.5) / base[k]
        table[f"{cell[0]},{cell[1]}"] = {
            "_n": n, **{k: round(m[k], 4) for k in m},
            **{f"se_{k}": round(se[k], 4) for k in se}}
        print(f"  {cell[0]:>3}{cell[1]:>5}{n:>10,}"
              + "".join(f"{m[k]:>6.3f}+-{se[k]:<6.4f}" for k in STATS))

    print("\n  frequency-weighted mean multiplier (must be ~1.000):")
    for stat in STATS:
        w = sum(table[c]["_n"] * table[c][stat] for c in table)
        print(f"    {stat:<8}{w / sum(table[c]['_n'] for c in table):.4f}")
    json.dump(table, open("scratchpad/state_table.json", "w"), indent=1)
    print("\n  -> scratchpad/state_table.json "
          "(now run scratchpad.state_shrink)")


if __name__ == "__main__":
    main(sys.argv[1:])
