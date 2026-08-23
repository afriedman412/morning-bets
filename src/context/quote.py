"""Price one bet you are looking at. Book price in, verdict out.

    venv/bin/python -m src.context.quote "Yusei Kikuchi" k under 4.5 +102

WHAT THIS IS FOR. Not finding edges — measured, we do not have any: the
simulator's disagreements with Kalshi carry zero information (blend weight
0.00, corr with market residual -0.0044, t = -0.15 over 1,220 settled
markets). What it answers is the question that IS reliably answerable: is
the price in front of you fair, and where is fair coming from.

THE HIERARCHY, IN ORDER OF TRUST.

  1. KALSHI, when it lists the contract with a tight book. It is an
     exchange — the two sides sum to about 1.01 against 1.04-1.05 at a
     retail book — and it beat our simulator head to head (Brier 0.1547
     vs 0.1593, AUC 0.854 vs 0.845). If Kalshi has it, Kalshi is the answer
     and the simulator is a footnote.
  2. THE SIMULATOR, only where Kalshi has no market. It is market-quality
     but not market-beating, which is exactly the profile of a usable
     stand-in for a missing price and NOT of an edge.
  3. NOTHING, when the pitcher fails `price.priceable`. Openers and
     two-start arms get no number, because the last time the model was
     asked about one it said 64% against a market at 14%.

READ THE ASK, NOT THE MID. The midpoint is fair value; it is not a price
you can trade at. Comparing a book's number to Kalshi's mid says whether it
is fair. Comparing it to Kalshi's ask says whether to bet it there instead.
"""
from __future__ import annotations

import sys
from datetime import date

from src import db, kalshi
from src.context import price as price_mod
from src.context import sim
from src.context.sources import rates as rate_src

#: Cents of markup over the exchange before it is worth saying out loud.
NOTABLE_MARKUP = 0.02


def american_to_prob(odds: str | int | float) -> float | None:
    """Break-even probability at an American price."""
    try:
        a = float(str(odds).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if a == 0:
        return None
    return abs(a) / (abs(a) + 100) if a < 0 else 100 / (a + 100)


def _sim_prob(name, stat, line, side, d):
    """(prob, note). None when the model declines to answer."""
    lg = sim.league()
    pr = rate_src.pitcher_rates(lg, before=d)
    p = pr.get(name)
    if not p:
        return None, "no rates on record"
    ok, why = price_mod.priceable(name, p["pa"], d)
    if not ok:
        return None, why

    for g in price_mod.slate(d):
        for s_key, o_key in (("away", "home"), ("home", "away")):
            if g[s_key]["starter"] != name:
                continue
            s, o = g[s_key], g[o_key]
            if g["status"] not in ("Scheduled", "Pre-Game", "Warmup",
                                   "Delayed Start", "Preview"):
                return None, f"game is {g['status']} — never price a live one"
            names = o["lineup"] or price_mod.projected_lineup(o["abbr"], d)
            if len(names) < 9:
                return None, "could not build an opposing lineup"
            br = rate_src.batter_rates(lg, before=d)
            league_bats = sim.BatterRates(
                name="league", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
                hr_pct=lg["hr_pct"], babip=lg["babip"])
            nine = price_mod._build(names, br, league_bats)
            hook = sim.for_start(sim.Hook(), s["abbr"], name)
            res = sim.simulate(
                sim.PitcherRates(name=name, k_pct=p["k_pct"],
                                 bb_pct=p["bb_pct"], hr_pct=p["hr_pct"],
                                 babip=p["babip"], pa=p["pa"]),
                nine, lg, n=20000, hook=hook, seed=0)
            attr = "k" if stat == "k" else "outs"
            over = sim.prob_over(res, attr, line)
            note = (f"{p['pa']} BF, vs {o['abbr']}, "
                    f"{'confirmed' if o['lineup'] else 'PROJECTED'} lineup")
            return (over if side == "over" else 1 - over), note
    return None, "not a listed probable starter today"


def _history(name, stat, line, d, conn=None):
    col = "k" if stat == "k" else "outs_recorded"
    q = f"""select g.date, p.{col} v
            from mlb_pitching p join games g on g.game_id = p.game_id
            where p.player_name = ? and p.is_starter = 1
              and g.status = 'Final' and g.date < ?
            order by g.date desc limit 10"""

    def _run(c):
        return [dict(r) for r in c.execute(q, (name, d))]
    if conn is not None:
        return _run(conn)
    with db.connect() as c:
        return _run(c)


def quote(name: str, stat: str, side: str, line: float,
          offered: str | None = None, date_str: str | None = None) -> dict:
    d = date_str or date.today().isoformat()
    side = (side or "over").lower()
    out: dict = {"player": name, "stat": stat, "side": side, "line": line}

    book_p = american_to_prob(offered) if offered else None
    out["offered"] = offered
    out["offered_prob"] = book_p

    k = kalshi.price_prop(name, stat, line, side)
    out["kalshi"] = k
    ours, note = _sim_prob(name, stat, line, side, d)
    out["sim"] = ours
    out["sim_note"] = note

    print(f"\n  {name} — {side} {line:g} {stat}"
          + (f"  at {offered}" if offered else ""))
    if book_p:
        print(f"    your book implies      {book_p:.3f}")

    if k and k.get("mid_prob") is not None:
        b, a = kalshi.book(k["ticker"])
        ask = a if side == "over" else 1.0 - b
        print(f"    Kalshi fair (mid)      {k['mid_prob']:.3f}   "
              f"{k['mid_american']}")
        print(f"    Kalshi ask (tradeable) {ask:.3f}   "
              f"{kalshi.american(ask)}   spread {k['spread']:.2f}"
              + ("" if k["usable"] else "   <- TOO WIDE to trade off"))
        out["kalshi_ask"] = ask
        if book_p is not None and k["usable"]:
            markup = book_p - ask
            print(f"    -> your book is {markup * 100:+.1f} cents "
                  f"{'worse' if markup > 0 else 'BETTER'} than the exchange")
            if markup > NOTABLE_MARKUP:
                print(f"       take it on Kalshi instead, or pass")
            elif markup < -NOTABLE_MARKUP:
                print(f"       your book is genuinely better than fair here")
    else:
        print(f"    Kalshi                 not listed")

    if ours is not None:
        print(f"    simulator              {ours:.3f}   ({note})")
        if k and k.get("mid_prob") is not None:
            print(f"       advisory only — our disagreements measured "
                  f"zero information (t = -0.15)")
    else:
        print(f"    simulator              declines — {note}")

    hist = _history(name, stat, line, d)
    if hist:
        vals = [h["v"] for h in hist]
        hit = sum(1 for v in vals
                  if (v > line) == (side == "over"))
        print(f"    his last {len(vals)} starts        {vals[::-1]}")
        print(f"       this side hit {hit}/{len(vals)}"
              f"  (small sample; not a probability)")
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 4:
        print(__doc__.strip().splitlines()[2].strip())
        sys.exit(1)
    quote(a[0], a[1], a[2], float(a[3]),
          a[4] if len(a) > 4 else None,
          a[5] if len(a) > 5 else None)
