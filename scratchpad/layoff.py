"""Does a pitcher back from a layoff pitch to his own pre-layoff rate?

    venv/bin/python -m scratchpad.layoff [--stat k_pct] [--gap 30]
    venv/bin/python -m scratchpad.layoff --control 0.90   (positive control)

WHAT IS BLOCKED ON THIS, and it is TODO item 12. The shrink target for a
thin current season is built from the pitcher's OWN past seasons
(`rates._load_seasons` -> `_blend_priors` -> `shrink_target`). The proposed
fix is one shrink against a DISCOUNTED prior sample, and the size of that
discount is a measurement. But before measuring HOW MUCH the career rate is
worth, this asks whether the career rate is the right TARGET AT ALL for the
population where the whole thing matters — men whose season is thin because
they were not there.

Blake Snell on 2026-08-29 is the case: 85 batters faced, a shrink target of
0.2699 sitting BELOW every one of his four seasons, and a 19-point "edge"
on his strikeout under that was our own shrinkage. If returning pitchers
come back AT their career rate, the target should be the career rate and
the current construction is simply wrong. If they come back BELOW it, part
of that pull is real and the fix is smaller than it looks.

THIS PROJECT IS 0-FOR-6 ON IMPORTED BASEBALL INTUITIONS and every counted
constant came out different from the published one. "A returning pitcher is
still himself" is an intuition. It is also directly testable, so it gets
counted.

THE DESIGN, and the three things it has to survive:

  1. MEAN REVERSION. `post - pre` is negative for anyone whose `pre` was
     lucky, and injury selects on recent performance. So the layoff group is
     compared against a CONTROL group of pitcher-seasons split the same way
     with no gap, and the group difference is also reported ADJUSTED for
     `pre` by regression. An unadjusted difference between groups whose
     `pre` distributions differ is mean reversion wearing a hat.

  2. THE CALENDAR. League strikeout rate drifts within a season and the
     layoff group's "after" sits later in the year than the control's by
     construction. Every rate here is therefore a RATIO to the league rate
     over the pitcher's own appearance dates, month by month, so a rate is
     never compared against a league it was not earned against.

  3. AN ESTIMATOR THAT CANNOT SEE. A mis-specified harness and an absent
     effect print the same table, so `--control` multiplies every
     post-layoff strikeout by a known factor and the run has to recover it.

WHAT IT CANNOT SEE. Why a man was absent is not in this database — an
elbow, a suspension, a demotion and a rest day are one gap here. That makes
this a measure of ABSENCE, not of injury, and it is the weaker question.
It is also the one the prior actually faces, because `rates` cannot see the
reason either.
"""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict

from src.context import store

#: Days between consecutive appearances that count as a layoff. 30 is a
#: fortnight beyond the longest ordinary rotation slip and comfortably past
#: a minimum IL stint.
GAP_DAYS = 30
#: A control season must have NO gap longer than this. Kept well below
#: `GAP_DAYS` so the two groups are not neighbours across one threshold.
CONTROL_MAX_GAP = 12
#: Batters faced required on EACH side of the split. Below this the ratio is
#: mostly sampling noise and the disattenuation cannot rescue it.
MIN_SIDE = 80
#: Bins for the stratified estimator. Enough to follow the shape of `pre`,
#: few enough that a bin holds several layoff arms.
NBINS = 6

STATS = ("k_pct", "bb_pct", "hr_pct")

_Q = """
select g.date date, p.player_name name, p.is_starter st,
       p.outs_recorded o, p.h h, p.bb bb, p.k k, p.hr hr
from bets.mlb_pitching p join bets.games g on g.game_id = p.game_id
where g.sport = 'mlb' and g.status = 'Final'
order by p.player_name, g.date
"""

_NUM = {"k_pct": "k", "bb_pct": "bb", "hr_pct": "hr"}


def appearances() -> dict[tuple[str, int], list[dict]]:
    """{(pitcher, season): [appearance rows in date order]}.

    Batters faced is outs + hits + walks — the same footing
    `rates.pitcher_rates` uses, so this counts what the prior is built from.
    EVERY appearance, starter or relief, for the same reason.
    """
    with store.connect() as c:
        rows = [dict(r) for r in c.execute(_Q)]
    out: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in rows:
        bf = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
        if bf < 1:
            continue
        out[(r["name"], int(r["date"][:4]))].append(
            {"date": r["date"], "bf": bf, "k": r["k"] or 0,
             "bb": r["bb"] or 0, "hr": r["hr"] or 0,
             "st": r["st"] or 0})
    for v in out.values():
        v.sort(key=lambda x: x["date"])
    return out


