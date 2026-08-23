"""Who was right when the simulator disagreed with the book?

The only test that matters, and the only one this project could not run
until the simulator existed. Calibration says our probabilities are honest.
Beating the six-start estimator says we improved on our own baseline.
Neither says anything about whether a disagreement with a real price is
worth acting on — for that you need the price, our number, and the outcome,
all three.

HOW LEAKAGE IS AVOIDED, IN THREE PLACES.

  1. Rates are computed strictly BEFORE the game date, so a start cannot
     inform its own projection.
  2. The market price is the last trade BEFORE FIRST PITCH. Kalshi settles
     at 0 or 1, so the final trade on a settled contract is the box score
     wearing a price tag — an earlier CLV pass in this project was ruined
     exactly this way, with a losing over "closing" at 0.01.
  3. Hook offsets are whatever is on disk. They were fitted on the full
     season, so a date inside that window is NOT clean for them. Pass
     `refit_before` to refit on the training window; without it, read the
     result as optimistic.

WHAT A WIN WOULD LOOK LIKE. Not "our Brier is lower than the market's" —
that would be extraordinary and would mean something is wrong. The useful
question is narrower: on the subset where we disagree by a lot, does the
disagreement point the right way more often than chance?
"""
from __future__ import annotations


from src import kalshi, roster
from src.context import calibrate, price as price_mod, sim
from src.context.sources import rates as rate_src

#: Minimum trades before a quoted price is a price rather than one resting
#: order somebody forgot about.
MIN_TRADES = 5


def _outcomes(date_str: str, conn=None) -> dict[str, dict]:
    """{player_name: start line} for one date, from the local boxscore."""
    rows = calibrate.actual_starts()
    return {r["player_name"]: r for r in rows if r["date"] == date_str}


def collect(dates, stat="k", n_sims=2000, seed=0, verbose=True) -> list[dict]:
    """One row per settled market: our number, the market's, the result."""
    lg = sim.league()
    out: list[dict] = []
    lineups = calibrate.opposing_lineups()

    for d in dates:
        actual = _outcomes(d)
        if not actual:
            continue
        pr = rate_src.pitcher_rates(lg, before=d)
        br = rate_src.batter_rates(lg, before=d)
        league_bats = sim.BatterRates(
            name="league", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
            hr_pct=lg["hr_pct"], babip=lg["babip"])

        series = kalshi.SERIES_BY_STAT[stat]
        markets = [m for m in kalshi.settled_markets(series)
                   if kalshi.ticker_date(m["ticker"]) == d]
        cache: dict[str, list] = {}
        key_ok: dict[str, bool] = {}
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
            p = pr.get(row["player_name"])
            if not p:
                continue
            if key_ok.get(row["player_name"]) is None:
                key_ok[row["player_name"]] = price_mod.priceable(
                    row["player_name"], p["pa"], d)[0]
            if not key_ok[row["player_name"]]:
                continue

            pp = kalshi.price_path(m["ticker"], "over")
            if not pp or pp.get("close_prob") is None:
                continue
            if (pp.get("trades") or 0) < MIN_TRADES:
                continue
            mkt = pp["close_prob"]

            key = row["player_name"]
            if key not in cache:
                names = lineups.get((row["game_id"], row["team"])) or []
                if len(names) < 9:
                    continue
                nine = []
                for nm in names:
                    b = br.get(nm)
                    nine.append(sim.BatterRates(
                        name=nm, k_pct=b["k_pct"], bb_pct=b["bb_pct"],
                        hr_pct=b["hr_pct"], babip=b["babip"], pa=b["pa"])
                        if b else league_bats)
                pitcher = sim.PitcherRates(
                    name=key, k_pct=p["k_pct"], bb_pct=p["bb_pct"],
                    hr_pct=p["hr_pct"], babip=p["babip"], pa=p["pa"])
                hook = sim.for_start(sim.Hook(), row["team"], key)
                cache[key] = [x.outs if stat == "outs" else x.k
                              for x in sim.simulate(pitcher, nine, lg,
                                                    n=n_sims, hook=hook,
                                                    seed=seed)]
            vals = cache[key]
            ours = sum(1 for v in vals if v > line) / len(vals)
            got = row["k"] if stat == "k" else row["o"]
            out.append({
                "date": d, "player": key, "line": line, "stat": stat,
                "ours": ours, "market": mkt, "gap": ours - mkt,
                "won": got > line, "actual": got, "trades": pp["trades"],
            })
        if verbose:
            print(f"  {d}: {len([r for r in out if r['date'] == d])} markets",
                  flush=True)
    return out


