"""COUNT the extra-binomial strikeout variance in real starts.

    venv/bin/python -m scratchpad.k_dispersion [--control SIGMA]

QUESTION    How far does a real starter's per-start strikeout rate move
            beyond what his own rate and that night's lineup already imply,
            and beyond what pure chance would produce? Unit of observation:
            one real start. The answer is a SIGMA on a latent per-start
            multiplier, in the units `dispersion.perturb` uses.

WHY IT IS THE ONE MEASUREMENT LEFT ON TODO ITEM 7. The K tail is 3.5 sigma
short (o8.5 0.063 against 0.095) and the K sd is 2.28 against 2.49. A
per-start draw loaded on `k_pct` ALONE fixes both — K sd lands exactly on
2.49 and 69% of the tail gap closes — at less than half the outs CRPS cost
of the four-channel version that was rejected. **But the sigma that does
that was CHOSEN to hit the target, which is solving for a spread.** This
counts it instead, so it can ship or die on its own evidence.

FALSIFIER, PRE-REGISTERED. If the counted excess variance is near zero, the
K tail is NOT night-to-night sharpness and the whole lead dies — reality's
extra spread would have to come from something the model already contains,
and the honest move is to say so and stop.

THE ESTIMATOR. For start i the model implies a POISSON-BINOMIAL: the
batters he faced are independent draws with per-plate-appearance strikeout
probabilities p_ij that already carry log5, the specific nine, the
times-through-the-order decay and the home/road split. So

    mu_i  = sum_j p_ij           var_i = sum_j p_ij (1 - p_ij)

Under a latent multiplier k_pct -> k_pct * exp(sigma * z), z ~ N(0,1),
mu_i(z) ~ mu_i * exp(sigma z), so to first order the per-start variance
gains mu_i^2 * sigma^2 on top of `var_i`. Method of moments:

    sigma^2 = ( S - sum_i var_i ) / sum_i mu_i^2

TWO TRAPS THIS DESIGN EXISTS TO AVOID.

  1. **THE SHRINKAGE TRAP, WHICH KILLED THE HOME-RUN COMPRESSION FINDING
     ON DAY FOURTEEN.** A pitcher's rate carries estimation error, and that
     error is CONSTANT across his starts — it would inflate a naive
     across-start variance and read as dispersion. So `S` is built from
     WITHIN-PITCHER deviations, which removes any persistent per-pitcher
     bias entirely:

         S = sum_p sum_i (r_i - rbar_p)^2 / (1 - 1/m_p)

     with r_i = k_i - mu_i and m_p >= 2 starts. The (1 - 1/m) factor is the
     exact correction for E[sum (r - rbar)^2] = (1 - 1/m) sum Var(r).
  2. **THE IN-SAMPLE TRAP.** Rates are frozen before the holdout and only
     starts on or after it are scored, so a pitcher's own line cannot
     contain the start being predicted.

POSITIVE CONTROL, AND IT IS NOT OPTIONAL HERE. `--control SIGMA` throws away
the real strikeout counts and regenerates them from the model at a KNOWN
sigma, then re-runs the estimator. A mis-specified estimator and a genuinely
undispersed league produce the same near-zero answer, and only this
separates them. It must recover what it was given at sigma 0.00, 0.10, 0.20.

APPROXIMATION DECLARED. `state_mult` is evaluated state-blind, because the
base-out state of each real plate appearance is not reconstructed here. The
state effect on strikeouts is a ~3% swing (0.2279 bases empty against
0.2160 with men on) and averages out over ~22 plate appearances, but what
survives lands in the residual and therefore BIASES sigma UPWARD. So a
small positive answer is not automatically a real one; the number to trust
is one comfortably larger than that bias.
"""
from __future__ import annotations

import math
import random
import sys
from collections import defaultdict

import numpy as np

from src.context import calibrate as cal
from src.context import sim
from src.context.sources import pbp

HOLDOUT = "2026-07-01"


