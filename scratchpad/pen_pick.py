"""COUNT the late-inning bullpen decision, for plan item 6.

    venv/bin/python -m scratchpad.pen_pick

THE DECISION THE MECHANISM WILL MAKE, counted directly: at every real
relief entry in inning >= 7, WAS THE ARM CHOSEN THE BEST STILL-UNUSED
ARM by K-BB%? That probability, by entry margin, is the Bernoulli
parameter of the shipped rule — "with counted probability take the best
remaining, else draw order" — so the count IS the constant, no fitting.

Rows: date < the July cut of each season (battery scoring territory
starts at the cut, rule 6 applied per fold). Quality: the same
`rate_src.bullpens` rank the simulator prices with, season-scoped,
frozen at the cut. An outing's own Ks sit inside that window, but one
outing is ~2% of a reliever's season and the covariate is a RANK over a
club's arms — second-order, unlike the GB leakage that bit 4b/4c.

Also printed: P(top-3 club arm | state) — the plan's pre-registered
descriptive number — per season for the stability gate, and the
model's own natural P(best remaining) under appearance-weighted draw
order, which is what the "else" leg already produces.
"""
from __future__ import annotations

import random
import statistics as st
import sys
from collections import defaultdict

from src.context import sim, store, game
from src.context.sources import rates as rate_src

CUTS = {s: f"{s}-07-01" for s in (2023, 2024, 2025, 2026)}
LATE = 7

_Q = """
select game_id, date, team, player_name name, appearance_order ord,
       entry_inning inning, entry_margin margin
from mlb_stints
where date >= '{a}' and date < '{b}'
order by game_id, team, appearance_order
"""


def bucket(margin: int) -> str:
    """Signed where the behaviour is signed: a manager protecting a
    one-run lead and one chasing it make different calls (K-BB% of the
    arm used: leading 0.151, tied 0.146, trailing 0.131 — deploy.py)."""
    a = abs(margin)
    if a > 4:
        return "blowout"
    if a > 2:
        return "mid"
    if margin > 0:
        return "lead"
    return "tied" if margin == 0 else "trail"


