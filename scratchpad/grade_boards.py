"""Grade every saved board against what actually happened.

For each dated board JSON (latest version per date), resolve every rung:
totals / team totals / F5 from bets.games, starter K and outs from
bets.mlb_pitching. Report, per market class and overall:

  - our Brier vs Kalshi's on the rungs where both quoted (PAIRED),
  - the record and P&L of "bet the gap at Kalshi's mid" by threshold.

Read-only. Usage: venv/bin/python -m scratchpad.grade_boards [--through DATE]

THE TABLES ARE FUNCTIONS, NOT PRINT STATEMENTS. `graded_rungs` returns one
row per settled rung and `head_to_head` / `bet_the_gap` / `calibration`
reduce that list; `main` only formats what they return. The chat endpoint
(`scratchpad.ask`) calls the same three, so the page and the terminal
cannot report two different Briers for the same date range — the same
reason `boards.py` exists.

PATHS ARE ABSOLUTE, resolved off this file rather than the working
directory, because the Flask server is not always started from the repo
root and a silently empty `glob` reads as "no boards graded yet".
"""
import glob
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
BETS_DIR = os.path.join(ROOT, "bets")
DB = os.path.join(ROOT, "morning_bets.db")

# later in this list wins when several boards exist for one date
VERSION_RANK = ["proj", "", "wx", "v2", "v3", "pm"]

BOARD_FILE = re.compile(
    r"^(\d{4}_\d{2}_\d{2})_(?:(\w+)_)?board(?:_(\w+))?\.json$")


def pick_boards(through, since=None, bets_dir=None):
    """{date: path} — the board of record per date, oldest date first.

    `bets_dir` defaults at CALL time so tests can point at a fixture.
    """
    by_date = {}
    for path in sorted(glob.glob(os.path.join(bets_dir or BETS_DIR,
                                              "2026_*_board*.json"))):
        m = BOARD_FILE.match(os.path.basename(path))
        if not m:
            continue
        date = m.group(1).replace("_", "-")
        tag = m.group(2) or m.group(3) or ""
        if date > through or (since and date < since):
            continue
        rank = VERSION_RANK.index(tag) if tag in VERSION_RANK else -1
        if rank < 0:
            continue
        if date not in by_date or rank > by_date[date][0]:
            by_date[date] = (rank, path)
    return {d: p for d, (r, p) in sorted(by_date.items())}


def load_actuals(dates, db=None):
    con = sqlite3.connect(f"file:{db or DB}?mode=ro", uri=True)
    qmarks = ",".join("?" * len(dates))
    games = {}          # (date, away, home) -> list of game rows
    for row in con.execute(
            f"""select date, away_team_abbr, home_team_abbr, game_id,
                       away_score, home_score, away_score_f5, home_score_f5
                from games where date in ({qmarks}) and status = 'Final'""",
            list(dates)):
        games.setdefault((row[0], row[1], row[2]), []).append(row)
    pitching = {}       # (game_id, name) -> (k, outs)
    gids = [g[3] for rows in games.values() for g in rows]
    for i in range(0, len(gids), 500):
        chunk = gids[i:i + 500]
        q = ",".join("?" * len(chunk))
        for gid, name, k, outs in con.execute(
                f"""select game_id, player_name, k, outs_recorded
                    from mlb_pitching
                    where is_starter = 1 and game_id in ({q})""", chunk):
            pitching[(gid, name)] = (k, outs)
    con.close()
    return games, pitching


def actual_value(row, game, pitching):
    """The realised number the rung settles on, or None if unresolvable."""
    _, _, _, gid, a_sc, h_sc, a_f5, h_f5 = game
    bet = row["bet"]
    if row["cls"] == "total":
        return a_sc + h_sc
    if row["cls"] == "f5":
        if a_f5 is None or h_f5 is None:
            return None
        return a_f5 + h_f5
    if row["cls"] == "team":
        abbr = bet.split()[0]
        if abbr == game[1]:
            return a_sc
        if abbr == game[2]:
            return h_sc
        return None
    if row["cls"] in ("k", "outs"):
        name = re.sub(r"\s+(k|outs)\s+[\d.]+$", "", bet)
        line = pitching.get((gid, name))
        if line is None:
            return None
        return line[0] if row["cls"] == "k" else line[1]
    return None


def line_of(bet):
    return float(bet.split()[-1])


def graded_rungs(through, since=None, bets_dir=None, db=None):
    """Every rung on every board of record that SETTLED, one dict each.

    Returns (rows, unresolved, boards). A row carries both what was
    priced (`p_us`, `p_k`, `line`) and what happened (`actual`, `hit`,
    `push`), so a caller never has to re-open a board to say why a rung
    won. `p_k` is None where Kalshi never quoted it — the head-to-head
    tables drop those and the calibration table keeps them.
    """
    boards = pick_boards(through, since=since, bets_dir=bets_dir)
    if not boards:
        return [], {}, {}
    games, pitching = load_actuals(list(boards), db=db)

    rows = []
    unresolved = defaultdict(int)
    for date, path in boards.items():
        d = json.load(open(path))
        for g in d["games"]:
            key = (date, g["away"], g["home"])
            found = games.get(key, [])
            if len(found) != 1:
                unresolved["game " + ("dup" if len(found) > 1 else "missing")]\
                    += len(g["rows"])
                continue
            for r in g["rows"]:
                val = actual_value(r, found[0], pitching)
                if val is None:
                    unresolved[r["cls"]] += 1
                    continue
                line = line_of(r["bet"])
                rows.append(dict(
                    date=date, cls=r["cls"], bet=r["bet"], board=path,
                    game=f'{g["away"]} @ {g["home"]}', line=line, actual=val,
                    p_us=r["p_over"], p_k=r.get("p_kalshi"),
                    push=(val == line), hit=(1 if val > line else 0)))
    return rows, dict(unresolved), boards


