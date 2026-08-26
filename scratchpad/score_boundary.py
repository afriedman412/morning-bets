"""Score the three boundary curves on the SAME simulated starts.

    venv/bin/python -m scratchpad.score_boundary [n_sims] [max_games]

WHY THIS EXISTS SEPARATELY FROM THE FIT. `scratchpad/fit_boundary_nl.py`
shows the knee reproduces the per-decision hazard at every bucket. That is
NOT the same claim as reproducing the outs distribution: the boundary and
mid-inning curves compete for the same exits, so a boundary curve that stops
over-pulling hands its exits to the other one (day-nine trap, recorded in
RESUME). The only way to know what a shape change does to the quantity we
price is to simulate it.

WHAT IS SCORED, in the order it should be read:

  1. P(over) AT THE LINES BOOKS HANG, split into the band that carries the
     volume (14.5-17.5, 91.2% of settled outs contracts) and the wide band.
     This is the standard from day nine and it is what decided the linear
     curve's ship.
  2. Discrete CRPS over the full support — shape, no book's lines involved.
  3. Mean, SD and boundary share, reported and NOT optimised. The mean is a
     known open defect (53% traffic deficit) and a curve that fixes it by
     accident should be visible as such rather than credited.

SAME SEEDS ACROSS VARIANTS. Every hook sees the identical game, lineup and
draw sequence, so the comparison is paired and a difference is the curve.

THE LEGACY-vs-LINEAR RANKING IS NOT STABLE AND THAT IS A FINDING, not a bug
in this script. Three configurations, three answers on band RMS:

    config                                  legacy   linear
    in-sample, season rates, leash on       0.0546   0.0342   (the ship)
    holdout, rates frozen, leash on         0.0374   0.0533
    holdout, rates frozen, leash off        0.0681   0.0252

So this morning's ship of the linear curve rests on a comparison that flips
when the population changes. I first attributed the flip to the leash —
the offsets were fitted in 068c937, BEFORE 6ab6737 shipped the linear curve,
so they are residuals against LEGACY — and the transcript refutes that on
its own: the run behind the ship had the leash ON too (`calibrate.replay`
defaults `apply_leash=True`). Population and rate-freezing move it as well,
and none of the three has been isolated. DO NOT quote a legacy-vs-linear
number without naming which row it came from.

THE KNEE-vs-LINEAR RANKING IS STABLE across every configuration tried, which
is why the knee decision does not depend on resolving the above.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import multiprocessing as mp
import os
import random
import statistics as st
import sys
from collections import Counter

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src

MAX_OUTS = 28

#: Where books hang outs. `BAND` is the 91.2% that actually gets bet.
LINES = (12.5, 14.5, 15.5, 16.5, 17.5, 18.5, 20.5)
BAND = (14.5, 15.5, 16.5, 17.5)

#: Rates and leash frozen before this, so a shape change is scored on starts
#: the inputs never saw.
HOLDOUT = "2026-07-01"

DUMP = "scratchpad/bnd_curves.json"

VARIANTS = {
    "legacy": sim.LEGACY_BOUNDARY,
    "linear": sim.LINEAR_BOUNDARY,
    "knee": {},                       # shipped defaults
}

_CASES: dict = {}
_PENS: dict = {}
_LG = None
_SIMS = 40


def crps(dist: Counter, n: int, actual: int) -> float:
    tot, c = 0.0, 0.0
    for v in range(MAX_OUTS + 1):
        c += dist.get(v, 0) / n
        tot += (c - (1.0 if v >= actual else 0.0)) ** 2
    return tot


def _one(args):
    """One game, every variant, identical seeds. -> [(variant, row), ...]"""
    i, gid = args
    v = _CASES[gid]
    home = next(x for x in v if x[0]["is_home"])
    away = next(x for x in v if not x[0]["is_home"])
    an = cal.adjust_lineup(away[2], False)
    hn = cal.adjust_lineup(home[2], True)
    out = []
    for name, fields in VARIANTS.items():
        hook = sim.Hook(**fields) if fields else sim.Hook()
        da, dh = Counter(), Counter()
        for draw in range(_SIMS):
            rng = random.Random(7 + i * 100003 + draw)
            A = game.build_side(away[1],
                                _PENS.get((away[0]["team"] or "").upper(), []),
                                hn, hook, rng, team=away[0]["team"])
            H = game.build_side(home[1],
                                _PENS.get((home[0]["team"] or "").upper(), []),
                                an, hook, rng, team=home[0]["team"])
            r = game.simulate_game(A, H, _LG, rng)
            da[r.away_sp.outs] += 1
            dh[r.home_sp.outs] += 1
        for act, d in ((away[0], da), (home[0], dh)):
            if act.get("o") is None:
                continue
            out.append((name, {"actual": act["o"], "dist": d}))
    return out


def main(argv):
    global _CASES, _PENS, _LG, _SIMS
    pos = [a for a in argv if not a.startswith("-")]
    _SIMS = int(pos[0]) if pos else 40
    cap = int(pos[1]) if len(pos) > 1 else None
    if "--no-leash" in argv:
        # Set BEFORE the pool forks. A spawned child would re-import at the
        # default and silently turn it back on.
        sim.USE_LEASH = False
        sim.USE_OFFSETS = False
        sim.reload_offsets()
        globals()["DUMP"] = "scratchpad/bnd_curves_noleash.json"
        print("  LEASH OFF — no curve gets offsets fitted against it")

    _LG = sim.league()
    _PENS = rate_src.bullpens(_LG)
    by: dict = {}
    for s, p, l in cal.build_cases(since=HOLDOUT, rates_before=HOLDOUT):
        by.setdefault(s["game_id"], []).append((s, p, l))
    by = {g: v for g, v in by.items()
          if len(v) == 2 and sum(bool(x[0]["is_home"]) for x in v) == 1}
    gids = list(by)[:cap] if cap else list(by)
    _CASES = {g: by[g] for g in gids}
    print(f"  {len(gids)} games / {len(gids)*2} starts x {_SIMS} draws "
          f"x {len(VARIANTS)} hooks, holdout {HOLDOUT}", flush=True)

    rows: dict = {k: [] for k in VARIANTS}
    workers = max(1, (os.cpu_count() or 4) - 1)
    with cf.ProcessPoolExecutor(max_workers=workers,
                                mp_context=mp.get_context("fork")) as pool:
        for n, res in enumerate(pool.map(_one, list(enumerate(gids))), 1):
            for name, row in res:
                rows[name].append(row)
            if n % 100 == 0:
                print(f"    {n}/{len(gids)} games", flush=True)

    real = [r["actual"] for r in rows["knee"]]
    n = len(real)
    # Seven minutes of simulation. Every later question about these three
    # curves reads this instead of re-running.
    with open(DUMP, "w") as fh:
        json.dump({k: [{"actual": r["actual"],
                        "dist": {str(o): c for o, c in r["dist"].items()}}
                       for r in v] for k, v in rows.items()}, fh)
    print(f"\n  {n:,} starts scored   -> {DUMP}\n")

    print("  P(over) AT THE LINES — sim rate against what happened")
    hdr = f"  {'line':<8}{'actual':>9}"
    for k in VARIANTS:
        hdr += f"{k:>9}"
    print(hdr + "     " + "  ".join(f"err {k}" for k in VARIANTS))
    err = {k: {} for k in VARIANTS}
    for ln in LINES:
        act = sum(1 for v in real if v > ln) / n
        line = f"  {ln:<8}{act:>9.3f}"
        tail = []
        for k in VARIANTS:
            p = st.mean(sum(c for o, c in r["dist"].items() if o > ln)
                        / sum(r["dist"].values()) for r in rows[k])
            err[k][ln] = p - act
            line += f"{p:>9.3f}"
            tail.append(f"{p - act:>+8.3f}")
        print(line + "     " + "  ".join(tail))

    def rms(k, lines):
        return (st.mean(err[k][ln] ** 2 for ln in lines)) ** 0.5

    # BRIER PER LINE — the settlement-level score, and the one the table
    # above cannot give. RMS of aggregate P(over) is a pure BIAS measure: a
    # model that says 0.55 for every start scores perfectly on it while
    # discriminating nothing. Brier carries reliability AND resolution, so a
    # curve that earns its per-decision accuracy back as between-start
    # separation shows up here and nowhere else.
    #
    # DO NOT RE-CENTRE THIS BY SHIFTING LINES. Tried, and it is invalid:
    # outs is lattice-valued with a large atom at every multiple of three,
    # so shifting the 14.5 line by a 0.63-out mean error carries it across
    # the 15-out atom and every variant's error triples. Any level
    # correction has to move the distribution, not the line.
    print("\n  BRIER PER LINE, paired on the same starts (lower is better)")
    print(f"  {'line':<8}{'base':>9}" + "".join(f"{k:>9}" for k in VARIANTS))
    briers = {k: {} for k in VARIANTS}
    for ln in LINES:
        act = sum(1 for v in real if v > ln) / n
        line = f"  {ln:<8}{act * (1 - act):>9.4f}"
        for k in VARIANTS:
            b = st.mean(
                (sum(c for o, c in r["dist"].items() if o > ln)
                 / sum(r["dist"].values()) - (1.0 if r["actual"] > ln else 0.0))
                ** 2 for r in rows[k])
            briers[k][ln] = b
            line += f"{b:>9.4f}"
        print(line)
    print(f"  {'mean 14.5-17.5':<17}"
          + "".join(f"{st.mean(briers[k][ln] for ln in BAND):>10.4f}"
                    for k in VARIANTS))
    base = st.mean(
        (lambda a: a * (1 - a))(sum(1 for v in real if v > ln) / n)
        for ln in BAND)
    print(f"  {'no-skill base':<17}{base:>10.4f}   <- beat this or the "
          f"per-start numbers are worse than a constant")

    print(f"\n  {'':<26}" + "".join(f"{k:>10}" for k in VARIANTS))
    print(f"  {'RMS err, 14.5-17.5':<26}"
          + "".join(f"{rms(k, BAND):>10.4f}" for k in VARIANTS)
          + "   <- 91.2% of the board")
    print(f"  {'RMS err, 12.5-20.5':<26}"
          + "".join(f"{rms(k, LINES):>10.4f}" for k in VARIANTS))

    print(f"\n  {'':<26}" + "".join(f"{k:>10}" for k in VARIANTS)
          + f"{'ACTUAL':>10}")
    stats = {}
    for k in VARIANTS:
        means = [sum(o * c for o, c in r["dist"].items())
                 / sum(r["dist"].values()) for r in rows[k]]
        allv = [o for r in rows[k] for o, c in r["dist"].items()
                for _ in range(c)]
        stats[k] = {
            "crps": st.mean(crps(r["dist"], sum(r["dist"].values()),
                                 r["actual"]) for r in rows[k]),
            "mean": st.mean(means),
            "sd": st.pstdev(allv),
            "bnd": cal._boundary(allv),
        }
    for label, key, fmt, actual in (
            ("discrete CRPS", "crps", "{:>10.4f}", None),
            ("mean outs", "mean", "{:>10.2f}", st.mean(real)),
            ("SD outs", "sd", "{:>10.2f}", st.pstdev(real)),
            ("boundary share", "bnd", "{:>10.3f}", cal._boundary(real))):
        row = f"  {label:<26}" + "".join(fmt.format(stats[k][key])
                                         for k in VARIANTS)
        if actual is not None:
            row += fmt.format(actual)
        print(row)

    print("\n  CRPS is the shape score and lower is better. The mean is a")
    print("  known open defect and is NOT what this ships on.")


if __name__ == "__main__":
    main(sys.argv[1:])
