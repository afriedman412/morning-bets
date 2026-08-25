"""Simulate one of TONIGHT's games end to end, the way the project intends.

Every other entrypoint either prices a single prop (`quote`) or replays
history (`calibrate`, `ladder`). This runs the full-game engine on a
SCHEDULED matchup: both starters, both real bullpens sampled per draw,
inherited runners played out, and the bottom of the ninth skipped when the
home team is ahead. Everything else — the team total, the F5, the starter's
strikeout line — is then READ OFF the same simulated games rather than
priced separately, which is the whole premise in `AF_PLAN.md`.

    venv/bin/python -m scratchpad.tonight "TB@DET" [n_sims]

`--force` prices a starter `price.priceable` would decline. Use it knowing
what the gate was for: pooled rates from a bulk reliever do not describe a
start.
"""
from __future__ import annotations

import random
import statistics as st
import sys
from collections import Counter
from datetime import date

from src.context import calibrate as cal
from src.context import game
from src.context import price as pm
from src.context import sim
from src.context.sources import rates as rate_src

N_SIMS = 4000


def find_game(matchup: str, d: str) -> dict:
    a, _, h = matchup.upper().partition("@")
    for g in pm.slate(d):
        if g["away"]["abbr"] == a.strip() and g["home"]["abbr"] == h.strip():
            return g
    raise SystemExit(f"no {matchup} on {d}; "
                     + ", ".join(f"{g['away']['abbr']}@{g['home']['abbr']}"
                                 for g in pm.slate(d)))


def nine(abbr: str, listed, d: str, br: dict, lg: dict) -> list:
    names = listed or pm.projected_lineup(abbr, d)
    league_bats = sim.BatterRates(name="league", k_pct=lg["k_pct"],
                                  bb_pct=lg["bb_pct"], hr_pct=lg["hr_pct"],
                                  babip=lg["babip"])
    return pm._build(names, br, league_bats), bool(listed)


_SPLIT_Q = """select sum(p.outs_recorded) o, sum(p.h) h, sum(p.bb) bb,
                     sum(p.k) k, sum(p.hr) hr, count(*) apps
              from mlb_pitching p join games g on g.game_id = p.game_id
              where p.player_name = ? and g.status = 'Final'
                and g.date < ? and p.is_starter = 1"""


def starts_only(name: str, d: str, lg: dict) -> dict | None:
    """His rates counted over STARTS ALONE, shrunk identically.

    The swingman gate assumes pooled rates flatter a bulk reliever's start.
    For a converted starter it can run the other way, and it does here:
    Seymour's raw K% is 0.370 as a starter against 0.259 in relief, so
    pooling all 37 appearances DILUTES the role he is in tonight. Worth
    seeing both rather than assuming which direction the bias points.
    """
    from src import db
    with db.connect() as c:
        r = dict(c.execute(_SPLIT_Q, (name, d)).fetchone())
    bf = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
    if bf < 1:
        return None
    bip = bf - (r["k"] or 0) - (r["bb"] or 0) - (r["hr"] or 0)
    sk = rate_src._shrink
    return {"pa": bf,
            "k_pct": sk(r["k"] / bf, lg["k_pct"], bf, "k_pct", who="pit"),
            "bb_pct": sk(r["bb"] / bf, lg["bb_pct"], bf, "bb_pct", who="pit"),
            "hr_pct": sk(r["hr"] / bf, lg["hr_pct"], bf, "hr_pct", who="pit"),
            "babip": sk((r["h"] - r["hr"]) / bip if bip > 0 else None,
                        lg["babip"], max(bip, 0), "babip", who="pit")}


def starter(name: str, pr: dict, d: str, force: bool,
            lg: dict | None = None, sp_only: bool = False) -> tuple:
    p = pr.get(name)
    if not p:
        raise SystemExit(f"no rates on record for {name}")
    if sp_only and lg is not None:
        s = starts_only(name, d, lg)
        if s:
            p = {**p, **s}
    ok, why = pm.priceable(name, p["pa"], d)
    if not ok and not force:
        raise SystemExit(f"{name}: model declines — {why}  (--force to "
                         f"override)")
    return sim.PitcherRates(name=name, k_pct=p["k_pct"], bb_pct=p["bb_pct"],
                            hr_pct=p["hr_pct"], babip=p["babip"],
                            pa=p["pa"]), (why if not ok else "")


def dist(vals, lo, hi) -> str:
    n = len(vals)
    c = Counter(vals)
    return "  ".join(f"{v}:{c[v] / n:.0%}" for v in range(lo, hi + 1))


