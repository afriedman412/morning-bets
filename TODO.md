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
previous engine and do not reproduce. Anything reasoning from a run deficit
— runline pricing above all — needs re-deriving.
**UPDATED 2026-09-09:** the "only the first inning survives, at -1.7 sigma"
line that sat here is also retracted. On the battery's four folds the first
inning is z -1.5 and the SIXTH is the largest per-inning gap at z -2.2. See
item 11.

## PITCH-LEVEL EXPECTATION — RUN 2026-09-07, CLOSED WITH A NULL

`PLAN-pitch-expectation.md`, the granular re-open of arsenal. The
expectation surface got built and validated (E0 384 cells on 2.9M
pitches; E1 batter offsets, shrinkage measured at K=84 swings) and the
per-start quantities are REAL within a night — but NOTHING predicts the
next start, all four candidates dead at the pre-registered bar. Do not
re-run the screens. The reusable leftovers are `scratchpad/pitch_e0.py`
and `pitch_e1.py`. The one branch never tested is the batter-side log5
matchup adjustment, and after five dead arsenal constructions its prior
is low. Full result in the notes; the sentence to remember is RELIABLE
IS NOT PREDICTIVE.

## PITCH-HISTORY MODELING — RUN 2026-09-07, mostly CLOSED

Steps one and two of `PLAN-pitch-history.md` are DONE and the results are
in the notes: per-start reliability measured on Cease and Holmes
(physicals reliable, whiff/zone outcome rates noise at n=1 start), then
the league-wide screen — secondary velo, FB spin, FB vertical break and
zone->K all dead or weak; ZONE->BB ALIVE and SHIPPED as `sim.USE_ZONE_BB`
(-0.1431/share, 4.9 sigma train-only, survives the box-score walk drift).
STILL OPEN from that plan: the per-channel leash half-life (outs only, K
flat) — pre-registered day 22, the Cease board miss (2026-09-07) is its
poster case, wiring exists switched off in `pitcher_rates`. And the
stopgap: board flag for sim-vs-last-10 outs divergence, display only.

**THREE MORE POSTER CASES, 2026-09-09, and they point at STALENESS
specifically rather than at the leash being wrong in general.** Each arm's
shipped `sim.leash` offset against what he actually did in 2026:

  * Yoshinobu Yamamoto, offset -1.16 (the largest magnitude on the board).
    Career 17.60 outs a start, 2026 **19.68**. We price over 18.5 outs at
    40.5% against his own 2026 rate of 52.0% (13/25, se 10.0).
  * Cristopher Sanchez, offset -0.89. Outs by season 15.9 -> 16.9 -> 18.8
    -> 18.1. Our K line implies 21.9 batters faced against the market's
    24.0 and his own ~25; the outs market confirms it independently
    (our over 18.5 at 36.0% against Kalshi 47.4%).
  * Rhett Lowder, offset -0.16. Over 14.5 outs: his 2026 76.2% (16/21),
    ours 66.1%.

**THE SIGN WAS READ BACKWARDS WHEN THIS WAS FIRST WRITTEN (2026-09-09,
corrected same day).** `team_offset` is added to a REMOVAL hazard, so a
NEGATIVE offset buys a LONGER outing — `OUTS_PER_OFFSET` says -2.0 maps to
+3.00 outs. All three arms above already carry a negative offset pushing
them longer, and we STILL price them short of their own record. So the
offset is not fitted short; it is not moving FAR ENOUGH.

THAT REWRITES THE HYPOTHESIS INTO A BETTER ONE — COMPRESSION, not
staleness. The base hook regresses everyone toward a generic length and
the per-pitcher offset under-corrects, so short-leash arms are run too
long and long-leash arms are pulled too short. That single mechanism
explains the poster cases AND the counter-evidence below, which staleness
never did. `OFFSET_CLAMP = 2.0` caps the whole adjustment at about +/-3.3
outs, which is the structural reason it cannot reach an opener.

