"""Durable, immutable, timestamped storage for assembled briefs.

Three things depend on this existing:

  REPLAY        a backtest that rebuilds context from today's leaderboards
                is not a backtest. Savant serves season-to-date numbers and
                cannot be asked what it said in June, so the only honest way
                to evaluate a past card is against the brief that was
                actually written that morning.
  ATTRIBUTION   "what did pick #3 know?" is answerable only if the answer
                was written down at the time.
  LINE MOVEMENT the market is already fetched on every assembly and then
                thrown away. Keep the snapshots and the path falls out for
                free — which is why the highest-coverage gap in the whole
                contract set is a storage problem, not a fetch.

IMMUTABLE, one file per assembly. Nothing is ever overwritten: a second run
at noon writes a second file rather than replacing the morning's, because
the difference between them IS the data. Identical content is skipped by
hash so an idle re-run costs nothing.

Snapshots are ~500 KB of JSON and compress about 12:1, so a full season of
several-per-day lands in tens of megabytes. They are gitignored — this is a
local record, not source.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = PROJECT_ROOT / "snapshots"

# v<context_version>_<utc timestamp>_<content hash>.json.gz
#
# The timestamp carries microseconds and is FIXED WIDTH, both on purpose.
# Ordering here is lexicographic on the filename, and at second resolution
# two snapshots written in the same second sort arbitrarily — which silently
# reported a total moving 8.5 -> 9.0 as 9.0 -> 8.5 and made load() return
# the wrong one of the pair. Real runs are minutes apart and would rarely
# collide, which is exactly what would have made it a bad bug to find later.
_TS_FMT = "%Y%m%dT%H%M%S%fZ"
_NAME = re.compile(
    r"^v(?P<ver>\d+)_(?P<ts>\d{8}T\d{12}Z)_(?P<hash>[0-9a-f]{8})\.json\.gz$"
)


def _digest(snap: dict) -> str:
    """Content hash, ignoring the fields that change on every run.

    assembled_at moves every second; without excluding it, two byte-identical
    briefs taken a minute apart would both be stored and the history would
    fill with noise that looks like movement.
    """
    body = {k: v for k, v in snap.items() if k != "assembled_at"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str).encode()
    ).hexdigest()[:8]


def day_dir(date_str: str) -> Path:
    return SNAPSHOT_DIR / date_str


def save(snap: dict, force: bool = False) -> Path | None:
    """Write a snapshot. Returns the path, or None if identical to the last.

    The no-op-on-identical rule is what makes it safe to assemble on a
    schedule: nothing changes between 3am and 4am on a rained-out slate, and
    storing that twice would imply it did.
    """
    date_str = snap.get("date")
    if not date_str:
        raise ValueError("snapshot has no date")
    d = day_dir(date_str)
    d.mkdir(parents=True, exist_ok=True)

    h = _digest(snap)
    if not force:
        prev = history(date_str)
        if prev and _NAME.match(prev[-1].name).group("hash") == h:
            return None

    ts = datetime.now(timezone.utc).strftime(_TS_FMT)
    path = d / f"v{snap.get('context_version', 0)}_{ts}_{h}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(snap, f, default=str)
    return path


def history(date_str: str, version: int | None = None) -> list[Path]:
    """Every snapshot for a date, oldest first."""
    d = day_dir(date_str)
    if not d.is_dir():
        return []
    out = []
    for p in d.iterdir():
        m = _NAME.match(p.name)
        if not m:
            continue
        if version is not None and int(m.group("ver")) != version:
            continue
        out.append(p)
    return sorted(out, key=lambda p: _NAME.match(p.name).group("ts"))


def read(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def load(
    date_str: str, at: str | None = None, version: int | None = None,
) -> dict | None:
    """The snapshot for a date. Latest by default.

    `at` selects the last snapshot taken at or before a UTC timestamp
    ('20260822T140000Z'), which is how a replay asks what was known at the
    moment a card was actually built rather than what was known by midnight.
    """
    hs = history(date_str, version)
    if not hs:
        return None
    if at:
        eligible = [p for p in hs if _NAME.match(p.name).group("ts") <= at]
        if not eligible:
            return None
        return read(eligible[-1])
    return read(hs[-1])


def versions(date_str: str) -> list[int]:
    return sorted({
        int(_NAME.match(p.name).group("ver")) for p in history(date_str)
    })


# ── line movement, derived rather than fetched ─────────────────────────
def _market_of(game: dict) -> dict | None:
    m = game.get("market") or {}
    if not m:
        return None
    return {
        "total": (m.get("total") or {}).get("over", {}).get("line"),
        "total_over_odds": (m.get("total") or {}).get("over", {}).get("odds"),
        "total_under_odds": (
            (m.get("total") or {}).get("under", {}).get("odds")),
        "ml_away": (m.get("ml") or {}).get("away", {}).get("odds"),
        "ml_home": (m.get("ml") or {}).get("home", {}).get("odds"),
        "runline_away": (m.get("runline") or {}).get("away", {}).get("odds"),
        "runline_home": (m.get("runline") or {}).get("home", {}).get("odds"),
    }


def line_movement(date_str: str) -> dict[str, dict]:
    """{matchup: {opened, current, path, moved}} across a date's snapshots.

    'Opened' here means the first number this system saw, not the true
    market open — the record starts whenever the first assembly ran. Named
    `first_seen` rather than `open` so nobody reads more into it than that.
    """
    hs = history(date_str)
    if not hs:
        return {}
    series: dict[str, list[dict]] = {}
    for p in hs:
        ts = _NAME.match(p.name).group("ts")
        snap = read(p)
        for g in snap.get("games", []):
            mk = _market_of(g)
            if mk:
                series.setdefault(g["matchup"], []).append({"at": ts, **mk})

    out: dict[str, dict] = {}
    for matchup, path in series.items():
        # Movement needs two observations. One snapshot yields moved={},
        # which reads as "the line held" when it actually means "we looked
        # once" — a distinction that matters most on the first assembly of
        # a day, exactly when someone is deciding whether a number is stale.
        if len(path) < 2:
            continue
        first, last = path[0], path[-1]
        moved = {
            k: (last[k], first[k])
            for k in first
            if k != "at" and first[k] is not None and last[k] != first[k]
        }
        out[matchup] = {
            "snapshots": len(path),
            "first_seen": first,
            "current": last,
            "moved": {k: {"from": v[1], "to": v[0]} for k, v in moved.items()},
            "path": path if len(path) > 2 else None,
        }
    return out


def prune(keep_per_day: int = 12) -> int:
    """Drop the oldest snapshots on days that accumulated too many.

    A safety valve for a scheduler gone wrong, not routine housekeeping —
    every deleted snapshot is a point on a line-movement path that cannot be
    recovered.
    """
    removed = 0
    if not SNAPSHOT_DIR.is_dir():
        return 0
    for d in SNAPSHOT_DIR.iterdir():
        if not d.is_dir():
            continue
        hs = history(d.name)
        for p in hs[:-keep_per_day] if len(hs) > keep_per_day else []:
            p.unlink()
            removed += 1
    return removed


if __name__ == "__main__":
    import sys
    from src.context.assemble import assemble

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    d = args[0] if args else datetime.now(timezone.utc).date().isoformat()

    if "--list" in sys.argv:
        for p in history(d):
            m = _NAME.match(p.name)
            print(f"  v{m.group('ver')}  {m.group('ts')}  "
                  f"{p.stat().st_size / 1024:.0f} KB  {m.group('hash')}")
        mv = line_movement(d)
        movers = {k: v for k, v in mv.items() if v["moved"]}
        print(f"\n{len(mv)} games tracked, {len(movers)} with movement")
        for k, v in list(movers.items())[:6]:
            print(f"  {k[:44]:<46}{v['moved']}")
        raise SystemExit

    snap = assemble(d)
    path = save(snap)
    if path is None:
        print(f"{d}: identical to the last snapshot — nothing written")
    else:
        raw = len(json.dumps(snap, default=str))
        gz = path.stat().st_size
        print(f"{d}: wrote {path.name}")
        print(f"  {raw / 1024:.0f} KB raw -> {gz / 1024:.0f} KB gz "
              f"({raw / gz:.1f}:1)")
    print(f"  {len(history(d))} snapshot(s) on file for {d}")
