"""Is the pitch cost of an outcome the SAME for every pitcher?

    venv/bin/python -m scratchpad.pitch_cost_spread [n_games]

QUESTION    `sim.PITCH_COST` is one number per outcome for the whole league
            — a strikeout costs 4.97 pitches, an out on contact 3.25. It is
            COUNTED (150,907 plate appearances) and its LEVEL is right (85.5
            against a real 85.6). This asks the next question: is that cost
            FLAT ACROSS PITCHERS, which is what a single table assumes?
            Unit of observation: one plate appearance.

WHY IT IS THE LIVE SUSPECT. Measured today at the hook, the simulator's
selection runs BACKWARDS — its mean-of-ratios strikeout rate at a removal
decision is 0.2002 where reality is 0.2276, on an identical ratio-of-sums.
High-strikeout starters last LONGER in reality and SHORTER in the
simulator, and the flat table is the named mechanism: if a strikeout always
costs 4.97, then missing bats always spends the pitch budget faster, so
dominance can only ever shorten a simulated outing.

HYPOTHESIS  Elite strikeout pitchers get their strikeouts CHEAPER than the
            league-average strikeout — better stuff means more swinging
            strikes early in the count rather than long two-strike battles.
            If so a flat table over-charges exactly the pitchers whose
            starts the model truncates, and the defect is a MISSING
            INTERACTION rather than a wrong constant.
            FALSIFIER: pitches per strikeout is flat across K-rate terciles.
            That would clear `PITCH_COST` and send item 7 elsewhere — most
            likely to the hook's boundary curve, which took no in-game state
            at all in either of today's fits.

DENOMINATOR, NAMED. "Pitches per strikeout" is pitches thrown IN PLATE
APPEARANCES THAT ENDED IN A STRIKEOUT, divided by the number of those plate
appearances. It is NOT pitches per start over strikeouts per start, which
would fold in every other outcome and is the mistake available here.

THE CONFOUND, AND IT IS WHY TERCILES ARE BUILT ON A PRIOR SEASON. Sorting
pitchers by strikeout rate measured on the SAME plate appearances being
scored puts the outcome inside the grouping variable. Terciles are built on
a pitcher's OTHER games — a leave-one-game-out split — so the grouping
cannot be reading the rows it grades.
"""
from __future__ import annotations

import sys
from collections import defaultdict

import numpy as np

from src.context.sources import pbp
from src.context import boundary

#: A plate appearance's terminal event, mapped to the bucket `PITCH_COST`
#: keys on. Only the two that matter for the hypothesis are split out.
K_EV = boundary.K_EVENTS
OUT_EV = {"field_out", "force_out", "grounded_into_double_play",
          "double_play", "fielders_choice_out", "sac_fly", "sac_bunt"}
BB_EV = {"walk", "intent_walk"}
HIT_EV = {"single", "double", "triple", "home_run"}

#: Outs a terminal event records. Double plays are TWO and that matters
#: here — they are the cheapest outs in baseball on a per-pitch basis and
#: they belong disproportionately to contact pitchers, which is exactly the
#: comparison this file is making.
OUT_VALUE = {"strikeout": 1, "field_out": 1, "force_out": 1,
             "fielders_choice_out": 1, "sac_fly": 1, "sac_bunt": 1,
             "strikeout_double_play": 2, "grounded_into_double_play": 2,
             "double_play": 2, "sac_fly_double_play": 2,
             "sac_bunt_double_play": 2, "triple_play": 3}


def collect(limit=None):
    ids = pbp.final_games()
    if limit:
        ids = ids[:limit]
    # (pitcher, game) -> {"k":n, "bf":n, "pk":pitches in K PAs, ...}
    per: dict = defaultdict(lambda: defaultdict(float))
    n = 0
    for gid in ids:
        if not pbp.have(gid):
            continue
        data = pbp.fetch(gid)
        if not data:
            continue
        n += 1
        for play in (data.get("allPlays") or []):
            res = play.get("result") or {}
            ev = res.get("eventType") or ""
            pid = ((play.get("matchup") or {}).get("pitcher") or {}).get("id")
            if not pid or ev in boundary.SKIP:
                continue
            np_ = sum(1 for e in (play.get("playEvents") or [])
                      if e.get("isPitch"))
            if not np_:
                continue
            d = per[(pid, gid)]
            d["bf"] += 1
            d["pitches"] += np_
            # OUTS RECORDED, which is the denominator that actually decides
            # how deep a start goes. Pitches per BATTER is the wrong one:
            # a strikeout pitcher spends more per batter AND retires more of
            # them, and only the ratio to OUTS says which wins.
            d["outs"] += OUT_VALUE.get(ev, 0)
            if ev in K_EV:
                d["k"] += 1
                d["pk"] += np_
            elif ev in OUT_EV:
                d["out"] += 1
                d["pout"] += np_
            elif ev in BB_EV:
                d["bb"] += 1
                d["pbb"] += np_
            elif ev in HIT_EV:
                d["hit"] += 1
                d["phit"] += np_
        if n % 500 == 0:
            print(f"  {n} games, {len(per):,} pitcher-games", flush=True)
    return per


