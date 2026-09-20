"""PER-PITCHER PITCH EFFICIENCY — how many pitches HE needs, TODO 34.

    venv/bin/python -m src.context.efficiency [--build] [--before DATE]

THE HOLE THIS FILLS, and `sim.PITCH_COST`'s own docstring already named it:
"What remains wrong is per-start ACCURACY (residual sd 8.2), and that is a
per-pitcher efficiency term, not noise."

`PITCH_COST` is a LEAGUE table keyed on the OUTCOME alone — every starter in
baseball is billed 4.85 pitches for a strikeout and 3.37 for an out. So the
engine differentiates arms only through their outcome MIX: a strikeout
pitcher burns more pitches because he records more strikeouts. It has no way
to know that Eury Pérez needs 4.30 pitches a batter and Ross Stripling needs
3.26.

WHY THAT MATTERS MORE THAN IT LOOKS. The hook integrates over pitch count, so
an arm billed 4% too many pitches arrives at every removal decision early and
is pulled early — his rates are right, his length is wrong. It is the same
shape of defect as the leash, entering one step UPSTREAM: not "the manager
treats him differently" but "he gets to 95 pitches at a different point in
the game".

AND IT IS NOT THE LEASH WEARING A DIFFERENT HAT, measured (TODO 32): the
per-arm OUTS residual correlates +0.137 with his pitches per batter, which is
larger than the decision-fitted hook offsets managed (+0.015) on the same
arms. NOTE THE OVERLAP HONESTLY THOUGH: `sim.leash` is fitted on the outs
residual, so it is ALREADY correcting part of this by the wrong mechanism —
an efficient arm goes deeper than the model says, and the leash hands him a
longer leash for it. So this must be scored ON TOP of the leash, which is how
the engine ships, and not against a leash-off baseline.

OBSERVED OVER EXPECTED, NEVER OBSERVED OVER LEAGUE. The multiplier is his
actual pitches divided by what `PITCH_COST` would charge for HIS OWN outcome
mix. That is what makes it new information rather than a restatement of his
strikeout rate: raw pitches per batter correlates +0.560 with K rate, so a
raw ratio would hand the engine back something it already has and
double-count it. Scored this way, K explains none of what is left. It is the
same convention `AIR_HR_PIT` follows, for the same reason.

    the multiplier, 743 arm-seasons (>= 200 batters faced, >= 10 starts)
      mean 0.9775   sd 0.0332   p10 0.932   p90 1.018
      year over year r +0.413 (369 arm-pairs, se 0.052)
      stable sd 0.0217  ->  about 0.35 outs at a 90-pitch hook

TWO THINGS ARE MEASURED AND NEITHER IS SEARCHED.

  1. THE CARRY. Every multiplier is multiplied by the year-over-year
     reliability above, because shrinking for sampling noise alone leaves a
     term that describes an arm's PAST and over-corrects his future. That is
     the exact mistake TODO 32 made and fixed; it is cheap to not repeat.
  2. THE CENTRING. The raw multipliers average 0.9775, not 1.0 — the
     expectation here is built from `PITCH_COST` and that table over-bills by
     a couple of percent (its own docstring records 2.6%). Shipping raw
     numbers would hand every pitcher in the league ~2% more pitch budget and
     lengthen every start, which is a LEVEL change competing with a
     calibrated 86.8-pitches-a-start. So the table is divided by its own
     batters-faced-weighted mean and the applied mean is exactly 1.0. The
     LEVEL stays with `PITCH_COST`; this only redistributes.

FOLD DISCIPLINE. `--before` bounds the evidence and defaults to `HOLDOUT`.
A completed prior season is a legitimate input; a season-to-date row pulled
after the cut knows the future.
"""
from __future__ import annotations

import json
import math
import os
import statistics as st
import sys

from src.context.holdout import HOLDOUT

_HERE = os.path.dirname(os.path.abspath(__file__))
PATH = _HERE + "/pitch_eff.json"

