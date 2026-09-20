"""OFFENSE PROPS, audited off the same engine — per-batter H/TB/HR/R/RBI.

    venv/bin/python -m scratchpad.batprops DATE AWAY HOME [SIMS]

Simulates ONE matchup through `slate.simulate_slate_game` (the shipped
live path) and prints, for every batter in either nine, the fair odds at
the standard prop lines, read off `GameResult.away_bats`/`home_bats` —
the per-batter tallies `game.py` folds across every arm.

**NOTHING PER-BATTER HAS EVER BEEN SCORED AGAINST OUTCOMES IN THIS REPO.**
This is an AUDIT TOOL, not a price. A batter prop is ~4 plate appearances
of shrunk season rates through log5; the predictable failure is the outs
story again — calibrated in aggregate, no discrimination on the
individual. Score it on the holdout (the pbp cache has every real PA)
before money moves on any row printed here.
"""
from __future__ import annotations

import sys

from src.context import sim, slate
from src.context.sources import rates as rate_src

#: (label, tally key, line). H+R+RBI is the book's combo prop.
PROPS = (("H 0.5", "h", 0.5), ("H 1.5", "h", 1.5),
         ("TB 1.5", "tb", 1.5), ("HR 0.5", "hr", 0.5),
         ("R 0.5", "r", 0.5), ("RBI 0.5", "rbi", 0.5),
         ("HRR 1.5", "hrr", 1.5))  # HRR = hits + runs + RBI, the combo


def american(p: float) -> str:
    if p <= 0 or p >= 1:
        return "-"
    if p > 0.5:
        return f"{-100 * p / (1 - p):+.0f}"
    return f"{100 * (1 - p) / p:+.0f}"


def main(argv):
    if len(argv) < 3:
        raise SystemExit(__doc__)
    d, away, home = argv[0], argv[1].upper(), argv[2].upper()
    n = int(argv[3]) if len(argv) > 3 else 20000
    g = next((x for x in slate.slate(d)
              if {x["away"]["abbr"], x["home"]["abbr"]} == {away, home}),
             None)
    if g is None:
        raise SystemExit(f"no {away}/{home} game on {d}")
    lg = sim.league()
    res, why = slate.simulate_slate_game(
        g, d, lg, rate_src.pitcher_rates(lg, before=d),
        rate_src.batter_rates(lg, before=d),
        sim.BatterRates(name="league", k_pct=lg["k_pct"],
                        bb_pct=lg["bb_pct"], hr_pct=lg["hr_pct"],
                        babip=lg["babip"]),
        rate_src.bullpens(lg, before=d), n_sims=n)
    if not res:
        raise SystemExit(f"declined: {why}")

    print(f"{away} @ {home} — {d} · {n:,} sims · fair odds (no vig)")
    print("UNSCORED per-batter — audit, not a price. See module docstring.")
    for side, key in (("away", "away_bats"), ("home", "home_bats")):
        abbr = g[side]["abbr"]
        posted = bool(g[side].get("lineup"))
        print(f"\n{abbr} ({'posted' if posted else 'PROJECTED'} lineup) — "
              f"vs {g['home' if side == 'away' else 'away']['starter']}")
        head = "".join(f"{lbl + ' ov':>13}" for lbl, _, _ in PROPS)
        print(f"  {'batter':<22}{head}")
        # Union of names across draws: a batter with zero counts in a draw
        # is absent from that draw's dict, and skipping him would price
        # P(over | he did something), which is the wrong denominator.
        names: dict = {}
        for r in res:
            for who in getattr(r, key):
                names[who] = True
        for who in names:
            cells = []
            for _, k, ln in PROPS:
                vals = []
                for r in res:
                    v = getattr(r, key).get(who) or {}
                    x = (v.get("h", 0) + v.get("r", 0) + v.get("rbi", 0)
                         if k == "hrr" else v.get(k, 0))
                    vals.append(x)
                p = sum(1 for v in vals if v > ln) / n
                cells.append(f"{american(p):>13}")
            print(f"  {who[:20]:<22}{''.join(cells)}")


if __name__ == "__main__":
    main(sys.argv[1:])
