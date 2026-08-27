"""Does a club's ability to TURN TWO persist? The gate before building it.

    venv/bin/python -m scratchpad.team_dp

WHY THIS IS A DEFENCE QUESTION AND NOT A PITCHER ONE. `sim` rolls one league
constant keyed only on the out count — every batter grounds into a double
play at the same rate and every defence converts at the same rate. But the
batter only supplies the OPPORTUNITY; the middle infield converts it. There
is no team defence anywhere in this model.

THE GATE IS THE ONE `deploy.py` USED, and it is a gate rather than a
measurement on purpose: a per-club number that does not persist is a
per-club number that cannot be projected, however real it was last year.
Split the club's games ODD/EVEN, correlate the two halves, Spearman-Brown up
to full-season reliability. Odd/even rather than first-half/second-half so a
midseason trade or a call-up hits both halves equally.

    passes  -> role-style, projectable, worth building (deploy hit +0.55..+0.78)
    fails   -> per-club advancement territory (+0.11..+0.38) and it stays out

2025+2026 ONLY. The league rate STEPPED between 2024 and 2025 (0.230 ->
0.213, see `sim.GIDP_RATE`), so pooling the older era would mix two
different leagues into every club's line.

DENOMINATOR IS THE MODEL'S OWN: double plays per ball-in-play out, with a
man on first and under two out, which is the only state `sim` ever rolls it
in. Counting per opportunity instead is a units mismatch, not a finding.
"""
from __future__ import annotations

import glob
import os
import statistics as st
import sys
from collections import defaultdict

from src import db
from src.context import advance
from src.context.sources import pbp

BIP_OUT = {"field_out", "force_out", "fielders_choice_out",
           "grounded_into_double_play", "double_play", "triple_play"}
ERA = ("2025", "2026")
MIN_PER_HALF = 60


def main(argv):
    with db.connect() as c:
        meta = {r["game_id"].split("-")[-1]:
                (r["date"][:4], r["home_team"], r["away_team"])
                for r in c.execute("select game_id, date, home_team,"
                                   " away_team from games where sport='mlb'")}
    gids = [os.path.basename(f).split(".")[0]
            for f in sorted(glob.glob(".cache/pbp/*.json.gz"))]
    gids = [g for g in gids if meta.get(g, ("",))[0] in ERA]
    print(f"  {len(gids):,} games in {'/'.join(ERA)}", flush=True)

    # {team: [[dp, n] half0, [dp, n] half1]}
    half: dict = defaultdict(lambda: [[0, 0], [0, 0]])
    for i, g in enumerate(gids):
        yr, home, away = meta[g]
        try:
            plays = list(pbp.plays(g))
        except Exception:
            continue
        h = i % 2                      # odd/even GAME, not odd/even inning
        for play, bases, outs, _a, _hs in plays:
            ev = ((play.get("result") or {}).get("eventType") or "")
            if ev not in BIP_OUT or not bases[0] or outs >= 2:
                continue
            top = bool((play.get("about") or {}).get("isTopInning"))
            # Top of the inning: the AWAY side is batting, so the HOME club
            # is in the field. That is the club being measured.
            field = home if top else away
            half[field][h][1] += 1
            if ev in advance.DP:
                half[field][h][0] += 1
        if (i + 1) % 2000 == 0:
            print(f"    {i+1:,}/{len(gids):,}", flush=True)

    rows = [(t, v) for t, v in half.items()
            if min(v[0][1], v[1][1]) >= MIN_PER_HALF]
    a = [v[0][0] / v[0][1] for _, v in rows]
    b = [v[1][0] / v[1][1] for _, v in rows]
    r = st.correlation(a, b) if len(a) > 2 else 0.0
    full = 2 * r / (1 + r) if r > -1 else 0.0
    n0 = st.mean(min(v[0][1], v[1][1]) for _, v in rows)
    print(f"\n  {len(rows)} clubs, ~{n0:.0f} chances per half")
    print(f"  split-half r {r:+.3f}   Spearman-Brown full-season {full:+.3f}")
    print(f"  bullpen-role gate passed at +0.55..+0.78;"
          f" per-club advancement FAILED at +0.11..+0.38")

    combined = sorted(((v[0][0] + v[1][0]) / (v[0][1] + v[1][1]), t)
                      for t, v in rows)
    print(f"\n  spread across clubs, both halves pooled")
    print(f"    best  " + ", ".join(f"{t} {x:.3f}" for x, t in combined[-3:]))
    print(f"    worst " + ", ".join(f"{t} {x:.3f}" for x, t in combined[:3]))
    print(f"    league {sum(v[0][0]+v[1][0] for _, v in rows) / sum(v[0][1]+v[1][1] for _, v in rows):.4f}"
          f"   sd across clubs {st.pstdev([x for x, _ in combined]):.4f}")


if __name__ == "__main__":
    main(sys.argv[1:])
