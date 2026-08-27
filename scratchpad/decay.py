"""How much is a pitcher's season worth k YEARS LATER? Counted, not fitted.

    venv/bin/python -m scratchpad.decay

WHAT IS BLOCKED ON THIS. `rates.USE_PRIOR_SEASON` shrinks a thin current
line toward the pitcher's OWN last season instead of toward the league, and
it is the only measured gain of day ten — K correlation 0.334 -> 0.384 at a
May cut for a third of pooling's bias cost. It ships behind a flag because
`set_prior` takes ONE season and there are now four on disk. The missing
number is the decay: what weight does 2024 carry against 2025, and 2023
against 2024.

THIS IS A MEASUREMENT AND MUST STAY ONE. `stabilise.py` is the template —
split-half reliability counted on this league, no loss function anywhere
near it. The same discipline applies here: the quantity being measured is
HOW WELL A PAST SEASON PREDICTS A FUTURE ONE, which is a fact about
pitchers. It is not scored against runs, prices or anything that settles.
Handing a decay weight to a search against the settlement value is exactly
how a measured constant goes back to absorbing other defects.

THREE READINGS, deliberately, because each fails differently:

  1. LAG CORRELATIONS, disattenuated. The raw correlation between season S-k
     and season S is pulled toward zero by sampling noise in BOTH seasons.
     Reliability at n batters faced is n/(n+k_stat) — that is not an
     assumption, it is the shrinkage form the model already uses with the
     constants `stabilise.py` counted — so dividing by sqrt(rel1*rel2)
     recovers the true-talent autocorrelation. If that falls geometrically,
     one decay weight describes it.
  2. JOINT REGRESSION on pitchers who have all three lags. Reads the
     relative weights directly, assuming no shape at all. It is the check on
     reading 1: if the correlations decay geometrically but the regression
     wants 2024 at zero, the geometry is an artifact.
  3. THE BLEND SWEEP, which is what actually ships. Build the prior at each
     candidate w and score it against the target season. Reading 3 is the
     one to trust when they disagree, because it is the estimator itself
     rather than a property of it.

LEAGUE-ADJUSTED FIRST, EVERY SEASON. Home runs are up 7% between 2025 and
2026 and the ball moves the whole population at once. Without adjustment a
lag correlation measures the ball as much as the pitcher, and the effect
grows with the lag, which would look exactly like decay.

SAME CONDITIONING AS THE CODE PATH. `rates.pitcher_rates` groups EVERY
appearance a pitcher makes in a season, starter or relief, and the prior is
built from its output. So this counts the same thing. Restricting to starts
would measure a different quantity from the one that ships.
"""
from __future__ import annotations

import statistics as st
import sys

from src.context import store
from src.context.sources import rates as rate_src

#: Batters faced required in BOTH seasons of a pair. A pitcher with 20
#: batters faced in one season contributes almost pure noise to the
#: correlation and pure noise to the disattenuation that tries to remove it.
MIN_BF = 100

STATS = ("k_pct", "bb_pct", "hr_pct", "babip")

_Q = """
select substr(g.date, 1, 4) season, p.player_name name,
       sum(p.outs_recorded) o, sum(p.h) h, sum(p.bb) bb,
       sum(p.k) k, sum(p.hr) hr
from bets.mlb_pitching p join bets.games g on g.game_id = p.game_id
where g.sport = 'mlb' and g.status = 'Final'
group by season, p.player_name
"""


def seasons() -> dict[int, dict[str, dict]]:
    """{season: {name: raw rates}}, on the same footing as `pitcher_rates`.

    Batters faced is outs + hits + walks, which is what the cache supports
    and what `sim._starter_league` uses, so pitcher and league agree.
    """
    with store.connect() as c:
        rows = [dict(r) for r in c.execute(_Q)]
    out: dict[int, dict[str, dict]] = {}
    for r in rows:
        bf = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
        if bf < 1:
            continue
        bip = bf - (r["k"] or 0) - (r["bb"] or 0) - (r["hr"] or 0)
        out.setdefault(int(r["season"]), {})[r["name"]] = {
            "bf": bf, "bip": max(bip, 0),
            "k_pct": (r["k"] or 0) / bf,
            "bb_pct": (r["bb"] or 0) / bf,
            "hr_pct": (r["hr"] or 0) / bf,
            "babip": (((r["h"] or 0) - (r["hr"] or 0)) / bip)
            if bip > 0 else None,
        }
    return out


def league(pop: dict[str, dict]) -> dict[str, float]:
    """One season's population mean, weighted by batters faced."""
    out = {}
    for stat in STATS:
        num = den = 0.0
        for r in pop.values():
            if r[stat] is None:
                continue
            n = r["bip"] if stat == "babip" else r["bf"]
            num += r[stat] * n
            den += n
        out[stat] = num / den if den else 0.0
    return out


