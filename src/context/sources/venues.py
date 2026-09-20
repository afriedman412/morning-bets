"""Which ballpark each game was actually played in.

WHY NOT JUST USE THE HOME TEAM. Because MLB does not always play at home.
Mexico City, London, the Field of Dreams game, the Little League Classic,
spring-training sites during hurricanes — and Mexico City is one of the most
extreme run environments anywhere. `park.for_venue` already refuses to fall
back to the home club when a supplied `venue_id` misses, precisely so a
neutral site returns None rather than a confidently wrong number. That
guarantee is worth nothing if the caller never has an id to supply, which
is the situation the `games` table left us in.

One request per DATE rather than per game — the schedule endpoint returns
every game that day with its venue attached, so a full season is ~180 calls
instead of ~2,400. Immutable once played.
"""
from __future__ import annotations

import json
import urllib.request

from src import db, parallel

BASE = "https://statsapi.mlb.com/api/v1"
TIMEOUT = 25


def _schedule(date_str: str) -> list[tuple]:
    """[(game_id, venue_id, venue_name, day_night, start_utc)] for a date.

    `dayNight` is MLB's own classification, not a guess from the clock —
    which matters because a 5pm first pitch is a day game in one park and
    a night game in another, and the league is the authority on which.
    """
    url = f"{BASE}/schedule?sportId=1&date={date_str}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            d = json.loads(r.read())
    except Exception:
        return []
    out = []
    for day in d.get("dates") or []:
        for g in day.get("games") or []:
            v = g.get("venue") or {}
            pk, vid = g.get("gamePk"), v.get("id")
            if pk and vid:
                out.append((f"mlb-{pk}", int(vid), v.get("name"),
                            g.get("dayNight"), g.get("gameDate")))
    return out


def backfill(workers: int = 6, verbose: bool = True) -> dict:
    """Set `games.venue_id` for every cached MLB game. Idempotent."""
    with db.connect() as conn:
        dates = [r["date"] for r in conn.execute("""
            select distinct date from games
            where sport = 'mlb'
              and (venue_id is null or day_night is null)
            order by date""")]
    if verbose:
        print(f"{len(dates)} date(s) to look up")
    if not dates:
        return {"dates": 0, "games": 0}

    done = rows = 0
    with db.connect() as conn:
        for _, got, err in parallel.gather(_schedule, dates, workers=workers):
            if err or not got:
                continue
            for gid, vid, _name, dn, start in got:
                rows += conn.execute(
                    "update games set venue_id = coalesce(venue_id, ?), "
                    "day_night = coalesce(day_night, ?), "
                    "start_utc = coalesce(start_utc, ?) "
                    "where game_id = ?", (vid, dn, start, gid)).rowcount
            done += 1
    if verbose:
        print(f"resolved {done} dates, set venue on {rows} games")
    return {"dates": done, "games": rows}


def audit() -> dict:
    """Coverage, and how often the home club's park is NOT the venue."""
    q = """
    select count(*) n,
           sum(case when venue_id is null then 1 else 0 end) missing,
           sum(case when day_night is null then 1 else 0 end) no_daynight,
           sum(case when day_night = 'day' then 1 else 0 end) day_games,
           count(distinct venue_id) venues,
           count(distinct home_team) clubs
    from games where sport = 'mlb'
    """
    with db.connect() as c:
        a = dict(c.execute(q).fetchone())
        # A club whose games span more than one venue played somewhere odd.
        a["clubs_with_multiple_home_venues"] = c.execute("""
            select count(*) from (
              select home_team from games
              where sport = 'mlb' and venue_id is not null
              group by home_team having count(distinct venue_id) > 1)
        """).fetchone()[0]
    return a


if __name__ == "__main__":
    import sys
    if "--backfill" in sys.argv:
        backfill()
    a = audit()
    print(f"\n{a['n']} MLB games, {a['missing']} without a venue")
    print(f"  {a['venues']} distinct venues across {a['clubs']} home clubs")
    print(f"  {a['day_games']} day games, {a['missing'] and '?' or ''}"
          f"{a['n'] - a['day_games'] - a['no_daynight']} night, "
          f"{a['no_daynight']} unclassified")
    n = a["clubs_with_multiple_home_venues"]
    print(f"  {n} club(s) hosted at more than one venue"
          + ("  <- these are the games home_team would get wrong" if n
             else ""))
