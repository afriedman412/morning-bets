"""Margin distribution for named games: moneyline, runline, F5 moneyline.

    venv/bin/python -m scratchpad.margin DATE n_sims ABBR [ABBR ...]

`card.py` reports a moneyline. A price quoted at -110 on a heavy favourite
is usually NOT a moneyline, so the margin distribution is what tells you
which market a number belongs to.
"""
from __future__ import annotations
import sys
from collections import Counter
from src.context import price, sim
from src.context.sources import rates as rate_src


def american(p):
    if p <= 0 or p >= 1:
        return "-"
    return f"{-100 * p / (1 - p):+.0f}" if p > 0.5 else f"{100 * (1 - p) / p:+.0f}"


def main(argv):
    d, n = argv[0], int(argv[1])
    only = {s.upper() for s in argv[2:]}
    lg = sim.league()
    pr, br = rate_src.pitcher_rates(lg), rate_src.batter_rates(lg)
    pens = rate_src.bullpens(lg)
    lb = sim.BatterRates(name="league", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
                         hr_pct=lg["hr_pct"], babip=lg["babip"])
    for g in price.slate(d):
        a, h = g.get("away") or {}, g.get("home") or {}
        if only and not ({a.get("abbr"), h.get("abbr")} & only):
            continue
        res, why = price.simulate_slate_game(g, d, lg, pr, br, lb, pens,
                                             n_sims=n)
        if not res:
            print(f"{a.get('abbr')} @ {h.get('abbr')}  DECLINED — {why}")
            continue
        N = len(res)
        marg = [r.home - r.away for r in res]          # + = home wins by
        print(f"\n  {a.get('abbr')} @ {h.get('abbr')}   {n} sims")
        hw = sum(1 for m in marg if m > 0) + 0.5 * sum(1 for m in marg if m == 0)
        print(f"    ML       {h.get('abbr')} {hw/N:.3f} ({american(hw/N)})"
              f"   {a.get('abbr')} {1-hw/N:.3f} ({american(1-hw/N)})")
        # RUNLINE: the favourite gives 1.5, so it needs a 2+ run win.
        rl_h = sum(1 for m in marg if m >= 2) / N
        rl_a = sum(1 for m in marg if m <= -2) / N
        print(f"    -1.5     {h.get('abbr')} {rl_h:.3f} ({american(rl_h)})"
              f"   {a.get('abbr')} {rl_a:.3f} ({american(rl_a)})")
        print(f"    +1.5     {h.get('abbr')} {1-rl_a:.3f} ({american(1-rl_a)})"
              f"   {a.get('abbr')} {1-rl_h:.3f} ({american(1-rl_h)})")
        f5 = [r.prefix_side[5] for r in res
              if getattr(r, "prefix_side", None) and 5 in r.prefix_side]
        if f5:
            # `prefix_side` is (away score, home score) through the inning.
            fh = sum(1 for x in f5 if x[1] > x[0]) / len(f5)
            fa = sum(1 for x in f5 if x[0] > x[1]) / len(f5)
            print(f"    F5 ML    {h.get('abbr')} {fh:.3f} ({american(fh)})"
                  f"   {a.get('abbr')} {fa:.3f} ({american(fa)})"
                  f"   tie {1-fh-fa:.3f}")
            print(f"    F5 team  {a.get('abbr')} {sum(x[0] for x in f5)/len(f5):.2f}"
                  f"   {h.get('abbr')} {sum(x[1] for x in f5)/len(f5):.2f}")
        c = Counter(marg)
        print("    margin   " + " ".join(
            f"{k:+d}:{c[k]/N:.3f}" for k in sorted(c) if -5 <= k <= 5))


if __name__ == "__main__":
    main(sys.argv[1:])
