"""STAGE 2 — the BOUNDARY hazard, conditioned on pitch count.

Stage 1 (mean starter outs) was a pooled read and is confounded by
September callups on innings limits, which push the other way. This asks
the manager's actual question: he has completed the inning at P pitches —
does he come back out? If "nothing to play for, let him cook" is real it
lives in the 85+ bins of a club that is buried.

Positive control included: --inject X flips X of the OUT-club removals to
'came back out' and confirms the harness resolves an effect that size.
"""
import math
import sys
from collections import defaultdict

from src.context import store, boundary
from src.context.holdout import HOLDOUT

AL = {"BAL","BOS","NYY","TB","TOR","CWS","CLE","DET","KC","MIN",
      "HOU","LAA","ATH","OAK","SEA","TEX"}
SPOTS = 6
LATE = "08-15"
BINS = [(0, 60), (60, 75), (75, 85), (85, 95), (95, 200)]


def standings(con):
    rows = con.execute(
        "select date, away_team_abbr a, home_team_abbr h, away_score, home_score"
        " from bets.games where sport='mlb' and status='Final'"
        "   and away_team_abbr is not null and home_team_abbr is not null"
        "   and away_score is not null and home_score is not null"
        " order by date").fetchall()
    rec, out, cur = defaultdict(lambda: [0, 0]), {}, None
    for r in rows:
        season = int(r["date"][:4])
        if season != cur:
            rec, cur = defaultdict(lambda: [0, 0]), season
        for t in (r["a"], r["h"]):
            out[(season, r["date"], t)] = tuple(rec[t])
        aw = r["away_score"] > r["home_score"]
        rec[r["a"]][0 if aw else 1] += 1
        rec[r["h"]][1 if aw else 0] += 1
    return out


def gb_on(rec, season, date):
    per = {}
    for lg in (True, False):
        teams = [(t, w, l) for (s, d, t), (w, l) in rec.items()
                 if s == season and d == date and ((t in AL) == lg)]
        if len(teams) < SPOTS + 1:
            continue
        teams.sort(key=lambda x: x[1] - x[2], reverse=True)
        _, w6, l6 = teams[SPOTS - 1]
        for t, w, l in teams:
            per[t] = ((w6 - w) + (l - l6)) / 2.0
    return per


def wilson_se(k, n):
    if not n:
        return float("nan")
    p = k / n
    return math.sqrt(max(p * (1 - p), 1e-9) / n)


def main():
    inject = 0.0
    if "--inject" in sys.argv:
        inject = float(sys.argv[sys.argv.index("--inject") + 1])
    train_only = "--train" in sys.argv

    with store.connect() as con:
        rec = standings(con)
        gb = {}
        for season in sorted({s for s, _, _ in rec}):
            dates = sorted({d for s, d, _ in rec
                            if s == season and d[5:] >= LATE})
            if not dates:
                continue
            for t, v in gb_on(rec, season, dates[0]).items():
                gb[(season, t)] = v
        games = con.execute(
            "select game_id, date, away_team_abbr a, home_team_abbr h"
            " from bets.games where sport='mlb' and status='Final'"
            "   and home_team_abbr is not null order by date").fetchall()

    # group -> bin -> [came_back_out, total]
    tab = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    import random
    rng = random.Random(7)
    for g in games:
        date = g["date"]
        if train_only and date >= HOLDOUT:
            continue
        season = int(date[:4])
        late = date[5:] >= LATE
        for row in boundary.decisions(g["game_id"]):
            if not row["ends_inning"] or row["inning"] < 4:
                continue
            team = g["h"] if row["side"] == "home" else g["a"]
            back = gb.get((season, team))
            if back is None:
                continue
            grp = ("OUT" if back > 10 else "IN" if back <= 3 else "MID")
            if not late:
                grp = grp + "-early"
            else:
                grp = grp + "-late"
            for lo, hi in BINS:
                if lo <= row["pitches"] < hi:
                    cell = tab[grp][(lo, hi)]
                    came = not row["removed"]
                    if inject and grp == "OUT-late" and row["removed"] \
                            and rng.random() < inject:
                        came = True
                    cell[0] += came
                    cell[1] += 1
                    break

    print(f"P(comes back out for the next inning) — boundary rows, inning 4+"
          f"{'  [pre-holdout only]' if train_only else ''}"
          f"{f'  [INJECTED {inject:.0%}]' if inject else ''}\n")
    hdr = "  pitches  " + "".join(f"{g:>22s}" for g in
                                  ("IN-late", "MID-late", "OUT-late"))
    print(hdr)
    for lo, hi in BINS:
        line = f"  {lo:3d}-{hi:<3d}  "
        for grp in ("IN-late", "MID-late", "OUT-late"):
            k, n = tab[grp][(lo, hi)]
            line += f"{k / n:>12.3f} n={n:<7d}" if n else f"{'-':>22s}"
        print(line)

    print("\n  OUT-late minus IN-late, per bin")
    for lo, hi in BINS:
        ko, no = tab["OUT-late"][(lo, hi)]
        ki, ni = tab["IN-late"][(lo, hi)]
        if no < 50 or ni < 50:
            continue
        d = ko / no - ki / ni
        se = math.hypot(wilson_se(ko, no), wilson_se(ki, ni))
        print(f"  {lo:3d}-{hi:<3d}  {d:+.3f} +/- {se:.3f}  ({d / se:+.2f} se)")

    print("\n  DIFF-IN-DIFF (late minus early, OUT minus IN) — removes"
          " the club's own baseline")
    for lo, hi in BINS:
        cells = {g: tab[g][(lo, hi)] for g in
                 ("OUT-late", "OUT-early", "IN-late", "IN-early")}
        if any(n < 50 for _, n in cells.values()):
            continue
        def rate(g):
            k, n = cells[g]
            return k / n
        dd = ((rate("OUT-late") - rate("OUT-early"))
              - (rate("IN-late") - rate("IN-early")))
        se = math.sqrt(sum(wilson_se(k, n) ** 2 for k, n in cells.values()))
        print(f"  {lo:3d}-{hi:<3d}  {dd:+.3f} +/- {se:.3f}  ({dd / se:+.2f} se)")


if __name__ == "__main__":
    main()
