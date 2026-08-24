"""Checks for the full-game simulator.

Offline: every check builds its own rates, so nothing here touches the DB.

What is worth guarding in a game sim is not the run average — that is a
distribution, and asserting on a mean invites a test that passes because two
errors cancelled. These pin the STRUCTURE: that the two sides are not
crossed, that nine innings actually happen, that the bullpen is reached and
used, and that a departing starter hands over the base-out state instead of
having his runners settled by a fudge factor.
"""
from __future__ import annotations

import random

from src.context import game, sim
from tests.test_sim import LG, _lineup, _pitcher


def _pen(n=6, **kw):
    return [sim.PitcherRates(**{"name": f"R{i}", "k_pct": LG["k_pct"],
                                "bb_pct": LG["bb_pct"], "hr_pct": LG["hr_pct"],
                                "babip": LG["babip"], "pa": 200, **kw})
            for i in range(n)]


def _side(starter=None, pen=None, hook=None, **kw):
    return game.Side(starter=starter or _pitcher(), pen=pen or _pen(),
                     lineup=_lineup(), hook=hook or sim.Hook(), **kw)


def check_scores_are_not_crossed():
    """The AWAY side's runs ALLOWED are the HOME team's score.

    The single most likely way to build this exactly backwards. Checked by
    making one staff unhittable: the team facing it must be the one that
    cannot score.
    """
    unhittable = _pitcher(name="ace", k_pct=0.99, bb_pct=1e-4, hr_pct=1e-6,
                          babip=1e-4)
    batting_practice = _pitcher(name="bp", k_pct=0.01, bb_pct=0.30,
                                hr_pct=0.15, babip=0.45)
    away = _side(starter=unhittable, pen=_pen(k_pct=0.99, bb_pct=1e-4,
                                              hr_pct=1e-6, babip=1e-4))
    home = _side(starter=batting_practice,
                 pen=_pen(k_pct=0.01, bb_pct=0.30, hr_pct=0.15, babip=0.45))
    r = game.simulate_game(away, home, dict(LG), random.Random(3))
    # away pitching is untouchable -> the HOME team (which it faces) scores ~0
    assert r.home < 2, (r.away, r.home)
    assert r.away > 4, (r.away, r.home)


def check_a_full_game_is_nine_innings_not_five():
    """The gap this module exists to close: before it, nothing simulated
    past the starter's exit, so a full team total could not be produced.
    The nine-inning total must exceed the five-inning one."""
    tot = f5 = 0
    rng = random.Random(5)
    for _ in range(40):
        r = game.simulate_game(_side(), _side(), dict(LG), rng)
        tot += r.total
        f5 += r.total_f5
    assert tot > f5 * 1.4, (tot, f5)


def check_starter_cannot_record_more_than_twenty_seven_outs():
    rng = random.Random(8)
    never = sim.Hook(intercept=-99.0, mid_intercept=-99.0,
                     hard_pitch_cap=100000)
    for _ in range(15):
        a, h = _side(hook=never), _side(hook=never)
        game.simulate_game(a, h, dict(LG), rng)
        # Bounded by the innings actually PLAYED, not by 27 — extra innings
        # exist now, and a never-pull hook rides one starter through them.
        assert a.line.outs <= 3 * a.line.innings_completed, a.line.outs
        assert h.line.outs <= 3 * h.line.innings_completed, h.line.outs


def check_the_bullpen_actually_pitches():
    """A starter yanked immediately must not keep pitching.

    Guards the handover: if `next_arm` failed to advance, the game would
    silently run the starter all nine innings and the whole bullpen model
    would be dead code that still produced plausible numbers.
    """
    quick = sim.Hook(intercept=99.0, mid_intercept=-99.0)
    away, home = _side(hook=quick), _side(hook=quick)
    game.simulate_game(away, home, dict(LG), random.Random(2))
    assert away.starter_out and home.starter_out
    assert away.pen_i > 0, away.pen_i
    assert away.line.outs < 27, away.line.outs


def check_a_sampled_bullpen_varies_between_games():
    """The point of sampling rather than taking the top eight: which arms
    are available is itself a source of game-to-game spread, and it is the
    spread the run distribution was missing."""
    pool = [{"name": f"P{i}", "apps": 40 - i, "pa": 200,
             "k_pct": 0.20 + i / 100, "bb_pct": 0.08, "hr_pct": 0.03,
             "babip": 0.29} for i in range(10)]
    rng = random.Random(1)
    seen = {tuple(a.name for a in
                  game.build_side(_pitcher(), pool, _lineup(), None, rng).pen)
            for _ in range(25)}
    assert len(seen) > 1, "bullpen is identical every game"


