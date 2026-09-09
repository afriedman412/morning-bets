# TODO — the running list

Started 2026-08-29 (day fifteen). **The backlog, not the log.** What was
measured and why lives in `NOTES-context-layer.md`. When something ships,
compress it into the CLOSED section at the bottom — one or two sentences,
number retained — and write the full result in the notes.

Roughly ordered by runs per day of work. The leverage floor (~0.05 runs) is
a BETTING threshold and decides ORDER, never admissibility — a small,
counted, reliability-gated mechanism ships and accumulates (CLAUDE.md).

Each item says what is ESTABLISHED and what is not, because the expensive
mistake here is re-running something that already has an answer. **Numbers
are never reused or renumbered**, so a reference to "item 11" in the notes
always resolves.

**THE FOUR-SEASON RESCAN IS DONE (2026-08-29) AND ITEMS 6, 13 AND 18 SHOULD
BUILD ON IT.** `scratchpad/state_counts_4season.json` holds 748,905 plate
appearances over 9,978 cached games, keyed by season and (men on, outs).
`state_seasons.py` is the scan and carries the stability gate. Items 6
(per-runner speed) and 18 (steal decisions) key on the SAME cell and need
only runner and batter IDs carried through the same pass; item 13
(per-pitcher hbp/wp) is the same pass grouped by pitcher. Extend that scan
rather than writing a third one.

**THE MODEL IS NOT LIGHT ON RUNS (retraction, 2026-08-30).** F5 -0.047 (0.6
sigma), F3 -0.024, F7 -0.040 over 1,645 games. The "3% fewer runs" and "4.5%
light" lines in older notes are from a previous engine; anything reasoning
from a run deficit needs re-deriving.

## WORKING ONE ITEM PER SESSION — read this first

Items are written to be picked up COLD. If one is not self-contained enough
to start from, that is a defect in the item; fix the item before starting
the work.

Before touching anything:

  1. `git status` must be CLEAN. If it is not, find out what is in the tree
     before adding to it — `scratchpad/mutate.py` refuses to run dirty, and
     an unexplained diff in `sim.py` is indistinguishable from your own.
  2. `venv/bin/python -m tests.run` — know it was green BEFORE you started.
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

Finish by compressing the item into the CLOSED section and writing the
result in `NOTES-context-layer.md`.

---

# OPEN

## THE LEASH, THE REMAINDER OF `PLAN-pitch-history.md`

Steps one and two of that plan are done (notes, 2026-09-07): per-start
reliability measured, then the league-wide screen — secondary velo, FB
spin, FB vertical break and zone->K all dead or weak; ZONE->BB ALIVE and
SHIPPED as `sim.USE_ZONE_BB`. STILL OPEN: the per-channel leash half-life
(outs only, K flat) — pre-registered day 22, wiring exists switched off in
`pitcher_rates` — plus the stopgap board flag for sim-vs-last-10 outs
divergence, display only.

**THE HYPOTHESIS IS COMPRESSION, NOT STALENESS (corrected 2026-09-09).**
`team_offset` is added to a REMOVAL hazard, so a NEGATIVE offset buys a
LONGER outing (`OUTS_PER_OFFSET`: -2.0 maps to +3.00 outs). The poster
cases below all carry a negative offset already and we STILL price them
short of their own record — so the offset is not fitted short, it is not
moving FAR ENOUGH. The base hook regresses everyone toward a generic
length and the per-pitcher offset under-corrects, so short-leash arms run
too long and long-leash arms are pulled too short. `OFFSET_CLAMP = 2.0`
caps the whole adjustment at about +/-3.3 outs, which is the structural
reason it cannot reach an opener.

Poster cases, each arm's shipped `sim.leash` offset against 2026:

  * Yamamoto, offset -1.16. Career 17.60 outs a start, 2026 **19.68**. We
    price over 18.5 outs at 40.5% against his own 52.0% (13/25, se 10.0).
  * Sanchez, offset -0.89. Outs by season 15.9 -> 16.9 -> 18.8 -> 18.1. Our
    K line implies 21.9 batters faced against the market's 24.0; the outs
    market confirms it independently (our over 18.5 36.0%, Kalshi 47.4%).
  * Lowder, offset -0.16. Over 14.5 outs: his 2026 76.2% (16/21), ours 66.1%.

