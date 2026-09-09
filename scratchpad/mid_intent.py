"""IS THE MID-INNING RELIEF HOOK WRONG FOR A BULK ARM? — TODO 15 part two.

    venv/bin/python -m scratchpad.mid_intent [limit_games]

THE DEFECT THIS IS COUNTING. `relief.RELIEF_MID_REMOVAL` is P(this reliever
is replaced before the next batter), counted over 50,023 in-inning relief
plate appearances and applied to EVERY arm. `bulk_shape.py` showed it is
the binding constraint on the arm behind an opener: switching it off moves
that arm from 5.00 outs to 7.03 against a real 7.39. It was counted on a
population of one-inning arms and it runs 7-10% per plate appearance, which
is survivable facing four men and fatal facing twenty.

TWO CANDIDATE DIMENSIONS WENT IN. ONE SURVIVED.

  INTENT — the inning the reliever ENTERED, the same conditioning that
  fixed the continuation hazard (`relief.CONTINUE_INTENT`). A man brought
  in at the top of the second is there to eat innings; a man brought in in
  the eighth is not. **THIS IS THE WHOLE EFFECT** (9,254 games):

    P(replaced before the next batter), batters already faced
                       1-3    4-6    7-9  10-12  13-15  16-18    19+
      entered 1-3     0.5%   3.6%   4.0%   5.6%   8.7%   7.4%  15.0%
      entered 4-6     2.1%  11.7%  11.3%  10.0%   9.5%   9.5%  10.0%
      entered 7+      1.6%  11.5%  12.7%   8.9%      -      -      -
      SHIPPED (r=0)   1.5%   9.9%   7.3%  ------ 7.0% flat ------

  An early-entry arm is roughly THREE TIMES less likely to be pulled
  through the 4-12 batter range, which is exactly where a bulk arm lives
  and exactly where the shipped table charges him 7-10% a plate
  appearance.

  DEPTH — REFUTED, and it is worth recording as a refuted hypothesis
  rather than quietly dropping. The shipped axis caps at `min(batters // 3,
  3)`, so everyone past nine batters sits in one flat cell, and the guess
  was that the real hazard FALLS past the cap (a man still out there is the
  designated long man). It does not: pooled over all relievers it runs
  8.5%, 9.1%, 8.2%, 13.7% and RISES at the end. A 600-game smoke test
  showed it falling to 3.0% and that was sampling noise — the full walk
  killed it. The cap is not the defect.

AND THE BULK CELL IS REDUNDANT. Keyed on "first reliever behind a short
start" the row reads 0.3 / 3.6 / 3.5 / 4.8 / 8.4 / 7.2 / 15.4 — within
noise of the intent-bucket-0 row above. So this ships as ONE new
dimension, not two, and no special case for the opener.

TRAIN ROWS ONLY (rule 6): `pbp.final_games(before=HOLDOUT)`. Note the
shipped table was counted without that filter, an inconsistency this does
not propagate.

POWER, stated before the result: ~1,200 bulk-arm stints over four seasons
at ~15 plate appearances each is ~18,000 PAs, so the deep cells are thin
but not empty. Every rate prints its own n and anything under `MIN_CELL`
is display only.
"""
from __future__ import annotations

import sys
from collections import defaultdict

from src.context import relief
from src.context.holdout import HOLDOUT
from src.context.sources import pbp

LIMIT = (int(sys.argv[1])
         if len(sys.argv) > 1 and sys.argv[1].isdigit() else None)

#: A cell below this is not counted, it is a rumour. Printed either way so
#: the thinness is visible rather than hidden behind a dash.
MIN_CELL = 200

#: Batter-depth bins.
DEPTH = ((0, 2, "1-3"), (3, 5, "4-6"), (6, 8, "7-9"), (9, 11, "10-12"),
         (12, 14, "13-15"), (15, 17, "16-18"), (18, 99, "19+"))


def depth_bin(batters: int) -> str:
    for lo, hi, lbl in DEPTH:
        if lo <= batters <= hi:
            return lbl
    return "19+"


def count(limit=None, verbose=True) -> dict:
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
        # side -> [pid, runs, batters, is_reliever, entry_inning, starter_outs]
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
                                   ab.get("inning") or 1, order[side] == 2]
            runs_before, batters_before, is_rel = st_[1], st_[2], st_[3]
            entry_inning, first_rel = st_[4], st_[5]
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

            if is_rel and same_half:
                e = relief.intent_bucket(entry_inning)
                d = depth_bin(batters_before)
                r = min(runs_before, 3)
                for key in ((e, d), (None, d), (e, None), (r, d, "runs"),
                            (e, r, d),
                            ("bulk", d) if (first_rel and e == 0) else None):
                    if key is None:
                        continue
                    cells[key][1] += 1
                    cells[key][0] += 1 if changed else 0

            # ADVANCE THIS PITCHER'S OWN ACCUMULATORS PAST THE PLAY. Leaving
            # this out puts every plate appearance in the first depth bin and
            # produces a table that looks plausible and says nothing.
            res = play.get("result") or {}
            st_[1] += ((res.get("awayScore", 0) + res.get("homeScore", 0))
                       - (away + home))
            st_[2] += 1
        if verbose and games % 1000 == 0:
            print(f"  {games:,} games", flush=True)
    return {"games": games, "cells": {k: tuple(v) for k, v in cells.items()}}


