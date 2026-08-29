"""Does the SCORE reach the manager's hook, and by how much per run?

    venv/bin/python -m scratchpad.hook_margin

`sim.Hook.per_margin` and `Hook.mid_per_margin` are both 0.0 and have been
since the parameters were created. Their docstring says so explicitly:
"BOTH DEFAULT TO ZERO, so nothing changes until this is measured. The sign
is not obvious in advance — a big lead buys a starter rope because the game
is safe, and also gets him lifted because there is nothing left to protect."
This measures it.

WHAT IS BEING FITTED, AND WHY THAT IS ALLOWED. The target is `removed` — a
DECISION a real manager made — not runs, not a settlement value. CLAUDE.md:
"do not fit the hook AGAINST THE SETTLEMENT VALUE. Fitting it to real
removal DECISIONS is a different thing."

TWO CANDIDATE MECHANISMS, AND THEY ARE NOT THE SAME. Both ship as separate
columns on every decision row and they answer different questions:

    margin      signed, from the PITCHER'S side. +4 means his own club
                leads by four. Tests "a manager treats a starter
                differently when his own team is ahead."
    abs_margin  unsigned. Tests "the game is out of hand either way, so
                the decision stops being about winning" — the mop-up
                channel, which is symmetric and which a signed term
                CANNOT represent.

Fitting only the signed term when the real effect is symmetric returns
approximately zero, which is the mis-specification failure CLAUDE.md warns
about: "a mis-specified mechanism and an absent effect produce identical
output."

TWO POPULATIONS, FITTED SEPARATELY, because a hook curve is fitted on the
population it fires in and pooling is the default mistake here — 248,568
mid-inning rows at a 2.42% pull rate against 73,637 boundary rows at
11.49%, so a pooled fit is dominated by the mid-inning population.

UNSTANDARDISED ON PURPOSE. The shipped Hook reads raw features, so a
coefficient here is directly `per_margin` in log-odds per run of lead. A
standardised coefficient would have to be divided by an sd that is not
recorded anywhere in `sim.py`.

STANDARD ERRORS come from the observed Fisher information, so every
coefficient below is reportable with its own sigma rather than as a point
estimate. That is the rule this file exists to satisfy.
"""
from __future__ import annotations

import json

import numpy as np

CACHE = "/tmp/hook_rows.json"
CUTOFF = "2026-07-15"

#: The features the SHIPPED boundary curve reads, in `sim.Hook.removal_p`
#: order. `pitches` enters as (pitches - centre)/scale there; here it is
#: raw and the fitted coefficient is 1/pitch_scale.
BND_BASE = ("pitches", "runs", "br", "inning")

#: The shipped LATE mid-inning branch: `late_mid_per_pitch` * pitches,
#: `late_mid_per_inning_br` * inn_br, `late_mid_per_run` * runs,
#: `late_mid_per_onbase` * on_base.
MID_BASE = ("pitches", "inn_br", "runs", "onbase")

#: THE CONFOUND CONTROL, and it is the one that matters for `abs_margin`.
#: A score gap WIDENS as a game goes on, and the shipped mid-inning branch
#: carries no inning term at all — so an inning effect would arrive on the
#: margin coefficient with nothing to stop it. `outs_before` is here for
#: the same reason: the mid-inning population spans outs 0/1/2 and the
#: split fit gives it a large coefficient.
MID_FULL = MID_BASE + ("inning", "outs_before", "bf")
BND_FULL = BND_BASE + ("bf", "tto", "damage")


def xy(rows, feats):
    X = np.array([[float(r[f]) for f in feats] for r in rows], dtype=float)
    y = np.array([1.0 if r["removed"] else 0.0 for r in rows])
    return X, y


def fit(X, y, ridge=1e-6, iters=60):
    """Newton-Raphson logistic. Returns (beta, se) with an intercept last.

    Hand-rolled rather than sklearn because sklearn regularises by default
    (C=1.0) and does not expose standard errors, and both of those are the
    point of this file.
    """
    Z = np.hstack([X, np.ones((len(X), 1))])
    b = np.zeros(Z.shape[1])
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-np.clip(Z @ b, -30, 30)))
        W = p * (1 - p)
        H = Z.T @ (Z * W[:, None]) + ridge * np.eye(Z.shape[1])
        g = Z.T @ (y - p) - ridge * b
        step = np.linalg.solve(H, g)
        b = b + step
        if np.max(np.abs(step)) < 1e-10:
            break
    p = 1.0 / (1.0 + np.exp(-np.clip(Z @ b, -30, 30)))
    W = p * (1 - p)
    H = Z.T @ (Z * W[:, None]) + ridge * np.eye(Z.shape[1])
    se = np.sqrt(np.diag(np.linalg.inv(H)))
    return b, se


def report(rows, base, extra, label):
    feats = base + extra
    X, y = xy(rows, feats)
    b, se = fit(X, y)
    print(f"\n  {label}")
    print(f"    n {len(rows):,}   pulls {int(y.sum()):,}   "
          f"base rate {y.mean():.4f}")
    print(f"    {'feature':<14}{'coef':>11}{'se':>10}{'z':>8}")
    for i, f in enumerate(feats):
        star = "  <--" if f in extra else ""
        print(f"    {f:<14}{b[i]:>+11.5f}{se[i]:>10.5f}"
              f"{b[i]/se[i]:>+8.1f}{star}")
    print(f"    {'intercept':<14}{b[-1]:>+11.5f}{se[-1]:>10.5f}")
    return {f: (b[i], se[i]) for i, f in enumerate(feats)}


