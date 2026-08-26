"""One team's runs against Kalshi. The target our own evidence points at.

WHY THIS AND NOT THE BIGGER MARKETS. Home runs carry 29,128 settled
contracts against this market's 12,152, and were the obvious next thing to
try. They are the wrong thing to try. Every edge this project has measured
comes from the STARTER — K props at 73.2% direction, F5 totals at 59.6% —
where the model carries ~600 batters faced, a specific opposing nine, and a
removal rule. A home-run prop is a BATTER outcome, and on the batter side we
carry a single `hr_pct` with no batted-ball data, no contact quality and no
launch angle. Adding park factors to a thin model does not make it an edge.
A ~12% base rate also needs far more contracts to resolve a given edge than
a ~55% one, so the headline count flatters it.

A TEAM TOTAL IS F5's ENGINE POINTED AT A DIFFERENT SETTLEMENT. One team's
runs are what the OPPOSING STARTER allows, which is exactly the quantity
this simulator is built around, and it carries roughly half the variance
sources of a game total — one side rather than two. It is also twice the
size of the F5 market we have been optimising.

AND IT IS A REAL TEST OF THE F5 RESULT. If the F5 edge is mechanism rather
than luck, it should appear here too, on different contracts settling on a
different quantity. If it does not, that is informative about F5.

SAME LEAKAGE GUARDS as every other market test: rates strictly before the
game date, league baselines cut at the same date, the price taken at the
last trade BEFORE first pitch, and a shuffle control on the CLV
correlation. Stale hook offsets are off (`sim.USE_OFFSETS`).
"""
from __future__ import annotations

import random
import re
import statistics as st
import sys
from collections import defaultdict

from src import db, kalshi
from src.context import calibrate as cal
from src.context import game, sim
from src.context.f5_market import MIN_TRADES, _match
from src.context.sources import rates as rate_src

#: `NYM8` -> ("NYM", 8), i.e. the Mets over 7.5 runs.
_LEG = re.compile(r"^([A-Z]{2,3})(\d+)$")

_GAMES_Q = """
select game_id, away_team_abbr a, home_team_abbr h,
       away_score asc_, home_score hsc
from games
where sport = 'mlb' and date = ? and status = 'Final'
  and away_score is not null and home_score is not null
"""


def _games(date_str: str) -> dict:
    with db.connect() as c:
        return {(r["a"], r["h"]): dict(r)
                for r in c.execute(_GAMES_Q, (date_str,))}


def _team_runs(pair, home_abbr, lg, pens, n_sims, seed) -> dict | None:
    """{'away': [...], 'home': [...]} — runs SCORED by each team."""
    home = next((x for x in pair if x[0]["is_home"]), None)
    away = next((x for x in pair if not x[0]["is_home"]), None)
    if not home or not away:
        return None
    # NAMED BY WHO FACES THEM. `away[2]` is the nine the AWAY PITCHER
    # faces, which is the HOME club's batters — so the away pitching
    # side takes `away_faces`. The old `a_nine`/`h_nine` names read as
    # "the away team's nine" and every one of these files handed the
    # away side the wrong one: every pitcher faced his own teammates.
    away_faces = cal.adjust_lineup(away[2], False)
    home_faces = cal.adjust_lineup(home[2], True)
    rng = random.Random(seed)
    out = {"away": [], "home": []}
    for _ in range(n_sims):
        A = game.build_side(away[1],
                            pens.get((away[0]["team"] or "").upper(), []),
                            away_faces, None, rng)
        H = game.build_side(home[1],
                            pens.get((home[0]["team"] or "").upper(), []),
                            home_faces, None, rng)
        r = game.simulate_game(A, H, lg, rng)
        # GameResult.away/.home are runs SCORED, which is what this market
        # settles on — the opposite convention from Side.runs, which is runs
        # ALLOWED. Mixing them is the obvious way to build this backwards.
        out["away"].append(r.away)
        out["home"].append(r.home)
    return out


