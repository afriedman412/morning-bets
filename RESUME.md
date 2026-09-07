# RESUME — the session handoff

**THIS FILE IS ONLY FOR PICKING UP WHERE THE LAST SESSION STOPPED.** It is
not a log and not a backlog. Keep it under ~150 lines; if a thing is history,
it belongs in `NOTES-context-layer.md`.

    CLAUDE.md            THE RULES. Read in full, every session. It is the
                         only file loaded into context automatically.
    TODO.md              THE BACKLOG — what to do next, ordered, each item
                         written to be picked up cold. GO HERE SECOND.
    NOTES-context-layer  THE LOG, append-only, 7,400 lines. Read BACKWARDS
                         from the end. Never read it forward.
    BETTING.md           How to price a slate. The only file you need to bet.
    RESUME-ARCHIVE.md    Days six to sixteen, moved out of here. Not deleted,
                         but its figures predate several engine changes.

## HANDOFF FOR THE NEXT (OPUS) SESSION — written 2026-09-06, late, to be
## worked COLD. Read this block, then the sitting summaries below it.

STATE: tree clean at `23eac40`, 460 checks (~25s), battery baseline
`battery_90590e37150f.json`, engine fingerprint 90590e37150f. Four
things shipped today: the plate umpire, the hook refit, the leash
rebuild+guard, and the night term. Nothing is half-done.

THE TWO ITEMS QUEUED, in order, each session-sized and countable:

