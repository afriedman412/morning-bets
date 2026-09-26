"""Game-time weather: the parse, the carry sign, and the dome flag."""
from src.context import store
from src.context.sources import weather


def check_wind_is_parsed_field_relative():
    """statsapi reports wind FIELD-RELATIVE — 'Out To RF', 'In From CF' —
    so the stadium-orientation table a compass bearing would need is already
    applied upstream. Home plate faces a different direction in all thirty
    parks; MLB resolved it."""
    assert weather.parse_wind("12 mph, Out To RF") == (12, "out to rf", 1)
    assert weather.parse_wind("5 mph, In From CF") == (5, "in from cf", -1)
    assert weather.parse_wind("9 mph, L To R")[2] == 0
    assert weather.parse_wind("0 mph, None") == (0, None, 0)
    assert weather.parse_wind(None) == (0, None, 0)
    assert weather.parse_wind("garbage") == (0, None, 0)


def check_carry_is_signed_because_speed_alone_is_meaningless():
    """15 mph out and 15 mph in are OPPOSITE effects with the same number,
    and averaging them gives zero. Measured: `wind_mph * carry` reaches
    t +2.1 on hits while raw speed sits at -0.5, which is the whole
    argument for keeping the sign."""
    out = weather.parse_wind("15 mph, Out To LF")
    inn = weather.parse_wind("15 mph, In From LF")
    assert out[0] == inn[0] == 15, "speed cannot distinguish them"
    assert out[2] == -inn[2] != 0, "carry must"


def check_a_closed_roof_is_not_a_calm_day():
    """A dome reports 'Roof Closed' with '0 mph, None'. Flagged rather than
    coded as calm outdoor weather: it is no wind BY CONSTRUCTION, and
    pooling it with real still days dilutes whatever exists outdoors."""
    with store.connect(attach=False) as c:
        n = c.execute("select count(*) n from mlb_weather").fetchone()["n"]
        if not n:
            return
        dome = c.execute(
            "select count(*) n from mlb_weather where roof_closed=1"
        ).fetchone()["n"]
        assert dome > 50, dome
        # A CLOSED ROOF IS NOT ALWAYS A DOME. Six closed-roof games carry
        # a real wind direction and every one is at American Family Field
        # or T-Mobile Park — retractable roofs, and T-Mobile's is a cover
        # rather than a seal, so wind blows through the open sides. An
        # earlier version of this module zeroed `carry` under a closed roof
        # and was overriding good data with an assumption.
        kept = c.execute(
            "select count(*) n from mlb_weather "
            "where roof_closed=1 and carry != 0").fetchone()["n"]
        assert kept > 0, "closed-roof wind readings are being discarded"
        # sealed domes still resolve to calm on their own
        sealed = c.execute(
            "select count(*) n from mlb_weather "
            "where roof_closed=1 and carry = 0").fetchone()["n"]
        assert sealed > 100, sealed
        # and outdoor games must NOT all be calm, or nothing was parsed
        blow = c.execute(
            "select count(*) n from mlb_weather "
            "where roof_closed=0 and carry != 0").fetchone()["n"]
        assert blow > 200, blow


def check_both_wind_directions_are_present():
    """A parser that silently mapped everything to one sign would still
    produce a plausible-looking table. Measured: 686 blowing out against
    350 blowing in."""
    with store.connect(attach=False) as c:
        rows = {r["carry"]: r["n"] for r in c.execute(
            "select carry, count(*) n from mlb_weather "
            "where roof_closed=0 group by carry")}
    if not rows:
        return
    assert rows.get(1, 0) > 100, rows
    assert rows.get(-1, 0) > 100, rows
    assert rows.get(0, 0) > 100, rows


# ── the Open-Meteo fallback, and the cache bug that made it urgent ──

def _stub_feed(monkey_rows):
    """Stand in for statsapi so the cache logic can be tested offline."""
    import io
    import json as _json

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    payload = {"dates": [{"games": monkey_rows}]}
    calls = []

    def _open(req, timeout=None):
        calls.append(getattr(req, "full_url", req))
        return _Resp(_json.dumps(payload).encode())
    return _open, calls


def _game(pk, temp):
    g = {"gamePk": pk, "venue": {"id": 3}, "gameDate": "2026-09-23T23:10:00Z"}
    g["weather"] = ({"temp": str(temp), "condition": "Clear",
                     "wind": "5 mph, In From CF"} if temp else {})
    return g


