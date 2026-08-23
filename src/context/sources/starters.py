"""Who actually started, from the boxscore. Ground truth, not a heuristic.

WHY THIS EXISTS. `mlb_pitching` carries no indication of who started, so
every consumer had been inferring it as "most outs on that team that game".
Measured against 120 boxscores that is right 91.7% of the time, and the 8.3%
it gets wrong are not random: they are the starts where the starter was
knocked out early and a long reliever passed him. Tyler Gilbert recorded two
outs and the heuristic credited David Sandlin; Zack Wheeler recorded six and
it credited Kyle Bradish.

The bias therefore runs one way. Short starts are exactly the ones dropped,
so any distribution built on the heuristic has a truncated left tail, an
inflated mean, and an understated early-inning hook hazard. A model tuned
against it will under-predict blowups — which is the half of the outs
distribution an under bet lives in.

`teams.<side>.pitchers[0]` in the boxscore payload is the appearance order,
so the first entry is the starter. One request per game, permanent once
stored: a completed game's starter never changes.

OPENERS ARE INCLUDED and are genuinely starters by this definition. That is
correct for calibration — an opener's two innings belong in the outs
distribution — but callers pricing a listed starter prop should filter on
workload, because no book offers an outs line on a bulk reliever.
"""
from __future__ import annotations

import json
import urllib.request

from src import db, parallel

BASE = "https://statsapi.mlb.com/api/v1"
TIMEOUT = 25


def _boxscore(game_id: str) -> dict | None:
    pk = game_id.split("-")[-1]
    try:
        with urllib.request.urlopen(
                f"{BASE}/game/{pk}/boxscore", timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except Exception:
        return None


def starters_for(game_id: str) -> list[tuple[str, str]]:
    """[(team_abbr, starter_name)] for one game. Empty when unavailable."""
    d = _boxscore(game_id)
    if not d:
        return []
    out = []
    for side in ("away", "home"):
        t = (d.get("teams") or {}).get(side) or {}
        pitchers = t.get("pitchers") or []
        if not pitchers:
            continue
        p = (t.get("players") or {}).get(f"ID{pitchers[0]}") or {}
        name = (p.get("person") or {}).get("fullName")
        abbr = ((t.get("team") or {}).get("abbreviation")
                or (t.get("team") or {}).get("triCode"))
        if name and abbr:
            out.append((abbr, name))
    return out


def backfill(limit: int | None = None, workers: int = 8,
             verbose: bool = True) -> dict:
    """Set `mlb_pitching.is_starter` for every cached game.

    Idempotent and resumable: games where every row already has a non-null
    flag are skipped, so an interrupted run costs only what it had not yet
    reached.
    """
    with db.connect() as conn:
        todo = [r["game_id"] for r in conn.execute("""
            select p.game_id
            from mlb_pitching p join games g on g.game_id = p.game_id
            where g.sport = 'mlb' and g.status = 'Final'
            group by p.game_id
            having sum(case when p.is_starter is null then 1 else 0 end) > 0
            order by p.game_id
        """)]
    if limit:
        todo = todo[:limit]
    if verbose:
        print(f"{len(todo)} game(s) to flag")
    if not todo:
        return {"games": 0, "rows": 0}

    done = rows = failed = 0
    with db.connect() as conn:
        for gid, got, err in parallel.gather(starters_for, todo,
                                             workers=workers):
            if err or not got:
                failed += 1
                continue
            # Default the whole game to 0 first, so a pitcher who did not
            # start is positively recorded as such rather than left null and
            # indistinguishable from "not yet checked".
            conn.execute(
                "update mlb_pitching set is_starter = 0 where game_id = ?",
                (gid,))
            for abbr, name in got:
                cur = conn.execute(
                    "update mlb_pitching set is_starter = 1 "
                    "where game_id = ? and player_name = ?", (gid, name))
                rows += cur.rowcount
            done += 1
            if verbose and done % 100 == 0:
                print(f"  {done}/{len(todo)}")
    if verbose:
        print(f"flagged {done} games, {rows} starter rows, {failed} failed")
    return {"games": done, "rows": rows, "failed": failed}


def audit(conn=None) -> dict:
    """Compare ground truth to the most-outs heuristic it replaces."""
    q = """
    with p as (
      select game_id, team, player_name, outs_recorded o, is_starter,
             row_number() over (partition by game_id, team
                                order by outs_recorded desc) rn
      from mlb_pitching where is_starter is not null)
    select
      sum(case when is_starter = 1 then 1 else 0 end) starters,
      sum(case when is_starter = 1 and rn = 1 then 1 else 0 end) agree,
      sum(case when is_starter = 1 and rn <> 1 then 1 else 0 end) missed,
      avg(case when is_starter = 1 then o end) avg_outs_true,
      avg(case when rn = 1 then o end) avg_outs_heuristic,
      min(case when is_starter = 1 then o end) min_outs_true
    from p
    """
    def _run(c):
        return dict(c.execute(q).fetchone())
    return _run(conn) if conn is not None else _with(_run)


def _with(fn):
    with db.connect() as c:
        return fn(c)


if __name__ == "__main__":
    import sys
    if "--backfill" in sys.argv:
        backfill()
    a = audit()
    if not a.get("starters"):
        print("no rows flagged yet — run with --backfill")
    else:
        print(f"\n{a['starters']} true starts flagged")
        print(f"  most-outs heuristic agreed: {a['agree']} "
              f"({a['agree'] / a['starters']:.1%})")
        print(f"  heuristic MISSED:           {a['missed']} "
              f"({a['missed'] / a['starters']:.1%})")
        print(f"  mean outs, true starters:   "
              f"{a['avg_outs_true']:.2f}")
        print(f"  mean outs, heuristic:       "
              f"{a['avg_outs_heuristic']:.2f}   <- the truncation bias")
        print(f"  shortest true start:        {a['min_outs_true']} outs")
