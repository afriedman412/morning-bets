"""Is a pitcher's LAST SEASON worth anything for pricing this one?

    venv/bin/python -m scratchpad.memory [n_sims]

THE QUESTION. Every rate in this model is measured on the current season
only, which was not a decision — it was what one season of data forced.
With 2025 loaded it becomes a choice, and the honest way to settle it is to
price the same 2026 starts twice: once off 2026 rates alone, once off rates
that also remember 2025, and score both against what actually happened.

WHY IT MIGHT HELP. Early in a season a pitcher's rates are thin, and the
model handles that by shrinking toward the league — which throws away a
perfectly good 180-inning record from last year in favour of a league
average. If memory pays anywhere it pays in April.

WHY IT MIGHT NOT, and the reason to test rather than assume: a pitcher is
not the same pitcher across a winter. deGrom is the case already on record
here — same K%, walks up 63%, BABIP .255 to .407 — and last year's line
would actively mislead. The league changes too: home runs are up 7% between
these two seasons, so a 2025 HR rate is measured against a different ball.

TWO CUTS, DELIBERATELY. A May cut is where 2026 rates are thinnest and
memory should matter most; a July cut is where it should matter least. If
the gain does not shrink between them, whatever is being measured is not
memory.

SCORED ON OUTCOMES, not on agreement with a price: discrete CRPS over the
full support for the starter's outs and strikeouts, plus the correlation
between the predicted mean and the actual — the discrimination the headroom
work says is the missing half. Paired: identical games, identical seeds,
only the rates differ.
"""
from __future__ import annotations

import concurrent.futures as cf
import multiprocessing as mp
import os
import random
import statistics as st
import sys
from collections import Counter

from src.context import calibrate as cal
from src.context import scope, sim
from src.context.sources import rates as rate_src

MAX = 30
CUTS = ("2026-05-01", "2026-07-01")

_CASES: dict = {}
_PENS: dict = {}
_LG = None
_SIMS = 30


def crps(dist: Counter, n: int, actual: int) -> float:
    tot, c = 0.0, 0.0
    for v in range(MAX + 1):
        c += dist.get(v, 0) / n
        tot += (c - (1.0 if v >= actual else 0.0)) ** 2
    return tot


def corr(xs, ys) -> float:
    n = len(xs)
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if not sx or not sy:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (n * sx * sy)


def _one(args):
    i, gid = args
    pair = _CASES[gid]
    rng = random.Random(11 + i * 100003)
    draws = [cal.replay(pair, _LG, _PENS, rng) for _ in range(_SIMS)]
    out = []
    for side, attr in ((0, "away_sp"), (1, "home_sp")):
        s = pair[side][0]
        lines = [getattr(d, attr) for d in draws]
        out.append({
            "o_act": s["o"], "k_act": s["k"],
            "o_dist": Counter(x.outs for x in lines),
            "k_dist": Counter(x.k for x in lines),
            "o_mean": st.mean(x.outs for x in lines),
            "k_mean": st.mean(x.k for x in lines),
        })
    return out


def score(rows):
    n = _SIMS
    return {
        "outs CRPS": st.mean(crps(r["o_dist"], n, r["o_act"]) for r in rows),
        "K CRPS": st.mean(crps(r["k_dist"], n, r["k_act"]) for r in rows),
        "outs corr": corr([r["o_mean"] for r in rows],
                          [r["o_act"] for r in rows]),
        "K corr": corr([r["k_mean"] for r in rows],
                       [r["k_act"] for r in rows]),
        "outs bias": st.mean(r["o_mean"] - r["o_act"] for r in rows),
        "K bias": st.mean(r["k_mean"] - r["k_act"] for r in rows),
    }


#: The three ways to treat a previous season, which is the actual question:
#:   none   each season is a different person          (what ships)
#:   pool   flat, an April 2025 inning = an August 2026 one
#:   prior  last season is the PRIOR his thin line shrinks toward
ARMS = ("none", "pool", "prior")


def cases_for(cut, arm):
    cal._CASES.clear()
    sim._LEAGUE_CACHE.clear()
    rate_src.USE_PRIOR_SEASON = (arm == "prior")
    if arm == "prior":
        rate_src.set_prior(scope.CURRENT_SEASON - 1)
    else:
        rate_src.set_prior(None)
    kw = {"rates_season": scope.ALL_SEASONS} if arm == "pool" else {}
    return cal.paired_cases(season=scope.CURRENT_SEASON, since=cut,
                            rates_before=cut, **kw)


def run_variant(cut, arm, label, restrict=None):
    """`restrict` forces both arms onto the SAME games.

    Without it the comparison is not paired and it flatters memory for the
    wrong reason: a 2026 callup with a 2025 record has rates under memory
    and none without, so extra games appear in one arm only. That coverage
    gain is real and is reported separately — it is just not accuracy.
    """
    global _CASES, _PENS, _LG
    pairs = cases_for(cut, arm)
    if restrict is not None:
        pairs = {g: v for g, v in pairs.items() if g in restrict}
    if not pairs:
        raise SystemExit(f"no paired cases for {cut}/{label}")
    _CASES = pairs
    _LG = sim.league(scope.ALL_SEASONS if arm == "pool"
                     else scope.CURRENT_SEASON, before=cut)
    _PENS = rate_src.bullpens(_LG)
    gids = list(pairs)
    workers = max(1, (os.cpu_count() or 4) - 1)
    rows = []
    with cf.ProcessPoolExecutor(max_workers=workers,
                                mp_context=mp.get_context("fork")) as pool:
        for res in pool.map(_one, list(enumerate(gids))):
            rows += res
    print(f"    {label:<22}{len(rows):>6} starts", flush=True)
    return rows


def main(argv):
    global _SIMS
    _SIMS = int(argv[0]) if argv else 30
    for cut in CUTS:
        print(f"\n  CUT {cut} — rates frozen before it, starts scored after")
        sets = {a: set(cases_for(cut, a)) for a in ARMS}
        common = set.intersection(*sets.values())
        print("    coverage: "
              + ", ".join(f"{a} {len(v)}" for a, v in sets.items())
              + f", scoring the {len(common)} in all three")
        got = {a: run_variant(cut, a, a, common) for a in ARMS}
        sc = {a: score(v) for a, v in got.items()}
        print(f"    {'metric':<14}" + "".join(f"{a:>12}" for a in ARMS)
              + f"{'prior-none':>12}")
        for k in sc["none"]:
            row = f"    {k:<14}" + "".join(f"{sc[a][k]:>12.4f}" for a in ARMS)
            d = sc["prior"][k] - sc["none"][k]
            better = ""
            if "CRPS" in k:
                better = "  better" if d < 0 else ""
            elif "corr" in k:
                better = "  better" if d > 0 else ""
            print(row + f"{d:>+12.4f}{better}")
    print("\n  CRPS lower is better; corr higher is better. Bias is reported")
    print("  and NOT optimised — it is the known mean-outs defect and it")
    print("  should not decide a question about memory.")


if __name__ == "__main__":
    main(sys.argv[1:])
