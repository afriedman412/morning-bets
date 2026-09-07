"""Recent fastball velocity -> tonight's strikeout rate. Item E.

    venv/bin/python -m src.context.velo --build     rebuild the table
    venv/bin/python -m src.context.velo             coverage + tonight's kicks

THE FINDING (day 22, third sitting): a starter's fastball velocity over
his last five starts, measured against his own season-to-date mean,
predicts his NEXT start's K% directly — and once it is in, the box-score
K streak adds almost nothing (drift persistence 0.18 -> 0.04). The radar
gun, not the game log. Counted on 8,240 pre-holdout start-rows with a
10-sigma positive control (`scratchpad/streaks.py`); per-season betas
+0.0137/+0.0188/+0.0124/+0.0282 — same sign, four seasons.

WHAT SHIPS is the univariate term, because velocity is what gets wired
and its coefficient must own everything that travels with it:

    k_pct += VELO_K_PER_MPH * (recent5_fb - season_fb - VELO_CENTER_MPH)

Centred on the TRAINING mean of the drift so the league K level is
untouched by construction; the falsifier's level clause is then a proof,
not a target. Applied to the STARTER only — measured on starters, and
"measured on starters, applied to every arm" is the recorded error
pattern (hit-by-pitch, sacrifices, wild pitches).

LEAK-FREE BY LOOKUP SHAPE: `kick_for(name, date)` reads starts STRICTLY
BEFORE the date, same season, so a replay of July is priced off June's
radar and a backtest cannot see its own game. Thin history (< 5 prior
starts with velocity, or < 3 in the recent window) returns exactly 0.0 —
silent-neutral, the ump/air rail's rule.

The table is per-start FF/SI mean release speed, extracted from our own
play-by-play cache (which carried per-pitch velocity for four seasons,
unread, until 2026-09-07). Rebuild is one pass over the cache, ~1 min.
"""
from __future__ import annotations

import glob
import gzip
import json
import multiprocessing as mp
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
PATH = _HERE + "/velo_starts.json"

#: Counted 2026-09-07 on 8,240 training rows (date < holdout, four
#: seasons), +5.3 sigma. K% points per mph of recent-vs-season drift.
VELO_K_PER_MPH = 0.0157
#: The training mean of the drift. Subtracted so the term is exactly the
#: counted regressor and the league level is invariant by construction.
VELO_CENTER_MPH = 0.0677
#: Pitch codes that count as "the fastball". Four-seam and sinker; cutters
#: are excluded — half the league throws one as a breaking-ball surrogate
#: and its speed tracks usage, not arm state.
FB_CODES = {"FF", "SI"}
#: Minimum pitches for a start's velo to mean anything.
MIN_FB = 10
#: History gates, matching the screen that counted the coefficient.
MIN_SEASON_STARTS = 5
MIN_RECENT = 3
RECENT_STARTS = 5

_INDEX: dict[str, list[tuple[str, float]]] | None = None
_MEMO: dict[tuple[str, str], float] = {}


# ── extraction (build time only) ────────────────────────────────────────

def _one(path: str):
    """[(name, velo, n_fb)] for the two STARTERS of one cached game."""
    try:
        d = json.load(gzip.open(path))
    except Exception:
        return None
    plays = (d.get("allPlays")
             or (d.get("liveData") or {}).get("plays", {}).get("allPlays")
             or [])
    if not plays:
        return None
    pk = path.split("/")[-1].split(".")[0]
    first: dict[str, str] = {}
    acc: dict[str, list] = {}
    for p in plays:
        m = (p.get("matchup") or {}).get("pitcher") or {}
        name = m.get("fullName")
        if not name:
            continue
        # top of an inning: the HOME club pitches
        side = "home" if (p.get("about") or {}).get("isTopInning") else "away"
        first.setdefault(side, name)
        if first[side] != name:
            continue
        for ev in p.get("playEvents") or []:
            if not ev.get("isPitch"):
                continue
            code = ((ev.get("details") or {}).get("type") or {}).get("code")
            sp = (ev.get("pitchData") or {}).get("startSpeed")
            if code in FB_CODES and sp:
                a = acc.setdefault(name, [0.0, 0])
                a[0] += sp
                a[1] += 1
    return [(pk, n, s / c, c) for n, (s, c) in acc.items() if c >= MIN_FB]


def build(path: str = PATH) -> None:
    from src import db
    files = sorted(glob.glob(".cache/pbp/*.json.gz"))
    print(f"  {len(files)} cached games")
    with mp.get_context("fork").Pool(max(mp.cpu_count() - 1, 1)) as pool:
        got = pool.map(_one, files, chunksize=64)
    with db.connect() as c:
        dates = {r["game_id"]: r["date"] for r in c.execute(
            "select game_id, date from games where sport='mlb'")}
    rows = [{"name": n, "date": dates[f"mlb-{pk}"], "velo": round(v, 2),
             "n_fb": nf}
            for g in got if g for pk, n, v, nf in g
            if dates.get(f"mlb-{pk}")]
    rows.sort(key=lambda r: (r["name"], r["date"]))
    json.dump(rows, open(path, "w"))
    print(f"  {len(rows)} starter-start velo rows -> {path}")


# ── lookup (sim time) ───────────────────────────────────────────────────

def _index() -> dict[str, list[tuple[str, float]]]:
    global _INDEX
    if _INDEX is None:
        _INDEX = {}
        try:
            for r in json.load(open(PATH)):
                _INDEX.setdefault(r["name"], []).append((r["date"],
                                                         r["velo"]))
        except (OSError, ValueError):
            pass                      # no table: every kick is 0.0
    return _INDEX


def kick_for(name: str, date: str | None) -> float:
    """The additive k_pct term for this starter on this date. 0.0 when
    history is thin or the table is absent — never a guess."""
    if not name or not date:
        return 0.0
    key = (name, date)
    if key in _MEMO:
        return _MEMO[key]
    season = date[:4]
    prior = [v for d, v in _index().get(name, ())
             if d < date and d[:4] == season]
    recent = prior[-RECENT_STARTS:]
    kick = 0.0
    if len(prior) >= MIN_SEASON_STARTS and len(recent) >= MIN_RECENT:
        drift = sum(recent) / len(recent) - sum(prior) / len(prior)
        kick = VELO_K_PER_MPH * (drift - VELO_CENTER_MPH)
    _MEMO[key] = kick
    return kick


def _reset() -> None:
    """Tests only: drop the lazy index and memo."""
    global _INDEX
    _INDEX = None
    _MEMO.clear()


if __name__ == "__main__":
    if "--build" in sys.argv:
        build()
        raise SystemExit
    from src import db
    with db.connect() as c:
        starts = [(r["player_name"], r["date"]) for r in c.execute(
            "select p.player_name, g.date from mlb_pitching p"
            " join games g on g.game_id = p.game_id"
            " where p.is_starter = 1 and g.sport = 'mlb'"
            " and g.status = 'Final' and g.date >= '2026-07-01'")]
    kicks = [kick_for(n, d) for n, d in starts]
    live = [k for k in kicks if k != 0.0]
    print(f"  coverage on 2026 July-onward starts: "
          f"{len(live)}/{len(kicks)} ({len(live) / len(kicks):.1%})")
    import statistics as st
    print(f"  kick spread: mean {st.mean(live):+.5f}  sd {st.pstdev(live):.5f}"
          f"  range {min(live):+.4f} .. {max(live):+.4f}  (k_pct points)")
