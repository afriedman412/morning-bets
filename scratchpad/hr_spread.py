"""Where does the model's PITCHER-LEVEL home-run compression come from?

    venv/bin/python -m scratchpad.hr_spread

QUESTION. Collapsing each arm to his mean predicted and mean actual home
runs, actual regressed on predicted has slope 2.36 raw / 2.81 corrected,
+10 sigma over 181 pitchers. Every other channel sits between 1.12 and 1.45.
The model separates pitchers on home runs less than half as much as reality
does. WHY.

THREE CANDIDATES, and this script tests the two that need no simulation.

  1. PITCHER SHRINKAGE, `STABILISE_MEASURED["pit"]["hr_pct"] = 934`. It must
     show as the shipped rate carrying much less across-pitcher spread than
     the RELIABLE share of the raw rate. Note the RESUME line "a 600-batter
     pitcher holds 39% of his own rate" assumes the target is the league —
     `USE_PRIOR_SEASON` is on, so the target is HIS OWN prior seasons and the
     pull is toward himself, not toward average. That is measured here.

  2. BATTER SHRINKAGE, `["bat"]["hr_pct"] = 160`. Near-null by construction
     at this unit of observation: a pitcher faces many lineups and their
     errors average out across his starts. Left to the simulation sweep.

  3. PARK. `USE_PARK` is False and park is a large home-run effect. A pitcher
     throws about half his innings in ONE park all season, so park is a
     PERSISTENT PER-PITCHER home-run effect the model does not carry at all.
     It must show as the pitcher-level residual correlating with the park
     factor of the venues he actually pitched in.

THE ATTENUATION CORRECTION IS THE SAME ONE `spread_cal` DOCUMENTS: `m_hr` is
a Monte Carlo mean over 40 draws per start, so the predictor carries its own
noise, which biases a slope toward zero. Averaging a pitcher's starts cuts it
by root-n, which is why this unit needs a x1.02-x1.19 correction where the
start-level version needed up to x2.9.
"""
from __future__ import annotations

import json

import statistics as st
import sys
from collections import defaultdict

MIN_STARTS = 8
N_SIMS = 40          # draws behind each m_* in ceiling_rows.json
ROWS = "scratchpad/ceiling_rows.json"


def slope(xs, ys):
    """OLS slope of y on x, its standard error, and the correlation."""
    n = len(xs)
    mx, my = st.mean(xs), st.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if not sxx:
        return 0.0, 0.0, 0.0
    b = sxy / sxx
    resid = [y - (my + b * (x - mx)) for x, y in zip(xs, ys)]
    s2 = sum(r * r for r in resid) / max(n - 2, 1)
    se = (s2 / sxx) ** 0.5
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    return b, se, (b * sx / sy if sy else 0.0)


def by_pitcher(rows, ch):
    """{name: (mean pred, mean actual, mean MC variance, n starts)}."""
    acc = defaultdict(lambda: [0.0, 0.0, 0.0, 0])
    for r in rows:
        if r.get(f"m_{ch}") is None or r.get(f"w_{ch}") is None:
            continue
        a = acc[r["player"]]
        a[0] += r[f"m_{ch}"]
        a[1] += r[f"a_{ch}"]
        a[2] += r[f"w_{ch}"]
        a[3] += 1
    return {k: (v[0] / v[3], v[1] / v[3], v[2] / v[3], v[3])
            for k, v in acc.items() if v[3] >= MIN_STARTS}


def park_factors(seasons=("2023", "2024", "2025", "2026")):
    """HR per batter faced in each club's park, against that club on the road.

    The standard construction, and the one that controls for the roster: the
    home team appears on both sides of the ratio, so a slugging club does not
    read as a home-run park. Both clubs' pitching lines are counted, so the
    numerator is every home run hit in the building.

    KEYED ON THE HOME CLUB, NOT ON `venue_id`. Only 2026 rows carry a venue
    id — 2023-2025 are all NULL — and one season is ~67 games per park, which
    is far too thin for a home-run factor. The club is a faithful stand-in
    over this window with two caveats, both checked by `--pf`: a neutral-site
    game is attributed to the nominal home club, and a club that moved parks
    is pooled across both.
    """
    from src import db
    like = " or ".join(f"g.date like '{s}%'" for s in seasons)
    hr = defaultdict(float)
    bf = defaultdict(float)
    with db.connect() as c:
        q = f"""
        select g.home_team_abbr ht, g.away_team_abbr at,
               sum(p.hr) hr,
               sum(p.outs_recorded) + sum(p.h) + sum(p.bb) bf
        from games g join mlb_pitching p on p.game_id = g.game_id
        where g.sport='mlb' and g.status='Final' and ({like})
        group by g.game_id
        """
        for r in c.execute(q):
            if not r["bf"] or not r["ht"] or not r["at"]:
                continue
            hr[("H", r["ht"])] += r["hr"] or 0
            bf[("H", r["ht"])] += r["bf"]
            hr[("A", r["at"])] += r["hr"] or 0
            bf[("A", r["at"])] += r["bf"]
    lg = (sum(hr.values()) / sum(bf.values())) if bf else 0.0
    pf = {}
    for (side, club), n in bf.items():
        if side != "H" or n < 2000 or bf.get(("A", club), 0) < 2000:
            continue
        pf[club] = ((hr[("H", club)] / n)
                    / (hr[("A", club)] / bf[("A", club)]))
    return pf, lg


