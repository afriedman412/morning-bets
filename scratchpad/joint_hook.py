"""Fit the two hook curves JOINTLY, validated on the simulated mix.

    venv/bin/python -m scratchpad.joint_hook [starts] [sims]

WHY JOINT. Each curve can match its own observed per-decision hazard and the
simulated distribution still be wrong, because THE TWO COMPETE FOR THE SAME
EXITS. `scratchpad/fit_boundary.py` fitted the boundary curve on 38,485 real
end-of-inning decisions to AUC 0.8925 — plainly better per decision than the
shipped one, which fires at 0.293 where reality is 0.074 — and dropped the
simulated boundary SHARE from 0.643 to 0.479 against a measured 0.663. A
boundary curve that stops over-pulling leaves starters in to face more
batters, and every extra batter is another mid-inning chance, so the exits it
gives up are taken by the other curve.

Day seven's lesson was do not POOL the two populations. This one is do not
fit them INDEPENDENTLY either.

WHAT IS HELD AND WHAT MOVES. The BOUNDARY curve is pinned at its per-decision
fit — it is measured against what managers actually did at 38k real
decisions and there is no reason to move it. What is rescaled is the
MID-INNING curve, whose day-seven coefficients were fitted against decisions
generated under the OLD, too-eager boundary curve and are therefore
calibrated to a state distribution that no longer exists.

Three parameters, not thirteen: `late_mid_offset` shifts its level,
`late_mid_per_pitch` its slope in workload, `mid_intercept` the shared level
both branches sit on. Everything else in that curve was COUNTED rather than
fitted — `mid_per_inning_run` comes off the real per-run hazard — and is
left alone.

THE OBJECTIVE IS `calibrate.loss` PLUS AN EXPLICIT BOUNDARY-SHARE TERM.
`loss` already contains the share but weights the hazard curve 4x against
it, which is exactly how the pooled sweep earlier today talked itself into
0.620. Here the share is what went wrong, so it is weighted to match. SD is
reported and NOT optimised, per the standing rule.
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

#: The boundary curve, fitted on its own 38,485 real decisions. Held fixed.
BOUNDARY = dict(intercept=-4.2384, pitch_center=47.6812, pitch_scale=10.8972,
                per_run=0.0089, per_baserunner=0.0379, per_inning=-0.1087,
                per_margin=-0.0113)

GRID = {
    "late_mid_offset": [-9.5, -8.8, -7.97, -7.2, -6.5, -5.8],
    "late_mid_per_pitch": [0.06, 0.085, 0.11508, 0.14, 0.17],
    "mid_intercept": [-6.5, -5.75, -5.0, -4.25, -3.5],
}

#: Weight on (simulated boundary share - real). `calibrate.loss` carries the
#: same term at weight 1 against a hazard block at 4; the share is the thing
#: that broke, so it is lifted to match rather than left to lose.
W_SHARE = 4.0

_CFG: dict = {}


def _score(fields):
    hook = sim.Hook(**fields)
    res = cal.run(season=None, n_sims=_CFG["sims"],
                  max_starts=_CFG["starts"], hook=hook, seed=_CFG["seed"])
    outs = [r.outs for r in res["sim"]]
    bnd = cal._boundary(outs)
    obj = cal.loss(res) + W_SHARE * (bnd - _CFG["act_bnd"]) ** 2
    return obj, cal.loss(res), st.mean(outs), st.pstdev(outs), bnd


def main(argv):
    starts = int(argv[0]) if argv else 1200
    sims = int(argv[1]) if len(argv) > 1 else 40
    pairs = cal.paired_cases(max_starts=starts)
    act = [c[0]["o"] for p in pairs.values() for c in p]
    _CFG.update(starts=starts, sims=sims, seed=0,
                act_bnd=cal._boundary(act))
    print(f"  {len(act)} starts x {sims} draws")
    print(f"  ACTUAL   mean {st.mean(act):.2f}  sd {st.pstdev(act):.2f}  "
          f"boundary {_CFG['act_bnd']:.3f}\n")

    base = dict(sim.Hook().__dict__)
    print(f"  {'state':<26}{'obj':>9}{'loss':>9}{'mean':>8}{'sd':>7}"
          f"{'bndry':>8}")

    def show(lbl, fields):
        o, l, m, s, b = _score(fields)
        print(f"  {lbl:<26}{o:>9.5f}{l:>9.5f}{m:>8.2f}{s:>7.2f}{b:>8.3f}")
        return o

    show("shipped", base)
    start = dict(base, **BOUNDARY)
    best_obj = show("+ fitted boundary", start)
    best = start

    workers = max(1, (os.cpu_count() or 4) - 1)
    t0 = time.time()
    print()
    with cf.ProcessPoolExecutor(max_workers=workers,
                                mp_context=mp.get_context("fork")) as pool:
        for sweep in range(2):
            for param, values in GRID.items():
                cands = [dict(best, **{param: v}) for v in values
                         if best.get(param) != v]
                if not cands:
                    continue
                for fields, (o, l, m, s, b) in zip(cands,
                                                   pool.map(_score, cands)):
                    if o < best_obj:
                        best, best_obj = fields, o
                        print(f"    s{sweep} {param}={fields[param]:<8} "
                              f"obj {o:.5f}  loss {l:.5f}  mean {m:.2f}  "
                              f"sd {s:.2f}  boundary {b:.3f}")

    print()
    show("JOINT best", best)
    print(f"  {'ACTUAL':<26}{'':>9}{'':>9}{st.mean(act):>8.2f}"
          f"{st.pstdev(act):>7.2f}{_CFG['act_bnd']:>8.3f}   "
          f"({time.time()-t0:.0f}s)")
    print("\n  moved from shipped:")
    for k in list(BOUNDARY) + list(GRID):
        if abs(best[k] - getattr(sim.Hook(), k)) > 1e-9:
            print(f"    {k:<20}{getattr(sim.Hook(), k):>10.4f} -> "
                  f"{best[k]:>10.4f}")


if __name__ == "__main__":
    main(sys.argv[1:])