def collect(dates, n_sims=250, seed=0, verbose=True) -> list[dict]:
    lg_all = sim.league()
    out = []
    for d in dates:
        games = _games(d)
        if not games:
            continue
        lg = sim.league(before=d)
        pens = rate_src.bullpens(lg, before=d)
        cal._CASES.clear()
        sides = defaultdict(list)
        for s, p, ln in cal.build_cases(since=d, rates_before=d):
            if s["date"] == d:
                sides[s["game_id"]].append((s, p, ln))

        cache = {}
        for m in kalshi.settled_markets("KXMLBTEAMTOTAL"):
            tk = m["ticker"]
            if kalshi.ticker_date(tk) != d:
                continue
            parts = tk.split("-")
            if len(parts) < 3:
                continue
            leg = _LEG.match(parts[-1])
            if not leg:
                continue
            team, thresh = leg.group(1), int(leg.group(2))
            line = thresh - 0.5
            g = _match(parts[1], games)
            if not g:
                continue
            # Which side is this ticker about? Anything that matches neither
            # abbreviation is dropped rather than guessed.
            if team == g["h"]:
                who, actual = "home", g["hsc"] or 0
            elif team == g["a"]:
                who, actual = "away", g["asc_"] or 0
            else:
                continue
            pair = sides.get(g["game_id"])
            if not pair or len(pair) != 2:
                continue
            pp = kalshi.price_path(tk, "over")
            if not pp or pp.get("close_prob") is None:
                continue
            if (pp.get("trades") or 0) < MIN_TRADES:
                continue
            if g["game_id"] not in cache:
                v = _team_runs(pair, g["h"], lg, pens, n_sims, seed)
                if v is None:
                    continue
                cache[g["game_id"]] = v
            vals = cache[g["game_id"]][who]
            out.append({
                "date": d, "game": g["game_id"], "team": team, "line": line,
                "ours": sum(1 for v in vals if v > line) / len(vals),
                "market": pp["close_prob"], "open": pp.get("open_prob"),
                "won": actual > line, "actual": actual,
                "sim_mean": sum(vals) / len(vals),
            })
        if verbose:
            print(f"  {d}: {len([r for r in out if r['date'] == d])} "
                  f"contracts", flush=True)
    return out


def report(rows: list[dict]) -> None:
    rows = [r for r in rows if r.get("open") is not None]
    n = len(rows)
    if n < 50:
        print(f"only {n} rows — not enough to say anything")
        return

    def brier(k):
        return sum((r[k] - (1 if r["won"] else 0)) ** 2 for r in rows) / n
    base = sum(1 for r in rows if r["won"]) / n
    bb = base * (1 - base)
    print(f"\n{n} settled TEAM-total contracts, base rate {base:.1%}")
    print(f"  {'':<14}{'Brier':>9}{'vs base':>10}")
    for lbl, k in (("Kalshi close", "market"), ("Kalshi open", "open"),
                   ("our team sim", "ours")):
        print(f"  {lbl:<14}{brier(k):>9.4f}{(bb - brier(k)) / bb:>+10.1%}")

    print(f"\n  simulated team runs {st.mean(r['sim_mean'] for r in rows):.2f}"
          f" vs actual {st.mean(r['actual'] for r in rows):.2f}"
          f"   (line {st.mean(r['line'] for r in rows):.2f})")

    def corr(xs, ys):
        mx, my = st.mean(xs), st.mean(ys)
        sx, sy = st.pstdev(xs), st.pstdev(ys)
        return 0.0 if sx == 0 or sy == 0 else sum(
            (x - mx) * (y - my) for x, y in zip(xs, ys)) / (n * sx * sy)

    ys = [r["market"] - r["open"] for r in rows]
    real = corr([r["ours"] - r["open"] for r in rows], ys)
    random.seed(0)
    cs = []
    for _ in range(200):
        sh = [r["ours"] for r in rows]
        random.shuffle(sh)
        cs.append(corr([s - r["open"] for s, r in zip(sh, rows)], ys))
    z = (real - st.mean(cs)) / max(st.pstdev(cs), 1e-9)
    print(f"\n  CLV: corr {real:+.3f}  shuffled {st.mean(cs):+.3f}  z {z:+.1f}")

    def sq(pred):
        return sum((p - r["market"]) ** 2 for p, r in zip(pred, rows)) / n
    o = sq([r["open"] for r in rows])
    best = min((sq([r["open"] + lam * (r["ours"] - r["open"]) for r in rows]),
                lam) for lam in (0.1, 0.2, 0.25, 0.3, 0.4, 0.5))
    print(f"  predicting the close: open {o:.5f} -> blend {best[0]:.5f} "
          f"({(o - best[0]) / o:+.1%} at lam {best[1]})")
    big = [r for r in rows if abs(r["ours"] - r["open"]) >= 0.05]
    if big:
        right = sum(1 for r in big
                    if (r["ours"] - r["open"]) * (r["market"] - r["open"]) > 0)
        signed = st.mean([(1 if r["ours"] > r["open"] else -1)
                          * (r["market"] - r["open"]) for r in big])
        print(f"  5c+ disagreements n={len(big)}: direction "
              f"{right / len(big):.1%}, {signed * 100:+.1f}c our way")
    print("\n  F5 totals: z +38.7, blend +23.4%, direction 59.6%, +3.4c")
    print("  game totals: z +27.2, blend +4.1%, direction 52.0%, +1.2c")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    dates = args or [f"2026-08-{d:02d}" for d in range(14, 24)]
    report(collect(dates))
