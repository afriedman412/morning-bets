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

## WHAT TO DO NEXT

**1. THE RUN LEVEL — 5% light at every prefix.** The ladder has said this
all day and every day; nothing has moved it. It is the stated product and it
is the one number that is unambiguously wrong. Note the ladder CAN see this
(it is a level error, not a redistribution) even though it cannot see a hook
change.

**2. The 12-14 out bucket.** 19.4% against a real 16.6%, the largest
remaining misfit in the STARTER-LENGTH distribution. That is 4.0-4.2 innings, which is where books hang outs
lines. Untouched by everything above.

**3. Collapse to ONE engine.** `sim.simulate_start` and
`game.simulate_game` both exist; the start-level loop has no bullpen, no
margin and cannot produce a team total. `quote`, `price`, `calibrate`, `f5`
and `versus_market` all sit on it, and every calibration table in the notes
was produced by it, so the migration invalidates recorded baselines in one
commit. Note `USE_MEASURED_INHERITED` RETIRES with that loop rather than
needing a port — `game.py` plays inherited runners out for real.

**4. Score the blind re-simulation.** Three games from 2026-08-24 were
re-simulated with rates cut off before the game date and published as a
dashboard (`scratchpad/lastnight.py`, `scratchpad/dash.py`). NOTHING has been
scored against what actually happened yet — that comparison is the point and
it has not been made.

**5. Within-start K% persistence, +6.4 sigma.** Whether he has the
swing-and-miss tonight carries; contact outcomes do not. Unused, and it bears
directly on strikeout props, which is what `quote` gets asked about most.

**6. Refit the hook properly.** `calibrate.tune` is serial, samples 500 of
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
