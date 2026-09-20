# PLAN — pitch-history modeling: tracking stuff from our own pitch data

Written 2026-09-07, out of the Cease board session. The operator's
directive that frames the whole item: **start with ONE pitcher — walk his
stuff start by start through a season and see what is actually there —
before building any league-wide feature.** Exploration first, wiring
later, falsifiers in between.

**RUN THE SAME DAY, steps one and two both — results below in each
section and in `NOTES-context-layer.md`. One survivor shipped
(`sim.USE_ZONE_BB`, zone drift -> next-start BB%). What remains open
here is the ADJACENT leash-recency item and the operational stopgap at
the bottom.**

## WHY THIS EXISTS

The box score is a bad thermometer for stuff and the radar gun is a good
one — that is now measured, not asserted:

  * A recent-window K% fade carries +0.18 ± 0.08 of its face value into
    remaining starts; the 63 biggest faders (-4.8 pts recent) ran only
    -1.2 ± 0.7 under their season rate afterward. ~80% of a fade is the
    window's own sampling noise. (day 22, third sitting)
  * Recent fastball velo vs own season mean predicts the NEXT start
    directly: +1.63 ± 0.28 K% pts per mph, positive all four seasons.
    With velo and bb controlled, the K-drift main falls 0.18 -> 0.04 —
    the persistent share of a fade largely IS the velocity component.
  * That term SHIPPED as `sim.USE_VELO_K` (2026-09-07). It is the first
    column pulled from the per-pitch data, chosen for reliability, not
    the only one there.

The generalisation this plan is built on: fastball velocity was one
physical, per-pitch measurement averaged over ~50 pitches a start. The
cache holds several more.

## THE DATA — verified in the cache 2026-09-07

Per pitch, in every cached game: pitch TYPE code, startSpeed, spinRate,
breakVertical (full breaks object), plate coordinates pX/pZ, and the
CALL (ball / foul / swinging strike / in play). 10,021 games, four
seasons; `scratchpad/velo_build.py` already walks exactly this data and
produced 19,273 starter-start velocity rows with 99.5% coverage. Extend
that extractor; do not write a second one.

## STEP ONE — THE SINGLE-PITCHER INSTRUMENT (the directed starting point)

One pitcher (Cease is the topical pick; Holmes the counter-case), every
2026 start, one row per start per pitch type: n, mean velo, mean spin,
mean vertical break, zone% (fixed-zone from pX/pZ), whiff/swing, next to
the start's K/BB/outs.

AND THE RELIABILITY MEASUREMENT, which is the actual point of step one:
split each start's pitches odd/even, compute every stat on both halves,
correlate the halves across his starts. That is the per-start
reliability of each column, measured, on the data we own.

**AN HONEST NULL TO SETTLE FIRST: "per-start whiff% is mostly noise" was
asserted in-session from binomial arithmetic (~45 swings -> ±6-7 pts SE)
and has NEVER been measured here.** Step one's split-half table settles
it. Expected ordering, to be confirmed or refuted: physical measurements
(velo, spin, break — instrument reads, hundreds of observations per
start) reliable; outcome rates (whiff%, chase%, zone-contact) unreliable
at n=1 start. If whiff% comes out reliable, the expected ordering is
wrong and the candidate list reorders.

**MEASURED 2026-09-07 (`scratchpad/pitch_one.py`, Cease 2026 n=28,
Holmes 2026 n=15 and 2025 n=32; planted/noise controls SEEN in every
run): the expected ordering is CONFIRMED.** Spearman-Brown full-start
reliability on primary types — velo 0.89-0.99, spin 0.79-0.98, vertical
break mostly 0.8+; zone% 0.1-0.5; whiff/swing r -0.30..+0.22, i.e.
noise. Whiff is OFF the candidate list; location stays, last. The walk
itself earned its keep: Cease's FF sat 97-98 through 2026-07-08, an
8-pitch start on 07-14, and 95-96 ever after — a 2 mph regime change the
box score never printed (his K totals held).

## STEP TWO — CANDIDATES, in the order the reliability table justifies

