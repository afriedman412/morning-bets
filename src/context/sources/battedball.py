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


#: THE SAME SCAN, SPLIT FIVE WAYS — `mlb_traj`. `mlb_batted` collapses
#: every trajectory to ground-or-not because the double play and the hit
#: mix were all it was built for; the home run channel needs the other
#: side of that split, so this table carries the full breakdown plus the
#: home runs among those balls.
#:
#: WHY A SECOND TABLE AND NOT FOUR MORE COLUMNS ON THE FIRST. `gb` and
#: `bip` are counted here too, and `scratchpad/hr_traj.py --agree` checks
#: them row-for-row against `mlb_batted` — 283,972 rows, 0 disagreements.
#: Two independent counts of the same cache is the only correctness check
#: available for an extractor whose output nothing else can be compared
#: against, and widening the original table would have thrown it away.
#: Retiring `mlb_batted` into this one is a cleanup, not part of the item.
_TRAJ_SCHEMA = """
create table if not exists mlb_traj (
    game_id text, date text, name text, role text,
    gb integer, fb integer, ld integer, pu integer, hr integer,
    bip integer,
    primary key (game_id, name, role)
)
"""
#: trajectory -> column. Bunts travel with the shape they are, not with a
#: category of their own, which is the rule `GROUND` already follows.
#: `bunt_line_drive` is 75 balls in four seasons and was the entire
#: disagreement on the first build of this table.
TRAJ = {"ground_ball": "gb", "bunt_grounder": "gb", "fly_ball": "fb",
        "line_drive": "ld", "bunt_line_drive": "ld",
        "popup": "pu", "bunt_popup": "pu"}
TRAJ_COLS = ("gb", "fb", "ld", "pu", "hr", "bip")

#: AIR IS FLY BALLS PLUS LINE DRIVES — the two trajectories home runs
#: actually leave on. Counted on 400 sampled games (`hr_traj_probe`,
#: 2026-09-10): 91.3% of home runs are `fly_ball`, 8.7% `line_drive`,
#: none a popup, at 100% trajectory coverage. EXACTLY ONE ground ball in
#: four full seasons is a home run and it is not a data error — an
#: inside-the-park home run, launch angle 1 degree, 57 feet of total
#: distance (mlb-825099, 2026-04-21). One in ~11,500, pinned by
#: `check_the_two_batted_ball_tables_count_the_same_balls`.
AIR = ("fb", "ld")


def traj_game_rows(game_id: str, data: dict | None = None) -> dict:
    """{(name, role): {col: n}} for one game — `game_rows` split five ways.

    Deliberately a second walk of the same plays rather than a widened
    `game_rows`: see `_TRAJ_SCHEMA` on why the duplication is the check.
    """
    out: dict = defaultdict(lambda: dict.fromkeys(TRAJ_COLS, 0))
    for play, *_ in pbp.plays(game_id, data):
        ev = ((play.get("result") or {}).get("eventType") or "")
        if ev not in BIP_EV:
            continue
        hd = None
        for e in (play.get("playEvents") or []):
            if e.get("hitData"):
                hd = e["hitData"]
        col = TRAJ.get((hd or {}).get("trajectory"))
        if not col:
            continue                      # coverage miss, not a fly ball
        mu = play.get("matchup") or {}
        for who, role in (((mu.get("batter") or {}).get("fullName"), "bat"),
                          ((mu.get("pitcher") or {}).get("fullName"), "pit")):
            if not who:
                continue
            r = out[(who, role)]
            r[col] += 1
            r["bip"] += 1
            r["hr"] += ev == "home_run"
    return out


def _one_traj(args):
    gid, date = args
    try:
        return gid, date, {f"{n}|{r}": v
                           for (n, r), v in traj_game_rows(gid).items()}
    except Exception:
        return None


