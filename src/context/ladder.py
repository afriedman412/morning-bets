"""Where is the model wrong? Score it by inning prefix and find out.

THE PROBLEM THIS SOLVES. A first-five error tells you the model is wrong and
nothing about WHICH PART is wrong, because five innings mixes three
mechanisms. Every diagnosis in this project so far has come from inferring
the decomposition — runs per baserunner, conversion ratios, boundary shares
— rather than measuring it.

Each prefix adds exactly one mechanism, so the prefix where the error
appears IS the mechanism that is wrong:

    F1-F3   the plate-appearance model ALONE. The bullpen cannot appear —
            no starter is pulled that early outside a disaster — and the
            hook is nearly silent, since a starter has thrown ~45 pitches by
            the third against a removal centre of 80.
    F4-F5   rates plus the beginnings of the hook. The starter covers all
            five about 76% of the time, so removal enters a quarter of them.
    F6-F7   rates, hook, and real bullpen exposure.

Read it as a cumulative diagnosis. If F3 already errs, the rate model is
wrong and nothing downstream can be trusted. If F3 is right and F7 is not,
the defect is in relief or removal, and the inning where the error opens up
says which.

NOT A BETTING TOOL. Kalshi lists first-five and full-game totals only — no
F3, no F7. This is for modelling.

STOPS AT F7. A home team leading after eight does not bat in the ninth, so
an F9 prefix keeps only the games where it did, which is a different
population. Full games have `away_score`/`home_score`; use those.
"""
from __future__ import annotations

import random
import statistics as st
import sys

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import innings as inn_src
from src.context.sources import rates as rate_src

#: F1/F3/F5/F7. Four and six add runtime without adding a mechanism —
#: nothing new enters the model between the third and the fifth beyond more
#: of the hook, and the same between the fifth and the seventh beyond more
#: bullpen.
PREFIXES = (1, 3, 5, 7)


def simulate_prefixes(cases_by_game, pens, lg, n_sims=40, seed=7,
                      prefixes=PREFIXES) -> dict[str, dict[int, float]]:
    """{game_id: {prefix: mean simulated total}}.

    One pass of the FULL game simulator per draw, reading every prefix off
    the same innings. Simulating each prefix separately would be seven times
    the work for a worse answer — the prefixes would stop being nested, and
    a model can only be diagnosed by prefix if F3 is genuinely the first
    three innings of the same game F7 came from.

    SEEDED PER DRAW, and that is not cosmetic. A single generator shared
    across the loop means a change anywhere downstream shifts the stream for
    everything after it, so comparing two model states contaminates every
    later game and every later draw with the difference from the first one.
    It shows up as a bullpen flag moving F1 — an inning in which no reliever
    can exist — by a large fraction of the effect being measured, and the
    ladder then charges relief error to the rate model, which is exactly the
    inference it exists to support.

    Per-GAME seeding is not enough: the draws within a game share a stream
    too, so draw 1's relief behaviour still perturbs draws 2..n. Only a seed
    per (game, draw) makes F1 bit-identical across states.
    """
    out: dict[str, dict[int, float]] = {}
    for i, (gid, v) in enumerate(cases_by_game.items()):
        home = next((x for x in v if x[0]["is_home"]), None)
        away = next((x for x in v if not x[0]["is_home"]), None)
        if not home or not away:
            continue
        an = cal.adjust_lineup(away[2], False)
        hn = cal.adjust_lineup(home[2], True)
        acc = {p: 0.0 for p in prefixes}
        for draw in range(n_sims):
            rng = random.Random(seed + i * 100003 + draw)
            A = game.build_side(
                away[1], pens.get((away[0]["team"] or "").upper(), []),
                hn, None, rng)
            H = game.build_side(
                home[1], pens.get((home[0]["team"] or "").upper(), []),
                an, None, rng)
            res = game.simulate_game(A, H, lg, rng, innings=max(prefixes),
                                     track=prefixes)
            for p in prefixes:
                acc[p] += res.prefix[p]
        out[gid] = {p: acc[p] / n_sims for p in prefixes}
    return out


def report(before=None, since=None, n_sims=40, limit=None,
           seed=7) -> None:
    lg = sim.league(before=before)
    pens = rate_src.bullpens(lg, before=before)
    by: dict[str, list] = {}
    for s, p, l in cal.build_cases(before=before, since=since,
                                   rates_before=before or since):
        by.setdefault(s["game_id"], []).append((s, p, l))
    by = {g: v for g, v in by.items()
          if len(v) == 2 and sum(bool(x[0]["is_home"]) for x in v) == 1}

    actual = {p: inn_src.prefix_totals(p, before=before, since=since)
              for p in PREFIXES}
    usable = [g for g in by if all(g in actual[p] for p in PREFIXES)]
    if limit:
        usable = usable[:limit]
    if not usable:
        print("no games with both starters and a full inning line")
        return
    by = {g: by[g] for g in usable}
    print(f"{len(by)} games with both starters modelled and a complete "
          f"inning line\n")

    simd = simulate_prefixes(by, pens, lg, n_sims=n_sims, seed=seed)
    print(f"  {'':<6}{'sim':>8}{'actual':>9}{'diff':>9}{'se':>8}"
          f"{'sigma':>8}{'per inning':>12}")
    prev = 0.0
    for p in PREFIXES:
        d = [simd[g][p] - actual[p][g]["total"] for g in simd]
        if not d:
            continue
        m = st.mean(d)
        se = st.pstdev(d) / len(d) ** 0.5
        s_ = st.mean(simd[g][p] for g in simd)
        a_ = st.mean(actual[p][g]["total"] for g in simd)
        # The MARGINAL error added by this inning. A cumulative total drifts,
        # and drift makes every later prefix look wrong once an early one is;
        # the marginal series says which inning actually broke.
        print(f"  F{p:<5}{s_:>8.2f}{a_:>9.2f}{m:>+9.3f}{se:>8.3f}"
              f"{m / se if se else 0:>+8.1f}{m - prev:>+12.3f}")
        prev = m
    print("\n  'per inning' is the MARGINAL error this inning adds. A "
          "cumulative\n  total drifts, so the marginal column is what "
          "localises the defect.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    before = args[0] if args else None
    n = 40
    lim = None
    for a in sys.argv:
        if a.startswith("--sims="):
            n = int(a.split("=")[1])
        if a.startswith("--limit="):
            lim = int(a.split("=")[1])
    report(before=before, n_sims=n, limit=lim)
