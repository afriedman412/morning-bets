"""COUNT the two inputs item 2 wires: GIDP runner movement, sac by state.

    venv/bin/python -m scratchpad.gidp_sac_count [--backfill]

One pass over the play-by-play cache, both questions read off the same
plays (the `board.py` rule), per season so the stability gate can run.

2a — ON A GROUNDED DOUBLE PLAY, WHAT DO THE OTHER RUNNERS DO?
    The model's DP branch erases the man on first, adds two outs and
    freezes everybody else. Counted here, keyed on outs BEFORE the play:
      * P(runner on 3B scores | GIDP, 3B occupied)
      * P(runner on 2B reaches 3B | GIDP, 2B occupied)
    THE BUILT-IN CONTROL: at one out the double play makes the third out
    and the batter is retired before reaching first, so no run can score.
    The outs=1 scoring cell must come back ~0 — if it does not, the
    counting is wrong, not the baseball.

2b — SACRIFICE SHARE OF PLATE APPEARANCES BY (MEN ON, OUTS).
    `pa_from` rolls `mu.sac` first, unconditionally — bases empty or two
    out, the draw becomes a pure out with no BABIP roll. Counted here the
    way `state_seasons.py` counts every other channel: within-season cell
    rate over that season's overall rate, pooled across seasons, then the
    PA-weighted mean renormalised to exactly 1.000.

    The DENOMINATOR INCLUDES the sacrifices themselves, intentional walks
    and sac bunts — the model's `mu.sac` is a share of ALL plate
    appearances, so the state table for it must be too. (`STATE_MULT`'s
    other channels deliberately EXCLUDE sac bunts and IBB; that is
    correct for k/bb/h and would be wrong here.)
"""
from __future__ import annotations

import json
import multiprocessing as mp
import statistics as st
import sys
from collections import defaultdict
from itertools import combinations

from src import db
from src.context.sources import pbp
from scratchpad.state_table import PA_EV

CACHE = "scratchpad/gidp_sac_counts.json"

SAC_EV = {"sac_fly", "sac_fly_double_play", "sac_bunt",
          "sac_bunt_double_play"}
#: The model's PA universe: everything the state scan counts, plus the
#: events it deliberately excludes and this question must not.
DENOM_EV = PA_EV | SAC_EV | {"intent_walk"}
GIDP_EV = {"grounded_into_double_play"}
#: Generic "double_play" separately — it holds lineouts doubling a runner
#: off, which is NOT the mechanism the model's DP branch draws.
DP_EV = {"double_play"}
CELLS = [(o, u) for o in (0, 1, 2, 3) for u in (0, 1, 2)]


def _one(args):
    gid, season = args
    sac = defaultdict(lambda: defaultdict(int))
    gidp = defaultdict(int)
    try:
        for play, bases, outs, _a, _h in pbp.plays(gid):
            ev = (play.get("result") or {}).get("eventType") or ""
            if ev in DENOM_EV:
                cell = (sum(1 for b in bases if b), outs)
                for key in (cell, "ALL"):
                    sac[key]["pa"] += 1
                    sac[key]["sac"] += ev in SAC_EV
            if ev in (GIDP_EV | DP_EV) and outs < 2:
                kind = "gidp" if ev in GIDP_EV else "dp"
                moves = {}
                for r in (play.get("runners") or []):
                    mv = r.get("movement") or {}
                    if mv.get("start"):
                        moves[mv["start"]] = mv.get("end")
                if bases[2]:
                    gidp[f"{kind}_{outs}_3b"] += 1
                    gidp[f"{kind}_{outs}_3b_scored"] += \
                        moves.get("3B") == "score"
                if bases[1]:
                    gidp[f"{kind}_{outs}_2b"] += 1
                    gidp[f"{kind}_{outs}_2b_to3"] += moves.get("2B") == "3B"
    except Exception:
        return None
    return season, {str(k): dict(v) for k, v in sac.items()}, dict(gidp)


def backfill():
    with db.connect() as c:
        rows = [(r["game_id"], r["date"][:4]) for r in c.execute(
            "select game_id, date from games where sport='mlb'"
            " and status='Final' order by date")]
    rows = [(g, s) for g, s in rows if pbp.have(g)]
    print(f"  {len(rows):,} cached games", flush=True)
    with mp.get_context("fork").Pool(8) as p:
        got = [g for g in p.map(_one, rows, chunksize=16) if g]
    agg: dict = {}
    for season, sac, gidp in got:
        a = agg.setdefault(season, {"sac": defaultdict(lambda:
                                    defaultdict(int)),
                                    "gidp": defaultdict(int)})
        for cell, c in sac.items():
            for k, v in c.items():
                a["sac"][cell][k] += v
        for k, v in gidp.items():
            a["gidp"][k] += v
    out = {s: {"sac": {c: dict(v) for c, v in a["sac"].items()},
               "gidp": dict(a["gidp"])} for s, a in agg.items()}
    json.dump(out, open(CACHE, "w"))
    print(f"  wrote {CACHE}")
    return out


