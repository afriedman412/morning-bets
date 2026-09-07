"""WHERE THE SIM AND THE DIRECT MODELS DISAGREE ON A PROP, AND WHO IS RIGHT.

    venv/bin/python -m scratchpad.diverge

Day 21 scored the sim against the direct models POOLED — one CRPS, one
histogram. This is the per-start view the pooled one cannot show: for each
holdout start, both predictors hang a probability on the same prop line
(the nearest half-line to the sim's own mean — our line, not a book's), and
the divergence between those two probabilities is the thing a session would
actually act on. Then the disagreements are graded against what settled.

It also carries the RESUME item-C verification, which must come FIRST: the
claim "the fitted outs model always returns a mean of 15" was never
measured. The sd of the per-start predicted mean and the mode histogram,
sim vs fitted, settle it before anything downstream is read.

THE MC TRAP, stated before the numbers (CLAUDE.md, the denominator block):
the sim's per-start pmf is 200 draws, so its P(over) carries ~3.5 cents of
histogram noise per row and its mean ~0.13 K. Selecting rows for large
divergence selects for that noise, and noise in a regression predictor
attenuates the slope. Both corrections are applied where the arithmetic
allows and stated where it does not:
  * per-row Brier for the sim subtracts p(1-p)/draws (E[(p_hat-a)^2] =
    (p-a)^2 + p(1-p)/draws — the same correction direct.py makes on CRPS).
  * the who-is-right slope is reported raw AND disattenuated by the known
    MC share of the divergence variance.
"""
from __future__ import annotations

import math
import statistics as st

import numpy as np

from scratchpad import direct

DRAWS = 200          # what built the cache; the MC corrections assume it
CENT_BINS = [(-100, -7.5), (-7.5, -2.5), (-2.5, 2.5), (2.5, 7.5), (7.5, 100)]


def mean_var(pmf):
    x = np.arange(len(pmf))
    m = float(np.sum(x * pmf))
    return m, float(np.sum(x * x * pmf) - m * m)


def p_over(pmf, line):
    return float(np.sum(pmf[math.ceil(line):]))


