"""The real batting order, and that the simulator actually receives it."""
from src.context import calibrate as cal
from src.context import order, store


def _a_cached_game():
    with store.connect(attach=False) as c:
        r = c.execute("select game_id from mlb_lineups limit 1").fetchone()
    return r["game_id"] if r else None


def check_the_order_comes_off_play_by_play_in_sequence():
    """Nine distinct batters a side, IN THE ORDER THEY CAME UP.

    The sequence is re-derived here straight from `pbp.plays` rather than
    trusted from `from_pbp`, because asserting only "nine distinct names"
    guards nothing about order — an alphabetical sort passes it just as
    happily, which is how this check was caught by mutation.
    """
    from src.context.sources import pbp
    gid = _a_cached_game()
    assert gid, "no lineups synced"
    got = order.from_pbp(gid)
    want = {"top": [], "bottom": []}
    for play, *_ in pbp.plays(gid):
        half = (play.get("about") or {}).get("halfInning")
        nm = (((play.get("matchup") or {}).get("batter") or {})
              .get("fullName"))
        if half in want and nm and nm not in want[half] \
                and len(want[half]) < 9:
            want[half].append(nm)
    for half in ("top", "bottom"):
        nine = got[half]
        assert len(nine) == 9, (half, len(nine))
        assert len({b["name"] for b in nine}) == 9, "a batter repeats"
        assert [b["name"] for b in nine] == want[half], (
            f"{half}: order does not follow the play sequence")


def check_the_real_order_disagrees_with_the_at_bat_proxy():
    """THE WHOLE POINT. If these agreed the migration bought nothing.

    Measured over 574 lineups the proxy matched exactly 0.0% of the time and
    put the average hitter 2.30 slots away. A fixture where they happen to
    agree would make this check vacuous, so it is asserted across enough
    games that agreement everywhere is impossible.
    """
    real = order.lineups()
    proxy = cal._ab_proxy_lineups()
    shared = [k for k in real if k in proxy][:200]
    assert len(shared) > 50, len(shared)
    differ = sum(1 for k in shared if real[k][:9] != proxy[k][:9])
    assert differ > len(shared) * 0.8, (differ, len(shared))


def check_lineups_hands_back_the_OPPOSING_nine():
    """Keyed by PITCHING team, valued by who he faces. Getting this backwards
    is the crossing bug that had every starter facing his own teammates, and
    it survived undetected because both sides still got a real nine."""
    gid = _a_cached_game()
    lu = order.lineups()
    with store.connect(attach=False) as c:
        rows = {}
        for r in c.execute("select team, slot, player_name from mlb_lineups "
                           "where game_id = ? order by team, slot", (gid,)):
            rows.setdefault(r["team"], []).append(r["player_name"])
    teams = list(rows)
    assert len(teams) == 2, teams
    a, b = teams
    assert lu[(gid, a)] == rows[b], "pitching side got its own club"
    assert lu[(gid, b)] == rows[a], "pitching side got its own club"


def check_calibrate_actually_uses_the_real_order():
    """The wiring, not the measurement. `USE_REAL_ORDER` off must fall back
    to the proxy and on must not."""
    gid = _a_cached_game()
    real = order.lineups()
    key = next(k for k in real if k[0] == gid)
    prev = cal.USE_REAL_ORDER
    try:
        cal.USE_REAL_ORDER = True
        assert cal.opposing_lineups()[key][:9] == real[key][:9]
        cal.USE_REAL_ORDER = False
        assert cal.opposing_lineups()[key][:9] == \
            cal._ab_proxy_lineups()[key][:9]
    finally:
        cal.USE_REAL_ORDER = prev


def check_a_short_extraction_is_not_written_as_a_lineup():
    """A club never bats eight men. A short list means the extraction
    failed, and writing it would look like data rather than a gap."""
    with store.connect(attach=False) as c:
        bad = c.execute(
            "select game_id, team, count(*) n from mlb_lineups "
            "group by game_id, team having n != 9").fetchall()
    assert not bad, [tuple(r) for r in bad[:5]]


def check_the_real_order_ships_switched_on():
    """Pins the DEFAULT. Every check above sets `USE_REAL_ORDER` itself, so
    flipping the shipped value is invisible to all of them — found by
    mutation, and the same gap `test_wiring` exists to close."""
    assert cal.USE_REAL_ORDER is True
