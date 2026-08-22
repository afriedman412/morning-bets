"""Has the number moved since the capper said it?

Two different questions wear the name "line movement", and this module
answers the one that actually changes a decision:

  MARKET PATH   how a game's number travelled across the day. Per game,
                needs accumulated snapshots, lives in context.snapshot.
  THIS BET      is the price this source quoted still available? Per bet,
                needs no history at all — the source's number was frozen
                into stated_line/stated_odds at ingest, and the current one
                is a lookup away.

The second is the useful one. A capper arguing "under 8.5 at -110" has
built a thesis on a number; if the board now reads 9.0 at -105 the thesis
may survive but the bet on offer is not the bet that was made. Nothing in
the system noticed that before, because stated and current were only ever
written at the same instant and never compared again.

WHY THE DELTA IS ALWAYS ZERO WITHOUT THIS. persist_bets freezes stated_*
at extraction and the backfills only ever FILL nulls, never overwrite. So
a capper bet's stated value equals its current value forever unless
something deliberately re-reads the market. That something is here.
"""
from __future__ import annotations

from src.grading import same_party

# Beyond this the line is a different bet, not a moved one — a total that
# goes 8.5 -> 10.0 is not the wager anyone argued for.
LINE_ALARM = 1.0
# American-odds drift worth mentioning. Roughly a 5% swing in break-even.
ODDS_ALARM = 15


def _current_line(bet: dict, market: dict | None) -> float | None:
    """Today's number for a game line, from the assembled market record."""
    if not market:
        return None
    bt = (bet.get("bet_type") or "").lower()
    if bt == "total":
        return (market.get("total") or {}).get("over", {}).get("line")
    if bt == "spread":
        side = bet.get("side") or ""
        if same_party(market.get("home_team"), side):
            return (market.get("runline") or {}).get("home", {}).get("line")
        if same_party(market.get("away_team"), side):
            return (market.get("runline") or {}).get("away", {}).get("line")
    return None


def _current_odds(bet: dict, market: dict | None) -> int | None:
    """Today's price. Game lines from ESPN, props from the exchange."""
    bt = (bet.get("bet_type") or "").lower()
    if bt in ("prop", "combo"):
        try:
            from src import kalshi
            got = kalshi.price_prop(
                bet.get("player_name"), bet.get("stat"),
                bet.get("line"), bet.get("side"),
            )
        except Exception:
            return None
        return got.get("mid_american") if got and got.get("usable") else None
    if not market:
        return None
    side = bet.get("side") or ""
    if bt == "total":
        leg = "over" if side.lower() == "over" else "under"
        return (market.get("total") or {}).get(leg, {}).get("odds")
    key = None
    if same_party(market.get("home_team"), side):
        key = "home"
    elif same_party(market.get("away_team"), side):
        key = "away"
    if not key:
        return None
    if bt == "ml":
        return (market.get("ml") or {}).get(key, {}).get("odds")
    if bt == "spread":
        return (market.get("runline") or {}).get(key, {}).get("odds")
    return None


#: A price is only a LINE before first pitch. After that ESPN is quoting a
#: live game and Kalshi is quoting a contract halfway to settlement, and
#: comparing either to what a capper said in the morning produces numbers
#: that look like enormous line moves and are nothing of the kind — a
#: Weathers strikeout prop read -120 -> -400 purely because the game was
#: over. Only these states are safe to compare against.
_PREGAME = {"Preview", "Scheduled", "Pre-Game", "Warmup", "Delayed Start"}


def _is_pregame(game: dict | None) -> bool:
    if not game:
        return False
    st = game.get("status")
    det = game.get("detailed_status")
    if st is None and det is None:
        return True   # status unavailable — assume comparable, flag nothing
    return st == "Preview" or det in _PREGAME