def run(target: str, tr, te, sims):
    print(f"\n{'=' * 72}\n  {target.upper()}\n{'=' * 72}")
    pr = direct.fit_direct([(x, y[target], c) for x, y, c in tr],
                           [(x, y[target], c) for x, y, c in te],
                           target, quiet=True)
    keep = [i for i in range(len(te)) if sims[target][i] is not None]
    rows = []
    for i in keep:
        y = te[i][1][target]
        ps, pg, pe = sims[target][i], pr["glm"][i], pr["emp"][i]
        ms, vs = mean_var(ps)
        mg, _ = mean_var(pg)
        me, _ = mean_var(pe)
        line = math.floor(ms) + 0.5
        rows.append({
            "case": te[i][2][0], "y": y, "line": line,
            "ms": ms, "mg": mg, "me": me,
            "mc_var_mean": vs / DRAWS,            # MC variance of ms
            "os": p_over(ps, line), "og": p_over(pg, line),
            "oe": p_over(pe, line),
        })
    n = len(rows)

    # ── item-C verification: does the fitted model collapse to one mean? ──
    print(f"\n  PER-START PREDICTED MEAN over {n} holdout starts "
          f"(item-C verify):")
    for name, key in (("sim", "ms"), ("glm", "mg"), ("emp", "me")):
        v = [r[key] for r in rows]
        print(f"    {name:<4} mean {st.mean(v):7.3f}   sd {st.pstdev(v):.3f}"
              f"   range {min(v):.2f} .. {max(v):.2f}")
    act = [r["y"] for r in rows]
    print(f"    real mean {st.mean(act):7.3f}   sd {st.pstdev(act):.3f}")
    print(f"    (sim per-start mean carries MC se "
          f"~{st.mean(r['mc_var_mean'] for r in rows) ** 0.5:.3f} "
          f"at {DRAWS} draws)")
    print("\n  MODE of each start's pmf (share of starts whose pmf peaks "
          "at each value):")
    hi = int(max(max(np.argmax(sims[target][i]) for i in keep),
                 max(int(np.argmax(p)) for p in pr["glm"]),
                 max(r["y"] for r in rows)))
    print(f"  {'value':>7}{'sim':>8}{'glm':>8}{'actual':>8}")
    mode_s = [int(np.argmax(sims[target][i])) for i in keep]
    mode_g = [int(np.argmax(pr["glm"][i])) for i in keep]
    for v in range(hi + 1):
        a = sum(1 for r in rows if int(r["y"]) == v) / n
        s_ = mode_s.count(v) / n
        g_ = mode_g.count(v) / n
        if s_ or g_ or a > 0.01:
            print(f"  {v:>7}{s_:>8.3f}{g_:>8.3f}{a:>8.3f}")

    # ── the divergence itself, in prop terms at the sim's own line ────────
    div = [100 * (r["og"] - r["os"]) for r in rows]
    mc_c = 100 * st.mean((r["os"] * (1 - r["os"]) / DRAWS) ** 0.5
                         for r in rows)
    print("\n  P(over) DIVERGENCE, glm - sim, cents at the nearest "
          "half-line to the sim mean:")
    q = np.percentile(div, [5, 25, 50, 75, 95])
    print(f"    mean {st.mean(div):+.1f}   mean|.| "
          f"{st.mean(map(abs, div)):.1f}   "
          f"p5/p25/p50/p75/p95 {q[0]:+.1f}/{q[1]:+.1f}/{q[2]:+.1f}/"
          f"{q[3]:+.1f}/{q[4]:+.1f}")
    print(f"    share |div| > 5c: {sum(abs(d) > 5 for d in div) / n:.1%}   "
          f"> 10c: {sum(abs(d) > 10 for d in div) / n:.1%}   "
          f"(sim MC noise alone is ~{mc_c:.1f}c per row)")

    # ── who is right where they disagree: paired Brier, MC-corrected ─────
    print("\n  GRADED AT THE LINE, by signed divergence "
          "(sim Brier is MC-corrected):")
    print(f"  {'bin (cents)':>14}{'n':>6}{'P_sim':>8}{'P_glm':>8}"
          f"{'real':>8}{'se':>6}{'B_sim':>8}{'B_glm':>8}")
    for lo_, hi_ in CENT_BINS:
        sel = [r for r, d in zip(rows, div) if lo_ <= d < hi_]
        if len(sel) < 20:
            continue
        m = len(sel)
        real = st.mean(float(r["y"] > r["line"]) for r in sel)
        bs = st.mean((r["os"] - float(r["y"] > r["line"])) ** 2
                     - r["os"] * (1 - r["os"]) / DRAWS for r in sel)
        bg = st.mean((r["og"] - float(r["y"] > r["line"])) ** 2 for r in sel)
        print(f"  {f'{lo_:+.0f}..{hi_:+.0f}':>14}{m:>6}"
              f"{st.mean(r['os'] for r in sel):>8.3f}"
              f"{st.mean(r['og'] for r in sel):>8.3f}"
              f"{real:>8.3f}{(real * (1 - real) / m) ** 0.5:>6.3f}"
              f"{bs:>8.4f}{bg:>8.4f}")
    ov = [float(r["y"] > r["line"]) for r in rows]
    d_brier = [(r["os"] - a) ** 2 - r["os"] * (1 - r["os"]) / DRAWS
               - (r["og"] - a) ** 2 for r, a in zip(rows, ov)]
    se = st.pstdev(d_brier) / n ** 0.5
    print(f"    all rows, paired Brier sim - glm: {st.mean(d_brier):+.4f} "
          f"± {se:.4f}  ({st.mean(d_brier) / se:+.1f} sigma, "
          f"{'glm better' if st.mean(d_brier) > 0 else 'sim better'})")

    # ── does the direct model carry signal the sim misses? ───────────────
    # (y - ms) on (mg - ms): slope 0 = sim already complete, 1 = the whole
    # divergence is real signal the sim lacks. MC noise in ms sits in BOTH
    # variables; the disattenuation uses the known MC variance.
    dm = np.array([r["mg"] - r["ms"] for r in rows])
    resid = np.array([r["y"] - r["ms"] for r in rows])
    slope = float(np.cov(dm, resid)[0, 1] / np.var(dm))
    mc = st.mean(r["mc_var_mean"] for r in rows)
    lam = 1 - mc / float(np.var(dm))       # share of div variance that is real
    se_s = (float(np.var(resid)) / (np.var(dm) * n)) ** 0.5
    # MC noise in ms appears in dm (-) and resid (-) alike, so it PUSHES the
    # raw slope toward +1, not 0; the corrected value removes that shared
    # noise from both moments.
    cov_c = float(np.cov(dm, resid)[0, 1]) - mc
    var_c = float(np.var(dm)) - mc
    print("\n  MEAN-DIVERGENCE REGRESSION  (y - sim) ~ (glm - sim):")
    print(f"    sd(glm - sim) {float(np.std(dm)):.3f}, of which MC noise "
          f"{mc ** 0.5:.3f}  ->  {max(lam, 0):.0%} of divergence "
          f"variance is real")
    print(f"    slope raw {slope:+.3f} ± {se_s:.3f}   "
          f"MC-corrected {cov_c / var_c:+.3f}")
    print("    (0 = sim already knows it; 1 = divergence is all real "
          "signal the sim misses)")

    # ── the ten largest prop disagreements, named ────────────────────────
    print("\n  LARGEST DISAGREEMENTS (so the inputs can be eyeballed, "
          "rule: verify inputs):")
    print(f"  {'date':>11} {'starter':<22}{'line':>6}{'P_sim':>7}"
          f"{'P_glm':>7}{'actual':>7}")
    for r in sorted(rows, key=lambda r: -abs(100 * (r["og"] - r["os"])))[:10]:
        c = r["case"]
        print(f"  {c.get('date', ''):>11} {c.get('player_name', ''):<22}"
              f"{r['line']:>6.1f}{r['os']:>7.3f}{r['og']:>7.3f}"
              f"{r['y']:>7.0f}")


def main():
    tr, te = direct.build_all()
    print(f"  {len(tr)} training starts, {len(te)} holdout starts")
    sims = direct.sim_pmfs_all(te, DRAWS)   # cache hit, no simulation
    for t in ("k", "outs"):
        run(t, tr, te, sims)


if __name__ == "__main__":
    main()
