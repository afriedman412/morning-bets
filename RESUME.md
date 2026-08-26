# Resume here — state as of 2026-08-25 (day eight)

## START HERE — TRUST ALMOST NO RECORDED NUMBER BEFORE THIS FILE

Day eight found TWO defects in the SIMULATION INPUTS. Both preserved every
aggregate this project tracks, so nothing in the notes flagged them, and
both destroyed the MATCHUP — the only thing that differentiates one game
from another, and the exact quantity days six and seven failed to find.

**1. EVERY PITCHER WAS FACING HIS OWN TEAMMATES.** `build_cases` attaches to
each start the nine that pitcher FACES, so the away start already carries
the HOME club's batters. Seven modules then handed the away pitching side
the other lineup: `ladder`, `calibrate.replay`, **`fitf5`** (the primary F5
benchmark), `f5_market`, `total_market`, `team_market`, `marginals`.
Verified on names — Ryan Feltner of Colorado simulated against Brett
Sullivan, Connor Norby and Jake McCarthy, Colorado's own hitters.

The variable names caused it: `a_nine` reads as "the away team's nine" and
held the nine the away PITCHER FACES. Renamed `away_faces`/`home_faces`
everywhere so the correct call is the one that reads correctly.

**2. NOT ONE LINEUP IN 574 WAS RIGHT.** `opposing_lineups` had no
batting-order column, so it sorted the boxscore by at-bats descending and
took the top nine:

    exact match (right nine, right order)      0.0%
    lineups with at least one wrong batter    23.5%
    mean slot error                            2.30

At-bats exclude walks, so a high-OBP leadoff man sorted below a free
swinger; a pinch hitter with two at-bats displaced a starter pulled early;
and a club that batted around handed its leadoff man five at-bats, so the
"input" was partly a function of the result. Order is not cosmetic — TTO is
a measured 19% K% swing and the simulator derives it from batters faced.

Fixed by `src/context/order.py`, counted off play-by-play. 1,956 games, 97%.

**INVALIDATED:** every full-game number — the prefix ladder including "the
model runs 5% light", the day-seven resolution finding and the 0.19
game-total ceiling, `score_outs`, the dispersion work, the blind dashboard,
and every `fitf5` result. **SURVIVES:** the model-free ANOVA (actuals only)
and the one-sided leash measurement.

## THE BASELINE, ON A CORRECT ENGINE

Two-sided, real matchup, real batting order, leash OFF, 3,248 starts:

           actual sd   our within   our spread   corr
    outs        3.99         3.86         0.59   0.263
    k           2.44         2.02         1.00   0.496
    er          2.00         1.77         0.28   0.203
    h           2.24         1.94         0.44   0.278

    TEAM TOTALS, per side, 1,624 games
              actual sd   implied real   our spread   share   corr   level
    F3             1.74           0.40         0.23     59%  0.198  -0.05
    F5             2.31           0.69         0.35     51%  0.222  -0.10
    F7             2.76           0.95         0.43     46%  0.213  -0.11
    full           3.17           1.23         0.59     48%  0.164  -0.26

**Fixing the engine did NOT move the starter numbers** (outs corr 0.263
before and after). Both lineups were always real major-league nines, and
club-to-club quality varies far less than the noise inside one start. The
level error on team totals is now -0.10 runs per side at F5, NOT the 5%
recorded from the crossed engine.

## WHAT IS ACTUALLY NEW AND REAL

**TEMPERATURE ON HOME RUNS: t +3.6** with a pitcher fixed effect, +0.0081
HR per degree — about 0.32 HR per start across 55-95F. Clears the bar.
UNWIRED; this is the first genuinely new mechanism in days.

**BULLPEN OUTS YESTERDAY ON STARTER OUTS: t +2.6** under the same fixed
effect. Nothing in the simulator knows about yesterday.

**THE PER-PITCHER LEASH** (`src/context/leash.py`, `sim.USE_LEASH`) — a
pitcher's residual is stable on OUTS and noise on k/h/bb/er, so what is
wrong is how long he is left in. Out of sample +0.105 -> +0.226. **THE
SHIPPED `hook_leash.json` WAS MEASURED ONE-SIDED AND MUST BE REBUILT.**

**PARK IS NEUTRAL, MEASURED PROPERLY FOR THE FIRST TIME.** `NEUTRALISE_PARK`
was off, so rates already contained each pitcher's own park and layering a
factor on top counted it 1.5x. Neutralised and applied once: F5 spread 0.35
-> 0.39, correlation 0.222 -> 0.208. More differentiation, no accuracy.

**DAY/NIGHT IS DEAD, cleanly.** Null in all three specifications, and with
real lineups "day games get weaker lineups" is already captured.

**HOME/ROAD IS REAL AND CORRECTLY SIZED.** With the adjustment on, t +0.1;
switched OFF it reappears at t +2.4, worth +0.38 outs.

## HOW TO TEST A BETWEEN-GAME FEATURE (use this, it is cheap)

`scratchpad/allelse.py` — joint fit plus a WITHIN-PITCHER fixed effect, on
the residual. Univariate correlation is not enough: park on hits reads +2.5
alone and +0.9 under the fixed effect, because "starts in a hitter park" is
partly "starts by Colorado pitchers". Costs seconds, needs no re-simulation.
The internal control that says the method works: signed `wind carry` reaches
+2.1 on hits while raw wind SPEED sits at -0.5.

## WHAT TO DO NEXT

**1. FINISH DELETING THE ONE-SIDED ENGINE.** `calibrate` is migrated;
`cal.paired_cases` + `cal.replay` are the only simulation entry point.
Remaining: `f5.py` (2 sites, and it invents a league-average reliever
instead of using real bullpens), `quote.py`/`price.py` via `sim.simulate`,
~45 test call sites. NOTHING SCHEDULES price OR quote — not cron, not
launchd, not the Makefile — so they do not gate this. Do `f5` + `quote` +
the delete in ONE commit. Rule to adopt: no opposing starter -> DECLINE to
price, which is what `price.py` already does for openers and live games.

**2. REBUILD THE LEASH TWO-SIDED** (`python -m src.context.leash --build`).
The shipped offsets were measured on the engine we no longer trust.

**3. WIRE TEMPERATURE as an HR multiplier and score it.** Use the park HR
factor, not the runs index — the -2.1 on `park runs idx` against a home-run
target is that mismatch, not a finding.

**4. RE-TEST HANDEDNESS.** Play-by-play carries real `batSide`/`pitchHand`
per plate appearance; the dead result used derived season splits, on the
broken engine.

**5. RE-RUN `fitf5`.** It was crossed. Every F5 number in these notes is
from that state.

## TRAPS ADDED ON DAY EIGHT

**AN AGGREGATE THAT LOOKS RIGHT IS NOT EVIDENCE THE INPUTS ARE RIGHT.** Both
defects preserved run level, outs distribution, boundary share and pitchers
per side. What catches them is asserting on NAMES.

**AN IDENTICAL-TO-FOUR-DECIMALS A/B IS PLUMBING, NEVER A NULL.** A paired
ladder read EXACTLY +0.0000 at all four prefixes over 1,615 games. That was
`game.build_side` never calling `sim.for_start`.

**A MODEL-BASED CEILING IS ONLY AS GOOD AS THE MODEL'S OWN SPREAD.**
`ceiling.py` reported an outs ceiling BELOW our own correlation. Cross-check
with the ANOVA on actuals, which touches no model.

