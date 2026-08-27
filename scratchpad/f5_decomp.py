"""WHERE the first-five run gap lives, channel by channel.

    venv/bin/python -m scratchpad.f5_decomp [n_sims] [--season YYYY]

The model is +0.053 runs light through five innings. Level errors ADD, so
the question is which channels are level-wrong and in which direction —
three were found and fixed today (hit-by-pitch, sacrifices, wild pitches),
all low, all for the same reason.

WHAT THIS COMPARES. For every side of every scored game: the events the
simulator produces through five, against the events that ACTUALLY happened
through five, counted off play-by-play. Not the boxscore, which is
full-game and cannot answer an F5 question.

READ IT AS A LADDER. If baserunners match and runs do not, the defect is in
ADVANCEMENT — the model gets men on and does not bring them home. If a hit
type is short, the defect is upstream of that. The two have completely
different fixes and the aggregate cannot tell them apart, which is why
`runs per baserunner` was the diagnostic that finally cracked the
advancement tables.
"""
from __future__ import annotations

import random
import statistics as st
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

from src import db
from src.context import fitf5, game, sim
from src.context.sources import pbp, rates as rate_src

#: `StartResult` carries total hits, not the 1B/2B/3B split — the split
#: lives only in the league `hit_mix`. So hits are compared in aggregate and
#: home runs separately, which is enough to place the defect.
CH = ("k", "bb", "hbp", "h", "hr", "on", "runs")

#: Linear-weights run value of one extra event, over an out. Used only to
#: rank which channel's gap MATTERS, never to fit anything.
#: `h` here is NON-home-run hits, valued at the mix's blend of singles,
#: doubles and triples.
RUN_VALUE = {"bb": 0.33, "hbp": 0.34, "h": 0.55, "hr": 1.40, "k": -0.02}


def actual_f5(short: str):
    """{(side): counts} for innings 1-5, side = the PITCHING side."""
    try:
        d = pbp.fetch(short)
    except Exception:
        return None
    if not d:
        return None
    out = defaultdict(lambda: defaultdict(int))
    first = {}
    for play, _bases, _outs, _a, _h in pbp.plays(short, d):
        ab = play.get("about") or {}
        # Top of the inning: the AWAY side is pitching.
        side = "away" if ab.get("isTopInning") else "home"
        pid = ((play.get("matchup") or {}).get("pitcher") or {}).get("id")
        if pid:
            first.setdefault(side, pid)
        if (ab.get("inning") or 99) > 5:
            continue
        # STARTER ONLY, on both halves of the comparison. `Side.line` is the
        # STARTER'S line and reliever lines are discarded on each arm change,
        # so counting every first-five plate appearance here compared a
        # starter-only simulation against a whole-side actual. That reads as
        # a UNIFORM 6.5-10.2% shortfall in every channel at once — which is
        # the signature of a denominator error, not of a rate being wrong.
        if pid != first.get(side):
            continue
        res = play.get("result") or {}
        ev = res.get("eventType") or ""
        c = out[side]
        if ev in ("strikeout", "strikeout_double_play"):
            c["k"] += 1
        elif ev in ("walk", "intent_walk"):
            c["bb"] += 1
        elif ev == "hit_by_pitch":
            c["hbp"] += 1
        elif ev in ("single", "double", "triple"):
            c["h"] += 1
        elif ev == "home_run":
            c["hr"] += 1
        c["runs"] += len([r for r in (play.get("runners") or [])
                          if (r.get("movement") or {}).get("end") == "score"])
    for side in out:
        o = out[side]
        o["on"] = o["bb"] + o["hbp"] + o["h"] + o["hr"]
    return {k: dict(v) for k, v in out.items()}


