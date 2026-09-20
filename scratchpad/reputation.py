"""Does REPUTATION explain how long a starter is left in, once you control
for how he actually pitched that night?

    venv/bin/python -m scratchpad.reputation [holdout-date]

WHY THE EARLIER TESTS WERE BADLY POSED. `rank_starters.py` and
`qualitative.py` both scored a candidate against a pitcher's PRIOR OUTS PER
START and found nothing added. The user identified the flaw: prior outs
conflates two different things.

    he went five because he was getting hit
    he went five because his leash is short

Only the second is a manager decision, and only the second is what a
reputation would drive. Burying them together guarantees a null, because
performance dominates the sum and every candidate has to beat it.

SO THE TARGET HERE IS THE RESIDUAL. For each starter, regress his actual
outs per start on how he ACTUALLY PITCHED in those same starts — strikeouts
minus walks, baserunners allowed, earned runs — and keep what is left over.
That leftover is "left in longer than his pitching justified", which is the
leash, isolated. Controls are measured IN the scored window on purpose: they
are covariates, not predictors, and the question is conditional on them.

REPUTATION IS PROXIED BY THINGS DATED BEFORE THE SEASON, so none of it can
leak: career innings and starts through last season, seasons in the majors,
All-Star selections, Cy Young finishes, age. A fantasy or preseason power
ranking would be a better proxy than any of these and needs a dated source;
these are what is retrievable today without scraping.

WHAT WOULD MAKE THIS REAL: a positive correlation between reputation and the
residual means managers extend men they rate regardless of the night's
evidence, which is a mechanism the simulator has no access to and cannot
recover from rates. A null means the hook really is a workload rule, which
is what the per-decision fit already said — pitch count alone ranks removals
at AUC 0.901 and everything else together adds +0.013.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import statistics as st
import sys
from collections import defaultdict

from src.context import calibrate as cal
from src.context.sources import statsapi as sa
from scratchpad.qualitative import _ip, corr, multi, player_index, year_by_year

HOLDOUT = "2026-07-01"
MIN_POST = 6
SEASON = 2026

#: How he pitched in the very starts being scored. These are CONTROLS.
CONTROLS = ("kbb_in", "br_in", "er_in")

REPUTATION = (("career innings through last season", "career_ip"),
              ("career starts", "career_gs"),
              ("seasons in the majors", "seasons"),
              ("All-Star selections", "allstar"),
              ("Cy Young finishes", "cy"),
              ("age", "age"))


def awards(pid: int) -> dict:
    """MLB All-Star and Cy Young counts, strictly before this season.

    The feed carries minor-league and spring honours too — 'PCL Pitcher of
    the Week', 'AFL Rising Stars' — so the names are matched exactly rather
    than by substring, which would count a Texas League all-star as
    reputation in a major-league dugout.
    """
    try:
        d = sa._cached(f"awards_{pid}", f"/people/{pid}/awards")
    except Exception:
        return {"allstar": 0.0, "cy": 0.0}
    a = c = 0
    for aw in d.get("awards", []):
        season = int(aw.get("season") or 0)
        if season >= SEASON:
            continue
        name = (aw.get("name") or "").strip()
        if name in ("AL All-Star", "NL All-Star"):
            a += 1
        elif "Cy Young" in name:
            c += 1
    return {"allstar": float(a), "cy": float(c)}


def main(argv):
    cut = argv[0] if argv else HOLDOUT
    cut_d = dt.date.fromisoformat(cut)

    post = defaultdict(list)
    for s, p, l in cal.build_cases(since=cut, rates_before=cut):
        post[s["player_name"]].append(s)
    names = [n for n, v in post.items() if len(v) >= MIN_POST]
    print(f"  {len(names)} starters with >={MIN_POST} starts after {cut}",
          flush=True)

    idx = player_index()
    ids = {n: idx[n]["id"] for n in names if n in idx}
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        yby = dict(zip(ids, pool.map(year_by_year, ids.values())))
        awd = dict(zip(ids, pool.map(awards, ids.values())))

    rows = []
    for n, pid in ids.items():
        v = post[n]
        bf = sum(s["o"] + s["h"] + s["bb"] for s in v)
        if not bf:
            continue
        y = yby.get(n) or {}
        past = {k: d for k, d in y.items() if k < SEASON}
        bio = idx[n]
        born = bio.get("birthDate")
        rows.append({
            "name": n,
            # CONTROLS — how he actually pitched in the scored starts.
            "kbb_in": (sum(s["k"] for s in v) - sum(s["bb"] for s in v)) / bf,
            # RATES, not per-start totals. Baserunners and earned runs per
            # START are cumulative — a man who goes deeper allows more of
            # both by construction, so controlling on them would control for
            # length with length and shrink the very residual being sought.
            "br_in": sum(s["h"] + s["bb"] for s in v) / bf,
            "er_in": sum(s["er"] for s in v) / bf,
            # REPUTATION — all of it dated before this season.
            "career_ip": sum(d["ip"] for d in past.values()),
            "career_gs": float(sum(d["gs"] for d in past.values())),
            "seasons": float(len([1 for d in past.values() if d["ip"] > 0])),
            "allstar": awd[n]["allstar"],
            "cy": awd[n]["cy"],
            "age": ((cut_d - dt.date.fromisoformat(born)).days / 365.25
                    if born else 28.0),
            "actual": st.mean(s["o"] for s in v),
            "n": len(v),
        })

    act = [r["actual"] for r in rows]
    print(f"  {len(rows)} matched; actual mean outs {st.mean(act):.2f}, "
          f"spread {st.pstdev(act):.2f}")

    # THE CONTROL MODEL. What his own pitching explains about his length.
    R, b = multi(rows, list(CONTROLS), "actual")
    print(f"\n  how he pitched explains his length at R {R:+.3f}   "
          + "  ".join(f"{k} {w:+.2f}" for k, w in zip(CONTROLS, b)))

    # Residual: outs beyond what the night's pitching justified.
    cols = {}
    for k in CONTROLS:
        v = [r[k] for r in rows]
        m, s = st.mean(v), st.pstdev(v)
        cols[k] = [(x - m) / s if s else 0.0 for x in v]
    am, asd = st.mean(act), st.pstdev(act)
    fit = [sum(b[i] * cols[k][t] for i, k in enumerate(CONTROLS))
           for t in range(len(rows))]
    for t, r in enumerate(rows):
        r["resid"] = (r["actual"] - am) / asd - fit[t]
    res = [r["resid"] for r in rows]
    print(f"  residual spread {st.pstdev(res) * asd:.2f} outs per start — "
          f"this is the leash, isolated")

    print(f"\n  REPUTATION vs THE RESIDUAL            corr    vs raw outs")
    for label, key in REPUTATION:
        print(f"  {label:<34}{corr([r[key] for r in rows], res):>+8.3f}"
              f"{corr([r[key] for r in rows], act):>+13.3f}")

    Rall, _ = multi(rows, [k for _, k in REPUTATION], "resid")
    chance = (len(REPUTATION) / (len(rows) - 1.0)) ** 0.5
    print(f"  {'all six together':<34}{Rall:>+8.3f}"
          f"   (fitting six on {len(rows)} gives {chance:.3f} by chance)")

    # THE SHIPPING TEST. Career workload could be nothing but "is he an
    # established starter or a callup", and short leashes on callups are
    # already known. So control for his own recent length as well: if the
    # career number still adds, it is carrying something his in-season
    # record does not.
    prior = defaultdict(list)
    for s_, p_, l_ in cal.build_cases(before=cut):
        prior[s_["player_name"]].append(s_)
    keep = [r for r in rows if len(prior.get(r["name"], [])) >= 5]
    for r in keep:
        r["prior_outs"] = st.mean(x["o"] for x in prior[r["name"]])
    print(f"\n  DOES IT SURVIVE HIS OWN RECENT LENGTH?  ({len(keep)} starters)")
    base, _ = multi(keep, list(CONTROLS) + ["prior_outs"], "actual")
    print(f"  {'pitching + prior outs':<40}{base:>+8.3f}")
    for label, key in (("+ career starts", "career_gs"),
                       ("+ career innings", "career_ip"),
                       ("+ age", "age")):
        R2, _ = multi(keep, list(CONTROLS) + ["prior_outs", key], "actual")
        print(f"  {label:<40}{R2:>+8.3f}   ({R2 - base:+.3f})")

    print(f"\n  LEFT IN LONGEST THAN HIS PITCHING JUSTIFIED")
    print(f"  {'pitcher':<24}{'resid':>8}{'outs':>7}{'ER':>6}{'AS':>4}"
          f"{'careerIP':>10}")
    ranked = sorted(rows, key=lambda r: -r["resid"])
    for r in ranked[:8] + [None] + ranked[-8:]:
        if r is None:
            print(f"  {'...':<24}")
            continue
        print(f"  {r['name'][:23]:<24}{r['resid'] * asd:>+8.2f}"
              f"{r['actual']:>7.1f}{r['er_in']:>6.2f}{int(r['allstar']):>4}"
              f"{r['career_ip']:>10.0f}")
    assert _ip


if __name__ == "__main__":
    main(sys.argv[1:])
