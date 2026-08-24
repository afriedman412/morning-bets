"""Whole-game play-by-play: the state the boxscore cannot give.

WHY THIS EXISTS. `sim.py` says outright that a boxscore "cannot give the
state at removal, only the totals," and names play-by-play as the thing that
would buy it. Everything the removal hook and the bullpen model are missing
is a per-play fact: what the score was when the manager went to the pen, how
many outs there were, whether men were on, which arm came in and how long he
stayed.

WHAT IT UNLOCKS, in the order the measurements want it:

  * DEPLOYMENT — entry inning, entry margin, entry base-out state, and outs
    recorded per outing. `game.build_side` currently uses eight sampled arms
    in sample order, one inning each, regardless of the score. Only 52.6% of
    real relief outings are a clean inning; the mean is 3.51 outs.
  * STATE AT REMOVAL — the hook's documented blind spot.
  * ADVANCEMENT MEASURED ON THIS LEAGUE rather than imported from published
    references. That mechanism moved runs-per-baserunner from -4.2% to
    -0.2% on published numbers alone.

FETCH ONCE, STORE WHOLE, EXTRACT LATER. An earlier plan here was to keep
only pitcher-change events to save space. That is a false economy on both
axes: the API call is identical either way, and re-scraping to recover a
field we discarded costs far more than disk. 92 KB gzipped a game, ~185 MB
for the season, about a minute over eight workers.

TWO SIDES, TRACKED SEPARATELY. The naive extractor keeps one `seen` pitcher
and emits a change every half-inning, because the pitcher legitimately
alternates. Which team is pitching is `about.isTopInning`: top of the inning
means the AWAY team bats and the HOME team pitches.
"""
from __future__ import annotations

import gzip
import json
import pathlib
import statistics as st
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from src import db
from src.context import store
from src.grading import USER_AGENT

CACHE = pathlib.Path(".cache/pbp")

#: A base a runner can stand on. `end` is also 'score', and null for an out.
_BASES = ("1B", "2B", "3B")


def path(game_id: str) -> pathlib.Path:
    return CACHE / f"{game_id.removeprefix('mlb-')}.json.gz"


def fetch(game_id: str, force: bool = False) -> dict | None:
    """One game's play-by-play, from disk when we already have it.

    Cached unconditionally: unlike a market snapshot, a final game's
    play-by-play is a settled historical record and cannot change.
    """
    p = path(game_id)
    if p.exists() and not force:
        try:
            with gzip.open(p, "rb") as f:
                return json.loads(f.read())
        except (OSError, ValueError):
            pass                      # truncated write — refetch below
    pk = game_id.removeprefix("mlb-")
    url = f"https://statsapi.mlb.com/api/v1/game/{pk}/playByPlay"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    raw = None
    for _ in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
            break
        except (urllib.error.URLError, OSError):
            continue
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not data.get("allPlays"):
        return None                   # never cache an empty game
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with gzip.open(tmp, "wb") as f:
        f.write(raw)
    tmp.replace(p)                    # atomic: a killed scrape leaves no
    return data                       # half-written file to be read back


def have(game_id: str) -> bool:
    return path(game_id).exists()


def final_games(before: str | None = None) -> list[str]:
    q = ("select game_id from games where sport = 'mlb' "
         "and status = 'Final'")
    args: tuple = ()
    if before:
        q += " and date < ?"
        args = (before,)
    with db.connect() as c:
        return [r["game_id"] for r in c.execute(q + " order by date desc",
                                                args)]


def backfill(limit: int | None = None, workers: int = 8,
             verbose: bool = True) -> dict:
    todo = [g for g in final_games() if not have(g)]
    if limit:
        todo = todo[:limit]
    if verbose:
        print(f"{len(todo)} games need play-by-play", flush=True)
    done = failed = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for got in ex.map(fetch, todo):
            done += 1
            failed += got is None
            if verbose and done % 200 == 0:
                print(f"  {done}/{len(todo)}", flush=True)
    if verbose:
        mb = sum(f.stat().st_size for f in CACHE.glob("*.json.gz")) / 1e6
        print(f"done: {done} fetched, {failed} failed, cache {mb:.0f} MB")
    return {"fetched": done, "failed": failed}


# ---------------------------------------------------------------- extraction

@dataclass
class Stint:
    """One pitcher's continuous appearance, and the state he walked into."""
    game_id: str
    side: str                 # the team PITCHING: 'away' or 'home'
    pitcher_id: int
    name: str
    order: int                # 0 = starter, 1 = first arm out of the pen
    inning: int               # entry inning
    outs: int                 # outs in that half-inning when he entered
    bases: tuple              # (on1B, on2B, on3B) when he entered
    margin: int               # his team's lead at entry (negative = behind)
    batters: int = 0
    outs_recorded: int = 0
    runs: int = 0             # runs scoring during his stint, charged or not
    last_inning: int = 0
    plays: list = field(default_factory=list)

    @property
    def relief(self) -> bool:
        return self.order > 0

    @property
    def mid_inning_entry(self) -> bool:
        return self.outs > 0 or any(self.bases)

    @property
    def innings(self) -> int:
        return self.last_inning - self.inning + 1