**A SPLIT-HALF THAT PASSES CAN STILL BE THE WRONG QUANTITY.** The club
residual passes the bullpen-role gate at +0.595 and is worthless once the
pitcher offset is in.

**NAME A VARIABLE BY WHO FACES IT.** `a_nine` cost seven modules.

**DO NOT OVERRIDE THE FEED WITH AN ASSUMPTION.** `weather.py` briefly zeroed
wind under a closed roof, treating six readings as a quirk. They are all
American Family Field and T-Mobile Park — RETRACTABLE roofs, and T-Mobile's
is a cover, not a seal.

**FIVE CHECKS WRITTEN TODAY GUARDED NOTHING** until mutation caught them:
two set the flag they were testing, one asserted a clamp against itself, one
asserted "nine distinct names" without checking the sequence, and one
inspected `replay`'s arguments instead of what it built.

## STATE

* 337 checks, `make test`. New: `test_leash` (6), `test_order` (6),
  `test_weather` (4), plus `test_game`, `test_sim`, `test_wiring`.
* `context.db` adds `mlb_lineups` (35,208 slots) and `mlb_weather` (2,034).
* Stadium home-plate bearings, if ever needed: NOT required — statsapi
  reports wind field-relative. User supplied a table; it is in the day-eight
  section of `NOTES-context-layer.md`.

---

# ARCHIVE — the rest of day eight and earlier

# Resume here — state as of 2026-08-25 (day eight)

## START HERE

**Read `CLAUDE.md`'s THE OBJECTIVE section and `AF_PLAN.md` first.** Judge
every change on ACTUAL OUTCOMES. CLV is not the target.

**Then read the END of `NOTES-context-layer.md`** — day eight is the last
section and carries the measured negatives, which are the expensive thing
to rediscover.

## WHAT LANDED ON DAY EIGHT

**THE PER-PITCHER LEASH IS MEASURED AND SHIPPED** (`src/context/leash.py`,
`sim.USE_LEASH`). Out of sample — rates before 2026-07-01, offsets built
`--before 2026-07-01`, scored on the 1,125 starts after it:

    outs                     OFF      ON
    spread of our means     0.56    1.29
    corr with actual       0.105   0.226     (model-free ceiling ~0.30)
    of ceiling               33%     71%
    sd(p) at 15.5 outs     0.060   0.127     <- Brier resolution, doubled
    distinct medians           8      17

Downstream too, which is the coherence argument for ONE simulator stated in
numbers: k +0.389 -> +0.408, h +0.207 -> +0.235, er +0.044 -> +0.063.

**IT BUYS RESOLUTION, NOT SHAPE, AND THAT IS THE HONEST SUMMARY.** Outs
CRPS is FLAT (2.1761 -> 2.1747, +0.1 sigma) and the prefix ladder is flat
(F7 +0.4 sigma). Both are expected: our within-start sd is 3.84, so moving
a start's centre by an out barely shifts a distribution that wide, and a
hook change cannot move a run total when starters and relievers are equal
in aggregate. What changed is DISCRIMINATION BETWEEN STARTS, which is
exactly the quantity day seven found we were short of.

**MOST OF THE RAW GAIN IS OPENERS, so quote the rotation-only row.**
`ROTATION_MIN_GS = 5` admits openers and bulk arms and they were being
simulated with a starter's hook. Separated out on the holdout:

    live starts            base corr   +leash   RMSE base   RMSE leash
    all                        0.075    0.268       3.831        3.697
    median outs >= 12          0.077    0.182       3.613        3.550
    median outs >= 15          0.051    0.099       3.591        3.555

On genuine rotation arms the correlation still more than doubles, and the
true per-pitcher leash sd there is ~0.9-1.1 outs rather than 1.77.

**A WIRING GAP THAT INVALIDATES SOME OLDER A/Bs.** `game.build_side` never
called `sim.for_start` — every caller passes `hook=None`, which fell
through to a bare league `Hook()`. So club and per-pitcher offsets reached
`sim.simulate_start` and NEVER REACHED A FULL GAME, which is the engine
that produces team totals. Fixed, and guarded in `tests/test_wiring.py`.

**THE CLUB IS DEAD FOR THE SIXTH TIME**, and its split-half is a trap: r
+0.595 passes the bullpen-role gate while measuring which ARMS a club runs
out. Fitted club-first, a club offset is +0.090 -> +0.122 alone and makes
things WORSE on top of the pitcher (+0.234 -> +0.227). `USE_PATIENCE` False.

**EVERY OTHER BETWEEN-GAME FEATURE MEASURED NULL ON THE OUTS RESIDUAL**,
directly rather than inferred: is_home +0.005, night +0.019, park runs
index -0.032, days rest +0.014, bullpen outs yesterday +0.037, month
+0.039. None worth 0.15 outs against 1.77 of real variation. **Run
`scratchpad/between.py` FIRST on any future between-game candidate** — it
is a residual correlation, not a build-and-re-simulate.

## THE MEASUREMENT THAT SHOULD DRIVE THE NEXT SESSION

Model-free one-way ANOVA on ACTUAL values by pitcher, `(MSB - MSW)/n0`, so
sampling noise is removed. A LOWER bound on real between-start variation:

    stat  actual sd  between  within  our within  our spread  share
    outs       3.96     1.77    3.50        3.84        0.57    32%
    k          2.44     1.10    2.17        2.03        1.02    93%
    h          2.23     0.67    2.12        1.96        0.45    67%
    bb         1.30     0.39    1.24        1.28        0.39   100%
    er         1.99     0.41    1.94        1.78        0.29    71%

Outs was the only quantity badly short and the leash is the answer to it.
**Strikeouts are at 93% and essentially exhausted.** Do not spend a day on
a between-game feature aimed at K props.

**AND NOTE `our within` > the real within on outs (3.84 vs 3.50).** The
simulator is OVER-DISPERSED per start. This is why the model-based ceiling
estimator in `ceiling.py` returned an impossible "105% of ceiling" and had
to be replaced by the ANOVA. It is also why CRPS cannot see the leash. It
is the largest remaining defect in the starter model.

## WHAT TO DO NEXT

**1. THE OVER-DISPERSION ON OUTS — 3.84 against a real 3.50.** Newly
identified and it now blocks two things at once: it broke the ceiling
estimator, and it is why a correct centre buys no CRPS. Narrowing the
within-start distribution is worth more than any remaining feature, because
every start is currently too vague to price sharply.

**2. THE RUN LEVEL — 5% light at every prefix.** Unmoved by everything for
three days. Stated product, unambiguously wrong.

**3. The 12-14 out bucket**, 19.4% against a real 16.6%. Where books hang
outs lines.

**4. Collapse to ONE engine.** Day eight found the cost of two: a mechanism
wired into one and silently absent from the other for a full day.

**5. Openers as a population.** They are in `actual_starts` with a
starter's hook, and the leash is currently containing them by pinning them
at the sweep boundary. That works but it is a clamp doing a filter's job.

**6. Within-start K% persistence, +6.4 sigma**, still unused.

## TRAPS ADDED ON DAY EIGHT

**AN IDENTICAL-TO-FOUR-DECIMALS A/B IS A PLUMBING RESULT, NEVER A NULL.**
The first paired ladder read EXACTLY +0.0000 at all four prefixes over
1,615 games. Two model states that agree to four decimals on 1,615 games
are the same model. Second time in two days a mechanism was not reaching
the simulator.

