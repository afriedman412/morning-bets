# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

**THIS FILE IS RULES AND ARCHITECTURE. STATUS LIVES ELSEWHERE** — what is
open is `TODO.md`, what was measured is `NOTES-context-layer.md`. Every
engine-status line ever written here went stale and then misled a session for
a week. Do not add one back.

## THE RULES, IN ONE SCREEN (added 2026-08-30)

Every line here was bought with a specific mistake. The failure behind each
is in THE FAILURES BEHIND THE RULES below; read those once, then use this
index.

  1. **THE OBJECTIVE IS ACCURATE SIMULATION AGAINST WHAT HAPPENED.** CLV is
     not the objective and must never decide whether a mechanism helped.
  2. **A FLAT MEAN IS NOT A NEUTRAL RESULT.** Judge the SHAPE against
     actuals. CRPS is dominated by the bulk and reads neutral on a tail fix.
  3. **THE LEVERAGE FLOOR DECIDES PRIORITY, NOT ADMISSIBILITY.** Small and
     MEASURED ships. Small and FITTED never does.
  4. **COUNT IT, DO NOT IMPORT IT.** Every imported baseball effect has
     measured zero; every constant counted on this league was wrong as
     shipped.
  5. **DO NOT SOLVE FOR A LEVEL.** Scaling a table until the mean lands on
     a target is fitting. A tuned 0.20 was refuted by a counted 0.16.
  6. **NEVER FIT ON ROWS YOU WILL SCORE ON.** `HOLDOUT` = 2026-07-01, one
     literal for the whole project, in `src/context/holdout.py`.
  7. **A NULL IS A CLAIM.** Positive-control every screen; a mis-specified
     mechanism and an absent effect look identical.
  8. **A GRID-EDGE PARAMETER IS A MISSING MECHANISM**, four for four.
  9. **FIT A CURVE ON THE POPULATION IT FIRES IN**, and only when something
     else covers the rest.
  10. **NAME THE DENOMINATOR — AND THE DEFINITION.** Uniform error across
      independent channels is a denominator, not a set of bugs.
  11. **WHEN A NEW NUMBER CONTRADICTS AN OLD ONE, CHECK THEY MEASURE THE
      SAME THING** before acting.
  12. **RUN INVESTIGATIONS AS LABELLED STAGES**, state the POWER and the
      STANDARD ERROR before the result.
  12b. **ONE HOLDOUT IS NOT A MEASUREMENT OF GENERALISATION.** The
      between-season spread of the baseline error is LARGER than most
      effects being measured. Score across FOUR FOLDS, report all of them,
      and set the bar before running.
  13. **DO NOT LOOSEN A TEST TO ADMIT A CHANGE.** Verify every check by
      MUTATION — one that guards nothing looks identical to one that does.
  14. **HUNT LEVEL ERRORS AND STRUCTURAL GAPS FIRST**, then refinements.
  15. **RUN THE BATTERY AROUND EVERY CHANGE AND REPORT THE DIFF** — every
      row that moved, not just the target row. `scratchpad/battery.py`.

## THE OBJECTIVE — read this before anything else

**`AF_PLAN.md` is the authority on what this project is for. Read it. It is
47 lines.**

Simulate baseball games as accurately as possible, **measured against what
actually happened**, and infer everything else — props, totals, game script
— from that simulation.

Judge every change on ACTUAL OUTCOMES: the prefix ladder (`ladder.py`,
F1/F3/F5/F7 against real runs), discrete CRPS and coverage for the
distribution shape, and resolution against what happened.

**WHAT THIS MODELS, settled 2026-08-23: F5 TEAM TOTALS**, and to a lesser
extent full team totals. Props are NOT the target — they are expected to
follow from a game simulation that is actually right.

