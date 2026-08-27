"""WILD PITCHES and PASSED BALLS — two populations, one flat constant.

    venv/bin/python -m scratchpad.wp_pb [workers]

`sim.WP_PB_RATE` is a single number applied to every pitcher and every
catcher. The leverage screen lists it with an ASSUMED 0.20 spread and
reliability `None`, meaning nobody has ever checked whether it varies or
whether the variation repeats.

WHY THIS IS THE BEST-AIMED THING ON THE LIST. The model has the right number
of hits, strikeouts and home runs and is 6% short on RUNS. A wild pitch or a
passed ball advances a runner WITHOUT A HIT — it is exactly the mechanism
that turns "right baserunners" into "more runs", and it is the only
candidate discussed that points straight at the open gap rather than at a
rate we already get right.

TWO POPULATIONS, AND POOLING THEM IS THE DEFAULT MISTAKE. A wild pitch is
charged to the PITCHER and a passed ball to the CATCHER. They have identical
run consequences and completely different causes — a pitcher who bounces
his breaking ball versus a catcher who cannot block. Fitting one rate over
both is the same error that just turned up in hit-by-pitch, where a starter
constant was applied to relievers.

AND THE CATCHER NULL DOES NOT COVER THIS. `catcher_framing` was measured on
STRIKEOUTS AND WALKS, which is what framing moves. BLOCKING is a different
skill and has never been screened here at all.

Same three steps as `hbp_sac.py`, in the order that decides whether to build:
SPREAD, then PERSISTENCE split-half with Spearman-Brown, then LEVERAGE in
runs. Under ~0.05 runs it cannot matter however real it is.
"""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

from src import db
from src.context import sim
from src.context.sources import pbp


def scan(short: str):
    """Per pitcher and per catcher: [pitches-ish, wp, pb], one game.

    The denominator is PLATE APPEARANCES WITH A RUNNER ON, because a wild
    pitch with the bases empty advances nobody and cannot reach a run. Using
    all plate appearances would dilute both rates by the ~57% of the time
    the bases are empty and make every arm look alike.
    """
    try:
        d = pbp.fetch(short)
    except Exception:
        return None
    if not d:
        return None
    pit = defaultdict(lambda: [0, 0, 0])
    cat = defaultdict(lambda: [0, 0, 0])
    names = {}
    half = defaultdict(lambda: [[0, 0], [0, 0]])
    i = 0
    # `pbp.plays` RECONSTRUCTS the base state BEFORE each play. The matchup
    # block only carries `postOnFirst`/`postOnSecond`/`postOnThird`, and
    # "post" means AFTER — reading those as the pre-play state counts every
    # plate appearance that ENDED with a runner on rather than every one
    # that STARTED with one, which is a different and much larger set. That
    # is the same misreading as `count.outs`, which mislabelled 27,401
    # inning endings earlier in this project.
    for p, bases, _outs, _a, _h in pbp.plays(short, d):
        mu = p.get("matchup") or {}
        pid = (mu.get("pitcher") or {}).get("id")
        if not pid:
            continue
        names[pid] = (mu.get("pitcher") or {}).get("fullName")
        on = any(bases)
        wp = pb = 0
        for ev in (p.get("playEvents") or []):
            det = (ev.get("details") or {})
            t = (det.get("eventType") or "")
            if t == "wild_pitch":
                wp += 1
            elif t == "passed_ball":
                pb += 1
        c = pit[pid]
        c[0] += 1 if on else 0
        c[1] += wp
        c[2] += pb
        if on:
            h = half[pid][i % 2]
            h[0] += 1
            h[1] += wp
            i += 1
    return ({str(k): v for k, v in pit.items()},
            {str(k): v for k, v in cat.items()},
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
    workers = int(argv[0]) if argv else 8
    with db.connect() as c:
        games = [r["game_id"] for r in
                 c.execute("select game_id from games where sport = 'mlb'")]
    todo = sorted(g for g in games if pbp.have(g.split("-")[-1]))
    print(f"  scanning {len(todo):,} games on {workers} workers ...",
          flush=True)
    pit = defaultdict(lambda: [0, 0, 0])
    half = defaultdict(lambda: [[0, 0], [0, 0]])
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for got in ex.map(scan, [g.split("-")[-1] for g in todo],
                          chunksize=32):
            if not got:
                continue
            p_, _c, _n, h_ = got
            for k, v in p_.items():
                c = pit[k]
                for i in range(3):
                    c[i] += v[i]
            for k, v in h_.items():
                for s in (0, 1):
                    half[k][s][0] += v[s][0]
                    half[k][s][1] += v[s][1]

    on = sum(v[0] for v in pit.values())
    wp = sum(v[1] for v in pit.values())
    pb = sum(v[2] for v in pit.values())
    print(f"\n  {on:,} plate appearances with a runner on")
    print(f"  wild pitches {wp:,} = {wp / on:.5f} per such PA")
    print(f"  passed balls {pb:,} = {pb / on:.5f} per such PA")
    print(f"  combined     {(wp + pb) / on:.5f}"
          f"   (shipped WP_PB_RATE {sim.WP_PB_RATE:.5f},"
          f" {100 * (sim.WP_PB_RATE / ((wp + pb) / on) - 1):+.1f}%)")
    print(f"  passed balls are {100 * pb / (wp + pb):.1f}% of the total —"
          f" the CATCHER's share")

    v = sorted(c[1] / c[0] for c in pit.values() if c[0] >= 150)
    if len(v) >= 20:
        print(f"\n  pitcher wild-pitch rate over {len(v)} arms with 150+:")
        print(f"    mean {st.mean(v):.5f}  sd {st.pstdev(v):.5f}"
              f"  p10 {v[len(v) // 10]:.5f}  p90 {v[-len(v) // 10]:.5f}")

    xs, ys = [], []
    for k, (a, b) in half.items():
        if min(a[0], b[0]) >= 120:
            xs.append(a[1] / a[0])
            ys.append(b[1] / b[0])
    r = corr(xs, ys)
    sb = 2 * r / (1 + r) if r > -1 else 0.0
    print(f"\n  split-half over {len(xs)} arms: r {r:+.3f},"
          f" full-length reliability {sb:+.3f}")

    usable = st.pstdev(v) * max(sb, 0.0) if v else 0.0
    # A start faces ~24 batters and roughly 43% of those come with a runner
    # on, so ~10 exposed plate appearances. A wild pitch advances a runner
    # about one base, worth ~0.25 runs at a typical base-out state.
    print(f"\n  usable spread {usable:.5f} per exposed PA"
          f"  = {usable * 10:.4f} extra advances per start (1 sd)")
    print(f"  at ~0.25 runs an advance that is"
          f" {usable * 10 * 0.25:.4f} RUNS of separation.")
    print("\n  The LEVEL correction stands on its own — it is measured")
    print("  replacing imported. The per-arm spread has to clear ~0.05")
    print("  runs to be worth wiring, and the CATCHER half is untouched")
    print("  here because passed balls need a catcher id per plate")
    print("  appearance, which this scan does not yet carry.")


if __name__ == "__main__":
    main(sys.argv[1:])
