"""THE PER-ARM HOOK OFFSET, FITTED ON THE DECISION — TODO item 32.

    venv/bin/python -m src.context.armhook [--build] [--before YYYY-MM-DD]
                                           [--limit N] [--rows PATH]

WHAT THIS IS AND HOW IT DIFFERS FROM `leash.py`, because the two are the
same mechanism fitted on two different quantities and only one of them is
the quantity the hook consumes.

`leash.py` measures a pitcher's OUTS residual against a full simulation and
converts it to log-odds through an interpolated table (`OUTS_PER_OFFSET`).
That is the upstream proxy: outs are the OUTPUT of a chain the hook only
starts, so the residual carries every other error in that chain — the rate
model, the traffic, the bullpen that finished the inning — and the
conversion has to undo a Monte-Carlo derivative to get back to the decision.

This module fits the offset ON THE DECISION ITSELF. The target is the real
manager's binary pull/leave at a real game state, the parameter is a
log-odds offset, and the two are in the same units with nothing in between.
That is "FIT THE QUANTITY THAT SETTLES, NOT THE UPSTREAM PROXY" (CLAUDE.md)
applied to a term that currently does the opposite.

WHY IT IS WORTH FITTING TWICE. `scratchpad/hook_resid.py` measured what the
shipped leash LEAVES BEHIND, on 89,414 boundary and 303,276 mid real
decisions with standard errors clustered on (game, side):

  * the per-arm residual REPEATS YEAR OVER YEAR — estimate on season N,
    score on N+1 — at r +0.538 boundary (147 arm-pairs) and +0.373 mid
    (402 arm-pairs). That is the only form a live hook could ever use;
  * its correlation with the shipped `sim.leash` offset is only -0.399, so
    ~84% of the variance is not in today's table;
  * and the sign of that correlation says the leash OVERSHOOTS. On the
    holdout, boundary residual by offset bucket: no entry +0.0291 (z +4.4),
    < -0.5 +0.0069, < 0.15 +0.0013, < 0.5 -0.0356 (z -3.3). The model both
    under-pulls the arms it thinks go long and over-pulls the arms it thinks
    come out early — it spreads pitchers too far apart, which is what a
    converted proxy with a noisy derivative does.

FOUR THINGS ARE MEASURED HERE AND NONE IS SEARCHED.

  1. THE OFFSET. For one arm it is the MLE of a single log-odds shift on a
     fixed linear predictor: the δ solving Σ y = Σ sigmoid(logit p + δ)
     over his decisions. One parameter, one monotone solve, no regression
     and no library.
  2. ITS VARIANCE, CLUSTER-ROBUST on (game, side). Six boundary decisions
     from one start are one manager on one night, and treating them as six
     draws would understate the noise and under-shrink every arm. The
     sandwich estimator is in `_solve`.
  3. THE SHRINKAGE, by method of moments across arms — between-variance is
     the spread of the estimates MINUS the mean sampling variance, which is
     the normal-normal posterior `leash.shrink_k` uses, except that here
     each arm gets his OWN weight because his own sample size and state mix
     set his own variance. A shrinkage handed to a grid search is what
     turns this from a measurement into a fit, and a fitted shrinkage
     absorbs whatever else is wrong with the hook.
  4. THE TWO CURVES SEPARATELY — rule 9. Boundary and mid-inning are
     DIFFERENT DECISIONS (63.2% / 36.8%, and pitch count does not
     distinguish them at all), and their per-arm reliabilities differ by a
     factor of 1.4. Pooling them would fit a manager who makes one decision.

AND ONE THING IS FITTED AND DELIBERATELY THROWN AWAY: a per-SEASON league
offset, solved on the same machinery and subtracted before any arm is
measured. TODO 33 established that the hazard tables are era-stale — at a
fixed state the model matches 2023 and misses 2026 by +0.11 in the sixth —
so an arm whose career sits mostly in one season would otherwise be handed
that season's league drift as if it were his own leash. Fitting against the
season offsets and SHIPPING NONE OF THEM is "club first, pitcher against
the remainder" applied to the calendar: it keeps this item orthogonal to 33
so the two compose instead of double-counting. The season table is not
shippable anyway (33's own note: a 2026 table can only be built from
pre-holdout 2026 rows, so the current manager is never measured when he is
needed).

THE POPULATION IS `leash.intended_starters`, for the reason that module
records at length: an opener who opened five times is a ROLE wearing a
leash's clothes, `USE_OPENER_EXIT` already models him, and because those
arms also set the shrinkage constant they would loosen it for every genuine
starter. The gate reads the 75th percentile of a man's own starts, never
the mean, so a starter who was sent out for six and shelled in the second
stays in — he is the observation carrying the signal.

FOLD DISCIPLINE. Rows filter to `date < before` (default `HOLDOUT`) BEFORE
fitting, and `before` bounds the intent gate too. `sim.USE_ARM_HOOK` is
forced OFF for the duration of the fit: the residual has to be measured
against the hook WITHOUT this mechanism or a rebuild folds its own
correction back in, which is the double-count guard `leash._sim_one` needs
for the same reason.
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict

from src.context import sim
from src.context.holdout import HOLDOUT

_HERE = os.path.dirname(os.path.abspath(__file__))
PATH = _HERE + "/hook_arm.json"

#: Decisions of one kind an arm needs before he is written at all. The
#: shrinkage already does the right thing below it — a thin sample has a
#: large variance and is pulled almost to zero — so this is not a
#: statistical floor but a degeneracy one: an arm with no removal at all in
#: eight decisions has an MLE at minus infinity and nothing useful to say.
MIN_DECISIONS = 25

#: Distinct (game, side) clusters — real STARTS — an arm needs before his
#: variance is believed. Below it the cluster-robust sandwich cannot be
#: estimated: at one cluster it is exactly zero by construction, which would
#: hand the least trustworthy arm in the table a shrinkage weight of 1.0.
MIN_CLUSTERS = 5

#: Nobody gets a leash the league does not contain. This is generous on
#: purpose — it is a guard against a degenerate solve escaping, not a
#: parameter — and `build` PRINTS how many arms it binds on so a clamp that
#: starts doing real work cannot do it silently. The shipped table's widest
#: entry should sit well inside it; if it does not, the shrinkage is wrong
#: and that is the thing to fix.
ARM_CLAMP = 1.0

#: Bisection bracket for the per-arm solve, in log-odds. Wider than
#: `ARM_CLAMP` so the clamp is applied to a CONVERGED estimate rather than
#: hiding a solve that ran out of room.
_BRACKET = 8.0


def _sigmoid(x: float) -> float:
    if x < -35:
        return 0.0
    if x > 35:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def _logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


# ── the one-parameter solve ────────────────────────────────────────────

def _solve(rows: list[dict], base: float = 0.0) -> tuple[float, float, int]:
    """(offset, cluster-robust variance, n) for one group of decisions.

    `rows` carry `p` (the shipped hook's probability), `removed` and a
    cluster id. `base` is an offset already attributed to a wider group —
    the season — which the arm is fitted AGAINST rather than re-absorbing.

    The estimate is the MLE of a single shift on a fixed linear predictor,
    found by bisection on the score Σ(y - p(δ)), which is monotone
    decreasing in δ. Newton would converge faster and would need a
    derivative guard at the boundary; this runs in microseconds on a few
    hundred rows and cannot diverge.

    THE VARIANCE IS THE SANDWICH, clustered on (game, side). The bread is
    the Fisher information Σ p(1-p); the meat is the sum of SQUARED CLUSTER
    SUMS of the score residuals. Independent rows would make the two equal
    and the sandwich collapse to 1/I, so this is strictly the honest
    version of the same number rather than a different one.
    """
    n = len(rows)
    if not n:
        return 0.0, float("inf"), 0
    lo = [_logit(r["p"]) + base for r in rows]
    y = [1.0 if r["removed"] else 0.0 for r in rows]
    target = sum(y)

    def score(d: float) -> float:
        return target - sum(_sigmoid(x + d) for x in lo)

    a, b = -_BRACKET, _BRACKET
    if score(a) <= 0:
        return -_BRACKET, float("inf"), n
    if score(b) >= 0:
        return _BRACKET, float("inf"), n
    for _ in range(80):
        m = (a + b) / 2
        if score(m) > 0:
            a = m
        else:
            b = m
    d = (a + b) / 2

    info = 0.0
    byc: dict = defaultdict(float)
    for r, x, yi in zip(rows, lo, y):
        p = _sigmoid(x + d)
        info += p * (1 - p)
        byc[r["cluster"]] += yi - p
    if info <= 0:
        return d, float("inf"), n
    # A SANDWICH NEEDS CLUSTERS TO COUNT. With one cluster the score
    # residuals sum to zero BY CONSTRUCTION — that is the equation `d`
    # solves — so the meat is exactly 0 and the variance comes back 0,
    # which would hand that arm a shrinkage weight of 1.0 and no shrinkage
    # at all. An arm whose decisions are one night is the least trustworthy
    # arm in the table, not the most. Found by
    # `check_the_variance_is_cluster_robust`.
    g = len(byc)
    if g < MIN_CLUSTERS:
        return d, float("inf"), n
    # The usual finite-cluster scaling, so a handful of clusters is not
    # reported as if it were hundreds.
    meat = sum(v * v for v in byc.values()) * g / (g - 1)
    return d, meat / (info * info), n


def yoy_reliability(rs: list[dict], season: dict,
                    min_n: int = 120) -> tuple[float, int]:
    """(r, pairs) — does an arm's offset carry to his NEXT season?

    THE SECOND SHRINKAGE, AND THE ONE THAT MATTERS MOST. `_eb` removes
    SAMPLING noise: it answers "how much of the spread in these estimates
    is real". It cannot answer the question a live hook actually asks, which
    is "how much of what was real LAST year is still true THIS year" — an
    arm ages, changes clubs and managers, and the league drifts under him.
    Those are different quantities and the difference is large: shrinking
    for sampling noise alone leaves an estimate that describes his past
    correctly and OVER-CORRECTS his future.

    That over-correction is not hypothetical. It is the established defect
    in the shipped `sim.leash`, which spreads pitchers too far apart and
    misses at BOTH ends (+0.0291 on arms it has no entry for, -0.0356 on
    arms it thinks come out early). A term fitted on four pooled seasons and
    applied to the next one has to be multiplied by how much of it survives
    the year, and that number is MEASURED here on the training rows rather
    than imported or assumed.

    Estimated on the same machinery as everything else: one solve per
    (arm, season) against the same season offsets, consecutive seasons
    paired, Pearson r over arms with at least `min_n` decisions in both.
    """
    cells: dict = defaultdict(list)
    for r in rs:
        cells[(r["name"], r["date"][:4])].append(r)
    per: dict = {}
    for (nm, s), v in cells.items():
        if len(v) >= min_n:
            per[(nm, s)] = _solve(v, base=season.get(s, 0.0))[0]
    pairs = [(per[(nm, s)], per[(nm, str(int(s) + 1))])
             for (nm, s) in per if (nm, str(int(s) + 1)) in per]
    if len(pairs) < 25:
        # None, NOT 0.0. Returning zero would multiply every offset by zero
        # and write a table of zeros that loads, validates and does nothing
        # — a mechanism that silently disables itself on a short window is
        # worse than one that fails. `fit` refuses instead.
        return None, len(pairs)
    mx = sum(p[0] for p in pairs) / len(pairs)
    my = sum(p[1] for p in pairs) / len(pairs)
    num = sum((x - mx) * (y - my) for x, y in pairs)
    dx = sum((x - mx) ** 2 for x, _ in pairs) ** 0.5
    dy = sum((y - my) ** 2 for _, y in pairs) ** 0.5
    r = num / (dx * dy) if dx and dy else 0.0
    return max(0.0, min(1.0, r)), len(pairs)


def _centre(offs: dict, n_by: dict) -> tuple[dict, float]:
    """Subtract the DECISION-WEIGHTED mean, so the term redistributes only.

    A per-arm offset must not move the league level: the level belongs to
    the hook's own intercept and the counted hazard tables, and a term that
    shifts it is competing with them instead of telling arms apart. This is
    the centring convention `AIR_HR_PIT` had to be given after its
    falsifier fired on exactly this — a table that only redistributes moved
    a LEVEL row in all four folds because it was centred over the counting
    sample rather than over the population it fires in.

    The weights are each arm's own decision count, which is the population
    the offsets fire in: an arm who starts thirty times is weighted thirty
    starts' worth. Returns the applied mean that was removed so it can be
    reported rather than assumed to be small.
    """
    if not offs:
        return offs, 0.0
    tot = sum(n_by.get(k, 0) for k in offs) or 1
    mean = sum(v * n_by.get(k, 0) for k, v in offs.items()) / tot
    return ({k: v - mean for k, v in offs.items()}, mean)


def _eb(est: dict, carry: float = 1.0) -> tuple[dict, float, float]:
    """Empirical-Bayes shrink {unit: (offset, var, n)} -> {unit: shrunk}.

    `carry` is the measured year-over-year reliability from
    `yoy_reliability` — the share of a real per-arm offset that survives
    into the season it will be used in. 1.0 reproduces the sampling-noise-
    only shrinkage, which is what this did before the clamp started binding
    on forty arms and said it was wrong.

    Between-variance by method of moments: the spread of the estimates MINUS
    the mean sampling variance, floored at zero. Each arm is then weighted
    by his OWN precision, which is the part a single K cannot express — an
    arm with 400 boundary decisions and an arm with 30 do not deserve the
    same pull toward the league even when their raw numbers agree.

    Returns (shrunk offsets, between_sd, mean within_sd) so `build` can
    report the three numbers this is all resting on.
    """
    usable = {u: v for u, v in est.items()
              if v[2] >= MIN_DECISIONS and math.isfinite(v[1])}
    if len(usable) < 3:
        return {}, 0.0, 0.0
    ds = [v[0] for v in usable.values()]
    vs = [v[1] for v in usable.values()]
    mean_d = sum(ds) / len(ds)
    spread = sum((d - mean_d) ** 2 for d in ds) / (len(ds) - 1)
    within = sum(vs) / len(vs)
    between = max(spread - within, 0.0)
    out = {}
    for u, (d, v, _n) in usable.items():
        w = carry * (between / (between + v) if (between + v) > 0 else 0.0)
        # Shrunk toward the LEAGUE (zero), not toward the mean of these
        # arms: the hook's own intercept is the league, and the season
        # offsets above have already taken each season's level out, so the
        # decision-weighted mean estimate is zero by construction. `fit`
        # PRINTS that mean rather than asserting it — a per-arm term must
        # not move the level, and this is the number that says whether it
        # does.
        out[u] = max(-ARM_CLAMP, min(ARM_CLAMP, w * d))
    return out, between ** 0.5, within ** 0.5


# ── rows ───────────────────────────────────────────────────────────────

def decision_rows(before: str | None = None, limit: int | None = None,
                  verbose: bool = True) -> list[dict]:
    """Real starter decisions, with everything the shipped hook reads.

    Built from `boundary.decisions` — the canonical row source, the one
    CLAUDE.md's holdout rule names — plus the three joins it does not carry:
    the date, the PITCHING club and the pitcher's name, which is the key
    both offset tables are stored under.
    """
    from src import db
    from src.context import boundary, store
    from src.context.sources import pbp

    games: dict = {}
    with db.connect() as c:
        for r in c.execute("select game_id, date, away_team_abbr, "
                           "home_team_abbr from games where sport='mlb'"):
            games[r["game_id"]] = dict(r)
    names: dict = {}
    with store.connect() as c:
        for r in c.execute("select pitcher_id, player_name from mlb_stints "
                           "where player_name is not null"):
            names.setdefault(int(r["pitcher_id"]), r["player_name"])

    ids = [g for g in pbp.final_games() if g in games]
    if before:
        ids = [g for g in ids if games[g]["date"] < before]
    ids.sort(key=lambda g: games[g]["date"])
    if limit:
        ids = ids[:limit]
    out: list[dict] = []
    for i, gid in enumerate(ids, 1):
        if not pbp.have(gid):
            continue
        try:
            rows = boundary.decisions(gid)
        except Exception:
            continue
        g = games[gid]
        for r in rows:
            nm = names.get(r["pitcher"])
            if not nm:
                continue
            r["date"] = g["date"]
            r["name"] = nm
            r["team"] = (g["home_team_abbr"] if r["side"] == "home"
                         else g["away_team_abbr"])
            r["cluster"] = (gid, r["side"])
            out.append(r)
        if verbose and i % 1000 == 0:
            print(f"  {i}/{len(ids)} games, {len(out):,} decisions",
                  flush=True)
    return out


def load_rows(path: str, before: str | None = None) -> list[dict]:
    """A prebuilt row dump (`scratchpad/fit_hooks.py`'s cache), for speed.

    THE SAME ROWS FROM THE SAME FUNCTION — that cache is `boundary.
    decisions` over every cached game — so this is an optimisation and not
    a second definition. It re-derives `team`, `name` and `cluster` here
    rather than trusting whatever the dump happens to carry, because a
    silently missing key would fit every arm under the name "".
    """
    from src import db
    from src.context import store
    with open(path) as f:
        rows = json.load(f)
    games: dict = {}
    with db.connect() as c:
        for r in c.execute("select game_id, date, away_team_abbr, "
                           "home_team_abbr from games where sport='mlb'"):
            games[r["game_id"]] = dict(r)
    names: dict = {}
    with store.connect() as c:
        for r in c.execute("select pitcher_id, player_name from mlb_stints "
                           "where player_name is not null"):
            names.setdefault(int(r["pitcher_id"]), r["player_name"])
    out = []
    for r in rows:
        g = games.get(r["game_id"])
        nm = names.get(int(r["pitcher"])) if r.get("pitcher") else None
        if not g or not nm:
            continue
        if before and g["date"] >= before:
            continue
        r["date"] = g["date"]
        r["name"] = nm
        r["team"] = (g["home_team_abbr"] if r["side"] == "home"
                     else g["away_team_abbr"])
        r["cluster"] = (r["game_id"], r["side"])
        out.append(r)
    return out


def predict(rows: list[dict]) -> None:
    """`p` on every row, from the SHIPPED hook at the SHIPPED call sites.

    THE CONDITIONING MATCHES THE CODE PATH (rule 10): every argument is the
    one `game._half_inning` passes, including the club and pitcher offsets
    through `sim.for_start`, the calendar term behind its flag and the hard
    pitch cap. TWO EXCEPTIONS, stated rather than hidden, and both are the
    ones `scratchpad/hook_resid.py` documents:

      * `pen` (arms unavailable, club rest) is not reconstructed — these
        rows do not carry a club's rolling bullpen state. It is a CENTRED
        term, so it contributes zero on average;
      * `forced_exit_outs` is the opener path, and openers are gated out of
        this population anyway.
    """
    base = sim.Hook()
    hooks: dict = {}
    for r in rows:
        key = (r["team"], r["name"])
        h = hooks.get(key)
        if h is None:
            h = hooks[key] = sim.for_start(base, r["team"], r["name"])
        gap = sim.layoff_gap(r["name"], r["date"])
        if r["ends_inning"]:
            p = h.removal_p(
                r["pitches"], r["runs"], r["inning"], r["br"], r["margin"],
                inning_runs=r["inn_runs"], pen=None, layoff_gap=gap,
                month_offset=(sim.bnd_month_offset(r["date"])
                              if sim.USE_HOOK_MONTH else 0.0))
        else:
            p = h.mid_removal_p(
                r["pitches"], r["runs"], r["onbase"], r["inn_dmg"],
                r["margin"], inning_runs=r["inn_runs"], inning=r["inning"],
                inning_br=r["inn_br"], k_rate=r["k_rate"], pen=None,
                layoff_gap=gap)
        if r["pitches"] >= h.hard_pitch_cap:
            p = 1.0
        r["p"] = p


# ── the fit ────────────────────────────────────────────────────────────

def fit(rows: list[dict], before: str | None = None,
        verbose: bool = True, keep: set | None = None,
        carry: float | None = None) -> dict:
    """{curve: {pitcher: offset}} plus a `_meta` dict, from real decisions.

    Separated from `build` so the whole fit can be tested on hand-made rows
    with no database and no play-by-play behind it — which is why `keep`
    (the intent-gated population) can be handed in rather than queried.
    """
    rows = [r for r in rows if not before or r["date"] < before]
    if keep is None:
        from src.context import leash as leash_mod
        try:
            keep = leash_mod.intended_starters(before=before)
        except Exception:                              # pragma: no cover
            keep = None
    if keep:
        before_n = len(rows)
        rows = [r for r in rows if r["name"] in keep]
        if verbose:
            print(f"  intent gate: {before_n:,} -> {len(rows):,} decisions "
                  f"({len(keep)} arms sent out for length)")

    out: dict = {}
    meta: dict = {}
    for curve, want in (("bnd", True), ("mid", False)):
        rs = [r for r in rows if bool(r["ends_inning"]) is want]
        if not rs:
            out[curve] = {}
            continue
        # THE SEASON OFFSET, fitted and thrown away — see the module
        # docstring. Solved on the same machinery so it cannot disagree
        # with the per-arm solve about what an offset means.
        season: dict = {}
        for s, v in _group(rs, lambda r: r["date"][:4]).items():
            season[s] = _solve(v)[0]
        measured, pairs = yoy_reliability(rs, season)
        use = carry if carry is not None else measured
        if use is None:
            raise ValueError(
                f"{curve}: the year-over-year reliability is not estimable "
                f"({pairs} arm-pairs, 25 needed) and it is the shrinkage "
                f"that keeps this term from over-correcting. Widen the "
                f"window or pass an explicit carry; do NOT default it to 1.0")
        est: dict = {}
        n_by: dict = {}
        for nm, v in _group(rs, lambda r: r["name"]).items():
            n_by[nm] = len(v)
            # One base per arm is an approximation when a career straddles
            # seasons — the exact version would carry a per-ROW base. It
            # does: `_solve` takes a scalar, so the base is the arm's own
            # decision-weighted mean season offset, which is the offset his
            # rows actually sat under.
            b = sum(season.get(r["date"][:4], 0.0) for r in v) / len(v)
            est[nm] = _solve(v, base=b)
        offs, between, within = _eb(est, carry=use)
        # Counted BEFORE centring, which shifts every value off the clamp
        # and would report zero however hard the clamp was working.
        clamped = sum(1 for v in offs.values()
                      if abs(abs(v) - ARM_CLAMP) < 1e-9)
        offs, applied = _centre(offs, n_by)
        out[curve] = {k: round(v, 4) for k, v in offs.items()}
        meta[curve] = {
            "decisions": len(rs), "arms_seen": len(est),
            "arms_written": len(offs),
            "yoy_r": round(use, 4), "yoy_pairs": pairs,
            "yoy_measured": (round(measured, 4)
                             if measured is not None else None),
            "applied_mean_removed": round(applied, 4),
            "between_sd": round(between, 4), "within_sd": round(within, 4),
            "season_offsets": {s: round(v, 4) for s, v in sorted(
                season.items())},
            "clamped": clamped,
        }
        if verbose:
            print(f"  {curve}: {len(rs):,} decisions, {len(est)} arms, "
                  f"{len(offs)} written   between sd {between:.4f}, "
                  f"within sd {within:.4f}")
            print("    season offsets " + "  ".join(
                f"{s} {v:+.3f}" for s, v in sorted(season.items())))
            print(f"    year-over-year r {use:+.3f} over {pairs} "
                  f"arm-pairs — the share that carries forward")
            if offs:
                vals = sorted(offs.values())
                sd = (sum(v * v for v in vals) / len(vals)) ** 0.5
                print(f"    shipped sd {sd:.4f}  range {vals[0]:+.3f} to "
                      f"{vals[-1]:+.3f}  level removed {applied:+.4f}  "
                      f"clamped {meta[curve]['clamped']}")
    out["_meta"] = {"before": before, "hook_hash": sim.hook_hash(),
                    **meta}
    return out


def _group(rows: list[dict], keyfn) -> dict:
    out: dict = defaultdict(list)
    for r in rows:
        k = keyfn(r)
        if k:
            out[k].append(r)
    return dict(out)


def build(before: str | None = HOLDOUT, path: str = PATH,
          limit: int | None = None, rows_path: str | None = None) -> dict:
    """Measure, shrink, persist. Returns the mapping.

    `sim.USE_ARM_HOOK` is forced off for the duration: the offsets are a
    residual against the hook WITHOUT them, and fitting on top of a table
    already in effect would fold the correction back into itself on every
    rebuild. Guarded by a mutation-verified check.
    """
    was = sim.USE_ARM_HOOK
    sim.USE_ARM_HOOK = False
    try:
        rows = (load_rows(rows_path, before=before) if rows_path
                else decision_rows(before=before, limit=limit))
        print(f"  {len(rows):,} decisions before {before}")
        predict(rows)
        data = fit(rows, before=before)
    finally:
        sim.USE_ARM_HOOK = was
    with open(path, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    print(f"  wrote {path}")
    for curve in ("bnd", "mid"):
        offs = data.get(curve) or {}
        if not offs:
            continue
        ranked = sorted(offs.items(), key=lambda kv: kv[1])
        print(f"\n  {curve.upper()} — LONGEST LEASH (negative = left in)")
        for nm, o in ranked[:6]:
            print(f"    {nm:<26}{o:>+8.3f}")
        print(f"  {curve.upper()} — SHORTEST LEASH")
        for nm, o in ranked[-6:]:
            print(f"    {nm:<26}{o:>+8.3f}")
    return data


def main() -> None:
    args = sys.argv[1:]
    before = HOLDOUT
    if "--before" in args:
        before = args[args.index("--before") + 1]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    rows_path = args[args.index("--rows") + 1] if "--rows" in args else None
    if "--build" in args:
        build(before=before, limit=limit, rows_path=rows_path)
        return
    try:
        with open(PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        print("  no hook_arm.json — run with --build")
        return
    meta = data.get("_meta", {})
    print(f"  built before {meta.get('before')}, "
          f"hook {meta.get('hook_hash')}")
    for curve in ("bnd", "mid"):
        offs = data.get(curve) or {}
        m = meta.get(curve) or {}
        if not offs:
            continue
        vals = sorted(offs.values())
        sd = (sum(v * v for v in vals) / len(vals)) ** 0.5
        print(f"  {curve}: {len(offs)} arms, {m.get('decisions'):,} "
              f"decisions   offset sd {sd:.4f}   range {vals[0]:+.3f} to "
              f"{vals[-1]:+.3f}")
        print(f"    between sd {m.get('between_sd')}  within sd "
              f"{m.get('within_sd')}  clamped {m.get('clamped')}")


if __name__ == "__main__":
    main()
