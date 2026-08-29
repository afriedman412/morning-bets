"""Does a manager leave a DEALING starter in longer?

    venv/bin/python -m scratchpad.hook_dominance

QUESTION    Conditional on everything the hook already reads — pitches,
            runs allowed, baserunners allowed, inning, batters faced — does
            HOW WELL HE IS PITCHING TONIGHT change the removal decision?
            Unit of observation: one real starter removal decision.

WHY IT MATTERS, AND IT IS TODO ITEM 7. The model's K per 27 outs by start
length runs 8.42 / 8.05 / 7.51 against a real 8.33 / 7.98 / 8.49. The two
short buckets match to a tenth and then the model keeps DECLINING where
reality JUMPS. A real seven-inning start is a SELECTED population, earned by
missing bats — and the simulator has no selection at all, because every
input to its hook is traffic or workload. It literally cannot tell a
dominant night from a lucky one. Consequence: it prices a high-strikeout
over at about 60% of true (o8.5 0.060 against 0.095, -3.9 sigma).

HYPOTHESIS  The coefficient on strikeout RATE so far is NEGATIVE — the
            better he is going, the less likely he comes out — and it is the
            missing selection.
            FALSIFIER: a coefficient inside the resolvable band, or one that
            does not hold its sign across the four seasons. Either would say
            managers are not reading dominance separately from traffic, and
            item 7's mechanism would have to be sought in `PITCH_COST`
            instead.

THE CONFOUND THAT DECIDES THIS, AND IT CUTS BOTH WAYS. Strikeouts are
mechanically entangled with the columns already in the model:

  * a strikeout is an out that allowed no baserunner, so `k` is negatively
    correlated with `br` and `runs` by construction;
  * a strikeout costs ~4.97 pitches against ~3.25 for a ball in play, so a
    high-K outing reaches any given pitch count in FEWER batters.

So the honest specification controls `pitches`, `bf`, `runs` and `br`
TOGETHER, and asks what dominance adds on top. Dropping any one of them
hands its variance to the strikeout column. Both a COUNT and a RATE are
screened, because they are different questions: `k` grows with the outing
and partly re-expresses `bf`, while `k_rate` is what "he is dealing" means.

POSITIVE CONTROL: inject a known coefficient and confirm recovery, because
a mis-specified mechanism and an absent effect produce identical output.
"""
from __future__ import annotations

import json

import numpy as np

from scratchpad.hook_margin import control, fit, power, report, xy

#: NEVER FIT ON ROWS THAT WILL BE SCORED ON. Same cutoff `shape.py` and
#: `fitf5` evaluate from — one cutoff for the whole project, because two is
#: how one of them drifts. See CLAUDE.md; this was got wrong on 2026-08-29.
HOLDOUT_CUT = "2026-07-01"


def train_only(rows):
    """Rows strictly before the holdout. Call it before ANY fit."""
    return [r for r in rows if r.get("date", "") < HOLDOUT_CUT]

CACHE = "/tmp/hook_rows.json"

#: THE FULL CONTROL SET, per the docstring. `abs_margin` is in it because
#: it is now a shipped term (`Hook.mid_per_abs_margin`) and leaving a
#: shipped mechanism out of the control set would let this one absorb it.
MID_BASE = ("pitches", "inn_br", "runs", "onbase", "inning", "bf",
            "abs_margin")
BND_BASE = ("pitches", "runs", "br", "inning", "bf", "tto", "abs_margin")


def seasons(pop, base, extra, label):
    print(f"\n  --- {label}: PER SEASON ---")
    for yr in ("2023", "2024", "2025", "2026"):
        sub = [r for r in pop if r["date"][:4] == yr]
        if len(sub) < 5000:
            continue
        X, y = xy(sub, base + extra)
        b, se = fit(X, y)
        i = len(base)
        print(f"    {yr}  n {len(sub):>7,}  {extra[0]:<8} "
              f"{b[i]:>+9.5f} +/- {se[i]:.5f}  z {b[i]/se[i]:>+5.1f}")


def main():
    rows = json.load(open(CACHE))
    rows = train_only(rows)   # THE GUARD, ACTUALLY CALLED
    mid = [r for r in rows if not r["ends_inning"]]
    bnd = [r for r in rows if r["ends_inning"]]
    print(f"{len(rows):,} starter decisions, {min(r['date'] for r in rows)} "
          f"to {max(r['date'] for r in rows)}")
    kr = np.array([r["k_rate"] for r in rows])
    print(f"  k_rate mean {kr.mean():.4f}  sd {kr.std():.4f}  "
          f"p10 {np.percentile(kr, 10):.4f}  p90 {np.percentile(kr, 90):.4f}")
    print(f"  A COEFFICIENT IS PER UNIT OF RATE, so multiply by "
          f"{np.percentile(kr, 90) - np.percentile(kr, 10):.3f} to read the "
          f"p10-to-p90 swing in log-odds.")

    for name, pop, base in (("BOUNDARY", bnd, BND_BASE),
                            ("MID-INNING", mid, MID_BASE)):
        print(f"\n{'='*66}\n{name}\n{'='*66}")
        power(pop, base, ("k_rate",), f"{name} strikeout rate")
        power(pop, base, ("k",), f"{name} strikeout count")
        print("\n  POSITIVE CONTROLS")
        control(pop, base, ("k_rate",), -2.0, "k_rate x-2.0")
        control(pop, base, ("k",), -0.10, "k count x-0.10")
        report(pop, base, ("k_rate",), f"{name} + strikeout RATE")
        report(pop, base, ("k",), f"{name} + strikeout COUNT")
        seasons(pop, base, ("k_rate",), f"{name} k_rate")


if __name__ == "__main__":
    main()
