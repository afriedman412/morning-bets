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
