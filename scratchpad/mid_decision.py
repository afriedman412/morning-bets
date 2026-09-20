"""THE MID-INNING RELIEF HOOK IS KEYED ONE PLATE APPEARANCE STALE — TODO 23.

    venv/bin/python -m scratchpad.mid_decision [--emit] [limit_games]

QUESTION. `pen_short.py` says 29.2% of simulated relief outings are two outs
or fewer against a real 22.3%, and splits that gap: about a fifth of it is
the entry mix and the rest is the hook. WITHIN AN ENTRY STATE the excess is
unambiguous, because an arm who was not pulled mid-inning records exactly
the outs his inning owed:

    outings ending SHORT OF THE ENTRY INNING (a mid-inning pull, and
    nothing else can produce them)

      entered with 0 out, <= 2 outs recorded     real 12.3%   sim 17.4%
      entered with 1 out, <= 1 out  recorded     real  5.9%   sim  8.3%
      entered with 2 out,    0 outs recorded     real  1.1%   sim  2.2%

    +41%, +41%, +100%. A uniform relative excess across three independent
    populations is a rate that is too high, not three separate defects
    (rule 10).

HYPOTHESIS. `relief.RELIEF_MID_REMOVAL` and `relief.MID_INTENT` are keyed
[runs allowed so far][batters faced so far], and the two halves disagree
about when "so far" is:

    THE COUNT (`relief.removal_hazard`, `scratchpad/mid_intent.py`) keys the
    decision on `runs_before` / `batters_before` — the state before the play
    it is standing on — and only advances the accumulators afterwards. So
    the row labelled "3 batters faced" is really the decision taken after
    his FOURTH.

    THE ENGINE (`game._half_inning`) calls `relief.mid_removal(rl.runs,
    rl.batters)` after `sim.apply_pa` has already incremented both. So it
    asks the table for the state AT the decision.

The engine is the one that is semantically right — a manager decides having
watched the plate appearance, which is also how `boundary.decisions` counts
the starter's hook. The TABLE is mis-specified, and the error is not
harmless because the hazard has a cliff in it: 1.5% for the early batters
and 9.9% at the peak. Being one batter early charges the arm the peak rate
for a decision reality charges 1.5% at, which is about +8 points of pull
probability over an outing.

TEST. One walk, both conventions, same rows:

    STALE      (runs_before, batters_before)          what shipped
    DECISION   (runs_before + runs on this play,      what the engine asks
                batters_before + 1)

POSITIVE CONTROL, and it is what makes the DECISION column readable: the
STALE column is counted by this file's own code on this file's own rows, so
it must REPRODUCE the shipped `MID_INTENT` cell for cell. If it does not,
the walk is wrong and neither column means anything.

POWER, before the result. ~38,000 in-inning relief plate appearances before
`HOLDOUT`; the peak cell (entered 7+, 0 runs, 4-6 batters) carries several
thousand, so its standard error is ~0.4 points against a predicted move of
about 3 points. Well powered on the cells that matter and thin in the deep
early-entry cells, which is why `MIN_CELL` and the marginal fallback exist.

TRAIN ROWS ONLY, both columns (rule 6). Note the shipped FLAT table was
counted over every game including the holdout; this counts it before the
cutoff, so its two columns differ by population as well as convention. The
intent tables were already train-only and are a clean convention A/B.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

from src.context import relief
from src.context.holdout import HOLDOUT
from src.context.sources import pbp

#: Same floor `mid_intent.py` ships with — under this a rate is a rumour.
MIN_CELL = 200

CACHE = "scratchpad/mid_decision_counts.json"

DEPTH = ((0, 2, "1-3"), (3, 5, "4-6"), (6, 8, "7-9"), (9, 11, "10-12"),
         (12, 14, "13-15"), (15, 17, "16-18"), (18, 99, "19+"))


def depth_bin(batters: int) -> str:
    for lo, hi, lbl in DEPTH:
        if lo <= batters <= hi:
            return lbl
    return "19+"


def count(limit=None, verbose=True) -> dict:
    """Tally every in-inning relief plate appearance under both conventions.

    The two conventions differ ONLY in which state labels the decision, so
    they walk the same rows and share the same `changed`. Anything that
    moves between them is the offset and nothing else.
    """
    ids = pbp.final_games(before=HOLDOUT)
    if limit:
        ids = ids[:limit]
    cells: dict = defaultdict(lambda: [0, 0])
    games = 0
    for gid in ids:
        if not pbp.have(gid):
            continue
        try:
            seq = list(pbp.plays(gid))
        except Exception:
            continue
        games += 1
        # side -> [pid, runs, batters, is_reliever, entry_inning]
        cur: dict = {}
        order: dict = defaultdict(int)
        for i, (play, bases, outs, away, home) in enumerate(seq):
            ab = play.get("about") or {}
            side = "home" if ab.get("isTopInning") else "away"
            pid = ((play.get("matchup") or {}).get("pitcher") or {}).get("id")
            if not pid:
                continue
            st_ = cur.get(side)
            if st_ is None or st_[0] != pid:
                order[side] += 1
                cur[side] = st_ = [pid, 0, 0, order[side] > 1,
                                   ab.get("inning") or 1]
            runs_before, batters_before, is_rel = st_[1], st_[2], st_[3]
            entry_inning = st_[4]

            nxt = seq[i + 1] if i + 1 < len(seq) else None
            same_half = bool(nxt) and (
                ((nxt[0].get("about") or {}).get("inning") == ab.get("inning"))
                and ((nxt[0].get("about") or {}).get("halfInning")
                     == ab.get("halfInning")))
            changed = False
            if same_half:
                npid = ((nxt[0].get("matchup") or {}).get("pitcher")
                        or {}).get("id")
                changed = bool(npid and npid != pid)

            res = play.get("result") or {}
            scored = ((res.get("awayScore", 0) + res.get("homeScore", 0))
                      - (away + home))

            if is_rel and same_half:
                e = relief.intent_bucket(entry_inning)
                for tag, rr, bb in (
                        ("stale", runs_before, batters_before),
                        ("decision", runs_before + scored, batters_before + 1)):
                    r = min(rr, 3)
                    lbl = depth_bin(bb)
                    d3 = min(bb // 3, 6)
                    flat = min(bb // 3, 3)
                    for key in ((tag, e, r, d3), (tag, e, d3),
                                (tag, "flat", r, flat),
                                (tag, "grid", e, r, lbl)):
                        cells[key][1] += 1
                        cells[key][0] += 1 if changed else 0

            st_[1] += scored
            st_[2] += 1
        if verbose and games % 1000 == 0:
            print(f"  {games:,} games", flush=True)
    return {"games": games, "cells": {k: tuple(v) for k, v in cells.items()}}


def cached(limit=None) -> dict:
    """Full walks only, for the reason `mid_intent.cached` gives.

    A 600-game smoke test of this same walk once showed the depth hazard
    falling away and that was pure noise; a cache that could serve a partial
    walk would make that kind of mistake permanent.
    """
    if limit is None and os.path.exists(CACHE):
        with open(CACHE) as f:
            raw = json.load(f)
        return {"games": raw["games"],
                "cells": {tuple(json.loads(k)): tuple(v)
                          for k, v in raw["cells"].items()}}
    h = count(limit)
    if limit is None:
        with open(CACHE, "w") as f:
            json.dump({"games": h["games"],
                       "cells": {json.dumps(list(k)): list(v)
                                 for k, v in h["cells"].items()}}, f)
    return h


def control(h: dict) -> bool:
    """Does the STALE column reproduce what shipped?

    Cell for cell against `relief.MID_INTENT`, which was counted by
    `mid_intent.py` on the same population under the same convention. A
    mismatch means this walk is not the walk that produced the shipped
    table, and the DECISION column below would be measuring the difference
    between two scripts rather than between two conventions.
    """
    cells, bad, n = h["cells"], [], 0
    for (e, r, d), ship in relief.MID_INTENT.items():
        s, cnt = cells.get(("stale", e, r, d), (0, 0))
        if cnt < MIN_CELL:
            continue
        n += 1
        if abs(s / cnt - ship) > 0.0002:
            bad.append(((e, r, d), s / cnt, ship, cnt))
    print(f"\n  POSITIVE CONTROL — the STALE column against the shipped"
          f" MID_INTENT: {n - len(bad)}/{n} cells reproduce")
    for k, got, ship, cnt in bad[:12]:
        print(f"    {k}  got {got:.4f}  shipped {ship:.4f}   n={cnt:,}")
    return not bad


def report(h: dict) -> None:
    cells = h["cells"]
    labels = [d[2] for d in DEPTH]
    print(f"\n{h['games']:,} games before {HOLDOUT}")
    control(h)

    print("\n  P(replaced before the next batter), by BATTERS FACED, pooled"
          " over runs")
    print(f"    {'entered':<14}{'convention':<11}"
          + "".join(f"{lbl:>10}" for lbl in labels))
    for e, nm in ((0, "inn 1-3"), (1, "inn 4-6"), (2, "inn 7+")):
        for tag in ("stale", "decision"):
            row = f"    {nm if tag == 'stale' else '':<14}{tag:<11}"
            for lbl in labels:
                s, n = cells.get((tag, "grid", e, 0, lbl), (0, 0))
                row += (f"{(s/n):>9.1%} " if n >= MIN_CELL
                        else f"{'-':>10}")
            print(row)

    print("\n  THE SHIFT, on the cells the engine actually spends its time"
          " in\n    (intent, runs, depth-bucket) -> shipped / recounted")
    moved = []
    for (e, r, d), ship in sorted(relief.MID_INTENT.items()):
        s, n = cells.get(("decision", e, r, d), (0, 0))
        if n < MIN_CELL:
            continue
        moved.append((ship - s / n, (e, r, d), ship, s / n, n))
    moved.sort()
    for delta, k, ship, got, n in moved[:6] + moved[-6:]:
        se = (got * (1 - got) / n) ** 0.5
        print(f"    {str(k):<14} {ship:6.2%} -> {got:6.2%}   {-delta:+6.2%}"
              f"   se {se:.2%}   n={n:>6,}")

    s0, n0 = cells.get(("stale", "flat", 0, 0), (0, 0))
    print(f"\n  POOLED over every in-inning relief plate appearance"
          f" ({n0:,} rows in the modal cell)")
    for tag in ("stale", "decision"):
        tot_s = sum(cells[k][0] for k in cells
                    if k[0] == tag and k[1] == "flat")
        tot_n = sum(cells[k][1] for k in cells
                    if k[0] == tag and k[1] == "flat")
        print(f"    {tag:<10} overall {tot_s/tot_n:.4f}   n={tot_n:,}")


def emit(h: dict) -> None:
    """The shippable literals, DECISION convention, train rows only."""
    cells = h["cells"]
    three, marg, flat = {}, {}, {}
    for e in (0, 1, 2):
        for d in range(7):
            s, n = cells.get(("decision", e, d), (0, 0))
            if n >= MIN_CELL:
                marg[(e, d)] = round(s / n, 4)
            for r in (0, 1, 2, 3):
                s, n = cells.get(("decision", e, r, d), (0, 0))
                if n >= MIN_CELL:
                    three[(e, r, d)] = round(s / n, 4)
    for r in (0, 1, 2, 3):
        for d in range(4):
            s, n = cells.get(("decision", "flat", r, d), (0, 0))
            flat[(r, d)] = round(s / n, 3) if n >= MIN_CELL else None
    print(f"\n# counted on {h['games']:,} games before {HOLDOUT},"
          f" DECISION convention")
    print("RELIEF_MID_REMOVAL = {")
    for r in (0, 1, 2, 3):
        inner = ", ".join(f"{d}: {flat[(r, d)]}" for d in range(4))
        print(f"    {r}: {{{inner}}},")
    print("}")
    print("MID_INTENT = {")
    for k in sorted(three):
        print(f"    {k}: {three[k]},")
    print("}")
    print("MID_INTENT_DEPTH = {")
    for k in sorted(marg):
        print(f"    {k}: {marg[k]},")
    print("}")


def main() -> None:
    limit = next((int(a) for a in sys.argv[1:] if a.isdigit()), None)
    h = cached(limit)
    if "--emit" in sys.argv:
        emit(h)
        return
    report(h)


if __name__ == "__main__":
    main()
