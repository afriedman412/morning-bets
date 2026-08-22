"""Reference prices for player props, from the Kalshi exchange.

ESPN publishes real DraftKings prices for moneylines, runlines and totals,
but nothing at player-prop level — and props are most of the card. Every
other route was a dead end: DraftKings 403s, Pinnacle geoblocks US traffic
on its price endpoint, Bovada's open feed is game lines only, and The Odds
API wants a key. Kalshi is a CFTC-regulated exchange with a public,
unauthenticated market-data API and real two-sided books on MLB props.

It is a reference, not a quote — Kalshi is an exchange, so its midpoint is
a fair-value estimate rather than the number DraftKings will give you.
That is exactly what is wanted here: a way to tell whether a price is good.

Two quirks of their API drove the shape of this module:

  * Markets are binary "N+ threshold" contracts, so 'over 15.5 outs' is
    'YES on 16+' and 'under 15.5' is 'NO on 16+'.
  * The summary fields (yes_bid, yes_ask, volume) come back null even on
    liquid markets, so prices have to be derived from /orderbook. The best
    YES ask is 1 - best NO bid.

    venv/bin/python -m src.kalshi 2026-08-14        # price today's card
    venv/bin/python -m src.kalshi 2026-08-14 --all  # every prop found
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date

BASE = "https://api.elections.kalshi.com/trade-api/v2"
USER_AGENT = (
    "morning-bets/1.0 (+https://github.com/afriedman412/morning-bets)"
)

# Our canonical stat keys -> Kalshi series. Keys we cannot price are simply
# absent, and callers fall back to leaving the prop unverified.
SERIES_BY_STAT = {
    "k": "KXMLBKS",            # pitcher strikeouts
    "outs": "KXMLBOUTS",       # pitcher outs recorded
    "hr": "KXMLBHR",           # home runs
    "tb": "KXMLBTB",           # total bases
    "h": "KXMLBHIT",           # hits
    "rbi": "KXMLBRBI",         # RBIs
    "h+r+rbi": "KXMLBHRR",     # hits + runs + RBIs
    # Verified against a live slate: every name in ERA/WA/HA is one of the
    # day's probable starters (24 of 25), so these are the pitcher side of
    # each stat, not the batter's. SB is the reverse — zero starters, all
    # position players.
    "er": "KXMLBERA",          # pitcher earned runs allowed
    "bb_allowed": "KXMLBWA",   # pitcher walks allowed
    "h_allowed": "KXMLBHA",    # pitcher hits allowed
    "sb": "KXMLBSB",           # batter stolen bases
}
# Listed by Kalshi but NOT mapped, because their subtitles do not fit the
# "Name: N+" shape _parse() reads: KXMLBTEAMTOTAL ('Texas over 7.5 runs
# scored'), KXMLBRFI ('Yes'), KXMLBTOTAL, KXMLBSPREAD, KXMLBF5*. Wiring
# those up means a second parser, not another dict entry.
#
# 'decision' (pitcher win/loss) genuinely has no per-game series — the
# KXMLBWINS-* series are season team win totals, not a starter's decision.

# A book this wide is not a price, it is two people shouting across a room.
MAX_SPREAD = 0.12

_cache: dict[str, list[dict]] = {}


def _get(path: str, attempts: int = 3):
    req = urllib.request.Request(
        f"{BASE}{path}", headers={"User-Agent": USER_AGENT},
    )
    last = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504):
                raise
        except urllib.error.URLError as e:
            last = e
        if i < attempts - 1:
            time.sleep(2 ** i)
    raise last


def american(prob: float) -> int | None:
    """Implied probability -> American odds."""
    if not prob or prob <= 0.0 or prob >= 1.0:
        return None
    if prob >= 0.5:
        return -round(100 * prob / (1 - prob))
    return round(100 * (1 - prob) / prob)


def threshold_for(line: float) -> int:
    """The 'N+' contract that settles a bet on this line.

    'over 15.5' needs 16+. 'over 9.0' needs 10+ — not identical, since the
    book would push at exactly 9 and Kalshi will not, but close enough for
    a reference price.
    """
    return math.floor(line) + 1


def markets(series: str) -> list[dict]:
    """Open markets for a series, cached for the life of the process."""
    if series in _cache:
        return _cache[series]
    out, cursor = [], None
    while True:
        q = f"/markets?series_ticker={series}&status=open&limit=1000"
        if cursor:
            q += f"&cursor={cursor}"
        d = _get(q)
        out.extend(d.get("markets", []))
        cursor = d.get("cursor")
        if not cursor or not d.get("markets"):
            break
    _cache[series] = out
    return out


_SUBTITLE = re.compile(r"^(.*?):\s*(\d+)\+")


def _parse(m: dict) -> tuple[str, int] | None:
    """('Jacob Misiorowski', 9) from a market's subtitle."""
    s = m.get("yes_sub_title") or m.get("title") or ""
    hit = _SUBTITLE.match(s.strip())
    if not hit:
        return None
    return hit.group(1).strip(), int(hit.group(2))


