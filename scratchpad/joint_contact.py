"""Do the two surviving contact hints ADD, or are they the same hint twice?

    venv/bin/python -m scratchpad.joint_contact

THE QUESTION. Handedness and arsenal both came back flat on strikeouts and
both came back about +2.5 sigma on contact, worth 1.9 and 1.6 cents against
a 3.7-cent bar. Stacking them looks like it clears the bar. It does not, for
two separate reasons, and only the second one needs measuring.

FIRST, CENTS DO NOT ADD — VARIANCE DOES. Two independent predictors combine
in quadrature, so 1.9 and 1.6 make 2.5, not 3.5. That is arithmetic and it
holds however unrelated the features are. It also sets the scale of the
whole stack-small-features plan: at 1.5 cents apiece you need SIX
independent features to reach 3.7, not two.

SECOND, THEY MAY NOT BE INDEPENDENT, and that is what this measures. Both
are ultimately a guess about how hard this lineup squares this pitcher up,
so any shared variance pushes the pair BELOW the quadrature ceiling. The
joint number is the one that decides it:

    R^2 = (r1^2 + r2^2 - 2 r1 r2 r12) / (1 - r12^2)

WHY THIS IS THE RIGHT TEST AND A THIRD SCREEN WOULD NOT BE. Running the two
features separately and adding the answers is exactly the univariate mistake
`allelse.py` was written to fix: a shared effect gets handed in full to
whichever feature is asked first, and then counted again when the second is
asked. Here the two are put in the same regression and made to compete.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict

from src.context.sources import rates as rate_src
from scratchpad.arsenal_screen import _one
from scratchpad.platoon_bat import CHANNELS, arm, load


def corr(xs, ys):
    n = len(xs)
    if n < 30:
        return 0.0, 0.0
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if not sx or not sy:
        return 0.0, 0.0
    r = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (n * sx * sy)
    return r, r * (n - 2) ** 0.5 / max((1 - r * r) ** 0.5, 1e-9)


def cents(r: float) -> float:
    """A correlation, in cents at the money.

    `removable` is |r| x sd(residual) and the density at the line is
    0.3989 / sd, so the standard deviation cancels and the conversion is a
    constant. That is why the bar can be stated once for every channel.
    """
    return abs(r) * 39.89


def arsenal_by_start(rows):
    """Per start, the mean contact and K multiplier off the pitcher's mix."""
    from datetime import date as _d
    from src import panel
    from src.context import calibrate as cal
    import concurrent.futures as cf
    import multiprocessing as mp
    import os

    lineups = cal.opposing_lineups()
    try:
        ars = panel._pitcher_arsenal_blob(
            panel.savant_pitcher_arsenal(2026, _d.today().isoformat())) or {}
    except Exception as e:
        print(f"  arsenal unavailable: {type(e).__name__} {e}")
        return {}
    # Savant keys names LOWERCASE, and matching without folding case returns
    # zero rows while looking exactly like a null result.
    import scratchpad.arsenal_screen as scr
    scr._ARS = ars
    jobs = []
    for r in rows:
        mix = ars.get((r["player"] or "").lower().strip())
        names = lineups.get((r["game_id"], r["team"]))
        if mix and names:
            jobs.append((r["game_id"], r["player"], mix, list(names)))
    workers = max(1, (os.cpu_count() or 4) - 1)
    print(f"  {len(jobs):,} starts to project over {workers} workers",
          flush=True)
    out = {}
    # Fork, never spawn: a spawned child re-imports at default globals and
    # rebuilds the Savant caches per worker.
    with cf.ProcessPoolExecutor(max_workers=workers,
                                mp_context=mp.get_context("fork")) as pool:
        for res in pool.map(_one, jobs, chunksize=16):
            if res:
                out[res[0]] = res[1]
    return out


def main(argv):
    rows = [r for r in json.load(open("scratchpad/ceiling_rows.json"))
            if not r.get("_team_row")]
    ars = arsenal_by_start(rows)
    print(f"  {len(ars):,} starts with an arsenal projection")

    by_year, starts = load()
    ins = defaultdict(lambda: [0, 0, 0, 0, 0])
    for k, v in by_year.get(2026, {}).items():
        c = ins[k]
        for i in range(5):
            c[i] += v[i]

    # Handedness on the contact channel, keyed by start so the two features
    # can be joined rather than zipped.
    num, den, stat, col = CHANNELS["babip"]
    k0 = rate_src.STABILISE_MEASURED["bat"][stat]
    xs, _flat, ys, _mags, keys = arm(rows, starts, ins, True, "babip", k0, 60)
    hand = {k: (x, y) for k, x, y in zip(keys, xs, ys)}

    shared = sorted(set(hand) & set(ars))
    print(f"  {len(shared):,} starts carry BOTH features\n")
    if len(shared) < 100:
        print("  too few to join")
        return
    h = [hand[k][0] for k in shared]
    a = [ars[k]["contact"] for k in shared]
    y = [hand[k][1] for k in shared]

    r1, z1 = corr(h, y)
    r2, z2 = corr(a, y)
    r12, z12 = corr(h, a)
    print(f"  {'feature':<22}{'r vs hits':>11}{'z':>8}{'cents':>8}")
    print(f"  {'handedness (contact)':<22}{r1:>+11.3f}{z1:>+8.1f}"
          f"{cents(r1):>8.2f}")
    print(f"  {'arsenal (contact)':<22}{r2:>+11.3f}{z2:>+8.1f}"
          f"{cents(r2):>8.2f}")
    print(f"\n  correlation BETWEEN the two features: {r12:+.3f} (z {z12:+.1f})")

    den_ = 1 - r12 * r12
    if den_ <= 1e-9:
        print("  the two features are the same number")
        return
    r2j = (r1 * r1 + r2 * r2 - 2 * r1 * r2 * r12) / den_
    R = max(r2j, 0.0) ** 0.5
    quad = (r1 * r1 + r2 * r2) ** 0.5
    print(f"\n  {'combination':<22}{'R':>11}{'cents':>8}")
    print(f"  {'naive sum (WRONG)':<22}{'-':>11}"
          f"{cents(r1) + cents(r2):>8.2f}")
    print(f"  {'quadrature ceiling':<22}{quad:>+11.3f}{cents(quad):>8.2f}")
    print(f"  {'JOINT, measured':<22}{R:>+11.3f}{cents(R):>8.2f}")
    print(f"  {'bar':<22}{'-':>11}{3.7:>8.2f}")
    print("\n  The naive sum double-counts whatever the two features share.")
    print("  The joint figure is what a model carrying BOTH would earn, and")
    print("  it is the only one of the three that answers the question.")


if __name__ == "__main__":
    main(sys.argv[1:])
