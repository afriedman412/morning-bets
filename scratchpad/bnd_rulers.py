"""ARE THE TWO BOUNDARY-SHARE NUMBERS MEASURING THE SAME THING?

    venv/bin/python -m scratchpad.bnd_rulers

QUESTION. `shape.py` reports a real boundary share of 0.674 and
`boundary.py` counted 63.2%. Four points apart, and every conclusion this
session about "the model pulls mid-inning too often" is scaled against
whichever is right. CLAUDE.md: when a new number contradicts an old one,
check they measure the same thing BEFORE acting.

THE TWO DEFINITIONS.
  SHAPE     a start is boundary if `outs % 3 == 0`. Inferred from the
            boxscore line, and it has a known hole: a starter pulled having
            recorded NO outs has outs = 0, which divides by three and
            scores as a clean end of inning. He was chased in the first.
  PBP       the removal event itself, read from play-by-play — the third
            out of an inning was recorded on or before his last play.

TEST. Both, on the same holdout starts, plus the disagreement rate and what
the `outs == 0` hole is worth on its own.
"""
from __future__ import annotations

import sys
from collections import Counter

from src import roster
from src.context import boundary, calibrate as cal

HOLDOUT = "2026-07-01"


def main(argv):
    cap = int(argv[0]) if argv else None
    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    gids = sorted(pairs)[:cap] if cap else sorted(pairs)

    shape_o, pbp_kind, agree = [], Counter(), Counter()
    missing = 0
    for gid in gids:
        try:
            # `exits` keys by MLB player id, the cases by name.
            ex = {e.get("pitcher"): e for e in boundary.exits(gid)}
        except Exception:
            missing += 1
            continue
        for act, _rates, _lineup in pairs[gid]:
            o = act.get("o")
            if o is None:
                continue
            shape_o.append(o)
            e = ex.get(roster.player_id(act.get("player_name")))
            if not e:
                continue
            k = e.get("kind")
            pbp_kind[k] += 1
            agree[(k, "b" if o % 3 == 0 else "m")] += 1

    n = len(shape_o)
    sb = sum(1 for o in shape_o if o % 3 == 0) / n
    zero = sum(1 for o in shape_o if o == 0)
    sb_nz = (sum(1 for o in shape_o if o % 3 == 0 and o > 0)
             / sum(1 for o in shape_o if o > 0))
    tot = sum(pbp_kind.values())
    print(f"  {n:,} holdout starts, {tot:,} matched to a play-by-play exit"
          f"{f', {missing} games unreadable' if missing else ''}\n")
    print(f"  SHAPE rule  (outs % 3 == 0)          {sb:.4f}")
    print(f"  SHAPE rule, dropping outs == 0       {sb_nz:.4f}"
          f"   ({zero} starts, {zero / n:.2%})")
    if tot:
        pb = pbp_kind.get("boundary", 0) / tot
        print(f"  PBP rule    (the removal event)      {pb:.4f}")
        both = sum(agree.values())
        same = agree[("boundary", "b")] + agree[("mid", "m")]
        print(f"\n  the two rules AGREE on {same:,}/{both:,} starts "
              f"({same / both:.2%})")
        print(f"    pbp boundary, shape mid: {agree[('boundary', 'm')]:,}")
        print(f"    pbp mid, shape boundary: {agree[('mid', 'b')]:,}")


if __name__ == "__main__":
    main(sys.argv[1:])
