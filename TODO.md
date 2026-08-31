# TODO — the running list

Started 2026-08-29 (day fifteen). **The backlog, not the log.** What was
measured and why lives in `NOTES-context-layer.md`. When something ships,
delete it here and write the result there.

Roughly ordered by runs per day of work. The leverage floor (~0.05 runs) is
a BETTING threshold and decides ORDER, never admissibility — a small,
counted, reliability-gated mechanism ships and accumulates (CLAUDE.md).

Each item says what is ESTABLISHED and what is not, because the expensive
mistake here is re-running something that already has an answer.

**THE FOUR-SEASON RESCAN IS DONE (2026-08-29) AND ITEMS 6, 13 AND 18 SHOULD
BUILD ON IT.** `scratchpad/state_counts_4season.json` holds 748,905 plate
appearances over 9,978 cached games, keyed by season and (men on, outs).
`state_seasons.py` is the scan and carries the stability gate. Items 6
(per-runner speed) and 18 (steal decisions) key on the SAME cell and need
only runner and batter IDs carried through the same pass; item 13
(per-pitcher hbp/wp) is the same pass grouped by pitcher. Extend that scan
rather than writing a third one.

**TWO FIGURES IN THE OLDER NOTES ARE RETRACTED (2026-08-30).** The model is
NOT light on runs. Verified on 1,645 games: F5 -0.047 (0.6 sigma), F3
-0.024, F7 -0.040. The "3% fewer runs" and "4.5% light" lines are from a
previous engine and do not reproduce. Only the first inning survives, at
-1.7 sigma. Anything reasoning from a run deficit — runline pricing above
all — needs re-deriving.

## WORKING ONE ITEM PER SESSION — read this first

Items are written to be picked up COLD. If one is not self-contained enough
to start from, that is a defect in the item; fix the item before starting
the work.

Before touching anything:

  1. `git status` must be CLEAN. If it is not, find out what is in the tree
     before adding to it — `scratchpad/mutate.py` refuses to run dirty, and
     an unexplained diff in `sim.py` is indistinguishable from your own.
  2. `venv/bin/python -m tests.run` — 414 checks, ~45s. Know it was green
     BEFORE you started.
  3. `venv/bin/python -m scratchpad.fingerprint 400 6` — one hash over
     2,400 simulated games. Record it. Any change that is meant to be inert
     must reproduce it exactly, and any change that is not must be able to
     say why it moved.

Then: write QUESTION / HYPOTHESIS / TEST / EVALUATE / CONCLUSION /
NEXT STEPS out as literal headers, state the POWER before the result, and
state the STANDARD ERROR of anything you are about to call a finding. Three
predictions failed on 2026-08-29 and two null results were misread as
regressions at 0.2 and 1.0 sigma, in both cases because the number
disagreed with a prediction and got scrutinised while the agreeable ones
did not.

Finish by deleting the item here and writing the result in
`NOTES-context-layer.md`. An item that ships and stays on this list is
worse than one that was never written.

---

**1. WITHDRAWN — the model reaches extras at roughly the right rate.**
Model 0.078 against a real 0.083, se 0.006. The "5.4% / 3.3% against 8.3%"
that made this item 1 was `simulate_game` skipping the track block on the
break that ends a game when the home side wins in its half — games ending on
the winning half read as nine innings and fell out NON-RANDOMLY. Fixed.
One-run games 0.247 against a real 0.266 (1.9 sigma) is mildly low and is
the only survivor; not its own item.

**6. Per-runner speed.**
Reliability +0.834 — the most repeatable player-level quantity measured in
this project. (Triple share +0.506; pitcher HBP +0.711 and was judged worth
wiring.)
The model has NO per-runner speed anywhere. `STEAL_TABLE` is keyed on (base
state, outs) alone; `FIRST_TO_THIRD_ON_1B`, `SECOND_SCORES_ON_1B`,
`FIRST_SCORES_ON_2B` and the `ADVANCE_*_ON_OUT` tables are keyed on the out
count alone. A burner and a backup catcher are the identical baserunner.
Reliability is settled, SENSITIVITY is not. Run `leverage.py` first —
reliability without sensitivity is how park died three times.