def sync_traj(verbose: bool = True) -> int:
    """Fill `mlb_traj` from every cached game it does not yet cover."""
    store.init()
    with store.connect() as c:
        c.execute(_TRAJ_SCHEMA)
        dates = {r["game_id"]: r["date"] for r in c.execute(
            f"select game_id, date from {store.BETS}.games "
            "where sport = 'mlb'")}
        have = {r[0] for r in c.execute(
            "select distinct game_id from mlb_traj")}
    todo = [(g, dates[g]) for g in
            (f"mlb-{f.name.split('.')[0]}" for f in pbp.CACHE.glob(
                "*.json.gz"))
            if g not in have and g in dates]
    if verbose:
        print(f"  {len(todo):,} games to scan for mlb_traj", flush=True)
    with mp.get_context("fork").Pool(8) as p:
        got = [g for g in p.map(_one_traj, todo, chunksize=16) if g]
    n = 0
    with store.connect(attach=False) as c:
        c.execute(_TRAJ_SCHEMA)
        for gid, date, rows in got:
            for key, v in rows.items():
                nm, role = key.rsplit("|", 1)
                c.execute(
                    "insert or replace into mlb_traj values (?,?,?,?," +
                    ",".join("?" * len(TRAJ_COLS)) + ")",
                    (gid, date, nm, role, *(v[k] for k in TRAJ_COLS)))
                n += 1
    if verbose:
        print(f"  wrote {n:,} player-game rows from {len(got):,} games")
    return n


def air_counts(role: str, season=None, before=None) -> dict:
    """{name: (air, bip)} under the same date scoping rates use."""
    where = ""
    if season:
        where += f" and date like '{season}%'"
    if before:
        where += f" and date < '{before}'"
    out = {}
    with store.connect(attach=False) as c:
        c.execute(_TRAJ_SCHEMA)
        for r in c.execute(
                "select name, sum(fb) + sum(ld) a, sum(bip) n "
                f"from mlb_traj where role = ? {where} group by name",
                (role,)):
            out[r["name"]] = (r["a"] or 0, r["n"] or 0)
    return out


#: SHRINKAGE for the air-ball share, measured the same way `GB_SHRINK`
#: was — odd/even games, Spearman-Brown, k = n(1-r)/r on the mean half
#: denominator (`scratchpad/hr_traj.py --stabilise`, 2026-09-10), over
#: players with at least 100 balls in play in each half:
#:
#:     rate         bat r_full  k          pit r_full  k
#:     hr_per_bip      0.856    140.7         0.416    943.7
#:     air_share       0.824    179.0         0.793    175.7
#:     hr_per_air      0.828     88.1         0.257    973.1
#:
#: THE PITCHER ROW IS THE FINDING and it is why `sim.AIR_HR_PIT` exists.
#: His home run OUTCOME barely repeats — and repeats even less once the
#: fly ball is granted — while his contact TYPE does, at five times the
#: reliability per ball in play. The batter is the exact opposite:
#: HR/BIP is the most reliable of his five rates, his own rate already
#: carries his power, and the counted batter-side table came back a null
#: with a +0.14 era gate. One measurement predicted both.
AIR_SHRINK = {"bat": 179.0, "pit": 175.7}

_AIR_MAPS: dict = {}


def air_pct_map(role: str, season=None, before=None) -> dict:
    """{name: shrunk air-ball share}, memoised per scope.

    Shrunk toward the LEAGUE mean of the same scope, exactly as
    `gb_pct_map` does it — and it must be built at the same `before=` cut
    the engine scores at, because the table it feeds was counted on a
    covariate frozen strictly before the rows it bins.
    """
    key = (role, season, before)
    if key in _AIR_MAPS:
        return _AIR_MAPS[key]
    counts = air_counts(role, season, before)
    tot_a = sum(a for a, _ in counts.values())
    tot_n = sum(n for _, n in counts.values())
    if not tot_n:
        _AIR_MAPS[key] = {}
        return {}
    lg = tot_a / tot_n
    k = AIR_SHRINK[role]
    _AIR_MAPS[key] = {nm: (a + k * lg) / (n + k)
                      for nm, (a, n) in counts.items() if n > 0}
    return _AIR_MAPS[key]


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
        sync_traj()
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
