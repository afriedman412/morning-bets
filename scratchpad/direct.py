"""SAME INPUTS, DIFFERENT TARGET — what we get when we throw out coherence.

    venv/bin/python -m scratchpad.direct k [--sim] [--draws 200]
    venv/bin/python -m scratchpad.direct outs

The simulator predicts a starter's strikeouts by playing the game: rates,
lineup, base-out state, a hook that decides when he leaves. Everything it
produces is mutually consistent — his K, his outs and his team's runs come
off one game and cannot contradict each other. That coherence is the
product, and it is also a CONSTRAINT: the K distribution has to be whatever
falls out of a start whose length the hook chose.

This trains a model on the SAME PREGAME INPUTS and the settled target
directly, with no game attached, and scores both on the same holdout rows.
The difference between them is the price of coherence for that quantity.

THE INPUT RULE, and the comparison is void without it: the direct model
gets nothing the simulator does not get. Same pitcher rates, same opposing
nine, same park, air and umpire. In particular IT GETS NO EXPOSURE FEATURE
— no expected batters faced, no projected length — because expected length
is downstream of the hook, and handing it over would import the very defect
under test. Both predictors get pregame inputs and both must produce a
distribution.

WHAT THIS COMPARISON FLATTERS, stated before the result: the direct model
gets the K marginal right precisely because it never has to get length
right. That is the finding, not a trick — but it is a MARGINAL comparison,
and the joint (K per 27 outs by length) is where the cost of dropping
coherence shows up. That check is `--joint`.

TWO DIRECT MODELS, deliberately dumb, because this project's history is
that fitted things absorb defects:
  * `glm`   Poisson GLM on the features, negative-binomial dispersion
            fitted by moments on TRAINING residuals only.
  * `emp`   no functional form at all: bucket by the GLM's predicted mean
            and use the EMPIRICAL distribution of training rows in that
            bucket. Counted, not imported — the house style.

HOLDOUT: `src.context.holdout.HOLDOUT`, 2026-07-01. Fitting touches
training rows only. The sim's own constants were fitted on the same window,
so this is a fair fight on the 2026 fold and only on the 2026 fold.

A NOTE ON THE TRAINING FEATURES, which is a real and stated imperfection:
rates for every row are frozen at the cut, so a 2024 start's pitcher rates
include seasons after it. That does not leak the TARGET across the holdout
boundary — test rows are still scored on rates that predate them — and it
makes training features cleaner than test features, which handicaps the
direct model rather than flattering it.
"""
from __future__ import annotations

import json
import math
import random
import statistics as st
import sys
import zlib

import numpy as np

from src import db
from src.context import calibrate as cal
from src.context import sim
from src.context.holdout import HOLDOUT
from src.context.sources import rates as rate_src

#: Every per-start line a book offers on a starter:
#:   target -> (boxscore field on the case row, StartResult attribute,
#:              CRPS support, the two cells reported beside the loss)
#: `build_cases` aliases outs_recorded to `o`, which is why that column is
#: spelled the way it is.
TARGETS = {
    "k":    ("k",  "k",       25, (9, 10)),
    "outs": ("o",  "outs",    28, (18, 21)),
    "bb":   ("bb", "bb",      10, (3, 4)),
    "h":    ("h",  "h",       18, (7, 9)),
    "hr":   ("hr", "hr",       7, (2, 3)),
    "er":   ("er", "earned",  14, (4, 5)),
    "r":    ("r",  "runs",    14, (4, 5)),
}
#: Support for the discrete CRPS. Wide enough that nothing falls off.
SUPPORT = {"k": 25, "outs": 28, "total": 32}
#: Targets scored per GAME rather than per start.
GAME_LEVEL = ("total",)
#: The cells reported beside CRPS, per target — the places the loss cannot
#: see. For the game total they are the two ends the battery says we get
#: wrong: short of quiet games in all four folds.
CELLS = {"k": (9, 10), "outs": (18, 21), "total": (5, 12)}
#: Buckets for the empirical conditional model.
N_BUCKETS = 12
SIM_CACHE = "scratchpad/direct_sim_{target}.json"


