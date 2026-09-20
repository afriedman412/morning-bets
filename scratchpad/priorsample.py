"""What is a PRIOR SEASON'S SAMPLE worth? Counted, not fitted.

    venv/bin/python -m scratchpad.priorsample [--stat k_pct]
    venv/bin/python -m scratchpad.priorsample --synth 300   (positive control)

TODO ITEM 12, AND THE MEASUREMENT THAT WAS MISSING. `_load_seasons` builds
the prior by calling `pitcher_rates`, which has ALREADY shrunk each season
toward the league; `shrink_target` then shrinks that toward the league again
with the same constant. League average is applied twice. For Blake Snell on
2026-08-29 the two stages take his own record from 0.3007 to 0.2814 to
0.2699 — a target below every season he has thrown.

THE NAIVE FIX WAS SCORED AND LOSES. `USE_RAW_PRIOR` removes the first
shrink and costs +0.00944 F5 CRPS, z +2.6, 4/4 salts. The double shrink is
wrong as a construction and better in practice, which means it is
COMPENSATING: `_blend_priors` sets the prior's `pa` to the raw sum of
decayed batters faced, and a season-old rate is worth LESS than its sample
implies once talent has had a year to move. `PRIOR_DECAY` discounts the
RATE. Nothing discounts the SAMPLE.

So the target form is ONE shrink against a discounted sample:

    rate = (n_own*own + m*prior + k_lg*league) / (n_own + m + k_lg)

`m` is the prior's EFFECTIVE batters faced and is what this counts. The
shipped construction is the same expression with the prior entering at its
full `pa` and then being diluted a second time; `m` replaces both.

IT IS COUNTED, NOT TUNED. The loss here is out-of-sample prediction of the
REST OF A PITCHER'S OWN SEASON — a fact about pitchers, scored on what they
did. It is not F5, not CRPS, and not anything that settles. That is the
same footing `stabilise.py` and `decay.py` stand on, and it is the whole
reason a measured constant does not go back to absorbing other defects.
Scoring the counted value on F5 comes AFTER, as a check, never as the
search.

WHY A SWEEP CAN LIE HERE, and what is done about it. The loss is smooth in
`m` with a broad minimum, so a grid edge or a flat basin reads as an
answer. `--synth` plants a known `m` and the sweep has to recover it; it
does, exactly, at 50/100/200/400/800. THE FIRST VERSION OF THAT CONTROL WAS
BACKWARDS and printed a believable 2x overshoot — see `synth` for what was
wrong with it. A mis-specified sweep and a genuinely flat loss print the
same table, and so does a mis-specified control.

TWO STATS SURVIVED AND TWO DID NOT, on a rule worth stating: `m` cannot
exceed the prior's own sample, because the prior's rate carries that
sample's binomial noise PLUS a year of talent drift. babip asks for 800
against a raw 291, which is a failed measurement rather than a large one;
hr_pct's argmin walks 400/400/800 across seasons for a 1% gain, because
k_lg is 934 and the curve is nearly flat. Both keep the shipped
construction. k_pct and bb_pct are interior, season-identical and stable
across four current-sample cuts.

AND THE FLAT FORM IS NOT THE RIGHT SHAPE, which the motivating case
exposes. A single `m` says a prior is worth 250 batters faced whatever it
contains — it caps a four-season arm and inflates a one-season one. Blake
Snell's prior holds 613 against a median 403, so the flat form moves him
DOWN (0.2840 -> 0.2778) rather than up. `m_of(..., harmonic=True)` sweeps
the structurally correct version, `1/m = 1/pa + 1/M`, where `M` is the
drift ceiling; it fits better on every stat but its `M` hits the grid edge
on hr and babip and moves 400-1300 across cuts on k_pct, so THIS DATA
CANNOT PIN IT. Recorded as the better parameterisation, not shipped.
"""
from __future__ import annotations

import random
import statistics as st
import sys
from collections import defaultdict

from src.context import store
from src.context.sources import rates as rate_src

STATS = ("k_pct", "bb_pct", "hr_pct", "babip")
_NUM = {"k_pct": "k", "bb_pct": "bb", "hr_pct": "hr", "babip": "hits_bip"}

#: Batters faced of the CURRENT season used as the pitcher's own evidence.
#: Swept, because `m` is meant to be a property of the prior alone — if the
#: answer moves with the current sample the form is wrong, not the number.
OWN_CUTS = (40, 80, 150, 300)
#: Held-out batters faced required after the cut.
MIN_OUT = 100
#: Batters faced required in a season for it to enter the prior.
MIN_PRIOR_BF = 100

