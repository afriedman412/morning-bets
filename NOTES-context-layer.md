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
