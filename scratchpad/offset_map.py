"""How many OUTS does one unit of `Hook.team_offset` buy?

The leash finding lives in output space — "this pitcher goes 1.4 outs longer
than the model says". The simulator's knob is a LOG-ODDS offset on both
removal decisions. Nothing connects the two analytically, because the
mapping runs through a hazard integrated over a whole start, so it is
MEASURED here and inverted by interpolation.

Measuring it rather than fitting it matters: a fitted conversion would be
free to absorb whatever else is wrong with the hook, which is the exact
failure mode `RESUME.md` records for the patience and leash offsets.

    venv/bin/python -m scratchpad.offset_map
"""
import multiprocessing as mp
import os
import random
import statistics as st

from src.context import calibrate as cal
from src.context import sim

OFFSETS = (-2.0, -1.5, -1.0, -0.6, -0.3, 0.0, 0.3, 0.6, 1.0, 1.5, 2.0)
_CASES = None


def _one(args):
    off, n_sims, seed, stride = args
    lg = sim.league()
    outs, ks = [], []
    for s, pitcher, lineup in _CASES[::stride]:
        rng = random.Random(seed)
        base = sim.Hook()
        hook = sim.Hook(**{**base.__dict__,
                           "team_offset": base.team_offset + off})
        pk = cal.park_for(s.get("venue_id")) if cal.USE_PARK \
            else sim.NEUTRAL_PARK
        nine = cal.adjust_lineup(lineup, bool(s.get("is_home")))
        for _ in range(n_sims):
            r = sim.simulate_start(pitcher, nine, lg, hook, rng, park=pk)
            outs.append(r.outs)
            ks.append(r.k)
    return off, st.mean(outs), st.pstdev(outs), st.mean(ks)


def main():
    global _CASES
    _CASES = cal.build_cases()
    stride = 4
    n_sims = 60
    print(f"  {len(_CASES[::stride])} starts x {n_sims} draws per offset")
    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, (os.cpu_count() or 4) - 2)) as pool:
        rows = pool.map(_one, [(o, n_sims, 7, stride) for o in OFFSETS])
    rows.sort()
    base = next(m for o, m, _, _ in rows if o == 0.0)
    print(f"\n  {'team_offset':>12}{'mean outs':>11}{'d outs':>9}"
          f"{'outs sd':>9}{'mean k':>9}")
    for o, m, sd, k in rows:
        print(f"  {o:>12.1f}{m:>11.2f}{m - base:>+9.2f}{sd:>9.2f}{k:>9.2f}")
    # local slope at zero, which is what a small leash offset actually uses
    lo = next(m for o, m, _, _ in rows if o == -0.3)
    hi = next(m for o, m, _, _ in rows if o == 0.3)
    print(f"\n  slope at 0: {(hi - lo) / 0.6:+.3f} outs per unit of offset")
    print(f"  so +1.0 out of leash needs offset "
          f"{1.0 / ((hi - lo) / 0.6):+.3f}")
    print("\n  NOTE the sd column: a leash offset moves the LEVEL of a"
          "\n  start without widening it, which is what differentiating"
          "\n  starts is supposed to look like. A mechanism that bought"
          "\n  spread by inflating every start's own variance would show"
          "\n  up here and would not be worth having.")


if __name__ == "__main__":
    main()
