"""Does a 5-start WHIFF rate beat a 5-start K rate at predicting the rest?

QUESTION. A starter has ~5 major-league starts. Two numbers describe how
he misses bats: the strikeouts he actually recorded, and the whiff rate
underneath them. Which one predicts his NEXT starts, and does whiff add
anything once the observed K rate is in the fit?

HYPOTHESIS UNDER TEST (raised against the Mason Adams board row): the
observed K rate over 5 starts is mostly noise and regresses toward what
the whiffs support, so whiff should dominate.

TEST. Every (pitcher, season) with >= 12 starts. Starts 1-5 give both
predictors; starts 6+ give the target, K/BF. Pearson on each, then a
bivariate OLS to see whether whiff carries anything the K rate does not.

POWER, stated first: n ~ 400 pitcher-seasons, se(r) ~ 1/sqrt(n-3) ~ 0.05.
That resolves "one clearly beats the other", not a 0.02 difference.

POSITIVE CONTROLS, built in: a planted column that is the target plus
noise must come out on top; an independent-noise column must read ~0. A
harness that fails either is not measuring prediction.

TRAINING ROWS ONLY by default: seasons whose games are entirely before
HOLDOUT, plus 2026 rows before it. --all lifts the filter.

    venv/bin/python -m scratchpad.whiff_test [--all] [--first N]
"""
from __future__ import annotations

import json
import math
import random
import sys
from collections import defaultdict

from src.context import store
from src.context.holdout import HOLDOUT

SRC = "scratchpad/whiff_starts.json"


def pearson(xs, ys):
    n = len(xs)
    if n < 4:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def ols2(y, a, b):
    """y ~ c0 + c1*a + c2*b, returned with t-stats. Plain normal equations."""
    n = len(y)
    X = [[1.0, ai, bi] for ai, bi in zip(a, b)]
    XtX = [[sum(X[i][r] * X[i][c] for i in range(n)) for c in range(3)]
           for r in range(3)]
    Xty = [sum(X[i][r] * y[i] for i in range(n)) for r in range(3)]
    # 3x3 inverse
    m = XtX
    det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
           - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
           + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    if abs(det) < 1e-18:
        return None
    inv = [[0.0] * 3 for _ in range(3)]
    for r in range(3):
        for c in range(3):
            r1, r2 = [k for k in range(3) if k != r]
            c1, c2 = [k for k in range(3) if k != c]
            cof = m[c1][r1] * m[c2][r2] - m[c1][r2] * m[c2][r1]
            inv[r][c] = ((-1) ** (r + c)) * cof / det
    beta = [sum(inv[r][c] * Xty[c] for c in range(3)) for r in range(3)]
    resid = [y[i] - sum(beta[r] * X[i][r] for r in range(3)) for i in range(n)]
    s2 = sum(e * e for e in resid) / (n - 3)
    se = [math.sqrt(max(s2 * inv[r][r], 0.0)) for r in range(3)]
    return beta, se


def main():
    allrows = "--all" in sys.argv
    first = 5
    if "--first" in sys.argv:
        first = int(sys.argv[sys.argv.index("--first") + 1])

    rows = json.load(open(SRC))
    with store.connect() as con:
        dates = {r["game_id"].split("-")[-1]: r["date"] for r in con.execute(
            "select game_id, date from bets.games"
            " where sport='mlb' and status='Final'")}

    by = defaultdict(list)
    for r in rows:
        d = dates.get(r["pk"])
        if not d:
            continue
        if not allrows and d >= HOLDOUT:
            continue
        by[(int(d[:4]), r["name"])].append((d, r))

    rng = random.Random(11)
    recs = []
    for key, lst in by.items():
        if len(lst) < first + 7:
            continue
        lst.sort()
        head = [r for _, r in lst[:first]]
        tail = [r for _, r in lst[first:]]
        bf = sum(r["bf"] for r in head)
        sw = sum(r["sw"] for r in head)
        tbf = sum(r["bf"] for r in tail)
        if bf < 60 or sw < 120 or tbf < 200:
            continue
        recs.append({
            "k_obs": sum(r["k"] for r in head) / bf,
            "whiff": sum(r["wh"] for r in head) / sw,
            "future": sum(r["k"] for r in tail) / tbf,
            "n_tail": tbf,
        })
    for r in recs:                       # controls
        r["planted"] = r["future"] + rng.gauss(0, 0.02)
        r["noise"] = rng.gauss(0, 1)

    print(f"  pitcher-seasons: {len(recs)}"
          f"   (first {first} starts -> rest of season)"
          f"{'' if allrows else '   [train rows only, date < ' + HOLDOUT + ']'}")
    if len(recs) < 30:
        print("  too few rows; widen the filters")
        return
    se_r = 1 / math.sqrt(len(recs) - 3)
    print(f"  se(r) ~ {se_r:.3f}\n")

    fut = [r["future"] for r in recs]
    print("  correlation with REST-OF-SEASON K/BF")
    for col, label in (("k_obs", "observed K/BF, first 5"),
                       ("whiff", "whiff/swing, first 5"),
                       ("planted", "PLANTED control (target+noise)"),
                       ("noise", "NOISE control")):
        r = pearson([x[col] for x in recs], fut)
        print(f"    {label:34s} r = {r:+.3f}")

    out = ols2(fut, [r["k_obs"] for r in recs], [r["whiff"] for r in recs])
    if out:
        beta, se = out
        print("\n  BIVARIATE  future ~ k_obs + whiff")
        for nm, b, s in zip(("intercept", "k_obs", "whiff"), beta, se):
            t = b / s if s else float("nan")
            print(f"    {nm:12s} {b:+.4f}  se {s:.4f}  ({t:+.2f} t)")


if __name__ == "__main__":
    main()
