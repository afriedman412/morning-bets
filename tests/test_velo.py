"""The velocity term (item E): lookup discipline and wiring.

Every check here was verified by mutation on 2026-09-07: the leak check
fails when `<` becomes `<=` in `kick_for`, the thin-history check fails
with the gates removed, and the wiring check fails with the `build_side`
application deleted. See tests/run.py's convention.
"""
from __future__ import annotations

import random

from src.context import game, sim, velo


def _plant(rows):
    """Install a synthetic velo index and clear the memo."""
    velo._reset()
    idx = {}
    for name, date, v in rows:
        idx.setdefault(name, []).append((date, v))
    for k in idx:
        idx[k].sort()
    velo._INDEX = idx


def _restore():
    velo._reset()


def check_velo_kick_reads_only_prior_starts_same_season():
    """A replay must be priced off the radar BEFORE the date — the start
    being priced, later starts, and other seasons are all invisible.

    Planted: five flat 94.0 starts, then three at 96.0, then the date
    under test, then a 99.0 that must not count, plus a prior-season 90.0
    that must not count either. Recent-5 = the last five prior starts
    (94, 94, 96, 96, 96) against a season mean over all eight priors.
    """
    try:
        rows = [("A", f"2026-05-{d:02d}", 94.0) for d in range(1, 6)]
        rows += [("A", f"2026-06-{d:02d}", 96.0) for d in range(1, 4)]
        rows += [("A", "2026-07-15", 99.0),      # ON a later date: unseen
                 ("A", "2025-08-01", 90.0)]      # other season: unseen
        _plant(rows)
        prior = [94.0] * 5 + [96.0] * 3
        recent = prior[-5:]
        drift = sum(recent) / 5 - sum(prior) / 8
        want = velo.VELO_K_PER_MPH * (drift - velo.VELO_CENTER_MPH)
        got = velo.kick_for("A", "2026-07-01")
        assert abs(got - want) < 1e-12, (got, want)
        # and the leak the other way: on the 99.0 start's own date, that
        # start itself still must not contribute
        got2 = velo.kick_for("A", "2026-07-15")
        assert abs(got2 - want) < 1e-12, (got2, want)
    finally:
        _restore()


def check_velo_kick_is_neutral_on_thin_history():
    """Fewer than five prior starts with velocity -> exactly 0.0, and so
    are an unknown name and a missing date. Silent-neutral, never a guess
    — the same rule the ump and air rails follow."""
    try:
        _plant([("A", f"2026-05-{d:02d}", 92.0) for d in range(1, 5)])
        assert velo.kick_for("A", "2026-06-01") == 0.0     # 4 priors
        assert velo.kick_for("Nobody", "2026-06-01") == 0.0
        assert velo.kick_for("A", None) == 0.0
        assert velo.kick_for("", "2026-06-01") == 0.0
    finally:
        _restore()


def check_zone_kick_reads_only_prior_starts_and_skips_missing_zone():
    """The BB kick follows the velocity kick's lookup discipline exactly:
    prior same-season starts only — and a start with no zone share (old
    cache rows, or a 2-tuple a velocity test planted) is dropped from the
    series rather than read as zero."""
    try:
        velo._reset()
        idx = {"A": [(f"2026-05-{d:02d}", 94.0, 0.50) for d in range(1, 6)]}
        idx["A"] += [(f"2026-06-{d:02d}", 94.0, 0.55) for d in range(1, 4)]
        idx["A"] += [("2026-06-20", 94.0, None),       # no coordinates:
                     ("2026-07-15", 94.0, 0.99),       # dropped, not 0.0
                     ("2025-08-01", 94.0, 0.10)]       # other season
        velo._INDEX = idx
        prior = [0.50] * 5 + [0.55] * 3
        recent = prior[-5:]
        drift = sum(recent) / 5 - sum(prior) / 8
        want = velo.ZONE_BB_PER_SHARE * (drift - velo.ZONE_CENTER)
        got = velo.bb_kick_for("A", "2026-07-01")
        assert abs(got - want) < 1e-12, (got, want)
        # the own-date probe that catches `<` becoming `<=`: on the 0.99
        # start's own date that start still must not contribute. The first
        # mutation run PASSED without this line — a leak check with no row
        # ON the boundary guards nothing.
        got2 = velo.bb_kick_for("A", "2026-07-15")
        assert abs(got2 - want) < 1e-12, (got2, want)
    finally:
        _restore()


