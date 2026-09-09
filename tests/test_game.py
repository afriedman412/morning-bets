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


def check_the_signed_margin_terms_stay_at_zero():
    """The SIGNED margin coefficients measured null and must not acquire a
    value by drift.

    322,205 real removal decisions: boundary +0.00479 +/- 0.00664 (z +0.7),
    mid-inning -0.00566 +/- 0.00611 (z -0.9), both powered to resolve 0.02
    log-odds per run at 3 sigma. A manager does NOT treat a starter
    differently for his own club being ahead rather than behind — what he
    responds to is the game being decided either way, which is
    `mid_per_abs_margin` and is guarded separately below.
    """
    h = sim.Hook()
    assert h.per_margin == 0.0 and h.mid_per_margin == 0.0


def check_the_blowout_term_is_symmetric_and_suppresses_mid_inning_pulls():
    """`mid_per_abs_margin` is UNSIGNED, and that is the finding.

    Counted at -0.0824 +/- 0.0079 (z -10.4) over 248,568 mid-inning
    decisions, stable in sign across all four seasons. Two properties have
    to hold and neither is implied by the other:

      1. SYMMETRY. Up five and down five are the same decision. Wiring the
         coefficient onto the signed `margin` instead of `abs(margin)`
         passes any level check and fails this one.
      2. DIRECTION. A wider gap means FEWER mid-inning changes — the
         manager stops interrupting an inning once the game is decided.
    """
    h = sim.Hook()
    assert h.mid_per_abs_margin < 0.0
    tied = h.mid_removal_p(90, 3, 2, 1.0, margin=0)
    for m in (2, 5, 8):
        ahead = h.mid_removal_p(90, 3, 2, 1.0, margin=m)
        behind = h.mid_removal_p(90, 3, 2, 1.0, margin=-m)
        assert abs(ahead - behind) < 1e-12, f"not symmetric at {m}"
        assert ahead < tied, f"a {m}-run gap did not suppress the pull"


def check_a_dealing_starter_survives_the_mid_inning_hook_longer():
    """`late_mid_per_k_rate` is the only input to either hook curve that is
    not traffic or workload.

    Counted at -1.5130 +/- 0.1587 (z -9.5) over 248,568 mid-inning
    decisions, every season negative. Three properties, and the third is
    the one that is easy to lose:

      1. DIRECTION. Higher strikeout rate, lower chance of being pulled.
      2. IT REACHES THE DECISION at all — a term wired onto an argument the
         engine never passes is invisible to every level check.
      3. IT IS CENTRED. At the league baseline the term contributes exactly
         nothing, so it buys discrimination between starts without moving
         the calibrated level. An uncentred version would subtract 0.34
         log-odds from every mid-inning decision, which is a level change
         nobody measured.
    """
    h = sim.Hook()
    assert h.late_mid_per_k_rate < 0.0

    # CENTRING, ASSERTED AGAINST THE TERM BEING ABSENT. Comparing
    # k_rate=BASELINE against k_rate=None only proves None defaults to the
    # baseline — an uncentred build passes that happily, which it did.
    # The real claim is that at the baseline the term contributes NOTHING,
    # so the comparison has to be against a hook with the coefficient off.
    off = sim.Hook(late_mid_per_k_rate=0.0)
    at_base = h.mid_removal_p(90, 3, 2, 1.0, margin=0,
                              k_rate=sim.K_RATE_BASELINE)
    absent = off.mid_removal_p(90, 3, 2, 1.0, margin=0,
                               k_rate=sim.K_RATE_BASELINE)
    assert abs(at_base - absent) < 1e-12, "the term is not centred"

    unaware = h.mid_removal_p(90, 3, 2, 1.0, margin=0, k_rate=None)
    assert abs(at_base - unaware) < 1e-12, "None does not mean league-neutral"

    dealing = h.mid_removal_p(90, 3, 2, 1.0, margin=0, k_rate=0.40)
    struggling = h.mid_removal_p(90, 3, 2, 1.0, margin=0, k_rate=0.05)
    assert dealing < at_base < struggling, "dominance does not reach the hook"


def check_the_engine_passes_a_live_strikeout_rate_to_the_hook():
    """The coefficient above is worthless if `game.py` never hands it a
    rate. Guarded separately from the curve because the two fail
    independently — and a missing argument defaults to None, which is
    silently neutral rather than loud.
    """
    import inspect
    src = inspect.getsource(game._half_inning)
    assert "k_rate=" in src, "the mid-inning hook call passes no k_rate"
    assert "ln.batters" in src, "k_rate is not built from a live count"


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
    relief.continues = lambda entry_outs, extra, **kw: 1.0
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
    relief.continues = lambda entry_outs, extra, **kw: 1.0
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

    def spy(self, entry_outs=0, *a, **kw):
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

    def spy(entry_outs, extra, **kw):
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
    relief.mid_removal = lambda runs, batters, entry_inning=None: 1.0
    seen = []
    orig_next = game.Side.next_arm

    def spy(self, entry_outs=0, *a, **kw):
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
    relief.mid_removal = lambda runs, batters, entry_inning=None: 1.0
    seen = []
    orig_next = game.Side.next_arm

    def spy(self, entry_outs=0, *a, **kw):
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


