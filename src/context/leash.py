"""The per-pitcher LEASH, measured: how long is he actually left in?

WHAT THIS IS FOR. The simulator differentiates starts far less than reality
does. Measured over 3,600 real starts, the sd of our per-start predicted
outs is 0.57 against a model-free floor of 1.77 — a one-way ANOVA on the
ACTUAL outs grouped by pitcher, sampling noise removed, which is a LOWER
bound on the real start-to-start variation because opponent, park and rest
all vary inside a pitcher's own season too. We produce under a third of the
differentiation that provably exists.

WHY IT IS A LEASH AND NOT A RATE ERROR, which is the whole argument and the
reason this module exists at all. A pitcher's leave-one-out residual is:

    outs   +0.295*      k   +0.008      h   +0.063*
    bb     -0.086*      er  +0.012                      (* = |z| > 3)

His rates are estimated over his own season, so his per-batter performance
is right by construction — and the columns agree: strikeouts, walks, hits
and earned runs carry no stable per-pitcher residual. Only OUTS does. The
one thing outs depends on that the other four do not is the manager, so
what is missing is how long he is left in.

IT IS NOT THE BLOWUPS. `RESUME.md` recorded, from day six, that per-pitcher
leash variation is "mostly blowups, not real". Rebuilt from a 20% TRIMMED
mean of prior residuals the gain is identical (corr +0.354 against +0.354
for the plain mean), and from the prior MEDIAN it is +0.336. A statistic
that discards his worst starts predicts just as well, so it is a central
tendency, not a tail.

THE CLUB IS STILL DEAD — this is the sixth independent finding. Fitted in
the correct order (club first, pitcher against the remainder), a club
offset moves the out-of-sample correlation +0.090 -> +0.122 on its own and
makes things WORSE on top of the pitcher offset (+0.234 -> +0.227, MAE up).
`sim.USE_PATIENCE` stays False.

MEASURED, NOT TUNED. Two constants could have been searched here and
neither is. The shrinkage K is `within_var / between_var` read off the
ANOVA, which is the normal-normal posterior mean; it is recomputed from
whatever window `build()` is given rather than baked in. The conversion
from outs to log-odds is INTERPOLATED through a measured table
(`OUTS_PER_OFFSET`) rather than regressed onto a slope — the same table
fitted as a line is the mistake `RESUME.md` records under "do not fit
counted points".

OUT-OF-SAMPLE RESULT. Rates estimated before 2026-07-01, scored on the
1,125 starts after it, offsets from strictly prior starts only:

    prediction              spread    corr     MAE    RMSE
    base (shipped)            0.55   0.090   2.944   3.906
    + pitcher offset          0.86   0.234   2.850   3.808

    venv/bin/python -m src.context.leash [--build] [--before YYYY-MM-DD]
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import random
import statistics as st
import sys
from collections import defaultdict

from src.context import sim

_HERE = os.path.dirname(os.path.abspath(__file__))
PATH = _HERE + "/hook_leash.json"

#: MEASURED, not derived: mean simulated outs at each `Hook.team_offset`,
#: relative to zero, over 900 real starts x 60 draws
#: (`scratchpad/offset_map.py`). Negative offset = longer leash.
#:
#: The curve is not a line — at -2.0 it buys +3.00 outs where the local
#: slope would promise +3.36 — so it is inverted by INTERPOLATION. Fitting
#: a slope through measured points is the failure recorded in RESUME under
#: the advance-on-out hazard, where a least-squares line charged +0.724 at
#: one run against a counted +0.296.
#:
#: The outs SD across the same sweep runs 4.10 at -0.6 to 3.83 at +1.0
#: against 4.00 at zero, so this knob moves a start's LEVEL without
#: inflating its own spread. That is what differentiating starts is
#: supposed to look like; a mechanism that bought spread by widening every
#: start would show up here and would not be worth having.
OUTS_PER_OFFSET = (
    (-2.0, 3.00), (-1.5, 2.34), (-1.0, 1.60), (-0.6, 0.97), (-0.3, 0.50),
    (0.0, 0.00), (0.3, -0.51), (0.6, -1.00), (1.0, -1.66), (1.5, -2.53),
    (2.0, -3.30),
)

#: Do not extrapolate past the measured sweep, and do not hand any one
#: pitcher a leash the league does not contain. +/-2.0 is already +3.0/-3.3
#: outs, wider than the 1.77-out sd of the whole pitcher population.
OFFSET_CLAMP = 2.0

#: A pitcher needs this many prior starts before his own number is used at
#: all. Below it the shrinkage would do the right thing anyway; the floor
#: exists so a single disaster start cannot register as a leash.
#:
#: RAISED 3 -> 5 on 2026-08-26. At three, a callup with two bad outings and
#: one good one reads as a short leash — Cody Bolton [3, 7, 13], Kendry
#: Rojas [6, 7, 12, 12] — when what it actually is is no evidence. It costs
#: 22 arms and 2.5% of the starts (3,018 -> 2,943), and those arms were
#: contributing almost nothing at K=14.8 anyway. What it really buys is
#: keeping them out of `shrink_k`, where a handful of noisy three-start
#: means inflate the between-pitcher variance for everybody else.
MIN_PRIOR = 5

#: A LEASH IS A MEASUREMENT OF ARMS THAT WERE MEANT TO GO LONG.
#:
#: `calibrate.ROTATION_MIN_GS` asks "did he start five times", and an opener
#: who opened five times clears it. Nine of the eleven offsets that pinned
#: at the +/-2.0 clamp on the first two-sided rebuild were openers and bulk
#: relievers — Wandy Peralta with five "starts" in fifty-three appearances,
#: averaging three outs. Their offsets are not manager patience, they are a
#: ROLE wearing a leash's clothes, and because they also feed `shrink_k`
#: they were setting the shrinkage constant for every real starter too.
#:
#: THE GATE IS ON THE UPPER TAIL OF HIS OWN DISTRIBUTION, NOT THE MEAN, and
#: that is the whole point. This module measures how long a starter lasts.
#: Screening on mean outs — which is what `price.priceable` does, correctly,
#: for a different question — would SELECT ON THE DEPENDENT VARIABLE: it
#: removes exactly the arms that were sent out for six and got shelled in
#: the second, which are the observations carrying the signal. Tatsuya Imai
#: has a one-out start and Noah Schultz has a one-out start; both belong.
#:
#: Measured on this league, the two populations do not overlap at all:
#:
#:     openers, p75 outs            3  4  4  4  6  6  6  9  9   (max 10)
#:     shelled starters, p75 outs  14 15 15 15 16 16 18 18      (min 1)
#:
#: Any cut from 10 to 13 separates them with no errors either way. 12 sits
#: in the middle of the gap rather than on the edge of a population.
INTENT_MIN_P75_OUTS = 12

_INTENT_Q = """
select p.player_name nm, p.outs_recorded o
from mlb_pitching p join games g on g.game_id = p.game_id
where g.sport = 'mlb' and g.status = 'Final' and p.is_starter = 1 {where}
"""


def intended_starters(before=None, conn=None) -> set:
    """Pitchers a club sends out MEANING to get length from them.

    `before` bounds the evidence exactly as it bounds everything else here —
    a file built for a date must contain nothing from that date onward, and
    a role judged partly on the starts being scored would leak.
    """
    from src import db
    q = _INTENT_Q.format(where=f" and g.date < '{before}'" if before else "")

    def _run(c):
        out = {}
        for r in c.execute(q):
            out.setdefault(r["nm"], []).append(r["o"] or 0)
        return out
    if conn is not None:
        starts = _run(conn)
    else:
        with db.connect() as c:
            starts = _run(c)
    return intended_from_starts(starts)


def intended_from_starts(starts: dict) -> set:
    """{pitcher: [outs per start]} -> the ones meant to go long.

    Split out from the query so the RULE can be tested without a database,
    and because the rule is the part that is easy to get subtly wrong: it
    reads the 75th percentile of a pitcher's own starts, never the mean.
    """
    keep = set()
    for nm, outs in starts.items():
        if len(outs) < MIN_PRIOR:
            continue
        v = sorted(outs)
        if v[min(len(v) - 1, int(0.75 * len(v)))] >= INTENT_MIN_P75_OUTS:
            keep.add(nm)
    return keep


def offset_for(d_outs: float) -> float:
    """Log-odds offset that buys `d_outs` more outs. Inverted by interpolation.

    `d_outs` is how much LONGER than the model this pitcher is left in, so a
    positive value returns a NEGATIVE offset.
    """
    pts = sorted(((d, o) for o, d in OUTS_PER_OFFSET))
    if d_outs <= pts[0][0]:
        return max(-OFFSET_CLAMP, min(OFFSET_CLAMP, pts[0][1]))
    if d_outs >= pts[-1][0]:
        return max(-OFFSET_CLAMP, min(OFFSET_CLAMP, pts[-1][1]))
    for (d0, o0), (d1, o1) in zip(pts, pts[1:]):
        if d0 <= d_outs <= d1:
            if d1 == d0:
                return o0
            t = (d_outs - d0) / (d1 - d0)
            return max(-OFFSET_CLAMP, min(OFFSET_CLAMP, o0 + t * (o1 - o0)))
    return 0.0


def shrink_k(residuals_by_pitcher: dict) -> tuple[float, float, float]:
    """(K, between_sd, within_sd) from a one-way ANOVA on the residuals.

    K = within_var / between_var is the number of starts at which a
    pitcher's own record outweighs the league prior. It is the normal-normal
    posterior and it is READ OFF THE DATA — handing it to a grid search is
    what would turn this from a measurement into a fit, and a fitted
    shrinkage absorbs whatever else is wrong with the hook.

    The (MSB - MSW) / n0 estimator rather than the raw spread of pitcher
    means: with a dozen starts a pitcher's observed mean carries a full out
    of sampling noise, and the raw spread would report most of it as leash.
    """
    by = {p: v for p, v in residuals_by_pitcher.items() if len(v) >= 2}
    if len(by) < 3:
        return 4.0, 0.0, 0.0
    n = sum(len(v) for v in by.values())
    k = len(by)
    grand = sum(sum(v) for v in by.values()) / n
    ssb = sum(len(v) * (st.mean(v) - grand) ** 2 for v in by.values())
    ssw = sum(sum((x - st.mean(v)) ** 2 for x in v) for v in by.values())
    msb, msw = ssb / (k - 1), ssw / (n - k)
    n0 = (n - sum(len(v) ** 2 for v in by.values()) / n) / (k - 1)
    between = max((msb - msw) / n0, 0.0)
    within = max(msw, 1e-9)
    if between <= 0:
        return float("inf"), 0.0, within ** 0.5
    return within / between, between ** 0.5, within ** 0.5


_CASES = None
_PENS = None


def _sim_one(args):
    """Residuals for BOTH starters, off the same simulated games.

    Two-sided, because a one-sided simulation cannot see its own team's
    runs — so a starter left in because his club was up five looked
    identical to one on a genuinely long leash, and the offset absorbed
    both. `apply_leash=False` is the double-count guard: the residual has
    to be measured against the model WITHOUT this mechanism or a rebuild
    folds its own correction back in. Guarded by
    `check_leash_residuals_are_measured_against_the_bare_hook`.
    """
    gid, n_sims, seed = args
    from src.context import calibrate as cal
    pair = _CASES[gid]
    lg = sim.league()
    rng = random.Random(seed)
    draws = [cal.replay(pair, lg, _PENS, rng, apply_leash=False)
             for _ in range(n_sims)]
    out = []
    for idx, side in ((0, "away_sp"), (1, "home_sp")):
        s = pair[idx][0]
        outs = [getattr(d, side).outs for d in draws]
        out.append((s["player_name"], s["date"], s["team"],
                    s["o"] - st.mean(outs)))
    return out


def residuals(before=None, n_sims=120, season=None, quiet=False) -> dict:
    """{pitcher: [outs residual, ...]} over every replayable start.

    `before` bounds BOTH the starts and the rates, so a file built for a
    date contains nothing from that date onwards.
    """
    global _CASES, _PENS
    from src.context import calibrate as cal
    from src.context.sources import rates as rate_src
    _CASES = cal.paired_cases(season=season, before=before,
                              rates_before=before)
    _PENS = rate_src.bullpens(sim.league(), before=before)
    if not quiet:
        print(f"  simulating {len(_CASES)} games "
              f"({len(_CASES) * 2} starts) x {n_sims} draws", flush=True)
    args = [(g, n_sims, 0) for g in _CASES]
    # fork, never spawn: a spawned worker re-imports at DEFAULT globals and
    # every flag this measurement depends on silently reverts.
    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, (os.cpu_count() or 4) - 2)) as pool:
        rows = pool.map(_sim_one, args, chunksize=16)
    out = defaultdict(list)
    for pairrows in rows:
        for name, _date, _team, resid in pairrows:
            out[name].append(resid)
    return dict(out)


def build(before=None, n_sims=120, path=PATH, season=None) -> dict:
    """Measure, shrink, convert to log-odds, persist. Returns the mapping."""
    res = residuals(before=before, n_sims=n_sims, season=season)
    # Openers leave BEFORE `shrink_k`, not after. They are systematically
    # short, so leaving them in inflates the between-pitcher variance and
    # drives K down — which loosens the shrinkage applied to every genuine
    # starter. Filtering only the output would fix their own rows and leave
    # everybody else's wrong.
    keep = intended_starters(before=before)
    dropped = [n for n in res if n not in keep]
    res = {n: v for n, v in res.items() if n in keep}
    if dropped:
        print(f"  dropped {len(dropped)} arms not sent out for length "
              f"(p75 outs < {INTENT_MIN_P75_OUTS}): "
              f"{', '.join(sorted(dropped)[:5])}"
              f"{' ...' if len(dropped) > 5 else ''}")
    k, between, within = shrink_k(res)
    offsets = {}
    for name, vals in res.items():
        n = len(vals)
        if n < MIN_PRIOR:
            continue
        # 20% trimmed mean, which measured identically to the plain mean
        # (corr +0.354 both) and is what refutes the "it is just blowups"
        # reading rather than merely asserting against it.
        s = sorted(vals)
        cut = n // 5
        core = s[cut:n - cut] or s
        shrunk = st.mean(core) * n / (n + k)
        off = offset_for(shrunk)
        if off:
            offsets[name] = round(off, 4)
    meta = {"_meta": {"before": before, "k": round(k, 3),
                      "between_sd": round(between, 3),
                      "within_sd": round(within, 3),
                      "pitchers": len(offsets),
                      "starts": sum(len(v) for v in res.values())}}
    with open(path, "w") as f:
        json.dump({**meta, **offsets}, f, indent=1, sort_keys=True)
    print(f"  K={k:.1f} starts (between {between:.2f}, within {within:.2f})")
    print(f"  wrote {len(offsets)} offsets to {path}")
    if offsets:
        ranked = sorted(offsets.items(), key=lambda kv: kv[1])
        print("\n  LONGEST LEASH (negative offset)")
        for nm, o in ranked[:8]:
            print(f"    {nm:<26}{o:>+8.3f}   {_d_outs(o):>+5.2f} outs")
        print("  SHORTEST LEASH")
        for nm, o in ranked[-8:]:
            print(f"    {nm:<26}{o:>+8.3f}   {_d_outs(o):>+5.2f} outs")
    return offsets


def _d_outs(offset: float) -> float:
    """Outs bought by an offset — the forward direction of `offset_for`."""
    pts = sorted(OUTS_PER_OFFSET)
    if offset <= pts[0][0]:
        return pts[0][1]
    if offset >= pts[-1][0]:
        return pts[-1][1]
    for (o0, d0), (o1, d1) in zip(pts, pts[1:]):
        if o0 <= offset <= o1:
            t = 0.0 if o1 == o0 else (offset - o0) / (o1 - o0)
            return d0 + t * (d1 - d0)
    return 0.0


def main() -> None:
    args = sys.argv[1:]
    before = None
    if "--before" in args:
        before = args[args.index("--before") + 1]
    if "--build" in args:
        build(before=before)
        return
    try:
        with open(PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        print("  no hook_leash.json — run with --build")
        return
    meta = data.get("_meta", {})
    offs = {k: v for k, v in data.items() if k != "_meta"}
    print(f"  {len(offs)} pitchers, built before {meta.get('before')}")
    print(f"  K={meta.get('k')} between {meta.get('between_sd')} "
          f"within {meta.get('within_sd')}")
    if offs:
        vals = list(offs.values())
        print(f"  offsets: sd {st.pstdev(vals):.3f}, range "
              f"{min(vals):+.2f} to {max(vals):+.2f}")
        print(f"  implied outs spread: "
              f"{st.pstdev([_d_outs(v) for v in vals]):.2f}")


if __name__ == "__main__":
    main()
