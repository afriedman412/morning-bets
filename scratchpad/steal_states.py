"""Stealing, counted in EVERY base state instead of one.

    venv/bin/python -m scratchpad.steal_states [--season YYYY] [workers]

`sim.baserunning` rolls for a steal only when first is occupied and SECOND
IS EMPTY, and the only move it can make is first->second. Measured, that
leaves 14.5% of real steal events — 2,564 of 17,742 — unreachable at any
rate: steals of third, and double steals. When a parameter cannot reach the
target the mechanism is missing rather than mistuned, which is the standing
diagnostic here and has been right four times.

We have every base state on file, so there is no reason to model one.

WHAT IS COUNTED: per (base state, outs), the number of plate appearances
that state was live for, and the steal and caught-stealing events that
occurred in it, keyed by WHICH BASE was taken. That is everything a general
version of `baserunning` needs.

DENOMINATOR IS THE PLATE APPEARANCE THE STATE WAS LIVE FOR, matching what
`baserunning` rolls once per plate appearance. Base state is reconstructed
by `pbp.plays`, which yields the state BEFORE each play — `matchup.postOn*`
is the state AFTER and reading it as "before" is the misreading that
mislabelled 27,401 inning endings in this project.

RUNNER MOVEMENT COMES FROM `pbp.resolve`, which collapses a runner's
multiple movement records into where he actually ended up. The hand-rolled
version of that reported 2 first-to-thirds in 557 singles.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

from src import db
from src.context.sources import pbp

_NAME = {(False, False, False): "empty",
         (True, False, False): "1B",
         (False, True, False): "2B",
         (False, False, True): "3B",
         (True, True, False): "1B+2B",
         (True, False, True): "1B+3B",
         (False, True, True): "2B+3B",
         (True, True, True): "loaded"}


def scan(short: str):
    try:
        d = pbp.fetch(short)
    except Exception:
        return None
    if not d:
        return None
    out = defaultdict(int)
    for play, bases, outs, _a, _h in pbp.plays(short, d):
        st = _NAME[tuple(bases)]
        if st == "empty":
            continue
        out[f"{st}|{outs}|opp"] += 1
        for r in (play.get("runners") or []):
            det = r.get("details") or {}
            e = det.get("event") or ""
            mv = r.get("movement") or {}
            if e.startswith("Stolen Base"):
                out[f"{st}|{outs}|sb_{mv.get('end')}"] += 1
                out[f"{st}|{outs}|sb"] += 1
            elif e.startswith("Caught Stealing"):
                out[f"{st}|{outs}|cs"] += 1
    return dict(out)


def main(argv):
    season = None
    if argv and argv[0] == "--season":
        season, argv = argv[1], argv[2:]
    workers = int(argv[0]) if argv else 8
    with db.connect() as c:
        dates = {r["game_id"]: r["date"] for r in
                 c.execute("select game_id, date from games"
                           " where sport = 'mlb'")}
    todo = sorted(g for g in dates if pbp.have(g.split("-")[-1])
                  and (season is None or dates[g].startswith(season)))
    print(f"  scanning {len(todo):,} games on {workers} workers"
          f"{' (' + season + ')' if season else ''} ...", flush=True)
    acc = defaultdict(int)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for got in ex.map(scan, [g.split("-")[-1] for g in todo],
                          chunksize=32):
            if got:
                for k, v in got.items():
                    acc[k] += v

    print(f"\n  {'state':<8}{'outs':>5}{'opps':>10}{'SB rate':>10}"
          f"{'CS rate':>10}{'to 2B':>8}{'to 3B':>8}{'home':>7}")
    tot_sb = tot_cs = 0
    modelled_sb = 0
    for st in ("1B", "2B", "3B", "1B+2B", "1B+3B", "2B+3B", "loaded"):
        for o in (0, 1, 2):
            opp = acc.get(f"{st}|{o}|opp", 0)
            if opp < 200:
                continue
            sb = acc.get(f"{st}|{o}|sb", 0)
            cs = acc.get(f"{st}|{o}|cs", 0)
            tot_sb += sb
            tot_cs += cs
            if st == "1B":
                modelled_sb += sb
            b2 = acc.get(f"{st}|{o}|sb_2B", 0)
            b3 = acc.get(f"{st}|{o}|sb_3B", 0)
            hm = acc.get(f"{st}|{o}|sb_score", 0)
            print(f"  {st:<8}{o:>5}{opp:>10,}{sb / opp:>10.4f}"
                  f"{cs / opp:>10.4f}{b2:>8,}{b3:>8,}{hm:>7,}")
    print(f"\n  total steals {tot_sb:,}, caught {tot_cs:,}")
    if tot_sb:
        print(f"  the model's ONE state (1B alone) covers "
              f"{100 * modelled_sb / tot_sb:.1f}% of them")
    print("\n  Every row below the first block is a state the simulator")
    print("  cannot steal in at all. The `to 3B` column is the mechanism")
    print("  that does not exist.")


if __name__ == "__main__":
    main(sys.argv[1:])