def home_club_of(game_ids):
    """{game_id: home club abbr} — the park each start was thrown in."""
    from src import db
    out = {}
    with db.connect() as c:
        for r in c.execute("select game_id, home_team_abbr h from games"
                           " where sport='mlb'"):
            out[r["game_id"]] = r["h"]
    return {g: out.get(g) for g in game_ids}


def main(argv):
    rows = [r for r in json.load(open(ROWS)) if not r.get("_team_row")]
    print(f"  {len(rows):,} starts, {MIN_STARTS}+ per arm\n")

    # ---- A. reproduce the measurement being explained -----------------
    print("  A. PITCHER LEVEL — regress mean ACTUAL on mean PREDICTED.")
    print("  This is the +10 sigma result restated. It is the positive")
    print("  control for everything below: if it does not come back at")
    print("  2.36 on home runs, this script is not measuring the same")
    print("  thing the finding was measured on.\n")
    print(f"  {'ch':<7}{'n':>5}{'sd(pred)':>10}{'MC sd':>8}{'sd(true)':>10}"
          f"{'raw b':>8}{'TRUE b':>8}{'z vs 1':>8}")
    per = {}
    for ch in ("er", "h", "hr", "bb", "k", "outs"):
        d = by_pitcher(rows, ch)
        per[ch] = d
        xs = [v[0] for v in d.values()]
        ys = [v[1] for v in d.values()]
        # MC variance of a pitcher's MEAN prediction: the per-start draw
        # variance over N_SIMS, averaged, and then over his own starts.
        mc = st.mean(v[2] / N_SIMS / v[3] for v in d.values())
        b, se, _ = slope(xs, ys)
        var_obs = st.pstdev(xs) ** 2
        var_true = var_obs - mc
        if var_true <= 0:
            print(f"  {ch:<7}{len(xs):>5}  all Monte Carlo noise")
            continue
        infl = var_obs / var_true
        print(f"  {ch:<7}{len(xs):>5}{var_obs ** 0.5:>10.3f}{mc ** 0.5:>8.3f}"
              f"{var_true ** 0.5:>10.3f}{b:>8.3f}{b * infl:>8.3f}"
              f"{(b * infl - 1.0) / (se * infl):>+8.1f}")

    # ---- B. what the shrinkage actually does to the spread ------------
    from src.context import sim
    from src.context.sources import rates as rate_src
    lg = sim.league()
    shipped = rate_src.pitcher_rates(lg, season=2026)
    prior = rate_src._ensure_prior(2026) if rate_src.USE_PRIOR_SEASON else {}
    names = [n for n in per["hr"] if n in shipped]
    print(f"\n  B. THE RATE ITSELF — {len(names)} of {len(per['hr'])} arms"
          f" matched to a shipped rate.")
    print("  raw   = his own 2026 line, unshrunk")
    print("  ship  = what the simulator is handed")
    print("  targ  = what he is shrunk TOWARD (his own prior seasons when")
    print("          he has one, else the league)")
    print("  true  = raw spread with binomial sampling noise removed. This")
    print("          is the honest ceiling on how far apart these arms can")
    print("          be known to be, and what `ship` should be compared to.\n")
    k_pit = rate_src.STABILISE_MEASURED["pit"]["hr_pct"]
    raws, ships, targs, ws, wp, sampvar = [], [], [], [], [], []
    for n in names:
        r = shipped[n]
        bf = r["pa"]
        # Reconstruct the raw rate from the shrink: ship = w*raw+(1-w)*targ.
        t = rate_src.shrink_target(n, None, "hr_pct", lg, prior, {})
        w = bf / (bf + k_pit)
        raw = (r["hr_pct"] - (1 - w) * t) / w
        raws.append(raw)
        ships.append(r["hr_pct"])
        targs.append(t)
        ws.append(w)
        wp.append(1.0 if prior.get(n) else 0.0)
        sampvar.append(max(raw, 1e-6) * (1 - raw) / max(bf, 1))
    var_true = st.pvariance(raws) - st.mean(sampvar)
    print(f"  {'':<8}{'mean':>9}{'sd':>9}")
    for lbl, v in (("raw", raws), ("ship", ships), ("targ", targs)):
        print(f"  {lbl:<8}{st.mean(v):>9.4f}{st.pstdev(v):>9.4f}")
    print(f"  {'true':<8}{'':>9}{max(var_true, 0) ** 0.5:>9.4f}")
    print(f"\n  mean weight on his OWN 2026 line   {st.mean(ws):>6.3f}"
          f"   (k = {k_pit})")
    print(f"  share with a prior-season target   {st.mean(wp):>6.3f}")
    print(f"  sd(ship) / sd(true)                "
          f"{st.pstdev(ships) / max(var_true, 1e-9) ** 0.5:>6.3f}"
          "   <- 1.0 means the rate carries every knowable point of spread")

    # ---- C. park -------------------------------------------------------
    pf, lg_hr = park_factors()
    park_of = home_club_of({r["game_id"] for r in rows})
    print(f"\n  C. PARK — {len(pf)} parks, HR/BF at home against the same"
          f" club on the road, 2023-2026.")
    top = sorted(pf.items(), key=lambda kv: -kv[1])
    print("  extremes: " + ", ".join(f"{v}={f:.2f}" for v, f in top[:4])
          + " ... " + ", ".join(f"{v}={f:.2f}" for v, f in top[-4:]))
    print(f"  sd across parks {st.pstdev(list(pf.values())):.4f}")
    pkc = defaultdict(lambda: [0.0, 0])
    for r in rows:
        f = pf.get(park_of.get(r["game_id"]))
        if f is None:
            continue
        a = pkc[r["player"]]
        a[0] += f
        a[1] += 1
    hr = per["hr"]
    arms = [n for n in hr if pkc.get(n, [0, 0])[1] >= MIN_STARTS]
    xs = [pkc[n][0] / pkc[n][1] for n in arms]          # his mean park factor
    ys = [hr[n][1] - hr[n][0] for n in arms]            # actual - predicted
    b, se, r_ = slope(xs, ys)
    print(f"\n  {len(arms)} arms. Mean park factor over HIS OWN starts,")
    print("  against his pitcher-level home-run residual (actual - pred).")
    print(f"    sd of his mean park factor   {st.pstdev(xs):>8.4f}")
    print(f"    slope of residual on it      {b:>8.4f}  (se {se:.4f},"
          f" z {(b / se if se else 0):+.1f})")
    print(f"    correlation                  {r_:>+8.4f}")
    exp = st.mean([hr[n][0] for n in arms])
    print(f"    implied HR spread from park  {abs(b) * st.pstdev(xs):>8.4f}"
          f"   against sd(true) {st.pstdev([hr[n][1] for n in arms]):.4f}")
    print(f"    (a fully missing park would give slope ~= mean predicted HR"
          f" = {exp:.3f})")

    # And the slope again with park added as a second regressor: if park is
    # the compression, controlling for it should pull the home-run slope
    # toward 1. Two-variable OLS by hand — no numpy in this venv path.
    px = [x - st.mean(xs) for x in xs]
    mx = [hr[n][0] for n in arms]
    mxc = [x - st.mean(mx) for x in mx]
    yy = [hr[n][1] - st.mean([hr[m][1] for m in arms]) for n in arms]
    s11 = sum(a * a for a in mxc)
    s22 = sum(a * a for a in px)
    s12 = sum(a * b_ for a, b_ in zip(mxc, px))
    s1y = sum(a * b_ for a, b_ in zip(mxc, yy))
    s2y = sum(a * b_ for a, b_ in zip(px, yy))
    det = s11 * s22 - s12 * s12
    if det:
        b1 = (s22 * s1y - s12 * s2y) / det
        b2 = (s11 * s2y - s12 * s1y) / det
        print(f"\n    home-run slope CONTROLLING for park   {b1:>7.3f}"
              f"   (was {slope(mx, [hr[n][1] for n in arms])[0]:.3f})")
        print(f"    park coefficient alongside it         {b2:>7.3f}")


