"""HOW MUCH OF THE OUTS ERROR IS THE FOURTH INNING? An oracle, by subsetting.

    venv/bin/python -m scratchpad.starts_query [DUMP.json]

QUESTION    Both curves over-pull in the fourth (boundary +0.041 and mid
            +0.058 against real, at 60-75 pitches). If those excess pulls
            simply did not happen, how much of the outs-ladder error goes
            away?

WHAT THIS IS. An ORACLE and an UPPER BOUND, not a mechanism. It removes the
measured excess of fourth-inning exits and lets those starts continue as the
SAME PITCHER'S surviving starts did. It answers "how much is this defect
worth" so the fix can be prioritised — it is not a candidate fix and must
never be scored as one.

WHAT IT CANNOT CAPTURE, and both run the same way. A start that keeps going
faces more batters, so its OWN state evolves; substituting a survivor's
line is a first-order approximation. And it holds the rest of the hook
fixed, so it does not model the pulls that would then happen later. Both
make this an over-estimate of the gain, which is what an upper bound is for.

Reads the dump written by `starts_dump.py`. No simulation here.
"""
from __future__ import annotations

import json
import random
import statistics as st
import sys
from collections import defaultdict

LINES = (12.5, 14.5, 15.5, 16.5, 17.5, 18.5, 20.5)
#: Measured excess of FOURTH-INNING exits, model minus real, as a share of
#: all starts. Mid is the four-season figure (+0.022 to +0.024, all four
#: seasons significant); the boundary figure is the 2026 cell comparison and
#: is the weaker of the two.
EXCESS_MID = 0.022
EXCESS_BND = 0.012


def ladder(vals):
    n = len(vals)
    return {ln: sum(1 for v in vals if v > ln) / n for ln in LINES}


def main(argv):
    path = argv[0] if argv else "scratchpad/starts_holdout.json"
    d = json.load(open(path))
    cols = {c: i for i, c in enumerate(d["cols"])}
    rows = d["rows"]
    print(f"  {len(rows):,} simulated starts, {d['games']} games x "
          f"{d['sims']} sims, holdout {d['holdout']}+\n")

    O, EX, MID, PIT = (cols["outs"], cols["exit_inning"], cols["mid"],
                       cols["pitcher"])
    sim_outs = [r[O] for r in rows]
    # One real line per (pitcher, game) -- the dump repeats it per draw.
    real = {}
    for r in rows:
        if r[cols["real_outs"]] is not None:
            real[(r[PIT], r[cols["game_id"]])] = r[cols["real_outs"]]
    real_outs = list(real.values())

    base = ladder(sim_outs)
    act = ladder(real_outs)
    print(f"  baseline model mean {st.mean(sim_outs):.2f}, real "
          f"{st.mean(real_outs):.2f}   ({len(real_outs):,} real starts)\n")

    # Survivor pool per pitcher: starts that got PAST the fourth.
    surv = defaultdict(list)
    for r in rows:
        if r[EX] > 4:
            surv[r[PIT]].append(r[O])
    allsurv = [r[O] for r in rows if r[EX] > 4]

    rnd = random.Random(29)
    for label, ex_mid, ex_bnd in (("mid only", EXCESS_MID, 0.0),
                                  ("mid + boundary", EXCESS_MID, EXCESS_BND)):
        idx4 = [i for i, r in enumerate(rows) if r[EX] == 4]
        mid4 = [i for i in idx4 if rows[i][MID]]
        bnd4 = [i for i in idx4 if not rows[i][MID]]
        n_mid = int(round(ex_mid * len(rows)))
        n_bnd = int(round(ex_bnd * len(rows)))
        drop = set(rnd.sample(mid4, min(n_mid, len(mid4))))
        drop |= set(rnd.sample(bnd4, min(n_bnd, len(bnd4))))
        fixed = []
        for i, r in enumerate(rows):
            if i in drop:
                pool = surv.get(r[PIT]) or allsurv
                fixed.append(rnd.choice(pool))
            else:
                fixed.append(r[O])
        new = ladder(fixed)
        print(f"  ORACLE: {label}   "
              f"({len(drop):,} of {len(idx4):,} fourth-inning exits "
              f"reassigned, {len(drop)/len(rows):.1%} of starts)")
        print(f"    {'line':<9}{'now':>9}{'oracle':>9}{'real':>9}"
              f"{'gap now':>10}{'gap oracle':>12}")
        tot_n = tot_o = 0.0
        for ln in LINES:
            gn, go = base[ln] - act[ln], new[ln] - act[ln]
            tot_n += abs(gn)
            tot_o += abs(go)
            print(f"    o{ln:<8.1f}{base[ln]:>9.3f}{new[ln]:>9.3f}"
                  f"{act[ln]:>9.3f}{gn:>+10.3f}{go:>+12.3f}")
        print(f"    mean |gap| {tot_n/len(LINES):.4f} -> {tot_o/len(LINES):.4f}"
              f"   ({1 - tot_o/tot_n:+.0%})")
        print(f"    mean outs  {st.mean(sim_outs):.2f} -> "
              f"{st.mean(fixed):.2f}   (real {st.mean(real_outs):.2f})\n")


if __name__ == "__main__":
    main(sys.argv[1:])
