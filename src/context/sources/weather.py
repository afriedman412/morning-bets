"""Game-time weather, backfilled from the schedule endpoint.

WHY THIS IS CHEAP. `hydrate=weather` returns temperature, condition and wind
for an ENTIRE DATE in one request, so a season costs ~150 calls rather than
one per game. Nothing about a final game's weather can change, so it caches
unconditionally, the same rule `pbp.fetch` follows.

WIND NEEDS NO COMPASS WORK, which is the pleasant surprise. statsapi reports
it FIELD-RELATIVE — "12 mph, Out To RF", "5 mph, In From CF", "9 mph, L To
R" — so the stadium-orientation table that a compass bearing would have
required is already applied upstream. Home plate faces a different direction
in all thirty parks and MLB has resolved that for us.

WHAT `carry` IS. Wind speed alone is close to useless: 15 mph in and 15 mph
out are opposite effects carrying the same number, and averaging them
produces zero. `carry` is the signed component — +1 blowing out, -1 blowing
in, 0 for a crosswind or calm — so `wind_mph * carry` is the scalar with the
physics in it.

DOMES IDENTIFY THEMSELVES, AND A CLOSED ROOF IS NOT ALWAYS A DOME. A sealed
park reports "Roof Closed" with "0 mph, None", so `carry` falls out at zero
without any special handling. But six closed-roof games report a REAL wind
direction, and they are all at American Family Field or T-Mobile Park —
retractable roofs. T-Mobile's is a cover rather than a seal: the sides stay
open and wind blows through. So the feed is not contradicting itself, and an
earlier version of this module that zeroed `carry` under a closed roof was
overriding good data with an assumption. TRUST THE READING; `roof_closed`
travels alongside as its own flag, for rain and sun rather than for wind.

TWO SOURCES, AND ONLY ONE OF THEM GOES IN THE TABLE. statsapi is an
OBSERVATIONS feed: it does not publish a night game's weather until near
first pitch, so a board priced at 10am sees nothing for the games that
matter most. Open-Meteo publishes a 72-hour HOURLY forecast that refreshes
hourly, so `fetch_live` falls back to it per game when statsapi has no
reading. `backfill` does NOT, and that asymmetry is deliberate: every
shipped `TEMP_*` and `WIND_HR` table was counted on statsapi observations,
and letting a forecast into `mlb_weather` would quietly retrain them on a
different source.

MEASURED BEFORE TRUSTING IT (2026-09-23, open-air games only, n=2,151):
temperature agrees at corr 0.942 with a +0.56F bias, which is nothing
against the bin widths, so the temperature tables take Open-Meteo as-is.
Wind speed agrees less well -- corr 0.563, statsapi reading 6% high -- so
the fallback rescales by `WIND_SCALE` and the direction goes through the
derived `PARK_CF` table rather than being trusted raw.

    venv/bin/python -m src.context.sources.weather [--backfill]
"""
from __future__ import annotations

import datetime
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from src.context import store
from src.context import atomic

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE = PROJECT_ROOT / ".cache" / "weather"
BASE = "https://statsapi.mlb.com/api/v1"
UA = "morning-bets/1.0"
TIMEOUT = 25

#: Field-relative wind, mapped to a signed carry component.
_CARRY = {"out to": 1, "in from": -1}


def parse_wind(s: str | None) -> tuple[int, str | None, int]:
    """'12 mph, Out To RF' -> (12, 'out to rf', +1).

    Returns carry 0 for a crosswind ("L To R"), for calm, and for a closed
    roof — all cases where the wind does not push a batted ball toward or
    away from the fence.
    """
    if not s:
        return 0, None, 0
    m = re.match(r"\s*(\d+)\s*mph\s*,\s*(.*)$", s, re.I)
    if not m:
        return 0, None, 0
    mph = int(m.group(1))
    d = (m.group(2) or "").strip().lower()
    if not d or d in ("none", "calm"):
        # normalise both spellings of "no wind" to a single missing value
        return mph, None, 0
    carry = 0
    for prefix, sign in _CARRY.items():
        if d.startswith(prefix):
            carry = sign
            break
    return mph, d, carry


