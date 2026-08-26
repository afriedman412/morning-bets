"""Does the market price RECENT form, and does the simulator get it wrong?

THE CASE THAT MOTIVATED THIS. Braxton Ashcraft, 2026-08-24, over 5.5
strikeouts. Season-flat rates said 0.542; Kalshi said 0.405 — a 14-cent
disagreement, and squarely in the regime this project measured as its worst
(where sim and Kalshi differ by 10+ cents our Brier is 0.2556 against their
0.2197). Re-run with recency-weighted rates:

    season K% 0.2562  ->  P(6+ K) 0.542   (+13.7c vs Kalshi)
    21-day half-life  ->  P(6+ K) 0.434   ( +2.9c)
    14-day half-life  ->  P(6+ K) 0.409   ( +0.4c)

The whole disagreement dissolved. That suggests our "disagreements carry no
information" finding may not mean the model has no edge — it may mean the
model is reading the wrong season, and the market is not.

WHY IT IS ONLY A HYPOTHESIS. It is one pitcher on one line, decided after
looking, with a good story attached. Every one of the six dead features had
a good story. Kalshi's 0.405 could be low for reasons nothing to do with
recency — the opponent, a scratch, a park — and 14-day weighting could land
there by coincidence.

So it makes a sharp prediction and this measures it at scale: recency-
weighted rates should predict the MARKET PRICE better than season-flat rates
across many contracts. Two endpoints, and they answer different questions:

  * vs the CLOSING PRICE — does the market price recent form? If yes, our
    stale rates are manufacturing false disagreements.
  * vs the OUTCOME — is recency actually more accurate? The market being
    right and the market being followed are not the same claim, and only
    this one says whether recency improves the model rather than the fit to
    somebody else's opinion.

MEASURED 2026-08-24 AND IT IS DEAD. 510 settled strikeout markets:

    paired vs season-flat        closeness to close   Brier vs outcome
    21-day half-life             +0.0081 (+3.8 sd)    +0.0066 (+3.0 sd)
    14-day half-life             +0.0135 (+5.4 sd)    +0.0079 (+3.0 sd)

Recency is FURTHER from the market AND worse at predicting outcomes. Both
endpoints, both half-lives, same sign, 3-5 sigma. The Ashcraft case was a
coincidence, which is what a single case chosen after looking usually is.

Seven for seven now on imported baseball knowledge. The generalisation from
the founding measurement keeps holding: the market prices the consensus
construction, and a season-to-date rate IS the consensus construction —
shading it toward recent form moves away from what everyone else, including
the market, is doing.

`rate_src.pitcher_rates_recent` stays because it is harmless and switched
off (`HALF_LIFE_DAYS = None`), and because the next person to have this idea
should find this file rather than rebuild it.

SAME LEAKAGE GUARDS as `versus_market`: rates strictly before the game date,
prices taken before first pitch. The recency weighting inherits the cutoff,
so a half-life window can never reach past the game it is pricing.
"""
from __future__ import annotations

import random
import statistics as st
import sys

from src import kalshi, roster
from src.context import calibrate, price as price_mod, sim
from src.context import versus_market as vm
from src.context.sources import rates as rate_src
from src.context.versus_market import MIN_TRADES, _outcomes

#: Half-lives to compare against the season-flat baseline, in days. None is
#: the baseline itself.
HALF_LIVES = (None, 21.0, 14.0)