def check_bullpen_sampling_favours_the_busy_arms():
    """Weighted by appearances. Uniform sampling would hand every club a pen
    made mostly of its worst pitchers, because there are more of them."""
    pool = [{"name": "leverage", "apps": 400, "pa": 400, "k_pct": 0.30,
             "bb_pct": 0.07, "hr_pct": 0.02, "babip": 0.28}]
    pool += [{"name": f"mop{i}", "apps": 5, "pa": 40, "k_pct": 0.15,
              "bb_pct": 0.11, "hr_pct": 0.05, "babip": 0.31}
             for i in range(20)]
    rng = random.Random(4)
    first = [game.build_side(_pitcher(), pool, _lineup(), None, rng,
                             depth=1).pen[0].name for _ in range(60)]
    assert first.count("leverage") > 20, first.count("leverage")


def check_margin_reaches_the_hook():
    """The reason both sides are interleaved at all.

    A pitching side simulated alone cannot know whether it is winning, so
    `mid_per_margin` had nowhere to enter. With a big enough coefficient the
    score MUST change how long starters last; if it does not, the margin is
    being computed but never passed.
    """
    def outs(mid_per_margin):
        # A FRESH seeded rng per call. Sharing one across both calls lets
        # the draw streams diverge on their own, so the comparison passes
        # whether or not the margin is wired up — this check was vacuous
        # until a mutation that ignored the margin entirely failed nothing.
        rng = random.Random(6)
        tot = 0
        for _ in range(40):
            h = sim.Hook(mid_per_margin=mid_per_margin, mid_intercept=-3.0)
            r = game.simulate_game(_side(hook=h), _side(hook=h), dict(LG), rng)
            tot += r.away_sp.outs + r.home_sp.outs
        return tot

    assert outs(0.0) != outs(2.5), "margin never reaches the removal rule"


def check_margin_defaults_to_no_effect():
    """Both margin terms ship at zero, so adding the capability changed no
    existing number. A non-zero default would have silently re-tuned every
    price in the project."""
    h = sim.Hook()
    assert h.per_margin == 0.0 and h.mid_per_margin == 0.0
    base = h.mid_removal_p(90, 3, 2, 1.0, margin=0)
    for m in (-8, -3, 3, 8):
        assert h.mid_removal_p(90, 3, 2, 1.0, margin=m) == base, m


def check_inherited_runners_are_simulated_not_estimated():
    """A starter pulled mid-inning hands over the bases and the outs.

    `f5._side_runs` settles his stranded runners with a flat 0.33 because it
    never simulates the reliever finishing the inning. This does, so the
    constant must not appear in the full-game path at all — if it crept back
    in, those runners would be counted twice.
    """
    import inspect
    src = inspect.getsource(game)
    # The attribute access is the only way the module could actually use it;
    # matching the bare name instead catches the prose explaining why it is
    # absent, which is how the first version of this check failed.
    assert "sim.INHERITED_SCORE_RATE" not in src, \
        "full game must not fudge inherited runners"
    # And the handover must really happen: a starter pulled mid-inning
    # leaves men on often enough that this is not a vacuous check.
    rng = random.Random(13)
    stranded = 0
    for _ in range(60):
        a = _side(hook=sim.Hook(mid_intercept=-2.0))
        game.simulate_game(a, _side(), dict(LG), rng)
        stranded += a.line.pulled_mid_inning and a.line.left_on_base > 0
    assert stranded > 0, "no starter ever handed over a baserunner"


def check_side_runs_match_the_pitchers_charged():
    """Side totals are accumulated from each pitcher's own line, so the two
    can never disagree. Guards the delta bookkeeping in `_half_inning`."""
    rng = random.Random(11)
    quick = sim.Hook(intercept=1.0, mid_intercept=-4.0)
    away, home = _side(hook=quick), _side(hook=quick)
    game.simulate_game(away, home, dict(LG), rng)
    assert away.runs >= away.line.runs, (away.runs, away.line.runs)
    assert home.runs >= home.line.runs, (home.runs, home.line.runs)


def check_prefix_totals_are_nested_and_cumulative():
    """F3 must be the first three innings of the SAME game F7 came from.

    Nested prefixes are the entire basis of diagnosing by prefix: if each
    were simulated separately they would be different games, and comparing
    them would say nothing about which inning the error entered.
    """
    r = game.simulate_game(_side(), _side(), dict(LG), random.Random(1),
                           track=(1, 3, 5, 7))
    assert set(r.prefix) == {1, 3, 5, 7}, r.prefix
    v = [r.prefix[p] for p in (1, 3, 5, 7)]
    assert v == sorted(v), v                       # runs cannot un-score
    assert r.prefix[7] <= r.total, (r.prefix[7], r.total)
    assert r.prefix[5] == r.away_f5 + r.home_f5, (r.prefix[5], r.total_f5)


def check_prefix_is_empty_unless_tracked():
    """Costs nothing when unused — every other caller passes no `track`."""
    r = game.simulate_game(_side(), _side(), dict(LG), random.Random(1))
    assert r.prefix == {}, r.prefix
