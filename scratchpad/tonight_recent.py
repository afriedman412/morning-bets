"""One upcoming game, simulated FLAT vs RECENCY-WEIGHTED, same draws.

    venv/bin/python -m scratchpad.tonight_recent 2026-09-07 ATL PHI [HL]

Rates run through TODAY (not the holdout freeze — recency is the point),
pitcher rates built twice via `pitcher_rates(half_life=...)`, everything
else identical: same league baseline, same batters, same bullpens, same
seed stream. The divergence is the half-life's doing and nothing else's.

CONTEXT FOR READING IT: the sweep (day-22, second sitting) REFUSED to ship
this — K got worse in 16/16 cells, outs improved on the clean fold only.
This scratchpad exists to LOOK at the divergence on one slate, not to
price with it.
"""
from __future__ import annotations

import random
import sys

import numpy as np

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src
from src.context.sources import weather as weather_src
from scratchpad import tonight_two as tt

TARGETS = {"k": ("k", 20), "outs": ("outs", 28)}


def simulate(date_str, g, pair, lg, pens, n_sims):
    wx = {r["game_id"]: r for r in weather_src.fetch_date(date_str)}
    w = wx.get(g["game_id"]) or {}
    hr_air = sim.air_hr_mult(w.get("temp_f"), w.get("carry"),
                             w.get("wind_mph"))
    park = cal.park_for(g["venue_id"], 2026) if cal.USE_PARK else None
    hist = {s: {t: np.zeros(cap + 1) for t, (_a, cap) in TARGETS.items()}
            for s in ("away", "home")}
    rng = random.Random(11)          # same stream both arms — the A/B rule
    for _ in range(n_sims):
        sides = {}
        for side, (row, p, nine) in zip(("away", "home"), pair):
            hook = sim.for_start(sim.Hook(), row["team"], p.name)
            if side == "home" and cal.HOME_HOOK:
                hook = sim.Hook(**{**hook.__dict__,
                                   "team_offset": hook.team_offset
                                   + cal.HOME_HOOK})
            sides[side] = game.build_side(
                p, pens.get((row["team"] or "").upper(), []), nine, hook,
                rng, team=row["team"], apply_leash=False, date=date_str)
        res = game.simulate_game(sides["away"], sides["home"], lg, rng,
                                 park=park, hr_air=hr_air)
        for side, sp in (("away", res.away_sp), ("home", res.home_sp)):
            for t, (attr, cap) in TARGETS.items():
                hist[side][t][min(int(getattr(sp, attr)), cap)] += 1
    for s in hist:
        for t in hist[s]:
            hist[s][t] /= n_sims
    return hist


def main(date_str, away, home, hl=60.0, n_sims=4000):
    g = tt.find(date_str, away, home)
    cut = date_str                    # through today: recency needs the data
    lg = sim.league(2026, before=cut)
    br = rate_src.batter_rates(lg, 2026, cut)
    pens = rate_src.bullpens(lg, 2026, cut)
    league_bats = sim.BatterRates(
        name="league", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
        hr_pct=lg["hr_pct"], babip=lg["babip"], pa=0)

    arms = {}
    for label, h in (("flat", 0), ("recent", hl)):
        pr = rate_src.pitcher_rates(lg, 2026, cut, half_life=h)
        pair = tt.build_pair(g, date_str, lg, pr, br, league_bats)
        arms[label] = (pair, simulate(date_str, g, pair, lg, pens, n_sims))

    print(f"  {g['away']['abbr']} @ {g['home']['abbr']}  {date_str}  "
          f"rates through today; half-life {hl:.0f}d; {n_sims} draws each\n")
    pair = arms["flat"][0]
    for si, side in enumerate(("away", "home")):
        row, p, _nine = pair[si]
        pf = arms["flat"][0][si][1]
        pr_ = arms["recent"][0][si][1]
        print(f"  {p.name} ({row['team']})   "
              f"k% {pf.k_pct:.3f} -> {pr_.k_pct:.3f}   "
              f"bb% {pf.bb_pct:.3f} -> {pr_.bb_pct:.3f}   "
              f"babip {pf.babip:.3f} -> {pr_.babip:.3f}")
        for t, (_a, cap) in TARGETS.items():
            hf = arms["flat"][1][side][t]
            hr_ = arms["recent"][1][side][t]
            mf = float(np.sum(np.arange(cap + 1) * hf))
            mr = float(np.sum(np.arange(cap + 1) * hr_))
            top = max(np.nonzero(hf > 0.004)[0].max(),
                      np.nonzero(hr_ > 0.004)[0].max())
            lo = min(np.nonzero(hf > 0.004)[0].min(),
                     np.nonzero(hr_ > 0.004)[0].min())
            print(f"    {t.upper():<5} mean flat {mf:.2f}  recent {mr:.2f}"
                  f"  ({mr - mf:+.2f})")
            print("      " + "".join(f"{v:>7}" for v in range(lo, top + 1)))
            print("      flat  " + "".join(f"{hf[v]:>6.1%} "
                                           for v in range(lo, top + 1)))
            print("      recent" + "".join(f"{hr_[v]:>6.1%} "
                                           for v in range(lo, top + 1)))
        print()


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], a[2], float(a[3]) if len(a) > 3 else 60.0)
