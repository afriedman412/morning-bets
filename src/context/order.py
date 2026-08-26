"""The REAL batting order, counted from play-by-play.

WHAT WAS THERE BEFORE. `calibrate.opposing_lineups` had no batting-order
column to work with — the boxscore cache carries at-bats and nothing else —
so it sorted each club's hitters by AB descending and called the top nine a
lineup. Measured against play-by-play over 574 lineups:

    exact match (right nine, right order)      0.0%
    lineups with at least one wrong batter    23.5%
    mean slot error                            2.30

NOT ONE LINEUP IN 574 WAS RIGHT. Three separate defects were stacked in
there and they fail differently:

  * MEMBERSHIP. A pinch hitter with two at-bats displaces a starter who was
    pulled early, in 23.5% of lineups.
  * ORDER. At-bats EXCLUDE walks, so a high-OBP leadoff man sorts below a
    free swinger, and ties break on whatever SQLite happens to return.
  * CONTAMINATION. A club that bats around hands its leadoff man five
    at-bats, so both membership and order are partly a function of how the
    game turned out — leakage into an input the model treats as known
    beforehand.

WHY THE ORDER IS NOT COSMETIC. The simulator wraps the lineup and derives
times through the order from batters faced, and TTO is a MEASURED 19% swing
in strikeout rate between the first pass and the third. A mean slot error of
2.3 assigns that penalty to roughly the wrong third of the lineup.

Recovering it needs no new scrape: the first nine distinct batters in a
half-inning ARE that club's order, and 2,006 games of play-by-play have been
on disk since day four.

    venv/bin/python -m src.context.order [--build] [--check]
"""
from __future__ import annotations

import sys

from src.context import store
from src.context.sources import pbp


def from_pbp(game_id: str, data: dict | None = None) -> dict:
    """{'top': [...nine...], 'bottom': [...]} in true batting order.

    Keyed by half rather than by club because that is what the play-by-play
    states directly: the top half is the AWAY club batting. Resolving that
    to a team abbreviation needs the schedule and is done by the caller, so
    a mis-joined game cannot silently swap two lineups here.
    """
    out: dict = {"top": [], "bottom": []}
    seen: dict = {"top": set(), "bottom": set()}
    for play, *_ in pbp.plays(game_id, data=data):
        half = (play.get("about") or {}).get("halfInning")
        if half not in out or len(out[half]) >= 9:
            continue
        m = (play.get("matchup") or {})
        b = m.get("batter") or {}
        nm = b.get("fullName")
        if not nm or nm in seen[half]:
            continue
        seen[half].add(nm)
        out[half].append({
            "name": nm, "id": b.get("id"),
            # real handedness for THIS plate appearance, which is the thing
            # the derived season splits were only ever approximating
            "bat_side": ((m.get("batSide") or {}).get("code")),
        })
    return out


def sync(verbose: bool = True) -> int:
    """Flatten every cached game into `mlb_lineups`. Derived, rebuildable."""
    store.init()
    with store.connect() as c:
        teams = {r["game_id"]: (r["date"], r["away_team_abbr"],
                                r["home_team_abbr"])
                 for r in c.execute(
                     "select game_id, date, away_team_abbr, home_team_abbr "
                     f"from {store.BETS}.games where sport = 'mlb'")}
        have = {r[0] for r in c.execute(
            "select distinct game_id from mlb_lineups")}
    todo = [f"mlb-{f.name.split('.')[0]}" for f in pbp.CACHE.glob("*.json.gz")]
    # A game whose schedule row is missing a club abbreviation cannot be
    # attributed to a side at all, and a lineup with no team is worse than
    # no lineup — it would join to nothing and read as missing data anyway.
    todo = [g for g in todo if g not in have and g in teams
            and teams[g][1] and teams[g][2]]
    n = 0
    with store.connect(attach=False) as c:
        for i, gid in enumerate(todo):
            date, away, home = teams[gid]
            got = from_pbp(gid)
            for half, team, side in (("top", away, "away"),
                                     ("bottom", home, "home")):
                nine = got.get(half) or []
                # A short lineup means the extraction failed, not that a
                # club batted eight men. Writing it would look like data.
                if len(nine) < 9:
                    continue
                for slot, b in enumerate(nine, start=1):
                    c.execute(
                        "insert or replace into mlb_lineups values "
                        "(?,?,?,?,?,?,?,?)",
                        (gid, date, team, side, slot, b["name"], b["id"],
                         b["bat_side"]))
                    n += 1
            if verbose and (i + 1) % 400 == 0:
                print(f"  {i + 1}/{len(todo)}", flush=True)
    if verbose:
        print(f"synced {n} lineup slots from {len(todo)} games")
    return n


def lineups() -> dict:
    """{(game_id, pitching_team): [the nine he FACES, in batting order]}.

    Same shape and same key as `calibrate.opposing_lineups`, so it is a
    drop-in — and deliberately the OPPOSING nine, because that is what a
    pitching side needs and the alternative is the crossing bug that had
    every starter facing his own teammates.
    """
    rows: dict = {}
    with store.connect(attach=False) as c:
        for r in c.execute("select game_id, team, slot, player_name "
                           "from mlb_lineups order by game_id, team, slot"):
            rows.setdefault((r["game_id"], r["team"]), []).append(
                r["player_name"])
    by_game: dict = {}
    for (gid, team), names in rows.items():
        by_game.setdefault(gid, []).append((team, names))
    out = {}
    for gid, sides in by_game.items():
        if len(sides) != 2:
            continue
        (t1, n1), (t2, n2) = sides
        out[(gid, t1)] = n2
        out[(gid, t2)] = n1
    return out


def coverage() -> None:
    with store.connect() as c:
        g = c.execute(f"select count(*) n from {store.BETS}.games "
                      "where sport='mlb' and status='Final'").fetchone()["n"]
        have = c.execute("select count(distinct game_id) n "
                         "from mlb_lineups").fetchone()["n"]
        slots = c.execute("select count(*) n from mlb_lineups").fetchone()["n"]
    print(f"  {have} games with a real order of {g} final "
          f"({have / g if g else 0:.1%}), {slots} slots")
    lu = lineups()
    print(f"  {len(lu)} (game, pitching team) keys available")


def main() -> None:
    if "--build" in sys.argv:
        sync()
    coverage()


if __name__ == "__main__":
    main()
