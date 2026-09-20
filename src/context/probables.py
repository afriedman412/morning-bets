"""Manually designated probable starters, for when the feed is behind us.

`slate.slate()` reads MLB's schedule live and takes `probablePitcher` as it
finds it. That field lands when the club posts it, which on 2026-09-11 was
after ten in the morning for three of fifteen games — and a game with no
probable is dropped by `board.build` before the DECLINED list is even
assembled, so the board printed "12 games" and said nothing about the other
three. The operator routinely knows a name hours before the API carries it.

This module is that side channel and nothing more. It is OPERATOR INPUT, not
a derived table, which is why it lives in a JSON file rather than in
`context.db` — the DB is rebuilt from the play-by-play cache and would wipe
it.

THREE RULES, each one guarding a way this could quietly go wrong:

  1. **THE API ALWAYS WINS.** An override fills a `None` and never replaces
     a name the feed already carries. A manual entry typed on Tuesday must
     not be able to re-write Wednesday's real probable after a rainout
     shuffles a rotation.
  2. **EVERY INJECTION IS ANNOUNCED.** `apply` returns a line per fill and
     the callers print it. The whole failure this was written for is a
     filter that ran silently; replacing it with an injection that runs
     silently would be no better.
  3. **A CONTRADICTED OVERRIDE IS REPORTED, NOT APPLIED.** If the feed comes
     back with a different name than the stored one, that is the operator's
     entry going stale, and it is worth saying out loud.

This does NOT relax BOTH STARTERS OR NEITHER. It supplies the missing name so
the pair is complete; a game still declines when one side is genuinely
unknown.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.context import atomic

#: Operator input, so it sits with the boards rather than in `context.db`.
PATH = Path(__file__).resolve().parents[2] / "bets" / "probables.json"

SIDES = ("away", "home")


def _key(away_abbr: str, home_abbr: str) -> str:
    return f"{away_abbr}@{home_abbr}"


def load(path: Path | None = None) -> dict:
    """The whole file: {date: {"AWY@HOM": {"away": name, "home": name}}}."""
    p = path or PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        # A hand-edited file is the expected case, so a typo here must not
        # take the board down — say so and price off the feed alone.
        print(f"  (probables: {p} is not valid JSON — ignoring)")
        return {}


def for_date(date_str: str, path: Path | None = None) -> dict:
    return load(path).get(date_str) or {}


def set_probable(date_str: str, away_abbr: str, home_abbr: str,
                 side: str, name: str, path: Path | None = None) -> None:
    """Record one manual probable. Overwrites a prior entry for that slot."""
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}, got {side!r}")
    p = path or PATH
    data = load(p)
    day = data.setdefault(date_str, {})
    day.setdefault(_key(away_abbr, home_abbr), {})[side] = name
    p.parent.mkdir(parents=True, exist_ok=True)
    # Through `atomic`, not `write_text`: a board reads this file while the
    # operator may be adding tonight's second name from another terminal,
    # and a half-written JSON reads as "no overrides" — which is silently
    # the pre-fix behaviour this module exists to end.
    atomic.write_text(p, json.dumps(data, indent=1, sort_keys=True) + "\n")


def apply(games: list[dict], date_str: str, path: Path | None = None
          ) -> list[str]:
    """Fill missing starters on slate rows in place. Returns a report line
    per fill and per contradiction — NEVER silent, see rule 2.

    `starter_id` is left None on an injected name. Nothing downstream reads
    it (the Kalshi mapping resolves ids from the name through `roster`), and
    guessing an id here would be a second thing that could be wrong.
    """
    day = for_date(date_str, path)
    if not day:
        return []
    notes = []
    for g in games:
        k = _key((g.get("away") or {}).get("abbr"),
                 (g.get("home") or {}).get("abbr"))
        want = day.get(k) or {}
        for side in SIDES:
            name = want.get(side)
            if not name:
                continue
            have = (g.get(side) or {}).get("starter")
            if have and have != name:
                notes.append(
                    f"  probables: {k} {side} — feed says {have!r}, "
                    f"manual entry says {name!r}; USING THE FEED")
                continue
            if have:
                continue
            g[side]["starter"] = name
            g[side]["starter_id"] = None
            notes.append(f"  probables: {k} {side} <- {name} (manual)")
    return notes


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print("usage:")
        print("  -m src.context.probables DATE                     # list")
        print("  -m src.context.probables DATE AWY@HOM SIDE NAME   # set")
        return 0
    date_str = argv[0]
    if len(argv) == 1:
        day = for_date(date_str)
        if not day:
            print(f"no manual probables for {date_str}  ({PATH})")
            return 0
        print(f"manual probables for {date_str}:")
        for k, v in sorted(day.items()):
            for side in SIDES:
                if v.get(side):
                    print(f"  {k:12s} {side:5s} {v[side]}")
        return 0
    if len(argv) < 4:
        print("need: DATE AWY@HOM SIDE NAME")
        return 1
    matchup, side, name = argv[1], argv[2], " ".join(argv[3:])
    if "@" not in matchup:
        print(f"matchup must look like TEX@AZ, got {matchup!r}")
        return 1
    away, home = matchup.split("@", 1)
    set_probable(date_str, away, home, side, name)
    print(f"set {date_str} {matchup} {side} = {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