FIRST CUT, and it is NOT a finding: regressing (our implied outs line -
his own 2026 mean) on (his own 2026 mean) over 12 arms gives slope -0.42,
r -0.56. **THE TEST AS RUN IS CONFOUNDED AND MUST NOT BE QUOTED.** His own
mean appears on BOTH sides and is measured on ~25 starts, so its standard
error is around 0.9 outs against a between-pitcher spread of about 1.1 —
noise in a regression PREDICTOR attenuates the slope, which is the failure
CLAUDE.md already records for `m_er`. Redo it SPLIT-HALF: estimate his
length on odd-numbered starts, score the residual on even-numbered ones.
The sample is also selected — arms whose implied line falls outside the
printed rungs drop out, which is why Yamamoto and Baz are missing.

**BUT DO NOT PRE-JUDGE THE DIRECTION — the counter-evidence is real and
sits in the same session.** Where the leash table has NO entry the error
runs the other way: Robert Stock (offset 0.0, 13.0 outs a start) priced at
65.4% over 14.5 against his own 33.3%, and Lake Bachar (offset 0.0, 6.9
outs a start) at 61.7% to clear 4.5 K against a market at 7.5%. And Zebby
Matthews has an offset (-0.74) and is STILL too long, 64.5% over 15.5
against 42.2% on 45 starts. So "stale offsets pull too short, missing
offsets run too long" is a HYPOTHESIS with one clear exception, not a
finding.

THE MEASUREMENT TO RUN FIRST, and it is cheap because both halves already
exist: for every start in the holdout, compare the SIMULATED outs
distribution to that pitcher's own trailing record, bucketed by (has an
offset / no offset) and by (offset magnitude). State the power before the
result. If the residual is flat in offset magnitude the staleness story is
dead and the board flag is all that is warranted; if it slopes, the
half-life has its falsifier ready-made.

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
halves rather than flipping.

**RE-RUN 2026-09-09 ON THE CURRENT ENGINE WITH LIVE BULLPENS IN ALL FOUR
FOLDS (TODO 20), and these numbers REPLACE the ones above** — same harness,
`hz_cv 20`, `USE_PITCH_HAZARD_BND` off. Band off -> ON: 0.0850 -> 0.0709
(2023), 0.0576 -> 0.0420 (2024), 0.0408 -> 0.0267 (2025), 0.0557 -> 0.0409
(2026) — **-0.0142 / -0.0155 / -0.0141 / -0.0148, four folds, tighter than
the original range**. Long lines -0.0046 / -0.0047 / +0.0040 / +0.0043, and
mean outs moves +0.08 toward a real 15.60 / 15.74 / 15.78 / 15.75 in every
fold without crossing it. The ship stands on evidence that is now four live
folds rather than one.

Runs unmoved across the prefix ladder. It
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

**RE-RUN 2026-09-09 ON THE CURRENT ENGINE WITH LIVE BULLPENS (TODO 20).
THE REFUTATION HOLDS AND THE BOUNDARY HALF IS UNCHANGED**, `pxi_cv 10`,
cell error off -> ON:

    fold        boundary            mid-inning        mid SIGNED off -> ON
    2023   0.0577 -> 0.0623      0.0223 -> 0.0280      +0.0166  +0.0279
    2024   0.0524 -> 0.0505      0.0177 -> 0.0173      +0.0067  +0.0166
    2025   0.0399 -> 0.0290      0.0172 -> 0.0130      -0.0005  +0.0105
    2026   0.0451 -> 0.0227      0.0181 -> 0.0111      -0.0002  +0.0102

Boundary is still WORSE in 2023, flat in 2024, better in the two most
recent — a table that does not transfer, which is the refutation. The
signed mid offset still trends monotonically by season, so "it is just a
constant" is still one fold's property. WHAT DID CHANGE: the MID half no
longer loses in three folds of four (it is worse in 2023, flat in 2024,
better in 2025-26), because the counted MID hazard SHIPPED after the
original run and the baseline it is scored against is a different, better
one. The verdict is unaffected — the flag stays False on the boundary
half — but do not quote "mid worse in 3 of 4" against the current engine.

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

