"""Days off, travel distance, and time-zone drag for both clubs.

Almost free: the local `games` table already holds every game either club
has played, so days-of-rest and the previous venue are a query. Only the
venue coordinates need fetching, and there are thirty of them.

What this is for. A club playing its nineteenth day in a row, or arriving
at 4am after three time zones east, is a worse version of itself in ways no
season-long rate reflects. The classic shape is a getaway day after a night
game — regulars rest, the lineup thins, and a total written off full-strength
offences is priced for a game that is not being played.

Directionality matters and is reported. Travelling EAST costs more than
travelling west: the body arrives on a clock that says it is later than it
is, and a 10pm first pitch on the east coast is 7pm to a body still on
Pacific time. So `tz_shift` is signed, positive eastbound.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

from src import db
from src.context import atomic

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = PROJECT_ROOT / ".cache"
BASE = "https://statsapi.mlb.com/api/v1"
UA = "morning-bets/1.0"
TIMEOUT = 25

#: Beyond this many consecutive days without an off day, fatigue is worth
#: mentioning. MLB schedules usually break every 10-14 days.
LONG_STRETCH = 13
#: A flight worth noting. Roughly coast-adjacent; below this is a bus ride.
FAR_MILES = 1200


def _venues(season: int | None = None) -> dict[int, dict]:
    """{venue_id: {name, lat, lon, tz}}. One request, cached per season."""
    season = season or date.today().year
    CACHE_DIR.mkdir(exist_ok=True)
    p = CACHE_DIR / f"statsapi_venues_{season}.json"
    if p.exists():
        try:
            d = json.loads(p.read_text())
        except json.JSONDecodeError:
            d = {}
    else:
        d = {}
    if not d:
        try:
            req = urllib.request.Request(
                f"{BASE}/venues?season={season}&hydrate=location,timezone",
                headers={"User-Agent": UA},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                d = json.loads(r.read())
            atomic.write_text(p, json.dumps(d))
        except (urllib.error.URLError, TimeoutError):
            return {}
    out: dict[int, dict] = {}
    for v in d.get("venues", []):
        loc = v.get("location") or {}
        coords = loc.get("defaultCoordinates") or {}
        tz = v.get("timeZone") or {}
        out[v["id"]] = {
            "name": v.get("name"),
            "lat": coords.get("latitude"),
            "lon": coords.get("longitude"),
            "tz": tz.get("id"),
            "utc_offset": tz.get("offset"),
        }
    return out


def _miles(a: dict, b: dict) -> float | None:
    """Great-circle distance. None if either venue lacks coordinates."""
    if not all(x and x.get("lat") is not None and x.get("lon") is not None
               for x in (a, b)):
        return None
    r = 3958.8
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp = p2 - p1
    dl = math.radians(b["lon"] - a["lon"])
    h = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return round(2 * r * math.asin(math.sqrt(h)), 0)


def _prior_games(team_abbr: str, before: str, limit: int = 20) -> list[dict]:
    """This club's most recent games before `before`, newest first."""
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT game_id, date, away_team_abbr, home_team_abbr, status "
            "FROM games WHERE sport='mlb' AND date < ? "
            "AND (away_team_abbr = ? OR home_team_abbr = ?) "
            "ORDER BY date DESC LIMIT ?",
            (before, team_abbr, team_abbr, limit),
        )]


def for_team(
    team_abbr: str, game_date: str, venue_id: int | None = None,
    season: int | None = None,
) -> dict | None:
    """Rest and travel for one club going into one game.

    Returns None when the local games table has no history for the club —
    early in a season, or for a date before the cache starts. A guess about
    rest is worse than none: 'well rested' about a team on its fifteenth
    straight day is exactly backwards.
    """
    prior = _prior_games(team_abbr, game_date)
    if not prior:
        return None
    season = season or datetime.strptime(game_date, "%Y-%m-%d").year
    last = prior[0]
    d0 = date.fromisoformat(last["date"])
    d1 = date.fromisoformat(game_date)
    days_rest = (d1 - d0).days - 1     # 0 = played yesterday

    # Consecutive days with a game, walking backwards until a gap.
    streak, cursor = 0, d1
    seen = {g["date"] for g in prior}
    while (cursor - date.fromisoformat("1900-01-01")).days:
        prev = cursor.replace()
        prev = date.fromordinal(cursor.toordinal() - 1)
        if prev.isoformat() in seen:
            streak += 1
            cursor = prev
        else:
            break

    venues = _venues(season)
    here = venues.get(venue_id) if venue_id else None
    # Where they played last is whichever club was home in that game.
    prev_home = last["home_team_abbr"]

    miles = tz_shift = None
    if here and prev_home:
        prev_v = _venue_of_club(prev_home, venues)
        if prev_v:
            miles = _miles(prev_v, here)
            if prev_v.get("utc_offset") is not None \
                    and here.get("utc_offset") is not None:
                # Eastbound is positive: offsets get less negative going east.
                tz_shift = here["utc_offset"] - prev_v["utc_offset"]

    return {
        "team": team_abbr,
        "days_rest": max(0, days_rest),
        "played_yesterday": days_rest == 0,
        "consecutive_days": streak,
        "long_stretch": streak >= LONG_STRETCH,
        "last_game": last["date"],
        "travel_miles": miles,
        "long_trip": bool(miles and miles >= FAR_MILES),
        "tz_shift": tz_shift,
        "eastbound": bool(tz_shift and tz_shift > 0),
    }


_CLUB_VENUE: dict[str, int] = {}


def _venue_of_club(abbr: str, venues: dict[int, dict]) -> dict | None:
    """Home park for a club abbreviation, resolved once via the teams API."""
    global _CLUB_VENUE
    if not _CLUB_VENUE:
        try:
            req = urllib.request.Request(
                f"{BASE}/teams?sportId=1", headers={"User-Agent": UA},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                d = json.loads(r.read())
            _CLUB_VENUE = {
                t["abbreviation"]: (t.get("venue") or {}).get("id")
                for t in d.get("teams", []) if t.get("abbreviation")
            }
        except (urllib.error.URLError, TimeoutError):
            return None
    vid = _CLUB_VENUE.get(abbr)
    return venues.get(vid) if vid else None


if __name__ == "__main__":
    import sys
    from src.context import slate as slate_src
    d = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    slate = slate_src.slate(d)
    print(f"{d}: rest and travel\n")
    print(f"  {'team':<6}{'rest':>5}{'streak':>8}{'miles':>8}{'tz':>5}  flags")
    seen = set()
    for g in slate:
        for side in ("away", "home"):
            nm = g[f"{side}_team"]
            abbr = None
            from src.context.sources import opponent
            ids = opponent.team_ids()
            for a, i in ids.items():
                if i == g[f"{side}_team_id"]:
                    abbr = a
                    break
            if not abbr or abbr in seen:
                continue
            seen.add(abbr)
            r = for_team(abbr, d, g.get("venue_id"))
            if not r:
                print(f"  {abbr:<6}  (no history)")
                continue
            flags = " ".join(f for f, on in (
                ("PLAYED-YDAY", r["played_yesterday"]),
                ("LONG-STRETCH", r["long_stretch"]),
                ("LONG-TRIP", r["long_trip"]),
                ("EASTBOUND", r["eastbound"]),
            ) if on)
            mi = "-" if r["travel_miles"] is None else f"{r['travel_miles']:.0f}"
            tz = "-" if r["tz_shift"] is None else f"{r['tz_shift']:+d}"
            print(f"  {abbr:<6}{r['days_rest']:>5}{r['consecutive_days']:>8}"
                  f"{mi:>8}{tz:>5}  {flags}")
