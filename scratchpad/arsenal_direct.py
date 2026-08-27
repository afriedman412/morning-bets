"""ARSENAL, re-tested with the three things eight attempts never had.

    venv/bin/python -m scratchpad.arsenal_direct [n_sims] [salts]

WHAT WAS MISSING EVERY PREVIOUS TIME, listed on 2026-08-27 while auditing
handedness and never acted on:

  1. NO POSITIVE CONTROL. Nobody ever amplified the multiplier and confirmed
     the harness could see it. If a 4x arsenal effect is invisible then every
     arsenal null ever recorded here is uninformative, and eight of them are.
  2. SCORED ON RUNS. The pre-registered tests used F5 CRPS, which sits four
     steps downstream of a plate appearance. Detection and fitting are
     different jobs; this scores the starter's OWN line, where a
     plate-appearance mechanism has power.
  3. LEAVE-ONE-OUT WAS AN ARGUMENT. `arsenal_screen.py` reasons the leak
     away in a docstring rather than removing it. The multiplier is built
     from Savant season aggregates that CONTAIN the start being scored.
     Handedness gained 3.5 sigma in sample and lost 2.3 out of it on exactly
     that.

FOUR ARMS.

    off            what ships (USE_ARSENAL is False)
    arsenal 2026   in-sample. The UPPER BOUND, inflated by the leak.
    arsenal 2025   the pitcher's PREVIOUS season's mix and results, scoring
                   2026 starts. Leak-free by construction, and what a model
                   would actually hold. THIS IS THE ARM THAT ADJUDICATES.
    arsenal x4     the positive control, in-sample multipliers pushed four
                   times as far from 1.0.

ONE MORE THING THE REFACTOR CHANGED. Arsenal used to MULTIPLY log5's
probability output; since `sim.odds_mult` it enters the odds instead, so the
same multiplier no longer means different things in high- and low-strikeout
matchups. Every earlier arsenal test ran on the old, incoherent application.
"""
from __future__ import annotations

import statistics as st
import sys

from src.context import calibrate as cal, fitf5, sim
from src.context.sources import rates as rate_src
from scratchpad.hand_direct import CHANNELS, _PAIRS, run_arm  # noqa: F401
import scratchpad.hand_direct as hd

SCORE_SEASON = 2026


def _amplify(pairs, amp: float) -> int:
    """Push every attached multiplier `amp` times as far from 1.0.

    The control, and the only way a null here means anything. Counts what it
    touched: a control that silently multiplies nothing is indistinguishable
    from a mechanism that does nothing.
    """
    n = 0
    for _gid, (away, home) in pairs.items():
        for case in (away, home):
            for b in case[2]:
                if b.arsenal_mult != 1.0:
                    b.arsenal_mult = 1.0 + amp * (b.arsenal_mult - 1.0)
                    n += 1
                if b.arsenal_k_mult != 1.0:
                    b.arsenal_k_mult = 1.0 + amp * (b.arsenal_k_mult - 1.0)
    return n


def arsenal_arm(kind, n_sims, salts, lg, workers=8):
    """Score one arsenal configuration on the starters' own lines."""
    cal.USE_ARSENAL = kind != "off"
    season = 2025 if kind == "prior" else SCORE_SEASON
    real = None
    if kind == "prior":
        # The pitcher's PREVIOUS season's arsenal, which cannot contain the
        # start being scored. Savant serves per-season, so this is the one
        # leak-free construction available — the `before` cutoff does not
        # help, because the blob is season-to-date whenever it is fetched.
        from src import panel
        real = panel.savant_pitcher_arsenal
        panel.savant_pitcher_arsenal = (
            lambda _s, stamp, _r=real: _r(2025, stamp))
    try:
        cal._CASES.clear()
        pairs = cal.paired_cases(season=SCORE_SEASON)
        touched = 0
        if kind.startswith("x"):
            touched = _amplify(pairs, float(kind[1:]))
        elif kind != "off":
            touched = sum(1 for _g, (a, h) in pairs.items()
                          for c in (a, h) for b in c[2]
                          if b.arsenal_mult != 1.0)
        if kind != "off" and touched == 0:
            raise SystemExit(f"{kind}: NO multiplier was attached — the arm "
                             f"is identical to `off` and its result is "
                             f"plumbing, not a null")
        hd._PAIRS = [(g, a, h) for g, (a, h) in sorted(pairs.items())]
        hd._LG, hd._PENS = lg, rate_src.bullpens(lg)
        n = len(hd._PAIRS)
        step = max(1, n // (workers * 2))
        jobs = [(lo, min(lo + step, n), n_sims, salt)
                for salt in salts for lo in range(0, n, step)]
        import multiprocessing as mp
        with mp.get_context("fork").Pool(workers) as pool:
            out = pool.map(hd._chunk, jobs)
        k = len(jobs) // len(salts)
        per_salt = []
        for i in range(len(salts)):
            acc = {c: [0.0, 0.0, 0] for c in CHANNELS}
            for a in out[i * k:(i + 1) * k]:
                for c in CHANNELS:
                    for j in range(3):
                        acc[c][j] += a[c][j]
            per_salt.append({c: (acc[c][0] / acc[c][2], acc[c][1] / acc[c][2])
                             for c in CHANNELS})
        return len(pairs), touched, per_salt
    finally:
        if real is not None:
            from src import panel
            panel.savant_pitcher_arsenal = real
        cal.USE_ARSENAL = False
        cal._CASES.clear()


def main(argv):
    n_sims = int(argv[0]) if len(argv) > 0 else 20
    salts = list(range(int(argv[1]) if len(argv) > 1 else 6))
    lg = sim.league()
    print(f"  starters' own lines, {SCORE_SEASON} starts")
    print(f"  {n_sims} sims x {len(salts)} salts, paired\n")

    res = {}
    for kind, label in (("off", "off"), ("in", "arsenal 2026"),
                        ("prior", "arsenal 2025"), ("x4", "arsenal x4")):
        ngames, touched, per_salt = arsenal_arm(kind, n_sims, salts, lg)
        res[label] = per_salt
        rps = {c: st.mean(s[c][1] for s in per_salt) for c in CHANNELS}
        print(f"  {label:<14}{ngames:>5} games  {touched:>6,} mults   "
              + "  ".join(f"{c} {rps[c]:.4f}" for c in CHANNELS))

    print(f"\n  RPS vs off, paired by salt (NEGATIVE is better):")
    print(f"  {'arm':<14}" + "".join(f"{c:>18}" for c in CHANNELS))
    base = res["off"]
    for label in ("arsenal 2026", "arsenal 2025", "arsenal x4"):
        cells = []
        for c in CHANNELS:
            d = [b[c][1] - a[c][1] for a, b in zip(base, res[label])]
            m, se = fitf5._mean_se(d)
            cells.append(f"{m:+.4f}({m / se if se else 0:+.1f})")
        print(f"  {label:<14}" + "".join(f"{x:>18}" for x in cells))
    print("\n  READ THE x4 ROW FIRST. If the control is invisible the")
    print("  harness cannot see arsenal at all and the other rows say")
    print("  nothing. If it IS visible, the 2025 row is the answer.")


if __name__ == "__main__":
    main(sys.argv[1:])
