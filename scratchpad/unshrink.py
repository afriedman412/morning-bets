"""Is the model bunched BECAUSE of shrinkage? Sweep it and see.

    venv/bin/python -m scratchpad.unshrink [n_sims] [salts]

THE FINDING THIS FOLLOWS FROM, and it was nearly dismissed. Regressing actual
on predicted, every channel comes out above 1.0 once Monte Carlo noise in the
predictor is corrected for: k 1.15, bb 1.23, er 1.32, h 1.37, outs 1.58,
hr 2.59, at +3.8 to +8.5 sigma. The model's predictions are too BUNCHED —
reality separates starts more than the model does.

WHY THE FIRST DISMISSAL WAS WRONG. An out-of-sample rescaling test came back
flat and was read as "not exploitable". But rescaling corrects the DELIVERED
40-draw predictions for their own sampling noise, which is a different
question from whether the UNDERLYING model is compressed. The first is about
the estimator; the second is about the baseball. Only the second was
measured, and only the first was tested.

WHY IT MATTERS MORE THAN A CALIBRATION NOTE. Under-differentiated predictions
are a DISCRIMINATION deficit, and discrimination is exactly what the flat
per-start dispersion term could not supply — it fixed the marginal shape and
was neutral on CRPS because it spread every start equally. A model that
separates starts too little has signal it is throwing away.

THE SUSPECT IS SHRINKAGE, which compresses by construction. The batter table
shows the model carrying 0.89 of observed strikeout spread, 0.73 on home
runs, 0.57 on BABIP, and pitcher home runs use k=934 — a 600-batter pitcher
keeps 39% of his own number. Every one of those pulls a prediction toward the
league mean.

THE TEST. Scale every `STABILISE_MEASURED` constant by a factor and measure
what happens to DISCRIMINATION — the correlation between prediction and
outcome — not to calibration. Less shrinkage means more spread; the question
is whether the extra spread is signal or noise. If correlation RISES the
constants are too aggressive and there is free accuracy here. If it FALLS the
shrinkage is doing its job and the compression is the price of it.

Correlation rather than MSE on purpose: MSE conflates spread with accuracy,
and spread is the thing being varied.
"""
from __future__ import annotations

import math
import multiprocessing as mp
import random
import statistics as st
import sys
from collections import defaultdict

from src.context import calibrate as cal, fitf5, game, sim
from src.context.sources import rates as rate_src

CHANNELS = ("k", "bb", "hr", "h", "er", "outs")
_PAIRS: list = []
_LG: dict = {}
_PENS: dict = {}


def _chunk(args):
    lo, hi, n_sims, salt = args
    out = []
    for gid, away, home in _PAIRS[lo:hi]:
        rng = random.Random((hash(gid) & 0xFFFFFF) + salt * 7919)
        acc = {t: {c: 0.0 for c in CHANNELS} for t in ("a", "h")}
        for _ in range(n_sims):
            r = cal.replay((away, home), _LG, _PENS, rng)
            for tag, ln in (("a", r.away_sp), ("h", r.home_sp)):
                for c in CHANNELS:
                    acc[tag][c] += getattr(ln, "earned" if c == "er" else c)
        for tag, case in (("a", away), ("h", home)):
            row = case[0]
            out.append(({c: acc[tag][c] / n_sims for c in CHANNELS},
                        # The start row keys outs as `o` (`p.outs_recorded o`
                        # in _STARTS_Q), not `outs`.
                        {c: (row["o"] if c == "outs" else row[c]) or 0
                         for c in CHANNELS}))
    return out


def corr(xs, ys):
    n = len(xs)
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if not sx or not sy:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (n * sx * sy)


def run(factor, n_sims, salts, workers=8, holdout=None):
    """Scale every shrinkage constant, rebuild rates, score discrimination."""
    global _PAIRS, _LG, _PENS
    base = {k: dict(v) for k, v in rate_src.STABILISE_MEASURED.items()}
    try:
        rate_src.STABILISE_MEASURED = {
            who: {stat: max(1.0, v * factor) for stat, v in d.items()}
            for who, d in base.items()}
        cal._CASES.clear()
        lg = sim.league()
        # HOLDOUT OR THE RESULT IS MEANINGLESS. Player rates are built
        # from the same season being scored, so LESS shrinkage lets each
        # rate track that player's own realised outcomes and the correlation
        # with those outcomes rises for free. `rates_before` trains on the
        # window before the cutoff; `since` scores only starts after it.
        pairs = (cal.paired_cases(season=2026, rates_before=holdout,
                                  since=holdout)
                 if holdout else cal.paired_cases(season=2026))
        _PAIRS = [(g, a, h) for g, (a, h) in sorted(pairs.items())]
        _LG, _PENS = lg, rate_src.bullpens(lg)
        n = len(_PAIRS)
        step = max(1, n // (workers * 2))
        jobs = [(lo, min(lo + step, n), n_sims, s)
                for s in salts for lo in range(0, n, step)]
        with mp.get_context("fork").Pool(workers) as pool:
            got = pool.map(_chunk, jobs)
        per_salt = []
        k = len(jobs) // len(salts)
        for i in range(len(salts)):
            rows = [x for part in got[i * k:(i + 1) * k] for x in part]
            per_salt.append({
                c: corr([p[c] for p, _a in rows], [a[c] for _p, a in rows])
                for c in CHANNELS})
        return per_salt
    finally:
        rate_src.STABILISE_MEASURED = base
        cal._CASES.clear()


def main(argv):
    holdout = None
    if "--holdout" in argv:
        i = argv.index("--holdout")
        holdout = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    n_sims = int(argv[0]) if len(argv) > 0 else 40
    salts = list(range(int(argv[1]) if len(argv) > 1 else 4))
    if holdout:
        print(f"  HOLDOUT: rates trained before {holdout},"
              f" scored on starts from {holdout}")
    print(f"  discrimination (corr of prediction with outcome), 2026 starts")
    print(f"  {n_sims} sims x {len(salts)} salts\n")
    print(f"  {'shrink x':<10}" + "".join(f"{c:>9}" for c in CHANNELS))
    res = {}
    for f in (0.25, 0.5, 1.0, 2.0):
        per = run(f, n_sims, salts, holdout=holdout)
        res[f] = per
        means = {c: st.mean(p[c] for p in per) for c in CHANNELS}
        print(f"  {f:<10.2f}" + "".join(f"{means[c]:>+9.4f}"
                                        for c in CHANNELS), flush=True)

    print(f"\n  paired against the shipped constants (POSITIVE = better):")
    print(f"  {'shrink x':<10}" + "".join(f"{c:>13}" for c in CHANNELS))
    base = res[1.0]
    for f in (0.25, 0.5, 2.0):
        cells = []
        for c in CHANNELS:
            d = [b[c] - a[c] for a, b in zip(base, res[f])]
            m, se = fitf5._mean_se(d)
            cells.append(f"{m:+.4f}({m / se if se else 0:+.1f})")
        print(f"  {f:<10.2f}" + "".join(f"{x:>13}" for x in cells))
    print("\n  If LESS shrinkage (x0.25, x0.5) raises the correlation, the")
    print("  constants are too aggressive and the model is throwing away")
    print("  signal. If it lowers it, the compression is the price of")
    print("  shrinkage doing its job and the slope result is explained.")


if __name__ == "__main__":
    main(sys.argv[1:])