**11. The first inning — LARGELY CLOSED, AND THE OLD HEADLINE IS RETRACTED.
Re-measured 2026-09-09 on the battery's four folds (post-bullpen-fix): the
gap is -0.036 runs / -3.5% / z -1.5, not the -12% / z -2.5 this item carried
all week.**
The old number came from `where_runs.py --cut 2026-05-15 --profile` on 926
games of 2026 against the 2026-08-30 engine. The battery reads FOUR folds
against the current engine and combines to z -1.5, with the sign stable 4/4
(2023 -0.6, 2024 -0.4, 2025 -1.7, 2026 -0.3). Rule 11 check: these do
measure the same quantity (both are the `where_runs` convention, runs as the
score change across a play), on different games and a different engine, so
the honest reading is that the pitch-hazard / sharpness / opener work
shipped since 2026-08-30 closed most of it.
**IT IS NO LONGER THE LARGEST PER-INNING DEFECT. Inning 6 is, at -0.056
runs / -5.3% / z -2.2, also sign-stable 4/4.** Item 11's replacement, if a
per-inning row is to be chased, is the SIXTH, not the first.

**DO NOT CLOSE THE REMAINDER BY ADJUSTING THE FIRST INNING UPWARD — THE ONLY
COUNTED INNING-1 MECHANISM POINTS THE OTHER WAY.** `scratchpad/inn1.py`
counted, on 306,506 pre-holdout starter plate appearances, what a starter's
rates do in inning 1 against the SAME batters later in the same lineup pass:

    channel   mult      honest z   per-season sign
    k_pct    1.0663       +5.7     +1.4 +2.4 +3.2 +2.7  (4/4)
    bb_pct   0.9883       -0.7     null
    hr_pct   1.0601       +1.3     null
    babip    1.0095       +0.6     null

Real starters strike out ~6.6% MORE in the first inning, and nothing else
moves. More strikeouts is FEWER runs, so wiring this counted table makes the
first inning score LESS — the model is already 3.5% short there — and,
because the pass-1 mean has to stay re-centred, moves K out of inning 2,
where the model is already 3.3% LONG. **Pre-registered: wiring it moves both
rows the wrong way.** So the residual run gap is not a missing inning-1 rate
effect; the standing clustering/advancement defect remains the better
explanation.
The measurement is positive-controlled (+10% injected reads +12.3) and its
null is calibrated over 25 permutations (null mean 0.9954, analytic se
within 8% of the permutation sd on babip/hr). It survives an exogenous
collider control — splitting by LINEUP SLOT 1-3 vs 7-9 instead of by which
inning the PA fell in — at 1.0546, z +3.2.
**THE COLLIDER IS WORTH KNOWING FOR ANY FUTURE INNING-1 WORK:** how many
batters bat in inning 1 IS AN OUTCOME of inning 1. A within-game-side
permutation preserves that count and is therefore NOT a valid null — it read
z +14 on BABIP with nothing injected. Shuffle labels globally instead
(`scratchpad/inn1_dbg3.py` is the discriminator).

Field state was separately RULED OUT as the cause of the TTO decay
(`scratchpad/tto_state_overlap.py`, +23.8% charged against -0.19% implied,
positive-controlled).

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

**14. Attribute a disagreement on the board — RATE or HOOK.**
The biggest edges arrive with no cause attached. On 2026-08-27 six of the top
ten rows were ONE lineup effect and it took a manual investigation to see it.
Attribute each gap to pitcher / lineup / park, and group correlated markets.

THE CONCRETE VERSION, scoped 2026-09-09 after two by-hand spot checks cost a
round of analysis each. A strikeout line is `batters faced x k_pct` — one
equation, two unknowns — so an edge of a given size can be the model
disagreeing about the PITCHER or about the MANAGER, and the printed number
looks identical either way. Those two halves have opposite track records:
the rate is measured accurate to a tenth through K 4.5-7.5, the hook is a
manager decision reproduced only in aggregate.