**A MODEL-BASED CEILING IS ONLY AS GOOD AS THE MODEL'S OWN SPREAD.**
Subtracting our within-start variance from the actual variance reported an
outs ceiling BELOW our own correlation. Cross-check with the ANOVA on
actuals, which touches no model at all.

**A SPLIT-HALF THAT PASSES CAN STILL BE THE WRONG QUANTITY.** The club
residual passes the bullpen-role gate at +0.595 and is worthless once the
pitcher offset is in. Split-half tests persistence, not incremental value;
run the nested fit before believing it.

**`hook_leash.json` AS COMMITTED IS BUILT ON THE FULL SEASON.** Correct for
pricing tomorrow, WRONG for scoring this season — a pitcher's offset was
measured partly on the starts an in-sample replay would score. Rebuild with
`--before <cutoff>` and score after it.

**A SEVENTH CHECK GUARDED NOTHING.** `check_the_offset_never_leaves_the_
measured_sweep` asserted the clamp against the clamp constant itself and
passed with it mutated to 99.0. Write the mutation before believing the
check.

## STATE

* 325 checks, `make test`, no network, no pytest. `tests/test_leash.py` is
  new (6), plus 3 in `test_sim` and 2 in `test_wiring`.
* All six new checks mutation-verified.

---

# ARCHIVE — day seven and earlier

# Resume here — state as of 2026-08-25 (day seven)

## START HERE

**Read `CLAUDE.md`'s THE OBJECTIVE section and `AF_PLAN.md` first.** Judge
every change on ACTUAL OUTCOMES. CLV is not the target — measured, our
resolution is LOWER than the opening price's while we still "beat the open",
so a CLV edge can rise while the model gets worse at baseball.

**Then read the END of `NOTES-context-layer.md`.** It is appended
chronologically; day seven is the last three sections and carries the
measured negatives, which are the expensive thing to rediscover.

## WHERE THE MODEL STANDS

    3,248 real starts        outs CRPS   whole-inning   mean outs
    day seven, morning          2.2199          9.5%       16.39
    day seven, end              2.1505         66.3%       16.00
    ACTUAL                                      65.7%       15.70

`calibrate.loss` 0.20626 -> 0.04730. Outs SD 4.43 -> 3.95 against a real
3.99. Boundary share 70.3% -> 66.0% against a real 65.7%.

## WHAT LANDED ON DAY SEVEN

**The learned hook is OFF and the two branches are back.** It was shipped on
a premise written into `game.py` that was false: one roll per plate
appearance does NOT span the inning boundary, because `_half_inning` breaks
out of its loop on the third out before the roll happens. 72,426 instrumented
hook calls, every one at outs 0/1/2, never at a boundary. It was validated on
removal-decision AUC while silently discarding a fitted, verified boundary
share (66.9% against a real 66.7%).

**Each hook branch is now fitted on its OWN population, and that was the big
one.** The pooled fit averaged 20,994 late decisions at a 6.29% pull rate
with 26,693 early ones at 0.65%; the early rows dominate by count, so the
late curve came out far too flat — 7.24% at 90+ pitches where reality is
33.80%. Refitting late-only is what moved every number above.

**Early-inning branches exist on BOTH hooks and ship OFF** (`early_innings`).
They fix the disaster tail almost exactly (sub-two-inning starts 0.31% ->
3.16% against a real 2.68%) but widen outs SD to 4.47 where reality is 3.99.
The tail miss is left standing rather than bought with spread.

**Kalshi prop lookups were matching the wrong player.** `price_prop` matched
on ANY shared name token, so "Tyler Glasnow" priced off Tyler Phillips of
Miami and reported fair at 0.920 against a true 0.595. `names_match` now
requires the surname. `find_settled` is the CLV path, so recorded prop CLV
numbers may carry some of this.

**Recency persists and it is BB% and BABIP that move** — 136 pitchers, 1,952
window-to-next-start pairs. Out rate persists at +0.2084 (9.4 sigma); K% at
+0.0624. A single half-life over all four rates averages a 5.6-sigma signal
with a 2.2-sigma one and dilutes both, which is what `recency.py` did.

**`tests/test_wiring.py`** — five shipped mechanisms had no guard at all. See
the notes; the short version is that every measurement module was tested and
none of the wiring was.

## THE FRAME FOR ALL OF IT (user, end of day seven)

**Central tendency beats the tail.** A bet on under 18.5 outs settles the
same whether he went six strong or blew up in the second. What matters is
the mass NEAR THE THRESHOLD, not the shape of the far tail. Day seven spent
most of its effort on the disaster tail, which is the less useful end — and
the tail work was then shipped OFF anyway. The 12-14 out bucket (19.4%
against a real 16.6%) is 4.0-4.2 innings, which is exactly where lines sit,
and it is the more valuable target.

**The model was RIGHT about the short starts.** Burns at 11 outs and
Whisenhunt at 8 priced at the 7.1st and 3.8th percentile. Those were rare.
Pricing them as common would be worse, not better.

**RUNS ARE THE GAME.** They lag as a within-start signal — that is why the
hook keys on baserunners — but as a measure of whether the SIMULATION is
right they are the thing itself. Everything else is a component.

**IS THE HOOK WORK JUICING THE OFFENCE? TESTED — NO.** The concern was that
the hook is fitted to reproduce starter lengths GIVEN this simulator's run
environment, so a wrong offence gets absorbed into the hook and vice versa.
Measured on the prefix ladder, 1,615 games, before and after a full day of
hook work:

    prefix     actual    morning    end of day
    F1           1.03       0.88          0.88
    F3           2.90       2.73          2.71
    F5           4.95       4.66          4.67
    F7           6.89       6.57          6.57

Identical to two decimals. Mechanically that follows: relievers and starters
are equal in aggregate here (K-BB 0.1358 against 0.1333), so moving WHEN a
pitcher leaves does not move how many score.

**THE MODEL RUNS COLD ON RUNS, AND THAT IS THE STANDING DEFECT.** 0.32 runs
light at F7, about 5% at every prefix, unchanged all day. Note a three-game
blind re-simulation made it look HOT (sim totals 7.6/8.1/8.4 against actual
11/5/5, mean percentile 0.356) — that was 21 correlated quantities, maybe
seven effectively independent, and it had the sign backwards. Trust the
1,615-game ladder.

## AN OPEN ARCHITECTURAL QUESTION (user, end of day seven)

**"Maybe we need different models for different props. Maybe we are
reaching too hard trying to recreate everything in one go."**

The day's evidence supports this. Hook work moved the outs distribution a
long way (CRPS 2.2199 -> 2.1505, whole-inning 9.5% -> 66.3%) and moved the
run level NOT AT ALL (F7 6.57 before and after). Those quantities are
separable in practice, and `calibrate.loss` targeting the outs distribution
while runs sit 5% light is one model being pulled two ways — a fix for one
quantity has to justify itself against a loss built for another.

WHAT ONE SIMULATOR BUYS, and what separate models would give up, is
COHERENCE: a team total and a starter's outs come out of the same simulated
game, so they cannot contradict each other and the correlations are free.
Separate models will happily price a starter for seven innings and a bullpen
for five.

THE MIDDLE PATH, and the recommendation: keep the simulator as the
generative model and add a THIN PER-QUANTITY CALIBRATION LAYER on its
output — a fitted map from predicted distribution to corrected distribution,
one per prop. Standard technique, keeps coherence, and lets each quantity be
right without the hook and the run model competing for the same parameters.

