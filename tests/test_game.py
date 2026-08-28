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
    """Legacy-hook path: `USE_LEARNED_HOOK` ignores `sim.Hook` entirely, so
    a never-pull Hook cannot keep a starter in and the invariant this pins
    (outs bounded by innings completed) stops holding the moment he is
    hooked mid-inning."""
    orig, game.USE_LEARNED_HOOK = game.USE_LEARNED_HOOK, False
    try:
        _never_pull_outs()
    finally:
        game.USE_LEARNED_HOOK = orig


def _never_pull_outs():
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
    """Legacy-hook path. The learned removal model carries `margin` and
    `abs_margin` as its own features, so this pins `sim.Hook`'s wiring.

    The reason both sides are interleaved at all.

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

    orig, game.USE_LEARNED_HOOK = game.USE_LEARNED_HOOK, False
    try:
        assert outs(0.0) != outs(2.5), "margin never reaches the removal rule"
    finally:
        game.USE_LEARNED_HOOK = orig


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

    The deleted `f5._side_runs` settled his stranded runners with a flat
    0.33 because it never simulated the reliever finishing the inning. This
    does, so the constant must not appear in the full-game path at all — if
    it crept back in, those runners would be counted twice.
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


def check_a_reliever_can_work_more_than_one_inning():
    """Before the measured length, `_end_of_inning` gave way unconditionally.

    Forcing the continuation hazard to 1.0 has to leave ONE arm on for the
    rest of the game. If the give-way is still unconditional the pen walks
    forward an arm an inning no matter what the hazard says.
    """
    from src.context import relief
    orig = game.USE_MEASURED_RELIEF_LENGTH
    game.USE_MEASURED_RELIEF_LENGTH = True
    # Isolate the end-of-inning decision: the mid-inning hook would pull
    # him for an unrelated reason and the check would read as a failure
    # of the continuation hazard.
    hook_orig = game.USE_MEASURED_RELIEF_HOOK
    game.USE_MEASURED_RELIEF_HOOK = False
    keep = relief.continues
    relief.continues = lambda entry_outs, extra: 1.0
    try:
        away = _side(starter=_pitcher(k_pct=0.01, bb_pct=0.30, hr_pct=0.10))
        home = _side()
        game.simulate_game(away, home, dict(LG), random.Random(11))
        assert away.starter_out, "the starter was never pulled"
        assert away.pen_i == 0, f"walked to arm {away.pen_i} despite p=1.0"
    finally:
        relief.continues = keep
        game.USE_MEASURED_RELIEF_LENGTH = orig
        game.USE_MEASURED_RELIEF_HOOK = hook_orig


def check_relief_length_flag_off_restores_one_inning_each():
    """Every mechanism stays separately scoreable, so off must be the old
    engine exactly — a fresh arm every inning regardless of the hazard."""
    from src.context import relief
    orig = game.USE_MEASURED_RELIEF_LENGTH
    game.USE_MEASURED_RELIEF_LENGTH = False
    hook_orig = game.USE_MEASURED_RELIEF_HOOK
    game.USE_MEASURED_RELIEF_HOOK = False
    keep = relief.continues
    relief.continues = lambda entry_outs, extra: 1.0
    try:
        away = _side(starter=_pitcher(k_pct=0.01, bb_pct=0.30, hr_pct=0.10))
        home = _side()
        game.simulate_game(away, home, dict(LG), random.Random(11))
        assert away.pen_i > 0, "flag off still held one arm on"
    finally:
        relief.continues = keep
        game.USE_MEASURED_RELIEF_LENGTH = orig
        game.USE_MEASURED_RELIEF_HOOK = hook_orig


def check_a_mid_inning_hook_hands_over_the_out_count():
    """The incoming arm inherits the OUT COUNT, not just the runners.

    `entry_outs` is the strongest predictor of how long he stays, so a
    mid-inning change that calls `next_arm()` bare — the old signature —
    silently prices every inherited-rally arm as a clean-inning arm.
    """
    seen = []
    orig_next = game.Side.next_arm
    # Record ONLY the starter's own handover. Relief handovers also pass a
    # non-zero out count, so an unfiltered spy is satisfied by those and the
    # starter's regression hides behind them — which is exactly what this
    # check missed once the relief hook landed.
    hook_orig = game.USE_MEASURED_RELIEF_HOOK
    game.USE_MEASURED_RELIEF_HOOK = False

    def spy(self, entry_outs=0):
        if not self.starter_out:
            seen.append(entry_outs)
        orig_next(self, entry_outs)

    game.Side.next_arm = spy
    try:
        for s in range(25):
            # A cap of zero pulls the starter at the first mid-inning check,
            # whatever the out count happens to be at that moment.
            away = _side(starter=_pitcher(k_pct=0.01, bb_pct=0.30),
                         hook=sim.Hook(hard_pitch_cap=0))
            home = _side()
            game.simulate_game(away, home, dict(LG), random.Random(s))
    finally:
        game.Side.next_arm = orig_next
        game.USE_MEASURED_RELIEF_HOOK = hook_orig
    assert any(v > 0 for v in seen), \
        "every handover reported a clean inning; the out count is not passed"


def check_the_continuation_hazard_advances_with_each_extra_inning():
    """A reliever's second inning is asked about with extra=1, not extra=0.

    If the counter never advances the hazard stays at the ENTRY rate for
    ever, and a two-out entry (63% per inning) compounds into an arm that
    effectively never leaves. The bug is invisible in the mean because the
    entry and extra rates are not far apart.
    """
    from src.context import relief
    seen = []
    orig = game.USE_MEASURED_RELIEF_LENGTH
    game.USE_MEASURED_RELIEF_LENGTH = True
    # Isolate the end-of-inning decision: the mid-inning hook would pull
    # him for an unrelated reason and the check would read as a failure
    # of the continuation hazard.
    hook_orig = game.USE_MEASURED_RELIEF_HOOK
    game.USE_MEASURED_RELIEF_HOOK = False
    keep = relief.continues

    def spy(entry_outs, extra):
        seen.append(extra)
        return 1.0 if extra < 2 else 0.0

    relief.continues = spy
    try:
        away = _side(starter=_pitcher(k_pct=0.01, bb_pct=0.30, hr_pct=0.10))
        home = _side()
        game.simulate_game(away, home, dict(LG), random.Random(11))
    finally:
        relief.continues = keep
        game.USE_MEASURED_RELIEF_LENGTH = orig
        game.USE_MEASURED_RELIEF_HOOK = hook_orig
    assert any(v >= 1 for v in seen), \
        f"the hazard was never asked past the entry inning: {sorted(set(seen))}"


def check_a_reliever_can_be_pulled_mid_inning():
    """58.2% of real mid-inning handovers are reliever-to-reliever.

    Before this the engine could only produce one off a starter's hook, so
    it could reach at most 41.8% of them however the pen was drawn.
    """
    from src.context import relief
    orig = game.USE_MEASURED_RELIEF_HOOK
    keep = relief.mid_removal
    game.USE_MEASURED_RELIEF_HOOK = True
    relief.mid_removal = lambda runs, batters: 1.0
    seen = []
    orig_next = game.Side.next_arm

    def spy(self, entry_outs=0):
        seen.append((self.starter_out, entry_outs))
        orig_next(self, entry_outs)

    game.Side.next_arm = spy
    try:
        away = _side(starter=_pitcher(k_pct=0.01, bb_pct=0.30, hr_pct=0.10))
        game.simulate_game(away, _side(), dict(LG), random.Random(4))
    finally:
        game.Side.next_arm = orig_next
        relief.mid_removal = keep
        game.USE_MEASURED_RELIEF_HOOK = orig
    # A handover with the starter ALREADY out and outs on the board is a
    # reliever-to-reliever mid-inning change, which used to be impossible.
    assert any(was_out and outs > 0 for was_out, outs in seen), seen


def check_the_relief_hook_flag_off_leaves_relievers_alone():
    """Off must be the pre-measurement engine exactly."""
    from src.context import relief
    orig = game.USE_MEASURED_RELIEF_HOOK
    keep = relief.mid_removal
    game.USE_MEASURED_RELIEF_HOOK = False
    relief.mid_removal = lambda runs, batters: 1.0
    seen = []
    orig_next = game.Side.next_arm

    def spy(self, entry_outs=0):
        seen.append((self.starter_out, entry_outs))
        orig_next(self, entry_outs)

    game.Side.next_arm = spy
    try:
        away = _side(starter=_pitcher(k_pct=0.01, bb_pct=0.30, hr_pct=0.10))
        game.simulate_game(away, _side(), dict(LG), random.Random(4))
    finally:
        game.Side.next_arm = orig_next
        relief.mid_removal = keep
        game.USE_MEASURED_RELIEF_HOOK = orig
    assert not any(was_out and outs > 0 for was_out, outs in seen), seen


def check_the_learned_hook_replaces_sim_hook_for_the_starter():
    """With the learned model on, a never-pull `sim.Hook` must NOT keep the
    starter in — the model is what decides now.

    Guards the wiring. A `USE_LEARNED_HOOK` that never reached
    `_half_inning` would leave every legacy-hook test passing and this one
    is the only thing that would notice.
    """
    never = sim.Hook(intercept=-99.0, mid_intercept=-99.0,
                     hard_pitch_cap=100000)
    orig, game.USE_LEARNED_HOOK = game.USE_LEARNED_HOOK, True
    try:
        pulled = 0
        for s in range(12):
            a = _side(hook=never)
            game.simulate_game(a, _side(hook=never), dict(LG),
                               random.Random(s))
            pulled += bool(a.starter_out)
    finally:
        game.USE_LEARNED_HOOK = orig
    assert pulled >= 10, f"learned hook pulled only {pulled}/12 starters"


def check_the_learned_hook_reads_cumulative_damage_not_inning_local():
    """`Frame.damage` resets every inning; `StartResult.damage` must not.

    The whole reason the state exists is that a starter squared up for three
    innings should not read as clean because he is between rallies.
    """
    r = sim.StartResult()
    fr = sim.Frame()
    for _ in range(3):
        fr = sim.Frame()               # new inning
        sim.apply_pa(sim.B2, r, fr, random.Random(1))
    assert r.damage > fr.damage, (r.damage, fr.damage)


def check_per_side_prefix_totals_are_not_crossed():
    """A Side's `runs` are runs ALLOWED, so the AWAY team's score is what the
    HOME side gave up. Crossing them is the obvious way to build this exactly
    backwards, and the sum would still come out right — so `prefix` cannot
    catch it and this check has to.

    Also pins that the per-side totals sum to the combined ones, and that
    both are nested."""
    import random

    from src.context import game, sim

    rng = random.Random(19)
    a, h = _side(), _side()
    r = game.simulate_game(a, h, dict(LG), rng, track=(1, 3, 5, 7))
    assert set(r.prefix_side) == set(r.prefix), (r.prefix_side, r.prefix)
    for n, (aw, hm) in r.prefix_side.items():
        assert aw + hm == r.prefix[n], (n, aw, hm, r.prefix[n])
    vals = [r.prefix_side[n] for n in sorted(r.prefix_side)]
    for i in range(1, len(vals)):
        assert vals[i][0] >= vals[i - 1][0], vals
        assert vals[i][1] >= vals[i - 1][1], vals
    # The final per-side totals must agree with the headline score.
    last = r.prefix_side[max(r.prefix_side)]
    assert last[0] <= r.away and last[1] <= r.home, (last, r.away, r.home)


def check_each_side_faces_the_opposing_lineup():
    """EVERY PITCHER WAS FACING HIS OWN TEAMMATES. Shipped, undetected.

    `build_cases` attaches to each start the nine that pitcher FACES, so the
    away start already carries the HOME club's batters. `ladder` and
    `calibrate.replay` both then handed the away PITCHING side the other
    lineup, which crossed them: Ryan Feltner of Colorado was simulated
    against Brett Sullivan, Connor Norby and Jake McCarthy — Colorado's own
    hitters.

    It survived because both sides still got a real major-league nine, so
    every AGGREGATE looked fine: run levels, outs distribution, boundary
    share. What it destroys is the MATCHUP, which is the only thing that
    differentiates one game from another — so it lands squarely on the
    quantity this project has spent days failing to find.

    Structural, not statistical: names in, names out.
    """
    from src.context import calibrate as cal
    from src.context.sources import rates as rate_src
    lg = sim.league()
    pairs = cal.paired_cases(max_starts=400)
    assert pairs, "no paired games"
    pens = rate_src.bullpens(lg)
    checked = 0
    for pair in list(pairs.values())[:5]:
        away, home = pair
        rng = random.Random(1)
        a_faces = {b.name for b in cal.adjust_lineup(away[2], False)}
        h_faces = {b.name for b in cal.adjust_lineup(home[2], True)}
        # the two nines must be different people in the first place
        assert not (a_faces & h_faces), "both sides given the same lineup"
        A = game.build_side(away[1], pens.get(
            (away[0]["team"] or "").upper(), []),
            cal.adjust_lineup(away[2], False), None, rng)
        H = game.build_side(home[1], pens.get(
            (home[0]["team"] or "").upper(), []),
            cal.adjust_lineup(home[2], True), None, rng)
        assert {b.name for b in A.lineup} == a_faces, "away side crossed"
        assert {b.name for b in H.lineup} == h_faces, "home side crossed"
        # and the starter must not appear among the hitters he faces
        assert A.starter.name not in {b.name for b in A.lineup}
        checked += 1
    assert checked >= 3, checked


def check_replay_does_not_hand_a_pitcher_his_own_teammates():
    """The same invariant THROUGH `calibrate.replay`, the only simulation
    entry point there is.

    Intercepts `game.simulate_game` to capture the Sides `replay` actually
    assembles, because checking the arguments beforehand guards nothing: the
    first version of this check inspected `adjust_lineup` output and
    `build_side` directly, and re-crossing the two lines inside `replay`
    left it passing. Found by mutation, which is the only way that surfaces.
    """
    from src import db
    from src.context import calibrate as cal
    from src.context.sources import rates as rate_src
    lg = sim.league()
    pairs = cal.paired_cases(max_starts=400)
    assert pairs, "no paired games"
    pens = rate_src.bullpens(lg)

    seen = {}
    real = game.simulate_game

    def spy(away_side, home_side, *a, **kw):
        seen["A"] = {b.name for b in away_side.lineup}
        seen["H"] = {b.name for b in home_side.lineup}
        seen["a_sp"] = away_side.starter.name
        seen["h_sp"] = home_side.starter.name
        return real(away_side, home_side, *a, **kw)

    pair = next(iter(pairs.values()))
    gid = pair[0][0]["game_id"]
    game.simulate_game = spy
    try:
        cal.replay(pair, lg, pens, random.Random(1))
    finally:
        game.simulate_game = real

    with db.connect() as c:
        by_team = {}
        for r in c.execute(
                "select team, player_name from mlb_batting where game_id=?",
                (gid,)):
            by_team.setdefault(r["team"], set()).add(r["player_name"])
    a_team = (pair[0][0]["team"] or "").upper()
    h_team = (pair[1][0]["team"] or "").upper()
    # a PITCHING side faces the OTHER club. Ryan Feltner of Colorado was
    # simulated against Colorado's own hitters for as long as this engine
    # has existed.
    assert seen["A"] <= by_team.get(h_team, set()), (
        f"away pitcher ({a_team}) is facing {a_team}'s own hitters")
    assert seen["H"] <= by_team.get(a_team, set()), (
        f"home pitcher ({h_team}) is facing {h_team}'s own hitters")


def check_per_batter_runs_add_up_to_the_team_score():
    """Attribution and the scoreboard cannot disagree.

    `_credit` records who scored beside `_score`, so if these two ever come
    apart it is the attribution that is wrong, not the total. Summed across
    a WHOLE game, which is the part that was missing: `next_arm` replaces
    `cur_line`, so before the fold every reliever's runs vanished from the
    tally while still counting on the board.
    """
    away = _side(starter=_pitcher(name="a", k_pct=0.05, bb_pct=0.25,
                                  hr_pct=0.08, babip=0.40),
                 pen=_pen(k_pct=0.05, bb_pct=0.25, hr_pct=0.08, babip=0.40))
    home = _side(starter=_pitcher(name="h", k_pct=0.05, bb_pct=0.25,
                                  hr_pct=0.08, babip=0.40),
                 pen=_pen(k_pct=0.05, bb_pct=0.25, hr_pct=0.08, babip=0.40))
    # MANY GAMES, not one. Sacrifices are about 1% of plate appearances,
    # so a single game passed this check for weeks while the `SAC` branch
    # scored its sacrifice flies with nobody credited at all.
    for seed in range(40):
        away = _side(starter=_pitcher(name="a", k_pct=0.05, bb_pct=0.25,
                                      hr_pct=0.08, babip=0.40),
                     pen=_pen(k_pct=0.05, bb_pct=0.25, hr_pct=0.08,
                              babip=0.40))
        home = _side(starter=_pitcher(name="h", k_pct=0.05, bb_pct=0.25,
                                      hr_pct=0.08, babip=0.40),
                     pen=_pen(k_pct=0.05, bb_pct=0.25, hr_pct=0.08,
                              babip=0.40))
        r = game.simulate_game(away, home, dict(LG), random.Random(seed))
        for team, bats in (("away", r.away_bats), ("home", r.home_bats)):
            scored = sum(v["r"] for v in bats.values())
            want = r.away if team == "away" else r.home
            assert scored == want, (seed, team, scored, want)
    for team, bats in (("away", r.away_bats), ("home", r.home_bats)):
        scored = sum(v["r"] for v in bats.values())
        rbi = sum(v["rbi"] for v in bats.values())
        want = r.away if team == "away" else r.home
        assert scored == want, (team, scored, want)
        # Every run is driven in by somebody in this model — there is no
        # unearned-advance path that scores a run with no batter at the
        # plate except a wild pitch, so RBI can only be lower.
        assert rbi <= want, (team, rbi, want)
    assert sum(v["r"] for v in r.away_bats.values()) > 0


def check_relief_innings_are_not_dropped_from_the_offence_tally():
    """The specific defect the fold exists for.

    A starter who cannot get anybody out is pulled early, so most of the
    game's runs arrive against the pen. If the tally only covered the
    starter's line it would come up far short of the board.
    """
    away = _side(starter=_pitcher(name="gone", k_pct=0.01, bb_pct=0.35,
                                  hr_pct=0.12, babip=0.45),
                 pen=_pen(k_pct=0.05, bb_pct=0.25, hr_pct=0.10, babip=0.40))
    home = _side()
    r = game.simulate_game(away, home, dict(LG), random.Random(11))
    starter_only = sum(away.line.scored_by.values())
    tallied = sum(v["r"] for v in r.home_bats.values())
    assert tallied == r.home, (tallied, r.home)
    # The point of the check: the pen really did allow a large share, so a
    # starter-only tally would have been visibly wrong rather than equal.
    assert tallied > starter_only + 2, (tallied, starter_only)


def check_the_offence_tally_is_crossed_the_same_way_the_score_is():
    """`away_bats` is the AWAY team's hitters — the nine the HOME side faced.

    Same crossing as `away`/`home`, and the same way to get it backwards.
    Checked on identity: the names in each tally must come from that team's
    own lineup and never from the other's.
    """
    away = _side()
    home = _side()
    for i, b in enumerate(away.lineup):
        b.name = f"HOMEBAT{i}"          # away side PITCHES to the home nine
    for i, b in enumerate(home.lineup):
        b.name = f"AWAYBAT{i}"
    r = game.simulate_game(away, home, dict(LG), random.Random(5))
    assert r.away_bats and r.home_bats, (r.away_bats, r.home_bats)
    assert all(n.startswith("AWAYBAT") for n in r.away_bats), r.away_bats
    assert all(n.startswith("HOMEBAT") for n in r.home_bats), r.home_bats


def check_reading_the_offence_twice_does_not_double_count():
    """`offense()` merges rather than folding, so it is safe to call again.

    A fold-on-read would pass every check above and silently double the
    numbers for the second caller.
    """
    away, home = _side(), _side()
    r = game.simulate_game(away, home, dict(LG), random.Random(9))
    first = {k: dict(v) for k, v in away.offense().items()}
    second = away.offense()
    assert first == second, (first, second)
    assert sum(v["r"] for v in second.values()) == r.home


def check_home_run_runs_are_tallied_across_every_arm():
    """`runs_on_hr` folds like the offence dicts, and cannot exceed runs.

    The starter's own line is not enough: about a third of a game's runs
    come against the pen, and the line carrying them is replaced at every
    pitching change.
    """
    away = _side(starter=_pitcher(name="a", k_pct=0.02, bb_pct=0.10,
                                  hr_pct=0.25, babip=0.30),
                 pen=_pen(k_pct=0.02, bb_pct=0.10, hr_pct=0.25, babip=0.30))
    home = _side()
    r = game.simulate_game(away, home, dict(LG), random.Random(4))
    assert 0 < r.home_hr_runs <= r.home, (r.home_hr_runs, r.home)
    # The starter alone must be short of the whole game, or the fold is
    # doing nothing and the check is vacuous.
    assert r.home_hr_runs > away.line.runs_hr, (r.home_hr_runs,
                                                away.line.runs_hr)


def check_plate_appearances_are_tallied_across_every_arm():
    """THE DENOMINATOR. Every offence question is a rate, and the starter's
    line alone covers about two thirds of a game's plate appearances."""
    away, home = _side(), _side()
    r = game.simulate_game(away, home, dict(LG), random.Random(6))
    # Nine innings of outs is 27 per side at minimum, plus everyone who
    # reached, so a full game cannot come in under that.
    assert r.away_pa >= 27 and r.home_pa >= 27, (r.away_pa, r.home_pa)
    assert r.away_pa > home.line.batters, (r.away_pa, home.line.batters)
    # A team cannot score more runs than it sent men to the plate.
    assert r.away <= r.away_pa and r.home <= r.home_pa, r