def check_zone_kick_is_neutral_on_thin_history():
    """Fewer than five prior starts WITH a zone share -> exactly 0.0,
    even when the velocity column is dense enough for its own kick."""
    try:
        velo._reset()
        velo._INDEX = {"A": [(f"2026-05-{d:02d}", 94.0,
                              0.5 if d <= 4 else None)
                             for d in range(1, 9)]}
        assert velo.bb_kick_for("A", "2026-06-01") == 0.0   # 4 with zone
        assert velo.bb_kick_for("Nobody", "2026-06-01") == 0.0
        assert velo.bb_kick_for("A", None) == 0.0
    finally:
        _restore()


def check_zone_kick_moves_the_starters_bb_only_when_on():
    """`build_side` applies the BB kick to the STARTER's bb_pct when
    USE_ZONE_BB is on and leaves it exactly alone when off. Velocity off
    both arms so the two terms cannot mask each other."""
    p = sim.PitcherRates(name="A", k_pct=0.220, bb_pct=0.080, hr_pct=0.03,
                         babip=0.29, pa=500)
    nine = [sim.BatterRates(name=f"b{i}", k_pct=0.22, bb_pct=0.08,
                            hr_pct=0.03, babip=0.29, pa=400)
            for i in range(9)]
    old = sim.USE_ZONE_BB
    old_velo = sim.USE_VELO_K
    old_sharp = sim.USE_START_SHARPNESS
    old_night = sim.USE_NIGHT_SIGMA
    try:
        # sharpness moves k_pct, the night draw moves bb_pct itself; both
        # off so the equality is exact on either arm
        sim.USE_START_SHARPNESS = False
        sim.USE_NIGHT_SIGMA = False
        sim.USE_VELO_K = False
        velo._reset()
        velo._INDEX = {"A": [(f"2026-05-{d:02d}", 94.0, 0.50)
                             for d in range(1, 6)]
                       + [("2026-06-02", 94.0, 0.60),
                          ("2026-06-03", 94.0, 0.60),
                          ("2026-06-04", 94.0, 0.60)]}
        kick = velo.bb_kick_for("A", "2026-07-01")
        assert kick < -0.001, kick     # zone UP -> walks DOWN, and real
        sides = {}
        for flag in (False, True):
            sim.USE_ZONE_BB = flag
            sides[flag] = game.build_side(
                p, [], nine, sim.Hook(), random.Random(5),
                team="TST", apply_leash=False, date="2026-07-01")
        assert sides[False].starter.bb_pct == 0.080
        assert abs(sides[True].starter.bb_pct - (0.080 + kick)) < 1e-12, \
            (sides[True].starter.bb_pct, kick)
    finally:
        sim.USE_ZONE_BB = old
        sim.USE_VELO_K = old_velo
        sim.USE_START_SHARPNESS = old_sharp
        sim.USE_NIGHT_SIGMA = old_night
        _restore()


def check_velo_kick_moves_the_starters_k_only_when_on():
    """`build_side` applies the kick to the STARTER's k_pct when the flag
    is on and leaves the engine bit-identical when it is off. Same seed
    both arms; the kick consumes no randomness, so the drawn pen must be
    identical too."""
    p = sim.PitcherRates(name="A", k_pct=0.220, bb_pct=0.08, hr_pct=0.03,
                         babip=0.29, pa=500)
    nine = [sim.BatterRates(name=f"b{i}", k_pct=0.22, bb_pct=0.08,
                            hr_pct=0.03, babip=0.29, pa=400)
            for i in range(9)]
    old = sim.USE_VELO_K
    old_sharp = sim.USE_START_SHARPNESS
    try:
        # sharpness off so the assert is on exact values; it multiplies
        # k_pct by a nightly draw and would blur the equality either side
        sim.USE_START_SHARPNESS = False
        _plant([("A", f"2026-05-{d:02d}", 94.0) for d in range(1, 6)]
               + [("A", "2026-06-02", 98.0), ("A", "2026-06-03", 98.0),
                  ("A", "2026-06-04", 98.0)])
        kick = velo.kick_for("A", "2026-07-01")
        assert kick > 0.01, kick          # a real, positive planted kick
        sides = {}
        for flag in (False, True):
            sim.USE_VELO_K = flag
            sides[flag] = game.build_side(
                p, [], nine, sim.Hook(), random.Random(5),
                team="TST", apply_leash=False, date="2026-07-01")
        assert sides[False].starter.k_pct == 0.220
        assert abs(sides[True].starter.k_pct - (0.220 + kick)) < 1e-12, \
            (sides[True].starter.k_pct, kick)
    finally:
        sim.USE_VELO_K = old
        sim.USE_START_SHARPNESS = old_sharp
        _restore()
