"""Does the model DIFFERENTIATE enough — matchup level and batter level?

    venv/bin/python -m scratchpad.spread_cal

THE QUESTION, as asked: is the offense accurately distributed across the
hitters — should Aaron Judge not be taking a bigger share than an average
bat? The literal per-batter version is not answerable today: `sim.apply_pa`
does not know which batter is up and the bases do not carry runner identity,
so no run can be attributed to whoever drove it in. That is a state-machine
change and is recorded as such.

TWO THINGS THAT ARE ANSWERABLE NOW AND ASK THE SAME THING.

  1. MATCHUP LEVEL. Regress what ACTUALLY happened on what the model
     PREDICTED. Slope 1.0 means the model's spread is right. Slope ABOVE 1
     means its predictions are too BUNCHED — reality separates matchups more
     than the model does, and every prediction should be pushed further from
     the mean. Slope below 1 means it over-differentiates.

     This is the cleanest statement of "is the model too flat", it needs no
     new machinery, and it is not the same as a correlation: a model can
     rank starts perfectly and still compress them all toward the middle.

  2. BATTER LEVEL. The spread of the rates the model FEEDS the lineup
     against the spread of what those hitters actually did. Shrinkage
     deliberately compresses this — the whole point of `STABILISE` — so the
     question is whether it compresses by the right amount. Over-shrink and
     Judge is priced as a league-average bat.

SCORED ON RUNS AND CONTACT, not strikeouts. Strikeouts are the channel this
project already sits at the market's level on.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict


def slope(xs, ys):
    """OLS slope of y on x, plus its standard error and the correlation."""
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
    sy = st.pstdev(ys)
    sx = st.pstdev(xs)
    r = b * sx / sy if sy else 0.0
    return b, se, r


#: Draws behind each `m_*` in `ceiling_rows.json`. Visible in the data —
#: `p_er` moves in steps of 0.025, which is 1/40.
N_SIMS = 40


def main(argv):
    rows = [r for r in json.load(open("scratchpad/ceiling_rows.json"))
            if not r.get("_team_row")]
    print(f"  {len(rows):,} starts\n")
    print("  MATCHUP LEVEL — regress ACTUAL on PREDICTED.")
    print("  slope 1.0 = the model's spread is right.")
    print("  slope > 1 = predictions too BUNCHED; reality separates starts")
    print("  more than the model does.\n")
    # ATTENUATION. `m_ch` is a MONTE CARLO MEAN over 40 draws, so it carries
    # its own sampling noise, and noise in a REGRESSION PREDICTOR biases the
    # slope toward zero. On earned runs that noise is most of the spread:
    # within-start variance 3.37 over 40 draws is an sd of 0.290 against an
    # observed predictor sd of 0.392, so 55% of the variance being regressed
    # on is simulation, not signal.
    #
    # Uncorrected the slope reads 0.594 and says the model OVER-separates
    # starts. Corrected it says the opposite. Reporting the raw number would
    # have been a confident sign error, and the tell was that `p_er` moves in
    # steps of 0.025 — which is 1/40, the draw count, printed in the data.
    print(f"  {'channel':<9}{'n':>7}{'sd(pred)':>10}{'MC sd':>8}"
          f"{'sd(true)':>10}{'raw b':>8}{'TRUE b':>8}{'z vs 1':>8}")
    for ch in ("er", "h", "hr", "bb", "k", "outs"):
        xs, ys, ws = [], [], []
        for r in rows:
            if r.get(f"m_{ch}") is None or r.get(f"w_{ch}") is None:
                continue
            xs.append(r[f"m_{ch}"])
            ys.append(r[f"a_{ch}"])
            ws.append(r[f"w_{ch}"])
        if len(xs) < 100:
            continue
        b, se, _r = slope(xs, ys)
        var_obs = st.pstdev(xs) ** 2
        mc_var = st.mean(ws) / N_SIMS
        var_true = var_obs - mc_var
        if var_true <= 0:
            print(f"  {ch:<9}{len(xs):>7,}  predictor is ALL Monte Carlo "
                  f"noise at {N_SIMS} draws — unmeasurable")
            continue
        infl = var_obs / var_true
        print(f"  {ch:<9}{len(xs):>7,}{var_obs ** 0.5:>10.3f}"
              f"{mc_var ** 0.5:>8.3f}{var_true ** 0.5:>10.3f}"
              f"{b:>8.3f}{b * infl:>8.3f}"
              f"{(b * infl - 1.0) / (se * infl):>+8.1f}")

    print("\n  A slope indistinguishable from 1 means the model separates")
    print("  starts by the right AMOUNT — it can still separate them in the")
    print("  wrong ORDER, which is what the correlation says.")

    # ---- BATTER LEVEL -------------------------------------------------
    from src.context import sim
    from src.context.sources import rates as rate_src
    lg = sim.league()
    shrunk = rate_src.batter_rates(lg)
    print(f"\n  BATTER LEVEL — {len(shrunk):,} batters with a model rate.")
    print("  Spread of the rate the model FEEDS the lineup against the")
    print("  spread of what those hitters actually did. Shrinkage")
    print("  deliberately compresses this; the question is by how much.\n")
    print(f"  {'stat':<9}{'n':>6}{'sd(model)':>11}{'sd(raw)':>10}"
          f"{'ratio':>8}")
    raw = rate_src.batter_rates(lg, conn=None)
    # `batter_rates` is already shrunk, so the raw comparison has to be
    # rebuilt from the counting stats rather than re-read from it.
    from src import db
    with db.connect() as c:
        obs = {}
        for r in c.execute(
                "select player_name name, sum(ab) ab, sum(bb) bb,"
                " sum(so) so, sum(h) h, sum(hr) hr from mlb_batting mb"
                " join games g on g.game_id = mb.game_id"
                " where g.sport='mlb' and g.date like '2026%'"
                " group by player_name having sum(ab)+sum(bb) >= 250"):
            pa = (r["ab"] or 0) + (r["bb"] or 0)
            bip = (r["ab"] or 0) - (r["so"] or 0) - (r["hr"] or 0)
            if pa < 250 or bip <= 0:
                continue
            obs[r["name"]] = {
                "k_pct": (r["so"] or 0) / pa, "bb_pct": (r["bb"] or 0) / pa,
                "hr_pct": (r["hr"] or 0) / pa,
                "babip": ((r["h"] or 0) - (r["hr"] or 0)) / bip}
    for stat in ("k_pct", "bb_pct", "hr_pct", "babip"):
        m, o = [], []
        for nm, v in obs.items():
            mv = shrunk.get(nm)
            if not mv:
                continue
            m.append(mv[stat])
            o.append(v[stat])
        if len(m) < 30:
            continue
        print(f"  {stat:<9}{len(m):>6}{st.pstdev(m):>11.4f}"
              f"{st.pstdev(o):>10.4f}{st.pstdev(m) / st.pstdev(o):>8.3f}")
    print("\n  ratio near 1 means the model carries the full observed")
    print("  spread. Well BELOW 1 means it is flattening the hitters — the")
    print("  good bat priced closer to average than he is. Some flattening")
    print("  is CORRECT, because observed spread contains sampling noise;")
    print("  the right target is the RELIABLE share, which `stabilise`")
    print("  measured. This says whether the shipped result matches it.")


if __name__ == "__main__":
    main(sys.argv[1:])
