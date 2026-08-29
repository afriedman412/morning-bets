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

**7. The K tail. LARGELY DIAGNOSED 2026-08-29 — READ BEFORE RESUMING.**
Two of the three things this item said are now settled and one of them was
WRONG. What remains is a single, well-specified measurement.

**DONE AND SHIPPED:** the hook now conditions on how the night is going.
`late_mid_per_k_rate` -1.5130 (z -9.5) and `mid_per_abs_margin` -0.0824
(z -10.4), both counted on 322,205 real removal decisions, both mid-inning
only — the boundary curve took neither term. Selection now runs the right
way: E[K] by start length moves toward the actual in five of six buckets.

**THE FIRST SUSPECT WAS WRONG AND `PITCH_COST` IS CLOSED.** "A strikeout
costs 4.97 pitches against 3.25, so a dominant night shortens a start" is
arithmetically incomplete — a dominant night also needs FEWER BATTERS and
the two cancel. Counted on 73,506 pitcher-games, everybody needs about 99
pitches for six innings (Q1 98.2, Q5 99.5), and the simulator reproduces
that to a tenth. PITCHES PER BATTER WAS THE WRONG DENOMINATOR. Do not
re-open the pitch-budget channel.

**THE HOOK FIX IS NOT SUFFICIENT AND THAT IS MEASURED:** at x4 the fitted
coefficient P(K>=9) reaches only 0.0649 against a real 0.0950, while
boundary share and outs both degrade. The manager's response to dominance is
real and is not the main cause.

**WHAT IS LEFT, AND IT IS ONE MEASUREMENT.** The residual is a
STRIKEOUT-SPECIFIC dispersion deficit (K sd 2.28 against 2.49). The old
sharpness sweep failed because `dispersion.LOAD` is one latent factor on
FOUR rates, so it widened traffic — and traffic is what the hook integrates
— wrecking the outs distribution for the K gain. **Loaded on `k_pct` ALONE
it lands K sd exactly (2.49), closes 69% of the o8.5 gap, improves K CRPS
0.0096, and leaves outs sd on target (4.05 against 4.04) at less than half
the outs CRPS cost.**
**DO NOT SHIP THAT — the sigma was chosen to hit the target, which is
solving for a spread.** COUNT the extra-binomial strikeout variance in real
starts (how far a pitcher's start-to-start K rate moves beyond his season
rate and that night's lineup) and use the counted value. This is NOT the
closed per-pitcher dispersion question (split-half 0.072): that asked WHICH
arms are variable, this asks how variable the league is.

**THE BOUNDARY SHARE NOW HAS A MECHANISM — SEE ITEM 8b.** Bullpen
availability reaches the boundary decision at 5-6 sigma and is the first
external signal that curve has ever accepted.

**STILL OPEN:** boundary share 0.609 against a real 0.669.
Reality ends starts at the end of an inning; the model ends them mid-inning.
Both of today's fits found the boundary curve takes NO in-game state —
margin, |margin| and strikeout rate all null or sign-unstable on it — so
whatever governs it is not the game situation. That is now the best-defined
unknown on this item.

**8b. WIRE BULLPEN AVAILABILITY INTO BOTH HOOK CURVES. MEASURED
2026-08-29, NOT WIRED — the best-evidenced unshipped mechanism on this
list.**
`pen_back2` (relievers who worked both of the club's last two days) and
`pen_rest` (days since the club last played) reach the removal decision at
z -5.3/+6.3 on the BOUNDARY curve and -5.2/+6.2 mid-inning, sign-stable in
all four seasons on both curves, all pre-registered signs correct, positive
control fired. Raw pitch totals are null — it is about WHO CAN PITCH, not
how much was thrown.
BOTH CONFOUNDS RUN AGAINST IT: a used-up pen correlates with a bad club and
a bad starter (pulled earlier, pushes positive), and an off day rests the
starter too (should push negative). It survives both.
**THIS IS THE FIRST MECHANISM THAT BELONGS ON BOTH CURVES.** Margin and
dominance were mid-inning only.
WIRING, and it does NOT need a deployment model — these are club-level
counts: two coefficients on both curves, the two columns carried on `Side`,
a supplier reading the club's last two games, and CENTRING on the league
mean so the level does not move. `scratchpad/pen_state.py` has the fit.

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

**11. The first inning is under-scored by 10.7%.**
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
