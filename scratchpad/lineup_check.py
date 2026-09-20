"""How wrong is the AB-sorted lineup proxy against the REAL batting order?

`calibrate.opposing_lineups` has no batting-order column to work with — the
boxscore cache carries at-bats and nothing else — so it sorts the nine by
AB descending and calls that the order. Two things are wrong with that and
they are different: WHO is in the nine (a pinch hitter with 2 AB can
displace a starter pulled early) and WHAT ORDER they bat in (AB excludes
walks, so a high-OBP leadoff man ranks below a free swinger, and ties are
broken by whatever SQLite returns).

Order is not cosmetic here: the simulator wraps the lineup, and times
through the order is computed from batters faced, so the order decides who
eats the third-pass penalty.
"""
import statistics as st
import sys
from collections import defaultdict

from src import db
from src.context.sources import pbp


def true_order(game_id):
    """{half: [first nine distinct batters, in order]} straight from PBP."""
    seen = {"top": [], "bottom": []}
    for play, *_ in pbp.plays(game_id):
        ab = play.get("about") or {}
        half = ab.get("halfInning")
        nm = (((play.get("matchup") or {}).get("batter") or {})
              .get("fullName"))
        if half not in seen or not nm:
            continue
        if nm not in seen[half] and len(seen[half]) < 9:
            seen[half].append(nm)
    return seen


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    with db.connect() as c:
        gids = [r["game_id"] for r in c.execute(
            "select distinct game_id from mlb_batting order by game_id")][:n]
        ab_rows = defaultdict(list)
        for r in c.execute(
                "select game_id, team, player_name, ab from mlb_batting "
                "order by game_id, team, ab desc"):
            ab_rows[(r["game_id"], r["team"])].append(r["player_name"])
        home_of = {r["game_id"]: r["home_team_abbr"] for r in c.execute(
            "select game_id, home_team_abbr from games where sport='mlb'")}

    set_diff, rank_err, exact, tot = [], [], 0, 0
    for gid in gids:
        try:
            real = true_order(gid)
        except Exception:
            continue
        home = home_of.get(gid)
        teams = [t for (g, t) in ab_rows if g == gid]
        if len(teams) != 2 or not home:
            continue
        for team in teams:
            half = "bottom" if team == home else "top"
            r9 = real.get(half) or []
            p9 = ab_rows[(gid, team)][:9]
            if len(r9) < 9 or len(p9) < 9:
                continue
            tot += 1
            set_diff.append(len(set(r9) - set(p9)))
            pos = {nm: i for i, nm in enumerate(r9)}
            errs = [abs(pos[nm] - i) for i, nm in enumerate(p9) if nm in pos]
            if errs:
                rank_err.append(st.mean(errs))
            if r9 == p9:
                exact += 1

    print(f"  {tot} lineups compared\n")
    print(f"  exact match (right nine, right order): {exact / tot:.1%}")
    print(f"  mean batters in the REAL nine that the proxy MISSES: "
          f"{st.mean(set_diff):.2f}")
    print(f"  share of lineups with at least one wrong batter:     "
          f"{sum(1 for v in set_diff if v) / tot:.1%}")
    print(f"  mean |slot error| for batters present in both:       "
          f"{st.mean(rank_err):.2f} slots")
    print("\n  A slot error of ~2 means the man the model bats leadoff is"
          "\n  really hitting third — which moves who faces the starter a"
          "\n  third time, and TTO is a measured 19% swing in K%.")


if __name__ == "__main__":
    main()
