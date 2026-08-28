"""Shrink the field-state multipliers by their own noise, then renormalise.

    venv/bin/python -m scratchpad.state_shrink

A cell seen 704 times must not shout as loudly as one seen 37,162 times.
This is the same move `stabilise.py` makes and it is measurement rather
than tuning: there is no loss function here, only the observed spread and
the binomial noise inside it.

    tau^2 = max(0, var(observed multipliers) - mean(se^2))
    shrunk = 1 + (m - 1) * tau^2 / (tau^2 + se^2)

A channel whose entire spread is explained by its own noise gets tau^2 = 0
and collapses to all-ones, which is the correct answer for it and is what
should happen to home runs.

RENORMALISED AFTER SHRINKING, because shrinking toward 1.0 does not
preserve the frequency-weighted mean exactly, and a table that does not
average to one ADDS OFFENCE instead of redistributing it.
"""
from __future__ import annotations

import json
import statistics as st

STATS = ("k_pct", "bb_pct", "hr_pct", "babip")


def main():
    raw = json.load(open("scratchpad/state_table.json"))
    cells = sorted(raw, key=lambda c: tuple(int(x) for x in c.split(",")))
    out = {c: {} for c in cells}
    print(f"  {'stat':<9}{'tau':>8}{'mean se':>9}{'kept':>8}   shrunk multipliers")
    for stat in STATS:
        m = [raw[c][stat] for c in cells]
        se = [raw[c][f"se_{stat}"] for c in cells]
        var_obs = st.pvariance(m)
        var_noise = st.mean(s * s for s in se)
        tau2 = max(var_obs - var_noise, 0.0)
        w = [tau2 / (tau2 + s * s) if (tau2 + s * s) > 0 else 0.0 for s in se]
        sh = [1.0 + (mi - 1.0) * wi for mi, wi in zip(m, w)]
        # RENORMALISE to a frequency-weighted mean of exactly 1.
        n = [raw[c]["_n"] for c in cells]
        mean = sum(ni * si for ni, si in zip(n, sh)) / sum(n)
        sh = [s / mean for s in sh]
        for c, s in zip(cells, sh):
            out[c][stat] = round(s, 4)
        print(f"  {stat:<9}{tau2 ** 0.5:>8.4f}{var_noise ** 0.5:>9.4f}"
              f"{st.mean(w):>8.2f}   "
              + " ".join(f"{s:.3f}" for s in sh))
    # A channel that collapsed to all-ones is DROPPED rather than shipped as
    # a dict of 1.0s: `odds_mult` short-circuits on exactly 1.0, so either
    # works, but an absent key says "measured, nothing there" and a key full
    # of ones reads like an oversight.
    for c in cells:
        for stat in STATS:
            if abs(out[c][stat] - 1.0) < 0.002:
                del out[c][stat]
    print("\n  STATE_MULT = {")
    for c in cells:
        on, outs = c.split(",")
        body = ", ".join(f'"{k}": {v}' for k, v in sorted(out[c].items()))
        print(f"    ({on}, {outs}): {{{body}}},")
    print("  }")
    json.dump(out, open("scratchpad/state_mult.json", "w"), indent=1)


if __name__ == "__main__":
    main()