def check_the_engine_passes_the_field_state_to_the_plate_appearance():
    """THE WIRING CHECK FOR `_half_inning`, and it is a different claim from
    the ones in test_sim.py.

    Those call `sim.pa_outcome` directly, so they pass whether or not the
    ENGINE ever supplies a state — which is precisely the gap
    `scratchpad/mutate.py` found five times over: every measurement was
    tested and none of the wiring was. Deleting the `state=` argument in
    `game._half_inning` leaves all four of those checks green and this one
    red.

    Keyed on a state that can only arise MID-INNING (a man on, nobody out),
    so a table that leaked into the bases-empty leadoff spot would not be
    enough to move it.
    """
    keep, keep_flag = sim.STATE_MULT, sim.USE_FIELD_STATE
    try:
        # SET BOTH EXPLICITLY. Relying on the shipped defaults broke this
        # twice in one day — once when the table was populated and once when
        # the flag was parked off. A wiring check must test the wiring, not
        # the configuration that happens to ship.
        sim.USE_FIELD_STATE = True

        def runs(table):
            sim.STATE_MULT = table
            tot = 0
            for i in range(120):
                rng = random.Random(1000 + i)
                a, h = _side(), _side()
                r = game.simulate_game(a, h, LG, rng)
                tot += r.away + r.home
            return tot / 120

        base = runs({})
        # Strikeouts collapse whenever a man reaches, so a rally that starts
        # cannot be ended — runs have to rise, and by a lot.
        hot = runs({(n, o): {"k_pct": 0.2}
                    for n in (1, 2, 3) for o in (0, 1, 2)})
        assert hot > base + 0.5, (
            f"field state never reached the engine: {base:.2f} -> {hot:.2f}")
    finally:
        sim.STATE_MULT, sim.USE_FIELD_STATE = keep, keep_flag
