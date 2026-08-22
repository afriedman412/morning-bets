"""Catcher framing, and who is likely to be behind the plate.

Framing is one of the larger measurable catcher skills and it lands squarely
on strikeout and walk props: the gap between the best and worst receivers is
worth real called strikes over a season, and nothing in the current brief
mentions it.

The awkward part is not the framing numbers — Savant publishes those — but
knowing WHICH catcher is catching. That is confirmed_lineup, which does not
post until close to first pitch. So this module offers two answers and is
explicit about which one it is giving:

    starter=True   the catcher named in a posted lineup (exact)
    starter=False  the club's primary catcher by pitches framed (a guess,
                   and flagged as one)

The fallback is usually right — most clubs have a clear number one — but a
brief that silently presents a backup's framing as the starter's is worse
than one that says it is estimating.
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

_URL = (
    "https://baseballsavant.mlb.com/leaderboard/catcher-framing"
    "?year={year}&csv=true"
)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _name(v: str) -> str:
    """Savant writes 'Rogers, Jake'."""
    s = (v or "").strip()
    if "," in s:
        last, first = [x.strip() for x in s.split(",", 1)]
        s = f"{first} {last}"
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", s.lower())).strip()


def framing(
    year: int | None = None, as_of: str | None = None,
) -> dict[str, dict]:
    """{name_key: framing record}. Roughly 61 catchers, and that is fixed.

    Savant applies its own playing-time bar here and honours no `min`
    parameter — min=q, min=1, min=0 and omitting it all return the same 61
    rows, verified directly. So part-time catchers are simply absent, and
    on any given slate two or three posted lineups will name a receiver
    this file has never heard of. That is a limit to report, not route
    around; see for_team().
    """
    year = year or date.today().year
    stamp = as_of or date.today().isoformat()
    CACHE_DIR.mkdir(exist_ok=True)
    p = CACHE_DIR / f"savant_catcher_framing_{year}_{stamp}.csv"
    if p.exists():
        text = p.read_text()
    else:
        req = urllib.request.Request(
            _URL.format(year=year), headers={"User-Agent": UA},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            text = r.read().decode("utf-8", errors="replace")
        if text.lstrip().startswith("<"):
            raise ValueError("catcher-framing returned HTML, not CSV")
        p.write_text(text)

    out: dict[str, dict] = {}
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        key = _name(r.get("name", ""))
        if not key:
            continue
        out[key] = {
            "name": r.get("name"),
            "player_id": _i(r.get("id")),
            "pitches": _i(r.get("pitches")),
            # rv_tot is runs saved by receiving; pct_tot is the share of
            # takes in the shadow zone turned into strikes.
            "framing_runs": round(_f(r.get("rv_tot")) or 0.0, 2),
            "strike_rate": round(_f(r.get("pct_tot")) or 0.0, 4),
        }
    return out


def ranked(year: int | None = None, as_of: str | None = None) -> list[dict]:
    """Framing records ordered best to worst, with a league percentile.

    A raw run value is uninterpretable on its own — is -2.3 bad? — so each
    record carries where it sits among catchers with real playing time.
    """
    recs = [r for r in framing(year, as_of).values() if (r["pitches"] or 0) > 0]
    qualified = sorted(
        (r for r in recs if (r["pitches"] or 0) >= 1000),
        key=lambda r: r["framing_runs"], reverse=True,
    )
    n = len(qualified)
    for i, r in enumerate(qualified):
        r["rank"] = i + 1
        r["of"] = n
        r["percentile"] = round((n - i) / n * 100) if n else None
    return qualified


def primary_catchers(
    year: int | None = None, as_of: str | None = None,
) -> dict[int, dict]:
    """{team_id: the catcher who has framed the most pitches}.

    The fallback for when no lineup is posted. Uses the roster for team
    membership, so a mid-season trade follows the player rather than
    stranding him on his old club.
    """
    from src import roster

    idx = roster.load(year)
    by_id = {r["id"]: r for r in idx["by_full"].values()}
    out: dict[int, dict] = {}
    for rec in framing(year, as_of).values():
        pl = by_id.get(rec["player_id"])
        if not pl or pl.get("pos") != "C" or not pl.get("team_id"):
            continue
        cur = out.get(pl["team_id"])
        if not cur or (rec["pitches"] or 0) > (cur["pitches"] or 0):
            out[pl["team_id"]] = {**rec, "team_id": pl["team_id"],
                                  "estimated": True}
    return out


def league_baseline(
    year: int | None = None, as_of: str | None = None,
) -> dict:
    """Average receiver: the only defensible answer when we know nothing.

    Framing runs are a season total, so they cannot be averaged directly —
    a catcher with twice the playing time contributes twice the runs at
    identical skill. Everything here is therefore a RATE, weighted by
    pitches received.
    """
    recs = [r for r in framing(year, as_of).values() if (r["pitches"] or 0)]
    tp = sum(r["pitches"] for r in recs)
    if not tp:
        return {"runs_per_1000": 0.0, "strike_rate": None, "pitches": 0}
    return {
        "runs_per_1000": round(
            sum(r["framing_runs"] for r in recs) / tp * 1000, 3),
        "strike_rate": round(
            sum(r["strike_rate"] * r["pitches"] for r in recs) / tp, 4),
        "pitches": tp,
        "catchers": len(recs),
    }


def team_prior(
    team_id: int, year: int | None = None, as_of: str | None = None,
) -> dict | None:
    """This club's receiving, weighted across everyone who has caught.

    The honest estimate when no lineup is posted. Taking the primary
    catcher's full value instead assumes he is definitely playing, and when
    he is not it moves the number by the entire gap between him and his
    backup — an eight-run swing on this slate. A playing-time weighting
    lands between them, which is where the truth sits before the card is
    posted.
    """
    from src import roster

    idx = roster.load(year)
    by_id = {r["id"]: r for r in idx["by_full"].values()}
    mine = []
    for rec in framing(year, as_of).values():
        pl = by_id.get(rec["player_id"])
        if pl and pl.get("team_id") == team_id and (rec["pitches"] or 0):
            mine.append(rec)
    if not mine:
        return None
    tp = sum(r["pitches"] for r in mine)
    return {
        "runs_per_1000": round(
            sum(r["framing_runs"] for r in mine) / tp * 1000, 3),
        "strike_rate": round(
            sum(r["strike_rate"] * r["pitches"] for r in mine) / tp, 4),
        "pitches": tp,
        # The underlying values, never just the blend — a two-catcher club
        # split 60/40 between +7 and -5 is a different situation from one
        # where both are average, and the mean hides it.
        "components": sorted(
            [{"name": r["name"], "pitches": r["pitches"],
              "framing_runs": r["framing_runs"]} for r in mine],
            key=lambda r: -(r["pitches"] or 0),
        ),
    }


def for_team(
    team_id: int, catcher_name: str | None = None,
    year: int | None = None, as_of: str | None = None,
) -> dict | None:
    """Framing for the receiver, with an explicit account of how sure we are.

    Three genuinely different states, which an earlier version collapsed
    into two and got wrong:

      exact       the lineup named him and Savant has him
      unrated     the lineup named him and Savant does NOT — a part-timer
                  below their fixed bar. Returning the club's primary
                  catcher here would attach the wrong player's framing to a
                  known name, which is worse than a blank.
      estimated   no lineup, so this is the club's usual receiver

    On a typical slate two or three lineups name an unrated catcher, so
    this is the common path, not an edge case.
    """
    lg = league_baseline(year, as_of)
    if catcher_name:
        hit = framing(year, as_of).get(_name(catcher_name))
        if hit:
            p = hit["pitches"] or 0
            return {
                **hit, "team_id": team_id, "estimated": False,
                "confidence": "exact", "basis": "measured",
                "runs_per_1000": (
                    round(hit["framing_runs"] / p * 1000, 3) if p else None),
                "league": lg,
            }
        # Confirmed receiver, no data on him. Neutral is the answer: he is
        # demonstrably NOT the primary, so substituting the primary's value
        # would push the estimate away from the truth rather than toward it.
        return {
            "name": catcher_name, "team_id": team_id, "player_id": None,
            "pitches": None, "framing_runs": None,
            "strike_rate": lg.get("strike_rate"),
            "runs_per_1000": lg.get("runs_per_1000"),
            "estimated": False, "confidence": "unrated",
            "basis": "league neutral",
            "league": lg,
            "note": "catcher confirmed but below Savant's framing "
                    "playing-time bar; held at league average rather than "
                    "borrowing another catcher's number",
        }
    prior = team_prior(team_id, year, as_of)
    if prior:
        return {
            "name": None, "team_id": team_id,
            "estimated": True, "confidence": "estimated",
            "basis": "team playing-time weighted",
            "league": lg, **prior,
        }
    return {
        "name": None, "team_id": team_id, "estimated": True,
        "confidence": "estimated", "basis": "league neutral",
        "league": lg, **lg,
    }


if __name__ == "__main__":
    rows = ranked()
    print(f"{len(rows)} catchers with 1000+ framed pitches\n")
    print(f"  {'catcher':<24}{'pitches':>9}{'runs':>8}{'strike%':>9}{'pct':>6}")
    for r in rows[:6] + [None] + rows[-4:]:
        if r is None:
            print("  ...")
            continue
        print(f"  {r['name'][:22]:<24}{r['pitches']:>9}"
              f"{r['framing_runs']:>+8.1f}{r['strike_rate'] * 100:>8.1f}%"
              f"{r['percentile']:>6}")
    prim = primary_catchers()
    print(f"\nprimary catcher resolved for {len(prim)} clubs")