**THE SPLIT NEEDS TWO MARKETS ON THE SAME START AND THAT IS THE WHOLE
TRICK.** The K market gives `BF x rate`; the OUTS market pins `BF`
independently; rate falls out. From a K line alone the two are
inseparable — do not attempt it, and do not tag a rung whose outs book is
missing (several arms on the 2026-09-09 board had none).

ESTABLISHED, both worked by hand on the 2026-09-09 board:
  * Cristopher Sanchez u6.5 K. Our k_pct 26.4% against his own raw 27.2% —
    essentially exact. The whole 0.54-K gap is exposure: our line implies
    21.9 batters faced, the market's 24.0. The outs market confirms it
    rather than assuming it — our over 18.5 at 36.0% against Kalshi 47.4%,
    his 2026 average 18.1 outs. A HOOK gap with no strikeout opinion in it.
    His leash offset (-0.89) looks fitted on a pitcher who no longer
    exists: outs per start ran 15.9 -> 16.9 -> 18.8 -> 18.1 by season.
  * Shane Baz u4.5 K, the contrast. Rate-driven, and his own under-rate
    trends toward it: 28.6% -> 35.5% -> 46.4% across 2024/25/26.

GENERALISES to earned runs, walks allowed and hits allowed — all the same
`BF x rate` shape with outs as the shared anchor. `kalshi.SERIES_BY_STAT`
ALREADY maps KXMLBERA / KXMLBWA / KXMLBHA and the board prices none of
them. DOES NOT GENERALISE to game, team or F5 totals: no rate-times-
exposure structure and no per-start history for a matchup that has never
happened. Totals get aggregate calibration instead (fair lines averaged
8.41 on 2026-09-08 against the league's ~8.5).

THE SECOND CHECK, and it is weaker — the pitcher's own empirical clear rate
for that exact line, by season, off `mlb_pitching`. A SANITY CHECK, NOT A
VERDICT: n is about 30 starts a season so se is ~9 points, and it is
UNCONDITIONAL while our number is conditional on tonight's nine. The model
is SUPPOSED to disagree with a season average. The decomposition is the
more robust half precisely because the leash barely moves with opponent.

NOT ESTABLISHED, and this is the item: that a hook-tagged gap actually
scores worse than a rate-tagged one. The tag is a plausible story until it
is graded, and a plausible story that reorders a board is exactly the kind
of thing this project has been wrong about before.

FALSIFIER, pre-registered: tag every quoted rung, then score our
probability against the Kalshi mid on OUTCOMES, split by tag. If
hook-tagged rungs do not show worse resolution than rate-tagged ones, the
tag is decoration and comes off the board. This needs stored boards
carrying the mids as they were at print time; `bets/2026_09_08_board.json`
and `bets/2026_09_09_board.json` are the first two and nothing grades them
yet.

**15. THE OPENER — the exit SHIPPED; the typed bulk arm and the slate
override are what remain.**

SHIPPED 2026-09-09 (notes, both entries of that date): `USE_RELIEF_INTENT`
(the follower of an early exit continues like the bulk arm he is) and
`USE_OPENER_EXIT` — a flagged short-yardage starter (avg < 11 outs a
start, the same `slate.priceable` cell, one shared constant now) exits on
a BOOTSTRAP from his own outs record via the existing `forced_exit_outs`
machinery. Measured: flagged arms' outs error +3.40 (6.7 sigma, sd far
too narrow) -> -1.20 (2.4 sigma, sd exact); affected-game totals move
toward actuals (9.01 -> 8.95 against a real 8.49); the intent falsifier's
recorded 4/4-fold failure dissolves to 0.2 sigma on truthful states. The
leash never could reach these arms (`OFFSET_CLAMP` ~+/-3.3 outs against a
needed ~-12). `scratchpad/opener_outs.py` is the instrument; the residual
-1.20 is role-drift staleness in the record, and if refined it gets a
recency WEIGHT, not a curve.

