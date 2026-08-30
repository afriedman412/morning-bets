"""Does the F5 model carry the same open-to-close signal the K model does?

The question this whole branch exists to answer. Strikeouts showed a real
edge against Kalshi's OPENING price — 32% better at predicting the close,
73% direction accuracy, +3.7 cents on five-cent disagreements — while outs
showed none (z 1.3 against 43.5). The difference is which half of the model
each bet leans on: K rides the rate model, outs ride the hook.

F5 runs ride the rate model too, which is the argument for expecting the
edge to transfer. This measures whether it actually does.

SAME THREE LEAKAGE GUARDS as versus_market: rates strictly before the game
date, the market price taken at the last trade BEFORE first pitch, and the
shuffle control on the CLV correlation — `sim - open` and `close - open`
share a `-open` term and can correlate for free. On K that artifact ran
NEGATIVE (-0.267), so it was hiding signal rather than making it, but that
is a fact about that data and not a guarantee.
"""
from __future__ import annotations

import random
import re
from collections import defaultdict

from src import db, kalshi
from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src

MIN_TRADES = 5
_TEAMS = re.compile(r"^\d{2}[A-Z]{3}\d{6}([A-Z]{2,3})([A-Z]{2,3})$")


def _games(date_str: str, conn=None) -> dict:
    """{(away_abbr, home_abbr): row} for one date, with F5 scores."""
    q = """select game_id, away_team_abbr a, home_team_abbr h,
                  away_score_f5 af5, home_score_f5 hf5
           from games where sport = 'mlb' and date = ?
             and away_score_f5 is not null"""
    def _run(c):
        return {(r["a"], r["h"]): dict(r) for r in c.execute(q, (date_str,))}
    if conn is not None:
        return _run(conn)
    with db.connect() as c:
        return _run(c)


def _match(seg: str, games: dict):
    """Kalshi packs both abbreviations into one run of letters, and they are
    2-3 characters each, so the split is ambiguous — try every one."""
    letters = re.sub(r"^\d{2}[A-Z]{3}\d{6}", "", seg)
    for i in (2, 3):
        for j in (2, 3):
            if i + j != len(letters):
                continue
            key = (letters[:i], letters[i:])
            if key in games:
                return games[key]
    return None


def _f5_totals(pair, home_abbr, lg, pens, n_sims, seed):
    """`n_sims` simulated F5 totals for one game. -> [int]

    THE STUB ENGINE IS GONE. Until 2026-08-25 this took an `engine` argument
    and could run `f5.simulate_f5` instead — one league-average reliever for
    every club and a flat 0.33 for stranded runners. It was kept so the two
    could be compared on the same contracts, and keeping it is what let a
    mechanism be wired into one engine and silently absent from the other
    for a full day. There is one engine now.
    """
    home = next((x for x in pair if x[0]["team"] == home_abbr), None)
    away = next((x for x in pair if x[0]["team"] != home_abbr), None)
    if not home or not away:
        return None
    # HOME/ROAD, which this module never applied. The rest of the pipeline
    # centres the opposing lineup on the season mean and `f5_market` did not,
    # so every previous number here was measured on a different model from
    # the one being priced.
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
        # `apply_leash=False` BECAUSE THE HOOK ABOVE IS ALREADY FINISHED.
        # `sim.for_start` adds to `team_offset`, so leaving the default on
        # top of a hook that has already been through it charged this
        # module's starters their own leash TWICE. `team` and `date` still
        # have to travel — they feed the bullpen state and the defence,
        # neither of which rides on the hook.
        A = game.build_side(away[1], pens.get((away[0]["team"] or "").upper(),
                                              []), away_faces, a_hook, rng,
                            team=away[0]["team"], apply_leash=False,
                            date=away[0].get("date"))
        H = game.build_side(home[1], pens.get((home[0]["team"] or "").upper(),
                                              []), home_faces, h_hook, rng,
                            team=home[0]["team"], apply_leash=False,
                            date=home[0].get("date"))
        out.append(game.simulate_game(A, H, lg, rng).total_f5)
    return out


def collect(dates, n_sims=400, seed=0, verbose=True) -> list[dict]:
    """One row per settled F5-total contract: our number, theirs, the result."""
    lg = sim.league()
    pens = rate_src.bullpens(lg)
    out = []
    for d in dates:
        games = _games(d)
        if not games:
            continue
        # Rates frozen strictly before the date; the starts scored are the
        # ones ON it. `rates_before` is what keeps those separate — tying
        # them together is what makes an "out-of-sample" test quietly
        # in-sample.
        cal._CASES.clear()
        sides = defaultdict(list)
        for s, p, l in cal.build_cases(since=d, rates_before=d):
            if s["date"] == d:
                sides[s["game_id"]].append((s, p, l))

        cache = {}
        for m in kalshi.settled_markets("KXMLBF5TOTAL"):
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
                vals = _f5_totals(pair, g["h"], lg, pens, n_sims, seed)
                if vals is None:
                    continue
                cache[g["game_id"]] = vals
            vals = cache[g["game_id"]]
            ours = sum(1 for v in vals if v > line) / len(vals)
            actual = (g["af5"] or 0) + (g["hf5"] or 0)
            out.append({
                "date": d, "game": g["game_id"], "line": line,
                "ours": ours, "market": pp["close_prob"],
                "open": pp.get("open_prob"), "won": actual > line,
                "actual": actual, "trades": pp["trades"],
            })
        if verbose:
            print(f"  {d}: {len([r for r in out if r['date'] == d])} contracts",
                  flush=True)
    return out


def report(rows: list[dict]) -> None:
    import statistics as st
    rows = [r for r in rows if r.get("open") is not None]
    n = len(rows)
    if n < 30:
        print(f"only {n} rows — not enough to say anything")
        return

    def brier(k):
        return sum((r[k] - (1 if r["won"] else 0)) ** 2 for r in rows) / n
    base = sum(1 for r in rows if r["won"]) / n
    bb = base * (1 - base)
    print(f"\n{n} settled F5-total contracts, base rate {base:.1%}")
    print(f"  {'':<14}{'Brier':>9}{'vs base':>10}")
    for lbl, k in (("Kalshi close", "market"), ("Kalshi open", "open"),
                   ("our F5 sim", "ours")):
        print(f"  {lbl:<14}{brier(k):>9.4f}{(bb - brier(k)) / bb:>+10.1%}")

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
    print(f"\n  for comparison, K on the same test: corr +0.586, z +43.5,")
    print(f"  blend +32.9%, direction 73.2%, +3.7c. Outs: z +1.3, +3.8%.")


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    dates = args or [f"2026-08-{d:02d}" for d in range(14, 22)]
    report(collect(dates))
