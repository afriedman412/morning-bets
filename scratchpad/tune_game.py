"""Refit `sim.Hook` against the FULL-GAME engine — joint search, all cores.

THREE THINGS WRONG WITH `calibrate.tune`, all fixed here.

  SERIAL. ~180 grid evaluations on one core.

  500 STARTS of the 3,248 available.

  IT FITTED THE ENGINE THAT HAS SINCE BEEN DELETED. `calibrate.run` used
  to call `sim.simulate`, the start-level loop with no bullpen and no
  margin term. It now replays real two-sided games, so any hook fitted
  before 2026-08-25 was fitted against a different model.

AND ONE THING WRONG WITH COORDINATE DESCENT ITSELF. It moves one parameter
at a time, so it cannot cross a ridge: `intercept` and `pitch_center` both
shift the overall pull rate, and a point where no SINGLE move helps is not
a point where no move helps. It is also order-dependent — whichever
parameter is swept first absorbs error the later ones should own, and
`intercept` was first. `differential_evolution` moves all ten together.

WHY THE BOUNDS ARE WIDER THAN THE OLD GRID. `pitch_center` and
`pitch_scale` both pinned at the bottom of their grids on the full 1,624
games, which is this project's most reliable diagnostic firing for the
fifth time: a parameter at the edge is a missing mechanism, not a tuning
problem. Both want the same thing — a sharper, earlier pitch-count cutoff —
because the simulator's pitch counts are far more dispersed than real ones
(deGrom's sd is 6.0 against a simulated 16.0), and the hook is being used to
compensate. Widening the bounds does not fix that. It shows where the
parameter actually wants to sit, which is the diagnostic.

THE LOSS IS UNCHANGED ON PURPOSE. `calibrate.loss` weights the hazard curve,
the threshold shares, the boundary share and the mean. It does NOT weight
the spread, and the coordinate-descent refit cut loss 12x while making the
outs SD worse — 4.43 against a real 3.99, down to 3.54. Changing the
objective to chase that would be tuning against a quantity nobody measured
first. SD is REPORTED here so the trade is visible.

COMMON RANDOM NUMBERS. Every candidate sees the same (game, draw) seeds, so
two hooks are compared on identical innings. Without it the search chases
noise — and a search that chases noise still terminates and still prints a
winner. Demonstrated: a 120-game slice put `pitch_scale` at 15.0, the full
run put it at 8.0, opposite ends of the same grid.

    venv/bin/python -m scratchpad.tune_game [--games N] [--sims N] [--iters N]
"""
from __future__ import annotations

import multiprocessing
import os
import random
import statistics as st
import sys
import time

from scipy.optimize import differential_evolution

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src

WORKERS = max(1, os.cpu_count() or 2)
#: fork, not spawn. Spawn re-imports every module fresh, reverting the flags
#: this process set — a worker would silently tune the wrong engine, and it
#: would not crash. Cost the fitf5 parallelisation paid to learn.
_MP = "fork"

#: (name, low, high). Wider than the grid `calibrate.tune` used; see the
#: module note on why that is diagnostic rather than a fix.
BOUNDS = (
    ("intercept", -8.0, -2.0),
    ("per_inning", 0.0, 2.0),
    ("per_run", 0.0, 1.0),
    ("per_baserunner", 0.0, 1.0),
    ("pitch_center", 60.0, 110.0),
    ("pitch_scale", 3.0, 25.0),
    ("mid_intercept", -8.0, -2.0),
    ("mid_per_run", 0.0, 1.0),
    ("mid_per_runner", 0.0, 2.0),
    ("mid_per_damage", 0.0, 1.0),
)

_CTX: dict = {}


def setup(limit=None, n_sims=6):
    lg = sim.league()
    pens = rate_src.bullpens(lg)
    by: dict = {}
    for s, p, l in cal.build_cases():
        by.setdefault(s["game_id"], []).append((s, p, l))
    by = {g: v for g, v in by.items()
          if len(v) == 2 and sum(bool(x[0]["is_home"]) for x in v) == 1}
    if limit:
        by = dict(list(by.items())[:limit])
    # Pre-flatten so the inner loop does no dict work per candidate.
    prepped = []
    for i, (gid, v) in enumerate(by.items()):
        home = next(x for x in v if x[0]["is_home"])
        away = next(x for x in v if not x[0]["is_home"])
        prepped.append((
            i,
            away[1], pens.get((away[0]["team"] or "").upper(), []),
            cal.adjust_lineup(home[2], True),
            home[1], pens.get((home[0]["team"] or "").upper(), []),
            cal.adjust_lineup(away[2], False),
        ))
    _CTX.update(lg=lg, prepped=prepped, n_sims=n_sims,
                actual=[s for v in by.values() for s, _, _ in v])
    return by


