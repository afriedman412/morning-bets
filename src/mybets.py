"""Track the user's own bets, tailed from suggestions in the bets table.

A "my bet" is a wrapper over a specific row in `bets` (identified by
`bet_id`) plus the stake and price the user actually took. Grading and
matchup context piggyback on the underlying capper/panel row, so this
module is small: tail / untail / summarize.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src import db
from src.panel import settle_bet


def tail_bet(bet_id: int, stake_cents: int, american_odds: int) -> None:
    """Insert (or update) a tail for a suggested bet."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO my_bets (bet_id, stake_cents, american_odds, "
            "created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(bet_id) DO UPDATE SET "
            "stake_cents=excluded.stake_cents, "
            "american_odds=excluded.american_odds, "
            "created_at=excluded.created_at",
            (bet_id, stake_cents, american_odds, now),
        )


def untail_bet(bet_id: int) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM my_bets WHERE bet_id=?", (bet_id,))


def tailed_bet_ids() -> set[int]:
    """IDs of bets the user has tailed — used to badge the daily view."""
    with db.connect() as conn:
        rows = conn.execute("SELECT bet_id FROM my_bets").fetchall()
    return {r["bet_id"] for r in rows}


def tail_map() -> dict[int, dict]:
    """bet_id -> {stake_cents, american_odds} for every tailed bet."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT bet_id, stake_cents, american_odds FROM my_bets"
        ).fetchall()
    return {
        r["bet_id"]: {
            "stake_cents": r["stake_cents"],
            "american_odds": r["american_odds"],
        }
        for r in rows
    }


def my_bets_status() -> dict:
    """Cumulative P/L summary + per-bet history joined with source rows."""
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT m.bet_id, m.stake_cents, m.american_odds, m.created_at, "
            "b.date, b.source_label, b.matchup, b.player_name, b.stat, "
            "b.line, b.side, b.bet_type, b.confidence, b.result, "
            "b.actual_value, b.rationale "
            "FROM my_bets m JOIN bets b ON b.id = m.bet_id "
            "ORDER BY b.date DESC, m.id DESC"
        ).fetchall()]

    counts = {"W": 0, "L": 0, "PUSH": 0, "PENDING": 0, "UNGRADABLE": 0}
    total_staked = 0
    total_profit = 0
    by_day: dict[str, dict] = {}
    history = []
    for r in rows:
        stake = r["stake_cents"]
        odds = r["american_odds"]
        result = r["result"]
        counts[result] = counts.get(result, 0) + 1
        profit = settle_bet(result, stake, odds)
        total_profit += profit
        total_staked += stake
        d = by_day.setdefault(
            r["date"],
            {"date": r["date"], "picks": [], "staked_cents": 0,
             "profit_cents": 0},
        )
        d["picks"].append({**r, "profit_cents": profit})
        d["staked_cents"] += stake
        d["profit_cents"] += profit
        history.append({**r, "profit_cents": profit})

    decided = counts["W"] + counts["L"]
    return {
        "counts": counts,
        "total_staked_cents": total_staked,
        "total_profit_cents": total_profit,
        "decided": decided,
        "win_pct": (counts["W"] * 100 / decided) if decided else 0.0,
        "roi_pct": (
            total_profit * 100 / total_staked
        ) if total_staked else 0.0,
        "history": history,
        "days": sorted(by_day.values(), key=lambda x: x["date"], reverse=True),
    }
