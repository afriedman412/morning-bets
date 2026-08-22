"""Backtest the consensus recommender against the days it would have replaced.

Runs the full nominate -> debate -> close flow for past dates in AS-OF MODE and
grades the resulting card through the normal pipeline, then compares it to what
the old accuracy-weighted recommender actually picked on those same days.

WHAT THIS DOES AND DOESN'T MEASURE
  * web_search is FORCED OFF. Searching today for a game played last week
    returns box scores and recaps — that is guaranteed lookahead, not a risk.
    So the sim tests the deliberation mechanism on capper + savant information
    only. It does NOT test live prop pricing, which is a real part of the
    production flow. Props fall back to capper-quoted lines at -110.
  * Savant CSVs are read from the date-keyed .cache/ snapshot pulled that
    morning, so they are genuine point-in-time data. A missing snapshot is a
    hard error, never a live refetch.
  * Market lines come from the bets table (what the cappers quoted and what
    fill_missing_lines wrote that morning), not a refetch, which would return
    closing rather than morning numbers.
  * Prices are DB-only. With search off a persona cannot look a price up, so
    any odds it reports would be recalled or invented; those are discarded and
    a real capper quote (or -110) is used instead. ROI here is therefore a
    -110-ish floor, not the price a live run would actually have gotten.
  * Picks are written under SIM_LABEL, never the live 'Recommendation' label,
    so the production bankroll is untouched.

Usage:
    venv/bin/python -m src.sim 2026-07-24 2026-07-25 ...
    venv/bin/python -m src.sim --window          # the known-good 9 days
    venv/bin/python -m src.sim --window --dry    # show the plan, no API calls
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from src import db, recommend
from src.grading import grade_pending
from src.panel import settle_bet

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SIM_DIR = PROJECT_ROOT / "bets" / "sim"

# Days with capper bets, panel picks, a graded result, and an old-recommender
# card to compare against. 7/29 is ungraded and 7/30 has no panel picks.
DEFAULT_WINDOW = [
    "2026-07-24", "2026-07-25", "2026-07-26", "2026-07-27", "2026-07-28",
    "2026-07-31", "2026-08-01", "2026-08-02", "2026-08-03",
]

BASELINE_LABEL = recommend.RECOMMENDER_LABEL


def sim_label() -> str:
    """Per-provider label so concurrent A/B runs can't clobber each other.

    Anthropic keeps the original 'Consensus (sim)' so existing backtest rows
    stay comparable; any other provider gets its own namespace.
    """
    from src import llm
    p = llm.provider()
    return recommend.SIM_LABEL if p == "anthropic" else f"Consensus (sim:{p})"


SIM_LABEL = sim_label()


def _rows(conn, date_str: str, label: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT matchup, player_name, stat, line, side, bet_type, period, "
        "confidence, result, stake_cents, american_odds "
        "FROM bets WHERE date=? AND source_label=? ORDER BY id",
        (date_str, label),
    ).fetchall()]


def _score(rows: list[dict]) -> dict:
    w = sum(1 for r in rows if r["result"] == "W")
    ls = sum(1 for r in rows if r["result"] == "L")
    p = sum(1 for r in rows if r["result"] == "PUSH")
    ungraded = sum(
        1 for r in rows if r["result"] not in ("W", "L", "PUSH")
    )
    staked = sum(r["stake_cents"] or 0 for r in rows)
    pnl = sum(
        settle_bet(r["result"], r["stake_cents"], r["american_odds"])
        for r in rows
    )
    return {
        "n": len(rows), "W": w, "L": ls, "PUSH": p, "ungraded": ungraded,
        "staked": staked, "pnl": pnl,
        "roi": (pnl / staked * 100) if staked else 0.0,
        "hit": (w / (w + ls) * 100) if (w + ls) else 0.0,
    }


def _fmt(label: str, s: dict) -> str:
    """Record first — W/L is the cleanest read on pick quality, since stake
    size and price add noise that has nothing to do with the selection."""
    return (
        f"{label:<22} {s['W']:>3}-{s['L']:<3}-{s['PUSH']}  "
        f"hit {s['hit']:>5.1f}%  "
        f"({s['n']:>2} picks)  "
        f"P&L ${s['pnl'] / 100:>+8.2f}  "
        f"ROI {s['roi']:>+6.1f}%"
        + (f"  ({s['ungraded']} ungraded)" if s["ungraded"] else "")
    )


def _by_rank(conn, dates: list[str], label: str) -> list[dict]:
    """Per-card-position record. This is the test of whether the debate's
    ranking actually orders bets by quality."""
    out = []
    for pos in range(1, recommend.NUM_PICKS + 1):
        rows = []
        for d in dates:
            ids = [
                r[0] for r in conn.execute(
                    "SELECT id FROM bets WHERE date=? AND source_label=? "
                    "ORDER BY id", (d, label),
                )
            ]
            if len(ids) >= pos:
                r = conn.execute(
                    "SELECT result, stake_cents, american_odds "
                    "FROM bets WHERE id=?", (ids[pos - 1],),
                ).fetchone()
                rows.append(dict(r))
        s = _score(rows)
        s["pos"] = pos
        out.append(s)
    return out


def run_day(date_str: str) -> dict | None:
    print(f"\n{'=' * 72}\n{date_str}\n{'=' * 72}")
    recommend.reset_recommendations(date_str, SIM_LABEL)
    try:
        res = recommend.run(
            date_str,
            label=SIM_LABEL,
            use_search=False,   # non-negotiable: search = lookahead
            as_of=True,
            md_path=SIM_DIR / f"{date_str.replace('-', '_')}_consensus.md",
        )
    except FileNotFoundError as e:
        print(f"  SKIPPED — {e}")
        return None
    except Exception as e:
        print(f"  FAILED — {e}")
        traceback.print_exc()
        return None

    with db.connect() as conn:
        summary = grade_pending(conn, date_str)
    print(f"  Graded: {summary}")
    return res


def report(dates: list[str]) -> None:
    print(f"\n\n{'=' * 72}\nRESULTS\n{'=' * 72}\n")
    agg: dict[str, list[dict]] = {SIM_LABEL: [], BASELINE_LABEL: []}
    with db.connect() as conn:
        for d in dates:
            sim = _rows(conn, d, SIM_LABEL)
            base = _rows(conn, d, BASELINE_LABEL)
            if not sim and not base:
                continue
            agg[SIM_LABEL] += sim
            agg[BASELINE_LABEL] += base
            print(d)
            print("  " + _fmt("consensus (new)", _score(sim)))
            print("  " + _fmt("recommender (old)", _score(base)))

    print(f"\n{'-' * 72}\nTOTAL over {len(dates)} day(s)\n{'-' * 72}")
    print(_fmt("consensus (new)", _score(agg[SIM_LABEL])))
    print(_fmt("recommender (old)", _score(agg[BASELINE_LABEL])))

    print(f"\n{'-' * 72}\nBY CARD RANK — does the debate order bets by "
          f"quality?\n{'-' * 72}")
    with db.connect() as conn:
        ranks = _by_rank(conn, dates, SIM_LABEL)
    for s in ranks:
        stake = recommend.STAKE_BY_RANK_CENTS.get(s["pos"], 0) / 100
        tier = recommend.TIER_BY_RANK.get(s["pos"], "LEAN")
        print(
            f"  #{s['pos']} [{tier:<4}] ${stake:>5.2f}/bet   "
            f"{s['W']:>3}-{s['L']:<3}-{s['PUSH']}  hit {s['hit']:>5.1f}%   "
            f"P&L ${s['pnl'] / 100:>+8.2f}"
        )
    top = [s for s in ranks if s["pos"] <= 2]
    rest = [s for s in ranks if s["pos"] > 2]

    def roll(group: list[dict]) -> tuple[int, int, float]:
        w = sum(s["W"] for s in group)
        ls = sum(s["L"] for s in group)
        return w, ls, (w / (w + ls) * 100 if (w + ls) else 0.0)

    tw, tl, th = roll(top)
    rw, rl, rh = roll(rest)
    print(f"\n  conviction (#1-2): {tw}-{tl}  hit {th:.1f}%")
    print(f"  tail       (#3-{recommend.NUM_PICKS}): {rw}-{rl}  "
          f"hit {rh:.1f}%")
    print(f"  spread: {th - rh:+.1f} pp  "
          f"({'ranking orders by quality' if th > rh else 'NO ordering power'})")
    print(
        "\nNote: web_search OFF (it would be lookahead), so live prop pricing "
        "is untested.\nPersona-reported odds are discarded; picks settle at a "
        "real capper quote or -110.\nTreat ROI as a price floor, not the "
        "price a live run would have gotten."
    )


def main(argv: list[str]) -> None:
    db.init()
    dry = "--dry" in argv
    args = [a for a in argv if not a.startswith("--")]
    dates = DEFAULT_WINDOW if ("--window" in argv or not args) else args

    print(f"Sim window: {len(dates)} day(s) — {dates[0]} .. {dates[-1]}")
    print(f"Label: {SIM_LABEL!r} (production bankroll untouched)")
    print("web_search: OFF | savant: as-of snapshots | lines: from DB")
    if dry:
        est = len(dates) * 9
        print(f"\n--dry: would make up to {est} API calls "
              f"({len(dates)} days x max 9).")
        return

    for d in dates:
        run_day(d)
    report(dates)


if __name__ == "__main__":
    main(sys.argv[1:])
