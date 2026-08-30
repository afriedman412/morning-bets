# BETTING — how to price a slate

Split out of `RESUME.md` on 2026-08-30. RESUME is the session handoff; this is the operator's reference and is the only file you need to price a card.

**CHECK IT AGAINST THE CURRENT STATE BLOCK IN `RESUME.md` before betting** — the model moved a lot on days 17-18 and two figures here were retracted on 2026-08-30.

## PRICING BETS TODAY — THE OPERATOR'S PAGE (written 2026-08-28)

Everything below this block is the modelling log. This block is what you
need to price a slate and nothing else.

### THE COMMANDS

    venv/bin/python -m src.context.price [DATE]          pitcher markets vs Kalshi
    venv/bin/python -m scratchpad.tonight [DATE] [SIMS]  game TOTALS
    venv/bin/python -m src.context.quote "Name" k under 4.5 +102     one bet
    venv/bin/python -m src.context.f5_market [DATE]      first-five totals
    venv/bin/python -m scratchpad.yesterday [DATE]       score a finished slate

`total_market` still has never completed a run. Use `scratchpad/tonight.py`
for totals — it walks `price.simulate_slate_game`, the same entry point the
props use, so a total and a starter's line cannot contradict each other.

**THE F5 COLUMN IN `tonight.py` READ 0.00 FOR EVERY GAME UNTIL 2026-08-28.**
`simulate_slate_game` passed no `track`, so `prefix_side` came back empty and
the first-five total — the STATED PRODUCT — was missing from the only tool
that shows a live slate. Fixed, `track=(5,)` is now the default, and a
missing F5 prints as `-` rather than as a number. If you are reading notes or
output from before today, ignore every F5 figure in them.

### 0. DO NOT BET THE MODEL'S HIGH-STRIKEOUT UNDERS (added 2026-08-29)

**THE K DISTRIBUTION IS TOO NARROW IN THE TAIL AND THE ERROR IS BIGGEST
EXACTLY WHERE THE BOARD SHOWS THE BIGGEST EDGES.** Measured on 1,074
holdout starts, rates frozen before 2026-07-01 (`scratchpad/shape.py`):

    line     model   actual     gap      se   sigma
    o3.5     0.713    0.676   +0.037   0.014   +2.6
    o4.5     0.539    0.515   +0.024   0.015   +1.6
    o5.5     0.365    0.364   +0.001   0.015    0.0
    o6.5     0.221    0.235   -0.014   0.013   -1.1
    o7.5     0.123    0.138   -0.015   0.011   -1.4
    o8.5     0.060    0.095   -0.035   0.009   -3.9
    o9.5     0.027    0.046   -0.019   0.006   -3.2
    o10.5    0.011    0.023   -0.013   0.005   -2.6

The middle of the board (5.5-7.5) is FINE. **At 8.5 and above the model
prices an over at roughly 60% of its true probability**, so its "edge" on
the under is largely its own missing tail. On 2026-08-28 that was six of
the ten largest gaps on the board — Skubal o8.5 ours 0.154 against a market
0.285, o9.5 0.074 against 0.165, o10.5 0.031 against 0.115. The market was
closer to right than we were.

**SOFTENED 2026-08-29, NOT DELETED.** The per-start strikeout draw
(`sim.START_K_SIGMA`, counted at 0.1625) closed a third of this. The table
above is the PRE-FIX state; current gaps are o3.5 +0.008, o8.5 -0.021,
o9.5 -0.010, o10.5 -0.006, so the model now prices a high-K over at about
78% of true rather than 60%.

**THE RULE NOW: add about 2 points to an over at 8.5+, and treat the
model's number as usable from 4.5 to 7.5.** The lean is still there and it
still runs one way — 2.3 sigma at o8.5 is better than 3.5 and is not zero —
so a high-K under still wants a second reason behind it.

WHY, LOCALISED: the length is right (mean outs 15.95 against 15.82) and the
K LEVEL is right (4.86 against 4.84). What is wrong is the JOINT. K per 27
outs, by length:

    bucket     model   actual
    15-17       8.42     8.33
    18-20       8.05     7.98
    21-27       7.51     8.49

