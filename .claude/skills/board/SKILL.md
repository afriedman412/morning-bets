---
name: board
description: Price a slate — full-game and team totals, F5, and each starter's K and outs lines, as fair American odds against Kalshi's mid — then render the HTML page and open it. Use when the user asks for the board, tonight's card, to price a slate or a game, "what should I bet", or to re-run after lineups post.
---

# The board

Four commands, always all four. The text board is the artefact of record;
the HTML is how it gets read. **Never stop at the .txt** — the page carries
the filter and the K-divergence table, and every session that skipped it
hand-ranked rungs the page would have ranked for it.

`BETTING.md` is the authority on what each market is worth and on the
adjustments the board does NOT make for you. Read it before quoting a
number back to the operator. This file is how to RUN the thing.

## Run it

```
# 0. Freshness. Results are the input to every rate the board prices with.
venv/bin/python -m scratchpad.data_status

# 1. The board. Default is today, 20,000 sims. REDIRECT, do not pipe.
venv/bin/python -m scratchpad.board > bets/<YYYY_MM_DD>_board.txt

# 2. Parse to JSON. Reads the .txt, never re-simulates.
venv/bin/python -m scratchpad.board_json  2026-09-10

# 3. Render and OPEN. Both, every time.
venv/bin/python -m scratchpad.gen_board_html  2026-09-10
open bets/2026_09_10_board.html
```

The date argument is `YYYY-MM-DD`; the filenames use underscores. Steps 2
and 3 default their paths off the date, so pass it and let them.

**Re-running after lineups post writes over the morning board.** Give the
second run its own stem — `bets/<date>_board_pm.txt` and pass the explicit
src/out paths to steps 2 and 3 — so the morning numbers survive for
comparison. On 2026-09-10 that comparison was the whole answer: our F5
number moved 0.4 points on the real nines while Kalshi moved 3.4.

**20,000 sims is the floor before any number is compared to a price.** A
total moved 7.34 → 7.05 between 400 and 20k, and two 1,500-sim runs of one
line differed 1.2 points on seed alone. Do not lower it to save time and
then quote the output. Five games is about 75 seconds.

## Operator-announced openers (added 2026-09-18)

When the operator announces a plan the schedule cannot know — "Burns goes
three innings, Williamson has the bulk" — record it BEFORE step 1 and the
board applies it to every rung of that game:

```
venv/bin/python -m src.context.plans <DATE> CIN 9 Brandon Williamson
venv/bin/python -m src.context.plans <DATE> CLE 3 Joey Cantillo
venv/bin/python -m src.context.plans <DATE>            # list
venv/bin/python -m src.context.plans <DATE> CIN off    # clear
```

OUTS is an int ("three innings" is 9), a range like `3-6` (the counted
opener curve clipped to those bounds), or `pool` for the full first-time
-opener curve. Omit the bulk name when the pen simply takes over. An
applied plan prints `[PLAN ...]` on the game's rungs, and plans expire
with their date.

**DO NOT INFER A PLAN FROM RECENT USAGE — THE OPERATOR SUPPLIES IT**
(settled 2026-09-18, twice). The historical opener gate cannot see an
announced plan either way: its 120-day half-life left Leahy's weighted
mean at 14.1 outs against the 11-out trigger while his last three starts
were 9, 8, 9.

The opener's own OUTS rows can vanish from the board under a flat plan —
every line goes off-band when all 20,000 draws exit at 9 — and that is
the plan working, not the parser dropping rungs. His K ladder is the
comparable market; the morning of 2026-09-18 it moved Burns k 4.5 from
-285 (unplanned, vs a +170 market) to +233 (planned, vs +174).

## Freshness, and the gap that is not fixed

`data_status` measures every source against the newest FINISHED GAME, which
means **it cannot see a gap in the results table itself** — if yesterday's
games were never pulled, it reports the day before as newest and calls
everything current.

And `/backfill-data` does not close that gap. `season.missing_dates()`
computes its window as `SEASON_START .. min(cached_dates)`, and with 2023
games in the table `min` is `2023-03-15`, so the window is empty and step 1
prints "0 dates to pull" forever. It only fills BACKWARDS toward opening
day; pulling yesterday was the deleted scheduler's job.

