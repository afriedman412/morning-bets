"""The blowout-hook A/B, scored on its PRE-REGISTERED falsifier.

    venv/bin/python -m scratchpad.blowout_ab [n_sims]

QUESTION    Does `Hook.mid_per_abs_margin` — the measured suppression of
            MID-INNING removals once the score gap widens — move the
            simulated start-length distribution toward reality, and does it
            cost the settlement quantity? Quantities: the BOUNDARY SHARE
            (what fraction of starts end on a completed inning), starter
            outs, and F5 runs allowed per team-side scored as discrete CRPS
            over the full support. Population: holdout games, rates frozen
            before the cutoff. Unit of observation: one start for the
            length columns, one team-side for F5.

HYPOTHESIS  The term only ever REMOVES mid-inning pulls (it is negative and
            |margin| >= 0), so starts that would have ended mid-inning now
            run to the end of the inning instead. The boundary share must
            RISE toward the real 0.669, and mean outs must rise slightly.
            PRE-REGISTERED BEFORE RUNNING, from the coefficient alone:
            mean |margin| at the hook is 1.68, so the mean log-odds shift is
            -0.138 and the mid-inning pull odds fall about 13%.

            FALSIFIER 1: the boundary share does not move, or moves DOWN.
            That would mean the term is not reaching the decision, which is
            the same failure the signed `mid_per_margin` had for months.
            FALSIFIER 2: outs overshoot past the real 15.82. The term has no
            free parameter to absorb that — it is counted, not fitted, so an
            overshoot is evidence the coefficient is carrying something else.

WHAT THIS CANNOT SHOW, and it is the honest limit. F5 CRPS is dominated by
the bulk of the run distribution and this changes only WHICH ARM throws the
late innings of a decided game. A flat F5 result is the EXPECTED outcome
(CLAUDE.md: "a flat CRPS on such a change is the expected result rather than
a refutation — the loss cannot resolve it"), so F5 is reported here as a
DID-NOT-HARM check and not as the evidence for the mechanism. The evidence
is the boundary share, which is counted on real games.

POSITIVE CONTROL: a third arm at x4 the measured coefficient. A term that
is wired but unreachable and a term that is genuinely small produce the same
near-flat table, and only the control separates them.
"""
from __future__ import annotations

import multiprocessing as mp
import random
import statistics as st
import sys
from collections import Counter

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src

HOLDOUT = "2026-07-01"
_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 20
_COEF = 0.0


def _one(args):
    i, gid = args
    v = _CASES[gid]
    home = next(x for x in v if x[0]["is_home"])
    away = next(x for x in v if not x[0]["is_home"])
    an = cal.adjust_lineup(away[2], False)
    hn = cal.adjust_lineup(home[2], True)
    out = []
    for draw in range(_SIMS):
        # SAME SEED ACROSS ARMS. The arms differ only in the coefficient,
        # so every difference below is the mechanism and not the dice.
        rng = random.Random(7 + i * 100003 + draw)
        hk = sim.Hook(mid_per_abs_margin=_COEF)
        A = game.build_side(away[1],
                            _PENS.get((away[0]["team"] or "").upper(), []),
                            hn, hk, rng, team=away[0]["team"])
        H = game.build_side(home[1],
                            _PENS.get((home[0]["team"] or "").upper(), []),
                            an, sim.Hook(mid_per_abs_margin=_COEF), rng,
                            team=home[0]["team"])
        r = game.simulate_game(A, H, _LG, rng, track=(5,))
        f5 = r.prefix_side.get(5)
        for sp in (r.away_sp, r.home_sp):
            # `outs % 3 == 0` AND NOTHING ELSE, because that is
            # `calibrate._boundary` and therefore the definition every
            # historical number in this project uses — including the 0.669
            # actual, which comes from real out totals where no
            # `pulled_mid_inning` flag exists. Adding the flag here made
            # the model column stricter than the actual it is compared
            # against and read 0.520 where the same engine scores 0.588.
            out.append({
                "outs": sp.outs, "k": sp.k,
                "boundary": sp.outs % 3 == 0,
            })
        if f5:
            out[-1]["f5"] = f5[0]
            out[-2]["f5"] = f5[1]
    return out