def league_by_month(app: dict) -> dict[str, dict[str, float]]:
    """{'YYYY-MM': {stat: league rate that month}}, weighted by batters faced.

    Month rather than season because the strikeout rate drifts within a
    year and the layoff group's return is late in it by construction.
    """
    acc: dict[str, dict[str, float]] = defaultdict(
        lambda: defaultdict(float))
    for rows in app.values():
        for r in rows:
            m = r["date"][:7]
            acc[m]["bf"] += r["bf"]
            for s, col in _NUM.items():
                acc[m][col] += r[col]
    return {m: {s: v[_NUM[s]] / v["bf"] for s in STATS}
            for m, v in acc.items() if v["bf"] > 0}


def _rel(rows: list[dict], lg: dict, stat: str):
    """(observed / league-expected, batters faced) over these appearances.

    A RATIO, not a difference: it is scale-free, so a 10% drop means the
    same thing in April and August, and it is what `_prior_adjusted`
    already does when it moves a season onto another run environment.
    """
    bf = sum(r["bf"] for r in rows)
    obs = sum(r[_NUM[stat]] for r in rows)
    exp = sum(r["bf"] * lg[r["date"][:7]][stat] for r in rows
              if r["date"][:7] in lg)
    if bf < 1 or exp <= 0:
        return None, 0
    return obs / exp, bf


def split(rows: list[dict]) -> tuple[int, int]:
    """(index of the largest gap, that gap in days).

    The split index is the first appearance AFTER the gap, so `rows[:i]` is
    everything before it.
    """
    best_i, best_d = 0, 0
    for i in range(1, len(rows)):
        a, b = rows[i - 1]["date"], rows[i]["date"]
        d = (_ord(b) - _ord(a))
        if d > best_d:
            best_i, best_d = i, d
    return best_i, best_d


def _ord(iso: str) -> int:
    from datetime import date
    return date.fromisoformat(iso).toordinal()


def _median_split(rows: list[dict]) -> int:
    """Index that puts half the batters faced on each side."""
    total = sum(r["bf"] for r in rows)
    run = 0
    for i, r in enumerate(rows):
        run += r["bf"]
        if run >= total / 2:
            return i + 1
    return len(rows)


def build(stat: str, gap_days: int, control_k: float | None,
          starters: bool = False):
    """Both groups, as (pre_ratio, post_ratio, pre_bf, post_bf) per season.

    `starters` keeps only pitcher-seasons that are mostly STARTS, on both
    sides of the split. The unrestricted population mixes an injured
    starter with a reliever riding the shuttle to Triple-A, and only the
    first is the case the prior has to get right.
    """
    app = appearances()
    lg = league_by_month(app)
    layoff, control = [], []
    for (name, season), rows in app.items():
        if len(rows) < 4:
            continue
        if starters and (sum(r["st"] for r in rows) / len(rows)) < 0.8:
            continue
        i, gap = split(rows)
        if gap >= gap_days:
            grp, cut = layoff, i
        elif gap < CONTROL_MAX_GAP:
            grp, cut = control, _median_split(rows)
        else:
            continue
        pre, post = rows[:cut], rows[cut:]
        if control_k is not None and grp is layoff:
            # POSITIVE CONTROL: a known multiplicative hit to the returning
            # side only. The estimator must read back `control_k`.
            # THE COLUMN MUST FOLLOW `stat`. A first version hard-coded
            # "k" here, so `--stat hr_pct --control 1.20` injected into
            # STRIKEOUTS and printed the null run's numbers to four
            # decimals — a positive control that silently controlled
            # nothing, which is worse than not running one.
            col = _NUM[stat]
            post = [{**r, col: r[col] * control_k} for r in post]
        a, na = _rel(pre, lg, stat)
        b, nb = _rel(post, lg, stat)
        if a is None or b is None or na < MIN_SIDE or nb < MIN_SIDE:
            continue
        grp.append({"name": name, "season": season, "pre": a, "post": b,
                    "pre_bf": na, "post_bf": nb, "gap": gap})
    return layoff, control


def _mean_se(xs):
    n = len(xs)
    if n < 2:
        return 0.0, 0.0
    return st.mean(xs), st.stdev(xs) / (n ** 0.5)