def count():
    lg = sim.league()
    out = defaultdict(lambda: defaultdict(int))
    tops = defaultdict(lambda: defaultdict(int))
    pctl = defaultdict(lambda: defaultdict(int))
    miss = total = 0
    for s in sorted(CUTS):
        pens = rate_src.bullpens(lg, season=s, before=CUTS[s])
        qual = {(t, a["name"]): a["k_pct"] - a["bb_pct"]
                for t, arms in pens.items() for a in arms}
        top3 = {t: {a["name"] for a in sorted(
                    arms, key=lambda a: a["bb_pct"] - a["k_pct"])[:3]}
                for t, arms in pens.items()}
        with store.connect(attach=False) as c:
            rows = [dict(r) for r in
                    c.execute(_Q.format(a=f"{s}-01-01", b=CUTS[s]))]
        used: dict = {}
        for r in rows:
            key = (r["game_id"], r["team"])
            seen = used.setdefault(key, set())
            if r["ord"] > 0 and r["inning"] >= LATE:
                total += 1
                q = qual.get((r["team"], r["name"]))
                remaining = [n for (t, n), v in qual.items()
                             if t == r["team"] and n not in seen]
                if q is None or not remaining:
                    miss += 1
                else:
                    best = max(remaining,
                               key=lambda n: qual[(r["team"], n)])
                    b = bucket(r["margin"])
                    for k in (b, "ALL"):
                        out[(s, k)]["n"] += 1
                        out[(s, k)]["best"] += r["name"] == best
                        tops[(s, k)]["n"] += 1
                        tops[(s, k)]["top3"] += \
                            r["name"] in top3.get(r["team"], ())
                    # THE WHOLE SELECTION PROFILE: the chosen arm's
                    # quality percentile among the arms still unused
                    # tonight, binned in fifths. 0 = the best remaining.
                    if len(remaining) > 1 and r["name"] in remaining:
                        ranked = sorted(
                            remaining,
                            key=lambda n: -qual[(r["team"], n)])
                        pct = ranked.index(r["name"]) \
                            / (len(ranked) - 1)
                        bin5 = min(int(pct * 5), 4)
                        pctl[(s, b)][bin5] += 1
                        pctl[(s, b)]["n"] += 1
            seen.add(r["name"])
    print(f"\n  {total:,} late entries, {miss / total:.1%} outside the "
          f"priced pen (call-ups, position players) -> counted as-is "
          f"in neither numerator nor denominator")
    seasons = sorted(CUTS)
    for label, acc, num in (("P(chose BEST remaining)", out, "best"),
                            ("P(top-3 club arm)", tops, "top3")):
        print(f"\n  {label} by entry margin, inning >= 7")
        print(f"  {'bucket':<9}{'n':>7}{'p':>8}{'se':>8}"
              + "".join(f"{s:>8}" for s in seasons))
        for b in ("lead", "tied", "trail", "mid", "blowout", "ALL"):
            n = sum(acc[(s, b)]["n"] for s in seasons)
            k = sum(acc[(s, b)][num] for s in seasons)
            if not n:
                continue
            p = k / n
            se = (p * (1 - p) / n) ** 0.5
            cols = []
            for s in seasons:
                c_ = acc[(s, b)]
                cols.append(c_[num] / c_["n"] if c_["n"] else None)
            print(f"  {b:<9}{n:>7,}{p:>8.4f}{se:>8.4f}"
                  + "".join(f"{c:>8.3f}" if c is not None else f"{'-':>8}"
                            for c in cols))

    print("\n  SELECTION PROFILE — chosen arm's quality percentile among"
          "\n  remaining (fifths; bin 1 = the best fifth), the counted"
          "\n  distribution the mechanism draws from")
    print(f"  {'bucket':<9}{'n':>7}" + "".join(f"{f'bin{i+1}':>8}"
                                               for i in range(5))
          + "   per-season correlation of the five weights")
    for b in ("lead", "tied", "trail", "mid", "blowout"):
        n = sum(pctl[(s, b)]["n"] for s in seasons)
        ws = [sum(pctl[(s, b)][i] for s in seasons) / n for i in range(5)]
        per = {s: [pctl[(s, b)][i] / pctl[(s, b)]["n"]
                   for i in range(5)]
               for s in seasons if pctl[(s, b)]["n"]}
        from itertools import combinations as _cmb
        cors = [st.correlation(per[a], per[c2])
                for a, c2 in _cmb(sorted(per), 2)]
        tail = f"   {st.mean(cors):+.3f}" if cors else ""
        print(f"  {b:<9}{n:>7,}"
              + "".join(f"{w:>8.4f}" for w in ws) + tail)

    # THE MODEL'S NATURAL RATE under appearance-weighted sampling used in
    # draw order — the "else" leg. Simulated on the real 2026 pen pools:
    # draw eight arms as build_side does, walk them in order, and at each
    # pen index ask whether the next arm is the best remaining.
    lgq = sim.league()
    pens = rate_src.bullpens(lgq, season=2026, before=CUTS[2026])
    rng = random.Random(7)
    hits = tries = 0
    for _ in range(300):
        for team, pool in pens.items():
            arms = []
            p2, w = list(pool), [max(a.get("apps") or 1, 1) for a in pool]
            while p2 and len(arms) < game.PEN_DEPTH:
                i = rng.choices(range(len(p2)), weights=w, k=1)[0]
                w.pop(i)
                arms.append(p2.pop(i))
            for i in range(min(3, len(arms) - 1)):
                rest = arms[i:]
                best = max(rest, key=lambda a: a["k_pct"] - a["bb_pct"])
                hits += arms[i] is best
                tries += 1
    print(f"\n  model's natural P(next = best remaining), first three pen "
          f"slots, draw order: {hits / tries:.4f}")


if __name__ == "__main__":
    count()
    sys.exit(0)
