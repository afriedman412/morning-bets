"""STAGE 3 — is the short leash the MANAGER, or is it a different pitcher?

Stage 2 found out-of-race clubs 10 points LESS likely to send a starter
back out at 75-95 pitches (-3.2 / -2.6 se), which is the opposite sign to
the "nothing to play for, let him cook" hypothesis that opened this.

BUT ITS OWN DOCSTRING NAMES THE CONFOUND AND DOES NOT CONTROL FOR IT. A
buried club in September promotes young arms on innings limits, and those
get pulled early. That is roster composition, not a leash, and it produces
this exact signature. Stage 2 takes every boundary row with no filter on
WHO is pitching.

THE TEST. Restrict to pitchers who started for that club in BOTH windows
-- the same arm, early and late, same season. Roster churn cannot survive
it. If the effect holds, it is the manager; if it vanishes, stage 2 was
measuring callups.

Positive control carried over: --inject X flips X of the OUT-late
removals and confirms the restricted harness still resolves an effect.
"""
import math
import sys
from collections import defaultdict

from src.context import store, boundary

SPOTS = 6
LATE = "08-15"
EARLY_END = "08-01"
BINS = [(0, 60), (60, 75), (75, 85), (85, 95), (95, 200)]
AL = {"BAL", "BOS", "NYY", "TB", "TOR", "CWS", "CLE", "DET", "KC", "MIN",
      "HOU", "LAA", "ATH", "OAK", "SEA", "TEX"}


def standings(con):
    rows = con.execute(
        "select date, away_team_abbr a, home_team_abbr h, away_score,"
        " home_score from bets.games where sport='mlb' and status='Final'"
        " and away_team_abbr is not null and home_team_abbr is not null"
        " and away_score is not null and home_score is not null"
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
    recs = {t: v for (s, d, t), v in rec.items() if s == season and d == date}
    out = {}
    for lg in (AL, None):
        sub = {t: v for t, v in recs.items()
               if (t in AL) == (lg is AL)}
        if not sub:
            continue
        rank = sorted(sub.items(), key=lambda kv: -(kv[1][0] - kv[1][1]))
        if len(rank) < SPOTS:
            continue
        cutw, cutl = rank[SPOTS - 1][1]
        for t, (w, l) in sub.items():
            out[t] = ((cutw - w) + (l - cutl)) / 2
    return out


def main():
    inject = 0.0
    if "--inject" in sys.argv:
        inject = float(sys.argv[sys.argv.index("--inject") + 1])

    with store.connect() as con:
        rec = standings(con)
        gb = {}
        for season in sorted({s for s, _, _ in rec}):
            dates = sorted({d for s, d, _ in rec
                            if s == season and d[5:] >= LATE})
            if dates:
                for t, v in gb_on(rec, season, dates[0]).items():
                    gb[(season, t)] = v
        games = con.execute(
            "select game_id, date, away_team_abbr a, home_team_abbr h"
            " from bets.games where sport='mlb' and status='Final'"
            " and home_team_abbr is not null order by date").fetchall()

    # pass 1: collect rows, and note which arms appear in each window
    rows = []
    seen = defaultdict(set)          # (season, team, window) -> {pitcher}
    for g in games:
        date = g["date"]
        season = int(date[:4])
        md = date[5:]
        win = "late" if md >= LATE else ("early" if md < EARLY_END else None)
        if win is None:
            continue
        for row in boundary.decisions(g["game_id"]):
            if not row["ends_inning"] or row["inning"] < 4:
                continue
            team = g["h"] if row["side"] == "home" else g["a"]
            if (season, team) not in gb:
                continue
            seen[(season, team, win)].add(row["pitcher"])
            rows.append((season, team, win, row["pitcher"], row["pitches"],
                         not row["removed"]))

    import random
    rng = random.Random(7)
    tab = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    kept = dropped = 0
    for season, team, win, pid, pitches, came in rows:
        both = (pid in seen[(season, team, "early")]
                and pid in seen[(season, team, "late")])
        if not both:
            dropped += 1
            continue
        kept += 1
        back = gb[(season, team)]
        grp = ("OUT" if back > 10 else "IN" if back <= 3 else "MID") + "-" + win
        for lo, hi in BINS:
            if lo <= pitches < hi:
                if inject and grp == "OUT-late" and not came \
                        and rng.random() < inject:
                    came = True
                tab[grp][(lo, hi)][0] += came
                tab[grp][(lo, hi)][1] += 1
                break

    print("SAME ARM IN BOTH WINDOWS — boundary rows, inning 4+"
          + (f"   [INJECTED {inject:.0%}]" if inject else ""))
    print(f"  kept {kept} rows, dropped {dropped} "
          f"({dropped/(kept+dropped):.0%}) for appearing in one window only\n")
    print("  pitches  " + "".join(f"{g:>20s}" for g in
                                  ("IN-late", "OUT-late")))
    for lo, hi in BINS:
        line = f"  {lo:3d}-{hi:<3d}  "
        for grp in ("IN-late", "OUT-late"):
            k, n = tab[grp][(lo, hi)]
            line += f"{(k/n if n else float('nan')):.3f} n={n:<12d}" if n \
                else f"{'--':>20s}"
        print(line)

    def se(k, n):
        p = k / n if n else 0
        return math.sqrt(max(p * (1 - p), 1e-9) / n) if n else float("nan")

    print("\n  OUT-late minus IN-late")
    for lo, hi in BINS:
        a, na = tab["OUT-late"][(lo, hi)]
        b, nb = tab["IN-late"][(lo, hi)]
        if not na or not nb:
            continue
        d = a / na - b / nb
        s = math.hypot(se(a, na), se(b, nb))
        print(f"   {lo:3d}-{hi:<3d}  {d:+.3f} +/- {s:.3f}  ({d/s:+.2f} se)")

    print("\n  DIFF-IN-DIFF (late minus early, OUT minus IN)")
    for lo, hi in BINS:
        cells = {g: tab[g][(lo, hi)] for g in
                 ("OUT-late", "OUT-early", "IN-late", "IN-early")}
        if any(n == 0 for _, n in cells.values()):
            continue
        d = ((cells["OUT-late"][0] / cells["OUT-late"][1]
              - cells["OUT-early"][0] / cells["OUT-early"][1])
             - (cells["IN-late"][0] / cells["IN-late"][1]
                - cells["IN-early"][0] / cells["IN-early"][1]))
        s = math.sqrt(sum(se(k, n) ** 2 for k, n in cells.values()))
        print(f"   {lo:3d}-{hi:<3d}  {d:+.3f} +/- {s:.3f}  ({d/s:+.2f} se)")


if __name__ == "__main__":
    main()
