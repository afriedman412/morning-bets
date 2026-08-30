"""Full-game totals against Kalshi. The product, measured for the first time.

WHY THIS COULD NOT EXIST BEFORE 2026-08-23. The engine then was
`simulate_start`, which modelled one pitcher and stopped when the hook
fired, so a nine-inning total was not something this project could produce.
First-five was reachable through a stub; the game was not. Both are deleted
now. `game.py` closed that, and this is the first time the actual deliverable
— a game over/under — has been scored against a real settled market.

WHY IT MATTERS MORE THAN THE PROP TESTS. Strikeouts and outs are one input
each. A total is the whole simulation at once: both rotations, both lineups,
two bullpens, the removal rule, base-running and errors, all of it settling
on one number. It is the only test where being wrong anywhere shows up.

SAME LEAKAGE GUARDS as `f5_market` and `versus_market`, and they are not
optional: rates strictly before the game date, the market price taken at the
last trade BEFORE first pitch, and a shuffle control on the CLV correlation
because `sim - open` and `close - open` share a `-open` term and can
correlate for free.

WHAT THIS RUN STILL CANNOT SETTLE. The hook, club patience and pitcher leash
were fitted on the full season including these dates. Rates are frozen per
date; those are not. So treat the absolute numbers as optimistic and the
comparison BETWEEN two engines — which share the contamination — as the
clean signal.
"""
from __future__ import annotations

import random
import statistics as st
import sys
from collections import defaultdict

from src import db, kalshi
from src.context import calibrate as cal
from src.context import game, sim
from src.context.f5_market import MIN_TRADES, _match
from src.context.sources import rates as rate_src

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


def _totals(pair, home_abbr, lg, pens, n_sims, seed) -> list[int] | None:
    """`n_sims` simulated NINE-INNING totals for one game."""
    home = next((x for x in pair if x[0]["team"] == home_abbr), None)
    away = next((x for x in pair if x[0]["team"] != home_abbr), None)
    if not home or not away:
        return None
    # NAMED BY WHO FACES THEM. `away[2]` is the nine the AWAY PITCHER
    # faces, which is the HOME club's batters — so the away pitching
    # side takes `away_faces`. The old `a_nine`/`h_nine` names read as
    # "the away team's nine" and every one of these files handed the
    # away side the wrong one: every pitcher faced his own teammates.
    away_faces = cal.adjust_lineup(away[2], False)
    home_faces = cal.adjust_lineup(home[2], True)
    a_hook = sim.for_start(sim.Hook(), away[0]["team"], away[1].name)
    h_hook = sim.for_start(sim.Hook(), home[0]["team"], home[1].name)
    rng = random.Random(seed)
    out = []
    for _ in range(n_sims):
        # `apply_leash=False` because `a_hook`/`h_hook` have already been
        # through `sim.for_start`, which ADDS — see `game.build_side`.
        A = game.build_side(away[1],
                            pens.get((away[0]["team"] or "").upper(), []),
                            away_faces, a_hook, rng,
                            team=away[0]["team"], apply_leash=False,
                            date=away[0].get("date"))
        H = game.build_side(home[1],
                            pens.get((home[0]["team"] or "").upper(), []),
                            home_faces, h_hook, rng,
                            team=home[0]["team"], apply_leash=False,
                            date=home[0].get("date"))
        out.append(game.simulate_game(A, H, lg, rng).total)
    return out


def collect(dates, n_sims=250, seed=0, verbose=True) -> list[dict]:
    lg = sim.league()
    pens = rate_src.bullpens(lg)
    out = []
    for d in dates:
        games = _games(d)
        if not games:
            continue
        # Rates strictly before the date; the games scored are the ones ON
        # it. Tying those together is what makes an out-of-sample test
        # quietly in-sample.
        cal._CASES.clear()
        sides = defaultdict(list)
        for s, p, ln in cal.build_cases(since=d, rates_before=d):
            if s["date"] == d:
                sides[s["game_id"]].append((s, p, ln))

        cache = {}
        for m in kalshi.settled_markets("KXMLBTOTAL"):
            tk = m["ticker"]
            if kalshi.ticker_date(tk) != d:
                continue
            parts = tk.split("-")
            if len(parts) < 3 or not parts[-1].isdigit():
                continue
            line = int(parts[-1]) - 0.5
            g = _match(parts[1], games)
            if not g:
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
                vals = _totals(pair, g["h"], lg, pens, n_sims, seed)
                if vals is None:
                    continue
                cache[g["game_id"]] = vals
            vals = cache[g["game_id"]]
            actual = (g["asc_"] or 0) + (g["hsc"] or 0)
            out.append({
                "date": d, "game": g["game_id"], "line": line,
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
    if n < 30:
        print(f"only {n} rows — not enough to say anything")
        return

    def brier(k):
        return sum((r[k] - (1 if r["won"] else 0)) ** 2 for r in rows) / n
    base = sum(1 for r in rows if r["won"]) / n
    bb = base * (1 - base)
    print(f"\n{n} settled GAME-total contracts, base rate {base:.1%}")
    print(f"  {'':<14}{'Brier':>9}{'vs base':>10}")
    for lbl, k in (("Kalshi close", "market"), ("Kalshi open", "open"),
                   ("our game sim", "ours")):
        print(f"  {lbl:<14}{brier(k):>9.4f}{(bb - brier(k)) / bb:>+10.1%}")

    # Is the simulated total itself unbiased against what happened? A
    # probability can score well while the underlying number is off, and on
    # a total that shows up as a systematic lean to one side.
    print(f"\n  simulated total {st.mean(r['sim_mean'] for r in rows):.2f} "
          f"vs actual {st.mean(r['actual'] for r in rows):.2f}"
          f"   (line {st.mean(r['line'] for r in rows):.2f})")
    over = sum(1 for r in rows if r["ours"] > 0.5) / n
    print(f"  we say OVER on {over:.1%} of contracts; "
          f"the over actually hit {base:.1%}")

    def corr(xs, ys):
        mx, my = st.mean(xs), st.mean(ys)
        sx, sy = st.pstdev(xs), st.pstdev(ys)
        if sx == 0 or sy == 0:
            return 0.0
        return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n * sx * sy)

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
    print("\n  F5 on the same test: z +29.7, blend +19.0%, direction 62.1%.")
    print("  K props: z +43.5, blend +32.9%, direction 73.2%.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    dates = args or [f"2026-08-{d:02d}" for d in range(14, 22)]
    report(collect(dates))