Note this is a departure from `AF_PLAN.md`, which says props should FOLLOW
from a game simulation that is actually right. Worth deciding deliberately
rather than drifting into.

**AND A CAUTION ON THE NOTES.** Much of `NOTES-context-layer.md` on the run
distribution ("compressed — too many shutouts and too few crooked numbers")
came out of chasing TAILS. It is evidence about tails, not about the bulk.
The user's read from the dashboard is that the distributions are too WIDE
around the likely numbers, which is the opposite claim about a different
part of the distribution, and both can be true at once.

## THE FINDING THAT SHOULD DRIVE THE NEXT SESSION

**The run distributions are CALIBRATED but nearly UNRESOLVED, and the
ceiling on game totals is tiny.**

Widths are right — the probability integral transform over 500 games is
uniform at every prefix (middle half 54.6 / 50.2 / 47.8% against 50%). What
was wrong is RESOLUTION, which PIT cannot see: a model handing every game
the same distribution, centred correctly, produces perfectly uniform PITs
and is useless for choosing between games.

    prefix   our spread   implied true   share   corr w/ actual   ceiling
    F3          0.32          0.39        83%        0.160         0.165
    F5          0.47          0.79        60%        0.205         0.251
    F7          0.56          0.69        81%        0.166         0.188

'our spread' is the sd of our per-game predicted means. 'implied true' is
sqrt(var(actual) - mean within-game var). 'ceiling' is the correlation a
PERFECT forecaster would achieve, which is between-sd over total-sd.

WE ARE AT 82-97% OF THE CEILING, and the ceiling is 0.19. About 96% of the
variance in a game total is within-game randomness no model can touch. The
predictions look samey because games ARE samey in expectation — a perfect
model ranges about 6.5 to 9.5 runs, not 3 to 15.

**This reframes the whole "0-for-everything" imported-feature list.**
Handedness, park, day/night and arsenal are exactly the features that
DIFFERENTIATE games rather than shift the level, and the differentiable
share of a game total is about 4% of its variance. An effect that size
cannot register against this target however well implemented. That is not
evidence they work — it means the nulls were UNINFORMATIVE, and re-testing
them against a game total will stay uninformative.

**So: test between-game features against a target that HAS between-game
signal.** Starter outs and strikeouts carry far more of their variance in
the pitcher's own rates than a team's run total ever will. Measure the
ceiling FIRST for any target before spending a day on a feature.

## WHAT TO DO NEXT

**1. BETWEEN-GAME DIFFERENCES.** We produce 60-83% of the real game-to-game
variation. Start by computing the CEILING for each target — starter outs,
K, team totals — so effort goes where signal exists. Then ask which inputs
should differentiate games and are not: opposing lineup quality, park,
bullpen strength. Note the run-total ceiling is 0.19 and we are at 88% of
it, so that target is close to exhausted.

**2. THE RUN LEVEL — 5% light at every prefix.** The ladder has said this
all day and every day; nothing has moved it. It is the stated product and it
is the one number that is unambiguously wrong. Note the ladder CAN see this
(it is a level error, not a redistribution) even though it cannot see a hook
change.

**3. The 12-14 out bucket.** 19.4% against a real 16.6%, the largest
remaining misfit in the STARTER-LENGTH distribution. That is 4.0-4.2 innings, which is where books hang outs
lines. Untouched by everything above.

**4. Collapse to ONE engine.** `sim.simulate_start` and
`game.simulate_game` both exist; the start-level loop has no bullpen, no
margin and cannot produce a team total. `quote`, `price`, `calibrate`, `f5`
and `versus_market` all sit on it, and every calibration table in the notes
was produced by it, so the migration invalidates recorded baselines in one
commit. Note `USE_MEASURED_INHERITED` RETIRES with that loop rather than
needing a port — `game.py` plays inherited runners out for real.

**5. The blind re-simulation is DONE and scored.** Six games from
2026-08-24, rates cut off before the date, published as a dashboard with the
actuals overlaid (`scratchpad/lastnight.py`, `scratchpad/dash.py`,
`scratchpad/actuals.json`). Mean sim total 8.16 against an actual 8.00 — a
gap of 0.1 standard errors. 78 quantities, mean percentile 0.461. It
confirms nothing is grossly wrong and CANNOT resolve a 5% level bias: six
games carry +/- 1.7 runs of resolution.

**6. Within-start K% persistence, +6.4 sigma.** Whether he has the
swing-and-miss tonight carries; contact outcomes do not. Unused, and it bears
directly on strikeout props, which is what `quote` gets asked about most.

**7. Refit the hook properly.** `calibrate.tune` is serial, samples 500 of
3,248 starts, and fits `sim.simulate` — the engine being deleted.
`scratchpad/tune_game.py` fixes all three and does a joint search, but its
objective still omits SPREAD, so it compresses the distribution to buy the
terms that are weighted.

## TRAPS, MEASURED THE HARD WAY

**A branch must carry an OFFSET from the shared intercept, never an absolute
level.** Callers disable the hook by driving `mid_intercept` to -99 —
`team_offset`, the patience fits and the never-pull tests all use that idiom.
This bug was introduced, fixed, and reintroduced in a different branch hours
later on the same day.

**Residualising against a mean that CONTAINS both sides manufactures a
negative correlation.** For n starts and a window of w the artifact is
`(-1/n) / sqrt((1/w - 1/n)(1 - 1/n))`, which is -0.158 at n=21, w=7. A
measured -0.112 was LESS negative than noise and concealed a true +0.21 — the
sign was backwards. Leave-both-out, always.

**Do not fit counted points.** A least-squares slope through five measured
hazard values got the shape wrong: the real hazard is flat from nought to one
run then climbs, and a line charges +0.724 where the truth is +0.296.

**`calibrate.loss` does not weight SPREAD.** Any optimiser pointed at it
compresses the outs distribution to buy the hazard curve and boundary share.
Report SD alongside; do not add it to the objective while the hook is
compensating for something else.

**The prefix ladder cannot see anything that changes WHO throws.** Starters
and relievers are equal in aggregate here (K-BB 0.1358 against 0.1333), so a
hook change is invisible to it. The boundary fix measured |sigma| <= 1.1 on
the ladder and +4.7 on outs CRPS — same change, same games.

**A mutation harness must refuse to run on a dirty tree.** Backups belong
outside the tree. A SIGKILL between mutate and restore left a shipped
mechanism switched off, and the next run backed up the mutated file and
restored that.

---

# ARCHIVE — day six and earlier

Kept for the measured negatives. Anything about the hook here is
SUPERSEDED: the learned model described below is switched off,
for reasons in the day-seven section above.

# Resume here — state as of 2026-08-25 (day six)

## START HERE

**Read `CLAUDE.md`'s THE OBJECTIVE section and `AF_PLAN.md` first.** Judge
every change on ACTUAL OUTCOMES. CLV is not the target — measured, our
resolution is LOWER than the opening price's while we still "beat the open",
so a CLV edge can rise while the model gets worse at baseball.

## WHAT LANDED ON DAY SIX