**CLV IS NOT THE OBJECTIVE.** Closing-line value, cents-our-way,
blend-against-the-open and "beating the market" must never decide whether a
mechanism helped. Measured 2026-08-24: our RESOLUTION — real discrimination
on outcomes, from the Brier decomposition — was LOWER than the OPENING
price's in July and August while we still "beat the open" on CLV. So the CLV
edge is market ANTICIPATION, not baseball knowledge, and it can rise while
the model gets worse at predicting games.

**THE MARKET IS NO LONGER IN THIS REPO.** The betting layer — `price`,
`quote`, `scan`, `movement`, `versus_market`, `f5_market`, `team_market`,
`total_market`, `contracts`, `estimate`, `snapshot` and the
`scratchpad/clv_*` drivers — was DELETED on 2026-09-05 on the `sim-only`
branch, along with everything that ingested a capper video or ran an LLM
persona. Recover from git history if a headroom number is wanted; do not
re-import one into the modelling loop. The yardstick it provided, kept
because it bounds the remaining prize: we sat at 91-98% of Kalshi's
resolution and were BETTER CALIBRATED than it, so the whole remaining gap was
about 2.5 Brier points. The historical CLV record is in
`NOTES-context-layer.md`.

**A MEASURED QUANTITY REPLACING AN IMPORTED GUESS DOES NOT HAVE TO PROVE
ITSELF ON THE SCORE.** A flat result means the test could not resolve ~0.02
runs, not that the mechanism failed. Applying a fitting standard — "prove it
improves the loss" — to measurement work makes every correct change read as
a null. This causes as much drift as the CLV rule does.

## THE BATTERY — every change scores against everything (added 2026-09-05)

`venv/bin/python -m scratchpad.battery` — one simulation pass per fold, four
folds (July-onward of 2023-2026, rates frozen at each cut), every table read
off the same games and draws: ladder, per-inning runs, per-venue residuals,
traffic and run-mass shape, platoon, DP/sac/XBH, late-inning runs by margin,
both hook curves cell by cell, the starter's outs/K shape, the current
`outs_adjust` corrections. Header prints every `USE_*` flag; output is
`scratchpad/battery_<engine-fingerprint>.json`; `--diff <fingerprint>` prints
every row that moved by more than one se against a saved run. `--maim` is the
built-in positive control.

THE RULE: every modelling item starts by running the battery and committing
the JSON with the pre-fingerprint, runs it again at the end, and reports the
DIFF — not just the row it was aiming at. A change that moves an unrelated
row by more than one se is not done until the log says why. The battery is
also what a session reads when deciding what to work on next: "make this row
go green" is the item, not "build an instrument to see if it moved". THE
FAILURE THAT BOUGHT THIS: the fourth-inning defect and the 60-85 pitch defect
were ONE defect seen through two single-purpose scratchpads, and it took days
to notice.

## WHERE THE MODEL IS ACTUALLY WRONG

Measured 2026-08-27, and the most useful line in these docs for choosing what
to work on: **THE EVENT RATES ARE RIGHT AND THE ADVANCEMENT IS NOT.** Through
five innings the model puts exactly the right men on base (+0.0%) with
strikeouts, walks, hits and home runs each inside 1.4%, and brings 1.7% fewer
of them home. No further measurement of a RATE can close that gap.
`scratchpad/f5_decomp.py`.

And it is SHAPE, not advancement rates: reality has more shutouts AND more
blowups while the model bunches in the middle, which is CLUSTERING — plate
appearances resolve independently and real ones arrive together. Runs are
convex in clustering, so the thin tail also drags the mean. One defect, both
symptoms, confirmed by a flat dispersion term that closed 44% of the shape
error and 86% of the level gap with one number.

That term is NOT shipped: it is neutral on CRPS because a flat spread added
to everyone improves calibration and not discrimination. And the obvious way
to make it vary is CLOSED — per-pitcher and per-club dispersion do not repeat
(split-half reliability 0.07 over 107 arms, powered to see 0.32).

## THE FAILURES BEHIND THE RULES

