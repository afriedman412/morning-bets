"""WHICH CHANNEL is the missing traffic? Decomposed, not aggregated.

    venv/bin/python -m scratchpad.traffic [n_games] [n_sims]

The oldest open defect in this model is that too few men reach base — outs
per plate appearance about 1.4% high, runs 3-5% light, sides scoring 5+ at
15.5% against a real 17.6%. Every one of those is the same statement.

WHAT HAS NEVER BEEN DONE IS SPLITTING IT. There are only five ways to reach
base — hit, walk, hit-by-pitch, home run, error — and "we are short of
baserunners" says nothing about which. Four of the five come from measured
per-player rates; ERRORS come from one league constant (`sim.ROE_PER_OUT`),
and an error is the one that EXTENDS an inning rather than merely occupying
a base.

So this counts the plate-appearance composition on both sides of the same
games: what the simulator produces, against what actually happened, per
1,000 plate appearances. A channel that matches is exonerated. A channel
that is short has a name and a size.

MEASURED AT THE OUTCOME, NOT THE BOXSCORE. Simulated outcomes are tallied by
instrumenting `sim.pa_outcome`, so what is counted is exactly what the
engine decided rather than a downstream summary. The actual side is counted
off play-by-play events for the same reason.
"""
from __future__ import annotations

import random
import sys
from collections import Counter

from src.context import calibrate as cal
from src.context import sim
from src.context.sources import pbp, rates as rate_src

#: pbp event -> the channel it belongs to. Anything unlisted is an out.
EVENT = {
    "strikeout": "K", "strikeout_double_play": "K",
    "walk": "BB", "intent_walk": "BB", "hit_by_pitch": "HBP",
    "home_run": "HR", "single": "1B", "double": "2B", "triple": "3B",
    "field_error": "ROE",
    # SAC on BOTH sides or the denominators differ. The simulator emits it
    # as its own outcome and it was being excluded there while falling into
    # OUT here, which deflated every actual rate by ~1%.
    "sac_fly": "SAC", "sac_bunt": "SAC",
    "sac_fly_double_play": "SAC", "sac_bunt_double_play": "SAC",
}
SKIP = {"game_advisory", "pitching_substitution", "offensive_substitution",
        "defensive_switch", "defensive_substitution", "runner_placed",
        "ejection", "injury"}

REACH = ("1B", "2B", "3B", "HR", "BB", "HBP", "ROE")


def actual(gids) -> Counter:
    t = Counter()
    for g in gids:
        try:
            d = pbp.fetch(g)
        except Exception:
            continue
        if not d:
            continue
        for p in (d.get("allPlays") or []):
            ev = ((p.get("result") or {}).get("eventType") or "")
            if ev in SKIP:
                continue
            t[EVENT.get(ev, "OUT")] += 1
    return t


def simulated(pairs, n_sims) -> Counter:
    t = Counter()
    real = sim.pa_outcome

    def spy(*a, **kw):
        o = real(*a, **kw)
        t[o] += 1
        return o

    sim.pa_outcome = spy
    try:
        lg = sim.league()
        pens = rate_src.bullpens(lg)
        rng = random.Random(3)
        for pair in pairs:
            for _ in range(n_sims):
                cal.replay(pair, lg, pens, rng)
    finally:
        sim.pa_outcome = real
    return t


def main(argv):
    if "--pen-league" in argv:
        rate_src.USE_RELIEVER_LEAGUE = True
        print("  RELIEVER LEAGUE as the bullpen's shrink target")
    n_games = int(argv[0]) if argv else 300
    n_sims = int(argv[1]) if len(argv) > 1 else 6
    pairs = cal.paired_cases(since="2026-07-01", rates_before="2026-07-01")
    gids = list(pairs)[:n_games]
    print(f"  {len(gids)} games, {n_sims} sims each", flush=True)

    sm = simulated([pairs[g] for g in gids], n_sims)
    ac = actual(gids)

    def rate(t, key):
        # SAC is not a plate appearance in the actual feed's sense and the
        # sim emits it separately; both denominators exclude it so the two
        # sides are on one footing.
        tot = sum(v for k, v in t.items() if k != "SAC")
        return 1000.0 * t.get(key, 0) / tot if tot else 0.0

    print(f"\n  PER 1,000 PLATE APPEARANCES")
    print(f"  {'channel':<10}{'sim':>9}{'actual':>9}{'diff':>9}{'rel':>9}")
    for key in ("K", "BB", "HBP", "HR", "1B", "2B", "3B", "ROE", "OUT"):
        s, a = rate(sm, key), rate(ac, key)
        rel = (s - a) / a * 100 if a else 0.0
        print(f"  {key:<10}{s:>9.1f}{a:>9.1f}{s - a:>+9.1f}{rel:>+8.1f}%")

    sr = sum(rate(sm, k) for k in REACH)
    ar = sum(rate(ac, k) for k in REACH)
    print(f"\n  {'REACHED':<10}{sr:>9.1f}{ar:>9.1f}{sr - ar:>+9.1f}"
          f"{(sr - ar) / ar * 100:>+8.1f}%")
    print("\n  A channel that matches is exonerated. The deficit has to live")
    print("  somewhere in this table, and every row but ROE comes from a")
    print("  per-player measured rate.")


if __name__ == "__main__":
    main(sys.argv[1:])