def pct(vals, p) -> float:
    s = sorted(vals)
    return s[min(len(s) - 1, int(p * len(s)))]


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    force = "--force" in sys.argv
    matchup = args[0] if args else "TB@DET"
    n_sims = int(args[1]) if len(args) > 1 else N_SIMS
    d = date.today().isoformat()

    lg = sim.league()
    pr = rate_src.pitcher_rates(lg, before=d)
    br = rate_src.batter_rates(lg, before=d)
    pens = rate_src.bullpens(lg, before=d)

    g = find_game(matchup, d)
    if g["status"] not in ("Scheduled", "Pre-Game", "Warmup", "Preview",
                           "Delayed Start"):
        raise SystemExit(f"game is {g['status']} — never price a live one")

    a_abbr, h_abbr = g["away"]["abbr"], g["home"]["abbr"]
    sp_only = "--sp-only" in sys.argv
    a_sp, a_why = starter(g["away"]["starter"], pr, d, force, lg, sp_only)
    h_sp, h_why = starter(g["home"]["starter"], pr, d, force, lg, sp_only)
    a_nine, a_conf = nine(a_abbr, g["away"]["lineup"], d, br, lg)
    h_nine, h_conf = nine(h_abbr, g["home"]["lineup"], d, br, lg)

    print(f"\n{a_abbr} @ {h_abbr} — {d}, {n_sims:,} simulated games"
          + ("   [STARTS-ONLY rates]" if sp_only else ""))
    for lbl, sp, why, opp, conf in (
            (a_abbr, a_sp, a_why, h_abbr, h_conf),
            (h_abbr, h_sp, h_why, a_abbr, a_conf)):
        print(f"  {lbl} {sp.name:<20} k% {sp.k_pct:.3f} bb% {sp.bb_pct:.3f} "
              f"hr% {sp.hr_pct:.3f} babip {sp.babip:.3f} ({sp.pa} BF)"
              + (f"  [FORCED: {why}]" if why else ""))
        print(f"       vs {opp} "
              f"{'confirmed' if conf else 'PROJECTED'} lineup, pen "
              f"{len(pens.get(opp, []))} arms")

    # Home/road lineup shift applies to the nine a pitcher FACES, so the
    # away pitcher faces the home lineup adjusted as the home lineup.
    a_faces = cal.adjust_lineup(h_nine, True)
    h_faces = cal.adjust_lineup(a_nine, False)

    away_r, home_r, tot, f5, a_k, h_k, a_o, h_o = ([] for _ in range(8))
    for i in range(n_sims):
        rng = random.Random(20260825 + i)
        A = game.build_side(a_sp, pens.get(a_abbr, []), a_faces, None, rng)
        H = game.build_side(h_sp, pens.get(h_abbr, []), h_faces, None, rng)
        r = game.simulate_game(A, H, lg, rng)
        away_r.append(r.away)
        home_r.append(r.home)
        tot.append(r.total)
        f5.append(r.total_f5)
        a_k.append(r.away_sp.k)
        h_k.append(r.home_sp.k)
        a_o.append(r.away_sp.outs)
        h_o.append(r.home_sp.outs)

    wins = sum(1 for x, y in zip(away_r, home_r) if x > y)
    ties = sum(1 for x, y in zip(away_r, home_r) if x == y)
    print(f"\n  SCORE   {a_abbr} {st.mean(away_r):.2f} — "
          f"{st.mean(home_r):.2f} {h_abbr}")
    print(f"  WIN     {a_abbr} {wins / n_sims:.1%}   "
          f"{h_abbr} {(n_sims - wins - ties) / n_sims:.1%}"
          + (f"   (tied {ties / n_sims:.1%})" if ties else ""))
    print(f"  TOTAL   mean {st.mean(tot):.2f}   median {pct(tot, .5):.0f}   "
          f"sd {st.pstdev(tot):.2f}   10-90 {pct(tot, .1):.0f}-"
          f"{pct(tot, .9):.0f}")
    print(f"  F5      mean {st.mean(f5):.2f}   "
          + "  ".join(f"o{x:g}:{sum(1 for v in f5 if v > x) / n_sims:.0%}"
                      for x in (3.5, 4.5, 5.5)))
    print("\n  TOTAL over/under")
    for line in (6.5, 7.5, 8.5, 9.5, 10.5):
        o = sum(1 for x in tot if x > line) / n_sims
        print(f"    {line:>5g}   over {o:.3f}   under {1 - o:.3f}")

    print("\n  TEAM TOTALS")
    for lbl, runs in ((a_abbr, away_r), (h_abbr, home_r)):
        print(f"    {lbl:<4} mean {st.mean(runs):.2f}   "
              + "  ".join(f"o{x:g}:{sum(1 for v in runs if v > x) / n_sims:.0%}"
                          for x in (2.5, 3.5, 4.5, 5.5)))

    print("\n  STARTERS, read off the same games")
    for lbl, sp, ks, os_ in ((a_abbr, a_sp, a_k, a_o),
                             (h_abbr, h_sp, h_k, h_o)):
        print(f"    {sp.name} ({lbl})  mean K {st.mean(ks):.2f}   "
              f"mean outs {st.mean(os_):.1f} ({st.mean(os_) / 3:.2f} IP)")
        print("      K   " + dist(ks, 2, 11))
        for line in (4.5, 5.5, 6.5, 7.5):
            o = sum(1 for x in ks if x > line) / n_sims
            print(f"        over {line:g} K  {o:.3f}   under {1 - o:.3f}")


if __name__ == "__main__":
    main()
