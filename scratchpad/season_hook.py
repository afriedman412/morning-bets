"""Do managers pull starters the same way in 2025 and 2026?

    venv/bin/python -m scratchpad.season_hook

THE GATE BEFORE POOLING. `context/scope.py` says league-behaviour
quantities — the removal curves, advancement, inherited runners — may pool
across seasons because they describe how the game is managed rather than
who is pitching. That doubles 38,485 boundary decisions to about 85,000,
which is the main prize in loading 2025 at all.

BUT POOLING IS NOT AUTOMATIC. `advance.py`'s per-club stability gate is the
precedent: check that the two populations agree before combining them, and
treat disagreement as a finding rather than a nuisance. If managers pull
faster in 2026 than they did in 2025 — and the league is already measurably
different, home runs up 7% — then a pooled curve describes neither season
and the extra sample is bought with bias.

WHAT IS COMPARED, per season and on its own population, because the
boundary and mid-inning branches are different decisions and pooling THOSE
is the error this project has made most often:

  BOUNDARY   end of a completed inning, starter still in. Hazard by pitch
             count, which is the axis the curve is built on.
  MID-INNING per batter, inning alive. Same axis.
  SHARE      what fraction of removals happen at a boundary at all.

A difference of a percentage point on 4,000 rows is noise; the standard
error is printed next to every cell so the reader is not left estimating it.
"""
from __future__ import annotations

import glob
import os
import statistics as st
import sys
from collections import defaultdict

from src import db
from src.context import boundary

EDGES = [(0, 60), (60, 70), (70, 80), (80, 90), (90, 100), (100, 999)]


def season_of() -> dict:
    """{game_id: 'YYYY'} for every cached game."""
    with db.connect() as c:
        # `games.game_id` is 'mlb-790404'; the pbp cache filename is the
        # bare '790404'. Joining the two raw returns nothing at all, silently.
        return {str(r["game_id"]).split("-")[-1]: r["date"]
                for r in c.execute(
                    "select game_id, date from games where sport = 'mlb'")}


def collect(window=None):
    """`window` is (mm-dd, mm-dd) and is not optional in practice.

    CALENDAR MUST MATCH OR THE COMPARISON IS ABOUT APRIL, NOT ABOUT SEASONS.
    Starters are on build-up in the first month — shorter leashes at the same
    pitch count, by design — so a 2025 sample that stops in May against a
    full 2026 season measures the build-up, and it measures it as a league
    trend. The first run of this made exactly that mistake: every one of
    eleven buckets came out lower in 2026, which is what a calendar
    confound looks like when it is mistaken for a finding.
    """
    dates = season_of()
    rows = defaultdict(lambda: {"bnd": [], "mid": []})
    files = sorted(glob.glob(".cache/pbp/*.json.gz"))
    for i, f in enumerate(files):
        gid = os.path.basename(f).split(".")[0]
        date = dates.get(gid)
        if not date:
            continue
        season, md = date[:4], date[5:]
        if window and not (window[0] <= md <= window[1]):
            continue
        try:
            ds = boundary.decisions(gid)
        except Exception:
            continue
        for r in ds:
            rows[season]["bnd" if r["ends_inning"] else "mid"].append(r)
        if (i + 1) % 800 == 0:
            print(f"    {i+1}/{len(files)} games", flush=True)
    return rows


def table(rows, kind, label):
    seasons = sorted(rows)
    print(f"\n  {label} HAZARD BY PITCH COUNT")
    hdr = f"  {'bucket':<11}"
    for s in seasons:
        hdr += f"{s:>10}{'n':>8}"
    print(hdr + f"{'diff':>9}{'se':>8}")
    for lo, hi in EDGES:
        cells = {}
        for s in seasons:
            g = [r for r in rows[s][kind] if lo <= r["pitches"] < hi]
            if len(g) < 100:
                continue
            p = sum(1 for r in g if r["removed"]) / len(g)
            cells[s] = (p, len(g))
        if len(cells) < 2:
            continue
        line = f"  {f'{lo}-{hi}':<11}"
        for s in seasons:
            p, n = cells.get(s, (float('nan'), 0))
            line += f"{p:>10.4f}{n:>8,}"
        (p1, n1), (p2, n2) = cells[seasons[0]], cells[seasons[1]]
        se = (p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2) ** 0.5
        d = p2 - p1
        flag = "  <-" if se and abs(d) > 2 * se else ""
        print(line + f"{d:>+9.4f}{se:>8.4f}{flag}")


