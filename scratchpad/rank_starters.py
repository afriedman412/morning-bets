"""Can a pitcher's STATS predict how long he lasts, better than his own
past length does?

    venv/bin/python -m scratchpad.rank_starters [holdout-date]

WHY. Our outs numbers barely beat "the same number for every pitcher"
(+1.3% over base with a clean leash). The between-start signal is there —
the real spread of per-pitcher mean outs is 1.39 and we produce 0.89 — so we
under-differentiate. The leash is the one mechanism that differentiates, and
it works by MEASURING a pitcher's own outs residual, which needs a long
record: `MIN_PRIOR` is 5 starts and it is really wanting 15. A rookie gets
nothing.

USER'S POINT, and it is the right one: rank on what a pitcher actually does,
not on what his club calls him. A number three on a good staff can be better
than another club's ace. Note the RATES already work this way — the
simulator reads each man's own K%, BB%, HR% and BABIP, never a rotation
slot. Rotation slot appears only as an eligibility FILTER
(`calibrate.ROTATION_MIN_GS`, and the opener gate in `leash.py`).

SO THE OPEN QUESTION IS NARROW: does a stat line predict LENGTH? If it does,
a rookie with three starts can be given a leash from his rates instead of
waiting fifteen starts for his outs to stabilise.

WHAT IS COMPARED, all measured BEFORE the holdout and scored on starts after
it, so nothing sees its own answer:

    prior outs/start   what the leash uses today
    K-BB%              the user's proposal, the standard quality rank
    K%, BB% alone      which half of it carries any signal
    prior pitches/start efficiency rather than quality

against each pitcher's ACTUAL mean outs in the holdout. Correlation across
pitchers is the whole answer: a predictor that does not rank starters cannot
differentiate starts.

NO SIMULATION HERE ON PURPOSE. This asks whether the SIGNAL exists in the
data at all. If it does not, no amount of wiring it into the hook helps, and
that is the cheap thing to know first (`scratchpad/leverage.py`, same idea).
"""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict

from src.context import calibrate as cal

HOLDOUT = "2026-07-01"

#: A pitcher needs enough starts on each side for his mean to mean anything.
MIN_PRIOR = 5
MIN_POST = 5


def corr(xs, ys) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if not sx or not sy:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (n * sx * sy)


def gather(**kw) -> dict:
    """{player: [start rows]} for one window."""
    by = defaultdict(list)
    for s, p, l in cal.build_cases(**kw):
        by[s["player_name"]].append((s, p))
    return by


