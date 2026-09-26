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

BETS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "bets")

BOARD_FILE = re.compile(r"^(\d{4})_(\d{2})_(\d{2})_board.*\.json$")



def prob(odds: str) -> float:
    """American odds -> implied probability, no vig removed.

    The board's one conversion. `board_json` parses every printed price
    through it and `rung` turns an operator's price into a breakeven with
    it, so the two can never disagree at even money.
    """
    o = float(odds)
    return -o / (-o + 100) if o < 0 else 100 / (o + 100)


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


#: The header stamp on a carried-forward block, and how to find it again.
#: "(FROZEN v5, game In Progress · lineups posted, mean 9.1)". `·` ends
#: the stamp because a status never contains one and `board_json.HEAD`
#: reads everything before ", mean" as the lineups field.
FROZEN = re.compile(r"FROZEN (v\d+), game [^·]* · ")


def version_of(path: str) -> str:
    """'..._board.json' -> 'v1', '..._board_v5.json' -> 'v5'."""
    m = _VERSIONED.search(os.path.basename(path))
    return f"v{m.group(1)}" if m else "v1"


def frozen_block(date: str, head: str, status: str,
                 bets_dir: str | None = None) -> list[str] | None:
    """A started game's block, copied from the newest pull that priced it.

    Operator decision 2026-09-26: once a game starts the board never
    prices it again (`gamestate`, never price a live one), and it used to
    drop into DECLINED — so every hourly pull after first pitch lost the
    number we had said about it. The last pregame block is the one worth
    keeping, and it is kept VERBATIM: its prices, its Kalshi mids and its
    notes are what the board said, not a re-derivation.

    `head` is "AWY @ HOM   Away SP v Home SP". Matching the starters as
    well as the clubs means a doubleheader cannot borrow the other game's
    block and a scratched starter's block is not passed off as the real
    game's. Newest pull first, reading the .txt of every pull whose JSON
    exists — a JSON is only written when the pull finished, so a crashed
    pull's half-written text is never the source. None when no pull ever
    priced it, and the caller declines as before.

    The stamp keeps the version the block was FIRST frozen from, so a
    game carried through six hourly pulls still says which pull priced
    it, while its status is refreshed ("In Progress" -> "Final").
    """
    for path in reversed(board_files(bets_dir).get(date, [])):
        txt = path[: -len(".json")] + ".txt"
        if not os.path.exists(txt):
            continue
        with open(txt) as f:
            lines = f.read().splitlines()
        for i, ln in enumerate(lines):
            if not ln.startswith(head + "   ("):
                continue
            block = [ln]
            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    break
                block.append(nxt)
            m = FROZEN.search(ln)
            ver = m.group(1) if m else version_of(path)
            bare = FROZEN.sub("", ln, count=1)
            block[0] = bare.replace(
                "   (", f"   (FROZEN {ver}, game {status} · ", 1)
            return block
    return None


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
