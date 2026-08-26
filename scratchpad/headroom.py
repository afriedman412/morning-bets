"""How much of the knowable is the model already getting, per stat?

    venv/bin/python -m scratchpad.headroom [n_draws] [cutoff]

WHY THIS AND NOT `scratchpad/ceiling.py`. That one subtracted the model's
own within-start variance from the actual variance and reported an outs
ceiling BELOW our own correlation, because the simulator is over-dispersed
per start. A ceiling estimated with the model in it is only as good as the
model. This uses a one-way ANOVA on ACTUAL values grouped by pitcher —
(MSB - MSW)/n0, so sampling noise is removed — which touches no model at
all. `between_sd / total_sd` is then the correlation a PERFECT forecaster
would achieve.

LIKE FOR LIKE, WHICH IS THE POINT. The recorded numbers compare our
correlation on one population against a ceiling computed on another. Day
eight put our K correlation at 0.496 and day nine put K's ceiling at 0.428 —
which would mean we had beaten a perfect forecaster. Both are right; they
are measured on different populations. With openers IN, K's ceiling is 0.491
and outs' is 0.599; with only arms meant to go long, 0.428 and 0.330. So the
population has to be declared, and it is declared here.

READ `share` AND NOT `corr`. A correlation of 0.30 against a ceiling of 0.33
is a nearly exhausted target; the same 0.30 against a ceiling of 0.60 is
half the prize still sitting there.

IT MUST BE A HOLDOUT, and the first version of this file was not. Run over
the whole season with `paired_cases()` and no cutoff, a pitcher's rates are
computed from every start he made INCLUDING the one being predicted — a
12-strikeout game raises his season K%, which then "predicts" that game. It
reported K at 112% OF A PERFECT FORECASTER'S CEILING, which is the useful
kind of impossible: a number above 100% is a leak announcing itself.

So rates are frozen strictly before `cutoff`, only starts after it are
scored, and the LEASH IS SWITCHED OFF — `hook_leash.json` is fitted on the
full season too, and would leak the same way. That makes the outs figure a
LOWER bound (day eight measured the leash worth +0.105 -> +0.226 on outs out
of sample); the K figure is barely affected, since the leash moves length
rather than rates.
"""
from __future__ import annotations

import random
import statistics as st
import sys

from src.context import calibrate as cal
from src.context import leash, sim
from src.context.sources import rates as rate_src

STATS = (("outs", "o", "outs"), ("k", "k", "k"))


def anova(by: dict) -> tuple:
    """(between_sd, within_sd, total_sd, ceiling) on ACTUAL values."""
    by = {p: v for p, v in by.items() if len(v) >= 2}
    n = sum(len(v) for v in by.values())
    k = len(by)
    grand = sum(sum(v) for v in by.values()) / n
    ssb = sum(len(v) * (st.mean(v) - grand) ** 2 for v in by.values())
    ssw = sum(sum((x - st.mean(v)) ** 2 for x in v) for v in by.values())
    msb, msw = ssb / (k - 1), ssw / (n - k)
    n0 = (n - sum(len(v) ** 2 for v in by.values()) / n) / (k - 1)
    betw = max((msb - msw) / n0, 0.0) ** 0.5
    tot = st.pstdev([x for v in by.values() for x in v])
    return betw, msw ** 0.5, tot, (betw / tot if tot else 0.0)


def main(argv):
    n_draws = int(argv[0]) if argv else 30
    cutoff = argv[1] if len(argv) > 1 else "2026-07-01"
    sim.USE_LEASH = False
    lg = sim.league()
    keep = leash.intended_starters(before=cutoff)

    print(f"  holdout: rates before {cutoff}, starts on or after it, "
          f"leash OFF")
    pairs = cal.paired_cases(since=cutoff, rates_before=cutoff)
    pens = rate_src.bullpens(lg)
    # {(game_id, pitcher): (actual_row, [predicted outs], [predicted k])}
    pred: dict = {}
    rng = random.Random(0)
    for i, pair in enumerate(pairs.values()):
        for _ in range(n_draws):
            r = cal.replay(pair, lg, pens, rng)
            for case, line in zip(pair, (r.away_sp, r.home_sp)):
                s = case[0]
                if s["player_name"] not in keep:
                    continue
                key = (s["game_id"], s["player_name"])
                e = pred.setdefault(key, (s, [], []))
                e[1].append(line.outs)
                e[2].append(line.k)
        if (i + 1) % 300 == 0:
            print(f"    {i + 1}/{len(pairs)} games", flush=True)

    print(f"\n  population: arms meant to go long, {len(pred)} starts, "
          f"{n_draws} draws each\n")
    print(f"  {'stat':<7}{'actual sd':>11}{'between':>9}{'ceiling':>9}"
          f"{'our corr':>10}{'share':>8}{'our spread':>12}")
    for name, col, attr in STATS:
        idx = 1 if attr == "outs" else 2
        by: dict = {}
        for (_g, nm), (s, _o, _k) in pred.items():
            by.setdefault(nm, []).append(s[col])
        betw, _within, tot, ceil = anova(by)
        act = [s[col] for s, _o, _k in pred.values()]
        mu = [st.mean(e[idx]) for e in pred.values()]
        corr = st.correlation(act, mu)
        print(f"  {name:<7}{tot:>11.2f}{betw:>9.2f}{ceil:>9.3f}"
              f"{corr:>10.3f}{corr / ceil:>8.0%}{st.pstdev(mu):>12.2f}")

    print("\n  'our spread' is the sd of our per-start predicted means. It is")
    print("  the model's own differentiation, and it caps `our corr` however")
    print("  well aimed the predictions are.")
    print("  Leash OFF and rates frozen, so outs is a LOWER bound.")


if __name__ == "__main__":
    main(sys.argv[1:])
