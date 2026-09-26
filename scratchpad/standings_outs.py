"""STAGE 1 — do out-of-the-race clubs let their starters go longer?

Diff-in-diff on STARTER OUTS, which differences out club talent:
  delta(club, season) = mean starter outs LATE (from Aug 15) - EARLY (before Aug 1)
then compare delta between clubs that are OUT and clubs still IN.
"""
import math
import statistics as st
from collections import defaultdict

from src.context import store

AL = {"BAL","BOS","NYY","TB","TOR","CWS","CLE","DET","KC","MIN",
      "HOU","LAA","ATH","OAK","SEA","TEX"}

CUT_EARLY = "08-01"
CUT_LATE = "08-15"
SPOTS = 6          # playoff teams per league


def standings(con):
    """(season, date, team) -> (w, l) BEFORE that date."""
    rows = con.execute(
        "select date, away_team_abbr a, home_team_abbr h, away_score, home_score"
        " from bets.games where sport='mlb' and status='Final'"
        "   and away_team_abbr is not null and home_team_abbr is not null"
        "   and away_score is not null and home_score is not null"
        " order by date").fetchall()
    rec = defaultdict(lambda: [0, 0])
    out = {}
    cur = None
    for r in rows:
        season = int(r["date"][:4])
        if season != cur:
            rec = defaultdict(lambda: [0, 0])
            cur = season
        d = r["date"]
        for t in (r["a"], r["h"]):
            out[(season, d, t)] = tuple(rec[t])
        aw = r["away_score"] > r["home_score"]
        rec[r["a"]][0 if aw else 1] += 1
        rec[r["h"]][1 if aw else 0] += 1
    return out


def gb_of_cutoff(rec_on_date, season, date):
    """Games behind the SPOTS-th best record in each league, per team."""
    per = {}
    for lg in ("AL", "NL"):
        teams = [(t, w, l) for (s, d, t), (w, l) in rec_on_date.items()
                 if s == season and d == date
                 and ((t in AL) == (lg == "AL"))]
        if len(teams) < SPOTS + 1:
            continue
        teams.sort(key=lambda x: (x[1] - x[2]), reverse=True)
        _, w6, l6 = teams[SPOTS - 1]
        for t, w, l in teams:
            per[t] = ((w6 - w) + (l - l6)) / 2.0
    return per


def main():
    with store.connect() as con:
        rec = standings(con)
        # GB as of Aug 15 each season, the state at the start of the LATE window
        gb = {}
        for season in sorted({s for s, _, _ in rec}):
            d = f"{season}-{CUT_LATE}"
            snap = {k: v for k, v in rec.items() if k[0] == season and k[1] == d}
            if not snap:
                # nearest date on/after
                cands = sorted({k[1] for k in rec if k[0] == season and k[1] >= d})
                if not cands:
                    continue
                d = cands[0]
            g = gb_of_cutoff(rec, season, d)
            for t, v in g.items():
                gb[(season, t)] = v

        starts = con.execute(
            "select s.date, s.team, s.outs_recorded outs, s.batters"
            " from mlb_stints s join bets.games g on g.game_id = s.game_id"
            " where s.appearance_order = 0 and g.sport = 'mlb'"
            "   and g.status = 'Final'").fetchall()

    early = defaultdict(list)
    late = defaultdict(list)
    for r in starts:
        season, md = int(r["date"][:4]), r["date"][5:]
        key = (season, r["team"])
        if md < CUT_EARLY:
            early[key].append(r["outs"])
        elif md >= CUT_LATE:
            late[key].append(r["outs"])

    rowsout = []
    for key in sorted(set(early) & set(late)):
        if key not in gb or len(early[key]) < 40 or len(late[key]) < 25:
            continue
        rowsout.append((key, gb[key], st.mean(late[key]) - st.mean(early[key]),
                        len(early[key]), len(late[key])))

    print(f"club-seasons: {len(rowsout)}")
    for lo, hi, label in ((-99, 3, "IN     (GB <= 3)"),
                          (3, 10, "MIDDLE (3 < GB <= 10)"),
                          (10, 999, "OUT    (GB > 10)")):
        sel = [d for _, g, d, _, _ in rowsout if lo < g <= hi]
        if not sel:
            continue
        se = st.stdev(sel) / math.sqrt(len(sel)) if len(sel) > 1 else float("nan")
        print(f"  {label:24s} n={len(sel):3d}"
              f"  delta outs {st.mean(sel):+.3f} +/- {se:.3f}")

    a = [d for _, g, d, _, _ in rowsout if g > 10]
    b = [d for _, g, d, _, _ in rowsout if g <= 3]
    if a and b:
        se = math.sqrt(st.stdev(a) ** 2 / len(a) + st.stdev(b) ** 2 / len(b))
        diff = st.mean(a) - st.mean(b)
        print(f"\n  OUT - IN: {diff:+.3f} outs  +/- {se:.3f}"
              f"  ({diff / se:+.2f} se)")

    # raw levels, no differencing, as a sanity read
    print("\nraw mean starter outs in the LATE window")
    for lo, hi, label in ((-99, 3, "IN"), (3, 10, "MIDDLE"), (10, 999, "OUT")):
        sel = [o for key, g, _, _, _ in rowsout if lo < g <= hi for o in late[key]]
        if sel:
            print(f"  {label:8s} n={len(sel):5d}  {st.mean(sel):.3f}")


if __name__ == "__main__":
    main()
