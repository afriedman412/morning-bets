"""Posted starting lineups, from the schedule endpoint.

One request covers the whole slate — `hydrate=lineups` returns nine players
a side with positions attached, so this costs the same as not having it.

WHEN IT EXISTS. Lineups post a couple of hours before first pitch, so an
8am assembly will find nothing and a 6pm one will find everything. That is
not a failure mode to route around; it is the single most useful thing this
module reports. A brief built before lineups is genuinely less certain than
one built after, and `posted` says which you are holding.

Its main job today is upgrading catcher_framing from an educated guess
about the club's primary receiver to the actual name, but a confirmed
lineup also settles handedness, who is resting, and whether the bat a prop
was written on is even playing.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from src.context import atomic

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = PROJECT_ROOT / ".cache"
BASE = "https://statsapi.mlb.com/api/v1"
UA = "morning-bets/1.0"
TIMEOUT = 25


def _fetch(date_str: str, allow_cache: bool) -> dict:
    """Cache per date, but only once lineups actually exist.

    A morning fetch legitimately returns nothing, and caching that empty
    answer would pin the whole day to 'no lineups' no matter how late the
    assembler ran again. So an empty result is never written to disk.
    """
    CACHE_DIR.mkdir(exist_ok=True)
    p = CACHE_DIR / f"statsapi_lineups_{date_str}.json"
    if allow_cache and p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    url = (f"{BASE}/schedule?sportId=1&date={date_str}"
           f"&hydrate=lineups")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError):
        if p.exists():
            return json.loads(p.read_text())
        return {}
    if any(g.get("lineups") for day in d.get("dates", [])
           for g in day.get("games", [])):
        atomic.write_text(p, json.dumps(d))
    return d


def _player(p: dict) -> dict:
    pos = p.get("primaryPosition") or {}
    return {
        "id": p.get("id"),
        "name": p.get("fullName"),
        "pos": pos.get("abbreviation"),
        "pos_type": pos.get("type"),
    }


def lineups(date_str: str | None = None) -> dict[str, dict]:
    """{game_id: {'away': [...], 'home': [...], 'posted': bool}}."""
    d = _fetch(date_str or date.today().isoformat(), allow_cache=True)
    out: dict[str, dict] = {}
    for day in d.get("dates", []):
        for g in day.get("games", []):
            lu = g.get("lineups") or {}
            away = [_player(p) for p in lu.get("awayPlayers", [])]
            home = [_player(p) for p in lu.get("homePlayers", [])]
            out[f"mlb-{g['gamePk']}"] = {
                "away": away,
                "home": home,
                "posted": bool(away or home),
            }
    return out


def catcher_in(side_lineup: list[dict]) -> dict | None:
    """The catcher in a posted lineup, or None if none is listed."""
    for p in side_lineup or []:
        if (p.get("pos") or "").upper() == "C":
            return p
    return None


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    lu = lineups(d)
    posted = [k for k, v in lu.items() if v["posted"]]
    print(f"{d}: {len(posted)}/{len(lu)} games with a posted lineup\n")
    for gid, v in list(lu.items())[:4]:
        if not v["posted"]:
            print(f"  {gid}: not posted")
            continue
        for side in ("away", "home"):
            c = catcher_in(v[side])
            print(f"  {gid} {side:<5} {len(v[side])} players, "
                  f"C = {c['name'] if c else '(none listed)'}")