**7. SHIPPED 2026-08-31 — the counted MID hazard. The BOUNDARY backbone is
what is left, and it is now the top modelling item.**

`sim.USE_PITCH_HAZARD = True`, `sim.USE_PITCH_HAZARD_BND = False`: counted
MID backbone, parametric BOUNDARY. Four-fold cross-validated on the outs
ladder — the 12.5-17.5 band improves in ALL FOUR seasons by a consistent
-0.016 to -0.018, the long lines are untouched, and the mean-outs error
halves rather than flipping. Runs unmoved across the prefix ladder. It
closes the fourth-inning over-pull (+0.033 -> -0.007), because 60-85 pitches
IS the fourth inning and those were one defect, not two.

TAKING BOTH CURVES WAS SCORED AND LOST. Dead heat on all-line error (0.0215
against 0.0223) and worse on everything else: it nearly doubled the
long-line error and turned a 0.2-out shortfall into a 0.18-out overshoot in
every season. Half the change beat all of it.

**7a. RE-SOLVE THE BOUNDARY BACKBONE AGAINST THE MODEL'S OWN STATES.**
`PITCH_HAZARD_BND` misses its own buckets: cell error 0.0265 -> 0.0314,
WORSE than the parametric curve it would replace, under-pulling from 60
pitches up (-0.018, -0.020, -0.088, -0.057, -0.084 against real holdout
rates). The cells were solved conditional on REAL game states and are being
applied to OURS, which are calmer.

THE FIX IS TO ITERATE THE SOLVE, NOT TO RE-CENTRE IT. Ask what value each
bucket needs so that OUR SIMULATED GAMES produce the REAL rate, run, adjust,
repeat. That is still measured entirely against real baseball — it just
checks the answer where it gets used rather than where it was counted.
Re-centring on our own occupancy was proposed and REJECTED: it makes the
aggregate land while leaving every individual situation wrong and buries a
measurement of how far our states sit from real ones. `scratchpad/
hz_cells.py` is the harness and the bar is fifteen buckets, fifteen real
rates.

WHAT IT IS WORTH, measured after the ship (`scratchpad/outs_split.py`):
the biggest single cell error left is the CLEAN SIX-INNING START — real
0.230 of starts, ours 0.198, and the missing mass sits on four-inning
walk-offs (+0.023) and starters yanked with two down in the fifth (+0.018).
And at every round number we under-produce the man who came back out and was
chased without an out (15 outs: real 14.5% of that spike, ours 9.5%).

**AND RE-MEASURE `scratchpad/outs_adjust.py` THE SAME SITTING.** Twelve
seconds. Shipping the mid hazard already took a third of the correction's
job (band |correction| 0.045 -> 0.031); the boundary one will move it again.

**7d. PITCH x INNING — REFUTED ON CROSS-VALIDATION. DO NOT REFIT WITHOUT
READING THIS.** `sim.USE_PITCH_X_INNING` is False and stays there.
`PXI_BND` / `PXI_MID` are solved conditional on the other shipped terms and
wired, and they do not transfer: boundary better in 2 folds of 4 and WORSE in
2023, mid worse in 3 of 4, and the mid offset trends by season (+0.0428 in
2023 to +0.0181 in 2026) rather than being the constant a single fold
suggested. The RAW phenomenon is real — 70 pitches in the third is pulled
6.01% against 1.62% in the fifth — but the table is not portable, and the
counted MID hazard that shipped closes the fourth inning anyway. Day twenty
parts two and three in the notes.

