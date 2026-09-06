"""THE LAYOFF: does a starter back from a long absence get a shorter leash?

QUESTION. Jameson Taillon took the ball on 2026-09-04 having last pitched
on 2026-08-10 — 25 days. The board priced him at his season workload (14.7
outs, 4.1 K) and the market had him near 2.7 K, which is a three-inning
cap. Nothing in `sim` or `game` reads days-since-last-appearance.

WHY THE EXISTING NULL DOES NOT SETTLE IT. `NOTES-context-layer.md:2250`
screened six between-game features on the outs residual and reported
`days rest +0.014`. That is a LINEAR slope, and the rest distribution is
74% at five or six days with under 4% past ten — a flat middle swamps a
step in the tail. This is the project's own recorded failure mode: a
mis-specified mechanism and an absent effect produce identical output.

WHAT THE COUNT SAYS, before any hook fit. Within-pitcher, within-season,
against the same pitcher's own 4-9 day starts that year, train rows only:

    gap          n            d_outs             d_BF             d_K/BF
    4-9      15497  +0.01 (z +0.2)  +0.00 (z +0.1)  +0.0002 (z +0.3)
    10-14      430  -0.81 (z -4.0)  -1.16 (z -5.8)  +0.0013 (z +0.3)
    15-20      169  -1.28 (z -4.4)  -1.62 (z -5.2)  -0.0117 (z -1.6)
    21-30      124  -1.11 (z -3.1)  -1.82 (z -4.3)  +0.0098 (z +1.0)
    31+        244  -0.86 (z -3.9)  -1.68 (z -7.1)  +0.0043 (z +0.6)

The 4-9 row is the baseline population and reads zero as it must. The
effect is ENTIRELY EXPOSURE: `d_BF` is -1.2 to -1.8 batters at z -4.3 to
-7.1 while `d_K/BF` is null in every bucket. A returning starter is not
worse per batter, he is pulled earlier. That is a HOOK term and not a rate
term, which is what this file fits.

A STEP, NOT A RAMP. The buckets are flat to nine days and then roughly
level from ten on — they do not climb with the gap. So the feature is a
binary indicator at `LAYOFF_MIN`, and fitting a slope through five
measured points is the move CLAUDE.md forbids (see `mid_per_inning_run`,
where a least-squares line through counted points charged +0.724 at one
run against a counted +0.296).

THE CONFOUND, AND IT RUNS THE WRONG WAY. A pitcher returning from the IL
may simply be a worse or more fragile pitcher, and a worse pitcher is
pulled earlier for reasons that have nothing to do with the layoff. That
pushes the coefficient POSITIVE (toward removal), so it works against the
hypothesis rather than for it. `leash` — his own recent length — is in the
control set to absorb what it can, the same rule `pen_state.py` follows.

GAPS ARE COMPUTED FROM CONSECUTIVE STARTS in the decision rows themselves,
not from a name join. `mlb_stints` covers 2026 only, so an id->name mapping
would silently drop every 2023-2025 arm that never pitched in 2026.
Consecutive starts is also exactly what `price.py` can look up at board
time, so the fitted quantity and the served quantity are the same one.

NOT A SIMULATION. This measures real decisions. Whether wiring it improves
the simulation is scored separately, on the ladder and CRPS.
"""
from __future__ import annotations

#: NEVER FIT ON ROWS THAT WILL BE SCORED ON. Same cutoff `shape.py` and
#: `fitf5` evaluate from — one cutoff for the whole project, because two is
#: how one of them drifts. See CLAUDE.md.
HOLDOUT_CUT = "2026-07-01"


def train_only(rows):
    """Rows strictly before the holdout. Call it before ANY fit."""
    return [r for r in rows if r.get("date", "") < HOLDOUT_CUT]


import json

import numpy as np

from src.context import sim, store
from scratchpad.hook_margin import control, fit, power, report, xy

CACHE = "/tmp/hook_rows.json"