def check_per_batter_hits_and_bases_are_recorded_and_consistent():
    """The offence tallies carry H/TB/HR per batter, and they cohere.

    Total bases are hits plus extra bases, so per batter `tb >= h + 3*hr`
    (a homer is one hit worth four bases) and `hr <= h`. A tally that
    counted every hit as one base, or dropped the increment entirely,
    fails one of these — verified by mutation.
    """
    hit = 0
    for seed in range(20):
        away = _side(starter=_pitcher(name="a", k_pct=0.05, bb_pct=0.10,
                                      hr_pct=0.06, babip=0.40),
                     pen=_pen(k_pct=0.05, bb_pct=0.10, hr_pct=0.06,
                              babip=0.40))
        home = _side(starter=_pitcher(name="h", k_pct=0.05, bb_pct=0.10,
                                      hr_pct=0.06, babip=0.40),
                     pen=_pen(k_pct=0.05, bb_pct=0.10, hr_pct=0.06,
                              babip=0.40))
        r = game.simulate_game(away, home, dict(LG), random.Random(seed))
        for bats in (r.away_bats, r.home_bats):
            for who, v in bats.items():
                assert v["hr"] <= v["h"], (seed, who, v)
                assert v["tb"] >= v["h"] + 3 * v["hr"], (seed, who, v)
                assert v["tb"] <= 4 * v["h"], (seed, who, v)
                hit += v["h"]
    assert hit > 0, "no hits recorded across 20 high-babip games"


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


def check_tonights_stuff_is_drawn_per_start_and_is_mean_one():
    """`sim.sharpen` is the per-start strikeout draw, counted at 0.1625.

    THREE PROPERTIES, and the second is the one that is easy to lose. A
    bare exp(sigma*z) has mean exp(sigma^2/2) — at 0.1625 that is +1.33%
    of strikeouts added to EVERY start, a level change nobody measured
    riding in on a spread that was counted.
    """
    import math
    import statistics as st
    p = sim.PitcherRates(name="x", k_pct=0.23, bb_pct=0.08,
                         hr_pct=0.03, babip=0.29)
    rng = random.Random(4)
    v = [sim.sharpen(p, rng).k_pct / 0.23 for _ in range(40000)]

    # 1. CENTRED: the multiplier averages one.
    assert abs(st.mean(v) - 1.0) < 0.01, st.mean(v)
    # 2. THE COUNTED SPREAD, on the log scale it was measured on.
    sd = st.pstdev([math.log(x) for x in v])
    assert abs(sd - sim.START_K_SIGMA) < 0.005, sd
    # 3. IT ONLY TOUCHES STRIKEOUTS. The four-channel version was measured
    #    and rejected — it widened traffic, which is what the hook reads.
    one = sim.sharpen(p, random.Random(9))
    assert one.bb_pct == p.bb_pct and one.hr_pct == p.hr_pct
    assert one.babip == p.babip


def check_sharpness_off_consumes_no_random_variate():
    """OFF must restore the previous engine EXACTLY, not merely closely.

    A draw taken and discarded shifts every downstream variate, so an A/B
    against the flag would compare two different random streams and read
    as a mechanism. Same rule as `USE_FIELD_STATE`'s empty table.
    """
    a, b = random.Random(7), random.Random(7)
    p = sim.PitcherRates(name="x", k_pct=0.23, bb_pct=0.08,
                         hr_pct=0.03, babip=0.29)
    assert sim.sharpen(p, a, sigma=0.0).k_pct == p.k_pct
    assert a.random() == b.random(), "sigma=0 consumed a variate"


def check_only_the_starter_gets_tonights_stuff():
    """Relievers get no draw, because none was counted for them.

    A one-inning outing cannot separate a flat slider from three bad
    swings. Importing the starter's sigma would repeat the exact error
    that hit-by-pitch, sacrifices and wild pitches all carried — measured
    on starters, applied to every arm.
    """
    import inspect
    src = inspect.getsource(game.build_side)
    assert "sim.sharpen(starter" in src, "the starter is not sharpened"
    assert "sharpen(a" not in src and "sharpen(arm" not in src


def check_bullpen_state_reaches_both_hook_curves():
    """The FIRST mechanism that belongs on both curves.

    Margin and dominance are mid-inning only — the boundary decision took
    neither. It is not deaf: it is deaf to the GAME and responds to
    RESOURCES. Counted at z -5.6/+6.4 (boundary) and -5.6/+6.3
    (mid-inning) over 322,205 real decisions.

    Direction on both: a pen with arms that cannot go keeps the starter
    out there; a rested pen gets him lifted.
    """
    h = sim.Hook()
    neutral = (sim.PEN_BACK2_BASELINE, sim.PEN_REST_BASELINE)
    for call in (lambda pen: h.removal_p(90, 3, 6, 4, 0, pen=pen),
                 lambda pen: h.mid_removal_p(90, 3, 2, 1.0, margin=0,
                                             pen=pen)):
        base = call(neutral)
        assert call((3.0, 1.0)) < base, "a gassed pen did not extend him"
        assert call((0.0, 2.0)) > base, "a rested pen did not shorten him"


def check_bullpen_state_is_centred_on_both_curves():
    """At the league mean the term contributes EXACTLY nothing.

    Asserted against the coefficients being zero, not against `pen=None` —
    comparing to None only proves None is neutral, which an uncentred
    build passes happily. That exact mistake was made and caught by
    mutation on the dominance term hours earlier.
    """
    h = sim.Hook()
    off = sim.Hook(per_pen_back2=0.0, per_pen_rest=0.0,
                   mid_per_pen_back2=0.0, mid_per_pen_rest=0.0)
    neutral = (sim.PEN_BACK2_BASELINE, sim.PEN_REST_BASELINE)
    assert abs(h.removal_p(90, 3, 6, 4, 0, pen=neutral)
               - off.removal_p(90, 3, 6, 4, 0, pen=neutral)) < 1e-12
    assert abs(h.mid_removal_p(90, 3, 2, 1.0, margin=0, pen=neutral)
               - off.mid_removal_p(90, 3, 2, 1.0, margin=0,
                                   pen=neutral)) < 1e-12


def check_an_unknown_club_gets_the_league_pen_not_a_guess():
    """Missing-group rule, and this one has a real gap behind it.

    The first game of a season has no yesterday, and a club whose previous
    game is not cached has no lookup. Both fall through to the league
    baseline, which contributes zero — never another club's bullpen.
    """
    assert sim.pen_state(None, None) == (sim.PEN_BACK2_BASELINE,
                                         sim.PEN_REST_BASELINE)
    assert sim.pen_state("NOWHERE FC", "2026-08-01") == (
        sim.PEN_BACK2_BASELINE, sim.PEN_REST_BASELINE)