def _ols(rows, key_y, keys_x):
    """Least squares with an intercept. Returns (coefs, se) including it."""
    import math
    n = len(rows)
    p = len(keys_x) + 1
    X = [[1.0] + [r[k] for k in keys_x] for r in rows]
    y = [r[key_y] for r in rows]
    XtX = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(p)]
           for a in range(p)]
    Xty = [sum(X[i][a] * y[i] for i in range(n)) for a in range(p)]
    inv = _inv(XtX)
    beta = [sum(inv[a][b] * Xty[b] for b in range(p)) for a in range(p)]
    resid = [y[i] - sum(beta[a] * X[i][a] for a in range(p))
             for i in range(n)]
    s2 = sum(e * e for e in resid) / (n - p)
    se = [math.sqrt(max(s2 * inv[a][a], 0.0)) for a in range(p)]
    return beta, se


def _inv(m):
    n = len(m)
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(n)]
         for i, row in enumerate(m)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[piv] = a[piv], a[col]
        d = a[col][col]
        a[col] = [v / d for v in a[col]]
        for r in range(n):
            if r == col:
                continue
            f = a[r][col]
            if f:
                a[r] = [v - f * w for v, w in zip(a[r], a[col])]
    return [row[n:] for row in a]


def main(argv):
    stat = "k_pct"
    gap_days = GAP_DAYS
    control_k = None
    for i, a in enumerate(argv):
        if a == "--stat":
            stat = argv[i + 1]
        elif a == "--gap":
            gap_days = int(argv[i + 1])
        elif a == "--control":
            control_k = float(argv[i + 1])

    layoff, control = build(stat, gap_days, control_k,
                            starters="--starters" in argv)
    if "--starters" in argv:
        print("\n  ** STARTERS ONLY: >=80% of appearances are starts **")
    print(f"\n  LAYOFF vs CONTROL — {stat}, gap >= {gap_days}d, "
          f"each side >= {MIN_SIDE} BF")
    if control_k is not None:
        print(f"  ** POSITIVE CONTROL: post-layoff {stat} x {control_k:.3f}"
              f" — the adjusted difference must read"
              f" {control_k - 1:+.3f} **")
    print(f"\n  {'group':<10}{'n':>6}{'pre':>8}{'post':>8}{'post-pre':>10}"
          f"{'se':>8}{'pre BF':>9}{'post BF':>9}{'gap d':>8}")
    for lbl, grp in (("layoff", layoff), ("control", control)):
        if not grp:
            print(f"  {lbl:<10}{0:>6}   — nothing qualified")
            continue
        d = [r["post"] - r["pre"] for r in grp]
        m, se = _mean_se(d)
        print(f"  {lbl:<10}{len(grp):>6}"
              f"{st.mean([r['pre'] for r in grp]):>8.4f}"
              f"{st.mean([r['post'] for r in grp]):>8.4f}"
              f"{m:>+10.4f}{se:>8.4f}"
              f"{st.median([r['pre_bf'] for r in grp]):>9.0f}"
              f"{st.median([r['post_bf'] for r in grp]):>9.0f}"
              f"{st.median([r['gap'] for r in grp]):>8.0f}")

    if not layoff or not control:
        return
    # THE HEADLINE, and it is the ADJUSTED one. `post - pre` carries mean
    # reversion, which is real and is not what is being asked; regressing on
    # `pre` removes the part of the fall that any group with that `pre`
    # would have shown.
    rows = ([{**r, "grp": 1.0} for r in layoff]
            + [{**r, "grp": 0.0} for r in control])
    beta, se = _ols(rows, "post", ["grp", "pre"])
    z = beta[1] / se[1] if se[1] else 0.0
    print(f"\n  ADJUSTED FOR `pre` — post ~ intercept + group + pre,"
          f" n = {len(rows):,}")
    print(f"    layoff effect  {beta[1]:>+8.4f} +/- {se[1]:.4f}   z {z:+.2f}")
    print(f"    slope on pre   {beta[2]:>+8.4f} +/- {se[2]:.4f}")
    print(f"    intercept      {beta[0]:>+8.4f}")
    print(f"\n  A layoff effect of {beta[1]:+.4f} means a returning pitcher"
          f" lands at\n  {1 + beta[1]:.3f} of what his pre-layoff rate"
          f" predicts, all else equal.")

    # STRATIFIED ON `pre`, AND THIS IS THE ESTIMATOR TO TRUST ON A NOISY
    # STAT. The regression above corrects the group difference in `pre` by
    # multiplying it by the fitted slope — and that slope is ATTENUATED by
    # sampling noise in `pre`, badly so on home runs where it reads 0.22.
    # Under-correcting leaves a real difference in group talent sitting in
    # the group dummy, which is indistinguishable from a layoff effect.
    #
    # This bins the POOLED sample on `pre`, takes the layoff-minus-control
    # difference in `post` WITHIN each bin, and averages them weighted by
    # layoff count. It assumes no functional form at all. Bins with no
    # layoff arms or no controls contribute nothing and are reported, since
    # a group difference that lives entirely outside the common support is
    # not an effect, it is an extrapolation.
    print(f"\n  STRATIFIED ON `pre` — no slope assumed, {NBINS} bins")
    print(f"  {'bin':<14}{'n lay':>7}{'n ctl':>7}{'lay post':>10}"
          f"{'ctl post':>10}{'diff':>9}")
    allp = sorted(r["pre"] for r in rows)
    edges = [allp[int(len(allp) * i / NBINS)] for i in range(1, NBINS)]

    def _bin(v):
        b = 0
        while b < len(edges) and v >= edges[b]:
            b += 1
        return b
    num = den = 0.0
    var = 0.0
    dropped_l = dropped_c = 0
    for b in range(NBINS):
        L = [r for r in layoff if _bin(r["pre"]) == b]
        C = [r for r in control if _bin(r["pre"]) == b]
        lo = "-inf" if b == 0 else f"{edges[b-1]:.2f}"
        hi = "inf" if b == NBINS - 1 else f"{edges[b]:.2f}"
        if len(L) < 3 or len(C) < 3:
            dropped_l += len(L)
            dropped_c += len(C)
            print(f"  {lo:>6}-{hi:<7}{len(L):>7}{len(C):>7}"
                  f"{'':>10}{'':>10}{'  (too thin)':>9}")
            continue
        ml, sl = _mean_se([r["post"] for r in L])
        mc, sc = _mean_se([r["post"] for r in C])
        w = len(L)
        num += w * (ml - mc)
        den += w
        var += (w ** 2) * (sl ** 2 + sc ** 2)
        print(f"  {lo:>6}-{hi:<7}{len(L):>7}{len(C):>7}{ml:>10.4f}"
              f"{mc:>10.4f}{ml - mc:>+9.4f}")
    if den:
        eff = num / den
        see = (var ** 0.5) / den
        print(f"\n    stratified effect  {eff:>+8.4f} +/- {see:.4f}"
              f"   z {eff / see if see else 0:+.2f}")
        print(f"    dropped to thin bins: {dropped_l} layoff,"
              f" {dropped_c} control")
        print(f"    COMPARE the regression's {beta[1]:+.4f}. A large"
              f" disagreement means the\n    slope correction was doing"
              f" the work, and on a noisy stat it cannot.")

    # AND THE SLOPE, SEPARATELY. A group can be unbiased in level and still
    # have a less predictive past, which is the other thing the prior needs
    # to know: it argues for a smaller effective sample, not a shifted one.
    print(f"\n  SLOPE ON `pre` WITHIN EACH GROUP — how much the past"
          f" carries\n  {'group':<10}{'n':>6}{'slope':>9}{'se':>8}{'z':>7}")
    for lbl, grp in (("layoff", layoff), ("control", control)):
        if len(grp) < 20:
            continue
        b, s = _ols(grp, "post", ["pre"])
        print(f"  {lbl:<10}{len(grp):>6}{b[1]:>9.4f}{s[1]:>8.4f}"
              f"{b[1] / s[1] if s[1] else 0:>7.1f}")
    print("\n  A LOWER SLOPE IS NOT A LOWER LEVEL. The level says where to")
    print("  aim the target; the slope says how much weight it deserves.")

    # THE STABILITY GATE. One pooled number over four seasons can be one
    # season's accident. A mechanism that is real repeats.
    print(f"\n  PER SEASON — the same adjusted layoff effect"
          f"\n  {'season':<8}{'n lay':>7}{'n ctl':>7}{'effect':>9}{'se':>8}"
          f"{'z':>7}")
    for yr in sorted({r["season"] for r in rows}):
        sub = [r for r in rows if r["season"] == yr]
        nl = sum(1 for r in sub if r["grp"])
        if nl < 15 or len(sub) - nl < 15:
            continue
        b, s_ = _ols(sub, "post", ["grp", "pre"])
        print(f"  {yr:<8}{nl:>7}{len(sub) - nl:>7}{b[1]:>+9.4f}"
              f"{s_[1]:>8.4f}{b[1] / s_[1] if s_[1] else 0:>+7.2f}")


if __name__ == "__main__":
    main(sys.argv[1:])