#: Days since the previous START at or beyond which the indicator fires.
#: Ten is where the counted effect first clears three sigma (-0.81 outs,
#: z -4.0) and it is also the first bucket boundary past a normal turn: a
#: five-man rotation on a normal week is four to six days, and seven to
#: nine covers a skipped turn or an off day. Ten means something happened.
LAYOFF_MIN = 10

#: Everything both shipped curves already read, so the layoff column is
#: asked what it ADDS rather than what it correlates with. Matches
#: `pen_state.py` exactly — including `leash`, which is the confound
#: control described in the docstring.
BND_BASE = ("pitches", "runs", "br", "inning", "bf", "tto", "abs_margin",
            "leash")
MID_BASE = ("pitches", "inn_br", "runs", "onbase", "inning", "bf",
            "abs_margin", "leash")


def attach(rows):
    """Add `gap`, `layoff` and `same_season` to every decision row.

    THE GAP COMES FROM `sim.layoff_gap`, NOT FROM THESE ROWS, and that is
    the whole point of this function. The obvious implementation — take
    each pitcher's consecutive start dates in the decision rows — is wrong
    and was shipped that way for an hour. `fit_hooks.build` drops every
    start whose leash lookup misses, so the rows carry 1.63 starters per
    game against a real 2.00, and a MISSING start does not weaken the
    feature but INVERTS it: one absent row turns a normal five-day turn
    into a ten-day layoff and fires the step on a pitcher who never went
    anywhere.

    Fitting on one definition and serving another is the mistake CLAUDE.md
    names directly — check that two numbers measure the same thing before
    acting on the difference. Both sides now read the same union index.
    """
    with store.connect() as c:
        names = {r["pitcher_id"]: r["player_name"] for r in
                 c.execute("select distinct pitcher_id, player_name "
                           "from mlb_stints")}
    out = []
    for r in rows:
        nm = names.get(r["pitcher"])
        gap = sim.layoff_gap(nm, r["date"]) if nm else None
        if gap is None:
            continue        # no prior start on record, or a season break
        r = dict(r)
        r["gap"] = gap
        r["layoff"] = 1.0 if gap >= LAYOFF_MIN else 0.0
        # `sim.layoff_gap` already returns None across a season break, so
        # everything that survives is in-season. The column stays so the
        # season-break block below still reports, and so a future change
        # to that rule cannot silently pool the two populations.
        r["same_season"] = True
        out.append(r)
    return out


def buckets(rows, label):
    """The raw pull rate by gap, so the SHAPE is visible before any fit."""
    print(f"\n  {label} — raw pull rate by gap")
    print(f"    {'gap':<9}{'n':>9}{'pulls':>9}{'rate':>9}")
    for lo, hi in ((4, 9), (10, 14), (15, 20), (21, 30), (31, 400)):
        s = [r for r in rows if lo <= r["gap"] <= hi]
        if not s:
            continue
        lbl = f"{lo}-{hi}" if hi < 400 else f"{lo}+"
        y = np.mean([r["removed"] for r in s])
        print(f"    {lbl:<9}{len(s):>9,}{int(sum(r['removed'] for r in s)):>9,}"
              f"{y:>9.4f}")


