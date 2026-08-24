# Pre-registration: arsenal mixture on CONTACT QUALITY

Written 2026-08-24 BEFORE running anything, and before the contact channel
was wired. The strikeout version has already been tested and failed; this
fixes the rule for the second channel so the result cannot be chosen after
the fact.

## Why this is a second hypothesis and not a subset fished from a null

The strikeout mixture was measured and is dead — +0.6 sigma the wrong way on
the primary endpoint, and flat (-0.2 sigma) in EVERY quartile of mixture
deviation, including lineups it moved 7.5-16%. There is no subset in which
it helps.

The contact channel was never wired at all. `BatterRates` carries two
arsenal slots and only one was used:

    arsenal_k_mult   mixed per pitch type   TESTED, DEAD
    arsenal_mult     contact quality        left at 1.0, NEVER TESTED

`mixture.league_by_pitch` already computes wOBA per pitch type; it was
simply never consumed.

**And contact is the more plausible channel for this project's target.**
Strikeouts move OUTS, which is the half measured to carry no edge for two
days running (CLV z 1.3 against strikeouts' 43.5). Team totals are runs, and
runs come from what happens when the ball is put in play. A pitch mix a
hitter squares up produces harder contact, not just fewer whiffs.

## What gets wired

The same construction as the K mixture, on wOBA instead of whiff:

    quality(b, p) = sum over pitch types t of
                    usage_p(t) * woba_matchup(b, p, t)

rescaled against a league-average arsenal so a neutral mix returns exactly
the aggregate, then applied through `BatterRates.arsenal_mult`, which
already scales home runs and BABIP inside `pa_outcome`.

## The decision rule, fixed now

**Primary endpoint.** Paired CRPS on per-side F5 runs, HELD-OUT window
(on/after 2026-07-01), contact mixture ON versus OFF, n_sims >= 60, six
salts, compared with the PAIRED standard error.

**Ships only if BOTH hold:**

  * the paired difference is negative by at least **2 standard errors**, and
  * the sign agrees on the game-total term.

Identical bar to the K test. Not renegotiable after seeing the number.

**Reported but NOT decisive:** anything on the training window, any
per-pitcher or per-matchup subset, Kalshi CLV.

**Explicitly NOT an endpoint:** prop lines of any kind, and any subset
chosen after seeing results. If contact only helps some slice, that is a
NULL and it goes in the notes beside the other eight.

## Prior

Eight for eight on imported baseball knowledge, and the K version of THIS
construction just failed. Honestly below 25%. The reasons to run it anyway
are that the channel is genuinely untested, it routes to runs rather than
outs, and the wiring already exists.


---

## RESULT (run 2026-08-24, held-out window, 1,106 sides)

                    CRPS      side     total    runs     sd
    baseline     1.63698   1.19874   1.75294    2.45   2.25
    contact      1.63937   1.20114   1.75292    2.44   2.25
    ACTUAL                                      2.45   2.31

    PRIMARY: total CRPS   +0.00239 +/- 0.00347  (+0.7 sd)
    side CRPS             +0.00240 +/- 0.00287  (+0.8 sd)
    game-total term       -0.00002 +/- 0.00329  (-0.0 sd)

**DO NOT SHIP.** Needed <= -0.00694; got +0.00239, the wrong way.

Both arsenal channels are now dead, and the two nulls are nearly identical
(+0.6 sd for strikeouts, +0.7 sd for contact). The pitch-arsenal data does
nothing to a team total whether routed through whiffs or through contact
quality, and the strikeout version was additionally flat in EVERY quartile
of mixture deviation.

What was ruled out, so nobody re-runs it: the scalar-multiplier construction
(9.79% vs 9.79%, day two), the per-pitch-type MIXTURE on strikeouts, and the
per-pitch-type mixture on contact. Three constructions, one dataset, no
signal.

One assumption remains untested and is recorded rather than defended: the
contact multiplier is a single wOBA-derived number applied identically to
home runs and BABIP. A hitter who squares up a slider might get more doubles
without more homers. Splitting the channel is the only version of this idea
left, and given three nulls the prior on it is low.
