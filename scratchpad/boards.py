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


#: `_board`, then `_board_v2`, `_board_v3`, ... A pull never overwrites the
#: one before it: the morning number IS the comparison, and on 2026-09-10
#: it was the whole answer — our F5 moved 0.4 points on the real nines
#: while Kalshi moved 3.4. That is only visible if both survive.
#: ANY EXTENSION, NOT JUST .json. A pull writes .txt first and the JSON
#: only if every step succeeds, so counting versions off .json alone made
#: a FAILED run invisible to the next one: 2026-09-21 fired five times,
#: died at the board step each time, and handed back `_v2` four runs
#: running — each overwriting the last one's text. The test that was
#: supposed to guard this only ever created .json files and sailed past
#: it, which is why the rule is now "any file that claims this stem".
_VERSIONED = re.compile(r"_board_v(\d+)\.")


def next_stem(date: str, bets_dir: str | None = None) -> str:
    """Path stem for the next pull of `date`, with NO extension.

    'bets/2026_09_20_board' when nothing exists yet, then '..._board_v2',
    '..._board_v3'. Returned as a stem because the three steps of the
    board each want it with a different suffix (.txt, .json, .html) and
    passing three hand-typed paths is how they end up disagreeing.

    Numbering is off the HIGHEST existing version, not off the count, so
    a deleted middle version can never hand back a name already taken.
    """
    d = bets_dir or BETS_DIR
    base = date.replace("-", "_")
    have = [f for f in os.listdir(d) if f.startswith(f"{base}_board")]
    if not any(f == f"{base}_board.json" or f.startswith(f"{base}_board.")
               for f in have):
        return os.path.normpath(os.path.join(d, f"{base}_board"))
    seen = [int(m.group(1)) for f in have if (m := _VERSIONED.search(f))]
    return os.path.normpath(
        os.path.join(d, f"{base}_board_v{max(seen, default=1) + 1}"))


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


if __name__ == "__main__":
    import sys
    # `--next DATE` prints the stem for the next pull. It is a CLI because
    # the board skill needs the same answer in three commands, and a stem
    # typed by hand three times is a stem that disagrees with itself.
    if "--next" in sys.argv:
        print(next_stem(sys.argv[sys.argv.index("--next") + 1]))
    else:
        for d, paths in sorted(board_files().items()):
            print(f"{d}  {len(paths)}  {os.path.basename(paths[-1])}")