### 2. A flat mean is not a neutral result — the distribution is the product

A run total is not a number, it is a DISTRIBUTION, so "the mean did not move"
says nothing about whether the simulation got better. Judge the SHAPE against
actuals — the mass at each value, the spread, the tails.

**THE EXAMPLE THAT SETTLES IT:** the strikeout distribution has an
essentially EXACT mean (4.86 against 4.84) and at nine or more strikeouts it
produces 6.0% where reality produces 9.5%. Judged on the mean it is healthy.
It is 3.9 sigma wrong where it matters and no summary statistic used in this
project would have found it.

**CRPS IS A WEAK DETECTOR OF THIS** and has been treated as the arbiter.
Almost all of it comes from the bulk, so a tail repair or a modest dispersion
change registers as neutral. A flat CRPS on a small measured change is the
EXPECTED result, not a rejection. Do not park a measured mechanism because
CRPS shrugged.

TWO FAILURES THIS PREVENTS, both on the same change: reading a 0.002 move in
the shutout share as a falsifier when its standard error is 0.012, and
calling a 0.3 sigma drift in the mean an overshoot that needed correcting.
**State the standard error of the thing you are about to call a result.**

### 3. The leverage floor is a betting threshold, not a truth threshold

**THE GOAL IS BETTER SIMULATION OVERALL, NOT JUST BEATING THE VIG. ANYTHING
THAT PRODUCES A CONSISTENT, MEASURED IMPROVEMENT IS WORTH KEEPING, BECAUSE
THESE CHANGES ACCUMULATE.** This OVERRIDES the reflex to discard a real
mechanism for being small.

`scratchpad/leverage.py` says "under ~0.05 runs it cannot matter however real
it is." True about A PRICE, false about THE MODEL: at a team-total line the
discrete run density is ~0.17 per run, so 0.05 runs is ~0.85 cents against
market spreads of four and up. That answers "can I bet this on its own
today", not "is the simulation closer to baseball". So the floor decides
PRIORITY, never ADMISSIBILITY.

**THE GUARD THAT KEEPS THIS FROM BECOMING A LICENCE TO OVERFIT:**
"consistent" means MEASURED, not FITTED. The thing must be counted on this
league and pass a stability gate BEFORE it is wired, as `advance.py` and
`stabilise.py` do it. Accumulating measured quantities converges on baseball;
accumulating quantities tuned until the loss moved converges on the seed —
and the noise floor is 0.0165, so anything smaller "improving" the loss is
fitting dice. **Small and measured, yes. Small and fitted, never.**

**LEVEL ERRORS ADD; SPREAD EFFECTS COMBINE IN QUADRATURE.** Nine independent
per-hitter effects of 0.010 runs make 0.030, not 0.090. Accumulation is real
but slower than addition — state which arithmetic applies before claiming a
pile of small things adds up.

### 4 and 5. Count it, do not import it — and do not solve for a level

Two things are 0-for-everything and one is not: every feature IMPORTED as
known baseball has measured zero (handedness, park, day/night, bullpen
availability, arsenal — five dead arsenal constructions now), while every
constant MEASURED on this league has turned out to be wrong in the shipped
version (advancement, the double play rate, inherited runners, the four
shrinkage constants).

AND DO NOT SOLVE FOR A LEVEL. Scaling a measured table until the mean lands
on a target hands a counted quantity back to a search, which is what every
absorbed constant in this project's history has in common. `START_K_SIGMA`
counted at 0.1625 refuted a tuned 0.20 by 4.2 sd — the clearest case here of
a count correcting a fit.

**MEASURING IS NOT FITTING**, provided the conditioning matches the code path
exactly. There is no loss function behind `advance.py` and there must not be
one. What is forbidden is handing a measured quantity back to a search, where
it goes back to absorbing other defects.

### 6. Never fit on rows you will score on. The cutoff is 2026-07-01.

