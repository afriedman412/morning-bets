"""Scan every offered line and surface where the data robustly disagrees.

This is the tool the rest of the context layer was built to feed. Not
"predict the game" — the market already prices the consensus construction,
and an estimator built the same way measured AUC 0.537 against it, which is
nothing. The question worth asking is narrower: given a line the book is
actually offering, does our evidence disagree, and does that disagreement
survive being resampled?

WHY THE WHOLE BOARD, NOT THE CARD. Every earlier evaluation ran on capper
selections, which are already filtered by somebody's judgement — the
population had a 65% base rate, which no real market does. Kalshi lists
every prop it offers, so scanning that gives the unfiltered set: all the
lines, including the boring ones, which is the only way to know whether a
flag means anything.

WHAT A FLAG IS AND IS NOT. A flagged line is a disagreement between a
handful of a pitcher's recent starts and a market price. Most of the time
the market is right and the flag is a small sample being loud, and a
meaningful minority of the time it is a bug on our side — that is how most
of this system's defects were found. Treat the output as a list of things
to look at, not a list of things to bet.
"""
from __future__ import annotations

from datetime import date

from src import kalshi, parallel, roster
from src.context import estimate
from src.context.sources import statsapi

#: Stats worth scanning: a per-start history exists and the market is real.
SCAN_STATS = ("outs", "k")
#: Minimum probability gap before a line is worth a second look.
MIN_DISAGREEMENT = 0.08


def _implied_from_book(ticker: str, side: str) -> float | None:
    """Market probability for a side, from the two-sided book midpoint.

    The midpoint, not the ask: the ask is what a taker pays and overstates
    the market's actual view. A one-sided book returns None rather than a
    number derived from a lone resting order.
    """
    yes_bid, yes_ask = kalshi.book(ticker)
    if yes_bid is None or yes_ask is None:
        return None
    if (yes_ask - yes_bid) > kalshi.MAX_SPREAD:
        return None                       # too wide to be a price
    mid = (yes_bid + yes_ask) / 2
    return mid if (side or "").lower() != "under" else 1.0 - mid


def scan_stat(
    stat: str, date_str: str, season: int | None = None,
) -> list[dict]:
    """Every offered market for one stat on one date, priced both ways."""
    series = kalshi.SERIES_BY_STAT.get(stat)
    if not series:
        return []
    season = season or int(date_str[:4])

    todays = []
    for m in kalshi.markets(series):
        if kalshi.ticker_date(m["ticker"]) != date_str:
            continue
        p = kalshi._parse(m)
        if p:
            todays.append((m["ticker"], p[0], p[1]))

    def _one(item: tuple) -> list[dict]:
        ticker, name, threshold = item
        line = threshold - 0.5
        pid = roster.player_id(name)
        if not pid:
            return []
        try:
            log = statsapi.game_log(pid, season, date_str)
        except Exception:
            return []
        summary = statsapi.game_log_summary(log, as_of=date_str)
        if not log:
            return []
        # Same window preference the brief uses.
        pool = log
        recent = summary.get("recent") or {}
        if recent.get("starts", 0) >= estimate.MIN_STARTS:
            pool = log[-recent["starts"]:]
        sample = [s.get("outs") if stat == "outs" else s.get("k")
                  for s in pool]

        out = []
        for side in ("over", "under"):
            mkt = _implied_from_book(ticker, side)
            if mkt is None:
                continue
            # Market as prior: the question is whether this
            # sample moves us off the price, not whether it
            # differs from a coin flip.
            ours = estimate.over_under(sample, line, side,
                                       prior=mkt)
            if not ours:
                continue
            gap = ours["p"] - mkt
            if gap < MIN_DISAGREEMENT:
                continue           # only positive disagreement is actionable
            res = estimate.resilience(
                sample, line, side, kalshi.american(mkt),
            )
            out.append({
                "stat": stat, "player": name, "line": line, "side": side,
                "ticker": ticker,
                "our_p": ours["p"], "market_p": round(mkt, 3),
                "gap": round(gap, 3),
                "n": ours["n"], "sample": sample,
                "survives_to": (res or {}).get("survives_to"),
                "fragile": (res or {}).get("fragile", True),
            })
        return out

    rows: list[dict] = []
    for _, got, err in parallel.gather(_one, todays, workers=6):
        if got:
            rows.extend(got)
    return rows


def scan(date_str: str | None = None) -> list[dict]:
    """The whole board for a date, ranked by how much noise the gap absorbs."""
    d = date_str or date.today().isoformat()
    rows: list[dict] = []
    for stat in SCAN_STATS:
        rows.extend(scan_stat(stat, d))
    rows.sort(
        key=lambda r: (-(r["survives_to"] if r["survives_to"] is not None
                         else -1), -r["gap"]),
    )
    return rows


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    rows = scan(d)
    solid = [r for r in rows if not r["fragile"]]
    print(f"{d}: {len(rows)} line(s) where our sample disagrees by "
          f"{MIN_DISAGREEMENT:+.0%} or more; {len(solid)} survive jitter\n")
    print(f"  {'stat':<6}{'player':<20}{'bet':<14}{'ours':>6}{'mkt':>6}"
          f"{'gap':>7}{'n':>3}{'holds':>7}  sample")
    for r in rows[:25]:
        bet = f"{r['side']} {r['line']:g}"
        holds = ("-" if r["survives_to"] is None
                 else f"{r['survives_to']:.0f}")
        print(f"  {r['stat']:<6}{r['player'][:18]:<20}{bet:<14}"
              f"{r['our_p']:>6.2f}{r['market_p']:>6.2f}{r['gap']:>+7.2f}"
              f"{r['n']:>3}{holds:>7}  {r['sample']}")
