"""THE OUTS DISTRIBUTION, SPLIT BY WHICH DECISION ENDED THE START.

    venv/bin/python -m scratchpad.outs_split [DUMP.json]

QUESTION    At a MULTIPLE OF THREE a start ended one of two ways: he
            finished the inning and came out (BOUNDARY), or he started the
            next one and was chased before recording an out (MID). The out
            count cannot tell them apart — that is the 7.8% mislabelling
            `bnd_rulers.py` found. What is the real split at each round
            number, and does the model reproduce it?

WHY IT MATTERS. The model's outs distribution has spikes at 9/12/15/18/21
and its boundary share is measured off those spikes. If reality's spike at
15 is really two populations and the model only produces one of them, the
spike can be the right HEIGHT and the wrong THING — and every boundary-share
number in these notes is computed from exactly that height.

TEST        Real side: `boundary.exits` reads the removal event out of
            play-by-play, so it knows which decision it was. Model side: the
            persisted dump carries `pulled_mid_inning`, which IS the
            decision — nothing is inferred on either side.

Holdout games only, to match every other scoring run.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict

from src import roster
from src.context import boundary, calibrate as cal

HOLDOUT = "2026-07-01"


def main(argv):
    path = argv[0] if argv else "scratchpad/starts_shipped.json"
    d = json.load(open(path))
    c = {k: i for i, k in enumerate(d["cols"])}

    m_b, m_m = Counter(), Counter()
    seen = set()
    for r in d["rows"]:
        o = r[c["outs"]]
        (m_m if r[c["mid"]] else m_b)[o] += 1
        seen.add((r[c["pitcher"]], r[c["game_id"]]))
    m_tot = sum(m_b.values()) + sum(m_m.values())

    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    r_b, r_m, missing = Counter(), Counter(), 0
    for gid in sorted(pairs):
        try:
            ex = {e.get("pitcher"): e for e in boundary.exits(gid)}
        except Exception:
            missing += 1
            continue
        for act, _r, _l in pairs[gid]:
            e = ex.get(roster.player_id(act.get("player_name")))
            if not e or act.get("o") is None:
                continue
            (r_b if e.get("kind") == "boundary" else r_m)[act["o"]] += 1
    r_tot = sum(r_b.values()) + sum(r_m.values())

    print(f"  {r_tot:,} real starts, {m_tot:,} simulated"
          f"{f', {missing} games without play-by-play' if missing else ''}\n")
    print("  share of ALL starts ending at each out count, by DECISION\n")
    print(f"  {'outs':<7}{'REAL bnd':>10}{'REAL mid':>10}{'':>4}"
          f"{'SIM bnd':>10}{'SIM mid':>10}{'':>4}{'bnd gap':>9}{'mid gap':>9}")
    for o in range(0, 28):
        rb, rm = r_b[o] / r_tot, r_m[o] / r_tot
        mb, mm = m_b[o] / m_tot, m_m[o] / m_tot
        if max(rb, rm, mb, mm) < 0.004:
            continue
        star = " <<" if o % 3 == 0 else ""
        print(f"  {o:<7}{rb:>10.3f}{rm:>10.3f}{'':>4}{mb:>10.3f}{mm:>10.3f}"
              f"{'':>4}{mb - rb:>+9.3f}{mm - rm:>+9.3f}{star}")

    print("\n  AT THE ROUND NUMBERS ONLY — what share of that spike is a")
    print("  starter who began the NEXT inning and never got an out\n")
    print(f"  {'outs':<7}{'real total':>12}{'real mid%':>11}"
          f"{'sim total':>11}{'sim mid%':>10}")
    for o in (9, 12, 15, 18, 21):
        rt, mt = r_b[o] + r_m[o], m_b[o] + m_m[o]
        if not rt:
            continue
        print(f"  {o:<7}{rt / r_tot:>12.3f}{r_m[o] / rt:>11.1%}"
              f"{mt / m_tot:>11.3f}{(m_m[o] / mt if mt else 0):>10.1%}")


if __name__ == "__main__":
    main(sys.argv[1:])
