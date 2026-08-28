"""Does the SHIPPED engine reproduce the starter's outs and K distribution?

    venv/bin/python -m scratchpad.shape [n_sims] [max_games] [--no-leash]

WHY THIS AND NOT `score_boundary.py`. That script compares candidate HOOK
CURVES against each other and reports outs only. This asks a different
question with no variants in it: taking the engine exactly as it ships
today, after the day-12/13/14 changes (BABIP denominator, reliever league,
role HBP, k_pct 132, babip 3068, the batter row), how far is the simulated
distribution from the real one — and does K inherit the outs error?

THE POINT IS THE INHERITANCE. `K = batters faced x K rate`, so a length
defect shows up in strikeouts at roughly the same relative size whatever
the rates do. Day nine measured exactly that ("K inherits it exactly, so
fixing length pays twice") on an engine that has since changed underneath
the finding. Reporting outs and K side by side on the same starts is what
makes the claim checkable rather than remembered.

HOLDOUT BY CONSTRUCTION. Rates and the league baseline are frozen before
`HOLDOUT` and only starts on or after it are scored, so a pitcher's own
line cannot contain the start being predicted. `build_cases` takes
`rates_before` and `since` separately for exactly this.

THE ACTUAL SIDE IS THE BINDING SAMPLE. Simulating each game 40 times
sharpens the MODEL's number and does nothing for the target it is compared
against; it is easy to read the combined draws as the sample size and they
are not. Power is printed BEFORE the table for that reason.
"""
from __future__ import annotations

import multiprocessing as mp
import random
import statistics as st
import sys
from collections import Counter

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src
from scratchpad.dispersion import perturb

#: Rates and league frozen before this; only starts on/after it are scored.
HOLDOUT = "2026-07-01"

#: Where books hang these two markets.
OUTS_LINES = (12.5, 14.5, 15.5, 16.5, 17.5, 18.5, 20.5)
K_LINES = (3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5)

_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 40

#: Per-start latent sharpness, borrowed from `scratchpad/dispersion.py`.
#:
#: WHY IT IS BEING RE-SCORED HERE. That script applies the same draw and
#: stops the game after five innings, so it has only ever been judged on F5
#: RUNS — where it is CRPS-neutral, because a flat term added to everyone
#: improves calibration and not discrimination. It has never once been
#: scored on the STARTER'S OWN LINE, which is the quantity a strikeout prop
#: settles on and the place this file measures a defect.
#:
#: The mechanism predicts SELECTION, not just spread: on a sharp night he
#: misses bats AND allows less traffic, so he throws fewer pitches and lasts
#: longer. Real 21+ out starts strike out 6.84; the model's manage 6.09.
_SIGMA = 0.0


def crps(dist: Counter, n: int, actual: int, top: int) -> float:
    """Discrete CRPS over the FULL support — no book's lines involved."""
    c = tot = 0.0
    for v in range(top + 1):
        c += dist.get(v, 0) / n
        tot += (c - (1.0 if v >= actual else 0.0)) ** 2
    return tot