def resolve(runners) -> tuple[dict, list]:
    """({runner_id: [start, end, is_out]}, ids in listed order).

    A runner can appear twice — advance, then thrown out trying for another
    base — so the LAST record that resolves him is the one that counts.
    Shared by the base-state reconstruction and by the advancement
    measurement, which must agree on what "where did he end up" means.
    """
    final: dict = {}
    order: list = []
    for r in runners:
        mv = r.get("movement") or {}
        rid = ((r.get("details") or {}).get("runner") or {}).get("id")
        if rid not in final:
            order.append(rid)
            final[rid] = [mv.get("start") or mv.get("originBase"),
                          mv.get("end"), bool(mv.get("isOut"))]
        elif mv.get("end") is not None or mv.get("isOut"):
            final[rid][1:] = [mv.get("end"), bool(mv.get("isOut"))]
    return final, order


def _apply(runners, bases: list) -> int:
    """Move the runners for one play, in place. Returns runs scored.

    VACATE EVERY MOVER FIRST, THEN PLACE THEM. Applying each record in
    sequence looks natural and is wrong: the batter's record is listed
    first, so on a double that scores a man from second, the batter takes
    second and the scoring runner's own record then CLEARS second on the way
    out. The bases silently lose a runner, and only a walk two batters later
    reveals it as a missing bases-loaded state.

    A runner can also appear twice — advance, then thrown out trying for
    another base — so the last record that resolves him is the one that
    counts.
    """
    final, order = resolve(runners)
    for rid in order:
        start = final[rid][0]
        if start in _BASES:
            bases[_BASES.index(start)] = False
    runs = 0
    for rid in order:
        _, end, is_out = final[rid]
        if is_out:
            continue
        if end == "score":
            runs += 1
        elif end in _BASES:
            bases[_BASES.index(end)] = True
    return runs


def plays(game_id: str, data: dict | None = None):
    """Yield (play, bases_before, outs_before, away_before, home_before).

    THE STATE IS THE PRODUCT, not the play. Everything this scrape was for
    — deployment, removal, advancement — is a conditional rate keyed on the
    situation a play started from, and statsapi reports only what the
    situation became. Reconstructing it once here means the deployment
    measurement and the advancement measurement cannot disagree about what
    "bases loaded, one out" meant.
    """
    data = data if data is not None else fetch(game_id)
    if not data:
        return
    bases = [False, False, False]
    outs = 0
    half = None
    away = home = 0
    for play in data.get("allPlays") or []:
        ab = play.get("about") or {}
        key = (ab.get("inning"), ab.get("halfInning"))
        if key != half:
            half, bases, outs = key, [False, False, False], 0
        yield play, tuple(bases), outs, away, home
        after = (play.get("count") or {}).get("outs")
        _apply(play.get("runners") or [], bases)
        if after is not None:
            outs = after
        res = play.get("result") or {}
        if res.get("awayScore") is not None:
            away, home = res["awayScore"], res["homeScore"]


def stints(game_id: str, data: dict | None = None) -> list[Stint]:
    """Every pitcher's outing, with the base-out-score state at entry.

    Both sides are tracked separately — see the module docstring — and the
    entry state is read from immediately BEFORE the new pitcher's first
    play, which makes an inning-start entry and a mid-inning entry the same
    piece of code rather than two.
    """
    out: list[Stint] = []
    current: dict = {}
    count: dict = defaultdict(int)
    for play, bases, outs, away, home in plays(game_id, data):
        ab = play.get("about") or {}
        mu = play.get("matchup") or {}
        p = mu.get("pitcher") or {}
        if not p.get("id"):
            continue
        side = "home" if ab.get("isTopInning") else "away"
        if current.get(side) != p["id"]:
            count[side] += 1
            current[side] = p["id"]
            # `away`/`home` are the score BEFORE this play. `result` carries
            # the score AFTER it, so reading entry margin from `result`
            # would credit a reliever's first-batter homer to the manager's
            # decision to bring him in.
            out.append(Stint(
                game_id=game_id, side=side, pitcher_id=p["id"],
                name=p.get("fullName") or "", order=count[side] - 1,
                inning=ab.get("inning") or 0, outs=outs,
                bases=tuple(bases),
                margin=(home - away) if side == "home" else (away - home),
                last_inning=ab.get("inning") or 0))
        s = out[-1] if out[-1].side == side else next(
            x for x in reversed(out) if x.side == side)
        s.batters += 1
        s.last_inning = ab.get("inning") or s.last_inning
        after = (play.get("count") or {}).get("outs")
        if after is not None:
            s.outs_recorded += max(after - outs, 0)
        # The bases are already the pre-play state from `plays`, so runs on
        # this play are counted against a throwaway copy rather than the
        # generator's own, which owns the state.
        s.runs += _apply(play.get("runners") or [], list(bases))
    return out


