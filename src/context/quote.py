"""Price one bet you are looking at. Book price in, verdict out.

    venv/bin/python -m src.context.quote "Yusei Kikuchi" k under 4.5 +102

WHAT THIS IS FOR. Not finding edges — measured, we do not have any: the
simulator's disagreements with Kalshi carry zero information. Blending our
gap into the price scores WORSE at every weight, best weight 0.00, over
3,366 settled K markets. What it answers is the question that IS reliably
answerable: is the price in front of you fair, and where is fair coming
from.

RE-MEASURED 2026-08-26 on the current engine. The figures here used to come
off `sim.simulate`, a one-sided loop with no bullpen, no margin and no
opposing offence, which was deleted that morning. The conclusion did not
change; some of the numbers did, and where they did it is noted.

THE HIERARCHY, IN ORDER OF TRUST.

  1. KALSHI, when it lists the contract with a tight book. It is an
     exchange — the two sides sum to about 1.01 against 1.04-1.05 at a
     retail book — and it beats our simulator head to head (Brier 0.1576
     vs 0.1636, AUC 0.847 vs 0.836, August, 3,366 markets). If Kalshi has
     it, Kalshi is the answer and the simulator is a footnote.
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
#: Small, because Kalshi's own error is small — it beat the simulator head
#: to head and its two sides sum to about 1.01.
NOTABLE_MARKUP = 0.02

#: Cents the book must differ from the SIMULATOR before we will say
#: anything at all, when Kalshi has no contract to check against.
#:
#: Measured, not chosen for comfort, and RE-MEASURED on 2026-08-26 after the
#: one-sided engine was deleted — the old figures came off an engine that no
#: longer exists. 3,366 settled K markets, August:
#:
#:     |gap|          n   mkt Brier  sim Brier
#:     0.00-0.05   1985      0.1407     0.1424
#:     0.05-0.10    921      0.1728     0.1769
#:     0.10-0.20    428      0.2023     0.2214
#:     0.20-1.00     32      0.1660     0.3153
#:
#: THE OLD CLAIM THAT WE BEAT KALSHI INSIDE FIVE CENTS DID NOT SURVIVE. It
#: read 0.1351 against 0.1379; the market is now marginally better in every
#: band. What did survive, and got stronger, is the shape: the error is not
#: symmetric in usefulness, and where we disagree by 20+ cents our Brier is
#: nearly double the market's and we are right 21.9% of the time. The sim is
#: least wrong precisely when it agrees and worst precisely when it does not.
#:
#: RETAIL MARKUP IS 2-5 CENTS AND OUR NOISE IS ~5. So the simulator cannot
#: do the job Kalshi does — it cannot separate a fair price from a marked-up
#: one, because its own error is the same size as the quantity. It can only
#: catch gross mispricing. Anything under this bar is silence, deliberately.
SIM_ONLY_BAR = 0.10


def american_to_prob(odds: str | int | float) -> float | None:
    """Break-even probability at an American price."""
    try:
        a = float(str(odds).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if a == 0:
        return None
    return abs(a) / (abs(a) + 100) if a < 0 else 100 / (a + 100)


#: Simulated games behind one quote. Fewer than `price.N_SIMS` per market
#: would be false economy here — a quote is one bet, looked at once.
N_SIMS = 20000


def _sim_prob(name, stat, line, side, d):
    """(prob, push, note). `prob` is None when the model declines.

    THE OPPOSING STARTER IS REQUIRED. This used to price the named pitcher
    alone through `sim.simulate`, an engine that modelled one pitching side
    in isolation and could not see its own team's runs. It now simulates the
    whole game, so a matchup with no modelled opponent DECLINES rather than
    being given a league-average one — the same posture as an opener or a
    game already in progress.
    """
    lg = sim.league()
    pr = rate_src.pitcher_rates(lg, before=d)
    p = pr.get(name)
    if not p:
        return None, None, "no rates on record"
    ok, why = price_mod.priceable(name, p["pa"], d)
    if not ok:
        return None, None, why

    br = rate_src.batter_rates(lg, before=d)
    league_bats = sim.BatterRates(
        name="league", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
        hr_pct=lg["hr_pct"], babip=lg["babip"])
    pens = rate_src.bullpens(lg, before=d)

    for g in price_mod.slate(d):
        for s_key, o_key in (("away", "home"), ("home", "away")):
            if g[s_key]["starter"] != name:
                continue
            o = g[o_key]
            games, whynot = price_mod.simulate_slate_game(
                g, d, lg, pr, br, league_bats, pens, n_sims=N_SIMS)
            if games is None:
                return None, None, whynot
            res = price_mod.starter_line(games, s_key == "home")
            attr = "k" if stat == "k" else "outs"
            over = sim.prob_over(res, attr, line)
            push = sim.prob_push(res, attr, line)
            note = (f"{p['pa']} BF, vs {o['abbr']}, "
                    f"{'confirmed' if o['lineup'] else 'PROJECTED'} lineup")
            # Both sides are P(strictly past the line), so on an integer
            # line they sum to 1 - push rather than to 1.
            under = 1.0 - over - push
            return (over if side == "over" else under), push, note
    return None, None, "not a listed probable starter today"


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
    ours, push, note = _sim_prob(name, stat, line, side, d)
    out["sim"] = ours
    out["sim_push"] = push
    out["sim_note"] = note

    # A BOOK'S INTEGER LINE AND KALSHI'S THRESHOLD ARE DIFFERENT BETS.
    # DraftKings' over-9.0 refunds at exactly 9; the contract that looks
    # like it, threshold 10, settles NO at 9 and pays nothing back. So the
    # book's break-even is not comparable to Kalshi's price until the push
    # mass is taken out of it. Breaking even needs
    #     P(win) * b = P(lose) = 1 - P(win) - P(push)
    # so the required win probability is the usual implied number scaled by
    # (1 - P(push)). Half-point lines have push = 0 and nothing changes.
    book_win = book_p
    if book_p is not None and push:
        book_win = book_p * (1.0 - push)
    out["offered_win_prob"] = book_win

    print(f"\n  {name} — {side} {line:g} {stat}"
          + (f"  at {offered}" if offered else ""))
    if book_p:
        print(f"    your book implies      {book_p:.3f}")
        if push:
            print(f"      minus a {push:.1%} push at exactly {line:g}, it "
                  f"only needs to WIN {book_win:.3f}")
        elif line == int(line):
            print(f"      NOTE: {line:g} can push at your book and cannot on "
                  f"Kalshi, and the model would not size the push")

    if k and k.get("mid_prob") is not None:
        b, a = kalshi.book(k["ticker"])
        ask = a if side == "over" else 1.0 - b
        print(f"    Kalshi fair (mid)      {k['mid_prob']:.3f}   "
              f"{k['mid_american']}")
        print(f"    Kalshi ask (tradeable) {ask:.3f}   "
              f"{kalshi.american(ask)}   spread {k['spread']:.2f}"
              + ("" if k["usable"] else "   <- TOO WIDE to trade off"))
        out["kalshi_ask"] = ask
        if book_win is not None and k["usable"]:
            markup = book_win - ask
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
            print(f"       advisory only — blending our gap into the "
                  f"price scores WORSE at every weight (3,366 markets)")
        elif book_win is not None:
            # No exchange price, so the simulator is all there is. Speak
            # only above the bar its own measured error justifies.
            d_ = book_win - ours
            if abs(d_) < SIM_ONLY_BAR:
                print(f"       within {SIM_ONLY_BAR * 100:.0f} cents of our"
                      f" number ({d_ * 100:+.1f}) — that is inside our own"
                      f" error, so we have NOTHING to say")
            else:
                print(f"       {d_ * 100:+.1f} cents vs our number — past the"
                      f" {SIM_ONLY_BAR * 100:.0f}c bar, so worth a look, but"
                      f" this is the regime where we are least reliable")
    else:
        print(f"    simulator              declines — {note}")

    hist = _history(name, stat, line, d)
    if hist:
        vals = [h["v"] for h in hist]
        pushes = sum(1 for v in vals if v == line)
        hit = sum(1 for v in vals
                  if v != line and (v > line) == (side == "over"))
        print(f"    his last {len(vals)} starts        {vals[::-1]}")
        print(f"       this side hit {hit}/{len(vals) - pushes}"
              + (f", {pushes} push" if pushes else "")
              + "  (small sample; not a probability)")
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 4:
        print(__doc__.strip().splitlines()[2].strip())
        sys.exit(1)
    quote(a[0], a[1], a[2], float(a[3]),
          a[4] if len(a) > 4 else None,
          a[5] if len(a) > 5 else None)
