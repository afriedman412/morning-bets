"""The A/B the handedness question actually needs: flag off vs flag on,
scored on F5 CRPS, with EXACT splits instead of derived ones.

    venv/bin/python -m scratchpad.hand_ab [n_sims] [workers]

WHY THE EARLIER SCREENS DO NOT SETTLE THIS. `platoon_bat.py` is a residual
CORRELATION with no simulation in it, and `hand_convex.py` simulates
SYNTHETIC lineups perturbed at random. Neither runs the model with real
handedness assignment. The only true A/B on record is the shipped one, and
`calibrate.USE_HANDEDNESS` says in its own docstring what would separate its
null from an artifact:

    "the derivation is attenuated: crediting a batter's whole game line to
     the opposing starter's hand includes his plate appearances against
     relievers, then SPLIT_STABILISE pulls each split roughly halfway back
     to his overall rate. Testing statsapi's exact splits would separate the
     two — if those also fail, the averaging argument wins."

That test is now cheap. Play-by-play carries real `pitchHand` on every plate
appearance across 9,962 games, so the split can be COUNTED rather than
inferred from a box score, with no reliever contamination at all.

THREE ARMS, and the third is the one the docstring asked for:

    off        overall rates. What ships.
    derived    the existing `batter_rates_by_hand` — whole-game lines
               credited to the starter's hand, shrunk at SPLIT_STABILISE.
    exact      counted per plate appearance off play-by-play.

SCORED ON F5 CRPS, which is the quantity that settles, across the full
support of the run distribution. Paired on common random numbers and run at
several salts, because the difference being looked for is small and an
unpaired mean at any affordable n_sims measures dice.

BOTH CASE CACHES MUST BE CLEARED between arms. `calibrate._CASES` and
`fitf5._SIDES` are separate memos and clearing one is worse than clearing
neither — it produces an A/B identical to five decimals, which reads as a
null and is plumbing.
"""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict

from src.context import calibrate as cal, fitf5, sim
from src.context.sources import rates as rate_src
from scratchpad.platoon_bat import load

#: Same two-level shrink the derived path uses, so the arms differ in the
#: SPLIT and nothing else. Changing the constant at the same time would
#: confound the comparison it exists to make.
SPLIT_K = rate_src.SPLIT_STABILISE

#: Which seasons the exact splits are COUNTED on. Empty means the season
#: being scored, which is IN-SAMPLE: every start sits inside its own
#: predictor, and splitting each hitter into two rates doubles the
#: parameters fitted on the very data being scored. That improves in-sample
#: fit whether or not handedness means anything, and it is the leak that
#: took the pitcher-side screen from +4.8 sigma to +1.2.
SPLIT_YEARS: list = []


def exact_splits(lg, season=None, before=None, conn=None):
    """{name: {'L': rates, 'R': rates}}, COUNTED per plate appearance.

    Signature matches `rate_src.batter_rates_by_hand` so it can stand in
    for it. `season`/`before` are accepted and IGNORED except for the
    season selection — the counts come from the play-by-play cache, which
    is aggregated per season, so a mid-season cutoff is not available here.
    Both arms of the A/B are run without a cutoff, so this does not
    advantage either one.
    """
    overall = rate_src.batter_rates(lg, season, before, conn)
    by_year, _starts, names = load(with_names=True)
    acc = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0, 0]))
    years = SPLIT_YEARS or ([season] if season else [2026])
    for y in years:
        for (bid, hand), v in by_year.get(y, {}).items():
            nm = names.get(bid)
            if not nm:
                continue
            c = acc[nm][hand]
            for i in range(5):
                c[i] += v[i]
    out = {}
    for nm, byhand in acc.items():
        base = overall.get(nm)
        if not base:
            continue
        out[nm] = {}
        for hand, c in byhand.items():
            pa, k, h, bip, hr = c
            w = pa / (pa + SPLIT_K) if pa else 0.0

            def mix(obs, prior):
                return w * obs + (1 - w) * prior if pa else prior

            out[nm][hand] = {
                "name": nm, "hand": hand, "pa": pa,
                "k_pct": mix(k / pa if pa else 0, base["k_pct"]),
                # Walks are not counted in the split cells — a plate
                # appearance that is not a strikeout, hit, batted out or
                # home run is mostly a walk, but "mostly" is not a count.
                # The batter's overall walk rate carries through unchanged,
                # which is the honest thing and also means this arm tests
                # the three channels that WERE counted.
                "bb_pct": base["bb_pct"],
                "hr_pct": mix(hr / pa if pa else 0, base["hr_pct"]),
                "babip": mix(h / bip if bip > 0 else base["babip"],
                             base["babip"]),
            }
    return out


