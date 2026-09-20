"""Is the model's error the same for a flamethrower and a contact starter?

    venv/bin/python -m scratchpad.bytype [n_draws]

WHY TYPE AT ALL, given `sources/archetype.py` came back absent for starters.
That typed by PITCH MIX and asked whether type predicts performance. This
types by OUTCOME PROFILE and asks a different question: whether the model's
own ERROR is homogeneous. Every defect measured on day nine was reported as
one number over all starters — pitches per out 6% light, too many 21+ out
starts, K under-dispersed in long outings. A single number is only a fair
summary if the error is flat across the population.

A pitcher who strikes out four and a pitcher who strikes out nine are
different machines. The contact starter's length is decided by balls in play
and defence; the power starter's by pitch count and traffic. There is no
reason in advance for one set of constants to fit both, and if it does not,
the interesting question is which group the global fix would be wrong for.

TERCILES BY K PER BATTER FACED, on the pitcher's own season, so the grouping
is a property of the arm rather than of the start being scored.

THE LEASH IS IN SAMPLE here, as everywhere it is not explicitly held out, so
read the LEVEL and SHAPE comparisons — which are what this file is for —
and not any correlation.
"""
from __future__ import annotations

import random
import statistics as st
import sys

from src import db
from src.context import calibrate as cal
from src.context import leash, sim
from src.context.sources import rates as rate_src

_Q = """
select p.player_name nm, p.pitches pit, p.outs_recorded o,
       p.k, p.bb, p.hr, p.h, p.hbp
from mlb_pitching p join games g on g.game_id = p.game_id
where g.sport = 'mlb' and g.status = 'Final' and p.is_starter = 1
  and p.outs_recorded > 0
"""

BUCKETS = ((0, 8), (9, 11), (12, 14), (15, 17), (18, 20), (21, 27))


def real_by_pitcher(keep):
    by: dict = {}
    with db.connect() as c:
        for r in c.execute(_Q):
            if r["nm"] in keep:
                by.setdefault(r["nm"], []).append(dict(r))
    return {k: v for k, v in by.items() if len(v) >= 8}


def terciles(by):
    """{pitcher: 0|1|2} by his own season K per batter faced."""
    rate = {}
    for nm, rows in by.items():
        bf = sum((r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
                 + (r["hbp"] or 0) for r in rows)
        rate[nm] = sum(r["k"] or 0 for r in rows) / max(bf, 1)
    order = sorted(rate, key=lambda n: rate[n])
    n = len(order)
    out = {}
    for i, nm in enumerate(order):
        out[nm] = 0 if i < n // 3 else (1 if i < 2 * n // 3 else 2)
    return out, rate


def main(argv):
    draws = int(argv[0]) if argv else 12
    keep = leash.intended_starters()
    by = real_by_pitcher(keep)
    grp, rate = terciles(by)
    names = {0: "contact  (low K)", 1: "middle", 2: "power (high K)"}

    real = {g: {"o": 0, "p": 0, "k": 0, "n": 0, "outs": []} for g in range(3)}
    for nm, rows in by.items():
        g = grp[nm]
        for r in rows:
            real[g]["o"] += r["o"] or 0
            real[g]["p"] += r["pit"] or 0
            real[g]["k"] += r["k"] or 0
            real[g]["n"] += 1
            real[g]["outs"].append(r["o"] or 0)

    lg = sim.league()
    pens = rate_src.bullpens(lg)
    rng = random.Random(0)
    simd = {g: {"o": 0, "p": 0, "k": 0, "n": 0, "outs": []} for g in range(3)}
    for pair in cal.paired_cases().values():
        for _ in range(draws):
            r = cal.replay(pair, lg, pens, rng)
            for case, line in zip(pair, (r.away_sp, r.home_sp)):
                nm = case[0]["player_name"]
                g = grp.get(nm)
                if g is None or line.outs <= 0:
                    continue
                simd[g]["o"] += line.outs
                simd[g]["p"] += line.pitches
                simd[g]["k"] += line.k
                simd[g]["n"] += 1
                simd[g]["outs"].append(line.outs)

    print(f"\n  {'group':<18}{'arms':>6}{'K/BF':>8}"
          f"{'outs A':>9}{'outs S':>9}{'d':>7}"
          f"{'p/out A':>10}{'p/out S':>10}{'d':>8}")
    for g in range(3):
        arms = [n for n in grp if grp[n] == g]
        a, s = real[g], simd[g]
        oa, os_ = st.mean(a["outs"]), st.mean(s["outs"])
        pa, ps = a["p"] / a["o"], s["p"] / s["o"]
        print(f"  {names[g]:<18}{len(arms):>6}"
              f"{st.mean(rate[n] for n in arms):>8.3f}"
              f"{oa:>9.2f}{os_:>9.2f}{os_-oa:>+7.2f}"
              f"{pa:>10.2f}{ps:>10.2f}{(ps/pa-1):>+8.1%}")

    print(f"\n  {'group':<18}{'K/start A':>11}{'K/start S':>11}{'d':>7}"
          f"   share of starts at 21+ outs (A / S)")
    for g in range(3):
        a, s = real[g], simd[g]
        ka, ks = a["k"] / a["n"], s["k"] / s["n"]
        la = sum(1 for v in a["outs"] if v >= 21) / len(a["outs"])
        ls = sum(1 for v in s["outs"] if v >= 21) / len(s["outs"])
        print(f"  {names[g]:<18}{ka:>11.2f}{ks:>11.2f}{ks-ka:>+7.2f}"
              f"        {la:>6.1%} / {ls:>5.1%}")

    print(f"\n  outs DISTRIBUTION by group, actual vs simulated")
    print(f"  {'group':<18}" + "".join(f"{f'{lo}-{hi}':>13}"
                                       for lo, hi in BUCKETS))
    for g in range(3):
        for lbl, d in (("A", real[g]), ("S", simd[g])):
            row = "".join(
                f"{sum(1 for v in d['outs'] if lo <= v <= hi)/len(d['outs']):>13.1%}"
                for lo, hi in BUCKETS)
            print(f"  {(names[g] + ' ' + lbl) if lbl == 'A' else '  ' + lbl:<18}"
                  + row)


if __name__ == "__main__":
    main(sys.argv[1:])