Set after shipping six constants in one day that were all fitted on 2023
through 2026-08-27 and then scored on `shape.py`, which evaluates 2026-07-01
onward. Roughly 10-20% of every fitting sample was inside its own evaluation
set, and I did not notice until the user asked. **REFITTED PROPERLY THEY ALL
MOVED BY 0.1 TO 0.4 SE AND NOTHING CHANGED. THAT IS NOT A DEFENCE** — a
marginal one would have shipped contaminated and been reported as clean.

  * Anything fitted on `boundary.decisions` rows or any per-decision table
    filters to `date < HOLDOUT` BEFORE fitting.
  * `HOLDOUT` is 2026-07-01, one literal for the whole project, imported from
    `src/context/holdout.py`. Two cutoffs is how one of them drifts.
  * State the row count of the TRAINING set, not the full table, when
    reporting a coefficient.

`calibrate.build_cases` separates `rates_before` from `since` for exactly
this reason; the scratchpad fitters did not, and that asymmetry made the
mistake easy.

### 7. A null is a claim and must be tested like one

The standing failure mode is asymmetric: a positive result gets an
adversarial test immediately, a negative one gets accepted and the session
moves on. Apply skepticism only to findings and the conclusion is "nothing
works" whatever the truth. Five handedness nulls were accepted in a row while
three positives were each attacked within minutes; the mechanism turned out
to be MIS-SPECIFIED, found only after the user pushed back twice.

**Positive-control every screen** — inject a known effect at the claimed size
and confirm the harness sees it, because a mis-specified mechanism and an
absent effect produce identical output. Before accepting a null, state the
specification and what would falsify it. A null should sometimes mean
"strengthen the mechanism", not "next candidate".

### 8. A grid-edge parameter is a missing mechanism

Four for four: it found the absent hit-by-pitch, absent fielding errors, and
out-dependent runner advancement (twice). Treat a grid-edge result as a
mechanism hypothesis immediately, not after three sweeps.

### 9. Fit a curve on the population it fires in

The removal model is two curves — BOUNDARY (does he come back out) and
MID-INNING (pull him now) — and each has its own rows. Pooling is what every
convenient tool invites: the pooled fit gave a late curve at 7.24% where
reality is 33.80%, and the same mistake was re-made THREE TIMES in one
session, twice inside the mid-inning curve's own low-pitch rows (32,497 of
47,716 sit under 60 pitches and swamp it).

BUT THE RULE HAS A LIMIT: restrict the BOUNDARY curve's training rows the
same way and the simulation gets WORSE (mean outs 16.49 -> 16.74). The
boundary curve is evaluated at EVERY pitch count and the mid-inning curve is
not, so calibrating boundary on late rows only makes it under-pull early.
Restrict only when the curve fires only there and something else covers the
rest.

### 10. Name the denominator — and the definition

No set of rate bugs moves strikeouts, walks, hits and home runs by the same
8% — that is a denominator. Three denominator mistakes in one script on
2026-08-27, each producing a confident wrong table: `Side.line` is the
STARTER'S and reliever lines are DISCARDED on each arm change, so it cannot
be compared against every first-five plate appearance.

Related and its own trap: **a MONTE CARLO MEAN carries its own noise, and
noise in a regression PREDICTOR attenuates a slope.** 55% of `m_er`'s
variance is simulation at 40 draws, which flipped the sign of a
spread-calibration result. The same noise is only ~2% of the RESIDUAL's
variance, so residual screens are unaffected.

### 12. Run investigations as labelled stages

Write QUESTION / HYPOTHESIS / TEST / EVALUATE / CONCLUSION / NEXT STEPS out
as literal headers — a missing stage is only visible when the others are
named. The full version is at the end of `NOTES-context-layer.md`. The three
that cost the most: STATE THE POWER BEFORE THE RESULT (a run chosen for speed
is a plumbing check and its number is not reportable), POSITIVE-CONTROL EVERY
SCREEN, and SEPARATE ESTABLISHED FROM INFERRED IN THE CONCLUSION.

