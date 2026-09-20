"""Does a pitcher's ARSENAL predict the CONTACT residual? The cheap screen.

    venv/bin/python -m scratchpad.arsenal_screen

WHY CONTACT AND NOT STRIKEOUTS. Every arsenal test this project has run
scored strikeouts, and strikeouts are the thing the model is already best at
— 85% of a model-free ceiling. The open channel is SINGLES, 4.9% short at
full sample, and `rates.arsenal_mults` already returns a `contact`
multiplier that scales balls in play and home runs. Aiming a mechanism at
the stat with the least headroom is how six of these came back zero.

WHY A SCREEN AND NOT `PREREG-arsenal.md`. That protocol demands n_sims >= 400
across 6 salts to resolve 2 sigma. Today's real mechanisms were visible at 25
sims in a single run; a thing needing that much machinery to see is below the
threshold that moves a price. This is a residual correlation, costs no
simulation, and if it is flat nothing downstream can rescue it.

LEAVE-ONE-OUT FROM THE START, because the handedness screen was run without
it this morning and reported +4.8 sigma that fell to +1.7 once each start
came out of its own predictor. The arsenal multiplier is built from Savant
season aggregates that CONTAIN the start being scored, which is the same
leak. Here it is handled by construction: the multiplier depends on the
BATTERS faced and the pitcher's MIX, not on what happened, so the start's own
outcome does not enter it — but the batter projections do come from
season-to-date rows, so a cutoff is applied.

WHAT IS PRE-REGISTERED, stated before looking: this is a null unless the
contact residual correlation clears the same bar every other candidate has
been held to — about 0.2 of removable spread. A significant correlation worth
0.05 of a hit per start is a null for this project's purpose.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict

from src.context import calibrate as cal
from src.context.sources import rates as rate_src


#: Set in `main` BEFORE the fork so every worker inherits it. A spawned
#: child would re-import and rebuild the Savant caches per worker; fork
#: shares them copy-on-write.
_ARS: dict = {}


def _one(job):
    gid, name, mix, names = job
    try:
        m = rate_src.arsenal_mults(mix, names, _ARS, season=2026)
    except Exception:
        return None
    vals = [v for v in (m or {}).values() if v]
    if not vals:
        return None
    return ((gid, name),
            {"contact": st.mean(v.get("contact", 1.0) for v in vals),
             "k": st.mean(v.get("k", 1.0) for v in vals)})


def corr(xs, ys):
    n = len(xs)
    if n < 30:
        return 0.0, 0.0
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if not sx or not sy:
        return 0.0, 0.0
    r = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (n * sx * sy)
    return r, r * (n - 2) ** 0.5 / max((1 - r * r) ** 0.5, 1e-9)


def main(argv):
    from datetime import date as _d
    from src import panel

    rows = [r for r in json.load(open("scratchpad/ceiling_rows.json"))
            if not r.get("_team_row")]
    lineups = cal.opposing_lineups()
    stamp = _d.today().isoformat()
    try:
        ars = panel._pitcher_arsenal_blob(
            panel.savant_pitcher_arsenal(2026, stamp)) or {}
    except Exception as e:
        print(f"  arsenal unavailable: {type(e).__name__} {e}")
        return
    print(f"  {len(ars):,} pitchers with an arsenal on file")
    globals()["_ARS"] = ars

    # FORKED, and the serial version was 1 core of 8 for ten minutes with
    # nothing to show. `arsenal_mults` projects nine batters against the
    # starter's mix AND against a league-average mix, so it is ~18 Savant
    # projections per start over 3,278 starts. Embarrassingly parallel.
    #
    # Fork, never spawn: a spawned child re-imports at default globals and
    # the Savant caches are rebuilt per worker.
    import concurrent.futures as cf
    import multiprocessing as mp
    import os

    jobs = []
    for r in rows:
        mix = ars.get((r["player"] or "").lower().strip())
        names = lineups.get((r["game_id"], r["team"]))
        if mix and names:
            jobs.append((r["game_id"], r["player"], mix, list(names)))

    per = {}
    workers = max(1, (os.cpu_count() or 4) - 1)
    print(f"  {len(jobs):,} starts to project over {workers} workers",
          flush=True)
    with cf.ProcessPoolExecutor(max_workers=workers,
                                mp_context=mp.get_context("fork")) as pool:
        for res in pool.map(_one, jobs, chunksize=16):
            if res:
                per[res[0]] = res[1]
    got = len(per)
    print(f"  {got:,} starts with a usable matchup projection\n")

    print(f"  {'mult':<9}{'stat':<7}{'n':>7}{'r':>9}{'z':>8}"
          f"{'removable spread':>19}")
    for mult in ("contact", "k"):
        for stat in ("h", "k", "er"):
            xs, ys = [], []
            for r in rows:
                key = (r["game_id"], r["player"])
                if key not in per or r.get(f"m_{stat}") is None:
                    continue
                xs.append(per[key][mult])
                ys.append(r[f"a_{stat}"] - r[f"m_{stat}"])
            r_, z = corr(xs, ys)
            sd = st.pstdev(ys) if ys else 0.0
            print(f"  {mult:<9}{stat:<7}{len(xs):>7,}{r_:>+9.3f}{z:>+8.1f}"
                  f"{abs(r_) * sd:>19.3f}")
    print("\n  Pre-registered bar: ~0.2 of removable spread, the same one")
    print("  every other candidate was held to. Significance alone is not it.")


if __name__ == "__main__":
    main(sys.argv[1:])
