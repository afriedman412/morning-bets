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
from tests import fixtures as fx

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
        return [fx.one_side(_pitcher(), _nine(), dict(LG),
                            hook or sim.Hook(), rng)
                for _ in range(n)]
    finally:
        for k, v in prev.items():
            setattr(sim, k, v)


def check_measured_advancement_reaches_the_simulated_inning():
    """`USE_MEASURED_ADVANCEMENT` was one of the five unguarded flags. It
    replaced imported advancement tables with rates counted on this league.

    THIS CHECK USED TO ASSERT ON THE RUN LEVEL AND WAS PASSING ON LUCK.
    Measured properly, the flag is worth about 0.05 runs a start (2.4040 on
    against 2.4550 off over 3,000 starts), and runs per start have an sd
    near 2.0 — so at the n=600 it could afford, the standard error on the
    difference was twice the effect. It read 2.3817 against 2.3800 and
    failed, having passed on the previous draw. Runs per baserunner is no
    better here: across n = 400 / 600 / 1000 it came out -3.8% / +0.1% /
    +4.3%, sign and all.

    So the aggregate cannot carry this check at any n the suite can afford,
    and the two halves are asserted separately instead — the same shape
    `check_errors_raise_the_run_level` was forced into.

      1. THE ENGINE CONSULTS `_advance`. Counted by instrumenting it and
         playing one real game. A flag wired to a function nothing calls is
         exactly the failure this file exists for.
      2. THE FLAG CHANGES WHAT `_advance` DOES. At 20,000 rolls of a single
         base-out state, where the measured and published tables differ by
         14% and the noise does not.
    """
    import random

    lg = dict(LG)
    calls = [0]
    real = sim._advance

    def counted(*a, **kw):
        calls[0] += 1
        return real(*a, **kw)

    sim._advance = counted
    try:
        rng = random.Random(21)
        a = game.build_side(_pitcher(), _pen(), _nine(), None, rng)
        h = game.build_side(_pitcher(), _pen(), _nine(), None, rng)
        game.simulate_game(a, h, lg, rng)
    finally:
        sim._advance = real
    assert calls[0] > 20, f"the engine barely consulted _advance ({calls[0]})"

    # A man on second, one out, and a single. Measured .542 against a
    # published .620 — a difference no 20,000-roll sample confuses.
    def scores(flag, n=20000):
        prev = sim.USE_MEASURED_ADVANCEMENT
        sim.USE_MEASURED_ADVANCEMENT = flag
        try:
            rng = random.Random(7)
            return sum(sim._advance([False, True, False], sim.B1, rng, 1)
                       for _ in range(n)) / n
        finally:
            sim.USE_MEASURED_ADVANCEMENT = prev

    on, off = scores(True), scores(False)
    assert 0.52 < on < 0.57, on
    assert 0.60 < off < 0.64, off
    assert off - on > 0.04, (on, off)


def check_inherited_runners_are_played_out_not_settled_by_a_flag():
    """`USE_MEASURED_INHERITED` was one of the five unguarded flags, and it
    is GONE rather than guarded.

    It only ever reached `sim.simulate_start`, which stopped the instant the
    hook fired and so had to settle a departing starter's stranded runners
    with a coin flip. Asserted against `simulate_game` the flag made no
    difference at all — exactly zero, 8.56 against 8.56 — because the full
    game hands the base-out state to the reliever and plays those runners
    out for real. So it retired with the one-sided engine.

    That is why this check inverts: it asserts the fudge is absent AND that
    the mechanism it stood in for is present. A reliever entering with the
    bases loaded must allow more runs than one entering clean, or inherited
    runners are not being played out at all and the deleted constant would
    have been covering for it.
    """
    assert not hasattr(sim, "USE_MEASURED_INHERITED")
    assert not hasattr(sim, "INHERITED_SCORE_RATE")

    def runs_after_handover(bases):
        tot = 0
        for i in range(400):
            rng = random.Random(70 + i)
            fr = sim.Frame(bases=list(bases), outs=1)
            side = game.Side(starter=_pitcher(), pen=[_pitcher()],
                             lineup=_nine())
            side.next_arm(fr.outs)          # the reliever walks into `fr`
            before = side.cur_line.runs
            while fr.outs < 3:
                b = side.lineup[side.idx % 9]
                side.idx += 1
                o = sim.pa_outcome(b, side.current, dict(LG), rng)
                sim.apply_pa(o, side.cur_line, fr, rng)
                if fr.outs >= 3:
                    break
                sim.baserunning(side.cur_line, fr, rng)
            tot += side.cur_line.runs - before
        return tot / 400

    loaded = runs_after_handover([True, True, True])
    clean = runs_after_handover([False, False, False])
    assert loaded > clean + 0.4, (loaded, clean)


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
    with it the whole per-pitcher leash, reached the start-level loop and
    never reached `game.simulate_game`. That loop was the one `calibrate`,
    `quote`, `price` and `f5` used, so the mechanism measured correctly
    there while the engine that produces TEAM TOTALS, which is the stated
    product, ran without it. Both the gap and the second engine are gone.

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


def check_nothing_prices_through_the_fixtures():
    """`tests/fixtures.py` mirrors the pitching side against ITSELF.

    That is a legitimate fixture and an illegitimate price. A mirror invents
    the opposing club, and inventing the opponent invents the score — which
    is what the hook, the bullpen and the margin are all conditioned on.
    `price.simulate_slate_game` DECLINES instead, the same posture the module
    already takes on openers and games in progress.

    So the boundary is one-way and this pins it: `tests/` may import `src/`,
    and nothing under `src/` may import `tests/`. Without the guard the
    cheapest fix for a missing opposing starter is to reach for the mirror,
    and it would price a real bet against a pitcher who is not in the game.
    """
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent / "src"
    bad = []
    for f in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(f.read_text())):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            if any(m.split(".")[0] == "tests" for m in mods):
                bad.append(str(f.relative_to(root.parent)))
    assert not bad, bad
