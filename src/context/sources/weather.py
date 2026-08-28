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

    venv/bin/python -m src.context.sources.weather [--backfill]
"""
from __future__ import annotations

import json
import re
import sys
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


def fetch_date(date_str: str, force: bool = False) -> list[dict]:
    """Every game's weather for one date. Cached; a final game cannot change."""
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{date_str}.json"
    if p.exists() and not force:
        try:
            return json.loads(p.read_text())
        except ValueError:
            pass
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
            })
    atomic.write_text(p, json.dumps(out))
    return out


def backfill(verbose: bool = True) -> int:
    """Pull every date the games table knows about that we do not have."""
    store.init()
    with store.connect() as c:
        dates = [r["date"] for r in c.execute(
            f"select distinct date from {store.BETS}.games "
            "where sport='mlb' and status='Final' order by date")]
        have = {r["date"] for r in c.execute(
            "select distinct date from mlb_weather")}
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