def check_the_engine_looks_up_pen_state_by_date():
    """A table keyed one way and a caller keying it another is a SILENT
    null: it produced 0% coverage and a believable "the mechanism does not
    help" before the coverage was checked.

    The replay path carries an ABBREVIATION ('COL') and the games table a
    full name, so the persisted table carries both.
    """
    import inspect
    src = inspect.getsource(game.build_side)
    assert "sim.pen_state(team, date)" in src, "build_side skips the lookup"
    import json
    import os
    from src.context import sim as _s
    assert os.path.exists(_s._PENSTATE_PATH)
    tbl = json.load(open(_s._PENSTATE_PATH))
    assert any(k.startswith("COL|") for k in tbl), "no abbreviation keys"
    assert any(k.startswith("COLORADO ROCKIES|") for k in tbl), "no name keys"


def check_the_high_pitch_branch_fires_on_both_curves():
    """A third hook branch above `high_pitch_threshold`, counted because
    the shipped curves under-pull a tiring starter.

    Real pull rate above 90 pitches is 0.8285 at a boundary where the
    shipped curve gave 0.6806, and 0.2344 mid-inning against 0.1934. The
    offsets are +0.8550 (24 sigma) and +0.2893 (13 sigma).

    BOTH curves carry it. The boundary decision is the one that matters
    most here — a starter at 100 pitches is pulled 97% of the time in real
    baseball and the shipped curve gave 81%.
    """
    h = sim.Hook()
    t = h.high_pitch_threshold
    assert h.high_pitch_bnd > 0 and h.high_pitch_mid > 0
    # BOUNDARY: crossing the threshold must raise the pull probability.
    assert h.removal_p(t, 3, 6, 4, 0) > h.removal_p(t - 1, 3, 6, 4, 0)
    # MID-INNING: same, and it is a separate coefficient on a separate
    # curve — wiring one and not the other is the failure this guards.
    assert (h.mid_removal_p(t, 3, 2, 1.0, margin=0)
            > h.mid_removal_p(t - 1, 3, 2, 1.0, margin=0))


def check_the_high_pitch_branch_leaves_early_counts_alone():
    """It is a BRANCH, not a refit, and that distinction is load-bearing.

    Refitting the whole boundary curve on late rows was measured and made
    the simulation WORSE (mean outs 16.49 -> 16.74) because that curve is
    evaluated at every pitch count. Below the threshold nothing may move.
    """
    h = sim.Hook()
    off = sim.Hook(high_pitch_bnd=0.0, high_pitch_mid=0.0)
    for p in (40, 60, 75, 89):
        assert abs(h.removal_p(p, 3, 6, 4, 0)
                   - off.removal_p(p, 3, 6, 4, 0)) < 1e-12, p
        assert abs(h.mid_removal_p(p, 3, 2, 1.0, margin=0)
                   - off.mid_removal_p(p, 3, 2, 1.0, margin=0)) < 1e-12, p


def check_the_layoff_reaches_both_hook_curves():
    """A starter back from an absence is pulled sooner, on BOTH curves.

    Counted on 278,062 in-season starter decisions: step +0.597 (boundary)
    and +0.347 (mid), slope +0.0441 and +0.0242 per day beyond ten. The
    direction is the whole claim — a longer absence means a shorter leash,
    so removal probability must RISE with the gap.
    """
    h = sim.Hook()
    for call in (lambda g: h.removal_p(90, 3, 6, 4, 0, layoff_gap=g),
                 lambda g: h.mid_removal_p(90, 3, 2, 1.0, margin=0,
                                           layoff_gap=g)):
        normal = call(5)
        assert call(15) > normal, "a layoff did not shorten the leash"
        # THE SLOPE, not just the step: both terms ship and a build with
        # only the step would pass a 5-vs-15 check alone.
        assert call(30) > call(15), "the term does not grow with the gap"


def check_the_layoff_is_centred_on_both_curves():
    """At the league mean the term contributes EXACTLY nothing.

    Asserted against the coefficients being zero rather than against
    `layoff_gap=None`, for the reason recorded on the bullpen version:
    comparing to None only proves None is neutral, which an UNCENTRED
    build passes happily.
    """
    h = sim.Hook()
    off = sim.Hook(per_layoff=0.0, per_layoff_day=0.0,
                   mid_per_layoff=0.0, mid_per_layoff_day=0.0)
    # THE BASELINES ARE ASSERTED AS LITERALS, not read back off the module.
    # Computing the expectation from `sim.LAYOFF_*_BASELINE` moves both
    # sides of the comparison together, so zeroing them passes — which is
    # exactly what the first version of this check did, and the mutation
    # sweep caught it. These are the league means over the 284,706
    # in-season decisions the coefficients were fitted on.
    assert abs(sim.LAYOFF_STEP_BASELINE - 0.0668) < 1e-9
    assert abs(sim.LAYOFF_SLOPE_BASELINE - 0.7262) < 1e-9
    assert abs(h._layoff(None, h.per_layoff, h.per_layoff_day)) < 1e-12
    # A starter on a NORMAL TURN sits below the league mean and therefore
    # gets a small NEGATIVE offset. An uncentred build gives exactly zero
    # here, which is the mutation this catches.
    for c_step, c_slope, want in (
            (h.per_layoff, h.per_layoff_day, -0.0727),
            (h.mid_per_layoff, h.mid_per_layoff_day, -0.0418)):
        assert abs(h._layoff(5, c_step, c_slope) - want) < 1e-3, want
    # And a zeroed build must differ from the shipped one at a real gap,
    # or the assertions above would be vacuous.
    assert abs(h.removal_p(90, 3, 6, 4, 0, layoff_gap=25)
               - off.removal_p(90, 3, 6, 4, 0, layoff_gap=25)) > 1e-6
    assert abs(h.mid_removal_p(90, 3, 2, 1.0, margin=0, layoff_gap=25)
               - off.mid_removal_p(90, 3, 2, 1.0, margin=0,
                                   layoff_gap=25)) > 1e-6