def crps(dist: Counter, n: int, actual: int, top: int = 14) -> float:
    """Discrete CRPS over the FULL support — no book's lines involved."""
    c = tot = 0.0
    for v in range(top + 1):
        c += dist.get(v, 0) / n
        tot += (c - (1.0 if v >= actual else 0.0)) ** 2
    return tot


def main(argv):
    global _CASES, _PENS, _LG, _SIMS, _COEF
    _SIMS = int(argv[0]) if argv else 20
    shipped = sim.Hook().mid_per_abs_margin
    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    gids = sorted(pairs)
    _CASES = {g: pairs[g] for g in gids}
    _LG = sim.league(before=HOLDOUT)
    _PENS = rate_src.bullpens(_LG, before=HOLDOUT)

    # ACTUAL start lengths on the same games, for the boundary share and
    # the outs level. The actual side is the binding sample and is stated
    # before the table, not after it.
    act_outs = [s[0]["o"] for v in _CASES.values() for s in v
                if s[0].get("o") is not None]
    act_bnd = sum(1 for v in act_outs if v % 3 == 0) / len(act_outs)
    se = (act_bnd * (1 - act_bnd) / len(act_outs)) ** 0.5
    n_start = 2 * len(gids)
    print(f"  {len(gids)} games x {_SIMS} sims  "
          f"({n_start * _SIMS:,} simulated starts per arm)")
    print(f"  POWER: the actual side is {len(act_outs):,} real starts. "
          f"Boundary share {act_bnd:.4f} +/- {se:.4f}.")
    print(f"  The gap being chased is {act_bnd - 0.588:+.3f}, "
          f"{abs(act_bnd - 0.588) / se:.1f} sigma of the ACTUAL's own "
          f"error.")
    print(f"  The model-vs-model arms are PAIRED on seeds, so a difference "
          f"between\n  columns is far sharper than that — the se above "
          f"bounds the claim\n  'reality is now matched', not the claim "
          f"'the term moved the model'.\n")

    arms = (("OFF", 0.0), ("SHIPPED", shipped), ("CONTROL x4", shipped * 4))
    got = {}
    for name, coef in arms:
        _COEF = coef
        with mp.get_context("fork").Pool(max(1, (mp.cpu_count() or 2) - 1)) as p:
            rows = [r for g in p.map(_one, list(enumerate(gids))) for r in g]
        f5 = [r["f5"] for r in rows if "f5" in r]
        got[name] = {
            "coef": coef,
            "outs": st.mean(r["outs"] for r in rows),
            "outs_sd": st.pstdev([r["outs"] for r in rows]),
            "bnd": st.mean(1.0 if r["boundary"] else 0.0 for r in rows),
            "k": st.mean(r["k"] for r in rows),
            "f5_mean": st.mean(f5),
            "f5_sd": st.pstdev(f5),
        }

    print(f"  {'':<22}" + "".join(f"{a[0]:>12}" for a in arms)
          + f"{'ACTUAL':>10}")
    for label, key, actual in (
            ("coefficient", "coef", None),
            ("boundary share", "bnd", 0.669),
            ("starter outs", "outs", 15.82),
            ("  sd", "outs_sd", 4.040),
            ("starter K", "k", 4.84),
            ("F5 runs / side", "f5_mean", 2.437),
            ("  sd", "f5_sd", 2.313)):
        a = f"{actual:>10.3f}" if actual is not None else f"{'':>10}"
        print(f"  {label:<22}"
              + "".join(f"{got[n[0]][key]:>12.4f}" for n in arms) + a)

    print("\n  READ THE CONTROL FIRST. If x4 does not move the boundary "
          "share well past\n  the shipped arm, the term is not reaching "
          "the decision and the shipped\n  column is uninformative rather "
          "than small.")


if __name__ == "__main__":
    main(sys.argv[1:])