**Prefer a high-n ratio to a low-n aggregate.** Runs per baserunner (~17,500
simulated starts) told the truth every time; the mean F5 total over a few
hundred games told me whatever the subsample felt like — four "improvements"
in a row all inside one standard error. Compare totals PAIRED and on every
game.

### 12b. One holdout is not a measurement of generalisation

The between-season spread of the baseline error is 0.040 to 0.058 — LARGER
than most effects being measured. Score across FOUR FOLDS
(`scratchpad/pxi_cv.py`, `hz_cv.py`), report all of them, and set the bar
before running. The bar, re-measured 2026-09-09 on the current engine with
live bullpens in all four folds (`pxi_cv`, boundary cell error, flag off):
0.0577 / 0.0524 / 0.0399 / 0.0451.

### 14. Hunt level errors and structural gaps first

Every win on 2026-08-27 was a LEVEL error pointing one way — hit-by-pitch,
sacrifices and wild pitches all measured on STARTERS and applied to every arm
— and the wild-pitch one closed a fifth of the run gap alone. Level errors
are worth more per day of work than refinements. Then take the refinements,
because they accumulate and nothing else is left.

## THE SYSTEM — one engine, two ways in

**THERE IS ONE ENGINE AND IT IS `game.py`.** It plays a WHOLE game: both
sides interleaved half-inning by half-inning so a live score exists, a
bullpen SAMPLED from the club's real arms, inherited runners actually played
out. `sim.py` holds the plate-appearance model (log5, base-out state machine,
the two hook curves) and does NOT drive a simulation — the one-sided driver
`sim.simulate_start` / `sim.simulate` was deleted 2026-08-25 along with the
`f5.py` stub, the input-uncertainty block (`DRAW_RATES`, `HOOK_SIGMA`) and
`INHERITED_SCORE_RATE`, all of which existed only because a loop that stopped
at the hook could not simulate the reliever finishing the inning. A full game
is ~20x the work of the old one-sided start.

