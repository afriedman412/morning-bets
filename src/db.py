"""SQLite schema and helpers for bet tracking + per-player game stats."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DB_PATH = Path(__file__).resolve().parent.parent / "morning_bets.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_id TEXT PRIMARY KEY,
    sport TEXT NOT NULL,
    date TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team_abbr TEXT,
    home_team_abbr TEXT,
    away_score INTEGER,
    home_score INTEGER,
    away_score_f5 INTEGER,
    home_score_f5 INTEGER,
    status TEXT
);

CREATE INDEX IF NOT EXISTS idx_games_sport_date ON games(sport, date);

CREATE TABLE IF NOT EXISTS nba_player_stats (
    game_id TEXT NOT NULL REFERENCES games(game_id),
    player_name TEXT NOT NULL,
    team TEXT NOT NULL,
    min INTEGER,
    pts INTEGER,
    reb INTEGER,
    oreb INTEGER,
    dreb INTEGER,
    ast INTEGER,
    stl INTEGER,
    blk INTEGER,
    to_ INTEGER,
    fgm INTEGER,
    fga INTEGER,
    fg3m INTEGER,
    fg3a INTEGER,
    ftm INTEGER,
    fta INTEGER,
    plus_minus INTEGER,
    PRIMARY KEY (game_id, player_name)
);

CREATE TABLE IF NOT EXISTS mlb_batting (
    game_id TEXT NOT NULL REFERENCES games(game_id),
    player_name TEXT NOT NULL,
    team TEXT NOT NULL,
    ab INTEGER,
    r INTEGER,
    h INTEGER,
    "1b" INTEGER,
    "2b" INTEGER,
    "3b" INTEGER,
    hr INTEGER,
    rbi INTEGER,
    bb INTEGER,
    so INTEGER,
    sb INTEGER,
    tb INTEGER,
    PRIMARY KEY (game_id, player_name)
);

CREATE TABLE IF NOT EXISTS mlb_pitching (
    game_id TEXT NOT NULL REFERENCES games(game_id),
    player_name TEXT NOT NULL,
    team TEXT NOT NULL,
    outs_recorded INTEGER,
    h INTEGER,
    r INTEGER,
    er INTEGER,
    k INTEGER,
    bb INTEGER,
    hr INTEGER,
    decision TEXT,
    PRIMARY KEY (game_id, player_name)
);

CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    source_label TEXT NOT NULL,
    source_video_id TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    sport TEXT,
    matchup TEXT,
    game_id TEXT REFERENCES games(game_id),
    player_name TEXT,
    stat TEXT,
    line REAL,
    side TEXT,
    bet_type TEXT NOT NULL,
    period TEXT NOT NULL DEFAULT 'full',
    confidence TEXT,
    rationale TEXT,
    result TEXT NOT NULL DEFAULT 'PENDING',
    actual_value REAL,
    graded_at TEXT,
    stake_cents INTEGER,
    american_odds INTEGER,
    -- What the SOURCE actually said, captured at extraction and never
    -- touched again. `line` and `american_odds` above are the CURRENT
    -- values: the backfills fill them when the source left a null, and the
    -- recommender overwrites odds with the live book price. Without a
    -- frozen copy there is no way to tell a number a capper stated from one
    -- reconstructed off an exchange strike, which matters both for judging
    -- a source's real record and for showing a persona what it is reading.
    -- NULL here means the source never stated one.
    stated_line REAL,
    stated_odds INTEGER
);

CREATE INDEX IF NOT EXISTS idx_bets_date_result ON bets(date, result);

CREATE TABLE IF NOT EXISTS my_bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bet_id INTEGER NOT NULL UNIQUE REFERENCES bets(id) ON DELETE CASCADE,
    stake_cents INTEGER NOT NULL,
    american_odds INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

-- Videos seen by the hourly discovery pass. Discovery is cheap (a yt-dlp
-- listing) and runs through the night; processing costs a transcript pull
-- plus two Claude calls, so it is deferred until the morning. Splitting the
-- two means an upload at 22:30 is known about immediately and paid for once,
-- at a time of our choosing.
CREATE TABLE IF NOT EXISTS video_queue (
    video_id TEXT PRIMARY KEY,
    channel_key TEXT NOT NULL,
    label TEXT NOT NULL,
    title TEXT,
    slate_date TEXT NOT NULL,     -- the betting date this video is for
    found_at TEXT NOT NULL,
    processed_at TEXT,            -- null while still queued
    n_bets INTEGER,
    error TEXT,                   -- last failure, if any
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_queue_pending
    ON video_queue(slate_date, processed_at);

-- One row per digest actually sent, so a manual `make morning` and the
-- scheduled run cannot both mail the same day's card.
CREATE TABLE IF NOT EXISTS digests (
    date TEXT PRIMARY KEY,
    sent_at TEXT NOT NULL,
    recipients TEXT
);

-- One row per bet-slip screenshot mailed in, keyed by image hash so the
-- same picture forwarded twice is only imported once.
CREATE TABLE IF NOT EXISTS bet_slips (
    sha256 TEXT PRIMARY KEY,
    received_at TEXT NOT NULL,
    message_id TEXT,
    filename TEXT,
    n_bets INTEGER NOT NULL DEFAULT 0,
    note TEXT
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection with foreign keys on and row-dict access.

    busy_timeout is per-connection, so it has to be set on every open. The
    default is 5s, which is ample for these writes on its own — the reason
    to raise it is that the panel personas now run concurrently, so a write
    can queue behind another thread's write *and* a boxscore fetch.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    """Create tables if they don't exist; add any missing columns."""
    with connect() as conn:
        conn.executescript(SCHEMA)
        # WAL is a property of the database file, so this runs once and
        # sticks. Under the default rollback journal a writer takes an
        # EXCLUSIVE lock that blocks READERS too, so one persona persisting
        # its picks could stall `make web` mid-run. WAL still permits only
        # one writer at a time — it is not a substitute for keeping writes
        # on a single thread (see src/parallel.py).
        conn.execute("PRAGMA journal_mode = WAL")
        cols = {r["name"] for r in conn.execute(
            "PRAGMA table_info(bets)",
        ).fetchall()}
        if "rationale" not in cols:
            conn.execute("ALTER TABLE bets ADD COLUMN rationale TEXT")
        if "line_inferred" not in cols:
            conn.execute(
                "ALTER TABLE bets ADD COLUMN line_inferred INTEGER DEFAULT 0"
            )
        if "stake_cents" not in cols:
            conn.execute("ALTER TABLE bets ADD COLUMN stake_cents INTEGER")
        if "american_odds" not in cols:
            conn.execute(
                "ALTER TABLE bets ADD COLUMN american_odds INTEGER"
            )
        if "period" not in cols:
            conn.execute(
                "ALTER TABLE bets ADD COLUMN period TEXT "
                "NOT NULL DEFAULT 'full'"
            )
        if "stated_line" not in cols:
            conn.execute("ALTER TABLE bets ADD COLUMN stated_line REAL")
            # Backfill history: before the prop backfill existed, `line` was
            # only ever what the source said, EXCEPT where the consensus
            # fill flagged it. So the old rows can be reconstructed exactly.
            conn.execute(
                "UPDATE bets SET stated_line = "
                "CASE WHEN COALESCE(line_inferred, 0) = 1 THEN NULL "
                "ELSE line END"
            )
        if "stated_odds" not in cols:
            conn.execute("ALTER TABLE bets ADD COLUMN stated_odds INTEGER")
            # Odds were never overwritten before now, so whatever is in
            # american_odds on an existing row is what the source stated.
            conn.execute("UPDATE bets SET stated_odds = american_odds")
        game_cols = {r["name"] for r in conn.execute(
            "PRAGMA table_info(games)",
        ).fetchall()}
        for col in ("away_team_abbr", "home_team_abbr"):
            if col not in game_cols:
                conn.execute(f"ALTER TABLE games ADD COLUMN {col} TEXT")
        for col in ("away_score_f5", "home_score_f5"):
            if col not in game_cols:
                conn.execute(
                    f"ALTER TABLE games ADD COLUMN {col} INTEGER"
                )
