"""The recent-workload term (item 36): lookup discipline and wiring.

Mutation-verified 2026-09-19: the leak check fails when `<` becomes
`<=` in `gap_for`, the ambiguity check fails with the `_AMBIG` gate
removed, and the wiring check fails with the `build_side` application
deleted or the coefficient negated. The MIN_PRIOR floor is NOT
claimed: with WINDOW == MIN_PRIOR the gap at or under the floor is
zero by arithmetic (window == season), so the guard is a stated
contract, not killable behaviour — the first fixture here planted
FLAT pitch counts and "verified" two mutations that were never
tested, which is exactly the degenerate-fixture trap the battery's
Fading check recorded on 2026-09-17.
"""
from __future__ import annotations

import random

from src.context import game, leash, sim, usage


def _plant(idx, ambig=()):
    usage._reset()
    for k in idx:
        idx[k].sort()
    usage._INDEX = idx
    usage._AMBIG = set(ambig)


def _restore():
    usage._reset()


def check_usage_gap_reads_only_prior_starts_same_season():
    """Priced off the record BEFORE the date: the start being priced,
    later starts, and other seasons are all invisible.

    Planted: eight 95-pitch starts then four at 60. On the morning of
    the FIRST 60 the gap is exactly zero (anything else leaks that
    day's own start); after all four the window is fully collapsed
    while the season mean still remembers the 95s."""
    try:
        idx = {"A": [(f"2026-04-{d:02d}", 95.0) for d in range(1, 9)]
               + [(f"2026-06-{d:02d}", 60.0) for d in range(1, 5)]
               + [("2026-07-15", 110.0),      # later date: unseen
                  ("2025-08-01", 45.0)]}      # other season: unseen
        _plant(idx)
        assert usage.gap_for("A", "2026-06-01") == 0.0
        want = 60.0 - (8 * 95.0 + 4 * 60.0) / 12
        got = usage.gap_for("A", "2026-07-01")
        assert abs(got - want) < 1e-12, (got, want)
        # the own-date probe that catches `<` becoming `<=`: on the
        # 110-pitch start's own date, that start must not contribute.
        got2 = usage.gap_for("A", "2026-07-15")
        assert abs(got2 - want) < 1e-12, (got2, want)
    finally:
        _restore()


def check_usage_gap_is_neutral_when_unknown():
    """Fewer than MIN_PRIOR prior starts, an unknown name, a missing
    date, or an AMBIGUOUS name (two pitcher ids, one string — the
    Sandlin trap) -> exactly 0.0. Silent-neutral, never a guess."""
    try:
        # NON-FLAT fixtures on purpose: a flat sequence has a zero gap
        # through ANY code path and verifies nothing (the degenerate-
        # fixture trap). Twin's real gap without the gate is -17.5.
        _plant({"A": [(f"2026-05-{d:02d}", 60.0 + 10 * d)
                      for d in range(1, 4)],
                "Twin": [(f"2026-05-{d:02d}", 95.0) for d in range(1, 5)]
                + [(f"2026-06-{d:02d}", 60.0) for d in range(1, 5)]},
               ambig=("Twin",))
        assert usage.gap_for("A", "2026-06-01") == 0.0      # 3 priors
        assert usage.gap_for("Nobody", "2026-06-01") == 0.0
        assert usage.gap_for("A", None) == 0.0
        assert usage.gap_for("", "2026-06-01") == 0.0
        assert usage.gap_for("Twin", "2026-07-01") == 0.0   # ambiguous
    finally:
        _restore()


def check_usage_gap_moves_the_hook_only_when_on():
    """`build_side` lands the term on the per-start hook's team_offset
    when USE_USAGE_GAP is on and leaves the hook exactly alone when
    off — and a FADING arm (negative gap) must get a POSITIVE offset,
    a shorter leash. Deterministic: no variate consumed, so the drawn
    pen is identical either side (empty pen here; the velo checks
    already pin the stream pairing)."""
    p = sim.PitcherRates(name="Nobody Fixture", k_pct=0.22, bb_pct=0.08,
                         hr_pct=0.03, babip=0.29, pa=500)
    nine = [sim.BatterRates(name=f"b{i}", k_pct=0.22, bb_pct=0.08,
                            hr_pct=0.03, babip=0.29, pa=400)
            for i in range(9)]
    old = sim.USE_USAGE_GAP
    try:
        _plant({"Nobody Fixture":
                [(f"2026-04-{d:02d}", 95.0) for d in range(1, 9)]
                + [(f"2026-06-{d:02d}", 60.0) for d in range(1, 5)]})
        gap = usage.gap_for("Nobody Fixture", "2026-07-01")
        assert gap < -8, gap                      # a real planted fade
        sides = {}
        for flag in (False, True):
            sim.USE_USAGE_GAP = flag
            sides[flag] = game.build_side(
                p, [], nine, sim.Hook(), random.Random(5),
                team=None, apply_leash=True, date="2026-07-01")
        base = sides[False].hook.team_offset
        want = leash.offset_for(usage.USAGE_OUTS_PER_PITCH * gap)
        assert want > 0.05, want    # fading -> shorter leash, and real
        got = sides[True].hook.team_offset - base
        assert abs(got - want) < 1e-12, (got, want)
    finally:
        sim.USE_USAGE_GAP = old
        _restore()
