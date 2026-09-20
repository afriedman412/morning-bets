"""Does WHICH CATCHER is behind the plate explain what the model misses?

    venv/bin/python -m scratchpad.catchers

The simulator has no catcher. `sources/catcher.py` has fetched framing for
months and `sim.py` mentions a catcher exactly once, in a comment about
passed balls.

WHY IT MIGHT SURVIVE WHERE PARK AND TEAM DEFENCE DIED. Both of those are
already inside a pitcher's own rates — he throws in his park and in front of
his gloves all season, so stripping and re-applying them is close to a round
trip. A CATCHER IS DIFFERENT: the backup catches roughly 30% of games, so
the starter/backup swing is variance INSIDE a pitcher's season line rather
than outside it. That is the only one of the three where the absorption
argument does not apply.

IDENTITY, NOT FRAMING, AND DELIBERATELY. If which catcher caught carries no
information about the residual, no framing number can rescue it — framing is
a property OF the catcher. Testing identity first costs nothing and needs no
Savant join, and it cannot be attenuated by a bad merge.

THE CATCHER IS READ OFF STRIKEOUT PUTOUTS: position code 2 in the play's
fielding credits. That is per plate appearance and exact, rather than the
club's primary catcher, which is the guess `catcher.py` is explicit about.

LEAVE-ONE-OUT, like `between.py`. For each start, the mean residual of the
SAME catcher's OTHER starts, correlated against this start's residual. A
group mean containing the target manufactures a correlation.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict

from src import db
from src.context.sources import pbp

MIN_STARTS = 4


def corr(xs, ys):
    n = len(xs)
    if n < 30:
        return 0.0, 0.0
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if not sx or not sy:
        return 0.0, 0.0
    r = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (n * sx * sy)
    return r, r * (n - 2) ** 0.5 / max((1 - r * r) ** 0.5, 1e-9)


def catcher_by_start() -> dict:
    """{(game_id, starter_name): catcher_id} from strikeout putouts."""
    with db.connect() as c:
        games = {r["game_id"]: (r["home_team_abbr"], r["away_team_abbr"])
                 for r in c.execute("select game_id, home_team_abbr,"
                                    " away_team_abbr from games"
                                    " where sport = 'mlb'")}
        starters = defaultdict(list)
        for r in c.execute("select game_id, player_name, team from"
                           " mlb_pitching where is_starter = 1"):
            starters[r["game_id"]].append((r["player_name"], r["team"]))

    out = {}
    for full, arms in starters.items():
        short = full.split("-")[-1]
        if full not in games or not pbp.have(short):
            continue
        home_ab, away_ab = games[full]
        try:
            d = pbp.fetch(short)
        except Exception:
            continue
        if not d:
            continue
        seen, catchers = {}, defaultdict(lambda: defaultdict(int))
        for p in (d.get("allPlays") or []):
            ab, mu = p.get("about") or {}, p.get("matchup") or {}
            pid = (mu.get("pitcher") or {}).get("id")
            if not pid:
                continue
            side = "home" if ab.get("isTopInning") else "away"
            seen.setdefault(side, pid)
            if seen[side] != pid:
                continue
            for r in (p.get("runners") or []):
                for cr in (r.get("credits") or []):
                    if (cr.get("position") or {}).get("code") == "2":
                        cid = (cr.get("player") or {}).get("id")
                        if cid:
                            catchers[side][cid] += 1
        for name, team in arms:
            t = (team or "").upper()
            side = ("home" if t == (home_ab or "").upper()
                    else "away" if t == (away_ab or "").upper() else None)
            if side is None or not catchers[side]:
                continue
            out[(full, name)] = max(catchers[side].items(),
                                    key=lambda kv: kv[1])[0]
    return out


def main(argv):
    rows = [r for r in json.load(open("scratchpad/ceiling_rows.json"))
            if not r.get("_team_row")]
    cat = catcher_by_start()
    hit = [(r, cat[(r["game_id"], r["player"])]) for r in rows
           if (r["game_id"], r["player"]) in cat]
    print(f"  {len(rows):,} residual rows, {len(hit):,} with a catcher"
          f" identified, {len(set(c for _r, c in hit)):,} distinct catchers\n")

    print(f"  {'stat':<8}{'n':>7}{'LOO r':>9}{'z':>8}"
          f"{'spread it could remove':>26}")
    for stat in ("k", "bb", "h", "outs"):
        by = defaultdict(list)
        vals = []
        for r, cid in hit:
            if r.get(f"m_{stat}") is None:
                continue
            res = r[f"a_{stat}"] - r[f"m_{stat}"]
            by[cid].append(res)
            vals.append((cid, res))
        xs, ys = [], []
        for cid, res in vals:
            others = [v for v in by[cid] if v is not res]
            if len(others) < MIN_STARTS:
                continue
            xs.append(st.mean(others))
            ys.append(res)
        r_, z = corr(xs, ys)
        sd = st.pstdev(ys) if ys else 0.0
        print(f"  {stat:<8}{len(xs):>7,}{r_:>+9.3f}{z:>+8.1f}"
              f"{abs(r_) * sd:>26.3f}")

    print("\n  For scale, `between.py` on the same residuals: pitcher +0.141")
    print("  (0.52 outs), club +0.078 (0.29), venue +0.006. Anything under")
    print("  ~0.2 of removable spread is not worth building.")


if __name__ == "__main__":
    main(sys.argv[1:])
