"""Which JSON is the board of record for a date.

One answer shared by the Flask server (`board_server`) and the update
checker (`check_updates`), so the page a reader opens and the board a
cron compares against can never be two different files. A date often has
several JSONs — `_board`, `_board_v2`, `_board_v3` — because the board is
re-run when lineups post; the LAST one written is the board of record,
decided by mtime rather than by parsing version suffixes.

Only the new-format files match: `bets/YYYY_MM_DD_board*.json`, the shape
`board_json.parse` writes (a `games` list of row dicts). The flat
`bets/YYYY_MM_DD.json` files are the old betting layer's records and are
not boards.
"""
from __future__ import annotations

import json
import os
import re

BETS_DIR = os.path.join(os.path.dirname(__file__), "..", "bets")

BOARD_FILE = re.compile(r"^(\d{4})_(\d{2})_(\d{2})_board.*\.json$")


def board_files(bets_dir: str | None = None) -> dict[str, list[str]]:
    """{iso date: [paths, oldest mtime first]} for every board JSON.

    `bets_dir` defaults to BETS_DIR at CALL time, not def time, so the
    server and the tests can repoint the module attribute.
    """
    bets_dir = bets_dir or BETS_DIR
    out: dict[str, list[str]] = {}
    for fn in os.listdir(bets_dir):
        m = BOARD_FILE.match(fn)
        if not m:
            continue
        d = "-".join(m.groups())
        out.setdefault(d, []).append(os.path.join(bets_dir, fn))
    for d in out:
        out[d].sort(key=os.path.getmtime)
    return out


def board_of_record(date: str, bets_dir: str | None = None) -> str | None:
    """The newest board JSON for a date, or None."""
    paths = board_files(bets_dir).get(date)
    return paths[-1] if paths else None


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)
