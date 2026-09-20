"""The context layer's own database. `morning_bets.db` stays read-only.

WHY A SECOND FILE. The pipeline database is not version controlled, holds a
season of boxscores that took real time to accumulate, and the notes call it
"the binding constraint on nearly every measurement." The context layer
derives tables from it — `mlb_stints` is 17,260 rows rebuilt from the
play-by-play cache in about thirty seconds — and derived data has no
business sharing a file with data that cannot be regenerated.

THE ATTACH IS READ-ONLY, ON PURPOSE. `context.db` is the writable one and
`morning_bets.db` comes in through a `mode=ro` URI as the `bets` schema, so
a join still reads `bets.games` and `bets.mlb_pitching` exactly as before,
but a stray INSERT against the pipeline tables raises instead of landing.
That is the difference between a convention and a guarantee, and only one of
them survives a coding session at two in the morning.

    from src.context import store
    with store.connect() as c:
        c.execute("select * from mlb_stints s "
                  "join bets.games g on g.game_id = s.game_id")
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.db import DB_PATH as BETS_DB

DB_PATH = Path(__file__).resolve().parent.parent.parent / "context.db"

#: The schema name the pipeline database is attached under. Every
#: cross-database join in the context layer spells it out, which is also
#: what makes those joins obvious in a grep.
BETS = "bets"

SCHEMA = """
CREATE TABLE IF NOT EXISTS mlb_stints (
    game_id TEXT NOT NULL,
    date TEXT,
    team TEXT,
    side TEXT,
    pitcher_id INTEGER,
    player_name TEXT,
    appearance_order INTEGER,
    entry_inning INTEGER,
    entry_outs INTEGER,
    on_1b INTEGER,
    on_2b INTEGER,
    on_3b INTEGER,
    entry_margin INTEGER,
    batters INTEGER,
    outs_recorded INTEGER,
    runs INTEGER,
    last_inning INTEGER,
    PRIMARY KEY (game_id, side, appearance_order)
);

CREATE INDEX IF NOT EXISTS idx_stints_date ON mlb_stints(date);
CREATE INDEX IF NOT EXISTS idx_stints_pitcher
    ON mlb_stints(team, player_name);

CREATE TABLE IF NOT EXISTS mlb_lineups (
    game_id TEXT NOT NULL,
    date TEXT,
    team TEXT NOT NULL,
    side TEXT,
    slot INTEGER NOT NULL,
    player_name TEXT,
    batter_id INTEGER,
    bat_side TEXT,
    PRIMARY KEY (game_id, team, slot)
);

CREATE INDEX IF NOT EXISTS idx_lineups_game ON mlb_lineups(game_id);

CREATE TABLE IF NOT EXISTS mlb_weather (
    game_id TEXT PRIMARY KEY,
    date TEXT,
    venue_id INTEGER,
    temp_f INTEGER,
    condition TEXT,
    wind_mph INTEGER,
    wind_dir TEXT,
    carry INTEGER,
    roof_closed INTEGER
);

CREATE INDEX IF NOT EXISTS idx_weather_date ON mlb_weather(date);
"""


@contextmanager
def connect(attach: bool = True) -> Iterator[sqlite3.Connection]:
    """Open `context.db`, with the pipeline DB attached READ-ONLY as `bets`.

    `attach=False` is for the rare caller that genuinely only touches
    derived tables — it saves opening a second file, nothing more.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    if attach:
        # A URI with mode=ro. sqlite3 refuses to open a URI path unless the
        # flag is set on the connection, but ATTACH honours it regardless,
        # which is why this works without touching how DB_PATH is opened.
        conn.execute(f"ATTACH DATABASE ? AS {BETS}",
                     (f"file:{BETS_DB}?mode=ro",))
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    """Create the derived tables. Idempotent, like `db.init`."""
    with connect(attach=False) as c:
        c.executescript(SCHEMA)


def migrate_from_bets() -> int:
    """Move `mlb_stints` out of `morning_bets.db` if an old copy is there.

    The table lived in the pipeline database for exactly one session. This
    carries it across rather than making anyone re-run the sync, and drops
    the original so the two cannot drift apart and be silently joined
    against each other.
    """
    from src import db
    with db.connect() as c:
        have = c.execute(
            "select name from sqlite_master where type = 'table' "
            "and name = 'mlb_stints'").fetchone()
        if not have:
            return 0
        rows = [tuple(r) for r in c.execute("select * from mlb_stints")]
    init()
    with connect(attach=False) as c:
        c.executemany(
            "insert or replace into mlb_stints values "
            "(" + ",".join("?" * 17) + ")", rows)
    with db.connect() as c:
        c.execute("drop table mlb_stints")
    return len(rows)


if __name__ == "__main__":
    init()
    moved = migrate_from_bets()
    print(f"context.db at {DB_PATH}")
    if moved:
        print(f"  moved {moved} stints out of morning_bets.db")
    with connect() as c:
        n = c.execute("select count(*) from mlb_stints").fetchone()[0]
        g = c.execute(f"select count(*) from {BETS}.games").fetchone()[0]
        print(f"  {n} stints, {g} games readable from {BETS}")
        try:
            c.execute(f"create table {BETS}.canary (x int)")
            print("  WARNING: the pipeline DB is WRITABLE")
        except sqlite3.OperationalError as e:
            print(f"  pipeline DB is read-only ({e})")