#: How long an INCOMPLETE cache file is trusted. See `fetch_date`.
EMPTY_TTL_SECONDS = 1800
#: After this many days, a date's holes are accepted as permanent and it
#: stops being re-fetched. Some games never get a reading at all, and
#: without a backstop an incomplete date would be re-pulled forever.
STALE_AFTER_DAYS = 4

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
#: statsapi reads 6% higher than Open-Meteo on the same night (n=2,138,
#: corr 0.563). `WIND_HR_MULT` was counted on statsapi, so a forecast
#: speed is scaled onto that footing before it reaches the table.
WIND_SCALE = 1.06

#: EVERY PARK'S COMPASS BEARING FROM THE PLATE TO CENTRE FIELD, DERIVED.
#: statsapi reports wind field-relative ("In From CF") and Open-Meteo in
#: compass degrees, so a fallback reading cannot be turned into a `carry`
#: without knowing which way the park points. Rather than typing a table
#: in, this was MEASURED off ~7,000 nights where we hold both readings:
#: each statsapi label pins the bearing (in-from-cf gives it directly,
#: out-to-lf gives it minus 135, and so on), and the eight routes have to
#: agree. `R` is that agreement, 1.0 being perfect.
#:
#: WIND IS GATED ON THE AGREEMENT, TEMPERATURE IS NOT. Temperature needs
#: no orientation, so it is filled everywhere. Six parks whose labels do
#: not agree well enough get temperature only and `carry` 0 -- notably
#: Coors (R 0.39, and the bearing disagrees with the real park) and the
#: retractables, where roof state pollutes the reading.
#:                 CF bearing   R     worst label disagreement
PARK_CF = {
    2395: (72.9, 0.928, 39.7),    # Oracle Park
    2680: (352.3, 0.879, 30.8),   # Petco Park
    10: (33.6, 0.878, 0.3),       # Oakland Coliseum
    3289: (35.9, 0.841, 10.8),    # Citi Field
    17: (37.0, 0.798, 16.9),      # Wrigley Field
    2602: (138.4, 0.785, 26.8),   # Great American Ball Park
    2681: (16.5, 0.769, 8.4),     # Citizens Bank Park
    22: (356.1, 0.765, 109.9),    # Dodger Stadium      -- wind gated off
    3309: (20.2, 0.743, 31.2),    # Nationals Park
    4: (130.3, 0.735, 21.9),      # Rate Field
    2529: (47.0, 0.734, 64.3),    # Sutter Health Park  -- wind gated off
    2394: (138.9, 0.732, 14.2),   # Comerica Park
    680: (62.5, 0.714, 56.1),     # T-Mobile Park
    31: (109.4, 0.701, 22.6),     # PNC Park
    2: (38.0, 0.690, 27.6),       # Oriole Park
    5: (358.3, 0.677, 36.1),      # Progressive Field
    2889: (68.1, 0.676, 40.2),    # Busch Stadium
    3312: (86.4, 0.664, 16.4),    # Target Field
    1: (59.9, 0.652, 68.2),       # Angel Stadium       -- wind gated off
    3: (36.0, 0.612, 56.2),       # Fenway Park
    32: (142.1, 0.606, 21.4),     # American Family Field
    7: (62.9, 0.595, 32.9),       # Kauffman Stadium
    4705: (183.8, 0.594, 68.3),   # Truist Park         -- wind gated off
    3313: (82.1, 0.571, 30.8),    # Yankee Stadium
    2523: (48.6, 0.555, 9.3),     # Steinbrenner Field
    14: (8.2, 0.549, 21.7),       # Rogers Centre       -- wind gated off
    19: (337.7, 0.388, 49.2),     # Coors Field         -- wind gated off
}
#: A park must clear both to have its wind direction believed.
MIN_R = 0.55
MAX_LABEL_DEV = 60.0


def _days_since(date_str: str) -> float:
    """Days from `date_str` to now, for the stale-cache backstop."""
    try:
        d = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return 0.0
    return (datetime.datetime.utcnow() - d).total_seconds() / 86400.0


