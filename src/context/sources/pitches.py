"""Real pitch counts, from a boxscore field the project has been discarding.

WHAT THIS FIXES. `sim.PITCH_COST` assigns a pitch count to every plate
appearance by table lookup — 4.8 for a strikeout, 5.5 for a walk, 3.4 for a
single — and the removal hook keys off the running total. Those nine numbers
were never fitted to anything. The docstring claimed they "reproduce the
observed distribution of starter pitch counts" while also saying the cache
has no pitch counts, which cannot both be true; they came from published
league averages.

That matters because pitch count is the hook's main input, and the hook is
the model's largest measured defect — starters leave before the fifth 31.2%
of the time against a real 25.6%.

AND THE DATA WAS ALREADY THERE. `grading.mlb_boxscore` downloads the full
statsapi pitching blob for every game and keeps eight fields.
`numberOfPitches`, `strikes`, `hitByPitch` and `wildPitches` are in the same
object and were being dropped on the floor. No new source, no play-by-play,
no scraping — one column and a backfill over games already cached.

TWO MORE GUESSED CONSTANTS BECOME MEASURED. `sim.HBP_RATE` (0.011) and
`sim.WP_PB_RATE` (0.028) were set from published league shares. Both are
countable here, on this league, in this season.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

from src import db, grading

_COLS = (("pitches", "INTEGER"), ("strikes", "INTEGER"),
         ("hbp", "INTEGER"), ("wp", "INTEGER"))


def ensure_columns(conn=None) -> None:
    """Idempotent ALTER TABLE, matching how `db.init` migrates."""
    def _run(c):
        have = {r[1] for r in c.execute("PRAGMA table_info(mlb_pitching)")}
        for name, typ in _COLS:
            if name not in have:
                c.execute(f"ALTER TABLE mlb_pitching ADD COLUMN {name} {typ}")
    if conn is not None:
        _run(conn)
    else:
        with db.connect() as c:
            _run(c)


def _lines(game_id: str) -> list[tuple] | None:
    """[(pitches, strikes, hbp, wp, player_name)] for one game, or None."""
    pk = game_id.removeprefix("mlb-")
    try:
        bs = grading._fetch_json(
            f"https://statsapi.mlb.com/api/v1/game/{pk}/boxscore")
    except Exception:
        return None
    out = []
    for side in ("away", "home"):
        team = bs.get("teams", {}).get(side) or {}
        for _pid, p in (team.get("players") or {}).items():
            st = (p.get("stats") or {}).get("pitching") or {}
            if not (st.get("battersFaced") or st.get("outs")):
                continue
            out.append((
                st.get("numberOfPitches"), st.get("strikes"),
                st.get("hitByPitch"), st.get("wildPitches"),
                p["person"]["fullName"], game_id,
            ))
    return out


def backfill(limit: int | None = None, workers: int = 8,
             verbose: bool = True) -> dict:
    """Fill pitch counts for every cached final game that lacks them."""
    ensure_columns()
    with db.connect() as c:
        rows = [r["game_id"] for r in c.execute("""
            select distinct g.game_id
            from games g join mlb_pitching p on p.game_id = g.game_id
            where g.sport = 'mlb' and g.status = 'Final' and p.pitches is null
            order by g.date desc""")]
    if limit:
        rows = rows[:limit]
    if verbose:
        print(f"{len(rows)} games need pitch counts", flush=True)

    done = failed = updated = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for lines in ex.map(_lines, rows):
            done += 1
            if not lines:
                failed += 1
                continue
            with db.connect() as c:
                for pitches, strikes, hbp, wp, name, gid in lines:
                    c.execute("""update mlb_pitching
                                 set pitches = ?, strikes = ?, hbp = ?, wp = ?
                                 where game_id = ? and player_name = ?""",
                              (pitches, strikes, hbp, wp, gid, name))
                    updated += 1
            if verbose and done % 100 == 0:
                print(f"  {done}/{len(rows)}", flush=True)
    if verbose:
        print(f"done: {done} games, {updated} rows, {failed} failed")
    return {"games": done, "rows": updated, "failed": failed}


def summary(conn=None) -> dict:
    """What the new columns say, versus what the model assumed."""
    q = """
    select count(*) n,
           sum(pitches) pitches, sum(outs_recorded) o, sum(h) h, sum(bb) bb,
           sum(k) k, sum(hr) hr, sum(hbp) hbp, sum(wp) wp
    from mlb_pitching p join games g on g.game_id = p.game_id
    where g.sport = 'mlb' and g.status = 'Final' and p.pitches is not null
      and p.is_starter = 1
    """

    def _run(c):
        return dict(c.execute(q).fetchone())
    r = _run(conn) if conn is not None else _with(_run)
    bf = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
    r["bf"] = bf
    r["pitches_per_pa"] = (r["pitches"] or 0) / bf if bf else None
    r["pitches_per_start"] = (r["pitches"] or 0) / r["n"] if r["n"] else None
    # The two constants that stop being guesses.
    r["hbp_rate"] = (r["hbp"] or 0) / bf if bf else None
    r["wp_rate"] = (r["wp"] or 0) / bf if bf else None
    return r


def _with(fn):
    with db.connect() as c:
        return fn(c)


if __name__ == "__main__":
    if "--backfill" in sys.argv:
        n = None
        for a in sys.argv:
            if a.startswith("--limit="):
                n = int(a.split("=")[1])
        backfill(limit=n)
    s = summary()
    if not s["n"]:
        print("no pitch counts yet — run with --backfill")
        sys.exit(0)
    print(f"\n{s['n']} starts with real pitch counts, {s['bf']} batters faced")
    print(f"  pitches per start   {s['pitches_per_start']:.1f}")
    print(f"  pitches per PA      {s['pitches_per_pa']:.3f}"
          f"   (model assumes 3.94)")
    print(f"  HBP per PA          {s['hbp_rate']:.4f}"
          f"   (sim.HBP_RATE = 0.011)")
    print(f"  WP per PA           {s['wp_rate']:.4f}"
          f"   (sim.WP_PB_RATE = 0.028, includes passed balls)")
