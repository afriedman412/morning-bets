"""Simulate a completed slate and score it against BOTH truths at once.

    venv/bin/python -m scratchpad.yesterday [YYYY-MM-DD] [n_sims]

TWO YARDSTICKS, AND THEY ARE NOT THE SAME QUESTION.

  WHAT HAPPENED   the runs actually scored, the outs actually recorded. This
                  is THE OBJECTIVE per AF_PLAN.md and it is what decides
                  whether a mechanism helped.
  WHAT IT CLOSED  Kalshi's last traded probability. A CEILING, not a target
                  — the market is the best available estimate of how much of
                  a game is knowable, and beating it on one slate means
                  nothing while losing to it badly means something.

ONE SET OF SIMULATED GAMES FEEDS EVERY LINE. That is the premise in
AF_PLAN.md: the full-game total, the F5, each team's runs and the starter's
own line are all READ OFF the same draws rather than priced by separate
models. A slate where the totals look right and the starter lines do not is
diagnostic in a way that four independent models could never be.

RATES ARE CUT STRICTLY BEFORE THE DATE. `rates_before=d` with `since=d` is
what keeps a game out of its own prediction; tying them together is how an
out-of-sample test goes quietly in-sample.

Both starters or neither — `paired_cases` drops a game where only one side
is modelled, and that is deliberate rather than a coverage failure. No
league-average stand-in: inventing the other club invents the score, and the
score is what the hook, the bullpen and the margin all condition on.
"""
from __future__ import annotations

import random
import statistics as st
import sys
from collections import defaultdict

from src import kalshi
from src.context import calibrate as cal
from src.context import sim
from src.context.sources import rates as rate_src

N_SIMS = 400

#: Kalshi series -> what we read off the simulation. Only the ones whose
#: ticker shape is understood are here; the rest are left alone rather than
#: guessed at.
SERIES = {
    "KXMLBF5TOTAL": "f5 total",
    "KXMLBTOTAL": "game total",
}


def _games(date_str: str, conn=None):
    """{game_id: row} with the actual result, for the date."""
    from src import db
    q = """select game_id, away_team, home_team,
                  away_team_abbr as away_abbr, home_team_abbr as home_abbr,
                  away_score, home_score,
                  away_score_f5 as away_f5, home_score_f5 as home_f5, status
           from games where sport = 'mlb' and date = ?"""
    def run(c):
        return [dict(r) for r in c.execute(q, (date_str,))]
    if conn is not None:
        rows = run(conn)
    else:
        with db.connect() as c:
            rows = run(c)
    return {r["game_id"]: r for r in rows}


def simulate_day(date_str, n_sims=N_SIMS, seed=0):
    """{game_id: {...distributions...}} for every fully-modelled game."""
    lg = sim.league()
    pens = rate_src.bullpens(lg)
    cal._CASES.clear()
    sides = defaultdict(list)
    for s, p, l in cal.build_cases(since=date_str, rates_before=date_str):
        if s["date"] == date_str:
            sides[s["game_id"]].append((s, p, l))

    out = {}
    for gid, v in sides.items():
        if len(v) != 2 or sum(bool(x[0]["is_home"]) for x in v) != 1:
            continue
        home = next(x for x in v if x[0]["is_home"])
        away = next(x for x in v if not x[0]["is_home"])
        rng = random.Random(seed + hash(gid) % 10000)
        draws = [cal.replay((away, home), lg, pens, rng, track=(5,))
                 for _ in range(n_sims)]
        # A Side's `runs` are runs ALLOWED, so away_sp.runs is the HOME
        # team's score. `prefix_side` has already undone that crossing.
        rec = {
            "away_name": away[0]["player_name"],
            "home_name": home[0]["player_name"],
            "away_team": away[0]["team"], "home_team": home[0]["team"],
            "total": [d.away + d.home for d in draws],
            "away_runs": [d.away for d in draws],
            "home_runs": [d.home for d in draws],
            "f5_total": [sum(d.prefix_side[5]) for d in draws
                         if 5 in d.prefix_side],
            "away_sp_outs": [d.away_sp.outs for d in draws],
            "home_sp_outs": [d.home_sp.outs for d in draws],
            "away_sp_k": [d.away_sp.k for d in draws],
            "home_sp_k": [d.home_sp.k for d in draws],
        }
        out[gid] = rec
    return out


def _p_over(vals, line):
    return sum(1 for v in vals if v > line) / len(vals) if vals else None


