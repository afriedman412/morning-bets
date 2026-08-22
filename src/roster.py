"""Local MLB player index: name -> position, cached on disk.

Bounds checking catches a line that is impossible for its stat, but not a
stat that is impossible for its PLAYER. 'Masataka Yoshida k over 1.5' (8/1)
is in range for pitcher strikeouts and always will be — Yoshida is a DH, so
that pick is a batter strikeout prop wearing the pitching key. Nothing
downstream can tell without knowing who he is.

statsapi returns every player in the sport in one unauthenticated call, so
the whole question is answerable from a 300 KB file. Rosters move slowly —
a trade or a callup, not a daily churn — so this is refreshed on staleness
rather than on a schedule, and a miss is never a reason to re-fetch: most
misses are nicknames and garbled transcripts ('Palante', 'Bob Bashette'),
which no amount of refreshing will resolve.

    venv/bin/python -m src.roster            # show cache state
    venv/bin/python -m src.roster --refresh  # force a re-pull
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / ".cache"
MAX_AGE_DAYS = 7
USER_AGENT = "morning-bets/1.0"

_URL = (
    "https://statsapi.mlb.com/api/v1/sports/1/players?season={season}"
    "&fields=people,id,fullName,firstName,lastName,primaryPosition,type,"
    "abbreviation,pitchHand,batSide,code,currentTeam"
)

# Position `type` as statsapi reports it. 'Two-Way Player' is deliberately in
# neither set: Ohtani legitimately carries both pitching and batting props,
# so any repair keyed off his position would be a coin flip.
_PITCHER_TYPES = {"Pitcher"}
_BATTER_TYPES = {"Infielder", "Outfielder", "Catcher", "Hitter"}

_index: dict | None = None


def _cache_path(season: int) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / f"mlb_players_{season}.json"


def _fetch(season: int) -> list[dict]:
    req = urllib.request.Request(
        _URL.format(season=season), headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read()).get("people", [])


def _norm(name: str) -> str:
    """Lower-case, strip punctuation and accents-as-written, collapse space."""
    s = re.sub(r"[^\w\s]", "", (name or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def load(season: int | None = None, force: bool = False) -> dict:
    """Return {'by_full': {...}, 'by_last': {...}} for the season.

    Cached in-process and on disk. Re-fetches when the file is missing,
    older than MAX_AGE_DAYS, or `force` is set.
    """
    global _index
    season = season or date.today().year
    if _index is not None and _index.get("season") == season and not force:
        return _index

    p = _cache_path(season)
    stale = (
        force or not p.exists()
        or (time.time() - p.stat().st_mtime) > MAX_AGE_DAYS * 86400
    )
    people: list[dict] | None = None
    if stale:
        try:
            people = _fetch(season)
            p.write_text(json.dumps(people))
        except Exception as e:
            # A stale index beats no index; only a missing one is fatal to
            # the lookup, and that just means "unknown", never a wrong call.
            print(f"  roster refresh failed ({e}); using cache if present")
    if people is None:
        people = json.loads(p.read_text()) if p.exists() else []

    # Records, not bare position strings: the id is needed for every
    # statsapi lookup downstream (game logs, splits), and having two name
    # matchers in the codebase is how they drift apart.
    by_full: dict[str, dict] = {}
    by_last: dict[str, list[dict]] = {}
    by_initial: dict[tuple[str, str], list[dict]] = {}
    for pl in people:
        ptype = (pl.get("primaryPosition") or {}).get("type")
        if not ptype:
            continue
        rec = {
            "id": pl.get("id"),
            "type": ptype,
            "pos": (pl.get("primaryPosition") or {}).get("abbreviation"),
            "name": pl.get("fullName"),
            # Which hand he throws with decides whether a lineup's vs-LHP or
            # vs-RHP split is the relevant one — the single most load-bearing
            # fact about a matchup, and one byte to carry.
            "throws": (pl.get("pitchHand") or {}).get("code"),
            "bats": (pl.get("batSide") or {}).get("code"),
            "team_id": (pl.get("currentTeam") or {}).get("id"),
        }
        by_full[_norm(pl.get("fullName", ""))] = rec
        last = _norm(pl.get("lastName", ""))
        first = _norm(pl.get("firstName", ""))
        if last:
            by_last.setdefault(last, []).append(rec)
            if first:
                by_initial.setdefault((first[0], last), []).append(rec)
    _index = {"season": season, "by_full": by_full, "by_last": by_last,
              "by_initial": by_initial, "n": len(by_full)}
    return _index


_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def candidates(name: str, season: int | None = None) -> list[dict]:
    """Every roster record a name could refer to. Empty when none fit.

    The surname index is ONLY consulted for a bare surname. Falling back to
    it for a full name that missed is how 'Eugenio Suarez' (a third baseman
    absent from this season's index) became a pitcher: the three Suarezes
    who ARE listed all pitch, so an unrelated player's surname answered for
    him and a home-run prop got relabelled 'hr_allowed'. 'Darick Hall' and a
    garbled 'Roki Suzuki' failed the same way. A full name that does not
    match is a different person, not a hint.
    """
    idx = load(season)
    key = _norm(name)
    if not key:
        return []
    if hit := idx["by_full"].get(key):
        return [hit]

    parts = [p for p in key.split() if p not in _SUFFIXES]
    if not parts:
        return []
    # Re-try the exact index once suffixes are gone ("Jacob Lopez Jr").
    if len(parts) > 1 and (hit := idx["by_full"].get(" ".join(parts))):
        return [hit]
    if len(parts) == 1:
        return list(idx["by_last"].get(parts[0], []))
    # "J. Lopez" — an initial plus a surname.
    if len(parts[0]) == 1:
        return list(idx["by_initial"].get((parts[0], parts[-1]), []))
    return []


def position(name: str, season: int | None = None) -> str | None:
    """Position type, or None when it cannot be pinned down.

    Ambiguity is tolerable here in a way it is not for an id: several
    players can share a surname and still answer the only question being
    asked, so long as they all play the same side of the ball. 'Gore'
    resolves; two Rodriguezes on opposite sides do not.

    Returning None is always safe — it means no repair, and a missed
    mislabel is far cheaper than an invented one.
    """
    cands = candidates(name, season)
    types = {c["type"] for c in cands}
    return next(iter(types)) if len(types) == 1 else None


def player_id(name: str, season: int | None = None) -> int | None:
    """MLB id, or None unless the name identifies exactly ONE player.

    Stricter than position() on purpose. Three pitchers named Suarez give a
    usable position and a meaningless id, and an id is what every downstream
    statsapi call keys on — a wrong one silently returns another player's
    game log rather than failing.
    """
    cands = candidates(name, season)
    return cands[0]["id"] if len(cands) == 1 else None


def is_pitcher(name: str, season: int | None = None) -> bool | None:
    """True/False, or None when unknown or two-way (never guess on Ohtani)."""
    pos = position(name, season)
    if pos in _PITCHER_TYPES:
        return True
    if pos in _BATTER_TYPES:
        return False
    return None


def throws(name: str, season: int | None = None) -> str | None:
    """'R', 'L', or None. Same one-player rule as player_id — a handedness
    guessed from the wrong Suarez would select the wrong lineup split."""
    cands = candidates(name, season)
    return cands[0].get("throws") if len(cands) == 1 else None


if __name__ == "__main__":
    import sys
    idx = load(force="--refresh" in sys.argv)
    p = _cache_path(idx["season"])
    age = (time.time() - p.stat().st_mtime) / 86400 if p.exists() else None
    print(f"season {idx['season']}: {idx['n']} players, "
          f"{len(idx['by_last'])} surnames")
    print(f"cache: {p} ({age:.1f} days old)"
          if age is not None else "no cache")
    for who in sys.argv[1:]:
        if who.startswith("--"):
            continue
        cands = candidates(who)
        print(f"  {who}: {position(who)} (pitcher={is_pitcher(who)}, "
              f"id={player_id(who)}, {len(cands)} candidate(s))")
