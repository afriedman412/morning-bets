"""The prefix ladder under each day-five flag state, compared PAIRED.

`src/context/ladder.py` already does the diagnosis — F1/F3/F5/F7 read off one
simulated game, marginal error per inning, seeded per (game, draw) so the
states are comparable. What it does not do is compare two states, and doing
that by eye across two of its reports is the wrong statistic.

WHY PAIRED, AND IT IS NOT A DETAIL. The spread of the error ACROSS games is
huge — a 14-run slugfest is mis-predicted by both states by a lot — so the
standard error on any one state's mean error is around +/-0.28 runs and
swamps a 0.10-run improvement. But both states run the SAME games on the
SAME seeds, so the per-game DIFFERENCE cancels the game itself. Averaging
those differences is roughly an order of magnitude more sensitive than
comparing two noisy means, and it is the only way a real effect this size
becomes visible without an implausible number of games.

WHAT A GENUINE BULLPEN IMPROVEMENT LOOKS LIKE. F1 must not move at all —
`ladder` is seeded so that it cannot, and `check_the_first_inning_is_immune
_to_a_bullpen_flag` pins it. F3 is the rate model and should barely move.
F7 is the first prefix with real bullpen exposure and is where the work has
to pay.

    venv/bin/python -m scratchpad.ladder_states [since] [--sims=N] [--limit=N]
"""
import statistics as st
import sys

from src.context import calibrate as cal
from src.context import game, ladder, sim
from src.context.sources import innings as inn_src
from src.context.sources import rates as rate_src

SINCE = next((a for a in sys.argv[1:] if not a.startswith("-")), "2026-07-01")
N, LIM = 60, None
for a in sys.argv:
    if a.startswith("--sims="):
        N = int(a.split("=")[1])
    if a.startswith("--limit="):
        LIM = int(a.split("=")[1])

STATES = [
    ("all off (pre-day-five)", False, False),
    ("+ relief length", True, False),
    ("+ mid-inning hook", True, True),
]


def main() -> None:
    lg = sim.league()
    pens = rate_src.bullpens(lg)
    by: dict[str, list] = {}
    for s, p, l in cal.build_cases(since=SINCE, rates_before=SINCE):
        by.setdefault(s["game_id"], []).append((s, p, l))
    by = {g: v for g, v in by.items()
          if len(v) == 2 and sum(bool(x[0]["is_home"]) for x in v) == 1}
    actual = {p: inn_src.prefix_totals(p, since=SINCE)
              for p in ladder.PREFIXES}
    usable = [g for g in by if all(g in actual[p] for p in ladder.PREFIXES)]
    if LIM:
        usable = usable[:LIM]
    by = {g: by[g] for g in usable}
    print(f"{len(by)} games since {SINCE}, n_sims={N}\n", flush=True)

    # state -> prefix -> {game_id: signed error}
    errs: dict[str, dict] = {}
    for label, length, hook in STATES:
        game.USE_MEASURED_RELIEF_LENGTH = length
        game.USE_MEASURED_RELIEF_HOOK = hook
        simd = ladder.simulate_prefixes(by, pens, lg, n_sims=N)
        errs[label] = {p: {g: simd[g][p] - actual[p][g]["total"]
                           for g in simd} for p in ladder.PREFIXES}
        print(f"  simulated {label}", flush=True)

    base = STATES[0][0]
    print("\n== signed error (sim - actual), runs. Negative = too few. ==")
    print(f"  {'state':<26}" + "".join(f"{'F' + str(p):>10}"
                                       for p in ladder.PREFIXES))
    for label, *_ in STATES:
        row = "".join(f"{st.mean(errs[label][p].values()):>+10.3f}"
                      for p in ladder.PREFIXES)
        print(f"  {label:<26}{row}")

    print(f"\n== PAIRED change vs '{base}', per game, same seeds ==")
    print("   negative = the error moved toward zero, i.e. better")
    for label, *_ in STATES[1:]:
        print(f"  {label}")
        for p in ladder.PREFIXES:
            a, b = errs[base][p], errs[label][p]
            gids = [g for g in a if g in b]
            # Improvement in ABSOLUTE error, paired per game.
            d = [abs(b[g]) - abs(a[g]) for g in gids]
            m = st.mean(d)
            se = st.pstdev(d) / len(d) ** 0.5 if len(d) > 1 else 0.0
            # And the raw signed shift, which says WHICH WAY it moved.
            sd = st.mean(b[g] - a[g] for g in gids)
            print(f"    F{p:<3} |err| {m:+.4f} +/- {se:.4f} "
                  f"({m / se if se else 0:+.1f} sigma)   "
                  f"signed shift {sd:+.4f}")

    print("\n  F1 should be ~0. It is not required to be EXACTLY 0: a")
    print("  starter knocked out in the first inning really does hand the")
    print("  ball to a reliever inside F1, so a bullpen flag can reach it")
    print("  in those games. A reading of more than a few thousandths is")
    print("  the seeding regressing, and then nothing here is readable.")


if __name__ == "__main__":
    main()