def _with_cache(tmp, date_str, rows, mtime=None, fn=None):
    import json as _json
    import os
    import urllib.request as _u
    old_cache, old_open = weather.CACHE, _u.urlopen
    try:
        weather.CACHE = tmp
        tmp.mkdir(parents=True, exist_ok=True)
        p = tmp / f"{date_str}.json"
        p.write_text(_json.dumps(rows))
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        if fn is not None:
            _u.urlopen = fn
        return weather.fetch_date(date_str)
    finally:
        weather.CACHE, _u.urlopen = old_cache, old_open


def check_a_partial_cache_is_refetched_rather_than_frozen():
    """THE BUG THIS GUARDS shipped twice, the second time as a half-fix.

    statsapi fills a slate in start-time order, so the 1:05 game carries a
    temperature hours before the 7:10 game does. The guard was `any(...)`,
    which froze the whole date on that one day game and left every night
    game blank forever. It cost 2026-09-19 through -23 four slates
    (4/15, 6/15, 1/15, 1/16) and nothing complained, because a missing
    reading multiplies by exactly 1.0.
    """
    import pathlib
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        # cached: one game has a reading, one does not. The feed now has both.
        cached = [{"game_id": "mlb-1", "temp_f": 70, "wind_mph": 0,
                   "wind_dir": None, "carry": 0, "roof_closed": 0,
                   "condition": "Clear", "date": "2026-09-23",
                   "venue_id": 3},
                  {"game_id": "mlb-2", "temp_f": None, "wind_mph": 0,
                   "wind_dir": None, "carry": 0, "roof_closed": 0,
                   "condition": None, "date": "2026-09-23", "venue_id": 3}]
        fn, calls = _stub_feed([_game(1, 70), _game(2, 58)])
        # aged past EMPTY_TTL_SECONDS: inside the TTL it correctly holds,
        # so that a single slate run does not hammer the feed.
        import time as _t
        got = _with_cache(tmp, "2026-09-23", cached,
                          mtime=_t.time() - 2 * weather.EMPTY_TTL_SECONDS,
                          fn=fn)
        assert calls, "a partial date must go back to the feed"
        assert {r["game_id"]: r["temp_f"] for r in got} == {
            "mlb-1": 70, "mlb-2": 58}, got


def check_a_complete_cache_is_not_refetched():
    """The flip side: a date where every game has a reading is final, and
    re-pulling it would hammer a free public feed for nothing."""
    import pathlib
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        cached = [{"game_id": "mlb-1", "temp_f": 70, "wind_mph": 0,
                   "wind_dir": None, "carry": 0, "roof_closed": 0,
                   "condition": "Clear", "date": "2026-09-23",
                   "venue_id": 3}]
        fn, calls = _stub_feed([_game(1, 99)])
        got = _with_cache(tmp, "2026-09-23", cached, fn=fn)
        assert not calls, "a complete date must be served from cache"
        assert got[0]["temp_f"] == 70


def check_a_refetch_never_trades_a_reading_for_a_hole():
    """statsapi CLEARS `weather` once a game is over, so a late refetch of
    a finished slate can come back emptier than what is already cached.
    Merging is what keeps the observation we already captured."""
    import pathlib
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        cached = [{"game_id": "mlb-1", "temp_f": 64, "wind_mph": 5,
                   "wind_dir": "in from cf", "carry": -1, "roof_closed": 0,
                   "condition": "Clear", "date": "2026-09-23",
                   "venue_id": 3},
                  {"game_id": "mlb-2", "temp_f": None, "wind_mph": 0,
                   "wind_dir": None, "carry": 0, "roof_closed": 0,
                   "condition": None, "date": "2026-09-23", "venue_id": 3}]
        # the feed has now forgotten game 1 entirely
        import time as _t
        fn, _ = _stub_feed([_game(1, None), _game(2, None)])
        got = {r["game_id"]: r for r in
               _with_cache(tmp, "2026-09-23", cached,
                           mtime=_t.time() - 2 * weather.EMPTY_TTL_SECONDS,
                           fn=fn)}
        assert got["mlb-1"]["temp_f"] == 64, "dropped a reading we held"
        assert got["mlb-1"]["carry"] == -1, got["mlb-1"]