def collect(dates, stat="k", n_sims=1200, seed=0, verbose=True) -> list[dict]:
    """One row per settled market, with our number under EVERY half-life.

    ONLY THE PRICED PITCHER'S RATES MOVE. The paired case carries both
    starters and the half-life is swapped into one of them; his opponent
    keeps season-flat rates throughout. That is deliberate — the question is
    whether recency helps the arm being priced, and re-weighting both sides
    would confound it with a different run environment.
    """
    out: list[dict] = []
    pens = rate_src.bullpens(sim.league())

    for d in dates:
        actual = _outcomes(d)
        if not actual:
            continue
        # Baselines respect the cutoff too — see sim.league. Without it a
        # "before the game" fit is anchored to numbers that saw the game.
        lg = sim.league(before=d)
        rates = {hl: (rate_src.pitcher_rates(lg, before=d) if hl is None
                      else rate_src.pitcher_rates_recent(lg, before=d,
                                                         half_life=hl))
                 for hl in HALF_LIVES}
        pairs = vm.day_pairs(d)

        markets = [m for m in kalshi.settled_markets(
            kalshi.SERIES_BY_STAT[stat])
            if kalshi.ticker_date(m["ticker"]) == d]
        cache: dict[tuple, list] = {}
        for m in markets:
            parsed = kalshi._parse(m)
            if not parsed:
                continue
            name, threshold = parsed
            line = threshold - 0.5
            row = actual.get(name)
            if row is None:
                pid = roster.player_id(name)
                row = next((r for n, r in actual.items()
                            if pid and roster.player_id(n) == pid), None)
            if row is None:
                continue
            key = row["player_name"]
            base = rates[None].get(key)
            if not base or not price_mod.priceable(key, base["pa"], d)[0]:
                continue
            pp = kalshi.price_path(m["ticker"], "over")
            if not pp or pp.get("close_prob") is None:
                continue
            if (pp.get("trades") or 0) < MIN_TRADES:
                continue

            pair = pairs.get(row["game_id"])
            if pair is None:
                continue
            # Which half of the pair this contract is about. The other half
            # is the opposing starter and is left alone.
            mine = 1 if row["is_home"] else 0

            rec = {"date": d, "player": key, "line": line,
                   "market": pp["close_prob"], "open": pp.get("open_prob"),
                   "won": (row["k"] if stat == "k" else row["o"]) > line}
            ok = True
            for hl in HALF_LIVES:
                p = rates[hl].get(key)
                if not p:
                    ok = False
                    break
                ck = (key, hl)
                if ck not in cache:
                    pitcher = sim.PitcherRates(
                        name=key, k_pct=p["k_pct"], bb_pct=p["bb_pct"],
                        hr_pct=p["hr_pct"], babip=p["babip"], pa=p["pa"])
                    # Same case, same opponent, same lineups, same seeds —
                    # only this pitcher's rates differ between half-lives, so
                    # the comparison is paired on everything else.
                    swapped = list(pair)
                    c = swapped[mine]
                    swapped[mine] = (c[0], pitcher, c[2])
                    rng = random.Random(seed)
                    games = [calibrate.replay(tuple(swapped), lg, pens, rng)
                             for _ in range(n_sims)]
                    lines = [(g.home_sp if row["is_home"] else g.away_sp)
                             for g in games]
                    cache[ck] = [x.k if stat == "k" else x.outs
                                 for x in lines]
                vals = cache[ck]
                rec[f"hl_{hl}"] = sum(1 for v in vals if v > line) / len(vals)
            if ok:
                out.append(rec)
        if verbose:
            print(f"  {d}: {len([r for r in out if r['date'] == d])} markets",
                  flush=True)
    return out


def report(rows: list[dict]) -> None:
    n = len(rows)
    if n < 50:
        print(f"only {n} rows — not enough to say anything")
        return
    base = sum(1 for r in rows if r["won"]) / n
    bb = base * (1 - base)
    print(f"\n{n} settled markets, base rate {base:.1%}\n")
    print(f"  {'rates':<16}{'|gap| vs close':>16}{'Brier':>9}"
          f"{'vs base':>10}{'mean p':>9}")
    print(f"  {'Kalshi close':<16}{'':>16}"
          f"{sum((r['market'] - r['won']) ** 2 for r in rows) / n:>9.4f}"
          f"{(bb - sum((r['market'] - r['won']) ** 2 for r in rows) / n) / bb:>+10.1%}"
          f"{st.mean(r['market'] for r in rows):>9.3f}")
    for hl in HALF_LIVES:
        k = f"hl_{hl}"
        gap = st.mean(abs(r[k] - r["market"]) for r in rows)
        br_ = sum((r[k] - r["won"]) ** 2 for r in rows) / n
        lab = "season flat" if hl is None else f"half-life {hl:g}d"
        print(f"  {lab:<16}{gap:>16.4f}{br_:>9.4f}"
              f"{(bb - br_) / bb:>+10.1%}{st.mean(r[k] for r in rows):>9.3f}")

    # Paired against the season baseline, because both numbers price the
    # same contract and their errors share everything about it.
    print("\n  PAIRED against season-flat (negative = recency better):")
    for hl in HALF_LIVES[1:]:
        k = f"hl_{hl}"
        d_gap = [abs(r[k] - r["market"]) - abs(r["hl_None"] - r["market"])
                 for r in rows]
        d_br = [(r[k] - r["won"]) ** 2 - (r["hl_None"] - r["won"]) ** 2
                for r in rows]
        for lab, d in (("closeness to market", d_gap), ("Brier vs outcome",
                                                        d_br)):
            se = st.pstdev(d) / n ** 0.5
            print(f"    {f'{hl:g}d {lab}':<34}{st.mean(d):>+9.4f}"
                  f" +/- {se:.4f}  ({st.mean(d) / se:+.1f} sigma)")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    stat = "outs" if "--outs" in sys.argv else "k"
    dates = args or [f"2026-08-{d:02d}" for d in range(1, 24)]
    print(f"stat: {stat}")
    report(collect(dates, stat=stat))
