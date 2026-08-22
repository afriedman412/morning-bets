"""Has this game started? The one question every live-price fetch must ask.

Once first pitch happens, a "price" stops being a line. ESPN quotes a game
in progress, Kalshi quotes a contract partway to settlement, and anything
that reads either and writes it down as the market number is recording
fiction. A Weathers strikeout prop looked like it moved from -120 to -400
purely because the game had ended.

Three callers need this and none of them had it:

    context.movement          comparing a capper's quote to the board
    grading.fill_missing_prop_lines   filling a null line from Kalshi
    recommend.assign_stakes   repricing a card pick off the live book

The local `games` table cannot answer it — cache_day writes status when it
runs, so mid-afternoon it still reads 'Scheduled' for games already
underway. Verified: the table said Scheduled for 12 games the API called
Pre-Game or Final. So this asks the schedule directly, with a short TTL so
one run does not make the same call fifteen times.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import date

BASE = "https://statsapi.mlb.com/api/v1"
UA = "morning-bets/1.0"
TIMEOUT = 15
TTL_SECONDS = 60

# Everything here means "no pitch has been thrown". Anything else — In
# Progress, Final, Suspended, Completed Early — is off limits for pricing.
PREGAME_STATES = {
    "Scheduled", "Pre-Game", "Warmup", "Delayed Start", "Preview",
    "Postponed",   # never starts; a price is meaningless either way
}

_cache: dict[str, tuple[float, dict]] = {}


def _states(date_str: str) -> dict[str, dict]:
    """{matchup: {status, detailed, game_id}} for a date, TTL-cached."""
    hit = _cache.get(date_str)
    if hit and (time.time() - hit[0]) < TTL_SECONDS:
        return hit[1]
    try:
        req = urllib.request.Request(
            f"{BASE}/schedule?sportId=1&date={date_str}",
            headers={"User-Agent": UA},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        # Unreachable schedule. Return what we had, or nothing — and note
        # that callers treat "unknown" as NOT pregame, so a failure here
        # blocks repricing rather than licensing it.
        return hit[1] if hit else {}
    out: dict[str, dict] = {}
    for day in d.get("dates", []):
        for g in day.get("games", []):
            t = g["teams"]
            out[f"{t['away']['team']['name']} @ {t['home']['team']['name']}"] = {
                "game_id": f"mlb-{g['gamePk']}",
                "status": (g.get("status") or {}).get("abstractGameState"),
                "detailed": (g.get("status") or {}).get("detailedState"),
            }
    _cache[date_str] = (time.time(), out)
    return out


def is_pregame(matchup: str | None, date_str: str | None = None) -> bool:
    """True only when we can positively confirm the game has not begun.

    Unknown resolves to FALSE on purpose. The cost of skipping a legitimate
    reprice is one stale number; the cost of pricing a game in progress is
    a number that is wrong in a way nothing downstream can detect.
    """
    if not matchup:
        return False
    states = _states(date_str or date.today().isoformat())
    rec = states.get(matchup)
    if rec is None:
        from src.grading import same_party
        for m, r in states.items():
            if same_party(m.split(" @ ")[0], matchup) and \
                    same_party(m.split(" @ ")[-1], matchup):
                rec = r
                break
    if rec is None:
        return False
    return (rec.get("detailed") in PREGAME_STATES
            or rec.get("status") == "Preview")


def pregame_matchups(date_str: str | None = None) -> set[str]:
    """Every matchup on a date that has not started."""
    return {
        m for m, r in _states(date_str or date.today().isoformat()).items()
        if r.get("detailed") in PREGAME_STATES or r.get("status") == "Preview"
    }


if __name__ == "__main__":
    import sys
    from collections import Counter
    d = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    st = _states(d)
    print(f"{d}: {len(st)} games")
    print("  ", dict(Counter(r["detailed"] for r in st.values())))
    pre = pregame_matchups(d)
    print(f"  {len(pre)} pregame, {len(st) - len(pre)} off-limits for pricing")
    for m, r in sorted(st.items()):
        mark = "ok" if m in pre else "NO PRICE"
        print(f"    {m[:44]:<46}{r['detailed']:<14}{mark}")
