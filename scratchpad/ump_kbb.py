"""Plan item 8b: the plate umpire's K and BB effect, counted properly.

    venv/bin/python -m scratchpad.ump_kbb --backfill   # scan pbp, ~30s
    venv/bin/python -m scratchpad.ump_kbb              # from cache

QUESTION: does the plate umpire move strikeouts and walks by enough, and
REPEATABLY enough, to be worth wiring as a shared-night condition? One
man, both clubs, the whole game — exactly the class of between-game
variance (temperature, wind) that fattens both tails without touching
within-game independence.

`sources/officials.py` already records the crew (10,146 games) and its
`profiles()` docstring names its own confound: raw K/9 per umpire is
mostly WHICH STAFFS HE DREW. This count removes that the same way the 8a
and wind counts did — every plate appearance carries an expected rate
from the pitcher's and batter's own season rates (log5-lite, shrunk 300
PA toward the league), and an umpire's multiplier is observed over
expected across his games. What the staffs bring is in the expectation;
what is left is the man behind the plate (plus park drift in the
schedule, which rotates enough across a season to wash).

ROWS: everything before HOLDOUT (2026-07-01) — full 2023-2025 plus
pre-July 2026, the same training convention `STATE_MULT` and the
temperature table used. Baselines are per season, so era drift stays out
of the cells.

THE GATE COMES FIRST, and it is the one `advance.py --by-team` FAILS on:
a spread that does not repeat must not ship. Registered BEFORE the run
(rule 12):

  * POWER: an umpire works ~28 plates a season, ~2,200 PA — se ~4% per
    season on a k multiplier, ~2% pooled over four. If the true spread is
    ~1.5% (the size public zone work suggests, but we count, not import),
    split-half r over high-n umpires should read ~0.3 and adjacent-season
    r ~0.15. se of r over ~90 umpires is ~0.1.
  * SURVIVES if: split-half r > 0.2 on a channel (the repo's "weak"
    line) AND the noise-adjusted spread tau > 0.01. Below that the league
    is flat at our power and the umpire stays out of the model — record
    the null and the bound, as always.

WIRING IS A SEPARATE DECISION EVEN IF THIS SURVIVES: replay can read
`game_officials`, but a live slate needs the crew BEFORE first pitch and
plate assignments rotate daily — availability at slate time is its own
check. Count first.

THE RESULT, 2026-09-06: **SURVIVES BOTH GATES, WALKS DECISIVELY.**
694,598 PAs over 9,254 games, every one matched to a recorded plate
umpire (146 of them, 89 with >= 40 games):

                sd(raw)   mean se     tau   split-half r   season r
    k            0.0308    0.0251   0.0176      +0.352       +0.204
    bb           0.0607    0.0416   0.0438      +0.454       +0.323

The bb spread is 2.5x the k spread and repeats harder — the plate
umpire is first a WALK effect. Both channels clear the registered gate
(r > 0.2, tau > 0.01); the registered power estimate (~1.5% k spread,
r ~0.3) was close. Season-pair r over 211 pairs rules out a single
year's schedule quirk. NOT established here: park-schedule confounding
is argued away by crew rotation, not measured; the wire's A/B is where
that would surface as rows moving that should not.
"""
from __future__ import annotations

import gzip
import json
import multiprocessing as mp
import statistics as st
import sys
from collections import defaultdict

from src import db
from src.context.sources import pbp
from scratchpad.state_table import PA_EV
from scratchpad.inning_feedback import _cls, CLS

CACHE = "scratchpad/ump_kbb_rows.json.gz"
HOLDOUT = "2026-07-01"
PRIOR = 300
CHANNELS = ("k", "bb")
NUM = {"k": CLS["k"], "bb": CLS["bb"]}


def _one(args):
    gid, season = args
    rows = []
    try:
        for play, _bases, _outs, _a, _h in pbp.plays(gid):
            ev = (play.get("result") or {}).get("eventType") or ""
            if ev not in PA_EV:
                continue
            mu = play.get("matchup") or {}
            p = (mu.get("pitcher") or {}).get("id")
            b = (mu.get("batter") or {}).get("id")
            if p and b:
                rows.append([p, b, _cls(ev)])
    except Exception:
        return None
    return gid, season, rows