def check_the_layoff_slope_is_capped():
    """A 120-day return must not run the hook off a cliff.

    The fit capped the slope at `LAYOFF_GAP_CAP`, so serving it uncapped
    would extrapolate a coefficient past every gap it was measured on.
    """
    h = sim.Hook()
    at_cap = h.removal_p(90, 3, 6, 4, 0, layoff_gap=sim.LAYOFF_GAP_CAP)
    assert abs(h.removal_p(90, 3, 6, 4, 0, layoff_gap=200) - at_cap) < 1e-12


def check_an_unknown_layoff_contributes_nothing():
    """Missing-group rule, and the season break is a DELIBERATE None.

    A pitcher opening a season has had a spring to build up and is not the
    same case as one returning in August, so the in-season coefficient
    must not be evaluated on him.
    """
    assert sim.layoff_gap(None, None) is None
    assert sim.layoff_gap("Nobody At All", "2026-08-01") is None
    h = sim.Hook()
    assert abs(h.removal_p(90, 3, 6, 4, 0, layoff_gap=None)
               - h.removal_p(90, 3, 6, 4, 0)) < 1e-12


def check_the_layoff_never_reaches_a_reliever():
    """The term was counted on STARTER decisions only.

    Both hook call sites are guarded by `not side.starter_out`, which is
    why the gap is carried on the Side rather than on the arm. If a future
    edit moves either call out from behind that guard, this fails.
    """
    import inspect
    src = inspect.getsource(game)
    for i, line in enumerate(src.splitlines()):
        if "layoff_gap=side.layoff_gap" not in line:
            continue
        window = "\n".join(src.splitlines()[max(0, i - 40):i])
        assert "starter_out" in window, (
            f"hook call at line {i} is not guarded by starter_out")


def check_the_engine_looks_up_the_layoff_by_pitcher_and_date():
    """A lookup a caller forgets is a SILENT null.

    `build_side` must ask for the gap by the starter's own name — the same
    failure `check_the_engine_looks_up_pen_state_by_date` exists for, where
    a shipped mechanism contributed exactly zero in four drivers because
    an argument was omitted.
    """
    import inspect
    src = inspect.getsource(game.build_side)
    assert "sim.layoff_gap(starter.name, date)" in src, \
        "build_side skips the layoff lookup"


def _pen_side(arms):
    return game.Side(starter=sim.PitcherRates(name="sp"), pen=arms,
                     lineup=[sim.BatterRates(name=f"b{i}")
                             for i in range(9)])


def check_pen_roles_ship_on_with_the_counted_profile():
    """The flag defaults ON, every bucket's five weights are a
    probability distribution, and the two signatures the count found are
    pinned absolutely (a table reset to uniform agrees with itself):
    protecting a lead leans hard on the best fifth, and a blowout leans
    on the BOTTOM of the pen — good arms are saved, not just deployed."""
    assert game.USE_PEN_ROLES, "ships ON"
    for b, w in game.PEN_PICK.items():
        assert abs(sum(w) - 1.0) < 2e-3, (b, sum(w))
    assert game.PEN_PICK["lead"][0] > 0.40
    assert game.PEN_PICK["blowout"][4] > game.PEN_PICK["blowout"][0]
    assert game.PEN_PICK["lead"][0] > game.PEN_PICK["trail"][0] > \
        game.PEN_PICK["blowout"][0]


def check_late_pen_selection_reads_the_margin():
    """Behavioural, through `next_arm` itself: over many fresh pens the
    arm handed the ball protecting a one-run lead in the eighth is
    better (K%-BB%) than the one mopping up a six-run game — and before
    the seventh the order is untouched and NO randomness is consumed,
    which is what keeps F5 bit-identical."""
    def arms():
        return [sim.PitcherRates(name=f"r{i}", k_pct=0.18 + 0.02 * i,
                                 bb_pct=0.08) for i in range(6)]
    got = {}
    for margin in (1, -6):
        rng = random.Random(11)
        q = 0.0
        for _ in range(800):
            s = _pen_side(arms())
            s.next_arm(0, rng, 8, margin)
            q += s.current.k_pct - s.current.bb_pct
        got[margin] = q / 800
    assert got[1] > got[-6] + 0.005, got
    rng = random.Random(3)
    twin = random.Random(3)
    s = _pen_side(arms())
    s.next_arm(0, rng, 6, 1)
    assert [a.name for a in s.pen] == [f"r{i}" for i in range(6)]
    assert rng.random() == twin.random(), "inning six must consume nothing"


def check_the_pen_roll_is_drawn_whether_or_not_the_flag_uses_it():
    """The A/B rule: flag off still consumes exactly one draw at an
    eligible entry, and changes nothing else — a switch that consumes a
    different number of random numbers is not an A/B."""
    orig = game.USE_PEN_ROLES
    game.USE_PEN_ROLES = False
    try:
        rng = random.Random(5)
        twin = random.Random(5)
        s = _pen_side([sim.PitcherRates(name=f"r{i}", k_pct=0.18 + 0.02 * i)
                       for i in range(6)])
        s.next_arm(0, rng, 9, 0)
        assert [a.name for a in s.pen] == [f"r{i}" for i in range(6)]
        twin.random()
        assert rng.random() == twin.random(), "exactly one draw"
    finally:
        game.USE_PEN_ROLES = orig