#: Batters faced before an arm is written at all. The shrinkage handles
#: thinness smoothly, so this is only a floor against degenerate rows (a
#: two-inning cameo whose pitch count was mis-scraped).
MIN_BF = 150

#: Nobody is handed an efficiency the league does not contain. p10/p90 are
#: 0.932/1.018 on a mean of 0.978, so +/-12% is far outside the observed
#: spread and this is a guard, not a parameter. `build` prints how many arms
#: it binds on.
EFF_CLAMP = 0.12

#: MEASURED year-over-year reliability of the multiplier, on 369 arm-pairs
#: of >= 200 batters faced (se 0.052). Not a tuned shrinkage: it is the
#: share of a real per-arm efficiency that is still true next season, and it
#: multiplies every offset for the reason the module docstring gives.
#:
#: Recomputed by `--build`, which prints what it measured and uses that
#: rather than this constant; the constant is here so the shipped number is
#: readable without a rebuild.
CARRY = 0.413

#: Batters faced an arm-season needs to enter the CARRY estimate and the
#: variance that carry scales. One number for both, because they are a ratio
#: and a ratio across two populations is meaningless.
CARRY_MIN_BF = 200

_Q = """select p.player_name nm, count(*) gs,
               sum(p.pitches) pt, sum(p.k) k, sum(p.bb) bb,
               sum(coalesce(p.hbp,0)) hbp, sum(p.hr) hr, sum(p.h) h,
               sum(p.outs_recorded) o, substr(g.date,1,4) yr
        from mlb_pitching p join games g on g.game_id = p.game_id
        where g.sport='mlb' and g.status='Final'
          and p.pitches is not null and p.outs_recorded is not null {w}
        group by p.player_name, substr(g.date,1,4)"""


def _expected(r: dict) -> tuple[float, int]:
    """(pitches `PITCH_COST` would charge for his mix, batters faced).

    The boxscore does not split singles from doubles from triples, and it
    does not have to: `PITCH_COST` charges 3.35 / 3.33 / 3.36 for the three,
    so one ball-in-play charge covers them to within a hundredth of a pitch.
    K, BB, HBP and HR are the four that differ materially and all four are
    in the table.
    """
    from src.context import sim
    c = sim.PITCH_COST
    bf = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0) + (r["hbp"] or 0)
    rest = max(bf - (r["k"] or 0) - (r["bb"] or 0) - (r["hbp"] or 0)
               - (r["hr"] or 0), 0)
    exp = (c[sim.K] * (r["k"] or 0) + c[sim.BB] * (r["bb"] or 0)
           + c[sim.HBP] * (r["hbp"] or 0) + c[sim.HR] * (r["hr"] or 0)
           + c[sim.OUT] * rest)
    return exp, bf


def rows(before: str | None = None, starters_only: bool = True) -> list[dict]:
    from src import db
    w = " and p.is_starter = 1" if starters_only else ""
    if before:
        w += f" and g.date < '{before}'"
    with db.connect() as c:
        return [dict(r) for r in c.execute(_Q.format(w=w))]


def carry_of(cells: dict, min_bf: int = CARRY_MIN_BF) -> tuple[float, int]:
    """Year-over-year reliability of the multiplier. See CARRY."""
    per = {k: v[0] for k, v in cells.items() if v[1] >= min_bf}
    pairs = [(per[(nm, y)], per[(nm, str(int(y) + 1))])
             for (nm, y) in per if (nm, str(int(y) + 1)) in per]
    if len(pairs) < 25:
        return 0.0, len(pairs)
    mx = sum(a for a, _ in pairs) / len(pairs)
    my = sum(b for _, b in pairs) / len(pairs)
    num = sum((a - mx) * (b - my) for a, b in pairs)
    dx = sum((a - mx) ** 2 for a, _ in pairs) ** 0.5
    dy = sum((b - my) ** 2 for _, b in pairs) ** 0.5
    r = num / (dx * dy) if dx and dy else 0.0
    return max(0.0, min(1.0, r)), len(pairs)


