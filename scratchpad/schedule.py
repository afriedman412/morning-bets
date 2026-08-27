"""SCHEDULE BURDEN — travel, getaway days, and how long since a day off.

    venv/bin/python -m scratchpad.schedule

WHAT IS AND IS NOT ALREADY MEASURED. Six between-game features were screened
on the OUTS residual and all came back null: home/away +0.005, night +0.019,
park index -0.032, days rest +0.014, bullpen outs yesterday +0.037, month
+0.039. But "days rest" there is the PITCHER'S days since his own last
start, and day/night was a FLAT FLAG. Nothing about where the TEAM was
yesterday has ever been tested.

TWO REASONS TO RE-OPEN RATHER THAN RE-RUN.

  1. THOSE NULLS WERE SCORED ON OUTS, which is the channel this project has
     found immune to everything, because outs are the hook. A null on outs is
     weak evidence about runs — the same mistake as screening handedness on
     strikeouts when the effect was on contact.
  2. THE DEFECT WE ACTUALLY HAVE IS DISPERSION, not level. Measured
     2026-08-27: the model puts exactly the right men on base and is short
     only on the tails. A team that played at night and then flew is
     plausibly MORE VARIABLE rather than simply worse, and nobody has looked
     for that. A flat dispersion term confirmed the defect and was neutral
     on CRPS precisely because it did not vary; this is a candidate for
     something that does.

SO THIS SCREENS TWO THINGS PER FEATURE, and they are different questions:

    signed    does it shift the run residual   (is the team WORSE)
    |resid|   does it shift the ABSOLUTE one   (is the team more VARIABLE)

A feature can be flat on the first and real on the second. That is exactly
what a fatigue effect should look like, and no screen in this project has
ever asked the second question.

FEATURES, all computed from the schedule alone — no external data:

    getaway     a DAY game today after a NIGHT game yesterday
    travel      the club changed venue since its last game
    both        travel AND a getaway day, the punishing combination
    stretch     consecutive games without an off day
    long_trip   games since the club was last at home
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict
from datetime import date as _date

from src import db


def _d(s):
    y, m, dd = (int(x) for x in s.split("-"))
    return _date(y, m, dd)


def club_schedule(season="2026"):
    """{(club, date): features} from the schedule alone."""
    with db.connect() as c:
        rows = [dict(r) for r in c.execute(
            "select date, home_team_abbr, away_team_abbr, venue_id,"
            " day_night from games where sport = 'mlb'"
            f" and date like '{season}%' order by date")]
    by_club = defaultdict(list)
    for r in rows:
        for club, home in ((r["home_team_abbr"], True),
                           (r["away_team_abbr"], False)):
            if club:
                by_club[club].append((r["date"], r["venue_id"],
                                      r["day_night"], home))
    out = {}
    for club, seq in by_club.items():
        seq.sort()
        stretch = 0
        since_home = 0
        for i, (d, ven, dn, home) in enumerate(seq):
            f = {"getaway": 0, "travel": 0, "both": 0,
                 "stretch": 0, "long_trip": 0}
            if i:
                pd, pven, pdn, _ph = seq[i - 1]
                gap = (_d(d) - _d(pd)).days
                stretch = stretch + 1 if gap == 1 else 0
                # A DAY game after a NIGHT game, next day. The getaway-day
                # complaint, and it is an INTERACTION — the flat day/night
                # flag that was screened cannot express it.
                f["getaway"] = int(gap == 1 and dn == "day" and pdn == "night")
                # Venue changed, so the club moved. Crude — it does not know
                # distance or time zones — but it is the schedule alone and
                # needs no external table.
                f["travel"] = int(ven != pven)
                f["both"] = f["getaway"] * f["travel"]
                f["stretch"] = stretch
            since_home = 0 if home else since_home + 1
            f["long_trip"] = since_home
            out[(club, d)] = f
    return out


FEATS = ("getaway", "travel", "both", "stretch", "long_trip")


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


def main(argv):
    sched = club_schedule()
    rows = [r for r in json.load(open("scratchpad/ceiling_rows.json"))
            if not r.get("_team_row")]
    print(f"  {len(sched):,} club-games, {len(rows):,} scored starts\n")

    # The residual is the PITCHER'S, so the schedule burden that matters is
    # the OPPOSING club's — they are the ones batting. Attaching the
    # pitcher's own club would test whether a tired PITCHER is worse, which
    # is a different question and is what `days rest` already asked.
    with db.connect() as c:
        opp = {}
        for r in c.execute("select game_id, home_team_abbr, away_team_abbr"
                           " from games where sport = 'mlb'"):
            opp[r["game_id"]] = (r["home_team_abbr"], r["away_team_abbr"])

    print(f"  {'feature':<11}{'n':>7}{'share':>8}"
          f"{'SIGNED r':>11}{'z':>7}{'|RESID| r':>12}{'z':>7}")
    for f in FEATS:
        xs, ys, ay = [], [], []
        for r in rows:
            pair = opp.get(r["game_id"])
            if not pair:
                continue
            # The batting club is the one that is NOT the pitcher's.
            bat = pair[0] if pair[1] == r["team"] else pair[1]
            s = sched.get((bat, r["date"]))
            if not s or r.get("m_er") is None:
                continue
            xs.append(float(s[f]))
            resid = r["a_er"] - r["m_er"]
            ys.append(resid)
            ay.append(abs(resid))
        if len(xs) < 100:
            continue
        r1, z1 = corr(xs, ys)
        r2, z2 = corr(xs, ay)
        share = st.mean(1.0 if x else 0.0 for x in xs)
        print(f"  {f:<11}{len(xs):>7,}{share:>8.3f}"
              f"{r1:>+11.3f}{z1:>+7.1f}{r2:>+12.3f}{z2:>+7.1f}")

    print("\n  SIGNED asks whether the tired club is WORSE. |RESID| asks")
    print("  whether it is more VARIABLE, which is the defect this model")
    print("  actually has and which no screen here has asked before.")
    print("  The bar is 2 sigma, and a feature that is flat on signed and")
    print("  real on absolute is a DISPERSION candidate, not a rate one.")


if __name__ == "__main__":
    main(sys.argv[1:])
