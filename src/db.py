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
    confidence TEXT,
    rationale TEXT,
    result TEXT NOT NULL DEFAULT 'PENDING',
    actual_value REAL,
    graded_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_bets_date_result ON bets(date, result);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection with foreign keys on and row-dict access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    """Create tables if they don't exist; add any missing columns."""
    with connect() as conn:
        conn.executescript(SCHEMA)
        cols = {r["name"] for r in conn.execute(
            "PRAGMA table_info(bets)",
        ).fetchall()}
        if "rationale" not in cols:
            conn.execute("ALTER TABLE bets ADD COLUMN rationale TEXT")
        if "line_inferred" not in cols:
            conn.execute(
                "ALTER TABLE bets ADD COLUMN line_inferred INTEGER DEFAULT 0"
            )
        game_cols = {r["name"] for r in conn.execute(
            "PRAGMA table_info(games)",
        ).fetchall()}
        for col in ("away_team_abbr", "home_team_abbr"):
            if col not in game_cols:
                conn.execute(f"ALTER TABLE games ADD COLUMN {col} TEXT")