def centre(shrunk: dict) -> tuple[dict, float, int]:
    """{nm: (mult, bf)} -> ({nm: centred mult}, the mean removed, clamped).

    EXTRACTED FROM `build` SO IT CAN BE TESTED AT ALL, and that is not a
    cosmetic refactor: the first version of this lived inline and the check
    that claimed to guard it SURVIVED a mutation which deleted the centring
    entirely. It passed because the shipped table's applied mean happened to
    be 1.002, so dividing by it or not moved every value by 0.2% and the
    assertion's tolerance was 1%. A test that cannot fail is worse than no
    test, because it reads as coverage.

    WEIGHTED BY BATTERS FACED — the population the multiplier fires in, not
    the arms it is keyed on. An arm who threw 900 batters' worth carries six
    times the weight of one who threw 150, because that is how much of the
    league's pitch budget he actually accounts for. Centring on the
    UNWEIGHTED mean leaves a level shift behind whenever the two differ,
    which is exactly how `AIR_HR_PIT`'s falsifier fired.
    """
    tot = sum(v[1] for v in shrunk.values()) or 1
    applied = sum(v[0] * v[1] for v in shrunk.values()) / tot
    out, clamped = {}, 0
    lo, hi = 1.0 - EFF_CLAMP, 1.0 + EFF_CLAMP
    for nm, (m, _bf) in shrunk.items():
        c = m / applied if applied else m
        if not (lo <= c <= hi):
            clamped += 1
            c = max(lo, min(hi, c))
        out[nm] = round(c, 5)
    return out, applied, clamped


