"""Do the measured mechanisms actually REACH the simulation?

A mutation sweep over the shipped flags found five that nothing guarded:
measured advancement, measured inherited runners, the hard pitch cap,
measured relief-outing length, and the mid-inning relief hook. Every one
could be switched off and the whole 307-check suite still passed.

The existing modules are well tested — `test_advance` has 16 checks,
`test_relief` 10, `test_inherit` 8 — but they test the MEASUREMENT: that the
counting code counts correctly. Nobody tested that the simulator uses the
numbers. That is exactly the gap two real bugs fell through in one day: the
boundary hook was never called at all, and the early branch was fitted on
baserunners ALLOWED this inning then wired to bases OCCUPIED.

So these are integration checks, and each is written the same way: flip the
flag, simulate, and assert the OUTPUT moves. Asserting the flag's value
alone would guard the default and not the wiring.
"""
import random

from src.context import game, sim

LG = sim.league()


def _pitcher(k=0.22, bb=0.08):
    return sim.PitcherRates(name="p", k_pct=k, bb_pct=bb, hr_pct=0.03,
                            babip=0.29, pa=600)


def _nine():
    return [sim.BatterRates(name=f"b{i}", k_pct=0.22, bb_pct=0.08,
                            hr_pct=0.03, babip=0.29, pa=500)
            for i in range(9)]


def _pen(n=8):
    return [{"name": f"r{i}", "k_pct": 0.23, "bb_pct": 0.09, "hr_pct": 0.03,
             "babip": 0.29, "pa": 200, "apps": 40} for i in range(n)]


def _games(n=400, seed=5, **flags):
    """Simulate `n` games with `flags` applied to `game`, then restore."""
    prev = {k: getattr(game, k) for k in flags}
    try:
        for k, v in flags.items():
            setattr(game, k, v)
        out = []
        for i in range(n):
            rng = random.Random(seed + i)
            a = game.build_side(_pitcher(), _pen(), _nine(), None, rng)
            h = game.build_side(_pitcher(), _pen(), _nine(), None, rng)
            out.append((game.simulate_game(a, h, dict(LG), rng), a, h))
        return out
    finally:
        for k, v in prev.items():
            setattr(game, k, v)


def _starts(n=600, seed=3, hook=None, **flags):
    prev = {k: getattr(sim, k) for k in flags}
    try:
        for k, v in flags.items():
            setattr(sim, k, v)
        rng = random.Random(seed)
        return [sim.simulate_start(_pitcher(), _nine(), dict(LG),
                                   hook or sim.Hook(), rng)
                for _ in range(n)]
    finally:
        for k, v in prev.items():
            setattr(sim, k, v)


def check_measured_advancement_reaches_the_run_level():
    """`USE_MEASURED_ADVANCEMENT` was unguarded. It replaced imported
    advancement tables with rates counted on this league, and it moves runs
    per baserunner — so turning it off has to change the run level."""
    on = _starts(USE_MEASURED_ADVANCEMENT=True)
    off = _starts(USE_MEASURED_ADVANCEMENT=False)
    r_on = sum(r.runs for r in on) / len(on)
    r_off = sum(r.runs for r in off) / len(off)
    assert abs(r_on - r_off) > 0.02, (r_on, r_off)


def check_measured_inherited_runners_reach_the_start_level_path():
    """`USE_MEASURED_INHERITED` replaced a flat 0.330 with a base-out table
    running 0.127 to 0.771, and it was unguarded.

    TWO REASONS AN AGGREGATE CHECK CANNOT SEE IT, both worth recording.

    It only reaches `simulate_start`. The full-game engine never consults it
    — it hands the base-out state to the reliever and plays the runners out
    for real, which is strictly better — so `_leave` and its table retire
    with the start-level loop rather than needing a port. Asserted against
    `simulate_game` the difference is exactly zero, 8.56 against 8.56.

    And the POOLED rate is 0.312 against the flat 0.330, so even on the path
    that does use it the mean barely moves: 1.975 runs against 1.978 over
    800 starts. The cells differ by a factor of six and cancel in the
    average. So the check goes at the cell, not the aggregate.
    """
    import random

    rng = random.Random(4)
    hits = {True: 0, False: 0}
    prev = sim.USE_MEASURED_INHERITED
    try:
        for flag in (True, False):
            sim.USE_MEASURED_INHERITED = flag
            for _ in range(4000):
                r = sim.StartResult()
                fr = sim.Frame()
                fr.bases = [False, False, True]     # man on third
                fr.outs = 0
                sim._leave(r, fr, rng)
                hits[flag] += r.runs
    finally:
        sim.USE_MEASURED_INHERITED = prev
    on, off = hits[True] / 4000, hits[False] / 4000
    # Third base, nobody out: 0.771 measured against the flat 0.330.
    assert 0.72 < on < 0.82, on
    assert 0.29 < off < 0.37, off


def check_the_hard_pitch_cap_actually_caps():
    """Unguarded, and it is the only thing bounding a start from above. With
    a never-firing hook the cap is the ONLY exit, so removing it has to let
    starters run past it."""
    never = sim.Hook(intercept=-99.0, mid_intercept=-99.0)
    capped = _starts(n=300, hook=sim.Hook(**{**never.__dict__,
                                             "hard_pitch_cap": 90}))
    assert max(r.pitches for r in capped) < 130, \
        max(r.pitches for r in capped)
    loose = _starts(n=300, hook=sim.Hook(**{**never.__dict__,
                                            "hard_pitch_cap": 100000}))
    assert max(r.pitches for r in loose) > max(r.pitches for r in capped), \
        (max(r.pitches for r in capped), max(r.pitches for r in loose))


