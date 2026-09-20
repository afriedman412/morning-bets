"""DID THE RECENCY WEIGHT MOVE THE SIM TOWARD REALITY? — TODO 15's falsifier
for the recency weight.

    venv/bin/python -m scratchpad.opener_decay_score [n_sims_per_state]

WHY NOT THE BATTERY, AND WHY NOT `opener_outs.py`. The battery ran clean
around this change — no row moved by more than one se over four folds —
which is the RIGHT result for a 2-3% population and says nothing about
whether the change helped. `PLAN-opener-bullpen.md` is explicit: judge this
in the AFFECTED GAMES. And `opener_outs.py` cannot do it, because it
defines its population with a flat average under 11 outs — the very
estimator being replaced — so the arms this change adds and drops fall
outside the population it scores.

THE POPULATION IS THE DISAGREEMENT. Score exactly the starts where
`opener_record` returns a different answer with `USE_OPENER_DECAY` on and
off, split by direction, because the two directions have opposite
predictions and pooling them would cancel:

  NEWLY CAUGHT     the decay flags him and the flat mean did not — a
                   converted opener. Sim outs should FALL toward his real
                   (short) line.
  NEWLY RELEASED   the flat mean flagged him and the decay does not — an
                   arm back in the rotation. Sim outs should RISE.

FALSIFIER, pre-registered: if the flag moves simulated outs AWAY from the
real mean in either direction, the change is wrong however good its
classification table looked. A wash in one direction and a gain in the
other is a partial result and must be reported as one.

Draws are PAIRED — the same seed per (game, draw index) in both states —
so the comparison is within-game and the noise mostly cancels. Note the
flag is not stream-paired in the sense `USE_OPENER_EXIT` is (see
`game.USE_OPENER_DECAY`): a flagged arm consumes a draw an unflagged one
does not, so downstream events differ. That is what is being measured.
"""
from __future__ import annotations

import random
import sys

from src import db
from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src

FOLDS = [(2023, "2023-07-01"), (2024, "2024-07-01"),
         (2025, "2025-07-01"), (2026, "2026-07-01")]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 60


def _flagged(nm, date) -> bool:
    return game.opener_record(nm, date) is not None


def direction(nm, date):
    """'caught', 'released' or None — which way the flag changes him."""
    if not nm or not date:
        return None
    prev = game.USE_OPENER_DECAY
    try:
        game.USE_OPENER_DECAY = True
        on = _flagged(nm, date)
        game.USE_OPENER_DECAY = False
        off = _flagged(nm, date)
    finally:
        game.USE_OPENER_DECAY = prev
    if on and not off:
        return "caught"
    if off and not on:
        return "released"
    return None


def stats(v):
    n = len(v)
    m = sum(v) / n
    sd = (sum((x - m) ** 2 for x in v) / (n - 1)) ** 0.5 if n > 1 else 0.0
    return m, sd, n


def main() -> None:
    real = {"caught": [], "released": []}
    sim_outs = {("caught", True): [], ("caught", False): [],
                ("released", True): [], ("released", False): []}
    for yr, cut in FOLDS:
        pairs = cal.paired_cases(season=yr, rates_before=cut, since=cut)
        lg = sim.league(season=yr, before=cut)
        pens = rate_src.bullpens(lg, season=yr, before=cut)
        hits = []
        for gid, pair in sorted(pairs.items()):
            sides = []
            for s, c_ in (("away", pair[0]), ("home", pair[1])):
                d = direction(c_[0].get("player_name"), c_[0].get("date"))
                if d:
                    sides.append((s, d, c_[0]["o"]))
            if sides:
                hits.append((gid, pair, sides))
        for gi, (gid, pair, sides) in enumerate(hits):
            for _, d, o in sides:
                real[d].append(o)
            for state in (True, False):
                game.USE_OPENER_DECAY = state
                for i in range(N):
                    rng = random.Random(yr * 1000003 + gi * 1009 + i)
                    r = cal.replay(pair, lg, pens, rng)
                    for s, d, _ in sides:
                        sp = r.away_sp if s == "away" else r.home_sp
                        sim_outs[(d, state)].append(sp.outs)
            game.USE_OPENER_DECAY = True
        n_c = sum(1 for _, _, ss in hits for s in ss if s[1] == "caught")
        n_r = sum(1 for _, _, ss in hits for s in ss if s[1] == "released")
        print(f"fold {yr}: {len(hits)} affected games "
              f"({n_c} newly caught, {n_r} newly released)", flush=True)

    for d, expect in (("caught", "should FALL"), ("released", "should RISE")):
        if not real[d]:
            print(f"\n{d.upper()}: no starts")
            continue
        mr, sdr, nr = stats(real[d])
        print(f"\n{d.upper()} — {nr} real starts, sim {expect}")
        print(f"  real outs         {mr:6.2f}   (sd {sdr:.2f}, "
              f"se {sdr / nr ** 0.5:.2f})")
        for state, tag in ((False, "off"), (True, "on ")):
            m, sd, n = stats(sim_outs[(d, state)])
            print(f"  sim decay {tag}     {m:6.2f}   "
                  f"|error| {abs(m - mr):5.2f}   ({n} draws)")
        off = stats(sim_outs[(d, False)])[0]
        on = stats(sim_outs[(d, True)])[0]
        gain = abs(off - mr) - abs(on - mr)
        verdict = "TOWARD reality" if gain > 0 else "AWAY from reality"
        print(f"  the flag moves it {abs(on - off):.2f} outs, {verdict}"
              f" by {abs(gain):.2f}")


if __name__ == "__main__":
    main()
