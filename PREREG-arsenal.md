# Pre-registration: pitch-arsenal mixture

Written 2026-08-24, BEFORE running anything. The decision rule is fixed here
so that the result cannot be chosen after the fact.

This exists because the last arsenal attempt measured 9.79% against 9.79% —
a dead-even zero — and left behind a tempting sub-threshold hint: every HIGH
K line improved (k 7.5 +0.67pp, AUC 0.813 -> 0.822; k 6.5 +0.62pp) while low
lines and outs got slightly worse. Selecting the four lines that rose is
exactly how findings get manufactured. So the lines and the bar are named
now.

## The hypothesis

A pitcher's arsenal is a property of the PITCHER, so every one of the nine
hitters faces the same mix. That is why it should survive where handedness
did not: platoon effects vary by batter and average out across a lineup,
while an arsenal does not. Measured per-start mean k-multiplier sd was
0.0642 with a range of 0.864-1.180 — the variance is genuinely there.

## What changes from last time

1. **A mixture, not a multiplier.** The old code collapsed the arsenal into
   one scalar and multiplied the aggregate rate by it, which discards the
   structure and double-shrinks (the aggregate is already shrunk, and the
   multiplier is built from shrunken components). The new form resolves the
   matchup inside log5, per pitch type, weighted by usage:

       P(K) = sum over pitch types t of
              usage_p(t) * log5(k_batter(t), k_pitcher(t), league_k(t))

2. **Scored on TOTALS, not prop lines.** The product is F5 and full-game
   team totals. The old test scored per-start prop Brier.

3. **A materially different simulator underneath** — rotation-starter
   baselines, SAC/HBP/CS/SB/WP, inherited runners, fielding errors, a
   sampled bullpen and a full two-sided game.

## The decision rule, fixed now

**Primary endpoint.** Mean CRPS on per-side F5 runs (`fitf5.evaluate`) over
the held-out window, arsenal ON versus OFF, at n_sims >= 400, scored across
>= 6 salts and compared with the PAIRED standard error (`fitf5.accept`).

**Ship it only if BOTH hold:**

  * the paired difference is negative by at least **2 standard errors**, and
  * the sign is the same on the full-game total CRPS.

Two sigma, not one. The in-search bar of one sigma already let noise through
once today and only the holdout caught it.

**Secondary, reported but NOT decisive:** Kalshi CLV on F5 and game totals.
Reported because it is the money question; not decisive because it carries
known contamination (hook, patience and leash were fitted on the full season
including the scored dates).

**Explicitly NOT an endpoint:** per-start prop Brier on K or outs lines, and
any subset of lines chosen after seeing results. If the mixture only helps
high-K prop lines again, that is a NULL for this project's stated goal.

## What counts as a null

Anything short of the bar above. A null gets recorded in
`NOTES-context-layer.md` alongside the other six measured negatives, and
`USE_ARSENAL` stays off. Seven for seven would itself be a finding worth
writing down: it would say the market prices every mechanism we can import,
and that our only durable edge is being early.

## Known risk

This is the seventh imported-baseball-knowledge attempt. Six returned zero.
Prior honestly somewhere near 30%.
