"""Per-inning runs, so the model can be debugged by prefix.

WHY, AND IT IS NOT FOR BETTING. Kalshi lists first-five and full-game totals
and nothing else — no F3, no F7. This exists because an F5 error cannot tell
you WHICH mechanism is wrong: five innings mixes the plate-appearance model,
the removal rule and a little bullpen exposure, and today that decomposition
had to be inferred from runs-per-baserunner ratios instead of measured.

A prefix ladder separates them, because each prefix adds exactly one
mechanism:

    F1-F3   the plate-appearance model ALONE. No bullpen, and the hook
            essentially never fires in three innings — starters throw ~45
            pitches by then against a removal centre of 80.
    F5      rates plus a little hook; the starter covers all five ~76% of
            the time, so the removal rule enters a quarter of the time.
    F7      rates, hook, and real bullpen exposure.
    F9      all of it, with the pen throwing ~40% of the innings.

If F3 is right and F7 is wrong, the defect is in relief. If F3 is already
wrong, nothing downstream can be trusted and the rate model is the problem.
That is a much sharper instrument than a single aggregate.

THE DATA WAS ALREADY BEING FETCHED AND DISCARDED. `grading.mlb_linescore_f5`
pulls the whole innings array and sums `innings[:5]`. Same endpoint, same
call — this stores the entire line so no future prefix needs another
backfill.

DO NOT USE THIS FOR A FULL-GAME TOTAL. A home team leading after eight never
bats in the ninth, so its ninth is blank and `prefix_totals(9)` correctly
drops the game — which means an F9 prefix silently selects for games the home
team was NOT leading, and those score differently. Measured on a 60-game
sample it kept 31. Full games have `away_score`/`home_score` already; use
those. The ladder below stops at F7 for exactly this reason.

STORED AS A STRING, not nine columns. Rain-shortened games have fewer than
nine, a home team leading after eight never bats in the ninth, and extras run
past nine — a fixed column set would need a sentinel for all three. A
comma-separated line handles them by construction, and prefix sums are one
`sum()` away.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

from src import db, grading


def ensure_columns(conn=None) -> None:
    """Idempotent ALTER TABLE, matching how `db.init` migrates."""
    def _run(c):
        have = {r[1] for r in c.execute("PRAGMA table_info(games)")}
        for name in ("away_innings", "home_innings"):
            if name not in have:
                c.execute(f"ALTER TABLE games ADD COLUMN {name} TEXT")
    if conn is not None:
        _run(conn)
    else:
        with db.connect() as c:
            _run(c)


def _line(game_id: str):
    """('0,1,0,...', '2,0,0,...') for one game, or None."""
    pk = game_id.removeprefix("mlb-")
    try:
        ls = grading._fetch_json(
            f"https://statsapi.mlb.com/api/v1/game/{pk}/linescore")
    except Exception:
        return None
    innings = ls.get("innings") or []
    if not innings:
        return None
    away, home = [], []
    for inn in innings:
        a = (inn.get("away") or {}).get("runs")
        h = (inn.get("home") or {}).get("runs")
        # A home team that never batted is a genuine blank, not a zero, and
        # writing 0 would make a 9-inning prefix look complete when the
        # bottom half was never played.
        away.append("" if a is None else str(int(a)))
        home.append("" if h is None else str(int(h)))
    return ",".join(away), ",".join(home)


def backfill(limit: int | None = None, workers: int = 8,
             verbose: bool = True) -> dict:
    ensure_columns()
    with db.connect() as c:
        ids = [r["game_id"] for r in c.execute("""
            select game_id from games
            where sport = 'mlb' and status = 'Final'
              and away_innings is null order by date desc""")]
    if limit:
        ids = ids[:limit]
    if verbose:
        print(f"{len(ids)} games need per-inning lines", flush=True)
    ok = bad = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (gid, res) in enumerate(
                zip(ids, ex.map(_line, ids)), 1):
            if not res:
                bad += 1
                continue
            with db.connect() as c:
                c.execute("update games set away_innings = ?, "
                          "home_innings = ? where game_id = ?",
                          (res[0], res[1], gid))
            ok += 1
            if verbose and i % 200 == 0:
                print(f"  {i}/{len(ids)}", flush=True)
    if verbose:
        print(f"done: {ok} filled, {bad} failed")
    return {"filled": ok, "failed": bad}


def _prefix(line: str | None, n: int) -> int | None:
    """Runs through `n` innings, or None if the game did not get there."""
    if not line:
        return None
    parts = line.split(",")
    if len(parts) < n:
        return None
    tot = 0
    for p in parts[:n]:
        if p == "":
            return None          # a half-inning that was never played
        tot += int(p)
    return tot


def prefix_totals(n: int, before: str | None = None, since: str | None = None,
                  conn=None) -> dict[str, dict]:
    """{game_id: {'away', 'home', 'total'}} through `n` innings.

    Games that did not reach `n` complete innings are omitted rather than
    truncated — a rain-shortened five-inning game is not a five-inning
    prefix of a nine-inning one, it is a different population.
    """
    where = ""
    if before:
        where += f" and date < '{before}'"
    if since:
        where += f" and date >= '{since}'"
    q = (f"select game_id, away_innings a, home_innings h from games "
         f"where sport = 'mlb' and status = 'Final' "
         f"and away_innings is not null{where}")

    def _run(c):
        return c.execute(q).fetchall()
    rows = _run(conn) if conn is not None else _with(_run)
    out = {}
    for r in rows:
        a, h = _prefix(r["a"], n), _prefix(r["h"], n)
        if a is None or h is None:
            continue
        out[r["game_id"]] = {"away": a, "home": h, "total": a + h}
    return out


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
    import statistics as st
    print(f"\n  {'prefix':<8}{'games':>8}{'mean total':>12}{'sd':>8}"
          f"{'runs/inning':>13}")
    # Stops at 7. See the header: an F9 prefix keeps only games where the
    # home team batted in the ninth, which is a different population.
    for n in (1, 2, 3, 4, 5, 6, 7):
        t = prefix_totals(n)
        if not t:
            continue
        tot = [v["total"] for v in t.values()]
        print(f"  F{n:<7}{len(tot):>8}{st.mean(tot):>12.2f}"
              f"{st.pstdev(tot):>8.2f}{st.mean(tot) / n:>13.3f}")
    # Cross-check against the column the project already had.
    with db.connect() as c:
        row = c.execute("""select count(*) n from games
            where sport='mlb' and away_score_f5 is not null
              and away_innings is not null""").fetchone()
    f5 = prefix_totals(5)
    with db.connect() as c:
        old = {r["game_id"]: (r["away_score_f5"] or 0) + (r["home_score_f5"] or 0)
               for r in c.execute("""select game_id, away_score_f5,
                   home_score_f5 from games where sport='mlb'
                   and away_score_f5 is not null""")}
    both = [g for g in f5 if g in old]
    agree = sum(1 for g in both if f5[g]["total"] == old[g])
    print(f"\n  cross-check vs the existing away_score_f5 column:")
    print(f"    {agree}/{len(both)} agree"
          + ("" if agree == len(both) else "   <-- MISMATCH, investigate"))
