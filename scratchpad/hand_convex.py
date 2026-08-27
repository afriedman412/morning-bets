"""Handedness measured where it OPERATES: inside the game, per lineup.

    venv/bin/python -m scratchpad.hand_convex [n_sims]

WHY THE RESIDUAL SCREEN WAS THE WRONG TEST. `platoon_bat.py` collapsed each
start to ONE number — the lineup's mean rate shift — and asked whether that
predicted the starter's aggregate line. But the simulator resolves a plate
appearance at a time, so it can hold each hitter's UNBLENDED rate against
the arm actually on the mound. Collapsing to a mean throws away the part
that only exists at that level, and this project keeps making exactly that
substitution.

WHAT THE MEAN CANNOT SEE. Handedness does not only move a lineup up or
down, it SPREADS THE NINE APART: the hitters who punish left-handers go one
way, the ones who cannot go the other. Runs are convex in offensive rates —
clustering is what produces crooked innings — so a mean-preserving spread
RAISES expected runs. A correlation against the mean shift is blind to this
by construction, because it is a variance effect and not a mean-linear one.

AND IT IS NOT UNIFORM ACROSS GAMES, which is what makes it a real feature
rather than a level constant to be recalibrated away. A hitter's blended
rate is dominated by the right-handers he mostly faces, so facing a LEFTY
pulls him much further from his season line than facing a righty does:

    vs LHP   deviation from blended = (1 - share_L) x split   sd ~0.036
    vs RHP   deviation from blended =      share_L  x split   sd ~0.014

So games against left-handed starters carry MORE lineup dispersion than
games against right-handers, every time. If convexity is worth anything,
it is worth it asymmetrically, and that is a per-game signal.

THE SCREEN. Same nine, same seeds, same everything, with and without the
extra dispersion handedness would introduce. Paired, because the effect
being looked for is ~0.02 runs against a per-draw spread near 3.0 and an
unpaired mean at any affordable n_sims is noise.

MEAN-PRESERVING BY CONSTRUCTION. The perturbation is centred within each
lineup before it is applied, so the lineup's average rate is IDENTICAL in
both arms. Anything this finds is dispersion, not level — if the mean moved
too, the screen could not tell the two apart.
"""
from __future__ import annotations

import random
import statistics as st
import sys

from src.context import game, sim

#: Batter K% spread across regulars, and the EXTRA spread handedness adds on
#: top of it. Both counted in `scratchpad/platoon_bat.py`: the vs-L minus
#: vs-R split has sd 0.0504 over 148 hitters with 120+ plate appearances
#: against each hand, and a left-hander's share of those is about 28%.
BAT_K_SD = 0.060
SPLIT_K_SD = 0.0504
SPLIT_BABIP_SD = 0.030
LHP_SHARE = 0.28

#: How far the perturbation had to be shrunk to stay in range, per draw.
_SCALES: list = []


def lineup(lg, rng, k_sd=BAT_K_SD):
    """Nine hitters with a REALISTIC spread, not nine league averages.

    A uniform lineup would overstate what adding dispersion buys, because
    the first unit of spread into a flat lineup is worth more than the
    marginal unit into a real one.
    """
    ks = [max(0.05, rng.gauss(lg["k_pct"], k_sd)) for _ in range(9)]
    m = st.mean(ks)
    ks = [k - m + lg["k_pct"] for k in ks]
    return [sim.BatterRates(name=f"b{i}", k_pct=ks[i], bb_pct=lg["bb_pct"],
                            hr_pct=lg["hr_pct"], babip=lg["babip"], pa=600)
            for i in range(9)]


def spread(bats, lg, rng, k_extra, bab_extra):
    """The same nine, pulled apart by what handedness would do tonight.

    CENTRED before it is applied: the lineup mean is untouched, so the two
    arms differ only in dispersion.
    """
    def perturb(vals, sd, lo, hi):
        """A CENTRED perturbation, scaled down until nothing clamps.

        Clamping after centring is not mean-preserving and cannot be undone
        — a clipped value will not move — and the error grows with the
        perturbation, which is what made the first control unreadable. A
        centred vector scaled by any factor keeps the mean EXACTLY, so the
        fix is to shrink the whole vector rather than clip its tails.

        Returns the scale actually used: if it sits well below 1 the
        exaggerated arms are quietly not exaggerated, and that has to be
        visible rather than assumed.
        """
        d = [rng.gauss(0.0, sd) for _ in vals]
        m = st.mean(d)
        d = [x - m for x in d]
        s = 1.0
        for v, x in zip(vals, d):
            if x > 0 and v + x > hi:
                s = min(s, (hi - v) / x)
            elif x < 0 and v + x < lo:
                s = min(s, (lo - v) / x)
        return [v + s * x for v, x in zip(vals, d)], s

    ks, sk = perturb([b.k_pct for b in bats], k_extra, 0.05, 0.60)
    bs, sb = perturb([b.babip for b in bats], bab_extra, 0.18, 0.45)
    _SCALES.append(min(sk, sb))
    return [sim.BatterRates(name=b.name, k_pct=k, bb_pct=b.bb_pct,
                            hr_pct=b.hr_pct, babip=bb, pa=b.pa)
            for b, k, bb in zip(bats, ks, bs)]


