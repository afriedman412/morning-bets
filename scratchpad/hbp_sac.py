"""HIT-BY-PITCH and SACRIFICES are imported league constants. Count them.

    venv/bin/python -m scratchpad.hbp_sac [workers]

`sim.pa_outcome` draws both off the top of every plate appearance from flat
league rates — `HBP_RATE` and `SAC_RATE` — for every pitcher, every hitter,
every night. Neither is a league constant in reality: some pitchers hit
fifteen batters a year and some hit two, and some hitters wear the ball for
a living. They are also KNOWABLE, which is the whole argument — this is a
measured quantity replacing an imported guess, not a new mechanism.

IT MATTERS MORE THAN THE RATE SUGGESTS. A hit-by-pitch is a BASERUNNER, and
this model is currently 6% short on runs with the right number of hits,
strikeouts and home runs. The notes also record HBP running 11% light, which
is a level error a counted version fixes for free.

WHAT IS MEASURED HERE, in the order that decides whether to build anything:

  1. SPREAD      how far apart are pitchers and hitters, really.
  2. PERSISTENCE split-half within the data, Spearman-Brown corrected. A
                 spread that does not repeat is noise and shrinks to the
                 league mean anyway, which is what ships today.
  3. LEVERAGE    the reliability-adjusted spread converted to RUNS. Under
                 ~0.05 runs it cannot matter however real it is.

Steps 2 and 3 are what stop this becoming another imported multiplier. The
dead list is mostly features that passed step 1 alone.
"""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

from src import db
from src.context import sim
from src.context.sources import pbp

_SAC = ("sac_bunt", "sac_fly", "sac_fly_double_play",
        "sac_bunt_double_play")


def scan_role(short: str):
    """[pa, hbp, sac] by ROLE for one game — the first pitcher a side uses
    is its starter, everyone after is relief.

    Split out because the shipped `HBP_RATE` was measured on STARTERS from
    boxscores while the simulator draws it for every arm in the game, and a
    starter/reliever gap would mean the constant is right for the population
    it was measured on and wrong for the one it is used on.
    """
    try:
        d = pbp.fetch(short)
    except Exception:
        return None
    if not d:
        return None
    first, out = {}, defaultdict(lambda: [0, 0, 0])
    for p in (d.get("allPlays") or []):
        mu = p.get("matchup") or {}
        res = p.get("result") or {}
        ab = p.get("about") or {}
        pid = (mu.get("pitcher") or {}).get("id")
        if not pid:
            continue
        side = "home" if ab.get("isTopInning") else "away"
        first.setdefault(side, pid)
        role = "SP" if first[side] == pid else "RP"
        ev = res.get("eventType") or ""
        c = out[role]
        c[0] += 1
        c[1] += ev == "hit_by_pitch"
        c[2] += ev in _SAC
    return dict(out)


def by_season(workers: int = 8):
    with db.connect() as c:
        games = {r["game_id"]: r["date"] for r in
                 c.execute("select game_id, date from games"
                           " where sport = 'mlb'")}
    todo = sorted((g, d) for g, d in games.items()
                  if pbp.have(g.split("-")[-1]))
    acc = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    with ProcessPoolExecutor(max_workers=workers) as ex:
        res = ex.map(scan_role, [g.split("-")[-1] for g, _ in todo],
                     chunksize=32)
        for (g, date), got in zip(todo, res):
            if not got:
                continue
            for role, v in got.items():
                for i in range(3):
                    acc[date[:4]][role][i] += v[i]
    print(f"  {'season':<8}{'role':<6}{'PA':>10}{'HBP/PA':>10}{'SAC/PA':>10}")
    for y in sorted(acc):
        for role in ("SP", "RP"):
            v = acc[y][role]
            if v[0]:
                print(f"  {y:<8}{role:<6}{v[0]:>10,}{v[1] / v[0]:>10.5f}"
                      f"{v[2] / v[0]:>10.5f}")
        b = [acc[y]["SP"][i] + acc[y]["RP"][i] for i in range(3)]
        print(f"  {y:<8}{'both':<6}{b[0]:>10,}{b[1] / b[0]:>10.5f}"
              f"{b[2] / b[0]:>10.5f}")
    return acc


def scan(short: str):
    """(pitcher id, batter id) -> [pa, hbp, sac], plus names, one game."""
    try:
        d = pbp.fetch(short)
    except Exception:
        return None
    if not d:
        return None
    pit = defaultdict(lambda: [0, 0, 0])
    bat = defaultdict(lambda: [0, 0, 0])
    names = {}
    #: Odd/even PLATE APPEARANCE index, for the split-half. Splitting by
    #: game would put a pitcher's whole start in one half and measure the
    #: start, not the pitcher.
    half = defaultdict(lambda: [[0, 0], [0, 0]])
    i = 0
    for p in (d.get("allPlays") or []):
        mu = p.get("matchup") or {}
        res = p.get("result") or {}
        pid = (mu.get("pitcher") or {}).get("id")
        bid = (mu.get("batter") or {}).get("id")
        if not pid or not bid:
            continue
        names[pid] = (mu.get("pitcher") or {}).get("fullName")
        names[bid] = (mu.get("batter") or {}).get("fullName")
        ev = res.get("eventType") or ""
        hbp = 1 if ev == "hit_by_pitch" else 0
        sac = 1 if ev in _SAC else 0
        for tgt, key in ((pit, pid), (bat, bid)):
            c = tgt[key]
            c[0] += 1
            c[1] += hbp
            c[2] += sac
        h = half[pid][i % 2]
        h[0] += 1
        h[1] += hbp
        i += 1
    return ({str(k): v for k, v in pit.items()},
            {str(k): v for k, v in bat.items()},
            {str(k): v for k, v in names.items() if v},
            {str(k): v for k, v in half.items()})


