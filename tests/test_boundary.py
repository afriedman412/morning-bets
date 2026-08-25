"""The two-hook measurement: mid-inning rescue vs end-of-inning routine."""
from src.context import boundary


def _play(inning, top, pid, event, outs_before, away=0, home=0, pitches=3):
    return {
        "about": {"inning": inning, "isTopInning": top},
        "matchup": {"pitcher": {"id": pid}, "batter": {"id": 900 + outs_before}},
        "result": {"eventType": event, "awayScore": away, "homeScore": home},
        "count": {"outs": outs_before},
        "playEvents": [{"isPitch": True}] * pitches,
        "runners": [],
    }


def _game(plays):
    return {"allPlays": plays}


def check_a_completed_inning_is_a_boundary_exit():
    """Three outs recorded and then a new pitcher is the routine hook."""
    pid, relief = 1, 2
    plays = [_play(1, True, pid, "strikeout", 0),
             _play(1, True, pid, "field_out", 1),
             _play(1, True, pid, "field_out", 2),
             _play(2, True, relief, "strikeout", 0)]
    rows = boundary.exits("g", _game(plays))
    assert len(rows) == 1, rows
    assert rows[0]["kind"] == "boundary", rows[0]


def check_a_reliever_finishing_the_inning_is_a_mid_inning_exit():
    """Pulled with outs left to get is the rescue, and must not be pooled
    with the routine hook — the whole two-model split rests on this line."""
    pid, relief = 1, 2
    plays = [_play(1, True, pid, "single", 0),
             _play(1, True, pid, "single", 0),
             _play(1, True, relief, "field_out", 0)]
    rows = boundary.exits("g", _game(plays))
    assert rows[0]["kind"] == "mid", rows[0]


def check_current_inning_damage_resets_but_cumulative_does_not():
    """The feature the shipped model lacks. A starter who allowed two in the
    first and nothing in the second must show inn_br 0, not 2 — otherwise
    'is he in trouble RIGHT NOW' is just cumulative traffic again."""
    pid, relief = 1, 2
    plays = [_play(1, True, pid, "single", 0),
             _play(1, True, pid, "single", 1),
             _play(1, True, pid, "field_out", 2),
             _play(2, True, pid, "strikeout", 0),
             _play(2, True, pid, "field_out", 1),
             _play(2, True, pid, "field_out", 2),
             _play(3, True, relief, "strikeout", 0)]
    r = boundary.exits("g", _game(plays))[0]
    assert r["inn_br"] == 0, f"current-inning traffic did not reset: {r}"
    assert r["br"] == 2, f"cumulative traffic was reset: {r}"
    assert r["kind"] == "boundary", r


def check_runs_are_attributed_to_the_inning_they_scored_in():
    """inn_runs is read off the score delta, so a scoring play in the second
    must not be charged to the first."""
    pid, relief = 1, 2
    plays = [_play(1, True, pid, "field_out", 0),
             _play(1, True, pid, "field_out", 1),
             _play(1, True, pid, "field_out", 2),
             _play(2, True, pid, "home_run", 0, away=2),
             _play(2, True, pid, "field_out", 0, away=2),
             _play(2, True, pid, "field_out", 1, away=2),
             _play(2, True, pid, "field_out", 2, away=2),
             _play(3, True, relief, "strikeout", 0, away=2)]
    r = boundary.exits("g", _game(plays))[0]
    assert r["runs"] == 2, r
    assert r["inn_runs"] == 2, r


def check_the_starter_is_the_first_pitcher_not_the_busiest():
    """Whoever throws the first pitch to a side owns the start; taking the
    pitcher with the most batters would hand a short start to the bulk arm."""
    opener, bulk = 1, 2
    plays = [_play(1, True, opener, "strikeout", 0),
             _play(1, True, opener, "field_out", 1),
             _play(1, True, opener, "field_out", 2)]
    plays += [_play(i, True, bulk, "field_out", o)
              for i in range(2, 5) for o in (0, 1, 2)]
    r = boundary.exits("g", _game(plays))[0]
    assert r["pitcher"] == opener, r


def check_both_sides_are_measured_separately():
    """Top and bottom halves each have their own starter and their own
    running state; sharing one would double-count every pitch."""
    away_sp, home_sp, relief = 1, 2, 3
    plays = [_play(1, True, away_sp, "strikeout", 0),
             _play(1, True, away_sp, "field_out", 1),
             _play(1, True, away_sp, "field_out", 2),
             _play(1, False, home_sp, "single", 0),
             _play(1, False, home_sp, "single", 0),
             _play(1, False, relief, "field_out", 0),
             _play(2, True, relief, "strikeout", 0)]
    rows = {r["side"]: r for r in boundary.exits("g", _game(plays))}
    assert rows["home"]["kind"] == "boundary", rows["home"]
    assert rows["away"]["kind"] == "mid", rows["away"]
    assert rows["home"]["pitches"] == 9, rows["home"]
    assert rows["away"]["pitches"] == 6, rows["away"]