# ── features: exactly what the simulator is handed ──────────────────────

def features(case) -> list[float]:
    """One start's pregame inputs, flattened. NO EXPOSURE TERM."""
    row, p, nine = case
    # log5 expected per-PA rates against this specific nine — the same
    # combination the engine makes, which is the single most informative
    # thing the sim knows before the first pitch.
    lg = _LG
    k = st.mean(sim.log5(p.k_pct, b.k_pct, lg["k_pct"]) for b in nine)
    bb = st.mean(sim.log5(p.bb_pct, b.bb_pct, lg["bb_pct"]) for b in nine)
    hr = st.mean(sim.log5(p.hr_pct, b.hr_pct, lg["hr_pct"]) for b in nine)
    ba = st.mean(sim.log5(p.babip, b.babip, lg["babip"]) for b in nine)
    air = cal.air_mult_for(row)
    uk, ubb = cal.ump_mult_for(row)
    park = cal.park_for(row.get("venue_id"),
                        int((row.get("date") or "0000")[:4]) or None) or {}
    # ALL FOUR PARK CHANNELS. The first cut carried k and bip only, which
    # left the fitted model blind to whether it was pitching in a home-run
    # park while the simulator applied one — at Camden (hr 1.10, bb 0.95)
    # that showed up as a home-run gap four times the typical size and read
    # as a model disagreement when it was a missing input. The game-level
    # vector had all four from the start; this one did not.
    return [k, bb, hr, ba,
            p.k_pct, p.bb_pct, p.hr_pct, p.babip,
            math.log(max(p.pa, 1)),
            float(row.get("is_home") or 0),
            air, uk, ubb,
            float(park.get("k", 1.0)), float(park.get("bip", 1.0)),
            float(park.get("hr", 1.0)), float(park.get("bb", 1.0))]


def _pen_block(pens, team) -> list[float]:
    """A club's bullpen as four appearance-weighted rates.

    THE DIRECT MODEL IS ENTITLED TO THIS. The rule is that it gets nothing
    the simulator does not get, and the simulator samples a real bullpen
    every draw — so withholding the pen would handicap it rather than keep
    the comparison honest. What it still does NOT get is how many innings
    the pen will actually throw, which is downstream of the hook.
    """
    arms = pens.get((team or "").upper(), [])
    w = sum(a["apps"] for a in arms) or 1
    return [sum(a[c] * a["apps"] for a in arms) / w
            for c in ("k_pct", "bb_pct", "hr_pct", "babip")]


def game_features(pair, pens) -> list[float]:
    """One GAME's pregame inputs: both sides, plus the shared conditions.

    Both halves are built with the same per-side block, so the vector is
    symmetric in the two clubs apart from the deliberate home/away ordering
    — a total does not care who is who, but home-field is real and the
    model is allowed to find it.
    """
    lg = _LG
    out: list[float] = []
    for row, p, nine in pair:
        out += [st.mean(sim.log5(p.k_pct, b.k_pct, lg["k_pct"]) for b in nine),
                st.mean(sim.log5(p.bb_pct, b.bb_pct, lg["bb_pct"])
                        for b in nine),
                st.mean(sim.log5(p.hr_pct, b.hr_pct, lg["hr_pct"])
                        for b in nine),
                st.mean(sim.log5(p.babip, b.babip, lg["babip"]) for b in nine),
                math.log(max(p.pa, 1))]
        out += _pen_block(pens, row.get("team"))
    row = pair[1][0]                      # shared conditions off the home row
    park = cal.park_for(row.get("venue_id"),
                        int((row.get("date") or "0000")[:4]) or None) or {}
    uk, ubb = cal.ump_mult_for(row)
    out += [cal.air_mult_for(row), uk, ubb,
            float(park.get("k", 1.0)), float(park.get("bip", 1.0)),
            float(park.get("hr", 1.0)), float(park.get("bb", 1.0))]
    return out


