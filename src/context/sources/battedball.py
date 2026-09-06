"""Batted-ball trajectory, COUNTED from the play-by-play cache.

    venv/bin/python -m src.context.sources.battedball [--build]

WHY COUNTED AND NOT FETCHED. Savant serves GB% season-to-date only, so a
2023 fold scored against today's table would read an input that knows the
future — the same anachronism the park index had before it was pinned per
year. The cache already carries `hitData.trajectory` on essentially every
ball in play, so ground-ball share is countable per player per GAME, and a
`before=` cut then means exactly what it means everywhere else in this
project.

WHAT ONE ROW IS. (game_id, date, name, role, gb, bip): one player's
batted balls in one game, from one side of the ball — `role` is 'bat' or
'pit', and the same ball in play writes one row-increment to each. `bip`
counts only KNOWN-trajectory balls in play; a play with no `hitData` is a
coverage miss, not a fly ball. `gb` is `ground_ball` + `bunt_grounder`.

DERIVED AND REBUILDABLE, like `mlb_lineups` and `mlb_stints`: the pbp
cache is the authority and `--build` reconstructs this table from it.
"""
from __future__ import annotations

import multiprocessing as mp
import sys
from collections import defaultdict

from src.context import store
from src.context.sources import pbp

#: PA-ending events that put a ball in play. Strikeouts and walks cannot
#: carry a trajectory; sacrifices and errors do.
BIP_EV = {"single", "double", "triple", "home_run", "field_out",
          "force_out", "grounded_into_double_play", "double_play",
          "triple_play", "fielders_choice", "fielders_choice_out",
          "field_error", "sac_fly", "sac_bunt", "sac_fly_double_play",
          "sac_bunt_double_play", "other_out"}
GROUND = {"ground_ball", "bunt_grounder"}

_SCHEMA = """
create table if not exists mlb_batted (
    game_id text, date text, name text, role text,
    gb integer, bip integer,
    primary key (game_id, name, role)
)
"""


def game_rows(game_id: str, data: dict | None = None) -> dict:
    """{(name, role): [gb, bip]} for one game.

    The trajectory lives on the LAST play event carrying `hitData` — the
    in-play pitch is the final event of its plate appearance, so earlier
    `hitData` entries (foul balls track too) never win.
    """
    out: dict = defaultdict(lambda: [0, 0])
    for play, *_ in pbp.plays(game_id, data):
        ev = ((play.get("result") or {}).get("eventType") or "")
        if ev not in BIP_EV:
            continue
        hd = None
        for e in (play.get("playEvents") or []):
            if e.get("hitData"):
                hd = e["hitData"]
        traj = (hd or {}).get("trajectory")
        if not traj:
            continue                      # coverage miss, not a fly ball
        mu = play.get("matchup") or {}
        for who, role in (((mu.get("batter") or {}).get("fullName"), "bat"),
                          ((mu.get("pitcher") or {}).get("fullName"), "pit")):
            if who:
                out[(who, role)][0] += traj in GROUND
                out[(who, role)][1] += 1
    return out


def _one(args):
    gid, date = args
    try:
        return gid, date, {f"{n}|{r}": v
                           for (n, r), v in game_rows(gid).items()}
    except Exception:
        return None


def sync(verbose: bool = True) -> int:
    """Fill the table from every cached game it does not yet cover."""
    store.init()
    with store.connect() as c:
        c.execute(_SCHEMA)
        dates = {r["game_id"]: r["date"] for r in c.execute(
            f"select game_id, date from {store.BETS}.games "
            "where sport = 'mlb'")}
        have = {r[0] for r in c.execute(
            "select distinct game_id from mlb_batted")}
    todo = [(g, dates[g]) for g in
            (f"mlb-{f.name.split('.')[0]}" for f in pbp.CACHE.glob(
                "*.json.gz"))
            if g not in have and g in dates]
    if verbose:
        print(f"  {len(todo):,} games to scan", flush=True)
    with mp.get_context("fork").Pool(8) as p:
        got = [g for g in p.map(_one, todo, chunksize=16) if g]
    n = 0
    with store.connect(attach=False) as c:
        c.execute(_SCHEMA)
        for gid, date, rows in got:
            for key, (gb, bip) in rows.items():
                nm, role = key.rsplit("|", 1)
                c.execute("insert or replace into mlb_batted values "
                          "(?,?,?,?,?,?)", (gid, date, nm, role, gb, bip))
                n += 1
    if verbose:
        print(f"  wrote {n:,} player-game rows from {len(got):,} games")
    return n


def gb_counts(role: str, season=None, before=None) -> dict:
    """{name: (gb, bip)} under the same date scoping rates use."""
    where = ""
    if season:
        where += f" and date like '{season}%'"
    if before:
        where += f" and date < '{before}'"
    out = {}
    with store.connect(attach=False) as c:
        c.execute(_SCHEMA)
        for r in c.execute(
                "select name, sum(gb) g, sum(bip) n from mlb_batted "
                f"where role = ? {where} group by name", (role,)):
            out[r["name"]] = (r["g"] or 0, r["n"] or 0)
    return out


#: SHRINKAGE, measured by `stabilise.py`'s method (odd/even games,
#: Spearman-Brown, k = n(1-r)/r) on the four-season table —
#: `scratchpad/gb_stabilise.py`, 2026-09-06:
#:
#:     bat   861 players   r_half 0.568   r_full 0.725   k = 111.9
#:     pit 1,093 players   r_half 0.600   r_full 0.750   k =  76.8
#:
#: The pitcher constant is FORTY TIMES smaller than his BABIP's 3,068 —
#: which is the whole reason item 4 exists: contact TYPE is a stable
#: per-player trait in a way contact OUTCOME is not, and the model has
#: been reading only the outcome.
GB_SHRINK = {"bat": 111.9, "pit": 76.8}

_MAPS: dict = {}


def gb_pct_map(role: str, season=None, before=None) -> dict:
    """{name: shrunk ground-ball share}, memoised per scope.

    Shrunk toward the LEAGUE mean of the same scope — a player with three
    balls in play is mostly the league until he is not, the same rule
    every rate in `sources/rates.py` follows.
    """
    key = (role, season, before)
    if key in _MAPS:
        return _MAPS[key]
    counts = gb_counts(role, season, before)
    tot_g = sum(g for g, _ in counts.values())
    tot_n = sum(n for _, n in counts.values())
    if not tot_n:
        _MAPS[key] = {}
        return {}
    lg = tot_g / tot_n
    k = GB_SHRINK[role]
    _MAPS[key] = {nm: (g + k * lg) / (n + k)
                  for nm, (g, n) in counts.items() if n > 0}
    return _MAPS[key]


def main(argv):
    if "--build" in argv:
        sync()
    for role in ("bat", "pit"):
        counts = gb_counts(role)
        tot_g = sum(g for g, _ in counts.values())
        tot_n = sum(n for _, n in counts.values())
        print(f"\n  {role}: {len(counts):,} players, {tot_n:,} balls in "
              f"play, league GB {tot_g / tot_n if tot_n else 0:.4f}")
        big = sorted(((g / n, nm, n) for nm, (g, n) in counts.items()
                      if n >= 300), reverse=True)
        for r, nm, n in big[:3] + big[-3:]:
            print(f"    {nm:<24}{r:.3f}  ({n:,} bip)")


if __name__ == "__main__":
    main(sys.argv[1:])
