# TODO — the running list

Started 2026-08-29 (day fifteen). **The backlog, not the log.** What was
measured and why lives in `NOTES-context-layer.md`. When something ships,
delete it here and write the result there.

Roughly ordered by runs per day of work. The leverage floor (~0.05 runs) is
a BETTING threshold and decides ORDER, never admissibility — a small,
counted, reliability-gated mechanism ships and accumulates (CLAUDE.md).

Each item says what is ESTABLISHED and what is not, because the expensive
mistake here is re-running something that already has an answer.

## WORKING ONE ITEM PER SESSION — read this first

Items are written to be picked up COLD. If one is not self-contained enough
to start from, that is a defect in the item; fix the item before starting
the work.

Before touching anything:

  1. `git status` must be CLEAN. If it is not, find out what is in the tree
     before adding to it — `scratchpad/mutate.py` refuses to run dirty, and
     an unexplained diff in `sim.py` is indistinguishable from your own.
  2. `venv/bin/python -m tests.run` — 408 checks, ~45s. Know it was green
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

**4. Hit-by-pitch by field state.**
+23.0% with men on, the largest relative effect measured. Held back from the
plumbing deliberately: hbp is drawn off the top against `cond`, which is
carried rather than recomputed so it can never disagree with the rates it
renormalises. Scaling hbp REQUIRES recomputing `cond` in the same breath, or
every rate below it is renormalised by the wrong denominator.

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

**7. Condition the hook on how the night is going.**
The single biggest defect, and it causes two of the three worst numbers on
the board.
K per 27 outs by length: model 8.42 / 8.05 / **7.51**, actual 8.33 / 7.98 /
**8.49**. The middle buckets are right to a tenth, then the model keeps
declining where reality JUMPS. A real seven-inning start is a SELECTED
population, earned by missing bats; the model has no selection. It therefore
prices a high-K over at ~60% of true (o8.5 0.060 against 0.095, -3.9 sigma).
Boundary share 0.598 against a real 0.669 (5.0 sigma) — 5.8 points short at
exactly 18 outs, the most common real outcome, and long at 11, 14 and 20.
Reality ends starts at the end of an inning; the model ends them mid-inning.
It also sends too many starters past the sixth (o18.5 0.224 against 0.173).
FIRST SUSPECT: `PITCH_COST` charges 4.97 pitches for a strikeout against
3.25 for an out, so a dominant night actively SHORTENS a simulated start.
DO NOT re-run the per-start sharpness sweep — it closes 78-85% of the K tail
and costs an equal amount of outs CRPS. It is a symptom patch on this.

**8. Role-based bullpen deployment, and fatigue.**
`build_side` samples 8 arms weighted by appearances and `next_arm` walks that
list IN DRAW ORDER. No leverage — the most-used arm is drawn 84.4% of games
and lands at average slot 3.01 of 8, as likely to pitch the sixth as the
ninth. No situation — nothing knows the score, the platoon or the save. No
fatigue — the pen is redrawn independently every game AND every draw, so
nothing records that an arm threw 30 pitches yesterday.
`deploy.py` already measured that role is real and projects (split-half +0.55
to +0.78 over 319 relievers) and concluded role-based deployment was worth
building. It was never built. Largest unbuilt item with a finished
feasibility study behind it.

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

**11. The first inning is under-scored by 13.3%.**
z -2.7. Reality's first is its highest-scoring inning, the model's is its
lowest. Innings 1-3 run -13.3%, -7.3%, -5.7% — a decay shaped like a lineup
pass. UNTESTED CANDIDATE: `TTO_MULT`'s first-pass penalty (k_pct 1.1053) may
be too strong.

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
