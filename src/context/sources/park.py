"""Park factors from Baseball Savant, all indices, all handedness splits.

The last required field. Coors runs at an index of 125 and T-Mobile at 83 —
a 42-point spread that dwarfs most edges anyone claims to find, and one the
current context never mentions.

Savant serves this as a page rather than a CSV: `?csv=true` returns HTML,
which is why an earlier attempt at this looked like a dead end. The table is
embedded in the document as `var data = [...]`, so the adapter parses that
out. Fragile in the way any scrape is — if the page stops declaring the
variable this raises rather than silently returning nothing, so a break is
visible on the first run rather than as a quietly thinner brief.

Two properties worth knowing when reading the numbers:

  * They are 3-YEAR ROLLING (`key_num_years_rolling: 3`), not single-season.
    That is the correct construction — one year of a park is a small sample
    dominated by which teams happened to visit — but it means a park altered
    over the winter takes time to show up.
  * 100 is league average. 125 means 25% more than a neutral park, not 125
    of anything.

Handedness: `batSide` is a query parameter, so L and R splits are one extra
request each. Yankee Stadium's short porch does not treat both sides alike,
and a batter prop wants the split that matches who is hitting.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = PROJECT_ROOT / ".cache"
UA = "Mozilla/5.0 (compatible; morning-bets/1.0)"
TIMEOUT = 40

_URL = (
    "https://baseballsavant.mlb.com/leaderboard/statcast-park-factors"
    "?type=year&year={year}&batSide={side}&stat=index_wOBA"
    "&condition=All&rolling=&parks=mlb"
)
_VAR = re.compile(r"var\s+data\s*=\s*(\[\{.*?\}\]);", re.S)

# Every index the page carries. Named rather than globbed so a new column
# appearing upstream does not silently change the shape of a brief.
INDICES = (
    "runs", "hr", "hits", "1b", "2b", "3b", "bb", "so",
    "woba", "obp", "hardhit", "bacon", "wobacon", "xwobacon", "xbacon",
)

SIDES = ("All", "L", "R")


def _fetch(year: int, side: str, as_of: str | None) -> list[dict]:
    CACHE_DIR.mkdir(exist_ok=True)
    stamp = as_of or date.today().isoformat()
    p = CACHE_DIR / f"savant_park_factors_{year}_{side}_{stamp}.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    url = _URL.format(year=year, side="" if side == "All" else side)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        html = r.read().decode("utf-8", errors="replace")
    m = _VAR.search(html)
    if not m:
        raise ValueError(
            f"park factors: no `var data` in {url} — Savant changed the page"
        )
    rows = json.loads(m.group(1))
    p.write_text(json.dumps(rows))
    return rows


def _norm(v: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (v or "").lower())


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def park_factors(
    year: int | None = None, side: str = "All", as_of: str | None = None,
) -> dict[str, dict]:
    """{venue_key: factors}, keyed by BOTH normalised venue name and club.

    Two keys per park because callers arrive from two directions: the slate
    names a venue, while a bet names a team. Indexing both removes a fuzzy
    match that would otherwise sit between the schedule and the brief.
    """
    year = year or date.today().year
    rows = _fetch(year, side, as_of)
    out: dict[str, dict] = {}
    for r in rows:
        rec = {
            "venue": r.get("venue_name"),
            "venue_id": _as_int(r.get("venue_id")),
            "club": r.get("name_display_club"),
            "team_id": _as_int(r.get("main_team_id")),
            "bat_side": side,
            "years_rolling": _as_int(r.get("key_num_years_rolling")),
            "pa": _as_int(r.get("n_pa")),
            # 100 = league average, for every one of these.
            **{k: _as_int(r.get(f"index_{k}")) for k in INDICES},
        }
        # venue_id first: the schedule payload carries it, so the common
        # path never touches a string. The name and club keys stay for
        # callers that only have a label to work with.
        keys = [
            f"id:{rec['venue_id']}" if rec["venue_id"] else None,
            f"team:{rec['team_id']}" if rec["team_id"] else None,
            _norm(r.get("venue_name")),
            _norm(r.get("name_display_club")),
        ]
        for key in keys:
            if key:
                out[key] = rec
    return out


def for_venue(
    venue: str | None = None, club: str | None = None,
    year: int | None = None, side: str = "All", as_of: str | None = None,
    venue_id: int | None = None, team_id: int | None = None,
) -> dict | None:
    """One park's factors. Prefer venue_id/team_id; names are the fallback.

    'UNIQLO Field at Dodger Stadium' is exactly why: sponsor renames break
    name matching every season, and the id does not move.
    """
    idx = park_factors(year, side, as_of)
    if venue_id:
        # A venue id was supplied, so it is the authority. Falling back to
        # the home club when it does not match is the bug this signature
        # exists to prevent: MLB plays at Field of Dreams, Mexico City,
        # London and the Little League Classic, and handing those games
        # the home team's park factors would be confidently wrong — Mexico
        # City is one of the most extreme run environments anywhere.
        # Missing is the correct answer for a park we have no data on.
        return idx.get(f"id:{venue_id}")
    if team_id and (hit := idx.get(f"team:{team_id}")):
        return hit
    for probe in (venue, club):
        if probe and (hit := idx.get(_norm(probe))):
            return hit
    return None


def all_sides(
    venue: str | None = None, club: str | None = None,
    year: int | None = None, as_of: str | None = None,
) -> dict:
    """{'All': {...}, 'L': {...}, 'R': {...}} for one park.

    Three requests, cached per day. Worth it for a batter prop, where the
    relevant number is the one matching the hitter's side.
    """
    out = {}
    for side in SIDES:
        try:
            got = for_venue(venue, club, year, side, as_of)
        except Exception:
            got = None
        if got:
            out[side] = got
    return out


if __name__ == "__main__":
    import sys
    pf = park_factors()
    seen = {}
    for rec in pf.values():
        seen[rec["venue"]] = rec
    roll = list(seen.values())[0]["years_rolling"] if seen else "?"
    print(f"{len(seen)} parks, {roll}-year rolling, 100 = average\n")
    hdr = ("runs", "hr", "so", "bb", "hits", "woba")
    print(f"  {'venue':<24}{'club':<12}" + "".join(f"{h:>6}" for h in hdr))
    for rec in sorted(seen.values(), key=lambda r: -(r["runs"] or 0)):
        v, cl = (rec["venue"] or "")[:22], (rec["club"] or "")[:10]
        print(f"  {v:<24}{cl:<12}"
              + "".join(f"{str(rec.get(h)):>6}" for h in hdr))
    if len(sys.argv) > 1:
        print(f"\nhandedness splits for {sys.argv[1]}:")
        for side, rec in all_sides(club=sys.argv[1]).items():
            print(f"  {side:<4} runs {rec['runs']:>4}  hr {rec['hr']:>4}  "
                  f"so {rec['so']:>4}  woba {rec['woba']:>4}")
