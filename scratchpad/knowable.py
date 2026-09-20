"""HOW MUCH OF A BASEBALL GAME IS KNOWABLE BEFORE IT STARTS?

    venv/bin/python -m scratchpad.knowable [DRAWS] [--fold 2026]

Not a diagnostic and not a fit. This decomposes the variance of what
actually happened into the part any pregame model could in principle move
and the part that is the game happening.

    var(actual)  =  var(what the model can tell apart)  +  the rest

The three quantities it prints per target:

  spread   the sd of our PREGAME predictions across games — how different
           the model thinks games are from each other before they start.
  r        correlation between that prediction and the outcome.
  r^2      the share of the outcome's variance our ordering explains.

THE MONTE-CARLO CORRECTION IS THE WHOLE REASON THIS FILE IS CAREFUL. A
simulated mean carries its own noise, and at 40 draws that noise is a large
fraction of the spread being measured — the same denominator trap recorded
in CLAUDE.md, where 55% of `m_er`'s variance was simulation rather than
signal. Every game's draw variance is recorded here and var/n is subtracted
from the observed spread of predictions, so `spread` is the model's real
between-game separation and not the simulator shaking. Both the raw and the
corrected figures print; if they differ much, raise the draw count.

THE FOLD IS THE CLEAN ONE BY DEFAULT. Every shipped constant was fitted on
rows before 2026-07-01, so scoring July-onward of 2023/2024/2025 — as the
battery's other three folds do — is inside the constant-fitting window.
Only the 2026 fold is out of sample for both the rates and the constants.
"""
from __future__ import annotations

import random
import statistics as st
import sys

from src import db
from src.context import calibrate as cal
from src.context import sim
from src.context.sources import rates as rate_src

#: Fold cut. Rates frozen before it, games scored from it onward.
CUTS = {2023: "2023-07-01", 2024: "2024-07-01",
        2025: "2025-07-01", 2026: "2026-07-01"}


def actuals() -> dict:
    with db.connect() as c:
        return {r["game_id"]: dict(r) for r in c.execute(
            "select game_id, away_score, home_score, away_score_f5,"
            " home_score_f5 from games where sport='mlb' and status='Final'")}


def run(fold: int = 2026, draws: int = 200, limit: int | None = None):
    cut = CUTS[fold]
    lg = sim.league(before=cut)
    pens = rate_src.bullpens(lg, before=cut)
    pairs = cal.paired_cases(season=fold, since=cut, rates_before=cut)
    act = actuals()
    gids = [g for g in sorted(pairs)
            if act.get(g, {}).get("away_score") is not None]
    if limit:
        gids = gids[:limit]
    print(f"  fold {fold}: {len(gids)} games from {cut}, {draws} draws each"
          f"{'  [DEV LIMIT]' if limit else ''}", flush=True)

    #: per target: [(model mean, model draw variance, actual)]
    rows: dict[str, list] = {k: [] for k in
                             ("total", "team", "f5_team", "margin")}
    for i, gid in enumerate(gids):
        pair = pairs[gid]
        tot, aw, hm, f5a, f5h, mar = [], [], [], [], [], []
        for d in range(draws):
            rng = random.Random(i * 100003 + d)
            r = cal.replay(pair, lg, pens, rng, track=(5,))
            tot.append(r.total)
            aw.append(r.away)
            hm.append(r.home)
            f5a.append(r.away_f5)
            f5h.append(r.home_f5)
            mar.append(r.home - r.away)
        a = act[gid]
        rows["total"].append((st.mean(tot), st.variance(tot),
                              a["away_score"] + a["home_score"]))
        rows["margin"].append((st.mean(mar), st.variance(mar),
                               a["home_score"] - a["away_score"]))
        for sim_, var_, real in ((aw, None, a["away_score"]),
                                 (hm, None, a["home_score"])):
            rows["team"].append((st.mean(sim_), st.variance(sim_), real))
        if a["away_score_f5"] is not None:
            rows["f5_team"].append((st.mean(f5a), st.variance(f5a),
                                    a["away_score_f5"]))
            rows["f5_team"].append((st.mean(f5h), st.variance(f5h),
                                    a["home_score_f5"]))
        if (i + 1) % 50 == 0:
            print(f"    {i + 1}/{len(gids)}", flush=True)
    return rows, draws


def report(rows: dict, draws: int, dump: str | None = None) -> None:
    if dump:
        import json
        json.dump({k: [list(x) for x in v] for k, v in rows.items()},
                  open(dump, "w"))
        print(f"  rows -> {dump}")
    print(f"\n  {'target':<10}{'n':>6}{'sd(actual)':>12}{'spread raw':>12}"
          f"{'spread adj':>12}{'r':>8}{'r^2':>8}{'slope':>16}")
    for name, v in rows.items():
        if not v:
            continue
        m = [x[0] for x in v]
        a = [x[2] for x in v]
        n = len(v)
        sd_a = st.pstdev(a)
        sd_m = st.pstdev(m)
        # Every prediction carries var/draws of Monte-Carlo noise, which
        # inflates the observed spread of predictions. Subtract the mean of
        # it — the correction is on the VARIANCE, not the sd.
        mc = st.mean(x[1] for x in v) / draws
        adj = max(sd_m ** 2 - mc, 0) ** 0.5
        r = st.correlation(m, a) if sd_m > 0 else 0.0
        # Slope of actual on prediction. 1.0 means the predicted spread is
        # the right SIZE; below 1 means the model separates games more than
        # reality rewards.
        slope = st.covariance(m, a) / st.variance(m) if sd_m > 0 else 0.0
        # se of the slope, so "we under-separate" is a claim with a bar on
        # it. Residual sd about the fitted line, over sd(pred) * sqrt(n).
        b0 = st.mean(a) - slope * st.mean(m)
        res = [ai - (b0 + slope * mi) for mi, ai in zip(m, a)]
        sse = (st.pstdev(res) / (sd_m * n ** 0.5)) if sd_m > 0 else 0.0
        print(f"  {name:<10}{n:>6}{sd_a:>12.3f}{sd_m:>12.3f}{adj:>12.3f}"
              f"{r:>8.3f}{r * r:>8.3f}{slope:>10.2f} ±{sse:.2f}")
    print(f"\n  spread adj = between-game separation with the {draws}-draw "
          f"Monte-Carlo variance removed.")
    print("  r^2 = share of the outcome's variance OUR pregame ordering "
          "explains. 1 - r^2 is NOT\n  a proof of irreducibility — a better "
          "model could score higher. What bounds it is\n  the market: our "
          "resolution sits at 91-98% of Kalshi's, so the best public\n  "
          "predictor is not far above these numbers.")
    print("  slope = runs of real movement per run of predicted movement. "
          "ABOVE 1 means the\n  model SEPARATES GAMES TOO LITTLE — its "
          "ordering is right but compressed.")


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("-")]
    draws = int(a[0]) if a else 200
    fold = 2026
    lim = None
    for x in sys.argv:
        if x.startswith("--fold"):
            fold = int(x.split("=")[-1]) if "=" in x else fold
        if x.startswith("--limit="):
            lim = int(x.split("=")[1])
    rows, d = run(fold, draws, lim)
    report(rows, d, dump=f"scratchpad/knowable_{fold}.json")