def adjusted(pop: dict[str, dict], lg: dict[str, float],
             ref: dict[str, float]) -> dict[str, dict]:
    """Move a season onto the REFERENCE season's run environment.

    The same operation `rates._prior_adjusted` performs, applied to every
    season so that lags of different lengths are on one footing.
    """
    out = {}
    for name, r in pop.items():
        a = {"bf": r["bf"], "bip": r["bip"]}
        for stat in STATS:
            base = lg.get(stat)
            a[stat] = (r[stat] * ref[stat] / base
                       if r[stat] is not None and base else None)
        out[name] = a
    return out


def corr(xs, ys) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if not sx or not sy:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (n * sx * sy)


def rel(n: float, stat: str) -> float:
    """Reliability of a sample of n at this stat — the shrink weight itself.

    `_shrink` uses w = n/(n+k) and that w IS the reliability under the model
    those constants were counted for, so no separate assumption enters here.
    """
    k = rate_src.STABILISE_MEASURED["pit"].get(stat) \
        or rate_src.STABILISE[stat]
    return n / (n + k)


def _n_for(r, stat):
    return r["bip"] if stat == "babip" else r["bf"]


def lag_table(adj: dict[int, dict[str, dict]], targets: list[int]):
    """Reading 1 — how far a season carries, at each lag."""
    print("\n  LAG CORRELATIONS — raw, and corrected for sampling noise")
    print(f"  {'stat':<9}{'lag':>5}{'pairs':>8}{'raw r':>9}{'atten':>8}"
          f"{'true r':>9}")
    got: dict[str, dict[int, float]] = {s: {} for s in STATS}
    for stat in STATS:
        for lag in (1, 2, 3):
            xs, ys, att = [], [], []
            for t in targets:
                p, q = adj.get(t - lag), adj.get(t)
                if not p or not q:
                    continue
                for name, a in p.items():
                    b = q.get(name)
                    if not b or a[stat] is None or b[stat] is None:
                        continue
                    na, nb = _n_for(a, stat), _n_for(b, stat)
                    if na < MIN_BF or nb < MIN_BF:
                        continue
                    xs.append(a[stat])
                    ys.append(b[stat])
                    att.append((rel(na, stat) * rel(nb, stat)) ** 0.5)
            if len(xs) < 30:
                continue
            r = corr(xs, ys)
            a = st.mean(att)
            true = min(r / a, 1.0) if a else 0.0
            got[stat][lag] = true
            print(f"  {stat:<9}{lag:>5}{len(xs):>8,}{r:>9.3f}{a:>8.3f}"
                  f"{true:>9.3f}")
    print("\n  IMPLIED DECAY — each lag's true correlation over the previous")
    print(f"  {'stat':<9}{'r2/r1':>9}{'r3/r2':>9}{'geometric w':>14}")
    for stat in STATS:
        g = got[stat]
        if 1 not in g or not g[1]:
            continue
        r21 = g.get(2, 0) / g[1] if g.get(1) else 0
        r32 = g.get(3, 0) / g[2] if g.get(2) else 0
        # One w describing both steps: the cube root of r3/r1 is the
        # per-year factor if the fall is geometric.
        w = (g.get(3, 0) / g[1]) ** 0.5 if g.get(3) and g[1] else 0
        print(f"  {stat:<9}{r21:>9.3f}{r32:>9.3f}{w:>14.3f}")
    return got


def joint(adj: dict[int, dict[str, dict]], targets: list[int]):
    """Reading 2 — the three lags fitted together, shape assumed nowhere."""
    import numpy as np
    print("\n  JOINT REGRESSION, pitchers with all three lags present")
    print(f"  {'stat':<9}{'n':>7}{'lag1':>9}{'lag2':>9}{'lag3':>9}"
          f"{'R2':>8}   normalised")
    for stat in STATS:
        X, y = [], []
        for t in targets:
            if any((t - k) not in adj for k in (1, 2, 3)):
                continue
            q = adj[t]
            for name, b in q.items():
                if b[stat] is None or _n_for(b, stat) < MIN_BF:
                    continue
                past = [adj[t - k].get(name) for k in (1, 2, 3)]
                if any(p is None or p[stat] is None
                       or _n_for(p, stat) < MIN_BF for p in past):
                    continue
                X.append([1.0] + [p[stat] for p in past])
                y.append(b[stat])
        if len(y) < 40:
            print(f"  {stat:<9}{len(y):>7}   too few")
            continue
        A, b = np.array(X), np.array(y)
        beta, *_ = np.linalg.lstsq(A, b, rcond=None)
        pred = A @ beta
        ss = 1 - ((b - pred) ** 2).sum() / ((b - b.mean()) ** 2).sum()
        w = beta[1:]
        tot = w.sum()
        norm = w / tot if tot else w
        print(f"  {stat:<9}{len(y):>7}{w[0]:>9.3f}{w[1]:>9.3f}{w[2]:>9.3f}"
              f"{ss:>8.3f}   "
              + " ".join(f"{v:.2f}" for v in norm))


