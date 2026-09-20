"""Backfill the rest of the season. Every measurement here is sample-starved.

WHY THIS MATTERS MORE THAN ANY FEATURE. The database starts 2026-05-28 —
roughly three months of a six-month season, 1,101 final games. Nearly every
result today ran into the noise floor rather than into a conclusion:

  * The F5 parameter fit moved three constants and every one was noise.
  * Arsenal typing explains 5.2% of reliever K% variance at one sample bar
    and 2.1% at another, which is a way of saying "we cannot tell".
  * A 455-contract Brier win against Kalshi's close evaporated at 2,149.
  * The paired standard error on the fitting objective is 0.008 against
    candidate differences of 0.005.

Doubling the sample does not double the resolution — it improves it by
about sqrt(2) — but several of those numbers sit close enough to their bars
that sqrt(2) decides them. And a full season allows a train/test split with
months on each side rather than two weeks.

WHAT IT PULLS. `grading.cache_day` already does the whole job for one date:
schedule, boxscores, and the first-five linescore. This walks dates and
calls it, then re-runs the three backfills that depend on boxscores being
present — starters, venues and pitch counts — because those read from the
cache rather than from the network.

POLITE BY CONSTRUCTION. One date at a time, sequential, no thread pool. This
is somebody's free public API and there is no deadline here.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

from src import db, grading

#: 2026 opening day. Dates before the season simply return no games, so an
#: early start costs a few wasted schedule calls and nothing else.
SEASON_START = date(2026, 3, 20)


def missing_dates(start: date | None = None, end: date | None = None,
                  conn=None) -> list[str]:
    """Dates in the window with no cached MLB games at all.

    A date with SOME games cached is treated as done. That is right for a
    completed date and wrong only for one interrupted mid-fetch, which the
    `--refetch` flag exists to handle.
    """
    def _run(c):
        return {r["date"] for r in c.execute(
            "select distinct date from games where sport = 'mlb'")}
    have = _run(conn) if conn is not None else _with(_run)
    start = start or SEASON_START
    end = end or (min(have) if have else date.today().isoformat())
    if isinstance(end, str):
        y, m, d = (int(x) for x in end.split("-"))
        end = date(y, m, d)
    out, cur = [], start
    while cur < end:
        s = cur.isoformat()
        if s not in have:
            out.append(s)
        cur += timedelta(days=1)
    return out


def backfill(dates: list[str] | None = None, verbose: bool = True) -> dict:
    dates = dates if dates is not None else missing_dates()
    if verbose:
        print(f"{len(dates)} dates to pull", flush=True)
    ok = fail = 0
    for i, d in enumerate(dates, 1):
        try:
            with db.connect() as conn:
                grading.cache_day(conn, d)
            ok += 1
        except Exception as e:
            fail += 1
            if verbose:
                print(f"  {d}: FAILED {e}", flush=True)
        if verbose and i % 10 == 0:
            print(f"  {i}/{len(dates)}", flush=True)
    if verbose:
        print(f"dates: {ok} ok, {fail} failed")
    return {"ok": ok, "failed": fail}


def _with(fn):
    with db.connect() as c:
        return fn(c)


def status(conn=None) -> dict:
    q = """
    select min(date) lo, max(date) hi, count(*) games,
           sum(case when status = 'Final' then 1 else 0 end) final,
           sum(case when away_score_f5 is not null then 1 else 0 end) f5
    from games where sport = 'mlb'
    """

    def _run(c):
        r = dict(c.execute(q).fetchone())
        r["pitching_rows"] = c.execute(
            "select count(*) n from mlb_pitching").fetchone()["n"]
        r["with_pitches"] = c.execute(
            "select count(*) n from mlb_pitching "
            "where pitches is not null").fetchone()["n"]
        r["with_starter"] = c.execute(
            "select count(*) n from mlb_pitching "
            "where is_starter is not null").fetchone()["n"]
        return r
    return _run(conn) if conn is not None else _with(_run)


if __name__ == "__main__":
    if "--backfill" in sys.argv:
        backfill()
        # Everything downstream reads the boxscore cache, not the network,
        # so these have to run AFTER the games land.
        print("\n-- starters --")
        from src.context.sources import starters
        starters.backfill()
        print("\n-- pitch counts --")
        from src.context.sources import pitches
        pitches.backfill()
        try:
            print("\n-- venues --")
            from src.context.sources import venues
            venues.backfill()
        except Exception as e:
            print(f"  venues backfill skipped: {e}")
    s = status()
    print(f"\n{s['lo']} .. {s['hi']}")
    print(f"  {s['games']} games, {s['final']} final, {s['f5']} with F5 scores")
    print(f"  {s['pitching_rows']} pitching rows — "
          f"{s['with_pitches']} with pitch counts, "
          f"{s['with_starter']} with starter truth")
