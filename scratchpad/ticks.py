"""Hourly market and slate snapshots — the only record of what a price WAS.

Kalshi serves the book as it is RIGHT NOW. It cannot be asked what it said
at two o'clock, and neither can the MLB schedule endpoint. So every hour
that is not collected is gone permanently, which is the same argument that
makes `snapshots/` worth keeping and the opposite of `context.db`: nothing
here is derived and nothing here can be rebuilt.

That single fact sets every decision below.

WHAT IT WRITES. One gzip member appended to `ticks/<date>.jsonl.gz` per
run, one JSON object per member:

    {"t": "2026-09-19T22:00:04Z", "date": "2026-09-19",
     "slate": [...], "markets": {"KXMLBTOTAL": [...], ...},
     "failed": {"KXMLBHR": "HTTPError 502"}}

RAW ROWS, NOT A PARSED SCHEMA. The exchange row goes in whole. Kalshi has
already renamed the top-of-book fields once — `summary_book` carries the
warning for it — and a parsed table would have silently dropped a column
across that rename with no way to recover it. The questions this data will
be asked have not been decided yet either. Store whole, derive later; the
same call the play-by-play cache makes.

A PARTIAL SNAPSHOT IS STILL WRITTEN, AND STILL FAILS LOUDLY. If one series
errors the rest are kept and the failure is recorded in `failed`, because
the hour cannot be re-fetched and thirteen series beat none. The exit code
is still non-zero, because the way the last scheduled job on this project
died was by failing quietly into a log nobody read.

IT NEVER CALLS `kalshi.book()`. `markets()` returns rows carrying their own
top-of-book, so a full sweep is one request per series. The per-ticker
orderbook round trip was measured at 50 seconds of a 52-second fetch, and
taking it here would turn an hourly job into a permanent one.

WHY THE SLATE IS IN THE SAME RECORD. `mlb_lineups` is reconstructed from
play-by-play, so it knows what a lineup WAS and never when it posted. The
live hydrate in `slate.slate()` does know — `lineup` is empty until the
card drops — but the board reads it and throws it away. Snapshotting it
beside the prices is what makes "how did the market move when the lineup
dropped" answerable at all; without it the price series has nothing to
join against.

LINEUPS ARE STATE, NOT AN EVENT. They post, then they change — scratches,
late swaps. So the state is stored every hour and diffed, rather than
latching a one-time "dropped" flag, which would miss the second move.

THIS IS NOT IN THE MODELLING LOOP AND MUST NOT ENTER IT. CLV is not the
objective and must never decide whether a mechanism helped; the betting
layer was deleted for that reason. Collecting the series is fine because
it is a record of what happened, but nothing under `src/` may read it and
nothing in the scoring path — `battery`, `fitf5`, `ladder` — may import
this module. `check_ticks_stays_out_of_the_model` pins that.

    venv/bin/python -m scratchpad.ticks            # snapshot now
    venv/bin/python -m scratchpad.ticks --show     # today's changes so far
    venv/bin/python -m scratchpad.ticks --show 2026-09-18
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
#: NOT under `.cache/`. That name reads as "safe to delete" and this is the
#: one tree here that cannot be rebuilt from anything.
TICKS_DIR = os.path.join(ROOT, "ticks")

#: Every series worth a column later. Props and game-level together, because
#: deciding today which ones matter is the choice that cannot be undone.
def _series() -> list[str]:
    from scratchpad import kalshi
    return sorted({*kalshi.SERIES_BY_STAT.values(),
                   *kalshi.GAME_SERIES.values()})


def path_for(date_str: str, ticks_dir: str | None = None) -> str:
    return os.path.join(ticks_dir or TICKS_DIR, f"{date_str}.jsonl.gz")


def append(rec: dict, ticks_dir: str | None = None) -> str:
    """Append one record as its own gzip member. -> the path written.

    Concatenated members are a legal gzip stream and `gzip.open` reads
    them back as one file, so an append never rewrites what is already
    there — a crash mid-run can lose the current hour and nothing else.
    """
    d = ticks_dir or TICKS_DIR
    os.makedirs(d, exist_ok=True)
    p = path_for(rec["date"], d)
    with gzip.open(p, "at", encoding="utf-8") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    return p


def read_day(date_str: str, ticks_dir: str | None = None) -> list[dict]:
    """Every record for a date, oldest first. [] when nothing is stored."""
    p = path_for(date_str, ticks_dir)
    if not os.path.exists(p):
        return []
    out = []
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def lineup_state(slate_rows: list[dict]) -> dict:
    """{game_id: {away/home: {lineup, starter, ...}, status}} for diffing.

    Reads the shape `slate.slate()` returns. An unposted lineup is an
    empty list there, which is exactly the signal we want to timestamp.
    """
    out = {}
    for g in slate_rows or []:
        row = {"status": g.get("status")}
        for side in ("away", "home"):
            s = g.get(side) or {}
            row[side] = {"lineup": list(s.get("lineup") or []),
                         "starter": s.get("starter"),
                         "abbr": s.get("abbr")}
        out[g["game_id"]] = row
    return out


def changes(prev: dict, cur: dict) -> list[dict]:
    """What moved between two `lineup_state` dicts, one dict per change.

    `kind` is the thing a rebuild would key on: a lineup appearing is the
    common case, but a PROBABLE CHANGE is not additive — a late scratch
    reprices the whole game and moves the book further than most lineups
    do. A game seen for the first time is not a change; there is no
    earlier state to have moved from.
    """
    out = []
    for gid, now in cur.items():
        was = prev.get(gid)
        if was is None:
            continue
        for side in ("away", "home"):
            a, b = (was.get(side) or {}), (now.get(side) or {})
            if a.get("starter") != b.get("starter"):
                out.append(dict(game_id=gid, side=side, kind="starter",
                                was=a.get("starter"), now=b.get("starter")))
            old_lu, new_lu = a.get("lineup") or [], b.get("lineup") or []
            if old_lu == new_lu:
                continue
            out.append(dict(
                game_id=gid, side=side,
                kind="lineup_posted" if not old_lu else "lineup_changed",
                was=old_lu, now=new_lu))
        if was.get("status") != now.get("status"):
            out.append(dict(game_id=gid, side=None, kind="status",
                            was=was.get("status"), now=now.get("status")))
    return out


def snapshot(date_str: str, fetch_slate=None, fetch_markets=None) -> dict:
    """One record: the slate and every series, plus whatever failed.

    Both fetchers are injectable so the tests never reach the network.
    A failure is CAUGHT PER SERIES rather than aborting the run — see the
    module docstring on why a partial hour is still worth writing.
    """
    if fetch_slate is None:
        from src.context import slate as slate_mod
        fetch_slate = slate_mod.slate
    if fetch_markets is None:
        from scratchpad import kalshi
        fetch_markets = kalshi.markets

    rec = {"t": dt.datetime.now(dt.timezone.utc)
           .strftime("%Y-%m-%dT%H:%M:%SZ"),
           "date": date_str, "slate": [], "markets": {}, "failed": {}}
    try:
        rec["slate"] = fetch_slate(date_str)
    except Exception as e:
        rec["failed"]["slate"] = f"{type(e).__name__}: {e}"[:200]
    for s in _series():
        try:
            rec["markets"][s] = fetch_markets(s)
        except Exception as e:
            rec["failed"][s] = f"{type(e).__name__}: {e}"[:200]
    return rec


def _fmt(c: dict) -> str:
    if c["kind"] == "lineup_posted":
        return f"  {c['game_id']} {c['side']:4s} LINEUP POSTED ({len(c['now'])})"
    if c["kind"] == "lineup_changed":
        was, now = set(c["was"]), set(c["now"])
        io = ", ".join(sorted(now - was)) or "-"
        out = ", ".join(sorted(was - now)) or "-"
        return f"  {c['game_id']} {c['side']:4s} lineup changed  in: {io}  out: {out}"
    if c["kind"] == "starter":
        return (f"  {c['game_id']} {c['side']:4s} STARTER {c['was']} "
                f"-> {c['now']}")
    return f"  {c['game_id']}      status {c['was']} -> {c['now']}"


def main(argv: list[str]) -> int:
    today = dt.date.today().isoformat()
    if "--show" in argv:
        rest = [a for a in argv if not a.startswith("-")]
        date_str = rest[0] if rest else today
        recs = read_day(date_str)
        if not recs:
            print(f"no ticks stored for {date_str}")
            return 0
        print(f"{len(recs)} snapshots for {date_str}  "
              f"({recs[0]['t']} .. {recs[-1]['t']})")
        for a, b in zip(recs, recs[1:]):
            ch = changes(lineup_state(a["slate"]), lineup_state(b["slate"]))
            if ch:
                print(f"\n{b['t']}")
                for c in ch:
                    print(_fmt(c))
        return 0

    prior = read_day(today)
    rec = snapshot(today)
    p = append(rec)
    n = sum(len(v) for v in rec["markets"].values())
    print(f"{rec['t']}  {len(rec['slate'])} games, {n} markets across "
          f"{len(rec['markets'])} series -> {os.path.relpath(p, ROOT)}")

    if prior:
        ch = changes(lineup_state(prior[-1]["slate"]), lineup_state(rec["slate"]))
        for c in ch:
            print(_fmt(c))
        if not ch:
            print("  no lineup or starter changes since the last snapshot")

    if rec["failed"]:
        # Written, then loud. The hour is banked; the operator still has to
        # hear about it, because the previous scheduled jobs on this project
        # died by exiting 1 into a log nobody read.
        for k, v in rec["failed"].items():
            print(f"  FAILED {k}: {v}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
