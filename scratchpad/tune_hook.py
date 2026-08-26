"""Refit `sim.Hook` against the CURRENT engine. Parallel coordinate descent.

    venv/bin/python -m scratchpad.tune_hook [starts] [sims]

WHY IT HAS TO BE REFITTED. `intercept`, `pitch_center`, `pitch_scale` and
`mid_intercept` all trace to the commit that created the simulator. They
were fitted by `calibrate.tune` against `sim.simulate` — one pitching side,
no bullpen, no margin, no opposing offence — which was deleted on
2026-08-25. They were also fitted against a pitch count that was billed
`int(round(PITCH_COST))`, roughly 4 pitches a start light. Both inputs have
changed underneath them.

WHY `calibrate.loss` AND NOT `fitf5`. CLAUDE.md draws the line explicitly:
do not fit the hook against the SETTLEMENT VALUE; fitting it to real removal
DECISIONS is a different thing. `loss` targets the observed hazard curve,
the boundary share and the shares at >=18 / <15 / >=21 outs — what managers
did. `fitf5` targets F5 runs, which is what we price, and pointing the hook
at it would let the removal rule absorb errors in the run model.

TWO THINGS THIS FIXES ABOUT `calibrate.tune`. It is serial, and it samples
500 of 3,248 starts. The values within one parameter's sweep are
independent — coordinate descent is only sequential ACROSS parameters — so
they fork. Fork and not spawn, for the reason recorded against every other
worker pool here.

AND IT REPORTS SD, WHICH IS NOT IN THE OBJECTIVE. The standing warning:
`loss` does not weight spread, so an optimiser pointed at it will compress
the outs distribution to buy the hazard curve and the boundary share. SD is
printed at every step so a compressing fit is visible rather than silently
accepted. It is deliberately NOT added to the objective while the hook may
still be compensating for something else.
"""
from __future__ import annotations

import concurrent.futures as cf
import multiprocessing as mp
import os
import statistics as st
import sys
import time

from src.context import calibrate as cal
from src.context import sim

GRID = {
    "intercept": [-7.0, -6.0, -5.2, -4.6, -4.0, -3.2, -2.4],
    "per_inning": [0.3, 0.45, 0.6, 0.8, 1.0, 1.3],
    "per_run": [0.1, 0.2, 0.3, 0.45, 0.6],
    "pitch_center": [74.0, 80.0, 86.0, 92.0, 98.0],
    "pitch_scale": [8.0, 11.0, 15.0, 19.0],
    "mid_intercept": [-6.5, -5.5, -5.0, -4.4, -3.8],
    "mid_per_run": [0.15, 0.3, 0.45],
    "mid_per_runner": [0.25, 0.55, 0.9, 1.3],
    "mid_per_damage": [0.0, 0.15, 0.25, 0.4],
    "per_baserunner": [0.0, 0.1, 0.2, 0.35],
}

_CFG: dict = {}


def _score(fields):
    """(loss, mean outs, sd outs, boundary share) for one candidate hook."""
    hook = sim.Hook(**fields)
    res = cal.run(season=None, n_sims=_CFG["sims"],
                  max_starts=_CFG["starts"], hook=hook, seed=_CFG["seed"])
    outs = [r.outs for r in res["sim"]]
    return (cal.loss(res), st.mean(outs), st.pstdev(outs),
            cal._boundary(outs))


def main(argv):
    starts = int(argv[0]) if argv else 1200
    sims = int(argv[1]) if len(argv) > 1 else 40
    _CFG.update(starts=starts, sims=sims, seed=0)

    # The ACTUAL distribution, for reading the fit against.
    pairs = cal.paired_cases(max_starts=starts)
    act = [c[0]["o"] for p in pairs.values() for c in p]
    print(f"  {len(pairs)} games / {len(act)} starts x {sims} draws")
    print(f"  ACTUAL   mean {st.mean(act):.2f}  sd {st.pstdev(act):.2f}  "
          f"boundary {cal._boundary(act):.3f}\n")

    workers = max(1, (os.cpu_count() or 4) - 1)
    best = dict(sim.Hook().__dict__)
    l0, m0, s0, b0 = _score(best)
    print(f"  start    loss {l0:.5f}   mean {m0:.2f}  sd {s0:.2f}  "
          f"boundary {b0:.3f}")
    best_loss = l0
    t0 = time.time()

    with cf.ProcessPoolExecutor(max_workers=workers,
                                mp_context=mp.get_context("fork")) as pool:
        for sweep in range(2):
            for param, values in GRID.items():
                cands = [dict(best, **{param: v}) for v in values
                         if best.get(param) != v]
                if not cands:
                    continue
                for fields, (lo, mu, sd, bd) in zip(
                        cands, pool.map(_score, cands)):
                    if lo < best_loss:
                        best, best_loss = fields, lo
                        print(f"    s{sweep} {param}={fields[param]:<7} "
                              f"loss {lo:.5f}  mean {mu:.2f}  sd {sd:.2f}  "
                              f"boundary {bd:.3f}")
    lo, mu, sd, bd = _score(best)
    print(f"\n  BEST     loss {lo:.5f}   mean {mu:.2f}  sd {sd:.2f}  "
          f"boundary {bd:.3f}   ({time.time()-t0:.0f}s)")
    print(f"  ACTUAL                     mean {st.mean(act):.2f}  "
          f"sd {st.pstdev(act):.2f}  boundary {cal._boundary(act):.3f}")
    print(f"\n  SD IS NOT IN THE OBJECTIVE. If it fell while the loss did,")
    print(f"  the fit bought the hazard curve with spread — do not ship it.\n")
    for k in GRID:
        flag = "  <- moved" if best[k] != getattr(sim.Hook(), k) else ""
        print(f"    {k:<18}{getattr(sim.Hook(), k):>8} -> {best[k]:<8}{flag}")


if __name__ == "__main__":
    main(sys.argv[1:])
