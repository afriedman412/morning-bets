"""Checks for the context layer's own database.

Offline, and pointed at temp files — nothing here opens the real
`context.db` or `morning_bets.db`.

The only property that matters here is the one that is a GUARANTEE rather
than a convention: derived tables are writable, the pipeline database is
not. `morning_bets.db` is not version controlled and holds a season of
boxscores that took real time to accumulate, so "we agreed not to write it"
is worth exactly nothing at two in the morning. The read-only attach is what
makes the agreement enforceable, so it is what gets tested.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from src.context import store


class _Temp:
    """Point `store` at throwaway files for the duration of a check."""

    def __enter__(self):
        self.dir = tempfile.TemporaryDirectory()
        d = Path(self.dir.name)
        self.old = (store.DB_PATH, store.BETS_DB)
        store.DB_PATH = d / "context.db"
        store.BETS_DB = d / "bets.db"
        # A stand-in pipeline database with one row to read back.
        c = sqlite3.connect(store.BETS_DB)
        c.execute("create table games (game_id text, sport text)")
        c.execute("insert into games values ('mlb-1', 'mlb')")
        c.commit()
        c.close()
        store.init()
        return self

    def __exit__(self, *a):
        store.DB_PATH, store.BETS_DB = self.old
        self.dir.cleanup()


def check_the_pipeline_database_cannot_be_written():
    """The whole reason this module exists."""
    with _Temp():
        with store.connect() as c:
            try:
                c.execute(f"create table {store.BETS}.canary (x int)")
            except sqlite3.OperationalError as e:
                assert "readonly" in str(e).lower(), e
            else:
                raise AssertionError("pipeline DB accepted a write")


def check_pipeline_tables_are_still_joinable():
    """Read-only must not mean unreachable — every deployment measurement
    joins stints against `games` and `mlb_pitching`."""
    with _Temp():
        with store.connect() as c:
            got = c.execute(
                f"select game_id from {store.BETS}.games").fetchall()
            assert [r[0] for r in got] == ["mlb-1"], got


def check_derived_tables_are_writable():
    with _Temp():
        with store.connect() as c:
            c.execute("insert into mlb_stints (game_id, side, "
                      "appearance_order) values ('mlb-1', 'home', 0)")
        with store.connect(attach=False) as c:
            n = c.execute("select count(*) from mlb_stints").fetchone()[0]
            assert n == 1, n


def check_the_two_databases_are_different_files():
    assert store.DB_PATH != store.BETS_DB
    assert store.DB_PATH.name == "context.db"


def check_init_is_idempotent():
    with _Temp():
        store.init()
        store.init()
        with store.connect(attach=False) as c:
            cols = {r[1] for r in c.execute("PRAGMA table_info(mlb_stints)")}
        assert "entry_margin" in cols and "on_1b" in cols, cols
