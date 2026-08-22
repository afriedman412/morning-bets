"""Outs Above Average — the gloves behind the pitcher.

A hits-allowed or earned-runs line is partly a bet on defence, and nothing
in the brief has ever mentioned it. The spread is not small: the range
across clubs is worth real outs over a season, and one team's shortstop is
at -17 OAA by himself.

TEAM level is the default and player level is the option, deliberately. A
team number needs no lineup, so it is available at 8am; a sum over the nine
fielders actually starting is more precise but only exists once the card is
posted, and the same reasoning that keeps batter-side evidence out of an
unposted brief applies here.

Savant keys this by `team_id`, which is the same id the schedule payload
carries, so nothing in this module matches on a club name.

Two splits worth knowing are in the payload and carried through:

  * DIRECTIONAL — in, back, and lateral toward each line. A club that
    cannot go to its left is a different problem from one that cannot come
    in on a ball.
  * BY BATTER HAND — defence is positioned differently against righties and
    lefties, so a starter facing a mostly-right-handed lineup should be
    read against the rhh column, not the aggregate.
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
UA = "Mozilla/5.0 (compatible; morning-bets/1.0)"
TIMEOUT = 40

_BASE = "https://baseballsavant.mlb.com/leaderboard/outs_above_average"
_URL = _BASE + "?type={kind}&startYear={year}&endYear={year}&split=no&csv=true"


def _load(kind: str, year: int, as_of: str | None) -> list[dict]:
    stamp = as_of or date.today().isoformat()
    CACHE_DIR.mkdir(exist_ok=True)
    p = CACHE_DIR / f"savant_oaa_{kind}_{year}_{stamp}.csv"
    if p.exists():
        text = p.read_text()
    else:
        req = urllib.request.Request(
            _URL.format(kind=kind, year=year), headers={"User-Agent": UA},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            text = r.read().decode("utf-8", errors="replace")
        if text.lstrip().startswith("<"):
            raise ValueError(f"OAA {kind} returned HTML, not CSV")
        p.write_text(text)
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


def _i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _name(v: str) -> str:
    s = (v or "").strip()
    if "," in s:
        last, first = [x.strip() for x in s.split(",", 1)]
        s = f"{first} {last}"
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", s.lower())).strip()


def team_defense(
    year: int | None = None, as_of: str | None = None,
) -> dict[int, dict]:
    """{team_id: OAA record}. Available without a lineup."""
    year = year or date.today().year
    out: dict[int, dict] = {}
    for r in _load("Fielding_Team", year, as_of):
        tid = _i(r.get("team_id"))
        if tid is None:
            continue
        out[tid] = {
            "team_id": tid,
            "team": r.get("team_name"),
            "oaa": _i(r.get("outs_above_average")),
            "oaa_vs_rhh": _i(r.get("outs_above_average_rhh")),
            "oaa_vs_lhh": _i(r.get("outs_above_average_lhh")),
            "oaa_in": _i(r.get("outs_above_average_infront")),
            "oaa_back": _i(r.get("outs_above_average_behind")),
            "oaa_toward_3b": _i(
                r.get("outs_above_average_lateral_toward3bline")),
            "oaa_toward_1b": _i(
                r.get("outs_above_average_lateral_toward1bline")),
            "success_rate": r.get("actual_success_rate_formatted"),
        }
    return out


def player_defense(
    year: int | None = None, as_of: str | None = None,
) -> dict[str, dict]:
    """{name_key: OAA record} for individual fielders.

    Unused by the assembler today: summing the nine who are starting needs
    a posted lineup, and the standing decision is not to estimate around an
    unposted one. Here for when that changes.
    """
    year = year or date.today().year
    out: dict[str, dict] = {}
    for r in _load("Fielder", year, as_of):
        key = _name(r.get("last_name, first_name", ""))
        if not key:
            continue
        out[key] = {
            "name": r.get("last_name, first_name"),
            "player_id": _i(r.get("player_id")),
            "team": r.get("display_team_name"),
            "pos": r.get("primary_pos_formatted"),
            "oaa": _i(r.get("outs_above_average")),
            "runs_prevented": _f(r.get("fielding_runs_prevented")),
        }
    return out


def for_team(
    team_id: int, year: int | None = None, as_of: str | None = None,
) -> dict | None:
    """One club's defence, with the league spread for context.

    An OAA of +6 means nothing without knowing the league runs -20 to +30;
    the rank travels with the number for the same reason every other module
    here carries its baseline.
    """
    idx = team_defense(year, as_of)
    rec = idx.get(team_id)
    if not rec:
        return None
    vals = sorted(
        (v["oaa"] for v in idx.values() if v["oaa"] is not None), reverse=True,
    )
    oaa = rec["oaa"]
    rank = (vals.index(oaa) + 1) if oaa in vals else None
    return {
        **rec,
        "rank": rank,
        "of": len(vals),
        "league_best": vals[0] if vals else None,
        "league_worst": vals[-1] if vals else None,
    }


if __name__ == "__main__":
    idx = team_defense()
    print(f"{len(idx)} clubs\n")
    print(f"  {'team':<16}{'OAA':>6}{'vsR':>6}{'vsL':>6}"
          f"{'in':>5}{'back':>6}{'3B':>5}{'1B':>5}")
    for r in sorted(idx.values(), key=lambda x: -(x["oaa"] or 0)):
        print(f"  {(r['team'] or '')[:14]:<16}{r['oaa']:>6}{r['oaa_vs_rhh']:>6}"
              f"{r['oaa_vs_lhh']:>6}{r['oaa_in']:>5}{r['oaa_back']:>6}"
              f"{r['oaa_toward_3b']:>5}{r['oaa_toward_1b']:>5}")