def check_every_next_arm_call_passes_the_selection_context():
    """Every `next_arm` call in `src/` must pass rng, inning and margin —
    a call site that omits them silently reverts that entry to draw
    order (the same dropped-kwarg failure the DP roll's `mu` had)."""
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent / "src"
    bad = []
    for f in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(f.read_text())):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else getattr(fn, "id", None))
            if name != "next_arm":
                continue
            if len(node.args) < 4 and "rng" not in \
                    {k.arg for k in node.keywords}:
                bad.append(f"{f.relative_to(root.parent)}:{node.lineno}")
    assert not bad, bad


def check_temp_hr_ships_on_and_is_counted():
    """Flag defaults ON; no reading or flag off contributes exactly 1.0;
    the counted slope is pinned absolutely (cold suppresses, heat
    carries, monotone) — a table reset to ones agrees with itself."""
    assert sim.USE_TEMP_HR, "ships ON"
    assert sim.temp_hr_mult(None) == 1.0
    assert sim.temp_hr_mult(70) == sim.TEMP_HR_MULT[2]
    assert sim.temp_hr_mult(50) < 0.85 and sim.temp_hr_mult(90) > 1.10
    assert all(a <= b for a, b in zip(sim.TEMP_HR_MULT,
                                      sim.TEMP_HR_MULT[1:]))
    orig = sim.USE_TEMP_HR
    sim.USE_TEMP_HR = False
    try:
        assert sim.temp_hr_mult(95) == 1.0
    finally:
        sim.USE_TEMP_HR = orig


def check_the_game_carries_the_air_to_both_sides():
    """`simulate_game(hr_air=...)` must land on BOTH sides' resolved
    matchups as the HR multiplier — the two clubs hit in the same air.
    Neutral park, blank hands and no GB keep every other multiplier at
    exactly 1.0, so m_hr IS hr_air and a dropped wire reads 1.0."""
    def _s():
        return game.Side(starter=sim.PitcherRates(name="sp"), pen=[],
                         lineup=[sim.BatterRates(name=f"b{i}")
                                 for i in range(9)])
    a, h = _s(), _s()
    game.simulate_game(a, h, dict(LG), random.Random(9), hr_air=2.5)
    for s in (a, h):
        mups = [m for m in (s._mups or []) if m is not None]
        assert mups, "no matchup was ever resolved"
        assert all(m.m_hr == 2.5 for m in mups), s


def check_every_simulate_game_call_passes_the_air():
    """Every `simulate_game` call in `src/` must pass `hr_air=` AND
    `ump_kbb=` — the same presence rule as `park`, and for the same
    reason: an omitted argument doesn't raise, it silently prices every
    game at 70 degrees with a league-average zone."""
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent / "src"
    bad = []
    for f in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(f.read_text())):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else getattr(fn, "id", None))
            if name != "simulate_game":
                continue
            kws = {k.arg for k in node.keywords}
            if not {"hr_air", "ump_kbb"} <= kws:
                bad.append(f"{f.relative_to(root.parent)}:{node.lineno}")
    assert not bad, bad


def check_wind_hr_ships_on_and_is_counted():
    """Flag defaults ON; a missing reading contributes exactly 1.0; the
    counted direction is pinned absolutely (wind in suppresses, wind out
    carries) and the middle bin is neutral to within a tenth of a
    percent, which is what "crosswind" has to mean."""
    assert sim.USE_WIND_HR, "ships ON"
    assert sim.wind_hr_mult(None, 12) == 1.0
    assert sim.wind_hr_mult(-1, None) == 1.0
    assert sim.wind_hr_mult(-1, 12) < 0.96 and sim.wind_hr_mult(1, 12) > 1.02
    assert sim.wind_hr_mult(0, 20) == sim.WIND_HR_MULT[1]
    assert abs(sim.WIND_HR_MULT[1] - 1.0) < 0.001, "crosswind is no push"
    # the bin edges are symmetric about zero and 4 mph is calm both ways
    assert sim.wind_hr_mult(-1, 4) == sim.wind_hr_mult(1, 4)
    assert sim.wind_hr_mult(-1, 5) == sim.WIND_HR_MULT[0]
    assert sim.wind_hr_mult(1, 5) == sim.WIND_HR_MULT[2]
    orig = sim.USE_WIND_HR
    sim.USE_WIND_HR = False
    try:
        assert sim.wind_hr_mult(1, 20) == 1.0
    finally:
        sim.USE_WIND_HR = orig


def check_the_air_is_temperature_times_wind():
    """`air_hr_mult` is the product, and BOTH halves reach it. Either
    term dropped from the composition leaves the other's value showing,
    which is what a silent wiring loss looks like."""
    t, w = sim.temp_hr_mult(90), sim.wind_hr_mult(1, 15)
    assert t != 1.0 and w != 1.0, "the fixture must exercise both"
    assert abs(sim.air_hr_mult(90, 1, 15) - t * w) < 1e-12
    assert sim.air_hr_mult(90) == t, "wind defaults to silent-neutral"
    assert sim.air_hr_mult(None, 1, 15) == w


def check_the_shared_air_lookup_reads_the_wind_column():
    """`calibrate.air_mult_for` must use the weather row's wind, not the
    temperature alone. MUTATION: revert it to `sim.temp_hr_mult(...)`
    and this check fails while every other weather check passes."""
    import src.context.calibrate as cal
    orig = cal._WEATHER
    cal._WEATHER = {"g1": {"temp_f": 90, "carry": -1, "wind_mph": 15},
                    "g2": {"temp_f": 90, "carry": 1, "wind_mph": 15}}
    try:
        a = cal.air_mult_for({"game_id": "g1"})
        b = cal.air_mult_for({"game_id": "g2"})
        assert a < b, (a, b)
        assert abs(a - sim.air_hr_mult(90, -1, 15)) < 1e-12
        assert cal.air_mult_for({"game_id": "absent"}) == 1.0
    finally:
        cal._WEATHER = orig


