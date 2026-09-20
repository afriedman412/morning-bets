"""Grade every saved board against what actually happened.

For each dated board JSON (latest version per date), resolve every rung:
totals / team totals / F5 from bets.games, starter K and outs from
bets.mlb_pitching. Report, per market class and overall:

  - our Brier vs Kalshi's on the rungs where both quoted (PAIRED),
  - the record and P&L of "bet the gap at Kalshi's mid" by threshold.

Read-only. Usage: venv/bin/python -m scratchpad.grade_boards [--through DATE]
"""
import glob
import json
import math
import re
import sqlite3
import sys
from collections import defaultdict

# later in this list wins when several boards exist for one date
VERSION_RANK = ["proj", "", "wx", "v2", "v3", "pm"]


def pick_boards(through):
    by_date = {}
    for path in sorted(glob.glob("bets/2026_*_board*.json")):
        m = re.match(r"bets/(\d{4}_\d{2}_\d{2})_(?:(\w+)_)?board(?:_(\w+))?\.json",
                     path)
        if not m:
            continue
        date = m.group(1).replace("_", "-")
        tag = m.group(2) or m.group(3) or ""
        if date > through:
            continue
        rank = VERSION_RANK.index(tag) if tag in VERSION_RANK else -1
        if rank < 0:
            continue
        if date not in by_date or rank > by_date[date][0]:
            by_date[date] = (rank, path)
    return {d: p for d, (r, p) in sorted(by_date.items())}


def load_actuals(dates):
    con = sqlite3.connect("file:morning_bets.db?mode=ro", uri=True)
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


def main(argv):
    through = "2026-09-18"
    if "--through" in argv:
        through = argv[argv.index("--through") + 1]
    boards = pick_boards(through)
    games, pitching = load_actuals(list(boards))

    graded = []         # dicts: date, cls, bet, p_us, p_k, hit(0/1), push
    unmatched = defaultdict(int)
    for date, path in boards.items():
        d = json.load(open(path))
        for g in d["games"]:
            key = (date, g["away"], g["home"])
            rows = games.get(key, [])
            if len(rows) != 1:
                unmatched["game " + ("dup" if len(rows) > 1 else "missing")] \
                    += len(g["rows"])
                continue
            for r in g["rows"]:
                val = actual_value(r, rows[0], pitching)
                if val is None:
                    unmatched[r["cls"]] += 1
                    continue
                line = line_of(r["bet"])
                graded.append(dict(
                    date=date, cls=r["cls"], bet=r["bet"], board=path,
                    p_us=r["p_over"], p_k=r.get("p_kalshi"),
                    push=(val == line), hit=(1 if val > line else 0)))

    live = [g for g in graded if not g["push"]]
    paired = [g for g in live if g["p_k"] is not None]

    print(f"boards: {len(boards)} dates {min(boards)}..{max(boards)}  "
          f"(latest version per date)")
    print(f"rungs graded {len(graded)}  pushes {sum(g['push'] for g in graded)}"
          f"  live {len(live)}  with-kalshi {len(paired)}")
    if unmatched:
        print("unresolved:", dict(unmatched))

    print("\nHEAD TO HEAD — Brier on the same rungs, lower is better")
    print(f"  {'class':6s} {'n':>5s} {'us':>8s} {'kalshi':>8s} "
          f"{'diff':>8s} {'se(diff)':>8s}")
    for cls in ["total", "team", "f5", "k", "outs", "ALL"]:
        rows = paired if cls == "ALL" else [g for g in paired
                                            if g["cls"] == cls]
        if not rows:
            continue
        diffs = [(g["p_us"] - g["hit"]) ** 2 - (g["p_k"] - g["hit"]) ** 2
                 for g in rows]
        bu = sum((g["p_us"] - g["hit"]) ** 2 for g in rows) / len(rows)
        bk = sum((g["p_k"] - g["hit"]) ** 2 for g in rows) / len(rows)
        md = sum(diffs) / len(diffs)
        sd = (sum((x - md) ** 2 for x in diffs) / max(len(diffs) - 1, 1)) ** .5
        se = sd / len(diffs) ** .5
        print(f"  {cls:6s} {len(rows):5d} {bu:8.4f} {bk:8.4f} "
              f"{md:+8.4f} {se:8.4f}")

    print("\nBET THE GAP — our side at Kalshi's mid, 1 unit stake per rung")
    print(f"  {'gap>=':>6s} {'n':>5s} {'won':>4s} {'P&L':>8s} "
          f"{'per bet':>8s} {'se':>7s}")
    for thr in (0.03, 0.05, 0.10):
        pl, wins, n, rets = 0.0, 0, 0, []
        for g in paired:
            gap = g["p_us"] - g["p_k"]
            if abs(gap) < thr:
                continue
            over = gap > 0
            price = g["p_k"] if over else 1 - g["p_k"]
            won = g["hit"] if over else 1 - g["hit"]
            ret = (1 - price) / price if won else -1.0
            pl += ret
            wins += won
            n += 1
            rets.append(ret)
        if not n:
            continue
        m = pl / n
        sd = (sum((x - m) ** 2 for x in rets) / max(n - 1, 1)) ** .5
        print(f"  {thr:6.2f} {n:5d} {wins:4d} {pl:+8.2f} "
              f"{m:+8.3f} {sd / n ** .5:7.3f}")

    print("\nCALIBRATION — our probability vs how often over actually hit")
    print(f"  {'bucket':>10s} {'n':>5s} {'ours':>6s} {'actual':>7s}")
    for lo in [x / 10 for x in range(1, 9)]:
        rows = [g for g in live if lo <= g["p_us"] < lo + .1]
        if len(rows) < 20:
            continue
        mu = sum(g["p_us"] for g in rows) / len(rows)
        hr = sum(g["hit"] for g in rows) / len(rows)
        se = (hr * (1 - hr) / len(rows)) ** .5
        print(f"  {lo:.1f}-{lo + .1:.1f} {len(rows):5d} {mu:6.3f} "
              f"{hr:7.3f}  (se {se:.3f})")


if __name__ == "__main__":
    main(sys.argv[1:])