def check_every_starter_plate_appearance_gets_one_removal_decision():
    """The invariant the boundary bug violated.

    `_half_inning` used to break out of its loop on the third out BEFORE
    reaching the removal block, and `_end_of_inning` returns early whenever
    the learned hook is on — so the plate appearance that ENDED an inning
    never produced a decision. 72,426 instrumented hook calls across 2,000
    simulated games all came back at outs 0, 1 or 2, never at a boundary,
    and the starter-length distribution put 7.6% of exits on a completed
    inning against a league 64.1%.

    Counting calls is what catches it. An earlier version of this check
    asserted that every observed `outs` was in (0, 1, 2), which is true
    whether or not the boundary roll exists — it passed against the
    reintroduced bug and guarded nothing. Measured here: with the roll the
    shortfall is 0-1 decisions a game, without it 17-21.

    The tolerance of 1 is the final plate appearance of the game, which has
    no decision after it, and the walk-off path, which returns before the
    removal block by design.
    """
    import random

    from src.context import game, removal, sim

    lg = sim.league()
    p = sim.PitcherRates(name="p", k_pct=0.22, bb_pct=0.08, hr_pct=0.03,
                         babip=0.29, pa=500)
    nine = [sim.BatterRates(name=f"b{i}", k_pct=0.22, bb_pct=0.08,
                            hr_pct=0.03, babip=0.29, pa=400)
            for i in range(9)]
    orig = removal.predict
    for seed in (3, 7, 11):
        n = [0]
        try:
            removal.predict = lambda st: (n.__setitem__(0, n[0] + 1), 0.0)[1]
            rng = random.Random(seed)
            a = game.build_side(p, [], nine, None, rng)
            h = game.build_side(p, [], nine, None, rng)
            game.simulate_game(a, h, lg, rng)
        finally:
            removal.predict = orig
        bf = a.line.batters + h.line.batters
        assert bf - n[0] <= 1, (
            f"seed {seed}: {bf} starter plate appearances but only {n[0]} "
            f"removal decisions — {bf - n[0]} were skipped, which is the "
            f"inning-ending ones")


def check_a_boundary_pull_inherits_nothing():
    """He finished the inning, so there are no runners to hand over.

    The mid-inning path sets `pulled_mid_inning`, `left_on_base` and
    `outs_when_pulled` because a reliever inherits that state. A boundary
    pull must not, or the inherited-runner machinery plays out runners who
    were never on base and charges the reliever for them.

    `_boundary_roll` is exercised directly. Driving a whole game cannot
    isolate it: a certainty hazard fires on the first mid-inning roll, and
    both paths can present outs=2, so there is no state that reaches only
    the boundary branch.
    """
    import random

    from src.context import game, removal, sim

    p = sim.PitcherRates(name="p", k_pct=0.22, bb_pct=0.08, hr_pct=0.03,
                         babip=0.29, pa=500)
    nine = [sim.BatterRates(name=f"b{i}", k_pct=0.22, bb_pct=0.08,
                            hr_pct=0.03, babip=0.29, pa=400)
            for i in range(9)]
    side = game.Side(starter=p, pen=[p], lineup=nine)
    fr = sim.Frame()
    fr.outs = 3
    side.line.pitches, side.line.batters, side.line.outs = 90, 24, 18

    orig = removal.predict
    try:
        removal.predict = lambda st: 1.0
        game._boundary_roll(side, fr, 6, 0, random.Random(1), 2)
    finally:
        removal.predict = orig

    assert side.starter_out, "a certainty hazard did not remove the starter"
    assert not side.line.pulled_mid_inning, \
        "a boundary pull was recorded as a mid-inning handover"
    assert side.cur_entry_outs == 0, \
        f"the reliever inherited {side.cur_entry_outs} outs from a clean inning"


def check_the_boundary_roll_uses_the_pre_plate_appearance_out_count():
    """`outs` in the learned model is outs BEFORE the plate appearance.

    A PA never begins with three out, so the coefficients have never seen
    outs=3. Passing `fr.outs` straight through — which is 3 at a boundary —
    would extrapolate the strongest secondary feature off the end of its
    fitted range on every boundary decision in every game.
    """
    import random

    from src.context import game, removal, sim

    p = sim.PitcherRates(name="p", k_pct=0.22, bb_pct=0.08, hr_pct=0.03,
                         babip=0.29, pa=500)
    nine = [sim.BatterRates(name=f"b{i}", k_pct=0.22, bb_pct=0.08,
                            hr_pct=0.03, babip=0.29, pa=400)
            for i in range(9)]
    side = game.Side(starter=p, pen=[p], lineup=nine)
    fr = sim.Frame()
    fr.outs = 3
    seen = []
    orig = removal.predict
    try:
        removal.predict = lambda st: (seen.append(st["outs"]), 0.0)[1]
        game._boundary_roll(side, fr, 6, 0, random.Random(1), 1)
    finally:
        removal.predict = orig
    assert seen == [1], f"expected the pre-PA count, got {seen}"


def check_the_boundary_hook_respects_its_flag():
    """A/B measurement depends on the flag actually gating the path."""
    import random

    from src.context import game, removal, sim

    p = sim.PitcherRates(name="p", k_pct=0.22, bb_pct=0.08, hr_pct=0.03,
                         babip=0.29, pa=500)
    nine = [sim.BatterRates(name=f"b{i}", k_pct=0.22, bb_pct=0.08,
                            hr_pct=0.03, babip=0.29, pa=400)
            for i in range(9)]
    side = game.Side(starter=p, pen=[p], lineup=nine)
    fr = sim.Frame()
    fr.outs = 3
    orig, flag = removal.predict, game.USE_BOUNDARY_HOOK
    try:
        removal.predict = lambda st: 1.0
        game.USE_BOUNDARY_HOOK = False
        game._boundary_roll(side, fr, 6, 0, random.Random(1), 2)
        assert not side.starter_out, "the off switch did not gate the path"
        game.USE_BOUNDARY_HOOK = True
        game._boundary_roll(side, fr, 6, 0, random.Random(1), 2)
        assert side.starter_out, "the on switch did not reach the path"
    finally:
        removal.predict, game.USE_BOUNDARY_HOOK = orig, flag
