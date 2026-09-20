"""Has anything moved under the board — probables, lineups, the slate?

    venv/bin/python -m scratchpad.check_updates [DATE]

Fetches the live slate and compares it against two things: the BOARD OF
RECORD for the date (`boards.py` — the newest board JSON, the same file
the server shows) and the LAST SNAPSHOT this checker took. The board
tells you the numbers on the page are stale; the snapshot tells you what
changed since the previous check, which is the line a cron wants.

What counts as drift, each one a re-run trigger from the standing rules:
  * a probable starter differing from the arm the board priced — two
    wrong names in a projected nine once cut the largest edge in half,
    and a wrong STARTER is worth far more than that;
  * lineups posted where the board carries projections — the footer of
    every board says re-run when this happens;
  * a posted lineup whose names changed since the last check;
  * games on the live slate the board never priced, or board games gone
    from the slate (postponements).

Exit status is the interface: 0 nothing moved, 1 drift (stdout says
what), 2 the check itself failed. A wrapper keys off the 1.

NOT SCHEDULED, deliberately — this repo schedules nothing (see CLAUDE.md
on the four dead launchd jobs). The deployment that runs it elsewhere
wants a line of this shape, every N minutes during the pre-game window:

    */15 * * * * cd /path/to/morning-bets && \
        venv/bin/python -m scratchpad.check_updates >> logs/watch.log 2>&1
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date as _date

from scratchpad import boards

STATE = os.path.join(boards.BETS_DIR, "lineup_watch.json")


def _live_by_tag(live: list[dict]) -> dict[str, dict]:
    out = {}
    for g in live:
        a, h = g.get("away") or {}, g.get("home") or {}
        out[f"{a.get('abbr')} @ {h.get('abbr')}"] = g
    return out


def diff_board(board: dict, live: list[dict]) -> list[str]:
    """Drift between the board of record and the live slate. Pure."""
    out = []
    by_tag = _live_by_tag(live)
    seen = set()
    for g in board.get("games") or []:
        tag = f"{g['away']} @ {g['home']}"
        seen.add(tag)
        lv = by_tag.get(tag)
        if lv is None:
            out.append(f"{tag}: on the board, gone from the slate "
                       "(postponed?)")
            continue
        for side, key in (("away", "ap"), ("home", "hp")):
            was, now = g.get(key), (lv[side] or {}).get("starter")
            if now and was and now != was:
                out.append(f"{tag}: {side} starter now {now}, "
                           f"board priced {was}")
        posted_now = all((lv[s] or {}).get("lineup") for s in
                        ("away", "home"))
        if posted_now and "posted" not in (g.get("lineups") or ""):
            out.append(f"{tag}: lineups posted, board is projected "
                       "— re-run")
    # Declined games are named on the board; only a matchup the board
    # never mentioned at all is news.
    declined = " ".join(board.get("declined") or [])
    for tag in by_tag:
        if tag not in seen and tag not in declined:
            out.append(f"{tag}: on the slate, not on the board")
    return out


def snapshot(live: list[dict]) -> dict:
    """What the next run compares against: starters and lineup names."""
    out = {}
    for tag, g in _live_by_tag(live).items():
        out[tag] = {s: {"starter": (g[s] or {}).get("starter"),
                        "lineup": (g[s] or {}).get("lineup") or []}
                    for s in ("away", "home")}
    return out


def diff_snapshot(prev: dict, cur: dict) -> list[str]:
    """What moved since the last check. Pure."""
    out = []
    for tag, now in cur.items():
        was = prev.get(tag)
        if was is None:
            continue  # first sighting is not a change
        for s in ("away", "home"):
            w, n = was.get(s) or {}, now[s]
            if w.get("starter") and n["starter"] \
                    and w["starter"] != n["starter"]:
                out.append(f"{tag}: {s} starter {w['starter']} -> "
                           f"{n['starter']}")
            if w.get("lineup") and n["lineup"] \
                    and w["lineup"] != n["lineup"]:
                out.append(f"{tag}: {s} lineup changed "
                           f"({_lineup_delta(w['lineup'], n['lineup'])})")
            elif not w.get("lineup") and n["lineup"]:
                out.append(f"{tag}: {s} lineup posted")
    return out


def _lineup_delta(old: list[str], new: list[str]) -> str:
    outs = [x for x in old if x not in new]
    ins = [x for x in new if x not in old]
    if outs or ins:
        return f"out: {', '.join(outs) or '-'}; in: {', '.join(ins) or '-'}"
    return "order only"


def main(argv):
    d = argv[0] if argv else _date.today().isoformat()
    from src.context import slate
    try:
        live = slate.slate(d)
    except Exception as e:
        print(f"slate fetch failed: {type(e).__name__} {e}")
        return 2

    lines = []
    path = boards.board_of_record(d)
    if path is None:
        lines.append(f"no board JSON for {d} — nothing to compare")
    else:
        lines += [f"[board {os.path.basename(path)}] {x}"
                  for x in diff_board(boards.load(path), live)]

    state = {}
    if os.path.exists(STATE):
        with open(STATE) as f:
            state = json.load(f)
    cur = snapshot(live)
    lines += [f"[since last check] {x}"
              for x in diff_snapshot(state.get(d) or {}, cur)]
    with open(STATE, "w") as f:
        json.dump({d: cur}, f, indent=1)  # one date; old days drop off

    if not lines:
        print(f"{d}: no changes")
        return 0
    for x in lines:
        print(x)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
