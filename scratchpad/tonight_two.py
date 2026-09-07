"""One upcoming game, priced by BOTH models, so the divergence is visible.

    venv/bin/python -m scratchpad.tonight_two 2026-09-07 TOR ATH [SIMS]

The simulator side is the shipped live path (`slate.simulate_slate_game`).
The fitted side is `scratchpad.direct`'s Poisson GLM, refitted here on the
same training rows and handed features built the same way.

RATES ARE FROZEN AT THE HOLDOUT CUT, not at today. That looks wrong for a
live game and is the only choice that makes the comparison mean anything:
the GLM's coefficients were fitted on features built from three months of
rates, and the holdout it was validated on scored September starts off
July-1-frozen rates too. Feeding it season-to-date rates would hand it
inputs of a shrinkage it has never seen. The cost is real and should be
said out loud — neither number here knows what either pitcher has done
since June.

THE LINEUP IS THE WEAK LINK when none is posted, and both models eat the
same projected nine, so a wrong name moves both together rather than
showing up as divergence.
"""
from __future__ import annotations

import random
import sys

import numpy as np

from src.context import calibrate as cal
from src.context import game, sim, slate
from src.context.holdout import HOLDOUT
from src.context.sources import rates as rate_src
from src.context.sources import weather as weather_src
from scratchpad import direct

TARGETS = direct.TARGETS


def find(date_str: str, away: str, home: str) -> dict:
    for g in slate.slate(date_str):
        if {g["away"]["abbr"], g["home"]["abbr"]} == {away, home}:
            return g
    raise SystemExit(f"no {away}/{home} game on {date_str}")


def build_pair(g, date_str, lg, pr, br, league_bats):
    """The two (row, PitcherRates, opposing nine) triples, slate-style."""
    out = {}
    for side, opp in (("away", "home"), ("home", "away")):
        s, o = g[side], g[opp]
        name = s["starter"]
        p = pr.get(name)
        if not p:
            raise SystemExit(f"no rates on record for {name}")
        names = o["lineup"] or slate.projected_lineup(o["abbr"], date_str)
        if len(names) < 9:
            raise SystemExit(f"could not build a lineup for {o['abbr']}")
        nine = cal.adjust_lineup(
            slate._build(names, br, league_bats), side == "home")
        row = {"game_id": g["game_id"], "team": s["abbr"],
               "player_name": name, "date": date_str,
               "venue_id": g["venue_id"], "is_home": side == "home"}
        rates = sim.PitcherRates(
            name=name, k_pct=p["k_pct"], bb_pct=p["bb_pct"],
            hr_pct=p["hr_pct"], babip=p["babip"], pa=p["pa"],
            hand=__import__("src.roster", fromlist=["x"]).throws(name) or "")
        out[side] = (row, rates, nine)
    return (out["away"], out["home"])


