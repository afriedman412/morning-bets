"""Plate umpire assignments, and what a season of them adds up to.

Two halves, deliberately separated:

  RECORD    who worked the plate, one row per game, accumulated in
            `game_officials`. Pure fact, fetched once per date from the
            schedule endpoint — `hydrate=officials` returns the whole
            slate's crew in a single call, so backfilling a season costs
            one request per day rather than one per game.

  PROFILE   what those games looked like, derived by joining the record
            against the boxscores already in `mlb_pitching`. Nothing is
            stored; the interpretation is recomputed so it cannot go stale
            against the underlying games.

HOW STRONG IS THIS SIGNAL. Weaker than it looks, and the output says so.
Strikeouts in a game are driven overwhelmingly by the pitchers in it, not
the umpire, and a season gives one umpire ~25 games. So a K/9 two points
above league average is mostly noise about which staffs he happened to
draw. Every profile therefore carries its sample size and the league
baseline beside it, and `reliable` is False below MIN_GAMES.

Doing it properly would mean pitch-level called-strike accuracy against an
expected zone — statsapi does serve that in playByPlay, at roughly 300
pitches per game. That is a real project, and this is the cheap honest
version until it exists.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, timedelta

from src import db

BASE = "https://statsapi.mlb.com/api/v1"
UA = "morning-bets/1.0"
TIMEOUT = 30

# Below this many games a profile is noise. Not a hard cutoff — the row is
# still returned, with `reliable: False` — because "we have 6 games on this
# umpire" is itself worth showing.
MIN_GAMES = 15


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def fetch_date(date_str: str) -> int:
    """Record every game's crew for one date. Returns rows written.

    Idempotent: re-running a date overwrites the same primary keys rather
    than duplicating, so a backfill can be interrupted and resumed.
    """
    try:
        d = _get(f"{BASE}/schedule?sportId=1&date={date_str}"
                 f"&hydrate=officials")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  officials {date_str}: fetch failed ({e})")
        return 0

    rows = []
    for day in d.get("dates", []):
        for g in day.get("games", []):
            by_type = {
                o.get("officialType"): (o.get("official") or {})
                for o in (g.get("officials") or [])
            }
            plate = by_type.get("Home Plate") or {}
            if not plate:
                continue  # crew not published yet — nothing to record
            rows.append((
                f"mlb-{g['gamePk']}", date_str,
                plate.get("fullName"), plate.get("id"),
                (by_type.get("First Base") or {}).get("fullName"),
                (by_type.get("Second Base") or {}).get("fullName"),
                (by_type.get("Third Base") or {}).get("fullName"),
            ))
    if not rows:
        return 0
    with db.connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO game_officials "
            "(game_id, date, plate_ump, plate_ump_id, first_ump, "
            " second_ump, third_ump) VALUES (?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


def backfill(start: str, end: str | None = None, quiet: bool = False) -> int:
    """Record every date in a range. One request per day."""
    end = end or date.today().isoformat()
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    total = 0
    while d0 <= d1:
        n = fetch_date(d0.isoformat())
        total += n
        if n and not quiet:
            print(f"  {d0} -> {n} game(s)")
        d0 += timedelta(days=1)
    return total


def backfill_missing(quiet: bool = True) -> int:
    """Fill only the dates we have games for but no crew recorded.

    Cheaper than a blind range and safe to run daily: the schedule for a
    date already played never changes, so a recorded day is never refetched.
    """
    with db.connect() as conn:
        gaps = [r[0] for r in conn.execute(
            "SELECT DISTINCT g.date FROM games g "
            "LEFT JOIN game_officials o ON o.game_id = g.game_id "
            "WHERE g.sport='mlb' AND o.game_id IS NULL "
            "ORDER BY g.date"
        )]
    total = 0
    for d in gaps:
        total += fetch_date(d)
    if gaps and not quiet:
        print(f"  filled {len(gaps)} date(s), {total} game(s)")
    return total


# ── profiles ───────────────────────────────────────────────────────────
_PROFILE_SQL = """
    WITH per_game AS (
        SELECT o.plate_ump, o.plate_ump_id, p.game_id,
               SUM(p.k)  AS k,
               SUM(p.bb) AS bb,
               SUM(p.er) AS er,
               SUM(p.outs_recorded) AS outs
        FROM game_officials o
        JOIN mlb_pitching p ON p.game_id = o.game_id
        JOIN games g        ON g.game_id = o.game_id
        WHERE o.plate_ump IS NOT NULL AND g.date < ?
        GROUP BY o.plate_ump, o.plate_ump_id, p.game_id
    )
    SELECT plate_ump, plate_ump_id, COUNT(*) games,
           AVG(k) avg_k, AVG(bb) avg_bb, AVG(er) avg_er,
           SUM(k) tk, SUM(bb) tbb, SUM(outs) touts
    FROM per_game GROUP BY plate_ump, plate_ump_id