def backfill():
    with db.connect() as c:
        games = [(r["game_id"], r["date"][:4]) for r in c.execute(
            "select game_id, date from games where sport='mlb'"
            " and status='Final' and date < ? order by date", (HOLDOUT,))]
    games = [(g, s) for g, s in games if pbp.have(g)]
    print(f"  {len(games):,} cached games before {HOLDOUT}", flush=True)
    with mp.get_context("fork").Pool(8) as p:
        got = [g for g in p.map(_one, games, chunksize=16) if g]
    out: dict = defaultdict(dict)
    for gid, season, rows in got:
        out[season][gid] = rows
    with gzip.open(CACHE, "wt") as f:
        json.dump(out, f)
    n = sum(len(v) for g in out.values() for v in g.values())
    print(f"  {n:,} plate appearances -> {CACHE}")
    return out


def _game_obs_exp(by_season):
    """Per game: observed and expected K and BB counts, standardised on
    player-season rates. {gid: {"season", "pa", "ok","ek","obb","ebb"}}."""
    games = {}
    for season, gmap in by_season.items():
        lg = defaultdict(int)
        per = {"p": defaultdict(lambda: defaultdict(int)),
               "b": defaultdict(lambda: defaultdict(int))}
        for rows in gmap.values():
            for pid, bid, c in rows:
                lg["pa"] += 1
                lg[c] += 1
                for w, key in (("p", pid), ("b", bid)):
                    d = per[w][key]
                    d["pa"] += 1
                    d[c] = d.get(c, 0) + 1
        L = {ch: lg[NUM[ch]] / lg["pa"] for ch in CHANNELS}

        def shrunk(d, ch):
            return (d.get(NUM[ch], 0) + PRIOR * L[ch]) / (d["pa"] + PRIOR)

        for gid, rows in gmap.items():
            g = {"season": season, "pa": len(rows)}
            for ch in CHANNELS:
                o = e = 0.0
                for pid, bid, c in rows:
                    rp = shrunk(per["p"][pid], ch)
                    rb = shrunk(per["b"][bid], ch)
                    e += min(0.95, rp * rb / L[ch])
                    o += c == NUM[ch]
                g[f"o{ch}"], g[f"e{ch}"] = o, e
            games[gid] = g
    return games


def _umps():
    with db.connect() as c:
        return {r["game_id"]: (r["plate_ump_id"], r["plate_ump"])
                for r in c.execute(
                    "select game_id, plate_ump_id, plate_ump"
                    " from game_officials where plate_ump_id is not null")}


def _mult(gs, ch):
    o = sum(g[f"o{ch}"] for g in gs)
    e = sum(g[f"e{ch}"] for g in gs)
    return (o / e if e else 1.0), o


