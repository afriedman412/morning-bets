"""HOW MUCH IS BULLPEN DEPLOYMENT WORTH, BEFORE BUILDING ONE? (TODO item 8)

    venv/bin/python -m scratchpad.deploy_screen [n_sims]

QUESTION. `next_arm` walks the drawn pen in DRAW ORDER, so the most-used arm
lands at average slot 3.01 of 8 and is as likely to pitch the sixth as the
ninth. `deploy.py` established that ROLE IS REAL AND PROJECTS (split-half
+0.55 to +0.78 over 319 relievers) and concluded role-based deployment was
worth building. What it never established is SENSITIVITY: how many runs of
separation ORDERING can buy at all, holding the arms themselves fixed.

That distinction is the one `leverage.py` exists to enforce, and TODO item 6
states it directly — "reliability without sensitivity is how park died three
times". `leverage.py` screens BULLPEN ARM QUALITY, which is a different
parameter: it asks what a better pen is worth, not what USING THE SAME PEN
IN A DIFFERENT ORDER is worth. Nothing screens deployment.

THE BOUND, and it is deliberately generous. Compare two EXTREME orderings of
the SAME drawn arms:

    BEST LAST    quality ascending — the best arm pitches the latest innings
    BEST FIRST   quality descending — the best arm pitches the earliest

No real deployment rule can beat that spread, because both endpoints are
oracle orderings of the same eight arms and every leverage rule is some
mixture of them. So the BEST-LAST vs BEST-FIRST difference is a CEILING on
what item 8 can buy from ordering. DRAW ORDER — what ships today — is
reported alongside to locate the status quo between them.

THE CEILING CONFLATES TWO CHANNELS AND THE BIG ONE IS NOT LEVERAGE. A
nine-inning game reaches only ~4.4 of the 8 drawn arms, so reordering does
not merely change WHEN each pitches — it changes WHICH of the eight pitch at
all, and the other ~3.6 never appear. "Best last" therefore means the WORST
arms are the ones actually used, which is why it scores MORE runs (9.093)
than "best first" (8.474) rather than fewer. Decomposed by the printout:

    which arms are exposed   ~0.6 runs   (the game-total row)
    when each one pitches    ~0.04 runs  (the 9th+ row)

Both are item 8's territory — "the most-used arm is as likely to pitch the
sixth as the ninth" is a statement about exposure as much as about leverage
— but a rule that only re-times a fixed set of arms buys the small number,
not the large one.

WHAT THIS SCREEN DOES NOT COVER, stated so the bound is not overread:

  * SITUATION. A real closer appears only in save situations, so his innings
    are selected by score. That is a redistribution ACROSS games and can
    move the SHAPE without moving the mean, which this measures only through
    the shutout and five-plus shares.
  * FATIGUE. The pen is redrawn independently every game, so nothing records
    yesterday's 30 pitches. That is a separate mechanism with its own
    spread and is not bounded here.

COMMON RANDOM NUMBERS. Both arms draw the SAME eight arms from the same
seeded stream — `build_side` is deterministic given its rng, and the
reordering consumes nothing — so the comparison is PAIRED at the draw. The
streams diverge after the first arm change, which IS the treatment effect.
Without this the comparison measures dice; `leverage.py` records a fake 74%
improvement from exactly that mistake.

POWER, STATED BEFORE THE RESULT. A game total has sd ~4.4, so an UNPAIRED
mean at n=20,000 has se ~0.031 — too coarse for a 0.03-run effect. Paired on
the draw the per-draw difference has a much smaller spread and the se is
reported directly; read it before the gap. The leverage floor for a BETTING
edge is ~0.05 runs, but per CLAUDE.md that decides PRIORITY, not
admissibility.
"""
from __future__ import annotations

import random
import statistics as st
import sys

from src.context import game, sim
from scratchpad.leverage import reference

SEED = 4801


def _quality(a: sim.PitcherRates) -> float:
    return a.k_pct - a.bb_pct


