"""DOES THE SHIPPED LEASH CARRY FROM ONE SEASON TO THE NEXT? And by how much?

    venv/bin/python -m scratchpad.leash_carry [n_sims] [--limit N]

THE ARGUMENT, and it is the one genuinely actionable thing to come out of
TODO 32. `leash.py` shrinks a pitcher's outs residual by K = within_var /
between_var off a one-way ANOVA. That removes SAMPLING noise — "how much of
the spread between these arms is real" — and it is the right answer to that
question. It is not the question the engine asks. The engine asks "how much
of what was real LAST year is still true in the start I am simulating", and
an arm ages, changes clubs and managers, and the league drifts under him.

Shrinking for sampling noise alone therefore leaves a term that describes an
arm's past correctly and OVER-CORRECTS his future. THAT IS EXACTLY THE
MEASURED DEFECT. TODO 32 established, on holdout decisions, that the leash
misses at BOTH ENDS — arms with no entry under-pulled by +0.0291 (z +4.4),
arms it thinks come out early over-pulled by -0.0356 (z -3.3) — which is the
signature of a term that SPREADS PITCHERS TOO FAR APART rather than one
pointing the wrong way. The same gap was found and fixed inside
`src/context/armhook.py`, where the year-over-year reliability is measured on
decisions at +0.558 (boundary) and +0.397 (mid) and multiplies every offset.

So: measure the same carry for the OUTS residual the leash is built from, and
report what rescaling by it would do.

WHY THIS IS NOT "SOLVING FOR A LEVEL" (rule 5). Nothing here consults a loss
function and no constant is free to move. The carry is the between-season
correlation of a measured quantity — one number, read off the data, the same
way `stabilise.py` reads its four shrinkage constants. A SEARCH over scale
factors to see which one scores best is the forbidden move and is not what
this is. The falsifier below is scored once, after the number is fixed.

METHOD. One simulation pass over every replayable PRE-HOLDOUT start with the
leash OFF, so the residual is measured against the bare hook — the
`apply_leash=False` discipline `leash._sim_one` needs, for the reason it
gives: a residual measured against a correction already applied folds that
correction back into itself. Residuals are aggregated per (arm, season),
consecutive seasons paired, and the correlation is the carry.

REPORTED WITH THE CONFOUND VISIBLE, the way `hook_resid.year_over_year` does
it: RAW, and with each SEASON'S OWN MEAN removed first. The second is what a
per-arm term has to beat, because a league-wide drift would otherwise show
up as every arm agreeing with himself.
"""
from __future__ import annotations

import math
import multiprocessing as mp
import os
import random
import statistics as st
import sys
import zlib
from collections import defaultdict

from src.context import calibrate as cal, leash, sim
from src.context.holdout import HOLDOUT
from src.context.sources import rates as rate_src

_CASES: dict = {}
_PENS: dict = {}
_SIMS = 24

#: Starts an arm needs in a season before that season's mean residual is
#: used. Low enough to keep the pair count usable, high enough that a single
#: disaster start is not a season. Stated here rather than buried: at six
#: starts a season mean carries roughly 1.7 outs of noise, which ATTENUATES
#: the correlation below — so the number this prints is a FLOOR on the true
#: carry, not an estimate of it, and the Spearman-Brown line says by how
#: much.
MIN_STARTS = 6


def _init(cases, pens, sims):
    global _CASES, _PENS, _SIMS
    _CASES, _PENS, _SIMS = cases, pens, sims
    sim.USE_LEASH = False
    sim.USE_ARM_HOOK = False
    sim.reload_offsets()


def _one(gid):
    pair = _CASES[gid]
    lg = sim.league()
    draws = [cal.replay(pair, lg, _PENS,
                        random.Random(zlib.crc32(f"{gid}|{d}".encode())))
             for d in range(_SIMS)]
    out = []
    for idx, side in ((0, "away_sp"), (1, "home_sp")):
        s = pair[idx][0]
        if s.get("o") is None:
            continue
        m = st.fmean(getattr(g, side).outs for g in draws)
        out.append((s["player_name"], s["date"], s["o"] - m))
    return out


