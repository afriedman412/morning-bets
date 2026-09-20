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


#: Shifts every game's seed together. The arms stay PAIRED whatever it is —
#: they share the seed, so a re-run answers "is this difference bigger than
#: the simulation noise" rather than re-rolling one arm against another.
SEED = 11


def _one(args):
    i, gid = args
    pair = _CASES[gid]
    rng = random.Random(SEED + i * 100003)
    draws = [cal.replay(pair, _LG, _PENS, rng, track=(5,)) for _ in range(_SIMS)]
    # THE STATED PRODUCT. Starter lines are diagnostics; F5 and full team
    # totals are what settles. A gain on strikeouts that does not reach the
    # total is a gain on a prop nobody asked this model to price.
    a_act = pair[1][0].get("r")          # runs the HOME starter allowed
    h_act = pair[0][0].get("r")
    tot = [d.away + d.home for d in draws]
    f5 = [sum(d.prefix_side[5]) for d in draws if 5 in d.prefix_side]
    out = [{"kind": "game",
            "tot_dist": Counter(tot), "tot_mean": st.mean(tot),
            "f5_mean": st.mean(f5) if f5 else None,
            "f5_dist": Counter(f5),
            "gid": gid}]
    for side, attr in ((0, "away_sp"), (1, "home_sp")):
        s = pair[side][0]
        lines = [getattr(d, attr) for d in draws]
        out.append({
            "kind": "sp",
            "o_act": s["o"], "k_act": s["k"],
            "o_dist": Counter(x.outs for x in lines),
            "k_dist": Counter(x.k for x in lines),
            "o_mean": st.mean(x.outs for x in lines),
            "k_mean": st.mean(x.k for x in lines),
        })
    return out


def score(rows):
    n = _SIMS
    rows = [r for r in rows if r.get("kind") == "sp"]
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


#: The four ways to treat a previous season, which is the actual question:
#:   none    each season is a different person          (what ships)
#:   pool    flat, an April 2025 inning = an August 2026 one
#:   prior   last season is the PRIOR his thin line shrinks toward
#:   prior3  the same, over three prior seasons at the MEASURED decay
#:
#: `prior3` is the arm added on day eleven. `scratchpad.decay` counted how
#: far a season carries — k_pct 0.3, bb_pct 0.5, hr_pct 0.7, babip 0.0 —
#: and the gain it predicts is mostly COVERAGE rather than sharpness: 22
#: more of the 467 meaningful 2026 arms get a prior at all, and 77 more of
#: the thin ones. Note which way that cuts here. Coverage is not accuracy,
#: and `run_variant`'s `restrict` is what keeps this honest.
ARMS = ("none", "pool", "prior", "prior3")


def cases_for(cut, arm):
    cal._CASES.clear()
    sim._LEAGUE_CACHE.clear()
    rate_src.USE_PRIOR_SEASON = arm.startswith("prior")
    if arm.startswith("prior"):
        rate_src.set_prior(scope.CURRENT_SEASON - 1,
                           seasons=1 if arm == "prior" else None)
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


def _totals(cut, got):
    """Game and F5 totals against what was actually scored."""
    truth = actual_totals(cut)
    print(f"    {'TOTALS':<14}" + "".join(f"{a:>12}" for a in ARMS))
    for label, mkey in (("game RMSE", "tot_mean"), ("F5 RMSE", "f5_mean")):
        line = f"    {label:<14}"
        for a in ARMS:
            errs = []
            for r in got[a]:
                if r.get("kind") != "game" or r.get(mkey) is None:
                    continue
                t = truth.get(r["gid"])
                if not t:
                    continue
                act = t[0] if mkey == "tot_mean" else t[1]
                if act is None:
                    continue
                errs.append(act - r[mkey])
            line += (f"{(st.mean(e*e for e in errs))**0.5:>12.3f}"
                     if errs else f"{'-':>12}")
        print(line)
    for label, mkey in (("game bias", "tot_mean"), ("F5 bias", "f5_mean")):
        line = f"    {label:<14}"
        for a in ARMS:
            errs = []
            for r in got[a]:
                if r.get("kind") != "game" or r.get(mkey) is None:
                    continue
                t = truth.get(r["gid"])
                if not t:
                    continue
                act = t[0] if mkey == "tot_mean" else t[1]
                if act is not None:
                    errs.append(r[mkey] - act)
            line += f"{st.mean(errs):>+12.3f}" if errs else f"{'-':>12}"
        print(line)


def actual_totals(cut):
    """{game_id: (full total, F5 total)} for games on or after the cut."""
    from src import db
    with db.connect() as c:
        return {r["game_id"]: (
            (r["away_score"] or 0) + (r["home_score"] or 0),
            ((r["away_score_f5"] + r["home_score_f5"])
             if r["away_score_f5"] is not None
             and r["home_score_f5"] is not None else None))
            for r in c.execute(
                "select game_id, away_score, home_score, away_score_f5,"
                " home_score_f5 from games where sport='mlb'"
                " and status='Final' and date >= ?", (cut,))}


def main(argv):
    global _SIMS, SEED
    pos = [a for a in argv if a.isdigit()]
    _SIMS = int(pos[0]) if pos else 30
    for a in argv:
        if a.startswith("--seed="):
            SEED = int(a.split("=", 1)[1])
    cuts = [a.split("=", 1)[1] for a in argv if a.startswith("--cut=")] or CUTS
    for cut in cuts:
        print(f"\n  CUT {cut} — rates frozen before it, starts scored after")
        sets = {a: set(cases_for(cut, a)) for a in ARMS}
        common = set.intersection(*sets.values())
        print("    coverage: "
              + ", ".join(f"{a} {len(v)}" for a, v in sets.items())
              + f", scoring the {len(common)} in all three")
        got = {a: run_variant(cut, a, a, common) for a in ARMS}
        sc = {a: score(v) for a, v in got.items()}
        _totals(cut, got)
        print(f"    {'metric':<14}" + "".join(f"{a:>12}" for a in ARMS)
              + f"{'prior3-prior':>14}")
        for k in sc["none"]:
            row = f"    {k:<14}" + "".join(f"{sc[a][k]:>12.4f}" for a in ARMS)
            # The comparison that decides whether the extra seasons ship.
            # `prior` against `none` is day ten's question and is already
            # answered; what is open is whether three beat one.
            d = sc["prior3"][k] - sc["prior"][k]
            better = ""
            if "CRPS" in k:
                better = "  better" if d < 0 else ""
            elif "corr" in k:
                better = "  better" if d > 0 else ""
            print(row + f"{d:>+14.4f}{better}")
    print("\n  CRPS lower is better; corr higher is better. Bias is reported")
    print("  and NOT optimised — it is the known mean-outs defect and it")
    print("  should not decide a question about memory.")


if __name__ == "__main__":
    main(sys.argv[1:])