def sync(verbose: bool = True) -> int:
    """Flatten every cached game into `mlb_stints`, in `context.db`.

    The extraction is 12ms a game, which is nothing once and a great deal
    when every deployment measurement re-reads 2,000 gzipped payloads. The
    table is DERIVED — rebuildable from the gzip cache in about thirty
    seconds — which is exactly why it lives in the context layer's own
    database rather than in the pipeline's un-versioned one.
    """
    store.init()
    with store.connect() as c:
        teams = {r["game_id"]: (r["date"], r["away_team_abbr"],
                                r["home_team_abbr"])
                 for r in c.execute(
                     "select game_id, date, away_team_abbr, home_team_abbr "
                     f"from {store.BETS}.games where sport = 'mlb'")}
        have = {r[0] for r in c.execute("select distinct game_id "
                                        "from mlb_stints")}
    todo = [f"mlb-{f.name.split('.')[0]}" for f in CACHE.glob("*.json.gz")]
    todo = [g for g in todo if g not in have and g in teams]
    n = 0
    with store.connect(attach=False) as c:
        for i, gid in enumerate(todo):
            date, away, home = teams[gid]
            for s in stints(gid):
                c.execute(
                    "insert or replace into mlb_stints values "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (s.game_id, date, home if s.side == "home" else away,
                     s.side, s.pitcher_id, s.name, s.order, s.inning, s.outs,
                     int(s.bases[0]), int(s.bases[1]), int(s.bases[2]),
                     s.margin, s.batters, s.outs_recorded, s.runs,
                     s.last_inning))
                n += 1
            if verbose and (i + 1) % 400 == 0:
                print(f"  {i + 1}/{len(todo)}", flush=True)
    if verbose:
        print(f"synced {n} stints from {len(todo)} games")
    return n


def men_on(bases: tuple) -> str:
    """The category statsapi reports, so reconstruction can be checked."""
    if all(bases):
        return "Loaded"
    if bases[1] or bases[2]:
        return "RISP"
    return "Men_On" if any(bases) else "Empty"


if __name__ == "__main__":
    if "--backfill" in sys.argv:
        n = None
        for a in sys.argv:
            if a.startswith("--limit="):
                n = int(a.split("=")[1])
        backfill(limit=n)
    if "--sync" in sys.argv:
        sync()

    cached = sorted(CACHE.glob("*.json.gz"))
    if not cached:
        print("no play-by-play cached — run with --backfill")
        sys.exit(0)
    mb = sum(f.stat().st_size for f in cached) / 1e6
    print(f"\n{len(cached)} games cached, {mb:.0f} MB gzipped")

    rows: list[Stint] = []
    for f in cached[-400:]:
        rows += stints(f"mlb-{f.name.split('.')[0]}")
    rel = [s for s in rows if s.relief]
    if not rel:
        sys.exit(0)
    print(f"{len(rows)} outings over {len(cached[-400:])} games, "
          f"{len(rel)} in relief")
    print(f"\n  outs per relief outing  mean "
          f"{st.mean(s.outs_recorded for s in rel):.2f}  median "
          f"{st.median(s.outs_recorded for s in rel):.0f}")
    exactly3 = sum(1 for s in rel if s.outs_recorded == 3)
    print(f"  exactly three outs      {exactly3 / len(rel):.1%}")
    mid = sum(1 for s in rel if s.mid_inning_entry)
    print(f"  entered mid-inning      {mid / len(rel):.1%}")
    print("\n  entry margin (pitching team's lead):")
    for lo, hi, lbl in ((-99, -4, "trailing 4+"), (-3, -1, "trailing 1-3"),
                        (0, 0, "tied"), (1, 3, "leading 1-3"),
                        (4, 99, "leading 4+")):
        g = [s for s in rel if lo <= s.margin <= hi]
        if g:
            print(f"    {lbl:<14} n={len(g):<5} mean order "
                  f"{st.mean(s.order for s in g):.2f}, "
                  f"{st.mean(s.outs_recorded for s in g):.2f} outs")
    print("\n  starters removed in inning:")
    sp = [s for s in rows if not s.relief]
    c = Counter(s.last_inning for s in sp)
    for i in sorted(c):
        print(f"    {i:>2}  {c[i]:>5}  {c[i] / len(sp):>6.1%}")
