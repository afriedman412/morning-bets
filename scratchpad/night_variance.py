"""How much of the parked dispersion term do the shipped conditions explain?

    venv/bin/python -m scratchpad.night_variance

QUESTION: `scratchpad/dispersion.py` measured that a per-side latent with
sigma 0.10 (k down, bb/hr/babip up, coherently — LOAD there) closes both
the shape gap and the level gap. It is PARKED: flat variance buys
calibration, not discrimination. Since it was parked, four SHARED-NIGHT
conditions shipped — park (per-year venue index), temperature, wind, and
the plate umpire — each a real, counted piece of "some nights favour
runs". This measures what fraction of the latent's variance the shipped
stack now explains, which is the number the re-open decision needs.

METHOD, in one currency: per-game LOG RUN-EXPECTATION SHIFT.

  * ELASTICITIES e_c = d ln(runs) / d ln(rate_c) are measured from the
    engine itself: both lineups' channel probability scaled +-10%, 4,000
    full games a point, fixed seed. Probability scaling matches how the
    latent applies (rate x exp(load*sigma*z)); the shipped conditions
    multiply ODDS, so their multipliers are converted to probability
    scale at the league rate first (om -> om / (1 + p*(om-1))).
  * TARGET: sd_target = 0.10 * (|e_k| + e_bb + e_hr + e_babip) — the
    coherent sum, because one draw moves all four together.
  * SHIPPED: for every real game, lambda_g = sum_c e_c * ln(prob mult_c)
    over park (k/bb/hr/bip), air (hr), umpire (k/bb). Missing readings
    contribute exactly 0, as they do in the engine. Variance of lambda_g
    over games IS the shipped between-night variance, covariances
    included (domes have no wind AND their own park).
  * POPULATION: July-onward Final games, all four seasons — the same
    half of the calendar the sigma-0.10 need was measured on. The
    conditions are read as SHIPPED (shrunk umpire table); the umpire's
    unshrunk tau reading is reported beside it as the ceiling.

REGISTERED BEFORE THE RUN: the guess is that the stack explains a small
share — air is one channel, the umpire ships shrunk, and the latent's
babip load (the biggest run lever) has NO shipped counterpart. If the
number comes back under ~10%, the honest conclusions are (a) the
night-to-night variance is mostly NOT yet explained by counted shared
conditions, and (b) the biggest missing channel is ball-in-play.

THE RESULT, 2026-09-06 — the guess was right on the line:

    elasticity (engine-measured, 4,000 games/point):
        k -0.439   bb +0.202   hr +0.387   babip +1.186
    target: sigma 0.10 x coherent sum 2.213 -> log-run sd 0.2213
    shipped stack: per-game log-run sd 0.0709 -> EXPLAINS 10.2%
        park 7.4%   air 1.4%   umpire 0.1% (0.4% at unshrunk tau)

Three conclusions, all decision-grade:

  * THE FUDGE IS 90% INTACT. Re-measured today the latent would need
    sigma ~0.095 instead of 0.10. Counting shared conditions is working
    but at this rate it does not close the shape defect in any
    reasonable number of items — the dispersion-as-remainder ship is
    the only near-term route to the marginal shape, and that remains a
    HUMAN decision.
  * RUN VARIANCE LIVES IN THE BALL IN PLAY. babip's elasticity (1.19)
    is 3x hr's and 6x bb's. Every future shared-night candidate should
    be priced in this currency first: a k/bb-channel effect (catcher
    framing) is worth ~1/6th of an equal-sized babip effect for the
    run distribution — still worth counting for K props, but it will
    not close the dispersion gap.
  * THE UMPIRE'S SMALLNESS HERE IS THE CURRENCY, NOT THE MECHANISM:
    tau 4.4% on walks is real and repeats, but walks move run
    expectation weakly (e_bb 0.20), so its run-variance share is tiny
    even at the tau ceiling.
"""
from __future__ import annotations

import math
import random
import statistics as st
import sys
from dataclasses import replace

from src import db
from src.context import game, sim
from src.context.sources import weather
from src.context import calibrate as cal
from tests.test_sim import LG, _lineup, _pitcher
from tests.test_game import _pen

SIGMA = 0.10
LOAD = {"k_pct": -1.0, "bb_pct": 1.0, "hr_pct": 1.0, "babip": 1.0}
N_GAMES = 4000
BUMP = 1.10


def _side():
    return game.Side(starter=_pitcher(), pen=_pen(), lineup=_lineup(),
                     hook=sim.Hook())


def _mean_runs(scale: dict[str, float], seed=71) -> float:
    """Mean total runs over N_GAMES with both lineups' channels scaled."""
    rng = random.Random(seed)
    total = 0
    for _ in range(N_GAMES):
        a, h = _side(), _side()
        for s in (a, h):
            s.lineup = [replace(b, **{c: min(0.9, getattr(b, c) * m)
                                      for c, m in scale.items()})
                        for b in s.lineup]
        r = game.simulate_game(a, h, LG, rng, hr_air=1.0,
                               ump_kbb=(1.0, 1.0))
        total += r.away + r.home
    return total / N_GAMES


def elasticities() -> dict[str, float]:
    out = {}
    for c in ("k_pct", "bb_pct", "hr_pct", "babip"):
        up = _mean_runs({c: BUMP})
        dn = _mean_runs({c: 1 / BUMP})
        out[c] = math.log(up / dn) / (2 * math.log(BUMP))
        print(f"    e_{c:<8} {out[c]:+7.3f}   "
              f"(runs {dn:.3f} -> {up:.3f} across x{1/BUMP:.3f}..x{BUMP:.3f})")
    return out


def _prob_mult(om: float, p: float) -> float:
    """An odds multiplier's effect on the probability, at league rate p."""
    return om / (1.0 + p * (om - 1.0))