def build(before: str | None = HOLDOUT, path: str = PATH,
          verbose: bool = True) -> dict:
    """Measure, shrink, centre, persist. Returns {name: multiplier}."""
    raw = rows(before=before)
    cells: dict = {}
    for r in raw:
        exp, bf = _expected(r)
        if exp > 0 and bf > 0:
            cells[(r["nm"], r["yr"])] = (r["pt"] / exp, bf)
    carry, pairs = carry_of(cells)
    if verbose:
        print(f"  {len(cells)} arm-seasons before {before}")
        print(f"  measured carry r {carry:+.3f} over {pairs} arm-pairs")
    if carry <= 0:
        raise ValueError(
            "the year-over-year carry is not estimable on this window, and "
            "it is what keeps this term from over-correcting. Widen the "
            "window; do NOT default it to 1.0 (see TODO 32)")

    # Per ARM, pooled across the seasons inside the window.
    by: dict = {}
    for (nm, _yr), (mult, bf) in cells.items():
        tot_p, tot_e = by.setdefault(nm, [0.0, 0.0])
        # Reconstruct totals so pooling is weighted by work, not by season.
        by[nm] = [tot_p + mult * bf, tot_e + bf]
    pooled = {nm: (v[0] / v[1], v[1])
              for nm, v in by.items() if v[1] >= MIN_BF}

    # SHRINKAGE — ONE COEFFICIENT, AND APPLYING TWO IS THE TRAP HERE.
    #
    # The obvious chain is "shrink for sampling noise, then multiply by the
    # carry". It is WRONG and it halved the first build of this table: the
    # carry is measured as a correlation between two SEASON estimates, and
    # those are themselves noisy, so that correlation ALREADY contains the
    # sampling-noise attenuation. Multiplying by an empirical-Bayes weight on
    # top charges for the same noise twice (it shipped sd 0.0090 against a
    # stable signal of 0.0217).
    #
    # The right quantity: the covariance between an arm's two seasons IS the
    # stable signal variance, because the noise in one season is independent
    # of the noise in the other. So
    #
    #     var_stable = carry * var(season estimates)
    #     weight_i   = var_stable / (var_stable + his own sampling variance)
    #
    # and nothing is multiplied twice. A well-sampled arm's shipped deviation
    # then approaches the stable signal rather than a fraction of it, which
    # is the behaviour to sanity-check in the printout below.
    ms = [v[0] for v in pooled.values()]
    grand = st.fmean(ms)
    # ON THE SAME POPULATION THE CARRY WAS MEASURED ON (rule 10, name the
    # denominator). Taking this variance over EVERY arm-season — twenty-batter
    # cameos included — inflated it 4x (sd 0.130 against 0.033), which made
    # `var_stable` larger than any arm's sampling variance and switched the
    # shrinkage off for the whole table. The carry and the variance it scales
    # have to come from the same rows or their ratio means nothing.
    season_ms = [v[0] for v in cells.values() if v[1] >= CARRY_MIN_BF]
    season_var = st.variance(season_ms) if len(season_ms) > 2 else 0.0
    var_stable = carry * season_var
    # A single plate appearance's pitch count carries sd ~1.6 against a mean
    # of ~3.8, so the multiplier's sampling variance is (1.6/3.8)^2 / bf.
    per_pa = (1.6 / 3.8) ** 2
    if verbose:
        print(f"  {len(pooled)} arms >= {MIN_BF} batters faced   "
              f"raw mean {grand:.4f}  pooled sd "
              f"{(st.variance(ms) if len(ms) > 2 else 0) ** 0.5:.4f}")
        print(f"  season sd {season_var ** 0.5:.4f}  -> STABLE signal sd "
              f"{var_stable ** 0.5:.4f} (= sqrt(carry x season var))")

    shrunk: dict = {}
    for nm, (m, bf) in pooled.items():
        v = per_pa / bf
        w = (var_stable / (var_stable + v)) if (var_stable + v) > 0 else 0.0
        shrunk[nm] = (1.0 + w * (m - grand), bf)

    # CENTRING, weighted by batters faced — the population the multiplier
    # fires in. `AIR_HR_PIT`'s falsifier fired on exactly this: a table that
    # only redistributes moved a LEVEL row because it was centred over the
    # counting sample instead.
    out, applied, clamped = centre(shrunk)
    data = {"_meta": {"before": before, "carry": round(carry, 4),
                      "pairs": pairs, "arms": len(out),
                      "applied_mean_removed": round(applied, 5),
                      "clamped": clamped}, "mult": out}
    with open(path, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    if verbose:
        vals = sorted(out.values())
        sd = math.sqrt(sum((v - 1) ** 2 for v in vals) / len(vals))
        print(f"  wrote {len(out)} multipliers, sd {sd:.4f}, "
              f"range {vals[0]:.3f} to {vals[-1]:.3f}, clamped {clamped}")
        print(f"  level removed {applied:.5f} (applied mean is now 1.0)")
        ranked = sorted(out.items(), key=lambda kv: kv[1])
        print("\n  FASTEST WORKERS (fewest pitches for the same outcomes)")
        for nm, v in ranked[:6]:
            print(f"    {nm:<26}{v:.4f}")
        print("  SLOWEST")
        for nm, v in ranked[-6:]:
            print(f"    {nm:<26}{v:.4f}")
    return out


def main() -> None:
    args = sys.argv[1:]
    before = (args[args.index("--before") + 1]
              if "--before" in args else HOLDOUT)
    if "--build" in args:
        build(before=before)
        return
    try:
        with open(PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        print("  no pitch_eff.json — run with --build")
        return
    m = data.get("_meta", {})
    mult = data.get("mult") or {}
    print(f"  {len(mult)} arms, built before {m.get('before')}, "
          f"carry {m.get('carry')} over {m.get('pairs')} pairs")
    if mult:
        vals = sorted(mult.values())
        sd = math.sqrt(sum((v - 1) ** 2 for v in vals) / len(vals))
        print(f"  sd {sd:.4f}  range {vals[0]:.3f} to {vals[-1]:.3f}  "
              f"clamped {m.get('clamped')}")


if __name__ == "__main__":
    main()
