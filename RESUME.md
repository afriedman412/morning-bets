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

## WHERE THINGS STAND (2026-08-30)

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
