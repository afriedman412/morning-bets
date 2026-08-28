"""Do TTO_MULT and STATE_MULT double-count? A scoping check.

    venv/bin/python -m scratchpad.tto_state_overlap [n_games]

QUESTION    `TTO_MULT` was counted per lineup pass and controls
            survivorship and batter mix. It does NOT control base-out
            state, and `STATE_MULT` now ships. If the first pass sees a
            different mix of field states than the third, part of the
            measured TTO decay IS the field-state effect and the two
            multipliers are charging for the same baseball twice.

TEST        For each starter, bin his plate appearances by lineup pass and
            by (men on, outs). Then push each pass's state distribution
            through the SHIPPED `STATE_MULT` to get the K multiplier the
            state table alone would produce for that pass. The gap between
            passes is the double-counted part.

POWER       This is a distribution over 12 cells on tens of thousands of
            plate appearances per pass; it is precise. What it CANNOT say
            is whether removing the overlap improves anything — that is a
            separate A/B.
"""
from __future__ import annotations

import multiprocessing as mp
import sys
from collections import defaultdict

from src import db
from src.context import sim
from src.context.sources import pbp

K_EV = {"strikeout", "strikeout_double_play", "strikeout_triple_play"}
PA_EV = K_EV | {"single", "double", "triple", "home_run", "walk",
                "hit_by_pitch", "field_out", "force_out",
                "grounded_into_double_play", "sac_fly", "field_error",
                "fielders_choice", "fielders_choice_out", "double_play",
                "triple_play", "sac_fly_double_play", "other_out"}


def _one(gid):
    """(pass, men on, outs) -> [pa, k] for the two STARTERS only."""
    out = defaultdict(lambda: [0, 0])
    try:
        starters, faced = {}, defaultdict(int)
        for play, bases, outs, _a, _h in pbp.plays(gid):
            ev = (play.get("result") or {}).get("eventType") or ""
            if ev not in PA_EV:
                continue
            mu = play.get("matchup") or {}
            pid = (mu.get("pitcher") or {}).get("id")
            half = (play.get("about") or {}).get("isTopInning")
            if pid is None or half is None:
                continue
            # The FIRST arm to appear for a side is that side's starter.
            starters.setdefault(half, pid)
            if starters[half] != pid:
                continue
            faced[pid] += 1
            tto = min((faced[pid] - 1) // 9 + 1, 3)
            cell = (tto, sum(1 for b in bases if b), outs)
            out[cell][0] += 1
            out[cell][1] += ev in K_EV
    except Exception:
        return None
    return {k: v for k, v in out.items()}


def main(argv):
    cap = int(argv[0]) if argv else 2000
    with db.connect() as c:
        gids = [r["game_id"] for r in c.execute(
            "select game_id from games where sport='mlb' and status='Final'"
            " and date like '2026%' order by date")][:cap]
    with mp.get_context("fork").Pool(8) as p:
        got = [g for g in p.map(_one, gids, chunksize=16) if g]
    agg = defaultdict(lambda: [0, 0])
    for g in got:
        for k, v in g.items():
            agg[k][0] += v[0]
            agg[k][1] += v[1]
    print(f"  {len(got):,} games, starters only\n")
    print(f"  {'pass':>5}{'PA':>9}{'K%':>8}{'men on':>9}"
          f"{'state-implied K mult':>22}")
    rows = {}
    for tto in (1, 2, 3):
        cells = {(o, u): agg[(tto, o, u)]
                 for o in (0, 1, 2, 3) for u in (0, 1, 2)
                 if (tto, o, u) in agg}
        n = sum(v[0] for v in cells.values())
        k = sum(v[1] for v in cells.values())
        on = sum(v[0] for c, v in cells.items() if c[0] > 0) / n
        # The K multiplier the SHIPPED state table alone would produce for
        # this pass's mix of field states.
        implied = sum(v[0] * sim.STATE_MULT.get(c, {}).get("k_pct", 1.0)
                      for c, v in cells.items()) / n
        rows[tto] = implied
        print(f"  {tto:>5}{n:>9,}{k / n:>8.4f}{on:>9.3f}{implied:>22.4f}")
    print(f"\n  TTO_MULT k_pct, shipped: "
          + "  ".join(f"{t} {sim.TTO_MULT[t]['k_pct']:.4f}" for t in (1, 2, 3)))
    print(f"  state-implied, rebased to pass 1 = shipped pass 1:")
    scale = sim.TTO_MULT[1]["k_pct"] / rows[1]
    for t in (1, 2, 3):
        print(f"    pass {t}   state alone {rows[t] * scale:.4f}   "
              f"TTO charges {sim.TTO_MULT[t]['k_pct']:.4f}")
    span_state = rows[1] / rows[3] - 1.0
    span_tto = sim.TTO_MULT[1]["k_pct"] / sim.TTO_MULT[3]["k_pct"] - 1.0
    print(f"\n  pass-1-over-pass-3 K spread:")
    print(f"    TTO_MULT charges      {span_tto:+.2%}")
    print(f"    field state alone     {span_state:+.2%}")
    print(f"    overlap               {span_state / span_tto:.1%} of the "
          f"TTO decay is field state the model now ALSO charges for")

    # POSITIVE CONTROL. A flat result and a harness that cannot see the
    # state distribution shift produce identical output. Substitute a table
    # with a KNOWN men-on strikeout effect and confirm the span opens up.
    # The men-on share really does move 0.367 -> 0.440 across the passes,
    # so if the real table produces nothing, it is because ITS OWN
    # multipliers cancel across that shift, not because the shift is absent.
    print("\n  POSITIVE CONTROL — a fake table at -20% K with men on:")
    fake = {(o, u): {"k_pct": 0.80 if o else 1.0}
            for o in (0, 1, 2, 3) for u in (0, 1, 2)}
    ctl = {}
    for tto in (1, 2, 3):
        cells = {(o, u): agg[(tto, o, u)]
                 for o in (0, 1, 2, 3) for u in (0, 1, 2)
                 if (tto, o, u) in agg}
        n = sum(v[0] for v in cells.values())
        ctl[tto] = sum(v[0] * fake[c]["k_pct"] for c, v in cells.items()) / n
    print(f"    implied by pass: "
          + "  ".join(f"{t} {ctl[t]:.4f}" for t in (1, 2, 3)))
    print(f"    span {ctl[1] / ctl[3] - 1.0:+.2%}  <- the harness sees a "
          f"real effect when one is there")


if __name__ == "__main__":
    main(sys.argv[1:])
