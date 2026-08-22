"""Baseball Savant adapter: pitcher quality, in both raw and relative form.

Savant publishes the same underlying metrics two ways, and the brief wants
both. `percentile-rankings` gives rank-within-league (xera 13 means 13th
percentile — bad), `expected_statistics` gives the actual number (xERA
5.80). A percentile alone is a comparison with no magnitude, and a raw
number alone needs league context to interpret; carrying both costs a few
tokens and removes the guesswork.

That also settles the xFIP/SIERA question. Neither is published free —
they live at FanGraphs, which has no public API. Savant's xERA is the
Statcast analogue (contact quality plus K and BB) and it is already in a
file this module fetches, so it stands in.

Caching follows the convention the existing savant fetchers in panel.py use:
one file per calendar day, date in the filename, no TTL. That makes a day
reproducible and means a PAST date can only be replayed if a snapshot was
captured that day — these leaderboards are season-to-date and cannot be
reconstructed after the fact. Backtests must treat a missing snapshot as an
error rather than silently fetching today's numbers, which is what
recommend._require_cached already enforces.
"""
from __future__ import annotations

import csv
import io
import re
import urllib.request
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = PROJECT_ROOT / ".cache"
UA = "morning-bets/1.0"
TIMEOUT = 40

_PCT_URL = (
    "https://baseballsavant.mlb.com/leaderboard/percentile-rankings"
    "?type=pitcher&year={year}&csv=true"
)
_EXP_URL = (
    "https://baseballsavant.mlb.com/leaderboard/expected_statistics"
    "?type=pitcher&year={year}&position=&team=&min=q&csv=true"
)


def _load_csv(cache_name: str, url: str) -> list[dict]:
    CACHE_DIR.mkdir(exist_ok=True)
    p = CACHE_DIR / cache_name
    if p.exists():
        text = p.read_text()
    else:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            text = r.read().decode("utf-8", errors="replace")
        # Savant hands back an HTML page rather than a 404 when a leaderboard
        # does not support csv=true. Caching that would poison the day.
        if text.lstrip().startswith("<"):
            raise ValueError(f"{url} returned HTML, not CSV")
        p.write_text(text)
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


def _name_key(v: str) -> str:
    """Savant writes 'Painter, Andrew'; everything else says 'Andrew Painter'."""
    s = (v or "").strip()
    if "," in s:
        last, first = [x.strip() for x in s.split(",", 1)]
        s = f"{first} {last}"
    s = re.sub(r"[^\w\s]", "", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pitcher_percentiles(
    year: int | None = None, as_of: str | None = None,
) -> dict[str, dict]:
    """{name_key: percentile ranks}. Values are RANKS 0-100, not stats.

    Worth being explicit about because the direction is not obvious: for
    xera and xwoba a HIGH percentile is good (Savant ranks these so that
    better run prevention scores higher), and reading 13 as "5.80 ERA"
    rather than "bottom of the league" inverts the whole read.
    """
    year = year or date.today().year
    stamp = as_of or date.today().isoformat()
    rows = _load_csv(
        f"savant_pitcher_percentiles_{year}_{stamp}.csv",
        _PCT_URL.format(year=year),
    )
    out = {}
    for r in rows:
        out[_name_key(r.get("player_name", ""))] = {
            "player_id": r.get("player_id"),
            "xwoba": _f(r.get("xwoba")),
            "xera": _f(r.get("xera")),
            "xba": _f(r.get("xba")),
            "xslg": _f(r.get("xslg")),
            "k_percent": _f(r.get("k_percent")),
            "bb_percent": _f(r.get("bb_percent")),
            "whiff_percent": _f(r.get("whiff_percent")),
            "chase_percent": _f(r.get("chase_percent")),
            "hard_hit_percent": _f(r.get("hard_hit_percent")),
            "barrel_percent": _f(r.get("brl_percent")),
            "fb_velocity": _f(r.get("fb_velocity")),
        }
    return out


def pitcher_expected(
    year: int | None = None, as_of: str | None = None,
) -> dict[str, dict]:
    """{name_key: raw expected stats}. The magnitudes behind the ranks."""
    year = year or date.today().year
    stamp = as_of or date.today().isoformat()
    rows = _load_csv(
        f"savant_pitcher_xstats_{year}_{stamp}.csv",
        _EXP_URL.format(year=year),
    )
    out = {}
    for r in rows:
        out[_name_key(r.get("last_name, first_name", ""))] = {
            "pa": _f(r.get("pa")),
            "ba": _f(r.get("ba")),
            "xba": _f(r.get("est_ba")),
            "slg": _f(r.get("slg")),
            "xslg": _f(r.get("est_slg")),
            "woba": _f(r.get("woba")),
            "xwoba": _f(r.get("est_woba")),
            "era": _f(r.get("era")),
            "xera": _f(r.get("xera")),
        }
    return out


def starter_profile(
    name: str, year: int | None = None, as_of: str | None = None,
) -> dict | None:
    """Both views of one pitcher, merged. None when Savant has no row.

    Raw and percentile side by side is the point: 'xERA 5.80 (13th pct)'
    says both how bad and how unusual, where either number alone leaves the
    reader to supply the other half.
    """
    key = _name_key(name)
    pct = pitcher_percentiles(year, as_of).get(key)
    try:
        raw = pitcher_expected(year, as_of).get(key)
    except Exception:
        raw = None
    if not pct and not raw:
        return None
    return {"name": name, "percentile": pct or {}, "raw": raw or {}}


if __name__ == "__main__":
    import json
    import sys
    who = sys.argv[1] if len(sys.argv) > 1 else "Andrew Painter"
    pct = pitcher_percentiles()
    print(f"percentile-rankings: {len(pct)} pitchers")
    try:
        raw = pitcher_expected()
        print(f"expected_statistics: {len(raw)} pitchers")
    except Exception as e:
        print(f"expected_statistics FAILED: {e}")
    p = starter_profile(who)
    print(f"\n{who}:")
    print(json.dumps(p, indent=2) if p else "  (not listed)")
