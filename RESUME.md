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
bullpen availability on both curves, and a high-pitch branch. Boundary share
0.609 -> 0.625 against a real 0.672.

**WHAT IS IN FLIGHT, AND IT IS ITEM 1 IN `TODO.md`.** A COUNTED PITCH HAZARD
TABLE is measured and wired and **PARKED OFF** behind `sim.USE_PITCH_HAZARD`.
It replaces the parametric pitch backbone, which pulls TWICE TOO MANY MEN
between 60 and 85 pitches. Two checks fail: one is the check's fault
(a band that never contained the true 0.972), one is NOT — a bullpen flag
moves F1 with an empty pen once first-inning pulls become realistic, and
that check had been passing vacuously. Answer the second, re-pin the first,
switch on, score.

**FINGERPRINT 00584230.** 436 checks. `venv/bin/python -m tests.run` ~45s.

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
