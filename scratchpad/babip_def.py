"""Is the league BABIP the model is built on measured on the wrong denominator?

    venv/bin/python -m scratchpad.babip_def

THE SUSPICION. `sim.league` derives balls in play from the BOXSCORE as

    bip = outs_recorded + hits - strikeouts - home runs

and `outs_recorded` is a count of OUTS, not of BALLS IN PLAY. Those differ in
two ways and both inflate the denominator:

  * A DOUBLE PLAY is one ball in play and TWO outs.
  * CAUGHT STEALING and PICKOFFS are outs and no ball in play at all.

An inflated denominator deflates BABIP, and BABIP is the rate that decides
how many balls in play become hits — which is the one channel still short at
full sample (singles -4.9%, men reaching base -2.4%).

COUNTED PER PLAY off the play-by-play, which cannot make either mistake: one
plate appearance is one event, a double play is one event, a caught stealing
is not a plate appearance at all.

STARTERS ONLY, because that is the population `_starter_league` measures and
the anchor the model log5s against. The comparison has to be like for like or
it measures the population difference instead of the definition.
"""
from __future__ import annotations

import concurrent.futures as cf
import glob
import multiprocessing as mp
import os
import sys
from collections import Counter

from src import db
from src.context.sources import pbp

HITS = {"single", "double", "triple"}
BIP_OUT = {"field_out", "force_out", "fielders_choice_out", "fielders_choice",
           "grounded_into_double_play", "double_play", "triple_play",
           "sac_fly", "sac_bunt", "sac_fly_double_play",
           "sac_bunt_double_play"}
DP = {"grounded_into_double_play", "double_play", "triple_play",
      "sac_fly_double_play", "sac_bunt_double_play", "strikeout_double_play"}
ONBASE_OUT = {"caught_stealing_2b", "caught_stealing_3b",
              "caught_stealing_home", "pickoff_1b", "pickoff_2b",
              "pickoff_3b", "pickoff_caught_stealing_2b",
              "pickoff_caught_stealing_3b", "pickoff_caught_stealing_home"}


def _one(gid):
    t = Counter()
    try:
        d = pbp.fetch(gid)
    except Exception:
        return t
    if not d:
        return t
    seen = {}
    for p in (d.get("allPlays") or []):
        ab, mu = p.get("about") or {}, p.get("matchup") or {}
        pid = (mu.get("pitcher") or {}).get("id")
        if not pid:
            continue
        side = "home" if ab.get("isTopInning") else "away"
        seen.setdefault(side, pid)
        if seen[side] != pid:
            continue                      # starters only
        ev = ((p.get("result") or {}).get("eventType") or "")
        if ev in HITS:
            t["hits"] += 1
            t["bip"] += 1
        elif ev in BIP_OUT:
            t["bip"] += 1
        elif ev == "field_error":
            t["bip"] += 1
            t["roe"] += 1
        if ev in DP:
            t["dp"] += 1
        if ev in ONBASE_OUT:
            t["onbase_out"] += 1
        if ev == "home_run":
            t["hr"] += 1
    return t


def main(argv):
    with db.connect() as c:
        season = {r["game_id"].split("-")[-1]: r["date"][:4]
                  for r in c.execute(
                      "select game_id, date from games where sport = 'mlb'")}
    gids = [os.path.basename(f).split(".")[0]
            for f in sorted(glob.glob(".cache/pbp/*.json.gz"))]
    gids = [g for g in gids if season.get(g) == "2026"]
    workers = max(1, (os.cpu_count() or 4) - 1)
    print(f"  {len(gids):,} games over {workers} workers", flush=True)
    tot = Counter()
    with cf.ProcessPoolExecutor(max_workers=workers,
                                mp_context=mp.get_context("fork")) as pool:
        for t in pool.map(_one, gids, chunksize=32):
            tot += t

    counted = tot["hits"] / tot["bip"]
    print(f"\n  COUNTED PER PLAY (starters, 2026)")
    print(f"    balls in play {tot['bip']:,}   hits {tot['hits']:,}"
          f"   BABIP {counted:.4f}")
    print(f"    double plays {tot['dp']:,}   caught stealing/pickoffs"
          f" {tot['onbase_out']:,}   errors {tot['roe']:,}")

    # What the boxscore formula produces on the same population.
    with db.connect() as c:
        r = c.execute(
            "select sum(p.outs_recorded) o, sum(p.h) h, sum(p.bb) bb,"
            " sum(p.k) k, sum(p.hr) hr from mlb_pitching p"
            " join games g on g.game_id = p.game_id"
            " where g.sport = 'mlb' and g.status = 'Final'"
            " and g.date like '2026%' and p.is_starter = 1").fetchone()
    bf = r["o"] + r["h"] + r["bb"]
    bip_box = bf - r["k"] - r["bb"] - r["hr"]
    box = (r["h"] - r["hr"]) / bip_box
    print(f"\n  BOXSCORE FORMULA (what `sim.league` uses)")
    print(f"    balls in play {bip_box:,}   BABIP {box:.4f}")
    print(f"\n  denominator inflated by {bip_box - tot['bip']:,}"
          f" = {(bip_box / tot['bip'] - 1) * 100:+.1f}%")
    print(f"  BABIP understated by {(box / counted - 1) * 100:+.1f}%")
    print(f"\n  For scale, the extra outs the boxscore counts as balls in")
    print(f"  play: {tot['dp']:,} second-outs-of-a-double-play plus"
          f" {tot['onbase_out']:,} outs on the bases.")


if __name__ == "__main__":
    main(sys.argv[1:])
