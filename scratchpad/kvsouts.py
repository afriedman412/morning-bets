"""Are strikeouts and length the SAME quantity in this simulator?

    venv/bin/python -m scratchpad.kvsouts [n_draws]

THE QUESTION. `K = batters faced x K rate`, and batters faced comes from how
long he lasts, so length drives strikeouts by construction. Reality has the
same coupling — a pitcher who goes seven faces more men than one who goes
four — so the coupling is not itself a defect. The defect would be getting
its STRENGTH wrong, and there are two forces to get wrong:

  * MORE OUTS, MORE BATTERS FACED, MORE STRIKEOUTS. Positive.
  * A STRIKEOUT COSTS MORE PITCHES than a ball in play (4.97 against 3.25,
    measured, in `sim.PITCH_COST`), so a high-K start burns the count faster
    and ends sooner. Negative.

If the second is too weak, the model over-couples them and cannot produce
the two starts that decouple in reality: the short outing full of swings and
misses, and the long efficient one with four strikeouts.

WHAT SETTLES IT is not the correlation alone but E[K | outs]. If, given
length, our strikeout distribution matches reality, then K carries no error
of its own and everything wrong with a K prop is inherited from the outs
model. If E[K | outs] is off, K and outs need separating.

Both sides are pooled over the same population and the same window, so the
comparison is like for like.
"""
from __future__ import annotations

import random
import statistics as st
import sys

from src.context import calibrate as cal
from src.context import leash, sim
from src.context.sources import rates as rate_src

BUCKETS = ((0, 8), (9, 11), (12, 14), (15, 17), (18, 20), (21, 27))


def _table(pairs, label):
    """pairs = [(outs, k)]. Prints E[K | outs] and the correlation."""
    o = [p[0] for p in pairs]
    k = [p[1] for p in pairs]
    print(f"\n  {label}: n={len(pairs)}  mean outs {st.mean(o):.2f}  "
          f"mean K {st.mean(k):.2f}  corr {st.correlation(o, k):+.3f}")
    out = {}
    for lo, hi in BUCKETS:
        g = [p for p in pairs if lo <= p[0] <= hi]
        if len(g) < 25:
            continue
        out[(lo, hi)] = (len(g) / len(pairs), st.mean(x[1] for x in g),
                         st.pstdev([x[1] for x in g]))
    return out


def main(argv):
    n_draws = int(argv[0]) if argv else 20
    lg = sim.league()

    # ---- REAL ----
    keep = leash.intended_starters()
    real = [(r["o"], r["k"]) for r in cal.actual_starts()
            if r["player_name"] in keep and r["o"] is not None]

    # ---- SIMULATED, same population, through the shipped path ----
    pairs = cal.paired_cases()
    pens = rate_src.bullpens(lg)
    simd = []
    rng = random.Random(0)
    for i, pair in enumerate(pairs.values()):
        names = (pair[0][1].name, pair[1][1].name)
        for _ in range(n_draws):
            r = cal.replay(pair, lg, pens, rng)
            for nm, line in zip(names, (r.away_sp, r.home_sp)):
                if nm in keep:
                    simd.append((line.outs, line.k))
        if (i + 1) % 200 == 0:
            print(f"    {i + 1}/{len(pairs)} games", flush=True)

    a = _table(real, "ACTUAL")
    b = _table(simd, "SIMULATED")

    print(f"\n  E[K | outs] — the test that matters")
    print(f"  {'outs':<10}{'share A':>9}{'share S':>9}"
          f"{'E[K] A':>9}{'E[K] S':>9}{'diff':>8}{'sd A':>7}{'sd S':>7}")
    for key in BUCKETS:
        if key not in a or key not in b:
            continue
        (sa, ma, da), (sb, mb, db) = a[key], b[key]
        print(f"  {f'{key[0]}-{key[1]}':<10}{sa:>9.1%}{sb:>9.1%}"
              f"{ma:>9.2f}{mb:>9.2f}{mb - ma:>+8.2f}{da:>7.2f}{db:>7.2f}")
    print("\n  'share' is the outs MARGINAL and is a separate defect from")
    print("  E[K | outs]. A model can have the length wrong and the")
    print("  strikeouts-given-length exactly right; that is the case where")
    print("  there is nothing to disentangle and the K prop is a length bet.")


if __name__ == "__main__":
    main(sys.argv[1:])
