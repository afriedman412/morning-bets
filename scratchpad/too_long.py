"""WHICH STARTS DO WE LEAVE IN TOO LONG? Typified, not aggregated.

    venv/bin/python -m scratchpad.too_long [DUMP.json]

QUESTION    The model's mean start is 15.71 against a real 15.81, so ON
            AVERAGE it is slightly SHORT. But the average hides two errors
            pointing opposite ways. Which starts does it run too long on,
            and what do they have in common?

HYPOTHESIS  The disaster tail. `EARLY_EXIT_DIST` and `early_exit_p` are the
            mixture built for "chased in the third", and they SHIP OFF
            (`early_exit_p = 0.0`), so nothing in the engine produces a
            start that ends because the wheels came off. If that is the
            shape of it, the over-long starts are the ones that REALLY
            ended short, and the residual should collapse as real length
            rises.

            The alternative worth separating: it is about the PITCHER, not
            the game — we leave certain arms in too long regardless of how
            the night went. That is what `leash` exists for, so if it shows
            up here the leash is under-doing its job.

TEST        Per real start, the model's MEAN simulated outs minus the actual
            outs. Bucketed by what actually happened, by how many runs the
            model had him allowing, and listed by pitcher.

Reads a dump from `starts_dump.py`. No simulation here.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict


def main(argv):
    path = argv[0] if argv else "scratchpad/starts_shipped.json"
    d = json.load(open(path))
    c = {k: i for i, k in enumerate(d["cols"])}
    per = defaultdict(list)
    real = {}
    runs = defaultdict(list)
    for r in d["rows"]:
        key = (r[c["pitcher"]], r[c["game_id"]])
        if r[c["real_outs"]] is None:
            continue
        per[key].append(r[c["outs"]])
        runs[key].append(r[c["runs"]])
        real[key] = r[c["real_outs"]]
    rows = [(k, st.mean(v), real[k], st.mean(runs[k]))
            for k, v in per.items()]
    resid = [(m - a, k, m, a, ru) for k, m, a, ru in rows]
    n = len(resid)
    print(f"  {n:,} real starts, {d['sims']} sims each   "
          f"model {st.mean(r[2] for r in resid):.2f} vs real "
          f"{st.mean(r[3] for r in resid):.2f}\n")

    print("  RESIDUAL BY WHAT ACTUALLY HAPPENED  (model mean outs - actual)")
    print(f"  {'real outs':<14}{'n':>6}{'model':>9}{'actual':>9}"
          f"{'residual':>11}")
    bands = ((0, 8), (9, 11), (12, 14), (15, 17), (18, 20), (21, 27))
    for lo, hi in bands:
        sub = [r for r in resid if lo <= r[3] <= hi]
        if not sub:
            continue
        print(f"  {f'{lo}-{hi}':<14}{len(sub):>6}"
              f"{st.mean(r[2] for r in sub):>9.2f}"
              f"{st.mean(r[3] for r in sub):>9.2f}"
              f"{st.mean(r[0] for r in sub):>+11.2f}")

    print("\n  RESIDUAL BY THE RUNS THE MODEL HAD HIM ALLOWING")
    print(f"  {'model runs':<14}{'n':>6}{'residual':>11}")
    for lo, hi in ((0, 1.99), (2, 2.99), (3, 3.99), (4, 99)):
        sub = [r for r in resid if lo <= r[4] <= hi]
        if sub:
            print(f"  {f'{lo:g}-{hi:g}':<14}{len(sub):>6}"
                  f"{st.mean(r[0] for r in sub):>+11.2f}")

    print("\n  THE TEN WE RUN LONGEST ON")
    print(f"  {'pitcher':<22}{'model':>8}{'actual':>8}{'over by':>9}")
    for x in sorted(resid, reverse=True)[:10]:
        print(f"  {str(x[1][0])[:20]:<22}{x[2]:>8.1f}{x[3]:>8.0f}"
              f"{x[0]:>+9.1f}")

    print("\n  BY PITCHER, arms with 3+ starts, worst five")
    byp = defaultdict(list)
    for x in resid:
        byp[x[1][0]].append(x[0])
    worst = sorted(((st.mean(v), len(v), k) for k, v in byp.items()
                    if len(v) >= 3), reverse=True)[:5]
    for m, cnt, k in worst:
        print(f"  {str(k)[:20]:<22}{cnt:>4} starts   mean over by {m:>+5.1f}")


if __name__ == "__main__":
    main(sys.argv[1:])
