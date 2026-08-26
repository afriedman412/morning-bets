"""Pitch efficiency: is per-pitcher TEMPO a missing mechanism?

    venv/bin/python -m scratchpad.tempo

THE CLAIM BEING SCREENED, from a hand analysis of the same slates: "pitch
efficiency (pitches per out) is the single most predictive input for outs
props" — Gray 4.74, Boyd 4.87, deGrom 5.9, Roupp 5.72, Dobnak 6.1. The
simulator charges `sim.PITCH_COST` per OUTCOME, identically for every
pitcher, so on its face it does not model this at all.

THE CONFOUND, AND IT IS THE WHOLE ANSWER. Pitches per out is
(pitches per PA) / (outs per PA). The denominator is TRAFFIC — a pitcher who
puts men on records fewer outs per batter — and the simulator already
generates traffic from his own K%, BB% and BABIP. Charging a per-pitcher
pitches-per-out multiplier on top would count the same thing twice.

So the quantity to screen is the RESIDUAL: actual pitches against what his
own outcome mix predicts under the league table. That is tempo proper —
deep counts and foul balls — with traffic removed.

    raw pitches per out          split-half r  +0.348
    outcome-mix residual         split-half r  +0.207

The residual persists WORSE than the raw ratio, which is what it looks like
when most of a signal is the part you already model. Its spread is +/-3% on
pitch cost, shrinking to about +/-1.8%, or ~0.3 outs — against a per-pitcher
leash already worth 0.90. Below the bar, and overlapping.

WHAT THE SCREEN FOUND INSTEAD, which is a level error and not a per-pitcher
one: our starts record an out every 5.14 pitches where real ones take 5.47.
Six percent light, on a ratio that needs no batters-faced denominator and so
survives any accounting quibble. At a 92-pitch hook that is 17.9 outs
against 16.8 — and the direction matches the marginal defect measured the
same day, too many 21+ out starts (16.4% against a real 11.4%) and too few
at 15-17 (28.6% against 34.2%).

Strikeouts are not the cause: K per batter faced is 0.2141 simulated against
0.2149 real.
"""
from __future__ import annotations

import random
import statistics as st
from src import db
from src.context import calibrate as cal
from src.context import leash, sim
from src.context.sources import rates as rate_src

_Q = """
select p.player_name nm, p.pitches pit, p.outs_recorded o,
       p.k, p.bb, p.hr, p.h, p.hbp
from mlb_pitching p join games g on g.game_id = p.game_id
where g.sport = 'mlb' and g.status = 'Final' and p.is_starter = 1
  and p.pitches is not null and p.pitches > 0 and p.outs_recorded > 0
"""


def expected_pitches(r) -> float:
    """What the LEAGUE table says this start's outcome mix should have cost."""
    k, bb, hr = r["k"] or 0, r["bb"] or 0, r["hr"] or 0
    h, o, hbp = r["h"] or 0, r["o"] or 0, r["hbp"] or 0
    return (k * sim.PITCH_COST[sim.K] + bb * sim.PITCH_COST[sim.BB]
            + hr * sim.PITCH_COST[sim.HR]
            + max(h - hr, 0) * sim.PITCH_COST[sim.B1]
            + max(o - k, 0) * sim.PITCH_COST[sim.OUT]
            + hbp * sim.PITCH_COST[sim.HBP])


def real(keep) -> dict:
    by: dict = {}
    tot = {"o": 0, "p": 0, "bf": 0, "k": 0}
    with db.connect() as c:
        for r in c.execute(_Q):
            if r["nm"] not in keep:
                continue
            e = expected_pitches(r)
            if e <= 20:
                continue
            by.setdefault(r["nm"], []).append((r["pit"], e, r["o"]))
            tot["o"] += r["o"] or 0
            tot["p"] += r["pit"] or 0
            tot["k"] += r["k"] or 0
            # APPROXIMATE. Omits reached-on-error, so BF runs a little low
            # and both per-BF figures a little high. The pitches-per-out
            # ratio below needs no BF at all and is the number to quote.
            tot["bf"] += ((r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
                          + (r["hbp"] or 0))
    return {k: v for k, v in by.items() if len(v) >= 10}, tot


def simulated(keep, stride=3, draws=12):
    lg = sim.league()
    pens = rate_src.bullpens(lg)
    rng = random.Random(0)
    acc: dict = {}
    tot = {"o": 0, "p": 0, "bf": 0, "k": 0}
    for pair in list(cal.paired_cases().values())[::stride]:
        for _ in range(draws):
            r = cal.replay(pair, lg, pens, rng)
            for case, line in zip(pair, (r.away_sp, r.home_sp)):
                nm = case[0]["player_name"]
                if nm not in keep or line.outs <= 0:
                    continue
                p, o = acc.setdefault(nm, [0, 0])
                acc[nm] = [p + line.pitches, o + line.outs]
                tot["o"] += line.outs
                tot["p"] += line.pitches
                tot["bf"] += line.batters
                tot["k"] += line.k
    return acc, tot


def main():
    keep = leash.intended_starters()
    by, rtot = real(keep)

    def halves(v, i):
        s = v[i::2]
        return (sum(p for p, _e, _o in s) / sum(e for _p, e, _o in s),
                sum(p for p, _e, _o in s) / sum(o for _p, _e, o in s))

    ra, rb, pa, pb = [], [], [], []
    for v in by.values():
        if len(v) >= 8:
            r1, o1 = halves(v, 0)
            r2, o2 = halves(v, 1)
            ra.append(r1), rb.append(r2), pa.append(o1), pb.append(o2)
    resid = {k: sum(p for p, _e, _o in v) / sum(e for _p, e, _o in v)
             for k, v in by.items()}
    vals = sorted(resid.values())
    print(f"  {len(by)} starters, 10+ starts\n")
    print(f"  DOES PER-PITCHER TEMPO PERSIST?")
    print(f"    outcome-mix residual   sd {st.pstdev(vals):.4f}   "
          f"split-half r {st.correlation(ra, rb):+.3f}   <- the gate")
    print(f"    raw pitches per out                   "
          f"split-half r {st.correlation(pa, pb):+.3f}")
    print(f"    the residual persists WORSE, so most of the raw signal is")
    print(f"    traffic — which the simulator already generates itself.\n")

    acc, stot = simulated(keep)
    sv = sorted(p / o for p, o in acc.values() if o > 200)
    rv = sorted(sum(p for p, _e, _o in v) / sum(o for _p, _e, o in v)
                for v in by.values())
    print(f"  LEVEL AND SPREAD, pitches per out (no BF denominator)")
    print(f"    real       mean {rtot['p']/rtot['o']:.2f}   sd {st.pstdev(rv):.3f}")
    print(f"    simulated  mean {stot['p']/stot['o']:.2f}   sd {st.pstdev(sv):.3f}")
    print(f"    level {(stot['p']/stot['o'])/(rtot['p']/rtot['o'])-1:+.1%}   "
          f"spread produced {st.pstdev(sv)/st.pstdev(rv):.0%}")
    print(f"\n    K per batter faced   real {rtot['k']/rtot['bf']:.4f}   "
          f"sim {stot['k']/stot['bf']:.4f}   (not the cause)")


if __name__ == "__main__":
    main()
