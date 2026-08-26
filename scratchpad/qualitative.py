"""Does anything OUTSIDE the stat line predict how long a starter goes?

    venv/bin/python -m scratchpad.qualitative [holdout-date]

WHY THIS AND NOT `rank_starters.py`. That one ranked starters on K-BB% and
found it adds +0.009 over their own innings history. The reason is circular
and the user named it: K% and BB% are the SAME numbers the simulator already
consumes to generate outcomes, so ranking on them tells the model nothing it
does not already know.

What is wanted is qualitative — the things that decide how long a manager
leaves a man out there and that a box score cannot see:

    prior-season innings   a pitcher who threw 90 last year is not going 200
                           this year, and by August his club is shortening
                           him however well he is throwing
    budget pressure        season-to-date innings as a share of last year's
                           total. Past 1.0 the club is in new territory for
                           him and the leash gets shorter.
    rookie                 no prior MLB season at all
    age                    standing. A 40-year-old gets the 7th that a
                           swingman with identical stuff does not — sign
                           unknown in advance, which is why it is measured

ALL OF THESE ARE INDEPENDENT OF K%, BB%, HR% AND BABIP by construction.
None is derivable from this season's rate line.

SCORED AS AN ADDITION TO HIS OWN RECORD, never on its own. `prior outs per
start` is the incumbent — it is what the leash uses — and the only question
that matters is whether a qualitative field adds to it. That is the same
residual discipline `calibrate.fit_patience` uses: a club whose starters go
deep may just have good starters.

Everything is measured strictly BEFORE the cut and scored on starts after.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import statistics as st
import sys
from collections import defaultdict

from src.context import calibrate as cal
from src.context.sources import statsapi as sa

HOLDOUT = "2026-07-01"
MIN_PRIOR = 5
MIN_POST = 5
SEASON = 2026


def corr(xs, ys) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if not sx or not sy:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (n * sx * sy)


def multi(rows, keys, target):
    """Standardised OLS; returns multiple R."""
    cols = []
    for k in keys:
        v = [r[k] for r in rows]
        m, s = st.mean(v), st.pstdev(v)
        cols.append([(x - m) / s if s else 0.0 for x in v])
    y = [r[target] for r in rows]
    ym, ys = st.mean(y), st.pstdev(y)
    y = [(a - ym) / ys if ys else 0.0 for a in y]
    p = len(cols)
    A = [[sum(cols[i][t] * cols[j][t] for t in range(len(y)))
          for j in range(p)] + [sum(cols[i][t] * y[t] for t in range(len(y)))]
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
    fit = [sum(b[i] * cols[i][t] for i in range(p)) for t in range(len(y))]
    return corr(fit, y), b


def _ip(v) -> float:
    """MLB innings are '187.2' meaning 187 and two thirds. Not a decimal."""
    if v is None:
        return 0.0
    s = str(v)
    if "." not in s:
        return float(s)
    whole, frac = s.split(".")
    return float(whole) + float(frac) / 3.0


def player_index() -> dict:
    d = sa._cached(f"players_{SEASON}", f"/sports/1/players?season={SEASON}")
    out = {}
    for p in d.get("people", []):
        out[p.get("fullName")] = p
    return out


def year_by_year(pid: int) -> dict:
    d = sa._cached(f"yby_{pid}",
                   f"/people/{pid}/stats?stats=yearByYear&group=pitching")
    out = {}
    for s in d.get("stats", []):
        for sp in s.get("splits", []):
            season = int(sp.get("season", 0))
            stat = sp.get("stat", {})
            out[season] = {"ip": _ip(stat.get("inningsPitched")),
                           "gs": stat.get("gamesStarted") or 0}
    return out


def main(argv):
    cut = argv[0] if argv else HOLDOUT
    cut_d = dt.date.fromisoformat(cut)

    prior, post = defaultdict(list), defaultdict(list)
    for s, p, l in cal.build_cases(before=cut):
        prior[s["player_name"]].append(s)
    for s, p, l in cal.build_cases(since=cut, rates_before=cut):
        post[s["player_name"]].append(s)

    names = [n for n in post
             if len(prior.get(n, [])) >= MIN_PRIOR and len(post[n]) >= MIN_POST]
    print(f"  {len(names)} starters clear the gates; pulling career lines ...",
          flush=True)

    idx = player_index()
    ids = {n: idx[n]["id"] for n in names if n in idx}
    print(f"  matched {len(ids)}/{len(names)} to MLB ids", flush=True)

    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        yby = dict(zip(ids, pool.map(year_by_year, ids.values())))

    rows = []
    for n, pid in ids.items():
        y = yby.get(n) or {}
        last = y.get(SEASON - 1, {}).get("ip", 0.0)
        # Season-to-date innings BEFORE the cut, from our own start rows —
        # the API's season total would include the holdout and leak.
        std = sum(s["o"] for s in prior[n]) / 3.0
        bio = idx[n]
        born = bio.get("birthDate")
        age = ((cut_d - dt.date.fromisoformat(born)).days / 365.25
               if born else 28.0)
        debut = bio.get("mlbDebutDate")
        rows.append({
            "name": n,
            "n_before": len(prior[n]),
            "prior_outs": st.mean(s["o"] for s in prior[n]),
            "prior_ip": last,
            # Past 1.0 he is in new territory for his own arm.
            "budget": std / last if last >= 20 else 2.5,
            # SPLIT, because the first cut of this lumped Gerrit Cole and
            # Shane McClanahan in with the callups: all three threw zero
            # innings last season and only one kind of them is a rookie.
            # A club shortens both, but for opposite reasons and on
            # different schedules, so they cannot share a coefficient.
            "rookie": 1.0 if (debut or "9999")[:4] >= str(SEASON - 1) else 0.0,
            "hurt_vet": (1.0 if last < 20
                         and (debut or "9999")[:4] < str(SEASON - 1) else 0.0),
            "age": age,
            "debut": debut,
            "actual": st.mean(s["o"] for s in post[n]),
        })

    act = [r["actual"] for r in rows]
    print(f"\n  {len(rows)} starters, cut {cut}")
    print(f"  actual mean outs after {st.mean(act):.2f}, "
          f"spread across pitchers {st.pstdev(act):.2f}")

    print(f"\n  ON ITS OWN                                  corr")
    for label, key in (("prior outs per start   [incumbent]", "prior_outs"),
                       ("last season's innings", "prior_ip"),
                       ("budget pressure (STD ip / last yr)", "budget"),
                       ("rookie (debuted this year or last)", "rookie"),
                       ("veteran who missed last season", "hurt_vet"),
                       ("age", "age")):
        print(f"  {label:<42}{corr([r[key] for r in rows], act):>+8.3f}")

    print(f"\n  ADDED TO HIS OWN RECORD — the only test that counts")
    base, _ = multi(rows, ["prior_outs"], "actual")
    print(f"  {'prior outs alone':<42}{base:>+8.3f}")
    for extra in ("prior_ip", "budget", "rookie", "hurt_vet", "age"):
        R, b = multi(rows, ["prior_outs", extra], "actual")
        print(f"  {'+ ' + extra:<42}{R:>+8.3f}   ({R - base:+.3f})")
    R, b = multi(rows, ["prior_outs", "prior_ip", "budget", "rookie",
                        "hurt_vet", "age"], "actual")
    print(f"  {'+ all of them':<42}{R:>+8.3f}   ({R - base:+.3f})")

    # WHERE IT SHOULD PAY: the man without an in-season record. If a club's
    # handling of him is already visible in how deep he has been going, then
    # prior outs absorbs everything and these fields are redundant BY
    # CONSTRUCTION. The only place that argument fails is a short record.
    print(f"\n  THIN RECORD ONLY (<= 8 starts before the cut)")
    thin = [r for r in rows if r["n_before"] <= 8]
    if len(thin) >= 8:
        a = [r["actual"] for r in thin]
        print(f"  {'n':<42}{len(thin):>8}")
        for lbl, key in (("prior outs", "prior_outs"),
                         ("last season's innings", "prior_ip"),
                         ("rookie", "rookie")):
            print(f"  {lbl:<42}{corr([r[key] for r in thin], a):>+8.3f}")
        tb, _ = multi(thin, ["prior_outs"], "actual")
        tr, _ = multi(thin, ["prior_outs", "prior_ip", "rookie"], "actual")
        print(f"  {'prior outs -> + innings + rookie':<42}"
              f"{tb:>+8.3f} -> {tr:+.3f}")

    print(f"\n  THE ROOKIES AND THE LIGHTLY-WORKED, sorted by last year's IP")
    print(f"  {'pitcher':<24}{'lastyr IP':>10}{'budget':>8}{'prior':>7}"
          f"{'actual':>8}")
    for r in sorted(rows, key=lambda r: r["prior_ip"])[:12]:
        print(f"  {r['name'][:23]:<24}{r['prior_ip']:>10.1f}"
              f"{min(r['budget'], 9.99):>8.2f}{r['prior_outs']:>7.1f}"
              f"{r['actual']:>8.1f}")


if __name__ == "__main__":
    main(sys.argv[1:])
