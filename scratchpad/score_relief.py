"""Score the three relief mechanisms on the ACTUAL F5 team totals.

This is the benchmark the project actually declares — not a market. Kalshi
does not list an F5 team total at all (the cached series are KXMLBKS,
KXMLBTEAMTOTAL for FULL-game team runs, and KXMLBF5TOTAL for the COMBINED
first-five total), and that is by design: `fitf5.SIDE_LINES` scores the
simulated distribution against what actually happened across the whole
support, because scoring against a book's liquid lines "would tune the model
to the shape of somebody's board".

`side_cases` gives one row per pitching side with `runs` = what that side
ACTUALLY allowed through five, which is the opposing team's F5 score. So the
loss below is exactly "how well do we simulate one team's runs through five",
measured on outcomes.

Same shape as `score_adv.py`: paired on the same sides, outcomes and salts,
train before the cut and test after, because the unpaired sd on this
objective is 2.6x the paired one and would swallow every real move.

Lower loss is better.

    venv/bin/python -m scratchpad.score_relief [n_sims]
"""
import sys

from src.context import fitf5, game, sim

CUT = "2026-07-01"

lg = sim.league()
train = fitf5.side_cases(before=CUT, rates_before=CUT)
test = fitf5.side_cases(since=CUT, rates_before=CUT)
print(f"train {len(train)} sides before {CUT}, test {len(test)} on/after",
      flush=True)

params = fitf5.defaults()
N = int(sys.argv[1]) if len(sys.argv) > 1 else 250

# Cumulative, in the order they were built, so each line shows what that one
# mechanism added on top of the previous state rather than in isolation.
STATES = [
    ("all off (pre-day-five)", False, False, False),
    ("+ relief length", True, False, False),
    ("+ mid-inning relief hook", True, True, False),
    ("+ inherited by base/out", True, True, True),
]

results = {}
for label, length, hook, inherited in STATES:
    game.USE_MEASURED_RELIEF_LENGTH = length
    game.USE_MEASURED_RELIEF_HOOK = hook
    sim.USE_MEASURED_INHERITED = inherited
    tr = fitf5.losses(train, params, N, lg)
    te = fitf5.losses(test, params, N, lg)
    results[label] = (tr, te)
    print(f"  {label:<26} train {sum(tr)/len(tr):.5f}   "
          f"test {sum(te)/len(te):.5f}", flush=True)

base = results[STATES[0][0]]
print("\n  PAIRED vs the pre-day-five engine (negative = better), on TEST:")
for label, (tr, te) in results.items():
    if label == STATES[0][0]:
        continue
    d, se = fitf5._paired_se(base[1], te)
    print(f"    {label:<26} {d:+.5f} +/- {se:.5f}   "
          f"({d/se if se else 0:+.1f} sigma)")

print("\n  and on TRAIN:")
for label, (tr, te) in results.items():
    if label == STATES[0][0]:
        continue
    d, se = fitf5._paired_se(base[0], tr)
    print(f"    {label:<26} {d:+.5f} +/- {se:.5f}   "
          f"({d/se if se else 0:+.1f} sigma)")

print("\n  The high-n ratio the notes prefer over a low-n aggregate:")
for label, _ in results.items():
    i = [s[0] for s in STATES].index(label)
    _, length, hook, inherited = STATES[i]
    game.USE_MEASURED_RELIEF_LENGTH = length
    game.USE_MEASURED_RELIEF_HOOK = hook
    sim.USE_MEASURED_INHERITED = inherited
    r = fitf5.evaluate(test, params, n_sims=N, lg=lg, salt=0)
    print(f"    {label:<26} sim runs/side {r['sim_runs']:.3f} "
          f"sd {r['sim']['sd']:.3f}   actual {r['act_runs']:.3f} "
          f"sd {r['act']['sd']:.3f}")

print("\n  Measured mechanisms STAY regardless. A worse score locates the")
print("  compensation; it does not license un-measuring a constant.")