**DO NOT PRE-JUDGE THE DIRECTION — the counter-evidence is real.** Where the
leash table has NO entry the error runs the other way: Robert Stock (offset
0.0, 13.0 outs a start) priced 65.4% over 14.5 against his own 33.3%, Lake
Bachar (offset 0.0, 6.9 outs) 61.7% to clear 4.5 K against a market at 7.5%.
And Zebby Matthews HAS an offset (-0.74) and is still too long, 64.5% over
15.5 against 42.2% on 45 starts.

A FIRST CUT EXISTS AND MUST NOT BE QUOTED: regressing (implied outs - his
own 2026 mean) on (his own 2026 mean) over 12 arms gave slope -0.42, r
-0.56, but his own mean appears on BOTH sides with se ~0.9 outs against a
between-pitcher spread of ~1.1 — noise in a PREDICTOR attenuates the slope,
the `m_er` failure CLAUDE.md already records. The sample is selected too
(arms whose implied line misses the printed rungs drop out).

THE MEASUREMENT TO RUN FIRST, cheap because both halves exist: for every
start in the holdout compare the SIMULATED outs distribution to that
pitcher's own trailing record, bucketed by (has an offset / none) and by
offset magnitude; split-half within pitcher (estimate on odd starts, score
on even) so the predictor is independent. State the power before the
result. Flat in offset magnitude kills the story and leaves only the board
flag; a slope hands the half-life its falsifier.

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

**7a. RE-SOLVE THE BOUNDARY BACKBONE AGAINST THE MODEL'S OWN STATES — the
top modelling item.**
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

WHAT IT IS WORTH, measured after item 7 shipped (`scratchpad/outs_split.py`):
the biggest single cell error left is the CLEAN SIX-INNING START — real
0.230 of starts, ours 0.198, and the missing mass sits on four-inning
walk-offs (+0.023) and starters yanked with two down in the fifth (+0.018).
And at every round number we under-produce the man who came back out and was
chased without an out (15 outs: real 14.5% of that spike, ours 9.5%).

**AND RE-MEASURE `scratchpad/outs_adjust.py` THE SAME SITTING.** Twelve
seconds. Shipping the mid hazard already took a third of the correction's
job (band |correction| 0.045 -> 0.031); the boundary one will move it again.

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
**ITS FORMER HEADLINE EVIDENCE IS GONE.** The ninth-inning gap it inherited
from 11b was two driver bugs, now fixed, and the ninth reads +2.0% / z +0.3.
Do not re-cite it. Item 21 is the cheap, counted slice of this item.

**8c. EVALUATE THE DOUBLE-SHRUNK PRIOR FIX.** Fitted already, never scored —
it was waiting on the hook work. See item 12 for the defect and the Snell
case. DO NOT re-run `USE_RAW_PRIOR`; it was measured and loses.

**9. Ship and score the seasonal home-run term.**
Measured on 2023-2025; applied out of sample it moves a team total from -3.9%
to +0.7% against actuals. BLOCKED because `fitf5.evaluate` cannot take a
park, so it has never been scored on F5 CRPS. The walk slot it also
needed shipped 2026-08-29.
Until it ships, treat July/August model totals as biased LOW by 0.15-0.20
runs a side.

**10. Get `total_market` to complete a run.**
Full-game totals are a stated product that has never once been scored against
a settled price. `scratchpad/tonight.py` is the workaround. NOTE the betting
layer was deleted 2026-09-05, so this is now an OPERATOR CALL that puts a
price back in the room.

**11c. Extra innings are now reached too often.**
OPENED BY THE 11b FIX, and unconfirmed. P(extras) 0.102 against a real 0.083
(z +2.0) and extra innings/game 0.147 against 0.114 (z +2.1); it was 0.079
before the half-innings were corrected. Runs per extra half is still short at
2.689 against 3.026. `scratchpad/ninth.py` is the instrument.
Two sigma on a quantity nobody pre-registered — treat as a direction.
Item 19's coupling measurement excludes extras and will speak to this.

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

**15. THE OPENER — the exit SHIPPED 2026-09-09; the typed bulk arm and the
slate override are what remain.**

What shipped: `USE_RELIEF_INTENT` and `USE_OPENER_EXIT` (a flagged
short-yardage starter exits on a bootstrap from his own outs record), plus
the `USE_OPENER_POOL` no-record fallback. Details in the CLOSED section and
the notes. `scratchpad/opener_outs.py` is the instrument; the residual
-1.20 outs is role-drift staleness in the record, and if refined it gets a
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
fallback mis-prices: the pooled curve reads ~6 outs on an arm the club
intends to run 10+.

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

