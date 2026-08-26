"""Does a PRESEASON ranking predict how long a starter is left in?

    venv/bin/python -m scratchpad.preseason_test [holdout-date]

THE ONE EXTERNAL SIGNAL LEFT. Three routes have now hit the same wall — a
stat-based rank (`rank_starters.py`), workload and rookie status
(`qualitative.py`), career record and awards (`reputation.py`) — and each
was absorbed by the pitcher's own in-season length. The stated reason is
that a club's opinion of a man is already expressed in how deep it lets him
go.

A PRESEASON RANKING IS THE ONE THING THAT ESCAPES THAT ARGUMENT, because it
is fixed before any of this season's innings exist. It is a human consensus
of what a pitcher is EXPECTED to be, and expectation is exactly what the
database has no column for. It also covers the callup, who has no in-season
record to be absorbed by.

Ranks come from `preseason_ranks.py` — Razzball 16 Feb and FantasyPros 22
March, both complete, agreeing at r +0.871.

TARGET IS THE RESIDUAL, per the correction in `reputation.py`: outs beyond
what the night's pitching justified, controlling on K-BB%, baserunners and
earned runs as RATES per batter faced.

UNRANKED IS INFORMATION AND IS NOT MISSING DATA. A starter nobody put in a
top 100 in March is a different animal from one ranked 12th, so absence is
scored as a rank just past the end of the list rather than dropped. Both
treatments are reported, because the choice can manufacture a result on its
own: dropping the unranked leaves only pitchers the industry rated, which is
a sample selected on the very thing being tested.
"""
from __future__ import annotations

import concurrent.futures as cf
import statistics as st
import sys
from collections import defaultdict

from src.context import calibrate as cal
from scratchpad import preseason_ranks as pre
from scratchpad.qualitative import corr, multi, player_index, year_by_year

HOLDOUT = "2026-07-01"
MIN_POST = 6
SEASON = 2026
CONTROLS = ("kbb_in", "br_in", "er_in")

#: What an unranked pitcher is worth. Both complete lists stop at 100 and 86.
UNRANKED = 115.0


