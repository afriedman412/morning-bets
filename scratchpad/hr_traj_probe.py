"""PROBE: does the play-by-play cache carry a trajectory on home runs?

Everything downstream of "model home runs off contact type" depends on the
HR/FB denominator being countable. `battedball.py` already counts
ground-ball share and drops any ball in play with no `hitData` as a
coverage miss; a home run that systematically lacks trajectory would put
the numerator and denominator on different populations.

    venv/bin/python -m scratchpad.hr_traj_probe [N_GAMES]
"""
from __future__ import annotations

import multiprocessing as mp
import sys
from collections import Counter

from src.context.sources import pbp
from src.context.sources.battedball import BIP_EV


def _one(gid: str) -> Counter:
    c: Counter = Counter()
    try:
        for play, *_ in pbp.plays(gid):
            ev = ((play.get("result") or {}).get("eventType") or "")
            if ev not in BIP_EV:
                continue
            hd = None
            for e in (play.get("playEvents") or []):
                if e.get("hitData"):
                    hd = e["hitData"]
            traj = (hd or {}).get("trajectory") or "MISSING"
            c[("all", traj)] += 1
            if ev == "home_run":
                c[("hr", traj)] += 1
    except Exception:
        pass
    return c


def main(argv):
    n = int(argv[0]) if argv else 300
    gids = sorted(f"mlb-{f.name.split('.')[0]}"
                  for f in pbp.CACHE.glob("*.json.gz"))
    step = max(1, len(gids) // n)
    sample = gids[::step][:n]
    print(f"  {len(sample)} games sampled from {len(gids):,} cached")
    with mp.get_context("fork").Pool(8) as p:
        tot = sum(p.map(_one, sample), Counter())
    for pop in ("all", "hr"):
        rows = sorted(((v, k) for (p_, k), v in tot.items() if p_ == pop),
                      reverse=True)
        n_tot = sum(v for v, _ in rows)
        print(f"\n  {pop.upper()}  ({n_tot:,} balls in play)")
        for v, k in rows:
            print(f"    {k:<20}{v:>8,}  {v / max(n_tot, 1):6.2%}")


if __name__ == "__main__":
    main(sys.argv[1:])
