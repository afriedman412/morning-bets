"""Checks for the advancement measurement.

Offline: every check builds its own play, so the 205 MB cache is never
touched.

A MEASUREMENT MODULE NEEDS TESTS MORE THAN A MODEL DOES, not less. A wrong
simulator produces a number that looks wrong; a wrong measurement produces
a number that looks like a finding, and the whole point of this module is to
be believed about which published constants are off. Each check pins one
CONDITION — the same conditions `sim._advance` uses — because a rate counted
under the wrong condition is the failure mode, not a rate counted wrong.
"""
from __future__ import annotations

from collections import Counter

from src.context import advance
from tests.test_pbp import _play, _r


def _count(ev, bases, outs, runners):
    p = _play(3, True, 10, outs, runners=runners)
    p["result"]["eventType"] = ev
    c: Counter = Counter()
    advance.count_play(c, p, bases, outs)
    return c


def check_a_runner_from_first_reaching_third_is_counted():
    c = _count("single", (True, False, False), 1,
               [_r(9, None, "1B"), _r(1, "1B", "3B")])
    assert c["first_on_1b/1"] == 1
    assert c["first_to_third/1"] == 1
    assert c["first_scores_on_1b/1"] == 0


def check_a_runner_held_at_third_blocks_the_first_to_third_count():
    """`sim._advance` only rolls FIRST_TO_THIRD_ON_1B when third is free
    after the lead runners resolve — `bases[0] and not third`. Counting the
    blocked cases would put a pile of guaranteed non-advances in the
    denominator and drag the measured rate down for a reason the model
    never experiences."""
    c = _count("single", (True, True, False), 1,
               [_r(9, None, "1B"), _r(2, "2B", "3B"), _r(1, "1B", "2B")])
    assert c["first_on_1b/1"] == 0, "counted a case the model cannot reach"
    assert c["second_on_1b/1"] == 1        # but the lead runner still counts
    assert c["second_on_1b_scored/1"] == 0


def check_a_runner_already_on_third_does_not_block():
    """He scores unconditionally in the model and vacates the base, so the
    roll still happens. Excluding these was the first version of this
    measurement and it dropped 10% of the sample."""
    c = _count("single", (True, False, True), 0,
               [_r(9, None, "1B"), _r(3, "3B", "score"), _r(1, "1B", "3B")])
    assert c["first_on_1b/0"] == 1
    assert c["first_to_third/0"] == 1
    assert c["third_on_1b_scored/0"] == 1


def check_scoring_from_first_on_a_single_is_counted_separately():
    """The model cannot do this at all — its single sends the runner from
    first to third at best. Counting it as a first-to-third would hide a
    missing mechanism inside a rate that looks merely mistuned."""
    c = _count("single", (True, False, False), 2,
               [_r(9, None, "1B"), _r(1, "1B", "score")])
    assert c["first_scores_on_1b/2"] == 1
    assert c["first_to_third/2"] == 0
    assert c["first_on_1b/2"] == 1


def check_advancement_on_an_out_is_per_base_and_pooled():
    """The model moves EVERY runner one base when the roll fires. Reality
    is per-base, so both views are counted: the pooled rate the constant is
    comparable to, and the split that says whether one constant can be
    right for all three bases."""
    c = _count("field_out", (True, True, False), 0,
               [_r(2, "2B", "3B")])
    assert c["out_with_runners/0"] == 1
    assert c["any_advance_on_out/0"] == 1
    assert c["on_2B_advanced/0"] == 1
    assert c["on_1B_out/0"] == 1 and c["on_1B_advanced/0"] == 0


def check_two_out_outs_are_excluded():
    """With two down the ball in play IS the third out, so the model never
    consults the rate. `RUNNER_ADVANCES_ON_OUT[2]` is documented as
    unreachable."""
    c = _count("field_out", (True, True, False), 2, [])
    assert c["out_with_runners/2"] == 0


def check_a_strikeout_is_not_a_ball_in_play_out():
    c = _count("strikeout", (True, False, False), 1, [])
    assert c["out_with_runners/1"] == 0
    assert c["dp_denom/1"] == 0            # not a ball in play
    assert c["dp_pa/1"] == 1               # but it IS an opportunity


def check_a_sacrifice_is_not_a_ball_in_play_out():
    """The simulator has a separate SAC outcome that advances runners for
    free. Pooling sacrifices with ordinary outs would load the advancement
    rate with plays whose entire purpose is to advance."""
    for ev in ("sac_fly", "sac_bunt"):
        c = _count(ev, (False, True, False), 1, [_r(2, "2B", "3B")])
        assert c["out_with_runners/1"] == 0, ev


def check_the_two_double_play_denominators_differ():
    """The finding this module exists to be believed about: `GIDP%` as
    published is per OPPORTUNITY and the simulator rolls its constant per
    BALL-IN-PLAY OUT, which is about half as many chances. Both must be
    counted or the mismatch reads as a mistuned constant."""
    c: Counter = Counter()
    for ev in ("strikeout", "walk", "single", "field_out",
               "grounded_into_double_play"):
        p = _play(3, True, 10, 1)
        p["result"]["eventType"] = ev
        advance.count_play(c, p, (True, False, False), 1)
    assert c["dp_pa/1"] == 5
    assert c["dp_denom/1"] == 2            # field_out + the DP itself
    assert c["dp_chance/1"] == 1