def _rows_for(adj, targets, stat, need_lag1: bool):
    """(actual, [(lag, rate, n)]) per pitcher-season, split by lag-1 cover.

    THE SPLIT IS THE POINT AND IT IS THE DAY-TEN TRAP. At w=0 every weight
    but lag 1's is zero, so a pitcher with no last season contributes to the
    w=1.0 arm and NOT to the w=0.0 arm — the arms would be scored on
    different populations and the extra coverage would read as accuracy.
    Intersect first: `need_lag1` True is the paired comparison, False is the
    population where an older season is the only thing there is.
    """
    rows = []
    for t in targets:
        for name, b in (adj.get(t) or {}).items():
            if b[stat] is None or _n_for(b, stat) < MIN_BF:
                continue
            past = []
            for k in (1, 2, 3):
                p = (adj.get(t - k) or {}).get(name)
                if p and p[stat] is not None and _n_for(p, stat) >= MIN_BF:
                    past.append((k, p[stat], _n_for(p, stat)))
            if not past:
                continue
            has1 = past[0][0] == 1
            if has1 == need_lag1:
                rows.append((b[stat], past))
    return rows


def _blend(past, w: float) -> float | None:
    num = den = 0.0
    for k, v, n in past:
        wt = (w ** (k - 1)) * n
        num += wt * v
        den += wt
    return num / den if den else None


def sweep(adj: dict[int, dict[str, dict]], targets: list[int]):
    """Reading 3 — the estimator itself, at each candidate decay weight.

    The prior at weight w is the batters-faced-weighted mean of the last
    three seasons with season S-k discounted by w^(k-1). w=0 is 'last season
    only', which is what `set_prior` does today; w=1 is a flat pool, which
    the memory experiment already showed costs calibration.

    Scored on how well the prior predicts the target season — a property of
    the predictor, not of anything that settles.
    """
    best = {}
    ws = [i / 10 for i in range(11)]
    print("\n  BLEND SWEEP, PITCHERS WHO HAVE LAST SEASON — does an older"
          " one add anything")
    print(f"  {'stat':<9}" + "".join(f"{w:>8.1f}" for w in ws)
          + f"{'best':>8}{'n':>8}")
    for stat in STATS:
        rows = _rows_for(adj, targets, stat, need_lag1=True)
        if len(rows) < 40:
            print(f"  {stat:<9}   too few")
            continue
        line, scores = f"  {stat:<9}", []
        for w in ws:
            xs, ys = [], []
            for act, past in rows:
                v = _blend(past, w)
                if v is not None:
                    xs.append(v)
                    ys.append(act)
            r = corr(xs, ys)
            scores.append((r, w))
            line += f"{r:>8.3f}"
        top = max(scores)
        best[stat] = top[1]
        print(line + f"{top[1]:>8.1f}{len(rows):>8,}")

    # The OTHER population, and the reason a blend might be worth having at
    # all. A man back from an elbow has no last season and currently shrinks
    # to the league — which is the worse guess if 2024 is sitting on disk.
    # Note w is irrelevant to a pitcher with only ONE older season, so the
    # question here is simply whether the older season beats league average.
    print("\n  PITCHERS WITH NO LAST SEASON — is an older one better than"
          " the league")
    print(f"  {'stat':<9}{'n':>7}{'oldest r':>10}{'lag mix':>22}")
    for stat in STATS:
        rows = _rows_for(adj, targets, stat, need_lag1=False)
        if len(rows) < 30:
            print(f"  {stat:<9}{len(rows):>7}   too few")
            continue
        xs = [_blend(p, 1.0) for _, p in rows]
        ys = [a for a, _ in rows]
        mix = {}
        for _, p in rows:
            mix[p[0][0]] = mix.get(p[0][0], 0) + 1
        print(f"  {stat:<9}{len(rows):>7}{corr(xs, ys):>10.3f}"
              + f"{str({k: mix[k] for k in sorted(mix)}):>22}")

    print("\n  correlation of the PRIOR with the season it is predicting."
          " w=0.0 is")
    print("  last season alone, w=1.0 is a flat three-season pool. A"
          " correlation of")
    print("  zero in the second table means the league average is the"
          " better target.")
    return best


def main(argv):
    pops = seasons()
    yrs = sorted(pops)
    print("  seasons on disk: " + ", ".join(
        f"{y} ({len(pops[y]):,} pitchers)" for y in yrs))
    ref = league(pops[max(yrs)])
    adj = {y: adjusted(pops[y], league(pops[y]), ref) for y in yrs}
    print(f"  league rates, {max(yrs)} as the reference environment:")
    for y in yrs:
        lg = league(pops[y])
        print(f"    {y}  " + "  ".join(f"{s} {lg[s]:.4f}" for s in STATS))
    targets = [y for y in yrs if (y - 1) in pops]
    print(f"  target seasons: {targets}")

    lag_table(adj, targets)
    joint(adj, targets)
    best = sweep(adj, targets)
    print("\n  ARGMAX w by stat: "
          + ", ".join(f"{s} {best.get(s, float('nan')):.1f}" for s in STATS))


if __name__ == "__main__":
    main(sys.argv[1:])