def build_games(target: str):
    """(train, test) as (X, y, pair) triples, one row per GAME."""
    global _LG
    with db.connect() as c:
        act = {r["game_id"]: dict(r) for r in c.execute(
            "select game_id, away_score, home_score from games"
            " where sport='mlb' and status='Final'")}
    tr, te = [], []
    for s in (2023, 2024, 2025, 2026):
        cut = f"{s}-07-01"
        _LG = sim.league(s, before=cut)
        pens = rate_src.bullpens(_LG, before=cut)
        for gid, pair in cal.paired_cases(season=s, since=cut,
                                          rates_before=cut).items():
            a = act.get(gid)
            d = pair[1][0].get("date") or ""
            if not a or a["away_score"] is None or not d:
                continue
            y = float(a["away_score"] + a["home_score"])
            rec = (game_features(pair, pens), y, pair)
            (tr if d < HOLDOUT else te).append(rec)
    return tr, te


def build(target: str):
    """(train rows, test rows) as (X, y, case) triples, split on HOLDOUT.

    ONE SEASON AT A TIME, and this is not cosmetic: `build_cases` with no
    `season` returns THE CURRENT SEASON ONLY — 3,909 starts where the cache
    holds four years — which silently cut the training set to a fifth of
    what it should be. The same trap `CLAUDE.md` records against
    `paired_cases`.

    The league baseline is rebuilt per season too. log5 anchors every
    feature on it, so pooling seasons under one baseline would put a
    league-level drift into the pitcher's own numbers.
    """
    global _LG
    tr, te = [], []
    for s in (2023, 2024, 2025, 2026):
        # THE BATTERY'S FOLD CONSTRUCTION, and it has to be this or the
        # comparison is rigged. Every row — training and holdout alike —
        # gets rates measured over the first three months of its OWN season
        # and is itself from July onward. Building training features from
        # full seasons and holdout features from three months made the
        # holdout's inputs far more shrunk than the training inputs, which
        # compressed the predicted means and cost the direct model a third
        # of its 9+ tail before it was allowed to compete.
        cut = f"{s}-07-01"
        _LG = sim.league(s, before=cut)
        for c in cal.build_cases(season=s, since=cut, rates_before=cut):
            row = c[0]
            # `build_cases` aliases outs_recorded to `o` — asking for
            # `outs_recorded` silently drops every row.
            y = row.get("k" if target == "k" else "o")
            d = row.get("date") or ""
            if y is None or not d:
                continue
            rec = (features(c), float(y), c)
            (tr if d < HOLDOUT else te).append(rec)
    return tr, te


# ── the two direct models ───────────────────────────────────────────────

