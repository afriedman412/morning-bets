"""Is the August edge just a market drift our high-running model matched?

`why_august` killed the composition explanations: restricted to the 101
pitchers priced in all three months the edge still doubles (+1.7c, +1.9c,
+3.2c), and August beats the other months inside every liquidity bucket
despite holding FEWER thin markets. What is left is that August markets
move more (sd of close-open +48%) AND our direction accuracy rises
(57.3% -> 70.5%), and the second does not follow from the first.

But August also DRIFTS: mean open 0.447, mean close 0.456, roughly +0.9c
toward the over, where June and July are flat. `sim` is documented as
running systematically high, so a permanently over-leaning model scores
direction points for free in a month whose market walks up. That is the
same confound `versus_market.report` already warns about for `(gap>0)==won`,
one level along.

The test: recompute the CLV statistics against CENTERED movement, i.e.
subtract each month's own mean(close-open) from every contract. If the edge
survives centering it is real information about WHICH markets move. If it
collapses, August is a directional drift the model happened to be pointing
at, and the honest number for planning is June/July.

Rows are cached to scratchpad/august_rows.json so this is cheap to re-run.

    venv/bin/python -m scratchpad.august_drift [n_sims]
"""
import json
import os
import statistics as st
import sys

from scratchpad.clv_nsims import _dates, clv
from src.context import versus_market

CACHE = "scratchpad/august_rows.json"
MONTHS = [("June", "2026-06-01", "2026-06-30"),
          ("July", "2026-07-01", "2026-07-31"),
          ("August", "2026-08-01", "2026-08-21")]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 1500

if os.path.exists(CACHE):
    data = json.load(open(CACHE))
    print(f"loaded cached rows from {CACHE}", flush=True)
else:
    data = {}
    for name, a, b in MONTHS:
        rows = versus_market.collect(_dates(a, b), stat="k", n_sims=N,
                                     verbose=False)
        data[name] = [r for r in rows if r.get("open") is not None]
        print(f"{name}: {len(data[name])} contracts", flush=True)
    json.dump(data, open(CACHE, "w"))
    print(f"cached to {CACHE}", flush=True)


def show(label, s):
    if s is None:
        return f"    {label:<10} (too few)"
    d = "--" if s["direction"] is None else f"{s['direction']:.1%}"
    c = "--" if s["cents"] is None else f"{s['cents']:+.1f}c"
    return (f"    {label:<10} n={s['n']:<5} corr {s['corr']:+.3f}  "
            f"blend {s['blend']:+6.1%}  dir {d:<7} {c}")


print("\n== the drift, and which way we lean ==")
print(f"    {'month':<10}{'drift(c-o)':>12}{'sd':>9}{'we say over':>13}"
      f"{'mkt closed over open':>22}")
for name, rows in data.items():
    mv = [r["market"] - r["open"] for r in rows]
    over = sum(1 for r in rows if r["ours"] > r["open"]) / len(rows)
    up = sum(1 for m in mv if m > 0) / len(mv)
    print(f"    {name:<10}{st.mean(mv):>+12.4f}{st.pstdev(mv):>9.4f}"
          f"{over:>13.1%}{up:>22.1%}")

print("\n== AS MEASURED (movement uncentred) ==")
for name, rows in data.items():
    print(show(name, clv(rows)))

print("\n== CENTRED: each month's own mean drift removed from the target ==")
for name, rows in data.items():
    mu = st.mean(r["market"] - r["open"] for r in rows)
    cent = [{**r, "market": r["market"] - mu} for r in rows]
    print(show(name, clv(cent)))

print("\n== and with OUR lean centred too (pure disagreement vs pure move) ==")
for name, rows in data.items():
    mu = st.mean(r["market"] - r["open"] for r in rows)
    lo = st.mean(r["ours"] - r["open"] for r in rows)
    cent = [{**r, "market": r["market"] - mu, "ours": r["ours"] - lo}
            for r in rows]
    print(show(name, clv(cent)))
