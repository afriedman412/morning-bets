"""The per-pitcher leash: the measurement, the conversion, and the wiring.

The wiring checks live in `test_sim.py` next to `for_start`. These cover the
three places `src/context/leash.py` could be silently wrong: the shrinkage
constant, the outs-to-log-odds conversion, and — the one that would not show
up as an error at all — measuring the residual against a model that already
has the leash in it.
"""
import random
import statistics as st

from src.context import leash, sim


def check_the_conversion_inverts_the_measured_table():
    """`offset_for` and `_d_outs` are the two directions of one table and
    must round-trip. A sign slip here hands every innings-eater a SHORT
    leash and still produces a plausible-looking spread."""
    for offset, d_outs in leash.OUTS_PER_OFFSET:
        assert abs(leash._d_outs(offset) - d_outs) < 1e-9, offset
        if abs(offset) < leash.OFFSET_CLAMP:
            assert abs(leash.offset_for(d_outs) - offset) < 1e-6, d_outs
    # a pitcher who goes LONGER than the model gets a NEGATIVE offset,
    # because a negative offset lowers the removal log-odds
    assert leash.offset_for(+1.5) < 0
    assert leash.offset_for(-1.5) > 0
    assert leash.offset_for(0.0) == 0.0


def check_the_conversion_is_interpolated_not_a_straight_line():
    """The measured curve bends: -2.0 buys +3.00 outs where the local slope
    at zero would promise +3.36. Fitting a line through counted points is
    the mistake RESUME records against the advance-on-out hazard, where a
    least-squares slope charged +0.724 at one run against a counted +0.296.
    """
    slope = (leash._d_outs(0.3) - leash._d_outs(-0.3)) / 0.6
    linear = slope * -2.0
    actual = leash._d_outs(-2.0)
    assert actual < linear - 0.2, (actual, linear)
    # and midpoints between measured knots are genuinely interpolated
    mid = leash._d_outs(-0.45)
    assert leash._d_outs(-0.6) > mid > leash._d_outs(-0.3)


def check_the_offset_never_leaves_the_measured_sweep():
    """Openers land in the starts table and their residual runs to minus six
    outs. Extrapolating past the sweep would hand them a leash the league
    does not contain, at a conversion that was never measured.

    Bounded by the TABLE's own endpoints, not by `OFFSET_CLAMP`. Asserting
    the clamp against itself is self-referential and passes just as happily
    at 99.0 — found by mutation, which is the only way this kind of vacuous
    check ever surfaces.
    """
    lo = min(o for o, _ in leash.OUTS_PER_OFFSET)
    hi = max(o for o, _ in leash.OUTS_PER_OFFSET)
    for extreme in (-40.0, -6.0, 6.0, 40.0):
        got = leash.offset_for(extreme)
        assert lo - 1e-9 <= got <= hi + 1e-9, (extreme, got)
    assert leash.OFFSET_CLAMP <= hi + 1e-9, leash.OFFSET_CLAMP


def check_shrinkage_is_the_measured_within_over_between():
    """K is a MEASURED ratio, not a tuned constant, and the estimator has to
    remove sampling noise. A population with a real spread of group means
    yields a small K; one where every group is the same yields a huge one.
    """
    rng = random.Random(3)
    # real differences between pitchers: between 3.0, within 1.0
    wide = {f"p{i}": [rng.gauss(i - 10, 1.0) for _ in range(12)]
            for i in range(20)}
    k_wide, betw, wit = leash.shrink_k(wide)
    assert 2.0 < betw < 9.0, betw
    assert 0.7 < wit < 1.4, wit
    assert k_wide < 1.0, k_wide
    # no real differences at all: the raw spread of group means is NOT zero
    # (it is sampling noise), so a naive estimator would report a leash
    flat = {f"p{i}": [rng.gauss(0.0, 3.0) for _ in range(12)]
            for i in range(20)}
    k_flat, betw_flat, _ = leash.shrink_k(flat)
    raw = st.pstdev([st.mean(v) for v in flat.values()])
    assert raw > 0.4, raw
    assert betw_flat < raw / 2, (betw_flat, raw)
    assert k_flat > k_wide * 20, (k_flat, k_wide)


def check_leash_residuals_are_measured_against_the_bare_hook():
    """THE DOUBLE-COUNT GUARD, and the failure it prevents is silent.

    `_sim_one` must simulate with a bare `sim.Hook()`, never through
    `sim.for_start`. Once the leash ships ON, a rebuild that went through
    `for_start` would measure the residual of a model that ALREADY has the
    correction in it, find it near zero, and write offsets that decay to
    nothing — or, with the sign the other way, run away. Neither shows up as
    an error; the file just quietly stops meaning anything.

    Behavioural rather than a source scan: a huge leash is installed and the
    residual must not move.
    """
    lg = sim.league()
    p = sim.PitcherRates(name="Somebody", k_pct=lg["k_pct"],
                         bb_pct=lg["bb_pct"], hr_pct=lg["hr_pct"],
                         babip=lg["babip"], pa=600)
    nine = [sim.BatterRates(name=f"b{i}", k_pct=lg["k_pct"],
                            bb_pct=lg["bb_pct"], hr_pct=lg["hr_pct"],
                            babip=lg["babip"]) for i in range(9)]
    s = {"player_name": "Somebody", "date": "2026-05-01", "team": "XXX",
         "o": 18, "venue_id": None, "is_home": 0}
    saved_cases, saved_leash = leash._CASES, sim._LEASH
    leash._CASES = [(s, p, nine)]
    try:
        sim._LEASH = None
        bare = leash._sim_one((0, 60, 0))[3]
        sim._LEASH = {"Somebody": -2.0}
        with_leash = leash._sim_one((0, 60, 0))[3]
    finally:
        leash._CASES, sim._LEASH = saved_cases, saved_leash
    assert abs(bare - with_leash) < 1e-9, (bare, with_leash)


def check_a_pitcher_with_too_little_history_gets_no_offset():
    """Same missing-group rule as everywhere else: unknown resolves to the
    league hook, never to a guess. One disaster start must not register as
    a leash."""
    assert leash.MIN_PRIOR >= 3, leash.MIN_PRIOR
    assert sim.leash("Nobody Who Has Ever Pitched") == 0.0
    assert sim.leash(None) == 0.0
    assert sim.leash("") == 0.0