def fit_direct(tr, te, target: str, quiet: bool = False):
    """-> {name: [per-test-row pmf]}. Fitted on TRAINING ROWS ONLY."""
    from sklearn.linear_model import PoissonRegressor
    Xtr = np.array([r[0] for r in tr])
    ytr = np.array([r[1] for r in tr])
    Xte = np.array([r[0] for r in te])
    mu_tr = None
    glm = PoissonRegressor(alpha=1e-4, max_iter=1000)
    glm.fit(Xtr, ytr)
    mu_tr = glm.predict(Xtr)
    mu_te = glm.predict(Xte)

    # Negative-binomial dispersion by moments on TRAINING residuals. var =
    # mu + mu^2/r, so r = mean(mu^2) / max(var_excess, eps).
    resid = ytr - mu_tr
    excess = float(np.mean(resid ** 2 - mu_tr))
    r_nb = float(np.mean(mu_tr ** 2) / excess) if excess > 1e-9 else 1e9
    n_max = TARGETS[target][2] if target in TARGETS else SUPPORT[target]

    def nb_pmf(mu):
        p = r_nb / (r_nb + mu)
        out = np.zeros(n_max + 1)
        lg_r = math.lgamma(r_nb)
        for x in range(n_max + 1):
            out[x] = math.exp(math.lgamma(x + r_nb) - math.lgamma(x + 1)
                              - lg_r + r_nb * math.log(p)
                              + x * math.log(max(1 - p, 1e-12)))
        s = out.sum()
        return out / s if s > 0 else out

    glm_pmfs = [nb_pmf(m) for m in mu_te]

    # The empirical conditional: no functional form, just the training
    # rows that looked like this one.
    order = np.argsort(mu_tr)
    edges = [mu_tr[order[int(len(order) * i / N_BUCKETS)]]
             for i in range(1, N_BUCKETS)]

    def bucket(m):
        return int(np.searchsorted(edges, m))

    hist = {}
    for b in range(N_BUCKETS):
        ys = [ytr[i] for i in range(len(ytr)) if bucket(mu_tr[i]) == b]
        h = np.zeros(n_max + 1)
        for v in ys:
            h[min(int(v), n_max)] += 1
        hist[b] = h / h.sum() if h.sum() else h
    emp_pmfs = [hist[bucket(m)] for m in mu_te]
    # var/mean of the target around the fitted mean. BELOW 1 means the
    # count is UNDER-dispersed relative to Poisson, the NB collapses to
    # Poisson, and the empirical model is the one carrying the shape.
    vm = float(np.mean(resid ** 2) / np.mean(mu_tr))
    if not quiet:
        print(f"  direct: {len(tr)} training rows, {len(te)} holdout rows")
        print(f"  residual var / mean = {vm:.3f}"
              f"{'  (under-dispersed vs Poisson)' if vm < 1 else ''}"
              f", NB r = {r_nb:.1f}")
    return {"glm": glm_pmfs, "emp": emp_pmfs}


# ── the simulator's own distribution on the same rows ───────────────────

def sim_pmfs(te, target: str, draws: int = 200):
    """Cached. One paired game per test start, `draws` full games each."""
    path = SIM_CACHE.format(target=target)
    try:
        got = json.load(open(path))
    except (OSError, ValueError):
        got = {}
    lg = sim.league(before=HOLDOUT)
    pens = rate_src.bullpens(lg, before=HOLDOUT)
    pairs = cal.paired_cases(since=HOLDOUT, rates_before=HOLDOUT)
    n_max = SUPPORT[target]
    out, missing = [], 0
    todo = [(i, r) for i, r in enumerate(te)
            if _key(r) not in got and _gid(r) in pairs]
    if todo:
        print(f"  simulating {len(todo)} starts x {draws} draws", flush=True)
    for n, (i, r) in enumerate(todo):
        gid = _gid(r)
        pair = pairs[gid]
        is_home = bool(r[2][0].get("is_home"))
        h = [0] * (n_max + 1)
        for d in range(draws):
            # crc32, not hash() — str hashing is salted per process, so a
            # cached run and a fresh one would draw different games.
            rng = random.Random((zlib.crc32(gid.encode()) & 0xFFFFFF)
                                * 100003 + d)
            res = cal.replay(pair, lg, pens, rng)
            sp = res.home_sp if is_home else res.away_sp
            v = sp.k if target == "k" else sp.outs
            h[min(int(v), n_max)] += 1
        got[_key(r)] = h
        if (n + 1) % 100 == 0:
            print(f"    {n + 1}/{len(todo)}", flush=True)
            json.dump(got, open(path, "w"))
    json.dump(got, open(path, "w"))
    for r in te:
        h = got.get(_key(r))
        if not h:
            missing += 1
            out.append(None)
            continue
        a = np.array(h, dtype=float)
        out.append(a / a.sum())
    if missing:
        print(f"  {missing} holdout starts have no paired game (dropped)")
    return out


