"""Run the REAL game engine against a fixture matchup.

WHY THIS EXISTS AND WHAT IT IS NOT. Until 2026-08-25 there were two engines:
`sim.simulate_start` walked one pitching side in isolation, and
`game.simulate_game` played both. They shared `pa_outcome`, `apply_pa` and
`baserunning` and diverged everywhere else — the one-sided loop had no
bullpen, no live score, no boundary hook and no margin, so `Hook.per_margin`
was structurally unreachable and sat at zero forever. Every measured null in
the dead list was produced on it. The cost of keeping both was measured on
day eight: a mechanism was wired into one and silently absent from the other
for a full day, and a paired ladder read EXACTLY +0.0000 because of it.

So the second engine is gone, and this is NOT a replacement for it. Nothing
here walks a plate appearance. `one_side` builds two real `game.Side`s and
calls `game.simulate_game` — the same function `calibrate.replay`, `fitf5`,
`f5_market` and `price` call — then hands back one starter's line.

THE OPPONENT IS A MIRROR, which is exactly what production must never do:
`price.simulate_slate_game` DECLINES when the other starter is missing,
because inventing the other club invents the score. That is fine here and
only here, where both sides are fixtures anyway and the question is whether
a home run clears the bases.

Readers stay in `sim` — `prob_over`, `prob_push` and `distribution` are what
`price` and `quote` call, so a copy here would be a second thing to keep
right. `check_nothing_prices_through_the_fixtures` guards the boundary in
the other direction.
"""
from __future__ import annotations

import random

from src.context import game


def one_side(pitcher, faces, lg, hook=None, rng=None, park=None,
             innings=9, seed=0):
    """One starter's line out of a real game. -> sim.StartResult

    `faces` is THE NINE THIS PITCHER FACES. The name is deliberate: `a_nine`
    read as "the away team's nine", held the opposite, and put seven modules
    on the wrong lineup for eight days.

    `hook` is used AS GIVEN with no leash applied — a check that hands over a
    hook is asserting on that hook, not on whatever `hook_leash.json` holds
    today. The pen is empty, so a pulled starter simply stops accumulating:
    `Side.line` is his own and `next_arm` swaps `cur_line` out from under it.
    """
    rng = rng if rng is not None else random.Random(seed)
    a = game.build_side(pitcher, [], faces, hook, rng, apply_leash=False)
    h = game.build_side(pitcher, [], faces, hook, rng, apply_leash=False)
    return game.simulate_game(a, h, lg, rng, innings=innings,
                              park=park).away_sp


def starts(pitcher, faces, lg, n=100, hook=None, seed=0, park=None,
           innings=9):
    """`n` starter lines from `n` real games. -> [sim.StartResult]

    Deterministic for a seed, and the draws are shared down a line curve —
    reading several thresholds off ONE list is what keeps `sim.prob_over`
    monotone in the line.
    """
    rng = random.Random(seed)
    return [one_side(pitcher, faces, lg, hook=hook, rng=rng, park=park,
                     innings=innings) for _ in range(n)]
