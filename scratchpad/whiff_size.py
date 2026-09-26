"""How much would a whiff term actually move the board?

TWO QUESTIONS, in order:
  1. Does whiff add over the SHRUNK rate the engine ships, or is the
     shrinkage already doing the regression whiff would do? The earlier
     bivariate used the RAW rate, which flatters whiff.
  2. If it survives, how big is the spread across real starters — in K
     per start and in runs, against the ~0.05-run leverage floor.

Train rows only. Positive controls carried through from whiff_test.
"""
from __future__ import annotations

import json
import math
import statistics as st
from collections import defaultdict

from src.context import store, slate
from src.context.holdout import HOLDOUT
from scratchpad.whiff_test import pearson, ols2

SRC = "scratchpad/whiff_starts.json"


def main():
    rows = json.load(open(SRC))
    with store.connect() as con:
        dates = {r["game_id"].split("-")[-1]: r["date"] for r in con.execute(
            "select game_id, date from bets.games"
            " where sport='mlb' and status='Final'")}
    by = defaultdict(list)
    for r in rows:
        d = dates.get(r["pk"])
        if d and d < HOLDOUT:
            by[(int(d[:4]), r["name"])].append((d, r))

    lgk = sum(r["k"] for r in rows) / sum(r["bf"] for r in rows)
    lgw = sum(r["wh"] for r in rows) / sum(r["sw"] for r in rows)

    recs = []
    for lst in by.values():
        if len(lst) < 12:
            continue
        lst.sort()
        head = [r for _, r in lst[:10]]
        tail = [r for _, r in lst[10:]]
        bf = sum(r["bf"] for r in head); sw = sum(r["sw"] for r in head)
        tbf = sum(r["bf"] for r in tail)
        if bf < 150 or sw < 250 or tbf < 200:
            continue
        kobs = sum(r["k"] for r in head) / bf
        w = slate.shrink_weight(bf)          # the SHIPPED shrink weight
        recs.append({
            "k_obs": kobs,
            "k_shrunk": w * kobs + (1 - w) * lgk,
            "whiff": sum(r["wh"] for r in head) / sw,
            "future": sum(r["k"] for r in tail) / tbf,
        })

    print(f"  {len(recs)} pitcher-seasons (first 10 starts -> rest)"
          f"   league K/BF {lgk:.4f}  whiff {lgw:.4f}")
    fut = [r["future"] for r in recs]
    print(f"\n  Q1 — does whiff add over the SHRUNK rate the engine ships?")
    for col, lab in (("k_shrunk", "shrunk K/BF (what we ship)"),
                     ("whiff", "whiff/swing")):
        print(f"    {lab:32s} r = {pearson([r[col] for r in recs], fut):+.3f}")
    out = ols2(fut, [r["k_shrunk"] for r in recs], [r["whiff"] for r in recs])
    beta, se = out
    print("    BIVARIATE  future ~ k_shrunk + whiff")
    for nm, b, s in zip(("intercept", "k_shrunk", "whiff"), beta, se):
        print(f"      {nm:11s} {b:+.4f}  se {s:.4f}  ({b / s:+.2f} t)")

    sdw = st.stdev(r["whiff"] for r in recs)
    print(f"\n  Q2 — size. sd of whiff/swing across starters {sdw:.4f}")
    dr = beta[2] * sdw
    print(f"    one sd of whiff moves K/BF by {dr:.4f}"
          f"  ({dr * 100:.2f} K-rate points)")
    print(f"    over 22 batters: {dr * 22:.3f} K per start")
    # run value: a K replaces an average non-K plate appearance
    RUN_PER_K = 0.30
    print(f"    in runs at ~{RUN_PER_K} run per K-vs-BIP:"
          f" {dr * 22 * RUN_PER_K:.3f} runs per side per start")
    print(f"    leverage floor from scratchpad/leverage.py: ~0.05 runs")

    # how far out the tails go
    ws = sorted(r["whiff"] for r in recs)
    p10, p90 = ws[len(ws) // 10], ws[-len(ws) // 10]
    print(f"\n    p10 whiff {p10:.4f}  p90 {p90:.4f}  spread {p90 - p10:.4f}")
    print(f"    p10->p90 arm differs by {beta[2] * (p90 - p10) * 22:.2f} K"
          f" per start, {beta[2] * (p90 - p10) * 22 * RUN_PER_K:.3f} runs")


if __name__ == "__main__":
    main()
