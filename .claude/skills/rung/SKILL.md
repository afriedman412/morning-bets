---
name: rung
description: Audit ONE bet against ONE price — breakeven, the board's number, the slate tilt, the pitcher's role and rate drift, counted batters faced, and a scenario grid. Use when the user names a specific line and a price ("singer u3.5k at +106", "is KC o3.5 at -136 any good", "pivetta o4.5 -112"), or asks whether a rung on the board is worth firing.
---

# Auditing one rung

`BETTING.md` is the authority on what each market is worth. This is the
procedure for a single bet, and `src/context/rung.py` is the procedure in
code — run it FIRST, then read around it.

```
venv/bin/python -m src.context.rung <DATE> "<selector>" <over|under> <price>

venv/bin/python -m src.context.rung 2026-09-24 "Singer k 3.5"     under +106
venv/bin/python -m src.context.rung 2026-09-24 "KC total 3.5"     over  -136
venv/bin/python -m src.context.rung 2026-09-24 "CWS@KC total 8.5" over  -120
```

The selector is a substring of `AWY@HOM <bet>` as the board prints it.
Several matches REFUSE rather than guessing — prefix the game when a name
is ambiguous. `--board <path>` overrides the board of record.

**It never re-simulates.** It reads the board JSON, which is why the
board must have been run for that date. It prints which file it read;
check that, because a re-run after lineups post makes a new version and
the old numbers stop being the numbers.

## What it does not do, and you must

**The price it is given is the price it believes.** Pass the price the
operator can actually get, not the Kalshi mid. The board's edge column is
measured against a mid nobody can bet — that is BETTING.md's first
reading rule and it is the whole reason this tool takes a price at all.

**It does not check the news.** A pitch limit, a scratch, a bullpen game
or an announced opener is invisible to every table it prints. An
announced plan goes in `src.context.plans` BEFORE the board is run.

**It does not recommend.** Every row is read off the board or counted on
this league. The call is the operator's.

## Reading the output

**TILT first, not the edge.** A uniform one-way gap is our level far
more often than it is an edge, and it moves day to day. The `de-tilted
edge` line is what is left if the slate gap is our level error rather
than information. On 2026-09-24 every totals rung on the board sat +5.8
points above Kalshi; three rungs that looked like bets were the tilt.

**But only a BROAD gap is a level.** The block is per UNIT (a pitcher's
ladder, a team side, a game), reports the median, the share leaning its
way and the two largest units, and prints the de-tilted edge only when
the lean reads UNIFORM. MIXED means a few arms carry the gap — read who
they are; a short-leash or rehab arm the market is pricing is information,
not our level, and it must not be subtracted from anyone else. On
2026-09-26 the blind mean said +6.9 and was May and Yesavage alone.

**DRIFT is the question the THIN flag cannot answer.** Pivetta and
Sandlin were both flagged THIN on ~120 batters faced. Pivetta's shipped
rate was .2758 against a post-layoff .2037; Sandlin's was .2278 against a
September .2308. Same flag, opposite verdicts, and only this table
separates them. **A LAYOFF row means the windows above it average across
an absence** — read that row, not the season.

**WORKLOAD decides strikeout props, not innings.** A K prop pays on
batters faced. Singer goes 15 outs on 90-plus pitches and still faces 24
to 25, so getting hit LENGTHENS his exposure. Three of the five rungs
audited on 2026-09-24 turned on this column and it is on no board.

**`board-implied` against DRIFT is the sim's own tell.** It backs out the
flat per-PA rate that reproduces the board's number at his usual
workload. Close to a DRIFT row means the sim agrees with that window.
Far from ALL of them means the sim's workload assumption or its TTO decay
is carrying the difference, not its rate — and that is worth saying out
loud rather than quoting the board.

**The scenario grid is binomial.** No hook, no TTO, no base-out state, so
expect it a few points off the board. A big gap is the finding.

**OUTS prints no grid, deliberately.** The hook is a manager decision,
not n independent trials, and BETTING.md has our outs number measured
2.5 sigma WORSE than the market head to head. Where we price an outs over
10+ points above Kalshi, we said 68.0%, the market said 51.6%, and it hit
45.6% — the bigger our edge looks on an outs rung, the more likely it is
ours that is wrong.

## The stale-flag trap, which fires backwards

A `swingman` or `opener` gate on the rung counts the arm's WHOLE
four-season cache, so a converted reliever reads as a swingman forever.
ROLE prints the per-season split so this is one glance.

But do not stop at the season share: **a September role change is
invisible to it either way.** Leahy was 29-for-29 starts in 2026 and his
last four outings were 9, 9, 8 and 9 outs on 38-61 pitches. Read the
`last 5 starts` outs row underneath, and if a heavily traded market sits
far from our number on a flagged arm, the flag is fresh, not stale.

## When the answer needs more than one rung

`venv/bin/python -m src.context.arm "Name" <DATE>` for the full per-PA
chain against tonight's lineup and park — the rung auditor deliberately
does not apply the lineup and park multipliers, because they need the
live slate and the board's own number already carries them.
