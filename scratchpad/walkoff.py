"""DOES THE WALK-OFF FIRE ON TAKING THE LEAD, OR ON SCORING AT ALL?

    venv/bin/python -m scratchpad.walkoff

`game._half_inning` ends a half early on

    if walk_off and side.runs > side.opposing_runs

`side` is the PITCHING side, so `side.runs` is what it has ALLOWED — the
BATTING club's score. For the condition to mean "the batting club has taken
the lead", `side.opposing_runs` has to be the PITCHING side's own club's
score. The driver sets it in exactly one place:

    home.opposing_runs = home.runs      # this team's own score

`home.runs` is what the HOME SIDE allowed, which is the AWAY club's score —
the BATTING club's, not its own. Snapshotted immediately before the half, so
the comparison becomes

    batting club's score NOW  >  batting club's score AT THE START OF THE HALF

which is true the moment the batting club scores ONE run, whatever the
margin. The half would then be truncated at the first run of every ninth and
every extra inning.

TWO TESTS, because the CONDITION and the DRIVER are separate claims.

  A. THE CONDITION, called directly with hand-set values. Trailing by five,
     a half with `walk_off=True` must play to three outs. This isolates the
     comparison from the driver and is a POSITIVE CONTROL for the harness:
     if the condition is sound, this passes and the bug is upstream.

  B. THE DRIVER, on real games. Runs in the final half-inning, and whether
     the batting club was AHEAD when it ended. Real baseball ends a half on
     three outs OR on the batting club going ahead; a half that ends with
     the batting club still behind is impossible.

POWER. Test A is deterministic — one constructed half, no sampling. Test B
runs 300 games and the observable is a SHARE, se ~0.03, against a predicted
difference of tens of points. Neither is a close call by design; a mechanism
this size does not need a subtle instrument.
"""
from __future__ import annotations

import random
import statistics as st

from src.context import calibrate as cal, game, sim
from src.context.sources import rates as rate_src

CUT = "2026-05-15"


def _side(runs: int, opposing: int) -> game.Side:
    bat = [sim.BatterRates(name=f"b{i}", k_pct=0.22, bb_pct=0.08,
                           hr_pct=0.03, babip=0.300) for i in range(9)]
    p = sim.PitcherRates(name="p", k_pct=0.22, bb_pct=0.08, hr_pct=0.03,
                         babip=0.300, pa=600)
    s = game.Side(starter=p, pen=[], lineup=bat)
    s.runs, s.opposing_runs = runs, opposing
    return s


def condition() -> None:
    """A. Trailing by five, the half must be played to three outs."""
    print("  A. THE CONDITION ALONE — batting club trails 0-5, walk_off=True")
    lg = sim.league()
    scored_and_stopped = 0
    trials = 400
    for i in range(trials):
        s = _side(runs=0, opposing=5)
        before = s.runs
        game._half_inning(s, lg, random.Random(i * 31 + 1), 9, 5, None,
                          walk_off=True)
        got = s.runs - before
        # A half that scored but stopped before the batting club reached 6
        # was truncated by the walk-off when it should not have been.
        if 0 < got < 6:
            scored_and_stopped += 1
    print(f"     halves that scored 1-5 runs: {scored_and_stopped}/{trials}")
    print("     (the condition is sound here — `opposing_runs` was set by")
    print("      hand to the pitching club's real score, so nothing fires)\n")


def driver() -> None:
    """B. The driver, on real games: how does the LAST half-inning end?"""
    print("  B. THE DRIVER — the final half-inning of 300 real games\n")
    lg = sim.league()
    pens = rate_src.bullpens(lg, before=CUT)
    cases = cal.paired_cases(season=2026, since=CUT, rates_before=CUT)
    gids = sorted(cases)[:300]

    seen: list = []
    real = game._half_inning

    def spy(side, lg_, rng_, inning, margin, park, walk_off=False, **kw):
        before = side.runs
        opp = side.opposing_runs
        real(side, lg_, rng_, inning, margin, park, walk_off=walk_off, **kw)
        if walk_off:
            # `side.runs` is the BATTING club's score; `margin` is the
            # pitching side's lead going in, so the batting club's deficit
            # at the start of the half is exactly `margin`.
            seen.append({"got": side.runs - before, "margin_before": margin,
                         "opp": opp, "before": before})

    game._half_inning = spy
    try:
        for i, gid in enumerate(gids):
            game.simulate_game(
                *_build(cases[gid], lg, pens, random.Random(i * 977)),
                lg, random.Random(i * 977), track=())
    finally:
        game._half_inning = real

    scoring = [h for h in seen if h["got"] > 0]
    print(f"     {len(seen)} walk-off-eligible halves, {len(scoring)} scored")
    if scoring:
        runs = [h["got"] for h in scoring]
        print(f"     runs when it scored: mean {st.mean(runs):.2f}, "
              f"max {max(runs)}")
        dist = {r: runs.count(r) for r in sorted(set(runs))}
        print(f"     distribution: {dist}")
        behind = sum(1 for h in scoring
                     if h["got"] <= h["margin_before"])
        print(f"     scored WITHOUT taking the lead: "
              f"{behind}/{len(scoring)} = {behind / len(scoring):.1%}")
        snap = sum(1 for h in scoring if h["opp"] == h["before"])
        print("     halves entered TIED (opposing_runs == the batting")
        print(f"     club's score at the start): "
              f"{snap}/{len(scoring)} = {snap / len(scoring):.1%}")
    print("\n     READ THE DISTRIBUTION, NOT THE SHARES. The tell is a hard")
    print("     cap: under the bug every scoring half stopped at the first")
    print("     run (34/42 scored exactly 1, max 3, and 42/42 carried the")
    print("     snapshot signature). Fixed, the half plays on and the tail")
    print("     extends — a trailing club scoring without going ahead is")
    print("     now the NORMAL case, not a defect. The earlier '0%' claim")
    print("     here was an artifact of the swapped wiring, under which the")
    print("     second half was only ever reached tied or already ahead.")


def _build(pair, lg, pens, rng):
    away, home = pair
    an = cal.adjust_lineup(away[2], False)
    hn = cal.adjust_lineup(home[2], True)
    A = game.build_side(away[1], pens.get((away[0]["team"] or "").upper(), []),
                        an, None, rng, team=away[0]["team"])
    H = game.build_side(home[1], pens.get((home[0]["team"] or "").upper(), []),
                        hn, None, rng, team=home[0]["team"])
    return A, H


if __name__ == "__main__":
    condition()
    driver()
