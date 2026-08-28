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

from src.context import calibrate as cal
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
            return sum(sim._advance([None, True, None],
                                    sim.B1, rng, 1)[0]
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
    from src.context.sources import rates as rate_src
    assert rate_src.USE_PRIOR_SEASON is True
    assert rate_src.PRIOR_SEASONS == 3, rate_src.PRIOR_SEASONS


def check_the_prior_season_reaches_a_thin_pitchers_rate():
    """THE FLAG DOES NOTHING ON ITS OWN, and that is the point of this check.

    `_PRIOR` is a module global that only the experiment ever populated, so
    `USE_PRIOR_SEASON = True` without the lazy load in `_ensure_prior` leaves
    it empty and every rate shrinks to the league exactly as before. A flag
    that is switched on and reaches nothing is the failure mode this file was
    created for, and it has now happened three times in this project.

    Asserted on a THIN line, because that is the only place a shrink target
    can show: a pitcher with a full season of his own barely moves whatever
    he is shrunk toward.
    """
    from src.context.sources import rates as rate_src
    was, prior, for_ = (rate_src.USE_PRIOR_SEASON, dict(rate_src._PRIOR),
                        rate_src._PRIOR_FOR)
    thin = [{"name": "A", "o": 30, "h": 12, "bb": 6, "k": 8, "hr": 2,
             "apps": 4}]
    lg = {"k_pct": 0.22, "bb_pct": 0.08, "hr_pct": 0.03, "babip": 0.29}
    # A prior with a strikeout rate nothing like the league's, so the two
    # targets cannot be confused for one another.
    fake = {"A": {"name": "A", "pa": 700, "k_pct": 0.40, "bb_pct": 0.08,
                  "hr_pct": 0.03, "babip": 0.29}}
    try:
        rate_src.USE_PRIOR_SEASON = False
        rate_src._PRIOR, rate_src._PRIOR_FOR = {}, None
        off = rate_src.pitcher_rates(lg, 2026, conn=_FakeConn(thin))
        rate_src.USE_PRIOR_SEASON = True
        rate_src._PRIOR, rate_src._PRIOR_FOR = fake, 2026
        on = rate_src.pitcher_rates(lg, 2026, conn=_FakeConn(thin))
    finally:
        rate_src.USE_PRIOR_SEASON = was
        rate_src._PRIOR, rate_src._PRIOR_FOR = prior, for_
    assert on["A"]["k_pct"] > off["A"]["k_pct"] + 0.01, (off, on)


def check_the_prior_is_loaded_without_anyone_calling_set_prior():
    """The half the check above does NOT cover, and it took a mutation to
    see that: it populates `_PRIOR` by hand, so it passes with the lazy load
    torn out and the flag reaching nothing.

    In production NOTHING calls `set_prior` — only the memory experiment
    ever did — so `pitcher_rates` has to load it itself on first use. This
    asserts the trigger fires, and that it fires for the RIGHT season: the
    prior for 2026 is built from 2025 back, and an off-by-one here would
    quietly shrink this season toward itself.
    """
    from src.context.sources import rates as rate_src
    was, prior, for_ = (rate_src.USE_PRIOR_SEASON, dict(rate_src._PRIOR),
                        rate_src._PRIOR_FOR)
    real = rate_src.set_prior
    called = []

    def fake_set_prior(season, lg_now=None, seasons=None):
        called.append(season)
        rate_src._PRIOR = {"A": {"name": "A", "pa": 700, "k_pct": 0.40,
                                 "bb_pct": 0.08, "hr_pct": 0.03,
                                 "babip": 0.29}}
        return 1

    rows = [{"name": "A", "o": 30, "h": 12, "bb": 6, "k": 8, "hr": 2,
             "apps": 4}]
    lg = {"k_pct": 0.22, "bb_pct": 0.08, "hr_pct": 0.03, "babip": 0.29}
    try:
        rate_src.set_prior = fake_set_prior
        rate_src.USE_PRIOR_SEASON = True
        rate_src._PRIOR, rate_src._PRIOR_FOR = {}, None
        got = rate_src.pitcher_rates(lg, 2026, conn=_FakeConn(rows))
    finally:
        rate_src.set_prior = real
        rate_src.USE_PRIOR_SEASON = was
        rate_src._PRIOR, rate_src._PRIOR_FOR = prior, for_
    assert called == [2025], called
    assert got["A"]["k_pct"] > 0.23, got["A"]


def check_building_the_prior_does_not_recurse_into_the_prior():
    """`set_prior` builds the prior by calling `pitcher_rates`, which is the
    function that asks for one. Without the re-entrancy guard that is either
    infinite or, worse, finite and wrong — each season's rates shrunk toward
    the seasons behind it before being blended, compounding three seasons
    into nine.
    """
    from src.context.sources import rates as rate_src
    was, prior, for_ = (rate_src.USE_PRIOR_SEASON, dict(rate_src._PRIOR),
                        rate_src._PRIOR_FOR)
    seen = []
    rows = [{"name": "A", "o": 30, "h": 12, "bb": 6, "k": 8, "hr": 2,
             "apps": 4}]
    lg = {"k_pct": 0.22, "bb_pct": 0.08, "hr_pct": 0.03, "babip": 0.29}
    try:
        rate_src.USE_PRIOR_SEASON = True
        rate_src._PRIOR, rate_src._PRIOR_FOR = {}, None
        rate_src._LOADING = True
        seen.append(rate_src._ensure_prior(2026))
    finally:
        rate_src._LOADING = False
        rate_src.USE_PRIOR_SEASON = was
        rate_src._PRIOR, rate_src._PRIOR_FOR = prior, for_
    assert seen == [{}], seen
    assert lg and rows


class _FakeConn:
    """Just enough connection to feed `pitcher_rates` its rows offline."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, *a, **k):
        return self

    def fetchall(self):
        return self._rows


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


def check_the_hook_argument_reaches_the_replayed_game():
    """`calibrate.run(hook=...)` must actually use the hook it is given.

    THE BUG THIS EXISTS FOR. `run` accepted a `hook` argument, documented it,
    and passed it nowhere: `replay` did not take one, so both sides were
    built with `hook=None` and fell through to a bare league `Hook()`. Every
    candidate `calibrate.tune` scored was therefore the SAME hook, and a full
    coordinate descent over ten parameters returned "nothing improves
    anything" with the loss identical to five decimal places.

    That is the recorded diagnostic, third time it has paid: an
    identical-to-many-decimals A/B is a plumbing result, never a null. The
    proof was cruder than the loss — a never-pull hook and a
    pull-immediately hook both returned 15.54 mean outs.

    Asserted with hooks whose effect is enormous rather than realistic, so
    the check tests the WIRING and cannot fail for a tuning reason.
    """
    never = sim.Hook(intercept=-99.0, mid_intercept=-99.0,
                     hard_pitch_cap=100000)
    quick = sim.Hook(intercept=9.0, mid_intercept=9.0)

    def mean_outs(h):
        res = cal.run(n_sims=2, max_starts=40, hook=h, seed=0)
        o = [r.outs for r in res["sim"]]
        return sum(o) / len(o)

    a, b = mean_outs(never), mean_outs(quick)
    assert a > b + 10, (a, b)


def check_the_early_exit_mixture_is_off_by_default():
    """Built on day eleven, UNSCORED, and inert until it is.

    Its fitting script (`scratchpad/fit_survivors.py`) ran on the mislabelled
    boundary rows and has to be re-run before any of it means anything, so
    the mechanism ships switched off rather than half-trusted.
    """
    h = sim.Hook()
    assert h.early_exit_p == 0.0, h.early_exit_p
    assert h.early_exit_floor == 0, h.early_exit_floor
    assert sim.EARLY_EXIT_DIST == {}, sim.EARLY_EXIT_DIST


def check_the_early_exit_mixture_reaches_a_simulated_start():
    """Both halves: the forced exit fires, and the floor suppresses the hook.

    The floor is the half that is easy to get wrong and invisible if you do —
    without it the hook keeps making its own short starts on top of the lump
    and the mixture produces more early exits than the league does.
    """
    was = dict(sim.EARLY_EXIT_DIST)
    try:
        sim.EARLY_EXIT_DIST.clear()
        sim.EARLY_EXIT_DIST[7] = 1          # every early exit lands on 7
        # p=1.0: every start is an early exit, so every starter must stop at
        # 7 outs however well he is pitching.
        hook = sim.Hook(early_exit_p=1.0, early_exit_floor=12)
        outs = []
        for seed in range(6):
            rng = random.Random(seed)
            side = game.build_side(_pitcher(), _pen(), _nine(), hook, rng,
                                   apply_leash=False)
            assert side.forced_exit_outs == 7, side.forced_exit_outs
            other = game.build_side(_pitcher(), _pen(), _nine(), hook, rng,
                                    apply_leash=False)
            game.simulate_game(side, other, LG, rng)
            outs.append(side.line.outs)
        assert all(7 <= o <= 9 for o in outs), outs

        # p=0.0 with a floor: no start is drawn as an early exit, and the
        # hook may not pull anybody before the floor.
        hook = sim.Hook(early_exit_p=0.0, early_exit_floor=12)
        outs = []
        for seed in range(8):
            rng = random.Random(100 + seed)
            side = game.build_side(_pitcher(), _pen(), _nine(), hook, rng,
                                   apply_leash=False)
            assert side.forced_exit_outs is None
            other = game.build_side(_pitcher(), _pen(), _nine(), hook, rng,
                                    apply_leash=False)
            game.simulate_game(side, other, LG, rng)
            outs.append(side.line.outs)
        assert min(outs) >= 12, outs
    finally:
        sim.EARLY_EXIT_DIST.clear()
        sim.EARLY_EXIT_DIST.update(was)


def check_the_bullpen_gets_the_same_shrink_target_as_the_rotation():
    """`bullpens` CARRIED A COPY of the rate block with `lg[stat]` hardcoded.

    Every improvement to the shrink target therefore reached starters only —
    including the multi-season prior shipped on 2026-08-26 — and reached them
    in the population where the target matters least. A reliever's median
    line is 106 batters faced against a starter's 480, so 38% of a reliever's
    strikeout rate IS the target against 11% of a starter's.

    Both call `rates.shrink_target` now. This asserts the reliever path
    actually consults it, because two code paths for one concept is the
    failure this whole file exists for.
    """
    from src.context.sources import rates as rate_src

    rows = [{"name": "Elite Arm", "team": "NYY", "o": 90, "h": 20, "bb": 10,
             "k": 30, "hr": 3, "apps": 40}]
    lg = {"k_pct": 0.22, "bb_pct": 0.08, "hr_pct": 0.03, "babip": 0.29}
    # A prior nothing like the league, so the two targets cannot be confused.
    fake = {"Elite Arm": {"name": "Elite Arm", "pa": 700, "k_pct": 0.42,
                          "bb_pct": 0.08, "hr_pct": 0.03, "babip": 0.29}}
    was, prior, for_ = (rate_src.USE_PRIOR_SEASON, dict(rate_src._PRIOR),
                        rate_src._PRIOR_FOR)
    try:
        rate_src.USE_PRIOR_SEASON = False
        rate_src._PRIOR, rate_src._PRIOR_FOR = {}, None
        off = rate_src.bullpens(lg, conn=_FakeConn(rows))
        rate_src.USE_PRIOR_SEASON = True
        rate_src._PRIOR, rate_src._PRIOR_FOR = fake, 2026
        on = rate_src.bullpens(lg, conn=_FakeConn(rows))
    finally:
        rate_src.USE_PRIOR_SEASON = was
        rate_src._PRIOR, rate_src._PRIOR_FOR = prior, for_
    a = off["NYY"][0]["k_pct"]
    b = on["NYY"][0]["k_pct"]
    assert b > a + 0.01, (a, b)


def check_defence_is_neutralised_out_and_applied_back_once():
    """Defence belongs to the SIDE IN THE FIELD, not to the pitcher.

    `rates` removes his own club's gloves from his observed BABIP to recover
    what he would allow behind an average defence; `build_side` puts
    TONIGHT'S club back on, for every arm that takes the mound. Two opposite
    uses of one number.

    Getting this wrong in the obvious way — applying without neutralising —
    counts defence twice, which is exactly what `NEUTRALISE_PARK` being off
    did to park factors. Getting it wrong the other way silently drops the
    mechanism.

    A round trip therefore has to return the original: neutralise, apply,
    and a pitcher who stays with his own club is unchanged.
    """
    from src.context.sources import rates as rate_src

    was = rate_src.USE_TEAM_DEFENCE
    real = rate_src._defence_targets
    try:
        rate_src.USE_TEAM_DEFENCE = True
        rate_src._defence_targets = lambda season=None: {"NYY": 0.012}
        d = rate_src.defence_delta("NYY")
        assert abs(d - 0.012) < 1e-9, d
        observed = 0.280
        neutral = observed + d          # what `rates` stores
        tonight = neutral - d           # what `build_side` puts back
        assert abs(tonight - observed) < 1e-12, (neutral, tonight)
        # A club with no OAA row gets league-neutral, never a neighbour's.
        assert rate_src.defence_delta("ZZZ") == 0.0
        assert rate_src.defence_delta(None) == 0.0
        # And the flag genuinely gates it.
        rate_src.USE_TEAM_DEFENCE = False
        assert rate_src.defence_delta("NYY") == 0.0
    finally:
        rate_src.USE_TEAM_DEFENCE = was
        rate_src._defence_targets = real


def check_the_rates_neutralise_defence_out_of_the_observed_babip():
    """THE HALF A MUTATION FOUND UNGUARDED, and it is the expensive half.

    Deleting the neutralisation leaves `build_side` applying a defence on top
    of a rate that already contains one — counted twice, silently, exactly as
    `NEUTRALISE_PARK` being off counted park 1.5x. Every check still passed.

    Asserted on the STORED rate: two arms with identical counting lines, one
    on a good defence and one on an unmapped club, must NOT come out equal.
    The good-defence arm stores a HIGHER BABIP, because those gloves are
    being removed to recover what he would allow behind an average one.
    """
    from src.context.sources import rates as rate_src

    def rows(team):
        return [{"name": "A", "team": team, "o": 90, "h": 20, "bb": 10,
                 "k": 30, "hr": 3, "apps": 40}]

    lg = {"k_pct": 0.22, "bb_pct": 0.08, "hr_pct": 0.03, "babip": 0.29}
    was, real = rate_src.USE_TEAM_DEFENCE, rate_src._defence_targets
    try:
        rate_src.USE_TEAM_DEFENCE = True
        rate_src._defence_targets = lambda season=None: {"NYY": 0.020}
        good = rate_src.bullpens(lg, conn=_FakeConn(rows("NYY")))
        none = rate_src.bullpens(lg, conn=_FakeConn(rows("ZZZ")))
    finally:
        rate_src.USE_TEAM_DEFENCE = was
        rate_src._defence_targets = real
    a = good["NYY"][0]["babip"]
    b = none["ZZZ"][0]["babip"]
    # THE EXPECTED GAP IS DERIVED, NOT HARDCODED. It was `> 0.002`, which
    # was implicitly calibrated to a babip shrinkage constant of 500 and was
    # only just clearing its own bar; raising the constant to the measured
    # 3068 dropped the real gap to 0.0005 and failed a check whose mechanism
    # was working perfectly. The neutralisation enters the OBSERVED rate, so
    # what survives into the stored one is the delta times the shrink
    # weight — pin that, and the check stops depending on a constant it is
    # not about.
    bip = rate_src.balls_in_play(90 + 20 + 10, 30, 10, 3)
    k = (rate_src.STABILISE_MEASURED["pit"]["babip"]
         if rate_src.USE_MEASURED_STABILISE else rate_src.STABILISE["babip"])
    want = 0.020 * bip / (bip + k)
    assert abs((a - b) - want) < 1e-9, (a, b, a - b, want)


def check_the_side_applies_defence_to_the_bullpen_too():
    """THE POINT OF MOVING IT. A defence attached to each pitcher's rates has
    to be applied once per code path and was therefore applied to starters
    only. Attached to the SIDE it reaches every arm for free.
    """
    from src.context.sources import rates as rate_src

    was = rate_src.USE_TEAM_DEFENCE
    real = rate_src._defence_targets
    try:
        rate_src.USE_TEAM_DEFENCE = True
        rate_src._defence_targets = lambda season=None: {"NYY": 0.020}
        rng = random.Random(4)
        good = game.build_side(_pitcher(), _pen(), _nine(), None, rng,
                               team="NYY", apply_leash=False)
        rng = random.Random(4)
        neutral = game.build_side(_pitcher(), _pen(), _nine(), None, rng,
                                  team="ZZZ", apply_leash=False)
    finally:
        rate_src.USE_TEAM_DEFENCE = was
        rate_src._defence_targets = real
    assert good.starter.babip < neutral.starter.babip - 0.01, (
        good.starter.babip, neutral.starter.babip)
    assert good.pen and len(good.pen) == len(neutral.pen)
    for a, b in zip(good.pen, neutral.pen):
        assert a.babip < b.babip - 0.01, (a.babip, b.babip)


def check_relievers_shrink_toward_the_reliever_league():
    """A reliever is not a starter and the shrink target dominates him.

    Counted on 2026: relievers allow 12% FEWER home runs (0.0280 against
    0.0319) and walk 18% MORE (0.0972 against 0.0823). The pitcher home-run
    shrink constant is 934 against a reliever's median 106 batters faced, so
    ~90% of his home-run rate IS the target — and it was the rotation's.

    `_starter_league` stays the log5 ANCHOR; only what a thin line is pulled
    toward moves. Both halves are asserted, because swapping the anchor
    instead would be a much larger change wearing the same name.
    """
    from src.context.sources import rates as rate_src

    assert rate_src.USE_RELIEVER_LEAGUE is True
    pen = rate_src.reliever_league(2026)
    assert pen, "the reliever league did not load"
    assert pen["hr_pct"] < 0.031, pen
    assert pen["bb_pct"] > 0.090, pen
    # The rotation baseline must be UNCHANGED — it is still the anchor.
    lg = sim.league(2026)
    assert lg["hr_pct"] > 0.031, lg
    assert lg["bb_pct"] < 0.090, lg


def check_the_handedness_flag_stays_off_because_it_makes_things_worse():
    """MEASURED 2026-08-27, and this is not the usual "it does nothing".

    The shipped `batter_rates_by_hand` shrinks each split toward the
    hitter's OWN OVERALL RATE, so a thin split regresses to no platoon
    effect at all — the one answer known to be false. Scored leak-free on
    the starters' own lines it costs +2.9 sd on strikeouts and +9.9 sd on
    walks against handedness off.

    Pinned rather than deleted because the flag is one line and the instinct
    to flip it is correct-sounding. The correct prior is the LEAGUE platoon
    cell for the side he bats from, and even that scores flat, because the
    lineup card is already the adjustment.
    """
    from src.context import calibrate as cal
    from src.context.sources import rates as rate_src

    assert cal.USE_HANDEDNESS is False
    # The constant that defines the broken prior. If someone rebuilds the
    # split path, this name should go with it.
    assert rate_src.SPLIT_STABILISE == 120, rate_src.SPLIT_STABILISE
    doc = cal.__doc__ or ""
    import inspect
    src = inspect.getsource(cal)
    i = src.index("USE_HANDEDNESS = False")
    assert "MAKES THE MODEL WORSE" in src[:i], \
        "the measurement must stay next to the flag"


def check_the_raw_prior_flag_reaches_the_prior():
    """A flag that changes nothing is the failure mode this file exists for.

    `USE_RAW_PRIOR` ships OFF after losing on F5, and an inert switch and a
    switch with a measured negative look identical from the outside. The
    prior's home-run spread is the quantity it moves, and it moves it by a
    factor of thirty — double-shrinking flattens a pitcher's multi-season
    record to almost nothing.
    """
    import statistics as st
    from src.context import sim
    from src.context.sources import rates as rate_src

    was = rate_src.USE_RAW_PRIOR
    lg = sim.league()
    try:
        out = {}
        for flag in (False, True):
            rate_src.USE_RAW_PRIOR = flag
            rate_src._PRIOR, rate_src._PRIOR_FOR = {}, None
            p = rate_src._ensure_prior(2026)
            out[flag] = st.pstdev([v["hr_pct"] for v in p.values()])
        assert out[True] > out[False] * 5, out
    finally:
        rate_src.USE_RAW_PRIOR = was
        rate_src._PRIOR, rate_src._PRIOR_FOR = {}, None