AND PITCHES PER INNING IS OLDER, DEADER GROUND. It folds back on itself:
high pitches-per-inning EARLY means FEW total pitches, so it measures
non-monotone (1.68% / 4.77% / 3.14%) against a monotone 75x span for raw
pitch count. Day seven measured and rejected it; day twenty re-derived the
same U-shape before finding the note.

**7b. WHAT IS ALREADY DONE ON THE K TAIL — do not re-run.**
Dominance shipped (`late_mid_per_k_rate`), the per-start strikeout draw
counted and shipped (`START_K_SIGMA` 0.1625, which refuted a tuned 0.20),
and `PITCH_COST` CLOSED — its premise was arithmetically wrong, since a
dominant night also needs fewer batters and everyone needs ~99 pitches for
six innings. o8.5 is now -2.3 sigma, from -3.5.

**7c. A DIRECT PROP MODEL IS TESTED AND DEAD.** The learned removal model
beats `sim.Hook` on decision AUC 0.912 to 0.876 and gives a boundary share
of 0.341 against a real 0.672. Do not rebuild props as a separate model.

**8c. EVALUATE THE DOUBLE-SHRUNK PRIOR FIX.** Fitted already, never scored —
it was waiting on the hook work. See item 12 for the defect and the Snell
case. DO NOT re-run `USE_RAW_PRIOR`; it was measured and loses.

**8. Role-based bullpen deployment, and fatigue.**
`build_side` samples 8 arms weighted by appearances and `next_arm` walks that
list IN DRAW ORDER. No leverage — the most-used arm is drawn 84.4% of games
and lands at average slot 3.01 of 8, as likely to pitch the sixth as the
ninth. No situation — nothing knows the score, the platoon or the save. No
fatigue — the pen is redrawn independently every game AND every draw, so
nothing records that an arm threw 30 pitches yesterday.
`deploy.py` measured that role is real and projects (split-half +0.55 to
+0.78 over 319 relievers). SENSITIVITY IS NOW SCREENED TOO
(`scratchpad/deploy_screen.py`, 20,000 paired draws): the oracle ceiling on
re-ordering the same eight arms is 0.618 runs, twelve times the leverage
floor, so this is not a sub-floor mechanism.
**BUT READ WHERE THAT 0.618 COMES FROM BEFORE BUILDING.** A nine-inning game
reaches only ~4.4 of the 8 drawn arms, so most of the ceiling is WHICH arms
are exposed (~0.6 runs), not WHEN each pitches (~0.04). A rule that only
re-times a fixed set of arms buys the small number. The unbounded channels
are SITUATION (a closer appears only in save situations — shape, not mean)
and FATIGUE. Start with exposure: "the manager uses his best available arms
in a close game" is a bigger and simpler lever than a leverage index.
**ITS FORMER HEADLINE EVIDENCE IS GONE.** The ninth-inning gap that item 11b
handed over was two driver bugs, now fixed, and the ninth reads +2.0% / z
+0.3. Do not re-cite it.

**9. Ship and score the seasonal home-run term.**
Measured on 2023-2025; applied out of sample it moves a team total from -3.9%
to +0.7% against actuals. BLOCKED because `fitf5.evaluate` cannot take a
park, so it has never been scored on F5 CRPS. The walk slot it also
needed shipped 2026-08-29.
Until it ships, treat July/August model totals as biased LOW by 0.15-0.20
runs a side.

**10. Get `total_market` to complete a run.**
Full-game totals are a stated product that has never once been scored against
a settled price. `scratchpad/tonight.py` is the workaround.