def report(h: dict) -> None:
    cells = h["cells"]
    labels = [d[2] for d in DEPTH]
    print(f"\n{h['games']:,} games before {HOLDOUT}\n")

    print("  P(replaced before the next batter) BY DEPTH — the shipped table")
    print("  caps at 9+ and holds it flat. Does reality?")
    print(f"    {'batters faced':<16}"
          + "".join(f"{lbl:>10}" for lbl in labels))
    row = "    " + f"{'all relievers':<16}"
    for lbl in labels:
        s, n = cells.get((None, lbl), (0, 0))
        row += f"{(s/n if n else 0):>9.1%} " if n >= 200 else f"{'-':>10}"
    print(row)
    for e, nm in ((0, "entered inn 1-3"), (1, "entered inn 4-6"),
                  (2, "entered inn 7+")):
        row = "    " + f"{nm:<16}"
        for lbl in labels:
            s, n = cells.get((e, lbl), (0, 0))
            row += f"{(s/n if n else 0):>9.1%} " if n >= 200 else f"{'-':>10}"
        print(row)
    row = "    " + f"{'BULK (1st rel)':<16}"
    for lbl in labels:
        s, n = cells.get(("bulk", lbl), (0, 0))
        row += f"{(s/n if n else 0):>9.1%} " if n >= 200 else f"{'-':>10}"
    print(row)

    print(f"\n    {'n, all relievers':<16}"
          + "".join(f"{cells.get((None, lbl), (0, 0))[1]:>10,}"
                    for lbl in labels))
    print(f"    {'n, bulk':<16}"
          + "".join(f"{cells.get(('bulk', lbl), (0, 0))[1]:>10,}"
                    for lbl in labels))

    print("\n  SHIPPED, for comparison (runs=0 row, the modal case)")
    print("    1-3 batters 1.5%   4-6 9.9%   7-9 7.3%   10+ 7.0% (flat)")

    # DOES RUNS STILL EARN A CELL ONCE INTENT IS IN? The shipped table
    # carries it, and a dimension that stops paying its way inside a new
    # conditioning is exactly how a table gets too thin to trust.
    print("\n  (intent, runs, depth) — cells under MIN_CELL are display only")
    for e, nm in ((0, "entered 1-3"), (1, "entered 4-6"), (2, "entered 7+")):
        print(f"    {nm}")
        for r in (0, 1, 2, 3):
            row = f"      {r}{'+' if r == 3 else ' '} runs  "
            for lbl in labels:
                s, n = cells.get((e, r, lbl), (0, 0))
                row += (f"{(s/n):>7.1%}({n:>5,})" if n >= MIN_CELL
                        else f"{'-':>7}({n:>5,})")
            print(row)


CACHE = "scratchpad/mid_intent_counts.json"


def cached(limit=None) -> dict:
    """The walk is ~6 minutes, so it is cached — but ONLY the full walk.

    A limited run is a smoke test and must never land in the cache: the
    600-game version of this count showed the depth hazard falling away and
    that was noise, so a cache that could serve a partial walk would make
    exactly that mistake permanent.
    """
    import json
    import os
    if limit is None and os.path.exists(CACHE):
        with open(CACHE) as f:
            raw = json.load(f)
        return {"games": raw["games"],
                "cells": {tuple(json.loads(k)): tuple(v)
                          for k, v in raw["cells"].items()}}
    h = count(limit)
    if limit is None:
        import json as _j
        with open(CACHE, "w") as f:
            _j.dump({"games": h["games"],
                     "cells": {_j.dumps(list(k)): list(v)
                               for k, v in h["cells"].items()}}, f)
    return h


def emit(h: dict) -> None:
    """Print the shippable literals for `relief.py`.

    FALLBACK HIERARCHY, and it is the whole reason this is not one table:
    the three-way cell is thin exactly where the new dimension matters
    most (an early entry with runs allowed), so a cell under `MIN_CELL`
    falls through to the (intent, depth) marginal rather than shipping a
    rate counted on forty rows. Anything with no adequate cell at either
    level falls through to the shipped flat table at serve time.
    """
    cells = h["cells"]
    labels = [d[2] for d in DEPTH]
    three, marg = {}, {}
    for e in (0, 1, 2):
        for di, lbl in enumerate(labels):
            s, n = cells.get((e, lbl), (0, 0))
            if n >= MIN_CELL:
                marg[(e, di)] = round(s / n, 4)
            for r in (0, 1, 2, 3):
                s, n = cells.get((e, r, lbl), (0, 0))
                if n >= MIN_CELL:
                    three[(e, r, di)] = round(s / n, 4)
    print(f"\n# counted on {h['games']:,} games before {HOLDOUT}")
    print(f"MID_INTENT = {{")
    for k in sorted(three):
        print(f"    {k}: {three[k]},")
    print("}")
    print(f"MID_INTENT_DEPTH = {{")
    for k in sorted(marg):
        print(f"    {k}: {marg[k]},")
    print("}")


def main() -> None:
    h = cached(LIMIT)
    if "--emit" in sys.argv:
        emit(h)
        return
    report(h)


if __name__ == "__main__":
    main()