def _corr(pairs):
    n = len(pairs)
    if n < 4:
        return 0.0
    mx = sum(x for x, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    num = sum((x - mx) * (y - my) for x, y in pairs)
    dx = sum((x - mx) ** 2 for x, _ in pairs) ** 0.5
    dy = sum((y - my) ** 2 for _, y in pairs) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def run(sims: int, limit: int | None) -> None:
    cases = {}
    for season in (2023, 2024, 2025, 2026):
        c = cal.paired_cases(season=season, before=HOLDOUT,
                             rates_before=HOLDOUT)
        print(f"  {season}: {len(c)} paired games before {HOLDOUT}")
        cases.update(c)
    gids = sorted(cases)
    if limit:
        gids = gids[:limit]
    cases = {g: cases[g] for g in gids}
    pens = rate_src.bullpens(sim.league(), before=HOLDOUT)
    print(f"  {len(gids)} games x {sims} draws, leash OFF")

    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, (os.cpu_count() or 4) - 2), initializer=_init,
                  initargs=(cases, pens, sims)) as pool:
        rows = pool.map(_one, gids, chunksize=8)

    cells: dict = defaultdict(list)
    for r in rows:
        for nm, date, resid in r:
            cells[(nm, date[:4])].append(resid)
    big = {k: v for k, v in cells.items() if len(v) >= MIN_STARTS}
    per_season: dict = defaultdict(list)
    for (_nm, s), v in big.items():
        per_season[s].extend(v)
    sm = {s: st.fmean(v) for s, v in per_season.items()}
    print(f"\n  {len(big)} arm-seasons with >= {MIN_STARTS} starts")
    print("  season mean residual (actual minus model outs): " + "  ".join(
        f"{s} {sm[s]:+.3f}" for s in sorted(sm)))

    for label, tbl in (
            ("RAW", {k: st.fmean(v) for k, v in big.items()}),
            ("DE-SEASONED", {k: st.fmean(v) - sm[k[1]]
                             for k, v in big.items()})):
        pairs = [(tbl[(nm, s)], tbl[(nm, str(int(s) + 1))])
                 for (nm, s) in tbl if (nm, str(int(s) + 1)) in tbl]
        if len(pairs) < 25:
            print(f"  {label}: {len(pairs)} arm-pairs — NOT POWERED")
            continue
        r = _corr(pairs)
        se = 1 / math.sqrt(len(pairs) - 3)
        sd = st.pstdev([p[0] for p in pairs])
        # Spearman-Brown up to the full sample an offset is actually built
        # on: one season is the unit here, the shipped table pools four, so
        # the single-season correlation UNDERSTATES the carry of the real
        # estimate. Both are printed; the shipped-table number is the second.
        sb = 2 * r / (1 + r) if r > -1 else float("nan")
        print(f"\n  {label}: {len(pairs)} arm-pairs   carry r {r:+.3f} "
              f"(se {se:.3f})   two-season equivalent {sb:+.3f}")
        # THE TWO SPREADS THAT GET CONFUSED, and the first version of this
        # script printed the wrong one as its headline. Keep them apart:
        #   STABLE SIGNAL  sd*sqrt(r) — how much real, repeatable between-arm
        #     spread exists. This is what a table built on a LONG record
        #     should converge to, and the right thing to compare a shipped
        #     table's width against.
        #   OPTIMAL PREDICTION FROM ONE SEASON  sd*r — the best predictor
        #     shrinks toward the mean, so from a single season's evidence it
        #     is NARROWER than the signal it is predicting.
        # A shipped table sitting between them is correctly scaled for the
        # evidence it was built on. Reading the first as the second is how a
        # correctly-scaled table gets reported as 2.7x too wide.
        print(f"    season-mean residual spread sd {sd:.3f} outs")
        print(f"    STABLE signal sd {sd * math.sqrt(max(r, 0)):.3f} outs   "
              f"optimal prediction from ONE season sd "
              f"{sd * max(r, 0):.3f} outs")

    # What the shipped offsets actually imply, for comparison — if their
    # spread already sits at the projectable one, there is nothing to fix
    # and this whole line of reasoning is wrong.
    import json
    with open(sim._LEASH_PATH) as f:
        lsh = {k: v for k, v in json.load(f).items() if k != "_meta"}
    implied = [leash._d_outs(v) for v in lsh.values()]
    print(f"\n  the SHIPPED table: {len(lsh)} arms, implied outs spread sd "
          f"{st.pstdev(implied):.3f}, range {min(implied):+.2f} to "
          f"{max(implied):+.2f}")
    print("  COMPARE against the STABLE signal sd above, not the optimal-"
          "prediction sd: the shipped offsets are built on up to four "
          "seasons, so that is the width they should approach.")


def main() -> None:
    args = sys.argv[1:]
    pos = [a for a in args if not a.startswith("-")]
    sims = int(pos[0]) if pos else 24
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    run(sims, limit)


if __name__ == "__main__":
    main()