def _one(args):
    """One game, both starters. -> [(actual_outs, outs_dist, actual_k, k_dist)]"""
    i, gid = args
    v = _CASES[gid]
    home = next(x for x in v if x[0]["is_home"])
    away = next(x for x in v if not x[0]["is_home"])
    an = cal.adjust_lineup(away[2], False)
    hn = cal.adjust_lineup(home[2], True)
    # JOINT (outs, k) as well as the marginals: K = batters faced x K rate,
    # so "is K under-dispersed" only localises once length is held fixed.
    aj, hj = Counter(), Counter()
    ao, ho, ak, hk = Counter(), Counter(), Counter(), Counter()
    for draw in range(_SIMS):
        # Seed varies by GAME and by draw. A seed shared across games
        # correlates the per-draw errors and inflates the standard error of
        # any absolute level by ~3.4x — it cancels in a paired A/B and this
        # is not one.
        rng = random.Random(7 + i * 100003 + draw)
        # DRAWN PER START, PER DRAW. Both z's come off the same rng before
        # either side is built, so sigma=0 consumes the same two variates
        # and the comparison stays paired on every later draw.
        za, zh = rng.gauss(0, 1), rng.gauss(0, 1)
        A = game.build_side(perturb(away[1], za, _SIGMA),
                            _PENS.get((away[0]["team"] or "").upper(), []),
                            hn, sim.Hook(), rng, team=away[0]["team"])
        H = game.build_side(perturb(home[1], zh, _SIGMA),
                            _PENS.get((home[0]["team"] or "").upper(), []),
                            an, sim.Hook(), rng, team=home[0]["team"])
        r = game.simulate_game(A, H, _LG, rng)
        ao[r.away_sp.outs] += 1
        ho[r.home_sp.outs] += 1
        ak[r.away_sp.k] += 1
        hk[r.home_sp.k] += 1
        aj[(r.away_sp.outs, r.away_sp.k)] += 1
        hj[(r.home_sp.outs, r.home_sp.k)] += 1
    out = []
    for act, od, kd, jd in ((away[0], ao, ak, aj), (home[0], ho, hk, hj)):
        if act.get("o") is None or act.get("k") is None:
            continue
        out.append((act["o"], od, act["k"], kd, jd))
    return out


def _report(label, real, dists, lines, top):
    n = len(real)
    sim_mean = st.mean(st.mean(list(d.elements())) for d in dists)
    flat = Counter()
    for d in dists:
        flat.update(d)
    tot = sum(flat.values())
    sim_sd = st.pstdev([v for v in flat.elements()])
    print(f"\n  === {label}   n={n} starts, {_SIMS} sims each ===")
    print(f"    {'':<18}{'model':>9}{'actual':>9}{'gap':>9}")
    print(f"    {'mean':<18}{sim_mean:>9.2f}{st.mean(real):>9.2f}"
          f"{sim_mean - st.mean(real):>+9.2f}")
    print(f"    {'sd':<18}{sim_sd:>9.2f}{st.pstdev(real):>9.2f}"
          f"{sim_sd - st.pstdev(real):>+9.2f}")
    if label == "OUTS":
        sb = sum(flat[v] for v in flat if v % 3 == 0) / tot
        rb = cal._boundary(real)
        print(f"    {'boundary share':<18}{sb:>9.3f}{rb:>9.3f}{sb - rb:>+9.2f}")
    print(f"    {'CRPS':<18}"
          f"{st.mean(crps(d, _SIMS, a, top) for d, a in zip(dists, real)):>9.4f}")
    print(f"\n    {'line':<8}{'model':>9}{'actual':>9}{'gap':>9}{'se':>8}")
    for ln in lines:
        m = sum(sum(c for v, c in d.items() if v > ln) for d in dists) / tot
        a = sum(1 for v in real if v > ln) / n
        se = (a * (1 - a) / n) ** 0.5
        print(f"    o{ln:<7}{m:>9.3f}{a:>9.3f}{m - a:>+9.3f}{se:>8.3f}")
    # THE MASS BY VALUE is where a boundary defect is actually visible: a
    # model that ends too many starts mid-inning shows as a deficit at the
    # multiples of three and a surplus beside them.
    print(f"\n    {'value':<8}{'model':>9}{'actual':>9}{'gap':>9}")
    ra = Counter(real)
    lo, hi = (9, 22) if label == "OUTS" else (1, 11)
    for v in range(lo, hi + 1):
        m, a = flat[v] / tot, ra[v] / n
        mark = "  <- boundary" if label == "OUTS" and v % 3 == 0 else ""
        print(f"    {v:<8}{m:>9.3f}{a:>9.3f}{m - a:>+9.3f}{mark}")


#: Day nine's buckets, so the two tables can be read against each other.
BUCKETS = ((0, 8), (9, 11), (12, 14), (15, 17), (18, 20), (21, 27))