def check_an_old_incomplete_date_stops_being_refetched():
    """Some games never get a reading, so completeness needs a backstop.
    Without one an incomplete date would be re-pulled on every call
    forever — politeness, and the reason `STALE_AFTER_DAYS` exists."""
    import pathlib
    import tempfile
    assert weather._days_since("2020-05-01") > weather.STALE_AFTER_DAYS
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        cached = [{"game_id": "mlb-1", "temp_f": None, "wind_mph": 0,
                   "wind_dir": None, "carry": 0, "roof_closed": 0,
                   "condition": None, "date": "2020-05-01", "venue_id": 3}]
        fn, calls = _stub_feed([_game(1, 70)])
        _with_cache(tmp, "2020-05-01", cached, mtime=0, fn=fn)
        assert not calls, "an old incomplete date must stop being re-pulled"


def check_the_direction_table_is_gated_on_its_own_agreement():
    """An orientation we did not measure cleanly must read as NO wind
    information, never as a guessed direction.

    Each park's bearing is pinned eight independent ways (in-from-cf gives
    it directly, out-to-lf gives it minus 135, ...) and `R` is how well
    those agree. Coors comes out at R 0.39 with a bearing that disagrees
    with the real park, so it is gated off and gets temperature only.
    """
    assert weather.field_relative(19, 45) == (None, 0), "Coors must be gated"
    assert weather.field_relative(999999, 45) == (None, 0), "unknown park"
    # ... while a park that did measure cleanly is believed
    assert weather.field_relative(3, 45)[1] == -1, "Fenway, wind off the CF"


def check_wind_from_centre_blows_in_and_the_opposite_blows_out():
    """`compass_from` is met convention: wind FROM centre field is blowing
    IN. Getting this backwards would invert `WIND_HR_MULT` at every park
    at once, which is the kind of sign error no aggregate row would show.
    """
    cf = weather.PARK_CF[3][0]          # Fenway, 36 deg
    assert weather.field_relative(3, cf) == ("in from cf", -1)
    assert weather.field_relative(3, (cf + 180) % 360) == ("out to cf", 1)
    # and a wind across the park pushes nothing toward a fence
    assert weather.field_relative(3, (cf + 90) % 360)[1] == 0
    assert weather.field_relative(3, (cf - 90) % 360)[1] == 0


def check_a_forecast_is_rescaled_onto_the_statsapi_footing():
    """`WIND_HR_MULT` was counted on statsapi speeds, which read about 6%
    higher than Open-Meteo on the same 2,138 nights. Serving the raw
    forecast into a table indexed by the other feed would under-apply the
    wind at every park."""
    assert 1.0 < weather.WIND_SCALE < 1.15, weather.WIND_SCALE


def check_the_backfill_never_takes_the_forecast():
    """THE ASYMMETRY IS THE WHOLE DESIGN. Every shipped TEMP_* and
    WIND_HR table was counted on statsapi observations. A forecast
    belongs in tonight's price and must never reach `mlb_weather`, or the
    tables quietly retrain on a feed nobody chose.
    """
    import inspect
    src = inspect.getsource(weather.backfill)
    assert "fetch_live" not in src, "backfill must not use the live fallback"
    assert "fetch_date" in src
    live = inspect.getsource(weather.fetch_live)
    assert "open_meteo" in live


def check_a_forecast_never_replaces_a_game_that_has_started():
    """Once the first pitch is thrown the conditions are being OBSERVED.

    Substituting a prediction for a game in progress or already final
    invents a reading for a night that has a real one, and afterwards it
    is indistinguishable from an observation. Unknown state counts as
    started, the same way `gamestate.is_pregame` resolves it — the cost
    of skipping a fill is a neutral multiplier, the cost of inventing one
    is a number nothing downstream can detect.
    """
    for detailed, state in (("Scheduled", "Preview"), ("Pre-Game", "Preview"),
                            ("Warmup", "Preview")):
        assert weather.is_pregame_row({"detailed": detailed, "state": state})
    for detailed, state in (("In Progress", "Live"), ("Final", "Final"),
                            ("Game Over", "Live"), ("Suspended", "Live")):
        assert not weather.is_pregame_row(
            {"detailed": detailed, "state": state}), (detailed, state)
    assert not weather.is_pregame_row({}), "unknown state must not be filled"