**19. MONEYLINES — the persist-and-score loop is DONE (2026-09-09). NAME THE
COUPLING is the item now.**

`scratchpad/moneyline.py` replayed all four folds (3,548 paired games x 200
draws) and persisted every draw's `(away, home, away_f5, home_f5)` to
`scratchpad/sims/ml_<fold>.json.gz` — gitignored, ~15 min to regenerate, and
the script LOADS the cache when the file exists and `n_sims` matches.
Regenerate rather than mixing cached and fresh draws across engine states.

ESTABLISHED by that pass (Brier-decomposed on outcomes; full tables in the
notes): calibration is GOOD (reliability 0.0005 F5 / 0.0007 full-game),
resolution is THIN (0.0040 / 0.0030 against uncertainty ~0.2495 — 2,861 of
3,548 forecasts sit in 0.4-0.6), the split beats climatology on discrete
CRPS in every quantity with the MARGIN weakest of the three, and item 20's
bullpen bug is positive-controlled as not touching any of it.

**THE ITEM'S ORIGINAL PREMISE IS REFUTED: the margin is too NARROW, not too
wide.** Mean |margin| 3.330 against 3.594 (se 0.047, -5.6 sigma); one- and
two-run shares HIGH, 8+ low at -3.4 sigma. Item 1's old 0.247-against-0.266
one-run figure was an OLD ENGINE number and is retired.

AND IT IS TWO DEFECTS. Club totals are too narrow (model sd 3.117/2.988
against 3.208/3.174, home worse) AND the model puts a +0.059 correlation
between the two clubs' runs where reality has -0.022 (se 0.017, 3.5 sigma),
mostly WITHIN a game (+0.048) rather than between games. sd(sum) 4.437
against 4.463 is a dead heat only because the coupling adds back what the
narrow clubs took out: A GAME-TOTAL INSTRUMENT IS BLIND TO BOTH DEFECTS AT
ONCE.

WHAT REMAINS, in order:

  1. **NAME THE COUPLING — a structural gap, not a refinement (rule 14).**
     Re-run the four folds recording the LAST INNING per draw and re-read
     the within-game correlation with extras excluded: if it collapses the
     defect is the extras handling and it is one mechanism (see 11c); if it
     survives it is shared state inside nine innings, and the sampled
     bullpen is the first suspect. Regenerate on a DECIDED engine — do not
     span an uncommitted `USE_PITCH_HAZARD_BND` change.
  2. The club under-dispersion is the known clustering defect and belongs
     with that item, not this one.
  3. Wire `KXMLBF5` / `KXMLBSPREAD` (same `floor_strike` parse as
     KXMLBTOTAL) if a settled-price yardstick is wanted — OPERATOR CALL,
     because the betting layer was deleted on 2026-09-05.

RELATED and still unrun: team totals are never separately scored and are
CHEAPER than the joint. On 2026-09-09 our mean absolute disagreement with
Kalshi was 3.03 points on the game total against 3.65 on the team totals
(1.20x, larger on the split in 8 of 14 games), and CIN/LAD agreed on the sum
to 0.5 while disagreeing 4.8 on the split. Score the split in the same
replay pass.

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

**Pitch-level expectation (`PLAN-pitch-expectation.md`) — CLOSED WITH A NULL
2026-09-07.** The granular re-open of arsenal. The expectation surface got
built and validated (E0 384 cells on 2.9M pitches; E1 batter offsets,
shrinkage at K=84 swings) and the per-start quantities are REAL within a
night, but NOTHING predicts the next start — all four candidates dead at the
pre-registered bar. Do not re-run the screens. Leftovers:
`scratchpad/pitch_e0.py`, `pitch_e1.py`. The one untested branch is the
batter-side log5 matchup adjustment, and after five dead arsenal
constructions its prior is low. RELIABLE IS NOT PREDICTIVE.

---

# CLOSED — what it was and when. Do not re-run; full write-ups in `NOTES-context-layer.md`.

**1. WITHDRAWN 2026-08-30 — the model reaches extras at about the right
rate**, 0.078 against a real 0.083 (se 0.006). The "5.4% against 8.3%" that
made this item 1 was `simulate_game` skipping the track block on a walk-off,
now fixed. Its one-run-game survivor (0.247 against 0.266) was an old-engine
number and is refuted by item 19 — the margin is too NARROW.

