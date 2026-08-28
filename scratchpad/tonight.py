"""Game TOTALS for a live slate, straight off the full-game engine.

    venv/bin/python -m scratchpad.tonight [DATE] [n_sims]

`price.py` prices PITCHER markets. The team-total path (`total_market`) has
never completed a run, so this walks `price.simulate_slate_game` — the same
entry point the props use, which is the point: one engine, both quantities,
so a total and a starter's line cannot contradict each other.

WHAT IT WILL NOT DO. A game with an unmodelled starter on either side is
DECLINED, not filled with a league-average arm. `simulate_slate_game`
already returns a reason and this prints it rather than hiding the row.

READ THE CAVEATS THIS PRINTS. Full-game totals are a STATED product that has
never been scored against settled prices here, and the engine changed
materially today. The number is the model's opinion, not a track record.
"""
from __future__ import annotations

import statistics as st
import sys
from collections import Counter
from datetime import date as _date

from src.context import price, sim
from src.context.sources import rates as rate_src


def american(p: float) -> str:
    if p <= 0 or p >= 1:
        return "-"
    return f"{-100 * p / (1 - p):+.0f}" if p > 0.5 else f"{100 * (1 - p) / p:+.0f}"


def main(argv):
    d = argv[0] if argv else _date.today().isoformat()
    n = int(argv[1]) if len(argv) > 1 else 400
    games = price.slate(d) if hasattr(price, "slate") else None
    if games is None:
        from src import panel
        games = panel.mlb_schedule_with_probables(d)
    lg = sim.league()
    pr = rate_src.pitcher_rates(lg)
    br = rate_src.batter_rates(lg)
    pens = rate_src.bullpens(lg)
    league_bats = sim.BatterRates(name="league", k_pct=lg["k_pct"],
                                  bb_pct=lg["bb_pct"], hr_pct=lg["hr_pct"],
                                  babip=lg["babip"])
    print(f"  {d}: {len(games)} games, {n} sims each\n")
    print(f"  {'game':<12}{'starters':<40}{'total':>7}{'F5*':>7}"
          f"{'sd':>6}"
          f"{'  lines: P(over) at each half-run'}")
    for g in games:
        try:
            res, why = price.simulate_slate_game(
                g, d, lg, pr, br, league_bats, pens, n_sims=n)
        except Exception as e:
            res, why = None, f"{type(e).__name__} {e}"
        # `price.slate` is the source, and it keys clubs under `away`/`home`
        # as {abbr, starter, ...}. Reading `matchup`/`away_team` off it —
        # the shape `panel.mlb_schedule_with_probables` returns — printed
        # "None @ None" for every row. Two schedule shapes, one of them
        # silently wrong, and a totals table nobody can attribute to a game
        # is worse than no table.
        a, h = g.get("away") or {}, g.get("home") or {}
        tag = f"{a.get('abbr')} @ {h.get('abbr')}"
        sp = f"{a.get('starter') or '-'} / {h.get('starter') or '-'}"
        if not res:
            print(f"  {tag:<12}{sp:<40}DECLINED — {why}")
            continue
        tot = [r.away + r.home for r in res]
        # `prefix_side` is only populated when `track` asks for it, so an
        # untracked run reports F5 as 0.00 rather than as missing.
        f5 = [sum(r.prefix_side[5]) for r in res
              if getattr(r, "prefix_side", None) and 5 in r.prefix_side]
        # A MISSING F5 PRINTS AS "-", NEVER AS 0.00. It read zero for every
        # game on the board until 2026-08-28 because `simulate_slate_game`
        # passed no `track`, and a zero that looks like a number hides that
        # far better than a dash would have.
        line = (f"  {tag:<12}{sp:<40}{st.mean(tot):>7.2f}"
                f"{(f'{st.mean(f5):.2f}' if f5 else '-'):>7}"
                f"{st.pstdev(tot):>6.2f}  ")
        for ln in (6.5, 7.5, 8.5, 9.5, 10.5):
            over = sum(1 for t in tot if t > ln) / len(tot)
            line += f"{ln}:{over:.3f} "
        print(line)
    print("\n  CAVEATS, and they are not boilerplate:")
    print("   * Full-game totals have NEVER been scored against settled")
    print("     prices here. `total_market` has never completed a run.")
    print("   * The engine changed materially today — hook, BABIP")
    print("     denominator, reliever rates. No CLV history applies to it.")
    print("   * Lineups are PROJECTED unless a card is posted.")


if __name__ == "__main__":
    main(sys.argv[1:])
