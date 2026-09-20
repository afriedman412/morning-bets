"""Replay ONE finished game many times and score the draws against it.

    venv/bin/python -m scratchpad.one_game mlb-823336 [SIMS]

The live-slate path (`slate.simulate_slate_game`) REFUSES a game that is not
pregame, which is correct and is why this exists separately: after the fact
the honest question is "what distribution would we have produced, on inputs
frozen before first pitch, and where did the real game land in it?".

Rates, the league baseline and the bullpens are all built with
`before=<the game's own date>`, so nothing from the game being scored can
reach the model that predicts it. Lineups are the REAL ones (`order.lineups`
off the cached play-by-play), which is the one thing this path knows and a
morning price does not — a live price projects the nine and that is recorded
as the weakest link in `BETTING.md`.

ONE GAME IS ONE DRAW FROM THE TRUTH. The percentile columns are the whole
output for a reason: "we said 8.1 and it went 1" is not a miss until you know
what share of the distribution sat at or below 1. Do not read a single game
as a measurement of the model — the battery is that.
"""
from __future__ import annotations

import random
import statistics as st
import sys
from collections import Counter

from src import db
from src.context import calibrate as cal
from src.context import sim
from src.context.sources import rates as rate_src


def game_row(gid: str) -> dict:
    with db.connect() as c:
        r = c.execute("select * from games where game_id = ?", (gid,)).fetchone()
    if not r:
        raise SystemExit(f"no cached game {gid}")
    return dict(r)


def actual_starters(gid: str) -> dict[str, dict]:
    with db.connect() as c:
        rows = c.execute(
            "select * from mlb_pitching where game_id = ? and is_starter = 1",
            (gid,)).fetchall()
    return {r["team"]: dict(r) for r in rows}


def pct_at_or_below(draws, x) -> float:
    return sum(1 for d in draws if d <= x) / len(draws)


def pct_at(draws, x) -> float:
    return sum(1 for d in draws if d == x) / len(draws)


def _american(p: float) -> int:
    """A probability as FAIR American odds — no vig, which is the point.
    A quoted -161 carries the book's margin and our number does not, so
    compare the two as probabilities and read the odds as a convenience."""
    p = min(max(p, 1e-6), 1 - 1e-6)
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def report(gid: str, n_sims: int = 20000, seed: int = 11) -> None:
    g = game_row(gid)
    d = g["date"]
    # FROZEN BEFORE FIRST PITCH. `before=d` on every builder — the league
    # baseline included, since log5 anchors every simulated rate on it.
    lg = sim.league(before=d)
    pens = rate_src.bullpens(lg, before=d)
    pairs = cal.paired_cases(since=d, rates_before=d)
    pair = pairs.get(gid)
    if not pair:
        raise SystemExit(f"{gid} is not a paired case — one starter unmodelled")
    away, home = pair

    print(f"{g['away_team_abbr']} @ {g['home_team_abbr']}  {d}  "
          f"venue {g['venue_id']}")
    print(f"  actual   {g['away_team_abbr']} {g['away_score']} - "
          f"{g['home_team_abbr']} {g['home_score']}   "
          f"(F5 {g['away_score_f5']}-{g['home_score_f5']}, "
          f"total {g['away_score'] + g['home_score']})")
    print(f"  starters {away[1].name} ({away[0]['team']}) vs "
          f"{home[1].name} ({home[0]['team']})")
    print(f"  lineups  {', '.join(b.name for b in away[2][:3])} ... / "
          f"{', '.join(b.name for b in home[2][:3])} ...")
    w = cal.air_mult_for(home[0])
    u = cal.ump_mult_for(home[0])
    print(f"  air x{w:.3f}   ump k x{u[0]:.3f} bb x{u[1]:.3f}   "
          f"{n_sims} draws\n")

    tot, aw, hm, f5a, f5h = [], [], [], [], []
    sp = {"away": [], "home": []}
    for i in range(n_sims):
        rng = random.Random(seed + i * 100003)
        r = cal.replay(pair, lg, pens, rng, track=(5,))
        tot.append(r.total)
        aw.append(r.away)
        hm.append(r.home)
        f5a.append(r.away_f5)
        f5h.append(r.home_f5)
        sp["away"].append(r.away_sp)
        sp["home"].append(r.home_sp)

    # THE MONEYLINE, so a claim about a PRICE can be audited against the
    # same draws the totals come off. Ties cannot survive — the simulator
    # plays extras — so the two probabilities sum to one.
    hw = sum(1 for a, h in zip(aw, hm) if h > a) / n_sims
    print(f"\n  P({g['home_team_abbr']} win) {hw:.3f} "
          f"(fair {_american(hw):+d})   "
          f"P({g['away_team_abbr']} win) {1 - hw:.3f} "
          f"(fair {_american(1 - hw):+d})")

    act = {"total": g["away_score"] + g["home_score"],
           "away": g["away_score"], "home": g["home_score"],
           "f5a": g["away_score_f5"], "f5h": g["home_score_f5"]}
    rows = (("game total", tot, act["total"]),
            (f"{g['away_team_abbr']} runs", aw, act["away"]),
            (f"{g['home_team_abbr']} runs", hm, act["home"]),
            (f"F5 {g['away_team_abbr']}", f5a, act["f5a"]),
            (f"F5 {g['home_team_abbr']}", f5h, act["f5h"]))
    print(f"  {'':<14}{'sim mean':>10}{'sd':>7}{'actual':>8}"
          f"{'P(<=act)':>10}{'P(=act)':>9}")
    for label, draws, a in rows:
        if a is None:
            continue
        print(f"  {label:<14}{st.mean(draws):>10.2f}{st.pstdev(draws):>7.2f}"
              f"{a:>8}{pct_at_or_below(draws, a):>10.3f}"
              f"{pct_at(draws, a):>9.3f}")

    print("\n  game total mass")
    c = Counter(tot)
    for v in range(0, min(16, max(tot) + 1)):
        n = c.get(v, 0) / n_sims
        mark = "  <-- actual" if v == act["total"] else ""
        print(f"    {v:>2}  {n:>6.3f}  {'#' * int(round(n * 120))}{mark}")

    sa = actual_starters(gid)
    print("\n  starters — sim mean vs actual")
    print(f"  {'':<20}{'outs':>7}{'k':>6}{'bb':>6}{'h':>6}{'hr':>6}"
          f"{'runs':>7}{'pitches':>9}")
    for key, case in (("away", away), ("home", home)):
        team = case[0]["team"]
        res = sp[key]
        a = sa.get(team, {})
        print(f"  {case[1].name[:19]:<20}"
              f"{st.mean(r.outs for r in res):>7.1f}"
              f"{st.mean(r.k for r in res):>6.2f}"
              f"{st.mean(r.bb for r in res):>6.2f}"
              f"{st.mean(r.h for r in res):>6.2f}"
              f"{st.mean(r.hr for r in res):>6.2f}"
              f"{st.mean(r.runs for r in res):>7.2f}"
              f"{st.mean(r.pitches for r in res):>9.1f}")
        print(f"  {'  actual':<20}{a.get('outs_recorded', 0):>7}"
              f"{a.get('k', 0):>6}{a.get('bb', 0):>6}{a.get('h', 0):>6}"
              f"{a.get('hr', 0):>6}{a.get('r', 0):>7}"
              f"{a.get('pitches') or 0:>9}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    gid = args[0] if args else "mlb-823336"
    n = int(args[1]) if len(args) > 1 else 20000
    report(gid if gid.startswith("mlb-") else f"mlb-{gid}", n_sims=n)