def main(argv):
    season = "2026"
    if "--season" in argv:
        i = argv.index("--season")
        season = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    n_sims = int(argv[0]) if argv else 40

    lg = sim.league()
    cases = fitf5.side_cases()
    by_game = defaultdict(dict)
    for c in cases:
        by_game[c["game_id"]][("home" if c["is_home"] else "away")] = c
    gids = [g for g, v in by_game.items() if len(v) == 2]
    print(f"  {len(gids):,} games with both sides modelled, {n_sims} sims\n",
          flush=True)

    shorts = [g.split("-")[-1] for g in gids]
    act = {}
    with ProcessPoolExecutor(max_workers=8) as ex:
        for g, got in zip(gids, ex.map(actual_f5, shorts, chunksize=32)):
            if got and "away" in got and "home" in got:
                act[g] = got
    print(f"  {len(act):,} with play-by-play\n", flush=True)

    pens = rate_src.bullpens(lg)
    #: The DISTRIBUTION of runs allowed, not just the mean. Advancement can
    #: be short two completely different ways and the mean cannot tell them
    #: apart: the per-event rates can be slightly low, or the model can be
    #: missing CLUSTERING — real innings arrive in bunches because a pitcher
    #: who is off gives up hits together, and independent plate appearances
    #: do not. Clustering is CONVEX in runs, so missing it lowers the mean
    #: AND thins the tail. If the model is short at every run total the
    #: rates are wrong; if it is short only high and long low, it is shape.
    sim_hist = defaultdict(float)
    act_hist = defaultdict(int)
    sim_tot = defaultdict(float)
    act_tot = defaultdict(float)
    n = 0
    for g in sorted(act):
        away, home = by_game[g]["away"], by_game[g]["home"]
        rng = random.Random(away["seed"])
        for _ in range(n_sims):
            A = game.build_side(away["pitcher"],
                                pens.get((away["team"] or "").upper(), []),
                                away["lineup"], None, rng)
            H = game.build_side(home["pitcher"],
                                pens.get((home["team"] or "").upper(), []),
                                home["lineup"], None, rng)
            game.simulate_game(A, H, lg, rng, stop_after=5)
            for sd in (A, H):
                ln = sd.line
                sim_tot["k"] += ln.k
                sim_tot["bb"] += ln.bb
                sim_tot["hbp"] += ln.hbp
                sim_tot["hr"] += ln.hr
                # `h` on the line INCLUDES home runs; the actual count above
                # does not, so subtract or the two are different quantities.
                sim_tot["h"] += ln.h - ln.hr
                # THE STARTER'S runs, not the side's. `runs_f5` includes what
                # relievers gave up in the first five, and the actual count
                # this is compared against is starter-only — mixing them
                # showed the model 10.5% HIGH on runs when every event
                # channel matched to within 1.4%, which is impossible and was
                # the third denominator slip in this one script.
                sim_tot["runs"] += ln.runs
                sim_hist[min(ln.runs, 6)] += 1
        for tag in ("away", "home"):
            a = act[g][tag]
            for c in CH:
                act_tot[c] += a.get(c, 0)
            act_hist[min(a.get("runs", 0), 6)] += 1
        n += 2
    for c in ("bb", "hbp", "h", "hr"):
        sim_tot["on"] += sim_tot[c]
    denom = n * n_sims

    print(f"  {'channel':<9}{'sim/side':>10}{'actual':>10}{'gap':>9}"
          f"{'gap %':>9}{'runs':>9}")
    runs_from = 0.0
    for c in CH:
        s = sim_tot[c] / denom
        a = act_tot[c] / n
        gap = a - s
        rv = RUN_VALUE.get(c)
        contrib = gap * rv if rv else 0.0
        if c in ("on", "runs"):
            print(f"  {'-' * 54}")
        print(f"  {c:<9}{s:>10.4f}{a:>10.4f}{gap:>+9.4f}"
              f"{100 * gap / a if a else 0:>+8.1f}%"
              f"{contrib if rv else 0:>+9.4f}")
        if rv:
            runs_from += contrib
    print(f"\n  run gap EXPLAINED by the event channels: {runs_from:+.4f}")
    print(f"  run gap OBSERVED:                        "
          f"{(act_tot['runs'] / n) - (sim_tot['runs'] / denom):+.4f}")
    print(f"\n  RUNS ALLOWED BY THE STARTER THROUGH FIVE — the SHAPE:")
    print(f"  {'runs':>6}{'sim %':>10}{'actual %':>10}{'diff':>9}")
    sd = sum(sim_hist.values()) or 1
    ad = sum(act_hist.values()) or 1
    for k_ in range(7):
        a_ = 100 * act_hist.get(k_, 0) / ad
        s_ = 100 * sim_hist.get(k_, 0) / sd
        lbl = f"{k_}" if k_ < 6 else "6+"
        print(f"  {lbl:>6}{s_:>10.2f}{a_:>10.2f}{a_ - s_:>+9.2f}")

    print("\n  If the observed gap is bigger than the explained one, the")
    print("  model gets the right men on and fails to bring them home —")
    print("  that is an ADVANCEMENT defect. If they match, the defect is")
    print("  upstream in whichever channel carries the biggest run number.")


if __name__ == "__main__":
    main(sys.argv[1:])