def check_ump_kbb_ships_on_and_is_counted():
    """Flag defaults ON; an unknown umpire or unrecorded crew is exactly
    neutral; the shipped table is non-flat with WALKS the wider channel
    (the counted headline — bb tau is 2.5x k tau) and was fitted before
    the holdout."""
    import statistics as st
    assert sim.USE_UMP_KBB, "ships ON"
    assert sim.ump_kbb_mult(None) == (1.0, 1.0)
    assert sim.ump_kbb_mult(999999999) == (1.0, 1.0)
    table = {u: v for u, v in sim._UMP_KBB.items() if u != "_meta"}
    assert len(table) > 100, "the whole league's crews"
    ks = [v[0] for v in table.values()]
    bbs = [v[1] for v in table.values()]
    assert st.pstdev(bbs) > st.pstdev(ks) > 0.004, "non-flat, walks wider"
    assert sim._UMP_KBB["_meta"]["rows_before"] == "2026-07-01"
    uid = max(table, key=lambda u: abs(table[u][1] - 1.0))
    assert sim.ump_kbb_mult(uid) == tuple(table[uid])
    orig = sim.USE_UMP_KBB
    sim.USE_UMP_KBB = False
    try:
        assert sim.ump_kbb_mult(uid) == (1.0, 1.0)
    finally:
        sim.USE_UMP_KBB = orig


def check_the_ump_multipliers_reach_the_matchup():
    """`resolve` carries the game's k and bb multipliers into the matchup
    INDEPENDENTLY — the umpire moves each channel by its own counted
    amount, not both through one knob. MUTATION: drop either term from
    `resolve` and this fails while the air checks pass."""
    base = sim.resolve(_lineup()[0], _pitcher(), LG)
    k = sim.resolve(_lineup()[0], _pitcher(), LG, k_game=1.3)
    b = sim.resolve(_lineup()[0], _pitcher(), LG, bb_game=0.7)
    assert abs(k.m_k - base.m_k * 1.3) < 1e-9 and k.m_bb == base.m_bb
    assert abs(b.m_bb - base.m_bb * 0.7) < 1e-9 and b.m_k == base.m_k


def check_the_ump_pair_reaches_a_full_game():
    """The pair travels from `simulate_game`'s own argument down to the
    plate appearance — a strikeout umpire raises simulated K, a
    tight-zone umpire raises walks. Amplified pairs so 200 games settle
    it; the shipped table's spread is the battery's business."""
    def totals(pair):
        rng = random.Random(61)
        k = bb = 0
        for _ in range(200):
            r = game.simulate_game(_side(), _side(), LG, rng,
                                   hr_air=1.0, ump_kbb=pair)
            k += r.away_sp.k + r.home_sp.k
            bb += r.away_sp.bb + r.home_sp.bb
        return k, bb
    k0, bb0 = totals((1.0, 1.0))
    k1, bb1 = totals((1.5, 1.0))
    k2, bb2 = totals((1.0, 1.8))
    assert k1 > k0 * 1.2, (k0, k1)
    assert bb2 > bb0 * 1.3, (bb0, bb2)


def check_the_shared_ump_lookup_reads_the_crew_record():
    """`calibrate.ump_mult_for` resolves game -> plate umpire -> table,
    and a game with no recorded crew is exactly neutral. MUTATION: make
    it return (1.0, 1.0) unconditionally and this fails while every
    game-level check passes."""
    import src.context.calibrate as cal
    orig_u, orig_t = cal._UMPS, sim._UMP_KBB
    cal._UMPS = {"g1": 4242}
    sim._UMP_KBB = {"4242": [1.07, 0.91]}
    try:
        assert cal.ump_mult_for({"game_id": "g1"}) == (1.07, 0.91)
        assert cal.ump_mult_for({"game_id": "absent"}) == (1.0, 1.0)
    finally:
        cal._UMPS, sim._UMP_KBB = orig_u, orig_t


def check_the_night_term_ships_on_and_is_a_remainder():
    """The night term is live, its size is the measured remainder (the
    2026-08-27 sigma-0.10 target shrunk by everything shipped since —
    shared-night stack 10.2%, counted k-stuff 10.4%;
    `scratchpad/night_variance.py`), the draw moves bb/hr/babip
    COHERENTLY, and `k_pct` passes through UNTOUCHED — strikeout nights
    are `START_K_SIGMA`'s counted job, and loading k here would stack
    two dispersions against one count. MUTATION: flag off, sigma to
    zero, or k added back to the load, and this fails."""
    import math
    import statistics as st
    assert sim.USE_NIGHT_SIGMA, "ships ON — a user decision, recorded"
    assert abs(sim.NIGHT_SIGMA - 0.1111) < 1e-6, sim.NIGHT_SIGMA
    assert "k_pct" not in sim.NIGHT_LOAD, "k is the counted stuff's job"
    rng = random.Random(83)
    draws = [sim.night(_pitcher(), rng) for _ in range(300)]
    base = _pitcher()
    assert all(d.k_pct == base.k_pct for d in draws), "k must not move"
    bbs = [d.bb_pct / base.bb_pct for d in draws]
    bs = [d.babip / base.babip for d in draws]
    assert 0.09 < st.pstdev([math.log(b) for b in bs]) < 0.14
    # Coherence: the SAME draw moves walks and babip TOGETHER.
    assert st.correlation(bbs, bs) > 0.99, st.correlation(bbs, bs)


def check_the_night_term_off_touches_neither_rates_nor_stream():
    """The off path must return the pitcher UNCHANGED and consume NO
    draws — a flag-off battery run has to reproduce the engine
    fingerprint bit for bit, which is the proof the wire is inert.
    MUTATION: draw the gauss before the flag test and this fails."""
    orig = sim.USE_NIGHT_SIGMA
    sim.USE_NIGHT_SIGMA = False
    try:
        rng = random.Random(84)
        state = rng.getstate()
        p = _pitcher()
        assert sim.night(p, rng) is p, "off must be identity"
        assert rng.getstate() == state, "off must not consume the stream"
    finally:
        sim.USE_NIGHT_SIGMA = orig


