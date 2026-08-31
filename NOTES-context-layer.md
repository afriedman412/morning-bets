# Where the context work stands — resume here

Written 2026-08-22, updated the same day after the simulator landed. This is
the debugging state, not documentation: what is half-finished, what is
measured, what is guessed, and what would waste a day if re-investigated.

---

## THE MARKET RESULTS (2026-08-24) — read this first

Everything below is how the model got here. This is what it is worth.

### Where the edge is, and is not

Measured on the CORRECTED model — leakage closed, `sim.USE_OFFSETS` off,
errors and out-dependent advancement in, the F5 stub retired:

| target | contracts | bullpen share | direction | blend | cents | verdict |
|---|---|---|---|---|---|---|
| K props | 12,181 | ~0% | 73.2% | +32.9% | +3.7c | EDGE |
| **F5 totals** | **2,676** | **~10%** | **59.6%** | **+23.4%** | **+3.4c** | **EDGE** |
| team totals | 4,943 | ~40% | 50.7% | +9.4% | +1.4c | nothing |
| game totals | 4,222 | ~40% | 52.0% | +4.1% | +1.2c | nothing |
| outs | — | ~0% | — | +3.8% | — | nothing |
| NRFI | — | ~0% | — | — | — | nothing (-2.9% skill) |

**THE EDGE TRACKS BULLPEN SHARE, NOT "STARTER-DRIVEN".** I predicted team
totals would carry the F5 edge because one team's runs are what the OPPOSING
STARTER allows — the exact quantity this simulator is built around, on twice
the contracts. It does not: 50.7% direction on 2,185 disagreements is a coin
flip. The prediction was wrong and the refutation is the useful part.

What separates the two is not whether a starter drives it but HOW MUCH
BULLPEN is in the settlement. A team total is ~40% relief; first five is
~10%, because the starter covers all five innings 73% of the time. Outs and
NRFI have no bullpen at all and no edge either, so it is not a monotone rule
— the requirement is a starter-dominated settlement AND enough plate
appearances for skill to separate from variance. F5 is the only quantity
measured that has both.

**The F5 edge SURVIVED a substantially rebuilt model.** CLV z went 30.2 ->
38.7, corr 0.452 -> 0.485. An edge that survives fielding errors,
out-dependent advancement, a refitted PITCH_COST, a real bullpen, the
retired stub AND the removal of leaked offsets is not a parameterisation
artifact. That is much stronger evidence than the original measurement.

Two things moved the other way and are not spin: we now LOSE to the open on
outcome Brier (0.1980 against 0.1966, ~0.1970 after correcting for sim
noise), and direction fell 65.1% -> 59.6%. Since every earlier F5 CLV number
had hook/patience/leash fitted on the scored dates, "the edge is smaller than
we thought" and "the old number was inflated" are the same statement.

### EVERY EDGE IS A STARTER EFFECT. That is the organising fact.

K props and F5 both hinge on one starter with ~600 batters faced against a
specific nine. Game totals, outs and NRFI do not, and none of them carry
anything. This decides several open questions at once:

* **Do NOT model reliever deployment.** It is a back-half mechanism and the
  back half is exactly where there is no edge. Real defect (only 52.6% of
  relief outings are one clean inning; mean 3.51 outs, not 3.00) improving a
  number nobody pays for.
* **Do NOT chase home run props** despite 29,128 contracts, the largest
  market. A home run is a BATTER outcome and the batter side carries one
  `hr_pct` with no batted-ball data. A ~12% base rate also needs far more
  contracts to resolve an edge than a ~55% one.
* **NRFI is dead and was cheap to kill.** P(NRFI) calibrates almost exactly
  (0.522 against 0.510) and carries NO information: Brier skill -2.9%. Three
  or four batters is all signal-free variance. The averaging that kills
  handedness across nine hitters is what CREATES the signal — remove it and
  nothing is left. Same shape as outs: perfectly calibrated, zero edge.

### KALSHI IS THE MARKET, at least on game totals

Spot-checked against DraftKings via ESPN on 2026-08-24. On correctly matched
HALF-POINT lines the two agree within ~1 cent (+0.1, +0.6, +1.0, +1.4).

**And a trap worth recording.** Integer lines looked wildly off (-4 to -7
cents) and that was entirely a matching bug of mine: DraftKings' 7.0 can
PUSH, so over-7.0 needs a total of 8, while Kalshi's threshold-7 contract is
over-6.5 and wins at exactly 7. Different bets. Check `quote.py` for the
same integer/half-point confusion — that would be a live bug on real quotes.

So DK and Kalshi are not independent opinions on game totals; they are the
same consensus, and arbitrating between them finds nothing. PROPS may
differ — the Ashcraft strikeout quote showed a 4.5-cent book-vs-Kalshi gap
against ~1 cent on game totals.

### Measurement hygiene learned the hard way today

* **n_sims=250 in the CLV runs gives ~3.2 cents of Monte Carlo error per
  contract, against a median disagreement of 3.7 cents.** That does not
  invalidate anything — it ATTENUATES. Noise adds ~0.001 to Brier and
  dilutes direction accuracy, so 59.6% is a floor rather than a ceiling.
  Re-run at higher sims before quoting these as final.
* **Trade histories now cache to disk** (154x on a warm run). A settled
  market's trades are immutable; only past-dated markets are cached, or a
  still-trading path would defeat the before-first-pitch cutoff.
* Kalshi publishes a LADDER — 7 lines per team-game, 12.2 per game total —
  so it implies a whole DISTRIBUTION. We score one rung at a time and throw
  the shape away. Unexplored.

---

## DAY THREE (2026-08-24) — the model work behind those numbers

**The database was half a season and that was the binding constraint.** It
started 2026-05-28; backfilled to opening day it holds 2,006 final games
(was 1,101), 16,656 pitching rows (was 8,823), and F5 scores went 512 ->
2,009 once it emerged that `cache_mlb_f5` had never run for months already
cached — June had none at all. Almost every inconclusive result from day two
was underpowered rather than negative. `sources/season.py` does the pull.

### The simulator is now materially more correct

Four mechanism fixes, none of them fitted against the objective they are
scored on:

| | |
|---|---|
| runs per baserunner | **-4.2% -> -0.2%** |
| PITCH_COST | fitted on 3,880 real starts, was invented |
| WP_PB_RATE | 0.028 -> 0.0155 — it was **1.8x too high** |
| HBP_RATE | 0.011 -> 0.0098, counted not published |
| advancement | now keyed BY OUT COUNT |
| F5 total (paired, 1,098 games) | **-0.130 +/- 0.095, 1.4 sigma light** |

**Pitch counts were in the boxscore all along.** `grading.mlb_boxscore`
downloads the full statsapi pitching blob and kept eight fields;
`numberOfPitches`, `strikes`, `hitByPitch` and `wildPitches` went on the
floor. `sources/pitches.py` backfills them. No new source, no play-by-play.

**WP_PB_RATE was a published rate on the wrong denominator** — the same class
of error that cost 6-8% on walks. Real wild pitches are 0.0057 per batter
faced; passed balls add ~20% and never appear in pitching stats at all,
being charged to the catcher.

### THE DIAGNOSTIC THAT DID ALL THE WORK — now four for four

**A parameter pinned at its grid ceiling is a MISSING MECHANISM, not a
tuning problem.** It found the absent hit-by-pitch, the absent fielding
errors, out-dependence on the three hit constants, and then out-dependence
on the fourth. Every time the fit was right and I was slow to read it. Treat
a grid-edge result as a mechanism hypothesis on FIRST sight.

The last one is the clearest. A flat advancement rate applies the same
number with nobody out and with two, and those are not the same play — with
two down the runner leaves on contact. Raising the flat rate cannot fix it,
because buying the two-out case over-converts the nobody-out case. That is
exactly why the search kept straining instead of settling.

### THREE OF MY OWN CLAIMS DIED TODAY

Recorded because the corrections are more useful than the claims were.

1. **"F5 totals 3% light to exact" was noise.** Every difference I quoted
   across four changes (-0.14, +0.04, -0.08, +0.10) sits inside one standard
   error — see the section below. Prefer a HIGH-N RATIO (runs per
   baserunner, ~17,500 starts) to a LOW-N AGGREGATE (a mean over a few
   hundred games) whenever both exist.
2. **"Arsenal typing is too small to use" was wrong for relievers.** R2 with
   four free parameters is upward-biased; the question was never "is 5%
   small" but "is it bigger than what this procedure invents from nothing".
   A permutation null separates relievers (p=0.003 at every sample bar) from
   starters (p=0.17-0.56). Disattenuating for sampling noise looked like the
   right correction and was NOT sufficient — corrected values still climbed
   with the sample bar, which is small-n bias. The permutation settled it.
3. **The recency hypothesis died at 3-5 sigma.** See below.

### ARSENAL IS DEAD, THREE CONSTRUCTIONS DEEP

Two PRE-REGISTERED tests on 2026-08-24, held-out window, rules fixed before
either was run (`PREREG-arsenal.md`, `PREREG-arsenal-contact.md`):

    channel                    primary CRPS      verdict
    strikeouts (mixture)     +0.00210 (+0.6 sd)  do not ship
    contact quality          +0.00239 (+0.7 sd)  do not ship

Both the wrong way, nearly identically. Earlier, the scalar-multiplier
version measured 9.79% against 9.79%. Three constructions, one dataset, no
signal.

**And no subset rescues it.** Asked whether any slice improved, the
strikeout mixture was scored on the TRAINING window by quartile of how much
it moved each lineup: -0.2 sigma in all four buckets, INCLUDING the top one
where it shifts K rates 7.5-16%. Where the mixture says the most, it still
says nothing. That is a cleaner negative than the headline test.

**Pre-registration earned its place here.** The first arsenal attempt left a
tempting sub-threshold hint ("every high-K line improved"), and choosing
those lines after the fact is how a null becomes a finding. Fixing the
endpoint and the 2-sigma bar in advance meant there was nothing to
renegotiate.

### RECENCY IS DEAD — seven for seven on imported baseball knowledge

The Ashcraft quote made a sharp case: season rates said 0.542 on his over-5.5
strikeouts against Kalshi's 0.405, and a 14-day half-life closed the gap to
0.4 cents. Over 510 settled markets, paired against season-flat:

    21-day half-life   closeness to close +0.0081 (+3.8 sd)
                       Brier vs outcome   +0.0066 (+3.0 sd)
    14-day half-life   closeness to close +0.0135 (+5.4 sd)
                       Brier vs outcome   +0.0079 (+3.0 sd)

FURTHER from the market and WORSE against outcomes, both half-lives, same
sign. A single case chosen after looking is usually a coincidence. The
founding observation explains the direction: a season-to-date rate IS the
consensus construction, so shading away from it loses on both endpoints at
once. `src/context/recency.py` holds the measurement.

### Leakage closed: the LEAGUE BASELINE is training data

`sim.league()` computed baselines over every cached game including the test
window. log5 returns the league value whenever both sides are average, so it
anchors every simulated rate. The obvious knob (player rates) was already
correct, which is what made it quiet. `before=` now reaches
`_starter_league` — the path that actually sets the baselines — and the
cache is keyed on `(season, before)`, because keyed on season alone the
FIRST caller fixed the baselines for the whole process.

### Where it stands / what is queued

Model believed settled. **Nothing has been measured against a market since
the fixes.** In order: F5 parameter refit (3 parameters left; the four
advancement constants are published out-state tables and out of the search),
then the PRE-REGISTERED arsenal mixture (`PREREG-arsenal.md`, 2-sigma bar,
`sources/mixture.py` built and tested but NOT yet wired into `pa_outcome`),
then totals-vs-Kalshi — which has still never completed a run.

numpy and scikit-learn are now dependencies.

---

## MEASURE F5 TOTALS PAIRED, ON EVERY GAME (correction, 2026-08-24)

A mistake I made repeatedly on 08-24 and should not be repeated. I quoted F5
total differences of -0.14, +0.04, -0.08 and +0.10 across four model changes
as if they were signal. **Every one sits inside one standard error.** Game
totals have sd 3.28, so a 350-game mean carries se 0.175 and I was reading
noise as progress — including in a commit message claiming "3% light to
exact".

Two fixes, both cheap:

  * **Use every game, and PAIR the comparison.** Simulated and actual totals
    for the same game share all the game-to-game variance, so the paired
    standard error over 1,098 games is 0.095 against the 0.175 I was
    quoting. That is the difference between measuring and guessing.
  * **Do not subsample by dict order.** The first 350 games had a real mean
    F5 total of 4.71 against 4.958 over all 1,098 — the slice was not
    representative, so even the sign was unreliable.

Properly measured, the model sits at **-0.130 +/- 0.095 on F5 totals, 1.4
sigma light.** Within noise of correct.

**The trustworthy diagnostic is RUNS PER BASERUNNER**, not the total. It is a
ratio over ~17,500 simulated starts, so its error bar is tiny, and it moved
monotonically with each mechanism fix: -4.2% flat, -2.6% with hits made
out-dependent, -3.6% with an indexing bug, -0.2% once corrected. Prefer a
high-n ratio over a low-n aggregate whenever both are available.

**A leakage path found while doing this.** `sim.league()` computes baselines
over ALL cached games, including the test window. Train-window starters walk
0.0823 per batter faced against the full-season 0.0812, so a "train-only" fit
is anchored to numbers that have seen the test data. Small, and real.

---

## WHAT THIS PROJECT IS MODELLING (settled 2026-08-23 — read this first)

**We are modelling F5 TEAM TOTALS, and to a lesser extent full team totals.
That is the product. Props are not the target — they are expected to fall
out of a game simulation that is actually right.**

This is a change of goal, not a change of technique, and it retires a lot of
what is written below. The old framing was "price the bets we can measure",
which produced an objective aimed at the hazard curve and the outs
distribution, 221 fitted parameters, and no edge on the thing being fitted.
The new framing is: **simulate the game correctly and let everything
downstream follow.**

Three consequences, each of which changed real code:

1. **Do not fit the hook.** It is a manager decision the model only ever
   reproduced in aggregate, and it is not what makes a simulated game right.
   Measured on the F5 objective, every hook term is flat inside its own
   error bar — across its ENTIRE grid `intercept` moved the loss 0.0034
   against a paired standard error of 0.0017, `per_run` 0.0050 against
   0.0036, `pitch_center` 0.0059 against 0.0055. That is the expected
   result: the starter is still in through the fifth about three-quarters of
   the time, so the removal rule usually never fires inside the window being
   scored. `fitf5.HOOK_KEYS` exists and is OFF; `--with-hook` puts it back.

2. **Do not fit to a book's lines.** Scoring across the lines a book happens
   to offer is "how well do we hit props" wearing a scoring rule's clothes,
   and it tunes the model to the shape of somebody's board. Scored across
   the FULL SUPPORT of the run distribution, the same arithmetic is the
   discrete CRPS — a measure of how far the simulated distribution sits from
   what happened. `fitf5.SIDE_LINES` is the support, 0.5 through 8.5, and it
   is deliberately not a line menu.

3. **The headline diagnostic is the SHAPE of the run distribution**, not the
   score. Mean, spread, shutout rate, crooked-number rate. A model can hold
   a good score while producing the right average out of the wrong shape,
   and only the tails show it. This was immediately vindicated: the first
   run of the fit improved nothing and the shape columns found four real
   defects. **Run `--score` and read the table; do not read the CRPS.**

### THE FIRST FIT RAN AND FOUND NOTHING. Ship nothing. (2026-08-23)

588 training sides before 2026-08-09, 321 unseen after. Two sweeps over the
seven run-production constants.

**Three constants moved and all three are noise.** The paired difference on
unseen sides is **-0.00174 +/- 0.00420, i.e. -0.4 sigma**. Worse: rescored
at 200 sims, the fitted set was WORSE THAN SHIPPED ON THE TRAINING DATA
ITSELF (1.5456 against 1.5324). The fit's claimed gain was 0.0020 and
measuring it more precisely reversed it by 0.0132.

**So the 1-sigma acceptance bar did NOT do its job, and the holdout did.**
That is the reusable lesson: on a Monte Carlo objective, an in-search
significance bar is not a substitute for out-of-sample scoring, because the
bar is computed from the same noisy draws that produced the candidate.

**Four of seven constants were CONFIRMED at their published references** by
an objective that never saw them — `SECOND_SCORES_ON_1B` 0.60 with a clean
minimum rising in both directions, `RUNNER_ADVANCES_ON_OUT` 0.25,
`WP_PB_RATE` 0.028, `GIDP_RATE` 0.11, each beating its neighbours by ~0.007
against a ~0.0014 error bar. The base-running model is not fudged. That is
the most valuable thing this run produced.

### WHAT IS ACTUALLY WRONG — the shape, not the constants

Consistent across both windows, from the `--score` diagnostic:

| | model | actual |
|---|---|---|
| runs per side | 2.30 | 2.50 |
| shutouts | 23.1% | 19.3% |
| sides allowing 5+ | 15.1% | 17.4% |
| **starter covered five innings** | **71.1%** | **76.0%** |

The run distribution is COMPRESSED — too many shutouts AND too few crooked
numbers — which is a different defect from being uniformly light, and only
the tails show it. Part of the level gap is period drift (the training
window really did score 2.33 a side against the test window's 2.50); the
shape gaps are not.

**A CORRECTION WORTH KEEPING.** Seeing every hook curve come back flat, I
recorded that the hook does not matter for F5. That was the wrong
conclusion. The model pulls the starter before the fifth 29% of the time
against a real 24% — a five-point error in exactly the mechanism the hook
controls — and the CRPS objective cannot see it. **Flat curves meant the
objective is blind to it, not that the model is right.** A parameter the
objective cannot resolve is not thereby unimportant; it is unconstrained,
which is more dangerous. Do not read the flat hook scans as a licence to
ignore the hook.

### THE WHOLE GAME NOW EXISTS (`src/context/game.py`) — and it found the cause

Until 2026-08-23 nothing simulated past the starter's exit. `simulate_start`
models ONE PITCHER and returns when the hook fires, so **a full team total
could not be produced at all.** There were pitcher props, first-five via a
stub, and no game. That is now built.

**Both sides run in tandem, not jointly.** Away pitching faces the home
nine, home pitching faces the away nine, and given the lineups those are
independent — there is nothing to co-model. The only reason to interleave is
ORDERING, so a live score exists when a manager decides in the bottom of the
fifth. `Hook.per_margin` and `mid_per_margin` can finally see it. **Both
default to ZERO**, so nothing changed until it is measured — and the sign is
genuinely not obvious in advance (a big lead both buys a starter rope and
gets him lifted).

**The bullpen is SAMPLED.** 374 relief arms spanning K% 0.165-0.304, sd
0.037, were being collapsed into one average reliever. Drawn without
replacement weighted by appearances — uniform sampling hands every club a
pen made mostly of its worst pitchers, since there are more of them.

**Inherited runners are no longer a fudge.** `f5._side_runs` settles a
departing starter's men at a flat 0.33 because it never simulates the
reliever finishing the inning. The full game hands over the base-out state
intact.

#### THE COMPRESSED RUN DISTRIBUTION WAS THE BULLPEN, AND THE LEVEL GAP IS ERRORS

Measured over 142 games on the unseen window:

| | sim | actual |
|---|---|---|
| game total | 8.09 | 8.67 |
| sd | 4.10 | 4.32 |
| **sd / mean** | **0.507** | **0.498** |
| starter outs | 16.09 | 16.07 |

With a real bullpen the RELATIVE dispersion matches. The compression is
gone; a league-average arm every night was causing it. What remains is a
pure LEVEL gap of 6.7%.

**That gap is unearned runs, and the arithmetic is not close to ambiguous.**
League unearned share is 7.64% of all runs. The simulator models no errors,
so it cannot produce them. 8.09 / (1 - 0.0764) = 8.76 against an actual
8.67.

This also explains the fit's behaviour: it kept shoving
`FIRST_TO_THIRD_ON_1B` to the EDGE of its grid because that was the only
channel it had for manufacturing the missing 7.6%. **Third time the
"no parameter can reach the target, so the mechanism is missing" diagnostic
has paid out here**, after the absent hit-by-pitch.

#### FIXED, and it closes the level gap (`ROE_PER_OUT = 0.018`)

A reached-on-error is a would-be OUT that becomes a baserunner: no hit, no
out, batter on first. That is what it IS, and it is why an error costs twice
— the runner it gives and the out it does not.

| | sim | actual |
|---|---|---|
| game total | 8.71 | 8.67 |
| sd | 4.33 | 4.32 |
| unearned share | 6.6% | 7.6% |

Calibrated against the LOCAL unearned share, not a published constant,
because this database has the number.

**Two costs, both real.** `StartResult.earned` is an approximation: every
run after an error in an inning is charged unearned, where official scoring
reconstructs the inning as it would have gone. It OVER-counts, so the `er`
diagnostic now carries a known bias and `runs` is the trustworthy figure —
which is fine, because a team total settles on total runs.

And the extra baserunners trip the hook sooner: early exits went from 28.8%
to **31.2% against a real 25.6%**. Adding errors made the removal timing
WORSE. That is the next job, and it is now the largest remaining defect.

Half-inning state lives in `sim.Frame` so the error flag travels with the
bases and outs. That refactor immediately caught a live bug: `_leave`
credited inherited runners straight to `r.runs`, bypassing the earned split.

### What is built (`src/context/fitf5.py`, 22 checks)

Fits on **SIDES**, not game totals. `games` stores `away_score_f5` and
`home_score_f5` separately: 512 games but **909 side observations with a
modelled rotation starter**. A side ties to ONE starter; a game total
confounds two. Runs allowed by a side = the OPPONENT'S F5 score, read off
the `is_home` flag rather than by matching abbreviations.

**Scored against TOTAL runs, not earned.** Everywhere else here the sim is
graded on earned runs, because it simulates no errors and charging it for
defence it never simulated read as a 12% deficit that was not there. That is
right for a diagnostic and WRONG here — an F5 total settles on runs that
crossed the plate. Expect fitted constants to sit a little hot against
published references; that is the ~8% unearned share being absorbed, and it
belongs in there.

**What the fit moves: seven run-production constants**, all rules about how
a runner gets home — the four advancement rates, `INHERITED_SCORE_RATE`,
`WP_PB_RATE`, `GIDP_RATE`. **The 176 pitcher leashes and 30 club patience
offsets are not applied** (`side_cases(offsets=False)`); `--offsets`
measures what that costs rather than asserting it is free.

### Two methodological traps this hit, both worth remembering

**A Monte Carlo score is biased upward by its own sampling variance.** An
RPS computed off `n` draws carries p(1-p)/n, and squaring puts it straight
into the score: the SAME parameters scored 1.434 / 1.411 / 1.380 at 20 / 40
/ 80 sims. That is not a model improving. `_rps` subtracts the plug-in
estimate, which also makes the number comparable to a Brier somebody else
computed. It cannot go negative — at p = k/n the squared error is
(n-k)²/n² and the correction k(n-k)/(n²(n-1)), and they cross exactly at
k = n-1 — so a clamp would only ever fire on a bug.

**Comparing two candidates needs a PAIRED error bar.** Both are scored over
the same sides with the same seeds, so their losses move together. The
unpaired sd is 0.0165 where the paired difference's is 0.0078: combining
separate standard errors inflates the bar 2.6x, and the search then rejects
every real move and reports that no parameter matters. This nearly happened.

**The acceptance bar is one standard error and is NOT a significance test.**
At six salts the standard error is itself estimated from six numbers, and a
one-sided 1σ bar admits ~16% of noise moves regardless. It guards against
wild moves; the out-of-sample window adjudicates.

### Known costs, accepted deliberately

* **Dropping the leashes loses something real.** Andrew Painter and Emmet
  Sheehan came out as short-leash arms because they are genuinely on innings
  limits, which no rate model can know. The plan is a small explicit OUTLIER
  list, not 176 fitted values to catch a handful of cases.
* **The fit only ever simulates five innings**, so nothing in it constrains
  hook behaviour in the sixth through ninth. Free for F5, NOT free for
  strikeout props, which are priced off a nine-inning simulation and carry
  the only robust CLV edge here (z +43.5). Measure outs and K as printed
  diagnostics before writing any fitted constant into `sim.py`.

### The existing F5 CLV number is not a clean comparator — twice over

z +31.4 was measured with **rates frozen per date but hook, patience and
leash fitted on the full season including those dates** (`versus_market` has
a `refit=True` path for exactly this; the F5 run did not use one). And
`f5_market.py` **never applies the home/road lineup adjustment**, which the
fit does. Optimistic by an unknown amount, in two independent ways.

---

## READ THIS FIRST (2026-08-23, end of day two)

Three findings, in descending order of how much they should change what you
do next. Everything below this section is older and partly superseded.

### 1. FIRST FIVE INNINGS carries a real CLV edge — against the OPEN

On 2,149 settled Kalshi F5-total contracts across 41 dates:

| | Brier | vs base rate |
|---|---|---|
| Kalshi close | 0.1927 | +21.4% |
| **our F5 sim** | **0.1947** | **+20.5%** |
| Kalshi open | 0.1977 | +19.3% |

We beat the OPEN and lose to the CLOSE — the same shape as strikeouts.

CLV: corr +0.463 against a shuffled control of −0.017, **z +31.4**, blend
+21.8% at lambda 0.5, and on the 760 contracts where we disagree with the
open by 5+ cents we call direction **67.1%** and the line moves **+3.9
cents** our way. That last number is better than K's +3.7.

**A CORRECTION WORTH KEEPING.** An earlier 8-date sample (455 contracts) had
us BEATING the settled close, 0.1890 against 0.1919, and this file recorded
it as the first time anything here had done that. **It was noise and it did
not survive.** At 2,149 contracts the market is ahead again. The caveat
attached at the time — "a 1.2-point skill edge is exactly the sort of thing
that evaporates" — was correct, and the lesson is that an outcome-Brier
comparison at n≈450 on a 60% base rate cannot separate a real edge from
nothing.

The reverse also happened: 5-cent direction accuracy read 55.6% at 8 dates
and 67.1% at 41. Both the flattering number and the discouraging one were
noise. **Do not draw conclusions from a single week of this market.**

### 2. The K edge is real, robust, and only against the OPEN

Measured twice, before and after a substantial model overhaul, and it did
not move: corr +0.586, z +43.5 against a shuffled −0.270, blend +32.9%,
direction 73.2%, +3.7 cents on 5-cent disagreements. Against the CLOSE it is
exactly zero (blend weight 0.00, t = −0.15).

An edge that survives changing the walk baseline 8%, adding two mechanisms,
and refitting the hook and all 176 leashes is not a parameterisation
artifact. But realising it means betting near the open, where books are
thinnest — execution is the binding constraint, not modelling.

### 3. Fit the settlement value, not the upstream proxy

`calibrate.loss()` targets the hazard curve, boundary share and outs
distribution — quantities chosen because they were measurable, not because
anyone bets them. That is why the outs machinery calibrated beautifully and
produced no edge, and it is the best available explanation for why F5, which
IS the settled quantity, does better.

**Nothing in the fitted objective currently knows what a settled bet looks
like.** Adding an F5 term to `loss()` is the obvious next move if the full
history holds up.

---

## THE EARLIER HEADLINE (superseded by the above): we lose to the close, we beat the open

Corrects the conclusion recorded below it. Both are true and they are not
in conflict.

**Against Kalshi's CLOSING price the simulator adds nothing.** Blend weight
0.00, corr with the market residual −0.0044, t = −0.15 over 1,220 settled
markets. The close already contains what we know.

**Against Kalshi's OPENING price it adds a lot.** That comparison is the
fair one — our number is built from morning information, and the close
carries confirmed lineups, weather and scratches that we never modelled.
Comparing our morning estimate to their close was a rigged test and it was
mine.

| predictor | MSE vs the closing price |
|---|---|
| the open alone | 0.00243 |
| our sim alone | 0.00448 |
| **open + 0.25 × (sim − open)** | **0.00165** |

Blending our number into the open predicts the close **32% better than the
open by itself**. Direction of the move called right 72.5% overall, and
73.3% on the 634 markets where we disagree with the open by 5+ cents, where
the line then moves our way by **+3.7 cents** on average. Kalshi costs ~1
cent to cross and 47 of 60 contracts sampled were two-sided inside 2 cents,
so this is tradeable rather than theoretical.

**THE ARTIFACT CHECK MATTERS AND CUT THE OTHER WAY.** `sim − open` and
`close − open` share a `−open` term, which can manufacture correlation.
Controls: shuffling our values across markets gives −0.2675, a constant
model gives −0.4004. The artifact is NEGATIVE, so it was suppressing the
signal. Real sits +43 sd above the shuffled distribution. Do not drop these
controls if this is re-run.

**SIZE IT HONESTLY BEFORE ACTING.** Kalshi's close beats its own open by
only 1.3 points of Brier skill (37.6% vs 36.3%), and blending us into the
open recovers +0.67 of that — about half the information the market itself
adds during the day. So the 3.7 cents of line movement is real and the
outcome-measured edge behind it is under a point of Brier. This is CLV, not
demonstrated profit. λ=0.25 was chosen on this same data, 8 dates, K only.

**What this changes.** "The simulator is a footnote" was wrong. It is a
footnote AT THE CLOSE, which is the single moment it has nothing left to
say. Its value is being early, and the way to realise that is to bet at or
near the open — which is also where the books are thinnest, so execution is
now the binding question rather than modelling.

Open follow-ups: does it hold on outs as well as K; does it hold on dates
outside 2026-08-14..21; can you actually get filled near the open.

---

## The day-two recalibration (all of this is now in the model)

The rate model was wrong in four ways and all four are fixed. Recorded
because each was found by a different route and two of them I had
explicitly cleared earlier.

**The league baseline was the wrong population.** log5 returns the league
value when batter and pitcher are both average, so the baseline is the
simulator's floor — and it was the whole pitcher pool on the BATTING
denominator (BB 0.0886) while the simulator only ever simulates rotation
starters (BB 0.0784). Every start was pulled toward a walkier population.
Baselines now come from `sim._starter_league`; the BATTER rates are scaled
onto that footing via `batter_scale`. Scaling the pitchers instead was tried
first and made walks WORSE (6.3% → 8.5%): their denominator was never the
problem, the reference was.

**Successful steals were missing** while caught stealing was not. For half a
day the model took every downside of baserunning and none of the upside —
1,301 steals in the data against ~346 caught.

**Hit by pitch was missing entirely.** ~1.1% of plate appearances. Its
absence made the run target UNREACHABLE rather than merely missed: runs per
hit-or-walk is measured in a world that also has hit batsmen putting men on,
and their runs land in the real numerator and never in ours. The giveaway
was that no plausible advancement rate closed the gap.

**Sacrifices and HBP are drawn off the top**, so everything after is
conditional on neither firing and needs rescaling by 1/(1 − SAC − HBP).
Without it every marginal rate came out light by exactly that much — K/9
8.16 against a real 8.44, on the one stat where the edge lives.

Advancement was then refitted, IN THAT ORDER, once hits, walks and batters
faced each landed inside 2%. Fitting it earlier buries the baserunner error
inside the run total, which the first attempt did.

Result — every per-start rate inside 2%:

    outs 16.08 vs 16.07    K 4.97 vs 5.03    walks 1.76 vs 1.73
    hits 4.86 vs 4.95      earned runs 2.33 vs 2.38    K/9 8.35 vs 8.44

**Two diagnostics worth reusing.** When no plausible parameter value reaches
the target, the mechanism is missing rather than mistuned. And when a fitted
constant lands far from its published reference, it is absorbing something —
the advancement rates sit ~30% high and are standing in for wild pitches,
passed balls and advancement on errors.

**One regression, not chased:** the outs distribution widened with the
softer pitch curve (SD 4.11 against a real 3.81, P(under 15) 29.3% vs
25.7%). `loss()` does not weight spread, so the tuner traded it away. It
matters little for K and would matter for an outs bet.

---

## PICK UP HERE (paused 2026-08-23, ~1am)

**The open question, and it is the only one that matters now.**
`versus_market.py` compares the simulator to real Kalshi prices on 1,220
settled markets with outcomes. Headline, already measured:

| | Brier | vs base | AUC |
|---|---|---|---|
| market | 0.1547 | +37.6% | 0.854 |
| sim | 0.1599 | +35.5% | 0.844 |

The simulator lands just short of a real market. That is a respectable
result and NOT the question. The question is whether our disagreement adds
anything to a price that already exists, tested by blending: score
`market + lam * gap` and sweep lam. **If the best lam is 0, the sim is
decoration.** That run was started and had not printed when work stopped —
re-run `venv/bin/python -m src.context.versus_market`.

Do NOT use the `(gap > 0) == won` band table for this. It is confounded and
labelled as such in the code: the sim runs systematically high, so its big
gaps land on longshots, which lose, and the metric collapses for reasons
that have nothing to do with information.

**What landed just before the pause.** Sacrifices and caught stealing are
now simulated (`SAC_RATE = 0.010` from published league shares, `CS_RATE =
0.0148` derived locally from 1,301 steals over 23,338 times on base at a
~79% success rate). Outs per batter moved 0.7017 → 0.7052 against a real
0.7094, closing about half the measured gap. The hook was REFIT afterwards
because the fix removes the baserunners its mid-inning terms key on — loss
0.0858 → 0.0720, `mid_intercept` −5.5 → −5.0, `mid_per_runner` 0.90 → 0.55.

Calibration shape is now close to exact:

| | actual | sim |
|---|---|---|
| ends on inning boundary | 66.7% | 66.9% |
| outs SD | 3.79 | 3.80 |
| strikeouts | 5.04 | 5.02 |
| outs | 16.11 | 16.24 |
| earned runs/9 | 4.00 | 3.77 |

**Two errors were cancelling and one is now exposed.** Run scoring is 5.8%
light. It was hidden while the sim produced ~5% too many baserunners; with
the phantom runners gone, the base-running advancement rates are visibly too
conservative. That is the next thing to look at, and it matters because runs
drive the hook. Hits are still +3.4% and walks +6%.

Also fixed on the way: the calibration report compared simulated runs to
TOTAL runs. The sim models no errors, so every run it produces is earned;
scoring against total runs read as a 12% deficit that was not there.

---

## THE SITUATION IN ONE PARAGRAPH

`scan.py`'s flag rule is still broken, but **the diagnosis changed and the
fix is no longer a better threshold.** Six starts cannot distinguish a 50%
line from a 65% one — measured power at alpha 0.05 is 8%, rising only to 9%
at ten starts. No threshold repairs that, because the information is not in
the sample. The answer was a better estimate, and that is what `sim.py` now
is. Wiring the simulator into the scanner is the outstanding work.

---

## Why the threshold rule cannot be fixed in place

`scan.py` flags when `our_p - market_p >= MIN_DISAGREEMENT` (0.08). Because
the prior IS the market price, that reduces exactly to *the surplus of
winning starts over what the market predicts, divided by (n + 4)* — a
binomial residual test with a constant bar on a quantity whose noise scale
moves with both `p` and `n`.

False-flag rate when the market is exactly right (pure noise):

| market p | n=6 | n=10 | n=20 |
|---|---|---|---|
| 0.065 | 5% | 13% | 4% |
| 0.20 | 10% | 12% | 20% |
| **0.50** | **34%** | **17%** | **25%** |
| 0.65 | 32% | 26% | 25% |

Three things to take from it:

1. **More data barely helps.** The required excess grows linearly in n while
   binomial noise grows as sqrt(n), so the bar improves at sqrt(n) from a
   terrible start: 0.65 standard deviations at six starts, 0.71 at ten. You
   would need ~100 starts to reach a respectable 1.7.
2. **The tails are the SAFEST region, not the worst.** Noise peaks at
   p=0.5. I claimed the opposite mid-session and was wrong; don't
   reintroduce a "skip tail lines" restriction on that basis.
3. **An exact tail test would be correctly calibrated and nearly silent.**
   Its false-flag rate is alpha by construction at every price and n — but
   its POWER at n=6 is 8% against a 50-vs-65 mispricing. Correct, and
   useless. This is why the effort went into the simulator instead.

If a threshold rule is ever wanted anyway, use the exact binomial tail, not
a standard-error z-score: at n=6 and tail prices the normal approximation is
worst exactly where the scan fires most.

---

## The simulator (`sim.py`) — built and measured

Replaces "count his last six starts" with a plate-appearance simulation:
log5 matchup rates against the specific nine he faces, a base-out state
machine, and a fitted hook. No network, no API key, ~15k simulated starts a
second.

**Measured calibration, K props, 1,776 rotation starts** (in-sample on
rates; see leakage note):

| line | base | model | bias | Brier vs base rate |
|---|---|---|---|---|
| k 3.5 | 70.2% | 70.9% | +0.7% | +14.5% |
| k 4.5 | 54.1% | 54.7% | +0.6% | +16.8% |
| k 5.5 | 37.3% | 38.6% | +1.3% | +19.0% |
| k 6.5 | 24.6% | 25.2% | +0.5% | +18.9% |
| k 7.5 | 14.8% | 15.3% | +0.5% | +17.3% |
| k 8.5 | 9.9% | 8.3% | −1.6% | +13.6% |

**Outs is the weak half, and the split is diagnostic:**

| line | base | model | bias | Brier vs base rate |
|---|---|---|---|---|
| outs 11.5 | 90.3% | 88.7% | −1.5% | +1.2% |
| outs 14.5 | 74.6% | 70.3% | −4.3% | +2.9% |
| outs 15.5 | 54.2% | 50.5% | −3.8% | +4.4% |
| outs 17.5 | 41.4% | 41.7% | +0.4% | +5.2% |
| outs 18.5 | 17.5% | 20.1% | +2.6% | +4.2% |
| outs 20.5 | 12.4% | 12.8% | +0.4% | +3.9% |

K runs +13.6% to +19.0%; outs runs +1.2% to +5.2%. **K is driven by rate,
which the sim models well. Outs are driven by the hook, which is fitted only
to marginals** because the local cache has no game state at removal. This is
the measurement that says play-by-play would buy something — and says it
would buy it for OUTS specifically, not for K.

Worst single cell: outs 15.5, top bucket, said 60.0% → happened 71.0%.
The model does not know which starters will be allowed to go deep.

### Out-of-sample, against the estimator it replaces

`versus_estimator("2026-08-01", refit=True)` — rates AND hook offsets
trained strictly before the cutoff, scored on 445 unseen starts:

| line | sim Brier | est Brier | sim AUC | est AUC |
|---|---|---|---|---|
| k 3.5 | +6.3% | −0.7% | 0.656 | 0.592 |
| k 4.5 | +7.3% | +1.0% | 0.660 | 0.607 |
| k 5.5 | +8.9% | +5.7% | 0.673 | 0.650 |
| k 6.5 | +9.8% | +0.1% | 0.708 | 0.672 |

The estimator barely beats quoting the base rate. Refitting the offsets on
the training window moved the sim by +0.3pt, so the earlier leakage was
negligible — but `refit=True` is the default now and should stay.

### Outs: decent ranking, poor calibration — which is the fixable kind

| line | AUC | Brier skill |
|---|---|---|
| outs 11.5 | 0.616 | 1.2% |
| outs 14.5 | 0.640 | 2.9% |
| outs 15.5 | 0.645 | 4.4% |
| outs 17.5 | 0.643 | 5.2% |
| outs 18.5 | 0.677 | 4.2% |
| outs 20.5 | 0.688 | 3.9% |

AUC 0.62–0.69 is real ranking ability, so the low Brier skill is
MISCALIBRATION, not absence of signal — bias runs −4.0% at 14.5 and +2.8%
at 18.5. An isotonic or Platt fit on a holdout should recover a chunk of the
gap. (An earlier note in this file called outs "weak discrimination, the
unfixable kind". That was wrong; these AUCs say otherwise.)

### THE LEAD: the sim over-produces baserunners, and that shortens starts

Calibrating all six counting stats at once found what outs alone could not.
1,776 starts, club patience and pitcher leash applied:

| stat | line | bias | Brier skill | AUC |
|---|---|---|---|---|
| k | 5.5 | +1.1% | 20.4% | 0.771 |
| outs | 14.5 | −4.9% | 7.2% | 0.691 |
| outs | 15.5 | −4.1% | 9.7% | 0.686 |
| **h** | 3.5 | **+7.2%** | 0.4% | 0.615 |
| **bb** | 2.5 | **+6.2%** | 6.4% | 0.703 |
| **hr** | 0.5 | **+4.5%** | 5.2% | 0.660 |
| er | 4.5 | −3.7% | 0.2% | 0.582 |

Hits, walks and home runs all read high; outs read low. **That is one
defect, not two.** Excess baserunners feed `per_baserunner` and `per_run`,
the hook fires early, starts come out short.

Isolated:

```
                    sim    actual     diff
outs / batter    0.7017    0.7094   -0.0077   (-1.1%)
batters / start   22.87     22.88     same
baserunners       7.06      6.65     +0.41
```

Batters faced matches exactly; the sim converts fewer of them to outs, by
0.18 outs per start. Two out-sources it structurally cannot produce account
for nearly all of it:

- **Caught stealing / pickoffs** — measured at ~0.10 per start. CS counts
  toward a pitcher's outs recorded, so this is a direct loss.
- **Sacrifice bunts and flies** — automatic outs. The sim rolls BABIP on
  those plate appearances instead, turning ~29% of them into hits.

Neither is in `StartResult`. Both add an out without a hit. This is the
highest-value fix on the list and it needs no new data source.

Corollary already checked and ruled out: the batting-side league rates run
3.2% above the pitching-side ones, uniformly across K, BB and HR. That is
pure denominator scaling (PA approximated as AB+BB) and it is
SELF-CONSISTENT — the sim's plate appearances exclude HBP and sacrifices,
so its rates should sit above per-real-PA rates by exactly that much. Not
the bug; do not re-chase it.

### How many simulations is enough (measured)

Same config, three seeds, k 5.5 over 600 starts:

| n_sims | seed 1 | seed 2 | seed 3 | sd | theory 1/n |
|---|---|---|---|---|---|
| 40 | 20.18% | 17.71% | 19.94% | 1.11% | 2.50% |
| 110 | 21.08% | 19.93% | 21.41% | **0.63%** | 0.91% |
| 300 | 21.52% | 21.04% | 20.73% | 0.32% | 0.33% |

Two separate effects. Monte Carlo noise **systematically deflates Brier
skill** — 40 sims reads ~19.3% where 300 reads ~21.1% — because it inflates
Brier by p(1−p)/n. That cancels in an A/B where both arms share n_sims, so
it does not bias a comparison, but it does mean any ABSOLUTE skill number
quoted from a low-sim run is understated.

What does not cancel is the 0.63pp seed scatter at n=110. **An A/B at 110
sims can detect a true effect of roughly 0.5pp or larger, not smaller.**
Quote that floor whenever a delta comes in small.

### Park factors — the double-count, and the fix

Three-way A/B, mean Brier skill over K/outs/hits/HR lines at n_sims=110:

| config | mean Brier skill |
|---|---|
| no park | 8.66% |
| park applied to raw rates | 8.59% |
| **park + rates neutralised** | **9.00%** |

The ORDERING is exactly what the mechanism predicts, which is the
interesting part: raw park is slightly WORSE than no park at all, and
neutralising recovers more than it costs.

Why raw park fails: a player's season line is not park-neutral. He takes
about half his plate appearances in one stadium, so Logan Gilbert's K rate
is inflated 10.6% by T-Mobile and Tanner Gordon's suppressed 7.9% by Coors.
Applying tonight's index to that raw rate counts the home park one and a
half times and mis-bases the road side. Measured exposure spread: starters
0.921–1.106 (sd 0.032), batters 0.940–1.091 (sd 0.030) — **the same size,
because hitters play half at home too.** An earlier note here claimed
hitters average over fifteen parks and are therefore fine; that was wrong.

`rates.park_exposure` / `rates.neutralise` divide each rate by the
usage-weighted park it was accumulated in. Requires `games.venue_id`, which
is why this could not exist before the venue backfill.

**+0.34pp is BELOW the 0.5pp detection floor above.** Direction and ordering
both match theory, which is worth something, but this is not established.
Confirm at n_sims >= 300 before switching `NEUTRALISE_PARK` on by default.

### Park factors — wiring notes

`games.venue_id` now exists, backfilled over 1,117 games from the schedule
endpoint (one call per DATE, not per game). `sim.park_mults` converts
Savant indices to rate multipliers for HR, K and balls in play.

Why the id and not the home team: **the Athletics played 38 home games this
season at venues Savant does not rate, and the Twins one.** Under a
home-team lookup all 39 would silently have received the wrong club's park.
`park_mults(None)` returns neutral, never a borrowed park.

Spread available: runs 83–125, HR 75–125, **SO 89–116** — the last matters
because K is where the model has signal.

NOT YET A/B'd against no-park. Do that before believing it helps.

**Park and home/road are confounded; fit in that order.** Savant's indices
are team-neutral by construction (three rolling years, every club visits),
and home advantage is roughly constant across parks, so park is the
exogenous term. Fit home/road as a residual on what park does not already
explain — fitting them jointly, or home/road first, lets the home term
absorb park. Same trap as using a club's raw starter length for manager
patience. Unmodelled: any park × home interaction.

### Home/road is real; day/night is not

Raw league splits over 1,776 rotation starts, before any modelling:

| split | metric | value | z |
|---|---|---|---|
| home v away | K rate | 0.2253 vs 0.2110 (+6.8%) | **+3.49** |
| home v away | hit rate | 0.2164 vs 0.2253 (−3.9%) | **−2.15** |
| home v away | outs | 16.12 vs 15.79 (+0.33) | +1.80 |
| day v night | K rate | 0.2159 vs 0.2189 (−1.4%) | −0.69 |
| day v night | hit rate | 0.2180 vs 0.2225 (−2.0%) | −1.03 |
| day v night | outs | 16.01 vs 15.92 (+0.09) | +0.45 |

`HOME_OPP_K = 1.068` and `HOME_OPP_CONTACT = 0.961`, applied to the opposing
lineup. **Set from the measurement, not tuned against Brier** — two free
parameters searched against the metric they are then scored on will find
something whether or not anything is there. Two multipliers because one
cannot fit both: K moves +6.8% while contact moves −3.9%.

`HOME_HOOK` stays 0.0. The outs difference does not clear 2σ on its own and
should emerge from the rate effects rather than be counted twice.

**Correction to an earlier worry in this file.** Park and home/road are NOT
confounded at the league level: every park hosts 81 home starts and 81 away
starts, so park balances out in the aggregate split. The confounding is real
only PER PITCHER, whose home starts all happen at one venue — so a
per-pitcher home term must still be fitted after park, but the league-wide
numbers above stand on their own.

**Day/night is a measured negative.** `games.day_night` and `games.start_utc`
are populated (MLB's own classification, not inferred from the clock) so this
is cheap to re-check, but nothing in it clears z=1.1 and a term keyed on it
would be fitting noise.

### Bullpen usage was being measured with the broken heuristic

`workload._primary_cte` used most-outs, which counted 2,026 reliever outs as
starter work and 880 starter outs as relief — a net 5% **understatement** of
relief innings. The error is not random: a long reliever only outranks the
starter when the starter was knocked out early, which is exactly the night
the pen had to cover six innings. So it was most wrong on the days the
bullpen was most taxed, which is the entire signal `bullpen()` exists to
measure. Now uses `is_starter` where available.

Still **not consulted by the simulator.** A gassed pen means a longer leash,
and `bullpen(as_of)` is already as-of correct and local, so this is a wired
gap rather than a missing capability.

### The scoreboard, and the pattern in it

Everything tried on top of the simulator, measured the same way:

| addition | verdict | evidence |
|---|---|---|
| club patience + pitcher leash | **KEEP** | outs skill 3.8–9.8% vs 1.2–5.2% flat |
| home/road | **KEEP** | K rate z=+3.49, hit rate z=−2.15 |
| park + neutralised rates | maybe | +0.34pp, below the 0.5pp floor |
| park on raw rates | reject | −0.07pp; double-counts |
| handedness splits | reject | deltas alternate sign, AUC unchanged |
| arsenal multipliers | reject | 9.79% vs 9.79%, exactly zero |
| day/night | reject | nothing clears z=1.1 |
| bullpen availability | reject | z ≤ 1.4 under four proxies |
| input uncertainty | reject | actively harmful; compresses further |

**The two that worked are the two fitted as residuals against the model's
own output. Every one imported as a known baseball effect failed.** That is
not a coincidence worth ignoring: the market prices the consensus
construction, and handedness, park, day/night and bullpen ARE the consensus
construction. Adding them to a model already near consensus buys nothing.

**The defect hunt is 4-for-4 over the same period**: the starter heuristic
truncating the left tail, the double-advance base-running bug, baserunner
over-production, and openers being priced as starters. Spend time there.

### Arsenal multipliers: right theory, zero result

Worth recording in full because the reasoning was correct and still lost.

The prediction was that arsenal would succeed where handedness failed,
because handedness varies by BATTER and nine of them average it away, while
an arsenal varies by PITCHER and the whole lineup faces the same one. That
prediction was verified — per-start mean k-multiplier sd is 0.0642 (range
0.864–1.180) where handedness scored about zero on the same measure. The
between-start variance is genuinely there.

It bought nothing. 9.79% mean Brier skill with, 9.79% without.

One sub-pattern, below the noise floor, recorded so it is not rediscovered
as a fresh idea: every HIGH K line improved on both Brier and AUC — k 7.5
+0.67pp with AUC 0.813 → 0.822, k 6.5 +0.62pp — while low K lines and outs
slipped. Consistent with a whiff-derived signal discriminating big
strikeout games. If revisited: re-run at n_sims >= 400 and commit to the
high-K hypothesis BEFORE looking, or this is just subset selection.

`rates.arsenal_mults` and `BatterRates.arsenal_k_mult` are kept and correct;
`calibrate.USE_ARSENAL` is the flag.

### Measured negative: handedness splits do nothing

Hypothesis was that vs-LHP/vs-RHP batter rates would supply the missing
between-start variance. Built (`rates.batter_rates_by_hand`, derived
locally from the opposing starter's throwing hand so it stays as-of
correct), A/B'd over 1,776 starts, and it is a wash:

- K lines: Brier skill deltas −0.23% to +0.49%, alternating sign
- outs lines: −0.20% to +0.40%
- AUC unchanged to three decimals on all twelve lines

It genuinely adds 20.3% more between-BATTER K% spread, which is why this is
worth recording rather than quietly dropping: **between-batter variance is
not between-start variance.** Platoon deviations largely average out across
nine hitters.

Confound not yet ruled out: the derivation is attenuated, because a batter's
game line includes plate appearances against relievers and `SPLIT_STABILISE`
then pulls each split halfway back to his overall rate. Testing statsapi's
exact splits would separate "the idea is wrong" from "our splits are too
small". `calibrate.USE_HANDEDNESS` is the flag; code is kept, default off.

### The bigger hole for outs, not yet built

The sim has **no game score**. It simulates one pitcher against one lineup
and does not know whether his team is winning, so a starter at 95 pitches in
a 1–0 game and one at 95 pitches in an 8–1 game are the same decision to it.
It also never consults `workload.bullpen()`, which is already in the local
cache. Both plausibly matter more for "which starters go deep" than platoon
splits do, and neither needs play-by-play.

**Known defect: the model is under-dispersed**, and specifically it
under-rates the top bucket at every line by 5–6 points (said 22.2% →
happened 28.5% at k 8.5; said 49.8% → 55.2% at k 6.5). Note the direction:
Monte Carlo noise would push the extremes *toward* the base rate, so the
true effect is LARGER than the tables show. The model is missing real
between-start variance. Candidates, untested: batter handedness splits are
not used (lineups carry only four overall rates), park applies to home runs
only, and there is no pitcher form/recency term.

Practical consequence: the sim **under-flags** rather than manufacturing
edges. That is the safe direction, and the opposite failure mode from the
0.08 rule.

### What is fitted and what is guessed

| thing | status |
|---|---|
| league rates, hit mix, BABIP | computed from the local boxscore cache |
| hook parameters | fitted by `calibrate.tune` against the observed hazard curve, boundary share and threshold rates |
| club patience | fitted as a RESIDUAL against what the model already predicts — never raw team average, which would double-count rotation quality |
| pitcher leash | fitted on top of club patience, in that order, shrunk by start count |
| `PITCH_COST`, `GIDP_RATE`, advancement rates | tuned to reproduce marginals; the boxscore cache has no pitch counts, so these are the least trustworthy numbers in the module |

### Leakage, and what has NOT been shown

Player rates in the reliability tables are season-long, including the games
being replayed. That is correct for "does the machinery produce the right
shape" and wrong for "does it predict". `calibrate.versus_estimator(cutoff)`
does the clean split and compares against the old estimator; run it before
believing any of the above predicts anything.

**Nothing has been compared against a price yet.** Calibration says the
probabilities are honest. A perfectly calibrated model that agrees with the
book everywhere earns nothing. The market comparison is a DEFECT check
first: if the sim disagrees with Kalshi's whole board, we are broken.

---

## Partially-applied fix (finish this)

`_shrink(hits, n, prior)` used to pull toward **0.5**, i.e. it priced every
bet as +100 while `edge()` compared the result against the real number. The
two halves lived in different worlds. On Mahle over 8.5 K the estimate came
out 0.397 against a market of 0.065; with the market as prior it is 0.225.

Threaded through:

- `scan.py` → passes the book midpoint ✓
- `resilience()` → passes break-even ✓
- **`estimate_outs()` → still defaults to 0.5** ✗

`assess()` *has* `bet["american_odds"]` and uses it only afterward in
`edge()`. Thread it into `estimate_outs`, then **re-run the AUC** — the
0.537 figure below was computed with the broken prior.

**Lower priority now than it was.** This fixes the estimator the simulator
is meant to replace. Worth doing only to keep the baseline honest for
`versus_estimator`, which is exactly the comparison that decides whether the
simulator earned its keep — so do it before trusting that comparison, and
not before.

---

## Starter identification — fixed 2026-08-22, keep it fixed

`mlb_pitching` carried no starter flag, so callers inferred one as "most
outs on that team that game". Measured against 2,012 boxscores that is
**wrong 8.6% of the time**, and the misses are not random: every one is a
starter knocked out early whose long reliever passed him. Tyler Gilbert at
two outs was credited to David Sandlin; Zack Wheeler at six to Kyle Bradish.

The bias runs one way and it is large where it matters:

| | mean outs | P(<12 outs) | P(<9 outs) |
|---|---|---|---|
| ground truth | 15.21 | 15.2% | **8.6%** |
| most-outs heuristic | 15.78 | 11.0% | **2.9%** |

A hook fitted to the heuristic has been taught that starters do not get
blown out — which is precisely the region an under bet lives in.

Now: `mlb_pitching.is_starter`, backfilled over 1,005 games and set going
forward by `grading.mlb_boxscore` from the API's own `gamesStarted` field.
`context/sources/starters.py` holds the backfill and an audit.

**Openers are correctly flagged as starters and are excluded from the
MODELLED population** via `calibrate.ROTATION_MIN_GS` (5 starts on the
season). Of the 172 heuristic misses, 101 were openers averaging 4.5 outs
and 71 were rotation starters knocked out early. The first group belongs in
the data and not in the model — no book offers an outs line on a bulk
reliever. The second group belongs in both, and was the thing being lost.

---

## Established findings — do not re-investigate

| finding | evidence |
|---|---|
| Head-to-head is noise | 1 of 234 batter/starter pairs on a full slate carried information the arsenal projection didn't. Samples are structurally tiny (median 3 PA, max 34) and *are already career* — season param makes no difference |
| Umpire tendencies unusable | 1,113 games / 90 umpires ≈ 12 each. Apparent 77–118 K-index range collapses to 90–99 once any sample bar is applied |
| Estimator has no edge on outs | AUC 0.537, permutation p=0.289, n=79. Expected: the market price *is* this construction |
| Source CLV differences are bet-type mix | outs unders pay +0.039 to anyone; HR overs pay 0.000. Controlling for stat×side, no source's CLV interval excludes zero |
| ESPN has no odds history | 0 of 15 games have any odds node on any past date. `open`/`close` exist only for current/upcoming. Game-line CLV is forward-only |
| Kalshi has ~2 months of history | Settled markets + timestamped trades back to 2026-06-22. This is why prop CLV was backfillable and game lines were not |
| statsapi has no times-through-order | Checked all 602 situation codes. Savant's TTO endpoint 404s. Field was dropped |
| Savant catcher-framing ignores `min` | `min=q`, `min=1`, `min=0`, omitted — all return the same 61 catchers. Part-timers are permanently absent |

### Unproven but promising

**Bootstrap resilience.** AUC 0.590 vs 0.537 for the point estimate;
resilient bets 23/30 (77%) vs fragile 28/49 (57%). Permutation p=0.069 raw,
**0.35 Bonferroni-adjusted for the 5 metrics tried**. The mechanism argument
is the persuasive part and is independent of this weak sample: the market
prices the consensus construction, resilience isn't part of it, and it's
unglamorous enough that most people skip it.

Caveat: `share_with_edge` **saturates on longshots** — at a 0.07 break-even
almost any estimate clears it, so the metric pins at ~100% and stops
discriminating exactly where the scan produces most flags.

---

## Untuned constants doing real work

Every one of these was invented, not derived. Two have already been caught
mis-set by looking at what they actually admitted.

| constant | value | status |
|---|---|---|
| `estimate.SHRINK_K` | 4.0 | never tuned. Sets how fast a sample overrides the market: with n=6 it caps movement at 60% of the way from price to raw rate |
| `estimate.MIN_DISAGREEMENT` (in scan) | 0.08 | **known too small** — see top section |
| `estimate.SURVIVE_AT` | 0.80 | was 0.60; at 0.60 a tight `[15,16,16,16,17]` and a scattered `[5,25,10,22,18]` both "survived" to 3 outs of noise |
| `estimate.JITTER_LEVELS` | 0,1,2,3 outs | arbitrary |
| `statsapi.RECENT_DAYS` | 42 | picked to span Painter's injury gap and Lopez's stretch-out |
| `batter.H2H_MIN_PA` / `H2H_DIVERGENCE_SLG` | 20 / 0.150 | PA gate does all the work; the SLG bar is nearly inert |
| `workload.LONG_STRETCH` / `rest.FAR_MILES` | 13 days / 1200 mi | never validated |

---

## Open questions, each with a specific test attached

- **`opponent_profile` group substitution.** A club's season split vs
  handedness applied to tonight's nine. Same shape as the two substitution
  bugs already fixed; individual `batter_splits` now exist to test it.
- **`defense` group substitution.** Same, but my measurement was confounded
  — Savant's OAA leaderboard covers only 5–6 of 9 starters, so a team total
  vs a partial lineup sum isn't a valid comparison. Needs full coverage.
- **Lineup prediction vs dropping batter-side.** Standing decision is
  *drop* — `confirmed_lineup` is required for batter props. History is
  backfillable to 2026-05-28, so no urgency. Cheap precursor: measure how
  often "most frequent recent starter" gets the catcher right before
  building anything.
- **Does the context layer improve the card at all?** Unanswerable until a
  card is built *with* it. Needs the persona wiring, which is not done.

---

## Not built

- **The simulator is not wired into `scan.py`.** This is the top of the
  list: the scanner still uses the six-start estimator behind the broken
  0.08 rule, and the simulator exists precisely to replace both halves.
- **Nothing has been priced against the market.** Run the sim over Kalshi's
  whole board and compare. Read it as a defect report first — nearly every
  large divergence this project has chased turned out to be our own bug.
- `versus_estimator(cutoff)` is written but its verdict has not been
  recorded here. Until it has, "the simulator is better" is unproven.
- Snapshots are **not** wired into the personas — they still get the old
  52k blob plus `web_search`
- No MCP server
- Simulator covers `outs` and `k`. `h_allowed` and earned runs fall out of
  the same `StartResult` and need only calibration lines and tests.
- Scan population is Kalshi's board, which is the right unfiltered set —
  earlier evaluations used capper selections and had a 65% base rate, which
  no real market has

## Testing convention

`make test` — 107 checks, ~40s, offline, no pytest. `tests/run.py` collects
every `check_*`. Three modules: `test_pure.py` (properties),
`test_regressions.py` (one check per shipped bug), `test_sim.py`
(simulator invariants).

**Verify a new test by mutation.** Reintroduce the bug it guards and confirm
that exact check fails. Six mutations were run against `test_sim.py` and all
six were caught — but the first attempt at one of them mutated the wrong
line and passed, which is the failure mode to watch: a test that guards
nothing looks identical to a test that guards something.

## Gotcha worth remembering

Nearly every large divergence chased this session turned out to be **our
bug**, not a market inefficiency: relief appearances contaminating a
starter's average, outcome leakage in the first CLV pass (Kalshi settles at
0/1, so the last trade is the box score), a `close` that was a settled
contract, team-name matching, neutral sites. Treat a big flag as a defect
report first and an opportunity second.

---

# DAY FIVE

## The recorded K-prop edge is an August edge

Re-measured at n_sims=1500 across the whole backfilled season, one window
at a time. Every number in this project's CLV record came from eight dates
in mid-August, and that window is not representative:

    window            n     corr    blend    dir     cents
    June           1,464  +0.416   +13.1%   59.1%   +1.8c
    July           3,134  +0.299    +7.7%   59.6%   +1.7c
    August (21d)   3,164  +0.575   +30.4%   69.0%   +3.3c
    SEASON (82d)   7,762  +0.451   +17.5%   63.4%   +2.4c

August reproduces the recorded +0.586 / +32.9% / 73.2% / +3.7c closely, so
nothing was mismeasured. What was wrong is the generalisation. June and
July run at roughly half the edge and July is the worst month of the three,
which rules out "the rates had accumulated" — that story predicts a
monotone curve and this is a V.

Chased and eliminated as explanations: Monte Carlo error (n_sims saturates
at 1500 — 250 gives +0.490, 1500 +0.515, 2000 +0.516 on the same
contracts); the measured advancement/GIDP tables (all four states within
0.002 corr of each other); stale hook offsets (`USE_OFFSETS` was already
False and the JSON files are unused).

**Quote cents, not correlation.** The pooled season corr (+0.451) sits
ABOVE both June and July because pooling windows with different levels
inflates it. And z is not an effect size — it went +41.4 -> +67.1 purely on
n growing 6x.

## Inherited runners: the advancement mistake, exactly repeated

5,507 inherited runners across 2,006 games (`src/context/inherit.py`),
followed by runner ID across each pitching change using the same
`pbp.resolve` the base-state reconstruction uses.

    overall 0.312   against the shipped flat 0.330

                0 out   1 out   2 out
        1B      0.396   0.267   0.127
        2B      0.628   0.428   0.215
        3B      0.771   0.633   0.229

Pooled it is near enough to the shipped constant to look settled, and every
cell is wrong — 0.127 to 0.771. Two-out handovers are the most common state
(2,624 of 5,507), so the flat rate over-credits the majority case and
inflates a departing starter's earned runs. That is the third time the
"aggregate is right for cancelling reasons" pattern has appeared here.

Behind `sim.USE_MEASURED_INHERITED`, deliberately NOT in `FITTABLE`.
Start-level runs/start 2.5693 -> 2.5497. `game.py` never used the constant.

## Relief outings run to their measured length

13,248 outings (`src/context/relief.py`, `game.USE_MEASURED_RELIEF_LENGTH`).
The continuation hazard is conditioned on the ENTRY state, and that is the
finding:

    entered with 0 out   continues 20.1%   n=9,734
    entered with 1 out   continues 44.8%   n=1,572
    entered with 2 out   continues 62.7%   n=1,942

Same shape as advance-on-out: one pooled constant cannot serve a man
brought in for one out and a man handed a clean inning. Engine effect —
arms per side 5.05 -> 4.07, mean total 8.16 -> 8.19 (unchanged), sd
3.91 -> 4.08. Level held, spread up, against the known under-dispersion.

Mid-inning entries are still starter-hook-only, so the model cannot yet
reach the real 30.4% (= entry_outs>0 OR runners on; the narrower
entry_outs>0 alone is 26.5%, which is what day four's 30.4% figure meant).

## The mutation harness was lying, and it cost an hour

`.pyc` validity is (mtime, size). A harness that rewrites a source file
twice inside the same second, with a mutation that PRESERVES SIZE
(`+= 1` -> `+= 0`), reuses stale bytecode — the mutation never happens, and
a genuinely-guarded behaviour is reported as unguarded. It also produced a
baffling debug session where a counter visibly failed to increment.

All `scratchpad/mutate_*.py` now clear `__pycache__` and run the suite with
`PYTHONDONTWRITEBYTECODE=1`.

The same harness caught three defects in checks written that hour:

* a fixture where counting-by-innings and counting-by-outs both returned
  1 of 3, so the assertion could not tell the definitions apart;
* two checks aimed at guards that were defensive rather than load-bearing
  (iterating an empty dict already does nothing), which passed trivially
  and guarded nothing;
* a vacate-then-place check that could not fail because `pending` is keyed
  on runner id, so the stale duplicate was overwritten. It only bites when
  a runner leaves a base nobody refills — scoring from first on a double.

**Write the mutation before believing the check.** That is now four times
this project has shipped a check that guarded nothing.

## The August anomaly survives every test I could throw at it

Five explanations, each eliminated on data rather than argued away:

1. **Monte Carlo error.** n_sims saturates at 1500 (250 +0.490, 1500 +0.515,
   2000 +0.516 on the same 1,222 contracts). Real but small, and it cannot
   move +1.7c to +3.3c.
2. **The measured advancement/GIDP tables.** All four states land within
   0.002 corr and 0.6pp of blend. Flat.
3. **Population composition.** `price.priceable` admits different arms as
   the season goes on, so restrict to the 101 pitchers priced in ALL three
   months: June +1.7c, July +1.9c, August +3.2c. Unchanged.
4. **Liquidity composition.** Within every month the edge falls as trade
   count rises, so a shift toward thin markets would explain it. August has
   FEWER thin markets (8% against June's 22%) and still beats both months
   in EVERY bucket — thin +4.1c vs +2.8c/+2.5c, and even 100+ trades
   +2.1c vs +1.5c/+1.3c. The composition works AGAINST August.
5. **A directional drift the model happened to match.** August opens 0.447
   and closes 0.456, roughly +0.9c toward the over, where June and July are
   near flat; `sim` is documented as running high, so a permanently
   over-leaning model would score free direction points. Tested by removing
   each month's own mean drift from the target. The edge does not shrink,
   it GROWS (+3.3c -> +3.5c), and the ranking is unchanged.

   The hypothesis was backwards. The model leans UNDER — it says over on
   34.8% / 35.5% / 41.8% of contracts — so the upward drift was suppressing
   measured direction accuracy in all three months (centring lifts June
   59.1% -> 66.6%, July 59.6% -> 67.5%, August 69.0% -> 75.2%).

What is left is a genuine regime difference. August markets move much more
(sd of close-open 0.0417 -> 0.0619, +48%) AND our direction on which way
they move is genuinely better (66.6% -> 75.2% centred). The second does not
follow from the first, and neither follows from anything about our model,
which did not change.

**Untested, and where to look next:** whether Kalshi changed when or how it
opens these markets late in the season; whether lineup/roster completeness
in our own inputs improved; and whether the set of games listed changed.
All three are about the market and the data feed rather than the simulator.

**Until that is understood, plan against the June/July number (~+1.8c), not
the August one.** Rows are cached at `scratchpad/august_rows.json`, so any
follow-up analysis is free — do not re-simulate to ask a market question.

## Relievers can now be pulled mid-inning

Of 4,026 mid-inning handovers only 41.8% come from a starter; the other
58.2% are reliever-to-reliever, which the engine could not produce at all.
Behind `game.USE_MEASURED_RELIEF_HOOK`, from a per-PA hazard over 50,023
in-inning relief plate appearances:

                0-2 bat     3-5     6-8      9+
        0 runs    0.015   0.099   0.073   0.070
        1 runs    0.045   0.130   0.097   0.060
        2 runs    0.033   0.141   0.122   0.087
        3+ runs   0.061   0.109   0.116   0.080

BEWARE THE SURVIVORSHIP TRAP that this replaced. Conditioning on a stint's
TOTAL runs gives 19.1% at zero rising to 40.5% at three, which reads
perfectly plausibly and is inflated by exactly the arms that stayed in and
kept being scored on — for a pitcher who was NOT pulled the total keeps
accumulating past the decision point. The per-PA hazard on state-before-the
-decision is 3.5% at zero runs and ~10% once he has been scored on.

The batter dimension is NOT monotone: the first two batters are nearly
immune (he has just been brought in for this situation), the hazard peaks at
3-5, then falls away. `game.py` used to hard-code that protection as a flat
rule, which is why it could never pull a reliever at all. It now lives in
the table.

Pitchers used per side: league 4.30, model 5.05 with neither mechanism, 4.07
length-only, 5.66 hook-only, **4.53 with both**. Length-only is equally
close in absolute terms but gets there BY CANCELLATION — no mid-inning
relief changes at all, offset by outings that run too long.

## A fourth guards-nothing check, and this one was pre-existing

`check_evaluate_applies_its_parameters` claimed to guard that a fitted
constant moves the loss. Its fixture uses fake team names ("HOM"/"AWY"), so
`rate_src.bullpens` returned nothing, `Side.pen` was empty, and
`Side.current` falls back to the starter for the entire game — `intercept`
had NO channel to run production whatsoever. It only ever passed because
changing the value shifted the RNG stream, and it broke the moment an
unrelated change consumed one draw per plate appearance and realigned the
two streams. Fixed by injecting a pen that is clearly worse than the
starter, so who is pitching actually moves runs; verified by mutation
(emptying the pen reproduces the original failure).

Related trap for anyone writing mutations here: `str.replace(old, new, 1)`
hits the FIRST occurrence, and there are now two `next_arm(fr.outs)` call
sites. A mutation meant for the starter's silently hit the reliever's and
reported a miss. Anchor on surrounding context.

### Sixth test: the open is not staler in August

If Kalshi's markets got their first trade earlier relative to first pitch,
the "open" would be a staler number and easier to beat. `price_path`
already returns `first_at` and `first_pitch`; `versus_market.collect` just
discards them. Sampled ~220 settled K markets per month:

    month     sampled   mean lead hrs   median   mean trades
    2026-06       206            12.9     13.4          37.7
    2026-07       212            13.8     14.3          48.8
    2026-08       219            14.4     14.5          64.2

Flat. An 11% difference in lead time cannot double an edge.

**And it deepens the puzzle rather than settling it.** Trades per market
rose 70% across the same window. WITHIN each month more trades means LESS
edge (the liquidity table above is monotone). ACROSS months more trades
comes with MORE edge. That reversal is independent confirmation that the
cross-month difference is not a liquidity story at all — it runs the wrong
way for that.

Six hypotheses down. The anomaly stands.

## The bullpen work does NOT improve prediction, and an earlier claim in
## this session was wrong

Scored on the prefix ladder against ACTUAL runs (not prices), 250 games
since 2026-07-01, paired per game on identical seeds:

    + relief length     F7  |err| +0.0069 +/- 0.0185  (+0.4 sigma)
    + mid-inning hook   F7  |err| -0.0242 +/- 0.0196  (-1.2 sigma)
    + inherited         F7  identical to the hook row

So the three mechanisms are measured correctly, make the engine
demonstrably more realistic (pitchers per side 5.05 -> 4.53 against a league
4.30; mid-inning relief changes exist at all), and have NO established
effect on predictive accuracy. All three of those are compatible and the
measured values stay — that is the standing rule, and a worse or flat score
locates compensation rather than licensing a revert.

**A NUMBER REPORTED EARLIER IN THIS SESSION WAS AN ARTEFACT.** An interim
run showed F7 error falling from -0.134 to -0.035, a 74% cut, and it was
reported as encouraging. It does not survive correct pairing. It came from
an ad-hoc per-GAME seeding patch which still let draw 1 perturb draws 2..n
inside the same game, so it was measuring dice. The real effect is ~0.02
runs and sits inside the noise.

### `ladder.simulate_prefixes` had a seeding defect

One `random.Random(seed)` for the entire loop, so any downstream change
shifted the stream for every later game AND every later draw. Comparing two
model states therefore contaminated everything after the first difference.
The symptom: a bullpen flag moved F1, an inning in which a reliever can
barely appear.

Fixed by seeding per (game, draw). PER-GAME SEEDING IS NOT ENOUGH and looks
like a fix — the draws within a game still share a stream. Both are pinned
by `check_the_first_inning_is_immune_to_a_bullpen_flag`, and both were
mutation-verified; the per-game-only variant fails it.

That check uses an EMPTY pen on purpose, so no reliever pitches and F1
immunity is exact. On real pens F1 can move a few thousandths honestly — a
starter knocked out in the first hands over inside F1 — and a check that
tolerated that could not separate the two causes.

### Pairing is worth more than sample size here

The spread of prefix error ACROSS games is ~0.28 runs, which swamps a
0.02-0.10 run effect. The same games on the same seeds make the per-game
DIFFERENCE the statistic, and its standard error is ~0.02 — an order of
magnitude tighter. Comparing two independently-reported means, which is what
reading two `ladder.report` outputs side by side does, is the wrong test and
will never resolve an effect this size.

### `fitf5.evaluate` seeds per GAME, not per draw

Same class as the ladder defect, milder. `rng = random.Random(away["seed"] +
salt)` sits outside the `n_sims` loop, so the draws within a game share a
stream and a model change in draw 1 perturbs draws 2..n.

Games ARE properly paired across model states, and game-to-game variation is
the dominant term, so `score_adv`-style results are valid. They are simply
less sensitive than they could be: Monte Carlo noise that per-draw seeding
would cancel is left in the paired standard error. When the effects being
compared are ~0.02 runs, that is the difference between resolving one and
not.

NOT CHANGED, deliberately. Re-seeding the fitting harness would move every
fitf5 number ever recorded and break comparability with the entire existing
record, so it is a decision to take explicitly rather than a tidy-up. If it
is taken, the whole recorded ladder of losses has to be re-run, and the
expectation does not change — only the variance of the comparison drops.

## THE YARDSTICK: we are at 91-98% of the market's discriminating power

Everything in this file measures CALIBRATION — is the model right on
average. That is not what a bet needs. The quantity that matters is
RESOLUTION: how far predictions pull away from the base rate and stay
right. Murphy's decomposition separates them:

    Brier = reliability - resolution + uncertainty

`uncertainty` is the base rate's own variance, identical for every
forecaster, and it is the part nobody can beat. On K props, 7,762 cached
contracts, no simulation required:

              RESOLUTION                   reliability
            market    ours     open      market     ours
    June    0.0815   0.0797   0.0781     0.0027    0.0083
    July    0.0798   0.0728   0.0787     0.0009    0.0013
    August  0.0902   0.0833   0.0856     0.0014    0.0005

**Our resolution is 97.8% / 91.2% / 92.3% of the market's.** The entire gap
is ~0.007 Brier, about 2.5 points of skill. So the honest reading of a long
run of "no measurable improvement" is not that the work was bad — it is
that the room is small and largely already taken.

TWO RESULTS WORTH KEEPING SEPARATE FROM THAT.

**We are BETTER CALIBRATED than Kalshi.** August reliability 0.0005 against
0.0014. Our probabilities are more honest; we simply separate games slightly
less well. Anyone reading "we lose to the close on Brier" as "the model is
worse" has it wrong — we lose on resolution and win on calibration.

**We have LESS resolution than the OPENING price** in July (0.0728 vs
0.0787) and August (0.0833 vs 0.0856). This matters more than the headline.
It means the recorded CLV edge is NOT superior knowledge of the game: we
anticipate where the price will MOVE without being more accurate about the
OUTCOME. Those are different products, and AF_PLAN commits to the second
one. A CLV edge built on the first is real money and a fragile thing to
model against, because it depends on the market's behaviour rather than on
baseball.

CAVEAT: measured on K props, the only market with rows cached. Team totals
show a similar ratio (ours +18.4% skill against the market's +20.7%, 0.89),
so the picture probably holds, but the F5 and team-total versions should be
run rather than assumed.

WHAT THIS IMPLIES FOR WHAT TO BUILD. Chasing resolution inside the run
engine competes for ~8% of an already-small quantity. The mechanisms worth
building are the ones that DIFFER ACROSS GAMES, because only those can add
resolution; a league-wide constant moves the level and cannot, by
construction, separate anything.

## The bullpen work shows nothing in THREE framings — and the F7
## distribution was already right

Day five kept re-testing the same mechanisms on new metrics, on the theory
that the previous metric was blind to them. It was not.

    framing                    verdict
    mean prefix error          ~0.02 runs at 1.2 sigma
    CLV against Kalshi         SLIGHTLY WORSE (+1.5c -> +1.3c)
    distributional CRPS        every state within 0.6 sigma

The variance argument was the last one standing and it is now dead too.
Relief length was justified on spread (engine sd 3.91 -> 4.08 in a synthetic
harness), so the natural defence of a flat mean was "it moves the
distribution, and a total settles on the distribution". Scored properly on
200 real games at F7:

    state                 CRPS   coverage   sim sd   paired dCRPS
    all off             2.0512     84.0%    3.610        +0.0000
    + relief length     2.0440     82.0%    3.619        -0.0072
    + mid-inning hook   2.0473     84.5%    3.623        -0.0039
    + inherited         2.0473     84.5%    3.623        -0.0039
    + TTO               2.0586     81.5%    3.599        +0.0074

    actual sd 3.589, coverage target 80%

**THE REASON IS IN THE SAME TABLE.** Simulated sd 3.61 against an actual
3.589, coverage 84% against a target of 80%. There was no dispersion error
at F7 to fix, and the model is if anything mildly OVER-dispersed — the
opposite of the under-dispersion these notes have assumed since day one.
That assumption should be treated as retired at this prefix.

WHAT THIS SETTLES ABOUT THE HOOK MODEL. A full behavioural model of removal
— fitted to real decisions from play-by-play, replacing the hand-specified
logistic and the two stale offset files — is defensible as REALISM and as
infrastructure for anything that depends on which arm is on the mound
(reliever props, inherited runners, role effects). It must NOT be budgeted
as a prediction improvement. Three framings say that branch has nothing to
give, and a fourth is unlikely to differ.

TTO IS THE EXCEPTION AND IS WORTH KEEPING. It is the only mechanism today
that produced a resolved improvement on real outcomes: F1 signed error
+0.070 -> +0.005, a -1.8 sigma paired gain in absolute error, which is the
largest anything moved. It slightly over-suppresses through F3 (+0.033 ->
-0.082); that is a level effect for the refit to absorb, since the seven
fitted parameters predate TTO entirely.

## The CLV record, moved out of CLAUDE.md

These numbers used to sit at the top of `CLAUDE.md`, which is loaded into
every session. Their prominence there WAS the problem: the always-loaded
brief described the project in market terms, so session after session began
by treating agreement with Kalshi as the objective, and the plan that says
otherwise (`AF_PLAN.md`) was not referenced from it at all. Kept here as the
record.

    Against the CLOSING price on strikeouts the model adds NOTHING
      (t = -0.15).
    Against the OPENING price it adds a lot (+32.9%, 73.2% direction).
    On FIRST FIVE INNINGS totals, the same shape and a comparable edge:
      beats the open (20.5% vs 19.3% Brier skill), loses to the close,
      CLV z +31.4, 67.1% direction, +3.9 cents on five-cent disagreements
      over 2,149 settled contracts.

Read them alongside the two findings that reframe what they mean:

**The edge is one month.** June +1.8c, July +1.7c, August +3.3c, season
+2.4c. August reproduces the record; the other months run at half of it, and
six explanations for the difference were tested and eliminated.

**And the edge is not baseball knowledge.** Our RESOLUTION is LOWER than the
OPENING price's in July (0.0728 vs 0.0787) and August (0.0833 vs 0.0856)
while we still beat the open on CLV. So the model anticipates where the
price MOVES without being more accurate about the GAME. That is a different
product from the one `AF_PLAN.md` commits to, and it is fragile — it depends
on Kalshi's opening behaviour rather than on baseball, which is also the
best remaining explanation for the August anomaly.

## THE LEARNED REMOVAL MODEL — the hook, done properly at last

`src/context/removal.py`. Per-decision logistic on 86k starter plate
appearances from play-by-play, target = "replaced before the next batter
this side faces". Beats the shipped hook by a wide margin on a DATE holdout
(rows within a start are not independent, so a random split leaks):

    model                            AUC    log loss
    learned model                 0.9123     0.1168
    shipped sim.Hook              0.8755     0.1592

Wired in behind `game.USE_LEARNED_HOOK`. It subsumes BOTH hook branches —
the target spans the inning boundary, so one roll per plate appearance
replaces `mid_removal_p` and `removal_p` together. Relievers keep
`relief.mid_removal`, measured on relief outings specifically.

Coefficients are persisted to `removal_model.json` as plain numbers, so the
simulator needs no sklearn at run time; prediction is a dot product.
`numpy` and `scikit-learn` are now declared in `requirements.txt` — they
were being imported undeclared by `sources/archetype.py`, which would have
crashed a fresh install.

### What it says the hook actually is

    pitches   +1.974        pitches ALONE as a ranker:  AUC 0.9014
    bf        +1.115        the full model:             AUC 0.9143
    outs      +0.591
    inning    -0.487
    br        -0.329
    onbase    +0.200
    damage    +0.160
    bb_pct    +0.160
    tto       -0.126
    quality   -0.081
    runs      +0.075

**IT IS A WORKLOAD RULE.** Pitch count alone reaches AUC 0.901; traffic,
damage, runs, TTO, pitcher quality and all thirty clubs together add
+0.013. Managers pull starters on pitch count and batters faced, and the
game situation is a rounding error on top.

**RUNS RANK 11th OF 14.** Confirmed independently by the refit, which halved
`per_run` 0.6 -> 0.3 and moved nothing else. Two methods, different data,
same answer: the old hook over-weighted runs.

**CLUB EFFECTS ARE WORTH +0.002 AUC.** 0.9143 with all thirty, 0.9123
without; whole spread 0.21 in standardised log-odds, sd 0.053. Dropped from
the shipped model. That is the FIFTH independent finding that team-specific
hook effects do not pay, and the first from a per-decision test.

### The negative `br` coefficient is arithmetic, not baseball

Cumulative baserunners comes out NEGATIVE, which reads as "traffic protects
you". It does not. `bf` is approximately outs recorded plus baserunners, so
holding `bf` fixed, more baserunners means FEWER OUTS, which means less deep
into the game, which means less likely to be pulled.

    drop nothing        br -0.338   AUC 0.9123
    drop pitches        br -0.331   AUC 0.9029
    drop bf             br -0.030   AUC 0.9113
    drop pitches + bf   br +0.424   AUC 0.8979

And br vs pitches is POSITIVELY correlated (+0.78 across rows, +0.47 across
whole starts) — both are cumulative counters. On its own `br` ranks at AUC
0.853; it is a fine signal that is almost entirely redundant with workload.

### OPEN: early hooks are a different event

The model is fitted on all 86k decisions at a 4.6% base rate, so it is
overwhelmingly fitting the ordinary case around 90 pitches. An early hook —
gone by the fourth — has different causes and is the case the model is least
likely to price well. Chase Burns on 2026-08-24 went 3.2 innings; the sim
put "pulled during the 4th" at 6.5%. Worth fitting separately, or at minimum
checking calibration in that region, before trusting the tail.

---

## DAY SEVEN — two hooks, a bug that hid inside one of them, and deGrom

### The starter was never offered a hook at an inning boundary

Found by looking at a simulated starter-length distribution instead of its
mean. `_half_inning` breaks out of its loop when the third out lands and the
break sits BEFORE the removal block; `_end_of_inning` returns early whenever
the learned hook is on, on the stated grounds that the per-PA roll already
spans the boundary. It does not — the boundary plate appearance is the one
the break skips. Instrumented: 72,426 hook calls across 2,000 games, all at
outs 0/1/2, never at a boundary.

Real appearances end on a completed inning 64.1% of the time (16,623
pitcher-games). The simulator managed 7.6%. Means were right, which is
exactly why it survived every aggregate check ever run against it — and why
anything priced at a specific outs line was wrong, since books hang their
lines at 15.5/17.5/18.5, right on the spikes the sim did not have.

Fixed, 7.6% -> 34.6%. The gap that remains is the argument for two models.

### A mid-inning hook and a boundary hook are different decisions

3,995 starter removals over 2,006 games: BOUNDARY 63.2%, MID 36.8%.

    state at removal   pitches  outs  cum runs  THIS inn runs  THIS inn br
    boundary              83.3  16.6      2.15           0.48         1.33
    mid-inning            82.6  14.3      2.72           0.84         2.20

PITCH COUNT DOES NOT DISTINGUISH THEM — 83.3 against 82.6 — while it carries
the largest coefficient in the shipped model. It is a pure "is he done"
signal, which is the boundary decision only. What separates them is damage
in the CURRENT inning, a quantity no feature in the shipped model carries.

The interaction, and the clearest signal measured in this project:

    P(mid | pulled)     0 runs   1 run  2 runs      3+
      innings 1-3        33.0%   27.8%   38.8%   61.6%
      innings 4-5        28.6%   37.6%   44.9%   46.4%
      inning 6           32.7%   51.7%   58.7%   60.5%
      inning 7+          33.6%   57.8%   72.7%       -

Through a clean inning the inning number does not matter at all. Allow runs
and it climbs steeply. Leash moderates it: long-leash starters take 43.1% on
2+ runs against 56.9% for short-leash, monotone across terciles, same
ordering by K-BB%.

### What the split is and is NOT worth

Refit like for like, same rows, same 2026-07-15 holdout:

    shipped features                    AUC 0.9361   log loss 0.1028
    + leash and K-BB%                   AUC 0.9409   log loss 0.1003
    + current-inning traffic            AUC 0.9463   log loss 0.0972
    split, combined                     AUC 0.9460   log loss 0.0986
    pooled + full ends_inning interaction  AUC 0.9468   log loss 0.0966

THE SPLIT BUYS NOTHING ON DISCRIMINATION. +0.0005 AUC. What buys the gain is
the FEATURES — current-inning traffic and leash.

The case for two models is therefore not AUC, it is the BASE RATES: boundary
removals fire at 6.30% and mid-inning at 2.83%, a 2.2x gap that a single
hazard function cannot express because it applies the same probability at
both decision points. That is a claim about where distribution mass lands,
testable on the outs distribution and not on AUC.

Two cautions before building it. The boundary fit looks collinear — `bf`
+4.548 against `br` -1.336, largely cancelling. And 6.30/2.83 is pooled over
all starters; `advance.py`'s per-club stability gate is the precedent for
checking it holds up before conditioning on it.

### The prefix ladder is the wrong instrument for this

1,615 games, paired, common random numbers, |sigma| <= 1.1 at every prefix.
Expected: the ladder scores TOTAL RUNS, and moving a hook from mid-inning to
a boundary swaps a starter for a reliever who is his equal in aggregate
(K-BB 0.1333 against 0.1358). It changes who throws, not how many score.
The starter's own line is what changes and what has to be scored.

### OPEN, and being tracked — JACOB deGROM

He is not the pitcher he was in the first half and the model has no way to
know it. His last 7 starts against his first 17:

                  BF     K%    BB%   BABIP   outs/BF   p/out   under 16.5
    first 17     382   .301   .052    .255      .751    5.31        5/17
    last 7       141   .298   .085    .407      .660    6.38         6/7

THE STUFF IS INTACT AND THE COMMAND IS NOT. K% is identical. Walks are up
63% and BABIP has gone from .255 to .407, so every non-strikeout plate
appearance turns into traffic, he burns 6.4 pitches per out instead of 5.3,
and he runs out at 15 outs instead of 18. Season rates hide all of it.

Re-simulated on last-7 rates: under 16.5 outs 0.412 -> 0.501, against his own
7/14 and a market at 0.490.

WHAT WAS TESTED AND WHAT WAS NOT. Recency in the LEASH — a trailing-5 mean
of outs per start, in place of the season mean — is a wash (MID 0.9422 vs
0.9418, BOUNDARY 0.9449 vs 0.9440). That does NOT address deGrom, whose case
is about his RATES, not about how long his manager lets him go. Recency in
the rates has only ever been scored against the MARKET (`recency.py`, dead at
3-5 sigma), which is the wrong yardstick by THE OBJECTIVE. It has never been
scored on the prefix ladder or on outs CRPS against actual outcomes.

That is the pre-registered re-opening: recency-weighted rates, scored on
outcomes, with the decomposition above as the hypothesis — the moving parts
are BB% and BABIP, not K%, so a single half-life over all four rates is
probably the wrong shape and per-rate half-lives are worth testing. Note
`stabilise.py` already measured how fast each rate becomes trustworthy, and
BABIP is the slowest of the four; .407 over ~90 balls in play regresses hard.

### Also fixed: Kalshi prop lookups were matching the wrong player

`price_prop` matched on ANY shared name token, so a pitcher Kalshi does not
list at the requested strike fell through the whole series to the first
market sharing a FIRST name. "Tyler Glasnow" under 6.5 K priced off Tyler
Phillips of Miami and reported Kalshi fair at 0.920 against a true 0.595.
`names_match` now requires the surname. `find_settled` is the CLV path, so
recorded prop CLV numbers may carry some of this.

---

## DAY SEVEN, AFTERNOON — the pooled hook fit, and what it cost

### The learned hook was replaced, and the note justifying it was false

`USE_LEARNED_HOOK` swapped `sim.Hook`'s two branches for one roll per plate
appearance. The comment in `game.py` said the model's target "spans the
inning boundary, so one roll per plate appearance covers what
`mid_removal_p` and `removal_p` did separately."

It does not. `_half_inning` breaks out of its loop on the third out BEFORE
the roll happens, so the inning-ending plate appearance never got a decision
at all — 72,426 instrumented hook calls across 2,000 games, every one at
outs 0/1/2. The premise was false when it was written and nothing caught it,
because the model was validated on removal-decision AUC (0.9123 against
0.8755) while what it silently discarded was a fitted, verified calibration:

    ends on inning boundary    actual 66.7%    sim.Hook 66.9%

`calibrate.loss` has always targeted the boundary share. The learned model
was scored on a different quantity and the shape went with it — 7.6% of
starts finishing on a completed inning against a league 64.1%.

BOTH ARE NOW OFF. `USE_LEARNED_HOOK = False`, and `_boundary_roll` — the fix
for the missing boundary decision — is dead code behind it. THE +4.7 SIGMA
OUTS-CRPS RESULT RECORDED THIS MORNING APPLIES ONLY TO THE LEARNED-HOOK
CONFIGURATION AND IS NOT A CLAIM ABOUT THE SHIPPED MODEL.

### The pooled fit was wrong late, and that was the big one

One mid-inning hazard fitted over all 47,687 decisions. 26,693 of those are
innings 1-3 where the real pull rate is 0.65%, so they dominate by count and
the late curve came out far too flat:

    90+ pitches, mid-inning     real 33.80%     pooled hook 7.24%

Nobody got yanked mid-inning late, everyone survived to the boundary, and
the boundary share reached 90.7% in the eighth against a real 54.1%.

Refit on the 20,994 late decisions alone, with its OWN coefficients rather
than the pitch curve shared with the boundary hook:

                     mean    sd   boundary     loss
    ACTUAL          15.70  3.99      65.7%
    before          16.05  4.43      70.3%  0.20626
    after           16.00  3.95      66.0%  0.04730

Loss falls 4.4x. Outs SD and boundary share both land — the two figures that
had resisted every other change.

### The boundary-share error was NOT uniform, and checking that mattered

The aggregate gap was 4 points and the obvious fix was a shared intercept
shift. Broken down it is not a level error at all:

    inning     actual    sim      gap
    1           79.8%    2.6%   -77.3%
    5           66.5%   67.2%    +0.7%
    8           54.1%   90.5%   +36.4%

The 4-point aggregate is the average of a -77 and a +36. One knob moves both
ends together and fixes neither. Two parameters against 3,995 counted
removals is not overfitting in the usual sense — the risk was COMPENSATING
ERROR, and splitting the cells is what tells them apart.

### Early innings are a different decision, and it is the BOUNDARY branch

Real removals in the first inning are 79.8% boundary. The simulator produced
2.6%, because BOTH hooks carry a pitch-count veto — at 30 pitches the term
is -3.3 log-odds (-6.3 under the tuned parameters) and nothing overcomes it.
With both silent early, every early removal was forced through the mid-inning
path, which is the branch reality barely uses.

The isolated early hazard, measured under 60 pitches where workload is not
the reason anybody moves:

    runs this inning     0      1      2      3     4+
    P(pulled)         0.32%  0.43%  1.26%  1.74%  5.59%

A LEAST-SQUARES SLOPE THROUGH THOSE POINTS IS THE WRONG SHAPE. The hazard is
flat from nought to one and then climbs; a line charges +0.724 log-odds at
one run where the truth is +0.296, and one-run innings are 11x more common
than four-run ones. Fitting five counted points is the move this project
forbids and it was made anyway.

Both branches now exist (`early_innings`) and SHIP SWITCHED OFF. They fix
the tail almost exactly — sub-two-inning starts 0.31% -> 3.16% against a real
2.68% — but widen the outs SD to 4.47 where reality is 3.99. The tail miss
is left standing rather than bought with spread.

### What the tail actually is

Starts under four innings are 11.0% of the total and carry 49.6% of the
variance in starter length. Excluding them, SD falls 3.96 -> 2.83. So the
distribution is bimodal — bombed out early, or four innings and up — and the
middle is genuinely rare. Two things follow that were each wrong on the first
guess:

  * IT IS NOT THE SCORING MODEL. The simulator produces 4+ run innings at
    1.68% against a real 1.38% — slightly MORE. The disaster innings happen;
    the manager does not react.
  * IT IS NOT PER-PITCHER LEASH VARIATION. Between-pitcher spread in mean
    pitch count is 5.1 with a 10th-90th of 82-94, and the apparent variation
    in TIGHTNESS is blowups: within-pitcher pitch SD runs 4.6-21.3 over all
    starts and 3.7-13.0 over five-inning ones. Kochanowicz 19.8 -> 6.9,
    Lopez 19.4 -> 3.8. There is no meaningful no-wall population to model.

### Pitch count does not mean the same thing in every inning

    P(pulled)      inn 2    inn 3    inn 4    inn 5    inn 6
    45-59 pitches   3.76%    0.83%    0.37%    0.17%    1.01%
    60-74               -    6.01%    2.22%    1.62%    3.04%
    75-89               -        -   12.30%    8.23%    8.95%

70 pitches in the third is pulled 3.7x more often than 70 in the fifth. The
model treats them identically. PITCHES PER INNING DOES NOT CAPTURE THIS —
tried, and it is non-monotone (1.68% at under 13, peaking at 4.77% at 19-21,
back to 3.14% at 26+) against a monotone 75x span for raw pitch count. High
pitches-per-inning early means FEW total pitches, so it folds back on itself.

What an inning costs in pitches, by how it went: 9.9 clean, 14.5 at one run,
18.1 at two, 21.5 at three, 25.8 at four-plus. A blowup inning is worth about
1.6 ordinary ones, so a bad second puts a starter roughly where he would
otherwise be after the fourth.

### FORM: within-start out rate does NOT persist

3,268 (first pass -> rest of start) pairs, baseline from the pitcher's OTHER
starts so nothing leaks:

    1st-pass OUT RATE -> rest OUT RATE    +0.0019    0.1 sigma
    1st-pass BB%      -> rest BB%         +0.0014    0.1
    1st-pass K%       -> rest K%          +0.1114    6.4

There is no "he is getting hit tonight" state carrying forward. Form as a
source of clustered traffic is DEAD. Note this contradicts the parked
`form.py`, which found damage predicting next-pass RUNS at 4.7 sigma —
different target, and runs are the lagging indicator.

STRIKEOUT RATE DOES PERSIST, at 6.4 sigma. Whether he has the swing-and-miss
tonight carries; contact outcomes do not. That is the mirror image of the
BETWEEN-start result, where K% is the weak one and BB%/BABIP are strong.
Unused so far and it bears directly on strikeout props.

### Four wiring mistakes in one change, all caught by the suite

Recorded because the pattern is the point, not the individual errors.
`pitch_center`/`pitch_scale` are shared between the two hooks, so refitting
them for one silently refit the other. Layering `mid_per_runner` and
`mid_per_damage` on top of a fit that already contained the traffic
double-counted it — 53% where the measurement says 34%. `late_mid_intercept`
was absolute, which breaks every caller that disables the hook by driving
`mid_intercept` to -99, and that exact bug had been fixed in the early branch
hours earlier. And the feature list omitted bases occupied entirely.

A branch carrying its own ABSOLUTE intercept is the recurring one. Carry
offsets from the shared intercept, always.

### The suite tested every measurement and none of the wiring

Sixteen mutations, one shipped constant each. Nine caught, seven survived,
five of those real: measured advancement, measured inherited runners, the
hard pitch cap, measured relief length and the mid-inning relief hook could
each be switched off with all 307 checks green.

`test_advance` has 16 checks, `test_relief` 10, `test_inherit` 8. They test
that the COUNTING CODE COUNTS CORRECTLY. Nothing tested that the simulator
uses the numbers — which is the gap both of the day's real bugs fell
through, the boundary hook that was never called and the early branch fitted
on baserunners allowed then wired to bases occupied.

`tests/test_wiring.py` covers it, and it needs TWO KINDS OF CHECK that do
not substitute for each other:

  * flip the flag, assert the OUTPUT moves — catches wiring rotting behind
    a flag that still reads True
  * pin the shipped DEFAULT — catches the flag being flipped

The first kind sets the flag itself in both directions, so a mutation of the
default is invisible to it. All 313 stayed green against exactly that.

### `USE_MEASURED_INHERITED` is dead in the full-game engine

`_leave` is reached only from `simulate_start`. `game.py` hands the base-out
state to the reliever and plays the runners out for real, which is strictly
better. Measured, the flag changes `simulate_game` by exactly nothing —
8.56 against 8.56. IT RETIRES WITH THE START-LEVEL LOOP; no port needed.

Its pooled effect is nil by construction anyway: 0.312 measured against a
flat 0.330, so cells differing sixfold cancel in the mean (1.975 runs
against 1.978 over 800 starts). Any check on it has to go at the CELL —
third base nobody out, 0.771 against 0.330 — not the aggregate.

### The mutation harness corrupted the source, and how

A two-minute timeout SIGKILLed it between mutating and restoring, leaving
USE_MEASURED_INHERITED false in `sim.py`. The next run then copied the
ALREADY-MUTATED file as its backup and faithfully restored that, cementing
it. Backups now live outside the tree, the tree must be clean before a sweep
starts, and restoration is registered with atexit and the terminating
signals — the clean-tree precondition being the real guard, since SIGKILL
cannot be caught. Blast radius was nil, but by luck rather than design.

### Where the model stands at the end of day seven

    3,248 real starts        outs CRPS   whole-inning   mean outs
    morning                     2.2199          9.5%       16.39
    after the boundary fix      2.1608         34.5%       15.44
    end of day                  2.1505         66.3%       16.00
    ACTUAL                                      65.7%       15.70

`calibrate.loss` 0.20626 -> 0.04730. Outs SD 4.43 -> 3.95 against a real
3.99. Boundary share 70.3% -> 66.0% against a real 65.7%.

LARGEST REMAINING MISFIT: starts of 12-14 outs, 19.4% against a real 16.6%.
That is 4.0-4.2 innings, which is where books hang outs lines. Untouched.

### The distributions are CALIBRATED but nearly UNRESOLVED — and the ceiling is tiny

Prompted by an eye-test on six blind re-simulations: "our distributions are
too wide, we aren't getting any resolution around the likely numbers."

WIDTH IS RIGHT. Probability integral transform over 500 games — where the
actual total lands inside the predicted distribution — comes out uniform:

    prefix   middle half (uniform 50%)   outer tenths (uniform 20%)
    F3               54.6%                       20.8%
    F5               50.2%                       18.4%
    F7               47.8%                       21.0%

RESOLUTION IS THE REAL ISSUE, and PIT cannot see it. A model handing every
game the same distribution, centred correctly, produces perfectly uniform
PITs and is useless for choosing between games.

    prefix   our spread   implied true   share   corr w/ actual
    F3          0.32          0.39        83%        0.160
    F5          0.47          0.79        60%        0.205
    F7          0.56          0.69        81%        0.166

'our spread' is the sd of our per-game predicted means; 'implied true' is
sqrt(var(actual) - mean within-game var), i.e. how much game-to-game
variation really exists.

BUT THE CEILING IS ALMOST NOTHING. With between-game sd 0.69 against a total
sd of 3.67, a PERFECT forecaster correlates 0.188 with actual game totals.
About 96% of the variance in a game total is within-game randomness no model
can touch.

    prefix   our corr   theoretical max   share of the ceiling
    F3         0.160         0.165                 97%
    F5         0.205         0.251                 82%
    F7         0.166         0.188                 88%

So the simulator already captures 82-97% of what is capturable on game
totals. The predictions look samey because GAMES ARE SAMEY IN EXPECTATION —
a perfect model would range about 6.5 to 9.5 runs, not 3 to 15.

TWO CONSEQUENCES.

It reframes the "0-for-everything" list. Handedness, park, day/night and
arsenal are exactly the features that DIFFERENTIATE games rather than shift
the level, and the differentiable share of a game total is about 4% of its
variance. A real effect of that size cannot show up against this target
however well it is implemented. That is not proof they work — it is a reason
the null was uninformative.

And it argues for spending effort where the signal is. A starter's outs or
strikeouts carry far more of their variance in the pitcher's own rates than
a team's run total ever will. The stated product is team totals; the
measurable edge may not be there.

---

# Day eight — between-game differences, and the per-pitcher leash

The session question was the user's: the model over-generalises on the
aggregate, so where does between-game variance come from and how do we
measure it? Target chosen deliberately — STARTER OUTS, as the most stable
and least flukey of the props.

## The ceiling estimator failed first, and the failure was informative

`scratchpad/ceiling.py` decomposes `var(actual) = var(true per-start mean)
+ E[within-start var]` and takes the within term from our own simulation.
On 3,600 real starts it reported an outs ceiling of 0.250 with us at 105%
of it. A correlation cannot exceed its own ceiling, so the estimator was
broken, and the reason is written into the module's own docstring as the
thing to distrust: our within-start spread on outs is 3.84 against a real
3.50. THE SIMULATOR IS OVER-DISPERSED PER START, and subtracting a
too-large within understates the between.

The fix is to stop using the model at all. `scratchpad/between.py` runs a
one-way ANOVA on the ACTUAL values grouped by pitcher, `(MSB - MSW)/n0` so
sampling noise is removed rather than counted as talent. What sits BETWEEN
pitchers is real start-to-start variation by construction, and it is a
LOWER bound because opponent, park and rest all vary inside a pitcher's own
season too:

    stat  actual sd  between  within  our within  our spread  share
    outs       3.96     1.77    3.50        3.84        0.57    32%
    k          2.44     1.10    2.17        2.03        1.02    93%
    h          2.23     0.67    2.12        1.96        0.45    67%
    bb         1.30     0.39    1.24        1.28        0.39   100%
    er         1.99     0.41    1.94        1.78        0.29    71%

**OUTS IS THE OUTLIER AND IT IS NOT CLOSE.** Every other quantity produces
67-100% of the differentiation that provably exists. Outs produces 32%.
Strikeouts, the other thing books hang on a starter, are essentially
exhausted at 93%.

## The user's reframing, which is the better metric

Mid-session: *"when we talk about bets we are talking about finding
medians, so a way to conceive of how well we are capturing between-game
difference is how much the median value moves compared to the aggregate."*

That is right and it is sharper than the spread of predicted means, because
a bet settles on a THRESHOLD. `ceiling.py --lines` now reports, per line,
the sd of our P(over) across starts — which IS the Brier resolution term —
against what the same simulator would produce if it differentiated starts
as much as reality does. It made the problem far more legible: on outs our
per-start median took only EIGHT distinct values and sd(p) at 15.5 was
0.060, meaning essentially every start was priced at the base rate.

## What is missing is a LEASH, and all five columns say so together

Leave-one-out per-pitcher residual — the group mean recomputed EXCLUDING
the target start, so no effect scores zero rather than the negative
artifact that leave-nothing-out manufactures:

    outs +0.295*   k +0.008   h +0.063*   bb -0.086*   er +0.012  (*|z|>3)

The pitcher's rates are estimated over his own season, so his per-batter
performance is right by construction — and the columns agree: no stable
per-pitcher residual on strikeouts, walks, hits or earned runs. Only OUTS
carries one. The single thing outs depends on that the other four do not is
the manager. That is a leash, and it is the only reading consistent with
the whole row rather than one cell of it.

## EVERY OTHER BETWEEN-GAME FEATURE MEASURED NULL, directly

On the outs residual, over 3,600 starts:

    is_home +0.005   night game +0.019   park runs index -0.032
    days rest +0.014   pen outs yesterday +0.037   pen outs last two +0.009
    month +0.039

None worth more than 0.15 outs against 1.77 of real between-start
variation. So the answer to "do we have park effects" is: yes, `park.py`
serves them, and on this target they are worth nothing — measured against
the residual directly rather than inferred from a game-total null. This is
a much cheaper test than building a feature and re-simulating, and it
should be the first thing run on any future between-game candidate.

`predicted outs` correlates +0.123 (z 7.4) with its OWN residual. That is a
CONTROL firing and it says something specific: our predictions are
COMPRESSED, not mis-directed. The fix is to differentiate more, not to add
an input.

## The club is dead for the SIXTH time, and its split-half is a trap

The chronological split-half on the CLUB outs residual reads r +0.595,
which passes the bullpen-role gate (+0.55..+0.78) that this project trusts.
It is wrong. It measures which ARMS a club runs out, not how patient its
manager is, and the pitcher offset already has that.

Fitted in the correct order — club first, pitcher against the remainder,
the rule `calibrate --patience` exists to enforce — a club offset is worth
+0.090 -> +0.122 out of sample ALONE, and ON TOP of the pitcher offset it
makes things WORSE (+0.234 -> +0.227, MAE up). `sim.USE_PATIENCE` stays
False. Note that fitting the two in the other order would have credited the
manager with the whole thing.

## It is NOT the blowups — the day-six claim, tested

RESUME recorded that per-pitcher leash variation is "mostly blowups, not
real". Rebuilt from a 20% TRIMMED mean of prior residuals the gain is
IDENTICAL (+0.354 against +0.354 for the plain mean); from the prior
MEDIAN, +0.336. A statistic that throws away his worst starts predicts just
as well, so it is a central tendency and not a tail.

## THE OPENERS, and the honest size of this

The short-leash end of the built file is entirely relievers pinned at the
sweep boundary — PJ Poulin, Lake Bachar, Wandy Peralta, Bryan Hudson.
`ROTATION_MIN_GS = 5` admits openers and bulk arms, and they were being
simulated with a starter's hook. Fixing that is real and worth having, but
it is not the interesting claim, so it was separated out:

    holdout, live starts     base corr   +leash   RMSE base   RMSE leash
    all                          0.075    0.268       3.831        3.697
    median outs >= 12            0.077    0.182       3.613        3.550
    median outs >= 15            0.051    0.099       3.591        3.555

**MOST OF THE HEADLINE GAIN IS OPENERS.** On genuine rotation arms the
effect is smaller and still real — the correlation more than doubles and
RMSE falls 0.063 — and the true per-pitcher leash sd among rotation arms is
about 0.9-1.1 outs rather than the 1.77 that includes openers. Anyone
quoting this number should quote the rotation-only row.

## Out of sample, through the shipped code path

Rates estimated before 2026-07-01, leash file built `--before 2026-07-01`,
scored on the 1,125 starts after it:

                     OFF      ON
    outs spread     0.56    1.29
    outs corr      0.105   0.226     (model-free ceiling 0.294-0.318)
    of ceiling       33%     71%
    sd(p) @ 15.5   0.060   0.127     <- the Brier resolution term, doubled
    distinct medians   8      17

Every downstream quantity improves as well — k +0.389 -> +0.408, h +0.207
-> +0.235, er +0.044 -> +0.063. That is the coherence argument for ONE
simulator, stated in numbers for the first time: a starter left in for the
right length accumulates the right number of everything else.

The prefix ladder is neutral, as designed: F7 d|err| +0.0015 at +0.4 sigma
over 1,615 paired games. A hook change is invisible to a run total because
starters and relievers are equal in aggregate here, so this was a
no-regression test and it passed.

## THE WIRING GAP — the most important find of the day

The FIRST paired ladder printed EXACTLY +0.0000 at F1, F3, F5 and F7 over
1,615 games. That is not "the ladder cannot see a hook change", which is
true and expected and is written in RESUME. It was the flag not arriving.

`game.build_side` never called `sim.for_start`. Every caller passes
`hook=None`, which fell through to a bare league `Hook()` — so the club and
per-pitcher offsets reached `sim.simulate_start` and NEVER REACHED A FULL
GAME. The start-level path is what `calibrate`, `quote`, `price` and `f5`
sit on; the engine that produces TEAM TOTALS, which is the stated product,
ran without any per-start hook at all.

**AN IDENTICAL-TO-FOUR-DECIMALS A/B IS A PLUMBING RESULT, NEVER A NULL.**
Two model states that agree to four decimals over 1,615 games are the same
model. This is the second time in two days that a mechanism turned out not
to be reaching the simulator, and both times the tell was in the output.

Guarded by `check_the_leash_reaches_a_full_game_and_not_only_a_start` in
`tests/test_wiring.py`, mutation-verified: the mutated run reproduces the
exact `(15.4125, 15.4125)` signature.

## Measured, not tuned — the two constants that could have been searched

Shrinkage K is `within_var / between_var` read off the ANOVA, which is the
normal-normal posterior mean, and it is RECOMPUTED from whatever window
`build()` is given rather than baked in. Handing it to a grid is what would
turn this from a measurement into a fit, and a fitted shrinkage absorbs
whatever else is wrong with the hook.

The outs-to-log-odds conversion is INTERPOLATED through a measured sweep
(`scratchpad/offset_map.py`, 900 starts x 60 draws at eleven offsets), not
regressed onto a slope. The curve bends — -2.0 buys +3.00 outs where the
local slope at zero promises +3.36 — and fitting a line through counted
points is the mistake recorded against the advance-on-out hazard, where a
least-squares slope charged +0.724 at one run against a counted +0.296.

The sweep also confirms the knob moves a start's LEVEL without inflating
its own spread: outs sd 4.10 at -0.6, 4.00 at 0.0, 3.83 at +1.0. A
mechanism that bought differentiation by widening every start would show up
here and would not be worth having.

## A SEVENTH CHECK THAT GUARDED NOTHING

`check_the_offset_never_leaves_the_measured_sweep` asserted the clamp
against `OFFSET_CLAMP` itself and passed just as happily with the constant
mutated to 99.0. Self-referential, and only a mutation run surfaces it.
Rewritten to bound against the measured table's own endpoints.

## A trap for the next session

`hook_leash.json` as committed is built on the FULL season. That makes it
correct for pricing tomorrow's games and WRONG for scoring this season's:
a pitcher's offset was measured partly on the very starts any in-sample
replay would score. `calibrate --reliability`, `ceiling.py` and
`score_leash_outs` all become flattered. Rebuild with `--before <cutoff>`
and score after it, which is what every number above did.

## DAY EIGHT, PART TWO — the engine was not simulating real games

Prompted by the user's question, which is the whole lesson: *"how are you
setting up the sides for these simulations? this matters."* Two defects, both
in the inputs rather than the model, both invisible to every aggregate.

### 1. Every pitcher was facing his own teammates

`build_cases` attaches to each start the nine that pitcher FACES, so the away
start already carries the HOME club's batters. `ladder` and the new
`calibrate.replay` both handed the away PITCHING side the other lineup.
Verified on names: Ryan Feltner of Colorado simulated against Brett Sullivan,
Connor Norby and Jake McCarthy — Colorado's own hitters.

It survived because both sides still got a real major-league nine, so run
level, outs distribution, boundary share and pitchers per side all looked
right. WHAT IT DESTROYS IS THE MATCHUP, which is the only thing that
differentiates one game from another.

INVALIDATES every full-game number: the prefix ladder including "the model
runs 5% light", the day-seven resolution finding and the 0.19 game-total
ceiling, `score_outs`, the dispersion work, the blind-game dashboard.

### 2. Not one lineup in 574 was the right nine in the right order

`opposing_lineups` had no batting-order column — the boxscore cache carries
at-bats and nothing else — so it sorted by AB descending and took the top
nine. Against play-by-play:

    exact match (right nine, right order)      0.0%
    lineups with at least one wrong batter    23.5%
    mean slot error                            2.30

Three stacked defects. At-bats EXCLUDE walks, so a high-OBP leadoff man
sorts below a free swinger. A pinch hitter with two at-bats displaces a
starter pulled early. And a club that bats around hands its leadoff man five
at-bats, so the "input" is partly a function of the result — leakage into a
quantity the model treats as known beforehand.

The order is not cosmetic: the simulator wraps the lineup and derives times
through the order from batters faced, and TTO is a MEASURED 19% swing in
strikeout rate between the first pass and the third. A 2.3-slot error
assigns that penalty to roughly the wrong third of the lineup.

Fixed by `src/context/order.py` — the first nine distinct batters in a
half-inning ARE the order, and the play-by-play has been cached since day
four. 1,956 games, 97% coverage. The at-bat proxy survives only as the
fallback for the rest.

### WHY THIS MATTERS MORE THAN ANY MECHANISM ON THE LIST

Every feature on the dead list — park, handedness, day/night, opponent
quality — is a BETWEEN-GAME feature, and every one was tested on an engine
where the opponent was the wrong club batting in an arbitrary order in a
park the simulator was never told about (`simulate_game` accepts a park
argument and every caller passed None). THOSE WERE NOT NULL RESULTS, THEY
WERE BROKEN TESTS. The dead list needs re-running, not defending.

### THE DIAGNOSTIC TO KEEP

AN AGGREGATE THAT LOOKS RIGHT IS NOT EVIDENCE THE INPUTS ARE RIGHT. Both
defects preserved every summary statistic this project tracks. What catches
them is asserting on NAMES — structural checks that a pitcher does not face
his own club, that a lineup follows the play sequence. Three of the six new
checks initially guarded nothing and were caught by mutation: two set the
flag they were testing, one asserted "nine distinct names" without checking
the sequence.

---

# Day nine — the one-sided engine is deleted

`sim.simulate_start` and `sim.simulate` are gone. So is `f5.py`, the
`engine="stub"` branch in `f5_market`, the input-uncertainty block
(`DRAW_RATES`, `HOOK_SIGMA`, the Beta posterior draws) and `_leave` with
`INHERITED_SCORE_RATE`, `INHERITED_SCORE_BY_STATE` and
`USE_MEASURED_INHERITED`.

## What went, and why each thing went with it rather than being ported

**The driver, not the state machine.** `pa_outcome`, `apply_pa`,
`baserunning` and `Hook` were always shared — they were extracted precisely
so the two engines could not drift. What was duplicated is the loop around
them, and that loop is what could not see a bullpen, an opposing offence or
a margin. `Hook.per_margin` and `mid_per_margin` were structurally
unreachable on it and sat at 0.0 forever.

**The inherited-runner constants were a fudge FOR that loop.** A start that
stops the instant the hook fires has to settle the runners it leaves behind
somehow, so it flipped a coin at 0.33 — later at a base-out table counted on
5,507 real handovers. `game.py` hands the state to the reliever and plays
them out. Measured before the deletion: with the flag ON and OFF, the
full-game engine gave EXACTLY the same answer, 8.56 against 8.56, because it
never consulted the constant at all. The MEASUREMENT in `inherit.py` stays
and is still the thing to check the simulator against; the constant does not.

**The input-uncertainty block is on the dead list** ("input-uncertainty
propagation") and both knobs shipped off. It hung off `simulate` and had
nowhere left to hang.

## Both starters or neither — the rule the migration adopted

`price` and `quote` priced ONE pitcher through `sim.simulate`. They now
simulate the whole game and read `away_sp` / `home_sp` off the same
`GameResult`, which is CHEAPER than what it replaced: two pitchers, one
matchup, one set of draws instead of two. `versus_market` and `recency` go
through `cal.paired_cases` + `cal.replay`, the route `f5_market` already
used.

The tempting shortcut is a league-average stand-in for a missing opposing
starter. It is refused everywhere: **inventing the other club invents the
score**, and the score is what the hook, the bullpen and the margin are
conditioned on, so the number would look exactly like every other number and
rest on a pitcher who is not in the game. `paired_cases` already drops about
10% of starts for this reason and that is the price of scoring on the engine
the product uses.

## THE COST, STATED PLAINLY: a full game is ~20x a one-sided start

1,000 fixture starts take 1.33s where the old loop did ~15k/sec. That is
both sides, a real bullpen, nine innings and extras. `make test` went 70s ->
95s; `scratchpad/seymour.py` went from 40,000 draws to 20,000. Nothing is
wrong — this is what simulating a game costs, and the old number was cheap
because it was not simulating one.

A second-order consequence worth knowing: **a never-pulled starter now
throws extra innings.** `check_errors_raise_the_run_level` asserted
`outs == 27` and had to become `outs >= 27`. The old loop capped at
`max_innings`; a real game does not.

## `tests/fixtures.py`, and the boundary around it

About 40 checks used `simulate_start` as a harness for the plate-appearance
model — does a home run clear the bases, do errors raise the run level, does
a leash offset lengthen the start. They now go through `fixtures.one_side`,
which builds two real `game.Side`s and calls `game.simulate_game`. It walks
no plate appearance of its own; it is a fixture builder, not an engine.

It MIRRORS the pitching side against itself, which is the one thing
production may never do. `check_nothing_prices_through_the_fixtures` walks
`src/` with `ast` and fails if anything there imports `tests`. Without it
the cheapest fix for a missing opposing starter is to reach for the mirror.

Evidence the fixture actually reaches the engine, which is the trap this
project keeps hitting: mutating `build_side` to drop the hook it is handed
fails four checks (`team_offset_lengthens_or_shortens_outings`,
`a_leash_offset_actually_lengthens_the_start`,
`longer_leash_raises_strikeout_totals`, `errors_raise_the_run_level`). A
harness that reached nothing would have passed all of them.

## Checks added, all mutation-verified

    check_input_uncertainty_stayed_deleted        re-add DRAW_RATES -> fails
    check_the_inherited_runner_fudge_stayed_...   re-add the constant -> fails
    check_inherited_runners_are_played_out_...    make _advance ignore the
                                                  bases -> loaded == clean
    check_nothing_prices_through_the_fixtures     import fx in price -> fails
    check_a_missing_opposing_starter_declines...  league-average fallback ->
                                                  fails
    check_both_starters_come_out_of_one_...       starter_line returns away_sp
                                                  for both sides -> fails

The first two are inverted checks — they assert a mechanism is ABSENT. That
is the right shape for a measured-harmful mechanism that shipped switched on
once already: the guard is against it coming back by accident, not against
its value drifting.

## NOTHING HERE HAS BEEN RE-SCORED

No number in `RESUME.md` moved. Four modules changed engine — `price`,
`quote`, `versus_market`, `recency` — so every CLV figure recorded for them
was produced on a loop with no bullpen after the hook, no margin term and no
opposing offence. The change is not expected to be neutral and has not been
measured. That is the first thing to establish, and it is cheap for
`versus_market` because the settled contracts are cached.

## Day nine, second pass — three optimisations, and a check that was luck

`build_side` was 22% OF A SIMULATED GAME (115us against 1,037us) and runs
twice per draw. Two things it did were waste, and both fixes are
bit-identical — same fingerprint over 3,000 games on outs, k, bb, h, hr,
runs, earned and pitches, and the same sampled bullpens:

  * the weight list was rebuilt from scratch on EVERY pick, eight passes
    over thirty dicts to draw eight arms. Built once and popped alongside
    the pool, `rng.choices` gets identical arguments in identical order.
  * the same thirty bullpen dicts were turned into fresh `PitcherRates`
    objects on every draw. Cached on the row, which is safe now that
    nothing mutates a `PitcherRates` — `_jitter_pitcher` was the only thing
    that did and it went with the one-sided engine.

115us -> 43us, and the production-shaped path (a game WITH a real bullpen)
1.268ms -> 1.127ms, an 11% cut. `price.simulate_slate_game` also hoists the
hook out of the per-draw loop: it is the same for every draw of a fixed
matchup, while the BULLPEN must stay per-draw because which arms are
available is a real source of spread.

**A PREDICTED OPTIMISATION THAT MEASURED ZERO, recorded because the reasoning
was wrong in an instructive way.** `pa_outcome` built a whole `PitcherRates`
per plate appearance to scale four floats, and the estimate was ~76 of them
per game. It is ~23: relievers are passed `tto=None`, so `tto_mult` returns
None and nothing is allocated for them. Removing it is still correct — it
was pointless work — but it bought nothing measurable, and the error was
counting plate appearances instead of checking which ones take the branch.

## A WIRING CHECK THAT WAS PASSING ON LUCK

`check_measured_advancement_reaches_the_run_level` asserted that flipping
`USE_MEASURED_ADVANCEMENT` moved the run level by more than 0.02 over 600
starts. Measured properly the flag is worth about 0.05 runs a start (2.4040
on against 2.4550 off, n=3,000) and runs per start have an sd near 2.0, so
the standard error on that difference was roughly twice the effect. It read
2.3817 against 2.3800 and failed.

RUNS PER BASERUNNER DID NOT RESCUE IT, which is worth recording because the
standing rule says to prefer a high-n ratio to a low-n aggregate. Across
n = 400 / 600 / 1000 it came out -3.8% / +0.1% / +4.3% — the sign flips. The
rule earned its place on ~17,500 simulated starts; at a few hundred the
ratio is as noisy as the mean, because runs within one start are correlated
and the baserunner count is not an independent sample.

So the check now asserts the two halves separately, at high signal and low
cost: that the engine CONSULTS `_advance` (instrumented, one real game,
20+ calls) and that the flag CHANGES what `_advance` does (20,000 rolls of
one base-out state where the measured and published tables differ by 14%).
Both mutation-verified — freezing the table selection to the measured branch
fails the second, stubbing the engine's calls fails the first.

THE GENERAL POINT: a wiring check does not need the mechanism's real effect
size to be resolvable. It needs to prove the flag reaches the code. Asking
it to also demonstrate the effect on the settled quantity is what made it
underpowered, and an underpowered check that passes is indistinguishable
from one that guards something.

## Day nine — the CLV record, re-measured on the shipped engine

Every recorded claim about what our disagreements are worth was produced on
`sim.simulate`, deleted this morning. All of it was re-run through
`scratchpad/remeasure.py`, which forks `versus_market.collect` over dates.
August 1-25, n_sims=1500.

**K PROPS: THE CONCLUSION HOLDS, on 3,366 markets against the recorded
1,220.** Market Brier 0.1576 (+36.0% over base, AUC 0.847), sim 0.1636
(+33.6%, AUC 0.836) — 94% of the market's skill, inside the recorded 91-98%
band. Best blend weight 0.00: our gap adds nothing to a price that exists.

**ONE SUB-CLAIM DOES NOT HOLD, and `quote.py` prints it.** "Where the two
agree within 5 cents the simulator is a shade better than Kalshi (0.1351
against 0.1379)" is now false — the market is marginally better in EVERY
band (0.1407 against 0.1424 inside five cents). The direction of the big-gap
finding is unchanged and stronger: at 20+ cents the sim is right 21.9% of
the time and its Brier is double the market's.

**OUTS LOOKED ALIVE AND IT WAS LEAKAGE.** With the shipped full-season
`hook_leash.json` the outs board scored sim Brier 0.2388 against the
market's 0.2403, AUC 0.627 against 0.602, and a best blend weight of 0.50
worth +1.21%. That would have been the first thing to beat a settled price.
It is in-sample: the leash was fitted on the full season and August is
inside it. Rebuilt `--before 2026-08-01` and re-scored:

    leash                       sim Brier  vs base    AUC   best lam
    full season (IN-SAMPLE)        0.2388    +4.5%  0.627   0.50
    before Aug 1, ungated          0.2506    -0.3%  0.555   0.00
    before Aug 1, intent-gated     0.2466    +1.3%  0.571   0.10

Outs is still the dead half. K was re-run at each step as a control and did
not move, so nothing systemic changed between the states.

## THE LEASH POPULATION — openers were half the signal

`calibrate.ROTATION_MIN_GS` asks "did he start five times", and an opener
who opened five times clears it. Nine of the eleven offsets that pinned at
the +/-2.0 clamp on the first two-sided rebuild were openers and bulk
relievers — Wandy Peralta, five "starts" in fifty-three appearances,
averaging three outs, carrying a leash offset.

USER'S FRAMING, and it is the right definition: what the leash measures is
how long a pitcher WHO WAS MEANT TO GO LONG actually lasts. An opener's
three outs are not a short leash, they are the plan. They dilute the real
signal, which is the starter sent out for six who gets shelled in the
second.

`leash.intended_starters` gates on that, and the effect is large:

                            ungated   gated
    offsets                     212     202
    between-pitcher sd        1.803   0.900
    shrinkage K (starts)        3.7    14.8
    offset range              +2.00   +1.19
    pinned at the clamp          11       0

OPENERS WERE HALF THE APPARENT BETWEEN-PITCHER VARIATION. The clamp stopped
binding — the grid-edge diagnostic clearing, which is what it does when a
missing mechanism is supplied — and the surviving 0.90 outs lands exactly on
the number day eight predicted from the other direction ("on genuine
rotation arms the true per-pitcher leash sd is ~0.9-1.1 rather than 1.77").

**THE GATE READS A PERCENTILE, NOT A MEAN, and the reason is worth keeping.**
Screening on mean outs would SELECT ON THE DEPENDENT VARIABLE: this module
measures how long a starter lasts, and a mean-based cut removes exactly the
arms that were sent out for six and got shelled. `price.priceable` screens
on mean outs and is right to — it answers a different question, whether to
put a number on a bet. Measured, the two populations do not overlap on p75
(openers 3-9, shelled starters 14-18) and any cut from 10 to 13 separates
them cleanly.

HONEST FOOTNOTE: the user pushed back that no real starter averages under 11
outs anyway, and the data agrees — the two gates disagree on 6 arms of 241,
all of them 3-4 start callups whose offsets shrink to nothing regardless. So
the percentile form is the safer statement of the rule and buys nothing
today. The synthetic fixture that motivated it was not checked against the
real distribution first, which it should have been.

`MIN_PRIOR` 3 -> 5. At three, a callup with two bad outings reads as a short
leash when it is really no evidence (Cody Bolton [3, 7, 13], Kendry Rojas
[6, 7, 12, 12]). Costs 22 arms and 2.5% of the starts, and mostly keeps them
out of `shrink_k`.

## TWO TRAPS ADDED

**A SCORING FILE AND A PRICING FILE ARE DIFFERENT FILES.** `--before` builds
the leash for SCORING a window; the shipped file must be full-season or
every offset ignores the most recent month. The working tree carried a
`--before 2026-08-01` build for a while today and would have priced with it.

**VERIFY THE MUTATION LANDED, not just that you wrote one.** A mutation
meant to disable shrinkage reported the check as unguarded. The insertion
had silently gone somewhere ineffective; re-applied properly, the check
caught it immediately. The standing rule is "write the mutation before
believing the check" — it needs "and confirm the mutation is in the file".

## A CHECK WHOSE PREMISE INVERTED

`check_the_leash_covers_thin_starters_not_just_established_ones` asserted
`MIN_PRIOR <= 3`, because a low bar was the only thing keeping short-outing
arms off the league default leash — COVERAGE WAS DOING A FILTER'S JOB. With
`intended_starters` doing that job on role, a low bar buys nothing and costs
something. Rewritten to guard SHRINKAGE instead: a pitcher at the floor must
keep under half his raw residual, and the floor must not creep past 8.

## Day nine — are K and outs the same quantity? No, and the coupling is right

The suspicion was that because `K = batters faced x K rate`, our strikeouts
are just our length wearing a different name, and the two need separating.
Measured (`scratchpad/kvsouts.py`), on arms meant to go long:

    ACTUAL     n=3,570   mean outs 15.88  mean K 4.92  corr +0.429
    SIMULATED  n=64,420  mean outs 16.12  mean K 4.89  corr +0.418

    outs      share A  share S   E[K] A  E[K] S    diff   sd A   sd S
    0-8          3.5%     2.3%     1.97    2.25   +0.28   1.30   1.39
    9-11         6.1%     7.9%     3.14    3.24   +0.09   1.61   1.63
    12-14       16.9%    19.4%     4.12    4.08   -0.04   1.84   1.86
    15-17       34.2%    28.6%     4.86    4.86   -0.00   2.18   2.07
    18-20       27.8%    25.3%     5.50    5.53   +0.03   2.35   2.23
    21-27       11.4%    16.4%     6.70    6.08   -0.62   2.69   2.40

THE COUPLING IS NOT THE DEFECT. The correlation matches to 0.011 and
E[K | outs] is right to 0.04 strikeouts across 12-20 outs, which is 73% of
starts and where every line sits. Reality couples them too — more batters
faced, more strikeouts — and the counter-force is already modelled, since
`PITCH_COST` charges 4.97 pitches for a strikeout against 3.25 for an out.
Separating them would make the model less right.

WHAT IS WRONG IS THE OUTS MARGINAL. Read the `share` columns: 16.4% of our
starts reach 21+ outs against a real 11.4%, and 28.6% land at 15-17 against
a real 34.2%. We simulate too many seven-inning starts and too few
five-inning ones — the same misfit as the recorded "12-14 out bucket". K
inherits it exactly, so fixing length pays twice.

TWO SMALLER FINDINGS. In 21+ out starts we give 6.08 K against a real 6.70:
real long starts are EARNED by missing bats, ours are too available to
contact pitchers. And conditional on length our K is slightly UNDER-dispersed
in the long buckets (2.07 against 2.18, 2.23 against 2.35, 2.40 against
2.69), which is what a missing per-start K% state looks like.

## THE HEADROOM, MEASURED LIKE FOR LIKE

`scratchpad/headroom.py`. Holdout: rates frozen before 2026-07-01, scored on
the 927 starts after it, leash OFF (it is fitted full-season and leaks the
same way). Ceiling is the model-free ANOVA on ACTUALS, between_sd/total_sd.

    stat   actual sd  between  ceiling  our corr  share  our spread
    outs        3.83     1.39    0.363     0.121    33%        0.89
    k           2.48     1.18    0.475     0.384    81%        1.02

**K IS AT 81%, NOT EXHAUSTED.** About +0.09 of correlation is available.
This CORRECTS the day-eight note that "strikeouts are at 93% and essentially
exhausted" and an in-session claim that K was already at its ceiling — both
compared an in-sample correlation against a clean ceiling.

**THE FIRST VERSION OF THIS MEASUREMENT LEAKED AND SAID SO OUT LOUD.** Run
with `paired_cases()` and no cutoff, a pitcher's season rates include the
start being predicted, and it reported K at 112% OF A PERFECT FORECASTER'S
CEILING. A share above 100% is the useful kind of impossible — it is a leak
announcing itself, and it is worth building measurements whose failure mode
is out of bounds rather than merely optimistic.

**AIM, NOT AMOUNT, ON K.** Our K spread is 1.02 against a real between-start
1.18 — we already produce 86% of the differentiation that exists, while
capturing 81% of the ceiling. So K is not short of spread; some of it points
at the wrong games. That is an input-quality problem. Outs is the opposite
at 64%, a genuine missing mechanism — and the market nobody beats anyway.

## WITHIN-START K% PERSISTENCE IS NOT A PRICING SIGNAL

Recorded as "+6.4 sigma, unused, and it bears directly on strikeout props",
and it was proposed this session as the K-specific mechanism to build. It is
not one. The measurement is 1st-pass K% -> REST-OF-START K%: it is observed
only once the game is under way. Pregame it says a per-start K% state exists
without saying which way tonight, so wiring it in widens the distribution
and does not move its centre — which is `DRAW_RATES`, measured harmful, and
cannot close a correlation gap in any case.

It is a LIVE-betting signal. Its pregame use is as evidence for the
under-dispersion in E[K | outs] above, which is a shape correction and not a
resolution one.

## Day nine — pitch efficiency screened, and what it actually found

Screened after a hand analysis of the same two slates named "pitch
efficiency (pitches per out)" as THE most predictive input for outs props —
Gray 4.74, Boyd 4.87, Dobnak 6.1 — and `sim.PITCH_COST` charges the same
league table to every pitcher. `scratchpad/tempo.py`.

**IT DOES NOT PASS ITS GATE, AND THE REASON IS THE INTERESTING PART.**
Pitches per out is (pitches per PA) / (outs per PA), and the denominator is
TRAFFIC — which the simulator already generates from a pitcher's own K%,
BB% and BABIP. A per-pitcher pitches-per-out multiplier would count the same
thing twice. The quantity to screen is the residual against his own outcome
mix, which is tempo proper: deep counts and foul balls.

    raw pitches per out          split-half r  +0.348
    outcome-mix residual         split-half r  +0.207

THE RESIDUAL PERSISTS WORSE THAN THE RAW RATIO, which is the signature of a
signal that is mostly the part you already model. Its spread is +/-3% on
pitch cost, shrinking to about +/-1.8% or ~0.3 outs, against a per-pitcher
leash already worth 0.90 — below the bar and overlapping it.

Worth recording that the overlap is real and large: corr(pitch efficiency,
leash offset) is +0.552, and Tatsuya Imai is both the least efficient arm
(6.54 pitches per out) and the largest short-leash offset. The leash has
been fitting this blind. But once traffic is removed there is not much left
for a separate mechanism to own.

## WHAT THE SCREEN FOUND INSTEAD — a LEVEL error, 6% light

    pitches per out    real 5.47   simulated 5.14    -6.1%
    spread (sd)        real 0.334  simulated 0.185    55% produced
    K per batter faced real 0.2149 simulated 0.2141   (not the cause)

The ratio needs no batters-faced denominator, so it survives any accounting
quibble about reached-on-error. **Our starts retire a hitter every 5.14
pitches where real ones take 5.47.** At a 92-pitch hook that is 17.9 outs
against 16.8, and the direction matches the marginal defect measured the
same day — too many 21+ out starts (16.4% against a real 11.4%), too few at
15-17 (28.6% against 34.2%).

CAUTION BEFORE ANYONE "FIXES" IT BY RAISING `PITCH_COST`. The hook is fitted
against the outs distribution, so it has been absorbing this: a pitch cost
that is too low with a threshold pulled in to compensate reproduces the mean
and distorts the shape. Raising the cost without refitting the hook will
move the level twice. This is the compensation pattern the notes keep
recording, and the honest fix is to re-measure `PITCH_COST` against the
play-by-play and refit the hook in the same commit.

`PITCH_COST` was last measured per PLATE APPEARANCE (3.94 billed against a
real 3.839) and corrected. Per OUT it has never been checked, and per out is
the quantity the hook actually integrates over.

## Day nine — the same error for a flamethrower and a contact starter?

`scratchpad/bytype.py`. Terciles by the pitcher's own season K per batter
faced, so the grouping is a property of the arm rather than of the start
being scored. Different question from `sources/archetype.py`, which typed by
PITCH MIX and asked whether type predicts performance; this asks whether the
model's own ERROR is homogeneous, because every defect measured today was
reported as a single number over all starters.

    group              arms   K/BF   outs A  outs S     d   p/out A  p/out S      d
    contact (low K)      62  0.162    15.62   15.96 +0.34     5.38     5.09  -5.5%
    middle               62  0.209    15.88   16.09 +0.21     5.41     5.14  -5.1%
    power (high K)       62  0.269    16.31   16.45 +0.14     5.38     5.14  -4.4%

    group           K/start A  K/start S     d    21+ out starts (A / S)
    contact              3.79       3.92 +0.12     9.2% / 15.9%
    middle               4.82       4.81 -0.01    11.6% / 16.2%
    power                6.15       5.92 -0.22    14.3% / 18.1%

**PITCH EFFICIENCY IS FLAT ACROSS TYPES** (-5.5 / -5.1 / -4.4%), so it is a
global constant and a global fix is the right shape. Note the REAL numbers
barely move by type either — 5.38 / 5.41 / 5.38. A strikeout costs more
pitches but converts reliably; a ball in play is cheap and often retires
nobody. They wash, and the simulator reproduces that correctly.

**THE OUTS MARGINAL IS FLAT TOO.** Every group over-produces 21+ out starts
and under-produces 15-17, slightly worse for contact arms. Global; the hook.

**THE K ERROR IS NOT FLAT, AND THAT IS THE FINDING.** Contact +0.12, middle
-0.01, power -0.22 — monotone. Part is the outs gradient, but converting to
K per batter faced leaves +3.2% on contact arms and -2.7% on power arms.
About 6% of RATE COMPRESSION across the type range: pitcher K% is
OVER-SHRUNK toward the league.

It agrees with the headroom result from the same day arrived at another way
— our K spread is 1.02 against a real between-start 1.18, 86%, and this is
85% of the between-type range. So "K's shortfall is aim, not amount", stated
earlier the same day, is half wrong: some of it is amount, and the mechanism
is shrinkage rather than a missing feature.

`stabilise.py` measures exactly this and has already found batter rates
over-shrunk 2.2x and pitcher HR under-shrunk 2.7x. Pitcher K% is the next
one to re-measure, and unlike a new mechanism it is a constant that is
already fitted — no new machinery, and it moves the quantity with the most
headroom (K, 81% of ceiling).

## Day nine — `int(round(PITCH_COST))` was throwing the calibration away

Chasing the 6% pitches-per-out deficit to its cause. The decomposition is
BF-free — everything per start, on arms meant to go long:

                    real      sim     diff
    outs           15.88    16.10    +1.4%
    K               4.92     4.88    -0.7%
    BB              1.84     1.85    +0.6%
    H               4.94     4.87    -1.4%
    HR              0.72     0.73    +2.0%
    baserunners     7.00     6.94    -0.9%
    pitches        86.82    82.60    -4.9%   <-

THE OUTCOME MIX IS RIGHT TO WITHIN 2% ON EVERYTHING. Only pitches are wrong,
so it is neither the run model nor the measured constants. `apply_pa` did:

    r.pitches += int(round(PITCH_COST[o]))

An out on contact costs 3.25 and was billed 3. A walk costs 5.48 and was
billed 5. Those are the two commonest outcomes in the game, rounded the same
way about 23 times a start. The out term alone is 2.8 pitches; the whole
rounding is 3.3 of the 4.2-pitch shortfall.

**THE TABLE WAS NEVER WRONG.** Applied to the real outcome mix it predicts
86.9 pitches a start against a real 86.82. A measured constant, correct to
two decimals, discarded at the point of use.

WHY IT MATTERED BEYOND PITCH COUNT: the hook integrates over pitch count, so
under-billing made every starter last too long. Fixed:

    pitches per out       5.14 -> 5.34   (real 5.47), level -6.1% -> -2.3%
    spread produced        55% -> 61%
    mean outs            16.12 -> 15.72  (real 15.88)
    starts at 21+ outs   16.4% -> 12.9%  (real 11.4%)

E[K | outs] is untouched and still exact through 12-20 outs, and
corr(outs, K) holds at +0.419 against a real +0.429.

WHAT IT DID NOT FIX is the SHAPE. The mass moved into 12-14 (now 21.0%
against a real 16.9%) rather than into 15-17 (30.1% against 34.2%). That is
the hook's fitted parameters, and they have never been refitted against this
engine — `intercept`, `pitch_center`, `pitch_scale` and `mid_intercept` all
trace to the commit that created the simulator, fitted against
`sim.simulate` AND against the rounded pitch counts. The refit now has a
correct input underneath it, which is the right order: fixing the input
after the fit would have moved the level twice.

TWO CHECKS ADDED, both mutation-verified, because 333 existing checks missed
this. One asserts the ARITHMETIC — fifty outs cost fifty times 3.25, not
fifty times 3 — rather than a simulated total, which is noisy where the
defect is exact. The other asserts the table reproduces the real per-start
pitch count from the real outcome mix, which would have caught it from the
other side.

THE GENERAL LESSON, and it is a new one for this project: every trap
recorded so far is about a constant being WRONG, or a mechanism not being
REACHED. This is a constant that was right and reached, and destroyed in
transit. Measuring a value and wiring it in is not sufficient; the units
have to survive the arithmetic.

## Day nine — `calibrate.run(hook=...)` was passing it nowhere

Found by the recorded diagnostic, third time it has paid. A full parallel
coordinate descent over ten hook parameters, two sweeps, 1,090 starts x 40
draws, returned NOT ONE PARAMETER MOVED and a loss identical to five decimal
places. An identical-to-many-decimals A/B is a plumbing result, never a null.

`run` accepted `hook`, documented it in its docstring, and passed it
nowhere. `replay` did not take a hook at all, so both sides were built with
`hook=None` and fell through to a bare league `Hook()`. Proven cruder than
the loss:

    shipped hook          mean outs 15.54
    NEVER pull            mean outs 15.54
    pull IMMEDIATELY      mean outs 15.54

After the fix: 15.54 / 26.44 / 0.82.

**SO `calibrate.tune` HAS BEEN INCAPABLE OF TUNING SINCE THE DAY-EIGHT
MIGRATION TO `replay`.** Any hook fit attempted in that window was scoring
one hook against itself. The shipped parameters were never affected, because
nothing could change them — they still trace to the commit that created the
simulator.

Guarded by `check_the_hook_argument_reaches_the_replayed_game`, asserted with
a never-pull and a pull-immediately hook so it tests the WIRING and cannot
fail for a tuning reason. Mutation-verified, and the failure message is the
signature: `(14.794117647058824, 14.794117647058824)`.

THE PATTERN, now four times in this project: measured advancement, measured
inherited runners, the per-pitcher leash, and now the hook argument. A
mechanism is built and tested, the wiring is not, and the symptom is always
a result that is TOO CLEAN. `tests/test_wiring.py` exists for exactly this
and it keeps earning its place.

## `scratchpad/tune_hook.py` — the tuner, parallel and honest about spread

`calibrate.tune` is serial and samples 500 of 3,248 starts. Coordinate
descent is sequential ACROSS parameters but the values within one parameter's
sweep are independent, so they fork — 488s for two full sweeps at 1,200
starts and 40 draws.

It prints SD at every accepted step. `calibrate.loss` does not weight
spread, so an optimiser pointed at it will compress the outs distribution to
buy the hazard curve and the boundary share, and we are ALREADY 8% narrow
(3.79 against a real 4.13). SD is deliberately not added to the objective —
the hook may still be compensating for something else — but a fit that buys
loss with spread is now visible instead of silently shipped.

`calibrate.loss` and not `fitf5` is the right objective for the hook, per
CLAUDE.md's own line: do not fit the hook against the SETTLEMENT VALUE;
fitting it to real removal DECISIONS is a different thing. `loss` targets
the observed hazard curve, the boundary share and the shares at >=18 / <15 /
>=21 outs.

## Day nine — fitting the boundary curve alone makes the SIM worse

The hook is two curves on two populations. Day seven fitted the MID-INNING
one directly as a logistic on its own rows (`late_mid_offset`,
`late_mid_per_pitch`, `late_mid_per_inning_br` are those coefficients). The
BOUNDARY one never got the same treatment. `scratchpad/fit_boundary.py` does
it, and the shipped form is already a logistic so no search is involved:

    logit = intercept + (pitches - pitch_center)/pitch_scale
            + per_run*runs + per_baserunner*br + per_inning*innings
            + per_margin*margin

38,485 real end-of-inning decisions, pull rate 0.0657, in-sample AUC 0.8925.
`pitch_center` and `intercept` are not separately identified, so
`pitch_center` is PINNED at the mean pitch count of a boundary decision and
the intercept solved from it — otherwise it drifts to an arbitrary partner
of the intercept, which is how it landed on a grid edge in the pooled sweep.

THE SHIPPED CURVE IS FAR TOO EAGER, which the fit exposes plainly:

    pitches       n   actual  shipped   fitted
    60-70      4362    0.029    0.137    0.051
    70-80      3927    0.074    0.293    0.114
    80-90      3212    0.218    0.488    0.231
    90-100     1775    0.504    0.679    0.406
    100-110     371    0.749    0.799    0.596

AND THE FITTED CURVE MAKES THE SIMULATED DISTRIBUTION WORSE:

                          loss    mean     sd   bndry    <15   >=18   >=21
    shipped            0.06265   15.64   3.79   0.643  0.329  0.360  0.118
    fitted boundary    0.08193   16.50   3.79   0.479  0.275  0.426  0.158
    ACTUAL                       15.78   4.13   0.663  0.271  0.406  0.119

**THE TWO CURVES COMPETE FOR THE SAME EXITS.** A boundary curve that stops
over-pulling leaves starters in to face more batters, and every extra batter
is another mid-inning chance — so correcting one curve in isolation hands
its exits to the other and the MIX collapses (boundary share 0.643 -> 0.479
against a measured 0.663). The mid-inning curve was fitted on day seven
against decisions generated under the OLD, too-eager boundary curve, so the
pair is only jointly consistent as it stands.

THE FINDING, and it is a new shape for this project: PER-DECISION
CALIBRATION DOES NOT IMPLY DISTRIBUTIONAL CALIBRATION when two coupled
curves share the state. Each can match its own observed hazard while the
simulated mix is wrong. Day seven's lesson was do not POOL two populations;
this one is do not fit them INDEPENDENTLY either. They have to be fitted
together and validated on the simulated boundary share, which is a joint
problem and not two separate ones.

NOTHING SHIPPED. The shipped hook is worse per-decision and better
distributionally, and until the pair is fitted jointly that trade is not
ours to make one side of.

## Day nine — the joint fit, and what actually blocks the hook

`scratchpad/joint_hook.py`. Boundary curve held at its per-decision fit,
mid-inning curve rescaled on three parameters, objective `calibrate.loss`
plus an explicit boundary-share term at weight 4 (the share is what broke,
and `loss` weights it 1 against a hazard block at 4).

                          obj     loss    mean     sd   bndry
    shipped           0.06429  0.06265   15.64   3.79   0.643
    + fitted boundary 0.21765  0.08193   16.50   3.79   0.479
    JOINT best        0.20491  0.17862   17.19   3.84   0.582
    ACTUAL                              15.78   4.13   0.663

IT WENT THE WRONG WAY AND THAT IS THE FINDING. To restore the share the fit
cut mid-inning pulls (`late_mid_offset` -7.97 -> -8.8), which lifted the
share 0.479 -> 0.582 and pushed mean outs to 17.19 against a real 15.78,
with the loss more than doubling.

**THE SHIPPED BOUNDARY CURVE'S OVER-EAGERNESS IS COMPENSATING FOR STARTERS
WHO WOULD OTHERWISE LAST TOO LONG.** It fires at 0.293 where reality is
0.074 — indefensible per decision — and the shipped hook still lands mean
outs at 15.64 against 15.78. Replace it with the honest curve and the mean
goes to 16.50. There is no setting of the two curves that fixes the mix
without breaking the mean, because the error is not in the curves.

WHAT IT IS. Pitches per out is 5.34 against a real 5.47, still 2.3% light
after the rounding fix closed the first 3.8 points. Pitches per PA is now
right, so the residual is the DENOMINATOR: outs per plate appearance runs
1.4% high, i.e. we retire slightly too many batters, i.e. slightly too few
baserunners. That is the oldest defect on the list — "the sim is 0.13 runs
light per side", recorded on day six and surviving measured advancement,
measured inherited runners, TTO and the new shrinkage.

SO THE HOOK IS BLOCKED ON THE RUN MODEL, not on the fitting method. The
method is now right and is reporting that its input is wrong. Two curves,
each correctly fitted to real decisions, each making the simulation worse,
is the signature of a downstream rule that has been absorbing an upstream
error — and the standing rule says a worse score after a correct measurement
LOCATES the compensation rather than licensing a revert.

THE ORDER OF WORK THAT FOLLOWS. Fix the traffic deficit first; refit the two
curves jointly after. Refitting now would only re-absorb the same error into
differently-wrong parameters. Nothing shipped: `sim.Hook` is untouched, and
the shipped hook remains the best available on the distribution while being
the worst on the decisions.

## Day nine — SHIPPED: the fitted boundary curve, on a value-weighted call

Reversed the decision recorded two sections above, and the reason is the
important part. The refusal rested on `calibrate.loss`, the mean and the
boundary share — a weighted sum whose weights were never chosen to match
what settles a bet. Nobody bets the boundary share. It is a diagnostic that
the hook has the right SHAPE, which is an upstream proxy, and CLAUDE.md's
central line is fit the quantity that settles, not the upstream proxy.

Scored on P(over) at real outs lines instead:

    line     ACTUAL  shipped   fitted   ship err  fit err
    12.5      0.807    0.761    0.841     -0.047   +0.034
    13.5      0.771    0.727    0.796     -0.043   +0.026
    14.5      0.729    0.671    0.725     -0.058   -0.004
    15.5      0.542    0.475    0.590     -0.067   +0.047
    16.5      0.472    0.427    0.518     -0.045   +0.046
    17.5      0.406    0.360    0.426     -0.045   +0.021
    18.5      0.172    0.190    0.285     +0.019   +0.114
    20.5      0.119    0.118    0.158     -0.001   +0.039

    RMS 14.5-17.5    0.0546 -> 0.0346      (-37%)
    RMS 12.5-20.5    0.0452 -> 0.0513

**THE OLD CURVE'S ERROR WAS A BIAS, NOT NOISE** — negative at every line
from 12.5 to 17.5, systematically under-pricing the over where the board
actually is. The aggregate favours it only through 18.5 and 20.5, six-plus
innings, which is the thin end.

WHAT GOT WORSE AND WHY IT WAS ACCEPTED: mean outs 15.64 -> 16.50 (real
15.78), boundary share 0.643 -> 0.479 (real 0.663), `calibrate.loss` 0.0627
-> 0.0819. None of the three is a bet. The mean and the share are
diagnostics of the compensation described in the previous section — outs per
plate appearance runs 1.4% high — and the standing rule is that a measured
value scoring worse LOCATES the compensation rather than refuting itself.

`sim.LEGACY_BOUNDARY` holds the old values so the change stays separately
scoreable, the same shape as `LEGACY_ADVANCEMENT`.

STILL WRONG, and it is the next fix: the logit is linear in pitches while
the real hazard accelerates past 90, so the fitted curve undershoots the
tail (0.596 against a real 0.749 at 100-110). That is exactly where the
+0.114 at the 18.5 line comes from.

### Two checks whose premise inverted with it

`per_inning` fitted to -0.109, and two checks asserted that a later inning
at a FIXED pitch count raises P(pulled). It does not, and that is defensible
baseball rather than a concession: a man in the 7th on 90 pitches has been
more efficient than one in the 5th on 90. Inning and pitch count carry the
same information and the fit gives it to pitches. MARGINALLY the hazard
still climbs 0.013 / 0.043 / 0.131 / 0.287 / 0.375 across innings three to
seven, because pitch count climbs with the inning — so both assertions moved
to a realistic joint step. Same treatment as
`check_advancement_rises_with_the_out_count`, which weakened a strict ladder
that turned out to be a property of the published references.

### THE LESSON, and it generalises past the hook

WE HAD BEEN TREATING EVERY NUMBER AS EQUALLY VALUABLE. `calibrate.loss` sums
a hazard block, a mean, a boundary share and three out-shares, and a change
that improves one and degrades another reads as no improvement. But we do
not care about them equally: 14-18 outs is where the board is, and anything
outside it is a line nobody bets. The same question is now open for
strikeouts — which K lines carry the volume — and the answer should shape
how K accuracy is scored too.

## Day nine — the two cheap hook leads, both eliminated

### Lead 2, the mid-inning refit: DEAD, and the premise was wrong

The hypothesis was that its day-seven coefficients were calibrated against a
state distribution the OLD boundary curve produced, and so were stale once
that curve was replaced. False: it was fitted to REAL decisions from
play-by-play, and real decisions do not depend on what our boundary curve
does. `scratchpad/fit_midinning.py`, 47,716 mid-inning decisions:

    bucket        n   actual  shipped   refit
    0-60      32497   0.0047   0.0012  0.0038
    60-70      5121   0.0201   0.0157  0.0304
    70-80      4675   0.0445   0.0456  0.0640
    80-90      3568   0.1132   0.1238  0.1325
    90-100     1603   0.3019   0.2869  0.2524
    100+        252   0.5635   0.5502  0.4456

The SHIPPED curve tracks the real hazard closely everywhere; the refit is
worse at five of six buckets. It needs nothing.

AND THE REFIT FAILED FOR A REASON I HAD ALREADY RE-DISCOVERED TWICE TODAY: I
pooled early and late rows. 32,497 of 47,716 sit under 60 pitches and swamp
the fit, so the curve came out flat exactly where removals happen. Day seven
fitted this curve late-only for precisely that reason. Third time in one
session that a population day seven separated got re-pooled.

### Restricting the BOUNDARY training set: worse, and the asymmetry is the point

The boundary curve I shipped has the same pooling defect — it undershoots
the tail, 0.596 against a real 0.749 at 100-110. Refitting it on restricted
rows fixes the hazard and breaks the simulation:

    candidate                mean    sd   bndry   RMS 14.5-17.5
    shipped (pooled fit)    16.49  3.80   0.480          0.0342
    trained pitches>=60     16.72  3.61   0.473          0.0576
    trained inning>=4       16.74  3.60   0.473          0.0615
    LEGACY (pre-today)      15.64  3.79   0.643          0.0546
    ACTUAL                  15.78  4.13   0.663

**THE BOUNDARY CURVE IS EVALUATED AT EVERY PITCH COUNT AND THE MID-INNING
CURVE IS NOT.** Calibrating the boundary curve on 60+ only makes it
under-pull early, so more starters survive to reach the tail and the mean
gets WORSE even though the tail probability is now right. For the mid-inning
curve, under-pulling early is harmless because the boundary curve does the
early work. For the boundary curve there is nothing underneath it.

So "fit each curve on its own population" is not universal advice. It holds
for a curve that only fires in part of the range and fails for one that
fires across all of it.

### What is actually left

The tail undershoot is a limitation of the FUNCTIONAL FORM, not of the
training rows: the logit is linear in pitches and the real hazard
accelerates past 90. No choice of training set fixes that. It needs a
non-linear pitch term, which is a code change rather than a refit.

The pooled boundary fit shipped today remains the best available in the
current form — band RMS 0.0342 against LEGACY's 0.0546 over the lines that
are 91.2% of the settled outs board.

## History supersedes typing, and the earlier measurements said so

USER, end of day nine: "adding more data for pitcher history probably does
what we were trying to do with typifying ... it gives the pitcher a baseline
tendency."

That is right and it retires a line of work rather than opening one. Typing
was always a stand-in for not having enough of the man himself: you group
pitchers who look alike because 40 batters faced will not support an
estimate. His own 180 innings from last season is the same borrowing from a
strictly better source.

Two results from this session already pointed at it and were not connected:

  * `bytype.py` split starters by strikeout rate and found the model's
    defects are GLOBAL. The groups were not behaving differently, so there
    was nothing for a type to capture.
  * `archetype.py` found pitch-mix typing real for relievers (p=0.003) and
    ABSENT for starters — the population that actually gets priced.

CORRECTED SAME DAY, after the user pushed back: that second bullet does NOT
say pitch mix is irrelevant to starters, and citing it that way conflates
two questions. Archetype asked whether arsenals form CLUSTERS, and its own
result is that they cluster for nobody — silhouette 0.121, decaying as k
rises, a continuum on the simplex. Starters simply throw too similarly to
each other to be sorted into types. The MATCHUP question was tested
separately as arsenal multipliers and is dead on its own evidence, 9.79%
Brier skill with and without.

AND THAT MATCHUP TEST IS RE-OPENABLE. Arsenal, mixture, handedness and
head-to-head were all scored against the two-engine setup on half a season,
and all four flags are False. The dead list records HOW a thing was tried,
and both the approach and the data have since changed. The specific thread
to pull is already in these notes: arsenal improved EVERY high-K line
(k 7.5 +0.67pp, AUC 0.813 -> 0.822) while low-K lines and outs slipped.
That was correctly called below the noise floor. It now fits the day-nine
result that strikeouts respond to better inputs and outs are immune to them,
so re-run it PRE-REGISTERED on K alone at n_sims >= 400.

It is also the trap already written into `sim.for_pitcher`: a group number
standing in for an individual is substitution bias. The standing rule is
shrink toward a prior and keep the underlying value; `rates.set_prior` just
supplies a much sharper prior to shrink toward.

WHERE TYPING KEEPS A CLAIM, both untested:

  1. A TRUE ROOKIE has no history to borrow from and his pitch mix is
     available from Savant on day one. Same small population where the
     preseason-rank gradient died, so measure before building.
  2. SHAPE RATHER THAN LEVEL. History gives a pitcher's level, not how he
     decays within a start. Times through the order is currently ONE
     league-wide curve, and whether a contact pitcher fades differently from
     a flamethrower is a separate question history cannot answer.

---

## Day thirteen — handedness, the other channel, and a magnitude result

Pre-registered in RESUME the night before and run first thing:
`scratchpad/platoon_bat.py`, full output in `scratchpad/platoon_bat.out`.
Per-plate-appearance `batSide`/`pitchHand` over 9,962 games, four seasons.

THE CONSTRUCTION. Per start, the opposing lineup's rate recomputed from each
batter's record against THIS STARTER'S HAND, minus the same lineup's rate
from their overall numbers — the amount a handedness-aware model would move
the start — correlated against the residual the model already leaves.
Switch hitters need no special case because the split is keyed on the
PITCHER'S hand, so a switch hitter's "vs LHP" cell is his right-handed
record, which is what he will actually do.

Four arms: `in-season` (2026 splits, the start's own plate appearances
removed), `strict-loo` (the batter's WHOLE GAME removed, either hand),
`raw` (unshrunk, to bound how much the shrink absorbs), `prior` (2023-25
only, no leak by construction and what a model would hold in March).

    channel   in-season   strict-loo   raw     prior    per start   ceiling
    k          -1.3        -1.2        -1.1    +0.9     0.142 K     +0.068
    babip      +2.6        +2.6        +2.7    -0.8     0.055 H     +0.026
    hr         +1.4        +1.4        +0.9    +1.6     0.034 HR    +0.040
    COMBINED   +1.7        +1.8        +1.7    +0.3     0.062 runs  +0.031

STRIKEOUTS ARE DEAD WITH POWER, and that is the channel the live-board case
was about. A perfect correction scores r +0.068, z ~3.8. Measured -0.024,
wrong-signed on every in-season arm, flat across quintiles, dead in the
top-20%-by-|x| tail.

THE COMBINED RESULT IS NOT A NULL AND SHOULD NOT BE FILED AS ONE. All three
channels as one linear-weights run adjustment move a start by 0.062 runs of
standard deviation, and the measured r EQUALS ITS OWN CEILING: +0.031
against +0.031. z +1.7 is the MOST a mechanism this size can score at
n=3,070. Handedness is real, correctly signed on contact, and sits at the
leverage floor where this project cannot distinguish it from nothing.

That distinction matters for the dead list. Handedness has now been killed
three times — the shipped A/B, the pitcher-side screen, and this — but only
the third is durable. The first two were MIS-SPECIFIED, and a null is only
as good as the channel it tested. This one is a MAGNITUDE result: it does
not say the effect is absent, it says the effect is 0.06 runs. Re-open it
only if the leverage floor moves or the residual gets much quieter, not on
a cleverer mechanism.

AND IT WOULD BE STRUCTURAL WORK. The hand changes when the sim swaps
pitchers, so handedness is a per-plate-appearance lookup against the current
arm, not a per-lineup adjustment applied once. That is the same shape as the
team-defence correction and it is not worth building for 0.06 runs.

### The leak, again, and what finally guards it

The `strict-loo` arm first reported **+6.2 sigma** on BABIP and +5.3 on HR —
the arm that removes MORE data scoring higher than the one that removes
less, which is arithmetically impossible for a real effect. It was
subtracting nothing. `game`'s batter-id keys stayed ints while `faced` was
normalised to strings, so every lookup missed and the start sat inside its
own predictor. Three plate appearances out of four hundred, perfectly
correlated with the outcome, doubled the correlation.

This is the third time this project has produced a several-sigma finding out
of a start being inside its own predictor (`headroom.py` at 112% of a
perfect forecaster, `platoon_split` at +4.8 before leave-one-out and +1.2
after). The general form: **a leave-one-out that silently removes nothing is
indistinguishable from a discovery.** `arm` now raises when misses outnumber
hits rather than reporting a number.

The diagnostic that caught it is worth keeping: MORE EXCLUSION SHOULD NEVER
RAISE THE SCORE. When a stricter arm beats a looser one, the stricter arm is
broken.

Second guard from the same run: the three channels drop different rows —
babip needs balls in play where k and hr need plate appearances — so the
combine refused to zip them and now joins on the start key. It printed the
mismatch rather than silently producing a fourth number.

### The aggregation objection, and the screen that answers it

The residual screen above collapses each start to ONE number — the lineup's
mean rate shift — and asks whether that predicts the starter's aggregate
line. That is an aggregate test of a mechanism that operates per plate
appearance, and it is the same substitution this project keeps making. The
objection is correct in principle: the simulator resolves one plate
appearance at a time and could hold each hitter's UNBLENDED rate against the
arm actually on the mound, and a mean cannot see what only exists below it.

Specifically, handedness does not only move a lineup up or down, it SPREADS
THE NINE APART. Runs are convex in offensive rates — clustering makes
crooked innings — so a mean-preserving spread should RAISE expected runs,
and a correlation against the mean shift is blind to that by construction.
It is also asymmetric, which would make it a per-game feature rather than a
level constant: a hitter's blended rate is dominated by the right-handers he
mostly faces, so a LEFTY pulls him ~0.036 off it against ~0.014 for a
right-hander.

MEASURED, `scratchpad/hand_convex.py`, 20,000 paired games on common random
numbers, lineup mean held EXACTLY fixed:

    arm                      F5        F7        F9
    vs LHP (real size)    -0.009    -0.004    -0.013
    vs RHP (real size)    +0.012    +0.004    +0.008
    2x the real spread    +0.014    +0.013    +0.009   +/- 0.018

Even at DOUBLE the real spread the effect is ~0.014 runs and unresolved. At
real size it is smaller and the sign flips between arms. Against a 0.05-run
leverage floor this is bounded at about a quarter of it. The dispersion
channel is closed.

AND THE BULLPEN ARGUMENT RUNS THE OTHER WAY. A lineup facing a left-handed
starter sees left-handers for roughly 60% of the game against the ~28% baked
into their season line, so there IS a systematic per-game shift — but it is
concentrated in the STARTER'S innings, which is exactly what the residual
screen measured and found null. Extending to the full game mixes in
right-handed relievers and DILUTES it. The starter-only test was handedness
at its strongest, not its weakest.

**A SAMPLING WARNING WORTH MORE THAN THE RESULT.** At 6,000 paired games the
2x control read +0.05 on all three prefixes — positive, consistent across
F5/F7/F9, and exactly what the mechanism predicts. At 20,000 it fell to
+0.014. It was noise wearing the shape of a finding, and the run would have
been reported as a confirmation if it had stopped where it was first
intended to. Paired common-random-numbers designs are not immune to this:
the pairing shrinks the standard error, it does not shrink it enough for
0.02 runs at 6,000 draws.

The clamp bug in the same file is the other half of the lesson. Perturbing a
rate and CLIPPING it into range is not mean-preserving and cannot be undone,
because a clipped value will not move; the floor binds harder than the
ceiling, mean K% rises, runs fall, and the convexity being measured is
cancelled by the artifact. The fix is to shrink the whole centred vector
until nothing clamps, which preserves the mean exactly. The first version
reported a 4x control at ZERO and would have been read as a broken screen
rather than a broken perturbation.

### Handedness, specified correctly — the fix is real, the gain is not

The challenge that reopened this: we simulate every plate appearance in a
league where the handedness effect is one of the best-established facts in
baseball, so a null should be suspicious. It was. The implementation was
wrong in a specific, identifiable way.

**THE SPECIFICATION ERROR.** `rates.batter_rates_by_hand` shrinks each split
toward the HITTER'S OWN OVERALL RATE, so a hitter with a thin split
regresses to having NO platoon effect — the one answer known to be false.
It keeps his PERSONAL DEVIATION, which is the noisy half that does not
persist, and discards the STRUCTURAL half, which is reliable. Counted on
9,962 games (`scratchpad/platoon_league.py`):

    bat/pit        PA        K%      BB%      HR%    BABIP
    R vs R    279,841    0.2296   0.0878   0.0298   0.2954
    R vs L    143,592    0.2205   0.0954   0.0312   0.3027
    L vs R    268,427    0.2187   0.1067   0.0325   0.2955
    L vs L     62,122    0.2387   0.0939   0.0240   0.2973

A left-handed bat loses 26% of its home run rate against a left-hander. A
lefty takes 81% of his plate appearances against right-handers, so his
blended HR rate is .0309 against a truth of .0240 vs LHP — 22% adrift.

THE TELL, missed for a full day: "72 of 148 hitters have reversed splits"
was reported as evidence of cancellation. It is not. That statistic pooled
left- and right-handed batters, and a lefty's split has the OPPOSITE SIGN
from a righty's by definition. Half reversed is what a large, real,
one-directional effect looks like when nobody conditions on batter side.

**THE CORRECTED CONSTRUCTION** (`scratchpad/platoon_fix.py`): shrink toward
the league platoon cell for the side he bats from, scaled against the blend
HIS OWN mix and sides produce. Switch hitters fall out for free — they take
the advantage both ways, so their ratios come out ~1.0 rather than needing a
special case. Verified before scoring anything:

    group      n   HR vsL   HR vsR    delta
    RHB      244   0.0325   0.0297    +9.4%
    LHB      144   0.0239   0.0340   -29.7%
    switch    48   0.0271   0.0273    -0.5%

against the shipped spec's -16.2% for left-handed bats. Roughly twice the
signal, and it matches the counted league truth.

**SCORED ON THE DIRECT CHANNELS**, which is where a plate-appearance
mechanism has power — runs are four steps downstream and F5 CRPS could not
resolve it. 2026 starts, splits from 2023-25, leak-free, 20 sims x 6 salts
paired (`scratchpad/hand_direct.py`). Positive is WORSE:

    arm                  k       bb       hr        h
    own-prior         +2.9     +9.9     +1.7     +1.6
    league-prior      +0.0     -1.0     +0.8     +0.9
    league+dev        +0.9     +4.7     +2.1     +1.3

TWO FINDINGS AND ONLY ONE IS THE ONE WANTED.

1. THE SHIPPED SPECIFICATION IS ACTIVELY HARMFUL — +9.9 sd worse than no
   handedness on walks. `USE_HANDEDNESS` is off, so nothing ships broken,
   but anyone flipping that flag makes the model worse and the docstring
   does not say so. It does now.
2. THE PERSONAL SPLIT IS NOISE. Adding each hitter's own deviation on top of
   the league structure costs 5.7 sd on walks against the pure structural
   arm. Only the structure carries anything.
3. CORRECTLY SPECIFIED, HANDEDNESS IS A WASH. league-prior lands on top of
   `off` in every channel. It repairs the damage; it does not beat baseline.

**WHY, AND THIS IS THE EXPLANATION THAT FITS EVERYTHING.** The lineup card
IS the handedness adjustment. The manager stacked his right-handed bats
against the left-hander before first pitch, and the simulator is fed the
lineup that actually played. The 26% home run gap is real and it is mostly
already expressed in WHO IS BATTING. Re-expressing it per hitter double
counts what the card already says.

That also retires the two-channel framing from earlier in the day. There is
a third channel — roster construction — and it is the big one, it is already
an input, and it is why both measured channels come back at zero.

**THREE SMALL-n FALSE POSITIVES IN ONE DAY.** The dispersion control read
+0.05 at 6,000 paired games and +0.014 at 20,000. The CRPS A/B read -3.5
sigma in sample and +2.3 out of it. This screen read -2.0 and -2.1 on home
runs and hits at 4 sims x 2 salts and +0.8 and +0.9 at 20 x 6. Every one of
them had the shape the mechanism predicted, which is exactly why they were
convincing. A cheap run is for finding bugs, never for deciding.

### Handedness specified correctly, end to end — and it is a wash

The challenge that forced this: are we matching hitter-vs-LHP with
pitcher-vs-(correct hand)? We were not. log5 takes three terms and only one
of them was ever conditioned.

WHAT WAS BUILT (`scratchpad/platoon_fix.py`, `scratchpad/hand_direct.py`):

  batter    his rate vs this pitcher hand, shrunk toward the LEAGUE platoon
            cell for the side he bats from
  pitcher   HIS rate vs this batter side — DID NOT EXIST BEFORE. Every
            handedness attempt in this project left the pitcher on his
            blended line, so a two-sided matchup was half specified.
  league    the (batter side, pitcher hand) cell, RATIOED onto the model's
            own league level

`sim.BatterRates` gained `side` and `lg_cell`; `sim.PitcherRates` gained
`vs_side`; all inert when unset and the plate appearance is bit-identical.

RESULT, 2026 starts against splits from 2023-25, 20 sims x 6 salts paired,
positive is worse:

    arm                  k       bb       hr        h
    league-prior      +0.0     -1.0     +0.8     +0.9
    matchup           +0.3     +0.0     +1.6     -0.1

Flat, on a harness proven to detect a 6x effect at 8 sd. THIS null is
earned. The four before it were not — each was a defect:

**1. THE SHRINK TARGET.** Toward the hitter's own overall rate, i.e. toward
"no platoon effect", which is the one answer known to be false.

**2. `adjust_lineup` DROPPED THE FIELDS.** It rebuilt every `BatterRates`
listing fields BY HAND, so `side` and `lg_cell` were set on the cases and
deleted before the simulation saw them. The matchup arm came out IDENTICAL
TO FOUR DECIMALS and would have been reported as "the fully specified
version changes nothing". Now uses `dataclasses.replace`, guarded by
`check_adjust_lineup_keeps_every_field_on_a_batter`, mutation-verified.

**3. THE LEAGUE BASELINE WAS SUBSTITUTED ABSOLUTELY.** The cells are counted
off play-by-play and the model's league rates come from boxscores, so they
sit on different footings — walks here include hit-by-pitch, which the
simulator draws separately:

    k_pct 1.042    bb_pct 1.172    hr_pct 0.966    babip 1.037

Substituting the cell moved the WALK LEVEL by 17% and called it handedness:
+6.9 sd worse on walks, swamping an effect worth a fraction of that. Only
the RATIO carries platoon information. The batter and pitcher priors were
never exposed because they already use `cell / blend`, where the footing
cancels.

**4. THE PITCHER SIDE SILENTLY MIGHT NOT HAVE ATTACHED.** The coverage guard
counted batter slots only. Verified after the fact: 3,203 of 3,318 starters
carry a side-split, the 115 misses being rookies with no prior history.
COUNT BOTH SIDES OF ANYTHING THAT ATTACHES TO TWO THINGS.

### log5 is half input-adjusted and half output-adjusted

Laid out during the same session, and it is an inconsistency worth fixing
independently of handedness:

    times through the order   INPUT  — scales the pitcher's rate
    handedness                INPUT  — all three terms (as of today)
    park                      OUTPUT — multiplies the probability
    arsenal                   OUTPUT — multiplies the probability

log5 is an ODDS-RATIO construction and multiplying its probability output is
not equivalent to any consistent change in the underlying rates. A 1.05x on
a .05 probability is nearly a 1.05x on the odds; on a .45 probability it is
not. So the same arsenal multiplier means something different in a high-K
matchup than a low-K one, and the distortion is worst in the TAILS, which is
where prop lines sit. It is also why the clamps exist — `min(max(k, 1e-6),
0.95)` and `min(0.95, babip)` are there because output multipliers can push
a probability out of range, and every clamp hit is a silently distorted tail.

Three more things the layout exposes: `arsenal_mult` is applied to home runs
AND babip with the SAME constant; the two paths differ (`hr` gets
`* arsenal_mult / cond`, `babip` gets `* arsenal_mult` with no `/cond`); and
walks carry no park and no arsenal term at all, the only clean log5 in the
model.

### What this says about the ARSENAL experiments

The same lens, applied to a feature with seven or eight nulls behind it:

  * Arsenal is an OUTPUT multiplier where handedness is an INPUT
    conditioning. Both cannot be the right shape.
  * ARSENAL HAS NEVER HAD A POSITIVE CONTROL. Nobody amplified the
    multiplier and confirmed the harness could see it. If a 6x arsenal
    effect is invisible, every arsenal null is uninformative.
  * The pre-registered tests scored it on RUNS, the low-power channel.
  * Its leave-one-out is an ARGUMENT in a docstring, not a mechanism.
  * The marginals may already be counted: a slider-heavy pitcher's K% is
    already high and a batter's K% already reflects the league mix, so the
    multiplier must carry ONLY the interaction. The screen claims to divide
    by a league-average mix, which is the right shape — verify rather than
    assume.

### HIT-BY-PITCH was a POPULATION MISMATCH, not a level error

`HBP_RATE` and `SAC_RATE` are drawn off the top of every plate appearance
from flat league constants — for every pitcher, every hitter, every night.
Both are KNOWABLE, which is the whole argument: measured replacing imported,
not a new mechanism. Counted per plate appearance off play-by-play
(`scratchpad/hbp_sac.py`, 753,982 PA):

    season   SP HBP   RP HBP    gap     SP SAC   RP SAC    gap
    2023     0.01003  0.01342   +34%    0.00794  0.01014   +28%
    2024     0.00991  0.01273   +28%    0.00783  0.01123   +43%
    2025     0.00944  0.01208   +28%    0.00864  0.01218   +41%
    2026     0.01044  0.01262   +21%    0.00888  0.01272   +43%

The pooled rate is 11.9% above the shipped 0.0098 — which matches the "HBP
11% light" note — but the shipped value is roughly RIGHT for the population
it was measured on. It was counted on STARTERS from boxscores and is applied
to EVERY ARM, and relievers hit batters 21-34% more often in every season on
file. Sacrifices are worse: relievers see 43% more, because late innings are
when a run is worth bunting for. Both are trending up.

FIXED BY ROLE, not by moving the constant. `PitcherRates` gained
`hbp_rate`/`sac_rate` (None = the old flat fallback, so it is inert),
`game.build_side` sets them per arm behind `USE_ROLE_HBP`, and `cond` now
rescales by THE SAME two rates that were drawn — using the league constant
there would bias every rate below it, worst for exactly the arms the
per-role rates exist to describe.

Relievers throw ~43% of plate appearances, so this is ~0.03 runs a game of
level that was simply missing. It matters more than 1% suggests because a
hit-by-pitch is a BASERUNNER and the model is 6% short on runs with the
right number of hits, strikeouts and home runs.

PER-PITCHER HBP IS ALSO REAL AND UNUSUALLY STABLE, and is NOT yet wired:
sd 0.00675 with p10 0.0043 against p90 0.0200 — a five-fold range — and a
split-half of +0.551 correcting to +0.711 reliability, which is bullpen-role
territory. Leverage 0.035 runs pitcher-only, near 0.05 with the batter side
added. Right at the floor, so it is a judgement call rather than a free win.

**TWO TEST FAILURES WORTH MORE THAN THE FIX.**

1. `check_rates_are_conditioned_on_the_off_the_top_draws` asserted the
   SOURCE TEXT `"cond = 1.0 - SAC_RATE - HBP_RATE"`. It broke on a refactor
   that was not a regression, which is the defining failure of a check that
   reads code instead of running it. Replaced with a behavioural check: an
   arm given a huge off-the-top share must still produce the SAME strikeouts
   per plate appearance, because that is the entire point of the rescale.
2. The replacement then SURVIVED ITS OWN MUTATION, twice. First because the
   asserted target was wrong — I expected strikeouts per plate appearance to
   FALL by the off-the-top share when the correct answer is that it does not
   move — inside a band wide enough to contain the bug either way. Second
   because `build_side` overwrote the test's explicit rates unconditionally,
   so the "loud" arm was never loud. That second one is a real design bug:
   the field was unusable by any caller. An explicit rate now wins.

A check that reads source text and a check that never runs its own premise
look identical from the outside — both pass, both green, both worthless.

### Wild pitches and passed balls — the catcher half is closed, the level is not

Raised as: catchers are dead for their effect on PITCHING, but what about
passed balls? The framing null was measured on strikeouts and walks, which
is what framing moves. BLOCKING is a different skill and had never been
screened. Counted on 330,808 plate appearances with a runner aboard
(`scratchpad/wp_pb.py`):

    wild pitches  6,150  0.01785 per exposed PA
    passed balls    863  0.00261 per exposed PA
    combined             0.02046   (shipped WP_PB_RATE 0.0155, -24.3%)

**THE CATCHER HALF IS CLOSED.** Passed balls are 12.8% of free-base
advances; the pitcher owns 87% of them through wild pitches. A per-catcher
blocking model works on an eighth of an already-small quantity — about 0.002
runs. Not worth building, and that is now measured rather than assumed.

**THE LEVEL IS 24.3% LIGHT, AND IT IS THE SAME BUG AS HIT-BY-PITCH.** The
docstring derives 0.0155 from "0.0057 wild pitches per batter faced across
2,070 starts" — STARTERS, from boxscores — then applies it to every arm.
Third constant in one day measured on one population and used on another.

Per-pitcher spread is real and persists: sd 0.01214, p10 0.00578 against p90
0.03509 (a six-fold range), split-half +0.490 correcting to +0.657
reliability. Leverage is 0.020 runs, under the floor, so the PER-ARM version
is not worth wiring. The LEVEL is.

**AND THE LEVEL CANNOT SIMPLY BE SET, WHICH IS THE INTERESTING PART.**
`WP_PB_RATE` is a FITTED parameter — `fitf5.RULE_KEYS` and its grid — and
the search pushed it DOWN to 0.0155 while reality is 0.0205. That direction
is a diagnostic: the model appears to OVER-CONVERT free bases into runs, so
the fit compensated by handing out fewer of them. Setting the measured value
would expose whatever that was masking, and this is exactly the
advance-without-a-hit channel that the 6% run shortfall lives in.

Doing it properly means setting 0.0205 AND REMOVING IT FROM THE SEARCH —
handing a measured quantity back to a fit is how it goes back to absorbing
other defects, which is the standing rule. That is a protocol change, not a
constant edit, so it is left as a decision rather than made quietly.

Note also `check_grids`: every searched parameter's grid must contain its
shipped value, so changing the constant without the grid silently freezes
the parameter and reads as a genuine "no move". It already happened to this
exact constant for two full runs.

**A denominator was checked and it mattered less than expected.** The first
version read `matchup.postOnFirst/postOnSecond/postOnThird` as the pre-play
base state. "post" means AFTER, so it counted plate appearances that ENDED
with a runner on rather than STARTED with one — the same misreading as
`count.outs`. Rebuilt on `pbp.plays`, which reconstructs the state before
each play, the answer moved 0.02036 -> 0.02046. Checking it was still right;
the two sets happen to be nearly the same size and that could not be known
in advance.

### WP_PB_RATE set to the counted value and REMOVED FROM THE SEARCH

0.0155 -> 0.02046, and the second half of that sentence is the important
one. It was the ONLY parameter `fitf5` searched, and the fit had settled it
BELOW the measurable truth — a fitted constant drifting away from a number
you can count is a fitted constant absorbing somebody else's error.

Scored on 3,664 sides, 60 sims, 4 salts:

    rate                 CRPS               sim F5 runs   actual   gap
    measured 0.02046     1.60186 +/-0.0015    2.4187      2.4708   +0.0521
    old fitted 0.0155    1.60147 +/-0.0024    2.4053      2.4708   +0.0655

**IT CLOSES 20% OF THE F5 RUN GAP AND THE SCORE CANNOT TELL.** That is the
expected shape for a measured quantity replacing an imported one, and it is
why the standing rule says such a change does not have to prove itself on
the loss. The CRPS difference is 0.0004 against error bars of 0.0015-0.0024.

The direction is the diagnostic that was predicted before the run: the
search had been buying accuracy by handing out FEWER free bases, which is
what you do when the model turns the ones it has into too many runs. With
the level pinned to reality, a fifth of the shortfall closes by itself and
whatever remains is now visible rather than absorbed.

`fitf5.MEASURED` is the new home for constants the search may not touch.
PARAMS is consequently EMPTY, which is the honest state and not a bug: the
only thing this objective ever fitted has now been counted instead.
`--with-hook` still adds the hook terms back.

TWO GUARDS MOVED WITH IT. `check_grids` iterated PARAMS, so it went VACUOUS
the moment the last searched parameter was measured — it looped over an
empty tuple and passed, and its own meta-test caught that. It now iterates
RULE_KEYS, which keeps the invariant for anything that could be re-enabled.
The hook keys stay excluded deliberately: their grids are known not to hold
the refitted incumbents, so widening the check would turn a real invariant
into a failure nobody could act on.

### log5 multipliers moved inside the construction; the clamps are gone

Park and arsenal MULTIPLIED log5's probability output. log5 is an odds-ratio
construction, so scaling its output is not a consistent change to the
underlying rates: 1.05x on a .05 probability is nearly 1.05x on the odds, and
on a .45 probability it is not close. The same park factor therefore meant
something different in a high-strikeout matchup than a low one, worst in the
TAILS, which is where prop lines sit.

`sim.odds_mult(p, m, lg)` applies the multiplier as the odds ratio that takes
the league rate to `m * lg`. A league-average matchup in an `m` park now
comes out at EXACTLY `m * lg` (verified to 1e-17), it bends rather than
scaling away from the league rate, and it CANNOT leave (0, 1) for any finite
positive multiplier.

THAT DELETES THE CLAMPS RATHER THAN TIDYING THEM. They existed only because
output multipliers can leave [0, 1], and they clamped three different ways in
four adjacent branches — `k` both sides, `babip` upper only, `bb` and `hr`
not at all. Measured before removal: ZERO clamps in 529,581 plate
appearances, so it was latent, but latent on the CURRENT multipliers, and
park and arsenal are both off.

**BIT-IDENTICAL, VERIFIED BY FINGERPRINT.** Every multiplier is 1.0 in the
shipped config and `odds_mult(p, 1.0, lg) == p` exactly for all 999 tested
probabilities, so this had to be a no-op — and is. 400 games x 6 sims,
hashing runs plus both starters' k/h/hr/bb:

    committed engine   5bdcf78e9e70c3579220e55431c18aeb   8.591667 runs
    refactored engine  5bdcf78e9e70c3579220e55431c18aeb   8.591667 runs

**AND A CORRECTION, CAUGHT BY MUTATION RATHER THAN BY READING.** A test at
impossible rates (a .62 matchup strikeout rate alongside a .69 walk rate)
returned only {K, BB, SAC, HBP} — no home runs, no balls in play. That was
reported here as a real defect the refactor had exposed. IT IS NOT ONE. Those
two rates sum past 1.0 and cannot coexist; the chain's response is arbitrary
but not wrong. Clamping the walk to the remainder does NOT change it, because
`bb / rest` is then exactly 1.0 and the walk still fires every time — proven
by removing the clamp and watching the check pass anyway.

**AND THE CLAMP BECAME A RAISE**, which is what it should have been from
the start. Clamping manufactures a plausible answer out of impossible
inputs, which is precisely the failure mode this session spent all day
unwinding — the clamp was itself an instance of the thing it was supposed to
guard against. Rates that sum past one mean a CALLER handed the model
numbers that cannot coexist: a bug upstream, not a runtime state to smooth
over.

`pa_outcome` now raises `ValueError` naming the offending rates. Free to be
strict, because it is measured at ZERO occurrences in 529,581 plate
appearances — nothing real trips it, and the next mechanism that inflates a
rate finds out immediately instead of via a home run channel quietly going
to zero and a fitted constant absorbing the difference.

Mutation-verified (removing the raise fails the check) and still
bit-identical: fingerprint 5bdcf78e9e70c3579220e55431c18aeb, unchanged.

Second time in one session a story was fitted to a result before it was
checked. Both times the mutation caught it.

### The restructure: one resolved Matchup, built when a pitcher takes the mound

A plate appearance's inputs came from FIVE places at once — fields on the
batter, fields on the pitcher, a league dict threaded down through several
call layers, module globals, and function arguments. Nothing owned the
question "what does this at-bat depend on", so every new value found its own
route down and picked whichever object was already going there.

THAT IS NOT COSMETIC AND IT COST TWO BUGS IN ONE DAY. `lg_cell` — a LEAGUE
baseline — ended up living on a `BatterRates`, because the batter was the
object that happened to flow to the right place. And `adjust_lineup` rebuilt
every `BatterRates` listing its fields by hand, so it silently dropped
`side` and `lg_cell`, and the handedness matchup arm came out identical to
four decimals, which reads as a null and is plumbing.

NOW: `sim.Matchup` holds the three log5 terms per channel kept ADJACENT and
on the same population, the rate multipliers, the per-arm off-the-top rates
with the `cond` they imply, and the league hit mix. `sim.resolve` is the
only place inputs are picked. `sim.pa_from` is the hot path. `pa_outcome`
survives as a convenience wrapper for tests and one-off questions.

RESOLVED PER PITCHER, NOT PER PLATE APPEARANCE. Nine objects an arm, reused
for every time through the order, cached on the `Side` and keyed on the
pitcher OBJECT — two clubs can carry the same name and a name key would
collide silently. This respects the standing note on `pa_outcome` that per-PA
object construction was deliberately removed as too expensive.

Times through the order is deliberately NOT folded in: it scales the
pitcher's rates and changes every lineup pass, so baking it in would need
three variants per batter. It stays a late input adjustment in `pa_from`,
which is what it already was.

**BIT-IDENTICAL THROUGHOUT.** Fingerprint 5bdcf78e9e70c3579220e55431c18aeb
over 400 games x 6 sims, hashing runs plus both starters' k/h/hr/bb —
unchanged from before the odds_mult work, through it, and after the
restructure. 376 checks pass.

The stale-cache failure is guarded and mutation-verified: serving the old
arm's numbers after a change would price every batter against the pitcher
who just left, the runs would still add up, and the error would be largest
exactly when the bullpen matters most.

WHAT THIS BUYS, and it is the reason to have done it before the arsenal
re-test: a new adjustment now touches `resolve` and nothing else. Nobody
constructing a batter needs to know handedness or park or arsenal exist, and
the three log5 terms sit on adjacent lines where conditioning one and not
the others is visible rather than scattered across five layers.

**AND IT COSTS 11%, WHICH CONTRADICTS WHAT WAS PREDICTED HERE.** The claim
was that structure and speed pointed the same way. They do not. Best of
seven over 2,000 games:

    inline, per plate appearance   2.169s   (median 2.203)
    resolved Matchup, lazy         2.414s   (median 2.435)

The FIRST attempt was worse still at 2.761s, because resolving all nine on
every arm change built ~90 matchups a game against ~76 plate appearances —
MORE objects than the per-PA version it replaced, which is exactly the cost
the old comment warned about. Lazy per-slot resolution plus `slots=True`
recovered most of it: a reliever who faces three batters now builds three.

11% is the price of the structure and it is worth paying, but it is a TRADE
and not a free win. It also sits against `stop_after=5` from the same day,
which made the F5 loop 1.66x faster — so the fit loop is still roughly 1.5x
ahead of where the morning started.

### The role audit: the pattern does NOT extend to baserunning

Three constants on 2026-08-27 turned out to be measured on starters and
applied to every arm, so the obvious next move was to check the rest.
`scratchpad/role_audit.py` re-counts every run-producing constant split by
SP/RP innings, on the denominators the simulator actually rolls in.

**IT IS A NULL, AND THAT IS THE USEFUL PART.** RP/SP lands between 0.91 and
1.08 on every advancement and baserunning constant. Relief innings are later
and tighter, but runners advance the same way in them. The
starter-measured-reliever-applied pattern is real for the PITCHER'S OWN
rates (hit-by-pitch, sacrifices, wild pitches) and absent for what runners
do. Stops the pattern being over-applied.

**ADVANCEMENT WAS ALREADY RIGHT** and an apples-to-oranges comparison nearly
said otherwise. `FIRST_SCORES_ON_1B` is a SEPARATE constant from
`FIRST_TO_THIRD_ON_1B`, so the shipped first-to-third excludes a runner who
scores. Comparing a "reached third OR scored" count against it read 9% light
at two outs; adding the two shipped constants back together gives 0.329 /
0.338 / 0.476 against a measured 0.291 / 0.323 / 0.447. Within a few percent.

`RUNNER_ADVANCES_ON_OUT` is LEGACY — only reached when
`USE_MEASURED_ADVANCEMENT` is off, and it is on. Measuring it was wasted.

**THE ONE REAL FINDING: SB_RATE AND CS_RATE WERE ON THE WRONG DENOMINATOR.**
Derived from "1,301 steals over 23,338 TIMES ON BASE", but `baserunning`
rolls only when first is occupied and SECOND IS EMPTY — a strictly smaller
population, so a rate over all times on base is too low by the ratio between
them. Same class of error as the wild-pitch rate.

    season      SB       CS        n        (per opportunity, correct state)
    2023    0.0672   0.0151   48,019
    2024    0.0718   0.0169   46,985
    2025    0.0681   0.0172   47,136
    2026    0.0651   0.0175   36,722

Era-gated and stable, so 2026 is used. Shipped 0.0557/0.0148 -> 0.0651/0.0175,
both up ~17%.

**RUN-NEUTRAL, AS THE ARITHMETIC SAID BEFORE THE RUN.** Attempts rise 17% and
so do caught-stealings, so the net value per opportunity barely moves:

    measured   CRPS 1.59885 +/-0.0035   sim 2.4143   gap +0.0565
    old        CRPS 1.60186 +/-0.0015   sim 2.4187   gap +0.0521

Both inside the error bars. Kept because it is measured replacing guessed
and the denominator was simply wrong; what it changes is the SHAPE, 17% more
runners moving into scoring position.

**AND A MECHANISM GAP THAT BOUNDS ANY RATE HERE.** 14.5% of real steal
events — 2,564 of 17,742 — happen in states this model cannot produce at
all: steals of third, and double steals. `baserunning` only ever moves a man
from first to second with second empty. No value of `SB_RATE` reaches them.
Sized at ~0.13 per side-game, ~0.026 runs. Below the floor, so recorded
rather than built.

THREE FULL SCANS WERE SPENT ON EXTRACTION BUGS, both mine. `pbp.resolve`
already collapses a runner's multiple movement records into where he ended
up — its docstring says so — and the hand-rolled version that took the first
record and broke reported 2 first-to-thirds in 557 singles, because a runner
going first to third is written as 1B->2B then 2B->3B. The steal denominators
were also mis-keyed so those rows silently did not print at all. When the
codebase already has a function for the thing, use it.

### Stealing in every base state, and the LEVEL vs SPREAD distinction

`baserunning` rolled for a steal in ONE state — first occupied, second empty
— and could only move that man to second. Counted on 2026
(`scratchpad/steal_states.py`), that single state is 69.9% of real steals.

    state    outs      opps   SB      CS      to2B  to3B
    1B          0     9,099   .0497   .0138    445     7
    1B          1    11,272   .0640   .0207    704    17
    1B          2    11,445   .0664   .0195    742    18
    2B          1     3,433   .0186   .0067      0    64
    1B+2B       1     3,955   .0308   .0076     52    70
    1B+3B       2     2,435   .1170   .0127    261     6

Three things the flat rate could not express. Stealing is OUT-DEPENDENT
(.0497 with nobody out against .066 with one or two). First-and-third at two
outs runs at .1170, nearly double the flat rate, because the defence will
not risk a throw with a man ninety feet away. And two states had no
mechanism at all — a runner on second takes third at .0074-.0186 and is
almost never caught, and first-and-second produces MORE steals of third than
of second. Third alone, second-and-third and loaded produce ZERO steals in
8,434 opportunities, so they are absent by measurement.

`STEAL_TABLE` + `USE_STEAL_TABLE` ship it. Scored, it is MARGINAL: gap
+0.0530 against +0.0565, CRPS 1.60580 against 1.59885, both inside error
bars. Kept on measured-replacing-absent, not on the score.

### THE DISTINCTION THAT REFRAMES THE WHOLE SUB-FLOOR PILE

Raised by the user: things keep getting discarded for missing the ~0.05-run
leverage floor, and there are now about five of them. Do they add up?

**They add up ONLY IF THEY ARE THE SAME KIND, and they are not.**

  SPREAD effects — how game A differs from game B — combine in QUADRATURE.
  Handedness 0.062, arsenal ~0.04, per-pitcher HBP 0.035, per-pitcher wild
  pitch 0.020 make sqrt(sum of squares) = 0.08 runs, not 0.16. That is the
  same arithmetic that killed stacking handedness with arsenal: two 1.5-cent
  features make 2.3 cents, and it takes SIX to reach the bar.

  LEVEL errors — the model systematically low or high — ADD LINEARLY.

**EVERY WIN TODAY WAS THE SECOND KIND.** Hit-by-pitch, sacrifices and wild
pitches were all level errors, all pointing the same way (the model held
fewer baserunners than reality), and the wild-pitch fix alone closed a fifth
of the F5 run gap. The remaining +0.052 is itself a level error.

So the productive search is NOT more features. It is LEVEL ERRORS THAT POINT
THE SAME DIRECTION, and both kinds were being sorted into one bucket and
discarded together. Per-player refinements are genuinely dead — they are
spreads and they quadrature away. Structural gaps in what the model can
produce at all are not.

### Diagnose with seeds, fix with n

A loose sanity band failed at 2.42 against a 2.4 ceiling after the steal
table changed the random stream. The right FIRST move is re-running the same
small sample at a DIFFERENT SEED — cheap, and it separates "sampling" from
"real" immediately. It did: four seed/size combinations landed at 1.82-2.15.

But the right FIX is more samples, not a different seed. Changing the seed
until a check passes is fitting the test to its outcome, which is the same
error as widening the band. n went 400 -> 900 and the band stayed.

### WHERE THE RUN GAP IS: advancement, not rates. Measured and settled.

`scratchpad/f5_decomp.py` compares, for every scored side, the events the
simulator produces through five against the events that ACTUALLY happened
through five, counted off play-by-play. 1,659 games, 30 sims, starter
innings on both halves of the comparison.

    channel    sim/side    actual      gap    gap %
    k            4.2771    4.2981   +0.0210    +0.5%
    bb           1.6041    1.6257   +0.0216    +1.3%
    hbp          0.2034    0.1962   -0.0072    -3.7%
    h            3.6555    3.6519   -0.0036    -0.1%
    hr           0.6301    0.6212   -0.0089    -1.4%
    ---------------------------------------------------
    on           6.0931    6.0949   +0.0018    +0.0%
    ---------------------------------------------------
    runs         2.1533    2.1905   +0.0372    +1.7%

**THE MODEL PUTS EXACTLY THE RIGHT MEN ON AND BRINGS 1.7% FEWER OF THEM
HOME.** Baserunners agree to +0.0%. Every event channel is inside 1.4%. The
linear-weights sum of the channel gaps says the model should have SLIGHTLY
MORE runs than it does (-0.0103 explained against +0.0372 observed), so the
shortfall is not upstream at all.

Runs per baserunner: 0.3534 simulated against 0.3594 actual.

**THIS CLOSES A WHOLE CLASS OF WORK.** No further measurement of strikeout,
walk, hit or home run rates can close the gap, because those are already
right to within a percent. The remaining defect is in the base-out state
machine — sequencing and advancement — and that is where the next effort
belongs. It also explains why today's rate fixes were individually real and
collectively small: they were correcting channels that were already nearly
right, and the wild-pitch one helped because it is an ADVANCEMENT mechanism
(a free base with no batter), not a rate.

**THREE DENOMINATOR MISTAKES IN ONE SCRIPT, all mine, all producing
confident wrong tables.** `Side.line` is the STARTER'S line and reliever
lines are DISCARDED on each arm change (`cur_line = StartResult()`), so
comparing it against every first-five plate appearance reads as a UNIFORM
6.5-10.2% shortfall in every channel at once. A uniform shortfall across
independent channels is the signature of a DENOMINATOR error, never of rates
being wrong — no set of rate bugs moves strikeouts, walks, hits and home
runs by the same 8%. Then the same again on runs alone, where `runs_f5` is
the SIDE's and the actual was the starter's, which showed the model 10.5%
HIGH on runs while every event channel matched to 1.4% — also impossible,
and also a denominator.

The rule worth keeping: WHEN EVERY CHANNEL IS WRONG BY THE SAME PERCENTAGE,
STOP LOOKING AT THE RATES AND CHECK WHAT YOU DIVIDED BY.

### And the advancement gap is SHAPE, not rates — the model is under-dispersed

Runs allowed by the starter through five, sim against actual:

    runs     sim %  actual %     diff
       0     22.72     23.24    +0.51
       1     21.80     21.43    -0.37
       2     18.93     18.38    -0.55
       3     14.31     13.74    -0.56
       4      9.75      9.37    -0.38
       5      6.12      6.51    +0.39
      6+      6.37      7.32    +0.95

**REALITY HAS MORE SHUTOUTS AND MORE BLOWUPS; THE MODEL IS BUNCHED IN THE
MIDDLE.** Both tails are thin at once, which is the clustering signature: the
simulator resolves plate appearances independently and real ones arrive in
bunches. Runs are CONVEX in clustering, so the missing tail is also what
drags the mean 1.7% low — the same defect explains both the shape and the
level, and no adjustment to advancement RATES produces it, because rates
move the middle.

The model is 13% short on 6+ run starts and 2% short on shutouts.

**THIS REFRAMES `form.py`, WHICH IS PARKED.** That measured whether a
pitcher's nightly form is PREDICTABLE IN ADVANCE and answered no, three
ways. That is a different question from whether the model GENERATES ENOUGH
BAD NIGHTS AT ALL. Nothing here needs to know which start blows up — it
needs the right RATE of blowups. A mean-preserving per-start dispersion
term would fatten both tails without predicting anything, and the parked
result does not bear on it.

Exactly the standing rule: the dead list records HOW a thing was tried. Form
was tried as a PREDICTOR and died. It has never been tried as a DISPERSION.

Note also `early_exit_p`, the mixture already built and shipped inert, which
was aimed at the same tail from the hook side and whose numbers were voided
when the boundary bug was fixed. Two mechanisms pointing at one measured
defect, neither currently on.

### A per-start dispersion term: closes the SHAPE, neutral on the SCORE

Following the under-dispersion diagnosis. One latent draw per start scaling
the pitcher's four rates the way they travel on a bad night — strikeouts
down, walks, home runs and contact up. NOT a prediction: nothing knows which
start blows up, and it does not need to, it needs the right RATE of blowups.
`scratchpad/dispersion.py`.

    sigma  mean runs  vs actual    P(0)   P(6+)  shape err
   actual     2.1905              23.24    7.32
     0.00     2.1477    -0.0428   22.59    6.16       4.29
     0.10     2.1843    -0.0062   23.05    6.97       2.39
     0.15     2.2211    +0.0306   23.60    7.81       2.54
     0.20     2.2933    +0.1028   23.85    9.09       5.54
     0.30     2.4381    +0.2476   25.17   11.96      13.79

**ONE SIGMA CLOSES BOTH GAPS**, which was pre-registered as the test of
whether shape and level are one defect or two: 44% off the shape error and
86% of the run-level gap at sigma 0.10. Two defects would need the shape
overshot to fix the level. They are one defect.

**BUT IT DOES NOT IMPROVE F5 CRPS.** Held out on July-onward sides:

    60 sims x 4 salts    sigma 0.10 BETTER  (1.61607 against 1.62187)
    100 sims x 6 salts   sigma 0.10 WORSE   (+0.00313 +/- 0.00315, +1.0 sd)

It FLIPPED with sample size — the fourth small-n reversal of the day, and it
was one report away from being written up as a win.

WHY NEUTRAL IS THE RIGHT ANSWER AND NOT A DISAPPOINTMENT. The term adds the
SAME dispersion to every start, so it makes the MARGINAL distribution righter
without making any individual game's prediction better. Calibration improves,
discrimination does not, and CRPS on this objective is dominated by telling
games apart. NOT SHIPPED: a fitted parameter that does not earn on the
settlement quantity stays out, however good the marginal looks.

WHAT WOULD BE DIFFERENT. The defect is real and measured. A dispersion that
VARIES — by pitcher, by workload, by anything with a measurable spread —
would move discrimination as well as calibration, and that is the version
worth building. A flat one was the cheapest test of the diagnosis and it
confirmed the diagnosis without earning its place.

### Schedule burden: travel, getaway days, stretches — null on BOTH questions

Raised as: are we considering where players played the day before, long
travel, day games right after night games? Checked first — six between-game
features were already screened and all came back null, but "days rest" there
is the PITCHER'S days since his own start and day/night was a FLAT FLAG.
Nothing about where the CLUB was yesterday had ever been tested, and all six
were scored on the OUTS residual, which is the channel immune to everything.

`scratchpad/schedule.py` screens the BATTING club's schedule burden against
the earned-run residual, and asks TWO questions per feature, which no screen
here had done before:

    signed    is the tired club WORSE
    |resid|   is the tired club more VARIABLE

The second is the one that matters, because the defect this model actually
has is dispersion, not level. A flat dispersion term confirmed the defect and
was neutral on CRPS precisely because it did not vary; schedule burden was a
candidate for something that does.

    feature      positives   signed z   |resid| z
    getaway            780       -0.5        -0.9
    travel             859       +1.2        +0.1
    both                13       +1.6        +2.3
    stretch          2,770       -1.5        -1.2
    long_trip        1,640       +0.9        -1.3

**NULL, AND WELL POWERED.** Getaway days have 780 cases and read -0.9 on
dispersion; crude travel has 859 and reads +0.1. This is not "too small to
see" — a tired club is neither worse nor more variable.

**THE ONE ROW OVER 2 SIGMA HAS THIRTEEN STARTS IN IT** and is not a lead.
Recorded explicitly because 0.4% of a sample producing +2.3 is exactly the
shape that gets written up as promising.

**AND THE REAL-DISTANCE VERSION IS ALSO NULL.** The coordinates were
already here: `sources/rest.py` has fetched the thirty venue locations and
computed great-circle miles and a SIGNED eastbound time-zone shift the whole
time. It was built for the evidence layer and had never once been scored
against outcomes. Re-run on the real numbers:

    feature        cases   signed z   |resid| z
    miles            860       +1.5        +0.3
    far (1200mi)     236       +1.2        +0.9
    eastbound tz     220       +0.6        -0.9
    any tz change    446       +1.0        +0.6
    getaway          780       -0.5        -0.9
    redeye             7       +2.2        +3.4
    consec days    2,770       -1.5        -1.3

Everything with power is flat on both questions. THE ONLY ROW OVER 2 SIGMA
IS AGAIN THE COMBINATION AND IT NOW HAS SEVEN STARTS IN IT — fewer than the
crude version's thirteen, and recorded as not a lead for the second time.

A tell that the near-misses are noise: `miles` is POSITIVELY signed, meaning
a batting club that just flew further scores MORE. That is backwards for a
fatigue effect, and a real one would not change sign to suit the feature.

Schedule burden is closed: no distance, no time zone, no getaway day, no
stretch, on either the level or the variance.

### Is anyone harder to predict? No — and that closes the dispersion lead

Asked directly: are there pitchers or teams we get more wrong than others?
`scratchpad/whos_wrong.py`, split-half on odd against even starts,
Spearman-Brown corrected, scored on EARNED RUNS.

    population  metric                 n   half r   full r
    pitcher     BIAS  mean residual  107   -0.006   -0.011
    pitcher     DISP  mean |resid|   107   +0.037   +0.072
    pitcher     DISP  sd of resid    107   +0.059   +0.112
    club        BIAS  mean residual   30   +0.171   +0.292
    club        DISP  mean |resid|    30   -0.119   -0.271

**NOTHING REPEATS.** There IS spread — mean |residual| runs 1.19 at the 10th
percentile to 1.91 at the 90th across pitchers — but the same arms are not
hard next time. Club dispersion comes back NEGATIVE, which is what noise
looks like, and club bias at +0.171 on n=30 is z 0.9.

Properly powered: at n=107 a half-length reliability of 0.19 (full ~0.32)
would have shown at 2 sigma. Measured 0.037. And anything below that would
shrink to the league mean anyway, which IS the flat term already measured
neutral on CRPS.

**SO "VARY THE DISPERSION BY PITCHER" IS CLOSED**, and it was the top
remaining lead out of the under-dispersion diagnosis. Whatever makes a start
blow up is not a property of the pitcher that persists.

### The model UNDER-DIFFERENTIATES starts — but it is not exploitable

`scratchpad/spread_cal.py` regresses ACTUAL on PREDICTED. Slope 1.0 means
the spread of predictions is right; above 1 means they are too bunched.

`m_*` is a MONTE CARLO MEAN over 40 draws, so it carries its own sampling
noise, and noise in a regression PREDICTOR attenuates the slope. That
correction is not optional here — on earned runs the noise is 55% of the
predictor's variance:

    channel   sd(pred)  MC sd  sd(true)  raw b  TRUE b  z vs 1
    er           0.392  0.290     0.263  0.594   1.317    +1.6
    h            0.587  0.328     0.487  0.942   1.370    +3.9
    hr           0.159  0.129     0.093  0.878   2.588    +5.7
    bb           0.442  0.200     0.394  0.979   1.232    +3.8
    k            1.133  0.317     1.088  1.063   1.153    +4.3
    outs         1.248  0.602     1.094  1.209   1.575    +8.5

**EVERY CHANNEL IS ABOVE 1.** Reality separates starts 15% more than the
model does on strikeouts, 37% on hits, 57% on outs, 2.6x on home runs. Trust
the SMALL corrections most — strikeouts (x1.08) and walks (x1.26) barely move
and still land at +4.3 and +3.8 sigma. Home runs need a x2.9 correction so
2.588 is the softest number there, but its direction agrees.

UNCORRECTED, EARNED RUNS READ 0.594 AND SAY THE OPPOSITE — that the model
over-separates. Reporting that would have been a confident sign error. The
tell was in the data: `p_er` moves in steps of 0.025, which is 1/40.

**BUT IT IS NOT EXPLOITABLE BY RESCALING.** Fit the slope on the early half
and apply it to the later half and MSE moves -1.43% to +0.70%, mixed signs.
The reason the two facts agree: the DELIVERED predictions carry the Monte
Carlo noise, and noise WIDENS what shrinkage NARROWED, so the raw slopes are
already near 1 (h 0.986, hr 0.997, k 0.982). The underlying model is too
bunched; its output is not.

The compression is where shrinkage lives — the batter table shows the model
carrying 0.89 of observed strikeout spread, 0.73 on home runs, 0.57 on
BABIP, and pitcher home-run rates use k=934, so a 600-batter pitcher keeps
39% of his own number. Closing it needs more SIGNAL, not rescaling.

**AND A NOTE THAT PROTECTS EVERY OTHER SCREEN RUN TODAY.** This Monte Carlo
noise is 55% of the PREDICTOR's variance and only ~2% of the RESIDUAL's
(0.084 against 4.0), because the residual is dominated by real outcome
variance. So residual correlations — handedness, arsenal, schedule, travel —
are attenuated by under 1% and stand as measured. The two are different
denominators and it matters which one is being asked about.

### Per-batter run share is NOT ANSWERABLE without a state-machine change

Asked: is the offense distributed across hitters correctly — should Judge not
take a bigger share? `sim.apply_pa` does not know which batter is up and
`fr.bases` carries booleans, not runner identity, so no run can be attributed
to whoever drove it in. Answering it means giving the bases identity, which
is a real change to the state machine and is recorded rather than guessed at.

What IS measurable is the INPUT spread, and it matches the shipped shrinkage
constants almost exactly (model/raw: k 0.887, bb 0.742, hr 0.733, babip
0.570 against STABILISE-implied weights at 250 plate appearances of 0.887,
0.758, 0.610, 0.576). Consistent, so the flattening is the configured amount
rather than a bug.

### ARSENAL, tested properly at last: not a null — HARMFUL

Eight previous attempts, and every one of them was missing all three of the
things listed on 2026-08-27 while auditing handedness. `arsenal_direct.py`
supplies them: a POSITIVE CONTROL, scoring on the DIRECT channels rather than
runs, and a mechanical leave-one-out (the pitcher's PREVIOUS season's
arsenal) instead of a docstring argument. 1,659 games, 100 sims x 6 salts,
paired. Positive is WORSE.

    arm                    k               bb              hr              h
    arsenal 2026    +0.0088(+5.5)   -0.0014(-1.1)   -0.0002(-0.2)  +0.0043(+2.3)
    arsenal x4     +0.1720(+113.0)  -0.0017(-1.9)   +0.0005(+0.7)  +0.0900(+58.7)
    arsenal 2025    +0.0082(+5.0)   -0.0007(-0.6)   -0.0008(-0.8)  +0.0040(+2.8)

**THE CONTROL FIRES AT +113 SIGMA.** The harness sees a 4x arsenal effect
with overwhelming power on strikeouts and hits. That is the first time in
nine attempts that an arsenal null has been shown to MEAN anything — every
earlier one was measured on an instrument nobody had checked.

**AND ARSENAL IS NOT NEUTRAL. IT IS HARMFUL.** Significantly worse on
strikeouts (+5.0 sigma) and hits (+2.8) with the LEAK-FREE 2025 arsenal, and
equally worse in sample, so it is not a leak artifact in either direction.
Same shape as `USE_HANDEDNESS`: the honest finding is not "does nothing" but
"makes the model worse". `USE_ARSENAL` is False and must stay False.

**A CAVEAT THAT MUST TRAVEL WITH THIS.** The x4 control barely moves walks
(-1.9) or home runs (+0.7). So the harness has power on STRIKEOUTS and HITS
and NOT on those two channels — the bb and hr rows above are UNINFORMATIVE,
not null. Anyone re-opening arsenal on a power or walk hypothesis needs a
different instrument, and the control is how they would find that out.

**WHY IT HURTS RATHER THAN DOING NOTHING**, and it is the same reason
handedness did: the multiplier is applied on top of a log5 that ALREADY
contains both marginals. A slider-heavy pitcher's strikeout rate is already
high and a batter's strikeout rate already reflects the league's mix of
pitches. The multiplier is only entitled to carry the INTERACTION — the
deviation from what the marginals predict — and to the extent it carries any
of the marginals again it double counts. Six of the eight earlier attempts
aimed it at strikeouts, which is exactly where the double counting is worst.

Note this ran AFTER `sim.odds_mult`, so it is the first arsenal test where
the multiplier entered the odds rather than scaling log5's probability
output. The incoherent application was not what was wrong with it.

### Shrinkage: the big in-sample gain was a leak; what survives is per-channel

Following the under-differentiation finding rather than dismissing it — the
earlier "not exploitable" verdict tested whether the DELIVERED 40-draw
predictions could be rescaled, which is a question about the estimator, not
about whether the underlying model is compressed. Only the second was
measured and only the first was tested.

`scratchpad/unshrink.py` scales every `STABILISE_MEASURED` constant and
measures DISCRIMINATION — correlation of prediction with outcome, not MSE,
because MSE conflates spread with accuracy and spread is what is being
varied.

IN SAMPLE it looks enormous and monotone. Earned-run discrimination goes
0.1317 -> 0.1777 at a quarter of the shrinkage, +8.9 sigma, with home runs
+7.3 and hits +6.9.

**IT IS MOSTLY A LEAK.** Player rates are built from the SAME season being
scored, so less shrinkage lets each rate track that player's own realised
outcomes and the correlation with those outcomes rises for free. On a real
holdout — rates trained before 2026-07-01, scored on starts after it:

    shrink x        k       bb       hr        h       er     outs
    0.25         -3.0     +2.4     +2.0     -0.3     +2.0     -5.5
    0.50         -1.8     +1.7     +0.1     +0.2     +0.6     -0.4
    2.00         +2.5     +2.3     -2.0     -3.1     -1.2     +3.3

**WHAT SURVIVES IS PER-CHANNEL AND POINTS BOTH WAYS.** Home runs want LESS
shrinkage (+2.0 at a quarter, -2.0 at double). Strikeouts and outs want MORE
(+2.5 and +3.3 at double). A single global knob is the wrong instrument, and
"un-shrink everything" would have made strikeouts and outs worse.

**TWO INDEPENDENT METHODS AGREE ON THE RANKING**, which is what makes the
home-run result worth acting on. The slope test found home runs the most
compressed channel (2.59) and strikeouts the least (1.15); the holdout finds
home runs wanting less shrinkage and strikeouts wanting more. Pitcher home
runs use k=934 — a 600-batter pitcher keeps 39% of his own number — and that
is the specific suspect.

NOT SHIPPED YET: +2.0 sigma on one channel out of sample is at the bar, and
the change should be a home-run-specific constant rather than a global
factor. Recorded with the holdout numbers so the next session does not have
to re-derive the leak.

### The bases carry RUNNER IDENTITY — per-hitter attribution is now possible

`Frame.bases` held three booleans, so the model knew THAT a bag was occupied
and never WHO was on it. No run could be credited to whoever scored it or
drove it in, which is why "does Judge take the run share he should" was
recorded as unanswerable.

The bases now hold a runner TOKEN or None. Truthiness is unchanged so every
occupancy test reads the same; `sum(bases)` would add strings, so counting
goes through `_n`. `_advance` returns `(runs, scorers)` and `_credit` records
`StartResult.scored_by` and `.rbi_by`, which stay empty unless a batter is
passed. `game._half_inning` passes `side.lineup[slot].name`.

**BIT-IDENTICAL, verified in isolation**: fingerprint
f0778667206fe5ce57dba06fa4a432a2 before and after, 400 games x 6 sims. (The
earlier 5bdcf78e is pre-steal-table; that fingerprint moved for the steal
work, not for this.) Attribution populates: 18 distinct batters credited over
200 sims of one game.

THREE BUGS THE TEST SUITE CAUGHT, all of which would have changed the game
rather than just the bookkeeping:

  1. A batter who reaches must OCCUPY THE BAG EVEN IF UNNAMED. Writing
     `None` to first when no batter is passed DELETED him from the base
     state. `True` is the unnamed token — truthy for occupancy, skipped by
     attribution. The bases-loaded walk check failed immediately.
  2. `STEAL_TABLE` is keyed on boolean occupancy tuples, and `tuple(bases)`
     is now `('Judge', None, None)`, which matches no key — steals stopped
     happening entirely. Keyed on `tuple(bool(b) for b in bases)`.
  3. Tests comparing whole base states to `[False, True, True]` were
     asserting the TOKEN TYPE, not occupancy. They now go through `_occ`.

WHAT IS STILL MISSING: reliever lines are discarded on each arm change
(`cur_line = StartResult()`), so a whole-side per-batter tally needs the
lines merged before they are dropped. The starter's innings are covered,
which is most of them and matches how everything else here is scored.

### PITCHER-level differentiation — the cleaner test, and home runs are the finding

Prompted by the right question: differentiation of WHAT? The earlier slope
regression was per START — one row per starter-start, predicted mean against
actual outcome, 3,278 rows. That is MATCHUP differentiation, since a start's
prediction moves with the pitcher, the opposing nine, the park and the hook.
Calling it "pitcher differentiation" was sloppy.

The pitcher-level version collapses each arm to his mean predicted and mean
actual and regresses across pitchers. 181 with 8+ starts:

    ch        n  sd(pred)   MC sd  sd(true)   raw b  TRUE b  z vs 1
    er      181     0.244   0.074     0.232   1.313   1.448    +2.3
    h       181     0.457   0.084     0.450   1.302   1.347    +3.7
    hr      181     0.083   0.033     0.076   2.359   2.805   +10.0
    bb      181     0.372   0.052     0.369   1.135   1.157    +3.0
    k       181     1.023   0.080     1.019   1.116   1.123    +4.4
    outs    181     1.071   0.155     1.060   1.405   1.434    +6.5

**IT IS THE MORE TRUSTWORTHY MEASUREMENT.** Averaging 8+ starts per pitcher
cuts Monte Carlo noise by root-n, so the attenuation correction falls to
x1.02-x1.19 and the RAW slopes are already the answer. The start-level
version needed corrections up to x2.9, which is why its home-run number was
the softest thing in that table. Run the pitcher-level version first next
time.

**HOME RUNS ARE THE FINDING, AT +10 SIGMA.** The model separates pitchers on
home runs less than HALF as much as reality does. Three independent lines
agree on that one channel and no other: the start-level slope (most
compressed, 2.59), the pitcher-level slope (2.36 raw, minimal correction),
and the holdout shrinkage sweep (the only channel wanting LESS shrinkage,
+2.0 sigma).

The suspect is named: `STABILISE_MEASURED["pit"]["hr_pct"] = 934`. A pitcher
with 600 batters faced keeps 39% of his own home-run rate and takes 61%
league average. Every other channel is between 1.12 and 1.45 — real, but
ordinary — while home runs are 2.36.

NOT CHANGED YET. The right move is a home-run-specific constant validated on
the holdout, not a global factor, and the holdout gain for a 4x reduction was
+2.0 sigma, so the size is modest even though the compression is large. That
is consistent with home runs being a small share of runs.

---

## THE INVESTIGATION PROTOCOL — label these stages explicitly

Adopted 2026-08-27 after a day in which the same handful of mistakes cost
more than every measurement combined. Each stage below exists because
skipping it produced a specific wrong answer that day. Write the labels out;
the point is that a missing stage becomes visible.

### QUESTION

**State the quantity, the population and the unit of observation.** Not "does
handedness matter" but "does the opposing lineup's vs-hand strikeout rate
predict this starter's strikeout residual, per start, over 2026."

Today's failure: "does the model differentiate pitchers" was answered with a
regression over STARTS, which is matchup differentiation — a start's
prediction moves with the pitcher, the lineup, the park and the hook. The
pitcher-level version is a different regression and gave a different, cleaner
answer. Ambiguity in the question produced a confident answer to a question
nobody asked.

### HYPOTHESIS

**State it before running, name the CHANNEL you expect it in, and say what
would falsify it.** A mechanism has to be aimed somewhere.

Today's failures: handedness was screened on strikeouts when the effect, if
any, was on contact. Arsenal was aimed at strikeouts six times out of eight,
which is exactly where its double counting is worst. Both were "tested" for
years against the wrong channel.

### TEST

Four things, and each has burned a day here:

  * **STATE THE POWER FIRST.** If the run cannot resolve the effect size
    being looked for, it is a plumbing check — does the code run, do the arms
    differ, did the flag arrive — and its NUMBER IS NOT REPORTABLE. Four
    small-n results reversed on 2026-08-27, one of them stated flatly as a
    win two minutes before it flipped.
  * **NAME THE DENOMINATOR.** Per plate appearance, per ball in play, per
    opportunity-in-the-state-the-code-actually-rolls-in. Three denominator
    errors in one script that day, each producing a confident wrong table.
  * **POSITIVE CONTROL.** Amplify the effect 3-6x and confirm the harness
    sees it. A null on an unchecked instrument means nothing — arsenal had
    eight of those before anyone amplified it and found the harness fires at
    +113 sigma.
  * **LEAVE-ONE-OUT MECHANICALLY, NOT BY ARGUMENT.** A docstring reasoning
    the leak away is not a leave-one-out. In-sample handedness read +3.5
    sigma and went to -2.3 when the start left its own predictor.

### EVALUATE

  * **READ THE CONTROL BEFORE THE RESULT.** If it did not fire, stop.
  * **A UNIFORM PERCENTAGE ERROR ACROSS INDEPENDENT CHANNELS IS A
    DENOMINATOR**, never a set of rate bugs. Nothing moves strikeouts, walks,
    hits and home runs by the same 8%.
  * **DOES THE RESULT LOCALISE TO WHAT THE HYPOTHESIS NAMED?** The home-run
    slope of 2.36 was read as "pitcher home-run rates are over-shrunk", but
    the predictor is a simulation output combining the pitcher's rate, the
    nine batters' rates and the workload. It does not localise to the
    pitcher, and asserting that it did was inference presented as
    measurement.
  * **A MONTE CARLO MEAN CARRIES ITS OWN NOISE**, and noise in a regression
    PREDICTOR attenuates the slope. It is 55% of the predictor's variance at
    40 draws and ~2% of the residual's — ask which one the question is about.

### CONCLUSION

**Separate what is ESTABLISHED from what is INFERRED, in the same breath.**
And give the size in units that decide something — runs, or cents at the line
— not only in sigma. A +2 sigma effect worth 0.02 runs is not a finding.

Also: LEVEL errors ADD, SPREAD effects combine in QUADRATURE. Five 0.03-run
spreads make 0.067, not 0.15.

### NEXT STEPS

**Name the ONE test that would resolve the largest remaining ambiguity**, not
a list. If the conclusion contains an inference, the next step is the test
that would turn it into a measurement.

### AND THE RULE THAT PROMPTED ALL OF THIS

**WHEN A NEW NUMBER CONTRADICTS AN EARLIER ONE, DO NOT ACT. CHECK WHETHER
THEY MEASURE THE SAME THING.** On 2026-08-27 three positions were taken in
two minutes — home runs are over-shrunk, then the reliability measurement
says shrink harder, then a reporting bug — each pivoting on the newest number.
Two of those three were not in conflict at all: a split-half reliability of a
RATE and a regression slope on a SIMULATION OUTPUT are different quantities,
and the second does not refute the first. Thrashing between them looked like
rigour and was the opposite.

---

## DAY FOURTEEN (2026-08-28) — THE HOME-RUN COMPRESSION IS AN ARTIFACT, AND THE REAL FINDING IS STRIKEOUTS

### QUESTION

Where does the model's pitcher-level home-run compression come from? Day
thirteen measured a slope of 2.36 raw / 2.81 corrected at +10 sigma over 181
arms, against 1.12-1.45 on every other channel, and named
`STABILISE_MEASURED["pit"]["hr_pct"] = 934` as the suspect.

### CONCLUSION FIRST: THERE IS NO COMPRESSION. THE HARNESS MANUFACTURES IT.

**The slope is measured IN SAMPLE and that is fatal.** A pitcher's shipped
rate is computed over the same starts it is graded against, so his own
sampling noise sits inside the predictor AND inside the outcome. Write the
season line as `raw = T + u`, hand the model `w*raw + (1-w)*prior`, and
score it against `y = raw`:

    cov(x, y) = w (var T + var u) + (1-w) cov(prior, T)
    var(x)    = w^2 (var T + var u) + ...

so **the slope tends to 1/w even when the model is exactly right.** It
measures the shrinkage weight, not the baseball.

**POSITIVE CONTROL, and it fires** (`scratchpad/hr_spread.py --synth`).
Invent pitchers whose true rates are KNOWN, deal them a season of binomial
luck, apply the shipped shrinkage, grade them the same way:

    stat      shipped k     k*   mean w    1/w   synth b   OBSERVED
    k_pct           57      98    0.880   1.137    1.046      1.116
    bb_pct         138     289    0.754   1.326    1.168      1.135
    hr_pct         934     946    0.323   3.100    2.568      2.359

**A model that is right by construction scores 2.57 on home runs.** The
observed 2.36 is BELOW it. The channel ordering of the "defect" is the
ordering of 1/w, which is arithmetic and not a property of the model.

**`k*` IS THE OTHER HALF OF THE ANSWER.** Sampling variance over true
between-pitcher variance is the shrinkage constant the data asks for, and
for home runs it is 946 against a shipped 934 — 1.3% apart. And
`sd(ship)/sd(true) = 0.617` is what an optimal posterior mean SHOULD be
(sqrt of reliability = 0.574), not a defect. A posterior mean is less
variable than the truth by construction; that is the point of it.

**HOLDOUT AGREES.** `ceiling_holdout.json` regenerated with the hr channel,
rates trained before 2026-07-01, scored after:

    hr slope        in sample    holdout
      raw               2.359      0.302
      corrected         2.805      0.496   (z -0.8 vs 1)

CARRY THE CAVEAT: the holdout has only ~2 sigma of power against 2.36, and
out of sample the model's HR correlation is 0.029 against a ceiling of
0.262. This arm cannot carry the conclusion on its own. The positive control
does.

**PARK IS BOUNDED, NOT RESOLVED.** Pitcher-level residual against the mean
park factor of his own starts (home club home/road HR rate, 2023-2026, 31
parks, sd 0.116): slope 0.30 +/- 0.29 where a fully missing park predicts
0.72. Only 1.5 sigma from full strength, so the regression does not settle
it — but the MAGNITUDE does. Park at full strength supplies 0.038 HR of
across-pitcher spread against a 0.11 gap. It cannot be the main term either
way. Note `venue_id` is NULL for every pre-2026 game, which is why the
factor is keyed on the home club.

### THE PRIOR IS SHRUNK TWICE. RECORDED, NOT FIXED.

Found by asking the right question — home runs are RARE, but they are not
RANDOM, so where does a pitcher's multi-year homer identity go?

`_load_seasons` calls `raw = pitcher_rates(lg_prior, yr)`, which returns
rates **already shrunk toward the league**. `shrink_target` then shrinks
that result toward the league AGAIN with the same constant. Shrinking an
estimate twice toward the same mean discards evidence, and it bites in
proportion to `k`:

    stat        k    own now   pooled once    gain
    k_pct      57      0.969        0.943   -0.026
    bb_pct    138      0.894        0.883   -0.011
    babip     500      0.497        0.537   +0.040
    hr_pct    934      0.418        0.568   +0.151

"own" is the share of the shipped rate that traces to this pitcher rather
than to the league. **A pitcher's four-year home-run record arrives
flattened to a sixth of its real spread** (target sd 0.0012 against a raw
0.0073).

**IT IS HOME-RUNS-ONLY IN SIZE AND IT SITS UNDER THE FLOOR.** 15 points of
HR identity widens predicted HR-per-start spread by ~36%, which at ~1.45
runs a homer is **0.044 runs** of extra separation between arms, against a
0.05-run leverage floor. Real defect, one line to fix, will not measurably
score. Left alone deliberately rather than shipped on a day when the
strikeout finding was live.

### THE FINDING: PITCHER STRIKEOUT SHRINKAGE WAS 57 AND IS 132

The 57 was measured on half a season and never re-measured after the
four-season load. THREE INDEPENDENT LINES agree, which is why this is a
replacement and not a tuning:

    stabilise, split-half over 406 starters      132
    method of moments on the 2026 spread          98
    holdout discrimination peak, 57 x 2.3        131

**THE SWEEP IS A CONFIRMATION, NOT THE FIT.** `unshrink --only pit:k_pct
--holdout`, rates trained before the cutoff, scored after:

    k = 57 x     value    K discrimination vs shipped
      0.25         14        -0.0114  (-5.3)
      0.50         29        -0.0033  (-0.6)
      1.50         86        +0.0045  (+4.5)
      2.30        131        +0.0135  (+9.5)
      3.50        200        +0.0163  (+4.3)
      5.00        285        +0.0127  (+4.3)   outs breaks (-2.5)

Monotone, peaked where the split-half puts it, and REPLICATED on an
independent cutoff (2026-06-01, x2.0 at +2.6). Past x3.5 the K gain
flattens and OUTS degrades, so the peak is not an artifact of scoring one
channel.

**IT LOCALISES TO THE PITCHER.** The batter arm is flat (+0.3, +0.2, +0.7).
Sweeping both constants at once is what made the day-thirteen home-run claim
unattributable, and `--only` exists now so it cannot happen again.

**THE TELL THAT SHOULD HAVE CAUGHT IT YEARS AGO:** 57 is BELOW the imported
all-players constant of 70. That says a starter's strikeout rate stabilises
FASTER than a generic player's, which is backwards. Now guarded by
`check_pitcher_strikeouts_are_not_shrunk_at_the_stale_57`.

**SCORED ON WHAT SETTLES, and this is where the day nearly went wrong.** F5
CRPS, paired, cut 2026-07-01 (`scratchpad/kshrink_ab.py`):

    per salt, k=57:   1.62470  1.64669  1.66992  1.65650
    per salt, k=132:  1.63261  1.61747  1.66154  1.65317

    paired difference (132 - 57)   -0.00825 +/- 0.00777   z -1.1
    noise floor, one arm across salts                     0.01650

**THE FIRST PASS READ +0.0079 — WORSE — OFF SALT 0 ALONE, AND IT WAS ABOUT
TO BE REPORTED AS "the change damages the settling quantity".** Across four
salts the sign reverses and the honest answer is NEUTRAL, because the noise
floor is twice the effect. `fitf5.evaluate` carries a `salt` argument whose
docstring says exactly this and it was not used. A cheap run is for finding
bugs, never for deciding — three days running.

Neutral on F5 is the bar for a measurement replacing a stale value, so it
ships.

### WALKS AND HOME RUNS MUST NOT BE RAISED — AND THAT IS THE CONTROL

`stabilise` now reads 165 for bb_pct and 2130 for hr_pct against shipped 138
and 934. Neither was changed, because the outcome test disagrees:

    pit:bb_pct  x1.2 -1.6   x2.0 -2.4   x3.0 -2.7    monotonically worse
    pit:hr_pct  x2.0 -2.6                             worse

**If raising every constant had helped, the harness would be suspect.** It
does not: strikeouts gain, walks and home runs lose. That specificity is
what makes the strikeout result believable.

For home runs the three numbers — split-half 2130, method of moments 946,
outcome sweep says do not raise — do not agree, on a channel where a
starter's season is ~15 events. The rule applies: do not act until they are
shown to measure the same thing.

### TOOLING

    scratchpad/hr_spread.py        the four-part diagnosis; --synth is the
                                   artifact's positive control
    scratchpad/kshrink_ab.py       paired F5 CRPS across salts
    unshrink --only who:stat       sweep ONE population's ONE constant
    unshrink --factors a,b,c       arbitrary grid; 1.0 forced as baseline
    ceiling_holdout.json           regenerated WITH the hr channel; the old
                                   one predated it and is kept as
                                   ceiling_holdout_prehr.json

## DAY FOURTEEN, PART TWO — THE OFFENCE IS READABLE NOW, AND THREE ANSWERS

### ARE WE PREDICTING WHICH BATTERS PRODUCE THE OFFENCE? MOSTLY YES.

`scratchpad/offense.py`, holdout: rates before 2026-07-01, 531 games after
it, 9,369 batter-games matched to a boxscore line (98%).

**A. THE BATTING-ORDER MACHINE IS RIGHT.** Runs decline monotonically from
the leadoff man (0.581 predicted, 0.578 actual) to the ninth (0.402/0.375),
and RBI peak at cleanup in both (0.556/0.542). The residual sits entirely at
slots 6-9 and it is SUBSTITUTION: the model never pinch-hits, so its nine
absorb the 0.207 runs a game that really went to substitutes. Against the
whole offence the model is 1.4% light, which is the F5 decomposition's
number arriving from a completely different direction.

**B. WE OVER-SEPARATE HITTERS.** Regressing actual on predicted, Monte Carlo
attenuation undone (at 40 draws the noise is 56% of a batter-game's
predicted variance, so the raw slope of 0.290 is not reportable):

    unit             stat   sd(pred)   MC sd   raw b   TRUE b   z vs 1
    batter-game      r        0.1393  0.1043   0.290    0.659     -3.0
    batter-game      rbi      0.1643  0.1348   0.200    0.611     -2.4
    player (20+ g)   r        0.0690  0.0196   0.671    0.730     -1.9
    player (20+ g)   rbi      0.0733  0.0254   0.724    0.823     -1.0

**THE POSITIVE CONTROL IS QUANTITATIVE, not just directional.** Doubling
every hitter's spread around the league raises sd(pred) by x1.69, so the
slope must fall to 1/1.69 = 0.59 of itself. Measured 0.56. The instrument
sees between-hitter spread and is calibrated on it, so a slope of 1.0 would
have meant something.

### THE STALE BATTER CONSTANTS FIX B AND COST F5. NOT SHIPPED.

`stabilise` reads 51/122/193/250 against a shipped 32/80/160/184 — the same
staleness signature pitcher `k_pct` had. Every slope moves toward 1:

    unit             stat    shipped        measured
    batter-game      r      0.659 (-3.0)   0.748 (-2.1)
    batter-game      rbi    0.611 (-2.4)   0.775 (-1.3)
    player           r      0.730 (-1.9)   0.816 (-1.3)
    player           rbi    0.823 (-1.0)   0.888 (-0.6)

AND ON WHAT SETTLES, paired over four salts (`kshrink_ab --bat`):

    paired F5 CRPS (measured - shipped)   +0.01263 +/- 0.00687   z +1.8

Worse. Not significant, but the point estimate is the wrong way and it did
NOT reverse across salts the way the pitcher one did.

**SO THE STALENESS CLASS IS NOT AUTOMATIC, AND THAT IS THE LESSON.** Pitcher
`k_pct` was stale AND helped what settles. The batter row is stale and does
not. Re-measuring is necessary and not sufficient; every candidate still has
to clear F5. Both results can be true without contradiction — individual
hitters can be over-separated while the LINEUP AVERAGES that a team total
sees are right, and shrinking each hitter then removes lineup-to-lineup
spread that was correct.

### ADVANCEMENT RE-MEASURED ON 5x THE DATA — CONFIRMED, NOT STALE

754,886 plays over 9,974 cached games, against the 2,006 games the shipped
tables were counted on.

    live constant           shipped     measured      sigma
    ADVANCE_1B_ON_OUT  0      0.221        0.220       -0.3
                       1      0.239        0.233       -2.0
    ADVANCE_2B_ON_OUT  0      0.490        0.479       -1.8
                       1      0.439        0.444       +1.3
    ADVANCE_3B_ON_OUT  0      0.331        0.363       +3.6
                       1      0.420        0.417       -0.5
    FIRST_TO_THIRD_1B  0      0.307        0.292       -3.1
                       1      0.295        0.310       +3.5
    FIRST_SCORES_ON_2B 0      0.274        0.299       +2.9
    FIRST_SCORES_ON_1B 0      0.022        0.028       +2.7
    SECOND_SCORES_ON_1B       all three            within 1.0
    GIDP per ball-in-play-out                     within 2.0

Weighted by how often each state arises, the direct run effect of every move
together is **~0.01 runs per team-game** — a fifth of the leverage floor,
with the two FIRST_TO_THIRD moves partly cancelling. NOT CHANGED.

**THAT IS WORTH MORE THAN A FIX.** CLAUDE.md points at advancement as where
the model is wrong. The advancement RATES are right to within 0.01 runs on
five times the data, which removes a competing explanation and leaves the
clustering/shape diagnosis holding the whole gap.

**TWO COMPARISONS IN `advance.report` ARE AGAINST THINGS THAT DO NOT SHIP,
and one of them reads -41 SIGMA.** `RUNNER_ADVANCES_ON_OUT` is the LEGACY
path — `USE_MEASURED_ADVANCEMENT` is True and `_advance` takes the per-base
branch — so the "ANY runner advances on a ball-in-play out" row compares
measured reality against a constant nothing reads. The double-play row at
-103 sigma is the report's own labelled denominator switch. Both were one
step from being reported as blockbusters.

### CONCENTRATION: THE MODEL PUTS RUNS ON TOO FEW HITTERS

New question, answerable only because of today's wiring. HYPOTHESIS, stated
first: if plate appearances resolve too independently the model's runs will
be spread across MORE hitters than reality's, and the big individual game
will be missing. **The sign came out backwards.**

Matched on the team's run total, so level and concentration are not
confounded:

    team runs   n model   n act   top rbi m   top rbi a     diff
        3         5,921     163       1.695       1.607    +0.088
        4         5,442     129       2.044       1.992    +0.052
        5         4,767     113       2.380       2.265    +0.115
        7         2,948      61       2.916       2.689    +0.227
        8         2,205      57       3.143       3.070    +0.073

    pooled over 985 real team-games   +0.0719   z +2.7, 8 of 10 levels

P(a hitter drives in 4+) is 10.66% against 8.66%, 23% high.

TWO ALTERNATIVES CHECKED AND NEITHER CARRIES IT. Substitution: restricting
the real side to its top nine by plate appearances moves mean top RBI 1.923
-> 1.905. The RBI DEFINITION: MLB awards none on a double play or an error
and `_credit` awards one for every run on a batted event, so the model
should read high — 0.982 RBI per run against 0.978 for real starters, worth
about 0.02 of the 0.072.

**IT DOES NOT SUPPORT THE CLUSTERING DIAGNOSIS AT THE BATTER LEVEL** —
clustering predicts the opposite sign — so the team-total shape defect and
this concentration defect are, on the evidence, two different things.

NEXT: what SHARE OF RUNS scores on a home run, model against actual. RBI
concentrate when runs arrive in one swing instead of passing through several
hitters, and the channel decomposition has only ever checked home-run
COUNTS, never the share of runs they carry.

### THE SEED IS SHARED ACROSS GAMES AND IT INFLATES EVERY ABSOLUTE LEVEL

**FOUND BY TWO OF MY OWN NUMBERS DISAGREEING**, which is the only reason it
surfaced: mean team runs read 4.4732 over the first 20 draws and 4.3205 over
40, from the same engine on the same games. That looked like state carrying
across replays — a serious bug — and it is not.

`ceiling`, `offense` and the first `hr_share` all pass `seed=0` for EVERY
game. Draw *i* then sits at the same position in the random stream for all
of them, so the per-draw errors CORRELATE ACROSS GAMES and the effective
sample size is nowhere near n_games x n_sims. Measured, 60 games x 100 draws
in blocks of 20:

    same seed for every game    8.480 8.873 8.564 8.184 7.733   sd 0.385
    seed varies BY GAME         8.187 8.342 8.290 8.168 8.480   sd 0.113

**3.4x on the standard error, 11.6x on the variance.** It CANCELS in a
paired A/B — both arms use the same seeds, which is why `unshrink` and
`kshrink_ab` are sound, and `unshrink` varies its seed by game anyway. It
does NOT cancel in a LEVEL or a SHARE, and those are exactly what the new
offence measurements report.

Note `scratchpad/fingerprint.py` must NOT adopt per-game variation for its
own sake — it needs a STABLE seed, which is why it uses crc32 of the game id
rather than `hash()`. Stable and varying-by-game are the same fix here.

### WHAT SHARE OF RUNS ARRIVES ON A HOME RUN — NOT RESOLVED

The test that was supposed to separate the two mechanisms behind the rbi
concentration. HYPOTHESIS stated first: the model's home-run share of runs
is too HIGH, so its runs land in one swing on one batter.

    cut 2026-07-01, 531 games   model 43.06%  actual 41.53%   +1.53%  z +1.4
    cut 2026-05-15, 923 games   model 40.76%  actual 42.10%   -1.33%  z -1.6

**TWO WINDOWS, OPPOSITE SIGNS, NEITHER RESOLVING.** The share matches within
about 1.5 points and the direction is not stable. Sequencing-through-homers
is not established as the mechanism, and the pre-registered fallback — "then
it is the batter rates" — does not survive either, because those cost F5.
**The concentration defect stands with NO mechanism identified.**

THE FIRST RUN OF THIS SAID +3.86% AT z +3.5. That was the shared seed, and
it is the second time in one day the instrument rather than the model
produced the headline (the other being `advance.report` comparing against
legacy constants at -41 sigma).

### `mlb_batting` UNDERCOUNTS RUNS BY 1%

On the same 531 holdout games: summing the batting table's per-player runs
gives 4.3578 per team-game against 4.4030 from the games table's final
scores. The scores are authoritative, so about 1.0% of runs have no batting
row behind them. Every "actual" figure in `scratchpad/offense.py` is
understated by that much, and a team-game with missing rows lands in a lower
run bucket than it belongs in — which matters for the run-matched
concentration table, though not enough to move a +0.072 result.

### PITCHER BABIP WAS NEVER MEASURED. 500 -> 3068.

Found by continuing the staleness audit into the one constant with no
measurement behind it. `stabilise.report` printed a babip row for BATTERS
and silently omitted it for pitchers — no reason given anywhere — so the
shipped 500 was the legacy all-players import, the same class of number that
left `k_pct` at 57.

    STARTING PITCHERS
      stat     players  PA/half  r half  r full  k measured  IN USE
      babip        365      368   0.057   0.107        3068     500

A pitcher's balls-in-play rate barely repeats. That is the standing DIPS
result and the file ALREADY ENCODES IT NEXT DOOR: `PRIOR_DECAY["babip"] =
0.0`, measured separately, says a BABIP is worth nothing a year later. The
shipped 500 was inconsistent with a constant twenty lines above it.

**THE POINT ESTIMATE IS SOFT AND THE DIRECTION IS NOT.** At r_half 0.057
with a standard error of 0.052 over 365 arms, k spans roughly 1,500 to
36,000 across ONE standard error:

    r_half 0.005 -> k 36,616   a starter keeps  0.9% of his own babip
    r_half 0.057 -> k  3,044                    9.8%
    r_half 0.109 -> k  1,504                   18.0%
    shipped k 500                              39.8%

Every value consistent with the data is at least 3x the shipped one, and the
split half SHARES park, defence and teammates between its halves, which
inflates the correlation — so the true-talent constant is higher still. It
is a direction, not a knife edge, and it must not be re-tuned to a decimal.

SCORED. F5 CRPS +0.0011 +/- 0.0034, neutral, which is the bar for a
measurement replacing a guess. Discrimination, holdout, `unshrink --only
pit:babip`: hits FLAT (-0.1) and home runs +0.0254 (+3.2 sigma), monotone
across x2, x4, x6.1. The flat hits row is worth carrying — that is the
channel babip drives most directly and it says the gain is not where the
mechanism predicts.

### AND THE BATTER BABIP NUMERATOR WAS WRONG

`measure(_rows(_BAT), {"babip": "h"}, ...)` used H as the numerator against a
denominator that excludes home runs. BABIP is (H - HR) / (AB - K - HR). With
the numerator corrected the batter figure moves 250 -> 447 and r_half 0.407
-> 0.277 — the contamination made a hitter's balls-in-play rate look 79%
more reliable than it is.

**THIS INVALIDATES ONE ARM OF TODAY'S EARLIER TEST.** The batter-row A/B
that lost on F5 used 51/122/193/**250**, and the honest measured row is
51/122/193/**447**. The babip element was wrong in the direction of too
little shrinkage. Re-run before concluding anything about the batter
constants.

### A TEST THRESHOLD THAT WAS SECRETLY A FUNCTION OF THIS CONSTANT

`check_the_rates_neutralise_defence_out_of_the_observed_babip` asserted the
stored gap was `> 0.002`. That number was implicitly calibrated to k=500 —
it produced 0.0026 and was only just clearing its own bar — so raising the
constant failed a check whose mechanism was working perfectly. The gap that
survives into a stored rate is the delta times the SHRINK WEIGHT, so the
check now derives what it expects from the shipped constant and pins it
exactly. Verified by mutation on `bullpens`, which is the call site it
actually exercises — the first mutation attempt patched `pitcher_rates` and
passed, because this check has never gone near it.

### THE CONCENTRATION FINDING IS RETRACTED

Re-run with per-game seeds, and with RUNS SCORED beside rbi because an rbi
depends on who happened to be on base ahead of the hitter:

                          before seeding fix    after      run levels
    top RBI                  +0.072 (z +2.7)  +0.057 (z +2.1)   9/9 positive
    top RUNS SCORED                  not run  +0.025 (z +1.1)   5/9 mixed

**ON THE NON-ARBITRARY STAT THERE IS NOTHING.** And the residual rbi gap has
a known cause that is not a modelling defect: `_credit` awards an rbi for
every run on a batted event where MLB awards none on a double play or an
error, measured at 0.982 rbi per run against 0.978 for real starters — worth
0.008 to 0.031 on a 1.92-rbi top hitter, a large fraction of what is left.

"The model puts runs on too few hitters" is WITHDRAWN. The other two
findings survive the reseeding unchanged: the batting order is right, and
hitters are over-separated (player-level slope 0.722 on runs, z -2.2).

### THE BATTER-ROW A/B, RE-RUN AT THE CORRECTED BABIP — BOTH EARLIER CLAIMS VOID

The first run used `babip: 250`, which the broken numerator produced. The
honest row is 51/122/193/**447**. Re-run, both arms sharing the new pitcher
babip of 3068:

    paired F5 CRPS (measured - shipped)
      babip 250 (broken)      +0.01263 +/- 0.00687   z +1.8   worse
      babip 447 (corrected)   -0.00264 +/- 0.00745   z -0.4   neutral

    differentiation           shipped        measured(447)
      batter-game  r        0.624 (-3.6)    0.638 (-3.2)
      batter-game  rbi      0.691 (-2.1)    0.583 (-2.5)   worse
      player       r        0.722 (-2.2)    0.711 (-2.1)   flat
      player       rbi      0.758 (-1.5)    0.880 (-0.7)   better

**BOTH OF THE MORNING'S CONCLUSIONS WERE THE BROKEN NUMERATOR.** "The batter
constants cost F5" is void — it is neutral. And so is "they fix
differentiation": that was four-of-four toward 1 and is now two better, two
worse. The row SHIPS anyway, on the same standard pitcher k_pct was held to
— a measured value replacing a stale one, neutral on what settles — and it
buys nothing measurable.

Unlike the pitcher figure, 447 is WELL DETERMINED: r_half 0.277 over 662
hitters puts k between 371 and 550 across one standard error, with the
shipped 184 far outside it.

### A STALE .pyc SURVIVED A MUTATION RESTORE, AND IT COULD HAVE POISONED ANY OF THIS

`make test` failed asserting `babip == 184` while the source on disk read
447, and the imported module carried 51/122/193/**184** — three of four keys
updated and one not, from a single-line edit that changed all four.

CPython validates a cached `.pyc` on **(mtime, size)**. The mutation loop
wrote `447 -> 184`, ran the suite (which wrote the bytecode), then restored
`184 -> 447` WITHIN THE SAME SECOND and with the SAME BYTE COUNT — three
digits either way. Both checks passed, so the mutated bytecode was reused
and every later run tested the MUTATED constant.

**THIS IS A HAZARD FOR THE PROJECT'S CORE METHOD.** Verifying a test by
mutation means editing a constant and putting it back, and a same-second
same-size restore is exactly the case Python cannot detect. The failure mode
is silent and it points the wrong way — the mutation itself fails correctly,
and it is everything AFTER the restore that is quietly wrong.

Mitigation when mutating by script: clear `__pycache__` after restoring, or
keep the byte count different, or `sleep 1`. `scratchpad/mutate.py` refuses
to run on a dirty tree, which is a different guard and does not cover this.

### THE DOUBLE-SHRUNK PRIOR — FIXED, SCORED, AND IT LOSES

The defect is real and was written up this morning: `_load_seasons` calls
`pitcher_rates`, which returns rates ALREADY shrunk toward the league, and
`shrink_target` shrinks them again with the same constant. Built behind
`USE_RAW_PRIOR`, which reaches the prior — home-run spread across 2,068 arms
goes 0.00159 double-shrunk to 0.05048 raw.

    paired F5 CRPS, 25 sims x 4 salts, cut 2026-07-01
      per salt, shipped      1.64694  1.62432  1.63189  1.65550
      per salt, shrunk once  1.64780  1.63044  1.64751  1.67064
      paired difference      +0.00944 +/- 0.00359   z +2.6, 4/4 positive

**HYPOTHESIS WAS NEUTRAL AND THE FALSIFIER WAS NAMED IN ADVANCE:** "a clear
loss would say the double shrink is absorbing a real defect somewhere else,
which is worth knowing before shipping." That is what happened.

**THE DOUBLE SHRINK IS WRONG AND EMPIRICALLY BETTER, SO IT IS COMPENSATING
FOR SOMETHING.** The candidate is `_blend_priors` setting the prior's `pa`
to the raw sum of decayed plate appearances. That OVERSTATES its predictive
weight: a season-old rate is worth less than its sample implies once talent
has had a year to move. `PRIOR_DECAY` already discounts the RATE for exactly
that and NOTHING DISCOUNTS THE SAMPLE, so the second shrink was standing in
for the missing discount.

So the fix is not this one. It is to shrink ONCE against a DISCOUNTED
effective sample, and the size of that discount has never been measured.
Kept switchable with the negative recorded rather than deleted, because the
defect it names is real and the replacement is a measurement away.

**AND IT IS A CLEAN INSTANCE OF THE RULE THAT MATTERS MOST HERE.** A
correctness argument said the change had to be right. The score said
otherwise, and the score is what settles. Reasoning from construction alone
would have shipped a 2.6-sigma regression on the stated product.

### SUBSTITUTION IS 0.033 RUNS, NOT 0.207. AND THE REAL NUMBER IS BETTER.

**THE 0.207 FIGURE QUOTED TWICE TODAY WAS WRONG.** It came from subtracting
the slot table's actual column (the nine the MODEL simulated, matched to a
boxscore row) from every batter's runs — two different populations, and 151
of 9,520 simulated batter-games had no boxscore line at all. Counted
properly on 1,062 team-games:

                        PA/game   runs/game   runs per PA
    all batters           36.90       4.358        0.1181
    top 9 by PA           35.41       4.214        0.1190
    substitutes            1.49       0.144        0.0967

Substitutes take 4.0% of plate appearances and are 19% worse per one, so
what the model loses by never pinch-hitting is 0.04 x 0.19 x 4.36 =
**0.033 runs a team-game**. Under the floor. CLOSED.

### THE MODEL SENDS EXACTLY THE RIGHT NUMBER OF MEN TO THE PLATE AND SCORES 3% FEWER RUNS

`Side.pa_faced` and `GameResult.away_pa`/`home_pa` exist now — the
DENOMINATOR, folded across arms like everything else. Holdout, 531 games:

                             PA/game   runs/game   runs per PA
    model (its nine)           37.64       4.229        0.1124
    actual, `ab + bb`          36.90       4.358        0.1181
    actual, PA corrected       37.64       4.358        0.1158

**AND THE CORRECTION IS THE POINT.** `mlb_batting` carries `ab` and `bb` and
NOT hit-by-pitch or sacrifices, both of which are plate appearances. Counted
— 0.410 hbp per team-game from `mlb_pitching`, 0.329 sacrifices at the
measured starter rate — that is 0.738, or **2.00% of the 36.90 the column
can see**. The model's apparent plate-appearance excess was **+1.99%**.

So the model's opportunity is EXACT and it converts 2.96% worse. That is the
full-game version of `f5_decomp`'s finding — the right men on base through
five, 1.7% fewer brought home — and it is about 0.13 runs a team-game,
2.6x the leverage floor.

**FOURTH NEAR-MISS OF THE DAY, AND THE SAME RULE EVERY TIME.** "+2% more
plate appearances" would have been a confident finding built on two missing
boxscore columns. The others: a -41 sigma advancement row against dead code,
a +3.5 sigma home-run share that was a shared seed, and a single-salt F5
read with the wrong sign. NAME THE DENOMINATOR.

### WHERE THE RUN GAP LIVES — NOT THE BULLPEN, AND THE SEASONAL PART IS A QUARTER OF WHAT IT LOOKED LIKE

QUESTION: the model sends the right number of men to the plate and scores
fewer runs. Where? `f5_decomp` put the starter's first five at 1.7% light
and the full game at 3.0%, which would put ~70% of the gap in innings 6+.

**HYPOTHESIS REFUTED. THE GAP IS UNIFORM BY INNING.** Both halves counted
the same way — all arms, split at the fifth, model against actual on the
same games (`scratchpad/where_runs.py`, cut 2026-05-15, 1,846 team-games):

    split           model   actual     gap      se     z      rel
    innings 1-5     2.291    2.485   -0.194   0.056  -3.5    -7.8%
    innings 6+      1.820    1.982   -0.161   0.052  -3.1    -8.1%
    whole game      4.111    4.466   -0.355   0.077  -4.6    -8.0%

The F5-versus-full-game arithmetic that motivated this was comparing
STARTER innings through five against EVERY inning and every arm. Two
populations. Relief carries its proportional share and no more.

**POWER IS THE BINDING CONSTRAINT ON ALL OF THIS.** A team-game's runs have
sd 3.22, so 1,062 team-games give se 0.099 — and the full-game gap at the
July cut is 0.174. **The headline was 1.7 sigma.** Resolving a gap this size
at 2 sigma needs ~2,500 team-games.

**THE FIRST INNING IS UNDER-SCORED, WHICH REVERSES AN OLD DEFECT.** Runs by
inning, both teams, 923 games:

    inning    model   actual      gap      se      z      rel
         1    0.883    1.018   -0.136   0.050   -2.7   -13.3%
         2    0.843    0.909   -0.066   0.047   -1.4    -7.3%
         3    0.941    0.998   -0.057   0.048   -1.2    -5.7%
         ...
     total    8.222    8.933   -0.711   0.152   -4.7    -8.0%

Reality's first inning is its HIGHEST-scoring (1.018 against a 0.993 average
for innings 2-8) because the top of the order is guaranteed to bat. The
model's is its LOWEST (0.883 against 0.936). The batting order is not the
cause — the model starts at the leadoff man. CANDIDATE, UNTESTED:
`TTO_MULT`. Inning 1 is entirely first-pass and innings 1-3 decline
monotonically at -13.3%, -7.3%, -5.7%, which is the shape an over-strong
first-pass penalty makes.

**A SIXTH INSTRUMENT ARTIFACT: the ninth inning first read -58.9%.**
`simulate_game` breaks out when the home team leads after the top of the
ninth — correctly, that half is not played — and that break happens BEFORE
the `if inning in track` block, so `prefix_side[9]` is never set for those
games and the top of the ninth, which WAS played, counts as zero. Take
innings 9+ as the residual against the final score.

### THE MODEL HAS NO SEASONAL VARIATION, AND TWO THINGS WERE CONFOUNDED

**RATE FRESHNESS IS CLEAN — same games, only the training window moves:**

    game month     model @ May cut    model @ July cut    change
    2026-07              4.100              4.202          +2.5%
    2026-08              4.136              4.255          +2.9%

Thinner rates shrink harder toward the league, spread comes out of the
lineup, and runs are CONVEX in that spread. So the model under-scores in
proportion to how little it knows — which is worst in April and May, exactly
when a live board is hardest to price.

**THE CALENDAR HALF WAS MOSTLY ONE SEASON'S NOISE, AND THE CHECK THAT FOUND
IT WAS "does it repeat across years".** Within the May cut the model's output
is flat to 0.9% across four months while 2026's actual swings 9.6% — which
read as a seasonal term worth up to 0.4 runs, eight times the leverage floor.
Centring each season on its own mean and pooling four seasons:

    month     2023     2024     2025     2026     mean     se     z     rel
    04      +0.020   -0.116   -0.124   +0.071   -0.037  0.049  -0.8   -0.8%
    05      -0.057   -0.170   -0.142   -0.169   -0.134  0.027  -5.0   -3.0%
    06      -0.075   +0.046   -0.008   +0.208   +0.043  0.060  +0.7   +1.0%
    07      +0.026   +0.147   +0.048   +0.024   +0.061  0.029  +2.1   +1.4%
    08      +0.085   +0.092   +0.226   -0.134   +0.067  0.075  +0.9   +1.5%

    shape correlation   2023/2024 +0.43  2023/2025 +0.68  2024/2025 +0.81
                        2023/2026 -0.38  2024/2026 +0.25  2025/2026 -0.17

**WHAT SURVIVES IS MAY, at -0.134 runs and -3.0%, negative in all four
seasons.** July is mildly high. **2026's OWN PROFILE DOES NOT REPLICATE** —
it anticorrelates with 2025 and 2023, and its June +0.21 and August -0.13,
which produced the whole "9.6% swing", appear in no other year.

So the real seasonal term is 0.13-0.20 runs, a QUARTER of what one season
suggested, and still 2.7x the leverage floor. **MONTH DUMMIES ARE THE WRONG
CONSTRUCTION** — fitted on 2026 they would fit noise. A TRAILING-WINDOW
league baseline picks up the May trough without a month model and handles
year-to-year level drift for free. That is the version to test.

MARCH IS EXCLUDED THROUGHOUT: 146 games in 2026 and a +0.516 outlier in
2024. Four days of opening-day pitching is not a seasonal effect.

### THE SEASON IS A HOME-RUN EFFECT, IT REPLICATES, AND IT CLOSES THE RUN GAP

**BUILT AGAINST MY OWN RECOMMENDATION AND THE RECOMMENDATION WAS WRONG.** I
measured the seasonal term on RUNS, found only May replicating, and advised
against month dummies. Runs DILUTE a channel-specific effect. Measured on the
home-run channel it is large and it replicates:

    HR per batter faced, each season centred on its own mean
    month     2023     2024     2025     2026     mean     se     z
    04      0.9536   0.8844   0.8906   0.9183   0.9117 0.0158  -5.6
    05      0.9690   0.9157   0.9531   0.9319   0.9424 0.0117  -4.9
    06      0.9669   1.0164   1.0059   1.1398   1.0322 0.0374  +0.9
    07      1.0323   1.1032   1.0551   1.0651   1.0639 0.0148  +4.3
    08      1.0782   1.0803   1.0952   0.9450   1.0497 0.0351  +1.4

    shape correlation  2023/2024 +0.82  2023/2025 +0.90  2024/2025 +0.95
    pooled April vs August HR/BF   0.02789 -> 0.03222   +15.5%

Strikeouts move a little (0.98-1.04) and BALLS IN PLAY ARE FLAT (0.996-1.004),
so this is a carry effect and not a general offence effect. That is why the
runs-by-month analysis was noisy and the channel version is not.

**NEUTRALISE THEN APPLY, the pair park taught this project.** A rate already
contains the months it was earned in, so the factor applied is the game's
month over the training window's exposure-weighted mix. Trained before
2026-07-01 that mix is hr 0.9498 — cold — and a July game asks for 1.0639,
so the applied factor is 1.1204. Cold rates, hot games, in EVERY holdout
this project runs.

**SCORED OUT OF SAMPLE — factors from 2023-2025, applied to 2026:**

    arm                 model   actual      gap      rel
    month OFF           4.229    4.403   -0.174    -3.9%
    month ON            4.432    4.403   +0.029    +0.7%
    paired change      +0.2031 runs per team-game (se 0.0235)

**IT CLOSES THE RUN-LEVEL GAP.** Largest single correction found on
2026-08-28.

**THREE THINGS THAT MUST HAPPEN BEFORE IT SHIPS.**

  1. IT IS A LEVEL RESULT, NOT CRPS. A flat correction that fixes the level
     and nothing else is precisely what the dispersion term did — calibration
     moved, discrimination did not, and it ships inert. `fitf5.evaluate` does
     not accept a park, so the F5 test needs a small change there.
  2. EVERY SCORED MONTH HERE HAS A FACTOR ABOVE 1, so the correction only
     ever ADDS runs and the model was light. It could be closing the gap for
     a cheap reason. The falsifier is a window where the factor is BELOW one
     — rates trained hot, games played cold — which needs prior-season rates
     against 2026 April-May.
  3. WALKS HAVE NO PARK SLOT, so a month's walk deviation is not applied.

**AND IT REFRAMES THE PITCHER HOME-RUN RELIABILITY CONTRADICTION.** Three
numbers disagreed — `stabilise` 2130, method of moments 946, the outcome
sweep saying do not raise it. A seasonal swing this large adds variance to a
pitcher's observed HR rate that is NOT talent: an arm who threw more of his
innings in April looks like a low-homer pitcher. Method of moments counts
that environment as talent and is therefore biased LOW, which is the
direction of the disagreement. Re-measuring reliability on month-adjusted
rates is the test that would reconcile them.

**IT ALSO CONTAMINATES EVERY LEVEL REPORTED TODAY.** Each holdout trains
April-June and scores July onward, so a ~10% home-run understatement sits
inside all of them. The paired A/Bs cancel it; the levels do not.

## DAY FIFTEEN (2026-08-29, overnight) — WHAT PRICING A REAL CARD EXPOSED

The session began as a pricing request, not a modelling one: nine bets on
the 2026-08-28 board. Everything below came out of that, which is the
argument for pricing live boards more often — three of these were invisible
from inside the measurement scripts.

### THE CACHE WRITES WERE NOT ATOMIC — FIXED, SHIPPED, GUARDED

QUESTION    Two runs of the same 20,000-sim card produced SF 0.551 and
            0.563 for the same game with the seed bound. Which input moved?
HYPOTHESIS  Not the RNG — `simulate_slate_game` builds `random.Random(seed)`
            and is deterministic. Something read a different cache.
TEST        Verified determinism first: three separate processes returned
            0.5638 to four decimals with identical lineups, so the engine
            was exonerated before anything was changed. The differing run
            was the one that had raced a concurrent `src.context.price`.
            POSITIVE CONTROL — a standalone repro, 3 readers against 1
            writer for 3 seconds.
EVALUATE    `Path.write_text` TRUNCATES and then writes, so a concurrent
            reader observes a partial file. 25,691 of 76,076 reads (33.8%)
            were torn; with `os.replace` it was 0 of 105,020. And the
            symptom is not a crash: `sources/*._cached` CATCHES
            `JSONDecodeError` and falls through to a LIVE REFETCH, so two
            processes silently disagree about the data instead of failing.
CONCLUSION  ESTABLISHED and fixed. `src/context/atomic.py`, 14 call sites
            across 12 modules. Five checks in `tests/test_atomic.py`,
            mutation-verified BOTH WAYS: reverting the writer fails
            `check_concurrent_readers_never_see_a_partial_cache` (11,733
            torn reads), reverting ONE source file fails
            `check_every_cache_writer_goes_through_atomic` and names the
            line. Suite 398 passed, 0 failed.
NEXT STEPS  None. This one is closed.

**THE TRANSFERABLE PART: a caught exception that falls back to a refetch
converts a crash into an irreproducibility.** The cache layer was written
to be robust to a truncated file from an interrupted run, and that
robustness is exactly what hid a concurrency bug for as long as it existed.
A pricing tool whose numbers do not reproduce is worse than one that fails.

### THE STRIKEOUT TAIL IS TOO THIN — MEASURED, AND IT IS A BETTING HAZARD

QUESTION    Does the shipped engine reproduce the STARTER'S OWN outs and K
            distribution? Unit of observation: one real start. This is the
            settled quantity for a prop, and `f5_decomp` measures a FIXED
            five-inning window instead, so it cannot see a hook defect.
HYPOTHESIS  Stated from the live board: `price.py` ran a mean SIGNED gap of
            -0.036 over 142 markets, i.e. the model sits below the market
            almost everywhere. Either the market is wrong in one direction
            all day, or the model's distributions are too narrow.
TEST        `scratchpad/shape.py`. 537 holdout games / 1,074 starts, rates
            AND the league baseline frozen before 2026-07-01, starts scored
            on or after it. 40 sims each. POWER PRINTED BEFORE THE TABLE:
            the ACTUAL side is binding at n=1,074, se 0.014 on boundary
            share, 0.124 on mean outs, 0.076 on mean K.
EVALUATE    The LEVELS are right and the SHAPE is not.

    quantity            model    actual      gap
    mean outs           15.95     15.82    +0.13   (1.0 se — fine)
    sd outs              4.01      4.04    -0.03
    boundary share       0.598     0.669   -0.071  (5.0 sigma)
    mean K               4.86      4.84    +0.02   (exact)
    sd K                 2.23      2.49    -0.26

            And it LOCALISES, which is what makes it actionable. sd(K|outs)
            by length bucket, gap against actual:

    outs        0-8    9-11   12-14   15-17   18-20   21-27
    sd gap    +0.14   -0.03   +0.06   -0.23   -0.20   -0.36
    se         0.13    0.13    0.10    0.09    0.09    0.17

            The short starts are FINE. The missing dispersion is entirely in
            long starts. And the conditional MEAN gives the mechanism:
            E[K|21-27] is 6.07 for the model against a real 6.84.
CONCLUSION  **ESTABLISHED: real long starts are EARNED by missing bats and
            the model's are not.** Counted rather than asserted — K per 27
            outs, within bucket, model against actual:

    bucket    mean outs   K/27 model   K/27 actual
    15-17         15.6         8.42          8.33
    18-20         18.4         8.05          7.98
    21-27         21.8         7.51          8.49
    all           16.0         8.22          8.26

            The model's K rate DECLINES MONOTONICALLY with length — 8.42,
            8.05, 7.51 — which is what times-through-the-order plus a pitch
            budget produces. Reality declines and then JUMPS: 8.33, 7.98,
            **8.49**. A real seven-inning start is a SELECTED population and
            the model has no selection at all, so its longest starts are its
            lowest-K ones and reality's are its highest.

            `PITCH_COST` charges 4.97 pitches for a strikeout against 3.25
            for an out, so in the model a high-K night actively SHORTENS the
            start. Real managers let a dominant arm go deep anyway. Note the
            two middle buckets are right to within 0.1, so this is not a
            level error smeared across the range — it is the top bucket
            alone, which is where the o8.5+ mass comes from.

            **This replicates day nine exactly on a changed engine**: 6.07
            here against 6.08 then, actual 6.84 against 6.70. Two seasons of
            engine changes did not touch it.

            SIZE, IN CENTS, which is the part that matters: at o8.5 the
            model says 0.060 where reality is 0.095 (-3.9 sigma), at o9.5
            0.027 against 0.046, at o10.5 0.011 against 0.023. **It prices a
            high-K over at ~60% of its true probability.** The correction
            table is now item 0 of the operator's page.
NEXT STEPS  The hook, not the rates. If length were conditioned on how the
            night is actually going rather than on pitch count alone, the
            selection would appear for free. `PITCH_COST` making strikeouts
            expensive is the specific suspect and it is measurable.

### THE PER-START SHARPNESS TERM — PRE-REGISTERED, FALSIFIER HELD, NOT SHIPPED

QUESTION    `scratchpad/dispersion.py` already draws a per-start latent
            quality (K down, walks/homers/contact up on a bad night). It
            applies `stop_after=5`, so it has ONLY ever been scored on F5
            RUNS, where it is CRPS-neutral. It has never been scored on the
            starter's own line — the quantity above.
HYPOTHESIS  Registered BEFORE running, with the channel and the falsifier:
            the term should reproduce SELECTION, not spread. A sharp night
            means fewer baserunners, fewer pitches, a longer start AND more
            strikeouts. So sd(K) must widen in the LONG buckets and NOT in
            the short ones, where it already matches within a standard
            error. **Uniform widening falsifies it** — that is dispersion
            bought for nothing, which is what the early-exit mixture and the
            `early_innings` branches were each rejected for.
TEST        Sigma 0.00 / 0.05 / 0.10 / 0.15 / 0.20, full holdout, paired by
            construction: same games, same seeds, both latent draws taken at
            the same stream position so sigma=0 consumes them too.
            POSITIVE CONTROL at sigma 0.40 — K sd 2.23 -> 3.17, outs sd
            3.92 -> 5.08, so the perturbation is genuinely wired through.
EVALUATE    The falsifier HELD through 0.15 and begins to fire at 0.20
            (the 12-14 bucket over-widens to +0.12). Everything aimed at
            moved monotonically toward truth:

    sigma   K sd   o8.5   o9.5  E[K|21+]  outs sd    bnd
    ACTUAL  2.49  0.095  0.046      6.84     4.04  0.669
     0.00   2.22  0.059  0.026      6.07     4.02  0.596
     0.10   2.28  0.066  0.030      6.21     4.08  0.595
     0.20   2.45  0.083  0.042      6.67     4.32  0.586

            AND THE PAIRED TEST IS A WASH. Per-start CRPS, paired:

    sigma    dK CRPS      se      z     dOUTS CRPS      se      z
     0.05    -0.0027  0.0057  -0.47        -0.0080  0.0092  -0.87
     0.10    -0.0132  0.0072  -1.83        +0.0169  0.0118  +1.43
     0.20    -0.0174  0.0088  -1.98        +0.0309  0.0146  +2.11

CONCLUSION  **NOT SHIPPED.** The K gain and the outs loss are the same size
            and cancel, and it degrades the outs distribution, which is
            already the weaker half. Neither column clears 2.1 sigma.

            SEPARATING ESTABLISHED FROM INFERRED: it is ESTABLISHED that
            the term closes 78-85% of the K tail and dispersion gap with the
            widening in the right buckets. It is ESTABLISHED that it costs
            an equal amount of outs CRPS. It is INFERRED, and NOT measured,
            that shipping it would improve prop pricing — CRPS is dominated
            by the bulk where the model is already right, so a tail repair
            cannot show up there, and a TAIL prop is priced on calibration
            rather than on discrimination. That inference is exactly the
            reasoning that would need a pre-registered prop-calibration
            harness to test, and there is not one.
NEXT STEPS  Do NOT re-run this sweep. The term is a symptom-level patch on
            a mechanism defect that is now named: the hook does not
            condition length on how the night is going. Fix the cause and
            the selection is free; keep patching the symptom and it costs
            outs every time. `PITCH_COST` is the first place to look.

### THE DENOMINATOR RETRACTION, AND IT WAS MINE, LIVE, THE SAME NIGHT

I told the user the model compressed Reid Detmers to 27.6% K against "his
card's 30.8%" and built a three-row sensitivity table on it. **That gap does
not exist.** The card is K PER AT-BAT; `k_pct` is K PER PLATE APPEARANCE.
Counted from the pipeline DB on his 25 starts: 162 K, 580 PA, 531 AB —
0.2793 per PA and 0.3051 per AB. His raw per-PA rate is 0.2812 and the
shipped value is 0.2761, which is ordinary shrinkage at 576 batters faced
with k=132. The model is not compressing him.

**AND THE DOUBLE-SHRUNK PRIOR IS NOT THE K PROBLEM EITHER**, which is worth
recording because it was the standing lead. The retained-fraction table says
k_pct goes 0.969 shipped against 0.943 pooled-once — a 2.6% effect, where
home runs are 0.418 against 0.568. Any K-input story that leans on the
double shrink is leaning on 2.6%. The measured K defect is 10% of the
distribution's spread and lives in the joint with length, not in the rate.

VERIFIED SEPARATELY AND CLEAN: the PA denominator inside the code is
consistent. `rates._PITCHER_Q` and `sim._SP_Q` both build `bf = outs + h +
bb`, so hit-by-pitch and reached-on-error are missing from BOTH and the
~1.6% understatement cancels in the log5 ratio. `sim.league`'s docstring
already records the day this did NOT cancel and what it cost. Not a defect;
checked rather than assumed.

### WHAT WAS NOT DONE, AND WHY IT IS THE NEXT THING

The boundary share is 0.598 against a real 0.669 and it is 5.0 sigma. The
mass table says where: the model is 5.8 points short at exactly 18 outs —
six innings, which is the single most common real outcome at 24.4% of
starts — and long at 11, 14 and 20. **Reality ends starts at the end of an
inning and the model ends them in the middle of one.** It is the same defect
family as the K finding (the hook is not conditioned on the right things)
and it is the largest single unexplained number now on the board. It also
means the model sends TOO MANY starters past the sixth: o18.5 0.224 against
an actual 0.173, o20.5 0.153 against 0.119.

## DAY FIFTEEN, PART TWO — FOUR STRUCTURAL QUESTIONS FROM THE USER

All four came from reading the pipeline description rather than the code,
which is worth noting: three are real and none had been looked at.

### EXTRA INNINGS ARE PLAYED UNDER THE PRE-2020 RULES — REAL, UNFIXED

`sim.Frame.__post_init__` sets `bases = [None, None, None]` on every
half-inning with no exception for the tenth. There is no automatic-runner
code anywhere. MLB has started each half-inning from the tenth with a
runner on second since 2020, permanently since 2023.

**AND THE RULE IS PLAINLY VISIBLE IN OUR OWN DATA**, which closes the loop:
counted off the 2026 line scores in `games.away_innings`/`home_innings`,

    games past nine            167 of 2,006   (8.3%)
    mean innings in those      10.34
    runs per EXTRA half        1.049   (448 halves)
    runs per REGULATION half   0.498   (35,207 halves)

**A real extra half-inning scores 2.11x a regulation one.** The model
produces a regulation one there, so it is short about 0.55 runs on every
extra half it plays — and it plays MORE of them, because a scoreless
inning is far likelier starting from empty than from second.

SIZE AND SCOPE: ~0.12 runs per game on the FULL-GAME TOTAL, concentrated
entirely in the 8.3% of games that go long, where it is ~1.1 runs light.
**It cannot touch F5 or a starter's line.** It is a full-game total and
moneyline defect only — which is exactly the pair that has never been
scored against a settled price, so it would not have shown up anywhere.

Note also `max_extra=9`: a game still tied after the eighteenth is returned
as a TIE. Rare, but real MLB has none.

### THE PLATE APPEARANCE IS BLIND TO THE BASE-OUT STATE — AND THIS IS THE
### CLUSTERING MECHANISM THE PROJECT HAS BEEN LOOKING FOR

QUESTION    The user asked whether resolving steals/wild pitches/passed
            balls AFTER the plate appearance is incongruous, since they
            really happen during it.
EVALUATE    The REORDER itself is nearly a no-op, and saying so matters.
            `_half_inning` alternates PA, baserunning, PA, baserunning, so
            moving the roll before the PA just drops the final one after
            the last batter — the sequence in between is identical.
            **But the question points at something real and larger.**
            `sim.pa_from(mu, rng, tto)` takes a resolved matchup and a
            times-through-order index and NOTHING ELSE. Not the bases, not
            the outs. A plate appearance resolves identically with the
            bases empty and loaded.
TEST        Counted on 1,500 games of 2026 play-by-play, 112,809 plate
            appearances (`scratchpad/basestate.py`). TWO CONFOUNDS
            EXCLUDED and they sit exactly where the effect appears:
            INTENTIONAL walks (a manager decision that only happens with
            runners on) and SACRIFICE BUNTS (a runners-on-only play that
            enters the denominator as a guaranteed non-strikeout).

    channel    empty   runners on      rel    sigma
    k         0.2279       0.2160    -5.2%     -4.7
    bb        0.0850       0.0920    +8.2%     +4.1
    hbp       0.0104       0.0128   +23.0%     +3.7
    hr        0.0316       0.0304    -3.9%     -1.2
    h         0.2138       0.2236    +4.6%     +3.9

CONCLUSION  **ESTABLISHED: real offence is materially better with runners
            on, and the model has no channel for it at all.** Fewer
            strikeouts, more walks, more hits — traffic begets traffic.

            **THIS IS THE CLUSTERING DEFECT, NAMED.** The standing
            diagnosis in RESUME is "plate appearances resolve
            independently and real ones arrive together", recorded as a
            symptom with no mechanism and chased through a flat dispersion
            term and per-pitcher dispersion (closed, does not repeat).
            The mechanism is a FEEDBACK LOOP the state machine does not
            have: a baserunner changes the next plate appearance's rates,
            which produces more baserunners. That generates fat tails at
            both ends for free — more blowups AND more shutouts — which is
            precisely the shape error measured on F5.
NOT ESTABLISHED  How much of the -5.2%/+8.2% is the pitcher working from
            the stretch versus defensive positioning versus selection this
            screen has not removed. The DIRECTION and rough size are solid;
            the causal split is not, and a wired version should be fitted
            as a state multiplier and leverage-screened before building.
NEXT STEPS  Run `scratchpad/leverage.py` on a bases-occupied rate
            multiplier before building it. If it clears, it is a change to
            `sim.resolve`/`pa_from` — the resolved-matchup object would
            need a per-base-state variant, which is exactly the "one
            resolved matchup object" refactor already written up as the
            next build.

### MID-PLATE-APPEARANCE REMOVALS — A NULL, WITH A NUMBER

The model rolls removal only BETWEEN plate appearances. Counted over 400
games of 2026 play-by-play: of 2,848 pitching changes, **13 happened
mid-plate-appearance — 0.456%.** The model is right 99.5% of the time and
this is not worth building. Recorded so it is not asked a third time.

### THE BULLPEN IS DRAWN, NOT DEPLOYED — AND FATIGUE DOES NOT EXIST

`build_side` samples `PEN_DEPTH` = 8 arms without replacement weighted by
season appearances, and `next_arm` walks that list IN DRAW ORDER. So:

* **NO LEVERAGE.** A club's most-used arm is drawn into the pen in 84.4%
  of games and lands at average slot 3.01 of 8 — as likely to pitch the
  sixth as the ninth. Real closers pitch the ninth.
* **NO SITUATION.** Nothing knows the score, the platoon, or the save.
* **NO FATIGUE OF ANY KIND.** The pen is redrawn independently every game
  AND every draw. Nothing records that an arm threw 30 pitches yesterday
  or has worked three days running. Real availability is the largest
  game-to-game difference between two outings by the same club.

Real usage for scale: the most-used reliever takes 13.8% of his club's
relief appearances (p10 11.8%, p90 15.6%), so usage is flatter than
intuition suggests and the DRAW is not crazy — it is the ORDER and the
availability that are missing.

**`deploy.py` ALREADY MEASURED THAT ROLE IS REAL AND PROJECTS** — split-half
r +0.55 to +0.78 over 319 relievers — and its own conclusion was that
role-based deployment is worth building. It was never built. This is the
largest unbuilt item with a completed feasibility measurement behind it.

### THE PER-HITTER HIT MIX — COUNTED, AND THE IMPORTED ASSERTION SURVIVES

`rates.py` carries a comment saying extra-base rates "move much less
between hitters than the overall hit rate does, so this is applied
league-wide and the individual variation is carried by BABIP", and
`sim.resolve` duly sets `hit_mix=lg["hit_mix"]` for everyone. That was an
ASSERTION in a file whose house rule is count it, do not import it.
Counted (`scratchpad/hitmix.py`, 294 hitters with 40+ non-homer hits):

    league extra-base share of a non-homer hit   0.2423
    observed spread across hitters (sd)          0.0587
    binomial noise at mean n=76                  0.0490
    TRUE spread after removing it                0.0324   (13.4%)
    split-half r                                 +0.116
    Spearman-Brown                               +0.209

**THE ASSERTION HOLDS.** Most of the visible spread is sampling noise — a
hitter with 76 non-homer hits carries 0.049 of binomial sd by himself, so
83% of the observed variance is nothing. What survives repeats only weakly
(+0.209, against +0.711 for pitcher HBP which IS worth wiring, and +0.072
for per-pitcher dispersion which is closed).

LEVERAGE: one true sd of extra-base share is worth ~0.010 runs a game per
hitter and ~0.09 across nine slots IF every slot deviated the same way,
which they do not. Against a 0.05-run floor this is below the bar
individually and marginal collectively. **Not worth building.**

CARRY THE CAVEAT: doubles power correlates with home-run power, and
`hr_pct` IS modelled per hitter, so part of the extra-base signal is
already in the model by another route. That makes +0.209 a RESIDUAL
reliability rather than the total, and it is the right number for deciding
whether to add a channel — but it means the honest statement is "the
marginal channel is small", not "hitters do not differ in doubles".

### BASERUNNER SPEED DOES NOT EXIST IN THE MODEL — AND IT IS THE VARIABLE
### THE HIT-MIX SCREEN SHOULD HAVE BEEN AIMED AT

The user's objection to the hit-mix null: "doubles aren't just power,
they're also speed — that is two identical outcomes with different
on-field structures." Correct, and it exposes a screen aimed at the wrong
quantity.

**THE MODEL HAS NO PER-RUNNER SPEED ANYWHERE.** `STEAL_TABLE` is keyed on
(base state, outs) and nothing else, so every runner steals at the league
rate for that state. `FIRST_TO_THIRD_ON_1B`, `SECOND_SCORES_ON_1B`,
`FIRST_SCORES_ON_2B` and the `ADVANCE_*_ON_OUT` tables are keyed on the
OUT COUNT alone. A burner and a catcher are the same baserunner in every
one of those decisions.

**AND SPEED PASSES THE STABILITY GATE THAT DOUBLES FAILED.** Split-half on
odd/even games, Spearman-Brown corrected, 2026:

    quantity                          n      r    S-B
    steal rate per time on base     306  +0.715  +0.834
    triple share of non-homer hits  222  +0.339  +0.506
    extra-base share (the screen)   271  +0.116  +0.209

    for scale: pitcher HBP +0.711 (judged worth wiring)
               per-pitcher dispersion +0.072 (closed)

**+0.834 is the most reliable player-level quantity measured in this
project.** The hit-mix screen returned a null because a hitter's DOUBLES
COUNT is a noisy 76-hit sample; his SPEED is not, and speed acts in far
more places than the one hit that becomes a double — it acts on every
subsequent hit, every ground ball, and every steal opportunity for as long
as he is on base.

**THE LEVERAGE ARITHMETIC WAS ALSO STATED SLOPPILY AND THE USER CAUGHT
IT.** I reported ~0.01 runs a game per hitter and then waved at 0.09 for a
lineup. Nine hitters deviating INDEPENDENTLY is a SPREAD effect and
combines in quadrature: 0.010 x sqrt(9) = **0.030 runs** of team-to-team
separation, not 0.09 and not 0.01. Against the ~0.05 floor that is closer
than the per-hitter figure implied. The floor itself is ~1 cent: at a
team-total line the discrete run density is ~0.17 per run, so 0.05 runs is
0.85 cents against market spreads of four and up.

NEXT STEPS  Screen SPEED, not hit mix. The quantity is a per-runner
            advancement and steal multiplier, and the three places it
            enters are already separate named tables, so it is a resolver
            change and not a state-machine change. Run
            `scratchpad/leverage.py` on it first — the reliability is
            settled, the SENSITIVITY is not, and reliability without
            sensitivity is how park died three times.

### FIELD STATE: THE PLUMBING, SHIPPED INERT (2026-08-29)

Scoped deliberately: make the engine ABLE to carry a base-out state, prove
the path is exact, and put no number in it. Populating the table is a
separate change with its own measurement and its own A/B.

WHAT SHIPPED

    sim.STATE_MULT      {} — keyed (men on base, outs). EMPTY.
    sim.USE_FIELD_STATE True
    sim.state_mult()    returns None on an empty table, not a dict of 1.0s
    sim.pa_from(..., state=)   applies it through `odds_mult`
    game._half_inning   passes (occupied bases, outs BEFORE the PA)

**`odds_mult`, NOT the `tto` pattern, and the reason is the measurement.**
Times through the order scales the PITCHER'S input rate before log5, which
is the right shape for "this man is wearing down". The field-state effect
was measured as a LEAGUE RATE PER STATE (0.2279 strikeouts bases empty
against 0.2160 with men on), and `odds_mult` is constructed so a
league-average matchup at multiplier `m` lands on exactly `m * lg`. The
measurement therefore maps onto the mechanism with nothing to reconcile.
It is also the already-vetted path: park and arsenal were moved onto it on
2026-08-27 precisely because output multipliers distort the TAILS, which is
where prop lines sit.

**BIT-IDENTICAL, VERIFIED THE WAY THE `odds_mult` MIGRATION WAS.** 400
games x 6 sims, `scratchpad/fingerprint.py`:

    before  07528f5b1eb8aff97750ae9283f30ac1
    after   07528f5b1eb8aff97750ae9283f30ac1

An EMPTY table returns None rather than a dict of 1.0s, and that is load
bearing: `odds_mult` short-circuits only on `m == 1.0` exactly, so the
distinction between "no multiplier" and "a multiplier of 0.9999" is the
difference between inert and silently rescaling every rate in the model.

**THREE CHANNELS, NOT FOUR, AND BOTH OMISSIONS ARE ON THE LIST.**
`k_pct`, `hr_pct` and `babip` have `odds_mult` slots on `Matchup`.

  * WALKS have no multiplier slot at all — `bb` is bare `log5(...) / cond`.
    Adding one is small and matches the other three. Note this is the SAME
    gap that blocks the seasonal park term ("walks have no park slot").
  * HIT-BY-PITCH is drawn off the top against `cond`, which is carried
    rather than recomputed so it can never disagree with the rates it
    renormalises. Scaling hbp by state REQUIRES recomputing cond in the
    same breath, or every rate below it is renormalised by the wrong
    denominator — a silent level error of exactly the kind this file is
    full of. Deliberately not attempted alongside the plumbing.

**THE TEST THAT MATTERS IS THE ENGINE ONE, AND MUTATION PROVED IT.** Four
checks in `test_sim.py` exercise `sim.pa_outcome` directly. Deleting the
`state=` argument from `game._half_inning` leaves ALL FOUR GREEN — the
mechanism works perfectly and the engine never calls it. Only
`test_game.check_the_engine_passes_the_field_state_to_the_plate_appearance`
goes red. That is the `scratchpad/mutate.py` finding reproduced on new
code: every measurement tested, none of the wiring. Both mutations were
run and each fails exactly the checks it should.

NEXT   Measure the multiplier: outs and bases JOINTLY, which has not been
       done — the tables so far vary one at a time and the two are
       entangled. Then `leverage.py`, then populate.
       PRE-REGISTER THE FALSIFIER NOW: the claim is CLUSTERING, so the
       tails must move (shutouts 22.1% -> 21.9%, five-plus 15.8% -> 17.6%)
       while the MEAN holds. Runs rising without the tails spreading means
       the multipliers do not average to one over the state distribution
       and the change is just added offence.

### FIELD STATE POPULATED, SCORED, AND PARKED — THE FALSIFIER FIRED

QUESTION    Does populating `sim.STATE_MULT` move the run distribution's
            SHAPE toward reality? F5 runs per team-side and the share at 0
            and 5+, over 537 holdout games, rates frozen before the cutoff.
HYPOTHESIS  Registered before running: a feedback loop should fatten BOTH
            tails while the mean holds. FALSIFIER: mean up with flat tails
            = the table adds offence. SECONDARY: only the upper tail
            moving = a level error, not clustering.
TEST        The table was counted JOINTLY on (men on, outs) over 150,275
            plate appearances, IBB and sac bunts excluded, each multiplier
            a cell's rate over the overall rate. Frequency-weighted mean
            verified at 1.0000 on all four channels. Then shrunk toward 1.0
            by each cell's own binomial noise.
            **HOME RUNS SHRANK TO ALL-ONES — tau 0.0000 against a mean se
            of 0.0953.** Their entire spread across twelve cells is their
            own sampling error, so they are absent from the shipped table
            on purpose. The raw number showed a tempting 0.797 at (2 on, 1
            out) with se 0.062.
            POSITIVE CONTROL: a third arm at 3x amplification.
            POWER STATED FIRST: model-vs-model is paired and sharp at
            21,480 sides an arm; model-vs-REALITY is bound by 1,074 real
            sides, se ~0.012, and the five-plus gap being chased is itself
            only ~1.6 sigma. Those are different claims.
EVALUATE
                             OFF      ON   CTRLx3   ACTUAL
    F5 mean / side         2.425   2.458    2.500    2.437
    sd                     2.254   2.286    2.326    2.313
    shutout share          0.215   0.213    0.211    0.219
    five-plus share        0.164   0.169    0.175    0.176

            The control fires, so wiring and harness are sound. The PRIMARY
            falsifier did not fire — the tails did move. **The SECONDARY
            one did:** the upper tail moves, the lower tail moves the WRONG
            WAY, and the mean rises past a level that was previously right.
            F5 CRPS is NEUTRAL — paired over four salts, +0.00169 +/-
            0.00235, 2/4 worse, against a 0.0165 noise floor.
CONCLUSION  **NOT SHIPPED. `USE_FIELD_STATE = False`.**
            ESTABLISHED: the mechanism is real and wired; rate-normalised
            multipliers do NOT preserve the run level; F5 CRPS is neutral.
            REFUTED: that this produces symmetric clustering.

            **WHY THE MEAN MOVED THOUGH THE MULTIPLIERS AVERAGE TO EXACTLY
            ONE — the transferable part. RATE-NEUTRAL IS NOT RUN-NEUTRAL,
            because the state distribution is ENDOGENOUS.** The states
            where offence is boosted (men on) are exactly the states where
            a boost converts to runs, and boosting them produces MORE
            men-on states, which compounds. The frequency weighting holds
            the RATES fixed and lets the RUNS drift. Verifying it at 1.0000
            felt like a proof and was the wrong invariant.
NEXT STEPS  Renormalise on RUNS, not rates: solve the single scalar that
            restores the F5 mean with the table applied. That is a
            normalisation against a level the model already had right, not
            a tuning against a loss. Then re-run the falsifier — if the
            lower tail STILL moves the wrong way with the mean pinned, the
            clustering claim is dead and this is only a dispersion term.

**A MEASUREMENT BUG IN THE A/B ITSELF, recorded so the number is not
believed:** `state_ab.py` reports "share past nine" as 0.000 in every arm.
It reads `max(r.prefix)` with `track=(5, 9)`, so the maximum is 9 by
construction and extras can never be detected. That column is an artifact
and says nothing about the tie rate.

### THE RUNNER-EVENT REORDER IS A STRUCTURAL NO-OP — MEASURED, DEAD

QUESTION    Should steals, wild pitches and passed balls resolve BEFORE the
            plate appearance rather than after it? Raised by the user on
            the grounds that these events happen DURING an at-bat.
HYPOTHESIS  Three effects, registered before running: (a) the at-bat
            resolves against the post-steal state, live now that
            `STATE_MULT` ships; (b) an inning-ending caught stealing VOIDS
            the at-bat instead of following it, worth ~0.18 fewer plate
            appearances a game; (c) the lineup pointer stops advancing on
            that voided at-bat.
            FALSIFIER: if PA/game does not fall by ~0.18, the voiding is
            not happening.
TEST        537 holdout games x 20 sims, flag on and off. Not paired — the
            reorder reshuffles the random stream — so marginals only.
EVALUATE    **THE FALSIFIER FIRED.** PA/game 74.902 -> 74.939, i.e. +0.037
            where -0.18 was predicted. Game total +0.042, F5 per side
            -0.007, five-plus share +0.001. All noise.
CONCLUSION  **THE DEFECT IS REAL. THE FIX IS WORTH NOTHING MEASURABLE.
            THOSE ARE DIFFERENT STATEMENTS AND AN EARLIER VERSION OF THIS
            NOTE COLLAPSED THEM INTO "the claim is wrong", WHICH IS NOT
            WHAT WAS MEASURED.**

            (a) IS A GENUINE DEFECT and remains one. An at-bat resolves
            against a state that is one event stale: at-bat N sees the
            steals from at-bat N-1, not its own. Reordering DOES fix that.
            What it buys is nothing, and the reason is that the staleness
            shifts UNIFORMLY — moving which at-bat owns each steal by one
            slot is a relabelling, and the same at-bats meet the same
            distribution of base states either way. So the aggregate rates
            are identical by construction, which is what +0.037 PA/game and
            noise on runs are reporting.

            Note what this does NOT say: it does not say the state is
            irrelevant (`STATE_MULT` ships and is measured), and it does
            not say events during an at-bat do not matter. It says the
            per-at-bat MISATTRIBUTION cancels over a sequence.

            (b) IS NOT REACHABLE AT THIS GRANULARITY. The at-bat reality
            erases is the one IN PROGRESS when the runner is thrown out,
            and a plate-appearance-granular model has no in-progress
            at-bat. It needs pitch-level simulation, which is a different
            engine. (c) follows (b).

            The 0.185 inning-ending caught stealings a game are real and
            counted; what is wrong is the belief that reordering captures
            them.
NEXT STEPS  None. Kept switchable so the null stays scoreable, and because
            the reordering argument is persuasive on inspection and will be
            made again by the next person to read `_half_inning`.

**AND IT COST A TEST BAND, WHICH IS ITS OWN LESSON.** With the reorder on,
`check_longer_leash_raises_strikeout_totals` failed by 0.0009 —
`marginal` is a RATIO OF TWO SMALL DIFFERENCES between separately-seeded
arms and carries far more noise than either input. I loosened the band
rather than establishing whether the move was real. When the change was
reverted the band went back. **Loosening a test to admit a change is a
decision that has to be made AFTER the change is established, not as part
of shipping it** — had the reorder been kept, the suite would have carried
a permanently weaker check bought with an unmeasured result.

### PITCH_COST WAS IMPORTED AND IS NOW COUNTED (2026-08-29)

QUESTION    The simulator does not simulate pitches; it CHARGES a fixed
            number per outcome and the hook keys on the total. What are the
            real values? Unit: one plate appearance, then one start.
HYPOTHESIS  Per-PA spread of 1.5-2.5 pitches, and a start-level pitch count
            that is TOO PRECISE by ~10 pitches once ~25 plate appearances
            add in quadrature.
TEST        150,907 plate appearances of 2026 play-by-play, 3,843 starts.
            The decisive comparison is per START — actual pitches against
            what the table predicts from that start's own outcomes.
EVALUATE    Wrong by up to 19%:

    outcome     was   counted        n
    K          4.97      4.85   33,469
    BB         5.48      5.72   13,181
    HBP        3.67      3.09    1,721   <- 19% high
    HR         3.76      3.28    4,610   <- 15% high
    1B         3.01      3.35   21,386
    2B         3.01      3.33    6,234
    3B         3.01      3.36      548
    OUT        3.25      3.37   67,298
    SAC        3.00      2.77    1,592
    ROE        3.25      3.46      868

            One flat 3.01 for every hit, and too much for a home run and a
            hit-by-pitch — both of which END AN AT-BAT EARLY. That is the
            tell it was imported.

            **TWO TABLES WERE BEING CONFLATED, INCLUDING BY ME.** The
            hook's `pitch_center` is FITTED on real removal decisions with
            REAL pitch counts, so the curve expects true units. `PITCH_COST`
            is how the SIMULATOR manufactures a count to feed it. Over a
            start that came to 83.6 against a real 85.6, so **every
            simulated starter reached the removal decision two pitches
            young.** After the fix, 85.5 against 85.6.

            **THE HYPOTHESIS WAS WRONG AND IT KILLED THE OBVIOUS NEXT
            IDEA.** Start-level spread is 15.0 against a real 14.2 —
            slightly TOO WIDE, not too precise. Drawing the cost from a
            distribution would add ~1.8 per-PA over ~25 plate appearances
            and push it to ~17.5. Real pitch counts are CORRELATED WITHIN A
            START, so independent noise is the wrong shape.
CONCLUSION  SHIPPED, measured replacing imported.

            DOWNSTREAM IS MIXED. Outs CRPS 2.1045 -> 2.0878. Mean outs
            15.95 -> 15.70 against 15.82 — a 1.0 sigma error flipping to a
            1.0 sigma error the other way (se 0.124), not a regression.
            Boundary share 0.598 -> 0.587. P(over) worse at low outs lines,
            better at high ones.

            **`pitch_center` DELIBERATELY NOT RESCALED.** It was fitted on
            real counts; the simulator was feeding it short ones. Moving
            the centre to preserve the old output would undo a correctness
            fix to protect a number that is 1 sigma from where it already
            is.
NEXT STEPS  The residual is still sd 8.2 pitches per start. The table now
            has the LEVEL right and cannot say WHO is efficient. Pitches
            per plate appearance is correlated within a start, so that is a
            PER-PITCHER term, not noise — and it feeds the hook directly.
            Reliability unmeasured. Screen before building.

---

## DAY SIXTEEN (2026-08-29) — HIT-BY-PITCH BY FIELD STATE (TODO item 4)

QUESTION    `STATE_MULT` shipped with four channels and deliberately without
            hit-by-pitch, which was the largest relative effect on the
            board (+23.0% with men on, 3.7 sigma). Does it survive being
            counted JOINTLY on (men on, outs) and shrunk, and can it be
            wired without breaking the renormaliser it sits on top of?

HYPOTHESIS  Pitchers hit more batters with men on — working from the
            stretch, more breaking balls in the dirt, pitching more
            carefully around contact. Should show as a gradient with the
            occupied cells above 1.0.
            FALSIFIER, pre-registered: if the OVERALL rate per plate
            appearance rises, the table is adding free baserunners rather
            than moving them around. If K or BB fall alongside, `cond` did
            not follow `hbp`.

TEST        No rescan. `scratchpad/state_counts.json` already held the
            per-cell `hbp` counts from the same 150,275 plate appearances
            the shipped table was built on, and `state_table.py` gained a
            `--from-counts` path to use them — rescanning today would fold
            in games played since and drift the four shipped columns for a
            reason unrelated to the new one. Self-check: the regenerated
            k/bb/babip multipliers came back IDENTICAL to the shipped
            table, which is what says nothing else moved.

            POWER, STATED FIRST, and the two halves are not comparable.
            The RATE half walks the real state distribution through
            `pa_from` directly and is exact — that is where the claim
            lives. The GAME half cannot resolve this: a hit batsman is 1.1%
            of plate appearances, the table moves ~6% of those into
            higher-leverage states, and at a ~0.15-run difference in run
            expectancy that is ~0.003 runs a game against F5 noise of
            ~0.03. TEN TIMES below the test's resolution, which is the
            expected result and not a null.

EVALUATE    IT SURVIVES, with the largest tau of the five channels and the
            least of its raw spread kept:

                stat        tau    mean se   weight kept
                k_pct    0.0281     0.0320       0.60
                bb_pct   0.0523     0.0532       0.63
                hr_pct   0.0000     0.0953       0.00
                babip    0.0496     0.0338       0.77
                hbp_pct  0.0759     0.1716       0.36   <- new

            36% kept, because a hit batsman is a 1.1% event and the
            thinnest cell (bases loaded, nobody out) saw eight of them. The
            raw +45% at two on and nobody out shrinks to +9%. Every empty
            cell sits at or below 1.01 and every occupied one at or above
            1.00, topping out at 1.14 with a man on and nobody out.

            **THE ONE-AT-A-TIME +23.0% WAS NEVER WRONG, IT WAS LESS CERTAIN
            THAN IT READ.** Counted jointly and shrunk, the men-on / empty
            ratio the model now produces is 1.112 against a counted 1.266 —
            42% of the raw gap, which is the shrinkage doing its job and
            not an implementation shortfall.

            BOTH FALSIFIERS CLEARED, on the exact rate half:

                arm          hbp/PA   men-on/empty    K/PA
                NO HBP      0.01017          1.001  0.2241
                HBP         0.01019          1.112  0.2241
                CONTROL x5  0.01014          1.734  0.2241
                COUNTED     0.01145          1.266

            The overall rate is flat to the fourth decimal, so this
            redistributes hit batsmen rather than manufacturing them, and
            K/PA does not move at all, so `cond` followed. The x5 positive
            control scales cleanly, which separates a real-but-small effect
            from a mis-specified one. (The 0.01145 counted level is not
            comparable to the harness's 0.0102 — the harness pitcher falls
            back to the flat `HBP_RATE`, not the per-role constants.)

            The game half is flat as pre-registered: F5 runs/side 2.457 ->
            2.455, sd 2.282 -> 2.281, shutout and five-plus shares
            unchanged to three decimals over 21,480 simulated sides.

CONCLUSION  SHIPPED. A measured quantity replacing a state-blind one.

            **THE REASON THIS ITEM WAITED A DAY IS THE WHOLE CHANGE.** HBP
            is drawn OFF THE TOP, so its rate is also `cond`, the
            denominator every rate below it is divided by. Scale one
            without the other and strikeouts, walks and hits all come out
            light — silently. `pa_from` now moves the two together, guarded
            on the multiplier being exactly 1.0 so an absent key is
            bit-identical rather than merely close.

            VERIFIED BY MUTATION, three checks and three bugs:
            leaving `cond` stale moves K by -8.1% and fails exactly
            `check_scaling_the_hit_by_pitch_moves_its_renormaliser_too`;
            drawing against `mu.hbp` instead of the scaled value fails the
            wiring check; inflating the table 1.2x fails the
            frequency-normalisation check.
            Fingerprint a0369429 -> 9eb102bf, and a0369429 reproduced
            exactly with the `hbp_pct` key stripped. 408 -> 411 checks.

NEXT STEPS  The `hbp_pct` column keeps only 36% of its spread because the
            cells are thin, not because the effect is small. It is the one
            channel here that would sharpen materially on more seasons —
            `state_counts.json` is 2026 only, and `advance.py` already runs
            2023-2026. Cheap, and it is the same rescan for all five
            channels.

### Scoping check: TTO_MULT and STATE_MULT do NOT double-count

QUESTION    `TTO_MULT` controls survivorship and batter mix and does NOT
            control base-out state. `STATE_MULT` now ships. If the first
            lineup pass sees a different mix of field states than the
            third, both multipliers are charging for the same baseball.

TEST        `scratchpad/tto_state_overlap.py`, 2,000 games, starters only.
            Bin every plate appearance by (pass, men on, outs), then push
            each pass's state mix through the shipped `STATE_MULT` to get
            the K multiplier the state table ALONE implies for that pass.

EVALUATE    The state mix genuinely moves — men-on share 0.367 / 0.429 /
            0.440 across the three passes. But the K multiplier it implies
            is 1.0002 / 1.0003 / 1.0021: the state table's own multipliers
            nearly cancel across that shift, because K rises with the out
            count and falls with traffic and the two move together.

                pass-1-over-pass-3 K spread
                TTO_MULT charges      +23.83%
                field state alone      -0.19%

            POSITIVE CONTROL: a fake table at -20% K with men on produces a
            +1.60% span, so the harness sees an effect when one is there.
            Sensitivity is ~8% of the injected size, since the men-on share
            only moves 7 points — the state table would need men-on
            multipliers near -300% to explain the TTO decay.

CONCLUSION  NO OVERLAP. The two mechanisms are independent and neither
            needs refitting against the other. Do not re-run this.

            NOT ESTABLISHED, and it is the reason to be careful with the
            raw column above: real K% by pass came out 0.2425 / 0.2068 /
            0.1976, ratios 1.000 / 0.853 / 0.815 against TTO_MULT's 1.000 /
            0.852 / 0.808. That LOOKS like TTO is calibrated, which would
            weaken item 11's stated candidate — but this count is NOT
            survivorship-controlled and `tto.py`'s is, so the two are not
            the same quantity and must not be compared. Item 11 needs its
            own measurement.

## DAY SIXTEEN, PART TWO — ITEM 11 RE-MEASURED, AND THE FOUR-SEASON RESCAN

### Item 11: the first inning is still under-scored, but its stated cause is weaker than the note claimed

QUESTION    The -13.3% first-inning gap was measured before `_track` fired
            on every exit path and before `STATE_MULT` shipped. The first
            inning is the one that starts bases-empty by construction, so
            the state table lands on it unevenly. Has it moved?

TEST        `scratchpad/where_runs.py --cut 2026-05-15 --profile`, the SAME
            instrument on the SAME games. Only the model changed.

EVALUATE    926 games, se ~0.050 a side per inning.

                inning   model  actual     gap      z     rel      [was]
                     1   0.898   1.021  -0.122   -2.5  -12.0%   [-13.3%]
                     2   0.839   0.910  -0.071   -1.5   -7.8%    [-7.3%]
                     3   0.970   0.995  -0.025   -0.5   -2.5%    [-5.7%]
                     4   0.976   0.973  +0.003   +0.1   +0.3%
                     5   0.945   1.068  -0.123   -2.5  -11.5%
                     6   0.960   1.023  -0.063   -1.2   -6.2%
                     7   0.961   0.932  +0.029   +0.6   +3.1%
                     8   0.960   1.051  -0.091   -1.8   -8.6%
                     9   0.793   0.960  -0.167   -2.9  -17.4%
                 total   8.302   8.932  -0.630   -4.1   -7.1%    [-8.0%]

CONCLUSION  ESTABLISHED: the first inning survives at -12.0%, z -2.5. The
            gap moved 0.014 runs against se 0.050 — nothing resolved it and
            nothing needs to. Item 11 stands.

            NOT ESTABLISHED, AND THE NOTE OVERSOLD IT: the "-13.3%, -7.3%,
            -5.7% monotonic decay shaped like a lineup pass" was the stated
            reason to suspect `TTO_MULT`. Innings 2 and 3 were NEVER
            individually significant (z -1.4 and -1.2 then, -1.5 and -0.5
            now) and inning 3 has drifted to -2.5% with inning 4 at +0.3%.
            The decay now dies by the third inning, faster than a lineup
            pass. **The shape argument rested on two numbers that were
            never distinguishable from zero.** Only inning 1 is a finding,
            then and now, and it needs a mechanism that is specific to the
            FIRST inning rather than to the first lineup pass.

            Combined with the TTO/field-state null above — field state
            explains none of the TTO decay — `TTO_MULT` is now a WEAK
            candidate for item 11 rather than the leading one.

NEXT STEPS  TWO NEW GAPS, and neither is in the old note because it printed
            only innings 1-3. NINE-PLUS is now the largest relative gap on
            the board at -17.4%, z -2.9, and innings 5 and 8 are at -11.5%
            and -8.6%. CAVEAT BEFORE ANYONE CHASES ONE: nine innings were
            tested, so at alpha 0.05 roughly half a false positive is
            expected; z -2.9 is p ~0.004 and survives that, the others do
            not clearly. The ninth is where the model has no closer and no
            leverage — `next_arm` walks the pen in DRAW ORDER (item 8) — so
            it is the one worth opening, and item 8 already has a finished
            feasibility study behind it.

### The four-season rescan: every channel gated, and home runs come back

QUESTION    `state_counts.json` was 2026 alone, 150,275 plate appearances,
            and its thin cells are what held the table back. All four
            seasons are cached locally. What does 5x the data change?

TEST        `scratchpad/state_seasons.py --backfill` — 9,978 games, 748,905
            plate appearances, no network. MULTIPLIERS COMPUTED WITHIN A
            SEASON AND POOLED AFTERWARDS: the league drifts (2023 struck
            out at 0.2299 against 2026's 0.2224), so pooling raw counts and
            taking one ratio lets a season's baseline leak into the cells.

            NEW: A STABILITY GATE, which the 2026 table never had. Does a
            cell's multiplier repeat from year to year, or is it that
            year's noise? This is the check `advance.py` applies per club
            and FAILS.

EVALUATE        stat       all 12    fat 8      tau  mean se   kept
                k_pct       0.859    0.945   0.0437   0.0146   0.91
                bb_pct      0.908    0.866   0.1121   0.0245   0.96
                hr_pct      0.172    0.519   0.0272   0.0439   0.48
                babip       0.432    0.850   0.0372   0.0154   0.88
                hbp_pct     0.550    0.764   0.1606   0.0807   0.84

            **THE TWO GATE COLUMNS DISAGREE AND THE FAT ONE IS RIGHT.** An
            unweighted correlation over twelve cells gives the three
            bases-loaded cells — 3,149 plate appearances between them
            against 185,488 in the leadoff cell — the same vote as the cell
            that decides the channel, so their own noise reads as a channel
            that does not repeat. Restricted to the eight cells above
            30,000, every channel repeats. Read the direction: a
            correlation over twelve points has se ~0.27.

            **HOME RUNS COME BACK, AND THAT IS THE HEADLINE.** On 2026
            alone tau was 0.0000 and the channel shipped as all-ones, with
            a test guarding its absence. On 2023-2026 tau is 0.0272 and it
            keeps 48%: 1.058 with the bases empty and nobody out down to
            0.942 at two on and one out. A pitcher challenges a hitter with
            nobody aboard and works away from the barrel with men on.
            **THE OLD NULL WAS NOT WRONG, IT WAS UNDERPOWERED** — which is
            exactly the distinction the standing rule about nulls exists to
            protect, and this is the first time the rescan has produced the
            other side of it.

            TWO EFFECTS SHARPENED HARD. Walks with the bases loaded go
            0.970/0.947 -> 0.781/0.758: nobody pitches around anyone when a
            walk forces in a run. Hit-by-pitch keeps 84% against 36%, with
            all three empty cells at 0.906-0.940 and every occupied one bar
            (1, 2) above 1.07.

            SCORED, 537 holdout games, 21,480 sides an arm
            (`scratchpad/state_4season_ab.py`). Read as two steps:

                                    OFF     2026  2023-26   ACTUAL   se
                F5 runs / side    2.424    2.455    2.460    2.437  0.070
                  sd              2.251    2.281    2.290    2.313
                  five-plus       0.164    0.168    0.168    0.176  0.012
                starter outs     15.872   15.855   15.819   15.820

            Dispersion keeps moving the right way — 2.251 -> 2.281 -> 2.290
            against a real 2.313 — which is the standing under-dispersion
            defect closing, slowly.

CONCLUSION  SHIPPED. More data, measured the same way, now gated on
            repeatability. Fingerprint 9eb102bf -> 93af75e7.

            THE FALSIFIER, AND WHY IT DID NOT FIRE. I pre-registered "the
            mean drifting up means normalisation broke", and the mean did
            drift up, 2.424 -> 2.460 against a real 2.437. That is 0.33
            sigma and NOT a finding — and the falsifier as I wrote it was
            sloppy, because the direct check is exact: the
            frequency-weighted mean of every channel is 1.0000 and a test
            asserts it. A mean that rises while the tails ALSO fatten is
            the mechanism working as designed, since runs are convex in
            clustering. The original `state_ab.py` falsifier said it
            properly — "mean up WITH FLAT TAILS" — and the tails are not
            flat.

            `check_home_runs_are_absent_from_the_state_table` was DELETED
            and replaced with one that guards the direction (empty > men
            on) rather than the values. The old check said in its own
            docstring that an edit adding `hr_pct` should have to delete it
            and say why. This is the why.

NEXT STEPS  The rescan cache (`state_counts_4season.json`) is keyed by
            season and cell and is the base for items 6, 13 and 18 — same
            plays, same pass, grouped by runner, pitcher or batter instead.

## DAY SIXTEEN, PART THREE — ITEM 11b WAS NOT THE BULLPEN. IT WAS TWO DRIVER BUGS IN `simulate_game`

QUESTION    TODO item 11b (innings 9+ under-scored by 17.4%, z -2.9) was
            handed to item 8, the bullpen, on the argument that "the ninth
            is exactly where the model has no closer". Before building a
            bullpen: CAN a bullpen move that number?

HYPOTHESIS  Not obviously. `9+` is a RESIDUAL over three populations
            selected in completely different ways — the top of the ninth
            (always played), the bottom (only when the home club is not
            ahead) and extras (only when tied). The last two are
            conditioned on the SCORE, which is the model's own output, so a
            model under-scoring by 7.1% everywhere reaches them at the wrong
            rate for reasons a closer cannot touch. Only a RATE gap in the
            halves actually played is available to item 8.

            The user's guard was the same point from the other side: the
            whole game is -7.1%, so only the ninth's ~10-point EXCESS over
            the global gap was ever claimable, not the full 17.4%.

TEST        `scratchpad/ninth.py` — the same 926 games and the same cut as
            `where_runs --profile`, decomposing

                E[9+] = P(top9) E[runs|top9] + P(bot9) E[runs|bot9]
                        + E[extra runs]

            POWER, STATED FIRST: the SHARES are the sharp terms (se ~0.016
            over 926 games); the conditional RATES are the noisy ones
            because they drop to the games that played the half. Read the
            shares first.

EVALUATE    THE DECOMPOSITION DID NOT LOOK LIKE A BULLPEN AT ALL:

                quantity          model   actual      gap     z
                9+ total          0.792    0.960   -0.168  -2.9
                top of 9          0.152    0.455   -0.302  -9.1
                bottom of 9       0.503    0.254   +0.249  +9.9

            Two nine-sigma errors pointing OPPOSITE ways, in a bucket whose
            combined gap is 2.9 sigma. A bullpen cannot produce that. An
            inverted top and bottom can.

            **CONFIRMED DIRECTLY, NOT INFERRED FROM RUNS**
            (`scratchpad/whobats.py`, 300 games, with a positive control on
            a hand-built game whose order is known by construction):

                                    model   reality
                bats first          home     away     300/300 games
                P(away bats in 9th) 0.467    1.000
                P(home bats in 9th) 1.000    0.557

            **BUG ONE: THE TWO HALF-INNINGS WERE THE WRONG WAY ROUND.** A
            `Side` is a PITCHING side and its `lineup` is "the OPPOSING
            nine", so the side named `away` FACES THE HOME CLUB. Calling it
            first batted the home club in the top of every inning, and the
            two rules that break the symmetry — the skipped bottom half and
            the walk-off — landed on the wrong club.

            **BUG TWO: THE WALK-OFF FIRED ON THE FIRST RUN, NOT ON THE
            LEAD.** `_half_inning` ends a half on
            `side.runs > side.opposing_runs`. `side.runs` is what the
            PITCHING side ALLOWED — the batting club's score — so
            `opposing_runs` has to hold the pitching side's OWN club's
            score. The driver set `home.opposing_runs = home.runs`, the
            BATTING club's score, snapshotted immediately before the half.
            The comparison collapsed to "has the batting club scored at all
            this half". Counted (`scratchpad/walkoff.py`): 34 of 42 scoring
            halves ended on exactly one run, max 3, and 42 of 42 carried the
            snapshot signature. The condition itself was always sound; only
            its input was wrong.

            **WHY NEITHER WAS EVER CAUGHT, and it is the transferable
            part.** Both rules key on `regulation`, so INNINGS 1-8 ARE
            EXACTLY SYMMETRIC and no F5 number ever moved — every fit,
            every ladder and every CRPS run in this project's history is
            untouched. And in the one place anyone looked, the two halves
            of the error very nearly ANNIHILATE: `where_runs --profile`
            sums both halves, so -0.302 and +0.249 read as -0.053.
            The user's correction on the day is the right framing and is
            recorded because it changed how this was reported: THE
            CANCELLATION IS NOT A REASON TO DISCOUNT IT. Those innings are
            really played, both per-club numbers are real, and TEAM TOTALS
            ARE THE STATED PRODUCT — so both sides of the product were
            wrong while the aggregate looked fine. Cancellation explains the
            SURVIVAL, not the severity.

            SCORED, same 926 holdout games x 20 sims:

                                       BEFORE    AFTER   ACTUAL     se
                9+ total                0.792    0.980    0.960  0.059
                  top of 9              0.152    0.452    0.455  0.034
                  bottom of 9           0.503    0.251    0.254  0.025
                P(bottom 9 played)      0.517    0.564    0.557  0.017
                whole game              8.302    8.530    8.932  0.154
                away club, whole game   ~3.88    4.180    4.485  0.112
                home club, whole game   ~4.60    4.350    4.447  0.106

            Item 11b: -17.4% / z -2.9 -> +2.0% / z +0.3. CLOSED.
            The whole-game gap: -7.1% / z -4.1 -> -4.5% / z -2.6.
**[RETRACTED 2026-08-30 — see the day 17/18 block at the top of RESUME.md. Verified on 1,645 games the model is NOT light on runs: F5 -0.047 at 0.6 sigma. This figure is from a previous engine.]**

            THE PRE-REGISTERED FALSIFIER PASSES. The user set it before the
            work: the ninth must move WITHOUT innings 1-5 moving, or the
            level has been changed rather than the deployment. Innings 1-5
            went -12.0/-7.8/-2.5/+0.3/-11.5% to -10.7/-5.5/-4.5/-0.3/-8.1%,
            every one inside 1 se, and the arithmetic says they cannot move
            — the two rules cannot fire before the ninth.

CONCLUSION  ESTABLISHED: two correctness bugs in `simulate_game`, each
            verified by mutation against its own regression check.
            `check_the_away_club_bats_in_the_top_of_the_inning` and
            `check_a_walk_off_needs_the_lead_not_just_a_run`; mutation 1
            (order swapped back) fails both, mutation 2 (`opposing_runs`
            alone) fails exactly the walk-off check. 411 -> 413 checks.
            Fingerprint 93af75e7 -> 5a39453e, deliberately NOT inert.

            ESTABLISHED: item 11b is closed and item 8 did not cause it.

            NOT ESTABLISHED, and it must not be read as a bullpen result:
            this says nothing about whether role-based deployment is worth
            building. It says only that the ninth-inning gap which was
            being used as EVIDENCE for it was an artifact.

            ONE TEST WAS ENCODING THE BUG rather than guarding against it.
            `check_errors_raise_the_run_level` asserted every start reached
            27 outs while reading `away_sp`, and the away side pitches the
            BOTTOM halves — a starter who is never pulled records 24 outs in
            exactly the games his club loses, which is real baseball.
            `fixtures.one_side` gained `side="home"` (the side that pitches
            every top half) and the check reads that. Defaulting to away
            keeps every other caller's seeded draw unchanged.

NEXT STEPS  TWO NEW GAPS OPENED BY THE FIX, both unconfirmed and neither
            chased:

              * EXTRAS ARE NOW TOO FREQUENT. P(extras) 0.102 against a real
                0.083 (z +2.0) and extra innings/game 0.147 against 0.114
                (z +2.1). It was 0.079 before. Runs per extra half is still
                short (2.689 against 3.026, -11%).
              * THE AWAY/HOME SPLIT NO LONGER MATCHES. Reality has the away
                club scoring slightly MORE than the home club (4.485 against
                4.447) because the home club forfeits ~44% of its ninths.
                The model has it the other way (4.180 against 4.350), a
                ~0.21-run disagreement at roughly 1.5-2 sigma. The
                home-pitcher advantage (`HOME_OPP_K` 1.034) pushes that way
                and may now be over-dominating. CHECKED AND NOT A BUG:
                `adjust_lineup(away[2], False)` looks inverted but is not —
                `is_home` means the PITCHER is at home, and `away[2]` is the
                nine the AWAY starter faces, so `False` is correct.

### The deployment screen for item 8 — sensitivity, which was never measured

QUESTION    `deploy.py` established that reliever ROLE IS REAL AND PROJECTS
            (split-half +0.55 to +0.78 over 319 relievers) and concluded
            deployment was worth building. It never established SENSITIVITY.
            `leverage.py` screens bullpen ARM QUALITY, a different
            parameter — what a better pen is worth, not what the same pen in
            a different order is worth. Nothing screened deployment.

TEST        `scratchpad/deploy_screen.py`, 20,000 paired draws on the
            reference club, common random numbers at the draw. Two ORACLE
            orderings of the same eight drawn arms bound every possible
            rule: best-last against best-first.

EVALUATE        ordering      game total    9th+   5+ runs   relievers
                best last          9.093   1.050     0.413        4.43
                draw order         8.793   1.032     0.383        4.40
                best first         8.474   1.006     0.352        4.40

                ceiling (last - first)  total +0.618 (se 0.024)
                                        9th+  +0.043 (se 0.015)
                status quo - best last  total -0.300 (se 0.020)

            SENSITIVITY IS LARGE — 0.618 runs, twelve times the ~0.05-run
            leverage floor. Deployment is not a sub-floor mechanism.

            **BUT THE CEILING CONFLATES TWO CHANNELS AND THE BIG ONE IS NOT
            LEVERAGE.** A nine-inning game reaches only ~4.4 of the 8 drawn
            arms, so reordering changes WHICH arms pitch at all, not merely
            when. That is why best-last scores MORE (9.093) rather than
            fewer runs: it puts the WORST arms in the innings that are
            actually played. Split:

                which arms are exposed   ~0.6 runs
                when each one pitches    ~0.04 runs

CONCLUSION  ESTABLISHED: ordering has ample sensitivity, so item 8 is not
            dead on leverage grounds and its feasibility study stands.

            NOT ESTABLISHED: that a leverage/role rule buys the 0.6. Most of
            the ceiling is ARM EXPOSURE — which of the eight are used —
            rather than the inning each is used in. A rule that only
            re-times a fixed set of arms is screened at ~0.04 runs.

            NOT BOUNDED AT ALL by this screen: SITUATION (a closer appears
            only in save situations, redistributing across games — shape,
            not mean) and FATIGUE (the pen is redrawn independently every
            game and every draw). Item 8's real case now rests on those two
            plus arm exposure, and no longer on the ninth-inning gap.

## DAY SIXTEEN, PART FOUR — TODO 11d: THE HOME/ROAD CONSTANTS, RECOUNTED, AND A FOURTH CHANNEL

QUESTION    After the half-innings were fixed, the model had the HOME club
            outscoring the away club by 0.17 runs while reality has it the
            other way by 0.04 — a 0.21-run disagreement on per-club totals,
            which are the stated product. Are `HOME_OPP_K` and
            `HOME_OPP_CONTACT` the cause?

HYPOTHESIS  They are overstated. They were MEASURED, but on RATES — K rate
            +6.8% (z +3.49), hit rate -3.9% (z -2.15) — and the RUN
            consequence was never checked. "Fit the quantity that settles,
            not the upstream proxy" is the most-repeated line in these docs
            and a rate split is exactly an upstream proxy.
            FALSIFIER, pre-registered: turning `USE_HOME_ROAD` off must
            collapse the model's home-away spread. If it survives, these
            constants are not the mechanism and 11d lives elsewhere.

TEST        `scratchpad/homeroad.py`. THE CLEAN WINDOW IS INNINGS 1-8 —
            both clubs bat in every one, so the ninth-inning forfeit (worth
            ~0.25 runs against the home club's own total) is excluded BY
            CONSTRUCTION rather than modelled and subtracted. Conflating it
            is what made 11d look ambiguous in the first place.
            Three arms: actual, model as shipped, model with home/road off.

            POWER: 926 holdout games give se ~0.147 on the raw home-away
            spread, which CANNOT resolve 0.21 — that is why 11d was logged
            at 1.5-2 sigma. The paired model-minus-actual and
            model-minus-model contrasts are far sharper, and the real LEVEL
            is taken over all 9,978 cached games at se 0.044.

EVALUATE    **MY HYPOTHESIS WAS HALF RIGHT AND MY ARITHMETIC WAS WRONG, and
            the wrong half is the instructive one.** I estimated real
            home-field advantage at 0.1-0.15 runs from general baseball
            knowledge. COUNTED ON THIS LEAGUE it is 0.306 (se 0.044, z
            +6.9) over 9,978 games. Twice my guess. The inference that the
            constants were "2-3x too strong" rested entirely on that
            imported number — count it, do not import it, applied to me.

            The falsifier behaved: off collapses the spread 0.382 -> 0.026,
            so the constants ARE the mechanism (+0.356, z +9.2).

            THE RECOUNT, 679,329 plate appearances, innings 1-8, all arms:

                quantity        home     away    ratio      se      z    was
                K per PA      0.2294   0.2180   1.0522  0.0048  +11.0  1.0692
                hits per PA   0.2184   0.2228   0.9804  0.0045   -4.4  0.9624
                walks+hbp     0.0930   0.0977   0.9516  0.0071   -6.8  (none)
                HR per PA     0.0307   0.0316   0.9710  0.0132   -2.2  (none)

            Both shipped constants overstated, by 3.5 and 4.1 sigma on the
            constant's own scale. Same story as every other constant here
            that got recounted: right in direction, thinly measured.

            **THE FOURTH CHANNEL IS THE REAL FINDING. WALKS HAD NO
            PARAMETER AND ARE THE LARGEST SPLIT OF THE THREE.** They were
            riding `HOME_OPP_CONTACT` alongside hits, home runs and babip,
            which charged them 0.9804 where their own count is 0.9516 —
            less than half their measured effect, at z -6.8. Home runs stay
            on the contact constant deliberately: their own 0.9710 sits 0.7
            sigma from what contact already gives them, so splitting them
            out would be adding a parameter to chase noise.

            SCORED IN THREE STEPS, and the middle one matters:

                arm                          home - away (innings 1-8)
                model, OLD constants                     0.382
                model, recounted K + contact             0.174
                model, + counted walk channel            0.247
                ACTUAL, holdout 926 games                0.205  se 0.147
                ACTUAL, all 9,978 games                  0.306  se 0.044

            **THE MIDDLE ROW IS WHY THE WALK CHANNEL WAS BUILT RATHER THAN
            THE CONSTANTS BEING NUDGED BACK UP.** Recounting alone
            OVERSHOT — 0.174 against a counted 0.306. The tempting move was
            to pick K and contact values that reproduce 0.306, which is
            precisely the forbidden "solve for a level". Instead the
            overshoot was read as what it is: a MISSING MECHANISM, and the
            same scan that found it named it at 6.8 sigma.

            THE ORIGINAL 11d SYMPTOM, full-game team totals:

                            BEFORE 11d work    AFTER    ACTUAL     se
                away club             4.180    4.275     4.485  0.111
                home club             4.350    4.281     4.447  0.106
                asymmetry             0.208    0.044

            Both clubs now sit inside the known global under-scoring
            (-4.5%) instead of pulling opposite ways.

CONCLUSION  SHIPPED. `HOME_OPP_K` 1.034 -> 1.026, `HOME_OPP_CONTACT`
            0.981 -> 0.990, and a new `HOME_OPP_BB` 0.975 with its own
            `AWAY_OPP_BB`, all centred so home x away = 1.0 exactly.
            414 checks (was 413), fingerprint 5a39453e -> ab32efb1.

            VERIFIED BY MUTATION: restoring `bb_pct * mc` — walks back on
            the shared contact knob — fails exactly
            `check_the_walk_multiplier_reaches_bb_pct_and_nothing_else` and
            nothing else. The check asserts the WIRING, not the value,
            because a constant that exists and is never read is this
            project's standing failure mode (`Matchup.m_bb` sat unread for
            the whole life of the park work).

            ESTABLISHED: 11d is closed. The away/home asymmetry is 0.044
            runs, down from 0.208.

            NOT ESTABLISHED: that the model now has home-field advantage
            exactly right. It produces 0.247 against a counted 0.306 — 1.1
            sigma, a direction and not a finding. Do NOT tune the constants
            to close it; they are each counted at 4-11 sigma on their own
            quantity, and the residual belongs to channels still unmodelled
            (errors, baserunning, and the structural effect of batting
            last, none of which have a home/road split).

NEXT STEPS  The remaining per-club gap is now the GLOBAL under-scoring
            (-4.5%, both clubs alike), which is items 7, 9 and 11 — not a
            home/road question. Nothing further to do on 11d.

### CORRECTION to PART FOUR, same session — the walk channel was counted on the wrong denominator

The user asked whether "pitchers walk fewer batters at home" was measured or
deduced. It was measured — but the count was WALKS PLUS HIT-BY-PITCH, and
that does not match the code path, which is the one condition that makes a
recount a measurement rather than a tune. `bb_pct` is walks; HBP is drawn
off the top on `hbp_rate` and is not in it. Applying a walks+HBP figure to
`bb_pct` charges the channel for an event it does not contain.

BROKEN OUT, on the same 679,329 plate appearances:

    channel                 home     away    ratio      se      z
    walks + hbp (used)    0.0930   0.0977   0.9516  0.0071   -6.8
    unintentional walks   0.0804   0.0847   0.9493  0.0077   -6.6
    hit by pitch          0.0110   0.0110   0.9992  0.0230   -0.0

THE EFFECT IS ENTIRELY WALKS. Hit-by-pitch has NO home/away split at all,
which is also the answer to whether it wants a constant of its own: it does
not. Intentional walks are excluded — statsapi types them separately and
they are a manager decision, not a pitching outcome.

`HOME_OPP_BB` 0.975 -> 0.974. **THE ORIGINAL VALUE WAS RIGHT BY LUCK, NOT BY
DESIGN** — HBP is only ~12% of the combined channel and has a ratio of
essentially exactly 1.0, so bundling it barely diluted the number (0.2
sigma). The provenance was wrong even though the value was not, and a
constant whose stated basis does not match what it multiplies is one
refactor away from being wrong for real.

RESCORED: model home-away over innings 1-8 is 0.263 (was 0.247 at the
bundled value) against a counted 0.306, se ~0.054 — 0.8 sigma.
414 checks, fingerprint ab32efb1 -> c7f3e41d.

### Auditing the rest of the cascade, prompted by the same question

HBP being "drawn off the top" does NOT mean it sits outside the plate
appearance — it is the second draw in the cascade, after the sacrifice and
before the strikeout, with everything below renormalised by
`cond = 1 - sac - hbp`. That is a sequential decomposition of a multinomial
and is equivalent to one draw over all outcomes. HBP is a full outcome and
already carries a state multiplier and a starter/reliever split.

WHICH RAISES THE CHANNEL THE AUDIT HAD MISSED: `sac` is drawn off the top
too, and bunting is a MANAGER decision, so batting last is a plausible
a-priori reason for a split. Counted:

    sacrifices per PA     0.0088   0.0096   0.9207  0.0232   -3.4

REAL AND NOT WORTH BUILDING, and the arithmetic is the whole argument.
Sacrifices are ~0.9% of plate appearances, so an 8% split is ~0.03
sacrifices a team-game; at roughly -0.05 runs each that is **~0.0015 runs**,
twenty times below the "small but counted ships" threshold and a thousand
times below the gaps still open. It would also need plumbing that does not
exist — `sac_rate` is a per-arm constant and `adjust_lineup` edits
`BatterRates`, which do not carry one.

RECORDED SO IT IS NOT RE-DISCOVERED: the home/road audit of the cascade is
now COMPLETE. K (+11.0), hits (-4.4) and walks (-6.6) have constants; HBP
(-0.0) needs none; home runs (-2.2) ride contact within 0.7 sigma of their
own count; sacrifices (-3.4) are real and negligible.

## DAY SEVENTEEN (2026-08-29) — THE HOOK, ONE PIECE AT A TIME. PART ONE: THE BLOWOUT TERM

**`Hook.mid_per_margin` AND `Hook.per_margin` HAVE BEEN ZERO SINCE THEY WERE
CREATED, AND THE REASON IS THAT THEY ARE THE WRONG SHAPE.** Their docstring
posed the question well — "a big lead buys a starter rope because the game is
safe, and also gets him lifted because there is nothing left to protect" —
and then encoded it as a SIGNED term, which cannot represent either reading.

QUESTION    Does the score reach the manager's hook, and by how much per run?
            Unit of observation: one real starter removal decision.
HYPOTHESIS  Two rival mechanisms, named before running and NOT the same:
            SIGNED margin (he is treated differently when his own club leads)
            and UNSIGNED |margin| (the game is decided either way, so the
            decision stops being about winning). Only the second is symmetric.
TEST        322,205 real decisions, 2023-2026, from `boundary.decisions`.
            Each curve fitted on ITS OWN population — 73,637 boundary rows at
            an 11.49% pull rate, 248,568 mid-inning rows at 2.42% — with an
            unregularised logistic and standard errors from the observed
            Fisher information. `scratchpad/hook_margin.py`.
            POWER STATED FIRST: se 0.0066 and 0.0061, resolving 0.020 and
            0.018 log-odds per run at 3 sigma. POSITIVE CONTROL: a 0.05
            injection recovered at +0.050 and +0.054, so the harness sees an
            effect of the size in question.

**THE RESULT, AND THE SIGNED FORM IS A CLEAN NULL ON BOTH CURVES:**

    curve         signed margin       z        |margin|         z
    boundary    +0.00479 +/-0.0066  +0.7   +0.01267 +/-0.0078  +1.6
    mid-inning  -0.00566 +/-0.0061  -0.9   -0.08240 +/-0.0079  -10.4

**THE BOUNDARY DECISION TAKES NEITHER TERM** and its |margin| coefficient
does not survive the stability gate — per season +2.5 / +1.4 / -0.9 / +0.5,
sign-flipping. A manager deciding whether to send his starter back out does
not care what the scoreboard says, once pitches, runs, baserunners and the
inning are known. That is a genuine null with a fired control behind it.

**THE MID-INNING DECISION TAKES THE UNSIGNED ONE AT 10.4 SIGMA, AND IT IS
STABLE:** -0.0887 / -0.0734 / -0.0837 / -0.0950 across 2023/2024/2025/2026,
same sign every year, never under 4.5 sigma. Controlled for `inning`,
`outs_before` and `bf`, so it is not the game clock arriving on the wrong
coefficient — uncontrolled it reads -0.0733 and controlled -0.0824, i.e. the
control makes it BIGGER.

**THE RAW MARGINAL POINTS THE OTHER WAY, AND CHECKING THAT IS WHAT MADE THIS
REPORTABLE.** Pull rate by |margin| within a pitch band RISES at 60-75
pitches, 0.014 -> 0.025. The two numbers were never in conflict: |margin| is
entangled with runs allowed (mean 0.71 at |m|<2 against 2.33 at |m| 4-6),
because a starter losing badly is usually losing badly BECAUSE of him. Hold
runs and pitches fixed and it is monotone in every row —

    runs=1, 75-95 pitches, by |margin| 0-1 / 2-3 / 4-5 / 6+
        0.073   0.074   0.051   0.027

— and the Hook already carries `runs`, so the CONDITIONAL effect is the one
it needs. The unconditional table would have killed the mechanism.

**SHIPPED as `mid_per_abs_margin = -0.0824`** on the late mid-inning branch.
Fitted on EVERY mid-inning row rather than late ones, because `early_innings`
is 0 and that branch therefore fires at every inning — the population it is
fitted on is the population it is evaluated on. Late rows alone give -0.1053
(z -12.4); early rows give +0.0196 (z +0.5) but carry only 549 pulls in
137,139 rows and resolve 0.109 at 3 sigma, so EARLY IS UNDERPOWERED, NOT A
NULL. Shipping the pooled, smaller value is the conservative reading.

**SCORED ON OUTCOMES**, 537 holdout games x 20 sims, arms PAIRED on seeds,
rates frozen before 2026-07-01 (`scratchpad/blowout_ab.py`):

                          OFF    SHIPPED   CONTROL x4    ACTUAL
    boundary share     0.5903     0.6151       0.6744    0.6695
    starter outs      15.6799    15.8203      16.1222    15.820
      sd               4.0334     4.0234       3.9904     4.040
    starter K          4.7880     4.8281       4.9108     4.840
    F5 runs / side     2.4495     2.4495       2.4511     2.437

The pre-registered prediction was that the boundary share must RISE, since
the term only ever removes mid-inning pulls. It closes 31% of the gap. The
CONTROL at x4 lands on 0.6744 and overshoots outs to 16.12, which is how a
reachable term is supposed to behave and is what makes the shipped column
small rather than uninformative.

**THE OUTS LEVEL LANDING ON 15.8203 AGAINST A REAL 15.820 IS A COINCIDENCE
AND MUST NOT BE READ AS A FIT.** Nothing in the fitting procedure saw an out
total — the target was `removed`, a manager's decision. Falsifier 2 was
"outs overshoot", and it did not fire; that is the falsifier passing, not the
coefficient being tuned.

**F5 IS DEAD FLAT (2.4495 -> 2.4495) AND THAT IS THE EXPECTED RESULT**, not a
refutation. The term changes WHICH ARM throws the late innings of a decided
game, and F5 stops at the fifth. Reported as a did-not-harm check.

**INDEPENDENTLY CONFIRMED ON `shape.py`**, same direction, different harness:
boundary share 0.588 -> 0.611, mean outs 15.65 -> 15.78, outs CRPS 2.0868 ->
2.0827, and o12.5 through o17.5 all improve. The cost is at the deep end —
o18.5 +0.028 -> +0.035 and o20.5 +0.015 -> +0.023, so the model now sends
slightly MORE starters past the sixth, which was already a defect.

**THE K TAIL IS UNTOUCHED**, as it should be: o8.5 -0.036 -> -0.034, K CRPS
1.3242 -> 1.3246. This is a margin mechanism, not the dominance mechanism
TODO item 7 is about, and it does not pretend to be.

**A HARNESS BUG WORTH RECORDING, BECAUSE IT IS THE DEFINITION TRAP AGAIN.**
The first A/B scored the boundary share as `outs % 3 == 0 AND NOT
pulled_mid_inning` and read 0.520 where the same engine scores 0.588.
`calibrate._boundary` is `outs % 3 == 0` and nothing else — necessarily, since
the 0.669 ACTUAL is computed from real out totals where no
`pulled_mid_inning` flag exists. A stricter model column against an unchanged
actual column is the same apples-to-oranges error as a denominator mistake.
NAME THE DEFINITION, not just the denominator.

415 checks (was 414). `check_margin_defaults_to_no_effect` was DELETED rather
than loosened — its premise ("both margin terms ship at zero, so this changed
no number") is obsolete by design — and replaced by two stricter checks:
`check_the_signed_margin_terms_stay_at_zero` and
`check_the_blowout_term_is_symmetric_and_suppresses_mid_inning_pulls`. Both
mutation-verified: wiring the coefficient onto signed `margin` fails the
symmetry assertion, and flipping its sign fails the direction assertion.
Fingerprint c7f3e41d -> 30cbdcad.

**AND THE STALE-CACHE TRAP FIRED AGAIN, ON A DIFFERENT FILE.**
`/tmp/hook_rows.json` was dated Aug 25 11:13; the labelling fix that moved
48.2% of the wrong rows out of the boundary training set landed Aug 27 00:09.
Every number above would have been computed on mislabelled rows had the cache
been trusted. CHECK THE MTIME OF A CACHE AGAINST THE COMMIT DATE OF THE CODE
THAT PRODUCES IT.

## DAY SEVENTEEN, PART TWO — THE HOOK COULD NOT TELL A DOMINANT NIGHT FROM A LUCKY ONE

**EVERY INPUT TO BOTH HOOK CURVES WAS TRAFFIC OR WORKLOAD** — pitches, runs,
baserunners, bases occupied, inning, batters faced. Nothing said how well he
was THROWING. That is TODO item 7's mechanism stated as a code fact, and it
is why the model's K per 27 outs keeps declining in long starts where
reality's jumps: a real seven-inning start is a SELECTED population, earned
by missing bats, and the simulator had no selection at all.

QUESTION    Conditional on everything the hook already reads, does strikeout
            rate so far change the removal decision?
HYPOTHESIS  Negative coefficient — the better he is going, the less likely he
            is interrupted. FALSIFIER: inside the resolvable band, or
            sign-unstable across seasons.
TEST        `boundary.decisions` gained a `k`/`k_rate` column (verified
            against the boxscore on a sample game: counted 4 and 3 against a
            boxscore 4 and 3). Rows rebuilt, 322,205 decisions.
            `scratchpad/hook_dominance.py`.

**THE CONTROL SET IS THE WHOLE ARGUMENT AND IS STATED FIRST.** A strikeout is
an out that allowed no baserunner, and it costs ~4.97 pitches against ~3.25
for a ball in play. So `pitches`, `bf`, `runs`, `inn_br`, `onbase`, `inning`
AND `abs_margin` all go in together; dropping any one hands its variance
straight to the strikeout column.

    curve         k_rate coefficient      z     per season
    mid-inning   -1.5130 +/- 0.1587    -9.5   -1.80/-1.11/-1.21/-1.83
    boundary     -0.3342 +/- 0.1614    -2.1   -0.14/-0.23/-0.29/-0.46

Positive controls fired on both (-2.0 injected, -2.03 and -1.71 recovered).

**MID-INNING SHIPS, BOUNDARY DOES NOT.** The boundary coefficient is
sign-stable but no season is individually significant and the pooled z is
-2.1 — a DIRECTION, not a finding. Recorded, not wired. Note this is the
SECOND time in one day the same split appeared: the mid-inning decision takes
in-game state and the boundary decision does not.

**SIZE:** the p10-p90 spread of `k_rate` is 0.444, so a dealing starter
carries -0.672 log-odds against a struggling one at the SAME pitch count,
runs, traffic and inning — a bit under half the odds of being pulled.

**IT SHIPS CENTRED, AND THE BLOWOUT TERM DID NOT — THAT ASYMMETRY IS
DELIBERATE.** `mid_per_abs_margin` arrived when mean outs were WRONG (15.68
against 15.82) and moved the level onto the actual. This one arrives when the
level is RIGHT, so uncentred it would subtract 1.5130 x 0.2276 = 0.344
log-odds from every mid-inning decision — a level change nobody measured,
riding in on a spread coefficient that was. Centred, it buys discrimination
and leaves the level alone.

**THE BASELINE IS 0.2276, THE MEAN OF THE PER-DECISION RATES, NOT THE 0.2260
RATIO OF SUMS — AND THE GAP BETWEEN THOSE TWO IS THE DEFECT ITSELF.** This
looked like an input bug for twenty minutes and is the most useful number of
the day. Measured at the hook, 20,712 simulated calls against 248,568 real:

                              mean of ratios   ratio of sums
        REAL                          0.2276          0.2260
        SIM (before the term)         0.2002          0.2254

The RATIO OF SUMS agrees to four decimals — the simulator's strikeout rate is
right, as everything else here has said. What differs is how decisions are
WEIGHTED. In reality the mean of ratios sits ABOVE the ratio of sums because
a high-strikeout starter lasts longer and accumulates more decisions. In the
simulator it sits BELOW, because `PITCH_COST` bills a strikeout 4.97 pitches
against 3.25 for a ball in play, **so a dominant night actively SHORTENS a
simulated start. The selection runs backwards.** Item 7 in one number.

**SCORED**, 537 holdout games x 20 sims, paired seeds
(`scratchpad/hook_ab.py`, which generalises `blowout_ab.py` and is the only
harness here that prints K BY START LENGTH):

                          OFF    SHIPPED         x4     ACTUAL
    boundary share     0.6151     0.6108     0.5969     0.6695
    starter outs      15.8203    15.7861    15.6333    15.8212
      sd               4.0234     4.0640     4.1910     4.0403
    starter K          4.8281     4.8191     4.7797     4.8389
      sd               2.2302     2.2571     2.3364     2.4893
      P(K >= 9)        0.0596     0.0609     0.0649     0.0950
    F5 runs / side     2.4495     2.4499     2.4466

    E[K] by start length
    0-8   outs        2.150      2.024      1.677      1.725
    9-11  outs        3.324      3.242      2.986      3.054
    12-14 outs        4.135      4.084      3.952      3.961
    15-17 outs        4.855      4.844      4.821      4.818
    18-20 outs        5.500      5.550      5.724      5.397
    21-27 outs        6.172      6.270      6.509      6.836

**THE SELECTION NOW RUNS THE RIGHT WAY:** short starts lose strikeouts and
long ones gain them, in five of six buckets toward the actual. K sd 2.2302 ->
2.2571 against a real 2.4893, and on `shape.py` the tail closes 11-15%
(o8.5 -0.036 -> -0.032, o9.5 -0.020 -> -0.017), outs CRPS 2.0868 -> 2.0819
and K CRPS 1.3242 -> 1.3240 across both of today's terms.

**THE COSTS, STATED PLAINLY:** boundary share 0.6151 -> 0.6108 and mean outs
15.8203 -> 15.7861, both small and both away from the actual. `k_rate` is
right-skewed (mean 0.2276, median 0.2000), so mean-centring leaves more
decisions below the centre than above and the net effect adds a few
mid-inning pulls. Mean-centring is kept because it is what the regression
implies; median-centring would be a choice nobody measured.

**AND THE MECHANISM IS NOT SUFFICIENT, WHICH IS THE MOST IMPORTANT LINE
HERE.** At x4 the measured coefficient P(K>=9) reaches only 0.0649 against a
real 0.0950 — 15% of a 4-sigma gap — while boundary share and outs both
degrade. **So the manager's response to dominance is real, measured and
NOT the main cause of the dead K tail.** `PITCH_COST` remains the named
suspect and is the next test.

417 checks (was 415). `check_a_dealing_starter_survives_the_mid_inning_hook_longer`
and `check_the_engine_passes_a_live_strikeout_rate_to_the_hook`, both
mutation-verified.

**A TEST THAT LOOKED LIKE IT GUARDED CENTRING AND DID NOT.** The first
version asserted `mid_removal_p(k_rate=BASELINE) == mid_removal_p(k_rate=None)`,
which an UNCENTRED build passes happily — it only proves None defaults to the
baseline. The mutation caught it: uncentring the term left the check green.
The assertion has to compare against a hook with the coefficient set to zero,
so that "contributes nothing at the baseline" is what is actually tested.
VERIFY BY MUTATION OR THE CHECK IS DECORATION.

## DAY SEVENTEEN, PART THREE — `PITCH_COST` IS EXONERATED, AND THE K TAIL IS A K-SPECIFIC DISPERSION DEFICIT

**TODO ITEM 7'S NAMED FIRST SUSPECT IS WRONG.** The item says "`PITCH_COST`
charges 4.97 pitches for a strikeout against 3.25 for an out, so a dominant
night actively SHORTENS a simulated start." The premise is arithmetically
incomplete: a dominant night also needs FEWER BATTERS, and the two cancel.

QUESTION    Is the pitch cost of an outcome flat across pitchers, as one
            league table assumes? And does the extra cost of a strikeout
            actually shorten an outing?
TEST        73,506 pitcher-games with a 300+ batter book elsewhere, 696
            pitchers, quintiled on a LEAVE-ONE-GAME-OUT strikeout rate so
            the grouping cannot contain the rows it grades.
            `scratchpad/pitch_cost_spread.py`.

    quintile   K rate   per K   per out   per BB   per hit    /PA
    Q1          0.186   4.863     3.303    5.763     3.269   3.764
    Q5          0.296   4.808     3.368    5.748     3.367   3.986

**PITCHES PER STRIKEOUT IS FLAT** — 4.863 to 4.808, a 1.1% decline. Real but
negligible (per-game 4.8797 +/- 0.0100 against 4.8111 +/- 0.0123). Elite
strikeout arms do NOT get their strikeouts materially cheaper. The flat table
is right.

**AND THE DENOMINATOR THAT DECIDES START LENGTH IS PITCHES PER OUT, WHICH IS
FLAT TOO:**

    quintile   K rate   outs/PA   pitches/out   pitches to 18 outs
    Q1          0.186     0.690         5.454                 98.2
    Q3          0.228     0.701         5.504                 99.1
    Q5          0.296     0.721         5.527                 99.5

A strikeout arm spends 5.9% more per BATTER and retires 4.5% more of them,
and the two cancel: everyone needs about 99 pitches for six innings. **PITCHES
PER BATTER WAS THE WRONG DENOMINATOR, AND IT IS THE denominator THE ITEM WAS
WRITTEN ON.**

**THE SIMULATOR REPRODUCES THE CANCELLATION ALMOST EXACTLY**
(`scratchpad/pitch_cost_sim.py`, 12,888 simulated starts, bucketed on the
pitcher's MODELLED rate):

    quintile   sim outs/PA   sim p/out   sim to 18   | real to 18
    Q1               0.694       5.460        98.3          98.2
    Q3               0.703       5.511        99.2          99.1
    Q5               0.725       5.430        97.7          99.5

If anything the simulator FAVOURS its strikeout arms slightly on pitch
budget. **THE PITCH-BUDGET CHANNEL IS CLOSED. Do not re-open it.**
(CAVEAT CARRIED: the real table includes relievers and the simulated one is
starters only, so the LEVELS are not comparable. The within-table flatness,
which is the claim, is established on each side independently.)

## THE ACTUAL CAUSE: THE MISSING VARIANCE IS STRIKEOUT-SPECIFIC

The sharpness term was rejected because it "closes 78-85% of the K tail and
costs an equal amount of outs CRPS". **THAT IS TRUE OF THE SPECIFICATION IT
WAS TESTED IN AND NOT OF THE MECHANISM.** `dispersion.LOAD` is a single
latent quality factor loading on FOUR rates — `k_pct` -1.0, `bb_pct` +1.0,
`hr_pct` +1.0, `babip` +1.0 — so a "sharp night" also suppresses walks,
homers and balls in play. Traffic is what the hook integrates, so the draw
was widening the LENGTH distribution as hard as the strikeout one.

Re-opened legitimately, because the DATA changed: the hook acquired a
dominance channel this morning. Pre-registered before running.

**FIRST, THE INTERACTION, AND IT IS A NEAR-NULL.** 2x2 on sigma x dominance,
paired seeds. The outs CRPS cost of sigma 0.10 falls from +0.0307 (dominance
off) to +0.0278 (on) — 9%, in the predicted direction and far too small to
rescue the term. The hypothesis that a correct length response would pay for
the noise is REFUTED at the size that matters.

**THEN, THE SPECIFICATION CHANGE, AND IT IS LARGE.** Loading the draw on
`k_pct` ALONE, everything else at 0.0:

                            base   full-load   K-only   K-only   actual
                            s=0     s=0.10     s=0.10   s=0.20
    K sd                   2.28        2.35      2.34     2.49     2.49
    o8.5 gap             -0.032      -0.026    -0.026   -0.010   (se 0.009)
    K CRPS               1.3240      1.3240    1.3205   1.3144
    outs sd                4.04        4.15      4.06     4.05     4.04
    outs CRPS            2.0819      2.1097    2.0938   2.0941
    boundary share        0.607       0.607     0.609    0.609    0.669

**K-only at 0.20 lands the strikeout sd EXACTLY (2.49 against 2.49), closes
69% of the o8.5 gap (-0.032 -> -0.010, now inside 1.1 sigma where it was
-3.5), improves K CRPS by 0.0096 — and leaves the OUTS sd on target at 4.05
against 4.04, where the four-channel draw overshoots to 4.15.** The outs CRPS
cost is +0.0122 against the four-channel +0.0278, for triple the K benefit.

**IT IS NOT SHIPPED AND MUST NOT BE SHIPPED ON THIS EVIDENCE. sigma = 0.20
WAS CHOSEN BY ME TO MAKE THE K SD LAND ON 2.49, WHICH IS SOLVING FOR A
SPREAD** — the exact move CLAUDE.md forbids, and the one every absorbed
constant in this project's history has in common. What is ESTABLISHED is the
SHAPE of the defect: the missing variance is STRIKEOUT-SPECIFIC and not a
general quality factor, which is why every previous test of this mechanism
read as a wash. What is NOT established is the magnitude.

**THE NEXT TEST, AND IT IS THE ONE THAT MATTERS:** COUNT the extra-binomial
strikeout variance in real starts — how much a real pitcher's start-to-start
K rate varies beyond what his season rate and that night's lineup imply — and
use THAT sigma. Note this is a different quantity from the closed
per-pitcher dispersion question (split-half 0.072 over 107 arms): that asked
WHICH pitchers are more variable, this asks how variable the league is. A
null on the former says nothing about the latter.

**FINGERPRINT LEDGER FOR DAY SEVENTEEN.** c7f3e41d at the start ->
30cbdcad after the blowout term -> **8af9d134** after the dominance term,
which is the shipped state. 414 -> 417 checks. Nothing in part three
changed a shipped constant, so the fingerprint is unchanged by it.

## DAY SEVENTEEN, PART FOUR — THE STRIKEOUT DISPERSION IS COUNTED: SIGMA 0.16, AND IT REFUTES MY OWN TUNED VALUE

**THE LEAGUE CARRIES REAL PER-START STRIKEOUT DISPERSION AND IT IS 0.154
RAW / 0.163 CALIBRATED, at 6.2 sigma from zero.** Counted, not fitted.
`scratchpad/k_dispersion.py`, 4,777 starts over three holdout windows
(2024/2025/2026, rates frozen before 1 July of each), 555 pitcher-windows
with two or more starts.

THE ESTIMATOR. Each start is a POISSON-BINOMIAL under the model: the
batters faced are independent draws whose per-plate-appearance strikeout
probabilities already carry log5, the specific nine, the times-through-the-
order decay and the home/road split. mu_i = sum p_ij, var_i = sum
p_ij(1-p_ij). Under k_pct -> k_pct * exp(sigma z) the per-start variance
gains mu_i^2 sigma^2, so sigma^2 = (S - sum var_i) / sum mu_i^2.

**S IS BUILT FROM WITHIN-PITCHER DEVIATIONS, AND THAT IS THE WHOLE DESIGN.**
A pitcher's rate carries estimation error which is CONSTANT across his
starts; an across-start variance would swallow it and read as dispersion.
That is precisely the trap that killed the home-run compression finding on
day fourteen. Deviations are taken inside each pitcher-window with the exact
(1 - 1/m) correction, so any persistent per-pitcher bias — including the
model being 2.5% light on K over these windows — cancels by construction.

**AND THE PITCHER KEY CARRIES THE WINDOW.** A pitcher's rate is re-estimated
in each holdout window, so pooling his 2024 and 2026 starts under one key
would put the difference between two RATE ESTIMATES into the within-pitcher
deviation and read as dispersion.

POSITIVE CONTROL, and it is what makes the number reportable:

    injected   recovered sig2   recovered sigma
        0.00         -0.00167           -0.0409
        0.10         +0.00486           +0.0697
        0.20         +0.03622           +0.1903
        0.30         +0.09534           +0.3088

The zero row is the estimator's own bias and is subtracted. **THE CONTROL
ALSO SHOWS THE ESTIMATOR UNDERSHOOTS AT SMALL SIGMA** — 0.10 comes back as
0.070 — so the raw answer is inverted through the injected->recovered curve,
which is legitimate only because that curve was built by INJECTION and not
fitted to the real data.

    raw sig2       +0.02203
    minus bias     -0.00167
    COUNTED        +0.02369   95% CI [+0.01615, +0.03119]   sd 0.00384
    calibrated      0.02642   =>  SIGMA 0.1625

**THE TUNED VALUE IS REFUTED BY THE COUNT. 0.20 means sig2 0.04000; the
league counts 0.0264, which is 4.2 sd away.** I chose 0.20 yesterday because
it made K sd land exactly on 2.49, and this is what that shortcut was worth:
it overstated the mechanism by 50% in variance. The count was worth doing.

**SCORED AT THE COUNTED VALUE** (K-only loading, sigma 0.16, 1,074 holdout
starts x 40 sims, against the shipped engine):

                    shipped   sigma 0.16   tuned 0.20    actual
    K sd               2.28         2.41         2.49      2.49
    o8.5 gap         -0.032       -0.018       -0.010   (se 0.009)
    o9.5 gap         -0.017       -0.007       -0.003   (se 0.006)
    K CRPS           1.3240       1.3195       1.3144
    outs sd            4.04         4.06         4.05      4.04
    outs CRPS        2.0819       2.0883       2.0941
    boundary share    0.607        0.607        0.609     0.669

At the COUNTED 0.16 it closes 62% of the K sd gap and 44% of the o8.5 gap —
taking the tail from 3.5 sigma wrong to 2.0 — improves K CRPS by 0.0045, and
costs 0.0064 of outs CRPS against the four-channel version's 0.0278. The
outs sd stays on target at 4.06 against 4.04.

**WHAT IS ESTABLISHED AND WHAT IS NOT.** ESTABLISHED: the league has
per-start strikeout dispersion at sigma ~0.16, measured out of sample with a
fired control and a within-pitcher design that removes rate error. NOT
ESTABLISHED: that the OTHER channels are undispersed. This counted `k_pct`
and nothing else. The four-channel draw failing is evidence that loading
walks, homers and balls in play at the SAME sigma is wrong — it is NOT
evidence that their true dispersion is zero, and each deserves its own count.

**NOT YET WIRED.** `dispersion.perturb` is a scratchpad instrument; the
shipped engine has no per-start rate draw. Wiring it into `game.build_side`
behind a flag, with tests and a mutation check, is the next step and is
mechanical now that the value is counted.

**A BOOTSTRAP THAT EXCLUDED ITS OWN POINT ESTIMATE, AND HOW IT WAS CAUGHT.**
The first interval came back [+0.00928, +0.02299] around a point of +0.02369
— outside its own CI, which is impossible for an honest percentile
bootstrap. Cause: `estimate` regroups rows by pitcher, so a pitcher drawn
twice merged into ONE group of 2m rows rather than appearing as two groups,
changing the deviations being squared. Each draw now gets a unique key.
The first version of the interval was also taken on percentiles of the
SIGNED SQUARE ROOT rather than of sig2, which is the quantity with a
symmetric sampling distribution. **AN INTERVAL THAT DOES NOT CONTAIN ITS
POINT ESTIMATE IS A BUG REPORT, NOT A WIDE ERROR BAR.**

## DAY SEVENTEEN, PART FIVE — TONIGHT'S STUFF IS WIRED IN

`sim.START_K_SIGMA = 0.1625`, `sim.sharpen`, applied in `game.build_side`
to the STARTER ONLY, behind `sim.USE_START_SHARPNESS`. The counted value
from part four ships; the tuned 0.20 does not.

**CENTRED, AND IT IS NOT COSMETIC.** A bare `exp(sigma*z)` has mean
`exp(sigma^2/2)` — at 0.1625 that is +1.33% of strikeouts on EVERY start, a
level change nobody measured riding in on a spread that was counted. The
draw is `exp(sigma*z - sigma^2/2)`, mean exactly one. The measurement was
taken around each pitcher's own rate, so his shipped `k_pct` is the average
of his nightly stuff, not his floor.

**STARTERS ONLY.** Nothing was counted for relievers and a one-inning outing
cannot separate a flat slider from three bad swings. Importing the starter's
number would be the "measured on starters, applied to every arm" error that
hit-by-pitch, sacrifices and wild pitches all carried.

**SCORED, AND THE FIRST SCORING WAS WRONG.** The paired comparison uses a
sigma of 1e-12, so the variate is still consumed and both arms run on the
SAME random stream:

    line          sigma~0   sigma 0.1625    actual     se
    K mean           4.82           4.81      4.84
    K sd             2.27           2.39      2.49
    o3.5 gap       +0.026         +0.008             0.014
    o4.5 gap       +0.014         +0.007             0.015
    o5.5 gap       -0.003         -0.006             0.015
    o6.5 gap       -0.014         -0.008             0.013
    o7.5 gap       -0.015         -0.003             0.011
    o8.5 gap       -0.032         -0.021             0.009
    o9.5 gap       -0.018         -0.010             0.006
    o10.5 gap      -0.012         -0.006             0.005
    K CRPS         1.3399         1.3420
    outs CRPS      2.1106         2.1211
    outs sd          4.03           4.06      4.04
    boundary share  0.611          0.609     0.669

**EVERY STRIKEOUT LINE ON THE BOARD MOVES TOWARD REALITY**, the sd closes
55% of its gap, and o8.5 goes from 3.5 sigma wrong to 2.3. Outs sd and
boundary share are untouched, which is the point of loading on `k_pct`
alone.

**THE CRPS COSTS ARE NOT RESOLVABLE AND I NEARLY REPORTED THEM AS A
REGRESSION.** The first scoring compared the wired engine against
`shape_DOM`, which consumed TWO FEWER VARIATES PER DRAW — the new draw
shifts the stream — and read K CRPS 1.3240 -> 1.3420 and outs 2.0819 ->
2.1211. Properly paired the costs are +0.0021 and +0.0105, while the same
engine on two different streams differs by 0.029 on outs CRPS. **THE SEED
MOVES IT ~3x FURTHER THAN THE MECHANISM DOES.** A stream shift is not a
paired A/B, and adding any draw to the engine creates one.

That CRPS reads flat-to-slightly-worse on a tail repair is the EXPECTED
result, not a refutation: CRPS is dominated by the bulk, and this mechanism
buys aggregate CALIBRATION rather than per-start DISCRIMINATION. It makes
the model hedge — which is more honest across a season and blurrier on any
one start, and CRPS charges for blur.

421 checks (was 417). Four new, all mutation-verified: uncentring fails the
mean-one assertion, loading walks fails the strikeouts-only assertion,
consuming a variate at sigma 0 fails the inertness assertion, and removing
the `build_side` call fails the wiring assertion.
Fingerprint 8af9d134 -> **1aefb445**.

**ONE TEST WAS SCOPED, AND IT IS NOT A LOOSENING.**
`check_strikeouts_cannot_exceed_outs` stresses the invariant with a 0.45
pitcher against a 0.40 lineup — a ~0.65 matchup, chosen deliberately. A
+2 sigma night takes it past 0.89, where walks and home runs can no longer
fit underneath and `pa_from` raises BY DESIGN. No real matchup is within
sight of that. Sharpness is held off there and
`check_strikeouts_cannot_exceed_outs_with_sharpness_on` covers the same
invariant at rates that occur in baseball, so no coverage was dropped.

**WHAT THIS CHANGES FOR PRICING.** The operator page says "DO NOT BET THE
MODEL'S HIGH-STRIKEOUT UNDERS" because at 8.5+ the model priced an over at
~60% of true. It now prices it at ~78%. The rule should be softened rather
than deleted — 2.3 sigma is better than 3.5 and is not zero.

## DAY SEVENTEEN, PART SIX — THE BOUNDARY CURVE DOES TAKE SOMETHING, AND IT IS THE BULLPEN

**THE FIRST EXTERNAL SIGNAL THE BOUNDARY DECISION HAS EVER ACCEPTED.** Every
fit today found it deaf to the game — signed margin +0.7 sigma, |margin|
sign-flipping across seasons, strikeout rate -2.1 with no season individually
significant — while its share sits at 0.609 against a real 0.669. The
hypothesis was that "does he come back out" is not a reaction to the game at
all but a RESOURCE decision. It is.

QUESTION    Conditional on everything the curves already read, does the
            state of the club's bullpen change the removal decision?
TEST        `scratchpad/pen_state.py`. Per (game, pitching club), reliever
            pitch counts reconstructed from play-by-play across 9,978 games,
            then each club's previous three games looked up by schedule.
            Joined to all 322,205 decisions — 100% coverage. `leash` is in
            the control set so the starter's own typical length is absorbed.

**IT IS ABOUT AVAILABILITY, NOT VOLUME, AND THAT IS THE FINDING.** Raw pitch
totals are null; counts of arms that CANNOT go are strong:

    column           BOUNDARY z   MID-INNING z   predicted
    pen_back2            -5.3          -5.2      negative  YES
    pen_rest             +6.3          +6.2      positive  YES
    pen_heavy_1          -1.9          -3.0      negative  YES
    pen_pitches_1        -0.8          -0.5      negative  null
    pen_pitches_3        +1.5          +1.6      negative  null
    pen_arms_1           +0.8          +0.4      negative  null
    pen_load             -0.5          -1.1      positive  null

`pen_back2` is the number of relievers who worked on BOTH of the club's last
two days — the actual unavailability rule a manager uses. `pen_rest` is days
since the club last played. A pen that is used up keeps the starter out
there; a rested pen gets him hooked. All four pre-registered signs are right
and the three that carry it are the three that describe WHO CAN PITCH rather
than HOW MUCH WAS THROWN. Positive control fired (0.01 injected, +0.0102
recovered).

**STABILITY GATE PASSED 8/8.** Sign held in all four seasons on BOTH curves:

    pen_back2  boundary   -0.108 / -0.108 / -0.089 / -0.075
    pen_back2  mid        -0.045 / -0.049 / -0.120 / -0.118
    pen_rest   boundary   +0.079 / +0.173 / +0.190 / +0.288
    pen_rest   mid        +0.160 / +0.258 / +0.052 / +0.237

**BOTH CONFOUNDS RUN AGAINST THE RESULT, WHICH IS WHY IT IS BELIEVABLE.**
(1) A club whose pen threw 120 pitches yesterday probably played a long or
losing game, which correlates with a bad club and a bad starter, and a bad
starter is pulled EARLIER — pushing `pen_back2` POSITIVE. It comes out
negative. (2) After an off day the STARTER is rested too, which should make
him go DEEPER and push `pen_rest` NEGATIVE. It comes out positive.

**SIZE.** `pen_rest` p10 1 to p90 2, so one day of rest is +0.186 log-odds
at a boundary. `pen_back2` p10 0 to p90 2, so the swing is -0.20. Both are
comparable to `mid_per_abs_margin` (-0.0824 per run over a p90 of 6) and
smaller than the dominance term's -0.67 p10-to-p90 swing. Real, and in the
size class of the two terms shipped this morning.

**NOTE `pen_pitches_1` IS A PROXY THAT ONLY WORKS ALONE.** Fitted without
`pen_back2` and `pen_heavy_1` it reads negative in all four seasons (-2.6 /
-1.7 / -0.9 / -1.6); with them it collapses to -0.8. It was carrying the
availability signal in the absence of anything better, which is what a
proxy does.

**NOT WIRED, AND THE PATH IS SPECIFIC.** Neither curve takes a bullpen
argument and `Side` has no usage state; the pen is redrawn independently
every game AND every draw. Wiring needs: two coefficients on BOTH curves
(this is the first mechanism that belongs on both), `pen_back2` and
`pen_rest` carried onto `Side`, a supplier that reads the club's last two
games, and CENTRING on the league mean so the level does not move — the
same rule `K_RATE_BASELINE` follows. It does NOT need a reliever deployment
model: these are club-level counts, and which specific arm gets the call is
a separate question that this measurement does not depend on.

**AND IT REOPENS A DEAD-LIST ITEM LEGITIMATELY.** "Bullpen availability" was
parked as "hook-adjacent by construction". The APPROACH is what changed: it
was previously conceived as a deployment question and is here a two-column
feature on the removal decision, which is a different thing and is measured
on real decisions rather than scored on runs.

## DAY SEVENTEEN, PART SEVEN — BULLPEN STATE WIRED, AND IT DOES NOT CLOSE THE BOUNDARY SHARE

The pre-registered question was whether wiring the bullpen mechanism closes
the 0.609-vs-0.669 boundary-share gap. **THE ANSWER IS NO, AND THE CONTROL
IS WHAT MAKES THAT A RESULT RATHER THAN A SHRUG.**

SHIPPED: `per_pen_back2` -0.09362 / `per_pen_rest` +0.18820 on the boundary
curve, `mid_per_pen_back2` -0.08883 / `mid_per_pen_rest` +0.17132
mid-inning, centred on `PEN_BACK2_BASELINE` 0.6943 and `PEN_REST_BASELINE`
1.1791, behind `sim.USE_PEN_STATE`. Refitted with ONLY these two columns so
the coefficients match what ships; they barely moved from the full fit
(-5.6/+6.4 against -5.3/+6.3).

`sim.pen_state(team, date)` reads a persisted `hook_penstate.json`, 39,178
keys. Unknown club or unknown date returns the league baseline, which
contributes exactly zero — never another club's bullpen.

**SCORED, 1,074 holdout starts x 40 sims:**

                        OFF     SHIPPED    x5 CONTROL    ACTUAL
    boundary share    0.609       0.609         0.606     0.669
    starter outs      15.75       15.75         15.73     15.82
      sd               4.06        4.07          4.18      4.04
    outs CRPS        2.1211      2.1170        2.1572
    starter K          4.81        4.81          4.80      4.84

**THE CONTROL FIRES AND THE BOUNDARY SHARE STILL DOES NOT MOVE.** At x5 the
outs sd goes 4.07 -> 4.18, so the term unambiguously reaches the decision —
and the share sits at 0.606. This is not an unreachable-mechanism null; it
is an answer.

**WHY, AND IT SHARPENS THE REMAINING PROBLEM.** The term is CENTRED, so it
changes WHICH games get an early hook and not HOW MANY do. The boundary
share is a LEVEL and every mechanism tried today is a SPREAD: margin,
dominance and now the bullpen all leave it at 0.607-0.611. **THE BOUNDARY
SHARE GAP NEEDS A LEVEL FIX — the shape of the boundary curve itself —
NOT ANOTHER FEATURE.** Three well-powered features in one day have now
failed to move it, which is the most informative thing known about it.

**IT SHIPS ANYWAY**, under the leverage-floor rule: counted on real
decisions, stability-gated 8/8, control fired, reaches the decision, and
neutral-to-slightly-better on outs CRPS (2.1211 -> 2.1170). It buys
discrimination between games — a club with a used-up pen genuinely gets a
longer start — which is what the objective asks for even when no summary
statistic moves. It is NOT credited with anything it did not do.

**A SILENT NULL, CAUGHT BY CHECKING COVERAGE.** The first persisted table
was keyed on FULL CLUB NAMES from the games table; the replay path carries
an ABBREVIATION ('COL'). Coverage was 0/1074 and every score came back
"no effect" — a completely believable result for a small mechanism. The
table now carries both key forms and coverage is 100%. **CLAUDE.md's "IDs,
NOT NAMES" rule has now cost this project twice. PRINT THE COVERAGE BEFORE
READING THE SCORE.**

421 -> 425 checks, four mutation-verified: uncentring fails the centring
assertion, flipping the boundary sign and dropping the boundary term both
fail the direction assertion, and removing the lookup fails the wiring
assertion. Fingerprint 1aefb445 -> see below.

**THE FINGERPRINT DID NOT MOVE AT FIRST, AND THAT WAS THE REAL BUG.**
1aefb445 unchanged after wiring, because `build_side` only looks the pen up
when handed a DATE and only `shape.py` had been given one. Eight callers
construct sides; the mechanism was live in a single scratchpad harness and
inert in `calibrate.replay`, `price.py` and the fingerprint itself. Now
wired in all three and the hash moves 1aefb445 -> **f5453dc2**.

**AN INERT MECHANISM AND AN ABSENT ONE PRODUCE THE SAME TABLE.** The
scoring above was run through `shape.py`, which was wired, so those numbers
stand. But had the boundary-share question been asked through
`calibrate.replay` it would have returned the same "no effect" for an
entirely different reason. A fingerprint that refuses to move after a
non-inert change is the cheapest possible detector of this and it worked.

**LIVE SLATES CURRENTLY FALL BACK TO LEAGUE-NEUTRAL, AND ANYONE PRICING
TONIGHT SHOULD KNOW IT.** `hook_penstate.json` is built from games with
status Final, and the pipeline DB is Final through 2026-08-27 — so there is
no row for today and `pen_state` returns the baseline, contributing exactly
zero. That is the SAFE failure (never another club's bullpen) but it means
the mechanism is inert precisely where it would be bet.

THE EXTENSION, and it is not a one-liner because of the missing-group rule:
building a row for today needs the club's schedule INCLUDING unplayed
games, while the lookback must come only from games whose play-by-play is
cached. A club whose previous game is uncached would read `pen_back2` 0 —
"fully rested" — which is a WRONG value rather than a neutral one, and this
project's rule is that an unknown resolves to league-neutral rather than to
a guess that moves the estimate the wrong way. So the builder must return
the baseline unless every game in the lookback window is cached.

## DAY SEVENTEEN, PART EIGHT — A THIRD HOOK BRANCH FOR HIGH PITCH COUNTS

**THE FIRST THING ALL DAY TO MOVE THE BOUNDARY SHARE.** Margin, dominance
and bullpen availability all left it at 0.607-0.611; this takes it to 0.625.

QUESTION    Do the SHIPPED curves under-pull a starter at high pitch counts?
HYPOTHESIS  Yes on both branches, more at the boundary. Pre-registered
            consequence: fewer very long starts and a HIGHER boundary share.
TEST        Every real decision scored through the SHIPPED `sim.Hook` rather
            than a refitted logistic, so the miss measured is the one that
            ships. `scratchpad/late_branch.py`, 322,205 decisions.

    pitches      boundary shipped/actual    mid shipped/actual
     0-60           0.0093 / 0.0105           0.0029 / 0.0030
     60-75          0.1123 / 0.0570           0.0268 / 0.0172
     75-90          0.3542 / 0.2659           0.0783 / 0.0671
     90-100         0.6406 / 0.7837           0.1721 / 0.2036
     100-130        0.8087 / 0.9717           0.3101 / 0.4026

**THE CURVE IS TOO FLAT, NOT MERELY TOO LAX AT THE TOP.** It over-pulls by
2x at 60-75 pitches and under-pulls by 20% at 100+. That is one shape error
with two symptoms, and it is the clearest statement yet of what is wrong
with the hook.

SHIPPED: `high_pitch_threshold` 90, `high_pitch_bnd` +0.8550 (24 sigma),
`high_pitch_mid` +0.2893 (13 sigma). Solved by bisection to match the
observed rate, not searched, so neither can pin at a grid edge.

**A BRANCH, NOT A REFIT, AND THE DISTINCTION IS LOAD-BEARING.** Refitting
the whole boundary curve on late rows was measured and made things worse
(mean outs 16.49 -> 16.74) because it is evaluated at every pitch count.
The rule — fit on the restricted population only when the curve fires only
there and something else covers the rest — is satisfied by a gated branch
with the existing curves untouched below it. Same shape as `early_innings`.

**THE OFFSETS RISE EVERY SEASON:** boundary +0.63 / +0.84 / +0.95 / +1.01
and mid +0.02 / +0.31 / +0.34 / +0.47 across 2023-2026. Managers are getting
quicker with a tiring starter. THE POOLED VALUE SHIPS as the conservative
choice — it under-corrects today by ~15% and cannot be accused of chasing a
trend. Revisit with a recency-weighted count, never by picking last season.

**SCORED**, 1,096 holdout starts x 40 sims:

                      before    after   actual     se
    boundary share     0.609    0.625    0.672  0.014
    outs CRPS         2.1170   2.0839
    mean outs          15.75    15.61    15.83  0.122
      sd                4.07     3.92     4.02
    o18.5 gap         +0.035   +0.010           0.011
    o20.5 gap         +0.024   +0.006           0.010
    o15.5 gap         -0.049   -0.057           0.015
    o16.5 gap         -0.033   -0.043           0.015
    o17.5 gap         -0.023   -0.037           0.015

**THE LONG-START OVER-PRODUCTION IS ESSENTIALLY FIXED** — o18.5 and o20.5
both fall inside one standard error, from +3.2 and +2.4 sigma. Outs CRPS
improves 0.033, which is LARGER than the 0.029 seed-to-seed wobble measured
earlier today, so it is a real win and the first one on outs all day.

**THE COST IS THE MIDDLE BAND, AND IT WAS PREDICTED BY THE SAME TABLE.**
Fixing the top while 60-90 still over-pulls shifts the whole distribution
short: mean outs 15.75 -> 15.61 (0.7 sigma, inside noise) and o15.5/o16.5/
o17.5 each about a point worse. The 60-90 over-pull is now the binding
defect and the measurement for it already exists above.

**NEXT AND OBVIOUS:** a middle branch, or the same treatment applied to
60-90 with a NEGATIVE offset. The counted values are in the table. That
should restore the level while keeping the tail fix, and is the natural
completion of this piece rather than a new idea.

434 -> 436 checks, three mutations caught: zeroing either coefficient fails
the fires-on-both-curves check, and removing the threshold gate fails the
leaves-early-counts-alone check. Fingerprint f5453dc2 -> see below.

**A BOOKKEEPING CORRECTION:** the check count quoted through the day as 425
was stale. Runner count and defined count agree exactly (434 before these
two, 436 after) and nothing is silently skipped.

## DAY EIGHTEEN — THE COUNTED PITCH HAZARD. MEASURED, WIRED, AND PARKED OFF.

The end of the whack-a-mole: the pitch backbone of both hook curves as a
COUNTED TABLE instead of one logistic. `scratchpad/pitch_hazard.py`,
294,884 TRAINING decisions (before 2026-07-01, the rule set yesterday).

**WHAT THE PARAMETRIC CURVE GOT WRONG**, its own predictions against reality
— and note the `shipped` column ALREADY INCLUDES yesterday's high-pitch
branch, so this is the miss that survived that patch:

    pitches   boundary shipped/real     mid shipped/real
     45-60       0.0264 / 0.0155        0.0101 / 0.0054
     60-70       0.0865 / 0.0416        0.0255 / 0.0134
     70-78       0.1907 / 0.1021        0.0507 / 0.0298
     78-85       0.3366 / 0.2207        0.0863 / 0.0594
     95-100      0.8463 / 0.9093        0.2888 / 0.2610
     100+        0.9074 / 0.9719        0.4076 / 0.4013

**IT PULLS ROUGHLY TWICE TOO MANY MEN BETWEEN 60 AND 85 PITCHES.** That is
the middle-band defect the third branch made worse, seen at its source.

SOLVED CONDITIONAL on the other shipped terms, never read off as a marginal
rate — a bucket's raw rate already contains the runs and traffic that occur
at that pitch count, and substituting it directly double-counts them.

**EXPRESSED AS AN OFFSET FROM `intercept`, NOT AS AN ABSOLUTE LEVEL, AND
GETTING THAT WRONG COST SIX CHECKS.** Callers disable the hook by driving
`intercept` / `mid_intercept` to -99 — team_offset, the patience fits and
every never-pull test use that idiom. A backbone with its own absolute level
goes on pulling people regardless. `late_mid_offset` has a docstring saying
exactly this and I did it anyway.

**BUCKET WIDTH IS A MECHANISM, NOT A PRESENTATION CHOICE.** The first cut
used 0-45 as one bucket and charged a 20-pitch starter the same hazard as a
44-pitch one, raising first-inning removals from ~0.0005 to ~0.006. Refined
to 0/25/40/50/60/70/78/85/90/95/100.

**PARKED OFF. TWO CHECKS FAIL AND NEITHER IS ALLOWED TO BE LOOSENED AWAY:**

  1. `check_the_boundary_curve_is_the_fitted_one` pins removal_p(105) into
     (0.55, 0.95). The table gives 0.957 and the REAL 100-110 rate is 0.972,
     so THAT BAND NEVER CONTAINED THE TRUTH — it was drawn around the old
     curve. Re-pin against the counted hazard, which is what the check's own
     comment says it is for. This one is the check's fault.
  2. `check_the_first_inning_is_immune_to_a_bullpen_flag` — NOT obviously
     the check's fault, and the more interesting one. Once first-inning
     pulls actually happen, toggling `USE_MEASURED_RELIEF_HOOK` moves F1
     even with an EMPTY pen. **THE CHECK WAS PASSING VACUOUSLY** because the
     old curve never exercised that path. That is precisely the attribution
     bug it was written to catch, so it gets answered rather than widened.

Fingerprint unchanged at 00584230 with the flag off, so nothing shipped
moved. 436 checks green.

**NEXT, IN ORDER:** answer (2) — does an empty pen handle a first-inning
removal correctly? — then re-pin (1) against the counted rate, then switch
on and score boundary share, outs CRPS and the 12.5-17.5 band. The
prediction to hold it to: the middle band should improve, because that is
where the old curve is out by a factor of two.

## DAY NINETEEN — THE OUTS CORRECTION, RE-MEASURED. AND THE BOARD AS A PAGE.

Two things, both small, both bookkeeping that had gone quietly wrong.

### THE CORRECTION TABLE WAS STALE AND ONE END OF IT WAS THREE TIMES TOO BIG

`scratchpad/outs_adjust.py` was measured on 2026-08-29 BEFORE the high-pitch
hook branch shipped, and both landed in the same commit (884db48), which is
why nobody noticed. TODO 8d recorded the debt and it sat for a day.

RE-MEASURED on the shipped engine: `scratchpad/shape.py 40`, holdout
2026-07-01+, 564 games / 1,128 starts, rates frozen before the cut, leash
on, dispersion off. Output kept at `scratchpad/shape_0830.out`.

    line     old gap   NEW gap      se
    o12.5     -0.039   -0.036    0.012
    o14.5     -0.065   -0.067    0.013
    o15.5     -0.049   -0.052    0.015
    o16.5     -0.033   -0.040    0.015
    o17.5     -0.023   -0.032    0.015
    o18.5     +0.035   +0.011    0.011
    o20.5     +0.024   +0.008    0.010

**WHAT MOVED WAS THE LONG LINES AND ONLY THE LONG LINES.** o18.5 +0.035 ->
+0.011 and o20.5 +0.024 -> +0.008, both now UNDER ONE SIGMA. The high-pitch
branch stopped the model over-producing long starts, so the bias it was
correcting is gone and the old table was applying roughly THREE TIMES too
much correction at o18.5 — on a live board, on the over side, at the exact
lines where a long-start bet gets priced.

**AND THE MIDDLE BAND DID NOT MOVE, WHICH REFUTES HALF OF WHAT 8d PREDICTED.**
8d said the stale table "under-states the middle-band error". Measured, the
band moved 0.003 to 0.009 against an se of 0.012 to 0.015 — directionally
right, nowhere near resolvable. **The prediction was written from the
mechanism rather than from a measurement and it should have been stated as a
guess.** What the re-run actually bought was the long lines; the 12.5-17.5
band was re-confirmed at 2-5 sigma, not corrected.

`HOLDOUT_MEAN_OUTS` 15.75 -> 15.61. It is compared against a MODEL
projection to flag extrapolation, so it must be the model's holdout mean and
not reality's 15.80. The old value was neither.

Boundary share now reads 0.626 against a real 0.674 (3.4 sigma), matching the
post-branch figure in RESUME. The defect is still there; it is the placement
of the 18-out mass, reality 24.4% against the model's 20.1%.

**THE STANDING RULE THIS PRODUCES:** a correction is only as current as the
hook underneath it, and a hook change invalidates it silently. So the date
is now a constant (`MEASURED_ON`), both board views PRINT it, and a check
fails if a page implies currency without one. The re-measure costs TWELVE
SECONDS on 7 workers — the reason it went stale was not cost, it was that
nothing displayed its age.

**AND I ESTIMATED THAT RUN AT TWENTY MINUTES, OUT BY A FACTOR OF A HUNDRED.**
`shape.py` has forked over `cpu_count() - 1` since it was written. The
estimate was a guess presented as a cost, and the user asking "even with
parallelization?" is the only reason it got checked. TIME A CAPPED RUN
BEFORE QUOTING A DURATION — 40 games took 6 seconds and extrapolated
correctly.

### THE BOARD RENDERS A PAGE NOW

`scratchpad/board.py --html` writes `scratchpad/board_<date>.html`. The
visual system moved out of `scratchpad/dash.py` into `scratchpad/dashkit.py`
and both pages share it.

**ONE PAYLOAD, TWO VIEWS.** `build()` simulates and prices; `print_board()`
and `board_html.render()` both READ what it returns. The samples travel, not
the summary statistics, so the page bins them the same way the terminal does
and neither can quote a different price for the same line — pinned by
`check_board_two_views_agree_on_the_fair_price`, which exists because two
`american()` definitions do.

**THE LAYOUT ENCODES THE TRUST ORDERING** rather than listing three markets
as equals: strikeouts lead, outs is demoted behind its warning, F5 gets a
card per game. A flat table asserts they are equally trustworthy and they
are not.

**A FRAGMENT, NOT A DOCUMENT** — `<title>` + `<style>` + body, no doctype.
A browser hoists the tags and the Artifact publisher accepts the same file,
so one string serves both. The cost is that there is no `<meta charset>`, so
the page must be ASCII. **THE FIRST LIVE RUN BROKE ON THIS AND THE TEST
SUITE DID NOT CATCH IT:** rosters carry accented names and `gamestate`
writes its decline reason with an em dash. Escaping now happens at the
render boundary (`dashkit.esc`) and is pinned. The synthetic payload was
ASCII, which is exactly why a synthetic payload is not a substitute for one
live run.

23 checks in `tests/test_board.py`, every one verified by mutation. 461
green.

## DAY TWENTY — TWO NULLS ON THE HOOK, AND THE RULER WAS WRONG

Chasing the boundary-share defect. Three well-powered tests, two nulls, and
the headline number shrank by 38% because it was measured with a rule that
mislabels one real start in thirteen.

### 1. THE PITCH TERM CAN BE FIXED AND IT DOES NOT MOVE THE SPLIT

Scored the counted pitch hazard (`sim.USE_PITCH_HAZARD`) against the
shipped parametric curve, and a third arm with the high-pitch branch laid
back on top. Mean |error| across all seven outs lines:

    shipped          0.0351      band 12.5-17.5 0.0454   long 0.0095
    counted hazard   0.0254      band 0.0186             long 0.0425
    hazard + branch  0.0156      band 0.0124             long 0.0235

Hazard+branch is much the best-shaped outs distribution yet: mean and sd
both inside noise (0.4 sigma) where the shipped curve is 1.6 sigma short.
**BUT BOUNDARY SHARE DID NOT MOVE IN ANY ARM: -0.050, -0.060, -0.060.** The
outs distribution reshaped substantially and the split sat still. The pitch
term is not the lever, which `boundary.py` had already said — it counted
83.3 pitches against 82.6 on the two branches and concluded pitch count does
not distinguish them. This re-derived it the expensive way.

DO NOT SHIP HAZARD+BRANCH AS IT STANDS. `high_pitch_bnd` was FITTED by
bisection; bolting it onto a COUNTED table is the pattern that produces
absorbed defects. The honest version is one more counting pass — re-solve
the top buckets against the MODEL's state distribution rather than
reality's. `scratchpad/hz_branch.py` is the probe, not a candidate.

WHY THE TABLE ALONE RUNS LONG, measured (`scratchpad/hz_states.py`): NOT
pitch accumulation. Pitches per out is 5.474 model against 5.466 real. The
model exits at 100+ pitches on 18.2% of starts against a real 13.4% and
under-exits at 78-95, so the miss is CONDITIONING — the buckets were solved
against real rows' states and are applied to the model's.

### 2. OUT COUNT IN THE INNING — RAW 29.6 SIGMA, CONDITIONAL NOTHING

`boundary.MID_FEATURES` has listed `outs_before` since the curves were
split and `mid_removal_p` never took it. `Frame` carries `outs` separately
from `damage`, `runs` and `br`, so with two down and nobody on every value
the hook receives is identical to nobody out and nobody on. It looked like a
missing mechanism with the variable already in hand.

COUNTED (`scratchpad/mid_outs.py`), 227,473 training mid-inning decisions:
1.63% / 2.25% / 5.96% by outs already recorded, +29.6 sigma, surviving
inside every pitch band (+9.9 to +17.4) and every damage band. **AND THE
DIRECTION IS THE OPPOSITE OF THE OBVIOUS GUESS** — a manager does not let
him finish, he pulls the man who could not close it out. My stated
hypothesis was backwards and the count said so immediately.

SOLVED CONDITIONAL on the other shipped terms (`mid_outs_fit.py`), which is
the only way to read it: **-0.043 / -0.250 / -0.098, two-out contrast -0.055
log-odds at -1.6 sigma. NULL.** The raw effect is entirely the traffic and
damage that come with a two-out rally, which the hook already reads through
`late_mid_per_inning_br`, `late_mid_per_onbase` and `mid_per_inning_run`.

POSITIVE-CONTROLLED (`mid_outs_control.py`): planted +0.600, recovered
+0.562 at 17.9 sigma; the harness resolves an effect of that size at 19
sigma. The null is real. The wiring was written, verified bit-identical at
zeros, and REVERTED — a zeroed parameter in the hot path is dead weight.

### 3. DO THE TWO HOOKS NEED TO SEE EACH OTHER? NO.

Bucketed every training mid-inning decision by the SHIPPED boundary hazard
at the same state and solved the mid offset each bucket needs.

    bnd P    shipped backbone    counted hazard
    0.00           +0.379            -0.062
    0.02           -0.590            +0.046
    0.05           -0.762            +0.121
    0.12           -0.512            +0.093
    0.25           -0.322            +0.163
    0.45           -0.083            +0.122
    spread    1.14 (-7.4 sigma)   0.22 (+3.0 sigma)

Under the shipped curve there is a 7.4-sigma bend that looks exactly like
the interaction: the mid curve over-fires precisely where the boundary
decision is live. **IT IS NOT AN INTERACTION. It is the parametric mid pitch
term being the wrong shape**, and the counted table absorbs 80% of it and
flips the sign of what is left. Positive-controlled: a planted -1.0 on the
top bucket came back -0.979 with the other buckets flat, so the harness does
not manufacture the pattern.

A SIDE RESULT WORTH MORE THAN THE NULL: this is independent evidence FOR
the counted pitch hazard. A defect that shows up as a spurious interaction
under the old backbone disappears under the new one.

### 4. THE RULER. THE DEFECT IS 38% SMALLER THAN REPORTED ALL SESSION.

`shape.py` calls a start boundary if `outs % 3 == 0`; `boundary.py` reads
the removal event from play-by-play. On the SAME 1,128 holdout starts
(`scratchpad/bnd_rulers.py`) they give 0.674 and 0.596 — and they disagree
on 88 starts, **every one of them the same way**: pbp says mid, the out
count says boundary. Zero disagreements in the other direction.

The category is the starter who comes out for one more inning and is chased
before recording an out. Fifteen outs on his line, divisible by three, and
he was pulled mid-frame.

The simulator does not have to infer it — `StartResult.pulled_mid_inning` IS
the decision. Both rules on both sides (`scratchpad/bnd_truth.py`):

    out-count rule    model 0.626   real 0.674   gap -0.048  (3.3 sigma)
    EVENT rule        model 0.566   real 0.596   gap -0.030  (2.1 sigma)

The out-count rule mislabels 6.0% of model starts and 7.8% of real ones, so
it flatters reality more than the model and EXAGGERATES the gap. **Every
boundary-share number quoted in these notes before today is the inflated
one.** The defect is real and it is 2.1 sigma, not 3.3.

THE RULE, and CLAUDE.md already had it: when a new number contradicts an old
one, check they measure the same thing BEFORE acting. `boundary.py` said
63.2% and `shape.py` said 67.4% and both numbers sat in the docs for days
while every session treated the difference as noise.

**NEXT.** Re-solve the pitch-hazard top buckets against the model's own
states (item 7). Do not chase the boundary split with another hook term
until that ships and the split is re-read on the EVENT rule.

## DAY TWENTY, PART TWO — PITCH x INNING. IT MOVES ITS TARGET. OFF PENDING A RE-CENTRE.

QUESTION    Is seventy pitches in the third a different decision from
            seventy in the fifth, beyond what the curves already read?

HYPOTHESIS  Yes. Both take `pitches` and the inning as SEPARATE ADDITIVE
            terms, so neither can say "this many pitches, this early".
            Counted on DAY SEVEN — 70 pitches pulled 6.01% in the third
            against 1.62% in the fifth, a 3.7x span — written down, and
            never built. Thirteen days.

TEST        An offset per (pitch band x inning) cell, SOLVED conditional on
            every other shipped term, each curve on its own population,
            training rows only. `scratchpad/pxi.py`.

            NOT PITCHES PER INNING. I proposed that first and it is a DEAD
            END ALREADY IN THESE NOTES: it folds back on itself, because
            high pitches-per-inning early means FEW total pitches. Day seven
            measured it non-monotone (1.68% / 4.77% / 3.14%) against a
            monotone 75x span for raw pitch count. My "discovery" of a
            U-shape was that artifact. READ THE DEAD LIST BEFORE PROPOSING.

            SUB-45 CELLS EXCLUDED from the table and from the centring.
            They solve to +0.9 and +1.1, which is the DISASTER TAIL — a
            starter gone that early was chased or hurt, not out-managed.
            That is the early-exit mixture's population and
            `early_exit_floor` exists to stop the hook competing for it.
            Day seven's `early_innings` branches fixed the tail from inside
            the curve and paid in spread (SD 4.47 against a real 3.99).

EVALUATE    Positive-controlled: planted +0.8 and -0.8 into two cells,
            recovered +0.924 and -0.617.

            THE PRE-REGISTERED TARGET WAS THE BY-INNING MID-EXIT PROFILE
            (`scratchpad/mid_by_inning.py`) and BOTH CELLS LANDED:

                inning    shipped    pxi on    real
                4          +0.020    +0.007    0.046
                5          +0.032    +0.035    0.084
                6          -0.029    +0.008    0.156
                TOTAL      +0.038    +0.057    0.399

            Fourth-inning over-pull and sixth-inning shortfall both inside
            noise. **This is the first mechanism this session that moved the
            thing it was aimed at.** Everything else — the out count, the
            hook interaction, mound visits — washed out under a conditional
            solve.

            AND IT COSTS TOO MUCH ELSEWHERE. Outs SD gap -0.110 -> -0.330,
            mean -0.190 -> -0.250, total mid share +0.038 -> +0.057.
            Boundary share did not move (-0.050 -> -0.060). Outs CRPS
            IMPROVED, 2.1021 -> 2.0732, and that is exactly the trap
            CLAUDE.md documents: CRPS is dominated by the bulk and reads a
            narrowing distribution as an improvement.

CONCLUSION  **NOT SHIPPED. `sim.USE_PITCH_X_INNING = False`.** Off is
            bit-identical; 463 checks green.

            ESTABLISHED: the interaction is real, it is absent from both
            curves, and correcting it fixes the fourth and sixth innings.
            REFUTED: that it can be shipped centred on the TRAINING rows.

            **WHY THE LEVEL LEAKED, and it is the third time today.** The
            table was centred on the row-weighted mean of REAL decisions,
            which assumes our simulated games land in those cells at the
            same rates real games do. They do not. So offsets meant to
            REDISTRIBUTE pulls ADDED them. Same failure as the counted
            pitch hazard running starters long, same failure as the
            out-count conditional not proving the marginal. **A CENTRED
            TABLE IS ONLY CENTRED WITH RESPECT TO SOME OCCUPANCY, AND OURS
            IS NOT REALITY'S.**

NEXT STEPS  Re-centre against the MODEL's cell occupancy: simulate, count
            how often each cell is reached, subtract THAT weighted mean,
            re-score. If the profile holds and the level and spread come
            back, it ships. This is the same iteration the pitch hazard
            needs and they should be done together, since both touch the
            pitch backbone and fitting them apart double-counts.

## DAY TWENTY, PART THREE — PITCH x INNING FAILS CROSS-VALIDATION. REFUTED.

QUESTION    Does the interaction improve cell-level fidelity in EVERY
            season, and is the uniform mid-inning offset a property of our
            simulator or of one stretch of games?

TEST        Four folds, July onward of 2023/2024/2025/2026. Table REFIT on
            every row outside the fold, fold simulated, hazard compared to
            the real rate cell by cell. `scratchpad/pxi_cv.py`. All four
            reported by construction.

            **THE DATA WAS THERE ALL ALONG AND I SAID IT WAS NOT.** Four
            full seasons of boxscores and batting, 10,021 cached
            play-by-play games, and `paired_cases` builds for prior seasons
            once `season=` is passed. CLAUDE.md still says 2,006 games —
            five times out of date, and that stale line is why I claimed
            for two turns that only 2026 could be simulated.

EVALUATE                boundary off -> ON      mid off -> ON
            2023        0.0590 -> 0.0638        0.0305 -> 0.0428
            2024        0.0516 -> 0.0518        0.0221 -> 0.0293
            2025        0.0401 -> 0.0325        0.0211 -> 0.0259
            2026        0.0420 -> 0.0223        0.0204 -> 0.0184

            Boundary: better in two folds, flat in one, WORSE in 2023. Mid:
            worse in three of four.

            AND THE CONSTANT IS NOT CONSTANT. Mid signed offset with the
            table on: +0.0428 (2023), +0.0293 (2024), +0.0254 (2025),
            +0.0181 (2026) — a monotone trend by season. The "thirteen of
            fourteen cells miss by the same amount, so subtract it" reading
            was one fold's property.

CONCLUSION  **REFUTED. `sim.USE_PITCH_X_INNING` stays False.** The tables
            stay in `sim.py` with this verdict attached so nobody refits
            them without reading it.

            ESTABLISHED: the RAW phenomenon is real (70 pitches in the
            third pulled 6.01% against 1.62% in the fifth, day seven, and
            the conditional solve reproduces it). What is refuted is that a
            cell table of those offsets TRANSFERS — it does not survive a
            season it was not fitted on.

            **THE METHODOLOGICAL FINDING, AND IT IS THE VALUABLE ONE.**
            With the flag OFF the baseline cell error ranges 0.0401 to
            0.0590 across seasons. **THE BETWEEN-FOLD SPREAD IS LARGER THAN
            THE EFFECT BEING MEASURED.** Every single-fold standard error
            quoted today was therefore optimistic, and every conclusion
            drawn from the 2026 fold alone — including "a clear win on the
            boundary curve" — was under-powered. One holdout is not a
            measurement of generalisation when the folds themselves differ
            by more than the change.

            THE SEQUENCE THAT PRODUCED THE ERROR, recorded because it will
            recur: iterate against one fold, watch a number improve, build
            a story for the residual ("it is a uniform constant"), propose
            to correct the constant — on the same fold. The user asked "was
            the holdout random", then "why not pull a month from earlier",
            and both questions were the ones that broke it open.

NEXT STEPS  If this is re-opened, the unit of evidence is FOUR FOLDS, not
            one, and the pre-registered bar is improvement in all four.
            Item 7's counted pitch hazard has never been cross-validated
            either and its 12.5-17.5 band result rests on the same single
            fold — that should be run before it ships.

## DAY TWENTY, PART FOUR — THE DEFECT IS THE FOURTH INNING, AND ONLY THAT

QUESTION    The model over-pulls starters mid-inning in all four seasons.
            On 2026 the excess sits in innings 3-5 with a shortfall in the
            sixth. Is that shape the same everywhere?

TEST        `scratchpad/mid_inning_cv.py`. Model against real, mid-inning
            starter exits as a share of ALL starts, by inning, July onward
            of each season. Both sides by the removal EVENT.

            AND THE CONTROL THE USER ASKED FOR AND I HAD NOT RUN: the REAL
            profile per season, printed alongside. Without it a moving gap
            is ambiguous between "our model is inconsistent" and "real
            baseball changed and we lag it".

EVALUATE    THE REAL PROFILE IS NOT UNIFORMLY STABLE.

                inning    2023    2024    2025    2026
                4        0.047   0.043   0.044   0.046
                5        0.080   0.105   0.112   0.084
                6        0.125   0.149   0.135   0.156
                7        0.071   0.072   0.070   0.068

            Innings 2,3,4,7,8 barely move. THE FIFTH SWINGS 40% AND THE
            SIXTH 25%. Managers really did move when in that window they go
            and get a starter.

            OUR GAP SPLITS THE SAME WAY (model minus real, * = 2 se):

                inning     2023     2024     2025     2026
                3       +0.010*  +0.013*  +0.007   +0.012*
                4       +0.024*  +0.022*  +0.023*  +0.022*
                5       +0.041*  +0.011   +0.005   +0.027*
                6       +0.003   -0.018   -0.007   -0.028*

CONCLUSION  **THE FOURTH INNING IS THE DEFECT AND IT IS THE ONLY ONE THAT
            REPLICATES.** +0.022 to +0.024 in all four seasons, all
            significant, a spread of 0.002 over four years — 6.9% of starts
            against a real 4.5%. The third is a consistent, smaller
            positive.

            REFUTED: the "innings 3-5 excess with a sixth-inning shortfall"
            profile. The fifth varies eight-fold across seasons and the
            sixth-inning shortfall exists only in 2026. Both sit on real
            behaviour that is itself unstable, so a fix aimed there would be
            aimed at one season.

            A NUMBER I CARRIED ACROSS TWO MEASUREMENTS THAT WERE NOT THE
            SAME THING. I described the over-pull as shrinking monotonically
            2023->2026 (+0.029/+0.018/+0.012/+0.006). That was PER-DECISION
            HAZARD averaged over cells. On SHARE OF STARTS the totals go
            +0.065/+0.017/+0.033/+0.043 — no trend. CLAUDE.md's rule 11
            exactly, and I broke it inside one session while quoting it.

NEXT STEPS  Aim at the FOURTH INNING specifically and pre-register the bar
            as all four folds. Do not build against the 5th/6th profile.
            The tooling for both is now written: `mid_inning_cv.py` for the
            profile, `pxi_cv.py` for cell-level cross-validation.

## DAY TWENTY, PART FIVE — `pen_heavy_1` FAILS THE STABILITY GATE

QUESTION    `pen_heavy_1` measured -3.0 on the mid-inning curve on day
            seventeen with the pre-registered sign correct, and was never
            wired. `pen_back2` and `pen_rest` passed a four-season gate 8/8;
            heavy was never put through one. Does it hold?

TEST        `scratchpad/pen_heavy_gate.py`. Coefficient and z on the mid
            curve conditional on the other shipped terms, fitted WITHIN each
            season, train rows only.

            HARNESS CHECKED FIRST, because a single-season number that
            contradicts a pooled one is usually the harness. Pooled:
            `pen_heavy_1` -3.4 (recorded -3.0), `pen_back2` -4.3,
            `pen_rest` +4.2. Reproduces; the seasons are comparable.

EVALUATE        2023  -0.0985  z -2.7   holds
                2024  -0.0963  z -3.1   holds
                2025  +0.0027  z +0.1   WRONG SIGN
                2026  -0.0441  z -1.2   weak

CONCLUSION  **FAILS. 2 of 4. Not wired, and now there is a recorded reason.**
            The pooled -3.4 is carried entirely by 2023 and 2024. Availability
            is BINARY — `pen_back2`, two days running, 8/8 — and a heavy
            outing yesterday does not reliably change the decision.

            **THE SCREEN WOULD HAVE SAID WHATEVER SEASON I DREW.** The plan
            was one season first as a cheap kill. I pre-registered 2025 and
            it read +0.1, which kills it. Had I drawn 2024 it reads -3.1 and
            I report "holds, run all four". One season is not a weak version
            of the gate; it is a coin flip with a narrative attached.

            This closes the last unshipped bullpen column. The fourth-inning
            defect now has EIGHT eliminated mechanisms against it: pitch
            count (3 backbones), out count in the inning, mid/boundary
            interaction, mound visits, pitches per inning, pitch x inning,
            bullpen state x inning, and `pen_heavy_1`.

## DAY TWENTY, PART SIX — THE FOURTH INNING IS 40% OF THE OUTS ERROR

QUESTION    Both curves over-pull in the fourth. If those excess pulls did
            not happen, how much of the outs-ladder error goes away?

TEST        ORACLE, by subsetting a persisted simulation
            (`scratchpad/starts_dump.py` -> `starts_query.py`). Remove the
            measured excess of fourth-inning exits and let those starts
            continue as the SAME PITCHER'S surviving starts did.

EVALUATE    line      now    oracle    real
            o12.5    0.775   0.808    0.812
            o14.5    0.673   0.701    0.741
            o15.5    0.489   0.509    0.543
            o16.5    0.442   0.460    0.484
            o17.5    0.382   0.397    0.416
            mean|gap|  0.0363 -> 0.0219   (-40%)
            mean outs  15.62  -> 15.82    (real 15.81)

            Mid-inning excess alone: -26%. Adding the boundary excess: -40%.
            Mean start length goes from 0.19 outs short to EXACT.

CONCLUSION  **THE FOURTH INNING IS THE LARGEST IDENTIFIED PIECE OF THE OUTS
            ERROR.** 3.4% of starts, and 40% of the ladder gap. It
            replicates in all four seasons on the mid curve (+0.022 to
            +0.024, all significant) and shows on the boundary curve in the
            2026 cell comparison (+0.041 at 60 pitches).

            UPPER BOUND, and the caveats all push one way: substituting a
            survivor's line is first-order, later pulls are not modelled,
            and the long lines get slightly worse (o18.5 +0.012 -> +0.019).

            **AND THE PRIORITY CALL I MADE EARLIER WAS WRONG, ON A
            DENOMINATOR.** I costed this defect in RUNS (~0.01-0.02) against
            `leverage.py`'s 0.05-RUN floor and called it low priority. Outs
            props do not settle on runs. In the denominator that matters it
            is 2-3 points of probability per line and 40% of the ladder.
            CLAUDE.md rule 10 — name the denominator — and I named the wrong
            one while quoting the rule.

            EIGHT MECHANISMS ARE ELIMINATED AGAINST IT (three pitch
            backbones, out count, mid/boundary interaction, mound visits,
            pitches per inning, pitch x inning, pen x inning, pen_heavy_1).
            None of that was wasted: it is now a well-localised, well-sized,
            four-season-verified defect with a long list of what it is not.

NEXT STEPS  The simulation is PERSISTED now (`starts_holdout.json`, 46,000
            starts) so questions of this shape are a query, not an engine
            run. Every harness written today re-simulated; none of them had
            to.

## DAY TWENTY, PART SEVEN — SHIPPED: THE COUNTED MID-INNING HAZARD, MID CURVE ONLY

The one thing that survived. `sim.USE_PITCH_HAZARD = True`,
`sim.USE_PITCH_HAZARD_BND = False`.

**THE UNIFICATION THAT MADE IT OBVIOUS, and it was the operator's.** The
fourth-inning defect and the pitch backbone's over-pull at 60-85 pitches are
THE SAME DEFECT — 60-85 pitches IS the fourth inning. Turning the counted
table on takes the fourth-inning exit gap from +0.033 to -0.007 and more than
halves the sixth-inning shortfall. Eight mechanisms died today because they
were aimed at a symptom of something already built.

**AND ONLY HALF OF IT SHOULD SHIP, which was also the operator's.** Scored
bucket by bucket against real holdout rates (`scratchpad/hz_cells.py`):

    MID    cell error 0.0203 -> 0.0144. Eight buckets essentially exact
           through 85 pitches; misses LOW only at 90+ (-0.051, -0.058).
    BND    cell error 0.0265 -> 0.0314, WORSE than the curve it replaces,
           under-pulling from 60 up (-0.018, -0.020, -0.088, -0.057, -0.084).

Four-fold on the outs ladder (`hz_cv.py`, `hz_cv_mid.py`):

    middle band     2023     2024     2025     2026     avg
    shipped       0.0582   0.0352   0.0292   0.0449   0.0419
    both curves   0.0108   0.0233   0.0266   0.0191   0.0200
    MID ONLY      0.0412   0.0172   0.0128   0.0290   0.0251

    long lines    both 0.0253   MID ONLY 0.0152 (shipped 0.0157)
    mean outs     both +0.18 LONG every season; MID ONLY -0.08 short

All-line error is a dead heat (0.0215 both, 0.0223 mid-only) and mid-only
wins everything else: it does not break the long lines, it HALVES the level
error instead of flipping it, and its band gain is -0.016 to -0.018 in every
fold where both-curves ranges -0.003 to -0.047. **HALF THE CHANGE BEAT ALL
OF IT**, and the cell-level read predicted exactly that.

**RUNS UNAFFECTED**, 508 holdout games: F1 -0.008, F3 -0.080 -> -0.078,
F5 -0.036 -> -0.032, F7 -0.029 -> -0.025. Every prefix under 0.004 runs,
inside a standard error of 0.06-0.17, every one toward zero.

**OUTS CORRECTION RE-MEASURED THE SAME SITTING** (mandatory, and the reason
the last one went stale). The hook took over a third of the table's job:
band |correction| 0.045 -> 0.031, mean outs 15.61 -> 15.71 against a real
15.81, boundary share 0.626 -> 0.646, outs CRPS 2.1021 -> 2.0673.

**A CHECK FIRED AS DESIGNED AND IT WAS RE-SPECIFIED, NOT LOOSENED.**
`check_outs_correction_long_lines_are_within_noise` bounded the long rows by
`SE`, a nominal 0.013 that is not the standard error of any row. The rows
drifted out (+0.011 -> +0.018) because the counted table under-pulls at 90+,
which is the real finding its docstring promised to surface. The bound is now
2 se on each row's own se — the bar that was always meant.

**AND NOTHING GUARDED THE SHIP.** Switching the whole mechanism back off
broke no check. `check_the_mid_curve_reads_the_counted_hazard_and_the_
boundary_does_not` now pins both halves; mutation-verified in both
directions. 464 checks.

NEXT: the boundary backbone is the open one. It misses its own buckets from
60 pitches up, and re-solving it so the MODEL reproduces the real rate cell
by cell — iterating the solve, not re-centring it — is the job.

## DAY TWENTY, PART EIGHT — WHAT IS LEFT, MEASURED: THE SIX-INNING START

After the ship, the outs distribution split by WHICH DECISION ended the
start — real side from the removal event in play-by-play, model side from
`pulled_mid_inning`, nothing inferred on either. `scratchpad/outs_split.py`.

**THE BIGGEST SINGLE CELL ERROR LEFT IS THE CLEAN SIX-INNING START.**

    ending                              real     ours       gap
    18 outs, walked off after the 6th   0.230    0.198    -0.031
    12 outs, walked off after the 4th   0.058    0.081    +0.023
    14 outs, pulled with 2 down in 5th  0.037    0.056    +0.018

Real managers get six full innings about 23% of the time and we manage 20%.
The mass we are missing there sits instead on four-inning walk-offs and on
starters yanked with two outs in the fifth. We take the ball about one
batter too early, repeatedly, around the fifth.

**AND AT EVERY ROUND NUMBER WE UNDER-PRODUCE ONE POPULATION** — the starter
who came back out for the next inning and was chased without recording an
out. That is the population the `outs % 3` ruler mislabels, and we are short
of it everywhere:

    outs    real mid-share of the spike    ours
     9              25.7%                 20.6%
    12              18.3%                 13.6%
    15              14.5%                  9.5%
    18               6.0%                  5.2%

At 15 outs one real start in seven is that man and we produce two-thirds of
them. Two readings and this measurement does not separate them: either we do
not send enough starters back out after five, or we send them and chase them
too fast. The 15-out shortfall points at the FIRST — they are not getting
the chance.

Both symptoms are the BOUNDARY curve, which is the one left parametric.

**AND THE MODEL BARELY DISCRIMINATES ON LENGTH** (`scratchpad/too_long.py`).
Residual by what actually happened:

    real outs   model   actual   residual      n
    0-8         15.11     5.05    +10.05      55
    9-11        15.23     9.89     +5.34      79
    12-14       15.29    12.76     +2.53     164
    15-17       15.66    15.60     +0.06     374
    18-20       15.91    18.26     -2.35     342
    21-27       16.38    21.73     -5.35     136

**We predict 15-to-16 outs for every start.** Our predictions span 1.3 outs
across the whole range; reality spans 16.7. Exact on the average start and
blind to every other kind. The aggregate SPREAD is right (3.99 against 4.02)
so the model does produce short and long starts — it does not know WHICH.
That is discrimination, which `leash` already moved from +0.105 to +0.226,
and how much of the rest is predictable at all is open.

The ten worst are all disasters — Bieber at 2 outs, Valdez at 2, Davis
Martin at 3, all priced at 15-16. The mixture built for exactly that
(`early_exit_p`) still ships at 0.0, so nothing in the engine can end a
start because the wheels came off.