def report(rows: list[dict]) -> None:
    if not rows:
        print("nothing collected")
        return
    n = len(rows)

    def brier(key):
        return sum((r[key] - (1 if r["won"] else 0)) ** 2 for r in rows) / n

    base = sum(1 for r in rows if r["won"]) / n
    bb = base * (1 - base)
    print(f"\n{n} settled markets, base rate {base:.1%}")
    print(f"  {'':<10}{'Brier':>9}{'vs base':>10}{'AUC':>8}")
    for lbl, key in (("market", "market"), ("sim", "ours")):
        auc = calibrate._auc([(r["won"], r[key]) for r in rows])
        print(f"  {lbl:<10}{brier(key):>9.4f}"
              f"{(bb - brier(key)) / bb:>+10.1%}{auc:>8.3f}")

    # ---- does our disagreement carry information the price lacks? ----
    #
    # NOT "(gap > 0) == won". That metric is confounded: the simulator runs
    # systematically high, so large positive gaps concentrate on longshots,
    # which mostly lose, and the score collapses without saying anything
    # about information content.
    #
    # The honest test is a blend. Price the bet at market + lam * gap and
    # sweep lam. If the best lam is 0, our disagreement adds nothing to a
    # price that already exists. If it is positive, it carries signal even
    # when our standalone number is worse than the market's.
    print("\n  blending our gap into the price: "
          "Brier at market + lam*gap")
    print(f"  {'lam':>6}{'Brier':>10}{'vs market':>11}")
    best = (None, 1e9)
    for lam in (0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0):
        b = sum((min(max(r["market"] + lam * r["gap"], 0.001), 0.999)
                 - (1 if r["won"] else 0)) ** 2 for r in rows) / n
        if b < best[1]:
            best = (lam, b)
        mk = brier("market")
        print(f"  {lam:>6.2f}{b:>10.4f}{(mk - b) / mk:>+11.2%}")
    print(f"  best lam {best[0]:.2f}"
          + ("   <- our gap adds nothing to the price" if best[0] == 0.0
             else "   <- our gap carries information the price lacks"))

    # Kept for reference, with its confound stated in the footer.
    print("\n  (confounded) when the sim disagrees, who is right?")
    print(f"  {'|gap|':<12}{'n':>6}{'sim right':>11}{'p(binom)':>10}"
          f"{'mkt Brier':>11}{'sim Brier':>11}")
    import math

    def binom_p(k, n_, p=0.5):
        return sum(math.comb(n_, i) * p ** i * (1 - p) ** (n_ - i)
                   for i in range(k, n_ + 1))

    for lo, hi in ((0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 1.0)):
        g = [r for r in rows if lo <= abs(r["gap"]) < hi]
        if len(g) < 20:
            continue
        # "Right" = the side we leaned toward is the side that happened.
        right = sum(1 for r in g
                    if (r["gap"] > 0) == r["won"])
        mb = sum((r["market"] - (1 if r["won"] else 0)) ** 2 for r in g)/len(g)
        sb = sum((r["ours"] - (1 if r["won"] else 0)) ** 2 for r in g)/len(g)
        print(f"  {f'{lo:.2f}-{hi:.2f}':<12}{len(g):>6}"
              f"{right / len(g):>11.1%}{binom_p(right, len(g)):>10.3f}"
              f"{mb:>11.4f}{sb:>11.4f}")
    print("\n  the band table above is CONFOUNDED with price level — a"
          " model that")
    print("  runs high puts its big gaps on longshots, which lose. Read the"
          " blend.")
    print("  A market Brier BELOW ours in every band is the expected result")
    print("  and is not a failure — it is what an efficient market looks"
          " like.")


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    stat = "outs" if "--outs" in sys.argv else "k"
    dates = args or [f"2026-08-{d:02d}" for d in range(14, 22)]
    report(collect(dates, stat=stat))