Each candidate is the same shape as the shipped velo term: recent-window
value minus OWN season mean, screened for whether it predicts the NEXT
start's K/BB beyond what fastball velo already carries.

  1. SECONDARY-PITCH VELO — a slider 2 mph slow is a different pitch;
     FB-secondary gap travels with it.
  2. SPIN RATE drift — physical like velo, similar per-start n.
  3. BREAK drift (vertical first).
  4. LOCATION — zone%, scatter around intent. The command channel; shows
     up in walks only later, so it may lead bb_pct.
  5. Whiff by pitch type — ONLY if step one's reliability table admits
     it. This is the box-score trap wearing pitch-type clothes unless
     the number says otherwise.

Screen harness exists: `scratchpad/streaks.py` (9,382 rows, positive
control — a planted velo-gated fade — SEEN at 10.1 sigma). Reuse it.

**SCREENED 2026-09-07 (`scratchpad/stuff_screen.py`, 9,382 rows, bar
pre-registered in the docstring, positive control 8-13 sigma per
candidate; extraction extended in `scratchpad/velo_build.py`, one
walker as directed):**

  1. SECONDARY-PITCH VELO -> K: DEAD (+0.2 sigma, sign flips).
  2. FB SPIN -> K: WEAK (+2.5 sigma, positive all four seasons but
     never individually; logged, not wired).
  3. FB VERTICAL BREAK -> K: DEAD (+0.6, sign flips).
  4. ZONE% -> K: DEAD (+0.3). ZONE% -> BB: **ALIVE AND SHIPPED** —
     -5.3 sigma pooled with velo controlled, same sign all four
     seasons, and it STRENGTHENS to -5.9 with the box-score walk drift
     in the fit while the walk drift itself carries -2.0: command
     drift is real and the plate coordinates lead the walk column, the
     mirror of velo-vs-K-streak. Shipped as `velo.bb_kick_for` /
     `sim.USE_ZONE_BB` at the train-only -0.1431/share (8,240 rows).
  5. WHIFF BY TYPE: gated out by step one, never screened.

## PRE-REGISTERED, before any wiring

  * FIT BEFORE `HOLDOUT` (2026-07-01), score across the FOUR FOLDS
    (`pxi_cv.py` pattern), bar stated before the run.
  * POSITIVE CONTROL every screen — plant the effect at claimed size,
    confirm the harness sees it, exactly as streaks.py did.
  * COLLISIONS, the velo-term checklist applies verbatim: START_K_SIGMA
    and NIGHT_SIGMA both live on this channel. 10.4% of NIGHT_SIGMA is
    already attributed to counted k-stuff — every term that ships from
    here SHRINKS those sigmas per the maintenance rule; re-run
    `night_variance` after each.
  * THE DEAD-LIST NOTE: "arsenal" died here twice (PREREG-arsenal.md) as
    IMPORTED season-level pitch-quality features scored as static edges.
    This item is within-pitcher DRIFT counted from our own cache — a
    different implementation, which is what re-opening requires. Say so
    in the log when opening it.
  * THE BATTERY TRAP from day 22: battery.main re-execs the interpreter
    on macOS, resetting in-process globals — export
    OBJC_DISABLE_INITIALIZE_FORK_SAFETY and confirm the flag prints in
    the battery header, or five candidates produce five identical
    fingerprints again.

## THE ADJACENT ITEM, related but SEPARATE: leash recency

The Cease miss (2026-09-07) was not stuff at all: K rate right, start
length wrong — leash fitted flat over 2023-26 (his offset -0.44, career
~16 outs) while 2026-him averages 17.4 and last-eight ~19. Usage is a
DECISION and persists; rates are noisy and do not. The rate half-life is
dead (16/16 K cells worse) but the outs channel improved on the one fold
where nothing was co-fitted, and the day-22 log pre-registers the
follow-up: a PER-CHANNEL half-life, outs/leash only, K flat, own
falsifier. Do not fold it into the stuff item — different mechanism,
different falsifier, and the half-life wiring already exists in
`pitcher_rates` switched off.

## OPERATIONAL STOPGAP, until any of this ships

The board flag proposed in-session: print each starter's real last-10
average outs beside the sim's mean; 2+ outs of divergence flags the row
the way `proj lineup` does. Display only, no engine change — it would
have caught Cease on sight.