def overlap_window() -> tuple:
    """The calendar range both seasons' cached play-by-play covers."""
    dates = season_of()
    have = set()
    for f in glob.glob(".cache/pbp/*.json.gz"):
        d = dates.get(os.path.basename(f).split(".")[0])
        if d:
            have.add(d)
    by = defaultdict(list)
    for d in have:
        by[d[:4]].append(d[5:])
    if len(by) < 2:
        return None
    lo = max(min(v) for v in by.values())
    hi = min(max(v) for v in by.values())
    return (lo, hi)


def main(argv):
    win = overlap_window()
    if not win:
        print("  only one season cached — nothing to compare")
        return
    print(f"  restricted to {win[0]} .. {win[1]}, the calendar range BOTH "
          f"seasons cover")
    rows = collect(win)
    seasons = sorted(rows)
    if len(seasons) < 2:
        print(f"  only {seasons} present — nothing to compare yet")
        return
    print(f"\n  DECISIONS BY SEASON")
    print(f"  {'season':<10}{'boundary':>12}{'mid-inning':>12}"
          f"{'bnd pull%':>11}{'mid pull%':>11}{'bnd share':>11}")
    for s in seasons:
        b, m = rows[s]["bnd"], rows[s]["mid"]
        bp = st.mean(r["removed"] for r in b)
        mp = st.mean(r["removed"] for r in m)
        pulls_b = sum(1 for r in b if r["removed"])
        pulls_m = sum(1 for r in m if r["removed"])
        share = pulls_b / (pulls_b + pulls_m) if (pulls_b + pulls_m) else 0
        print(f"  {s:<10}{len(b):>12,}{len(m):>12,}{bp:>11.4f}"
              f"{mp:>11.4f}{share:>11.4f}")

    table(rows, "bnd", "BOUNDARY")
    table(rows, "mid", "MID-INNING")

    # THE CONFOUND, MEASURED ON ITS OWN. Restricting the calendar removed
    # every season difference, which means the April/August gap it was
    # hiding is the larger effect. Nothing in `sim.Hook` knows what month it
    # is, so if this is real the model prices an April start like an August
    # one. Measured WITHIN 2026 so no season effect can contaminate it.
    early = collect(("03-01", "05-15"))
    late = collect(("07-01", "09-30"))
    cur = str(max(int(x) for x in seasons))
    both = {"early Mar-May15": early.get(cur, {"bnd": [], "mid": []}),
            "late Jul-Sep": late.get(cur, {"bnd": [], "mid": []})}
    if all(v["bnd"] for v in both.values()):
        print(f"\n  WITHIN {cur}: IS THE LEASH SHORTER IN APRIL?")
        print(f"  {'window':<18}{'bucket':<10}{'pull%':>9}{'n':>8}")
        for lo, hi in EDGES:
            cells = {}
            for lbl, v in both.items():
                g = [r for r in v["bnd"] if lo <= r["pitches"] < hi]
                if len(g) >= 100:
                    cells[lbl] = (sum(1 for r in g if r["removed"]) / len(g),
                                  len(g))
            if len(cells) < 2:
                continue
            for lbl, (p, n) in cells.items():
                print(f"  {lbl:<18}{f'{lo}-{hi}':<10}{p:>9.4f}{n:>8,}")
            (p1, n1), (p2, n2) = list(cells.values())
            se = (p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2) ** 0.5
            d = p2 - p1
            print(f"  {'':<18}{'diff':<10}{d:>+9.4f}  se {se:.4f}"
                  f"{'  <-' if abs(d) > 2 * se else ''}")
    print("\n  `<-` marks a gap over two standard errors. A season effect")
    print("  there means a pooled curve describes neither season, and the")
    print("  extra sample would be bought with bias.")


if __name__ == "__main__":
    main(sys.argv[1:])
