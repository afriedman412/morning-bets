"""Score the measured mechanisms PAIRED on F5, all four combinations.

Two discrete changes, so four states, each scored on the same sides, the
same actual outcomes and the same salts. Paired, because the unpaired sd on
this objective is 2.6x the paired one and would swallow every real move.

Lower loss is better (discrete CRPS over the full support of the run
distribution, not a book's line menu).
"""
import itertools
import sys

from src.context import fitf5, sim

CUT = "2026-07-01"

lg = sim.league()
train = fitf5.side_cases(before=CUT, rates_before=CUT)
test = fitf5.side_cases(since=CUT, rates_before=CUT)
print(f"train {len(train)} sides before {CUT}, test {len(test)} on/after",
      flush=True)

params = fitf5.defaults()
N = int(sys.argv[1]) if len(sys.argv) > 1 else 120

results = {}
for adv, gidp in itertools.product((False, True), (False, True)):
    sim.USE_MEASURED_ADVANCEMENT = adv
    sim.USE_MEASURED_GIDP = gidp
    label = f"adv={'measured' if adv else 'published':<9} " \
            f"gidp={'measured' if gidp else 'published':<9}"
    tr = fitf5.losses(train, params, N, lg)
    te = fitf5.losses(test, params, N, lg)
    results[(adv, gidp)] = (tr, te)
    print(f"  {label}  train {sum(tr)/len(tr):.5f}   "
          f"test {sum(te)/len(te):.5f}", flush=True)

base = results[(False, False)]
print("\n  PAIRED vs the shipped model (negative = better), on TEST:")
for k, (tr, te) in results.items():
    if k == (False, False):
        continue
    d, se = fitf5._paired_se(base[1], te)
    adv, gidp = k
    name = ("advancement only" if adv and not gidp else
            "GIDP only" if gidp and not adv else "both")
    print(f"    {name:<20} {d:+.5f} +/- {se:.5f}   "
          f"({d/se if se else 0:+.1f} sigma)")

print("\n  and on TRAIN:")
for k, (tr, te) in results.items():
    if k == (False, False):
        continue
    d, se = fitf5._paired_se(base[0], tr)
    adv, gidp = k
    name = ("advancement only" if adv and not gidp else
            "GIDP only" if gidp and not adv else "both")
    print(f"    {name:<20} {d:+.5f} +/- {se:.5f}   "
          f"({d/se if se else 0:+.1f} sigma)")

# The high-n ratio the notes prefer over a low-n aggregate.
print("\n  runs per baserunner and the run level, each state:")
for k, _ in results.items():
    sim.USE_MEASURED_ADVANCEMENT, sim.USE_MEASURED_GIDP = k
    r = fitf5.evaluate(test, params, n_sims=N, lg=lg, salt=0)
    print(f"    adv={'M' if k[0] else 'P'} gidp={'M' if k[1] else 'P'}   "
          f"sim runs/side {r['sim_runs']:.3f}  sd {r['sim']['sd']:.3f}   "
          f"actual {r['act_runs']:.3f}  sd {r['act']['sd']:.3f}   "
          f"covered5 {r['sim_covered']:.1%} vs {r['act_covered']:.1%}")