def main(argv):
    if "--backfill" in argv:
        by_season = backfill()
    else:
        with gzip.open(CACHE, "rt") as f:
            by_season = json.load(f)
    games = _game_obs_exp(by_season)
    umps = _umps()
    by_ump = defaultdict(list)
    matched = 0
    for gid, g in games.items():
        u = umps.get(gid)
        if u:
            matched += 1
            by_ump[u].append(g)
    print(f"\n  {len(games):,} games scored, {matched:,} with a recorded"
          f" plate umpire, {len(by_ump)} umpires")

    # ── pooled per-umpire multipliers and the noise-adjusted spread ────
    print(f"\n  {'':>26}{'k mult':>10}{'se':>7}{'bb mult':>10}{'se':>7}"
          f"{'G':>6}")
    pooled = {}
    for u, gs in sorted(by_ump.items(), key=lambda kv: -len(kv[1])):
        row = {}
        for ch in CHANNELS:
            m, o = _mult(gs, ch)
            row[ch] = (m, m / o ** 0.5 if o else 9.9)
        pooled[u] = (row, len(gs))
        if len(gs) >= 100:
            print(f"  {u[1][:24]:<26}{row['k'][0]:>10.4f}{row['k'][1]:>7.4f}"
                  f"{row['bb'][0]:>10.4f}{row['bb'][1]:>7.4f}{len(gs):>6}")

    big = {u: (row, n) for u, (row, n) in pooled.items() if n >= 40}
    print(f"\n  spread over {len(big)} umpires with >= 40 games"
          " (sd of multiplier, noise removed):")
    for ch in CHANNELS:
        ms = [row[ch][0] for row, _n in big.values()]
        ses = [row[ch][1] for row, _n in big.values()]
        var = st.pvariance(ms) - st.mean(s * s for s in ses)
        tau = var ** 0.5 if var > 0 else 0.0
        print(f"    {ch:<4} sd(raw) {st.pstdev(ms):.4f}   mean se "
              f"{st.mean(ses):.4f}   tau {tau:.4f}")

    # ── GATE 1: split-half over each umpire's own games ────────────────
    print("\n  GATE 1 — split-half (alternate games), umpires >= 40 G:")
    for ch in CHANNELS:
        a, b = [], []
        for u, gs in by_ump.items():
            if len(gs) < 40:
                continue
            gs = sorted(gs, key=lambda g: g["pa"])  # any stable order
            a.append(_mult(gs[0::2], ch)[0])
            b.append(_mult(gs[1::2], ch)[0])
        r = st.correlation(a, b) if len(a) >= 3 else 0.0
        print(f"    {ch:<4} r = {r:+.3f} over {len(a)} umpires")

    # ── THE SHIP TABLE ─────────────────────────────────────────────────
    if "--build" in argv:
        taus = {}
        for ch in CHANNELS:
            ms = [row[ch][0] for row, _n in big.values()]
            ses = [row[ch][1] for row, _n in big.values()]
            var = st.pvariance(ms) - st.mean(s * s for s in ses)
            taus[ch] = var ** 0.5 if var > 0 else 0.0
        table = {}
        for u, (row, n) in pooled.items():
            out = []
            for ch in CHANNELS:
                m, se = row[ch]
                w = taus[ch] ** 2 / (taus[ch] ** 2 + se * se)
                out.append(1.0 + (m - 1.0) * w)
            table[str(u[0])] = out
        # Renormalise to a game-weighted mean of exactly 1.0 per channel,
        # the same self-normalising discipline as STATE_MULT: the umpire
        # table must redistribute strikeouts and walks, never add them.
        tot = sum(n for _row, n in pooled.values())
        for i, ch in enumerate(CHANNELS):
            mean = sum(table[str(u[0])][i] * n
                       for u, (_row, n) in pooled.items()) / tot
            for u in table:
                table[u][i] = round(table[u][i] / mean, 4)
        out = {"_meta": {"built": "2026-09-06", "rows_before": HOLDOUT,
                         "tau": {ch: round(taus[ch], 4) for ch in CHANNELS},
                         "umpires": len(table),
                         "source": "scratchpad.ump_kbb --build"},
               **table}
        with open("src/context/ump_kbb.json", "w") as f:
            json.dump(out, f, indent=1)
        sd_k = st.pstdev([v[0] for k, v in table.items() if k != "_meta"])
        sd_bb = st.pstdev([v[1] for k, v in table.items() if k != "_meta"])
        print(f"\n  -> src/context/ump_kbb.json  {len(table)} umpires, "
              f"shrunk sd k {sd_k:.4f} bb {sd_bb:.4f}")

    # ── GATE 2: adjacent seasons ───────────────────────────────────────
    print("\n  GATE 2 — same umpire, adjacent seasons (>= 15 G each):")
    per_us = defaultdict(dict)
    for u, gs in by_ump.items():
        for s in {g["season"] for g in gs}:
            sub = [g for g in gs if g["season"] == s]
            if len(sub) >= 15:
                per_us[u][s] = {ch: _mult(sub, ch)[0] for ch in CHANNELS}
    for ch in CHANNELS:
        pairs = []
        for u, ss in per_us.items():
            ys = sorted(ss)
            pairs += [(ss[y1][ch], ss[y2][ch])
                      for y1, y2 in zip(ys, ys[1:])
                      if int(y2) == int(y1) + 1]
        r = (st.correlation([p[0] for p in pairs], [p[1] for p in pairs])
             if len(pairs) >= 3 else 0.0)
        print(f"    {ch:<4} r = {r:+.3f} over {len(pairs)} season pairs")


if __name__ == "__main__":
    main(sys.argv[1:])