ORDERS = {
    # `next_arm` walks the list from index 0, so index 0 pitches EARLIEST.
    # Ascending quality therefore puts the best arm latest.
    "best last": lambda pen: sorted(pen, key=_quality),
    "draw order": lambda pen: list(pen),
    "best first": lambda pen: sorted(pen, key=_quality, reverse=True),
}


def run(order, lg, bat, sp, pen, n_sims):
    """Per-draw game totals and ninth-inning runs under one ordering rule."""
    tot, ninth, arms = [], [], []
    for d in range(n_sims):
        rng = random.Random(SEED + d)
        A = game.build_side(sp, pen, bat, None, rng)
        H = game.build_side(sp, pen, bat, None, rng)
        # REORDER AFTER THE DRAW. The draw itself is identical across
        # treatments because it happened before this line and consumed the
        # same stream; only the order the arms are USED in differs.
        A.pen, H.pen = order(A.pen), order(H.pen)
        r = game.simulate_game(A, H, lg, rng, track=(8,))
        tot.append(r.away + r.home)
        ninth.append((r.away + r.home) - r.prefix.get(8, r.away + r.home))
        arms.append(A.pen_i + 1 if A.starter_out else 0)
    return {"total": tot, "ninth": ninth, "arms": arms}


def _paired(a, b, key):
    d = [x - y for x, y in zip(a[key], b[key])]
    m = st.mean(d)
    se = st.pstdev(d) / len(d) ** 0.5 if len(d) > 1 else 0.0
    return m, se


def main(argv):
    n_sims = int(argv[0]) if argv and argv[0].isdigit() else 20000
    lg = sim.league()
    bat, sp, pen = reference(lg)
    qs = sorted(_quality(game._arm(a)) for a in pen)
    print(f"  {n_sims:,} paired draws, reference club\n")
    print(f"  pen K-BB spread: {qs[0]:.3f} to {qs[-1]:.3f}"
          f"  (sd {st.pstdev(qs):.3f})\n")

    got = {k: run(v, lg, bat, sp, pen, n_sims) for k, v in ORDERS.items()}

    print(f"  {'ordering':<14}{'game total':>12}{'9th+':>10}"
          f"{'shutouts':>10}{'5+ runs':>10}{'relievers':>11}")
    for k in ORDERS:
        g = got[k]
        sh = sum(1 for t in g["total"] if t == 0) / n_sims
        fp = sum(1 for t in g["total"] if t >= 10) / n_sims
        print(f"  {k:<14}{st.mean(g['total']):>12.3f}"
              f"{st.mean(g['ninth']):>10.3f}{sh:>10.3f}{fp:>10.3f}"
              f"{st.mean(g['arms']):>11.2f}")
    print(f"  {'sd of total':<14}"
          f"{st.pstdev(got['draw order']['total']):>12.3f}")

    print("\n  THE CEILING — best-last minus best-first, paired on the draw")
    print(f"  {'quantity':<14}{'gap':>12}{'se':>10}{'z':>8}")
    for key in ("total", "ninth"):
        m, se = _paired(got["best last"], got["best first"], key)
        z = m / se if se else 0.0
        print(f"  {key:<14}{m:>+12.3f}{se:>10.3f}{z:>+8.1f}")

    print("\n  WHERE THE STATUS QUO SITS — draw order minus best-last")
    print(f"  {'quantity':<14}{'gap':>12}{'se':>10}{'z':>8}")
    for key in ("total", "ninth"):
        m, se = _paired(got["draw order"], got["best last"], key)
        z = m / se if se else 0.0
        print(f"  {key:<14}{m:>+12.3f}{se:>10.3f}{z:>+8.1f}")

    print("\n  READ THE CEILING FIRST. It bounds every possible ordering rule")
    print("  on the SAME arms, so if it sits under the noise floor then no")
    print("  leverage model, however well fitted, can move the run level —")
    print("  and item 8's value would have to come from SITUATION or")
    print("  FATIGUE, which this does not bound.")


if __name__ == "__main__":
    main(sys.argv[1:])