def fetch_date(date_str: str, force: bool = False) -> list[dict]:
    """Every game's weather for one date.

    CACHED, BUT A TEMPERATURE-LESS SLATE IS NOT A FINAL ANSWER. The old
    docstring said "a final game cannot change" and cached on that basis,
    which was true of the GAME and false of the FILE: the live path asks
    for a date PREGAME, statsapi does not populate `weather.temp` until
    near first pitch, and the empty answer was then frozen forever. It
    cost 2026-09-07, -08 and -09 their weather entirely — 41 games — and
    nothing complained, because `TEMP_HR_MULT` and `WIND_HR_MULT` are
    silent-neutral by design and a missing reading contributes exactly
    1.0. Two shipped mechanisms sat inert for four days and the only
    reason it surfaced is that a new board printed the air column.

    THE FIRST FIX WAS HALF A FIX, and the half it missed is the common
    case. It froze a date once ANY game on it carried a temperature —
    but statsapi fills a slate in start-time order, so the 1:05 game has
    a reading hours before the 7:10 game does. One day game was enough to
    lock the file, and the night games could never heal. Between 2026-09-19
    and -23 that cost four more slates: 4/15, 6/15, 1/15, 1/16 — and it
    went unseen for the same reason as last time, that a missing reading
    multiplies by exactly 1.0.

    So the test is COMPLETENESS, not existence: a cache is final when every
    game has a temperature, or when the date is `STALE_AFTER_DAYS` old and
    the remaining holes are accepted as permanent. Anything else is a
    pregame read and is re-fetched once it is `EMPTY_TTL_SECONDS` old. The
    refetch MERGES — a reading already held is never dropped for a later
    empty one, because statsapi clears the field again after a game ends.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{date_str}.json"
    cached = None
    if p.exists() and not force:
        try:
            cached = json.loads(p.read_text())
        except ValueError:
            cached = None
        if cached:
            if all(r.get("temp_f") is not None for r in cached):
                return cached
            if _days_since(date_str) > STALE_AFTER_DAYS:
                # past the backstop the holes are permanent, and the shape
                # check below would only re-pull a finished slate that the
                # pregame gate is going to refuse anyway
                return cached
            if "state" not in cached[0]:
                # A CACHE FROM BEFORE THE FIELD EXISTED IS NOT USABLE.
                # `is_pregame_row` reads `state`, and absent it every game
                # looks started, which switches the fallback off for the
                # whole date rather than failing. Re-pull instead.
                pass
            elif time.time() - p.stat().st_mtime < EMPTY_TTL_SECONDS:
                return cached
    url = (f"{BASE}/schedule?sportId=1&date={date_str}"
           f"&hydrate=venue,weather")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError):
        return []
    out = []
    for day in d.get("dates") or []:
        for g in day.get("games") or []:
            w = g.get("weather") or {}
            mph, wdir, carry = parse_wind(w.get("wind"))
            cond = w.get("condition")
            roof = bool(cond and "roof closed" in cond.lower())
            try:
                temp = int(w.get("temp"))
            except (TypeError, ValueError):
                temp = None
            out.append({
                "game_id": f"mlb-{g.get('gamePk')}",
                "date": date_str,
                "venue_id": (g.get("venue") or {}).get("id"),
                "temp_f": temp,
                "condition": cond,
                "wind_mph": mph,
                "wind_dir": wdir,
                "carry": carry,
                "roof_closed": int(roof),
                # carried for the Open-Meteo fallback, which needs the
                # hour to index an hourly forecast and the state to refuse
                # a game that has already begun. Not `mlb_weather` columns.
                "start_utc": g.get("gameDate"),
                "state": (g.get("status") or {}).get("abstractGameState"),
                "detailed": (g.get("status") or {}).get("detailedState"),
            })
    # NEVER TRADE A READING FOR A HOLE. statsapi clears `weather` again
    # once a game is over, so a late refetch of a finished slate can come
    # back emptier than what is already cached.
    if cached:
        prev = {r["game_id"]: r for r in cached}
        for r in out:
            old = prev.get(r["game_id"])
            if r["temp_f"] is None and old and old.get("temp_f") is not None:
                r.update({k: old.get(k) for k in
                          ("temp_f", "condition", "wind_mph", "wind_dir",
                           "carry", "roof_closed")})
    atomic.write_text(p, json.dumps(out))
    return out


VENUE_CACHE = PROJECT_ROOT / ".cache" / "venue_coords.json"


def _coords(venue_id: int) -> tuple[float, float] | None:
    """(lat, lon) for a venue, cached on disk after one statsapi call."""
    try:
        book = json.loads(VENUE_CACHE.read_text())
    except (OSError, ValueError):
        book = {}
    key = str(venue_id)
    if key in book:
        v = book[key]
        return (v[0], v[1]) if v else None
    url = f"{BASE}/venues/{venue_id}?hydrate=location"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read())
        c = d["venues"][0]["location"]["defaultCoordinates"]
        book[key] = [c["latitude"], c["longitude"]]
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError):
        return None
    VENUE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_text(VENUE_CACHE, json.dumps(book))
    return (book[key][0], book[key][1])


def field_relative(venue_id: int, compass_from: float) -> tuple[str | None, int]:
    """Compass degrees the wind blows FROM -> ('in from cf', -1).

    `compass_from` is met convention, so a wind FROM the centre-field
    bearing is blowing IN. The sign that matters to `WIND_HR_MULT` is the
    cosine of the angle between the wind and the plate-to-centre line;
    everything within 45 degrees of a foul line is called a crosswind and
    gets `carry` 0, which is what statsapi's own "L To R" resolves to.

    Returns (None, 0) for a park whose orientation did not measure
    cleanly — see `PARK_CF`. Unknown orientation must read as "no wind
    information", never as a guessed direction.
    """
    park = PARK_CF.get(venue_id)
    if not park:
        return None, 0
    cf, r, dev = park
    if r < MIN_R or dev > MAX_LABEL_DEV:
        return None, 0
    off = (compass_from - cf + 180) % 360 - 180      # -180..180 from CF
    if abs(off) <= 45:
        return "in from cf", -1
    if abs(off) >= 135:
        return "out to cf", 1
    return ("l to r" if off > 0 else "r to l"), 0


def open_meteo(venue_id: int, start_utc: str) -> dict | None:
    """One game's forecast: temperature, wind speed and carry.

    THE HOUR IS THE POINT. Open-Meteo publishes 72 hours ahead and
    refreshes hourly, so a 10am board gets tonight's 7:10 first pitch and
    the 5pm re-price gets a better one. statsapi cannot do this at all --
    it reports what happened, not what will.
    """
    co = _coords(venue_id)
    if not co or not start_utc:
        return None
    hour = start_utc[:13] + ":00"
    day = start_utc[:10]
    url = (f"{OPEN_METEO}?latitude={co[0]}&longitude={co[1]}"
           "&hourly=temperature_2m,wind_speed_10m,wind_direction_10m"
           "&temperature_unit=fahrenheit&wind_speed_unit=mph"
           f"&timezone=UTC&start_date={day}&end_date={day}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read())
        h = d["hourly"]
        i = h["time"].index(hour)
        temp = h["temperature_2m"][i]
        mph = h["wind_speed_10m"][i]
        deg = h["wind_direction_10m"][i]
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError):
        return None
    if temp is None:
        return None
    wdir, carry = (field_relative(venue_id, deg)
                   if deg is not None and mph else (None, 0))
    return {
        "temp_f": int(round(temp)),
        "wind_mph": int(round((mph or 0) * WIND_SCALE)),
        "wind_dir": wdir,
        "carry": carry,
        "condition": None,
        "source": "open-meteo",
    }


def is_pregame_row(row: dict) -> bool:
    """Has this game definitely not started?

    Keyed on `gamestate.PREGAME_STATES` rather than a second list of its
    own — two spellings of "has not started" is how one of them drifts.
    Unknown resolves to FALSE, the same way `gamestate.is_pregame` does.
    """
    from src.context import gamestate
    d, st = row.get("detailed"), row.get("state")
    if d is None and st is None:
        return False
    return d in gamestate.PREGAME_STATES or st == "Preview"


#: `fetch_live` is called once PER GAME by `simulate_slate_game`, so
#: without this a 16-game slate would make 16 x 16 forecast calls.
_LIVE: dict[str, tuple[float, list[dict]]] = {}
LIVE_TTL_SECONDS = 600


def fetch_live(date_str: str) -> list[dict]:
    """Weather for pricing: statsapi first, Open-Meteo for the holes.

    THIS IS THE BOARD'S ENTRY POINT AND `backfill` MUST NOT USE IT. The
    shipped temperature and wind tables were counted on statsapi
    observations; a forecast reaching `mlb_weather` would retrain them on
    a different feed without anyone deciding to. So the fallback lives
    here, in memory, and is never written to the date cache or the table.

    A FORECAST ONLY EVER REPLACES A GAME THAT HAS NOT STARTED. Once the
    first pitch is thrown the real conditions are being observed, and
    statsapi will publish them; substituting a prediction for a game that
    is in progress or already final would be inventing a reading for a
    night that has a real one, and it would be indistinguishable from an
    observation afterwards. Unknown state counts as started.

    A closed roof is left alone — the reading that matters indoors is the
    indoor one, and Open-Meteo only knows the sky.
    """
    hit = _LIVE.get(date_str)
    if hit and time.time() - hit[0] < LIVE_TTL_SECONDS:
        return hit[1]
    rows = fetch_date(date_str)
    for r in rows:
        if r.get("temp_f") is not None or r.get("roof_closed"):
            continue
        if not is_pregame_row(r):
            continue
        alt = open_meteo(r.get("venue_id"), r.get("start_utc"))
        if alt:
            r.update(alt)
    _LIVE[date_str] = (time.time(), rows)
    return rows


def backfill(verbose: bool = True) -> int:
    """Pull every date the games table knows about that we do not have."""
    store.init()
    with store.connect() as c:
        dates = [r["date"] for r in c.execute(
            f"select distinct date from {store.BETS}.games "
            "where sport='mlb' and status='Final' order by date")]
        # A DATE WITH ROWS BUT NO TEMPERATURE IS NOT "HAVE". Plain
        # `distinct date` is the second half of the bug above: once the
        # empty pregame rows were written, the backfill skipped those
        # dates forever and they could never heal.
        # COMPLETE, not merely non-empty. `sum(...) > 0` was the same
        # half-fix as the cache guard: one day game with a reading made
        # the whole date "have" and its night games never healed.
        have = {r["date"] for r in c.execute(
            "select date from mlb_weather group by date "
            "having sum(temp_f is null) = 0")}
        known = {r["game_id"] for r in c.execute(
            f"select game_id from {store.BETS}.games where sport='mlb'")}
    todo = [d for d in dates if d not in have]
    n = 0
    with store.connect(attach=False) as c:
        for i, d in enumerate(todo):
            for row in fetch_date(d):
                if row["game_id"] not in known:
                    continue
                c.execute(
                    "insert or replace into mlb_weather values "
                    "(?,?,?,?,?,?,?,?,?)",
                    (row["game_id"], row["date"], row["venue_id"],
                     row["temp_f"], row["condition"], row["wind_mph"],
                     row["wind_dir"], row["carry"], row["roof_closed"]))
                n += 1
            if verbose and (i + 1) % 25 == 0:
                print(f"  {i + 1}/{len(todo)} dates", flush=True)
    if verbose:
        print(f"backfilled {n} games over {len(todo)} dates")
    return n


def by_game() -> dict:
    """{game_id: weather row} for every game we have."""
    with store.connect(attach=False) as c:
        return {r["game_id"]: dict(r)
                for r in c.execute("select * from mlb_weather")}


def main() -> None:
    if "--backfill" in sys.argv:
        backfill()
    with store.connect() as c:
        tot = c.execute(f"select count(*) n from {store.BETS}.games "
                        "where sport='mlb' and status='Final'").fetchone()["n"]
        rows = c.execute("select count(*) n from mlb_weather").fetchone()["n"]
        dome = c.execute("select count(*) n from mlb_weather "
                         "where roof_closed=1").fetchone()["n"]
        t = c.execute("select avg(temp_f) t from mlb_weather "
                      "where roof_closed=0").fetchone()["t"]
        print(f"  {rows} of {tot} final games ({rows / tot if tot else 0:.1%})")
        print(f"  {dome} closed-roof, mean outdoor temp "
              f"{t:.1f}F" if t else "")
        print(f"  {'dir':<14}{'games':>7}{'mean mph':>10}")
        for r in c.execute(
                "select carry, count(*) n, avg(wind_mph) m from mlb_weather "
                "where roof_closed=0 group by carry order by carry"):
            lbl = {1: "out (+1)", -1: "in (-1)", 0: "cross/calm"}.get(
                r["carry"], "?")
            print(f"  {lbl:<14}{r['n']:>7}{r['m']:>10.1f}")


if __name__ == "__main__":
    main()