def report(agg):
    seasons = sorted(agg)

    print("\n  2a — GIDP RUNNER MOVEMENT, keyed on outs BEFORE the play")
    print(f"  {'cell':<26}" + "".join(f"{s:>10}" for s in seasons)
          + f"{'pooled':>10}{'se':>8}")
    for kind in ("gidp", "dp"):
        for outs in (0, 1):
            for tag, num in (("3b_scored", "3b"), ("2b_to3", "2b")):
                cols, tot_n, tot_k = [], 0, 0
                for s in seasons:
                    g = agg[s]["gidp"]
                    n = g.get(f"{kind}_{outs}_{num}", 0)
                    k = g.get(f"{kind}_{outs}_{tag}", 0)
                    cols.append(k / n if n else None)
                    tot_n += n
                    tot_k += k
                if not tot_n:
                    continue
                p = tot_k / tot_n
                se = (p * (1 - p) / tot_n) ** 0.5
                lbl = f"{kind} outs={outs} {tag}"
                print(f"  {lbl:<26}" + "".join(
                    f"{c:>10.3f}" if c is not None else f"{'-':>10}"
                    for c in cols) + f"{p:>10.4f}{se:>8.4f}"
                    + f"   n={tot_n:,}")

    print("\n  2b — SAC SHARE OF PA BY (men on, outs), multiplier vs the")
    print("  season's own overall rate, pooled across seasons\n")
    print(f"  {'cell':<10}{'pa':>10}{'sac rate':>10}{'mult':>8}{'se':>8}"
          + "".join(f"{s:>8}" for s in seasons))
    pooled = {}
    weights = {}
    for cell in CELLS:
        key = str(cell)
        muls, ns = [], []
        for s in seasons:
            c = agg[s]["sac"].get(key) or {}
            allc = agg[s]["sac"]["ALL"]
            if not c.get("pa"):
                continue
            overall = allc["sac"] / allc["pa"]
            muls.append((c["sac"] / c["pa"]) / overall if overall else 0)
            ns.append(c["pa"])
        if not muls:
            continue
        n = sum(ns)
        m = sum(mu * w for mu, w in zip(muls, ns)) / n
        tot_sac = sum(agg[s]["sac"].get(key, {}).get("sac", 0)
                      for s in seasons)
        rate = tot_sac / n
        se_rate = (rate * (1 - rate) / n) ** 0.5 if 0 < rate < 1 else 0
        overall_pool = (sum(agg[s]["sac"]["ALL"]["sac"] for s in seasons)
                        / sum(agg[s]["sac"]["ALL"]["pa"] for s in seasons))
        se_mult = se_rate / overall_pool if overall_pool else 0
        pooled[cell] = m
        weights[cell] = n
        print(f"  {key:<10}{n:>10,}{rate:>10.4f}{m:>8.3f}{se_mult:>8.3f}"
              + "".join(f"{mu:>8.3f}" for mu in muls))

    # Stability gate, the state_seasons way: correlation of the 12 cell
    # multipliers between seasons, averaged over pairs.
    per_season = {}
    for s in seasons:
        v = []
        for cell in CELLS:
            c = agg[s]["sac"].get(str(cell)) or {}
            allc = agg[s]["sac"]["ALL"]
            overall = allc["sac"] / allc["pa"]
            v.append((c.get("sac", 0) / c["pa"]) / overall
                     if c.get("pa") else None)
        per_season[s] = v
    cors = []
    for a, b in combinations(seasons, 2):
        xs = [(x, y) for x, y in zip(per_season[a], per_season[b])
              if x is not None and y is not None]
        if len(xs) > 2:
            xa, ya = [x for x, _ in xs], [y for _, y in xs]
            cors.append(st.correlation(xa, ya))
    print(f"\n  stability gate: mean between-season correlation "
          f"{st.mean(cors):.3f} over {len(cors)} pairs "
          f"(state gate passed k_pct at 0.859)")

    # Renormalise so the PA-weighted mean is exactly 1.000 — the same rule
    # as TTO_MULT and the rest of STATE_MULT.
    wtot = sum(weights.values())
    mean = sum(pooled[c] * weights[c] for c in pooled) / wtot
    print(f"\n  PA-weighted mean before renorm: {mean:.4f}")
    print("\n  sac_pct COLUMN FOR STATE_MULT (renormalised):")
    for cell in CELLS:
        if cell in pooled:
            print(f'    ({cell[0]}, {cell[1]}): {pooled[cell] / mean:.4f},')


def main(argv):
    if "--backfill" in argv:
        agg = backfill()
    else:
        agg = json.load(open(CACHE))
        agg = {s: {"sac": v["sac"], "gidp": v["gidp"]}
               for s, v in agg.items()}
    report(agg)


if __name__ == "__main__":
    main(sys.argv[1:])