def check_a_stolen_base_is_not_an_opportunity():
    c = _count("stolen_base_2b", (True, False, False), 0, [])
    assert c["dp_pa/0"] == 0
    assert c["plays"] == 1                 # still seen, just not counted


def check_reaching_on_an_error_is_a_plate_appearance():
    c = _count("field_error", (True, False, False), 0, [])
    assert c["dp_pa/0"] == 1


def check_the_batting_team_owns_the_baserunners():
    """Top of the inning is the AWAY club batting. Backwards, the whole
    per-club table measures each club's OPPONENTS and still looks fine."""
    assert advance.batting_team(("NYY", "BOS"), True) == "NYY"
    assert advance.batting_team(("NYY", "BOS"), False) == "BOS"
    assert advance.batting_team(None, True) is None


def _team_counter(rates, halves=(0, 1), n=200):
    """{club: (first-half rate, second-half rate)} -> a tally-shaped dict."""
    c = {}
    for club, (a, b) in rates.items():
        for h, rate in zip(halves, (a, b)):
            c[f"{club}.{h}|first_on_1b/0"] = n
            c[f"{club}.{h}|first_to_third/0"] = round(rate * n)
    return c


def check_team_stability_finds_a_club_effect_when_there_is_one():
    c = _team_counter({"AAA": (0.20, 0.21), "BBB": (0.30, 0.29),
                       "CCC": (0.40, 0.41), "DDD": (0.25, 0.24),
                       "EEE": (0.35, 0.36), "FFF": (0.45, 0.44)})
    r, n = advance.team_stability(c, "first_to_third", "first_on_1b",
                                  keys=(0,))
    assert n == 6, n
    assert r > 0.95, r


def check_team_stability_is_near_zero_when_halves_are_unrelated():
    """The failure this gate exists to catch: clubs differ in the observed
    table, but a club's first half says nothing about its second, so the
    spread is a season of sampling noise and the league number is the
    honest one."""
    c = _team_counter({"AAA": (0.20, 0.44), "BBB": (0.44, 0.21),
                       "CCC": (0.32, 0.33), "DDD": (0.21, 0.43),
                       "EEE": (0.43, 0.20), "FFF": (0.33, 0.32)})
    r, _ = advance.team_stability(c, "first_to_third", "first_on_1b",
                                  keys=(0,))
    assert r is not None and r < 0.0, r


def check_team_stability_drops_thin_halves():
    c = _team_counter({"AAA": (0.2, 0.2), "BBB": (0.3, 0.3)}, n=10)
    r, n = advance.team_stability(c, "first_to_third", "first_on_1b",
                                  keys=(0,), min_n=60)
    assert n == 0 and r is None, (r, n)


def check_advance_means_forward_only():
    assert advance._adv("score", "1B")
    assert advance._adv("3B", "1B")
    assert not advance._adv("1B", "1B")
    assert not advance._adv("out", "2B")
    assert not advance._adv(None, "2B")


def check_the_double_play_rate_is_the_current_era_not_the_pooled_one():
    """`GIDP_RATE` is the one measured constant whose ERA GATE FAILED.

    Counted per season, man on first, under two out, in the model's own
    denominator (`scratchpad/season_gate.py`, one pass over 9,962 games):

        season    0 out     1 out
        2023     0.2307    0.2531
        2024     0.2303    0.2300
        2025     0.2132    0.2327
        2026     0.2129    0.2276

    The 0-out rate steps between 2024 and 2025, about 3.3 sigma on ~6,900
    rows a season, so pooling all four imports a rate the league no longer
    has. What ships is 2025+2026.

    NOTHING GUARDED THIS VALUE UNTIL NOW — it was changed from 0.209 and the
    whole suite stayed green, which is how a measured constant drifts back
    to a guess. Pinned as a BAND rather than to four decimals, so a genuine
    re-measurement is free and a pooled or legacy value is not.
    """
    from src.context import sim

    assert sim.USE_MEASURED_GIDP is True
    for outs, lo, hi in ((0, 0.205, 0.222), (1, 0.222, 0.240)):
        got = sim.GIDP_RATE[outs]
        assert lo < got < hi, (outs, got)
    # Two out is not a double-play state in this model: the inning ends.
    assert sim.GIDP_RATE[2] == 0.0, sim.GIDP_RATE
    # The 2023/24 rate is OUTSIDE the 0-out band, which is what makes the
    # band meaningful rather than decorative.
    assert not (0.205 < 0.2305 < 0.222)
    # And the published per-opportunity figure is on the wrong denominator.
    assert sim.LEGACY_GIDP_RATE < 0.15, sim.LEGACY_GIDP_RATE
    assert sim.gidp_rate(0) == sim.GIDP_RATE[0], "the accessor is bypassed"
