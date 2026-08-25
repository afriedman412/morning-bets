"""Why is August different?

The whole recorded K-prop edge lives in one month — June +1.8c, July +1.7c,
August +3.3c — and it is not Monte Carlo error, not the advancement tables,
and not a maturation curve (July is the worst of the three, so the shape is
a V rather than a ramp).

This decomposes the edge WITHIN each month rather than comparing months, so
a composition change shows up as a shift in which bucket carries the edge
rather than as an unexplained level difference. Three candidates:

  * LIQUIDITY. Markets per date roughly triples June -> August (49, 101,
    151), so Kalshi was adding coverage. If the marginal listed market is
    opened less carefully, the edge should concentrate in the low-trade
    bucket and August should hold proportionally more of them.
  * HEADROOM. The CLV metric predicts `close - open`. If June opens already
    sit near their closes there is less to predict, and a flat edge would
    look small purely for want of movement.
  * POPULATION. `price.priceable` declines thin-sample arms, so early in the
    season only established starters qualify — exactly the pitchers a market
    prices well. The gate admits a different population each month.

    venv/bin/python -m scratchpad.why_august [n_sims]
"""
import statistics as st
import sys
from collections import defaultdict

from scratchpad.clv_nsims import _dates, clv
from src.context import versus_market

MONTHS = [("June", "2026-06-01", "2026-06-30"),
          ("July", "2026-07-01", "2026-07-31"),
          ("August", "2026-08-01", "2026-08-21")]

N = int(sys.argv[1]) if len(sys.argv) > 1 else 1500


def bucket_trades(t):
    if t < 10:
        return "thin <10"
    if t < 30:
        return "10-29"
    if t < 100:
        return "30-99"
    return "100+"


def line(label, s):
    if s is None:
        return f"    {label:<12} (too few rows)"
    d = "--" if s["direction"] is None else f"{s['direction']:.1%}"
    c = "--" if s["cents"] is None else f"{s['cents']:+.1f}c"
    return (f"    {label:<12} n={s['n']:<5} corr {s['corr']:+.3f}  "
            f"blend {s['blend']:+6.1%}  5c+ {s['n_big']:<5} dir {d:<7} {c}")


rows_by_month = {}
for name, a, b in MONTHS:
    rows = versus_market.collect(_dates(a, b), stat="k", n_sims=N,
                                 verbose=False)
    rows = [r for r in rows if r.get("open") is not None]
    rows_by_month[name] = rows
    print(f"{name}: {len(rows)} settled contracts", flush=True)

print("\n== HEADROOM: how far does the market actually move? ==")
print(f"    {'month':<12}{'|close-open|':>14}{'sd':>9}{'trades':>9}"
      f"{'open':>8}{'close':>8}")
for name, rows in rows_by_month.items():
    mv = [abs(r["market"] - r["open"]) for r in rows]
    print(f"    {name:<12}{st.mean(mv):>14.4f}"
          f"{st.pstdev([r['market'] - r['open'] for r in rows]):>9.4f}"
          f"{st.mean([r['trades'] for r in rows]):>9.1f}"
          f"{st.mean([r['open'] for r in rows]):>8.3f}"
          f"{st.mean([r['market'] for r in rows]):>8.3f}")

print("\n== LIQUIDITY: where does the edge sit inside each month? ==")
for name, rows in rows_by_month.items():
    print(f"  {name}")
    by = defaultdict(list)
    for r in rows:
        by[bucket_trades(r["trades"])].append(r)
    for b in ("thin <10", "10-29", "30-99", "100+"):
        if b in by:
            share = len(by[b]) / len(rows)
            print(line(f"{b} ({share:.0%})", clv(by[b])))

print("\n== POPULATION: does the gate admit different arms? ==")
print(f"    {'month':<12}{'pitchers':>10}{'contracts/arm':>15}")
for name, rows in rows_by_month.items():
    arms = {r["player"] for r in rows}
    print(f"    {name:<12}{len(arms):>10}{len(rows)/max(len(arms),1):>15.1f}")

print("\n== the same arms, month over month ==")
common = set.intersection(*[{r["player"] for r in rows}
                            for rows in rows_by_month.values()])
print(f"    {len(common)} pitchers priced in all three months")
for name, rows in rows_by_month.items():
    sub = [r for r in rows if r["player"] in common]
    print(line(name, clv(sub)))
