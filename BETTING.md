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

## READING A ROW — the adjustments the board does NOT make for you

Added 2026-09-09, each one bought by a live bet in one session. The board
prints our probability and the mid; every line below is something the
operator has to do on top, and every one of them changed a verdict.

**1. COMPARE OUR PERCENTAGE TO YOUR PRICE'S BREAKEVEN, NOT TO THE EDGE
COLUMN.** The edge is measured against the Kalshi MID, which is not a
number you can bet. What you keep is `our probability - breakeven of the
price you got`. STL/SF F5 over 4.5 showed +2.9 against the mid and was
+1.5 at the +100 actually taken — a third of the disagreement went to the
book on the price.

**2. A GAP IN RUNS IS NOT A GAP IN PROBABILITY.** The slope measured 7.7
to 10.5 points per run across one slate, so half a run is worth 3.8 points
in one game and 5.2 in another. MIN/DET F5 read as "4.78 against a 4.5
line" — 0.28 runs of cushion — and was 53.3% against a 56.5% breakeven,
i.e. NEGATIVE. Convert first, always.

**3. A NEGATIVE EDGE DOES NOT MEAN TAKE THE OTHER SIDE.** It means we
price the over LOWER than the market does. COL/NYY F5 showed -3.2 and our
over was still 53.9%, so the under at +108 lost 4.2%. The edge column
tells you which way we differ; the breakeven tells you whether anything is
playable.

**4. SUBTRACT THE SLATE TILT BEFORE RANKING.** Game totals ran +3.7 points
against Kalshi on 09-08 and +0.16 runs on 09-09; outs rungs ran +9.3
points with 9 of 10 leaning the same way. A uniform one-way gap is our
level far more often than it is an edge, and a fixed threshold fires
disproportionately on whichever side the tilt is on. Rank on the residual
after removing the day's mean. The tilt MOVES day to day — it is not a
constant to subtract once.

**5. FIND WHICH SIDE OF THE GAME THE GAP IS ON.** Split a game total into
its two team totals before believing it. TEX/SEA: the whole +0.48-run gap
was Texas's runs off Kade Anderson, an arm 66% of whose priced rate is
league average — the Seattle side was dead on the market, so there was no
opinion in the bet. STL/SF was the same test passed: the flagged arm's
side agreed with the market and the gap sat on the CLEAN arm.

**6. IF THE TWO TEAM TOTALS CANCEL, IT IS A GAME-SCRIPT BET.** CIN/LAD
agreed with Kalshi on the game total to three tenths of a point (50.2
against 50.5) while disagreeing +5.3 on one club and -4.5 on the other.
That is a wager on how the runs DIVIDE, on a market never separately
scored here.

**7. CHECK THE ARM'S OWN RECORD FOR THAT EXACT LINE, BY SEASON.** It is a
SANITY CHECK, NOT A VERDICT: n is about 25-30 starts a season so se is
9-10 points, and his record is UNCONDITIONAL while our number is
conditional on tonight's nine — the model is SUPPOSED to disagree with a
season average. It still caught Sanchez (our 61.8% against his own 40.0%,
with the trend running away from the side) and it still backed Pallante
(our 3.84 sitting on his own 3.92 while the market sat at 3.21).

**8. INTEGER TOTALS PUSH, AND KALSHI HANGS NONE OF THEM.** Derive the
market's number from the half-run rungs either side; the gap between them
IS the push. COL/NYY implied P(total = 9) = 11.5%, so about one ticket in
nine refunds rather than resolving — which also makes it a weak data point
for any record you are keeping.

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

**Openers, swingmen and debuts are FLAGGED, not declined** (changed
2026-09-09; they were silently ungated 09-05 to 09-09, when `priceable`
went out with `price_slate`). `slate.priceable` asks whether an arm is one
a book hangs a normal line on — 3+ starts, 80+ batters faced, 11+ outs a
start, half his appearances starts — and the board prints the row with the
failing reason attached rather than hiding it. Hiding a rung hides the
disagreement too. TREAT A LARGE GAP ON A FLAGGED ARM AS OUR ERROR: the
model gives an opener a full starter's leash, which put Lake Bachar at
61.7% to clear 4.5 K on 2026-09-09 against a market at 7.5%. Flagged arms
are excluded from the K-divergence table and from the headline
disagreements for that reason.

**The market is a yardstick, never the objective.** Our resolution sits
at 91-98% of Kalshi's and better calibrated; the whole remaining prize
is ~2.5 Brier points. CLV can rise while the model gets worse at
baseball — no mechanism ships because it "beats the board."
