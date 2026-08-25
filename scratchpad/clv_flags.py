"""Did the measured advancement/GIDP tables change the K-prop CLV edge?

`RESUME.md` records K props at corr +0.586, z +43.5, blend +32.9%, direction
73.2%, +3.7c. That was written in 13f5370, BEFORE the advancement tables were
measured. `sim.USE_MEASURED_ADVANCEMENT` and `sim.USE_MEASURED_GIDP` now
default to True, and the current code reproduces +0.516 at every n_sims from
250 to 2000 — a gap far larger than Monte Carlo error explains.

So the hypothesis is not "the recorded number was understated by n_sims". It
is "the recorded number was measured with the PUBLISHED constants, and the
measured ones scored worse on this market."

Four states on the same 1,222 contracts, same dates, same seed, same n_sims —
the K-prop counterpart of `score_adv.py`. Whatever it says, the measured
values stay: this locates the compensation, it does not adjudicate it.

    venv/bin/python -m scratchpad.clv_flags [start] [end] [n_sims]
"""
import itertools
import sys

from src.context import sim, versus_market
from scratchpad.clv_nsims import _dates, clv

start = sys.argv[1] if len(sys.argv) > 1 else "2026-08-14"
end = sys.argv[2] if len(sys.argv) > 2 else "2026-08-21"
N = int(sys.argv[3]) if len(sys.argv) > 3 else 1500

dates = _dates(start, end)
print(f"K props, {len(dates)} dates {dates[0]}..{dates[-1]}, n_sims={N}",
      flush=True)

results = {}
for adv, gidp in itertools.product((False, True), (False, True)):
    sim.USE_MEASURED_ADVANCEMENT = adv
    sim.USE_MEASURED_GIDP = gidp
    rows = versus_market.collect(dates, stat="k", n_sims=N, verbose=False)
    s = clv(rows)
    results[(adv, gidp)] = s
    label = (f"adv={'measured' if adv else 'published':<9} "
             f"gidp={'measured' if gidp else 'published':<9}")
    if s is None:
        print(f"  {label}  only {len(rows)} rows", flush=True)
        continue
    print(f"  {label}  n={s['n']}  corr {s['corr']:+.3f}  z {s['z']:+.1f}  "
          f"blend {s['blend']:+.1%}  5c+ n={s['n_big']} "
          f"dir {s['direction']:.1%}  {s['cents']:+.1f}c", flush=True)

print("\n  recorded in RESUME.md (13f5370, pre-advancement):")
print("    corr +0.586  z +43.5  blend +32.9%  dir 73.2%  +3.7c")
