"""Does the at-bat depend on the CONTEXT — outs, runners, score? Counted.

    venv/bin/python -m scratchpad.context_pa [max_games]

`sim.pa_from` takes a resolved matchup and a times-through-order index.
Not the outs, not the bases, not the score. This counts whether real rates
move with each of the three.

AND IT COUNTS THE VOIDED PLATE APPEARANCE. A caught stealing or pickoff
that records the THIRD OUT ends the inning in the middle of an at-bat: the
batter's plate appearance never completes and he leads off the next inning
with a fresh count. `game._half_inning` resolves the plate appearance
FIRST and rolls `sim.baserunning` after it, so that at-bat is played to
completion and then the inning ends. The model therefore plays a plate
appearance that reality erases, and the lineup pointer advances one slot
further than it should have.
"""
from __future__ import annotations

import multiprocessing as mp
import sys
from collections import defaultdict

from src import db
from src.context.sources import pbp

K_EV = {"strikeout", "strikeout_double_play", "strikeout_triple_play"}
HIT_EV = {"single", "double", "triple", "home_run"}
PA_EV = K_EV | HIT_EV | {"walk", "hit_by_pitch",
    "field_out", "force_out", "grounded_into_double_play", "sac_fly",
    "field_error", "fielders_choice", "fielders_choice_out",
    "double_play", "triple_play", "sac_fly_double_play", "other_out"}
#: Baserunning outs that can end an inning with no batter retired.
RUNNER_OUT = {"caught_stealing_2b", "caught_stealing_3b",
              "caught_stealing_home", "pickoff_1b", "pickoff_2b",
              "pickoff_3b", "pickoff_caught_stealing_2b",
              "pickoff_caught_stealing_3b", "pickoff_caught_stealing_home",
              "other_out"}


def _one(gid):
    out = defaultdict(lambda: [0, 0, 0, 0])     # pa, k, bb, hit
    ends = [0, 0]                               # runner-outs, of which 3rd
    try:
        plays = list(pbp.plays(gid))
    except Exception:
        return None
    for play, bases, outs, a, h in plays:
        ev = (play.get("result") or {}).get("eventType") or ""
        top = (play.get("about") or {}).get("isTopInning")
        if ev in RUNNER_OUT and ev not in PA_EV:
            ends[0] += 1
            if outs == 2:
                ends[1] += 1
        if ev not in PA_EV:
            continue
        # Margin from the PITCHING side's point of view.
        lead = (a - h) if top else (h - a)
        band = ("trail 4+" if lead <= -4 else "trail 1-3" if lead < 0
                else "tied" if lead == 0
                else "lead 1-3" if lead <= 3 else "lead 4+")
        on = sum(1 for b in bases if b)
        for cell in (f"outs {outs}", band,
                     "bases empty" if on == 0 else f"{on} on"):
            c = out[cell]
            c[0] += 1
            c[1] += ev in K_EV
            c[2] += ev == "walk"
            c[3] += ev in HIT_EV
    return dict(out), ends


def main(argv):
    cap = int(argv[0]) if argv else 1500
    with db.connect() as c:
        gids = [r["game_id"] for r in c.execute(
            "select game_id from games where sport='mlb' and status='Final'"
            " and date like '2026%' order by date")][:cap]
    with mp.get_context("fork").Pool(8) as p:
        got = [g for g in p.map(_one, gids, chunksize=16) if g]
    agg = defaultdict(lambda: [0, 0, 0, 0])
    ends = [0, 0]
    for d, e in got:
        for k, v in d.items():
            for i in range(4):
                agg[k][i] += v[i]
        ends[0] += e[0]
        ends[1] += e[1]
    n_games = len(got)
    print(f"  {n_games:,} games\n")
    print(f"  {'context':<14}{'PA':>9}{'K%':>8}{'BB%':>8}{'H%':>8}")
    order = ["outs 0", "outs 1", "outs 2", "", "bases empty", "1 on",
             "2 on", "3 on", "", "trail 4+", "trail 1-3", "tied",
             "lead 1-3", "lead 4+"]
    for k in order:
        if not k:
            print()
            continue
        c = agg.get(k)
        if not c or not c[0]:
            continue
        print(f"  {k:<14}{c[0]:>9,}{100*c[1]/c[0]:>8.2f}"
              f"{100*c[2]/c[0]:>8.2f}{100*c[3]/c[0]:>8.2f}")

    print(f"\n  === THE VOIDED PLATE APPEARANCE ===")
    print(f"  runner outs (CS / pickoff):        {ends[0]:,}")
    print(f"  of which recorded the THIRD out:   {ends[1]:,}"
          f"   ({ends[1]/n_games:.3f} per game)")
    print(f"\n  Each of those erases an at-bat in progress. The model")
    print(f"  resolves the plate appearance first and rolls baserunning")
    print(f"  after, so it plays that at-bat to completion instead —")
    print(f"  ~{ends[1]/n_games:.2f} extra plate appearances a game, and the")
    print(f"  lineup pointer advances a slot it should not have.")


if __name__ == "__main__":
    main(sys.argv[1:])