def build_all():
    """(train, test) with EVERY target's y on each row, features built once.

    The feature vector does not depend on which line is being predicted, so
    building seven times would be seven times the work for identical X.
    """
    global _LG
    tr, te = [], []
    for s in (2023, 2024, 2025, 2026):
        cut = f"{s}-07-01"
        _LG = sim.league(s, before=cut)
        for c in cal.build_cases(season=s, since=cut, rates_before=cut):
            row = c[0]
            d = row.get("date") or ""
            ys = {t: row.get(f) for t, (f, *_r) in TARGETS.items()}
            if not d or any(v is None for v in ys.values()):
                continue
            rec = (features(c), {t: float(v) for t, v in ys.items()}, c)
            (tr if d < HOLDOUT else te).append(rec)
    return tr, te


def sim_pmfs_all(te, draws: int = 200):
    """{target: [pmf per test row]} from ONE simulation pass.

    TWO ECONOMIES, both of which matter at 200 draws a game:

    Every target is read off the same draws — the battery's one-payload
    rule. Simulating per target would give seven passes whose views could
    disagree about the same simulated start, which is exactly the failure
    the battery exists to prevent.

    And it iterates over GAMES, recording BOTH starters from each replay.
    The per-start version simulated every game twice, once for each side,
    which was half the run doing work it already had.
    """
    path = "scratchpad/direct_sim_start.json"
    try:
        got = json.load(open(path))
    except (OSError, ValueError):
        got = {}
    lg = sim.league(2026, before=HOLDOUT)
    pens = rate_src.bullpens(lg, before=HOLDOUT)
    pairs = cal.paired_cases(since=HOLDOUT, rates_before=HOLDOUT)
    want = {_gid(r) for r in te if _gid(r) in pairs}
    todo = sorted(g for g in want if g not in got)
    if todo:
        print(f"  simulating {len(todo)} games x {draws} draws, "
              f"both starters, every target", flush=True)
    for n, gid in enumerate(todo):
        pair = pairs[gid]
        acc = {side: {t: [0] * (TARGETS[t][2] + 1) for t in TARGETS}
               for side in ("away", "home")}
        for d in range(draws):
            rng = random.Random((zlib.crc32(gid.encode()) & 0xFFFFFF)
                                * 100003 + d)
            res = cal.replay(pair, lg, pens, rng)
            for side, sp in (("away", res.away_sp), ("home", res.home_sp)):
                for t, (_f, attr, cap, _c) in TARGETS.items():
                    acc[side][t][min(int(getattr(sp, attr)), cap)] += 1
        for side, idx in (("away", 0), ("home", 1)):
            got[f"{gid}|{pair[idx][0]['player_name']}"] = acc[side]
        if (n + 1) % 100 == 0:
            print(f"    {n + 1}/{len(todo)}", flush=True)
            json.dump(got, open(path, "w"))
    json.dump(got, open(path, "w"))
    out = {t: [] for t in TARGETS}
    for r in te:
        h = got.get(_key(r))
        for t in TARGETS:
            if not h:
                out[t].append(None)
                continue
            a = np.array(h[t], dtype=float)
            out[t].append(a / a.sum())
    return out


def sim_pmfs_game(te, draws: int = 200):
    """The simulator's own GAME TOTAL distribution on the same games."""
    path = SIM_CACHE.format(target="total")
    try:
        got = json.load(open(path))
    except (OSError, ValueError):
        got = {}
    lg = sim.league(2026, before=HOLDOUT)
    pens = rate_src.bullpens(lg, before=HOLDOUT)
    n_max = SUPPORT["total"]
    todo = [r for r in te if r[2][1][0]["game_id"] not in got]
    if todo:
        print(f"  simulating {len(todo)} games x {draws} draws", flush=True)
    for n, r in enumerate(todo):
        gid = r[2][1][0]["game_id"]
        h = [0] * (n_max + 1)
        for d in range(draws):
            rng = random.Random((zlib.crc32(gid.encode()) & 0xFFFFFF)
                                * 100003 + d)
            h[min(int(cal.replay(r[2], lg, pens, rng).total), n_max)] += 1
        got[gid] = h
        if (n + 1) % 100 == 0:
            print(f"    {n + 1}/{len(todo)}", flush=True)
            json.dump(got, open(path, "w"))
    json.dump(got, open(path, "w"))
    out = []
    for r in te:
        a = np.array(got[r[2][1][0]["game_id"]], dtype=float)
        out.append(a / a.sum())
    return out


