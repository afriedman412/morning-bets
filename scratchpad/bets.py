"""Simulate specific bets off today's slate and KEEP EVERY DRAW.

    venv/bin/python -m scratchpad.bets [YYYY-MM-DD] [n_sims]

WHY IT STORES THE DRAWS. A probability is a summary, and the summary is the
part you cannot re-interrogate: "what does the run line do if the total goes
over" or "how often does Gore reach seven with the team under nine" are
questions about the JOINT distribution, and both sides of them come out of
the same simulated game. Answering them from stored draws is a query;
answering them from a stored probability is another two-minute run.

One row per (game, draw) in `scratchpad/sims/sims_<date>.db`, table `draws`.
Both starters' lines and both teams' scores are on the row, because they
came out of one game and separating them would throw away exactly the
correlation that makes the file worth keeping.

EVERY NUMBER HERE IS ON A PROJECTED LINEUP unless the slate says otherwise,
and `price` flags that per row for a reason: it is the largest single source
of error in a morning run. On 2026-08-26 all five bets below were projected,
and every disagreement of 10+ cents on the full board was too.
"""
from __future__ import annotations

import pathlib
import sqlite3
import sys
import time
from datetime import date

from src.context import calibrate, price, sim
from src.context.sources import rates as rate_src

OUT_DIR = pathlib.Path("scratchpad/sims")

#: (label, matchup, how to read one simulated game -> did it win)
#: `r` is a `game.GameResult`: `away`/`home` are runs SCORED, `away_sp` /
#: `home_sp` are the two starters' lines.
BETS = [
    ("Red Sox -1.5", "BOS@MIA", lambda r: r.away - r.home >= 2),
    ("CHC @ AZ over 8.5", "CHC@AZ", lambda r: r.away + r.home >= 9),
    ("Randy Dobnak under 16.5 outs", "KC@TOR", lambda r: r.away_sp.outs <= 16),
    ("Dodgers -1.5", "LAD@ATL", lambda r: r.away - r.home >= 2),
    ("MacKenzie Gore over 6.5 K", "TEX@CWS", lambda r: r.away_sp.k >= 7),
]

SCHEMA = """
create table if not exists draws (
  matchup text, draw int, away_abbr text, home_abbr text,
  away_sp text, home_sp text,
  away_runs int, home_runs int, away_f5 int, home_f5 int,
  a_outs int, a_k int, a_bb int, a_h int, a_hr int, a_er int, a_pitches int,
  h_outs int, h_k int, h_bb int, h_h int, h_hr int, h_er int, h_pitches int
);
create index if not exists ix_draws_matchup on draws(matchup);
"""


def _bar(head: str, done: int, total: int, t0: float, width: int = 24):
    """One in-place progress line per matchup.

    Written to STDERR so that piping the report somewhere does not carry a
    hundred half-drawn bars into the file, and with `\r` rather than a
    newline so a two-minute run is one line and not a screenful.
    """
    frac = done / total
    el = time.time() - t0
    eta = (el / frac - el) if frac else 0.0
    bar = "#" * int(frac * width)
    sys.stderr.write(
        f"\r{head}[{bar:<{width}}] {frac:4.0%} {done:>6}/{total}"
        f"  {el:3.0f}s elapsed, {eta:3.0f}s left")
    if done >= total:
        sys.stderr.write(f"\r{head}[{'#' * width}] done, {el:.0f}s"
                         + " " * 28)
    sys.stderr.flush()


def simulate(date_str: str, n_sims: int) -> dict:
    """{matchup: [GameResult]} for every matchup a listed bet needs."""
    lg = sim.league()
    # Rates strictly before today: a start cannot inform its own price.
    pr = rate_src.pitcher_rates(lg, before=date_str)
    br = rate_src.batter_rates(lg, before=date_str)
    league_bats = sim.BatterRates(name="league", k_pct=lg["k_pct"],
                                  bb_pct=lg["bb_pct"], hr_pct=lg["hr_pct"],
                                  babip=lg["babip"])
    pens = rate_src.bullpens(lg, before=date_str)

    want = {m for _, m, _ in BETS}
    games = {f"{g['away']['abbr']}@{g['home']['abbr']}": g
             for g in price.slate(date_str)}
    out = {}
    for m in want:
        g = games.get(m)
        if g is None:
            print(f"  {m:<10} NOT ON THE SLATE")
            continue
        conf = bool(g["away"]["lineup"]) and bool(g["home"]["lineup"])
        head = (f"  {m:<10} {g['away']['starter']} vs "
                f"{g['home']['starter']}"[:56]).ljust(58)
        t0 = time.time()
        res, why = price.simulate_slate_game(
            g, date_str, lg, pr, br, league_bats, pens, n_sims=n_sims,
            progress=lambda i, n: _bar(head, i, n, t0))
        if res is None:
            # The standing rule: no modelled opposing starter -> decline.
            print(f"{head}DECLINED — {why}")
            continue
        print(f"   {'confirmed' if conf else 'PROJECTED'} lineups, "
              f"{time.time() - t0:.0f}s")
        out[m] = (g, res)
    return out


def store(date_str: str, sims: dict) -> pathlib.Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"sims_{date_str.replace('-', '_')}.db"
    if path.exists():
        path.unlink()          # a re-run replaces, never appends
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    for m, (g, res) in sims.items():
        conn.executemany(
            "insert into draws values (" + ",".join("?" * 24) + ")",
            [(m, i, g["away"]["abbr"], g["home"]["abbr"],
              g["away"]["starter"], g["home"]["starter"],
              r.away, r.home, r.away_f5, r.home_f5,
              r.away_sp.outs, r.away_sp.k, r.away_sp.bb, r.away_sp.h,
              r.away_sp.hr, r.away_sp.earned, r.away_sp.pitches,
              r.home_sp.outs, r.home_sp.k, r.home_sp.bb, r.home_sp.h,
              r.home_sp.hr, r.home_sp.earned, r.home_sp.pitches)
             for i, r in enumerate(res)])
    conn.commit()
    conn.close()
    return path


def report(sims: dict) -> None:
    print(f"\n  {'bet':<32}{'our P':>8}{'+/-':>7}{'fair':>9}")
    for label, m, won in BETS:
        if m not in sims:
            continue
        res = sims[m][1]
        n = len(res)
        p = sum(1 for r in res if won(r)) / n
        se = (p * (1 - p) / n) ** 0.5
        # American odds at our probability, before any vig.
        fair = (f"{-100 * p / (1 - p):+.0f}" if p > 0.5
                else f"{100 * (1 - p) / p:+.0f}") if 0 < p < 1 else "--"
        print(f"  {label:<32}{p:>8.3f}{se:>7.3f}{fair:>9}")


def main(argv: list[str]) -> None:
    d = argv[0] if argv else date.today().isoformat()
    n = int(argv[1]) if len(argv) > 1 else 20000
    print(f"{d}, {n} draws per matchup, leash "
          f"{'ON' if sim.USE_LEASH else 'off'}, park "
          f"{'ON' if calibrate.USE_PARK else 'off'}\n")
    sims = simulate(d, n)
    report(sims)
    path = store(d, sims)
    rows = sqlite3.connect(path).execute(
        "select count(*) from draws").fetchone()[0]
    print(f"\n  {rows} draws -> {path}")
    print(f"  query it:  sqlite3 {path} "
          f"\"select avg(away_runs+home_runs) from draws "
          f"where matchup='CHC@AZ'\"")


if __name__ == "__main__":
    main(sys.argv[1:])
