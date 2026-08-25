"""Score a change across EVERY marginal the simulation produces, not just runs.

WHY THIS EXISTS. The prefix ladder scores total runs and nothing else, and
runs is both a heavily aggregated view of a simulated game and a low-power
one. Measured on the boundary hook, same change and same games:

    prefix ladder (runs)     |sigma| <= 1.1   -> reads as null
    starter outs CRPS               +4.7      -> a real improvement

Runs per game has a standard deviation near 4 and the mechanisms built here
are worth 0.02-0.05 runs, so the ladder cannot resolve them. Worse, a whole
class of mechanism — the hook, relief length, inherited runners, bullpen
deployment — changes WHICH pitcher throws WHICH inning without changing how
many runs the two of them allow between them, because a starter and a
reliever are near-identical in aggregate on this league (K-BB 0.1358 against
0.1333). The ladder is structurally blind to all of it.

This is the same argument already accepted one level down. `form.py` found
runs predict the next time through the order at r = +0.008 while damage with
runs partialled out reaches +0.081, so the hook was keyed on baserunners
rather than runs. Runs lag. That applies to EVALUATION exactly as it applies
to features, and it had never been carried across.

WHAT THIS IS NOT. It is not a licence to fish. A mechanism declares which
marginals it should plausibly move BEFORE the run — `expect=` — and the
report separates those from the rest. Scanning eleven marginals and keeping
the best sigma is how a null becomes a finding.

TRAINING TARGET AND EVALUATION TARGET ARE DIFFERENT THINGS. "Fit the
quantity that settles, not the upstream proxy" still governs what a loss
function is pointed at. This module governs what a CHANGE is judged on, and
there the answer is plural: the model is trying to be right about the game,
not about the box score's runs column.

    venv/bin/python -m src.context.marginals            # the boundary hook
    venv/bin/python -m src.context.marginals --limit 300 --sims 20
"""
from __future__ import annotations

import random
import statistics as st
import sys
from collections import Counter

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import innings as inn_src
from src.context.sources import rates as rate_src

#: Upper bound for the discrete CRPS sum. Comfortably past the longest
#: outing and the biggest crooked inning; a support that truncates below the
#: observed maximum silently forgives the tail, which is where this model is
#: known to be thin.
SUPPORT = 32

N_SIMS = 40

#: Per-START marginals: (label, key in the actual row, attr on StartResult).
#: These are the prop quantities. Baserunners is included because a high-n
#: ratio has told the truth in this project every time a low-n aggregate
#: did not.
START_MARGINALS = (
    ("starter outs", "o", "outs"),
    ("starter K", "k", "k"),
    ("hits allowed", "h", "h"),
    ("walks allowed", "bb", "bb"),
    ("runs allowed", "r", "runs"),
)

#: Per-GAME marginals read off prefixes. F9 is the full-game total.
PREFIXES = (1, 3, 5, 7)


def _crps(dist: Counter, actual: int) -> float:
    """Discrete CRPS over the FULL SUPPORT.

    Deliberately not scored at a book's lines. Doing that tunes the model to
    the shape of somebody's board; summing the squared CDF gap over every
    value is both the principled choice and the standard metric.
    """
    n = sum(dist.values()) or 1
    tot = c = 0.0
    for v in range(SUPPORT + 1):
        c += dist.get(v, 0) / n
        tot += (c - (1.0 if v >= actual else 0.0)) ** 2
    return tot


def _pit(dist: Counter, actual: int) -> float:
    """Probability integral transform, mid-rank for the discrete ties.

    Uniform across starts means calibrated. Piling up at the ends means the
    distribution is too narrow; piling up in the middle means too wide.
    """
    n = sum(dist.values()) or 1
    below = sum(v for k, v in dist.items() if k < actual) / n
    at = dist.get(actual, 0) / n
    return below + at / 2