def _name_key(name: str) -> set[str]:
    return {w.lower().strip(".") for w in re.findall(r"[A-Za-z']+", name or "")
            if len(w) >= 3}


# Kalshi books are laddered: hundreds of contracts resting at a penny and
# often a single lot near the top. Taking max(price) let one stray order
# define the market — a 99c bid on a pitcher-outs contract implied the
# under was a 1% shot. A level only counts as top-of-book once it holds
# real size.
MIN_SIZE = 25.0


def book(ticker: str) -> tuple[float | None, float | None]:
    """(best YES bid, best YES ask) as probabilities, from the orderbook."""
    ob = (_get(f"/markets/{ticker}/orderbook") or {}).get("orderbook_fp") or {}

    def best(side: str) -> float | None:
        levels = [(float(p), float(sz)) for p, sz in (ob.get(side) or [])]
        return max((p for p, sz in levels if sz >= MIN_SIZE), default=None)

    yes_bid = best("yes_dollars")
    no_bid = best("no_dollars")
    # Buying YES means taking the other side of the best NO bid.
    yes_ask = (1.0 - no_bid) if no_bid is not None else None
    return yes_bid, yes_ask


_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
     "NOV", "DEC"], 1)}
_TICKER_DATE = re.compile(r"^[A-Z0-9]+-(\d{2})([A-Z]{3})(\d{2})")


def ticker_date(ticker: str) -> str | None:
    """The ISO date encoded in a market ticker, or None if unparseable.

    e.g. KXMLBOUTS-26AUG221910NYMCWS-CWSLCASTILLO58-18 -> '2026-08-22'.

    markets() returns every OPEN market in a series, which spans several days
    once tomorrow's slate lists. Without this filter a pitcher who starts
    twice in a week matches whichever of his contracts came back first.
    """
    hit = _TICKER_DATE.match(ticker or "")
    if not hit:
        return None
    month = _MONTHS.get(hit.group(2))
    if not month:
        return None
    return f"20{hit.group(1)}-{month:02d}-{int(hit.group(3)):02d}"


def discover_prop(
    player: str, stat: str, side: str, date_str: str | None = None,
) -> dict | None:
    """The market's line AND price for a prop whose source never said a number.

    Several cappers read their picks off a screen — "Castillo under in outs",
    with the number only ever on-screen — so the line arrives null, the bet
    can never be graded, and the personas see a pick they cannot evaluate.

    Kalshi hangs its pitcher-outs contract at exactly the threshold the books
    are using, so the listed strike reconstructs the line: an 18+ contract is
    a 17.5 line. Where a series lists several strikes for one player (total
    bases, hits), the line is the strike whose midpoint sits nearest even
    money — that is where a book sets a number.

    Same shape as price_prop() plus `line`. None when the player is not
    listed for that date, or no strike has a two-sided book.
    """
    from src import parallel

    series = SERIES_BY_STAT.get((stat or "").lower())
    key = _name_key(player)
    if series is None or not key:
        return None

    cands = []
    for m in markets(series):
        p = _parse(m)
        if not p or not (key & _name_key(p[0])):
            continue
        if date_str and ticker_date(m["ticker"]) not in (None, date_str):
            continue
        cands.append((p[0], p[1], m["ticker"]))
    if not cands:
        return None

    # One HTTP round-trip per strike, and total bases lists up to five.
    # Capped low on purpose: this runs inside another fan-out, so the real
    # concurrency is the product of the two.
    books = parallel.gather(lambda c: book(c[2]), cands, workers=4)

    best = None
    for (name, n, ticker), bk, err in books:
        if err or not bk:
            continue
        yes_bid, yes_ask = bk
        if yes_bid is None or yes_ask is None:
            continue  # one-sided book — no fair value to read
        mid = (yes_bid + yes_ask) / 2
        if best is None or abs(mid - 0.5) < abs(best[3] - 0.5):
            best = (name, n, ticker, mid, yes_ask - yes_bid)
    if best is None:
        return None

    name, n, ticker, mid, spread = best
    over = (side or "").lower() != "under"
    mid_prob = mid if over else (1.0 - mid)
    return {
        "ticker": ticker, "threshold": n, "player": name,
        "line": n - 0.5,
        "mid_prob": round(mid_prob, 4),
        "mid_american": american(mid_prob),
        "spread": round(spread, 3),
        "usable": spread <= MAX_SPREAD,
    }


