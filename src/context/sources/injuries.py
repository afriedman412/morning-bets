"""Who is unavailable, and who just became available.

Two halves, because they answer different questions:

  STANDING    the current injured list, from each club's 40-man roster.
              statsapi carries a per-player status there — 'Injured 10-Day',
              'Injured 60-Day' — which the active roster does not, since
              everyone on the active roster is by definition active.
  RECENT      IL moves in the last few days, from the transactions feed.
              One call, and it is the half that catches a bat going down
              yesterday or an arm activated this morning.

The direct use is blunt and valuable: a prop written on a player who is on
the IL is not a bet, and nothing in this system could previously tell.

Thirty roster calls a day sounds heavy and is not — they are small, cached
by date, and fanned out. The transactions feed is a single request.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from src.context import atomic

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = PROJECT_ROOT / ".cache"
BASE = "https://statsapi.mlb.com/api/v1"
UA = "morning-bets/1.0"
TIMEOUT = 25

#: statsapi status descriptions that mean "cannot play today".
OUT_STATUSES = {
    "Injured 7-Day", "Injured 10-Day", "Injured 15-Day", "Injured 60-Day",
    "Bereavement", "Paternity", "Restricted List", "Suspended",
}


def _cached(name: str, url: str) -> dict:
    CACHE_DIR.mkdir(exist_ok=True)
    p = CACHE_DIR / name
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError):
        return json.loads(p.read_text()) if p.exists() else {}
    atomic.write_text(p, json.dumps(d))
    return d


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ",
                  re.sub(r"[^\w\s]", "", (name or "").lower())).strip()


def team_injuries(
    team_id: int, season: int | None = None, as_of: str | None = None,
) -> list[dict]:
    """Everyone on `team_id`'s 40-man who cannot play."""
    season = season or date.today().year
    stamp = as_of or date.today().isoformat()
    d = _cached(
        f"statsapi_roster40_{team_id}_{season}_{stamp}.json",
        f"{BASE}/teams/{team_id}/roster?rosterType=40Man&season={season}",
    )
    out = []
    for p in d.get("roster", []):
        status = (p.get("status") or {}).get("description")
        if status not in OUT_STATUSES:
            continue
        person = p.get("person") or {}
        out.append({
            "name": person.get("fullName"),
            "player_id": person.get("id"),
            "position": (p.get("position") or {}).get("abbreviation"),
            "status": status,
        })
    return out


def all_injuries(
    team_ids: list[int], season: int | None = None, as_of: str | None = None,
) -> dict[int, list[dict]]:
    """{team_id: [injured...]}, fetched concurrently.

    Network only — nothing here writes, so the fan-out is safe.
    """
    from src import parallel

    out: dict[int, list[dict]] = {}
    for tid, got, err in parallel.gather(
        lambda t: team_injuries(t, season, as_of), team_ids, workers=6,
    ):
        out[tid] = got if not err else []
    return out


def recent_moves(
    as_of: str | None = None, days: int = 3,
) -> list[dict]:
    """IL activity in the days before `as_of`. One request.

    Ends the day BEFORE as_of by default so a backtest cannot read a
    transaction filed after the slate it is pricing.
    """
    stamp = as_of or date.today().isoformat()
    end = date.fromisoformat(stamp)
    start = (end - timedelta(days=days)).isoformat()
    d = _cached(
        f"statsapi_txns_{start}_{stamp}.json",
        f"{BASE}/transactions?sportId=1&startDate={start}&endDate={stamp}",
    )
    out = []
    for t in d.get("transactions", []):
        desc = t.get("description") or ""
        if "injured list" not in desc.lower():
            continue
        person = t.get("person") or {}
        out.append({
            "date": t.get("date"),
            "player": person.get("fullName"),
            "player_id": person.get("id"),
            "team": (t.get("toTeam") or t.get("fromTeam") or {}).get("name"),
            "team_id": (t.get("toTeam") or t.get("fromTeam") or {}).get("id"),
            # 'activated ... from the 15-day injured list' is a return;
            # 'placed ... on the 10-day injured list' is a departure.
            "direction": (
                "activated" if "activated" in desc.lower() else
                "placed" if "placed" in desc.lower() else "other"
            ),
            "description": desc,
        })
    return out


def index_by_player(
    injured: dict[int, list[dict]],
) -> dict[str, dict]:
    """{normalised name: record} across every club, for a fast is-he-out."""
    out: dict[str, dict] = {}
    for tid, rows in injured.items():
        for r in rows:
            key = _norm(r.get("name", ""))
            if key:
                out[key] = {**r, "team_id": tid}
    return out


if __name__ == "__main__":
    import sys
    from collections import Counter
    from src.context.sources import opponent

    as_of = sys.argv[1] if len(sys.argv) > 1 else None
    tids = list(opponent.team_ids().values())
    inj = all_injuries(tids, as_of=as_of)
    total = sum(len(v) for v in inj.values())
    print(f"{total} players unavailable across {len(inj)} clubs")
    print("  by status:", dict(Counter(
        r["status"] for v in inj.values() for r in v)))
    worst = sorted(inj.items(), key=lambda kv: -len(kv[1]))[:5]
    abbr = {v: k for k, v in opponent.team_ids().items()}
    print("\n  most depleted:")
    for tid, rows in worst:
        names = ", ".join(f"{r['name']} ({r['position']})" for r in rows[:4])
        print(f"    {abbr.get(tid, tid):<5}{len(rows):>3}  {names}")
    mv = recent_moves(as_of)
    print(f"\n  {len(mv)} IL moves in the last 3 days")
    for m in mv[:6]:
        print(f"    {m['date']}  {m['direction']:<10}{m['description'][:76]}")
