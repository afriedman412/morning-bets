"""COUNT double-play rate per opportunity by GB%, for item 4b.

    venv/bin/python -m scratchpad.dp_gb [--backfill]

THE DENOMINATOR IS THE BATTERY'S, imported not re-typed: an opportunity is
a plate appearance ending in `EV_INPLAY_OUT` with a man on first and fewer
than two out; a double play is `EV_DP`. Rule 10 — the counted table and
the scoring instrument must not disagree about what a chance was.

TRAINING ROWS ONLY (rule 6, applied per fold): date < July 1 of each
season. July-onward of 2023-2025 are battery SCORING rows, not just 2026's
holdout, so the count stops at the cut in every season.

THE COVARIATE IS THE MODEL'S OWN: `battedball.gb_pct_map(role, season,
before=cut)` — the shrunk GB% the engine reads at resolve time, frozen at
the same cut the battery freezes rates at. Counting the relation on raw
season-long GB% and applying it to shrunk values would attenuate twice.

WHAT IT PRINTS:
  * DP rate per opportunity by pitcher GB quintile and batter GB quintile
    (pooled edges, opportunity-weighted), per season and pooled, with se —
    the era gate runs on the ODDS RATIOS, not the level (the level already
    stepped 2024->2025 and is era-gated in `sim.GIDP_RATE`).
  * The 25-cell pitcher x batter cross, observed vs the log5 prediction
    from the two marginals — the check that log5 is the right combination
    shape before it is wired.
  * The constants to ship: quintile edges and centred odds multipliers,
    renormalised so the opportunity-weighted mean rate over REAL rows
    reproduces the pooled league rate (redistribution, not re-levelling).
"""
from __future__ import annotations

import json
import multiprocessing as mp
import statistics as st
import sys
from itertools import combinations

from src import db
from src.context.sources import pbp, battedball
from scratchpad.battery import EV_INPLAY_OUT, EV_DP

CACHE = "scratchpad/dp_gb_rows.json"
CUTS = {s: f"{s}-07-01" for s in (2023, 2024, 2025, 2026)}

#: THE COVARIATE IS STRICTLY PRIOR TO THE ROW — the correction found by
#: 4c's scoring run and applied to both tables. The first count binned
#: April-June rows by GB% counted over April-June, so every counted DP
#: grounder sat inside its own pitcher's covariate, inflating the slope
#: (training 0.108 vs ~0.07 on the disjoint battery holdouts, and the
#: shipped table tilted low-quintiles-under / high-quintiles-over in
#: every fold). Rows in month m now use the map frozen BEFORE month m,
#: matching how the engine reads the covariate at scoring time.
MONTHS = (5, 6)

#: Per-(season, month) {name: shrunk gb} maps, filled in the parent
#: before the fork so workers inherit them.
_GB: dict = {}


def _one(args):
    gid, season, month = args
    rows = []
    try:
        gb_p, gb_b = _GB[(season, month)]
        for play, bases, outs, _a, _h in pbp.plays(gid):
            ev = (play.get("result") or {}).get("eventType") or ""
            if ev not in EV_INPLAY_OUT or not bases[0] or outs >= 2:
                continue
            mu = play.get("matchup") or {}
            pn = (mu.get("pitcher") or {}).get("fullName")
            bn = (mu.get("batter") or {}).get("fullName")
            rows.append((season, gb_p.get(pn), gb_b.get(bn),
                         int(ev in EV_DP)))
    except Exception:
        return None
    return rows


def backfill():
    with db.connect() as c:
        games = [(r["game_id"], int(r["date"][:4]), r["date"]) for r in
                 c.execute("select game_id, date from games where "
                           "sport='mlb' and status='Final' order by date")]
    games = [(g, s, int(d[5:7])) for g, s, d in games
             if s in CUTS and d < CUTS[s] and int(d[5:7]) in MONTHS
             and pbp.have(g)]
    for s in sorted(CUTS):
        for m in MONTHS:
            cut = f"{s}-{m:02d}-01"
            _GB[(s, m)] = (battedball.gb_pct_map("pit", s, cut),
                           battedball.gb_pct_map("bat", s, cut))
    print(f"  {len(games):,} May-June pre-cut cached games", flush=True)
    with mp.get_context("fork").Pool(8) as p:
        got = p.map(_one, games, chunksize=16)
    rows = [r for g in got if g for r in g]
    json.dump(rows, open(CACHE, "w"))
    print(f"  wrote {len(rows):,} opportunities to {CACHE}")
    return rows


def _edges(vals):
    s = sorted(vals)
    return [s[int(len(s) * q / 5)] for q in range(1, 5)]


def _q(v, edges):
    return sum(v >= e for e in edges) + 1


def _odds(p):
    return p / (1 - p)