**7. SHIPPED 2026-08-31 — the counted MID pitch hazard.**
`sim.USE_PITCH_HAZARD = True`, `USE_PITCH_HAZARD_BND = False`: counted MID
backbone, parametric BOUNDARY. Re-run 2026-09-09 on the current engine with
live bullpens in all four folds — the 12.5-17.5 outs band improves -0.0142 /
-0.0155 / -0.0141 / -0.0148, long lines flat, mean outs moves +0.08 toward
real in every fold without crossing. Runs unmoved across the prefix ladder.
It closes the fourth-inning over-pull, because 60-85 pitches IS the fourth
inning and those were one defect, not two. TAKING BOTH CURVES WAS SCORED AND
LOST (nearly doubled the long-line error, 0.2-out shortfall -> 0.18-out
overshoot in every season) — half the change beat all of it. The open
remainder is 7a.

**7b. CLOSED — the K tail work is done, do not re-run.** Dominance shipped
(`late_mid_per_k_rate`), the per-start strikeout draw counted and shipped
(`START_K_SIGMA` 0.1625, refuting a tuned 0.20), and `PITCH_COST` closed —
its premise was arithmetically wrong, since a dominant night also needs
fewer batters and everyone needs ~99 pitches for six innings. o8.5 is now
-2.3 sigma, from -3.5.

**7c. CLOSED — a direct prop model is tested and dead.** The learned removal
model beats `sim.Hook` on decision AUC 0.912 to 0.876 and gives a boundary
share of 0.341 against a real 0.672. Do not rebuild props as a separate
model.

**7d. REFUTED on cross-validation; re-confirmed 2026-09-09 with live
bullpens. `sim.USE_PITCH_X_INNING` is False and stays there.** `PXI_BND` /
`PXI_MID` are solved conditional on the other shipped terms and do not
transfer — boundary still WORSE in 2023, flat in 2024, better in 2025-26,
and the signed mid offset trends monotonically by season rather than being
the constant one fold suggested. The RAW phenomenon is real (70 pitches in
the third is pulled 6.01% against 1.62% in the fifth) but the table is not
portable, and the counted MID hazard closes the fourth inning anyway. TWO
CAVEATS FOR ANYONE TEMPTED TO REFIT: the old "mid worse in 3 of 4" line is
engine drift and must not be quoted against the current engine (item 20);
and PITCHES PER INNING is older, deader ground — it folds back on itself
(high early pitches-per-inning means FEW total pitches), measuring
non-monotone 1.68% / 4.77% / 3.14% against a monotone 75x span for raw
pitch count. Rejected day seven, re-derived day twenty.

**11. LARGELY CLOSED 2026-09-09 — the first inning is no longer the largest
per-inning defect and the old headline is retracted.** Re-measured on the
battery's four folds: the gap is -0.036 runs / -3.5% / z -1.5, not the -12% /
z -2.5 this item carried all week (that came from one 926-game cut against
the 2026-08-30 engine). Sign stable 4/4. The pitch-hazard, sharpness and
opener work shipped since closed most of it. **INNING 6 IS NOW THE LARGEST,
at -0.056 runs / -5.3% / z -2.2, also sign-stable 4/4** — that is the
replacement item if a per-inning row is chased.

TWO THINGS WORTH KEEPING FOR ANY FUTURE INNING-1 WORK. First,
`scratchpad/inn1.py` counted on 306,506 pre-holdout starter plate
appearances that real starters strike out ~6.6% MORE in inning 1 (z +5.7,
4/4 seasons) and NOTHING else moves (bb, hr, babip all null). More
strikeouts is FEWER runs, so wiring that counted table makes the first
inning score LESS — where we are already short — and pushes K out of inning
2, where we are already long. Pre-registered: it moves both rows the wrong
way. So the residual is not a missing inning-1 rate effect; clustering /
advancement remains the better explanation. Second, THE COLLIDER: how many
batters bat in inning 1 IS AN OUTCOME of inning 1, so a within-game-side
permutation is NOT a valid null — it read z +14 on BABIP with nothing
injected. Shuffle labels globally (`scratchpad/inn1_dbg3.py` is the
discriminator). Field state was separately ruled out as the cause of the TTO
decay (`tto_state_overlap.py`, positive-controlled).