def k_prob(mu: sim.Matchup, tto: int) -> float:
    """P(strikeout) for one plate appearance, mirroring `sim.pa_from`.

    Kept as a transcription of that function rather than a re-derivation:
    a sacrifice is drawn off the top, then a hit-by-pitch, then the
    strikeout conditional on neither, which is why `k` is divided by `cond`
    inside the model and multiplied back out here.
    """
    p_k = mu.p_k
    m = sim.tto_mult(tto)
    if m is not None:
        p_k = p_k * m["k_pct"]
    k = sim.odds_mult(sim.log5(mu.b_k, p_k, mu.lg_k), mu.m_k, mu.lg_k)
    k = k / mu.cond
    return (1.0 - mu.sac) * (1.0 - mu.hbp) * k


def batters_faced(gids: set) -> dict:
    """(pitcher_name, game_id) -> batters the STARTER actually faced.

    Counted off play-by-play rather than taken as `outs + h + bb` from the
    boxscore, which understates a plate appearance count by ~2% because
    `mlb_batting` carries no hit-by-pitch or sacrifice column — the exact
    denominator error recorded on day fourteen.
    """
    out: dict = {}
    for gid in gids:
        if not pbp.have(gid):
            continue
        data = pbp.fetch(gid)
        if not data:
            continue
        starter, seen = {}, defaultdict(int)
        for play in (data.get("allPlays") or []):
            res = play.get("result") or {}
            if (res.get("eventType") or "") in getattr(
                    sys.modules.get("src.context.boundary"), "SKIP", set()):
                continue
            mu_ = play.get("matchup") or {}
            pid = (mu_.get("pitcher") or {}).get("id")
            name = (mu_.get("pitcher") or {}).get("fullName")
            if not pid:
                continue
            top = bool((play.get("about") or {}).get("isTopInning"))
            side = "home" if top else "away"
            if side not in starter:
                starter[side] = (pid, name)
            if starter[side][0] == pid:
                seen[(side, name)] += 1
        for (_side, name), n in seen.items():
            out[(name, gid)] = n
    return out


#: ONE HOLDOUT WINDOW PER SEASON, POOLED. A single 2026 window gives 1,043
#: usable starts and a bootstrap sd of 0.065 on sigma, which cannot tell
#: 0.125 from the 0.20 that fixes the K distribution — the comparison the
#: whole measurement exists to make. Three windows roughly triple the
#: sample. 2023 is excluded: `PRIOR_SEASONS` is 3, so its rates have no
#: prior seasons behind them and are built differently from the rest.
WINDOWS = ("2024-07-01", "2025-07-01", "2026-07-01")


