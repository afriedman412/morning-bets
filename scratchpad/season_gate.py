"""One pass over the play-by-play, per season: TTO and the double-play rate.

    venv/bin/python -m scratchpad.season_gate

WHY BOTH IN ONE PASS. Each is a single-core walk over 9,962 cached games and
neither forks, so running them separately is two walks for no reason. This
is also deliberately gentle on the machine — one core, `nice`-able — after a
day of eight-way forks.

WHY PER SEASON AT ALL. Both modules query "every game on disk" with no season
filter, so what they measure changed silently when three seasons of history
landed. `stabilise` demonstrated the cost: pooled, its odd/even split spans
years and reads a player CHANGING as a player being UNRELIABLE, inflating
every constant. TTO and the double-play rate do not have that specific
defect — neither is a within-player reliability measure — but they can still
carry an era difference, and the hook has already proved 2023/24 is a
different league on manager behaviour.

So the question here is narrow and the answer decides whether pooling is
allowed: does each quantity hold still across four seasons?
"""
from __future__ import annotations

import glob
import os
import sys
from collections import defaultdict

from src import db
from src.context import advance, tto
from src.context.sources import pbp

BIP_OUT = {"field_out", "force_out", "fielders_choice_out",
           "grounded_into_double_play", "double_play", "triple_play"}


def seasons() -> dict[str, str]:
    with db.connect() as c:
        return {r["game_id"].split("-")[-1]: r["date"][:4]
                for r in c.execute(
                    "select game_id, date from games where sport = 'mlb'")}


def main(argv):
    season = seasons()
    gids = [os.path.basename(f).split(".")[0]
            for f in sorted(glob.glob(".cache/pbp/*.json.gz"))]
    gids = [g for g in gids if g in season]
    print(f"  {len(gids):,} games, one pass, single core", flush=True)

    # TTO: {season: {pass: {bucket: n}}}
    t: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    # DP: {season: {outs: [dp, bip_outs]}}
    d: dict = defaultdict(lambda: defaultdict(lambda: [0, 0]))

    for i, g in enumerate(gids):
        yr = season[g]
        try:
            data = pbp.fetch(g)
            if not data:
                continue
            for r in tto.start_passes(g, data):
                t[yr][r["pass"]][r["event"]] += 1
            # The double play is counted in the MODEL'S OWN DENOMINATOR —
            # per ball-in-play out, with a man on first and under two out,
            # which is the only state `sim` ever rolls it in. Counting per
            # opportunity instead is the -99 sigma line in `advance`, and it
            # is a units mismatch rather than a finding.
            for play, bases, outs, _a, _h in pbp.plays(g, data):
                ev = ((play.get("result") or {}).get("eventType") or "")
                if ev not in BIP_OUT or not bases[0] or outs >= 2:
                    continue
                d[yr][outs][1] += 1
                if ev in advance.DP:
                    d[yr][outs][0] += 1
        except Exception:
            continue
        if (i + 1) % 2000 == 0:
            print(f"    {i+1:,}/{len(gids):,}", flush=True)

    print("\n  TIMES THROUGH THE ORDER — K% by pass, per season")
    print(f"  {'season':<9}{'pass1':>9}{'pass2':>9}{'pass3':>9}"
          f"{'p3/p1':>9}{'n':>10}")
    for yr in sorted(t):
        ks = []
        n = 0
        for p in (1, 2, 3):
            cell = t[yr][p]
            tot = sum(cell.values())
            n = max(n, tot)
            ks.append(cell.get("k", 0) / tot if tot else 0.0)
        print(f"  {yr:<9}{ks[0]:>9.4f}{ks[1]:>9.4f}{ks[2]:>9.4f}"
              f"{(ks[2]/ks[0] if ks[0] else 0):>9.4f}{n:>10,}")

    print("\n  DOUBLE PLAY per ball-in-play out, man on first, per season")
    print(f"  {'season':<9}{'0 out':>9}{'n':>9}{'1 out':>9}{'n':>9}")
    for yr in sorted(d):
        row = f"  {yr:<9}"
        for o in (0, 1):
            dp, tot = d[yr][o]
            row += f"{(dp/tot if tot else 0):>9.4f}{tot:>9,}"
        print(row)
    print(f"\n  SHIPPED   {'':<0}0 out 0.2090   1 out 0.2240")


if __name__ == "__main__":
    main(sys.argv[1:])
