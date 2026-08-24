# Where the context work stands — resume here

Written 2026-08-22, updated the same day after the simulator landed. This is
the debugging state, not documentation: what is half-finished, what is
measured, what is guessed, and what would waste a day if re-investigated.

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