Two ways in: `calibrate.replay` for a historical pair, `slate.py` for a live
date. Both end at `game.simulate_game`. `slate.py` survived the betting-layer
deletion because it was never a betting module — it turns a DATE into two
`game.Side` objects (schedule call, projected lineup, the "will we price this
arm at all" gate).

**Both starters or neither.** No opposing starter modelled means DECLINE,
never a league-average stand-in: inventing the other club invents the score,
and the score is what the hook, the bullpen and the margin are conditioned
on. `paired_cases` drops about 10% of starts for this reason. The one
mirror-the-opponent harness is `tests/fixtures.py`, and
`check_nothing_prices_through_the_fixtures` stops it reaching `src/`.

**FIT THE QUANTITY THAT SETTLES, NOT THE UPSTREAM PROXY** — the single most
useful generalisation here. What you tune against decides what you get:
`calibrate.loss()` targets the hazard curve and outs distribution, which
nobody bets, and outs is exactly where the model has never earned anything.
`fitf5` targets F5 runs allowed by one side, scored across the FULL SUPPORT
of the run distribution — which is the discrete CRPS — because scoring across
a book's liquid lines would tune the model to the shape of somebody's board.
And do not fit the hook AGAINST THE SETTLEMENT VALUE; fitting it to real
removal DECISIONS is a different thing and is what `removal.py` does.

```
src/context/
  sim.py           plate-appearance model, both hook curves, the USE_* rate
                   flags. NOT a driver
  game.py          THE ENGINE. Whole game, both sides, bullpen, extras
  slate.py         a DATE -> two game.Side objects (the live path)
  calibrate.py     replays real starts; reliability + Brier; paired_cases
  fitf5.py         fit to F5 runs, discrete CRPS over the full support
  ladder.py        score by inning prefix — where the model is wrong
  holdout.py       THE cutoff literal, imported everywhere a fit filters
  scope.py         what season a query means when nobody says
  atomic.py        atomic cache writes, so two processes cannot disagree
  store.py         context.db; morning_bets.db attaches READ-ONLY as `bets`
  advance.py       what runners actually do, counted on this league
  boundary.py      the two removal decisions, counted separately
  relief.py        how long a relief outing lasts, and when he is pulled
  inherit.py       what inherited runners do, by base and out count
  deploy.py        how bullpens are actually used
  leash.py         the per-pitcher removal offset, fitted as a residual
  order.py         the REAL batting order, counted from play-by-play
  tto.py           times through the order, measured
  stabilise.py     how fast each rate becomes trustworthy, measured
  velo.py          recent fastball velocity -> tonight's K rate
  removal.py       the LEARNED hook. OFF — see the entrypoint list
  form.py          PARKED — "he does not have it tonight", not there
  gamestate.py     has this game started
  sources/pbp.py   whole-game play-by-play, gzipped; base-out-score state
  sources/         one module per data source, all offline-cacheable
```

**Two databases.** `context.db` holds DERIVED tables (`mlb_stints`, rebuilt
from the play-by-play cache in ~30s). `morning_bets.db` attaches through a
`mode=ro` URI as the `bets` schema, so joins read `bets.games` and a stray
INSERT raises — it is not version controlled and holds boxscores that cannot
be regenerated. Use `store.connect()`, not `db.connect()`, from the context
layer.

**Why the estimator is gone.** `estimate.py` counted how many of a pitcher's
last six starts would have won a bet. Not fixable by tuning: **six starts
cannot distinguish a 50% line from a 65% one** — measured power at alpha 0.05
is 8%, rising to 9% at ten starts. The LLM-over-a-blob approach died the same
way: an estimator built the way the market is built scores AUC 0.537 against
actual results, and the market price *is* the consensus construction, so
reproducing it well buys nothing.

### Rules the code enforces (and why)

- **Never price a game in progress.** `gamestate.is_pregame()` guards every
  live fetch, and unknown state resolves to *not* pregame: a stale number
  costs little, pricing a live game writes fiction nothing downstream can
  detect.
- **The dead list records HOW a thing was tried, not that it is
  unknowable.** Six of the nine dead features were imported scalar
  multipliers scored against a model that has since changed, on half the
  data. Re-opening one is legitimate when the APPROACH changes (residual fit
  rather than import) or the DATA does (play-by-play). Pre-register it.
- **Shrink toward a prior, and keep the underlying value.** Where a group
  number stands in for an individual, both travel and one is marked as the
  lead.
- **A guessed value must not move the estimate in the wrong direction.** A
  confirmed-but-unrated catcher gets league-neutral, never another catcher's
  number.
- **IDs, not names.** `'Arizona Diamondbacks'` vs a standings row reading
  `'D-backs'` cost that club four fields. Team and venue ids travel through
  `mlb_schedule_with_probables`.
- **Neutral sites get no park factors.** A `venue_id` that misses returns
  None rather than the home club's park — MLB plays in Mexico City.

## Commands

Run everything through the Makefile's virtualenv (`venv/bin/python`).

- `make install` — create `venv/`, install `requirements.txt`.
- `make test` / `make test ARGS=sim` — the offline suite.
- `make ladder` — the prefix ladder, F1/F3/F5/F7 against real runs.
- `make fitf5` — F5 runs allowed, discrete CRPS over the full support.
- `make shape ARGS=40` — per-start outs and K distribution on the holdout.
- `make backfill` / `make pbp` — pull missing dates; cache play-by-play.

**THERE IS NO `make calibrate`, AND THAT IS A FINDING.** `calibrate.py` has
no `__main__` block and no `main()`, so the `--reliability|--tune|--patience|
--leash|--holdout` invocations older docs advertised cannot have worked as
written — its functions are called directly from tests and scratchpads.
Either give it a CLI or correct the docs; do not add a Makefile target that
fails. (`make lint` likewise references tooling that is not installed.)

### Play-by-play, and what it unlocked

- `... -m src.context.sources.pbp --backfill --sync` — WHOLE games, ~10,000
  cached, ~1 GB gzipped, **FOUR full seasons, not one** (a line here said
  2,006 for weeks and cost two turns insisting only 2026 could be replayed).
  Fetched whole and stored whole — extracting a subset to save disk is a
  false economy, the API call is identical. `cal.paired_cases(season=2024,
  rates_before=..., since=...)` returns 958 paired games in nine seconds;
  **PASS `season=` OR it infers the current one and returns nothing.**
  `plays()` reconstructs base-out-score state BEFORE every play; `stints()`
  gives one row per pitcher per game with the state he walked into.
- `... -m src.context.advance` — advancement rates COUNTED. `--by-team` runs
  the per-club stability gate (it fails; the league number stays). Found the
  published tables wrong in both directions and cancelling.
- `... -m src.context.boundary` — mid-inning and boundary removals are
  DIFFERENT DECISIONS, 63.2% / 36.8%, and pitch count does not distinguish
  them at all (83.3 against 82.6).
- `... -m src.context.relief` — relief-outing length on 13,248 outings. The
  continuation hazard is conditioned on the state he ENTERED in (20.1% /
  44.8% / 62.7% by entry outs).
- `... -m src.context.inherit` — inherited runners followed by runner ID
  across 5,507 handovers. Pooled 0.312 against a shipped flat 0.330; cells
  run 0.127 to 0.771.
- `... -m src.context.deploy` — bullpen usage. Role is stable and projects
  (split-half r +0.55 to +0.78 over 319 relievers).
- `... -m src.context.leash --build [--before DATE]` — the PER-PITCHER LEASH.
  A pitcher's leave-one-out residual is +0.295 on OUTS and noise on
  k/h/bb/er, so what is wrong is how long he is left in, not how he pitches.
  Out of sample it takes the outs correlation +0.105 -> +0.226, and it is
  FLAT on outs CRPS and the run ladder BY DESIGN — it buys discrimination
  between starts, not a better-shaped start. Club patience stays off; that is
  the sixth finding against it.
- `... -m src.context.removal` — the LEARNED hook, fitted to 86k real
  decisions. AUC 0.912 against `sim.Hook`'s 0.876 and **switched OFF since
  day seven**: it was validated on removal-decision AUC while discarding a
  fitted boundary share, and the premise in `game.USE_LEARNED_HOOK` (that one
  roll per plate appearance spans the inning boundary) is false.
- `... -m src.context.tto` — times through the order. K% falls 19% from the
  first pass to the third.
- `... -m src.context.stabilise` — the four shrinkage constants. Batter rates
  were over-shrunk 2.2x, pitcher HR under-shrunk 2.7x.
- `... -m src.context.sources.archetype` — unsupervised pitcher typing by
  pitch mix. Real for relievers (p=0.003), absent for starters, too small to
  wire in.
- `... -m src.context.sources.season --backfill` — pull missing dates to
  opening day, then the starter/pitch-count/venue backfills that depend on
  boxscores. `sources.pitches --backfill` adds REAL pitch counts, hit-by-pitch
  and wild pitches from fields the boxscore fetch was already discarding.
  `sources.starters --backfill` is ground truth for who started.
- `... -m src.context.store` — creates `context.db`, reports whether the
  pipeline DB is correctly read-only.
- `... -m src.context.gamestate [DATE]` — which games are safe to price.
  Every `sources/<name>` module has a demo main.

### Screens and harnesses

- `... -m scratchpad.battery` — THE BATTERY, rule 15.
- `... -m scratchpad.data_status` — RUN THIS BEFORE ANY MEASUREMENT. See
  below.
- `... -m scratchpad.leverage` — SCREEN A MECHANISM BEFORE BUILDING IT.
  Swings each parameter across its reliability-adjusted club spread and
  reports the runs of separation it could buy. Reliability without
  sensitivity is how park died three times.
- `... -m scratchpad.mutate` — MUTATION SWEEP. Flips one shipped constant at
  a time and reports which are unguarded. It found five: every measurement
  module was tested and none of the WIRING was. Refuses to run on a dirty
  tree.
- `... -m scratchpad.fingerprint 400 6` — one hash over 2,400 simulated
  games. A change meant to be inert must reproduce it exactly.

### The data is only as fresh as the last backfill (added 2026-09-09)

**NOTHING IS SCHEDULED.** The four `com.morningbets.*` launchd jobs were
unloaded and deleted, and `.cron-config` with them: three of the four ran
`src.main` or `src.context.snapshot`, both removed with the betting layer,
and had been exiting 1 daily into a log nobody read while every session
assumed the data was fresh. `grade` worked and was retired with them by
decision — the board runs `/backfill-data` instead.

Run `venv/bin/python -m scratchpad.data_status` before any measurement. It
reports each source's lag against the newest FINISHED GAME (not the wall
clock, so it reads correctly out of season) and the play-by-play gap. First
run found five derived tables 2-5 days stale and 37 of 111 finished September
games missing from the cache, none of which had surfaced anywhere.