def price_prop(player: str, stat: str, line: float, side: str) -> dict | None:
    """Reference price for one player prop, or None if not listed.

    Returns {ticker, threshold, prob, american, spread} where `prob` is the
    cost of taking the bet as asked — YES for an over, NO for an under.
    """
    series = SERIES_BY_STAT.get((stat or "").lower())
    if series is None or line is None:
        return None
    want = threshold_for(line)
    key = _name_key(player)
    if not key:
        return None

    for m in markets(series):
        p = _parse(m)
        if not p:
            continue
        name, n = p
        if n != want or not (key & _name_key(name)):
            continue
        yes_bid, yes_ask = book(m["ticker"])
        if yes_bid is None or yes_ask is None:
            # Listed, but only one side has resting size. There is no
            # two-sided market to read a fair value off, and guessing from
            # a lone bid produced nonsense (a 99c bid implying 99%).
            return {"ticker": m["ticker"], "threshold": want, "player": name,
                    "prob": None, "american": None, "mid_prob": None,
                    "mid_american": None, "spread": None, "usable": False,
                    "note": "one-sided book"}
        spread = yes_ask - yes_bid
        over = (side or "").lower() != "under"
        # Under = buy NO. Best NO ask is 1 - best YES bid.
        prob = yes_ask if over else (1.0 - yes_bid)
        mid = (yes_bid + yes_ask) / 2
        mid_prob = mid if over else (1.0 - mid)
        return {
            "ticker": m["ticker"], "threshold": want, "player": name,
            "prob": round(prob, 4), "american": american(prob),
            "mid_prob": round(mid_prob, 4), "mid_american": american(mid_prob),
            "spread": round(spread, 3),
            # A wide book is still evidence, just not a price. Reported
            # rather than swallowed, so the caller can show it and decline
            # to size a stake off it.
            "usable": spread <= MAX_SPREAD,
        }
    return None


if __name__ == "__main__":
    from src import db
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    d = args[0] if args else date.today().isoformat()
    show_all = "--all" in sys.argv

    with db.connect() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT DISTINCT player_name, stat, line, side, source_label, "
            "american_odds FROM bets WHERE date=? AND bet_type IN "
            "('prop','combo') AND player_name IS NOT NULL AND line IS NOT NULL"
            + ("" if show_all else " AND source_label='Recommendation'"),
            (d,))]

    def implied(a: int) -> float:
        """American odds -> the win rate needed to break even at that price."""
        return abs(a) / (abs(a) + 100) if a < 0 else 100 / (a + 100)

    print(f"{len(rows)} prop(s) on {d}\n")
    print(f"{'player':<20s} {'bet':<20s} {'quoted':>7s} {'fair':>7s} "
          f"{'edge':>7s}  note")
    for r in rows:
        got = price_prop(r["player_name"], r["stat"], r["line"], r["side"])
        q = r["american_odds"]
        qs = f"{q:+d}" if q is not None else "—"
        bet = f"{r['side']} {r['line']:g} {r['stat']}"
        if not got or got["american"] is None:
            why = (got or {}).get("note", "not listed")
            print(f"{r['player_name'][:20]:<20s} {bet:<20s} {qs:>7s} "
                  f"{'—':>7s} {'':>7s}  {why}")
            continue
        ks = f"{got['american']:+d}"
        # Edge in probability points: what the market thinks the bet's real
        # chance is, minus the chance your price needs to break even.
        # Positive means the market rates it likelier than you are paying
        # for. Fair value is the midpoint, not the ask — the ask is what a
        # taker pays and overstates the true cost.
        edge = (f"{got['mid_prob'] - implied(q):+.3f}"
                if q is not None and got["mid_prob"] is not None else "")
        note = ("" if got["usable"]
                else f"WIDE {got['spread']:.2f} — indicative")
        print(f"{r['player_name'][:20]:<20s} {bet:<20s} {qs:>7s} {ks:>7s} "
              f"{edge:>7s}  {note}")