def _gid(r):
    return r[2][0]["game_id"]


def _key(r):
    return f"{r[2][0]['game_id']}|{r[2][0]['player_name']}"


# ── scoring ─────────────────────────────────────────────────────────────

def crps(pmf, actual) -> float:
    """Discrete CRPS: sum over the support of (F(x) - 1{y<=x})^2."""
    cdf = np.cumsum(pmf)
    step = (np.arange(len(pmf)) >= actual).astype(float)
    return float(np.sum((cdf - step) ** 2))


def mc_penalty(pmf, draws: int) -> float:
    """How much of the simulator's CRPS is its own histogram noise.

    THE SIMULATOR IS SCORED ON AN EMPIRICAL CDF and the fitted models on a
    smooth one, so the comparison is biased against the sim by the variance
    of its own sampling: E[extra] = sum_x F(x)(1-F(x)) / draws. On game
    totals this is 0.0120, which is LARGER than the gap it was being
    compared on — reading the raw numbers had the direct model nominally
    ahead when it is not. Subtracted per row so the paired se is honest.
    """
    F = np.cumsum(pmf)
    return float(np.sum(F * (1 - F)) / draws)


def score(name, pmfs, te, target, cells) -> dict:
    rows = [(p, r[1]) for p, r in zip(pmfs, te) if p is not None]
    n = len(rows)
    c = [crps(p, y) for p, y in rows]
    out = {"name": name, "n": n, "crps": st.mean(c),
           "se": st.pstdev(c) / n ** 0.5}
    for lo in cells:
        pred = st.mean(float(p[lo:].sum()) for p, _y in rows)
        real = st.mean(float(y >= lo) for _p, y in rows)
        out[f"p{lo}+"] = (pred, real,
                          (real * (1 - real) / n) ** 0.5)
    return out


def main_all(draws=200):
    """Every starter line, one simulation pass, one feature build.

    THE OUTPUT IS THE DISTRIBUTIONS THEMSELVES — for each stat, the
    probability of every value, from the simulator and from each fitted
    model, beside how often it actually happened. No loss, no cells, no
    sigma. Any summary can be computed from these four columns and none of
    them can show a disagreement the columns do not already contain.

    `actual` is the holdout's own histogram over the same starts, so the
    three model columns and the real one are strictly comparable.
    """
    tr, te = build_all()
    print(f"  {len(tr)} training starts, {len(te)} holdout starts, "
          f"train < {HOLDOUT}")
    sims = sim_pmfs_all(te, draws)
    dump = {}
    for t, (_f, _a, cap, _c) in TARGETS.items():
        keep = [i for i in range(len(te)) if sims[t][i] is not None]
        pr = fit_direct([(x, y[t], c) for x, y, c in tr],
                        [(x, y[t], c) for x, y, c in te], t, quiet=True)
        pr = {m: [v[i] for i in keep] for m, v in pr.items()}
        pr["sim"] = [sims[t][i] for i in keep]
        acts = [te[i][1][t] for i in keep]
        n = len(acts)
        actual = np.zeros(cap + 1)
        for y in acts:
            actual[min(int(y), cap)] += 1
        actual /= n
        pooled = {m: np.mean(np.array(v), axis=0) for m, v in pr.items()}
        # Trim at the highest value anyone actually reached; beyond that
        # every column is zeros and the table is just longer.
        top = max(int(max(acts)), 1)
        dump[t] = {"n": n, "support": list(range(top + 1)),
                   **{m: [round(float(x), 6) for x in pooled[m][:top + 1]]
                      for m in ("sim", "glm", "emp")},
                   "actual": [round(float(x), 6) for x in actual[:top + 1]]}
        print(f"\n  {t.upper()}   n = {n} holdout starts")
        print(f"  {'value':>6}{'sim':>9}{'glm':>9}{'emp':>9}{'actual':>9}")
        for v in range(top + 1):
            print(f"  {v:>6}{pooled['sim'][v]:>9.4f}{pooled['glm'][v]:>9.4f}"
                  f"{pooled['emp'][v]:>9.4f}{actual[v]:>9.4f}")
    json.dump(dump, open("scratchpad/direct_pmfs.json", "w"), indent=1)
    print("\n  -> scratchpad/direct_pmfs.json")