def main():
    rows = attach(json.load(open(CACHE)))
    rows = train_only(rows)              # THE GUARD, ACTUALLY CALLED
    ins = [r for r in rows if r["same_season"]]
    print(f"{len(rows):,} starter decisions with a prior start, "
          f"{min(r['date'] for r in rows)} to {max(r['date'] for r in rows)}")
    print(f"  {len(ins):,} in-season   "
          f"{len(rows) - len(ins):,} across a season break")
    fire = np.mean([r["layoff"] for r in ins])
    print(f"  layoff indicator (gap >= {LAYOFF_MIN}) fires on "
          f"{100 * fire:.2f}% of in-season decisions")

    mid = [r for r in ins if not r["ends_inning"]]
    bnd = [r for r in ins if r["ends_inning"]]
    print(f"  {len(bnd):,} boundary   {len(mid):,} mid-inning")

    for name, pop, base in (("BOUNDARY", bnd, BND_BASE),
                            ("MID-INNING", mid, MID_BASE)):
        print(f"\n{'=' * 66}\n{name}\n{'=' * 66}")
        buckets(pop, name)
        # STATE THE POWER BEFORE THE RESULT.
        power(pop, base, ("layoff",), f"{name} layoff")
        # POSITIVE CONTROL, injected at the size actually being CLAIMED.
        # 0.25 was the first choice and the boundary curve reads MISSED on
        # it — recovered +0.214 +/- 0.075, right magnitude, z 2.9. That is
        # the harness stating its resolution, not a mis-specification, and
        # the smaller injection is kept so the limit stays visible rather
        # than being quietly dropped once a larger one passed.
        print("\n  POSITIVE CONTROLS")
        for size in (0.25, 0.60, 1.00):
            control(pop, base, ("layoff",), size, f"layoff x{size:.2f}")
        report(pop, base, ("layoff",), f"{name} + layoff, controlled")

        # STABILITY GATE. A coefficient that does not repeat across seasons
        # is not a mechanism, whatever its in-sample sigma.
        print(f"\n  --- {name}: PER SEASON ---")
        for yr in ("2023", "2024", "2025", "2026"):
            sub = [r for r in pop if r["date"][:4] == yr]
            if len(sub) < 3000:
                continue
            X, y = xy(sub, base + ("layoff",))
            b, se = fit(X, y)
            i = len(base)
            print(f"    {yr}  n {len(sub):>7,}  layoff "
                  f"{b[i]:>+9.5f} +/- {se[i]:.5f}  z {b[i] / se[i]:>+5.1f}")

        # IS THE STEP THE RIGHT SHAPE? If the effect climbed with the gap a
        # continuous term would beat the indicator. Reported, not assumed.
        print(f"\n  --- {name}: SHAPE CHECK (continuous vs step) ---")
        for r in pop:
            r["gap_over"] = float(max(0, min(r["gap"], 45) - LAYOFF_MIN))
        report(pop, base, ("gap_over",), f"{name} + days beyond {LAYOFF_MIN}")
        report(pop, base, ("layoff", "gap_over"), f"{name} + step AND slope")

        # THE GATE THAT DECIDES WHAT SHIPS. Both terms clear three sigma
        # pooled, which is not enough to wire two parameters: a coefficient
        # that does not repeat across seasons is not a mechanism. Run on the
        # COMBINED spec because that is the one being considered, and a term
        # can be stable alone and unstable beside its partner.
        print(f"\n  --- {name}: PER SEASON, step AND slope together ---")
        for yr in ("2023", "2024", "2025", "2026"):
            sub = [r for r in pop if r["date"][:4] == yr]
            if len(sub) < 3000:
                continue
            X, y = xy(sub, base + ("layoff", "gap_over"))
            b, se = fit(X, y)
            i = len(base)
            print(f"    {yr}  n {len(sub):>7,}  step {b[i]:>+8.5f} "
                  f"(z {b[i] / se[i]:>+5.1f})   slope {b[i + 1]:>+8.5f} "
                  f"(z {b[i + 1] / se[i + 1]:>+5.1f})")

    # THE SEASON BREAK, reported separately rather than pooled in. A pitcher
    # opening a season has had a spring to build up and is not the same case
    # as one returning mid-season, which is why `same_season` exists.
    print(f"\n{'=' * 66}\nACROSS A SEASON BREAK — separate population\n{'=' * 66}")
    xs = [r for r in rows if not r["same_season"]]
    for name, pop, base in (
            ("BOUNDARY", [r for r in xs if r["ends_inning"]], BND_BASE),
            ("MID-INNING", [r for r in xs if not r["ends_inning"]], MID_BASE)):
        if len(pop) < 3000:
            print(f"  {name}: {len(pop):,} rows, too few")
            continue
        print(f"  {name}: n {len(pop):,}   pull rate "
              f"{np.mean([r['removed'] for r in pop]):.4f}")


if __name__ == "__main__":
    main()