def cases(before=None, since=None, limit=None):
    """Games with both starters modelled and a complete inning line."""
    by: dict = {}
    for s, p, l in cal.build_cases(before=before, since=since,
                                   rates_before=before or since):
        by.setdefault(s["game_id"], []).append((s, p, l))
    by = {g: v for g, v in by.items()
          if len(v) == 2 and sum(bool(x[0]["is_home"]) for x in v) == 1}
    actual = {n: inn_src.prefix_totals(n, before=before, since=since)
              for n in PREFIXES}
    ok = [g for g in by if all(g in actual[n] for n in PREFIXES)]
    if limit:
        ok = ok[:limit]
    return {g: by[g] for g in ok}, actual


def run(by, actual, lg, pens, n_sims=N_SIMS, seed=7) -> dict:
    """Simulate every game and collect a distribution per marginal.

    SEEDED PER (GAME, DRAW), which is what makes two states comparable: a
    single shared generator lets a change anywhere shift the stream for
    everything after it, and the comparison then measures the perturbation
    rather than the mechanism.
    """
    starts: list[dict] = []
    games: list[dict] = []
    for i, (gid, v) in enumerate(by.items()):
        home = next(x for x in v if x[0]["is_home"])
        away = next(x for x in v if not x[0]["is_home"])
        an = cal.adjust_lineup(away[2], False)
        hn = cal.adjust_lineup(home[2], True)
        d_away = {m[0]: Counter() for m in START_MARGINALS}
        d_home = {m[0]: Counter() for m in START_MARGINALS}
        d_pre = {n: Counter() for n in PREFIXES}
        d_side = {"away": Counter(), "home": Counter()}
        crooked = big = 0
        for draw in range(n_sims):
            rng = random.Random(seed + i * 100003 + draw)
            A = game.build_side(
                away[1], pens.get((away[0]["team"] or "").upper(), []),
                hn, None, rng)
            H = game.build_side(
                home[1], pens.get((home[0]["team"] or "").upper(), []),
                an, None, rng)
            r = game.simulate_game(A, H, lg, rng, track=PREFIXES)
            for lbl, _k, attr in START_MARGINALS:
                d_away[lbl][getattr(r.away_sp, attr)] += 1
                d_home[lbl][getattr(r.home_sp, attr)] += 1
            for n in PREFIXES:
                if n in r.prefix:
                    d_pre[n][r.prefix[n]] += 1
            d_side["away"][r.away] += 1
            d_side["home"][r.home] += 1
            crooked += (r.away >= 5) + (r.home >= 5)
            big += (r.away == 0) + (r.home == 0)
        for act, d in ((away[0], d_away), (home[0], d_home)):
            for lbl, key, _a in START_MARGINALS:
                if act.get(key) is None:
                    continue
                starts.append({"marginal": lbl, "actual": act[key],
                               "dist": d[lbl]})
        g = {"game_id": gid, "pre": d_pre, "side": d_side,
             "crooked": crooked / (2 * n_sims), "shutout": big / (2 * n_sims),
             "actual_pre": {n: actual[n][gid]["total"] for n in PREFIXES},
             "actual_side": {"away": actual[max(PREFIXES)][gid]["away"],
                             "home": actual[max(PREFIXES)][gid]["home"]}}
        games.append(g)
    return {"starts": starts, "games": games}


def _rows(res) -> dict:
    """{marginal: [(crps, pit, sim_mean, actual)]} for every scored quantity."""
    out: dict = {}
    for s in res["starts"]:
        n = sum(s["dist"].values()) or 1
        out.setdefault(s["marginal"], []).append((
            _crps(s["dist"], s["actual"]), _pit(s["dist"], s["actual"]),
            sum(k * v for k, v in s["dist"].items()) / n, s["actual"]))
    for g in res["games"]:
        for n in PREFIXES:
            a = g["actual_pre"][n]
            d = g["pre"][n]
            tot = sum(d.values()) or 1
            out.setdefault(f"F{n} total runs", []).append((
                _crps(d, a), _pit(d, a),
                sum(k * v for k, v in d.items()) / tot, a))
        for side in ("away", "home"):
            a = g["actual_side"][side]
            d = g["side"][side]
            tot = sum(d.values()) or 1
            out.setdefault("team runs (full game)", []).append((
                _crps(d, a), _pit(d, a),
                sum(k * v for k, v in d.items()) / tot, a))
    return out


