"""Did today's bullpen work actually improve the product?

Three mechanisms landed, each behind its own flag:

    game.USE_MEASURED_RELIEF_LENGTH   outings run to their measured length
    game.USE_MEASURED_RELIEF_HOOK     relievers can be pulled mid-inning
    sim.USE_MEASURED_INHERITED        DELETED 2026-08-25 with the one-sided
                                      engine. It settled a departing
                                      starter's stranded runners by coin
                                      flip because `simulate_start` could
                                      not simulate the reliever finishing
                                      the inning; the full game plays them
                                      out. It never reached this engine at
                                      all, so the old fourth state was
                                      always identical to the third.

Each is measured rather than fitted, so none of them is allowed to be
reverted on a bad score — a guess that happens to score well is still a
guess. What this run is for is LOCATING the compensation: if the measured
mechanisms score worse, something else in the model was absorbing their
absence, and that is a finding about the model rather than about them.

Scored against Kalshi on TEAM TOTALS, which is the stated product, paired on
the same contracts with the same seed so the only thing that moves is the
flags. Reported as CLV against the open, because nothing here has ever beaten
a settled close and the edge is being early.

    venv/bin/python -m scratchpad.relief_value [start] [end] [n_sims]
"""
import sys

from scratchpad.clv_nsims import _dates, clv
from src.context import game, team_market

start = sys.argv[1] if len(sys.argv) > 1 else "2026-08-01"
end = sys.argv[2] if len(sys.argv) > 2 else "2026-08-21"
N = int(sys.argv[3]) if len(sys.argv) > 3 else 400

dates = _dates(start, end)
print(f"team totals, {len(dates)} dates {dates[0]}..{dates[-1]}, n_sims={N}",
      flush=True)

STATES = [
    ("all off (pre-day-five)", False, False),
    ("length only", True, False),
    ("length + hook (shipped)", True, True),
]

for label, length, hook in STATES:
    game.USE_MEASURED_RELIEF_LENGTH = length
    game.USE_MEASURED_RELIEF_HOOK = hook
    rows = team_market.collect(dates, n_sims=N, verbose=False)
    rows = [r for r in rows if r.get("open") is not None]
    s = clv(rows)
    if s is None:
        print(f"  {label:<24} only {len(rows)} rows", flush=True)
        continue
    d = "--" if s["direction"] is None else f"{s['direction']:.1%}"
    c = "--" if s["cents"] is None else f"{s['cents']:+.1f}c"
    print(f"  {label:<24} n={s['n']:<5} corr {s['corr']:+.3f}  "
          f"blend {s['blend']:+6.1%}  5c+ {s['n_big']:<5} dir {d:<7} {c}  "
          f"| Brier skill ours {s['skill_ours']:+.1%} "
          f"mkt {s['skill_market']:+.1%}", flush=True)

print("\n  Measured mechanisms STAY regardless of this table. A worse score")
print("  locates compensation; it does not license un-measuring a constant.")
