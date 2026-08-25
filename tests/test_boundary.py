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
