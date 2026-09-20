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
from src.context.sources import rates as rate_src

OFFSETS = (-2.0, -1.5, -1.0, -0.6, -0.3, 0.0, 0.3, 0.6, 1.0, 1.5, 2.0)
_PAIRS = None


def _one(args):
    """One offset, applied through the channel the leash actually uses.

    THE OFFSET GOES IN VIA `sim._LEASH`, not by handing `replay` a hook.
    `cal.replay` builds its sides with `hook=None` and lets `build_side`
    call `sim.for_start`, which is the one path that is tested — passing a
    pre-offset hook in beside it would measure a code path nothing prices
    through. Every modelled pitcher gets the same offset, so both sides of
    every game move together and the reading is the marginal effect of the
    offset itself rather than of a mismatch between the two starters.
    """
    off, n_sims, seed, stride = args
    lg = sim.league()
    pens = rate_src.bullpens(lg)
    pairs = list(_PAIRS.values())[::stride]
    names = {c[1].name for pair in pairs for c in pair}
    saved = sim._LEASH
    sim._LEASH = {n: off for n in names}
    try:
        outs, ks = [], []
        for pair in pairs:
            rng = random.Random(seed)
            for _ in range(n_sims):
                r = cal.replay(pair, lg, pens, rng)
                for line in (r.away_sp, r.home_sp):
                    outs.append(line.outs)
                    ks.append(line.k)
    finally:
        sim._LEASH = saved
    return off, st.mean(outs), st.pstdev(outs), st.mean(ks)


def main():
    global _PAIRS
    _PAIRS = cal.paired_cases()
    stride = 4
    n_sims = 30
    print(f"  {len(list(_PAIRS.values())[::stride])} games x {n_sims} draws "
          f"per offset (both starters scored)")
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
