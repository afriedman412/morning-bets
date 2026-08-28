"""Do plate-appearance OUTCOMES depend on the base-out state? Counted.

    venv/bin/python -m scratchpad.basestate [max_games]

WHY THIS IS THE REAL VERSION OF THE SEQUENCING QUESTION. `sim.pa_from`
takes a resolved matchup and a times-through-order index and NOTHING ELSE
— not the bases, not the outs. So a plate appearance resolves identically
with the bases empty and with the bases loaded, and only `apply_pa` then
knows where the runners were. If real rates move with the base state, that
is a channel the model does not have at all, and no amount of reordering
the steal/wild-pitch roll can supply it.

Counted off play-by-play, which reconstructs the state BEFORE every play.
"""
from __future__ import annotations

import multiprocessing as mp
import sys
from collections import defaultdict

from src import db
from src.context.sources import pbp

K = {"strikeout", "strikeout_double_play", "strikeout_triple_play"}
BB = {"walk"}   # UNINTENTIONAL only — see below
HBP = {"hit_by_pitch"}
HITS = {"single", "double", "triple", "home_run"}
#: A plate appearance ended. Excludes pickoffs, steals, wild pitches etc,
#: which are not plate appearances and would inflate every denominator.
#: TWO CONFOUNDS EXCLUDED, and they sit exactly where the effect appears.
#: An INTENTIONAL walk is a manager's decision that only ever happens with
#: runners on, and counting it inflates the walk channel by construction.
#: A SACRIFICE BUNT is likewise a runners-on-only play, and it enters the
#: denominator as a guaranteed non-strikeout, depressing K% with runners on
#: for a reason that has nothing to do with the pitcher.
PA_EVENTS = K | BB | HBP | HITS | {
    "field_out", "force_out", "grounded_into_double_play", "sac_fly",
    "field_error", "fielders_choice", "fielders_choice_out",
    "double_play", "triple_play", "sac_fly_double_play", "other_out"}


def _one(gid):
    out = defaultdict(lambda: defaultdict(int))
    try:
        for play, bases, outs, _a, _h in pbp.plays(gid):
            ev = ((play.get("result") or {}).get("eventType") or "")
            if ev not in PA_EVENTS:
                continue
            on = sum(1 for b in bases if b)
            risp = bool(bases[1] or bases[2])
            for cell in (("ALL",),
                         ("empty" if on == 0 else "runners on",),
                         ("RISP" if risp else "no RISP",)):
                c = out[cell[0]]
                c["pa"] += 1
                c["k"] += ev in K
                c["bb"] += ev in BB
                c["hbp"] += ev in HBP
                c["hr"] += ev == "home_run"
                c["h"] += ev in HITS
    except Exception:
        return None
    return dict((k, dict(v)) for k, v in out.items())


def main(argv):
    cap = int(argv[0]) if argv else 1500
    with db.connect() as c:
        gids = [r["game_id"] for r in c.execute(
            "select game_id from games where sport='mlb' and status='Final' "
            "and date like '2026%' order by date")][:cap]
    with mp.get_context("fork").Pool(8) as p:
        got = [g for g in p.map(_one, gids, chunksize=16) if g]
    agg = defaultdict(lambda: defaultdict(int))
    for g in got:
        for cell, c in g.items():
            for k, v in c.items():
                agg[cell][k] += v
    print(f"  {len(got):,} games\n")
    print(f"  {'state':<14}{'PA':>9}{'K%':>8}{'BB%':>8}{'HBP%':>8}"
          f"{'HR%':>8}{'H%':>8}")
    for cell in ("ALL", "empty", "runners on", "no RISP", "RISP"):
        c = agg.get(cell)
        if not c:
            continue
        n = c["pa"]
        print(f"  {cell:<14}{n:>9,}"
              + "".join(f"{100 * c[k] / n:>8.2f}"
                        for k in ("k", "bb", "hbp", "hr", "h")))
    e, r = agg["empty"], agg["runners on"]
    print(f"\n  {'channel':<10}{'empty':>9}{'runners':>9}{'rel':>9}{'se':>9}")
    for k in ("k", "bb", "hbp", "hr", "h"):
        pe, pr = e[k] / e["pa"], r[k] / r["pa"]
        se = (pe * (1 - pe) / e["pa"] + pr * (1 - pr) / r["pa"]) ** 0.5
        print(f"  {k:<10}{pe:>9.4f}{pr:>9.4f}{pr / pe - 1:>+8.1%}"
              f"{(pr - pe) / se:>+9.1f}")
    print("\n  last column is sigma on the DIFFERENCE, not on either rate.")


if __name__ == "__main__":
    main(sys.argv[1:])