def compare(states, before=None, since=None, limit=None, n_sims=N_SIMS,
            seed=7, expect=()) -> dict:
    """Paired A/B across every marginal. `states` is [(label, setup_fn)].

    The first state is the baseline; every later one is reported as a paired
    delta against it. `expect` names the marginals the change was predicted
    to move, and they are printed first and marked — everything else is
    context, not evidence.
    """
    lg = sim.league(before=before)
    pens = rate_src.bullpens(lg, before=before)
    by, actual = cases(before, since, limit)
    print(f"{len(by)} games, {n_sims} draws each, "
          f"{len(states)} states", flush=True)
    got = {}
    for lbl, setup in states:
        setup()
        print(f"  simulating {lbl} ...", flush=True)
        got[lbl] = _rows(run(by, actual, lg, pens, n_sims, seed))
    states[0][1]()                      # leave the baseline configured

    base_lbl = states[0][0]
    base = got[base_lbl]
    order = ([m for m in base if m in expect]
             + [m for m in base if m not in expect])
    for lbl, _ in states[1:]:
        cur = got[lbl]
        print(f"\n  {lbl}  vs  {base_lbl}      "
              f"({len(by)} games, paired)")
        print(f"    {'marginal':<24}{'actual':>8}{'base':>8}{'new':>8}"
              f"{'CRPS base':>11}{'d CRPS':>9}{'sigma':>8}   PIT")
        for m in order:
            b, c = base[m], cur[m]
            if not b or len(b) != len(c):
                continue
            d = [x[0] - y[0] for x, y in zip(b, c)]
            mu = st.mean(d)
            se = st.pstdev(d) / len(d) ** 0.5
            pit = st.mean(y[1] for y in c)
            mark = " *" if m in expect else "  "
            print(f"   {mark}{m:<22}{st.mean(x[3] for x in b):>8.2f}"
                  f"{st.mean(x[2] for x in b):>8.2f}"
                  f"{st.mean(y[2] for y in c):>8.2f}"
                  f"{st.mean(x[0] for x in b):>11.4f}{mu:>+9.4f}"
                  f"{mu / se if se else 0:>+8.1f}   {pit:.3f}")
        gb = [g for g in got[base_lbl]]  # noqa: F841  (kept for symmetry)
    print("\n  d CRPS > 0 means the change IMPROVED that marginal.")
    print("  '*' marks a marginal the change was PREDECLARED to move; the")
    print("  rest are context. PIT near 0.500 is centred — far from it means")
    print("  the distribution sits to one side of what happened.")
    return got


def _flag(mod, name, value):
    def setup():
        setattr(mod, name, value)
    return setup


if __name__ == "__main__":
    lim = None
    n = N_SIMS
    for a in sys.argv[1:]:
        if a.startswith("--limit="):
            lim = int(a.split("=", 1)[1])
        if a.startswith("--sims="):
            n = int(a.split("=", 1)[1])
    if "--limit" in sys.argv:
        lim = int(sys.argv[sys.argv.index("--limit") + 1])
    if "--sims" in sys.argv:
        n = int(sys.argv[sys.argv.index("--sims") + 1])
    compare(
        [("boundary hook OFF", _flag(game, "USE_BOUNDARY_HOOK", False)),
         ("boundary hook ON", _flag(game, "USE_BOUNDARY_HOOK", True))],
        limit=lim, n_sims=n,
        # Predeclared: it changes when a starter hands off, so his own line
        # moves and total runs should not.
        expect=("starter outs", "starter K", "hits allowed",
                "walks allowed"),
    )