def check_the_night_term_reaches_a_full_game():
    """The draw lands on the STARTER inside `build_side`, so simulated
    run totals spread wider with the term on than off. Amplified sigma so
    a small sample settles it; the shipped size is the battery's
    business. MUTATION: drop the `sim.night` call from `build_side` and
    this fails while the sim-level checks pass."""
    import statistics as st

    def spread(n=400, seed=85):
        rng = random.Random(seed)
        runs = []
        for _ in range(n):
            # Through `build_side`, not a hand-built Side — the draw
            # lives there, and a direct `Side(...)` never sees it.
            a = game.build_side(_pitcher(), [], _lineup(), sim.Hook(), rng)
            h = game.build_side(_pitcher(), [], _lineup(), sim.Hook(), rng)
            r = game.simulate_game(a, h, LG, rng,
                                   hr_air=1.0, ump_kbb=(1.0, 1.0))
            runs.append(r.away + r.home)
        return st.pstdev(runs)

    orig = sim.NIGHT_SIGMA
    sim.NIGHT_SIGMA = 0.5
    try:
        wide = spread()
    finally:
        sim.NIGHT_SIGMA = orig
    sim.NIGHT_SIGMA = 0.0
    try:
        flat = spread()
    finally:
        sim.NIGHT_SIGMA = orig
    assert wide > flat * 1.15, (flat, wide)


