"""What SHARE of runs arrives on a home run — model against actual?

    venv/bin/python -m scratchpad.hr_share [n_sims]

QUESTION. Not how many home runs — that is measured and right to within
1.4%. What fraction of a team's RUNS the homer delivers. A homer pays its
runs in one swing to one batter; a single passes them through several, so
the two produce identical run totals with completely different rbi
distributions.

WHY IT IS THE RIGHT NEXT TEST. Matched on the team total, the model puts
+0.072 more rbi on its top hitter than reality does (z +2.7) and P(a hitter
drives in 4+) runs 23% high. Two mechanisms could do that and they call for
opposite fixes:

  SEQUENCING   too many runs arrive on homers, so they land on one batter.
               Nothing to do with the hitters' rates.
  RATES        hitters are over-separated, so the good bats hog the rbi.
               But the batter constants that fix that COST F5, so this
               cannot be the whole story.

This separates them. HYPOTHESIS, stated before running: the model's home-run
share of runs is too HIGH. Falsifier: if the share matches, sequencing is
exonerated and the concentration goes back to the rates.

THE ACTUAL SIDE IS COUNTED, not derived. Runs on a play come from the score
CHANGE across it rather than from the rbi field, because MLB awards no rbi
on a double play or an error and this question is about runs.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import random
import statistics as st
import sys
import zlib

from src.context import calibrate as cal, sim
from src.context.sources import pbp, rates as rate_src

CUT = "2026-07-01"
_CASES: dict = {}
_LG: dict = {}
_PENS: dict = {}


def _model(args):
    gid, n_sims, seed = args
    # SEED VARIES BY GAME. Handing every game the same seed puts draw i at
    # the same position in the stream for all of them, so the per-draw
    # errors CORRELATE across games and the standard error of an absolute
    # aggregate comes out about 3.4x wider than sqrt(n) suggests (measured:
    # block sd 0.385 against 0.113). It cancels in a paired A/B, which is
    # why the salt method is sound, and it does NOT cancel in a level.
    rng = random.Random((zlib.crc32(gid.encode()) & 0xFFFF) * 1009 + seed)
    runs = hr_runs = 0
    for _ in range(n_sims):
        r = cal.replay(_CASES[gid], _LG, _PENS, rng)
        runs += r.away + r.home
        hr_runs += r.away_hr_runs + r.home_hr_runs
    return runs, hr_runs


def _actual(gid):
    """(runs, runs that scored on a home run) for one real game."""
    runs = hr = 0
    prev = None
    for play, _b, _o, away, home in pbp.plays(gid):
        res = play.get("result") or {}
        if res.get("awayScore") is None:
            continue
        after = res["awayScore"] + res["homeScore"]
        got = after - (away + home)
        if got <= 0:
            continue
        runs += got
        ev = (res.get("eventType") or res.get("event") or "").lower()
        if "home_run" in ev or ev == "home run":
            hr += got
        prev = ev
    return runs, hr


def main(argv):
    global _CASES, _LG, _PENS, CUT
    if "--cut" in argv:
        i = argv.index("--cut")
        CUT = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    n_sims = int(argv[0]) if argv else 20
    _LG = sim.league()
    _PENS = rate_src.bullpens(_LG, before=CUT)
    _CASES = cal.paired_cases(season=2026, since=CUT, rates_before=CUT)
    print(f"  HOLDOUT: rates before {CUT}, {len(_CASES)} games x {n_sims}"
          f" sims\n", flush=True)
    ctx = mp.get_context("fork")
    workers = max(1, (os.cpu_count() or 4) - 2)
    with ctx.Pool(workers) as pool:
        got = pool.map(_model, [(g, n_sims, 0) for g in _CASES], chunksize=8)
    m_runs = sum(a for a, _b in got)
    m_hr = sum(b for _a, b in got)
    # SAME GAMES on both sides. Comparing the model on one game set against
    # the league on another is how a 3.4% denominator error hid behind a
    # 3.3% coverage gap once already.
    a_runs = a_hr = 0
    per = []
    for gid in _CASES:
        r, h = _actual(gid)
        if not r:
            continue
        a_runs += r
        a_hr += h
        per.append(h / r)
    print(f"  {'':<12}{'runs':>10}{'on a HR':>10}{'share':>9}")
    print(f"  {'model':<12}{m_runs:>10,}{m_hr:>10,}{m_hr / m_runs:>9.2%}")
    print(f"  {'actual':<12}{a_runs:>10,}{a_hr:>10,}{a_hr / a_runs:>9.2%}")
    d = m_hr / m_runs - a_hr / a_runs
    # The actual share's error bar comes from the spread across games, which
    # is the sample being generalised from. The model's is negligible at
    # this many simulated games and is not the binding side.
    se = st.pstdev(per) / len(per) ** 0.5
    print(f"  {'diff':<12}{'':>10}{'':>10}{d:>+9.2%}"
          f"   (se {se:.2%}, z {d / se:+.1f})")
    print(f"\n  {len(per)} real games on the same slate as the simulation.")
    print("  HYPOTHESIS was that the model's share is too HIGH — that its")
    print("  runs arrive in one swing and so land on one batter. A share")
    print("  that MATCHES exonerates sequencing and sends the")
    print("  concentration finding back to the batter rates.")


if __name__ == "__main__":
    main(sys.argv[1:])