def sim_outs(hook: sim.Hook, seed: int = 7) -> list[int]:
    """Every simulated starter's outs. Only `outs` is returned because that
    is all `calibrate.loss` reads — sending StartResult objects back from a
    worker would pickle a dozen unused fields per start."""
    lg, prepped, n_sims = _CTX["lg"], _CTX["prepped"], _CTX["n_sims"]
    out = []
    for i, a_sp, a_pen, a_nine, h_sp, h_pen, h_nine in prepped:
        for draw in range(n_sims):
            rng = random.Random(seed + i * 100003 + draw)
            A = game.build_side(a_sp, a_pen, a_nine, hook, rng)
            H = game.build_side(h_sp, h_pen, h_nine, hook, rng)
            r = game.simulate_game(A, H, lg, rng)
            out.append(r.away_sp.outs)
            out.append(r.home_sp.outs)
    return out


class _Outs:
    """`calibrate.loss` reads `.outs`; nothing else."""
    __slots__ = ("outs",)

    def __init__(self, o):
        self.outs = o


def score(vec) -> float:
    hook = sim.Hook(**{n: float(v) for (n, _, _), v in zip(BOUNDS, vec)})
    return cal.loss({"actual": _CTX["actual"],
                     "sim": [_Outs(o) for o in sim_outs(hook)]})


def report(hook: sim.Hook, label: str) -> None:
    a = [s["o"] for s in _CTX["actual"]]
    o = sim_outs(hook)
    b = sum(1 for v in o if v % 3 == 0) / len(o)
    ls = cal.loss({"actual": _CTX["actual"], "sim": [_Outs(x) for x in o]})
    print(f"  {label:<16}mean {st.mean(o):>6.2f}   sd {st.pstdev(o):>5.2f}"
          f"   boundary {b:>6.1%}   loss {ls:.5f}")
    if label == "ACTUAL":
        return
    print(f"  {'':<16}(actual mean {st.mean(a):.2f}, sd {st.pstdev(a):.2f}, "
          f"boundary {sum(1 for v in a if v % 3 == 0) / len(a):.1%})")


def main():
    limit, n_sims, iters = None, 6, 40
    a = sys.argv[1:]
    for i, x in enumerate(a):
        if x == "--games":
            limit = int(a[i + 1])
        if x == "--sims":
            n_sims = int(a[i + 1])
        if x == "--iters":
            iters = int(a[i + 1])
    by = setup(limit, n_sims)
    assert game.USE_LEARNED_HOOK is False, \
        "tuning sim.Hook while the learned model shadows it"
    n = len(by) * n_sims * 2
    print(f"{len(by)} games x {n_sims} draws x 2 starters = {n:,} simulated "
          f"starts per candidate, {WORKERS} workers", flush=True)

    t0 = time.time()
    report(sim.Hook(), "shipped")
    per = time.time() - t0
    pop = 15
    print(f"  {per:.1f}s per candidate; differential_evolution popsize "
          f"{pop} x {len(BOUNDS)} dims, {iters} iters "
          f"~= {pop * len(BOUNDS) * iters:,} evals "
          f"~= {pop * len(BOUNDS) * iters * per / WORKERS / 60:.0f} min",
          flush=True)

    ctx = multiprocessing.get_context(_MP)
    with ctx.Pool(WORKERS) as pool:
        res = differential_evolution(
            score, [(lo, hi) for _, lo, hi in BOUNDS],
            maxiter=iters, popsize=pop, tol=1e-4, seed=1,
            polish=False, updating="deferred", workers=pool.map,
            disp=True)
    best = sim.Hook(**{nm: float(v)
                       for (nm, _, _), v in zip(BOUNDS, res.x)})
    print(f"\nbest loss {res.fun:.5f} after {res.nit} iters, "
          f"{res.nfev:,} evals, {time.time() - t0:.0f}s")
    report(best, "REFIT")
    print()
    for (nm, lo, hi), v in zip(BOUNDS, res.x):
        edge = ""
        if abs(v - lo) < (hi - lo) * 0.02:
            edge = "   <- AT LOWER BOUND"
        if abs(v - hi) < (hi - lo) * 0.02:
            edge = "   <- AT UPPER BOUND"
        print(f"  {nm:<18}{v:>9.3f}   [{lo}, {hi}]{edge}")
    return best


if __name__ == "__main__":
    main()
