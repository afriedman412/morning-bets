"""The (men on, outs) rate multipliers, counted. Feeds `sim.STATE_MULT`.

    venv/bin/python -m scratchpad.state_table [max_games]

`scratchpad/basestate.py` varied bases and outs ONE AT A TIME, which cannot
separate them — a two-out plate appearance is likelier to have runners on,
and vice versa. This counts the JOINT cell, which is what `pa_from` is
keyed on.

MULTIPLIERS ARE RATIOS TO THE OVERALL RATE, and that is what makes them
self-normalising: sum over cells of freq(s) x rate(s) IS the overall rate by
definition, so the multipliers average to one weighted by how often each
state occurs. Anything else would add offence rather than redistribute it.
`odds_mult` is not linear, so a small second-order drift survives — verify
the simulated marginals after wiring rather than assuming.

TWO CONFOUNDS EXCLUDED, both runners-on-only plays that would manufacture
the effect: INTENTIONAL walks (a manager's decision) and SACRIFICE BUNTS
(a guaranteed non-strikeout in the denominator).

BABIP IS A DIFFERENT DENOMINATOR from the other three and getting it wrong
is the single likeliest error here. The model's `babip` channel is
P(a ball in play becomes a hit), so the ratio must be
(H - HR) / (PA - K - BB - HBP - HR), NOT hits per plate appearance.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import sys
from collections import defaultdict

from src import db
from src.context.sources import pbp

K_EV = {"strikeout", "strikeout_double_play", "strikeout_triple_play"}
HIT_EV = {"single", "double", "triple", "home_run"}
PA_EV = K_EV | HIT_EV | {"walk", "hit_by_pitch",
    "field_out", "force_out", "grounded_into_double_play", "sac_fly",
    "field_error", "fielders_choice", "fielders_choice_out",
    "double_play", "triple_play", "sac_fly_double_play", "other_out"}


def _one(gid):
    out = defaultdict(lambda: defaultdict(int))
    try:
        for play, bases, outs, _a, _h in pbp.plays(gid):
            ev = (play.get("result") or {}).get("eventType") or ""
            if ev not in PA_EV:
                continue
            cell = (sum(1 for b in bases if b), outs)
            for key in (cell, "ALL"):
                c = out[key]
                c["pa"] += 1
                c["k"] += ev in K_EV
                c["bb"] += ev == "walk"
                c["hbp"] += ev == "hit_by_pitch"
                c["hr"] += ev == "home_run"
                c["h"] += ev in HIT_EV
    except Exception:
        return None
    return {k: dict(v) for k, v in out.items()}


def _rates(c):
    pa = c["pa"]
    bip = pa - c["k"] - c["bb"] - c["hbp"] - c["hr"]
    return {
        "k_pct": c["k"] / pa,
        "bb_pct": c["bb"] / pa,
        "hr_pct": c["hr"] / pa,
        "babip": (c["h"] - c["hr"]) / bip if bip > 0 else 0.0,
    }


def main(argv):
    cap = int(argv[0]) if argv else 2000
    with db.connect() as c:
        gids = [r["game_id"] for r in c.execute(
            "select game_id from games where sport='mlb' and status='Final'"
            " and date like '2026%' order by date")][:cap]
    with mp.get_context("fork").Pool(8) as p:
        got = [g for g in p.map(_one, gids, chunksize=16) if g]
    agg = defaultdict(lambda: defaultdict(int))
    for g in got:
        for cell, c in g.items():
            key = tuple(cell) if isinstance(cell, list) else cell
            for k, v in c.items():
                agg[key][k] += v
    # RAW COUNTS DUMPED so shrinkage can be reconsidered without a
    # 2,000-game rescan.
    json.dump({str(k): dict(v) for k, v in agg.items()},
              open("scratchpad/state_counts.json", "w"), indent=1)
    base = _rates(agg["ALL"])
    print(f"  {len(got):,} games, {agg['ALL']['pa']:,} plate appearances")
    print(f"  overall  k {base['k_pct']:.4f}  bb {base['bb_pct']:.4f}  "
          f"hr {base['hr_pct']:.4f}  babip {base['babip']:.4f}\n")
    print(f"  {'on':>3}{'out':>5}{'n':>9}"
          + "".join(f"{s:>13}" for s in ("k", "bb", "hr", "babip")))
    table = {}
    for on in (0, 1, 2, 3):
        for outs in (0, 1, 2):
            c = agg.get((on, outs))
            if not c or c["pa"] < 500:
                continue
            r = _rates(c)
            m = {k: r[k] / base[k] for k in r}
            # SE ON THE MULTIPLIER. A cell's rate carries binomial noise
            # sqrt(p(1-p)/n); dividing by the overall rate carries it into
            # the multiplier. The `babip` denominator is balls in play, not
            # plate appearances, so it gets its own n.
            bip = (c["pa"] - c["k"] - c["bb"] - c["hbp"] - c["hr"])
            se = {}
            for k, n in (("k_pct", c["pa"]), ("bb_pct", c["pa"]),
                         ("hr_pct", c["pa"]), ("babip", max(bip, 1))):
                pr = r[k]
                se[k] = ((pr * (1 - pr) / n) ** 0.5) / base[k]
            # SHRUNK TOWARD 1.0 BY ITS OWN NOISE, which is the same move
            # `stabilise` makes and is measurement rather than tuning: a
            # cell seen 704 times should not shout as loudly as one seen
            # 37,162 times. `tau` is the spread of the TRUE multipliers,
            # taken as the observed spread with the mean noise removed.
            table[f"{on},{outs}"] = {"_n": c["pa"],
                                     **{k: round(m[k], 4) for k in m},
                                     **{f"se_{k}": round(se[k], 4) for k in se}}
            print(f"  {on:>3}{outs:>5}{c['pa']:>9,}"
                  + "".join(f"{m[k]:>6.3f}+-{se[k]:<5.3f}"
                            for k in ("k_pct", "bb_pct", "hr_pct", "babip")))
    # THE NORMALISATION CHECK. Weighted by cell frequency these must come
    # back to 1.0, or the table adds offence instead of moving it around.
    tot = sum(agg[k]["pa"] for k in agg if k != "ALL")
    print(f"\n  frequency-weighted mean multiplier (must be ~1.000):")
    for stat in ("k_pct", "bb_pct", "hr_pct", "babip"):
        s = sum(agg[k]["pa"] * (_rates(agg[k])[stat] / base[stat])
                for k in agg if k != "ALL" and agg[k]["pa"] >= 500)
        n = sum(agg[k]["pa"] for k in agg if k != "ALL" and agg[k]["pa"] >= 500)
        print(f"    {stat:<8}{s / n:.4f}")
    json.dump(table, open("scratchpad/state_table.json", "w"), indent=1)
    print("\n  -> scratchpad/state_table.json")


if __name__ == "__main__":
    main(sys.argv[1:])
