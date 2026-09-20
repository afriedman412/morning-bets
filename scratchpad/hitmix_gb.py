"""COUNT the hit mix (XBH share of non-HR hits) by GB%, for item 4c.

    venv/bin/python -m scratchpad.hitmix_gb [--backfill]

THE DENOMINATOR IS THE MODEL'S OWN: `pa_outcome` draws the 1B/2B/3B
split AFTER the HR branch, so the counted share must condition on
single/double/triple — never on all hits. It is also the battery's
(`xbh_share_nonhr_hits`, `xbh_by_batter_gb_q*`).

Same discipline as `dp_gb.py`, which validated the whole pattern one
item ago: pre-July rows of ALL FOUR seasons (July-onward is battery
scoring territory in every season); the covariate is the SHRUNK
`gb_pct_map(role, season, before=cut)` the engine reads at resolve
time; era gate on the odds ratios; the 25-cell cross decides whether
log5 is the right combination; centring over real hit rows.

ALSO PRINTED: the 3B share WITHIN XBH by quintile — the wire keeps the
league 2B:3B split inside the XBH mass unless this table says the split
itself moves with GB%.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import statistics as st
import sys
from itertools import combinations

from src import db
from src.context.sources import pbp, battedball

CACHE = "scratchpad/hitmix_gb_rows.json"
CUTS = {s: f"{s}-07-01" for s in (2023, 2024, 2025, 2026)}
HIT_EV = {"single": 0, "double": 1, "triple": 2}

#: THE COVARIATE IS STRICTLY PRIOR TO THE ROW. The first version binned
#: April-June rows by GB% counted over April-June — the outcome rows sat
#: inside their own covariate window, and since a single IS a ground ball
#: more often than a double, every counted single mechanically raised the
#: same batter's GB%. That self-correlation roughly DOUBLED the slope
#: (counted 0.056 vs 0.028 on the disjoint battery holdouts), and the
#: wired table overshot exactly that way in the 2024/2025 folds. Rows in
#: month m now use the map frozen BEFORE month m — the same
#: covariate-precedes-outcome arrangement the engine scores under.
MONTHS = (5, 6)

_GB: dict = {}


def _one(args):
    gid, season, month = args
    rows = []
    try:
        gb_p, gb_b = _GB[(season, month)]
        for play, _bases, _outs, _a, _h in pbp.plays(gid):
            ev = (play.get("result") or {}).get("eventType") or ""
            if ev not in HIT_EV:
                continue
            mu = play.get("matchup") or {}
            pn = (mu.get("pitcher") or {}).get("fullName")
            bn = (mu.get("batter") or {}).get("fullName")
            rows.append((season, gb_p.get(pn), gb_b.get(bn), HIT_EV[ev]))
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
    print(f"  wrote {len(rows):,} non-HR hits to {CACHE}")
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
    print(f"\n  {len(rows):,} non-HR hits; pitcher gb known "
          f"{sum(r[1] is not None for r in rows) / len(rows):.1%}, batter "
          f"{sum(r[2] is not None for r in rows) / len(rows):.1%}, both "
          f"{len(known) / len(rows):.1%}")
    xbh = [int(r[3] > 0) for r in known]
    lg = sum(xbh) / len(known)
    seasons = sorted({r[0] for r in known})
    cols = []
    for s in seasons:
        sl = [r for r in known if r[0] == s]
        cols.append(f"   {s} "
                    f"{sum(int(r[3] > 0) for r in sl) / len(sl):.4f}")
    print(f"  pooled XBH share of non-HR hits {lg:.4f} on {len(known):,}"
          + "".join(cols))

    pe = _edges([r[1] for r in known])
    be = _edges([r[2] for r in known])
    out = {}
    for label, idx, edges in (("batter", 2, be), ("pitcher", 1, pe)):
        print(f"\n  XBH share by {label} GB quintile  "
              f"(edges {' '.join(f'{e:.3f}' for e in edges)})")
        print(f"  {'q':<3}{'n':>9}{'share':>8}{'se':>8}{'odds x':>8}"
              f"{'3b|xbh':>8}" + "".join(f"{s:>9}" for s in seasons))
        mults = []
        for q in range(1, 6):
            sub = [r for r in known if _q(r[idx], edges) == q]
            p = sum(int(r[3] > 0) for r in sub) / len(sub)
            se = (p * (1 - p) / len(sub)) ** 0.5
            om = _odds(p) / _odds(lg)
            mults.append(om)
            nx = sum(int(r[3] > 0) for r in sub)
            t3 = sum(int(r[3] == 2) for r in sub) / nx if nx else 0.0
            cols = []
            for s in seasons:
                ss = [r for r in sub if r[0] == s]
                sl = [r for r in known if r[0] == s]
                slr = sum(int(r[3] > 0) for r in sl) / len(sl)
                cols.append(
                    _odds(sum(int(r[3] > 0) for r in ss) / len(ss))
                    / _odds(slr) if ss else None)
            print(f"  {q:<3}{len(sub):>9,}{p:>8.4f}{se:>8.4f}{om:>8.3f}"
                  f"{t3:>8.4f}"
                  + "".join(f"{c:>9.3f}" if c is not None else f"{'-':>9}"
                            for c in cols))
        out[label] = (edges, mults)

    per = {}
    for s in seasons:
        sl = [r for r in known if r[0] == s]
        slr = sum(int(r[3] > 0) for r in sl) / len(sl)
        v = []
        for idx, edges in ((2, be), (1, pe)):
            for q in range(1, 6):
                ss = [r for r in sl if _q(r[idx], edges) == q]
                v.append(_odds(sum(int(r[3] > 0) for r in ss) / len(ss))
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

    print("\n  batter x pitcher cross — observed / log5-predicted (z)")
    print("  rows = batter quintile, cols = pitcher quintile")
    worst = 0.0
    for qb in range(1, 6):
        line = f"  q{qb} "
        for qp in range(1, 6):
            sub = [r for r in known
                   if _q(r[2], be) == qb and _q(r[1], pe) == qp]
            if len(sub) < 50:
                line += f"{'-':>16}"
                continue
            obs = sum(int(r[3] > 0) for r in sub) / len(sub)
            od = _odds(lg) * out["batter"][1][qb - 1] \
                * out["pitcher"][1][qp - 1]
            pred = od / (1 + od)
            se = (pred * (1 - pred) / len(sub)) ** 0.5
            z = (obs - pred) / se
            worst = max(worst, abs(z))
            line += f"{obs:.3f}/{pred:.3f}({z:+.1f})"
        print(line)
    print(f"  worst |z| {worst:.1f}")

    def mean_rate(c):
        tot = 0.0
        for r in known:
            od = _odds(lg) * c * out["batter"][1][_q(r[2], be) - 1] \
                * out["pitcher"][1][_q(r[1], pe) - 1]
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
    print("\n  CONSTANTS TO SHIP (centring folded into the batter side):")
    bm = [m * c for m in out["batter"][1]]
    print(f"  XBH_GB_BAT = ({tuple(round(e, 4) for e in be)},\n"
          f"                {tuple(round(m, 4) for m in bm)})")
    print(f"  XBH_GB_PIT = ({tuple(round(e, 4) for e in pe)},\n"
          f"                {tuple(round(m, 4) for m in out['pitcher'][1])})")


def main(argv):
    rows = backfill() if "--backfill" in argv \
        else [tuple(r) for r in json.load(open(CACHE))]
    report(rows)


if __name__ == "__main__":
    main(sys.argv[1:])