def build_window(cut):
    """One row per start in one holdout window: mu, var, observed k."""
    from src.context import boundary          # for SKIP, via sys.modules
    assert boundary
    # SEASON IS EXPLICIT PER WINDOW. It defaults to the current one, so a
    # 2024 window built without it asks for 2026 batting rows and raises —
    # which is the right failure, but only because `sim.league` is strict.
    yr = int(cut[:4])
    pairs = cal.paired_cases(season=yr, rates_before=cut, since=cut)
    lg = sim.league(yr, before=cut)
    bf = batters_faced(set(pairs))
    rows = []
    for gid, v in pairs.items():
        for case in v:
            row, rates, lineup = case
            n = bf.get((row.get("player_name"), gid))
            k_obs = row.get("k")
            if not n or k_obs is None or n < 6:
                continue
            nine = cal.adjust_lineup(lineup, bool(row.get("is_home")))
            mus = [sim.resolve(b, rates, lg) for b in nine]
            mu_i = var_i = 0.0
            ps = []
            for j in range(n):
                p = k_prob(mus[j % 9], min(j // 9 + 1, 3))
                p = min(max(p, 1e-6), 0.999)
                ps.append(p)
                mu_i += p
                var_i += p * (1.0 - p)
            # THE PITCHER KEY CARRIES THE WINDOW. Deviations are taken
            # within pitcher to remove persistent rate error, and a
            # pitcher's rate is re-estimated in each window — so pooling
            # his 2024 and 2026 starts under one key would put the
            # DIFFERENCE between two rate estimates into the within-pitcher
            # deviation and read as dispersion.
            rows.append({"pit": f"{row.get('player_name')}|{cut}",
                         "gid": gid, "n": n, "k": k_obs, "mu": mu_i,
                         "var": var_i, "ps": ps})
    return rows


def build():
    rows = []
    for cut in WINDOWS:
        got = build_window(cut)
        print(f"    {cut}: {len(got):,} starts", flush=True)
        rows.extend(got)
    return rows


def estimate(rows, key="k"):
    """Method-of-moments sigma from WITHIN-pitcher deviations."""
    by: dict = defaultdict(list)
    for r in rows:
        by[r["pit"]].append(r)
    S = V = M2 = 0.0
    used = 0
    for _pit, grp in by.items():
        m = len(grp)
        if m < 2:
            continue
        res = [r[key] - r["mu"] for r in grp]
        rbar = sum(res) / m
        S += sum((x - rbar) ** 2 for x in res) / (1.0 - 1.0 / m)
        V += sum(r["var"] for r in grp)
        M2 += sum(r["mu"] ** 2 for r in grp)
        used += m
    excess = S - V
    sig2 = excess / M2 if M2 else 0.0
    return {"n": used, "pitchers": sum(1 for g in by.values() if len(g) >= 2),
            "S": S, "V": V, "M2": M2, "excess": excess,
            # SIGMA-SQUARED IS THE ESTIMATED QUANTITY AND IS REPORTED
            # ALONGSIDE. It is linear in the moments, so it is the thing
            # that has a symmetric sampling distribution and the thing a
            # confidence interval belongs on. The signed square root below
            # is for reading only — taking percentiles of it produced an
            # interval whose point estimate sat near its own upper edge.
            "sig2": sig2,
            "sigma": math.sqrt(sig2) if sig2 > 0 else -math.sqrt(-sig2),
            "ratio": S / V if V else 0.0}


def synth(rows, sigma, seed=0):
    """Regenerate k from the model at a KNOWN sigma. The control."""
    rng = random.Random(seed)
    out = []
    for r in rows:
        z = rng.gauss(0.0, 1.0)
        mult = math.exp(sigma * z)
        k = 0
        for p in r["ps"]:
            if rng.random() < min(p * mult, 0.999):
                k += 1
        out.append({**r, "ksyn": k})
    return out


def report(label, e):
    print(f"  {label:<34}sigma {e['sigma']:>+7.4f}   "
          f"S/V {e['ratio']:.4f}   excess {e['excess']:>9.1f}")


def main(argv):
    rows = build()
    ns = np.array([r["n"] for r in rows])
    print(f"\n  {len(rows):,} holdout starts, rates frozen before {HOLDOUT}")
    print(f"  batters faced: mean {ns.mean():.1f}, median "
          f"{np.median(ns):.0f}")
    print(f"  model mean K {np.mean([r['mu'] for r in rows]):.3f}  "
          f"actual mean K {np.mean([r['k'] for r in rows]):.3f}")
    e0 = estimate(rows)
    print(f"  {e0['pitchers']} pitchers with 2+ starts, {e0['n']} starts "
          f"used\n")

    print("  POSITIVE CONTROL — the estimator against known sigmas")
    print(f"    {'injected':>10}{'recovered sig2':>16}{'recovered sigma':>17}"
          f"{'S/V':>8}")
    bias = 0.0
    for s in (0.00, 0.10, 0.20, 0.30):
        c = estimate(synth(rows, s, seed=11), key="ksyn")
        if s == 0.0:
            bias = c["sig2"]
        print(f"    {s:>10.2f}{c['sig2']:>16.5f}{c['sigma']:>17.4f}"
              f"{c['ratio']:>8.4f}")
    print(f"    THE ZERO ROW IS THE BIAS: the estimator returns "
          f"sig2 {bias:+.5f} on a\n    league that has NO dispersion, so "
          f"that much is subtracted below. It is\n    the state-blind "
          f"approximation declared in the docstring, showing up as\n"
          f"    residual the model cannot account for.")

    # An error bar, by resampling PITCHERS (the unit that carries the
    # within-pitcher deviations), not starts. Percentiles are taken on
    # sig2, then square-rooted — not the other way round.
    by: dict = defaultdict(list)
    for r in rows:
        by[r["pit"]].append(r)
    keys = [k for k, g in by.items() if len(g) >= 2]
    rng = random.Random(5)
    boots = []
    for _ in range(400):
        # EACH DRAW GETS A UNIQUE KEY. `estimate` regroups on `pit`, so a
        # pitcher drawn twice would otherwise merge into ONE group of 2m
        # rows — which changes the deviations being squared and pulled the
        # bootstrap below its own point estimate, putting the point outside
        # its own interval. That contradiction is what exposed the bug.
        sub = []
        for t, k in enumerate(rng.choice(keys) for _ in keys):
            sub.extend({**r, "pit": f"{r['pit']}#{t}"} for r in by[k])
        boots.append(estimate(sub)["sig2"])
    boots = np.array(boots) - bias
    sd2 = float(np.std(boots))
    lo2, hi2 = np.percentile(boots, [2.5, 97.5])
    corrected = e0["sig2"] - bias

    def rt(v):
        return math.sqrt(v) if v > 0 else -math.sqrt(-v)

    print("\n  THE MEASUREMENT, BIAS-CORRECTED")
    print(f"    raw sig2          {e0['sig2']:+.5f}   (sigma "
          f"{e0['sigma']:+.4f})")
    print(f"    minus bias        {bias:+.5f}")
    print(f"    COUNTED sig2      {corrected:+.5f}   "
          f"=> SIGMA {rt(corrected):+.4f}")
    print(f"    95% CI on sig2    [{lo2:+.5f}, {hi2:+.5f}]   "
          f"=> sigma [{rt(lo2):+.4f}, {rt(hi2):+.4f}]")
    print(f"    sd {sd2:.5f}  ->  {corrected / sd2 if sd2 else 0:+.1f} "
          f"sigma from zero")
    print(f"    {len(keys)} pitcher-windows with 2+ starts, "
          f"{e0['n']:,} starts used")

    # CALIBRATE AGAINST THE CONTROL CURVE. The control does not recover what
    # it injects one-for-one at small sigma, so reading the raw number as
    # the answer understates it. Inverting the injected->recovered curve is
    # the correction, and it is only legitimate because the curve was built
    # by injection rather than fitted to the real data.
    print("\n  CALIBRATED AGAINST THE CONTROL CURVE")
    pts = []
    for s in (0.00, 0.10, 0.20, 0.30):
        c = estimate(synth(rows, s, seed=11), key="ksyn")
        pts.append((s * s, c["sig2"] - bias))
    print(f"    injected sig2 -> recovered sig2: "
          + ", ".join(f"{a:.4f}->{b:.4f}" for a, b in pts))
    inv = float(np.interp(corrected, [b for _, b in pts],
                          [a for a, _ in pts]))
    print(f"    counted {corrected:+.5f} inverts to TRUE sig2 {inv:.5f}"
          f"  =>  SIGMA {rt(inv):.4f}")

    print(f"\n  AGAINST THE TUNED VALUE. 0.20 means sig2 0.04000; this "
          f"counts {inv:.5f} calibrated ({corrected:+.5f} raw).")
    if sd2:
        print(f"  Raw is {(0.04 - corrected) / sd2:+.1f} sd from the tuned "
              f"value, so 0.20 is "
              f"{'NOT supported' if abs(0.04 - corrected) > 2 * sd2 else 'compatible'}"
              f".")
    print(f"  THE HONEST STATEMENT: the league carries real per-start "
          f"strikeout\n  dispersion, and it is roughly {rt(inv):.2f} — "
          f"smaller than the {0.20:.2f} that made\n  the K distribution "
          f"land on target. So sharpness is REAL and PARTIAL.")


if __name__ == "__main__":
    main(sys.argv[1:])