### A. Ball-in-play shared-night conditions (weather on babip/XBH)
QUESTION: temperature and wind ship on the HR channel only. Does the
same air move BALLS IN PLAY — babip and the XBH share? The elasticity
measurement (`scratchpad/night_variance.py`) says this is where run
variance lives: e_babip 1.19 vs e_hr 0.39, so a babip effect is worth
3x an equal-sized HR effect to the run distribution.
COUNT: the `scratchpad/temp_hr.py` pattern verbatim — within-venue
indirect standardisation, per-season multipliers pooled after, era
gate, pre-holdout rows only (`from src.context.holdout import
train_only`). Channels: babip (denominator BALLS IN PLAY, not PA —
state_table's docstring carries the warning) and xbh-share-of-hits.
Covariates: temp bins as shipped, wind carry bins as shipped.
POWER, state before running: babip se over ~5k games/bin is ~0.004, so
a 1% effect is ~2.5 se — well powered. XBH share se ~0.008/bin.
TRAPS: (1) park's `bip` channel ALREADY carries the venue's ball-in-play
level — count within venue or it double-counts, same as wind did.
(2) A survivor SHRINKS `NIGHT_SIGMA` — rerun night_variance, update the
sigma and its docstring arithmetic in the same commit. That rule is
load-bearing: the night term must only ever get smaller.
WIRE (only if the gate passes): a `bip_air` per-game value riding the
`hr_air` rail (`resolve` takes it beside `k_game`/`bb_game`; grep
`ump_kbb` for the six call sites — the caller-presence check in
test_game will catch any you miss, extend it to the new argument).
FALSIFIER, register verbatim before the A/B: flag-off reproduces
90590e37150f exactly; flag-on moves babip/traffic rows toward real in
>= 3 of 4 folds; run LEVEL inside 1 se (the night term's centre keeps
the mean invariant — if level moves, the new term is adding, not
redistributing); outs rows within 1 se.

### B. The cruise state (the six-inning cell, worst in the battery)
QUESTION: clean six-inning starts are real 0.230 vs model 0.198 and the
clean hook refit did NOT move it — structural, not a coefficient. The
recorded diagnosis: one smooth logistic cannot be bimodal; managers
either cruise a starter or knock him out. Does the boundary hazard,
conditioned on CLEAN-SO-FAR (zero runs allowed), have a visibly
different shape than the pooled curve?
COUNT ONLY THIS SESSION: split the 98,694 cached boundary decisions
(`/tmp/boundary_rows.json`, dated; rebuild with
`scratchpad/fit_boundary.py --rebuild` if missing) by runs-so-far == 0
vs > 0, print hazard-by-pitch and hazard-by-inning for each, per
season, train rows only. If the clean curve is flatter late (the cruise
signature), fit it as its own branch the way late_mid_* got its own —
but WIRING A SECOND BRANCH IS A SHIP DECISION RESERVED FOR THE USER OR
A FABLE SESSION. Deliver the count and the proposed falsifier, stop.

STANDING RULES THE SESSION MUST NOT RELEARN (each cost something today):
  * Before loading ANY channel with a new effect, grep for an existing
    counted mechanism on that channel (`START_K_SIGMA` nearly got
    double-counted by the night term — the suite's check names are the
    map).
  * `NIGHT_SIGMA` changes ONLY via a night_variance rerun. Never tune
    it to a battery row — its centre term means level rows are a PROOF,
    not a target.
  * Any Hook coefficient change turns the suite red until
    `python -m src.context.leash --build --before 2026-07-01` reruns —
    that is the forcing function working, not a broken test.
  * A/B discipline: flag-off must reproduce the baseline fingerprint
    EXACTLY before the flag-on run means anything. Register the
    falsifier in writing before either run.
  * Mutations: `scratchpad/mutate.py` or cp backups. NEVER
    `git checkout` a file carrying uncommitted work.
  * A failed registered clause is not yours to reinterpret (rule 13).
    Narrow failures with a named mechanism go to the user — that is how
    both wind and the night term shipped.

## WHERE THINGS STAND (2026-09-06, night — Fable session)

**THE NIGHT TERM SHIPS (`sim.USE_NIGHT_SIGMA`, fourth sitting) — the
parked dispersion re-opened BY THE USER and shipped as a REMAINDER:**
sigma 0.111 on bb/hr/babip only (k is START_K_SIGMA's counted job — the
first wiring collided with it and was caught), run-mean invariant by
construction after the uncentred version failed its A/B on level in all
four folds (+2% runs = the convexity arithmetic, exactly). Centred A/B:
level clean, shutouts toward real, blowups held, outs split
2-folds-better/2-slightly-long — the registered outs clause failed
narrowly and the USER made the ship call (wind's precedent). THE
MAINTENANCE RULE: rerun `scratchpad/night_variance.py` after every
counted ship and SHRINK the sigma; it must only get smaller. Ledger as
of tonight: 20.6% of the night explained (park 7.4, air 1.4, ump 0.1,
k-stuff 10.4). Baseline battery_90590e37150f.json, 460 checks.

**THE HYGIENE LIST IS CLOSED (second sitting, same session).** Both hook
curves refit on clean training rows — the era gate refused the
four-season pool (managers are a moving regime; 2023-24 is another era)
and rule 9 fit 2025-through-holdout; the clean values reproduce the
contaminated ones within 1-5%, now known rather than hoped.
`src/context/holdout.py` owns the cutoff, six live fitters import it, a
check bans drift. The leash was rebuilt on pre-holdout rows against the
refit hook (the shipped file had `before: None` — a worse debt than the
hook's), stamped with `sim.hook_hash()`, and BOTH the loader and a
check refuse a stale file — any future Hook change turns the suite red
until `leash --build` reruns. Also: slate.py fetches the day's crew at
price time (crews publish game-day, not the night before — 0/11
measured). Full log in the notes. `.cron-config` still lists three
deleted modules; recorded, not touched.

**ITEM 8b SHIPPED THE PLATE UMPIRE (`sim.USE_UMP_KBB`), the third
shared-night condition.** Counted with the staffs-he-drew confound
standardised out (bb tau 0.0438, split-half +0.454, season-pair +0.323;
k tau 0.0176 — WALKS are the channel), shrunk against tau, renormalised
to a game-weighted mean of 1.0, wired through the air's rail into
replay/fitf5/ladder/slate. The A/B passed the falsifier registered
before the wire existed: run level held (max 0.14 se), k_sd and
k_9_plus_share toward real in 3/4 folds, mass rows 3/4, shutout
sub-clause unresolvable at 0.1 se. Flag-off reproduced 079082494e7e
exactly; NEW BASELINE battery_9229ea8a0897.json. The extended
caller-presence check caught fitf5 and ladder unwired on its first run
— the fifth-caller class, stopped by a check this time. OPEN on 8b:
slate-time crew coverage unmeasured (silent-neutral when missing);
rebuild the table when the season rolls.

**ITEM 8a IS RESOLVED: WITHIN-INNING FEEDBACK IS A NULL AT THE REGISTERED
BAR, AND NOTHING WIRED.** `scratchpad/inning_feedback.py`, 398,605
pre-July PAs over four seasons, three controls on a heterogeneous inning
machine. The session's value was the two specification catches, both now
in the notes: the plan's registered traffic binning failed its own
positive control (occupancy floors traffic — surplus = traffic − men on
is the identifiable coordinate, and a step effect at traffic ≥ 1 already
lives inside STATE_MULT), and half the apparent k effect was
times-through-the-order, removed by a batters-faced standardiser with its
own verified confound control. Result: k 1.9 se in both surplus bins
(under the 2-se gate, 4/4 and 3/4 season signs, monotone), bb 1.4 se,
babip 1.5 se; a true hit gradient above ~x1.03/runner is EXCLUDED by the
positive control. Rule 13 held: the near-miss is recorded, the gate was
not loosened. No engine change, so fingerprint stays b505bb6b and
battery_079082494e7e.json remains the baseline. NEXT: item 8b (umpire
zone is the first candidate — check whether pbp caches officials), or
the hygiene list. The parked dispersion term stays a human decision.

## WHERE THINGS STOOD (2026-09-06, end of day — Opus session)

**TEST AUDIT, after item 7: the sweep was eight mechanisms behind and the
suite's cost was one check.** `scratchpad/mutate.py` now runs 37 mutations
covering every live flag AND its table (a flag check passing over a flat
table is the failure it exists to find). 30 caught, 7 survived. THREE
SURVIVORS ARE INERT, not unguarded, and the fingerprint proves it —
`late_mid_per_pitch`/`late_mid_offset` sit in the `else` of
`if USE_PITCH_HAZARD`, `MID_INNING_RUN_OFFSET` feeds only the early branch
(`early_innings == 0`), `USE_BOUNDARY_HOOK` sits behind `USE_LEARNED_HOOK`;
flipping any leaves the 400x6 fingerprint at b505bb6b. THE OTHER FOUR were
real: USE_PLATOON, USE_FIELD_STATE, USE_PEN_STATE, USE_ROLE_HBP.
AND THE DIAGNOSIS WAS WRONG THE FIRST TIME, which is the part worth
keeping: each of the four HAD a wiring check. Every one sets its own flag
(the house pattern), so the mechanism checks override the very thing being
mutated and only the DEFAULT was unpinned.
`check_the_measured_mechanisms_are_switched_on_by_default` pinned 4 of 17
flags; it now pins all of them. Only genuinely new checks kept: pen_state's
cached reading (its old checks asserted the BASELINE fallback, which is
exactly what the off path returns), STATE_MULT not-flat, role HBP.
SUITE 43.6s -> 22.8s, no coverage lost: `check_rps_is_proper` was 29s of
44, sampling 4000x3000 for a STRUCTURAL property whose margin is 19.6%
there and 18.5% at 1000x800. Segmentation already exists and needs no
work — `make test ARGS=<module>` is ~7s. 451 checks.
SCAR, second time in one day: hand-rolled mutation loops leaked
`USE_PEN_STATE = False` into the tree and nearly shipped it. Use
`scratchpad/mutate.py`, which refuses a dirty tree and restores via
atexit, or `cp` backups — NEVER `git checkout` on an uncommitted file
(that destroyed the wind block earlier).


**ITEM 7 SHIPPED (`sim.USE_WIND_HR`): wind into the HR channel.** In 5+
mph 0.9242, calm/cross 1.0002, out 5+ 1.0431 — counted on 4,798
open-air pre-July games WITHIN VENUE and NET OF THE SHIPPED TEMPERATURE
TABLE, climate-centred (0.9981). Three bins; five is worse (era gate
0.795 -> 0.567, ordering fails in three seasons). `hr_temp` is renamed
`hr_air` end to end — six callers, the fingerprint instrument included.
THE A/B THAT MATTERED: the first battery said "no row moved", which was
VACUOUS because the wind rows were new — re-ran with the flag off (same
stream; the off run reproduces fingerprint 525e62464717 exactly, which
proves the wire is inert when off) and the wind sum|gap| closed in
2024/25/26, widened in 2023. FIVE ROWS OF 687 MOVED PAST ONE SE AND ALL
FIVE ARE ITS OWN; level within 0.17 se every fold.
THE PRECEDENT, because it will be quoted: item 7's ordering gate FAILED
(2026 inverts by 0.007 against a difference se of 0.043 — 0.16 sigma)
and it shipped anyway ON THE USER'S CALL, not the session's. Admissible
because NOTHING WAS RESCALED after seeing a score. Re-reading a gate
against its own se is not tuning a row green; do not let the two blur.
448 checks (4 new, each mutation-verified alone); fingerprint b505bb6b;
baseline `battery_079082494e7e.json`.
PROCESS SCAR: `git checkout <file>` to revert a mutation DESTROYED the
uncommitted mechanism. Back up with `cp`, or mutate a committed tree —
`scratchpad/mutate.py` refuses a dirty tree for this exact reason.
NEXT: plan item 8a (clustering — count within-inning feedback; written
to be worked cold, traps and positive control spelled out), or the
hygiene list at the plan's foot. Item 8's ship decision is still
reserved for a human.

## WHERE THINGS STOOD (2026-09-06, mid-day — Fable session)

**ITEM 5 SHIPPED (`sim.USE_TEMP_HR`): temperature into the HR channel —
and the plan is now EMPTY, items 0-6 all shipped or parked.** Counted
WITHIN VENUE (the pooled count confounded park) and centred on CLIMATE
(prior seasons' full-year mean multiplier 1.0191 — spring centring
double-counted the air already in the baseline rates; the first
battery run caught both, +2-3 sigma on the level). Corrected table
0.798 -> 1.115 across <55F..85F+, era gate 0.923, dome control 0.973,
coverage 100%. Wired game-level through the `hr_park` slot; all five
callers pass it (the fingerprint instrument was the fifth and sat
still until fixed). Clean folds landed on the registered prediction
(2023/24 levels -0.0000/-0.0003, hot buckets within 1.1 sigma); 2026-H2
hot side +2.3 sigma, co-located with the standing dead-ball anomaly —
one cause, two instruments (XBH level + HR hot buckets). Wind counted
x0.90/x1.06, not wired. 444 checks; fingerprint b211fce6; baseline
`battery_525e62464717.json`.
NEXT — REGISTERED FOR A COLD SESSION (written 2026-09-06, Fable, for
Opus to pick up): plan items 7 (wind, temperature's mirror — the
template and every trap are written into the item) and 8 (clustering —
8a counts within-inning feedback with the leakage trap and positive
control spelled out; 8b shared-night conditions after). Work ONE item,
follow the protocol at the top of the plan, read the traps before the
count. The hygiene list at the plan's foot is also safe cold work.
HOLD FOR A HUMAN OR A STRONGER SESSION: any ship/park decision where
the falsifier reads ambiguous, re-opening the flat dispersion term,
and anything that involves rescaling a counted table to make a scored
row go green — that is the one move every trap this week had in
common.

**ITEM 6 SHIPPED (`game.USE_PEN_ROLES`): late-inning arms are picked by
the counted selection profile, not draw order.** The count refuted the
plan's deterministic rule (real P(best remaining | close) 0.18-0.23 vs
the draw's natural 0.157; the true defect was blowouts at 0.084 — good
arms are SAVED) and the behaviour is signed: lead 44% top-fifth, trail
near-flat. One uniform per entry from inning 7, drawn flag-on or off
(the A/B stream rule); percentile rank so the real 12-arm profile fits
the sampled 8. Battery flat everywhere — the PREDICTED result at the
counted size (~0.01 runs/late inning vs pooled se 0.025); ships on
rule 3. F5 untouched by construction (a 0.0002 bit-drift chased to the
`mlb_stints` rebuild reaching `layoff_gap` for two 2024 starters — the
stints table was 2026-only and is now four seasons, 87,855 rows).
THE FINDING: late-inning margin gaps (+2.5 sigma pooled at margin 1)
SURVIVE deployment — they are clustering's late face, not arm choice.
441 checks; fingerprint 954c4a5f; baseline `battery_5216a886af94.json`.
NEXT: item 5, weather — temperature into the HR channel; battery
weather rows are stubs, instrument first.

**ITEMS 4b + 4c SHIPPED (`sim.USE_GB_DP`, `sim.USE_GB_HITMIX`): double
plays and the hit mix both read the matchup's GB profile**, as counted
odds per quintile combined log5-style (validated on the 25-cell crosses),
silent-neutral per side, centred at 1.0000 over real rows. THE SESSION'S
BIG FINDING: 4c's scoring run caught the first counts binning rows
INSIDE their own covariate window — a counted single raises its own
batter's GB% — which inflated both slopes (~2x on XBH) and overshot on
the holdouts. Both tables recounted with GB% frozen BEFORE each row's
month; corrected falsifier clean: XBH quintile sum|gap| shrank in all
four folds (0.069->0.052 / 0.056->0.036 / 0.043->0.030 / 0.088->0.073),
DP pooled 0.485 flat -> 0.366, levels and every other battery row under
one se. THE PORTABLE RULE: a covariate must be frozen before the rows it
bins, or the outcome leaks into its own conditioning and the era gate
cannot see it. 437 checks; every mutation kills exactly its guard.
Fingerprint ccdb3903; baseline `battery_7ad09292970f.json`. Watch (all
odd ACTUALS, not model): 2024 xbh q1, 2026 DP q2, 2026 XBH level
(+0.012 before item 4 existed — a `lg["hit_mix"]` season-scope
question).
NEXT: item 5, weather — temperature into the HR channel via `m_hr`;
battery weather rows are stubs, so the instrument comes first.

**PLATOON SHIPPED (`sim.USE_PLATOON`)** — the league cell as an odds
multiplier per (batter side, pitcher hand) pairing, counted on 761,719
PA. Per-batter falsifier passed 3/4 folds; 2026 improved on every row
(adv-side K residual 0.0062 -> 0.0008); start-level marginals flat as
predicted. Adv-K overshoots ~2 se in 2024-25 where the counted RHB
advantage faded — watch item. Baseline `battery_b33f96512e59.json`,
fingerprint ada0369f, 428 checks.

**REAL BATTING ORDERS NOW COVER ALL FOUR SEASONS** (mlb_lineups was
2026-only; the 2023-25 folds had been replaying proxy orders). Moved the
2024 first inning toward real and nothing else past one se.

**ITEM 4a SHIPPED (2026-09-06): `gb_pct` counted from our own pbp cache
(never Savant — season-to-date knows the future), shrunk by measured
constants (bat 112, pit 77 — forty times faster than pitcher BABIP),
carried inert on every rate object. The battery quintile rows are live
and show the target: model DP flat vs real 0.224->0.286 by pitcher GB
quintile; model XBH flat vs real 0.273->0.228 by batter quintile.
NEXT: 4b — gidp_rate reads the matchup, log5-style odds vs the league
DP rate.**

## WHERE THINGS STOOD (2026-09-06, mid-day)

**GIDP ADVANCEMENT SHIPPED (`sim.USE_GIDP_ADVANCE`).** On a nobody-out
double play the man on third now scores (counted 0.8515, four seasons
stable) and the man on second takes third (0.9277); no rbi, tokens not
booleans, third-out rule intact. Battery diff spotless — no row past one
se, sac/DP levels bit-identical. Fingerprint 9d45b134; baseline
`battery_ad90c1c4a6af.json`.

**THE SAC STATE TABLE PARKED ITSELF, AND THE KILL IS A FINDING.** The
counted column (gate 0.994, zero at two out everywhere) re-levelled the
league sac rate x0.964 through the model's own state occupancy: the model
under-visits exactly the extreme-traffic cells (bases loaded 0.32% vs
0.42% real). That is the CLUSTERING defect at sharper resolution than the
shutout/blowup shares ever gave it — a second instrument for whatever
attacks clustering. Wire live and inert; see plan item 2.

**ALSO 2026-09-06: the engine no longer drifts overnight.** The park
index is pinned per year on scoring paths (the daily cache stamp moved 11
venue indices between mornings and the fingerprint with them), and rate
neutralisation moved into the rate builders — the LIVE slate path had
been pricing off raw rates while replays scored on neutral ones.

## WHERE THINGS STOOD (2026-09-05)

**THE BATTERY SHIPPED — RULE 15.** `venv/bin/python -m scratchpad.battery`
scores every table off one pass per fold, four folds, 94 seconds, with
`--diff`, `--on/--off` config flips and a `--maim` positive control.
Every modelling item now starts and ends with a battery run and reports
the DIFF — every row, not just the target.

**PARK SHIPPED THE SAME DAY — `USE_PARK` + `NEUTRALISE_PARK`, on the
pre-registered per-venue test.** Weighted mean |per-venue residual| down
in 3 of 4 folds on both full and F5 team totals; ladder inside one se
everywhere; 10 of 671 battery rows moved and every one is a venue row
moving toward zero (Coors, all four folds). Fingerprint
2fafc653 -> ac8e9c1a; `outs_adjust` re-measured (all rows within one se);
battery baseline is now `scratchpad/battery_4927c96f259b.json`. The 2026
fold is the one park does not yet help — lowest rated coverage (88.4%)
and a season-to-date index. Next item in `PLAN-baseball-logic.md`: GIDP
advancement + state-blind sacrifices (item 2), scored on the battery's
traffic and contact rows.

## WHERE THINGS STOOD (2026-08-30)

**THE MODEL.** Event rates are right. Runs are right — verified on 1,645
games, F5 -0.047 at 0.6 sigma, F3 and F7 inside noise. **The one open
run-level defect is the FIRST INNING at -1.7 sigma.**

**THE HOOK IS THE WORK, AND IT IS HALF DONE.** Days 17-18 shipped five
counted mechanisms: the blowout term, dominance, a per-start strikeout draw,
bullpen availability on both curves, and a high-pitch branch.

**READ THE BOUNDARY SHARE ON THE EVENT RULE, NOT THE OUT COUNT (2026-08-31).**
`shape.py` infers it from `outs % 3 == 0`, which scores a starter chased in
a new inning as a clean end of frame — 7.8% of real starts, 6.0% of
simulated ones, so it INFLATES the gap. Model 0.566 against a real 0.596,
**-0.030 at 2.1 sigma**, not the -0.048 quoted everywhere before today.
`scratchpad/bnd_truth.py`.

**THE FOURTH INNING IS 40% OF THE OUTS-LADDER ERROR (2026-08-31), AND IT
IS THE TOP MODELLING JOB.** Oracle: remove the excess fourth-inning exits
(3.4% of starts, both curves) and mean |gap| across the outs lines goes
0.0363 -> 0.0219 with mean outs landing 15.82 against a real 15.81, from
0.19 short. `scratchpad/starts_query.py`. Upper bound, but the largest
identified piece of the outs error and on the market priced nightly.

**THE MID-INNING DEFECT IS THE FOURTH INNING, FOUR SEASONS RUNNING
(2026-08-31).** We pull starters mid-inning in the fourth on 6.9% of starts
against a real 4.5% — +0.022 to +0.024 in 2023, 2024, 2025 and 2026, every
one significant, spread 0.002. The third is a smaller consistent positive.
**THE FIFTH AND SIXTH ARE NOT A TARGET**: the real profile there moves 25-40%
between seasons and our gap follows it, so anything built against the
"innings 3-5, short in the sixth" shape is built on 2026.
`scratchpad/mid_inning_cv.py`.

**AND THE PITCH TERM IS NOT THE ROUTE TO IT.** Three backbones scored on day
twenty (shipped, counted hazard, hazard+branch): the outs distribution
reshaped substantially and boundary share sat at -0.050/-0.060/-0.060. Two
further candidates are dead, both positive-controlled — out count in the
inning (raw +29.6 sigma, conditional -1.6) and a mid/boundary interaction
(-7.4 sigma under the old backbone, +3.0 and sign-flipped under the counted
one, so it was the parametric pitch shape all along).

**SHIPPED 2026-08-31: THE COUNTED MID-INNING PITCH HAZARD.**
`USE_PITCH_HAZARD = True`, `USE_PITCH_HAZARD_BND = False` — counted MID
backbone, parametric BOUNDARY. Four-fold cross-validated: outs band better in
all four seasons by a consistent -0.016 to -0.018, long lines untouched, mean
outs error halved (0.2 short -> 0.08). Runs unaffected across the ladder.
**IT CLOSES THE FOURTH-INNING DEFECT** (+0.033 -> -0.007) because 60-85
pitches IS the fourth inning — one defect, not two. Taking BOTH curves was a
dead heat on error and lost on everything else, so only half shipped.
**THE BOUNDARY BACKBONE IS THE OPEN JOB**: it misses its own buckets from 60
pitches up (cell error 0.0265 -> 0.0314, worse than what it replaces).

**SUPERSEDED — the paragraph below described the pre-ship state.** A COUNTED
PITCH HAZARD TABLE is measured and wired and **PARKED OFF** behind
`sim.USE_PITCH_HAZARD`.
It replaces the parametric pitch backbone, which pulls TWICE TOO MANY MEN
between 60 and 85 pitches. Two checks fail: one is the check's fault
(a band that never contained the true 0.972), one is NOT — a bullpen flag
moves F1 with an empty pen once first-inning pulls become realistic, and
that check had been passing vacuously. Answer the second, re-pin the first,
switch on, score.

**THE BOARD RENDERS A PAGE.** `scratchpad/board.py --html` writes
`scratchpad/board_<date>.html` off the same run as the terminal dump — one
payload, two views, so they cannot disagree. Visual system in
`scratchpad/dashkit.py`, shared with `scratchpad/dash.py`.

**THE OUTS CORRECTION IS CURRENT AGAIN (2026-08-30).** `outs_adjust.py`
re-measured on the shipped hook, 1,128 holdout starts. Only the long lines
moved — o18.5 +0.035 -> +0.011, o20.5 +0.024 -> +0.008, both now under one
sigma, because the high-pitch branch stopped the model over-producing long
starts. The middle band did not move. **RE-MEASURE IT AGAIN THE DAY THE
PITCH HAZARD SHIPS**; it costs 12 seconds and it went stale silently last
time.

**FINGERPRINT CHANGED 2026-08-31 — the hook moved.** 464 checks. `venv/bin/python -m tests.run` ~45s.

## FIVE THINGS THAT WILL COST YOU A DAY

  1. **NEVER FIT ON ROWS YOU WILL SCORE ON.** `HOLDOUT_CUT` = 2026-07-01.
     Six constants got this wrong in one day; `train_only()` is in the
     fitters now and must be CALLED, not merely defined.
  2. **CHECK A CACHE'S MTIME AGAINST THE CODE THAT WROTE IT.**
     `/tmp/hook_rows.json` predated a labelling fix by two days and would
     have poisoned everything.
  3. **PRINT THE COVERAGE OF ANY LOOKUP BEFORE READING A SCORE.** A table
     keyed on club NAMES against a caller keying ABBREVIATIONS gave 0%
     coverage and a completely believable null.
  4. **A FINGERPRINT THAT WILL NOT MOVE AFTER A LIVE CHANGE IS THE BUG.**
     Eight callers build sides; a mechanism was live in one scratchpad
     harness and inert everywhere else.
  5. **VERIFY EVERY CHECK BY MUTATION.** Two written this week passed while
     guarding nothing.

## WHAT IS RUNNING RIGHT NOW

NOTHING. The history load finished at the end of day ten:
(day eleven added no long jobs; everything below completed.)

    scratchpad/load_rest.out ends "=== HISTORY LOAD COMPLETE ==="

It ran 2023 -> play-by-play -> real pitch counts as one chained job. Both
of those passes take their work list from the `games` table, so they cover
every season present with no argument.

## DATA STATE — FOUR COMPLETE SEASONS

    season   games   final
    2023     2,677   2,664
    2024     2,652   2,635
    2025     2,639   2,632   (+ postseason)
    2026     2,079   2,031   (in progress)

    play-by-play   9,962 games cached, 981 MB in `.cache/pbp`
    pitch counts   46,185 rows backfilled, 0 failed

Backups of the pipeline DB taken before each load:
`/tmp/morning_bets_backup_pre2025.db`, `..._pre2024.db`.

NOTE (CORRECTED day thirteen) the four seasons ARE used now:
`USE_PRIOR_SEASON` is True and `PRIOR_SEASONS` is 3. The paragraph below was
written on day ten and its flag states are stale. The decay
weight across three prior seasons is unmeasured — that is next.

## PARALLELISATION — WHAT IS AND IS NOT, AND WHY

**The season load is SEQUENTIAL ON PURPOSE. Do not "optimise" it.**
`season.py` says so in its own docstring — it is somebody's free public API.
More importantly a second writer against SQLite would collide, and
`backfill` COUNTS A LOCK COLLISION AS A FAILED DATE AND SKIPS IT. That
leaves silent gaps that look exactly like a completed load. ~14s per date,
~50 min per season.

**Everything else already forks and does not need work:**

    pbp / pitches backfill    8 workers (network-bound)
    tests/run.py              one process per check, 95s -> 35s
    score_boundary, memory    fork over games, cpu_count-1
    fit_boundary              one pass, ~5 min over 4,663 games

Fork, never spawn. A spawned child re-imports at DEFAULT globals and every
`USE_*` flag silently reverts.

## TOOLS BUILT TODAY — CHECK HERE BEFORE WRITING ONE

    memory.py           3 arms (none/pool/prior) x 2 cuts, on outs, K,
                        game totals and F5. THE main experiment.
    season_hook.py      do managers pull the same way across seasons
    preseason_test.py   preseason rank vs the leash residual, any season
    preseason_ranks.py  2025 + 2026 lists, transcribed with provenance
    reputation.py       career/awards vs the residual
    qualitative.py      prior-season IP, budget, rookie, age
    rank_starters.py    stat-line rank vs prior outs
    yesterday.py        one slate vs actuals AND vs Kalshi close
    score_boundary.py   legacy/linear/knee/shipped, paired seeds
    fit_boundary_nl.py  linear vs quad vs hinge forms
    scope_baseline.py   digests every season-sensitive number
    battery.sh          the whole re-measurement, unattended

## QUESTIONS ALREADY ANSWERED — DO NOT RE-RUN

* Does more data fix outs? NO. Memory, and 89,983 hook decisions.
* Does it reach game totals? NO. Inside noise on RMSE 4.5.
* Do managers pull the same in 2025 and 2026? YES, on matched calendar.
* Stat-line rank, career record, awards, workload, rookie status vs the
  leash? ALL absorbed by the pitcher's own recent innings.
* Preseason rank gradient? DEAD on 2025. Headline correlation replicates.
* Boundary knee? Better per decision, worse on what settles. Ships inert.
* K% shrinkage constants? Tested, no change needed.

---