def check_measured_relief_length_reaches_the_bullpen():
    """`USE_MEASURED_RELIEF_LENGTH` was unguarded. Off, every relief outing
    is one inning and a game burns more arms; on, outings run to the length
    measured over 13,248 of them."""
    on = _games(USE_MEASURED_RELIEF_LENGTH=True)
    off = _games(USE_MEASURED_RELIEF_LENGTH=False)
    a_on = sum(a.pen_i + h.pen_i for _, a, h in on) / len(on)
    a_off = sum(a.pen_i + h.pen_i for _, a, h in off) / len(off)
    assert a_on < a_off, (a_on, a_off)


def check_the_relief_mid_inning_hook_reaches_the_bullpen():
    """`USE_MEASURED_RELIEF_HOOK` was unguarded. Off, only a STARTER's hook
    can produce a mid-inning handover, which caps the model at 41.8% of the
    real ones. On, relievers are pulled mid-inning too — so more arms per
    game."""
    on = _games(USE_MEASURED_RELIEF_HOOK=True)
    off = _games(USE_MEASURED_RELIEF_HOOK=False)
    a_on = sum(a.pen_i + h.pen_i for _, a, h in on) / len(on)
    a_off = sum(a.pen_i + h.pen_i for _, a, h in off) / len(off)
    assert a_on > a_off, (a_on, a_off)


def check_the_measured_mechanisms_are_switched_on_by_default():
    """The checks above set each flag THEMSELVES, in both directions, so
    they prove the mechanism works and say nothing about which way it ships.
    A mutation sweep flipping the shipped defaults left all 313 of them
    green — the mechanism checks override the very thing being mutated.

    So the default is pinned separately. Both halves are needed and neither
    substitutes for the other: this one catches a flag being flipped, the
    ones above catch the wiring rotting behind a flag that still reads True.

    Every value here is a MEASURED quantity that replaced an imported guess,
    which is the work this project is made of. Flipping one back silently is
    the cheapest way to lose it.
    """
    assert sim.USE_MEASURED_ADVANCEMENT is True
    assert sim.USE_MEASURED_INHERITED is True
    assert sim.USE_TTO is True
    assert game.USE_MEASURED_RELIEF_LENGTH is True
    assert game.USE_MEASURED_RELIEF_HOOK is True
    # Deliberately OFF, each for a recorded reason — the learned hook was
    # shipped on a false premise, and the early branches buy the disaster
    # tail with spread. Pinned so a flip is a decision, not a drift.
    assert game.USE_LEARNED_HOOK is False
    assert sim.Hook().early_innings == 0
    assert sim.Hook().mid_per_inning_run == 0.0
    # A start has to be bounded from above by something.
    assert 95 <= sim.Hook().hard_pitch_cap <= 130, sim.Hook().hard_pitch_cap


def check_the_leash_reaches_a_full_game_and_not_only_a_start():
    """THE GAP THIS FILE EXISTS FOR, found again on 2026-08-25.

    Every `build_side` caller passes `hook=None`, and until this was fixed
    that fell through to a bare league `Hook()` — so `sim.for_start`, and
    with it the whole per-pitcher leash, reached `sim.simulate_start` and
    never reached `game.simulate_game`. The start-level path is the one
    `calibrate`, `quote`, `price` and `f5` use, so the mechanism measured
    correctly there while the engine that produces TEAM TOTALS, which is the
    stated product, ran without it.

    It surfaced as a paired prefix ladder printing EXACTLY +0.0000 at F1,
    F3, F5 and F7 over 1,615 games. Read that as a plumbing failure, never
    as a null: two model states that agree to four decimals on 1,615 games
    are the same model.
    """
    saved = sim._LEASH
    sim._LEASH = {"p": -1.5}
    try:
        def mean_outs(apply_leash):
            tot = 0
            for i in range(120):
                rng = random.Random(11 + i)
                a = game.build_side(_pitcher(), _pen(), _nine(), None, rng,
                                    apply_leash=apply_leash)
                h = game.build_side(_pitcher(), _pen(), _nine(), None, rng,
                                    apply_leash=apply_leash)
                r = game.simulate_game(a, h, dict(LG), rng)
                tot += r.away_sp.outs + r.home_sp.outs
            return tot / 240
        on, off = mean_outs(True), mean_outs(False)
    finally:
        sim._LEASH = saved
    # -1.5 is worth about +2.3 outs on the measured sweep; a full game caps
    # a starter at 27 outs so require a clear move rather than the exact one
    assert on - off > 1.0, (on, off)


def check_a_tuner_can_switch_the_leash_off_at_the_side():
    """`calibrate.run(flat=True)` fits global hook parameters with everyone
    on the league curve, because searching them while per-pitcher offsets
    absorb the error drives them somewhere meaningless. The full-game
    engine needs the same escape hatch or every tuner that moved to it
    silently fits against a leashed model."""
    saved = sim._LEASH
    sim._LEASH = {"p": -2.0}
    try:
        rng = random.Random(1)
        side = game.build_side(_pitcher(), _pen(), _nine(), None, rng,
                               apply_leash=False)
        assert side.hook.team_offset == 0.0, side.hook.team_offset
        rng = random.Random(1)
        side = game.build_side(_pitcher(), _pen(), _nine(), None, rng)
        assert side.hook.team_offset == -2.0, side.hook.team_offset
    finally:
        sim._LEASH = saved