So before a board, check the newest date by hand and pull it explicitly if
it is behind. **Results ending at yesterday is the EXPECTED morning state,
not a failure** — nothing runs overnight by design, so the morning session
pulls the previous night's games itself. Do it quietly and report the count;
warn only if the gap is more than one day (settled 2026-09-17):

```
venv/bin/python -c "
from src.context.sources import season as s
print(s.backfill(dates=['2026-09-09']))"
```

then run the rest of the `/backfill-data` chain, which does follow forward.
Found 2026-09-10 with 09-09's fifteen finished games missing and every
freshness row reading `ok`.

## Reading the output

**A short slate is usually real.** 2026-09-10 printed five games and the
first instinct was a broken slate call; the schedule API had five that day
against fifteen on either side. Check the API before debugging the code.

**`DECLINED` empty is not the same as nothing filtered.** Declines are
missing-opposing-starter only. The arm gate MARKS and does not decline, so
a flagged arm still prints every rung with its reason attached.

**A FLAGGED ARM MAY BE A STALE FLAG.** `slate.priceable` counts a
pitcher's start share over his ENTIRE four-season cache, so a reliever who
converted reads as a swingman forever. Nick Martinez is 27/28 starts in
2026 and 81/177 career, and printed as a swingman on two boards. Seven arms
league-wide are mis-flagged this way — Clay Holmes, Griffin Jax, Kyle Leahy
and Stephen Kolek among them. **Check the arm's CURRENT season before
believing a swingman or opener tag**, because BETTING.md says to treat a
gap on a flagged arm as our error and that rule fires backwards on a false
flag. **AND CHECK HIS LAST FEW WEEKS, NOT JUST THE SEASON SHARE** (added
2026-09-17): Wrobleski was 20/25 starts in 2026 and the flag was called
stale — but he had no start since 08-15, two 2-inning relief outings since,
and was an OPENER that night. A season share cannot see a September role
change; the market can (+264 on his outs 14.5, $48k traded, against our
-198). When the flag disagrees with the season share, query his recent
appearances (`is_starter`, outs) before overriding it — and a heavily
traded market far from our number on a flagged arm is the tell that the
flag is fresh, not stale. The gate is display-only — every rate build filters `is_starter = 1`,
so a bad tag never reached the simulation. The check is one command:

```
venv/bin/python -m src.context.arm "Name" <date>
```

whose STARTS table is counted with `appearance_order = 0` as the start —
Wesneski's flag was once "confirmed" by a hand query that filtered `=1`
and counted second pitchers. The same command answers "why is this K/outs
line priced like that": neutralised rates, velo kick, and the per-PA
chain against that night's lineup and park. `--parks <date>` lists the
slate's venue factors (MIL's k 1.11 is real — verified by count, NOTES
2026-09-13).

## Traps in the pipeline itself

**Step 1 must be redirected, not piped.** Same rule as `fit_hooks
--rebuild`: a `| head` closes the pipe and the exit status becomes the
pager's.

**Step 2 parses text.** `board_json` reads the printed columns with a
regex, so any change to `print_board`'s spacing silently drops rungs. The
counts it prints are the check — 2026-09-10 parsed 118 rungs over 5 games
with 96 carrying a Kalshi mid, and the same slate after lineups posted
gave 123 and 99. A fall in rungs-per-game means the parser, not the slate.

**Step 3 has died on a missing crossing.** `cross()` returns None when
every printed rung sits on one side of even money, which the ±170 band
makes ordinary rather than rare — the rung that would bracket the crossing
is the one the band drops. Guarded at `fmt_cross` since 2026-09-10 and
covered by
`check_board_html_survives_a_ladder_that_never_crosses_even_money`.

## What the page adds over the text

The FILTER and the K-DIVERGENCE table. The filter drops off-band rungs,
starter rungs with no Kalshi mid, and anything inside 3 points of the mid;
totals, team totals and F5 always stay, because fair-only is the product
there rather than a missing comparison. The K ladder ignores the filter —
a pitcher's divergence is a property of his whole curve.

Four prices per rung and no interpretation layered on top: our over, our
under, Kalshi's over, Kalshi's under. Kalshi's two cells mirror because its
`N+` binary is one contract; a sportsbook's two do not, because its hold is
baked into both. De-vig a book before calling anything backwards.