**11. The first inning is under-scored — STILL LIVE AT -1.7 SIGMA (2026-08-30 ladder, 1,645 games). It is the ONLY surviving run-level defect; F3/F5/F7 are all inside noise.**
RE-MEASURED TWICE on 2026-08-29, the same instrument and the same games
(`where_runs.py --cut 2026-05-15 --profile`): -13.3% / z -2.7 originally,
-12.0% / z -2.5 mid-day, and -0.109 runs / z -2.2 after the half-inning fix.
Reality's first is its highest-scoring inning (1.021), the model's is near
its lowest (0.912). ESTABLISHED and unmoved by everything shipped since —
the half-inning fix cannot touch it, since both halves are symmetric before
the ninth.
**ITS STATED CAUSE IS NOW WEAK, AND THE NOTE OVERSOLD IT.** The reason to
suspect `TTO_MULT` was a "monotonic decay shaped like a lineup pass" across
innings 1-3. Innings 2 and 3 were NEVER individually significant — z -1.4
and -1.2 then, -1.5 and -0.5 now — and inning 3 has drifted to -2.5% with
inning 4 at +0.3%. The decay dies by the third inning, faster than a lineup
pass. Field state is separately RULED OUT as the cause of the TTO decay
(`scratchpad/tto_state_overlap.py`, +23.8% charged against -0.19% implied,
positive-controlled). So this needs a mechanism specific to the FIRST
INNING, not to the first lineup pass.

**11c. Extra innings are now reached too often.**
OPENED BY THE 11b FIX, and unconfirmed. P(extras) 0.102 against a real 0.083
(z +2.0) and extra innings/game 0.147 against 0.114 (z +2.1); it was 0.079
before the half-innings were corrected. Runs per extra half is still short at
2.689 against 3.026. `scratchpad/ninth.py` is the instrument.
Two sigma on a quantity nobody pre-registered — treat as a direction.

**11d-residual. The model produces less home-field advantage than the league
has — 0.263 runs against a counted 0.306. NOT AN ITEM YET.**
0.8 sigma, a direction and not a finding, recorded so it is not re-derived.
**DO NOT CLOSE IT BY TUNING `HOME_OPP_*`** — each is counted at 4-11 sigma on
its own rate, and moving them to hit a run target is the forbidden
solve-for-a-level. The residual belongs to home/road channels with NO
parameter at all: fielding errors, baserunning, and the structural effect of
batting last. Home runs were counted (0.9710, z -2.2) and deliberately left
on the contact constant rather than given one.

**12. The prior is shrunk twice.**
`_load_seasons` loads prior seasons through `pitcher_rates`, which already
shrank them, and `shrink_target` shrinks again with the same constant.
Home-runs-sized: a pitcher keeps 0.418 of his own homer record where pooling
once gives 0.568. K is only 2.6%. Worth ~0.044 runs.
The naive fix (`USE_RAW_PRIOR`) was scored and LOSES — +0.00944 F5 CRPS,
z +2.6, 4/4 salts. DO NOT re-run it. The real fix is one shrink against a
DISCOUNTED sample, and that discount has never been measured: `PRIOR_DECAY`
discounts the RATE and nothing discounts the SAMPLE.

**13. Per-pitcher hit-by-pitch, and per-pitcher wild pitch.**
Previously discarded for sitting under the leverage floor; admissible now.
HBP reliability +0.711, sd 0.00675, p10 0.0043 against p90 0.0200, ~0.035
runs pitcher-only and near 0.05 with the batter side. Wild pitch +0.657 and
~0.020 runs.

**14. Attribute a disagreement on the board.**
The biggest edges arrive with no cause attached. On 2026-08-27 six of the top
ten rows were ONE lineup effect and it took a manual investigation to see it.
Attribute each gap to pitcher / lineup / park, and group correlated markets.

**16. Propagate projected-lineup uncertainty.**
Two wrong names out of nine moved a headline edge by half. Flag any edge
whose size depends on unconfirmed names.

**17. Per-pitcher pitch efficiency.**
`PITCH_COST` is counted now and the start-level residual is still sd 8.2
pitches: the table has the LEVEL right (85.5 against a real 85.6) and cannot
say WHO is efficient. Pitches per plate appearance are correlated within a
start, so this is a per-pitcher trait rather than noise. Feeds the hook,
which keys on pitch count. Reliability unmeasured — screen before building.

