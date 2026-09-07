# BETTING — the operator's page

Rebuilt from scratch 2026-09-07. The old file described a betting layer
deleted on 2026-09-05 (`price`, `quote`, `tonight`, `f5_market` — none of
those commands exist); it survives in git history. Everything here refers
to tooling that runs today, and every rule carries the measurement that
bought it.

## THE COMMANDS

    venv/bin/python -m scratchpad.board [DATE] [SIMS]      the board
    venv/bin/python -m scratchpad.batprops DATE AWY HOM    offense props (AUDIT ONLY)
    venv/bin/python -m src.context.sources.lineup [DATE]   who has a posted nine

The board prices, per game off ONE shared set of draws: the full-game
total, both team totals, the F5 total, and each starter's K and outs
lines. Everything prints as fair AMERICAN ODDS, no vig. Kalshi mids
attach to K and outs where a book tighter than 12 cents exists.

**USE 20,000 SIMS FOR ANYTHING YOU MIGHT ACT ON.** Measured: a total
moved 7.34 → 7.05 between 400 and 20k sims; two 1,500-sim runs of one
line differed 1.2 points on seed alone.

## THE WORKFLOW

1. Morning board = orientation only. Every lineup is projected.
2. **Re-run once lineups post** (~2-3h before first pitch; the lineup
   command says who has one). The header flips to `lineups posted` and
   the `proj lineup` flags drop. Measured cost of skipping this: two
   wrong names in a projected nine erased HALF the biggest edge on the
   2026-08-27 board (Cameron, 17.03% K projected vs 18.69% real).
3. Fire or don't — the board is not a bet list. Before firing, check
   news on the specific arm (pitch limits, scratches, bullpen game);
   a uniform one-way gap against the market is more often the market
   knowing something than a free edge.

## WHAT TO TRUST, PER MARKET — measured, in order of confidence

    F5 total        THE PRODUCT. The only number here that ever beat a
                    settled price on outcomes (0.1890 Brier vs Kalshi's
                    close 0.1919, 455 contracts, unconfirmed sample).
    K 4.5-7.5       Usable as printed. The K level and the middle of the
                    distribution are measured right to a tenth.
    K 8.5+          The tail is light: the model prices a high-K over at
                    ~78% of its true probability (post-fix, 2026-08-29).
                    ADD ~2 POINTS TO THE OVER before comparing. A high-K
                    UNDER still wants a second reason — part of its edge
                    is our own missing tail.
    K vs the market K beat the OPEN (32.9% better at predicting the
                    close, +3.7c on 5c disagreements) and adds NOTHING
                    against the close (blend weight 0.00). Bet early or
                    not at all.
    outs            The corrected number is what prints; the raw is in
                    the note. Still the weakest starter market — the hook
                    is a manager decision reproduced only in aggregate —
                    but the sim beats a fitted model here at 4.1 sigma
                    on grading, so the number is not empty.
    full total      Usable with a season caveat: July/Aug measured ~4%
                    (0.15-0.20 runs/side) LIGHT — the month HR term is
                    unshipped — and September is UNMEASURED. The model
                    also over-weights 3-6 run games; a low-total under
                    lean is BIAS, not information.
    team totals     Follow from the same engine as the full total; same
                    caveats, never separately scored.
    ML / run line   **NEVER SCORED AGAINST OUTCOMES IN THIS REPO.** The
                    engine emits them; nothing has ever measured whether
                    its win probabilities are good. Not on the board
                    until that number exists.
    batter props    **UNSCORED — AUDIT ONLY.** `batprops` prints fair
                    odds for H/TB/HR/R/RBI/H+R+RBI off real per-batter
                    tallies (wired 2026-09-07), but no per-batter
                    quantity has ever been graded. The predictable
                    failure is the outs story again: calibrated in
                    aggregate, no discrimination per man. Grade it on
                    the pbp cache before a dollar moves on it.

## THE STANDING RULES

**Rank by gap over simulation error, not raw gap.** An 8.8-point gap on
a longshot is worth less than 8.3 at a coin flip; the probability is
least reliable exactly where the gap is largest.

**The ±170 band is a shopping filter, not a quality filter.** It keeps
the board to lines a book actually hangs. A rung the market quotes
prints regardless (`off-band`) — hiding the big disagreements was how
the board misread Ryan and Cease on 2026-09-07.

**THIN means the shrink target, not the arm.** Under 60% of a THIN
pitcher's priced rate is his own record; a gap on his rows can be our
shrinkage rather than his talent.

**Both starters or neither; never a live game.** A missing opposing
starter is a DECLINE (inventing the other club invents the score), and
`gamestate` resolves unknown to NOT pregame. Both print as declines —
that is working as designed; do not override it.

**Openers and debuts are declined, not priced.** A four-season-empty
arm is exactly where the market knows things this system cannot see.

**The market is a yardstick, never the objective.** Our resolution sits
at 91-98% of Kalshi's and better calibrated; the whole remaining prize
is ~2.5 Brier points. CLV can rise while the model gets worse at
baseball — no mechanism ships because it "beats the board."
