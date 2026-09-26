"""TODO 45, PRE-REGISTERED GATE 1 — over how many SWINGS does whiff/swing
become trustworthy?

The item says it in order: "(1) a split-half stability gate on whiff
itself, as `stabilise.py` does it -- over how many SWINGS does it become
trustworthy is a constant to be COUNTED, not chosen; (2) the four folds,
bar set before running; (3) only then the wiring."

None of the three had been run. This is (1). It matters more than the
6-sigma bivariate does, because a predictor that does not repeat cannot
carry a per-arm term however well it fits in sample -- that is exactly
how per-pitcher and per-club DISPERSION died (split-half 0.07 over 107
arms, powered to see 0.32).

METHOD. Within a pitcher-season, alternate starts into two halves, so
each half sees the same arm at the same age against a similar schedule.
Correlate half A's whiff/swing against half B's, in buckets of total
swings. Train rows only. Reported beside the same split for the OBSERVED
K rate, which is the thing whiff would have to beat, and beside a
SHUFFLE control that must read ~0.
"""
import json
import math
import pathlib
import random
from collections import defaultdict

from src.context import store
from src.context.holdout import HOLDOUT

STARTS = "scratchpad/whiff_starts.json"
BUCKETS = [(0, 150), (150, 250), (250, 400), (400, 600), (600, 900),
           (900, 10 ** 9)]


def corr(pairs):
    n = len(pairs)
    if n < 12:
        return None, n
    ma = sum(a for a, _ in pairs) / n
    mb = sum(b for _, b in pairs) / n
    num = sum((a - ma) * (b - mb) for a, b in pairs)
    den = math.sqrt(sum((a - ma) ** 2 for a, _ in pairs)
                    * sum((b - mb) ** 2 for _, b in pairs))
    return (num / den if den else None), n


def spearman_brown(r):
    """Half-length r -> full-length reliability."""
    return 2 * r / (1 + r) if r is not None and r > -1 else None


def main():
    if not pathlib.Path(STARTS).exists():
        raise SystemExit(
            f"{STARTS} is missing -- it is a 1.8MB intermediate and is not\n"
            "committed. Rebuild it from the play-by-play cache first:\n"
            "    venv/bin/python -m scratchpad.whiff_build")
    rows = json.load(open(STARTS))
    with store.connect() as c:
        dates = {r["game_id"]: r["date"] for r in c.execute(
            "select game_id, date from bets.games where sport='mlb'")}

    by_ps = defaultdict(list)
    for r in rows:
        d = dates.get(f"mlb-{r['pk']}")
        if not d or d >= HOLDOUT:
            continue
        by_ps[(r["name"], d[:4])].append(r)

    print(f"{len(by_ps)} pitcher-seasons, train rows only (< {HOLDOUT})\n")
    print(f"{'swings':>12s} {'n':>5s} {'whiff/swing':>12s} {'K/BF':>9s}"
          f" {'shuffle':>9s}")

    rng = random.Random(11)
    for lo, hi in BUCKETS:
        wp, kp, sp = [], [], []
        for (nm, ss), st in by_ps.items():
            if len(st) < 4:
                continue
            sw_tot = sum(s["sw"] for s in st)
            if not (lo <= sw_tot < hi):
                continue
            a = st[0::2]
            b = st[1::2]
            for half in (a, b):
                if sum(s["sw"] for s in half) < 20 or \
                        sum(s["bf"] for s in half) < 20:
                    break
            else:
                wa = sum(s["wh"] for s in a) / sum(s["sw"] for s in a)
                wb = sum(s["wh"] for s in b) / sum(s["sw"] for s in b)
                ka = sum(s["k"] for s in a) / sum(s["bf"] for s in a)
                kb = sum(s["k"] for s in b) / sum(s["bf"] for s in b)
                wp.append((wa, wb))
                kp.append((ka, kb))
                sp.append((wa, rng.random()))
        rw, n = corr(wp)
        rk, _ = corr(kp)
        rs, _ = corr(sp)
        if rw is None:
            print(f"{f'{lo}-{hi}':>12s} {n:5d}   (thin)")
            continue
        lab = f"{lo}-{hi if hi < 10**9 else ''}"
        print(f"{lab:>12s} {n:5d} {rw:12.3f} {rk:9.3f} {rs:9.3f}")

    # pooled, and the Spearman-Brown lift to a full season
    allw, allk = [], []
    for (nm, ss), st in by_ps.items():
        if len(st) < 4:
            continue
        a, b = st[0::2], st[1::2]
        if min(sum(s["sw"] for s in a), sum(s["sw"] for s in b)) < 20:
            continue
        allw.append((sum(s["wh"] for s in a) / sum(s["sw"] for s in a),
                     sum(s["wh"] for s in b) / sum(s["sw"] for s in b)))
        allk.append((sum(s["k"] for s in a) / sum(s["bf"] for s in a),
                     sum(s["k"] for s in b) / sum(s["bf"] for s in b)))
    rw, n = corr(allw)
    rk, _ = corr(allk)
    print(f"\npooled  n={n}")
    print(f"  whiff/swing  half-split r {rw:.3f}   "
          f"full-season reliability {spearman_brown(rw):.3f}")
    print(f"  K/BF         half-split r {rk:.3f}   "
          f"full-season reliability {spearman_brown(rk):.3f}")
    print("\nTHE BAR: dispersion died at split-half 0.07 (powered to see "
          "0.32).\nA predictor carrying a per-arm term wants reliability "
          "comparable to\nthe rate it is meant to correct, which is the "
          "K/BF column.")


if __name__ == "__main__":
    main()