def power(rows, base, extra, label):
    """SE of the candidate coefficients BEFORE the estimate is looked at.

    STATE THE POWER BEFORE THE RESULT. The SE of a logistic coefficient
    does not depend on the outcome vector except through the fitted
    probabilities, so fitting the base model and adding the candidate
    column to the information matrix gives the SE the full fit will have,
    without anyone having seen the effect.
    """
    Xb, y = xy(rows, base)
    b, _ = fit(Xb, y)
    Zb = np.hstack([Xb, np.ones((len(Xb), 1))])
    p = 1.0 / (1.0 + np.exp(-np.clip(Zb @ b, -30, 30)))
    W = p * (1 - p)
    Xf, _ = xy(rows, base + extra)
    Z = np.hstack([Xf, np.ones((len(Xf), 1))])
    H = Z.T @ (Z * W[:, None]) + 1e-6 * np.eye(Z.shape[1])
    se = np.sqrt(np.diag(np.linalg.inv(H)))
    print(f"\n  POWER — {label}")
    for i, f in enumerate(base + extra):
        if f in extra:
            print(f"    {f:<14}se {se[i]:.5f}   resolves "
                  f"{3*se[i]:.5f} log-odds/run at 3 sigma")
    return se


def control(rows, base, extra, size, label):
    """POSITIVE CONTROL. Inject a known coefficient and confirm recovery.

    Re-rolls the outcome from the base model's own fitted probabilities
    PLUS `size` * the candidate feature, so the harness is being asked to
    find an effect of a size it was told. A mis-specified fit and an
    absent effect look identical without this.
    """
    rng = np.random.default_rng(11)
    Xb, y = xy(rows, base)
    b, _ = fit(Xb, y)
    Zb = np.hstack([Xb, np.ones((len(Xb), 1))])
    lin = Zb @ b
    Xe, _ = xy(rows, extra)
    lin = lin + size * Xe[:, 0]
    p = 1.0 / (1.0 + np.exp(-np.clip(lin, -30, 30)))
    y2 = (rng.random(len(p)) < p).astype(float)
    Xf, _ = xy(rows, base + extra)
    bb, se = fit(Xf, y2)
    i = len(base)
    print(f"    {label}: injected {size:+.4f}  recovered "
          f"{bb[i]:+.5f} +/- {se[i]:.5f}  "
          f"({'SEEN' if abs(bb[i]/se[i]) > 3 else 'MISSED'})")


def main():
    rows = json.load(open(CACHE))
    mid = [r for r in rows if not r["ends_inning"]]
    bnd = [r for r in rows if r["ends_inning"]]
    print(f"{len(rows):,} starter decisions, {min(r['date'] for r in rows)} "
          f"to {max(r['date'] for r in rows)}")
    print(f"  {len(bnd):,} boundary ({np.mean([r['removed'] for r in bnd]):.4f} "
          f"pulled)   {len(mid):,} mid-inning "
          f"({np.mean([r['removed'] for r in mid]):.4f} pulled)")
    print(f"  margin sd {np.std([r['margin'] for r in rows]):.2f}, "
          f"|margin| mean {np.mean([r['abs_margin'] for r in rows]):.2f}")

    for name, pop, base, full in (
            ("BOUNDARY", bnd, BND_BASE, BND_FULL),
            ("MID-INNING", mid, MID_BASE, MID_FULL)):
        print(f"\n{'='*66}\n{name}\n{'='*66}")
        power(pop, base, ("margin",), f"{name} signed margin")
        power(pop, base, ("abs_margin",), f"{name} |margin|")
        print("\n  POSITIVE CONTROLS")
        control(pop, base, ("margin",), 0.05, "signed margin x0.05")
        control(pop, base, ("abs_margin",), 0.05, "|margin| x0.05")
        report(pop, base, ("margin",), f"{name} + signed margin")
        report(pop, base, ("abs_margin",), f"{name} + |margin|")
        report(pop, base, ("margin", "abs_margin"), f"{name} + both")

        # THE CONFOUND. If |margin| is really carrying an inning effect it
        # will collapse once the game clock is in the model.
        print(f"\n  --- {name}: CONTROLLED for game progress "
              f"({', '.join(f for f in full if f not in base)}) ---")
        report(pop, full, ("abs_margin",), f"{name} + |margin|, controlled")
        report(pop, full, ("margin", "abs_margin"),
               f"{name} + both, controlled")

        # STABILITY GATE. A coefficient that does not repeat across seasons
        # is not a mechanism, whatever its in-sample sigma.
        print(f"\n  --- {name}: PER SEASON, controlled ---")
        for yr in ("2023", "2024", "2025", "2026"):
            sub = [r for r in pop if r["date"][:4] == yr]
            if len(sub) < 5000:
                continue
            X, y = xy(sub, full + ("abs_margin",))
            b, se = fit(X, y)
            i = len(full)
            print(f"    {yr}  n {len(sub):>7,}  abs_margin "
                  f"{b[i]:>+9.5f} +/- {se[i]:.5f}  z {b[i]/se[i]:>+5.1f}")


if __name__ == "__main__":
    main()