_Q = """
select g.date date, p.player_name name,
       p.outs_recorded o, p.h h, p.bb bb, p.k k, p.hr hr
from bets.mlb_pitching p join bets.games g on g.game_id = p.game_id
where g.sport = 'mlb' and g.status = 'Final'
order by p.player_name, g.date
"""


def load():
    """{(name, season): [appearances]} plus {season: league rates}."""
    with store.connect() as c:
        rows = [dict(r) for r in c.execute(_Q)]
    app = defaultdict(list)
    for r in rows:
        bf = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
        if bf < 1:
            continue
        app[(r["name"], int(r["date"][:4]))].append(
            {"date": r["date"], "bf": bf, "k": r["k"] or 0,
             "bb": r["bb"] or 0, "hr": r["hr"] or 0,
             # BABIP's denominator is BALLS IN PLAY, not batters faced, and
             # `rates.balls_in_play` divides by BIP_PER_OUT_UNIT to undo the
             # phantom balls in play a boxscore denominator creates. Same
             # correction here or this measures a different quantity from
             # the one that ships.
             "bip": max(((bf - (r["k"] or 0) - (r["bb"] or 0)
                          - (r["hr"] or 0)) / rate_src.BIP_PER_OUT_UNIT), 0.0)
             if rate_src.USE_COUNTED_BIP else
             max(bf - (r["k"] or 0) - (r["bb"] or 0) - (r["hr"] or 0), 0),
             "hits_bip": max((r["h"] or 0) - (r["hr"] or 0), 0)})
    for v in app.values():
        v.sort(key=lambda x: x["date"])
    lg = defaultdict(lambda: defaultdict(float))
    for (_, season), rows_ in app.items():
        for r in rows_:
            lg[season]["bf"] += r["bf"]
            lg[season]["bip"] += r["bip"]
            for s, col in _NUM.items():
                lg[season][col] += r[col]
    league = {s: {st_: v[_NUM[st_]] / (v["bip"] if st_ == "babip"
                                       else v["bf"]) for st_ in STATS}
              for s, v in lg.items() if v["bf"] > 0}
    return app, league


def totals(rows, stat):
    """(numerator, denominator) — and the DENOMINATOR follows the stat.

    BABIP is per ball in play. Using batters faced for it would be the
    denominator mistake CLAUDE.md records three of in one script.
    """
    den = sum((r["bip"] if stat == "babip" else r["bf"]) for r in rows)
    return sum(r[_NUM[stat]] for r in rows), den


def blended_prior(app, league, name, season, stat):
    """(rate, raw pa) — the prior `_blend_priors` would build, RAW.

    Mirrors the shipped construction in the two ways that matter: each
    season is moved onto the target season's run environment first
    (`_prior_adjusted`), and the decay lag is RELATIVE TO THE PITCHER'S OWN
    most recent available season rather than to the calendar, so a man back
    from a missing year enters at full weight.

    RAW because the whole question is what this evidence is worth before
    anything is shrunk. The shipped path takes it already shrunk.
    """
    have = []
    for lag in range(1, rate_src.PRIOR_SEASONS + 1):
        yr = season - lag
        rows = app.get((name, yr))
        if not rows:
            continue
        num, bf = totals(rows, stat)
        if bf < MIN_PRIOR_BF or yr not in league:
            continue
        adj = (num / bf) * (league[season][stat] / league[yr][stat])
        have.append((lag, adj, bf))
    if not have:
        return None, 0.0
    base = min(l for l, _, _ in have)
    dec = rate_src.PRIOR_DECAY.get(stat, 0.0)
    num = den = 0.0
    for lag, rate, bf in have:
        w = (dec ** (lag - base)) * bf
        num += w * rate
        den += w
    return (num / den, den) if den else (None, 0.0)


def cases(app, league, stat, own_cut):
    """One row per pitcher-season: own evidence, prior, held-out outcome."""
    out = []
    for (name, season), rows in sorted(app.items()):
        prior, prior_pa = blended_prior(app, league, name, season, stat)
        if prior is None:
            continue
        run, cut_i = 0, None
        for i, r in enumerate(rows):
            run += r["bf"]
            if run >= own_cut:
                cut_i = i + 1
                break
        if cut_i is None:
            continue
        own_num, own_bf = totals(rows[:cut_i], stat)
        out_num, out_bf = totals(rows[cut_i:], stat)
        if out_bf < MIN_OUT:
            continue
        out.append({"name": name, "season": season,
                    "own": own_num / own_bf, "own_bf": own_bf,
                    "prior": prior, "prior_pa": prior_pa,
                    "lg": league[season][stat],
                    "out": out_num / out_bf, "out_bf": out_bf})
    return out