def head_to_head(rows, classes=("total", "team", "f5", "k", "outs", "ALL")):
    """Brier ours against Kalshi's, PAIRED on the rungs both quoted.

    The se is of the PER-RUNG DIFFERENCE, not of either Brier: the two
    scores are read off the same outcome and move together, so the
    difference is far better resolved than two independent means would
    suggest. Rungs Kalshi never quoted are not a head to head and are
    dropped rather than scored against nothing.
    """
    paired = [r for r in rows if not r["push"] and r["p_k"] is not None]
    out = []
    for cls in classes:
        sel = paired if cls == "ALL" else [r for r in paired
                                           if r["cls"] == cls]
        if not sel:
            continue
        diffs = [(r["p_us"] - r["hit"]) ** 2 - (r["p_k"] - r["hit"]) ** 2
                 for r in sel]
        md = sum(diffs) / len(diffs)
        sd = (sum((x - md) ** 2 for x in diffs) / max(len(diffs) - 1, 1)) ** .5
        out.append(dict(
            cls=cls, n=len(sel),
            brier_us=sum((r["p_us"] - r["hit"]) ** 2 for r in sel) / len(sel),
            brier_kalshi=sum((r["p_k"] - r["hit"]) ** 2 for r in sel)
            / len(sel),
            diff=md, se=sd / len(diffs) ** .5))
    return out


def bet_the_gap(rows, thresholds=(0.03, 0.05, 0.10)):
    """Our side at Kalshi's mid, one unit a rung, by minimum gap.

    A COUNTERFACTUAL, not a record: it takes every disagreement at the
    morning mid, which is neither what was bet nor what could have been
    filled. Read it as whether the disagreements pointed the right way.
    """
    paired = [r for r in rows if not r["push"] and r["p_k"] is not None]
    out = []
    for thr in thresholds:
        rets, wins = [], 0
        for r in paired:
            gap = r["p_us"] - r["p_k"]
            if abs(gap) < thr:
                continue
            over = gap > 0
            price = r["p_k"] if over else 1 - r["p_k"]
            won = r["hit"] if over else 1 - r["hit"]
            rets.append((1 - price) / price if won else -1.0)
            wins += won
        if not rets:
            continue
        m = sum(rets) / len(rets)
        sd = (sum((x - m) ** 2 for x in rets) / max(len(rets) - 1, 1)) ** .5
        out.append(dict(thr=thr, n=len(rets), won=wins, pl=sum(rets),
                        per_bet=m, se=sd / len(rets) ** .5))
    return out


def calibration(rows, min_n=20):
    """Our P(over) against how often the over actually hit, by decile."""
    live = [r for r in rows if not r["push"]]
    out = []
    for lo in [x / 10 for x in range(1, 9)]:
        sel = [r for r in live if lo <= r["p_us"] < lo + .1]
        if len(sel) < min_n:
            continue
        hr = sum(r["hit"] for r in sel) / len(sel)
        out.append(dict(lo=lo, hi=lo + .1, n=len(sel),
                        ours=sum(r["p_us"] for r in sel) / len(sel),
                        actual=hr, se=(hr * (1 - hr) / len(sel)) ** .5))
    return out


def main(argv):
    through = "2026-09-18"
    if "--through" in argv:
        through = argv[argv.index("--through") + 1]
    graded, unresolved, boards = graded_rungs(through)
    if not boards:
        print(f"no boards on or before {through}")
        return

    live = [g for g in graded if not g["push"]]
    paired = [g for g in live if g["p_k"] is not None]

    print(f"boards: {len(boards)} dates {min(boards)}..{max(boards)}  "
          f"(latest version per date)")
    print(f"rungs graded {len(graded)}  pushes {sum(g['push'] for g in graded)}"
          f"  live {len(live)}  with-kalshi {len(paired)}")
    if unresolved:
        print("unresolved:", unresolved)

    print("\nHEAD TO HEAD — Brier on the same rungs, lower is better")
    print(f"  {'class':6s} {'n':>5s} {'us':>8s} {'kalshi':>8s} "
          f"{'diff':>8s} {'se(diff)':>8s}")
    for r in head_to_head(graded):
        print(f"  {r['cls']:6s} {r['n']:5d} {r['brier_us']:8.4f} "
              f"{r['brier_kalshi']:8.4f} {r['diff']:+8.4f} {r['se']:8.4f}")

    print("\nBET THE GAP — our side at Kalshi's mid, 1 unit stake per rung")
    print(f"  {'gap>=':>6s} {'n':>5s} {'won':>4s} {'P&L':>8s} "
          f"{'per bet':>8s} {'se':>7s}")
    for r in bet_the_gap(graded):
        print(f"  {r['thr']:6.2f} {r['n']:5d} {r['won']:4d} {r['pl']:+8.2f} "
              f"{r['per_bet']:+8.3f} {r['se']:7.3f}")

    print("\nCALIBRATION — our probability vs how often over actually hit")
    print(f"  {'bucket':>10s} {'n':>5s} {'ours':>6s} {'actual':>7s}")
    for r in calibration(graded):
        print(f"  {r['lo']:.1f}-{r['hi']:.1f} {r['n']:5d} {r['ours']:6.3f} "
              f"{r['actual']:7.3f}  (se {r['se']:.3f})")


if __name__ == "__main__":
    main(sys.argv[1:])