def check_no_caller_builds_the_air_from_temperature_alone():
    """`sim.air_hr_mult` is the ONLY way into the `hr_air` slot from
    `src/`. A caller that reaches past it to `temp_hr_mult` prices every
    game in still air and nothing raises — the fifth-caller failure from
    item 5, one channel down. MUTATION: put `sim.temp_hr_mult(` back in
    `slate.py` and this fails."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent / "src"
    bad = [str(f.relative_to(root.parent)) for f in sorted(root.rglob("*.py"))
           if "temp_hr_mult(" in f.read_text() and f.name != "sim.py"]
    assert not bad, bad


# --------------------------------------------------------------------------
# THE BULK ARM BEHIND AN OPENER (TODO 15). He is a STARTER, so he goes down
# the starter's path — hook, leash, times through the order — instead of
# being run as a one-inning reliever, which is what `starter_out` used to
# condemn him to.
# --------------------------------------------------------------------------

def check_the_bulk_arm_takes_the_ball_instead_of_the_pen():
    """The whole mechanism: a named bulk arm follows the opener, and
    `starter_out` STAYS FALSE so the five things that key on it — rates,
    TTO, mid-inning removal, the boundary hook, the continuation hazard —
    all keep applying to him."""
    bulk = _pitcher(name="bulk")
    s = _side(bulk=bulk, forced_exit_outs=3)
    assert s.to_bulk() is True
    assert s.starter_out is False, "the bullpen flag must not trip"
    assert s.starter is bulk, s.starter.name
    assert s.bulk_in is True


def check_the_bulk_arm_is_used_once_and_then_it_is_the_pen():
    """Second time of asking he is already out there, so the ball goes to
    the pen — otherwise one arm pitches the whole game on repeat."""
    s = _side(bulk=_pitcher(name="bulk"))
    assert s.to_bulk() is True
    assert s.to_bulk() is False


def check_no_named_bulk_arm_means_the_pen_exactly_as_before():
    """48.5% of planned openers are pure bullpen games and must be
    untouched — `to_bulk` declining is what routes them."""
    assert _side().to_bulk() is False


def check_the_bulk_arm_keeps_the_openers_line_for_props():
    """`line` is the man the board named. Handing the bulk arm the starter's
    line reports HIS fifteen outs as the opener's in every replay, and the
    prop settles on the opener."""
    s = _side(bulk=_pitcher(name="bulk"))
    s.cur_line.outs = 4
    s.cur_line.k = 2
    opener_line = s.line
    s.to_bulk()
    assert s.line is opener_line, "the opener's line was replaced"
    assert s.line.outs == 4, s.line.outs
    assert s.cur_line is not s.line
    assert s.cur_line.outs == 0, s.cur_line.outs


def check_the_bulk_arm_does_not_inherit_the_openers_drawn_exit():
    """`forced_exit_outs` was the OPENER's bootstrap draw. Left set, it pulls
    the bulk arm at the same out count the moment he arrives — a mechanism
    that fires and instantly undoes itself."""
    s = _side(bulk=_pitcher(name="bulk"), forced_exit_outs=3)
    s.to_bulk()
    assert s.forced_exit_outs is None


def check_times_through_the_order_restarts_for_the_bulk_arm():
    """The lineup has seen the OPENER, not him. Reading the SIDE's starter
    line hands him a second or third time through before he has faced nine
    men, and the counted TTO decay is 19% of K% by the third pass.

    THIS HAS TO SPY ON THE VALUE THE ENGINE PASSES, not on the line
    `to_bulk` installs. The first version asserted `cur_line.batters == 0`
    after the handover, which is true whichever line the TTO expression
    reads — it survived the mutation that pointed TTO back at `side.line`
    and guarded nothing.
    """
    # A DISTINCTIVE K RATE IS HOW HIS PLATE APPEARANCES ARE PICKED OUT.
    # `Matchup` carries no pitcher name, and pooling both sides' `tto`
    # values is what let the first version of this check pass under the
    # mutation — the HOME starter's opening pass supplied the 1 the away
    # side was supposed to produce.
    mark = 0.1111
    bulk = _pitcher(name="bulk", k_pct=mark)
    # An opener who goes twelve outs has faced enough men to put the side's
    # starter line into its SECOND pass, so the two readings disagree.
    away = _side(bulk=bulk, forced_exit_outs=12)
    home = _side()
    ttos = []
    orig = sim.pa_from

    def spy(mu, rng, tto=None, **kw):
        if abs(mu.p_k - mark) < 1e-9 and tto is not None:
            ttos.append(tto)
        return orig(mu, rng, tto=tto, **kw)
    try:
        sim.pa_from = spy
        game.simulate_game(away, home, dict(LG), random.Random(19))
    finally:
        sim.pa_from = orig
    assert away.bulk_in is True, "the mechanism never fired"
    assert ttos, "the bulk arm never faced anyone"
    assert min(ttos) == 1, ttos


def check_the_bulk_flag_off_sends_him_to_the_pen():
    """OFF must be the pre-item engine: the ball goes to the bullpen."""
    keep = game.USE_BULK_STARTER
    game.USE_BULK_STARTER = False
    try:
        assert _side(bulk=_pitcher(name="bulk")).to_bulk() is False
    finally:
        game.USE_BULK_STARTER = keep


def check_the_bulk_arm_gets_a_shorter_leash_than_his_own_start():
    """The counted -3.15 outs, and it must arrive as a hook the engine can
    read rather than as a number in a docstring. A POSITIVE `team_offset`
    shift is a shorter leash."""
    rng = random.Random(11)
    s = game.build_side(_pitcher(), [], _lineup(), sim.Hook(), rng,
                        team="XXX", date="2026-05-01",
                        bulk=_pitcher(name="bulk"))
    assert s.bulk_hook is not None
    assert s.bulk_hook.team_offset > s.hook.team_offset, (
        s.bulk_hook.team_offset, s.hook.team_offset)


def check_a_bulk_arm_actually_reaches_a_simulated_game():
    """PLUMBING, and this project has shipped three flags that never arrived.
    An opener forced out after three outs, with a named follower, must leave
    that follower on the mound and pitching — not the first man in the pen.
    """
    bulk = _pitcher(name="bulk")
    away = _side(bulk=bulk, forced_exit_outs=3)
    home = _side()
    # His own line is folded away when his own hook eventually pulls him —
    # which it should, this is a nine-inning game — so grab it at handover
    # rather than asserting on the state at the final out.
    seen = []
    orig = game.Side.to_bulk
    try:
        def spy(self):
            ok = orig(self)
            if ok:
                seen.append((self.starter, self.cur_line))
            return ok
        game.Side.to_bulk = spy
        game.simulate_game(away, home, dict(LG), random.Random(7))
    finally:
        game.Side.to_bulk = orig
    assert away.bulk_in is True
    assert seen and seen[0][0] is bulk, seen
    assert seen[0][1].batters > 0, "he never faced anyone"


# --------------------------------------------------------------------------
# THE CLOSER'S SLOT (TODO 21). `PEN_PICK` was counted POOLED over innings
# 7-9, so the engine could spend a club's best arm two innings early.
# --------------------------------------------------------------------------

def check_the_best_arm_is_saved_for_the_ninth():
    """The whole item, and it is not a blur but an error at BOTH ends:
    protecting a lead, the real share of entries taking the best remaining
    arm is 0.3356 in the 7th and 0.5750 in the 9th against a pooled 0.4415.
    If this ordering ever flattens, the table has been regressed to the
    pooled row — which still produces a plausible mean reliever quality and
    is exactly what would get believed."""
    lead7 = game.PEN_PICK_BY_INNING[("lead", "7")][0]
    lead8 = game.PEN_PICK_BY_INNING[("lead", "8")][0]
    lead9 = game.PEN_PICK_BY_INNING[("lead", "9+")][0]
    assert lead7 < lead8 < lead9, (lead7, lead8, lead9)
    pooled = game.PEN_PICK["lead"][0]
    assert lead7 < pooled < lead9, (lead7, pooled, lead9)


def check_every_inning_cell_is_a_distribution():
    """Five weights that do not sum to one silently reweight the whole
    profile, and `next_arm` walks them cumulatively so the error lands on
    the last bin."""
    for key, w in game.PEN_PICK_BY_INNING.items():
        assert len(w) == 5, key
        assert abs(sum(w) - 1.0) < 0.001, (key, sum(w))


def check_extras_take_the_ninth_inning_slot():
    """The same arms work the tenth as the ninth. Falling through to a
    missing cell would raise, and keying extras to their own row would count
    them on nothing."""
    assert game._pick_inning(9) == "9+"
    assert game._pick_inning(12) == "9+"
    assert game._pick_inning(7) == "7"
    assert game._pick_inning(8) == "8"


def check_the_inning_split_actually_changes_who_pitches_the_seventh():
    """PLUMBING. A constant table that never reaches `next_arm` is the
    failure this project has shipped three times, and it looks identical to
    a mechanism that did not help.

    Protecting a lead in the SEVENTH, the split should reach for the best
    remaining arm LESS often than the pooled table does.
    """
    def best_share(flag):
        keep = game.USE_PEN_INNING
        game.USE_PEN_INNING = flag
        try:
            hits = 0
            for i in range(400):
                rng = random.Random(i)
                # Rank 0 is the highest K%-BB%, so name the arms by quality.
                pen = [sim.PitcherRates(name=f"R{j}", k_pct=0.30 - 0.02 * j,
                                        bb_pct=0.05, hr_pct=LG["hr_pct"],
                                        babip=LG["babip"], pa=200)
                       for j in range(5)]
                # `starter_out` stays False so `slot` is 0 and the WHOLE
                # pen is the pool — setting it True first marks `pen[0]` as
                # already used and the best arm can never be picked, which
                # reads as 0.0 either way and looks like a dead flag.
                s = _side(pen=pen)
                s.next_arm(0, rng, 7, 2)
                hits += s.current.name == "R0"
            return hits / 400
        finally:
            game.USE_PEN_INNING = keep

    pooled, split = best_share(False), best_share(True)
    assert split < pooled - 0.03, (pooled, split)
