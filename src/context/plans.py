"""Operator-announced pitching plans: openers, short starts, bulk arms.

The engine has modelled opener games since 2026-09-09 — `game.build_side`
takes a named bulk arm, `Side.to_bulk` hands him the ball, and the exit
comes off `forced_exit_outs` — but every input to that machinery is
HISTORICAL: `game.opener_record` classifies an arm by his past starts and
`game.bulk_follower` names the bulk man from past pairings. A club
announcing "Burns goes three and Williamson has the bulk" the morning of
is invisible to all of it, so the live path simulated Burns as a full
starter on 2026-09-18 while $24k of Kalshi volume priced the short start
correctly.

This module is the side channel for that announcement, built to the same
three rules as `probables` (operator input in a JSON file the DB rebuild
cannot wipe; every injection announced; the API's ground truth never
overridden — though here there is no API field to defer to, so the plan
simply expires with its date). A plan names:

  * the TEAM and DATE it applies to,
  * the planned exit — an outs count ("pitching 3 innings" is 9), a
    range like `3-6` ("an inning or two", drawn from the counted opener
    curve clipped to those bounds, so the mass stays at the inning
    boundaries the way real opener exits land), or `pool` for the full
    counted first-time-opener curve when only "he is opening" is known,
  * optionally the BULK ARM. No bulk name means the pen takes over
    normally, which is the majority case for real openers (48.5%).

The plan applies to WHOEVER STARTS for that team that day, which is
deliberate: the operator's sentence is about the club's plan for the
game, and naming the arm twice is a second thing that can go stale.

usage:
  -m src.context.plans DATE                        # list
  -m src.context.plans DATE TEAM OUTS [BULK NAME]  # OUTS: int, lo-hi, pool
  -m src.context.plans DATE TEAM off               # clear
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.context import atomic

#: Operator input, so it sits with the boards rather than in `context.db` —
#: same placement decision as `probables.PATH`.
PATH = Path(__file__).resolve().parents[2] / "bets" / "plans.json"

#: The planned-exit sentinel for "he is opening, length unannounced".
POOL = "pool"


def parse_outs(outs) -> int | str:
    """Validate a planned exit: an int, `pool`, or a `lo-hi` range.

    Raises ValueError on anything else, so a typo fails at the terminal
    where the operator can fix it, never mid-simulation on the board.
    """
    if outs == POOL:
        return outs
    s = str(outs)
    if "-" in s:
        lo, hi = (int(x) for x in s.split("-", 1))
        if not 0 < lo <= hi:
            raise ValueError(f"bad outs range {s!r}")
        return s
    return int(s)


def load(path: Path | None = None) -> dict:
    """The whole file: {date: {TEAM: {"outs": int|"pool", "bulk": name|None}}}."""
    p = path or PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        # Same posture as `probables.load`: a hand-edited typo must not
        # take the board down — say so and price with no plans.
        print(f"  (plans: {p} is not valid JSON — ignoring)")
        return {}


def for_date(date_str: str, path: Path | None = None) -> dict:
    """{TEAM: {"outs": ..., "bulk": ...}} for one date, teams uppercased."""
    day = load(path).get(date_str) or {}
    return {k.upper(): v for k, v in day.items()}


def for_team(date_str: str, team_abbr: str | None,
             path: Path | None = None) -> dict | None:
    """The one club's plan for the date, or None."""
    if not team_abbr:
        return None
    return for_date(date_str, path).get(team_abbr.upper())


def set_plan(date_str: str, team_abbr: str, outs: int | str,
             bulk: str | None = None, path: Path | None = None) -> None:
    """Record one club's plan. Overwrites a prior entry for that club."""
    outs = parse_outs(outs)  # fail loudly at entry, not mid-simulation
    p = path or PATH
    data = load(p)
    data.setdefault(date_str, {})[team_abbr.upper()] = {
        "outs": outs, "bulk": bulk}
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_text(p, json.dumps(data, indent=1, sort_keys=True) + "\n")


def clear_plan(date_str: str, team_abbr: str,
               path: Path | None = None) -> bool:
    """Remove one club's plan. Returns whether one existed."""
    p = path or PATH
    data = load(p)
    day = data.get(date_str) or {}
    had = day.pop(team_abbr.upper(), None) is not None
    if not day:
        data.pop(date_str, None)
    atomic.write_text(p, json.dumps(data, indent=1, sort_keys=True) + "\n")
    return had


def describe(plan: dict) -> str:
    """One announcement line, for the board note and the list command."""
    outs = plan.get("outs")
    exit_txt = ("pooled opener exit" if outs == POOL
                else f"planned {outs} outs")  # ints and ranges read alike
    bulk = plan.get("bulk")
    return exit_txt + (f", {bulk} in bulk" if bulk else ", pen behind him")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    date_str = argv[0]
    if len(argv) == 1:
        day = for_date(date_str)
        if not day:
            print(f"no plans for {date_str}  ({PATH})")
            return 0
        print(f"plans for {date_str}:")
        for team, plan in sorted(day.items()):
            print(f"  {team:5s} {describe(plan)}")
        return 0
    if len(argv) < 3:
        print("need: DATE TEAM OUTS [BULK NAME]  or  DATE TEAM off")
        return 1
    team = argv[1]
    if argv[2] == "off":
        had = clear_plan(date_str, team)
        print(f"cleared {date_str} {team.upper()}" if had
              else f"no plan stored for {date_str} {team.upper()}")
        return 0
    outs = argv[2]
    try:
        parse_outs(outs)
    except ValueError:
        print(f"OUTS must be an integer, a range like 3-6, or {POOL!r} "
              f"— got {outs!r}")
        return 1
    bulk = " ".join(argv[3:]) or None
    set_plan(date_str, team, outs, bulk)
    plan = for_team(date_str, team)
    print(f"set {date_str} {team.upper()}: {describe(plan)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