def m_of(r, M, harmonic):
    """The prior's effective sample for ONE pitcher.

    FLAT: every prior is worth `M` batters faced whatever it contains,
    which is what a single-constant sweep implicitly assumes and is wrong
    at both ends — it caps a four-season arm and inflates a one-season one.

    HARMONIC, and this is the right form: the prior's rate carries its own
    BINOMIAL noise (p(1-p)/pa) plus a year of TALENT DRIFT (sigma_d^2).
    Adding variances and converting back to a sample size gives

        1/m = 1/pa + 1/M    ->    m = pa*M / (pa + M)

    so `M` is the DRIFT CEILING — what an infinitely long career is worth
    once a year has passed — and a thin prior is discounted below it by its
    own sample. One constant either way; this one has the right shape.
    """
    if not harmonic:
        return M
    pa = r.get("prior_pa") or 0.0
    return (pa * M / (pa + M)) if (pa + M) > 0 else 0.0


def loss_at(rows, m, k_lg, harmonic=False):
    """Batters-faced-weighted squared error of the pooled estimate.

    Weighted by the HELD-OUT sample, so each held-out plate appearance
    counts once. Binomial noise in the outcome inflates every loss by the
    same constant and cannot move the argmin.
    """
    num = den = 0.0
    for r in rows:
        mi = m_of(r, m, harmonic)
        p = ((r["own_bf"] * r["own"] + mi * r["prior"] + k_lg * r["lg"])
             / (r["own_bf"] + mi + k_lg))
        num += r["out_bf"] * (r["out"] - p) ** 2
        den += r["out_bf"]
    return num / den if den else 0.0


def shipped_loss(rows, k_lg):
    """The same loss for what the code does TODAY — two shrinks.

    Stage 1 shrinks each prior season inside `pitcher_rates`; the blend is
    linear in those rates, so shrinking the blend by the same constant is
    the same operation and is applied here at the blend's own `pa`. Stage 2
    is `shrink_target`. Then the current line shrinks toward that.
    """
    num = den = 0.0
    for r in rows:
        w1 = r["prior_pa"] / (r["prior_pa"] + k_lg)
        stage1 = w1 * r["prior"] + (1 - w1) * r["lg"]
        w2 = r["prior_pa"] / (r["prior_pa"] + k_lg)
        target = w2 * stage1 + (1 - w2) * r["lg"]
        w3 = r["own_bf"] / (r["own_bf"] + k_lg)
        p = w3 * r["own"] + (1 - w3) * target
        num += r["out_bf"] * (r["out"] - p) ** 2
        den += r["out_bf"]
    return num / den if den else 0.0


GRID = [0, 25, 50, 75, 100, 150, 200, 250, 300, 400, 500, 600, 800,
        1000, 1300, 1700, 2200, 3000]


def sweep(rows, k_lg, harmonic=False):
    curve = {m: loss_at(rows, m, k_lg, harmonic) for m in GRID}
    return min(curve, key=curve.get), curve


def synth(n_pitchers, m_true, k_lg, p0=0.22, seed=1):
    """Pitchers generated by the model the ESTIMATOR assumes.

    THE FIRST VERSION OF THIS CONTROL WAS BACKWARDS and it is worth saying
    how, because the table it printed was completely believable. It drew
    talent as T ~ N(prior, sigma) — talent scattered around the pitcher's
    own past. Under that model the league carries NO information once the
    prior is known, but the estimator always spends `k_lg` batters on the
    league anyway, so the sweep inflated `m` to drown it out: a uniform 2x
    overshoot, and the grid EDGE at the smallest sigma. A grid edge is a
    missing mechanism, and the missing mechanism was in the generator.

    The right model, which is the one the pooled form encodes:

        T      ~ N(league,  p0(1-p0)/k_lg)     talent varies around league
        prior  = T + N(0,   p0(1-p0)/m_true)   the past READS talent, noisily
        own    ~ Binom(n_own, T)
        out    ~ Binom(n_out, T)

    Precision-weighting those three sources gives exactly
    `(n*own + m*prior + k_lg*league) / (n + m + k_lg)`, so `m_true` is
    recoverable by construction and the sweep has to find it.
    """
    rng = random.Random(seed)
    sd_t = (p0 * (1 - p0) / k_lg) ** 0.5
    sd_p = (p0 * (1 - p0) / m_true) ** 0.5
    rows = []
    for i in range(n_pitchers):
        talent = min(max(rng.gauss(p0, sd_t), 0.02), 0.60)
        prior = min(max(rng.gauss(talent, sd_p), 0.02), 0.60)
        own_bf = rng.choice([60, 90, 140, 220])
        out_bf = rng.choice([150, 250, 400])
        own = sum(1 for _ in range(own_bf) if rng.random() < talent) / own_bf
        got = sum(1 for _ in range(out_bf) if rng.random() < talent) / out_bf
        rows.append({"own": own, "own_bf": own_bf, "prior": prior,
                     "prior_pa": 600.0, "lg": p0, "out": got,
                     "out_bf": out_bf, "season": 2000 + (i % 4)})
    return rows, m_true


