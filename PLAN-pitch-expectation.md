# PLAN — pitch-level expectation: what he threw, to whom, and whether the
# outcome was the one the pitch deserved

**RUN AND CLOSED 2026-09-07. THE VERDICT: the instrument works, the
per-start quantities are REAL, and NOTHING PREDICTS THE NEXT START.**
The expectation and the residual are both reliable WITHIN a night
(split-half SB 0.54 and 0.22 on 17,762 starts, negative control 0.00) —
and all four next-start candidates came back dead at the pre-registered
bar. RELIABLE IS NOT PREDICTIVE, and that distinction is the finding.
This is a fourth and much sharper measurement agreeing with `form.py`:
"he does not have it tonight" is a real property of the night that
cannot be seen the morning before. Nothing shipped; nothing in `src/`
was touched. The E0/E1 surface survives as the reusable asset the last
section of this plan anticipated. Full log in `NOTES-context-layer.md`.

Written 2026-09-07, out of the zone->BB session, on the operator's
directive: go GRANULAR. Not season tables crossed against season tables —
per pitch: type, physics, location, count, batter, and the outcome, all
of which sit in our own cache. The question a granular model can ask
that nothing else here can: **was tonight's result the expected one for
the pitches he actually threw?**

## WHY THIS IS NOT THE DEAD ARSENAL, and say so when opening it

Arsenal died three times (PREREG-arsenal.md, PREREG-arsenal-contact.md)
as IMPORTED season-level quality tables scored as static edges — the
information was already priced into everyone's aggregate rates, so
crossing the tables double-counted what log5 knew. This item COUNTS
outcome expectations per pitch from our own four seasons and reads
DEVIATIONS from them — the same implementation change (imported static
-> counted drift) that turned velocity and zone% from dead features into
shipped terms. That is what re-opening requires. The prior is still
modest and the batter-side branch is expected to die; the bar is written
below before anything runs.

## WHAT IS ALREADY ESTABLISHED, and constrains the design

  * Raw per-start whiff% is NOISE (split-half r ~ 0, measured,
    `pitch_one.py`). Any per-start read this plan produces must BEAT
    that measured zero, not argue with it.
  * The physicals (velo, spin, break) are reliable per start but only
    velo predicts anything ALONE (spin +2.5 sigma weak, break dead —
    `stuff_screen.py`). The open possibility is that they earn their
    keep as a COMPOSITE — through a fitted expected-whiff surface — a
    genuinely different construction from screening them one at a time.
  * Anything shipped from here must add BEYOND the two live channels on
    this data: velo->K and zone->BB. Both go in every screen as
    controls.
  * ~3M pitches, four seasons, with batter identity on every one
    (`matchup.batter` beside the pitcher in every cached play).

## THE DATA ROW, one per pitch

    pitcher, batter, date, count (balls-strikes), pitch type,
    velo / spin / ivb (deviations from THIS pitcher's own season mean
    for THIS type), location (pX/pZ), and the outcome as a small
    alphabet: ball / called strike / swinging strike / foul / in play
    (+ batted-ball quality if `mlb_batted` joins cleanly).

Extraction extends the ONE walker (`scratchpad/velo_build.py` pattern);
do NOT store 3M raw rows if aggregates serve — design the extract around
the models below, and print coverage before anyone reads a number.

## STEP ONE — THE EXPECTATION LADDER, counted, each rung validated
## before the next is added

E0  league P(outcome | pitch type, count, coarse location) — the floor.
E1  + batter: his own counted deviation per context, SHRUNK at a
    measured rate (`stabilise.py` discipline — count the shrinkage,
    do not guess it).
E2  + pitch physics: the velo/spin/break deviations.

Fit before `HOLDOUT` (2026-07-01), score log-loss + calibration on
held-out pitches, POSITIVE CONTROL each rung (plant a known effect,
confirm the harness sees it). Each rung must beat the previous on
held-out pitches or it does not join. The pitch-level n (~3M) means
power is not the issue; leakage and double-counting are.

## STEP TWO — THE RESIDUAL INSTRUMENT, the single-pitcher walk again

One pitcher first (the standing directive). Per start: expected whiffs /
balls / contact from the ladder, summed over his actual pitches, beside
the actual counts — "he threw 34 sliders in good spots at full break and
got two whiffs; expectation was seven."

THE MEASUREMENT THAT DECIDES EVERYTHING DOWNSTREAM, same instrument as
`pitch_one.py`: split-half reliability across starts of

  (a) actual minus expected (is over/under-performance a repeatable
      trait once the pitch quality is removed?), and
  (b) the EXPECTATION itself (is "what his stuff deserved tonight" a
      more reliable per-start read than the raw outcome was?).

Pre-registered expectations, to be confirmed or refuted: (b) reliable —
it is built from physicals that measured 0.8-0.99; (a) mostly noise —
it is whiff% with the good part subtracted. If (a) comes out reliable,
that is a latent skill/deception channel nothing in the engine carries,
and it jumps the queue.

## STEP THREE — SCREENS, only for what step two admits, bar fixed now

Same harness shape as `stuff_screen.py`, features strictly prior,
positive control planted per candidate. THE BAR: |t| >= 3 pooled WITH
velo AND zone controlled, same sign all four folds; 2-3 sigma
consistent = log, do not wire.

  1. EXPECTED-WHIFF DRIFT -> next-start K. The composite-stuff test:
     recent expected-whiff per pitch vs own season mean. This is where
     spin and break get their one chance to matter jointly.
  2. RESIDUAL DRIFT -> next-start K/BB, only if step two's (a) is
     reliable.
  3. BATTER-SIDE: per-batter deviation vs pitch-type expectation,
     split-half across each batter's halves — persistence measured
     BEFORE any matchup screen. This is granular arsenal-x-batter; the
     three dead runs say it dies; if it lives, the usable form is a
     log5 adjustment per PA and the quadrature warning applies to any
     claim about nine of them adding up.

## PRE-REGISTERED HOUSEKEEPING

  * Leverage screen the winner (`scratchpad/leverage.py`) before wiring;
    the floor decides priority, not admissibility.
  * Collisions: velo->K, zone->BB, START_K_SIGMA, NIGHT_SIGMA. Any
    shipped term shrinks the sigmas per the ledger rule.
  * Battery around any wire, fork-safety flag exported, diff reported.
  * The paired per-start check (velo/zone precedent) is the decisive
    read; pooled battery rows are expected flat for discrimination
    terms.
  * Sized for a full session (likely Opus): the extraction plus E0/E1
    is a sitting on its own; steps two and three another. Stop at any
    rung that fails — the ladder is ordered so partial credit is real
    (a validated E0/E1 surface is reusable even if every screen dies).
