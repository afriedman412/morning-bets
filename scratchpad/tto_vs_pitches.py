"""Is the times-through-the-order decay FAMILIARITY or just FATIGUE?

    venv/bin/python -m scratchpad.tto_vs_pitches [max_games]

`tto.py` controls survivorship and batter mix and then says plainly that
"fatigue and familiarity are not separable here. A pitcher deeper into a
game is both more tired and better known." That is the open question and
it decides whether `TTO_MULT` is the right shape of term at all: if the
decay is really pitch count, a term keyed on BATTERS FACED charges an
efficient pitcher the same penalty as a labouring one.

THE SEPARATION. Times through the order and pitch count are collinear but
NOT identical — some starters reach the third pass at 60 pitches and
others at 95. So bucket on BOTH and read the table two ways:

  * down a PITCH column, TTO rising  -> familiarity is real
  * across a TTO row, pitches rising -> fatigue is real

If the whole effect is fatigue, the TTO gradient vanishes once pitch count
is held fixed and `TTO_MULT` is keyed on the wrong variable.

SURVIVORSHIP IS CONTROLLED THE SAME WAY `tto.py` DOES IT: only starts that
reached the third time through are counted, so every cell is the same
population of pitcher-days.
"""
from __future__ import annotations

import multiprocessing as mp
import sys
from collections import defaultdict

from src import db
from src.context.sources import pbp

K_EV = {"strikeout", "strikeout_double_play", "strikeout_triple_play"}
BB_EV = {"walk"}
HIT_EV = {"single", "double", "triple", "home_run"}
PA_EV = K_EV | BB_EV | HIT_EV | {
    "hit_by_pitch", "field_out", "force_out", "grounded_into_double_play",
    "sac_fly", "field_error", "fielders_choice", "fielders_choice_out",
    "double_play", "triple_play", "sac_fly_double_play", "other_out"}

PITCH_BUCKETS = ((0, 29), (30, 44), (45, 59), (60, 74), (75, 89), (90, 200))


def _one(gid):
    """-> {(tto, pitch_bucket): [pa, k, bb, hit]} for the two starters."""
    out = defaultdict(lambda: [0, 0, 0, 0])
    try:
        d = pbp.fetch(gid)
    except Exception:
        return None
    if not d:
        return None
    # First pitcher seen on each half is that side's starter.
    starter, bf, pitches = {}, defaultdict(int), defaultdict(int)
    rows = []
    for play in d.get("allPlays") or []:
        ab = play.get("about") or {}
        side = "away" if ab.get("isTopInning") else "home"
        pid = ((play.get("matchup") or {}).get("pitcher") or {}).get("id")
        if pid is None:
            continue
        starter.setdefault(side, pid)
        if pid != starter[side]:
            continue                       # starter only
        ev = (play.get("result") or {}).get("eventType") or ""
        n_pitch = sum(1 for e in (play.get("playEvents") or [])
                      if e.get("isPitch"))
        if ev in PA_EV:
            # Pitch count BEFORE this plate appearance, and the TTO index
            # he is on — both are the state he faced the hitter in.
            rows.append((side, bf[side] // 9 + 1, pitches[side], ev))
            bf[side] += 1
        pitches[side] += n_pitch
    for side, tto, pc, ev in rows:
        if bf[side] < 19:        # never reached a third pass: survivorship
            continue
        if tto > 3:
            continue
        b = next((i for i, (lo, hi) in enumerate(PITCH_BUCKETS)
                  if lo <= pc <= hi), None)
        if b is None:
            continue
        c = out[(tto, b)]
        c[0] += 1
        c[1] += ev in K_EV
        c[2] += ev in BB_EV
        c[3] += ev in HIT_EV
    return dict(out)


def main(argv):
    cap = int(argv[0]) if argv else 2000
    with db.connect() as c:
        gids = [r["game_id"] for r in c.execute(
            "select game_id from games where sport='mlb' and status='Final'"
            " and date like '2026%' order by date")][:cap]
    with mp.get_context("fork").Pool(8) as p:
        got = [g for g in p.map(_one, gids, chunksize=16) if g]
    agg = defaultdict(lambda: [0, 0, 0, 0])
    for g in got:
        for k, v in g.items():
            for i in range(4):
                agg[k][i] += v[i]
    print(f"  {len(got):,} games, starters only, starts that reached the "
          f"third pass\n")
    print("  K% by times-through-order (down) and pitches thrown so far "
          "(across)")
    print(f"  {'':<6}" + "".join(f"{f'{lo}-{hi}':>11}"
                                 for lo, hi in PITCH_BUCKETS))
    for tto in (1, 2, 3):
        row = f"  TTO {tto:<2}"
        for b in range(len(PITCH_BUCKETS)):
            c = agg.get((tto, b))
            if not c or c[0] < 150:
                row += f"{'-':>11}"
            else:
                row += f"{100 * c[1] / c[0]:>8.1f}%{'':>2}"
        print(row)
    print(f"\n  n per cell")
    for tto in (1, 2, 3):
        row = f"  TTO {tto:<2}"
        for b in range(len(PITCH_BUCKETS)):
            c = agg.get((tto, b))
            row += f"{(c[0] if c else 0):>11,}"
        print(row)
    # THE TWO READS, as one number each.
    print("\n  THE TWO READS")
    for b in range(len(PITCH_BUCKETS)):
        cells = [agg.get((t, b)) for t in (1, 2, 3)]
        ok = [c for c in cells if c and c[0] >= 150]
        if len(ok) >= 2:
            lo, hi = ok[0], ok[-1]
            print(f"    within pitches {PITCH_BUCKETS[b][0]}-"
                  f"{PITCH_BUCKETS[b][1]}: K% {100*lo[1]/lo[0]:.1f} -> "
                  f"{100*hi[1]/hi[0]:.1f}  (TTO effect, fatigue held)")
    for tto in (1, 2, 3):
        cells = [agg.get((tto, b)) for b in range(len(PITCH_BUCKETS))]
        ok = [c for c in cells if c and c[0] >= 150]
        if len(ok) >= 2:
            lo, hi = ok[0], ok[-1]
            print(f"    within TTO {tto}: K% {100*lo[1]/lo[0]:.1f} -> "
                  f"{100*hi[1]/hi[0]:.1f}  (fatigue effect, TTO held)")


if __name__ == "__main__":
    main(sys.argv[1:])