def clear():
    """Both memos. Clearing one is worse than clearing neither."""
    cal._CASES.clear()
    fitf5._SIDES.clear()


def arm(label, handed, exact, n_sims, salts, lg):
    real = rate_src.batter_rates_by_hand
    cal.USE_HANDEDNESS = handed
    if exact:
        rate_src.batter_rates_by_hand = exact_splits
        cal.rate_src.batter_rates_by_hand = exact_splits
    try:
        clear()
        cases = fitf5.side_cases()
        ls = fitf5.losses(cases, {}, n_sims, lg, salts=salts)
    finally:
        rate_src.batter_rates_by_hand = real
        cal.rate_src.batter_rates_by_hand = real
        cal.USE_HANDEDNESS = False
        clear()
    return cases, ls


def main(argv):
    n_sims = int(argv[0]) if argv else 120
    lg = sim.league()
    salts = fitf5.SALTS
    print(f"  F5 CRPS, {n_sims} sims per side, {len(salts)} salts\n")

    # A sanity read on the splits BEFORE any simulation: if the exact and
    # derived arms hand the lineup nearly the same numbers, the A/B cannot
    # separate them and a null would be about the wiring, not the baseball.
    ex = exact_splits(lg)
    dv = rate_src.batter_rates_by_hand(lg)
    both = [n for n in ex if n in dv]
    gaps = []
    for n in both:
        for h in ("L", "R"):
            a, b = ex[n].get(h), dv[n].get(h)
            if a and b:
                gaps.append(abs(a["k_pct"] - b["k_pct"]))
    print(f"  {len(both):,} hitters in both split sources;"
          f" mean |exact - derived| K% = {st.mean(gaps):.4f}"
          f" over {len(gaps):,} cells")
    sp = []
    for n in ex:
        L, R = ex[n].get("L"), ex[n].get("R")
        if L and R and min(L["pa"], R["pa"]) >= 80:
            sp.append(L["k_pct"] - R["k_pct"])
    print(f"  exact split spread, {len(sp)} hitters with 80+ each hand:"
          f" sd {st.pstdev(sp):.4f}\n")

    res = {}
    arms = [("off (overall)", False, False, []),
            ("derived splits", True, False, []),
            ("EXACT in-sample", True, True, []),
            # THE ONE THAT ADJUDICATES. Splits counted on seasons the
            # scored starts are not in, so no start can be inside its own
            # predictor. If the in-sample gain survives here it is real; if
            # it collapses, it was the extra parameters fitting themselves.
            ("EXACT 2023-25", True, True, [2023, 2024, 2025])]
    for label, handed, exact, years in arms:
        global SPLIT_YEARS
        SPLIT_YEARS = years
        cases, ls = arm(label, handed, exact, n_sims, salts, lg)
        SPLIT_YEARS = []
        res[label] = ls
        m, se = fitf5._mean_se(ls)
        print(f"  {label:<17}{len(cases):>6,} sides   CRPS {m:.5f} +/- {se:.5f}")

    base = res["off (overall)"]
    print()
    for label in ("derived splits", "EXACT in-sample",
                  "EXACT 2023-25"):
        d, se = fitf5._paired_se(base, res[label])
        print(f"  {label:<17}vs off:  {d:+.5f} +/- {se:.5f}"
              f"  ({d / se if se else 0:+5.1f} sd)"
              f"   {'BETTER' if d < 0 else 'worse'}")
    print("\n  NEGATIVE means handedness LOWERS CRPS, which is the")
    print("  improvement — `_paired_se(a, b)` returns b - a and lower loss")
    print("  is better, so the obvious reading of the sign is backwards.")
    print("  The bar every candidate is held to is 2 sd, and the salts are")
    print("  what make that number mean anything.")


if __name__ == "__main__":
    main(sys.argv[1:])