def for_bet(bet: dict, game: dict | None) -> dict:
    """What this source quoted, what is on the board, and the gap.

    `still_available` is the headline: False means the exact wager as
    described cannot be placed at the number it was argued from. That is
    not the same as a bad bet — it is a bet whose premise needs rechecking,
    which is a distinction the reader should get to make.

    Refuses to compare once a game is underway; see _PREGAME.
    """
    if not _is_pregame(game):
        return {
            "comparable": False,
            "still_available": None,
            "stated_line": bet.get("stated_line"),
            "stated_odds": bet.get("stated_odds"),
            "current_line": None, "current_odds": None,
            "line_delta": None, "odds_delta": None,
            "game_state": (game or {}).get("detailed_status"),
            "summary": "game has started — a live price is not a line",
        }
    market = (game or {}).get("market")
    stated_line = bet.get("stated_line")
    stated_odds = bet.get("stated_odds")
    cur_line = _current_line(bet, market)
    cur_odds = _current_odds(bet, market)

    line_delta = (
        round(cur_line - stated_line, 2)
        if stated_line is not None and cur_line is not None else None
    )
    odds_delta = (
        int(cur_odds - stated_odds)
        if stated_odds is not None and cur_odds is not None else None
    )

    out = {
        "stated_line": stated_line,
        "current_line": cur_line,
        "line_delta": line_delta,
        "stated_odds": stated_odds,
        "current_odds": cur_odds,
        "odds_delta": odds_delta,
        # Nothing to compare against is not the same as no movement, and
        # conflating them is how "the line held" gets reported about a
        # number nobody looked up.
        "comparable": bool(line_delta is not None or odds_delta is not None),
    }
    out["still_available"] = (
        None if not out["comparable"]
        else not (
            (line_delta is not None and abs(line_delta) >= LINE_ALARM)
            or (odds_delta is not None and abs(odds_delta) >= ODDS_ALARM)
        )
    )
    notes = []
    if line_delta:
        notes.append(f"line {stated_line:g} -> {cur_line:g}")
    if odds_delta:
        notes.append(f"price {stated_odds:+d} -> {cur_odds:+d}")
    out["summary"] = "; ".join(notes) if notes else (
        "unchanged" if out["comparable"] else "no current number to compare"
    )
    return out


def for_slate(bets: list[dict], snapshot: dict) -> list[dict]:
    """Annotate a list of bets with their movement. Order preserved."""
    by_match = {g.get("matchup"): g for g in snapshot.get("games", [])}
    out = []
    for b in bets:
        g = by_match.get(b.get("matchup"))
        if g is None:
            bm = b.get("matchup") or ""
            for gm, rec in by_match.items():
                if gm and same_party(gm.split(" @ ")[0], bm) \
                        and same_party(gm.split(" @ ")[-1], bm):
                    g = rec
                    break
        out.append({**b, "movement": for_bet(b, g)})
    return out


if __name__ == "__main__":
    import sys
    from src import db
    from src.context.assemble import assemble

    d = sys.argv[1] if len(sys.argv) > 1 else None
    from datetime import date as _date
    d = d or _date.today().isoformat()
    snap = assemble(d)
    with db.connect() as c:
        bets = [dict(r) for r in c.execute(
            "SELECT source_label, matchup, player_name, stat, line, side, "
            "bet_type, stated_line, stated_odds, american_odds FROM bets "
            "WHERE date=? AND sport='mlb' AND source_label NOT LIKE 'Panel:%'",
            (d,))]
    rows = for_slate(bets, snap)
    comp = [r for r in rows if r["movement"]["comparable"]]
    moved = [r for r in comp if r["movement"]["summary"] != "unchanged"]
    gone = [r for r in comp if r["movement"]["still_available"] is False]
    print(f"{len(rows)} bets | {len(comp)} comparable | {len(moved)} moved "
          f"| {len(gone)} no longer at the quoted number\n")
    for r in moved[:15]:
        desc = " ".join(str(x) for x in
                        (r["player_name"] or "", r["stat"] or "",
                         r["side"] or "", r["line"] or "") if x)
        flag = "" if r["movement"]["still_available"] else "   << GONE"
        print(f"  {desc[:38]:<40}{r['movement']['summary']}{flag}")