def shipped_lambda(e: dict[str, float]) -> list[float]:
    """Per-game log-run shift from park + air + umpire, July-onward games."""
    with db.connect() as c:
        games = [dict(r) for r in c.execute(
            "select g.game_id, g.date, g.venue_id, o.plate_ump_id"
            " from games g left join game_officials o"
            " on o.game_id = g.game_id"
            " where g.sport='mlb' and g.status='Final'"
            " and cast(substr(g.date,6,2) as int) >= 7")]
    wx = weather.by_game()
    lg_p = {"k_pct": LG["k_pct"], "bb_pct": LG["bb_pct"],
            "hr_pct": LG["hr_pct"], "babip": LG["babip"]}
    lam, cover = [], {"park": 0, "air": 0, "ump": 0}
    for g_ in games:
        x = 0.0
        d = g_.get("date") or ""
        park = cal.park_for(g_.get("venue_id"),
                            int(d[:4]) if d[:4].isdigit() else None)
        if park:
            cover["park"] += 1
            for ch, key in (("k_pct", "k"), ("bb_pct", "bb"),
                            ("hr_pct", "hr"), ("babip", "bip")):
                om = park.get(key, 1.0)
                x += e[ch] * math.log(_prob_mult(om, lg_p[ch]))
        w = wx.get(g_["game_id"]) or {}
        air = sim.air_hr_mult(w.get("temp_f"), w.get("carry"),
                              w.get("wind_mph"))
        if air != 1.0:
            cover["air"] += 1
        x += e["hr_pct"] * math.log(_prob_mult(air, lg_p["hr_pct"]))
        uk, ub = sim.ump_kbb_mult(g_.get("plate_ump_id"))
        if (uk, ub) != (1.0, 1.0):
            cover["ump"] += 1
        x += e["k_pct"] * math.log(_prob_mult(uk, lg_p["k_pct"]))
        x += e["bb_pct"] * math.log(_prob_mult(ub, lg_p["bb_pct"]))
        lam.append(x)
    n = len(games)
    print(f"\n  {n:,} July-onward games; coverage park "
          f"{cover['park']/n:.2f}  air {cover['air']/n:.2f}  "
          f"ump {cover['ump']/n:.2f}")
    return lam


def main(argv):
    print("\n  ELASTICITIES, from the engine "
          f"({N_GAMES:,} games a point):")
    e = elasticities()

    coherent = sum(abs(e[c]) for c in LOAD)
    target = SIGMA * coherent
    print(f"\n  TARGET (the parked latent, sigma {SIGMA}):")
    print(f"    coherent elasticity sum {coherent:.3f}"
          f" -> per-side log-run sd {target:.4f}")

    lam = shipped_lambda(e)
    sd = st.pstdev(lam)
    print("\n  SHIPPED STACK (park + air + umpire, as shipped):")
    print(f"    per-game log-run sd {sd:.4f}")
    frac = sd * sd / (target * target)
    print(f"    EXPLAINED FRACTION of the latent's variance: {frac:.1%}")

    # The umpire ships shrunk; tau is the true between-night spread.
    # Scale its per-channel contribution up to tau for the ceiling read.
    ceil_k = 0.0176 / 0.0082 if 0.0082 else 1.0
    ceil_bb = 0.0438 / 0.0248 if 0.0248 else 1.0
    print(f"\n    (umpire ships SHRUNK; at tau its k/bb spreads are"
          f" x{ceil_k:.1f}/x{ceil_bb:.1f} — a ceiling, not a ship)")

    # Per-condition variance, marginal (others zeroed), for the ranking.
    print("\n  PER-CONDITION sd (marginal):")
    for name, keep in (("park", "p"), ("air", "a"), ("ump", "u")):
        lam1 = _marginal(e, keep)
        print(f"    {name:<6} {st.pstdev(lam1):.4f}   "
              f"({st.pvariance(lam1)/(target*target):.1%} of target var)")


def _marginal(e, keep):
    with db.connect() as c:
        games = [dict(r) for r in c.execute(
            "select g.game_id, g.date, g.venue_id, o.plate_ump_id"
            " from games g left join game_officials o"
            " on o.game_id = g.game_id"
            " where g.sport='mlb' and g.status='Final'"
            " and cast(substr(g.date,6,2) as int) >= 7")]
    wx = weather.by_game()
    lg_p = {"k_pct": LG["k_pct"], "bb_pct": LG["bb_pct"],
            "hr_pct": LG["hr_pct"], "babip": LG["babip"]}
    out = []
    for g_ in games:
        x = 0.0
        if keep == "p":
            d = g_.get("date") or ""
            park = cal.park_for(g_.get("venue_id"),
                                int(d[:4]) if d[:4].isdigit() else None)
            if park:
                for ch, key in (("k_pct", "k"), ("bb_pct", "bb"),
                                ("hr_pct", "hr"), ("babip", "bip")):
                    x += e[ch] * math.log(
                        _prob_mult(park.get(key, 1.0), lg_p[ch]))
        elif keep == "a":
            w = wx.get(g_["game_id"]) or {}
            air = sim.air_hr_mult(w.get("temp_f"), w.get("carry"),
                                  w.get("wind_mph"))
            x += e["hr_pct"] * math.log(_prob_mult(air, lg_p["hr_pct"]))
        else:
            uk, ub = sim.ump_kbb_mult(g_.get("plate_ump_id"))
            x += e["k_pct"] * math.log(_prob_mult(uk, lg_p["k_pct"]))
            x += e["bb_pct"] * math.log(_prob_mult(ub, lg_p["bb_pct"]))
        out.append(x)
    return out


if __name__ == "__main__":
    main(sys.argv[1:])
