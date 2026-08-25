"""Price Ian Seymour's K prop past the swingman gate, and say what the
gate was protecting against.

`price.priceable` declines him on start share alone — 8 of 37 appearances
are starts, against a 0.50 bar — while every other gate passes with room
(8 starts vs 3, 355 BF vs 80, 15.1 average outs vs 11). The gate exists
because a bulk reliever's pooled rates do not describe a start. Seymour is
the case it handles badly: he CONVERTED, starting five of his last six, so
the season-long share is describing a role he no longer has.

Two rate sets are simulated so the pooling is visible rather than assumed:
the shipped pooled rate, and one counted from his starts only.

    venv/bin/python -m scratchpad.seymour
"""
from __future__ import annotations

from src import db
from src.context import price as pm
from src.context import sim
from src.context.sources import rates as rate_src

NAME = "Ian Seymour"
DATE = "2026-08-25"
LINE = 5.5
N = 40000


def split_rates(name: str, before: str) -> dict:
    """Raw K/BB/HR/BABIP counted separately over starts and relief."""
    q = """select p.is_starter s, sum(p.batters_faced) bf, sum(p.k) k,
                  sum(p.bb) bb, sum(p.hr) hr, sum(p.h) h, sum(p.outs_recorded) o
           from mlb_pitching p join games g on g.game_id = p.game_id
           where p.player_name = ? and g.status = 'Final' and g.date < ?
           group by p.is_starter"""
    with db.connect() as c:
        return {r["s"]: dict(r) for r in c.execute(q, (name, before))}


def run(rates: sim.PitcherRates, nine, lg, hook, label: str) -> None:
    res = sim.simulate(rates, nine, lg, n=N, hook=hook, seed=0)
    over = sim.prob_over(res, "k", LINE)
    ks = sorted(r.k for r in res)
    outs = sorted(r.outs for r in res)
    mean_k = sum(ks) / len(ks)
    mean_o = sum(outs) / len(outs)
    print(f"\n  {label}")
    print(f"    k_pct {rates.k_pct:.4f}  bb_pct {rates.bb_pct:.4f}  "
          f"babip {rates.babip:.4f}")
    print(f"    mean K {mean_k:.2f}   mean outs {mean_o:.1f} "
          f"({mean_o / 3:.2f} IP)")
    print(f"    P(over {LINE:g} K) = {over:.3f}")
    print("    K distribution: " + "  ".join(
        f"{v}:{sum(1 for x in ks if x == v) / len(ks):.0%}"
        for v in range(2, 12)))


def main() -> None:
    lg = sim.league()
    pr = rate_src.pitcher_rates(lg, before=DATE)
    p = pr[NAME]

    ok, why = pm.priceable(NAME, p["pa"], DATE)
    print(f"\n{NAME} — priceable: {ok}" + (f" ({why})" if why else ""))

    sp = split_rates(NAME, DATE)
    for s, r in sorted(sp.items(), reverse=True):
        bf = r["bf"] or 1
        print(f"  {'starts ' if s else 'relief '}: {bf:>4} BF  "
              f"K% {r['k'] / bf:.4f}  BB% {r['bb'] / bf:.4f}  "
              f"HR% {r['hr'] / bf:.4f}  outs {r['o']}")

    g = next(g for g in pm.slate(DATE)
             if NAME in (g["away"]["starter"], g["home"]["starter"]))
    side = "away" if g["away"]["starter"] == NAME else "home"
    opp = g["home" if side == "away" else "away"]
    names = opp["lineup"] or pm.projected_lineup(opp["abbr"], DATE)
    br = rate_src.batter_rates(lg, before=DATE)
    league_bats = sim.BatterRates(name="league", k_pct=lg["k_pct"],
                                  bb_pct=lg["bb_pct"], hr_pct=lg["hr_pct"],
                                  babip=lg["babip"])
    nine = pm._build(names, br, league_bats)
    print(f"  vs {opp['abbr']} "
          f"({'confirmed' if opp['lineup'] else 'PROJECTED'} lineup)")
    hook = sim.for_start(sim.Hook(), g[side]["abbr"], NAME)

    run(sim.PitcherRates(name=NAME, k_pct=p["k_pct"], bb_pct=p["bb_pct"],
                         hr_pct=p["hr_pct"], babip=p["babip"], pa=p["pa"]),
        nine, lg, hook, "POOLED rates (what the model would have used)")

    st = sp.get(1)
    if st and st["bf"]:
        bf = st["bf"]
        # Shrunk the same way `rates` does, so the two rows differ only in
        # which appearances were counted.
        raw = {"k_pct": st["k"] / bf, "bb_pct": st["bb"] / bf,
               "hr_pct": st["hr"] / bf,
               "babip": st["h"] / max(bf - st["k"] - st["bb"] - st["hr"], 1)}
        sh = {k: rate_src._shrink(raw[k], bf, lg[k], k, who="pit")
              for k in raw}
        run(sim.PitcherRates(name=NAME, pa=bf, **sh), nine, lg, hook,
            "STARTS-ONLY rates (the role he is actually in)")


if __name__ == "__main__":
    main()