def main(argv):
    lim = int(argv[0]) if argv else None
    per = collect(lim)

    # LEAVE-ONE-GAME-OUT K RATE. The grouping variable must not contain the
    # rows it grades, so each pitcher-game is ranked by its pitcher's rate
    # over his OTHER games.
    tot: dict = defaultdict(lambda: defaultdict(float))
    for (pid, _), d in per.items():
        for key in ("k", "bf"):
            tot[pid][key] += d[key]

    rows = []
    for (pid, gid), d in per.items():
        bf_o = tot[pid]["bf"] - d["bf"]
        if bf_o < 300:              # needs a real book on the other games
            continue
        rows.append({"pid": pid, "loo_k_rate": (tot[pid]["k"] - d["k"]) / bf_o,
                     **{k: d[k] for k in
                        ("k", "bf", "pk", "out", "pout", "bb", "pbb",
                         "hit", "phit", "pitches", "outs")}})
    print(f"\n  {len(rows):,} pitcher-games with a 300+ batter book "
          f"elsewhere, {len({r['pid'] for r in rows}):,} pitchers")

    kr = np.array([r["loo_k_rate"] for r in rows])
    cuts = np.percentile(kr, [20, 40, 60, 80])
    print(f"  quintile cuts on leave-one-out K rate: "
          f"{'  '.join(f'{c:.3f}' for c in cuts)}")

    print(f"\n  PITCHES PER PLATE APPEARANCE, BY OUTCOME, BY THE PITCHER'S "
          f"OWN K RATE")
    print(f"  {'quintile':<12}{'n PA':>10}{'K rate':>9}"
          f"{'per K':>9}{'per out':>9}{'per BB':>9}{'per hit':>9}{'/PA':>8}")
    bounds = [-1] + list(cuts) + [2]
    deep = []
    for i in range(5):
        sub = [r for r in rows
               if bounds[i] < r["loo_k_rate"] <= bounds[i + 1]]
        if not sub:
            continue
        s = {k: sum(r[k] for r in sub) for k in
             ("k", "pk", "out", "pout", "bb", "pbb", "hit", "phit",
              "bf", "pitches", "outs")}
        print(f"  {f'Q{i + 1}':<12}{int(s['bf']):>10,}"
              f"{s['k'] / s['bf']:>9.3f}"
              f"{s['pk'] / max(s['k'], 1):>9.3f}"
              f"{s['pout'] / max(s['out'], 1):>9.3f}"
              f"{s['pbb'] / max(s['bb'], 1):>9.3f}"
              f"{s['phit'] / max(s['hit'], 1):>9.3f}"
              f"{s['pitches'] / s['bf']:>8.3f}")
        deep.append((f"Q{i + 1}", s))

    print(f"\n  THE DENOMINATOR THAT DECIDES START LENGTH — PITCHES PER OUT.")
    print(f"  A strikeout arm spends more per BATTER and retires more of "
          f"them; only\n  this ratio says which wins, and it is what the "
          f"hook's pitch term integrates.")
    print(f"  {'quintile':<12}{'K rate':>9}{'outs/PA':>10}"
          f"{'pitches/out':>13}{'pitches to 18 outs':>21}")
    for name, s in deep:
        ppo = s["pitches"] / max(s["outs"], 1)
        print(f"  {name:<12}{s['k'] / s['bf']:>9.3f}"
              f"{s['outs'] / s['bf']:>10.3f}{ppo:>13.3f}{ppo * 18:>21.1f}")
    # The spread that matters, with an error bar on it.
    lo = [r for r in rows if r["loo_k_rate"] <= cuts[0]]
    hi = [r for r in rows if r["loo_k_rate"] > cuts[3]]
    for label, grp in (("Q1 (lowest K)", lo), ("Q5 (highest K)", hi)):
        pk = np.array([r["pk"] / r["k"] for r in grp if r["k"] >= 3])
        print(f"  {label:<16} pitches per K, per-game mean "
              f"{pk.mean():.4f} +/- {pk.std() / len(pk) ** 0.5:.4f} "
              f"(n {len(pk):,} games)")

    print(f"\n  sim.PITCH_COST ships one number per outcome for everybody. "
          f"Compare the\n  'per K' column across quintiles against that "
          f"assumption.")


if __name__ == "__main__":
    main(sys.argv[1:])
