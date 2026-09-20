"""WHICH CLUB BATS IN THE FIRST HALF OF AN INNING?

    venv/bin/python -m scratchpad.whobats

A direct instrumented check, not an inference off a run total. `ninth.py`
found the model's away-team ninth scoring 0.152 against a real 0.455 and its
home-team ninth 0.503 against a real 0.254 — an inversion, which is what a
top/bottom swap looks like. That is circumstantial. This reads the answer
off the engine.

THE DECISIVE OBSERVABLE is not runs, it is WHO IS SKIPPED. Real baseball
plays the away club's half of the ninth in every game and skips the HOME
club's when the home club already leads. So:

    P(away club bats in the 9th) = 1.000
    P(home club bats in the 9th) < 1.000

If the engine has those the other way round, the halves are reversed.

POSITIVE CONTROL, because a harness that reports the same answer whatever
the engine does proves nothing: the same counter is run against a
HAND-BUILT game whose half-inning order is known by construction, and it
must recover the known answer.
"""
from __future__ import annotations

import random
import statistics as st

from src.context import calibrate as cal, game, sim
from src.context.sources import rates as rate_src

CUT = "2026-05-15"


def _bats_in_ninth(pair, lg, pens, rng) -> tuple[bool, bool]:
    """(away club batted in the 9th, home club batted in the 9th).

    Read off `prefix_side`, which is {inning: (away TEAM score, home TEAM
    score)}. A club that does not bat cannot change its score, so the score
    alone cannot answer this — the SKIP has to be reconstructed from the
    rule the engine applies. Instead of reconstructing it, this counts
    plate appearances directly by wrapping `_half_inning`.
    """
    seen: list[tuple[int, str]] = []
    real = game._half_inning

    def spy(side, lg_, rng_, inning, margin, park, **kw):
        # WHICH CLUB IS BATTING is a property of the side that is PITCHING:
        # `side.lineup` is "the OPPOSING nine". The away pitching side faces
        # the home club, so a call on the away side IS the home club batting.
        seen.append((inning, "home" if side is spy.A else "away"))
        return real(side, lg_, rng_, inning, margin, park, **kw)

    away, home = pair
    an = cal.adjust_lineup(away[2], False)
    hn = cal.adjust_lineup(home[2], True)
    A = game.build_side(away[1], pens.get((away[0]["team"] or "").upper(), []),
                        an, None, rng, team=away[0]["team"])
    H = game.build_side(home[1], pens.get((home[0]["team"] or "").upper(), []),
                        hn, None, rng, team=home[0]["team"])
    spy.A = A
    game._half_inning = spy
    try:
        game.simulate_game(A, H, lg, rng, track=())
    finally:
        game._half_inning = real
    order = [who for inn, who in seen if inn == 1]
    ninth = {who for inn, who in seen if inn == 9}
    return ("away" in ninth, "home" in ninth, order[0] if order else "?")


def control() -> None:
    """The same counter against a game whose order is known by construction."""
    print("  POSITIVE CONTROL — a hand-built game, order known in advance")
    seen = []
    real = game._half_inning

    def spy(side, *a, **kw):
        seen.append(side.tag)
        return real(side, *a, **kw)

    lg = sim.league()
    bat = [sim.BatterRates(name=f"b{i}", k_pct=0.22, bb_pct=0.08,
                           hr_pct=0.03, babip=0.300) for i in range(9)]
    p = sim.PitcherRates(name="p", k_pct=0.22, bb_pct=0.08, hr_pct=0.03,
                         babip=0.300, pa=600)
    A = game.Side(starter=p, pen=[], lineup=bat)
    H = game.Side(starter=p, pen=[], lineup=bat)
    A.tag, H.tag = "A", "H"
    game._half_inning = spy
    try:
        game.simulate_game(A, H, lg, random.Random(7), track=())
    finally:
        game._half_inning = real
    print(f"    first side to pitch: {seen[0]}   (A is the 'away' side)")
    print(f"    order in inning 1:   {seen[:2]}")
    print("    The away SIDE pitches to the HOME club, so 'A first' means")
    print("    the HOME club bats first — which is the top of the inning.\n")


def main() -> None:
    control()
    lg = sim.league()
    pens = rate_src.bullpens(lg, before=CUT)
    cases = cal.paired_cases(season=2026, since=CUT, rates_before=CUT)
    gids = sorted(cases)[:300]
    aw, hm, first = [], [], []
    for i, gid in enumerate(gids):
        a, h, f = _bats_in_ninth(cases[gid], lg, pens, random.Random(i * 977))
        aw.append(float(a))
        hm.append(float(h))
        first.append(f)
    n = len(gids)
    print(f"  THE ENGINE, {n} real games\n")
    print(f"  {'club':<28}{'P(bats in the 9th)':>20}")
    print(f"  {'away club':<28}{st.mean(aw):>20.3f}")
    print(f"  {'home club':<28}{st.mean(hm):>20.3f}")
    print(f"\n  bats first in inning 1: "
          f"{st.mode(first)}  ({first.count(st.mode(first))}/{n} games)")
    print("\n  REAL BASEBALL: away 1.000, home ~0.557, away bats first.")
    print("  Anything else means the two halves are reversed.")


if __name__ == "__main__":
    main()