**15-exit. SHIPPED 2026-09-09 — the opener's exit.** `USE_RELIEF_INTENT`
(the follower of an early exit continues like the bulk arm he is) and
`USE_OPENER_EXIT` (a flagged short-yardage starter — avg < 11 outs, the same
`slate.priceable` cell — exits on a bootstrap from his own outs record via
`forced_exit_outs`), plus `USE_OPENER_POOL` for arms with no record.
Measured: flagged arms' outs error +3.40 (6.7 sigma, sd far too narrow) ->
-1.20 (2.4 sigma, sd exact); affected-game totals move toward actuals (9.01
-> 8.95 against a real 8.49); the intent falsifier's recorded 4/4-fold
failure dissolves to 0.2 sigma on truthful states. The leash never could
reach these arms (`OFFSET_CLAMP` ~+/-3.3 outs against a needed ~-12). The
rest of item 15 is still open above.

**20. CLOSED 2026-09-09 — every cross-fold result re-run with live bullpens,
no verdict changed.** Rule 12b's bar is 0.0399-0.0577 against a recorded
0.0401-0.0590 and CLAUDE.md carries the new figure; item 7 replicates four
folds for four; 7d's refutation replicates; `USE_PEN_ROLES` re-run with live
pens still moves no battery row past one se. ONE AMENDMENT, recorded on 7d:
its MID half no longer loses in three folds of four, and that is engine
drift, not the bullpen. NOT worth re-running: the run-LEVEL 2023-2025
columns of any battery before `55b73d1d3ed5` — wrong at the level and
superseded. `scratchpad/pen_ab.py` reproduces the bug on demand and stays as
the positive control for the next harness that comes back identical to four
decimals across folds.

**ZONE->BB. SHIPPED 2026-09-07** as `sim.USE_ZONE_BB` (-0.1431 per share of
zone, 4.9 sigma train-only, survives the box-score walk drift) — the one
live channel out of `PLAN-pitch-history.md`'s league-wide screen.

## Shipped 2026-08-29/30 (days seventeen and eighteen) — the hook

All counted on real removal DECISIONS, never on runs, and all refit-verified
on training rows only.

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

## Shipped 2026-08-29 — the correctness and constants batch

  * **The home/road constants, recounted, and walks got their own** (was
    11d). `HOME_OPP_K` 1.034 -> 1.026, `HOME_OPP_CONTACT` 0.981 -> 0.990,
    both overstated by 3.5-4.1 sigma on 679,329 plate appearances. THE REAL
    FINDING WAS THE FOURTH CHANNEL: walks rode the contact constant at
    0.9804 where their own count is 0.9493 (z -6.6) — new `HOME_OPP_BB`
    0.974. Counted on UNINTENTIONAL walks alone to match the code path; HBP
    has no home/away split. Real home-field advantage counted on this league
    is 0.306 runs (se 0.044), twice an outside guess; we now produce 0.263
    (see 11d-residual).
  * **The half-innings were reversed and the walk-off fired on the first
    run** (was 11b). Two correctness bugs in `simulate_game`: the side named
    `away` is a PITCHING side, so calling it first batted the home club in
    the top of every inning; and `home.opposing_runs = home.runs` truncated
    every ninth and extra inning at the first run. Innings 9+ z -2.9 -> +0.3.
    INNINGS 1-8 CANNOT MOVE — both rules key on `regulation` — so no F5
    number, ladder or CRPS in this project's history is affected. Two
    regression checks, each verified by mutation.
  * **Hit-by-pitch by field state** (was 4). `STATE_MULT` gained an
    `hbp_pct` column and `pa_from` moves `hbp` with its renormaliser. Keeps
    only 36% of its raw spread after shrinkage. FOLLOW-UP TAKEN: the
    four-season rescan at the top of this file is the sharper input it
    needed.
  * **Rank by gap over simulation error** (was 15-old). Sorting on
    `z = gap / se` — the estimate is least reliable where the gap is
    largest, so a tail gap and a central gap were never the same evidence.
  * **Walks have an `odds_mult` slot** (was 3). `Matchup.m_bb`,
    `NEUTRAL_PARK["bb"]`, `park_mults` now reads Savant's walk index, which
    had always been fetched and discarded — so every park test ever run here
    excluded walks by construction. Inert, fingerprint unchanged.
  * **`_track` fires on every exit path in `simulate_game`.** The prefix
    block sat after the walk-off `break`, so `prefix[9]` was missing for
    ~40% of games and the notes carried a standing "take 9+ as the residual"
    warning. Verified inert on outcomes.