**A learned removal model replaces `sim.Hook` for starters**
(`src/context/removal.py`, `game.USE_LEARNED_HOOK`). Per-decision logistic on
86k plate appearances from play-by-play. AUC 0.9123 against the shipped
hook's 0.8755, log loss 27% better, on a date holdout. Coefficients persisted
to `removal_model.json` so the sim needs no sklearn at run time.

    THE HOOK IS A WORKLOAD RULE. Pitch count alone ranks removals at AUC
    0.901; the full model reaches 0.914. Traffic, damage, runs, TTO, pitcher
    quality and all thirty clubs together are worth +0.013.

    RUNS RANK 11th OF 14 FEATURES. Independently confirmed by the refit,
    which halved `per_run` 0.6 -> 0.3 and moved nothing else.

    CLUB EFFECTS ARE WORTH +0.002 AUC and are dropped. Fifth independent
    finding that team-specific hook effects do not pay.

**Times through the order** (`src/context/tto.py`, `sim.USE_TTO`). Measured
on 85,909 starter plate appearances: strikeout rate falls 19% from the first
pass to the third, walks +9.5%, homers +6%, BABIP flat. Multipliers are
RE-CENTRED to a PA-weighted mean of 1.0 — anchoring them at pass 1 would
raise every pitcher's strikeout rate. It fixed first-inning error +0.070 ->
+0.005 (-1.8 sigma), the largest outcome-based gain of either day.

**Measured shrinkage constants** (`src/context/stabilise.py`,
`rates.USE_MEASURED_STABILISE`). The four imported `STABILISE` values were
wrong in both directions: batter rates over-shrunk ~2.2x, pitcher HR rate
UNDER-shrunk 2.7x, and one table was serving two populations that differ
six-fold on home runs. Now split by population.

**Relief-outing length, mid-inning relief changes, inherited runners by
base and out** — all measured, all shipped behind flags, and all with NO
demonstrated effect on prediction across three framings (mean prefix error,
CLV, distributional CRPS). Measured values stay; see the standing rule.

## THE YARDSTICK, AND WHY MOST THINGS READ AS NULL