def check_the_pregame_test_uses_one_definition():
    """Two spellings of 'has not started' is how one of them drifts."""
    import inspect
    from src.context import gamestate
    src = inspect.getsource(weather.is_pregame_row)
    assert "gamestate.PREGAME_STATES" in src, \
        "weather is keeping its own copy of the pregame state list"
    assert "Scheduled" in gamestate.PREGAME_STATES


def check_the_live_fetch_is_memoised_per_date():
    """`simulate_slate_game` calls this ONCE PER GAME, so a 16-game slate
    would otherwise make 16 x 16 forecast calls against a free feed."""
    import time as _t
    saved = dict(weather._LIVE)
    try:
        weather._LIVE.clear()
        sentinel = [{"game_id": "mlb-1", "temp_f": 70}]
        weather._LIVE["2026-09-23"] = (_t.time(), sentinel)
        # a memoised date must not reach fetch_date at all
        assert weather.fetch_live("2026-09-23") is sentinel
        # ... and an expired entry must not be served
        weather._LIVE["2026-09-23"] = (
            _t.time() - 2 * weather.LIVE_TTL_SECONDS, sentinel)
        assert weather._LIVE["2026-09-23"][1] is sentinel
        age = _t.time() - weather._LIVE["2026-09-23"][0]
        assert age > weather.LIVE_TTL_SECONDS
    finally:
        weather._LIVE.clear()
        weather._LIVE.update(saved)


def check_fetch_live_actually_applies_the_pregame_gate():
    """The gate has to be WIRED, not merely defined.

    `is_pregame_row` passing its own unit test says nothing about whether
    `fetch_live` consults it — deleting the two lines that call it left
    every other check in this file green.
    """
    import pathlib
    import tempfile
    rows = [
        {"game_id": "mlb-pre", "temp_f": None, "roof_closed": 0,
         "venue_id": 3, "start_utc": "2026-09-23T23:10:00Z",
         "detailed": "Scheduled", "state": "Preview"},
        {"game_id": "mlb-live", "temp_f": None, "roof_closed": 0,
         "venue_id": 3, "start_utc": "2026-09-23T17:10:00Z",
         "detailed": "In Progress", "state": "Live"},
        {"game_id": "mlb-final", "temp_f": None, "roof_closed": 0,
         "venue_id": 3, "start_utc": "2026-09-23T13:10:00Z",
         "detailed": "Final", "state": "Final"},
    ]
    asked = []

    def fake_open_meteo(venue_id, start_utc):
        asked.append(start_utc)
        return {"temp_f": 55, "wind_mph": 8, "wind_dir": "in from cf",
                "carry": -1, "condition": None, "source": "open-meteo"}

    saved_live = dict(weather._LIVE)
    real_fetch, real_om = weather.fetch_date, weather.open_meteo
    try:
        weather._LIVE.clear()
        weather.fetch_date = lambda d, force=False: [dict(r) for r in rows]
        weather.open_meteo = fake_open_meteo
        got = {r["game_id"]: r for r in weather.fetch_live("2026-09-23")}
    finally:
        weather.fetch_date, weather.open_meteo = real_fetch, real_om
        weather._LIVE.clear()
        weather._LIVE.update(saved_live)

    assert got["mlb-pre"]["temp_f"] == 55, "a pregame hole was not filled"
    assert got["mlb-live"]["temp_f"] is None, \
        "a game IN PROGRESS was given a forecast"
    assert got["mlb-final"]["temp_f"] is None, \
        "a game ALREADY PLAYED was given a forecast"
    assert asked == ["2026-09-23T23:10:00Z"], asked


def check_a_cache_written_before_the_state_field_is_repulled():
    """A cache file from an older shape must not silently disable the gate.

    `is_pregame_row` resolves unknown to FALSE, which is right for a game
    whose state we could not read — and wrong for a whole date whose cache
    simply predates the field. Left alone it turned the fallback off for
    every game at once and looked exactly like 'no forecast needed'.
    """
    import pathlib
    import tempfile
    import time as _t
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        old_shape = [{"game_id": "mlb-1", "temp_f": None, "wind_mph": 0,
                      "wind_dir": None, "carry": 0, "roof_closed": 0,
                      "condition": None, "date": "2026-09-23",
                      "venue_id": 3}]          # no "state" key
        fn, calls = _stub_feed([_game(1, 61)])
        got = _with_cache(tmp, "2026-09-23", old_shape, mtime=_t.time(), fn=fn)
        assert calls, "an old-shape cache must be re-pulled"
        assert "state" in got[0], got[0]
