# Day eight — between-game differences, on starter outs

Scratch notes; folded into `NOTES-context-layer.md` and `RESUME.md`.

## The ceiling question, and why the first answer was wrong

`ceiling.py` decomposes `var(actual) = var(true per-start mean) +
E[within-start var]`, taking the within term from our own simulation. On
3,600 real starts that reported an outs ceiling of 0.250 with us at 105% of
it — an impossible number, and the tell that the estimator had failed.

It failed because our within-start spread on outs is 3.84 against a real
3.50: the simulator is over-dispersed per start, and subtracting a
too-large within understates the between.

`between.py` does it MODEL-FREE instead — a one-way ANOVA on the ACTUAL
values grouped by pitcher, `(MSB - MSW)/n0` so sampling noise is removed.
That is a LOWER bound on real between-start variation, because opponent,
park and rest all vary inside a pitcher's own season too:

    stat  actual sd  between  within  our within  our spread  share
    outs       3.96     1.77    3.50        3.84        0.57    32%
    k          2.44     1.10    2.17        2.03        1.02    93%
    h          2.23     0.67    2.12        1.96        0.45    67%
    bb         1.30     0.39    1.24        1.28        0.39   100%
    er         1.99     0.41    1.94        1.78        0.29    71%

OUTS IS THE OUTLIER. Everything else is 67-100%; outs is 32%.

## What is missing is a LEASH, and the five columns say so together

Leave-one-out per-pitcher residual (a group mean recomputed excluding the
target start, so no-effect scores zero rather than the negative artifact):

    outs +0.295*   k +0.008   h +0.063*   bb -0.086*   er +0.012   (*|z|>3)

The pitcher's rates are estimated over his own season, so his per-batter
performance is right by construction — and the columns agree: no stable
per-pitcher residual on strikeouts, walks, hits or earned runs. Only outs.
The one thing outs depends on that the other four do not is the manager.

## Everything else measured null on the residual

    is_home +0.005   night +0.019   park runs -0.032   days rest +0.014
    pen outs yesterday +0.037   pen outs last 2 +0.009   month +0.039

None worth more than 0.15 outs against 1.77 of real variation. So the
answer to "do we have park effects" is: yes, and on this target they are
worth nothing, measured directly rather than inferred.

`predicted outs` correlates +0.123 (z 7.4) with its OWN residual, which is
a CONTROL firing: our predictions are compressed, not mis-directed. The fix
is to differentiate more, not to add a feature.

## The club is dead for the sixth time, and the split-half is a trap

Chronological split-half on the club residual reads r +0.595, which PASSES
the bullpen-role gate (+0.55..+0.78). It is measuring which ARMS a club
runs out, not how patient its manager is. Fitted in the correct order
(club first, pitcher against the remainder) a club offset is worth +0.090
-> +0.122 out of sample alone and makes things WORSE on top of the pitcher
offset (+0.234 -> +0.227, MAE up).

## It is not blowups

RESUME recorded from day six that per-pitcher leash variation is "mostly
blowups, not real". Rebuilt from a 20% TRIMMED mean of prior residuals the
gain is identical (+0.354 against +0.354 for the plain mean); from the
prior MEDIAN, +0.336. A statistic that discards his worst starts predicts
just as well.

## The openers, and the honest size of this

The short-leash end of the built file is entirely relievers clamped at the
sweep boundary — PJ Poulin, Lake Bachar, Wandy Peralta. `ROTATION_MIN_GS =
5` admits openers, and they were being simulated with a starter's hook.
That is a real defect the mechanism fixes, but it is not the interesting
claim, so it was separated out:

    holdout, live starts     base corr   +leash   RMSE base   RMSE leash
    all                          0.075    0.268       3.831        3.697
    median outs >= 12            0.077    0.182       3.613        3.550
    median outs >= 15            0.051    0.099       3.591        3.555

Most of the headline gain is openers. On GENUINE rotation arms the effect
is smaller and still real: correlation more than doubles and RMSE falls
0.063. The true per-pitcher leash sd among rotation arms is ~0.9-1.1 outs,
not the 1.77 that includes openers.

## Out-of-sample, through the shipped code path

Rates before 2026-07-01, leash file built `--before 2026-07-01`, scored on
the 1,125 starts after it:

                     OFF      ON
    outs spread     0.56    1.29
    outs corr      0.105   0.226      (model-free ceiling 0.294-0.318)
    of ceiling       33%     71%
    sd(p) @ 15.5   0.060   0.127      <- the Brier resolution term
    median values      8      17

Every downstream stat improves too, which is what one simulator buys:
k +0.389 -> +0.408, h +0.207 -> +0.235, er +0.044 -> +0.063.

## THE WIRING GAP — the most important find of the day

The first paired prefix ladder printed EXACTLY +0.0000 at F1, F3, F5 and F7
over 1,615 games. That is not "the ladder cannot see a hook change", which
is true and expected; it is the flag not arriving.

`game.build_side` never called `sim.for_start`. Every caller passes
`hook=None`, which fell through to a bare league `Hook()` — so the club and
per-pitcher offsets reached `sim.simulate_start` and NEVER REACHED A FULL
GAME. The start-level path is what `calibrate`, `quote`, `price` and `f5`
use; the engine that produces TEAM TOTALS, the stated product, ran without
any of it.

An identical-to-four-decimals A/B is a plumbing result, never a null.
Guarded now by `check_the_leash_reaches_a_full_game_and_not_only_a_start`,
mutation-verified — the mutated run reproduces the exact `(15.4125,
15.4125)` signature.

## Measured, not tuned

Two constants could have been searched here and neither was. Shrinkage K is
`within_var/between_var` off the ANOVA (the normal-normal posterior),
recomputed from whatever window `build()` is given. The outs-to-log-odds
conversion is INTERPOLATED through a measured sweep, not regressed onto a
slope — the curve bends (-2.0 buys +3.00 outs where the local slope
promises +3.36), and fitting a line through counted points is the mistake
RESUME records against the advance-on-out hazard.

The sweep also shows the knob moves a start's LEVEL without inflating its
own spread (outs sd 4.10 at -0.6, 4.00 at 0, 3.83 at +1.0). A mechanism
that bought differentiation by widening every start would not be worth
having.

## A check that guarded nothing

`check_the_offset_never_leaves_the_measured_sweep` asserted the clamp
against `OFFSET_CLAMP` itself and passed just as happily at 99.0. Found by
mutation, which is the only way this surfaces. Rewritten to bound against
the measured table's own endpoints. That is now the seventh vacuous check
in this project.