def main(argv):
    cut = argv[0] if argv else HOLDOUT
    R = pre.ranks()
    complete = [k for k, m in pre.SOURCES.items() if m["complete"]]

    post, prior = defaultdict(list), defaultdict(list)
    for s, p, l in cal.build_cases(since=cut, rates_before=cut):
        post[s["player_name"]].append(s)
    for s, p, l in cal.build_cases(before=cut):
        prior[s["player_name"]].append(s)

    rows = []
    for n, v in post.items():
        if len(v) < MIN_POST:
            continue
        bf = sum(s["o"] + s["h"] + s["bb"] for s in v)
        if not bf:
            continue
        key = pre.normalise(n)
        got = [R[src][key] for src in complete if key in R[src]]
        rows.append({
            "name": n,
            "kbb_in": (sum(s["k"] for s in v) - sum(s["bb"] for s in v)) / bf,
            "br_in": sum(s["h"] + s["bb"] for s in v) / bf,
            "er_in": sum(s["er"] for s in v) / bf,
            "ranked": 1.0 if got else 0.0,
            "rank": st.mean(got) if got else UNRANKED,
            "n_prior": len(prior.get(n, [])),
            "prior_outs": (st.mean(s["o"] for s in prior[n])
                           if prior.get(n) else 0.0),
            "actual": st.mean(s["o"] for s in v),
            "n": len(v),
        })

    hit = sum(1 for r in rows if r["ranked"])
    print(f"  {len(rows)} starters with >={MIN_POST} starts after {cut}")
    print(f"  {hit} of them ({hit/len(rows):.0%}) appear on a preseason list")

    act = [r["actual"] for r in rows]
    _, b = multi(rows, list(CONTROLS), "actual")
    cols = {}
    for k in CONTROLS:
        v = [r[k] for r in rows]
        m, s = st.mean(v), st.pstdev(v)
        cols[k] = [(x - m) / s if s else 0.0 for x in v]
    am, asd = st.mean(act), st.pstdev(act)
    for t, r in enumerate(rows):
        r["resid"] = ((r["actual"] - am) / asd
                      - sum(b[i] * cols[k][t] for i, k in enumerate(CONTROLS)))
    res = [r["resid"] for r in rows]

    # Sign: a BETTER pitcher has a LOWER rank number, so a negative
    # correlation with the residual means the well-regarded go deeper.
    print(f"\n  PRESEASON RANK vs THE LEASH RESIDUAL")
    print(f"  {'consensus rank (unranked = 115)':<38}"
          f"{corr([r['rank'] for r in rows], res):>+8.3f}")
    print(f"  {'ranked at all (yes/no)':<38}"
          f"{corr([r['ranked'] for r in rows], res):>+8.3f}")
    only = [r for r in rows if r["ranked"]]
    print(f"  {'rank, RANKED PITCHERS ONLY':<38}"
          f"{corr([r['rank'] for r in only], [r['resid'] for r in only]):>+8.3f}"
          f"   (n={len(only)}, selected sample)")
    for src in complete:
        v = [r for r in rows if pre.normalise(r["name"]) in R[src]]
        c = corr([R[src][pre.normalise(r["name"])] for r in v],
                 [r["resid"] for r in v])
        print(f"  {'  ' + src + ' alone':<38}{c:>+8.3f}   (n={len(v)})")

    print(f"\n  DOES IT SURVIVE HIS OWN RECENT LENGTH?")
    keep = [r for r in rows if r["n_prior"] >= 5]
    base, _ = multi(keep, list(CONTROLS) + ["prior_outs"], "actual")
    print(f"  {'pitching + prior outs':<38}{base:>+8.3f}   (n={len(keep)})")
    for label, key in (("+ preseason rank", "rank"),
                       ("+ ranked at all", "ranked")):
        R2, _ = multi(keep, list(CONTROLS) + ["prior_outs", key], "actual")
        print(f"  {label:<38}{R2:>+8.3f}   ({R2 - base:+.3f})")

    # THE POPULATION IT WAS FETCHED FOR. A man with no in-season record is
    # the only one prior outs cannot already speak for.
    thin = [r for r in rows if r["n_prior"] <= 8]
    print(f"\n  THIN RECORD (<= 8 starts before the cut, n={len(thin)})")
    if len(thin) >= 8:
        tr = [r["resid"] for r in thin]
        print(f"  {'preseason rank vs residual':<38}"
              f"{corr([r['rank'] for r in thin], tr):>+8.3f}")
        print(f"  {'ranked at all vs residual':<38}"
              f"{corr([r['ranked'] for r in thin], tr):>+8.3f}")
        tb, _ = multi(thin, list(CONTROLS), "actual")
        t2, _ = multi(thin, list(CONTROLS) + ["rank"], "actual")
        print(f"  {'pitching -> + rank':<38}{tb:>+8.3f} -> {t2:+.3f}")

    # THE FULL PICTURE BY RECORD LENGTH. "+0.011 overall" and "+0.048 on
    # the thin group" are both true and neither shows where the crossover
    # is. Every band gets the same two models so the gain is comparable.
    print(f"\n  WHAT THE RANK ADDS, BY LENGTH OF IN-SEASON RECORD")
    print(f"  {'prior starts':<16}{'n':>5}{'pitching':>10}{'+rank':>9}"
          f"{'gain':>8}{'corr':>8}")
    bands = (("0-4", 0, 4), ("5-8", 5, 8), ("9-12", 9, 12),
             ("13-16", 13, 16), ("17+", 17, 99), ("ALL", 0, 99))
    for lbl, lo, hi in bands:
        g = [r for r in rows if lo <= r["n_prior"] <= hi]
        if len(g) < 8:
            print(f"  {lbl:<16}{len(g):>5}   too few to read")
            continue
        b0, _ = multi(g, list(CONTROLS), "actual")
        b1, _ = multi(g, list(CONTROLS) + ["rank"], "actual")
        c = corr([r["rank"] for r in g], [r["resid"] for r in g])
        print(f"  {lbl:<16}{len(g):>5}{b0:>10.3f}{b1:>9.3f}"
              f"{b1 - b0:>+8.3f}{c:>+8.3f}")

    print(f"\n  BEST AND WORST LEASH RESIDUALS, with their March rank")
    print(f"  {'pitcher':<24}{'resid':>8}{'outs':>7}{'rank':>7}{'prior':>7}")
    ranked = sorted(rows, key=lambda r: -r["resid"])
    for r in ranked[:8] + [None] + ranked[-8:]:
        if r is None:
            print(f"  {'...':<24}")
            continue
        rk = "-" if not r["ranked"] else f"{r['rank']:.0f}"
        print(f"  {r['name'][:23]:<24}{r['resid'] * asd:>+8.2f}"
              f"{r['actual']:>7.1f}{rk:>7}{r['n_prior']:>7}")


if __name__ == "__main__":
    main(sys.argv[1:])
