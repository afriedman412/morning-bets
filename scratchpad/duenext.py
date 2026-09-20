"""Does WHO IS DUE UP belong in the hook? The user's idea, tested.

    venv/bin/python -m scratchpad.duenext

THE HYPOTHESIS, stated before looking: a manager leaves a starter in to face
7-8-9 and takes him out rather than let him face 1-2-3 a fourth time. The
shipped hook has no lineup feature at all — pitches, runs, baserunners,
inning, margin, and nothing about who is coming.

THE CONFOUND, and it is why this cannot be tested on its own. The slot due
up is mechanically tied to how many batters he has faced, which is tied to
pitch count and times through the order — all of which the hook already
reads. So the slot goes in ALONGSIDE the existing features and the question
is whether it adds anything to them, not whether it correlates with removal.

TWO ENCODINGS, because the shape is not obvious and picking after the fact
is how findings get manufactured:

  * TOP-OF-ORDER indicator, slots 1-3, which is the hypothesis as stated.
  * The slot itself, 1-9 linear, which would show a smooth preference.

FITTING TO REMOVAL DECISIONS IS PERMITTED — the target is what the manager
did, not what the game settled at.

BOUNDARY DECISIONS ONLY. Between innings the manager knows exactly who leads
off next; mid-inning the "next batter" is already in the box and the choice
is a different one. 2025+2026, since the hook is era-scoped.
"""
from __future__ import annotations

import concurrent.futures as cf
import glob
import multiprocessing as mp
import os
import statistics as st
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression

from src import db
from src.context import boundary, removal
from src.context.sources import pbp

BASE = ("pitches", "runs", "br", "inning", "margin")
SKIP = boundary.SKIP


def _one(gid):
    """Boundary decisions for one game, tagged with the slot due up next."""
    try:
        rows = [r for r in boundary.decisions(gid) if r["ends_inning"]]
        d = pbp.fetch(gid)
    except Exception:
        return []
    if not rows or not d:
        return []
    plays = [p for p in (d.get("allPlays") or [])
             if ((p.get("result") or {}).get("eventType") or "") not in SKIP]

    # Batting order: the first nine distinct batters a side sends up are
    # slots 1-9. Derived rather than joined so a missing lineup row cannot
    # silently drop a game.
    order, seq = {}, {}
    for p in plays:
        top = bool((p.get("about") or {}).get("isTopInning"))
        bat = "away" if top else "home"
        bid = ((p.get("matchup") or {}).get("batter") or {}).get("id")
        if not bid:
            continue
        o = order.setdefault(bat, {})
        if bid not in o and len(o) < 9:
            o[bid] = len(o) + 1
        seq.setdefault(bat, []).append(bid)

    # For each pitching side, the sequence of batters it faced in order.
    out = []
    per_side = {}
    for p in plays:
        top = bool((p.get("about") or {}).get("isTopInning"))
        pit = "home" if top else "away"
        bat = "away" if top else "home"
        bid = ((p.get("matchup") or {}).get("batter") or {}).get("id")
        if bid:
            per_side.setdefault(pit, []).append((bat, bid))
    for r in rows:
        side = r["side"]
        lst = per_side.get(side) or []
        # THE NEXT BATTER IS THE ONE AFTER THE ONES HE HAS FACED, and the
        # row already carries that count. The first version advanced a
        # per-decision counter instead, so it read the Nth batter of the
        # GAME — a proxy for the inning — and produced a beautiful table in
        # which "slots 1-3 due up" averaged 24.8 pitches. The leadoff man
        # comes up in the seventh as often as the first.
        nxt = r["bf"]
        if nxt >= len(lst):
            continue
        bat, bid = lst[nxt]
        slot = (order.get(bat) or {}).get(bid)
        if not slot:
            continue
        r["slot"] = slot
        r["top3"] = 1 if slot <= 3 else 0
        out.append(r)
    return out


def fit(rows, feats, label):
    X = np.array([[float(r[f]) for f in feats] for r in rows])
    y = np.array([1 if r["removed"] else 0 for r in rows])
    m = LogisticRegression(max_iter=8000, C=1e6)
    m.fit(X, y)
    p = m.predict_proba(X)[:, 1]
    ll, auc = removal.log_loss(y, p), removal.auc(y, p)
    print(f"  {label:<22}{ll:>11.5f}{auc:>9.4f}   "
          + "  ".join(f"{f} {c:+.4f}" for f, c in zip(feats, m.coef_[0])
                      if f in ("slot", "top3")))
    return ll, auc


def main(argv):
    with db.connect() as c:
        season = {r["game_id"].split("-")[-1]: r["date"][:4]
                  for r in c.execute(
                      "select game_id, date from games where sport = 'mlb'")}
    gids = [os.path.basename(f).split(".")[0]
            for f in sorted(glob.glob(".cache/pbp/*.json.gz"))]
    gids = [g for g in gids if season.get(g) in ("2025", "2026")]
    workers = max(1, (os.cpu_count() or 4) - 1)
    print(f"  {len(gids):,} games over {workers} workers", flush=True)
    rows = []
    with cf.ProcessPoolExecutor(max_workers=workers,
                                mp_context=mp.get_context("fork")) as pool:
        for got in pool.map(_one, gids, chunksize=32):
            rows += got
    print(f"  {len(rows):,} boundary decisions with a known next slot\n")

    print("  REMOVAL RATE BY THE SLOT DUE UP NEXT — counted, before fitting")
    print(f"  {'slot':<8}{'n':>9}{'pull rate':>12}")
    for s in range(1, 10):
        g = [r for r in rows if r["slot"] == s]
        if len(g) < 100:
            continue
        print(f"  {s:<8}{len(g):>9,}"
              f"{sum(1 for r in g if r['removed']) / len(g):>12.4f}")
    top = [r for r in rows if r["top3"]]
    bot = [r for r in rows if not r["top3"]]
    print(f"  slots 1-3 {sum(1 for r in top if r['removed'])/len(top):.4f}"
          f"   slots 4-9"
          f" {sum(1 for r in bot if r['removed'])/len(bot):.4f}")
    print(f"  mean pitches: 1-3 {st.mean(r['pitches'] for r in top):.1f}"
          f"   4-9 {st.mean(r['pitches'] for r in bot):.1f}"
          f"   <- the confound, in one line")

    print(f"\n  {'model':<22}{'log loss':>11}{'AUC':>9}   added coefficient")
    fit(rows, BASE, "shipped features")
    fit(rows, BASE + ("top3",), "+ top of order")
    fit(rows, BASE + ("slot",), "+ slot 1-9")


if __name__ == "__main__":
    main(sys.argv[1:])