def corr(xs, ys):
    n = len(xs)
    if n < 10:
        return 0.0
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if not sx or not sy:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (n * sx * sy)


def main(argv):
    if argv and argv[0] == "--by-season":
        by_season(int(argv[1]) if len(argv) > 1 else 8)
        return
    workers = int(argv[0]) if argv else 8
    with db.connect() as c:
        games = [r["game_id"] for r in
                 c.execute("select game_id from games where sport = 'mlb'")]
    todo = sorted(g for g in games if pbp.have(g.split("-")[-1]))
    print(f"  scanning {len(todo):,} games on {workers} workers ...",
          flush=True)
    pit = defaultdict(lambda: [0, 0, 0])
    bat = defaultdict(lambda: [0, 0, 0])
    half = defaultdict(lambda: [[0, 0], [0, 0]])
    names = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for got in ex.map(scan, [g.split("-")[-1] for g in todo],
                          chunksize=32):
            if not got:
                continue
            p_, b_, n_, h_ = got
            for src, dst in ((p_, pit), (b_, bat)):
                for k, v in src.items():
                    c = dst[k]
                    for i in range(3):
                        c[i] += v[i]
            for k, v in h_.items():
                for s in (0, 1):
                    half[k][s][0] += v[s][0]
                    half[k][s][1] += v[s][1]
            names.update(n_)

    lg_pa = sum(v[0] for v in pit.values())
    lg_hbp = sum(v[1] for v in pit.values())
    lg_sac = sum(v[2] for v in pit.values())
    print(f"\n  {lg_pa:,} plate appearances")
    print(f"  HBP {lg_hbp:,} = {lg_hbp / lg_pa:.5f} per PA"
          f"   (shipped HBP_RATE {sim.HBP_RATE:.5f},"
          f" {100 * (sim.HBP_RATE / (lg_hbp / lg_pa) - 1):+.1f}%)")
    print(f"  SAC {lg_sac:,} = {lg_sac / lg_pa:.5f} per PA"
          f"   (shipped SAC_RATE {sim.SAC_RATE:.5f},"
          f" {100 * (sim.SAC_RATE / (lg_sac / lg_pa) - 1):+.1f}%)")

    # 1. SPREAD
    print(f"\n  {'population':<12}{'n':>6}{'min PA':>8}{'mean':>9}{'sd':>9}"
          f"{'p10':>9}{'p90':>9}")
    for label, tbl, idx, lo in (("pitcher HBP", pit, 1, 300),
                                ("batter HBP", bat, 1, 300),
                                ("pitcher SAC", pit, 2, 300),
                                ("batter SAC", bat, 2, 300)):
        v = sorted(c[idx] / c[0] for c in tbl.values() if c[0] >= lo)
        if len(v) < 20:
            continue
        print(f"  {label:<12}{len(v):>6}{lo:>8}{st.mean(v):>9.5f}"
              f"{st.pstdev(v):>9.5f}{v[len(v) // 10]:>9.5f}"
              f"{v[-len(v) // 10]:>9.5f}")

    # 2. PERSISTENCE — odd vs even plate appearances, Spearman-Brown to full
    xs, ys = [], []
    for k, (a, b) in half.items():
        if min(a[0], b[0]) >= 250:
            xs.append(a[1] / a[0])
            ys.append(b[1] / b[0])
    r = corr(xs, ys)
    sb = 2 * r / (1 + r) if r > -1 else 0.0
    print(f"\n  pitcher HBP split-half over {len(xs)} arms: r {r:+.3f},"
          f" full-length reliability {sb:+.3f}")

    # 3. LEVERAGE — the reliability-adjusted spread, in runs.
    v = [c[1] / c[0] for c in pit.values() if c[0] >= 300]
    usable = st.pstdev(v) * max(sb, 0.0)
    print(f"\n  usable pitcher spread {usable:.5f} per PA"
          f"  =  {usable * 24:.4f} extra baserunners per start (1 sd)")
    print(f"  at ~0.30 runs per baserunner that is"
          f" {usable * 24 * 0.30:.4f} RUNS of separation.")
    print("\n  Under ~0.05 runs it cannot matter however real it is —")
    print("  but note this is a MEASURED quantity replacing an imported")
    print("  one, so the LEVEL correction stands on its own regardless of")
    print("  whether the per-pitcher spread clears the leverage floor.")


if __name__ == "__main__":
    main(sys.argv[1:])