**AND A FINGERPRINT COMPARISON IS ONLY VALID ACROSS CONSTANT DATA.** Measured
the same day: identical code, one backfill, and `fingerprint 400 6` moved
2fa14f8df0c6 -> 00925f199684 — not new games entering (661 paired games
before and after) but the CONTENT of existing ones, since the backfill set
venues on 26 games, lineups on 88 and pitch counts on 2, all of which feed the
replay. Never backfill between recording a fingerprint and re-measuring it;
the same caveat applies to a saved battery JSON and `--diff`.

`snapshots/` stopped at 2026-09-05 with the betting layer and no new ones are
being taken. The existing ones stay valid as the historical record, which is
the whole reason they exist: Savant serves season-to-date only and cannot be
asked what it said in June, so a backtest that rebuilds context today is not
a backtest.

`ANTHROPIC_API_KEY` in `.env` is still read by `src/grading.py`; nothing in
the simulation path needs a key.

### Test suite

`make test` runs `tests/run.py` — 485 `check_*` functions, no pytest (not
installed, not a dependency), no network. `ARGS=` filters on module name and
is the segmentation: run the module you touched during the edit loop, the
whole suite at the protocol gates.

**THE WALL CLOCK IS THE SLOWEST SINGLE CHECK OR THE TOTAL WORK OVER 8 CORES,
WHICHEVER IS LARGER.** On 2026-09-06 `check_rps_is_proper` was 29s of a 44s
suite, sampling 4000x3000 to measure a STRUCTURAL property whose margin is
19.6% at that size and 18.5% at 1000x800. Cut 15x, suite halved, mutation
still kills it. Before segmenting the suite, look at the slowest check — the
runner prints the top five every run for this reason.

Tests ship with the module, not afterwards. **Verify a new check by
mutation:** reintroduce the bug it guards and confirm that exact check fails.
A test that guards nothing looks identical to one that guards something.
`tests/test_regressions.py` is one check per bug that actually shipped.

## Where to read next

- **`RESUME.md`** — where the edge is and the long list of things already
  measured and dead, so nobody re-runs them.
- **`TODO.md`** — THE BACKLOG. Ordered, with ESTABLISHED separated from
  inferred and the falsifier pre-registered where one exists. Numbers are
  never reused; closed items compress to a line at the bottom.
- **`NOTES-context-layer.md`** — THE LOG, appended chronologically, so read
  backwards from the end. It carries the measured negatives and the
  calibration tables. Read it before changing the context layer.

Keeping the backlog inside the log is what made "what should I do next" a
twenty-minute read; that is why they are three files.