def main(argv):
    cut = argv[0] if argv else HOLDOUT
    prior = gather(before=cut)
    post = gather(since=cut, rates_before=cut)

    rows = []
    for name, after in post.items():
        before = prior.get(name, [])
        if len(before) < MIN_PRIOR or len(after) < MIN_POST:
            continue
        bf = sum(s["o"] + s["h"] + s["bb"] for s, _ in before)
        if not bf:
            continue
        k = sum(s["k"] for s, _ in before)
        bb = sum(s["bb"] for s, _ in before)
        rows.append({
            "name": name,
            "n_before": len(before),
            "n_after": len(after),
            "prior_outs": st.mean(s["o"] for s, _ in before),
            "k_pct": k / bf,
            "bb_pct": bb / bf,
            "kbb": (k - bb) / bf,
            "actual": st.mean(s["o"] for s, _ in after),
        })

    if len(rows) < 10:
        print(f"  only {len(rows)} pitchers clear the gates — nothing to say")
        return

    act = [r["actual"] for r in rows]
    print(f"\n  {len(rows)} starters, >={MIN_PRIOR} starts before {cut} and "
          f">={MIN_POST} after")
    print(f"  actual mean outs after: {st.mean(act):.2f}, "
          f"spread across pitchers {st.pstdev(act):.2f}")
    print(f"\n  {'predictor (all measured BEFORE the cut)':<40}{'corr':>8}")
    for label, key in (("prior outs per start  [the leash today]",
                        "prior_outs"),
                       ("K-BB%                 [the proposal]", "kbb"),
                       ("K% alone", "k_pct"),
                       ("BB% alone", "bb_pct")):
        print(f"  {label:<40}{corr([r[key] for r in rows], act):>+8.3f}")

    # Does the stat line say anything the record of his own length does not?
    # If K-BB% only ranks starters the way prior outs already does, it adds
    # nothing for a pitcher who HAS a record — its whole value would be
    # covering the ones who do not.
    print(f"\n  K-BB% against prior outs, across pitchers: "
          f"{corr([r['kbb'] for r in rows], [r['prior_outs'] for r in rows]):+.3f}")

    # THE DECIDING NUMBER. Correlations one at a time cannot answer whether
    # the stat line ADDS anything: if K-BB% only re-ranks starters the way
    # prior outs already does, combining them gains nothing. Ordinary least
    # squares on standardised predictors, scored by multiple R.
    def multi(keys):
        cols = []
        for k in keys:
            v = [r[k] for r in rows]
            m, s = st.mean(v), st.pstdev(v)
            cols.append([(x - m) / s if s else 0.0 for x in v])
        ym, ys = st.mean(act), st.pstdev(act)
        y = [(a - ym) / ys for a in act]
        # Normal equations, tiny system, solved by Gaussian elimination.
        p = len(cols)
        A = [[sum(cols[i][t] * cols[j][t] for t in range(len(y)))
              for j in range(p)] + [sum(cols[i][t] * y[t]
                                        for t in range(len(y)))]
             for i in range(p)]
        for i in range(p):
            piv = max(range(i, p), key=lambda r_: abs(A[r_][i]))
            A[i], A[piv] = A[piv], A[i]
            if abs(A[i][i]) < 1e-12:
                continue
            for j in range(i + 1, p):
                f = A[j][i] / A[i][i]
                for c in range(i, p + 1):
                    A[j][c] -= f * A[i][c]
        b = [0.0] * p
        for i in range(p - 1, -1, -1):
            if abs(A[i][i]) < 1e-12:
                continue
            b[i] = (A[i][p] - sum(A[i][j] * b[j]
                                  for j in range(i + 1, p))) / A[i][i]
        fit = [sum(b[i] * cols[i][t] for i in range(p))
               for t in range(len(y))]
        return corr(fit, y), b

    print(f"\n  COMBINED — does the stat line add to his own record?")
    print(f"  {'model':<40}{'R':>8}   weights")
    for keys in (("prior_outs",), ("kbb",), ("prior_outs", "kbb"),
                 ("prior_outs", "k_pct", "bb_pct")):
        R, b = multi(list(keys))
        print(f"  {' + '.join(keys):<40}{R:>+8.3f}   "
              + "  ".join(f"{k} {w:+.2f}" for k, w in zip(keys, b)))

    # AND WHERE IT SHOULD PAY MOST: the pitcher without a record. Split on
    # how many prior starts he has — if the stat line is worth anything, it
    # is worth it for the callup, not for the man with twenty starts.
    print(f"\n  BY LENGTH OF RECORD")
    print(f"  {'prior starts':<16}{'n':>5}{'prior outs':>12}{'K-BB%':>9}")
    thin = [r for r in rows if r["n_before"] <= 8]
    thick = [r for r in rows if r["n_before"] >= 12]
    for lbl, grp in (("<= 8", thin), (">= 12", thick)):
        if len(grp) < 8:
            print(f"  {lbl:<16}{len(grp):>5}   too few to read")
            continue
        a = [r["actual"] for r in grp]
        print(f"  {lbl:<16}{len(grp):>5}"
              f"{corr([r['prior_outs'] for r in grp], a):>+12.3f}"
              f"{corr([r['kbb'] for r in grp], a):>+9.3f}")

    print(f"\n  TOP AND BOTTOM BY K-BB%, and how deep they actually went")
    print(f"  {'pitcher':<24}{'K-BB%':>8}{'prior':>8}{'actual':>8}{'n':>5}")
    ranked = sorted(rows, key=lambda r: -r["kbb"])
    for r in ranked[:6] + [None] + ranked[-6:]:
        if r is None:
            print(f"  {'...':<24}")
            continue
        print(f"  {r['name'][:23]:<24}{r['kbb']:>8.3f}{r['prior_outs']:>8.1f}"
              f"{r['actual']:>8.1f}{r['n_after']:>5}")


if __name__ == "__main__":
    main(sys.argv[1:])