def main(date_str, away, home, n_sims=4000, cut=None):
    """`cut` is the rate freeze. Defaults to the holdout, which is what
    makes the two models COMPARABLE. Pass today's date to make them
    CURRENT — and note the trade: the GLM's coefficients were fitted on
    features built from three-month rate windows, so a five-month window
    feeds it a shrinkage it was not fitted on. The simulator has no such
    problem; season-to-date rates are how `slate.py` runs it in production.
    """
    cut = cut or HOLDOUT
    g = find(date_str, away, home)
    lg = sim.league(2026, before=cut)
    pr = rate_src.pitcher_rates(lg, 2026, cut)
    br = rate_src.batter_rates(lg, 2026, cut)
    pens = rate_src.bullpens(lg, 2026, cut)
    league_bats = sim.BatterRates(
        name="league", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
        hr_pct=lg["hr_pct"], babip=lg["babip"], pa=0)
    pair = build_pair(g, date_str, lg, pr, br, league_bats)

    print(f"  {g['away']['abbr']} @ {g['home']['abbr']}  {date_str}  "
          f"venue {g['venue_id']}  ({g['status']})")
    for side, (row, p, nine) in zip(("away", "home"), pair):
        posted = "posted" if g[
            "home" if side == "away" else "away"]["lineup"] else "projected"
        print(f"  {p.name:<20} {row['team']:<4} vs a {posted} nine: "
              f"{', '.join(b.name for b in nine[:3])} ...")
    print(f"  rates frozen before {cut}; {n_sims} draws\n")

    # ── the simulator ──────────────────────────────────────────────────
    wx = {r["game_id"]: r for r in weather_src.fetch_date(date_str)}
    w = wx.get(g["game_id"]) or {}
    hr_air = sim.air_hr_mult(w.get("temp_f"), w.get("carry"),
                             w.get("wind_mph"))
    park = cal.park_for(g["venue_id"], 2026) if cal.USE_PARK else None
    caps = {t: TARGETS[t][2] for t in TARGETS}
    hist = {side: {t: np.zeros(caps[t] + 1) for t in TARGETS}
            for side in ("away", "home")}
    rng = random.Random(11)
    for i in range(n_sims):
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
            for t, (_f, attr, cap, _c) in TARGETS.items():
                hist[side][t][min(int(getattr(sp, attr)), cap)] += 1
    for side in hist:
        for t in hist[side]:
            hist[side][t] /= n_sims

    # ── the fitted model, on the same inputs ───────────────────────────
    tr, _te = direct.build_all()
    direct._LG = lg
    fitted = {}
    for side, case in zip(("away", "home"), pair):
        x = np.array([direct.features(case)])
        fitted[side] = {}
        for t in TARGETS:
            pmfs = direct.fit_direct([(f, y[t], c) for f, y, c in tr],
                                     [(x[0], 0.0, case)], t, quiet=True)
            fitted[side][t] = pmfs["glm"][0]

    out = {"game": f"{g['away']['abbr']} @ {g['home']['abbr']}",
           "date": date_str, "venue_id": g["venue_id"], "draws": n_sims,
           "park": cal.park_for(g["venue_id"], 2026) or {},
           "air": round(hr_air, 4), "pitchers": []}
    for side, (row, p, nine) in zip(("away", "home"), pair):
        out["pitchers"].append({
            "name": p.name, "team": row["team"],
            "opp": g["home" if side == "away" else "away"]["abbr"],
            "faces": [b.name for b in nine],
            "stats": {t: {"support": list(range(TARGETS[t][2] + 1)),
                          "sim": [round(float(x), 6) for x in hist[side][t]],
                          "fit": [round(float(x), 6)
                                  for x in fitted[side][t]]}
                      for t in TARGETS}})
    import json as _json
    tag = "" if cut == HOLDOUT else "_now"
    path = f"scratchpad/game_{g['game_id'].split('-')[-1]}{tag}.json"
    _json.dump(out, open(path, "w"))
    print(f"  -> {path}")

    for side, (row, p, _n) in zip(("away", "home"), pair):
        print(f"\n  {p.name} ({row['team']})")
        for t, (_f, _a, cap, _c) in TARGETS.items():
            s, f = hist[side][t], fitted[side][t]
            top = max(i for i in range(cap + 1)
                      if max(s[i], f[i]) > 0.004)
            print(f"    {t.upper():<5} " + "  ".join(
                f"{i}:{s[i]:.2f}/{f[i]:.2f}" for i in range(top + 1)))
            ms = sum(i * s[i] for i in range(cap + 1))
            mf = sum(i * f[i] for i in range(cap + 1))
            print(f"    {'':<5} mean  sim {ms:.2f}   fitted {mf:.2f}   "
                  f"diff {mf - ms:+.2f}")
    print("\n  each cell is value:SIM/FITTED. Divergence, not agreement, "
          "is the signal.")


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("-")]
    d = a[0] if a else "2026-09-07"
    aw = a[1] if len(a) > 1 else "TOR"
    hm = a[2] if len(a) > 2 else "ATH"
    n = int(a[3]) if len(a) > 3 else 4000
    now = next((x.split("=")[1] for x in sys.argv
                if x.startswith("--cut=")), None)
    main(d, aw, hm, n, cut=now)