OPERATOR DIRECTIVE 2026-09-09, and it is the shape of the remaining
build: the pitching side of an opener game is a SEQUENCE OF TYPED ROLES —
(opener) -> (bulk arm) -> pen — and the bulk arm is one of THREE types,
counted at 40.6% bona fide starter / 18.6% swingman / 40.8% pure
reliever (full bullpen game). Model each: the starter-as-bulk uses his
own rates plus the counted role diff (interleaved swingmen, relief minus
start: K% +1.01, BB% -0.54, HR% -0.61, BABIP -1.06; per-pitcher does not
repeat, POOLED or nothing — still unwired, nothing consumes it). The
pure-bullpen game is the pen we already sample plus the intent tables.
AND THE SLATE ACCOMMODATES ANNOUNCED COMBOS: the opener and his follower
are usually public before lineups, but `mlb_schedule_with_probables`
carries one arm per side — add a manual override on the slate ("bulk arm:
X") before building any scraper. The step-zero null killed PREDICTING the
follower from history; an announced name is input, not prediction. The
same override should accept "stretching out: X" — a relief-to-rotation
conversion is announced too, and it is the one population the no-record
fallback (`USE_OPENER_POOL`, notes 2026-09-09 third entry) mis-prices:
the pooled curve reads ~6 outs on an arm the club intends to run 10+.

FALSIFIER for the remaining build, unchanged: the run distribution in
opener games against what actually happened. Note `opener_score.py`'s
run-level CRPS se (0.0164 at 124 games x 100 sims) is larger than the
effects measured so far — score the bulk arm on HIS OWN line (outs, K)
the way `opener_outs.py` scores the opener, or the result will read as a
null whatever the truth.

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

**19. MONEYLINES — THE EASY VERSION. Persist the draws, count, score, stop.**
Raised by the operator 2026-09-09. 15 is the opener item, so this is 19.

**STARTED 2026-09-09 — the persist-and-score loop is DONE; pick up from
"WHAT REMAINS" below.** `scratchpad/moneyline.py` replayed all four
folds (3,548 paired games x 200 draws, July-onward, rates frozen at each
cut) and persisted every draw's `(away, home, away_f5, home_f5)` to
`scratchpad/sims/ml_<fold>.json.gz` — gitignored, ~15 min to regenerate,
and the script LOADS the cache when the file exists and `n_sims`
matches, so rescoring is seconds, not minutes. NOTE the engine gained
`USE_OPENER_EXIT` / `USE_OPENER_POOL` the same day (commits baa3b8f,
5db4e17) — the cached draws include them; regenerate rather than mixing
cached and fresh draws across engine states.

ESTABLISHED by that pass, Brier-decomposed on outcomes:

  * CALIBRATION IS GOOD: reliability 0.0005 (F5 winner, no-tie
    conditional, 3,032 games) / 0.0007 (full-game ML, 3,548). Every
    populated decile is inside 2 se except full-game 0.5-0.6 (forecast
    0.544, actual 0.513) — mild home-side overstatement in the modal
    band. F5 tie share 0.151 against a real 0.145 (se 0.006).
  * RESOLUTION IS THIN: 0.0040 / 0.0030 against uncertainty ~0.2495.
    The model hugs the coin flip — 2,861 of 3,548 full-game forecasts
    sit in 0.4-0.6. Whether that clears a vig is a pricing question the
    scored record can now answer; nothing here says it cannot.
  * THE MARGIN CONTRADICTION IS SETTLED AND THERE WAS NONE (2026-09-09,
    fourth entry in the notes; `scratchpad/ml_margin.py` and
    `scratchpad/ml_split.py`, both off the cached draws, no new sims).
    The moneyline pass reads one-run share 0.2929, the battery on the
    same engine reads 0.2917, real 0.2731 — one measurement, and the
    draw count moves it by 0.001. Item 1's 0.247/0.266 is an OLD ENGINE
    number, and the notes' own 2026-09-04 entry had already recorded the
    flip. **THE ITEM'S PREMISE IS REFUTED: the margin is too NARROW, not
    too wide** — mean |margin| 3.330 against 3.594 (se 0.047, -5.6
    sigma), one- and two-run shares HIGH, 8+ low at -3.4 sigma.
  * AND IT IS TWO DEFECTS. Club totals are too narrow (model sd
    3.117/2.988 against 3.208/3.174, home worse) AND the model puts a
    +0.059 correlation between the two clubs' runs where reality has
    -0.022, se 0.017 — 3.5 sigma, and mostly WITHIN a game (+0.048)
    rather than between games. sd(sum) 4.437 against 4.463 is a dead
    heat only because the coupling adds back what the narrow clubs took
    out: A GAME-TOTAL INSTRUMENT IS BLIND TO BOTH DEFECTS AT ONCE.
  * CALIBRATION, step 2, done: slope b 0.774 full-game / 0.804 F5, se
    ~0.13 — leans OVER-confident, which is what too-narrow margins
    predict, but 1.5-1.8 sigma is a direction and not a finding, and the
    forecast sd of 0.067 is why.
  * SPLIT vs SUM, step 4, done, on outcomes rather than on the market:
    every quantity beats a climatology benchmark on discrete CRPS (skill
    +0.0114 sum / +0.0091 team total / +0.0065 margin full-game, and
    +0.0080 / +0.0073 / +0.0059 on F5) and THE MARGIN IS THE WEAKEST OF
    THE THREE IN BOTH WINDOWS.

  * ITEM 20 DOES NOT TOUCH ANY OF THIS, checked with a positive control
    (`pen_check` in `ml_margin.py`): `moneyline.py` passed `season=`
    explicitly, the draws post-date the 12:18 root fix, and fold by fold
    the cache matches the FIXED-pen battery (F5 total within 0.044, club
    8+ share within 0.005) where the bug's own signature is 0.07-0.10 on
    F5 and 0.013-0.021 on 8+. What the control DOES say: an empty pen
    moves one-run share DOWN 0.007-0.015, the same direction as item 1's
    retired 0.247, so a broken-pen harness is a named contributor to
    about a third of that stale gap.

WHAT REMAINS, in order: (1) **NAME THE COUPLING — that is the item now,
and it is a structural gap rather than a refinement (rule 14).** Re-run
the four folds recording the LAST INNING per draw and re-read the
within-game correlation with extras excluded: if it collapses the defect
is the extras handling and it is one mechanism; if it survives it is a
shared state inside nine innings, and the sampled bullpen is the first
suspect. Regenerate on a DECIDED engine — do not span the uncommitted
`USE_PITCH_HAZARD_BND` change. (2) The club under-dispersion is the
known clustering defect and belongs with that item, not this one. (3)
Wire `KXMLBF5` / `KXMLBSPREAD` (same floor_strike parse as KXMLBTOTAL)
if a settled-price yardstick is wanted — OPERATOR CALL, because the
betting layer was deleted on 2026-09-05 and this puts a price back in
the room. What follows is the original item.

**THE NUMBER IS NOT MISSING, THE ARRAY IS.** `game.simulate_game` already
returns each draw's away and home runs, so P(home wins) is a COUNTER, not a
model. Nothing computes it because nothing persists the per-draw `(away,
home)` pairs — the board stores only marginals (game total, team totals,
F5), and a win probability needs the JOINT. Store one array per matchup and
the moneyline, the run line, the F5 winner and any margin question all fall
out of it without touching the engine. `scratchpad/sims/` and
`starts_*.json` are the existing precedent for persisting draws; follow it.

**THEN SCORE IT, BECAUSE IT HAS NEVER BEEN SCORED.** BETTING.md keeps ML
and run line OFF the board for exactly this reason. Replay paired
historical games (`calibrate.replay`, `cal.paired_cases` builds a season's
list in ~9 seconds, four seasons cached — **PASS `season=` EXPLICITLY or it
infers the current one and returns nothing**, a trap that has already cost
two turns), emit P(home wins), and run a
Brier decomposition against who actually won plus a calibration table by
bucket. That is the whole item. DO NOT start repairing the margin if it
scores badly — stop and write the null.

**THE PRIOR SHOULD BE WORSE THAN TOTALS, and the reason is specific.** A
win probability depends on the MARGIN, and the margin is where the hook,
the sampled bullpen and the still-unexplained late-innings lean all land
(+1.2 points against Kalshi across 11 games on 2026-09-09, uncorrelated
with how we price either pen, r = -0.16). Totals average two starters;
a margin does not.

**THIS ITEM ADOPTS THE ORPHANED ONE-RUN-GAME FINDING, and they are the
same question.** Item 1 retired with one survivor: one-run games at 0.247
against a real 0.266, 1.9 sigma light, explicitly recorded as "not its own
item". A model that under-produces one-run games has a margin distribution
that is too WIDE, which makes win probabilities too CONFIDENT and misprices
the run line first. Check that cell in the same pass — if the calibration
table shows us over-confident at the extremes, that is the mechanism and it
was already measured.

**THE YARDSTICK EXISTS AND IS UNUSED.** `KXMLBSPREAD` (run line) and
`KXMLBF5` (first-five winner) are live Kalshi series found 2026-09-09 and
priced by nothing. Both parse the same way the game-level totals did —
`floor_strike` plus the ticker's club code — so wiring them is the same
half-hour that wired KXMLBTOTAL.

**TEST F5 WINNER FIRST, not the full-game moneyline.** F5 is the only
market here that has ever beaten a settled price, and `KXMLBF5` is an
ML-shaped contract on exactly that window — before the bullpen and the
late-innings lean are involved. If any win probability works it is that
one, and if it fails the full-game version is not worth running.

RELATED: team totals are also never separately scored and are CHEAPER to
check than this, because they are marginals and need no joint. On
2026-09-09 our mean absolute disagreement with Kalshi was 3.03 points on
the game total against 3.65 on the team totals (1.20x, larger on the split
in 8 of 14 games), and CIN/LAD agreed on the sum to 0.5 while disagreeing
4.8 on the split. Score the split in the same replay pass; it is the same
loop and the market is one an operator is actually offered.

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

**20. CLOSED 2026-09-09 — every cross-fold result re-run with live
bullpens, no verdict changed** (notes, fifth entry of that date). Rule
12b's bar is 0.0399-0.0577 against a recorded 0.0401-0.0590 and CLAUDE.md
carries the new figure; item 7's counted MID hazard replicates four folds
for four at -0.0142 to -0.0148; 7d's boundary refutation replicates;
`USE_PEN_ROLES` re-run with live pens still moves no battery row past one
se. ONE AMENDMENT, recorded on item 7d: its MID half no longer loses in
three folds of four, and that is engine drift (the counted MID hazard
shipped after the original run), not the bullpen. What is NOT worth
re-running: the run-LEVEL 2023-2025 columns of any battery before
`55b73d1d3ed5` — they are wrong at the level and superseded by the current
engine's own battery. `scratchpad/pen_ab.py` reproduces the bug on demand
and stays as the positive control for the next harness that comes back
identical to four decimals across folds.

**21. THE CLOSER IS SPENT IN THE SEVENTH — SPLIT `PEN_PICK` BY INNING.**
Raised by the operator 2026-09-09. The closer is in the pool and nothing
reserves him for the ninth: `PEN_PICK` routes by margin bucket only, and
its weights were COUNTED POOLED over innings 7-9 — the real structure
(setup 7th-8th, closer 9th) is smeared into "44% best-fifth whenever
leading late", so the engine can spend the best arm two innings early.
Same pooling defect as the hook curves and the relief hazard, same fix:
recount the selection profile keyed (inning 7/8/9, margin bucket).
`deploy.py` already measured role as stable (split-half r +0.55 to
+0.78), so the split should resolve cleanly. Check cell sizes first; the
operator's point is that the ninth-inning closer is one of the few
STABLE, RELIABLE pieces of bullpen behaviour, so this is a count, not a
model. Battery around the wiring per rule 15.
