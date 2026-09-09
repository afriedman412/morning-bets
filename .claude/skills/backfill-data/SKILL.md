---
name: backfill-data
description: Bring every data source current — results, play-by-play, derived tables and the hook-decision rows — in dependency order, and report what moved. Use before the board, before any measurement or fit, or when the user asks whether the data is up to date, to backfill, to pull, or why a table looks stale.
---

# Backfill the data

**Nothing keeps this current on its own. Run it before you measure.** As of
2026-09-09 three of the four launchd jobs point at code deleted with the
betting layer (`src.main`, `src.context.snapshot`) and exit 1 daily;
`.cron-config` is not installed at all — `crontab -l` is empty. Only
`com.morningbets.grade` still works, which is why results stay current while
everything derived from them drifts.

## First, see what is actually behind

```
venv/bin/python -m scratchpad.data_status
```

One screen: every source, its newest row, its lag against the newest
FINISHED GAME (not the wall clock — in February everything trails the clock
by months and nothing is stale), the play-by-play gap, and whether the
scheduled jobs are alive.

**Run it before and after.** The report is the only thing that will tell you
a step silently did nothing.

## Then run the chain, in this order

Order is dependency, not preference. Each step reads what the one above it
wrote, and running them out of order fails quietly rather than loudly.

```
# 1. Results first — everything downstream reads boxscores, not the network.
#    Internally chains starters -> pitch counts -> venues.
venv/bin/python -m src.context.sources.season --backfill

# 2. Play-by-play. --backfill fetches missing games over 8 workers;
#    --sync flattens the cache into mlb_stints (~30s). BOTH flags.
venv/bin/python -m src.context.sources.pbp --backfill --sync

# 3. The per-game tables.
venv/bin/python -m src.context.sources.weather --backfill
venv/bin/python -m src.context.order --build            # mlb_lineups
venv/bin/python -m src.context.sources.battedball --build   # mlb_batted

# 4. The hook decision rows, LAST — built from the pbp cache plus
#    mlb_stints, so it is wrong if step 2 has not finished.
venv/bin/python -m scratchpad.fit_hooks --rebuild
```

`make backfill` is step 1 and `make pbp` is step 2; there are no targets for
the rest.

## The traps, each of which has actually happened

**`--sync` is not optional.** `pbp --backfill` alone fills the gzip cache and
leaves `mlb_stints` untouched, so every role lookup, deployment measurement
and opener classification keeps reading yesterday's table while the disk
says the data arrived.

**A partial pbp run looks like a finished one.** On 2026-09-09 the cache had
been topped up that morning and still missed 37 of 111 finished September
games, spread across every date. `data_status` counts the gap; the backfill's
own output does not.

**`/tmp/hook_rows.json` is in `/tmp`.** It does not survive a reboot, and
every hook fit and the battery read it. If it is missing, step 4 rebuilds it
from scratch (minutes, not seconds). `fit_hooks` reads the CACHE without
rebuilding unless you pass `--rebuild`, so a stale file is used silently.

**DO NOT PIPE STEP 4 TO `head`.** It prints progress every 400 games and
writes the file only at the END, so `| head -6` closes the pipe, SIGPIPEs
the rebuild dead partway through, and exits 0 — the pipeline's status is
`head`'s. It looks exactly like a completed run and the file keeps its old
mtime. Redirect to a log and `tail` that instead. (Done on 2026-09-09, which
is why the step reported success while `data_status` still said STALE — the
report is what caught it.)

**Early season is thin for a real reason, not a bug to fix here.** At an
April rate freeze almost no arm has cleared `MIN_PEN_APPS` — 2026-04-01
resolves to 17 pen clubs and 30 arms — and March cannot be replayed at all
(`sim.league` raises "no batting rows"). Backfilling does not change that;
see TODO's early-season cold start.

## After it runs

Re-run `data_status` and say what moved. If a source is still behind, say
which and why rather than reporting success — the entire point of this skill
is that stale data is silent, and a backfill that claims to have worked is
worth nothing on its own.

**THE FINGERPRINT MOVES, AND THAT IS NOT A BUG — IT IS THE POINT.** Measured
2026-09-09: identical code before and after this chain, and
`fingerprint 400 6` went 2fa14f8df0c6 -> 00925f199684. The paired-game
COUNT was unchanged (661 both times, same first-400 span), so it is not new
games entering the set — it is the CONTENT of games already in it. The
backfill set venues on 26 games, synced lineups for 88 and pitch counts for
2, and park, lineup and pitch count all feed the replay.

The consequence is a rule, because this project uses the fingerprint to
prove a refactor was inert:

  **A FINGERPRINT COMPARISON IS ONLY VALID ACROSS CONSTANT DATA.** Record
  it, change code, re-measure — never backfill in between. If you did,
  the comparison proves nothing and has to be re-baselined: re-measure
  the fingerprint on the NEW data before making the code change you
  intend to test.

Same for the battery: a saved JSON is a measurement on the data of its day,
so `--diff` across a backfill mixes a code effect with a data effect. Any
number fitted or scored before this ran should be re-read on that basis, not
trusted, and any A/B still in flight should be restarted rather than
finished on half-old data.