def _conditional(rows):
    """E[K | outs] and sd(K | outs), model against actual.

    THE LOCALISING STEP. If K is under-dispersed while OUTS is not, the
    missing spread is in the rate given length rather than in the length —
    which is what a missing per-start K% state looks like, and is a
    different repair from anything aimed at the hook.

    The actual side is thin inside a bucket, so the sd column carries its
    own standard error: sd/sqrt(2n) for n starts in the cell.
    """
    print("\n  === K CONDITIONAL ON LENGTH ===")
    print(f"    {'outs':<10}{'n':>6}{'E[K] mod':>10}{'E[K] act':>10}"
          f"{'sd mod':>9}{'sd act':>9}{'sd gap':>9}{'se':>7}")
    for lo, hi in BUCKETS:
        act = [r[2] for r in rows if lo <= r[0] <= hi]
        if len(act) < 25:
            continue
        mod = Counter()
        for r in rows:
            for (o, k), c in r[4].items():
                if lo <= o <= hi:
                    mod[k] += c
        mv = list(mod.elements())
        sd_m, sd_a = st.pstdev(mv), st.pstdev(act)
        se = sd_a / (2 * len(act)) ** 0.5
        print(f"    {f'{lo}-{hi}':<10}{len(act):>6}{st.mean(mv):>10.2f}"
              f"{st.mean(act):>10.2f}{sd_m:>9.2f}{sd_a:>9.2f}"
              f"{sd_m - sd_a:>+9.2f}{se:>7.2f}")


def main(argv):
    global _CASES, _PENS, _LG, _SIMS, _SIGMA
    pos = [a for a in argv if not a.startswith("-")]
    _SIMS = int(pos[0]) if pos else 40
    cap = int(pos[1]) if len(pos) > 1 else None
    for a in argv:
        if a.startswith("--sigma="):
            _SIGMA = float(a.split("=", 1)[1])
    if "--no-leash" in argv:
        sim.USE_LEASH = False
        sim.USE_OFFSETS = False

    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    gids = sorted(pairs)[:cap] if cap else sorted(pairs)
    _CASES = {g: pairs[g] for g in gids}
    _LG = sim.league(before=HOLDOUT)
    _PENS = rate_src.bullpens(_LG, before=HOLDOUT)

    n_starts = 2 * len(gids)
    print(f"  holdout {HOLDOUT}+, {len(gids)} games / ~{n_starts} starts, "
          f"{_SIMS} sims each, leash "
          f"{'OFF' if '--no-leash' in argv else 'ON'}"          f", sigma {_SIGMA}")
    # POWER FIRST. A run chosen for speed is a plumbing check and its
    # number is not reportable.
    print(f"  POWER (actual side is binding, n~{n_starts}):")
    print(f"    boundary share  se {(0.67 * 0.33 / n_starts) ** 0.5:.4f}"
          f"  -> resolves {3 * (0.67 * 0.33 / n_starts) ** 0.5:.3f} at 3 sigma")
    print(f"    mean outs       se {4.05 / n_starts ** 0.5:.3f}"
          f"  -> resolves {3 * 4.05 / n_starts ** 0.5:.2f} at 3 sigma")
    print(f"    mean K          se {2.48 / n_starts ** 0.5:.3f}"
          f"  -> resolves {3 * 2.48 / n_starts ** 0.5:.2f} at 3 sigma")

    ctx = mp.get_context("fork")     # never spawn: USE_* flags revert
    with ctx.Pool(max(1, (mp.cpu_count() or 2) - 1)) as pool:
        got = pool.map(_one, list(enumerate(gids)))
    rows = [r for g in got for r in g]
    # PER-START CRPS DUMPED FOR A PAIRED TEST. The sweep is paired by
    # construction — same games, same seeds, the latent z drawn at the
    # same stream position — so the difference between two sigmas has a
    # standard error of its own and the unpaired columns do not show it.
    import json
    json.dump({"sigma": _SIGMA,
               "outs": [crps(r[1], _SIMS, r[0], 28) for r in rows],
               "k": [crps(r[3], _SIMS, r[2], 20) for r in rows]},
              open(f"scratchpad/shape_crps_{_SIGMA:.2f}.json", "w"))
    _report("OUTS", [r[0] for r in rows], [r[1] for r in rows], OUTS_LINES, 28)
    _report("K", [r[2] for r in rows], [r[3] for r in rows], K_LINES, 20)
    _conditional(rows)


if __name__ == "__main__":
    main(sys.argv[1:])
