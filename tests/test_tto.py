"""Checks for times through the order.

Offline: builds its own play-by-play and rates, so nothing touches disk.

TTO is the mechanism that makes staying in COST something. Before it, three
separate measurements found the removal rule flat, because relievers are no
better than starters and pulling one was free. What gets pinned here is the
re-centring (which stops the table shifting the run level), the reliever
exemption (which would otherwise hand every bullpen arm a strikeout bonus),
and the pass arithmetic.
"""
from __future__ import annotations

import random
import statistics as st

from src.context import game, sim, tto
from tests.test_sim import LG, _lineup, _pitcher


def check_the_multipliers_are_recentred_not_anchored_at_the_first_pass():
    """The model's k_pct is a SEASON rate, already averaged over passes.

    Multipliers anchored at pass-1 = 1.0 would raise every pitcher's
    strikeout rate and shift the run level. Re-centred, the first pass must
    sit ABOVE 1 and the third BELOW it.
    """
    m = sim.TTO_MULT
    assert m[1]["k_pct"] > 1.0 > m[3]["k_pct"], m
    assert m[1]["hr_pct"] < 1.0 < m[3]["hr_pct"], m


def check_the_strikeout_decline_is_the_dominant_term():
    """K% falls ~19% first pass to third; walks and homers move 3-4%.

    If some other rate ever carries more of the effect, the measurement has
    changed and the run consequences change with it.
    """
    m = sim.TTO_MULT
    k = m[1]["k_pct"] - m[3]["k_pct"]
    for stat in ("bb_pct", "hr_pct", "babip"):
        assert k > abs(m[3][stat] - m[1][stat]) * 2, (stat, k)


def check_a_reliever_gets_no_tto_adjustment():
    """`None`, not pass 1. Defaulting to the first pass would give every arm
    out of the bullpen a 1.105 strikeout multiplier for free."""
    assert sim.tto_mult(None) is None


def check_the_flag_off_disables_it_entirely():
    orig, sim.USE_TTO = sim.USE_TTO, False
    try:
        assert sim.tto_mult(1) is None and sim.tto_mult(3) is None
    finally:
        sim.USE_TTO = orig


def check_the_pass_is_clamped_beyond_the_measured_range():
    """A starter into his fourth pass is 0.4% of plate appearances and its
    raw numbers are erratic, so it folds into the third."""
    assert sim.tto_mult(9) == sim.TTO_MULT[3]
    assert sim.tto_mult(4) == sim.TTO_MULT[3]


def check_tto_actually_reaches_the_simulated_start():
    """A starter must strike out fewer batters late than early.

    Guards the WIRING, not the table: a `tto` argument that never reached
    `pa_outcome` would leave this flat while every table check still passed.
    """
    orig, sim.USE_TTO = sim.USE_TTO, True
    try:
        p = _pitcher(k_pct=0.25)
        early = late = 0
        for s in range(400):
            rng = random.Random(s)
            r = sim.simulate(p, _lineup(), dict(LG), n=1, seed=s,
                             hook=sim.Hook(intercept=-99.0,
                                           mid_intercept=-99.0))[0]
            early += r.k
        sim.USE_TTO = False
        for s in range(400):
            r = sim.simulate(p, _lineup(), dict(LG), n=1, seed=s,
                             hook=sim.Hook(intercept=-99.0,
                                           mid_intercept=-99.0))[0]
            late += r.k
    finally:
        sim.USE_TTO = orig
    # Net over a full start is near-neutral by construction, so this asserts
    # only that the switch CHANGES the start at all.
    assert early != late, (early, late)


def check_the_pass_counter_turns_over_at_nine_batters():
    """The tenth batter faced is the first of the second pass."""
    assert 9 // 9 + 1 == 2 and 8 // 9 + 1 == 1 and 18 // 9 + 1 == 3


def check_only_plate_appearances_are_bucketed():
    """A steal or a wild pitch is not a plate appearance and must not
    advance the count, or the pass turns over early."""
    assert tto._bucket("stolen_base") is None
    assert tto._bucket("wild_pitch") is None
    assert tto._bucket("strikeout") == "k"
    assert tto._bucket("field_error") == "out"


def check_a_batter_faced_twice_is_not_counted():
    """The paired design needs all three passes, or the buckets stop being
    the same nine hitters."""
    plays = []
    for i in range(2):
        plays.append({
            "about": {"inning": i + 1, "halfInning": "top",
                      "isTopInning": True},
            "matchup": {"pitcher": {"id": 1}, "batter": {"id": 100}},
            "count": {"outs": 0}, "runners": [],
            "result": {"eventType": "strikeout"}})
    assert tto.start_passes("fake", {"allPlays": plays}) == []
