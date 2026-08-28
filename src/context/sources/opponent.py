"""How a lineup handles the kind of pitcher it is about to face.

This is the right-hand column of a props-site matchup view, and the field
seven contracts require. The question it answers — does this club strike out
against right-handers? — is the one a career head-to-head line pretends to
answer with 21 plate appearances.

A LIMITATION WORTH KNOWING BEFORE READING ANY OUTPUT.

statsapi will give handedness or recency, not both:

    stats=statSplits&sitCodes=vr + startDate/endDate  -> date range IGNORED
                                                         (returns all 3,411 PA)
    stats=byDateRange + sitCodes=vr                   -> sitCodes IGNORED
                                                         (returns both hands)

Probed directly rather than assumed. So rather than blend two windows into
one number that describes neither, this carries both, labelled:

    vs_hand  — season to date against LHP or RHP specifically
    recent   — last RECENT_DAYS against everyone

A club hitting .242 against righties on the season but .275 overall this
month is telling you something real. It is not telling you they hit .275
against righties this month, and the shape of this record is meant to make
that impossible to misread.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from src.context import atomic

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = PROJECT_ROOT / ".cache"
BASE = "https://statsapi.mlb.com/api/v1"
UA = "morning-bets/1.0"
TIMEOUT = 30
RECENT_DAYS = 30

_SIT = {"L": "vl", "R": "vr"}


def _cached(name: str, url: str) -> dict:
    CACHE_DIR.mkdir(exist_ok=True)
    p = CACHE_DIR / name
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError):
        if p.exists():
            return json.loads(p.read_text())
        raise
    atomic.write_text(p, json.dumps(d))
    return d


def team_ids(season: int | None = None) -> dict[str, int]:
    """{'STL': 138}. Abbreviation is what the rest of the system keys on."""
    season = season or date.today().year
    d = _cached(
        f"statsapi_teams_{season}.json",
        f"{BASE}/teams?sportId=1&season={season}",
    )
    return {t.get("abbreviation"): t["id"]
            for t in d.get("teams", []) if t.get("abbreviation")}


def _rates(st: dict) -> dict:
    """Counting stats are not comparable across windows; rates are."""
    pa = st.get("plateAppearances") or 0
    out = {
        "pa": pa,
        "avg": st.get("avg"),
        "obp": st.get("obp"),
        "slg": st.get("slg"),
        "ops": st.get("ops"),
        "hr": st.get("homeRuns"),
    }
    if pa:
        out["k_pct"] = round((st.get("strikeOuts") or 0) / pa * 100, 1)
        out["bb_pct"] = round((st.get("baseOnBalls") or 0) / pa * 100, 1)
        out["hr_pct"] = round((st.get("homeRuns") or 0) / pa * 100, 2)
    return out


def vs_hand(
    team_id: int, hand: str, season: int | None = None,
    as_of: str | None = None,
) -> dict | None:
    """Season-to-date hitting against LHP ('L') or RHP ('R')."""
    sit = _SIT.get((hand or "").upper())
    if not sit:
        return None
    season = season or date.today().year
    stamp = as_of or date.today().isoformat()
    d = _cached(
        f"statsapi_teamsplit_{team_id}_{sit}_{season}_{stamp}.json",
        f"{BASE}/teams/{team_id}/stats?stats=statSplits&sitCodes={sit}"
        f"&group=hitting&season={season}",
    )
    for blk in d.get("stats", []):
        for s in blk.get("splits", []):
            return {"window": f"season vs {hand.upper()}HP",
                    **_rates(s.get("stat", {}))}
    return None


def recent(
    team_id: int, season: int | None = None, as_of: str | None = None,
    days: int = RECENT_DAYS,
) -> dict | None:
    """Last `days` of hitting against ALL pitchers — form, not matchup.

    Ends the day BEFORE as_of. A window that includes today would let a
    backtest read the game it is betting on.
    """
    season = season or date.today().year
    stamp = as_of or date.today().isoformat()
    end = (date.fromisoformat(stamp) - timedelta(days=1)).isoformat()
    start = (date.fromisoformat(stamp) - timedelta(days=days)).isoformat()
    d = _cached(
        f"statsapi_teamrecent_{team_id}_{season}_{stamp}_{days}.json",
        f"{BASE}/teams/{team_id}/stats?stats=byDateRange&group=hitting"
        f"&season={season}&startDate={start}&endDate={end}",
    )
    for blk in d.get("stats", []):
        for s in blk.get("splits", []):
            return {"window": f"last {days}d, all pitchers",
                    "start": start, "end": end, **_rates(s.get("stat", {}))}
    return None


def profile(
    team_abbr: str, pitcher_hand: str, season: int | None = None,
    as_of: str | None = None,
) -> dict | None:
    """Both views for one club against one handedness. None if unresolvable.

    `pitcher_hand` comes from roster.throws(). When it is None — an
    ambiguous name, a pitcher not on the index — the matchup half cannot be
    selected and only recent form is returned, flagged as such. Guessing a
    hand would pick the wrong split, which is worse than a thinner brief.
    """
    tid = team_ids(season).get((team_abbr or "").upper())
    if not tid:
        return None
    out: dict = {"team": team_abbr.upper(), "team_id": tid,
                 "pitcher_hand": pitcher_hand}
    try:
        out["recent"] = recent(tid, season, as_of)
    except Exception:
        out["recent"] = None
    if pitcher_hand:
        try:
            out["vs_hand"] = vs_hand(tid, pitcher_hand, season, as_of)
        except Exception:
            out["vs_hand"] = None
    else:
        out["vs_hand"] = None
        out["note"] = "pitcher handedness unknown — no matchup split selected"
    return out


if __name__ == "__main__":
    import sys
    from src import roster
    who = sys.argv[1] if len(sys.argv) > 1 else "Andrew Painter"
    opp = sys.argv[2] if len(sys.argv) > 2 else "STL"
    hand = roster.throws(who)
    print(f"{who} throws {hand} vs {opp}\n")
    p = profile(opp, hand)
    if not p:
        print("  unresolved")
        raise SystemExit
    for key in ("vs_hand", "recent"):
        blk = p.get(key)
        if not blk:
            print(f"  {key}: (none)")
            continue
        print(f"  {blk['window']:<26} PA {blk['pa']:>5}  "
              f"{blk.get('avg')}/{blk.get('obp')}/{blk.get('slg')}  "
              f"K {blk.get('k_pct')}%  BB {blk.get('bb_pct')}%  "
              f"HR {blk.get('hr_pct')}%")
    if p.get("note"):
        print(f"  note: {p['note']}")