def main(argv):
    date_str = argv[0] if argv and argv[0][:2] == "20" else "2026-08-25"
    n_sims = int(argv[1]) if len(argv) > 1 else N_SIMS

    games = _games(date_str)
    finals = {g: r for g, r in games.items() if r["status"] == "Final"}
    print(f"  {date_str}: {len(games)} games, {len(finals)} final", flush=True)
    sims = simulate_day(date_str, n_sims)
    print(f"  {len(sims)} fully modelled (both starters on record), "
          f"{n_sims} draws each\n", flush=True)

    # ---- against WHAT HAPPENED ----------------------------------------
    print("  AGAINST WHAT HAPPENED")
    print(f"  {'game':<12}{'sim total':>10}{'actual':>8}{'z':>7}"
          f"{'sim F5':>8}{'actF5':>7}{'P(o8.5)':>9}")
    tot_err, f5_err, rows = [], [], []
    for gid, rec in sorted(sims.items()):
        g = games.get(gid)
        if not g or g["status"] != "Final":
            continue
        act = (g["away_score"] or 0) + (g["home_score"] or 0)
        m, s = st.mean(rec["total"]), st.pstdev(rec["total"])
        z = (act - m) / s if s else 0.0
        af5 = ((g.get("away_f5") or 0) + (g.get("home_f5") or 0)
               if g.get("away_f5") is not None else None)
        f5m = st.mean(rec["f5_total"]) if rec["f5_total"] else float("nan")
        tot_err.append(act - m)
        if af5 is not None and rec["f5_total"]:
            f5_err.append(af5 - f5m)
        lbl = f"{g['away_abbr']}@{g['home_abbr']}"
        print(f"  {lbl:<12}{m:>10.2f}{act:>8}{z:>+7.2f}{f5m:>8.2f}"
              f"{(af5 if af5 is not None else -1):>7}"
              f"{_p_over(rec['total'], 8.5):>9.3f}")
        rows.append((gid, rec, g, act))
    if tot_err:
        print(f"\n  full-game total: mean error {st.mean(tot_err):+.2f} runs, "
              f"RMSE {(st.mean(e*e for e in tot_err))**0.5:.2f}, n={len(tot_err)}")
    if f5_err:
        print(f"  F5 total:        mean error {st.mean(f5_err):+.2f} runs, "
              f"RMSE {(st.mean(e*e for e in f5_err))**0.5:.2f}, n={len(f5_err)}")

    # ---- starters ------------------------------------------------------
    print(f"\n  STARTERS — outs and strikeouts against what they did")
    print(f"  {'pitcher':<22}{'simOuts':>9}{'act':>5}{'simK':>7}{'actK':>6}")
    o_err, k_err = [], []
    for gid, rec, g, _ in rows:
        for side in ("away", "home"):
            nm = rec[f"{side}_name"]
            truth = _starter_line(gid, nm)
            if not truth:
                continue
            mo = st.mean(rec[f"{side}_sp_outs"])
            mk = st.mean(rec[f"{side}_sp_k"])
            o_err.append(truth["o"] - mo)
            k_err.append(truth["k"] - mk)
            print(f"  {nm[:21]:<22}{mo:>9.1f}{truth['o']:>5}"
                  f"{mk:>7.1f}{truth['k']:>6}")
    if o_err:
        print(f"\n  starter outs: mean error {st.mean(o_err):+.2f}, "
              f"RMSE {(st.mean(e*e for e in o_err))**0.5:.2f}, n={len(o_err)}")
        print(f"  starter K:    mean error {st.mean(k_err):+.2f}, "
              f"RMSE {(st.mean(e*e for e in k_err))**0.5:.2f}")

    # ---- against WHAT IT CLOSED ---------------------------------------
    print(f"\n  AGAINST KALSHI'S CLOSE")
    print(f"  {'series':<14}{'line':>7}{'ours':>8}{'close':>8}{'won':>6}"
          f"{'ourBr':>8}{'mktBr':>8}")
    ours_b, mkt_b = [], []
    for series, what in SERIES.items():
        try:
            mkts = kalshi.settled_markets(series)
        except Exception as e:
            print(f"  {series}: unavailable ({str(e)[:40]})")
            continue
        for m in mkts:
            tk = m["ticker"]
            if kalshi.ticker_date(tk) != date_str:
                continue
            parts = tk.split("-")
            if len(parts) < 3 or not parts[-1].isdigit():
                continue
            line = int(parts[-1]) - 0.5
            g = _match_abbr(parts[1], games)
            if not g or g["game_id"] not in sims:
                continue
            rec = sims[g["game_id"]]
            vals = rec["f5_total"] if "F5" in series else rec["total"]
            if not vals:
                continue
            try:
                pp = kalshi.price_path(tk, "over")
            except Exception:
                continue
            if not pp or pp.get("close_prob") is None:
                continue
            ours = _p_over(vals, line)
            if "F5" in series:
                actual = ((g.get("away_f5") or 0) + (g.get("home_f5") or 0))
            else:
                actual = (g["away_score"] or 0) + (g["home_score"] or 0)
            won = actual > line
            ob = (ours - won) ** 2
            mb = (pp["close_prob"] - won) ** 2
            ours_b.append(ob)
            mkt_b.append(mb)
            print(f"  {what:<14}{line:>7.1f}{ours:>8.3f}"
                  f"{pp['close_prob']:>8.3f}{str(won):>6}{ob:>8.3f}{mb:>8.3f}")
    if ours_b:
        print(f"\n  {len(ours_b)} settled contracts   "
              f"our Brier {st.mean(ours_b):.4f}   "
              f"market {st.mean(mkt_b):.4f}")
        print("  ONE SLATE. This is a smoke test, not evidence — the sample")
        print("  is far too small to move any conclusion either way.")
    else:
        print("  no settled contracts matched for this date")


def _starter_line(game_id, name):
    from src import db
    with db.connect() as c:
        for r in c.execute(
                "select outs_recorded o, k from mlb_pitching "
                "where game_id = ? and player_name = ?", (game_id, name)):
            return dict(r)
    return None


def _match_abbr(seg, games):
    seg = seg.upper()
    for g in games.values():
        if (g["away_abbr"] or "").upper() in seg or \
           (g["home_abbr"] or "").upper() in seg:
            return g
    return None


if __name__ == "__main__":
    main(sys.argv[1:])
