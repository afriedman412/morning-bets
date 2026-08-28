"""Are we predicting WHICH batters produce the offence?

    venv/bin/python -m scratchpad.offense [n_sims] [--cut YYYY-MM-DD]

QUESTION. Not "is the team total right" — that is measured elsewhere and it
is close. Whether the RIGHT MEN produce it. Unit of observation is the
BATTER-GAME: one hitter, one game, runs scored and runs driven in, against
`mlb_batting`'s actual line for him.

Answerable for the first time as of today. `sim.StartResult` has carried
`scored_by`/`rbi_by` since 2026-08-27, but `Side.next_arm` replaced the line
on every pitching change and every reliever's attribution was dropped —
about a third of the runs in a game. `Side.offense()` merges across arms now.

TWO SEPARATE QUESTIONS AND THEY MUST NOT BE POOLED.

  A. LEVEL BY LINEUP SLOT. The leadoff man scores more and the cleanup man
     drives in more, purely from where he bats. This is batting-order
     mechanics — the run-scoring machine, not the hitters. Scored against
     the SAME NINE in the same order, since `opposing_lineups` feeds the
     simulator the card that actually played.

  B. DIFFERENTIATION BETWEEN HITTERS. Does Judge take the share he should,
     or is he priced as a league-average bat? Regress actual on predicted:
     slope 1.0 means the spread is right, above 1 means the model bunches
     hitters together.

OUT OF SAMPLE OR IT MEASURES NOTHING. A hitter's shipped rate is built from
the season it would be graded against, and with his own sampling noise
inside the predictor AND inside the outcome the slope tends to 1/w — the
shrinkage weight — however good the model is. That artifact cost a day on
the pitcher side (`scratchpad/hr_spread.py --synth`). Rates are trained
strictly before the cutoff and only starts after it are scored.

THE MONTE CARLO CORRECTION IS THE SAME ONE. A per-batter mean over `n_sims`
draws carries its own noise, and noise in a regression PREDICTOR attenuates
the slope toward zero, so the raw number understates the model. Both are
printed.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import random
import zlib
import statistics as st
import sys
from collections import defaultdict

from src import db
from src.context import calibrate as cal, sim
from src.context.sources import rates as rate_src

CUT = "2026-07-01"
_CASES: dict = {}
_LG: dict = {}
_PENS: dict = {}


def actuals(game_ids) -> dict:
    """{(game_id, player): (runs, rbi)} straight off the boxscores."""
    out = {}
    with db.connect() as c:
        for r in c.execute(
                "select game_id, player_name, r, rbi from mlb_batting"):
            if r["game_id"] in game_ids:
                out[(r["game_id"], r["player_name"])] = (r["r"] or 0,
                                                         r["rbi"] or 0)
    return out


def _one(args):
    """Per (game, batter): slot, mean predicted runs, mean predicted rbi."""
    gid, n_sims, seed = args
    pair = _CASES[gid]
    # SEED VARIES BY GAME. `seed=0` for every game puts draw i at the same
    # position in the stream for all of them, which correlates the per-draw
    # errors across games and inflates the standard error of any LEVEL or
    # SHARE by about 3.4x (measured: block sd 0.385 against 0.113). Every
    # number in sections A and C is a level or a share.
    rng = random.Random((zlib.crc32(gid.encode()) & 0xFFFF) * 1009 + seed)
    # Sum AND sum of squares: the within-batter-game variance across draws
    # is what the attenuation correction needs, and recomputing it later is
    # impossible once the draws are gone.
    acc: dict = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    # CONCENTRATION, per DRAW and not from the means. Whether one hitter
    # drives in four is a property of a single game; averaging each batter
    # over 40 draws first destroys exactly the quantity being asked about.
    conc: list = []
    for _ in range(n_sims):
        r = cal.replay(pair, _LG, _PENS, rng)
        for bats, tot in ((r.away_bats, r.away), (r.home_bats, r.home)):
            rb = sorted((v["rbi"] for v in bats.values()), reverse=True)
            rs = sorted((v["r"] for v in bats.values()), reverse=True)
            conc.append((tot, rb[0] if rb else 0, rs[0] if rs else 0,
                         sum(1 for x in rb if x >= 2),
                         sum(1 for x in rb if x >= 3)))
        for bats in (r.away_bats, r.home_bats):
            for who, v in bats.items():
                acc[who][0] += v["r"]
                acc[who][1] += v["rbi"]
                acc[who][2] += v["r"] ** 2
                acc[who][3] += v["rbi"] ** 2
    # The nine each side FACES, in order. `away[2]` is the HOME club's
    # card — the same crossing `replay` documents — but for a per-batter
    # tally only the ORDER matters, and both cards are wanted.
    slots = {}
    for case in pair:
        for i, b in enumerate(case[2][:9]):
            slots[b.name] = i + 1
    out = []
    for who, v in acc.items():
        mr, mb = v[0] / n_sims, v[1] / n_sims
        out.append((gid, who, slots.get(who, 0), mr, mb,
                    max(v[2] / n_sims - mr * mr, 0.0),
                    max(v[3] / n_sims - mb * mb, 0.0)))
    return out, conc


def slope(xs, ys):
    n = len(xs)
    mx, my = st.mean(xs), st.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if not sxx:
        return 0.0, 0.0
    b = sxy / sxx
    resid = [y - (my + b * (x - mx)) for x, y in zip(xs, ys)]
    s2 = sum(r * r for r in resid) / max(n - 2, 1)
    return b, (s2 / sxx) ** 0.5


def _line(unit, stat, xs, ys, mc_var):
    """One row, with the Monte Carlo attenuation undone.

    A per-batter mean over `n_sims` draws is a NOISY predictor, and noise in
    a regression predictor pulls the slope toward zero. At 40 draws that
    noise is most of a batter-game's predicted spread, so the raw number is
    not reportable on its own — the same correction, and the same reason,
    as `spread_cal` and `hr_spread`.
    """
    b, se = slope(xs, ys)
    var_obs = st.pstdev(xs) ** 2
    var_true = var_obs - mc_var
    if var_true <= 0:
        print(f"  {unit:<16}{stat:<5}{len(xs):>8,}{var_obs ** 0.5:>10.4f}"
              f"{mc_var ** 0.5:>8.4f}   predictor is ALL simulation noise")
        return
    infl = var_obs / var_true
    print(f"  {unit:<16}{stat:<5}{len(xs):>8,}{var_obs ** 0.5:>10.4f}"
          f"{mc_var ** 0.5:>8.4f}{b:>8.3f}{b * infl:>8.3f}"
          f"{(b * infl - 1) / (se * infl):>+8.1f}")


def main(argv):
    global _CASES, _LG, _PENS
    cut = CUT
    if "--cut" in argv:
        i = argv.index("--cut")
        cut = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    amplify = 1.0
    if "--amplify" in argv:
        i = argv.index("--amplify")
        amplify = float(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    # The batter constants `stabilise` measures TODAY, against the shipped
    # 32/80/160/184. Same staleness the pitcher k_pct turned out to have —
    # measured on less data and never re-run after the four-season load —
    # and higher means MORE shrinkage, which is the direction an
    # over-differentiated lineup asks for.
    if "--bat-measured" in argv:
        argv = [a for a in argv if a != "--bat-measured"]
        rate_src.STABILISE_MEASURED["bat"] = {
            "k_pct": 51, "bb_pct": 122, "hr_pct": 193, "babip": 250}
        print("  BATTER CONSTANTS at the currently measured 51/122/193/250")
    n_sims = int(argv[0]) if argv else 40
    _LG = sim.league()
    # POSITIVE CONTROL. Push every hitter's rates FURTHER from the league by
    # `amplify`, which over-differentiates the lineup by a known factor. The
    # measured slope must fall by that factor — if it does not, the harness
    # cannot see between-hitter spread and a slope near 1 would mean
    # nothing. A mis-specified instrument and an absent effect look
    # identical without this.
    _PENS = rate_src.bullpens(_LG, before=cut)
    _CASES = cal.paired_cases(season=2026, since=cut, rates_before=cut)
    if amplify != 1.0:
        print(f"  POSITIVE CONTROL: batter spread x{amplify}")
        seen = set()
        for pair in _CASES.values():
            for case in pair:
                for b in case[2]:
                    if id(b) in seen:
                        continue        # one object can sit in many cards
                    seen.add(id(b))
                    for stat in ("k_pct", "bb_pct", "hr_pct", "babip"):
                        base = _LG[stat]
                        setattr(b, stat, max(1e-4, base + amplify
                                             * (getattr(b, stat) - base)))
    print(f"  HOLDOUT: rates before {cut}, scored on games from {cut}")
    print(f"  {len(_CASES)} games x {n_sims} sims\n", flush=True)
    ctx = mp.get_context("fork")
    workers = max(1, (os.cpu_count() or 4) - 2)
    rows = []
    with ctx.Pool(workers) as pool:
        conc = []
        for got, cc in pool.imap(_one, [(g, n_sims, 0) for g in _CASES],
                                 chunksize=8):
            rows.extend(got)
            conc.extend(cc)
    act = actuals(set(_CASES))
    # A batter the model simulated who has no boxscore line did not bat —
    # a card that changed after the lineup was posted. Dropped rather than
    # scored as a zero, which would credit the model for a man who never
    # came to the plate.
    keep = [row for row in rows if (row[0], row[1]) in act]
    print(f"  {len(rows):,} simulated batter-games,"
          f" {len(keep):,} matched to a boxscore line"
          f" ({len(keep) / max(len(rows), 1):.0%})\n")

    # ---- A. LEVEL BY SLOT ---------------------------------------------
    print("  A. LEVEL BY LINEUP SLOT — the batting-order machine.")
    print(f"  {'slot':>5}{'n':>8}{'pred r':>9}{'act r':>8}{'diff':>8}"
          f"{'pred rbi':>10}{'act rbi':>9}{'diff':>8}")
    by_slot = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])
    for row in keep:
        g, w, s, pr, pb = row[0], row[1], row[2], row[3], row[4]
        if not s:
            continue
        a = by_slot[s]
        ar, ab = act[(g, w)]
        a[0] += pr
        a[1] += ar
        a[2] += pb
        a[3] += ab
        a[4] += 1
    for s in sorted(by_slot):
        p_r, a_r, p_b, a_b, n = by_slot[s]
        print(f"  {s:>5}{n:>8,}{p_r / n:>9.3f}{a_r / n:>8.3f}"
              f"{(p_r - a_r) / n:>+8.3f}{p_b / n:>10.3f}{a_b / n:>9.3f}"
              f"{(p_b - a_b) / n:>+8.3f}")

    # ---- B. DIFFERENTIATION -------------------------------------------
    print("\n  B. DIFFERENTIATION — regress ACTUAL on PREDICTED.")
    print("  slope 1.0 = the spread across hitters is right;")
    print("  above 1 = the model bunches them toward a common bat.\n")
    print(f"  {'unit':<16}{'stat':<5}{'n':>8}{'sd(pred)':>10}{'MC sd':>8}"
          f"{'raw b':>8}{'TRUE b':>8}{'z vs 1':>8}")
    for stat, idx, widx in (("r", 3, 5), ("rbi", 4, 6)):
        xs = [row[idx] for row in keep]
        ys = [act[(row[0], row[1])][0 if stat == "r" else 1] for row in keep]
        mc = st.mean(row[widx] for row in keep) / n_sims
        _line("batter-game", stat, xs, ys, mc)
    # Collapsed to the PLAYER, which is the unit the shrinkage constants
    # are about. A batter-game is one plate appearance's worth of luck;
    # averaging his games is where a hitter's own spread has to show up.
    for stat, idx, widx in (("r", 3, 5), ("rbi", 4, 6)):
        per = defaultdict(lambda: [0.0, 0.0, 0])
        per_w: dict = defaultdict(float)
        for row in keep:
            a = per[row[1]]
            a[0] += row[idx]
            a[1] += act[(row[0], row[1])][0 if stat == "r" else 1]
            a[2] += 1
            per_w[row[1]] += row[widx]
        for k in per_w:
            per_w[k] /= per[k][2]
        d = {k: v for k, v in per.items() if v[2] >= 20}
        xs = [v[0] / v[2] for v in d.values()]
        ys = [v[1] / v[2] for v in d.values()]
        if len(xs) < 30:
            continue
        # His MEAN over g games carries 1/g of one game's draw noise.
        mc = st.mean(per_w[k] / n_sims / per[k][2] for k in d)
        _line("player (20+ g)", stat, xs, ys, mc)
    concentration(conc, cut)


def concentration(conc, cut):
    """C. Is a team's offence spread across the nine the way reality's is?

    The standing diagnosis of the run gap is CLUSTERING — reality has more
    shutouts AND more blowups while the model bunches in the middle,
    because plate appearances resolve independently here and arrive
    together in life. Runs are convex in clustering, so the thin tail also
    drags the mean.

    Every test of that so far has been on the TEAM's run total. This looks
    at the same thing one level down: if the model's innings really are too
    independent, its runs will be spread more evenly across the nine and
    the BIG INDIVIDUAL GAME will be missing.
    """
    from src import db
    with db.connect() as c:
        act: dict = defaultdict(list)
        gids = set(_CASES)
        for r in c.execute("select game_id, team, r, rbi from mlb_batting"):
            if r["game_id"] in gids:
                act[(r["game_id"], r["team"])].append((r["r"] or 0,
                                                       r["rbi"] or 0))
    a_rows = []
    for lst in act.values():
        rb = sorted((b for _a, b in lst), reverse=True)
        rs = sorted((a for a, _b in lst), reverse=True)
        a_rows.append((sum(a for a, _b in lst), rb[0] if rb else 0,
                       rs[0] if rs else 0,
                       sum(1 for x in rb if x >= 2),
                       sum(1 for x in rb if x >= 3)))
    print(f"\n  C. CONCENTRATION — {len(conc):,} simulated team-games"
          f" against {len(a_rows):,} real ones.")
    print("  The team total is scored elsewhere; this asks whether the runs")
    print("  land on the same NUMBER of hitters.\n")
    print(f"  {'quantity':<34}{'model':>9}{'actual':>9}{'diff':>9}")

    def _row(lbl, f):
        m = sum(1 for x in conc if f(x)) / len(conc)
        a = sum(1 for x in a_rows if f(x)) / len(a_rows)
        print(f"  {lbl:<34}{m:>9.3%}{a:>9.3%}{m - a:>+9.3%}")

    _row("a hitter drives in 2+", lambda x: x[1] >= 2)
    _row("a hitter drives in 3+", lambda x: x[1] >= 3)
    _row("a hitter drives in 4+", lambda x: x[1] >= 4)
    _row("a hitter scores 3+", lambda x: x[2] >= 3)
    _row("two hitters drive in 2+", lambda x: x[3] >= 2)
    print()
    print(f"  {'mean top RBI in a team-game':<34}"
          f"{st.mean(x[1] for x in conc):>9.3f}"
          f"{st.mean(x[1] for x in a_rows):>9.3f}"
          f"{st.mean(x[1] for x in conc) - st.mean(x[1] for x in a_rows):>+9.3f}")
    print(f"  {'mean team runs':<34}"
          f"{st.mean(x[0] for x in conc):>9.3f}"
          f"{st.mean(x[0] for x in a_rows):>9.3f}"
          f"{st.mean(x[0] for x in conc) - st.mean(x[0] for x in a_rows):>+9.3f}")
    # CONDITION ON THE TEAM TOTAL. Concentration and level are different
    # claims and the raw block above confounds them: a side that scores
    # more will have a bigger top line for that reason alone. Matched on
    # runs, the question is purely "given N runs, how many men drove them
    # in", which is what clustering is actually about.
    print(f"\n  GIVEN THE SAME TEAM TOTAL — the top hitter's rbi and runs")
    print(f"  {'team runs':>10}{'n model':>9}{'n act':>7}"
          f"{'top rbi m':>11}{'top rbi a':>11}{'diff':>8}"
          f"{'top r m':>10}{'top r a':>10}{'diff':>8}")
    for n in range(0, 10):
        mm = [x for x in conc if x[0] == n]
        aa = [x for x in a_rows if x[0] == n]
        if len(aa) < 25 or len(mm) < 25:
            continue
        tm, ta = st.mean(x[1] for x in mm), st.mean(x[1] for x in aa)
        # RUNS SCORED as well as rbi. An rbi depends on who happened to be
        # on base ahead of the hitter, so a gap in it can be a property of
        # the STAT rather than of the model; runs scored is the less
        # arbitrary of the two and the conclusion leans on it.
        rm, ra = st.mean(x[2] for x in mm), st.mean(x[2] for x in aa)
        print(f"  {n:>10}{len(mm):>9,}{len(aa):>7,}{tm:>11.3f}{ta:>11.3f}"
              f"{tm - ta:>+8.3f}{rm:>10.3f}{ra:>10.3f}{rm - ra:>+8.3f}")
    print("\n  READ THE SECOND LINE FIRST. If the model is short on team")
    print("  runs to begin with, it is short on big individual games for")
    print("  that reason alone and the first block says nothing about")
    print("  clustering. The claim needs the top-RBI gap to be LARGER in")
    print("  relative terms than the run gap.")


if __name__ == "__main__":
    main(sys.argv[1:])