**18. Steal decisions should depend on the runner and the hitter.**
`STEAL_TABLE` is keyed on base state and outs alone, so a steal is
independent of who is running and who is batting. That independence is WHY
the runner-event reorder washed out — the pairing carries no information.
Same table and same code as per-runner speed (item 6); screen them together.

---

## Parked — measured, decided against. Re-open only if the APPROACH or the DATA changes, and say which.

**Runner-event reorder — real defect, no measurable gain.** An at-bat
resolves against a state one event stale: at-bat N sees at-bat N-1's
steals, not its own. Reordering fixes that and buys nothing, because the
staleness shifts uniformly and the same at-bats meet the same distribution
of states — measured +0.037 PA/game against a predicted -0.18, runs noise.
The at-bat reality VOIDS is the one in progress during the steal, which a
plate-appearance-granular model does not have at all; that part needs
pitch-level simulation. `game.USE_RUNNERS_FIRST`, off, switchable.

**Per-hitter hit mix.** True spread 13.4% of the level, reliability +0.209,
~0.010 runs a game per hitter and ~0.030 across a lineup by quadrature. Home
run rate predicts a hitter's extra-base share (+0.196) BETTER than his own
doubles rate does (+0.115), so if revisited, impute it from power. Plumbing
exists — `hit_mix` is a field on `Matchup`, not a global.

**Mid-plate-appearance removals.** 13 of 2,848 pitching changes, 0.456%. The
model rolls removal between plate appearances and is right 99.5% of the time.
Recorded so it is not asked a third time.

**Fatigue vs familiarity in the TTO decay.** Cannot be separated — pitch
count is CAUSED by the outcome being measured, so every stratification
selects on strikeouts. Two designs tried, both contaminated; the second
looked like a clean fatigue result (z +4.12) and is mean reversion. The
pooled within-start decay is -14.9% and that is the quotable number.
NOT FULLY ACADEMIC: if it is fatigue, an efficient starter should decay less
than a labouring one and the model charges them identically — a candidate
for the missing K spread (sd 2.23 against 2.49).

**Score-dependence of the plate appearance.** K% 19.79 with a 4+ lead against
23.19 tied, but that is almost certainly WHO IS PITCHING — mop-up arms in
blowouts. Confounded by reliever quality; do not build on it without
controlling for the arm.


---

## Shipped 2026-08-29/30 (days seventeen and eighteen) — the hook

Full write-ups in `NOTES-context-layer.md`. All counted on real removal
DECISIONS, never on runs, and all now refit-verified on training rows only.

  * `mid_per_abs_margin` -0.0824 — the BLOWOUT term, unsigned. The signed
    form measures zero on both curves, so the specified parameter was the
    wrong shape and would have closed the question as a null.
  * `late_mid_per_k_rate` -1.5130 — DOMINANCE. Until this, every input to
    both hook curves was traffic or workload.
  * `START_K_SIGMA` 0.1625 — per-start strikeout variation, COUNTED, and it
    refuted a tuned 0.20 by 4.2 sd. The clearest case in the project's
    history of a count correcting a fit.
  * `per_pen_back2` / `per_pen_rest` on BOTH curves — bullpen availability,
    the first external signal the boundary decision ever accepted. About WHO
    CANNOT GO, not pitches thrown. Needs no deployment model.
  * `high_pitch_*` — a third branch above 90 pitches. Fixed o18.5/o20.5 and
    made the middle band worse, which is what motivated item 7.
  * The HOLDOUT RULE in CLAUDE.md, with `train_only()` in the fitters.

## Shipped 2026-08-29 — delete from above, recorded in the notes