def synthetic(argv):
    """D. THE ARTIFACT'S POSITIVE CONTROL — a PERFECT model, scored in sample.

    The slope regression takes x = the model's prediction and y = what the
    pitcher actually did. In sample those are not independent: his shipped
    rate is computed over THE SAME STARTS, so his own sampling noise is
    inside the predictor and inside the outcome at once.

    Write the season line as raw = T + u, where T is true talent and u is
    binomial noise. The model is handed w*raw + (1-w)*prior, and it is
    scored against y = raw. Then

        cov(x, y) = w * (var T + var u) + (1 - w) * cov(prior, T)
        var(x)    = w^2 (var T + var u) + ...

    so the slope tends to 1/w EVEN WHEN THE MODEL IS EXACTLY RIGHT. It is a
    measure of the shrinkage weight, not of the baseball.

    This routine injects a perfectly specified model — true talent drawn to
    the measured spread, a season simulated from it, the shipped shrinkage
    applied — and reports the slope the harness then produces. If it comes
    back near the observed slope, the observed slope is explained and no
    compression has been demonstrated.
    """
    import random
    from src.context import sim
    from src.context.sources import rates as rate_src
    lg = sim.league()
    shipped = rate_src.pitcher_rates(lg, season=2026)
    prior = rate_src._ensure_prior(2026) if rate_src.USE_PRIOR_SEASON else {}
    rows = [r for r in json.load(open(ROWS)) if not r.get("_team_row")]
    arms = {n for n, v in by_pitcher(rows, "hr").items() if n in shipped}
    K = rate_src.STABILISE_MEASURED["pit"]
    rng = random.Random(11)
    print(f"\n  D. POSITIVE CONTROL FOR THE ARTIFACT — {len(arms)} arms,"
          f" a PERFECTLY specified model scored in sample.\n")
    print(f"  {'stat':<9}{'k':>7}{'k*':>7}{'mean w':>9}{'1/w':>8}"
          f"{'sd(true)':>10}{'sd(samp)':>10}{'synth b':>9}{'OBSERVED':>10}")
    obs_b = {"k_pct": 1.116, "bb_pct": 1.135, "hr_pct": 2.359}
    for stat in ("k_pct", "bb_pct", "hr_pct"):
        bfs, raws, sampv, ws, targ = [], [], [], [], []
        for n in arms:
            r = shipped[n]
            bf = r["pa"]
            t = rate_src.shrink_target(n, None, stat, lg, prior, {})
            w = bf / (bf + K[stat])
            raw = (r[stat] - (1 - w) * t) / w
            bfs.append(bf)
            raws.append(raw)
            ws.append(w)
            targ.append(t)
            sampv.append(max(raw, 1e-6) * (1 - raw) / max(bf, 1))
        mu = st.mean(raws)
        var_true = max(st.pvariance(raws) - st.mean(sampv), 1e-9)
        # The prior carries only part of the true spread — measured, not
        # assumed: sd(target) against sd(true).
        lam = st.pstdev(targ) / var_true ** 0.5
        mt = st.mean(targ)
        xs, ys = [], []
        for bf, w in zip(bfs, ws):
            T = max(rng.gauss(mu, var_true ** 0.5), 1e-4)
            hits = sum(1 for _ in range(int(bf)) if rng.random() < T)
            raw = hits / bf
            p = mt + lam * (T - mu)
            xs.append(w * raw + (1 - w) * p)
            ys.append(raw)
        b, _se, _r = slope(xs, ys)
        # THE SHRINKAGE CONSTANT THE DATA ASKS FOR. A rate observed over n
        # plate appearances carries sampling variance p(1-p)/n against a
        # true between-pitcher variance `var_true`, and the posterior-mean
        # weight n/(n+k) is optimal at k = p(1-p)/var_true. Same arithmetic
        # `stabilise` runs from a split half, from the other direction.
        kstar = st.mean(sampv) * st.mean(bfs) / var_true
        print(f"  {stat:<9}{K[stat]:>7}{kstar:>7.0f}{st.mean(ws):>9.3f}"
              f"{1 / st.mean(ws):>8.3f}{var_true ** 0.5:>10.4f}"
              f"{st.mean(sampv) ** 0.5:>10.4f}{b:>9.3f}"
              f"{obs_b[stat]:>10.3f}")
    print("\n  'k*' is the shrinkage constant the measured spread implies:")
    print("  sampling variance over true between-pitcher variance. Compare")
    print("  it to the shipped 'k'. They answer the hypothesis directly.")
    print("\n  'synth b' is what a model that is EXACTLY RIGHT scores on")
    print("  this harness. Compare it to OBSERVED. Where they agree, the")
    print("  observed slope measures the shrinkage weight and says nothing")
    print("  about whether the model separates pitchers correctly.")


if __name__ == "__main__":
    if "--synth" in sys.argv:
        synthetic(sys.argv[1:])
    else:
        main(sys.argv[1:])
