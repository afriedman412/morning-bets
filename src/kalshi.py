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


# ── retroactive price history ──────────────────────────────────────────
#
# Kalshi keeps settled markets and their trades, roughly two months back at
# the time of writing (KXMLBOUTS reaches 2026-06-22). That makes closing
# line value computable for props WITHOUT waiting to accumulate snapshots,
# which matters because the alternative source has no history at all:
# ESPN serves open/close only for current and upcoming games and returns no
# odds node whatsoever for a past date. Verified on five past dates, zero
# games with odds on any of them.
#
# So: game lines are forward-only, props are backfillable. That asymmetry
# decides what can be evaluated today.

_settled_cache: dict[str, list[dict]] = {}


def settled_markets(series: str) -> list[dict]:
    """Every settled market in a series, paginated, cached per process."""
    if series in _settled_cache:
        return _settled_cache[series]
    out, cursor = [], None
    while True:
        q = f"/markets?series_ticker={series}&status=settled&limit=1000"
        if cursor:
            q += f"&cursor={cursor}"
        d = _get(q)
        out.extend(d.get("markets", []))
        cursor = d.get("cursor")
        if not cursor or not d.get("markets"):
            break
    _settled_cache[series] = out
    return out


#: Trade histories are cached to disk, keyed by ticker.
#:
#: A SETTLED market's trades are immutable — the game is over and nothing
#: further will print — so re-fetching them is pure waste. A 54-date CLV
#: run makes ~2,700 of these calls at ~0.12s each, which is five minutes of
#: network on data that cannot change. Every re-run pays it again, and this
#: project re-runs these tests constantly.
#:
#: Only markets whose ticker date is strictly in the past are cached. A
#: market that is still trading must NOT be, or a stale path would silently
#: become the answer — and the whole point of `price_path` is that the
#: cutoff is exact.
_TRADES_DIR = _HERE + "/../.cache/kalshi_trades" if "_HERE" in dir() else \
    ".cache/kalshi_trades"


def _trades_cache_path(ticker: str) -> str:
    import os
    os.makedirs(_TRADES_DIR, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in ticker)
    return f"{_TRADES_DIR}/{safe}.json"


def _settled_in_the_past(ticker: str) -> bool:
    from datetime import date
    d = ticker_date(ticker)
    return bool(d and d < date.today().isoformat())


def trades(ticker: str, limit: int = 1000) -> list[dict]:
    """Every recorded trade for a market, oldest first. Cached when settled."""
    import json
    import os
    cacheable = _settled_in_the_past(ticker)
    path = _trades_cache_path(ticker) if cacheable else None
    if path and os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    out, cursor = [], None
    while True:
        q = f"/markets/trades?ticker={ticker}&limit={min(limit, 1000)}"
        if cursor:
            q += f"&cursor={cursor}"
        try:
            d = _get(q)
        except Exception:
            break
        out.extend(d.get("trades", []))
        cursor = d.get("cursor")
        if not cursor or not d.get("trades") or len(out) >= limit:
            break
    out = sorted(out, key=lambda t: t.get("created_time", ""))
    # Only write once there is something to write. An empty result from a
    # transient failure must not be cached as fact — that would turn one bad
    # request into a permanent hole in every future run.
    if path and out:
        try:
            with open(path, "w") as f:
                json.dump(out, f)
        except OSError:
            pass
    return out


def find_settled(
    player: str, stat: str, line: float, date_str: str,
) -> dict | None:
    """The settled market matching one historical prop, or None.

    Same name/threshold matching as price_prop, restricted to the date so a
    pitcher who started twice in a window cannot match the wrong game.
    """
    series = SERIES_BY_STAT.get((stat or "").lower())
    if series is None or line is None:
        return None
    want = threshold_for(line)
    key = _name_key(player)
    if not key:
        return None
    # Search settled AND open: a market for a game still in progress has
    # not settled yet, so a today lookup would find nothing at all.
    pool = settled_markets(series) + markets(series)
    for m in pool:
        if ticker_date(m["ticker"]) != date_str:
            continue
        p = _parse(m)
        if not p:
            continue
        name, n = p
        if n == want and (key & _name_key(name)):
            return m
    return None


_TICKER_DT = re.compile(r"^[A-Z0-9]+-(\d{2})([A-Z]{3})(\d{2})(\d{4})")


def ticker_start_utc(ticker: str) -> str | None:
    """First pitch, in UTC, from the ticker's embedded date and time.

    The time segment is Eastern — 'KXMLBOUTS-26AUG221335TORNYY' is a 13:35
    ET start, and that game's statsapi gameDate is 17:35Z. Converting
    through the ET zone rather than a fixed offset keeps it right across
    the DST boundary.
    """
    hit = _TICKER_DT.match(ticker or "")
    if not hit:
        return None
    mon = _MONTHS.get(hit.group(2))
    if not mon:
        return None
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    hhmm = hit.group(4)
    try:
        naive = datetime(
            2000 + int(hit.group(1)), mon, int(hit.group(3)),
            int(hhmm[:2]), int(hhmm[2:]),
        )
    except ValueError:
        return None
    et = naive.replace(tzinfo=ZoneInfo("America/New_York"))
    return et.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def price_path(ticker: str, side: str) -> dict | None:
    """Opening and CLOSING price for one side, closing = at first pitch.

    Over is YES on the N+ contract, under is NO — the same convention
    price_prop uses. Prices are probabilities, so close minus open IS
    closing line value in probability points: positive means the market
    moved toward this side before the game started.

    THE CUTOFF IS THE WHOLE THING. Kalshi keeps trading through a game and
    settles at 0 or 1, so the last recorded trade on a finished market is
    the RESULT, not a price. Taking it as the close made CLV perfectly
    circular — Gerrit Cole's over closed at 0.01 and Mackenzie Gore's under
    at 0.87, which is just the box score wearing a probability. Only trades
    strictly before first pitch count.
    """
    start = ticker_start_utc(ticker)
    tr = [t for t in trades(ticker)
          if not start or (t.get("created_time") or "") < start]
    if len(tr) < 2:
        return None
    over = (side or "").lower() != "under"
    field = "yes_price_dollars" if over else "no_price_dollars"

    def px(t):
        try:
            return float(t.get(field))
        except (TypeError, ValueError):
            return None

    first = next((px(t) for t in tr if px(t) is not None), None)
    last = next((px(t) for t in reversed(tr) if px(t) is not None), None)
    if first is None or last is None:
        return None
    return {
        "ticker": ticker,
        "side": side,
        "open_prob": round(first, 4),
        "close_prob": round(last, 4),
        # The headline. Positive = the market moved toward this side, i.e.
        # taking it early was value regardless of whether it won.
        "clv": round(last - first, 4),
        "trades": len(tr),
        "first_at": tr[0].get("created_time"),
        "last_at": tr[-1].get("created_time"),
        "first_pitch": ticker_start_utc(ticker),
    }


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