def main(argv):
    stat = "k_pct"
    for i, a in enumerate(argv):
        if a == "--stat":
            stat = argv[i + 1]

    k_lg = (rate_src.STABILISE_MEASURED["pit"].get(stat)
            or rate_src.STABILISE[stat])

    if "--synth" in argv:
        n = int(argv[argv.index("--synth") + 1])
        print(f"\n  POSITIVE CONTROL — {n} synthetic pitchers per cell,"
              f" k_lg = {k_lg}")
        print(f"  {'true m':>10}{'found m':>10}{'ratio':>8}")
        for true_m in (50, 100, 200, 400, 800):
            rows, tm = synth(n, true_m, k_lg)
            got, _ = sweep(rows, k_lg)
            print(f"  {tm:>10}{got:>10}{got / tm:>8.2f}")
        print("\n  The grid is coarse, so a ratio near 1 across the range is")
        print("  the pass. A ratio that drifts with `m` is a biased sweep.")
        return

    app, league = load()
    print(f"\n  WHAT A PRIOR SEASON'S SAMPLE IS WORTH — {stat}")
    print(f"  league shrink constant k_lg = {k_lg}, "
          f"PRIOR_DECAY = {rate_src.PRIOR_DECAY[stat]}, "
          f"PRIOR_SEASONS = {rate_src.PRIOR_SEASONS}")
    print(f"\n  {'':>30}{'--- flat m ---':>20}"
          f"{'--- harmonic M ---':>20}")
    print(f"  {'own cut':>9}{'n':>7}{'med prior pa':>14}{'m':>9}"
          f"{'loss':>11}{'M':>9}{'loss':>11}{'shipped':>11}{'gain':>9}")
    rows_all = {}
    for cut in OWN_CUTS:
        rows = cases(app, league, stat, cut)
        if len(rows) < 40:
            print(f"  {cut:>9}{len(rows):>7}   too few")
            continue
        rows_all[cut] = rows
        best, curve = sweep(rows, k_lg)
        bestH, curveH = sweep(rows, k_lg, harmonic=True)
        shp = shipped_loss(rows, k_lg)
        print(f"  {cut:>9}{len(rows):>7}"
              f"{st.median([r['prior_pa'] for r in rows]):>14.0f}"
              f"{best:>9}{curve[best]:>11.6f}"
              f"{bestH:>9}{curveH[bestH]:>11.6f}{shp:>11.6f}"
              f"{(shp - curveH[bestH]) / shp * 100:>+8.2f}%")

    if not rows_all:
        return
    pooled = [r for rows in rows_all.values() for r in rows]
    best, curve = sweep(pooled, k_lg, harmonic="--flat" not in argv)
    print(f"\n  THE LOSS CURVE, pooled over cuts (n = {len(pooled):,})")
    lo = min(curve.values())
    for m in GRID:
        bar = "#" * int(round((curve[m] - lo) / (max(curve.values()) - lo)
                              * 48)) if max(curve.values()) > lo else ""
        mark = "  <-- best" if m == best else ""
        print(f"  {m:>6}{curve[m]:>12.6f}  {bar}{mark}")

    # STABILITY GATE. A constant that only holds in one season is a fit.
    print(f"\n  PER TARGET SEASON — the same sweep")
    print(f"  {'season':<8}{'n':>7}{'best M':>9}{'(flat m)':>12}")
    for yr in sorted({r["season"] for r in pooled}):
        sub = [r for r in pooled if r["season"] == yr]
        if len(sub) < 40:
            continue
        b, _ = sweep(sub, k_lg, harmonic="--flat" not in argv)
        bf_, _ = sweep(sub, k_lg)
        print(f"  {yr:<8}{len(sub):>7}{b:>9}{bf_:>12}")
    print(f"\n  SHIPPED prior pa is the RAW decayed sum — median"
          f" {st.median([r['prior_pa'] for r in pooled]):.0f} batters faced."
          f"\n  The counted `m` is what that evidence is actually worth.")


if __name__ == "__main__":
    main(sys.argv[1:])