**The home/road constants, recounted — and walks got their own** (was 11d).
`HOME_OPP_K` 1.034 -> 1.026 and `HOME_OPP_CONTACT` 0.981 -> 0.990, both
overstated by 3.5-4.1 sigma against a recount on 679,329 plate appearances.
THE REAL FINDING IS THE FOURTH CHANNEL: walks were riding the contact
constant at 0.9804 where their own count is 0.9493 (z -6.6), the LARGEST of
the three splits and the one with no parameter. New `HOME_OPP_BB` 0.974.
Recounting alone OVERSHOT (model home-away 0.382 -> 0.174 against a counted
0.306); the walk channel brought it to 0.263.
COUNTED ON UNINTENTIONAL WALKS ALONE — `bb_pct` is walks and HBP is drawn
off the top on its own rate, so a walks+HBP figure would not match the code
path. HBP has NO home/away split (0.9992, z -0.0). The cascade audit is
COMPLETE: sacrifices split too (0.9207, z -3.4) but are worth ~0.0015 runs
and need plumbing that does not exist. That overshoot is why the
constants were NOT nudged back up — it was read as a missing mechanism and
the same scan named it. Away/home asymmetry on team totals 0.208 -> 0.044.
Real home-field advantage COUNTED on this league is 0.306 runs (se 0.044,
z +6.9), twice the 0.1-0.15 an outside guess supplies.

**The half-innings were reversed, and the walk-off fired on the first run**
(was 11b). Two correctness bugs in `simulate_game`. The side named `away` is
a PITCHING side facing the HOME club, so calling it first batted the home
club in the top of every inning — the away club reached the ninth in 46.7%
of games against a real 1.000. And `home.opposing_runs = home.runs` handed
the walk-off the BATTING club's own score, truncating every ninth and extra
inning at the first run (34 of 42 scoring halves ended on exactly one).
Innings 9+ -17.4% / z -2.9 -> +2.0% / z +0.3; whole game -7.1% -> -4.5%;
away-club totals ~-0.61 -> -0.305 and home-club ~+0.15 -> -0.097.
INNINGS 1-8 CANNOT MOVE — both rules key on `regulation` — so no F5 number,
ladder or CRPS run in this project's history is affected. That symmetry, plus
the two errors nearly cancelling in the only place anyone looked (a COMBINED
per-inning total), is why it survived. Two regression checks, each verified
by mutation. 411 -> 413 checks, fingerprint 93af75e7 -> 5a39453e.

**Hit-by-pitch by field state** (was 4). `STATE_MULT` gained an `hbp_pct`
column and `pa_from` now moves `hbp` and its renormaliser `cond` together.
Survives shrinkage with the largest tau of the five channels but keeps only
36% of its raw spread — the men-on / empty ratio lands at 1.112 against a
counted 1.266. Overall rate flat, K/PA flat, x5 control scales.
FOLLOW-UP WORTH TAKING: `state_counts.json` is 2026 only and the cells are
thin. Rescanning 2023-2026 sharpens all five channels at once and this is
the one that needs it most.

**Rank by gap over simulation error** (was 15). `price.py` now sorts on
`z = gap / se` and prints the column. The estimate is least reliable where
the gap is largest, so a tail gap and a central gap were never the same
evidence.

**Walks have an `odds_mult` slot** (was 3). `Matchup.m_bb`,
`NEUTRAL_PARK["bb"]`, `park_mults` reads Savant's walk index — which
`sources/park.py` had always fetched and this had always discarded, so every
park test ever run here excluded walks by construction. Inert, fingerprint
unchanged. Three tests, and it broke `check_park_index_100_is_neutral`
immediately, which is that check doing its job.

**`_track` fires on every exit path in `simulate_game`.** The prefix block
sat after the `break` that ends a game when the home side wins in its half,
so the DECIDING inning was never recorded — `prefix[9]` missing for ~40% of
games, and the notes carried a standing "take 9+ as the residual" warning.
Found while measuring extras, where it drops precisely the walk-off halves
and therefore the highest-scoring ones: runs per extra half read 0.553
against a real 1.049 while the half-inning itself produced a correct 0.969.
Verified inert on outcomes — fingerprint unchanged with the auto runner off.