def report(rows):
    known = [r for r in rows if r[1] is not None and r[2] is not None]
    print(f"\n  {len(rows):,} opportunities; pitcher gb known "
          f"{sum(r[1] is not None for r in rows) / len(rows):.1%}, batter "
          f"{sum(r[2] is not None for r in rows) / len(rows):.1%}, both "
          f"{len(known) / len(rows):.1%}")
    lg = sum(r[3] for r in known) / len(known)
    seasons = sorted({r[0] for r in known})
    cols = []
    for s in seasons:
        sl = [r for r in known if r[0] == s]
        cols.append(f"   {s} {sum(r[3] for r in sl) / len(sl):.4f}")
    print(f"  pooled league DP/opp {lg:.4f} on {len(known):,} rows"
          + "".join(cols))

    pe = _edges([r[1] for r in known])
    be = _edges([r[2] for r in known])
    out = {}
    for label, idx, edges in (("pitcher", 1, pe), ("batter", 2, be)):
        print(f"\n  DP/opp by {label} GB quintile  "
              f"(edges {' '.join(f'{e:.3f}' for e in edges)})")
        print(f"  {'q':<3}{'n':>9}{'rate':>8}{'se':>8}{'odds x':>8}"
              + "".join(f"{s:>9}" for s in seasons))
        mults = []
        for q in range(1, 6):
            sub = [r for r in known if _q(r[idx], edges) == q]
            p = sum(r[3] for r in sub) / len(sub)
            se = (p * (1 - p) / len(sub)) ** 0.5
            om = _odds(p) / _odds(lg)
            mults.append(om)
            cols = []
            for s in seasons:
                ss = [r for r in sub if r[0] == s]
                sl = [r for r in known if r[0] == s]
                slr = sum(r[3] for r in sl) / len(sl)
                cols.append(_odds(sum(r[3] for r in ss) / len(ss))
                            / _odds(slr) if ss else None)
            print(f"  {q:<3}{len(sub):>9,}{p:>8.4f}{se:>8.4f}{om:>8.3f}"
                  + "".join(f"{c:>9.3f}" if c is not None else f"{'-':>9}"
                            for c in cols))
        out[label] = (edges, mults)

    # Era gate on the SHAPE: between-season correlation of the ten
    # per-quintile odds ratios (5 pitcher + 5 batter, each season's
    # quintile odds against its own league odds).
    per = {}
    for s in seasons:
        sl = [r for r in known if r[0] == s]
        slr = sum(r[3] for r in sl) / len(sl)
        v = []
        for idx, edges in ((1, pe), (2, be)):
            for q in range(1, 6):
                ss = [r for r in sl if _q(r[idx], edges) == q]
                v.append(_odds(sum(r[3] for r in ss) / len(ss))
                         / _odds(slr) if ss else None)
        per[s] = v
    cors = []
    for a, b in combinations(seasons, 2):
        xs = [(x, y) for x, y in zip(per[a], per[b])
              if x is not None and y is not None]
        if len(xs) > 2:
            cors.append(st.correlation([x for x, _ in xs],
                                       [y for _, y in xs]))
    print(f"\n  era gate: mean between-season correlation of the odds "
          f"ratios {st.mean(cors):.3f} over {len(cors)} pairs")

    # The 25-cell cross: observed vs the log5 prediction from the two
    # marginals. This is the check that odds MULTIPLY — a product of two
    # rate multipliers would overshoot the corner cells.
    print("\n  pitcher x batter cross — observed / log5-predicted (z)")
    print("  rows = pitcher quintile, cols = batter quintile")
    worst = 0.0
    for qp in range(1, 6):
        line = f"  q{qp} "
        for qb in range(1, 6):
            sub = [r for r in known
                   if _q(r[1], pe) == qp and _q(r[2], be) == qb]
            if len(sub) < 50:
                line += f"{'-':>16}"
                continue
            obs = sum(r[3] for r in sub) / len(sub)
            od = _odds(lg) * out["pitcher"][1][qp - 1] \
                * out["batter"][1][qb - 1]
            pred = od / (1 + od)
            se = (pred * (1 - pred) / len(sub)) ** 0.5
            z = (obs - pred) / se
            worst = max(worst, abs(z))
            line += f"{obs:.3f}/{pred:.3f}({z:+.1f})"
        print(line)
    print(f"  worst |z| {worst:.1f}")

    # Centring over REAL opportunity weights: apply the construction to
    # every known row and renormalise the joint odds by one factor so the
    # implied mean rate equals lg. Redistribution, not re-levelling.
    def mean_rate(c):
        tot = 0.0
        for r in known:
            od = _odds(lg) * c * out["pitcher"][1][_q(r[1], pe) - 1] \
                * out["batter"][1][_q(r[2], be) - 1]
            tot += od / (1 + od)
        return tot / len(known)
    lo, hi = 0.5, 2.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if mean_rate(mid) < lg:
            lo = mid
        else:
            hi = mid
    c = (lo + hi) / 2
    print(f"\n  raw implied mean {mean_rate(1.0):.4f} vs lg {lg:.4f}; "
          f"centring odds factor {c:.4f}")
    print("\n  CONSTANTS TO SHIP (centring folded into the pitcher side):")
    pm = [m * c for m in out["pitcher"][1]]
    print(f"  DP_GB_PIT = ({tuple(round(e, 4) for e in pe)},\n"
          f"               {tuple(round(m, 4) for m in pm)})")
    print(f"  DP_GB_BAT = ({tuple(round(e, 4) for e in be)},\n"
          f"               {tuple(round(m, 4) for m in out['batter'][1])})")


def main(argv):
    rows = backfill() if "--backfill" in argv \
        else [tuple(r) for r in json.load(open(CACHE))]
    report(rows)


if __name__ == "__main__":
    main(sys.argv[1:])