We sit at **91-98% of the market's resolution** on outcomes and are BETTER
CALIBRATED than it (August reliability 0.0005 against Kalshi's 0.0014). The
entire remaining prize is about 2.5 Brier points. So a mechanism moving 0.02
runs is exactly what the ceiling predicts, and demanding each one clear 2
sigma alone guarantees everything reads as a failure.

Use `scratchpad/leverage.py` BEFORE building: it swings each parameter across
its reliability-adjusted club spread and reports the runs of separation it
could buy. Under ~0.05 runs it cannot matter however real it is. It has
already redirected a day of work.

## WHAT IS ACTUALLY WRONG WITH THE MODEL

Two durable defects, both from the refit diagnostics on unseen data:

  * **The sim is 0.13 runs light per side** — 2.32 simulated against 2.45
    actual. This survived measured advancement, measured inherited runners,
    TTO and the new shrinkage. Most durable defect in the model.
  * **It is short of crooked innings.** 15.2% of sides score 5+ against
    17.7% actual, while shutouts are right (22.6% vs 22.0%). The upper tail
    is too thin, and that is where totals are decided.

## THE ORDER OF WORK

0. **EARLY HOOKS.** The removal model is fitted at a 4.6% base rate and
   overwhelmingly fits the ordinary case near 90 pitches. An early hook is a
   different event. Chase Burns went 3.2 on 2026-08-24; the sim priced
   "pulled in the 4th" at 6.5%. Fit it separately or at least check
   calibration in that region.
1. **Score the learned hook on OUTCOMES**, not just AUC. It is wired in and
   its effect on the prefix ladder and on starter-length distribution has
   NOT been measured yet.
2. **Per-batter and per-pitcher HIT MIX.** Every ball in play that becomes a
   hit is split single/double/triple by ONE LEAGUE CONSTANT, so a slugger
   and a slap hitter with the same BABIP produce identical doubles. Leverage
   screen puts it at 0.145 runs — the highest-scoring thing in the model
   that does not exist yet, and it feeds the advancement tables.
3. **Make `ladder` per-side.** AF_PLAN targets TEAM totals; the ladder sums
   both sides, which hid a 5% dispersion error that per-side scoring found
   immediately.
4. Role-based bullpen deployment (passed its gate, unbuilt, but hook-adjacent
   so expect the same story).

## MEASURED AND DEAD — do not re-run without a NEW approach or NEW data

* **The latent "he does not have it tonight" state.** Tested three ways:
  outcome damage does not persist within a start (0.1 sigma), exit velocity
  barely persists (1.8 sigma, and inflated by the constant lineup), and
  NEITHER predicts later runs (0.1 and 0.4 sigma). Against the SAME NINE
  HITTERS, 94.6% of the time. A rough first pass tells you nothing about the
  next one.
* **Team-specific hook effects.** Five findings now, including a
  per-decision test worth +0.002 AUC.
* **Per-club advancement** — split-half r +0.11 to +0.38, leverage <=0.032
  runs.
* The nine imported features from earlier days (handedness, park, day/night,
  bullpen availability, arsenal, recency, ...).

## TRAPS THAT COST REAL TIME

* **Mutation harnesses lie if a mutation preserves file SIZE** — stale .pyc
  is reused and the mutation never runs. All `scratchpad/mutate_*.py` now
  clear `__pycache__` and set `PYTHONDONTWRITEBYTECODE=1`.
* **`ladder.simulate_prefixes` needs per-(game, draw) seeding.** Per-GAME
  looks like a fix and is not. Without it a bullpen flag moves F1, an inning
  no reliever reaches. Pinned by
  `check_the_first_inning_is_immune_to_a_bullpen_flag`.
* **Fork, not spawn, for the fit workers.** A spawned child re-imports
  modules at DEFAULT global state, so every flag silently reverts and the
  search returns a flat surface that reads as "this parameter does not
  matter". Pinned by `check_worker_state_crosses_the_fork`.
* **Six checks have now been found to guard nothing**, one of them
  pre-existing. Write the mutation before believing the check.
* **Pairing beats sample size.** Prefix error varies ~0.28 runs across games
  and swamps a 0.02-run effect; the paired per-game difference has an SE
  near 0.02. Comparing two independently-reported means will never resolve
  anything here.

## STATE

* 294 checks, `make test`, no network, no pytest.
* `fitf5.losses` is parallel over salts (4.4x, fork-based). A full hook fit
  is ~1.2h, not 5.1h.
* `pitch_center`'s search grid was stale by two revisions and had silently
  disabled `--with-hook`; re-centred on the shipped 80.0.

---

# Below: day five and earlier

## DAY FIVE

**Read "What the benchmark IS" below before anything else.** The
objective is the game simulation being right, measured on ACTUAL
OUTCOMES through `fitf5`. Everything else — props, totals, prices — is
expected to follow from that. The CLV work below is a downstream sanity
check and day five briefly mistook it for the scoreboard.

### The headline CLV numbers in this file are ONE MONTH

Read this before believing any CLV figure in this file. The K-prop record
(corr +0.586, blend +32.9%, direction 73.2%, +3.7c) was measured on eight
dates in mid-August. Re-measured at n_sims=1500 on the whole backfilled
season it does not hold up, and the reason is not sample size or Monte
Carlo error — it is that August is genuinely unlike June and July:

    window            n     corr    blend    dir     cents
    June           1,464  +0.416   +13.1%   59.1%   +1.8c
    July           3,134  +0.299    +7.7%   59.6%   +1.7c
    August (21d)   3,164  +0.575   +30.4%   69.0%   +3.3c
    SEASON (82d)   7,762  +0.451   +17.5%   63.4%   +2.4c

August reproduces the record almost exactly. June and July run at half the
edge, and July — the largest single month before August — is the worst.

**SIX explanations have now been tested and eliminated**, each on data:
Monte Carlo error; the measured advancement/GIDP tables; population
composition (restrict to the 101 arms priced in all three months and the
gap survives: +1.7c / +1.9c / +3.2c); liquidity composition (August holds
FEWER thin markets and still wins in every trade bucket); a directional
drift the model happened to match (centring each month's drift out GROWS
the August edge — the model leans under, so the drift was suppressing
measured accuracy everywhere); and a staler open (first-trade lead time is
12.9 / 13.8 / 14.4 hours — flat).

The liquidity result reverses across levels, which is the strongest clue:
WITHIN a month more trades means less edge, ACROSS months more trades comes
with more edge (37.7 -> 64.2 per market). Whatever changed is not liquidity.

See `NOTES-context-layer.md` for the full table of each test. What is left
to check is all about the market and the feed rather than the simulator:
whether Kalshi changed how it opens these markets, whether our own lineup
and roster completeness improved, and whether the mix of listed games
changed. Rows are cached at `scratchpad/august_rows.json` — do NOT
re-simulate to ask a market question.

**Plan against the June/July number (~+1.8c), not +3.7c and not the
pooled +2.4c** — the pooled figure is dragged up by the one month nobody
can explain, so it is not a number to size bets against. And note the
pooled season correlation
sits above both June and July, which is what pooling windows with different
levels does — quote the cents, not the corr.

**n_sims saturates at 1500.** On the same 1,222 August contracts: 250 gives
corr +0.490, 1500 gives +0.515, 2000 gives +0.516. Real attenuation (34 of
627 five-cent disagreements at 250 were noise) but small, and there is no
reason to pay for 2000 anywhere.

**z is not an effect size.** It rose from +41.4 to +67.1 purely because n
grew 6x. It measures confidence that an edge exists, not how big it is.

### The measured advancement/GIDP tables are NEUTRAL on K props

Four states at n_sims=1500 on the same 1,222 contracts, corr +0.513 to
+0.515 and blend +23.4% to +24.0%. Flat. Whatever the F5 scoring run says,
the measured tables cost nothing on this market.

### Three mechanisms shipped, all measured, all separately scoreable

* **Relief outings run to their measured length** (`src/context/relief.py`,
  `game.USE_MEASURED_RELIEF_LENGTH`). The continuation hazard is
  conditioned on the state the reliever ENTERED in — 20.1% of arms handed a
  clean inning come back out against 62.7% of those brought in with two
  down, over 13,248 outings. Effect on the engine: arms per side 5.05 ->
  4.07, mean total unchanged at 8.16 -> 8.19, **sd 3.91 -> 4.08**. Level
  held, spread up, which is the variance mechanism and the right direction
  against the known under-dispersion.
* **Inherited runners score by BASE and OUTS** (`src/context/inherit.py`,
  `sim.USE_MEASURED_INHERITED`). Counted on 5,507 inherited runners across
  2,006 games. THE ADVANCEMENT MISTAKE AGAIN, and it fails the same way —
  pooled it lands at 0.312 against the shipped flat 0.330, near enough to
  look right, while the cells run 0.127 to 0.771:

        0 out   1 out   2 out
    1B  0.396   0.267   0.127
    2B  0.628   0.428   0.215
    3B  0.771   0.633   0.229

  Two-out handovers are the most common state (2,624 of 5,507) and the flat
  rate over-credits every one, inflating a departing starter's earned runs.
  Start-level runs/start 2.5693 -> 2.5497.

* **Relievers can be pulled MID-INNING** (`game.USE_MEASURED_RELIEF_HOOK`),
  from a per-PA hazard over 50,023 in-inning relief plate appearances. Of
  4,026 real mid-inning handovers only 41.8% come from a starter; the other
  58.2% are reliever-to-reliever and the engine could not make them at all.

        0-2 bat     3-5     6-8      9+
    0r    0.015   0.099   0.073   0.070
    1r    0.045   0.130   0.097   0.060
    2r    0.033   0.141   0.122   0.087
    3r+   0.061   0.109   0.116   0.080

  NOT monotone in batters faced: the first two are nearly immune, then it
  peaks, then falls. `game.py` used to hard-code that protection as a flat
  rule, which is exactly why it could never pull a reliever.

  **SURVIVORSHIP TRAP, recorded because it is easy to fall into.**
  Conditioning on a stint's TOTAL runs gives 19.1% rising to 40.5% and reads
  perfectly plausibly — it is inflated by the arms that stayed in and kept
  being scored on, because for a pitcher who was not pulled the total keeps
  accumulating past the decision point.

**Pitchers used per side: league 4.30.** Model 5.05 with none of this, 4.07
length-only, 5.66 hook-only, **4.53 with both**. Length-only is equally close
in absolute terms and gets there BY CANCELLATION — no mid-inning relief
changes at all, offset by outings that run too long. That is the pattern
these notes keep warning about, so prefer the state with both mechanisms.

**Not yet measured: whether any of this improves a PRICE.** Run
`scratchpad/relief_value.py` — team totals, four flag states, paired on the
same contracts. Whatever it says the measured values stay; a worse score
locates compensation rather than licensing a revert.

## What the benchmark IS, because day five briefly forgot

**The objective is the game simulation being right. Prices are downstream.**
CLV is a sanity check on a model that is already correct on outcomes; it is
not the thing being optimised, and reading it as the scoreboard is how a
session ends up chasing a market anomaly instead of a mechanism.

The F5 TEAM TOTAL benchmark is `fitf5`, scored on ACTUAL OUTCOMES:
`side_cases` gives one row per pitching side where `runs` is what that side
really allowed through five (the opposing team's F5 score), and `_rps`
scores the simulated distribution across `SIDE_LINES` = 0.5..8.5, the full
support. The comment there is explicit about why it is not a book's lines:
doing that "would tune the model to the shape of somebody's board".

**Kalshi does not list an F5 team total at all.** Cached series are
`KXMLBKS` (10,525), `KXMLBTEAMTOTAL` (7,084, FULL-game team runs),
`KXMLBF5TOTAL` (3,521, the COMBINED first-five total) and `KXMLBTOTAL` (25).
So there is no market test for the primary target and there does not need to
be one. `scratchpad/score_relief.py` scores the three day-five relief
mechanisms through `fitf5`, which is the correct payoff test; the Kalshi
team-total run below is a downstream check on the SECONDARY target.

### Downstream check: full-game team totals vs Kalshi

August 2026, 21 dates, 2,335 settled contracts, day-five mechanisms ON:

    n_sims=250    corr +0.208  blend  +8.3%  dir 58.6%  +1.3c
    n_sims=1500   corr +0.236  blend +10.3%  dir 58.7%  +1.3c

Same n_sims shape as everywhere — 60 of 1,234 five-cent disagreements at 250
were noise, cents unchanged — so 1500 stays the operating point.

Brier skill ours +18.4% against the market's +20.7%: still behind a settled
close, as everywhere. This is the FULL-GAME team market, not F5, and it is
the secondary target. Do not read it as "the product is weak" — that was a
day-five misreading that cost an hour.

**Market data starts in July.** `KXMLBF5TOTAL` and `KXMLBTEAMTOTAL` have NO
June contracts, so the recorded F5 "+3.7c" pools July and August — the worst
and best K months. Splitting it by month is worth doing, and it doubles as a
test of whether the August anomaly is market-wide or specific to K props.

### The mutation harness itself was lying — read this before using it

Rewriting a source file twice inside the same mtime second means a
SIZE-PRESERVING mutation (`+= 1` -> `+= 0`) reuses stale `.pyc` and never
takes effect, reporting a genuinely-guarded behaviour as unguarded. Both
`scratchpad/mutate_*.py` now clear `__pycache__` and run with
`PYTHONDONTWRITEBYTECODE=1`. Anyone doing mutation work here hits this.

It also caught two real defects in checks written the same hour: one whose
fixture returned the same count under both the right and wrong definition,
and two that were behaviourally vacuous because the guards they targeted
were defensive rather than load-bearing. **Write the mutation before
believing the check.**

---

# Below: state as of end of day four

`NOTES-context-layer.md` has the long record; this is what you need to act.
Read it before touching anything, then read `CLAUDE.md`.

---

## The one-paragraph version

Play-by-play is scraped and it changed what we know. The advancement
constants the run model rests on were **published guesses that were wrong in
both directions and cancelled**, and they are now measured on this league.
The bullpen work has passed its gate — role is real and projects from prior
games — and per-club baserunning has FAILED its gate, so the league number
stays. The model is calibrated; the binding constraint is execution near the
open, and the biggest remaining mechanism is the bullpen.

---

## What is new since day three

**205 MB of whole-game play-by-play, all 2,006 games** (`sources/pbp.py`,
`.cache/pbp/`, ~2 min over 8 workers). Fetched whole and stored whole —
extracting a subset to save disk is a false economy, the API call is
identical either way and re-scraping for a discarded field is the expensive
mistake. `pbp.plays()` reconstructs base-out-score state BEFORE every play;
`pbp.stints()` turns that into one row per pitcher per game.

**`context.db` is new and `morning_bets.db` is now READ-ONLY to this
layer.** Derived tables (`mlb_stints`, 17,260 rows) live in the new file;
the pipeline DB attaches through a `mode=ro` URI as the `bets` schema, so
joins read `bets.games` exactly as before and a stray INSERT raises. The
pipeline DB is not version controlled and holds a season of boxscores that
cannot be regenerated — that is the whole reason.

**Independent validation of the extraction:** PBP-derived outs agree exactly
with the boxscore on **99.68%** of 16,653 pitcher-games, and reconstructed
base state agrees with statsapi's own `menOnBase` on 62/62 non-inning-ending
plays of the first game checked.

---

## Where the edge is (n_sims CORRECTED — the old table understated it)

Every recorded CLV number was measured at `n_sims=250`, which carries ~3.2
cents of Monte Carlo error against a 3.7-cent median disagreement. That
ATTENUATES. Re-run at 1500 on the same 2,676 F5 contracts:

| | 250 sims | 1500 sims |
|---|---|---|
| CLV corr | +0.456 | **+0.496** |
| z | +36.2 | **+39.5** |
| blend vs open | +20.7% | **+24.9%** |
| 5c+ direction | 56.3% | **63.2%** |
| cents our way | +2.9c | **+3.7c** |
| n disagreements | 932 | **787** |

145 of the "five-cent disagreements" at 250 sims were simulation noise
rather than opinions, and +3.7c now matches the K prop exactly. **K props,
team totals and game totals have NOT been re-run and are all understated by
an unknown amount.** That is cheap and it is high on the list, because it
may change which markets look worth pursuing.

Nothing has ever beaten a settled CLOSING price. The edge is being EARLY.

---

## The advancement tables are measured now, and they were cancelling

152,153 plays (`src/context/advance.py`). The published references were
wrong in BOTH directions at once, which is why nothing showed up in the
aggregate:

    first -> third on a single   .307 .295 .408   was .240 .280 .340
    second scores on a single    .411 .542 .796   was .420 .620 .840
    first scores on a double     .274 .346 .565   was .330 .450 .630
    anyone advances on an out    .326 .354        was .300 .450

Too many runners stranded at second, then too many of the ones who got
there scored. Runs per baserunner sat at **-0.2%** while every component was
off by 3-6 sigma. **The aggregate was right for cancelling reasons**, which
is the exact failure the notes warn about, and it means the model breaks
wherever the compensation does.

Two mechanisms were wrong in SHAPE, not level, and both are now fixed:

* **Advance-on-out is per base.** One pooled constant moved every runner
  together on one coin flip. Measured, the man on second goes ~twice as
  often as the man on first (.49 vs .22 with nobody out), so no single value
  is right for both. Now three tables, rolled LEAD RUNNER FIRST, and
  conditioned on the base ahead being free — which is a different quantity
  from the marginal, and using the marginal would double-count the blocking.
* **Scoring from first on a single did not exist.** Measured .022 / .043 /
  .068 by out count. Added as its own table with a cumulative threshold
  against first-to-third, so the two stay disjoint.

**`sim.USE_MEASURED_ADVANCEMENT` and `sim.USE_MEASURED_GIDP` switch each
change independently** (`LEGACY_ADVANCEMENT` holds the old values). Every
mechanism here is discrete and must stay separately scoreable — the winning
combination is not necessarily the newest state.

**A test changed meaning and you should know.**
`check_advancement_rises_with_the_out_count` asserted a strict 0<1<2 ladder.
That is a property of the published references, not the league: first-to-
third goes .307 .295 .408, so the middle entry is 0.8 sigma BELOW the first.
The invariant was weakened to what the data supports (two-out >> nobody-out)
rather than making the data fit the test.

**THE PAIRED F5 SCORING RUN WAS IN FLIGHT WHEN THIS WAS WRITTEN.** Four
states — advancement published/measured x GIDP published/measured — on the
same sides, outcomes and salts, train before 2026-07-01 and test after.
Re-run it: `scratchpad/score_adv.py`. Whatever it says, the measured values
STAY: a guess that happens to score well is still a guess, and if measured
values score worse that locates the compensation rather than refuting them.
Do NOT reverse-engineer which constant to un-measure to win the score back.

### The GIDP constant is on the wrong denominator

`GIDP%` as published is double plays per OPPORTUNITY — every PA with a man
on first and under two out — and measures .089/.095 here, right next to the
shipped 0.11. But the simulator rolls it only once a ball in play has
ALREADY become an out, about half as many chances, where the real rate is
**.209/.224**. So it turns roughly half the double plays it should.

Not simply corrected, because the F5 fit chose 0.11 in the model's own
denominator over a grid reaching 0.19. Something compensates. Behind
`USE_MEASURED_GIDP`; the scoring run adjudicates.

---

## Per-club baserunning: MEASURED, and it does not pass the gate

The hypothesis was that league-wide generalisation costs accuracy. Mostly
no. Split-half per club, first half of each club's own season against its
second (`advance.py --by-team`):

    grounds into a double play      r +0.384   n=30
    first -> third on a single      r +0.289   n=30
    advances on a ball-in-play out  r +0.119   n=30
    second scores on a single       r +0.111   n=12

Compare the bullpen role gate at r +0.55 to +0.78. The observed club spread
looks large — first-to-third runs .265 (TEX) to .493 (DET), sd .051 — but
with a split-half r of .289 most of that is a season of sampling noise, not
a persistent club property. **Do not wire per-club advancement tables.**

GIDP is the one with any case (r +0.384, and it makes sense as a batter
trait — ground-ball rate and speed), and even that needs heavy shrinkage.

---

## BUILD THE BULLPEN MODEL — the gate has passed

The question was never "is random deployment wrong". It is whether ROLE IS
PREDICTABLE FROM PRIOR GAMES, because otherwise role-based deployment is a
more expensive way to draw from the same distribution. Split-half over 319
relievers, chronological (`src/context/deploy.py`):

    outs recorded        r +0.780
    entry inning         r +0.627
    high-leverage share  r +0.551
    entry margin         r +0.393

**Role is real and it projects.** Build it.

The score does select the arm, but modestly: K-BB% .154 leading 1-3 against
.127 down 4+, and close (<=2) .147 against blowout (>=5) .134 — a gap of
0.36 SD of the reliever pool. The model draws at random, so it prices every
late inning as the AVERAGE arm: too good in a blowout, too bad in a one-run
game, wrong in both tails at once.

**The bigger errors are structural, not selection.** 13,248 relief outings
average **3.47 outs** against the model's flat 3.00, only 52.2% are one
clean inning, 25.4% are longer, and **30.4% are mid-inning entries the model
cannot produce at all.** That changes how many arms a game uses, which is a
variance question, and variance is what a total settles on.

Supporting: team-total direction accuracy by how deep the opposing starter
went — 49.9% (<=15 outs), 52.7% (16-18), 57.1% (19+). Monotone. The relief
innings are what destroy the edge, so the ~40%-bullpen markets are
recoverable rather than hopeless.

Do NOT fit team-specific bullpen offsets. That is the patience/leash mistake
waiting to happen.

---

## The order of work from here

0. **WHY IS AUGUST DIFFERENT?** The single most valuable open question —
   the whole recorded edge lives in one month and nobody knows why. Not a
   maturation curve (July is worse than June). Check Kalshi liquidity and
   trade counts by month, lineup-data completeness, and whether the
   `MIN_TRADES = 5` filter admits different populations across the season.
1. ~~Re-read the paired F5 scoring result~~ — RUNNING, ~43 min per state,
   four states, so ~3h. First state landed: adv=published gidp=published,
   train 1.59699 / test 1.63980. Resume from `scratchpad/score_adv.out`.
2. ~~Re-run every CLV test at n_sims >= 1500~~ — K props DONE (see day
   five). Team totals and game totals still pending; use
   `scratchpad/clv_nsims.py`, which takes `team`/`total`/`f5`/`k`/`outs`.
   Do them month by month, not pooled — pooling is what hid this.
3. **Bullpen: role score from prior games**, deploy by role and live margin
   instead of sample order. `game.py` already tracks the margin.
4. ~~Bullpen: multi-inning outings~~ DONE. **Mid-inning reliever-to-reliever
   changes are NOT** — still the biggest missing piece of the 30.4%.
5. ~~Bullpen: inherited-runner rates from PBP by base-out state~~ DONE for
   the start-level path (`sim.USE_MEASURED_INHERITED`). `game.py` never
   used the constant. `f5.py` does not reference it either — day four's
   note that it did was wrong; the constant lives in `sim.py` alone.
6. **Re-run team totals and game totals** — the targets this unlocks.
7. **Times through the order** — the biggest absent mechanism. The sim wraps
   the lineup and charges nothing for it. PBP has real TTO per PA. Fit as a
   RESIDUAL.
8. **Handedness, re-run as a residual and PRE-REGISTERED.** Dead as an
   imported scalar; PBP carries `batSide`/`pitchHand` per plate appearance.
9. **Rest/availability, re-opened** — same reasoning.
10. `price.py` / `quote.py` are start-only and cannot price an F5 or a team
    total, which is the stated product. `game.py` exists and does.
11. Stale `hook_patience.json` / `hook_leash.json` — 206 offsets fitted
    against a model that no longer exists. `USE_OFFSETS` is False. Refit on
    the training window or delete.

---

## Rules that have earned their place

**A fitted parameter at the EDGE of its grid is a MISSING MECHANISM.** Four
for four: absent hit-by-pitch, absent fielding errors, out-dependent
advancement twice.

**Prefer a high-n ratio to a low-n aggregate.** Runs per baserunner over
~17,500 simulated starts tracked every real fix; the mean F5 total over a
few hundred games gave four consecutive "improvements" inside one standard
error.

**MEASURING IS NOT FITTING.** Replacing a published constant with the same
quantity counted on this league is not tuning against the settlement value,
provided the conditioning matches the code path exactly. There is no loss
function behind the advancement tables and there must not be one.

**THE DEAD LIST RECORDS HOW A THING WAS TRIED, NOT THAT IT IS UNKNOWABLE.**
Six of the nine dead features were imported scalar multipliers, scored
against a model that has since changed, on half the data. Re-opening one is
legitimate when the APPROACH changes (residual fit rather than import) or
the DATA does (play-by-play). Pre-register it, so it is a test and not a
fishing trip.

**Verify every new check by mutation.** THREE tests in this project have
turned out to guard nothing, and only the mutation run revealed it. The most
recent: a split-half check that passed just as happily when the outings were
sorted, because sorting turns every pitcher into a promotion and made the
correlation MORE negative, not less. It was the assertion that could not
tell them apart, not the mutation that was subtle.

---

## Do not re-run these (measured, recorded)

* **Home run props** despite being the largest market (29,128 contracts) — a
  BATTER outcome, and we hold one `hr_pct` with no batted-ball data.
* **NRFI** — Brier skill -2.9%. Three batters is signal-free variance.
* **Cross-book arbitrage on game totals** — Kalshi agrees with DraftKings
  within ~1 cent on matched half-point lines. Same consensus.
* **Nine features** measured null: handedness, park on raw rates, day/night,
  bullpen availability, arsenal scalar, input-uncertainty propagation,
  recency weighting (3-5 sigma the WRONG way), arsenal mixture on
  strikeouts, arsenal mixture on contact. The last two were pre-registered.
  See the dead-list rule above before assuming any of these is closed.
* **Pitcher archetypes by pitch mix** — real for relievers (permutation null
  p=0.003), absent for starters, too small to wire in.

## State

* 267 checks, `make test`, ~60s, no network, no pytest. (Day four's "257"
  was wrong — the baseline was 245, matching CLAUDE.md. Day five added 22:
  7 in `test_relief`, 8 in `test_inherit`, 4 in `test_game`, 3 in
  `test_sim`.)
* 2,006 final games, F5 scores on 2,009, real pitch counts on 16,624
  pitching rows, 17,260 stints, 205 MB of play-by-play.
* `.claude/settings.json` sets bypass permissions for this repo, denying
  `git push`, `make publish`, `rm -rf` and reading `.env`.


## TRAP ADDED ON DAY SEVEN — DO NOT READ A LEVEL OFF A SMALL SAMPLE

Three blind games put the mean percentile of actuals at 0.356 and it was
reported as the model running hot. Six games put it at 0.461. The ladder,
over 1,615 games, says the opposite — 5% LIGHT. Real game totals have an sd
near 4.4, so the standard error of the mean gap is 2.5 runs at n=3, 1.8 at
n=6 and 0.11 at n=1,615.

TWENTY THOUSAND SIMULATIONS PER GAME DO NOT HELP. They sharpen the
PREDICTION, not the EVALUATION: there is still exactly one real outcome per
game. Simulating a million times leaves the right-hand side of the
comparison at n=6.
