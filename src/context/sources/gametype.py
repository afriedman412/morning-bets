"""Which games are NOT regular season — spring training, exhibitions, the
All-Star game — so nothing counts them as baseball.

THE FAILURE THIS EXISTS FOR (found 2026-09-21). The schedule ingest asked
statsapi for `sportId=1` by date and took every game it got, so about
150-200 spring-training games a season sat in `games` as `sport='mlb'`,
`status='Final'`, with full batting and pitching lines and cached
play-by-play. Every rate query keys on `sport = 'mlb'`, so all of it was
baseball to the engine: a hitter's April line was mostly March exhibition
at-bats, the April league anchor was exhibition strikeouts on 22,000 PA
where a week of real games is 10,000, and every April starter's pitch
counts, outs and hook decisions carried two-inning March outings. It was
invisible from July on, because by then the exhibitions were a tenth of
the record, and the spring folds (2026-09-20) were the first thing that
scored April at all.

THE FIX IS THE LABEL, NOT THE QUERIES. Relabelling `sport` to `mlb-s`
(spring), `mlb-e` (exhibition) or `mlb-a` (All-Star) excludes the game
from every query that filters on `sport = 'mlb'` — which is nearly all of
them — in one reversible UPDATE, and the ingest applies the same mapping
to new games so it cannot recur. The two queries that did not filter on
sport (`sources/workload.py`, `arm.py`) got the filter the same day.
Postseason games are NOT touched: `rates.EXCLUDE_POSTSEASON` owns that
question by date range and is off until measured.

The ids come from `schedule?sportId=1&season=YYYY&gameType=S|E|A`, one
call per type per season, cached under `.cache/gametype/` so a re-run is
offline. `--apply` relabels, `--revert` puts every row back to `mlb`, and
both print what they touched. Games already relabelled are skipped, so
`--apply` is idempotent.

    venv/bin/python -m src.context.sources.gametype            # report
    venv/bin/python -m src.context.sources.gametype --apply
    venv/bin/python -m src.context.sources.gametype --revert
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.request

BASE = "https://statsapi.mlb.com/api/v1"
CACHE = pathlib.Path(".cache/gametype")
#: statsapi gameType codes that are NOT regular season and NOT postseason.
NON_REGULAR = ("S", "E", "A")
#: The sport label a non-regular game gets. `mlb-s`, `mlb-e`, `mlb-a`.
def sport_for(game_type: str | None) -> str:
    """The `games.sport` value for a statsapi gameType. Regular season and
    every postseason type stay `mlb`; spring, exhibition and All-Star get
    their own label so `sport = 'mlb'` excludes them."""
    if game_type in NON_REGULAR:
        return f"mlb-{game_type.lower()}"
    return "mlb"


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "morning-bets"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def nonregular_ids(season: int, fetch=_get) -> dict[str, str]:
    """{game_id: gameType} for every S/E/A game of `season`, cached."""
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{season}.json"
    if p.exists():
        return json.load(open(p))
    out: dict[str, str] = {}
    for gt in NON_REGULAR:
        d = fetch(f"{BASE}/schedule?sportId=1&season={season}&gameType={gt}")
        for day in d.get("dates", []):
            for g in day.get("games", []):
                out[f"mlb-{g['gamePk']}"] = gt
    json.dump(out, open(p, "w"))
    return out


def apply(conn, ids: dict[str, str]) -> list[tuple[str, str]]:
    """Relabel every `sport='mlb'` game in `ids`. Returns what changed."""
    changed = []
    for gid, gt in ids.items():
        cur = conn.execute("select sport from games where game_id=?",
                           (gid,)).fetchone()
        if cur is None or cur[0] != "mlb":
            continue
        conn.execute("update games set sport=? where game_id=?",
                     (sport_for(gt), gid))
        changed.append((gid, sport_for(gt)))
    conn.commit()
    return changed


def revert(conn) -> int:
    """Every relabelled game back to `mlb`. Returns the count."""
    n = conn.execute("update games set sport='mlb' where sport in "
                     "('mlb-s','mlb-e','mlb-a')").rowcount
    conn.commit()
    return n


def main(argv):
    from src import db
    seasons = (2023, 2024, 2025, 2026)
    with db.connect() as conn:
        if "--revert" in argv:
            print(f"reverted {revert(conn)} games to sport='mlb'")
            return
        for yr in seasons:
            ids = nonregular_ids(yr)
            have = [g for g in ids if conn.execute(
                "select 1 from games where game_id=?", (g,)).fetchone()]
            labelled = [g for g in have if conn.execute(
                "select sport from games where game_id=?", (g,)).fetchone()[0]
                != "mlb"]
            print(f"{yr}: {len(ids)} non-regular games on the schedule, "
                  f"{len(have)} in our records, {len(labelled)} already "
                  f"relabelled")
            if "--apply" in argv:
                ch = apply(conn, ids)
                print(f"      relabelled {len(ch)}")
        if "--apply" not in argv:
            print("(dry run — pass --apply to relabel, --revert to undo)")


if __name__ == "__main__":
    main(sys.argv[1:])