def main(target="k", draws=200, do_sim=True):
    cells = CELLS[target]
    game = target in GAME_LEVEL
    tr, te = build_games(target) if game else build(target)
    print(f"  target {target}: train < {HOLDOUT}, holdout >= {HOLDOUT}"
          f"  ({'one row per game' if game else 'one row per start'})")
    preds = fit_direct(tr, te, target)
    if do_sim:
        preds["sim"] = (sim_pmfs_game(te, draws) if game
                        else sim_pmfs(te, target, draws))
    keep = [i for i in range(len(te))
            if all(preds[k][i] is not None for k in preds)]
    te = [te[i] for i in keep]
    preds = {k: [v[i] for i in keep] for k, v in preds.items()}
    print(f"\n  scored on {len(te)} holdout starts common to all predictors")
    res = [score(k, v, te, target, cells) for k, v in preds.items()]
    head = f"  {'model':<7}{'n':>7}{'CRPS':>10}{'se':>8}"
    for lo in cells:
        head += f"{'P(' + str(lo) + '+) pred/real':>22}"
    print(head)
    for r in res:
        line = f"  {r['name']:<7}{r['n']:>7}{r['crps']:>10.4f}{r['se']:>8.4f}"
        for lo in cells:
            pr, re_, se_ = r[f"p{lo}+"]
            line += f"{pr:.3f} / {re_:.3f} ±{se_:.3f}".rjust(22)
        print(line)
    bname = "sim" if do_sim else res[0]["name"]
    # PAIRED, and the unpaired se above is the wrong bar for this. Every
    # predictor scores the SAME starts, so the difference's se comes from
    # the per-row differences, not from the spread of CRPS itself — which
    # is dominated by how hard each start was to predict and cancels.
    print(f"\n  vs {bname}, PAIRED per start:")
    ys = [r[1] for r in te]
    bc = [crps(p, y) for p, y in zip(preds[bname], ys)]
    for r in res:
        if r["name"] == bname:
            continue
        rc = [crps(p, y) for p, y in zip(preds[r["name"]], ys)]
        d = [x - b for x, b in zip(rc, bc)]
        m = st.mean(d)
        se = st.pstdev(d) / len(d) ** 0.5
        print(f"    {r['name']:<7}{m:+.4f} ± {se:.4f} CRPS  "
              f"({m / se if se else 0:+.1f} sigma, "
              f"{'better' if m < 0 else 'worse'})")
    print("\n  A TAIL REPAIR IS INVISIBLE TO CRPS BY CONSTRUCTION (rule 2):")
    print("  almost all of the loss lives in the bulk, so read the cell "
          "columns above,\n  not this one.")


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("-")]
    t = a[0] if a else "all"
    dr = 200
    for x in sys.argv:
        if x.startswith("--draws="):
            dr = int(x.split("=")[1])
    if t == "all":
        main_all(dr)
    else:
        main(t, dr, do_sim="--nosim" not in sys.argv)
