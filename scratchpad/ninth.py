"""WHAT IS THE `9+` GAP MADE OF — half-inning COMPOSITION or a run RATE?

    venv/bin/python -m scratchpad.ninth [n_sims] [--cut YYYY-MM-DD]

QUESTION. `where_runs --profile` reports innings 9+ under-scored by 17.4%
(model 0.793, actual 0.960, z -2.9), the largest relative gap on the board,
and TODO item 11b hands it to item 8 — the bullpen, which has no closer, no
leverage and no fatigue. Before building a bullpen, establish that a bullpen
CAN move this number.

WHY THE HANDOFF IS NOT SAFE ON ITS FACE. `9+` is a RESIDUAL over three
populations that are selected in completely different ways:

    top of the 9th     ALWAYS played
    bottom of the 9th  played only when the home team is NOT ahead
    extras             played only when the game is TIED after nine

The last two are conditioned on the SCORE, which is the model's own output.
A model that under-scores by 7.1% everywhere reaches those halves at
different rates than reality does, so `9+` can be short for two reasons that
have nothing to do with each other:

    COMPOSITION   the model plays fewer of these halves
    RATE          the model scores less in the halves it does play

ONLY THE RATE TERM IS AVAILABLE TO A BULLPEN FIX. A composition shortfall is
downstream of the run level in innings 1-8 and putting a closer in the ninth
cannot touch it — it would move the rate term the WRONG way while the gap
stayed open.

So this decomposes the residual into

    E[runs in 9+] = P(top9) E[runs | top9]
                  + P(bot9) E[runs | bot9]
                  + E[extra runs]

model against actual on the SAME games, and reports each factor separately.

POWER, STATED FIRST. `where_runs` gives se ~0.050 a side per inning on 926
games and the `9+` gap it is decomposing is 0.167 runs. The sub-buckets here
are SMALLER quantities measured on the same games, so their standard errors
do not shrink — the conditional-rate terms are the noisiest because they
drop to the subset of games where the half was played (~60% for the bottom
of the ninth, ~8% for extras). The PROBABILITY terms are the sharp ones: a
share over 926 games has se ~0.016, so a composition gap of 3 points is
readable and one of 1 point is not. Read the shares first.

The model side is an average over `n_sims` draws and contributes little
noise; the binding term is reality's single realisation, as always here.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import random
import statistics as st
import sys
import zlib

from src.context import calibrate as cal, sim
from src.context.sources import pbp, rates as rate_src

CUT = "2026-05-15"
_CASES: dict = {}
_LG: dict = {}
_PENS: dict = {}

#: Track every inning a game can reach. `simulate_game` defaults to
#: `max_extra=9`, so 18 is the ceiling and asking for more is free.
TRACK = tuple(range(1, 19))


def _model_one(pair, rng) -> dict:
    """One simulated game, decomposed at the ninth.

    Everything here is read off `prefix_side`, which is
    {inning: (away TEAM score, home TEAM score)} through that inning, and
    `_track` fires on EVERY exit path as of 2026-08-29 — including the break
    that ends a game when the home side wins in its half. That fix is what
    makes this readable at all; before it, `prefix[9]` was missing for ~40%
    of games and precisely the walk-off halves were the ones dropped.
    """
    r = cal.replay(pair, _LG, _PENS, rng, track=TRACK)
    ps = r.prefix_side
    a8, h8 = ps.get(8, (0, 0))
    a9, h9 = ps.get(9, (a8, h8))
    # The away team does not bat in the bottom half and the home team does
    # not bat in the top, so the two halves separate exactly.
    top9 = a9 - a8
    bot9 = h9 - h8
    # THE BOTTOM HALF IS SKIPPED WHEN THE HOME TEAM LEADS AFTER THE TOP.
    # Its score going into the half is its inning-8 score; the away team's
    # score after the top is `a9`, since it does not bat again.
    bot9_played = not (h8 > a9)
    extras = ps.get(9) is not None and a9 == h9
    n_extra = sum(1 for i in TRACK if i > 9 and i in ps)
    extra_runs = (r.away + r.home) - (a9 + h9)
    return {"top9": top9, "bot9": bot9, "bot9_played": float(bot9_played),
            "extras": float(extras), "n_extra": n_extra,
            "extra_runs": extra_runs, "nine_plus": top9 + bot9 + extra_runs,
            "away_total": r.away, "home_total": r.home}


def _actual_one(gid: str) -> dict:
    """The same decomposition, counted off the play-by-play.

    Runs on a play are the score CHANGE across it — the only reading that
    survives an rbi being withheld on a double play or an error, and the
    same convention `where_runs` uses so the two are comparable.
    """
    top9 = bot9 = extra_runs = 0
    away_total = home_total = 0
    halves = set()
    for play, _b, _o, aw, ho in pbp.plays(gid):
        ab = play.get("about") or {}
        inn, half = ab.get("inning"), ab.get("halfInning")
        if inn:
            halves.add((inn, half))
        res = play.get("result") or {}
        if res.get("awayScore") is None or not inn:
            continue
        away_total, home_total = res["awayScore"], res["homeScore"]
        got = res["awayScore"] + res["homeScore"] - (aw + ho)
        if got <= 0:
            continue
        if inn > 9:
            extra_runs += got
        elif inn == 9:
            if half == "top":
                top9 += got
            else:
                bot9 += got
    n_extra = len({i for i, _h in halves if i > 9})
    return {"top9": top9, "bot9": bot9,
            "bot9_played": float((9, "bottom") in halves),
            "extras": float(n_extra > 0), "n_extra": n_extra,
            "extra_runs": extra_runs, "nine_plus": top9 + bot9 + extra_runs,
            "away_total": away_total, "home_total": home_total}


def _one(args):
    gid, n_sims = args
    # Seed varies BY GAME, matching `where_runs` — a shared seed correlates
    # the per-draw errors across games and inflates the se of a level.
    rng = random.Random((zlib.crc32(gid.encode()) & 0xFFFF) * 1009)
    keys = ("top9", "bot9", "bot9_played", "extras", "n_extra",
            "extra_runs", "nine_plus", "away_total", "home_total")
    m = {k: 0.0 for k in keys}
    for _ in range(n_sims):
        got = _model_one(_CASES[gid], rng)
        for k in keys:
            m[k] += got[k]
    return {k: v / n_sims for k, v in m.items()}, _actual_one(gid)


def paired(diffs):
    m = st.mean(diffs)
    se = st.pstdev(diffs) / len(diffs) ** 0.5
    return m, se, (m / se if se else 0.0)


def _row(lbl, got, key, pct=False):
    mm = st.mean(m[key] for m, _a in got)
    aa = st.mean(a[key] for _m, a in got)
    mean, se, z = paired([m[key] - a[key] for m, a in got])
    rel = mean / aa if aa else 0.0
    fmt = "{:>9.3f}"
    print(f"  {lbl:<22}{fmt.format(mm)}{fmt.format(aa)}{mean:>+9.3f}"
          f"{se:>8.3f}{z:>+7.1f}{rel:>+9.1%}")


def _cond_row(lbl, got, key, gate):
    """Runs per half AMONG THE GAMES WHERE THAT HALF WAS PLAYED.

    The gate differs between model and actual by construction — that IS the
    composition term — so this is NOT a paired difference and gets no z.
    Reported as two independent means with their own standard errors.
    """
    mv = [m[key] / m[gate] for m, _a in got if m[gate] > 0]
    av = [a[key] for _m, a in got if a[gate] > 0]
    if not mv or not av:
        return
    mm, aa = st.mean(mv), st.mean(av)
    se = (st.pstdev(mv) ** 2 / len(mv) + st.pstdev(av) ** 2 / len(av)) ** 0.5
    print(f"  {lbl:<22}{mm:>9.3f}{aa:>9.3f}{mm - aa:>+9.3f}{se:>8.3f}"
          f"{(mm - aa) / se:>+7.1f}{(mm - aa) / aa:>+9.1%}"
          f"   n={len(mv):.0f}/{len(av)}")


def main(argv):
    global _CASES, _LG, _PENS, CUT
    if "--cut" in argv:
        i = argv.index("--cut")
        CUT = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    n_sims = int(argv[0]) if argv and argv[0].isdigit() else 20
    _LG = sim.league()
    _PENS = rate_src.bullpens(_LG, before=CUT)
    _CASES = cal.paired_cases(season=2026, since=CUT, rates_before=CUT)
    print(f"  HOLDOUT: rates before {CUT}, {len(_CASES)} games x {n_sims}"
          f" sims\n", flush=True)
    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, (os.cpu_count() or 4) - 2)) as pool:
        got = pool.map(_one, [(g, n_sims) for g in _CASES], chunksize=8)

    print(f"  FULL-GAME TEAM TOTALS — the stated product, {len(got)} games\n")
    print(f"  {'quantity':<22}{'model':>9}{'actual':>9}{'gap':>9}"
          f"{'se':>8}{'z':>7}{'rel':>9}")
    _row("away club, whole game", got, "away_total")
    _row("home club, whole game", got, "home_total")
    print("\n  THE TWO CLUBS ARE THE READING THAT MATTERS. A combined total")
    print("  hides a bias that is equal and opposite across the two, which")
    print("  is exactly what the reversed half-innings produced.\n")
    print(f"  THE `9+` RESIDUAL, DECOMPOSED — {len(got)} games\n")
    print(f"  {'quantity':<22}{'model':>9}{'actual':>9}{'gap':>9}"
          f"{'se':>8}{'z':>7}{'rel':>9}")
    _row("9+ total", got, "nine_plus")
    print()
    print("  COMPOSITION — how often each half is reached")
    _row("P(bottom 9 played)", got, "bot9_played")
    _row("P(extras)", got, "extras")
    _row("extra innings/game", got, "n_extra")
    print()
    print("  RUNS, unconditional (these sum to the 9+ total)")
    _row("top of 9", got, "top9")
    _row("bottom of 9", got, "bot9")
    _row("extras", got, "extra_runs")
    print()
    print("  RATE — runs per half AMONG GAMES THAT PLAYED IT (unpaired)")
    _cond_row("bottom 9 | played", got, "bot9", "bot9_played")
    _cond_row("extra runs | extras", got, "extra_runs", "extras")
    print()
    print("  THE TOP OF THE NINTH IS THE CLEAN TEST. It is played in every")
    print("  game by both, so its gap is a pure RATE gap with no composition")
    print("  term at all — that is the number a bullpen change is allowed to")
    print("  claim. A shortfall concentrated in the other two rows is")
    print("  downstream of the run level in innings 1-8 and no amount of")
    print("  closer-ordering can reach it.")


if __name__ == "__main__":
    main(sys.argv[1:])
