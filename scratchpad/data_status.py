"""IS THE DATA CURRENT, AND IF NOT, WHAT IS BEHIND?

    venv/bin/python -m scratchpad.data_status

WHY THIS EXISTS. On 2026-09-09 the raw results were current through
yesterday while `mlb_lineups` was five days stale and 37 of 111 finished
September games were missing from the play-by-play cache — and nothing
anywhere said so. Three of the four launchd jobs had been failing since the
betting layer was deleted (`src.main` and `src.context.snapshot` no longer
exist), each one exiting 1 into a log nobody reads.

THE FAILURE MODE IS SILENCE, NOT ERROR. Every layer below this degrades
quietly: a thin bullpen still simulates, a stale lineup still prices, and a
missing play-by-play game just is not counted. A measurement taken on top
of that looks exactly like a measurement taken on complete data. This
module exists so "is it current" is one command instead of six ad-hoc
queries against tables whose date column is named differently each time.

WHAT IT DOES NOT DO: fetch anything. It reports, and `/backfill-data` acts.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import subprocess

from src.context import store

PBP_CACHE = pathlib.Path(".cache/pbp")
HOOK_ROWS = "/tmp/hook_rows.json"

#: The velocity table is a SHIPPED INPUT, not a derived convenience: every
#: starter's K and BB kick is read off it, and it is a FILE rather than a
#: table, so nothing in this report saw it until 2026-09-22. It had stopped
#: at 2026-09-11 while `mlb_stints` read 0d, and it still carried spring
#: training — it predated the `gametype` relabel, so every pitcher's season
#: mean was contaminated by March. Rebuild: `-m src.context.velo --build`.
VELO_TABLE = "src/context/velo_starts.json"

#: Days a source may trail the newest finished game before it is STALE.
#: One, not zero: a source refreshed after last night's games is current,
#: and a game finishing near midnight UTC can legitimately land a day late.
BUDGET = 1

#: THERE IS NO SCHEDULER, BY DECISION (2026-09-09). All four launchd jobs
#: were unloaded and deleted: three pointed at code removed with the betting
#: layer (`src.main`, `src.context.snapshot`) and had been exiting 1 daily,
#: and the fourth (`grade`) was retired with them — `/backfill-data` is the
#: path now, run before the board.
#:
#: THE LIST STAYS, and it is not vestigial. It is the only thing that can
#: notice a job coming BACK: a stray plist reinstalled by hand would
#: otherwise pull data on its own schedule while every session assumed
#: nothing did. Absent is the expected state and is reported as ok; present
#: is what gets flagged.
RETIRED = ("com.morningbets.grade", "com.morningbets.process",
           "com.morningbets.discover", "com.morningbets.context")

#: AND SINCE 2026-09-20 TWO JOBS ARE SUPPOSED TO BE RUNNING, which inverts
#: this check a second time. `backfill` at 07:30 and `hourly` every hour
#: 08:05-23:05 feed the versioned board series. So absence is no longer
#: uniformly correct: one of these MISSING is now its own silent failure —
#: the boards quietly stop accumulating and the page keeps happily serving
#: yesterday's, which is the exact shape of the drift that killed the last
#: scheduler. A name in neither tuple is a stray and still gets flagged.
EXPECTED = ("com.morningbets.backfill", "com.morningbets.hourly")

JOBS = RETIRED + EXPECTED


def assess(latest: str | None, ref: str, budget: int = BUDGET) -> tuple:
    """(status, lag_days) for a source whose newest row is `latest`.

    Pure so it can be tested without a database. `None` means the source is
    EMPTY, which is a different thing from stale and must not be reported as
    a lag of zero — that is the bug this return shape exists to prevent.
    """
    if not latest:
        return "EMPTY", None
    d0 = datetime.date.fromisoformat(latest)
    d1 = datetime.date.fromisoformat(ref)
    lag = (d1 - d0).days
    return ("ok" if lag <= budget else "STALE"), lag


def _max_date(c, table, schema="", col="date"):
    try:
        q = f"SELECT MAX({col}) FROM {schema}{table}"
        return c.execute(q).fetchone()[0]
    except Exception:
        return None


def _last_useful_date(c, table, col, schema="", date_col="date"):
    """The newest date on which `col` is actually POPULATED.

    A ROW IS NOT A READING. `mlb_weather` carried rows for 2026-09-07,
    -08 and -09 with `temp_f` NULL on all 41 of them — the live board had
    fetched the dates pregame, before statsapi populates the forecast,
    and the empty answer was cached as final. Every freshness check here
    keyed on MAX(date), so the table reported a 0-day lag while two
    shipped mechanisms (`TEMP_HR_MULT`, `WIND_HR_MULT`) sat inert for
    four days. Both are silent-neutral by design, so nothing anywhere
    raised: a missing reading contributes exactly 1.0 and is
    indistinguishable from calm, average air.

    So a source with a content column gets TWO dates, and the gap
    between them is the thing worth seeing.
    """
    try:
        q = (f"SELECT MAX({date_col}) FROM {schema}{table} "
             f"WHERE {col} IS NOT NULL")
        return c.execute(q).fetchone()[0]
    except Exception:
        return None


def pbp_gap(c, since: str) -> tuple[int, int]:
    """(final games since `since`, how many are missing from the cache).

    `status = 'Final'` IS THE TEST, and it must stay the same one
    `pbp.final_games()` uses to decide what to fetch — otherwise this
    reports a gap the backfill will never close. The first version asked
    for `home_score IS NOT NULL` and reported two permanently missing
    games on 2026-09-09: a suspended game sitting 'In Progress' at 1-10
    and a postponed one sitting 'Pre-Game' at 0-0. Both carry a score and
    neither has play-by-play to fetch.
    """
    cached = {f.name.split(".")[0] for f in PBP_CACHE.glob("*.json.gz")}
    rows = c.execute("""SELECT game_id FROM bets.games
                        WHERE date >= ? AND status = 'Final'
                          AND sport = 'mlb'""", (since,)).fetchall()
    miss = sum(1 for (g,) in rows
               if str(g).removeprefix("mlb-") not in cached)
    return len(rows), miss


def job_health() -> list[tuple[str, str, str]]:
    """(job, state, kind) for every `com.morningbets.*` job that matters.

    `kind` is what the caller acts on, and the three are different
    problems, not degrees of one:

      'expected'  one of EXPECTED. Reported whether loaded OR NOT — a
                  missing one is the failure, since the board series
                  silently stops growing and the page serves the last
                  one it got as though it were current.
      'retired'   one of RETIRED, deleted 2026-09-09. Present means
                  something put it back.
      'unknown'   a `com.morningbets.*` nobody declared. MATCHED BY
                  PREFIX rather than by list, which the old check could
                  not do: it compared against four literal names, so a
                  stray under any other name was invisible — exactly the
                  hole this guard was written to close.

    Off macOS, or with no launchd, returns [] rather than claiming every
    expected job is missing.
    """
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:
        return []
    loaded = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2].startswith("com.morningbets."):
            pid, code = parts[0], parts[1]
            loaded[parts[2]] = ("running" if pid.isdigit()
                                else f"last exit {code}")
    return _classify_jobs(loaded)


def job_is_bad(state: str, kind: str) -> bool:
    """Is this job row a FINDING rather than a status line?

    A NON-ZERO LAST EXIT IS A FAILURE. This is the 2026-09-09 death
    exactly: three jobs exited 1 every day into a log nobody read while
    anything that checked only whether they existed said the pipeline was
    fine. Loaded is not running, and running is not succeeding. Proven
    again the hour this was written — `hourly` came back `last exit 126`,
    macOS refusing a launchd agent access to ~/Documents, and the first
    cut of the report printed it as though it were healthy.

    Pure, and shared with the report, so the test cannot pass against a
    copy of the rule while the printed answer says something else.
    """
    if kind != "expected":
        return True                      # retired or undeclared
    if state == "NOT LOADED":
        return True                      # the series has stopped growing
    return state.startswith("last exit ") and state != "last exit 0"


def _classify_jobs(loaded: dict[str, str]) -> list[tuple[str, str, str]]:
    """The sorting, split out PURE so it is testable without launchctl.

    Every EXPECTED job appears whether or not it is loaded; everything
    else appears only when present.
    """
    seen = [(j, loaded.get(j, "NOT LOADED"), "expected") for j in EXPECTED]
    seen += [(j, s, "retired" if j in RETIRED else "unknown")
             for j, s in sorted(loaded.items()) if j not in EXPECTED]
    return seen


def _json_max_date(path: str) -> str | None:
    """Newest `date` in a list-of-rows JSON sidecar, or None.

    TWO SHIPPED INPUTS LIVE IN FILES RATHER THAN IN `context.db`, and a
    file has no row this report can count. Missing and unreadable both
    return None, which `assess` renders as the loudest status there is —
    a sidecar nobody can parse is exactly as stale as one nobody built.
    """
    if not os.path.exists(path):
        return None
    try:
        ds = [r.get("date") for r in json.load(open(path)) if r.get("date")]
    except Exception:
        return None
    return max(ds) if ds else None


def collect() -> dict:
    with store.connect() as c:
        ref = _max_date(c, "games", "bets.")
        srcs = [
            ("bets.games (results)", ref),
            ("mlb_stints", _max_date(c, "mlb_stints")),
            ("mlb_lineups", _max_date(c, "mlb_lineups")),
            ("mlb_batted", _max_date(c, "mlb_batted")),
            ("mlb_weather", _max_date(c, "mlb_weather")),
            # THE CONTENT ROW, not a duplicate of the one above it — see
            # `_last_useful_date`. When these two disagree the table is
            # being written but is not carrying readings.
            ("mlb_weather (temp_f set)",
             _last_useful_date(c, "mlb_weather", "temp_f")),
        ]
        month = (ref or "2000-01-01")[:8] + "01"
        total, miss = pbp_gap(c, month)
    hook = _json_max_date(HOOK_ROWS)
    srcs.append((f"{HOOK_ROWS} (hook rows)", hook))
    srcs.append(("velo_starts.json (velo/zone)", _json_max_date(VELO_TABLE)))
    return {"ref": ref, "sources": srcs, "pbp_total": total,
            "pbp_missing": miss, "month": month,
            "pbp_cached": len(list(PBP_CACHE.glob("*.json.gz")))}


def main():
    d = collect()
    ref = d["ref"]
    print(f"\n  NEWEST FINISHED GAME: {ref}   (everything is measured "
          f"against this, not against the wall clock)\n")
    print(f"  {'source':<34}{'latest':>12}{'lag':>7}{'':>4}status")
    stale = 0
    for name, latest in d["sources"]:
        status, lag = assess(latest, ref)
        stale += status != "ok"
        lag_s = "-" if lag is None else f"{lag}d"
        shown = latest or "(empty)"
        print(f"  {name:<34}{shown:>12}{lag_s:>7}{'':>4}{status}")

    print(f"\n  PLAY-BY-PLAY CACHE: {d['pbp_cached']:,} games on disk")
    if d["pbp_missing"]:
        print(f"    {d['pbp_missing']} of {d['pbp_total']} finished games "
              f"since {d['month']} are NOT cached  <- gap")
        stale += 1
    else:
        print(f"    every finished game since {d['month']} is cached")

    jobs = job_health()
    if jobs:
        print("\n  SCHEDULED JOBS")
        for j, state, kind in jobs:
            bad = job_is_bad(state, kind)
            tag = {"expected": "", "retired": "  RETIRED 2026-09-09",
                   "unknown": "  UNDECLARED"}[kind]
            print(f"    {j:<30}{state}{tag}")
            if bad:
                stale += 1
        if any(k == "expected" and s.startswith("last exit ")
               and s != "last exit 0" for _, s, k in jobs):
            print("    A non-zero exit means it is loaded and FAILING — "
                  "read logs/*.log.\n    On macOS, exit 126 on a repo "
                  "under ~/Documents is the TCC sandbox:\n    grant Full "
                  "Disk Access to /bin/bash in System Settings.")
        if any(s == "NOT LOADED" for _, s, k in jobs if k == "expected"):
            print("    A missing expected job means the board series has "
                  "stopped growing while\n    the page keeps serving the "
                  "last one — reload it with launchctl bootstrap.")
        if any(k != "expected" for _, _, k in jobs):
            print("    A job pulling on its own schedule while sessions "
                  "assume nothing does is\n    how the data drifts "
                  "silently. Remove it or account for it.")

    print(f"\n  {'ALL CURRENT' if not stale else f'{stale} SOURCE(S) BEHIND'}"
          f" — `/backfill-data` refreshes everything in dependency order.\n")


if __name__ == "__main__":
    main()