def staff(lg):
    sp = sim.PitcherRates(name="sp", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
                          hr_pct=lg["hr_pct"], babip=lg["babip"], pa=600)
    pen = [{"name": f"r{i}",
            "k_pct": max(0.05, lg["k_pct"] + o * 0.037),
            "bb_pct": max(0.01, lg["bb_pct"] - o * 0.037 * 0.25),
            "hr_pct": lg["hr_pct"], "babip": lg["babip"], "apps": 40}
           for i, o in enumerate((1.5, 1.0, .6, .2, -.2, -.6, -1.0, -1.5))]
    return sp, pen


def run(lg, n_sims, k_extra, bab_extra, seed=101):
    """Paired runs allowed at each prefix, flat lineup vs spread lineup."""
    _SCALES.clear()
    sp, pen = staff(lg)
    out = {p: ([], []) for p in (5, 7, 9)}
    for d in range(n_sims):
        # One lineup and one perturbation per draw, both arms sharing them.
        base = lineup(lg, random.Random(90000 + d))
        wide = spread(base, lg, random.Random(70000 + d), k_extra, bab_extra)
        for arm, bats in ((0, base), (1, wide)):
            rng = random.Random(seed + d)
            A = game.build_side(sp, pen, bats, None, rng)
            H = game.build_side(sp, pen, bats, None, rng)
            r = game.simulate_game(A, H, lg, rng, track=(5, 7))
            out[5][arm].append(A.runs_f5)
            out[7][arm].append(r.prefix.get(7, 0) / 2.0)
            out[9][arm].append(A.runs)
    return out


def report(label, out):
    sc = st.mean(_SCALES) if _SCALES else 1.0
    for p in (5, 7, 9):
        lo, hi = out[p]
        d = [b - a for a, b in zip(lo, hi)]
        m = st.mean(d)
        se = st.pstdev(d) / len(d) ** 0.5
        print(f"  {label:<22}F{p}  flat {st.mean(lo):6.3f}"
              f"  spread {st.mean(hi):6.3f}"
              f"  delta {m:+7.4f} +/- {se:.4f}"
              f"  ({m / se if se else 0:+5.1f} sd)"
              f"{'' if sc > 0.98 else f'  [scaled {sc:.2f}]'}")


def main(argv):
    n = int(argv[0]) if argv else 3000
    lg = sim.league()
    print(f"  {n:,} paired games per arm, common random numbers\n")
    print("  Does mean-preserving lineup dispersion change runs at all?")
    # vs LHP is the big one: the blended rate is mostly the right-handers he
    # faces, so a left-hander pulls each hitter furthest from it.
    for label, mult in (("vs LHP  (x0.72)", 1 - LHP_SHARE),
                        ("vs RHP  (x0.28)", LHP_SHARE)):
        out = run(lg, n, SPLIT_K_SD * mult, SPLIT_BABIP_SD * mult)
        report(label, out)
    # And an exaggerated arm, to prove the screen can see the effect at all
    # before its null is believed. A screen that reports zero for a 4x
    # effect is broken, not informative.
    # A screen that reports zero for an exaggerated effect is broken, not
    # informative. 2x rather than 4x keeps the clamp off the floor, which
    # is what made the first version of this control unreadable.
    print("\n  CONTROL — 2x the real spread, which must be LARGER than 1x.")
    print("  If it is not, the screen is broken and the rows above mean")
    print("  nothing.")
    out = run(lg, n, SPLIT_K_SD * 2, SPLIT_BABIP_SD * 2)
    report("2x control", out)


if __name__ == "__main__":
    main(sys.argv[1:])