The two middle buckets are right to a tenth. The model's rate then keeps
declining where reality's JUMPS — a real seven-inning start is a SELECTED
population, earned by missing bats, and the model has no selection at all.
`PITCH_COST` charges 4.97 pitches for a strikeout against 3.25 for an out,
so a high-K night SHORTENS a simulated start. That top bucket is where the
o8.5+ mass comes from, which is why the error is confined to the tail.

### FIVE THINGS THAT WILL COST YOU MONEY IF YOU FORGET THEM

**1. USE AT LEAST 20,000 SIMS BEFORE COMPARING TO A PRICE.** Measured: a
LAD/ATL total came out 7.34 at 400 sims and 7.05 at 20,000, which moved the
under from 51.6% to 54.8%. Two 1,500-sim runs of the same Cole line differed
by 1.2 points on seed alone. The defaults in these scripts are for
development, not for betting.

**2. THE MODEL IS ABOUT 4% LIGHT ON RUNS IN JULY AND AUGUST, AND IT IS A
KNOWN, MEASURED, UNSHIPPED CORRECTION.** Home runs per batter faced swing
from 0.912 in April to 1.085 in August and the model has one season-wide
baseline, so it under-produces homers in hot months. Measured on 2023-2025
and applied out of sample the correction moves a team total from -3.9% to
+0.7% against actuals (`scratchpad/month_league.py`). It is NOT shipped —
it has never been scored on F5 CRPS — so until it is, **treat model totals
in July/August as biased LOW by roughly 0.15-0.20 runs a side** and lean
accordingly. In April/May the bias runs the other way.

**3. RANK BY GAP OVER SIMULATION ERROR, NOT BY RAW GAP.** `price.py` already
computes the per-market error. Sorting on |ours - market| puts an 8.8-point
gap on a longshot above an 8.3-point gap at a coin flip, and the probability
estimate is least reliable exactly where the gap is largest.

**4. THE PROJECTED LINEUP IS THE WEAKEST LINK, and it is not modelled as a
source of error anywhere.** On 2026-08-27 the biggest edge on the board was
Noah Cameron unders against Toronto, built on a projected nine at 17.03% K.
Two of nine names were wrong; the real card was 18.69%, and HALF THE EDGE
DISAPPEARED. Before betting a large edge, check the posted lineup and
re-run. Flag any edge whose size depends on unconfirmed names.

**5. THE MODEL LEANS UNDER ON LOW TOTALS AS A MATTER OF BIAS.** It carries
too much mass at 3-6 runs (0.099 against an actual 0.067 at three). The
odd/even sawtooth in game totals is real and correctly reproduced; the
low-total lean is not information.

### WHAT IT WILL AND WILL NOT PRICE

**Both starters or neither.** A game with an unmodelled starter on either
side is DECLINED, never filled with a league-average arm — `simulate_slate_game`
returns a reason and `tonight.py` prints it. A debut or a four-season-empty
arm is exactly where the market knows things this system cannot see. That is
working as designed; do not override it.

**Never price a game in progress.** `gamestate.is_pregame()` guards the live
paths and an unknown state resolves to NOT pregame.

**What this models, in order of confidence:** F5 team totals, then full team
totals, then strikeout props. Outs props are the dead half — the model
reproduces the manager's hook only in aggregate. Home-run props are not
worth pricing off this until the seasonal factor ships.

### WHAT CHANGED TODAY THAT AFFECTS YOUR NUMBERS

Three shipped constants, all measured, all neutral-or-better on F5:

    pitcher k_pct    57 -> 132     was stale, +9.5 sigma on holdout K
    pitcher babip   500 -> 3068    had NEVER been measured
    batter row      32/80/160/184 -> 51/122/193/447

Net effect on a price: strikeout projections are pulled harder toward league
for arms with short lines, and a pitcher's own BABIP now counts for about a
tenth rather than four tenths. Both make thin-sample arms read closer to
average, which is the correct direction and slightly reduces the number of
large edges the board shows.


