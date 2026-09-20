"""TTO decay: familiarity or fatigue? PAIRED WITHIN THE SAME START.

    venv/bin/python -m scratchpad.tto_fatigue [max_games]

WHY THE 2-D TABLE IN `tto_vs_pitches.py` CANNOT SETTLE IT. Bucketing on
raw pitch count selects on pitcher STYLE in both directions at once: a man
who is only at 35 pitches in his second pass is efficient, which means
contact, which means low strikeouts — so the TTO gradient inside a pitch
bucket is part familiarity and part "efficient pitchers miss fewer bats".
Read the other way, a man at 90 pitches by the third pass got there by
missing bats, so the fatigue read is biased the opposite way. Both columns
are contaminated and neither is quotable.

THE CLEAN DESIGN. Compare a starter against HIMSELF on the SAME DAY —
his first-pass K% against his third-pass K% — which holds pitcher, day,
opponent and style fixed by construction. Then stratify those PAIRED
DECAYS by how many pitches he had actually thrown by the third pass.

    if the decay is FATIGUE   -> starts that arrive at the third pass on
                                 high pitch counts decay MORE
    if it is FAMILIARITY      -> the decay is flat across pitch counts,
                                 because the third time through is the
                                 third time through either way

Same nine men in both buckets is NOT enforced here — `tto.py` already
shows that control barely moves the number, and requiring it would cut the
sample that the stratification needs.
"""
from __future__ import annotations

import multiprocessing as mp
import statistics as st
import sys
from collections import defaultdict

from src import db
from src.context.sources import pbp

K_EV = {"strikeout", "strikeout_double_play", "strikeout_triple_play"}
PA_EV = K_EV | {
    "walk", "single", "double", "triple", "home_run", "hit_by_pitch",
    "field_out", "force_out", "grounded_into_double_play", "sac_fly",
    "field_error", "fielders_choice", "fielders_choice_out",
    "double_play", "triple_play", "sac_fly_double_play", "other_out"}


def _one(gid):
    """-> [(k1, n1, k3, n3, pitches_at_third)] per starter."""
    try:
        d = pbp.fetch(gid)
    except Exception:
        return None
    if not d:
        return None
    starter, bf, pitches = {}, defaultdict(int), defaultdict(int)
    rows = defaultdict(list)
    p_at_3 = {}
    for play in d.get("allPlays") or []:
        ab = play.get("about") or {}
        side = "away" if ab.get("isTopInning") else "home"
        pid = ((play.get("matchup") or {}).get("pitcher") or {}).get("id")
        if pid is None:
            continue
        starter.setdefault(side, pid)
        if pid != starter[side]:
            continue
        ev = (play.get("result") or {}).get("eventType") or ""
        n_pitch = sum(1 for e in (play.get("playEvents") or [])
                      if e.get("isPitch"))
        if ev in PA_EV:
            tto = bf[side] // 9 + 1
            if tto == 3 and side not in p_at_3:
                p_at_3[side] = pitches[side]
            rows[side].append((tto, ev in K_EV))
            bf[side] += 1
        pitches[side] += n_pitch
    out = []
    for side, rs in rows.items():
        first = [k for t, k in rs if t == 1]
        third = [k for t, k in rs if t == 3]
        # Enough of both passes to form a rate at all.
        if len(first) < 9 or len(third) < 6 or side not in p_at_3:
            continue
        out.append((sum(first), len(first), sum(third), len(third),
                    p_at_3[side]))
    return out


def main(argv):
    cap = int(argv[0]) if argv else 2000
    with db.connect() as c:
        gids = [r["game_id"] for r in c.execute(
            "select game_id from games where sport='mlb' and status='Final'"
            " and date like '2026%' order by date")][:cap]
    with mp.get_context("fork").Pool(8) as p:
        got = [g for g in p.map(_one, gids, chunksize=16) if g]
    starts = [s for g in got for s in g]
    print(f"  {len(starts):,} starts that reached a third time through\n")

    k1 = sum(s[0] for s in starts) / sum(s[1] for s in starts)
    k3 = sum(s[2] for s in starts) / sum(s[3] for s in starts)
    print(f"  POOLED   first pass K% {100*k1:.2f}   third pass K% "
          f"{100*k3:.2f}   decay {100*(k1-k3):+.2f}pp "
          f"({k3/k1 - 1:+.1%})\n")

    # STRATIFY THE PAIRED DECAY BY PITCH COUNT ON ARRIVAL AT THE THIRD PASS.
    bands = ((0, 59), (60, 69), (70, 79), (80, 200))
    print(f"  {'pitches at 3rd':<18}{'starts':>8}{'K% 1st':>9}{'K% 3rd':>9}"
          f"{'decay pp':>11}{'rel':>9}")
    rows = []
    for lo, hi in bands:
        sel = [s for s in starts if lo <= s[4] <= hi]
        if len(sel) < 40:
            continue
        a = sum(s[0] for s in sel) / sum(s[1] for s in sel)
        b = sum(s[2] for s in sel) / sum(s[3] for s in sel)
        rows.append((lo, hi, len(sel), a, b))
        print(f"  {f'{lo}-{hi}':<18}{len(sel):>8,}{100*a:>9.2f}{100*b:>9.2f}"
              f"{100*(a-b):>+11.2f}{b/a - 1:>+9.1%}")

    if len(rows) >= 2:
        lo_row, hi_row = rows[0], rows[-1]
        d_lo = lo_row[3] - lo_row[4]
        d_hi = hi_row[3] - hi_row[4]
        # se on the difference of two paired decays, binomial per cell.
        def se(sel_lo, sel_hi):
            tot = 0.0
            for r in (sel_lo, sel_hi):
                lo2, hi2 = r[0], r[1]
                sel = [s for s in starts if lo2 <= s[4] <= hi2]
                for i, j in ((0, 1), (2, 3)):
                    n = sum(s[j] for s in sel)
                    p = sum(s[i] for s in sel) / n
                    tot += p * (1 - p) / n
            return tot ** 0.5
        s = se(lo_row, hi_row)
        print(f"\n  DECAY at the LOWEST pitch band  {100*d_lo:+.2f}pp")
        print(f"  DECAY at the HIGHEST pitch band {100*d_hi:+.2f}pp")
        print(f"  difference {100*(d_hi - d_lo):+.2f}pp   se {100*s:.2f}pp"
              f"   z {(d_hi - d_lo)/s:+.2f}")
        print("\n  A POSITIVE, SIGNIFICANT difference means the men who")
        print("  arrive tired decay more -> FATIGUE. Flat means the third")
        print("  time through is the third time through -> FAMILIARITY,")
        print("  and `TTO_MULT` is keyed on the right variable.")


if __name__ == "__main__":
    main(sys.argv[1:])