"""


def profiles(as_of: str | None = None) -> dict[str, dict]:
    """{umpire_name: tendencies}, derived fresh from the recorded games.

    Rates are per nine innings so a game that went extras does not read as
    a strikeout-friendly umpire. Each row carries the league baseline it
    should be read against — an absolute K/9 means nothing without it.
    """
    cutoff = as_of or date.today().isoformat()
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(_PROFILE_SQL, (cutoff,))]
    if not rows:
        return {}

    lg_outs = sum(r["touts"] or 0 for r in rows)
    lg = {
        "k9": round(sum(r["tk"] or 0 for r in rows) * 27.0 / lg_outs, 2)
        if lg_outs else None,
        "bb9": round(sum(r["tbb"] or 0 for r in rows) * 27.0 / lg_outs, 2)
        if lg_outs else None,
    }

    out: dict[str, dict] = {}
    for r in rows:
        outs = r["touts"] or 0
        k9 = round((r["tk"] or 0) * 27.0 / outs, 2) if outs else None
        bb9 = round((r["tbb"] or 0) * 27.0 / outs, 2) if outs else None
        out[r["plate_ump"]] = {
            "umpire": r["plate_ump"],
            "umpire_id": r["plate_ump_id"],
            "games": r["games"],
            "k9": k9,
            "bb9": bb9,
            "league_k9": lg["k9"],
            "league_bb9": lg["bb9"],
            # Index against the league, 100 = neutral. The comparison is
            # the only part worth reading.
            "k_index": round(k9 / lg["k9"] * 100) if k9 and lg["k9"] else None,
            "bb_index": (
                round(bb9 / lg["bb9"] * 100) if bb9 and lg["bb9"] else None
            ),
            "reliable": (r["games"] or 0) >= MIN_GAMES,
            "caveat": (
                "K/BB in a game are driven mostly by the pitchers, not the "
                "plate umpire; treat as weak evidence"
            ),
        }
    return out


def for_game(game_id: str) -> dict | None:
    """The crew for one game, with the plate umpire's profile attached."""
    with db.connect() as conn:
        r = conn.execute(
            "SELECT * FROM game_officials WHERE game_id=?", (game_id,),
        ).fetchone()
    if not r:
        return None
    rec = dict(r)
    rec["profile"] = profiles().get(rec.get("plate_ump"))
    return rec


if __name__ == "__main__":
    import sys
    db.init()
    if "--backfill" in sys.argv:
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        if args:
            print(f"backfilling from {args[0]}...")
            print(f"  {backfill(args[0])} game(s) recorded")
        else:
            print(f"  {backfill_missing(quiet=False)} game(s) recorded")
    with db.connect() as c:
        n = c.execute("SELECT COUNT(*) n FROM game_officials").fetchone()["n"]
    print(f"\n{n} games with a recorded crew")
    p = profiles()
    print(f"{len(p)} umpires\n")
    print(f"  {'umpire':<22}{'G':>4}{'K/9':>7}{'idx':>5}"
          f"{'BB/9':>7}{'idx':>5}  reliable")
    for u in sorted(p.values(), key=lambda x: -(x["k_index"] or 0)):
        print(f"  {u['umpire'][:20]:<22}{u['games']:>4}{u['k9'] or 0:>7.2f}"
              f"{u['k_index'] or 0:>5}{u['bb9'] or 0:>7.2f}"
              f"{u['bb_index'] or 0:>5}  {'yes' if u['reliable'] else 'no'}")
