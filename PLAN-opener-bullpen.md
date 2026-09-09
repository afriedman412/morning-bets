# PLAN — the opener, the bulk arm, and whether relief roles need models

Written 2026-09-09 out of the TOR @ ATH board, where BOTH listed starters
were openers (Braydon Fisher, 3.38 outs a start; Brady Basso, 9.44) and the
model handed each of them a generic starter's ~16. Every number in that
game block was wrong in the direction the defect predicts, and the market
was right: it had Toronto over 4.5 runs at 70.0% against our 44.6%.

The operator's framing, and it is the load-bearing idea in this document:
**an opener start is TWO pitchers, and the second one is the one that
matters.** Everything below is built on that. His second question — whether
openers, long relievers and closers want one "short yardage" model or three
— is answered in STEP THREE, and the answer is neither.

## THE PRIZE, SIZED HONESTLY BEFORE ANY WORK

Counted on the cache 2026-09-09, starter outs by season:

    2023   5,328 starts   <=6 outs 6.3%   <=9 outs 12.2%   mean 15.15
    2024   5,268                   5.3%            10.3%          15.36
    2025   5,264                   4.8%            10.1%          15.31
    2026   4,306                   6.4%            11.1%          15.17

**So this is a 5-6% population, not a league-wide defect.** On a fifteen
game slate that is one or two games. Anything measured here will be
invisible in a season-level loss, and the battery will read it as noise.

THAT IS NOT A REASON TO SKIP IT, BUT IT DOES CHANGE THE YARDSTICK. This is
a COVERAGE item, not a level item: it converts one or two games a night
from unusable into priceable. Judge it on the run distribution IN THE
AFFECTED GAMES, never on a slate-wide loss, and say so in the writeup or
the result will be misread as a null. Related: the leverage floor decides
priority, never admissibility (CLAUDE.md).

## WHAT ALREADY EXISTS — DO NOT REBUILD ANY OF THIS

  * `relief.py` — outing length as a continuation hazard conditioned on
    the state he ENTERED in (0/1/2 out -> 20.1% / 44.8% / 62.7%), counted
    on 13,248 outings. `USE_MEASURED_RELIEF_LENGTH` on.
  * `USE_MEASURED_RELIEF_HOOK` — relievers can be pulled mid-inning, which
    is 58.2% of real handovers.
  * `deploy.py` — role is stable and projects: split-half r +0.55 to +0.78
    over 319 relievers. `PEN_PICK` already routes arms by margin bucket,
    `USE_PEN_ROLES` on.
  * `inherit.py` — inherited runners, followed by runner ID across 5,507
    handovers.
  * `leash.py` — and note `intended_from_starts` / `intended_starters`
    already exist, i.e. this repo has prior art on separating an INTENDED
    long start from a short one. Read it before writing anything new.
  * `slate.priceable` — identifies these arms already (avg outs < 11.0).
    It MARKS them on the board as of 2026-09-09; it does not fix them.

**WHY A LEASH FIX CANNOT WORK, so nobody tries it first.** `OFFSET_CLAMP`
bounds the per-pitcher hook adjustment at about +/-3.3 outs
(`OUTS_PER_OFFSET`). Fisher needs roughly -12. No value inside the clamp
reaches an opener. The representation is wrong, not the fit.

## STEP ZERO — THE GATE QUESTION, AND IT CAN KILL THE WHOLE ITEM

**Is the bulk arm predictable the morning of?** If, after a one-inning
opener, the follower is a coin flip among six relievers, then modelling the
handoff is a more expensive way to draw from the bullpen distribution we
already sample — which is the exact argument `deploy.py` opens with, and it
is why that module measured role stability BEFORE anything was built.

TEST. **IT IS A SQL QUERY, NOT A PLAY-BY-PLAY WALK.** `mlb_stints` in
`context.db` already holds 87,855 rows — one per pitcher per game with
`appearance_order`, `entry_inning`, `entry_outs`, `entry_margin`, `batters`
and `outs_recorded`. Join order 0 to order 1 on (game_id, team) and the
whole question falls out. Do not write an extractor.

**`appearance_order` IS 0-INDEXED AND THIS IS A LANDMINE.** Order 0 is the
STARTER (mean 15.21 outs), order 1 the first reliever (3.96). Reading it as
1-indexed silently measures "which reliever follows the first reliever",
returns 17,106 rows instead of ~1,200, and produces a modal-follower share
of 10.7% against a ~17% six-arm coin flip — i.e. **a clean-looking FALSE
NULL that kills this item.** That mistake was made and caught on
2026-09-09; sanity-check the row count against the ~1,143 short starts the
sizing table above predicts before believing any share.

Report, per club: the share of the time the follower is the club's modal
bulk arm, and the split-half reliability of "is X the bulk arm for this
club" across a season.

PREVIEW, from the corrected query on 2026-09-09 — **not the answer, but
enough to say the item is not obviously dead**: 1,220 short starts have an
identified follower, the starter averages 4.09 outs and the follower
averages **8.27** against 3.96 for a normal first reliever. So the second
man IS being used as a bulk arm rather than as an ordinary reliever, which
is the premise. What remains untested is whether WHICH man is predictable.

PRE-REGISTERED BAR: the follower must be predictable at better than
split-half r +0.40 — below `deploy.py`'s weakest measured role (+0.55) is
already generous. **If it fails, STOP. The gate flag stays the answer and
this document closes with a null**, which is a good outcome and should be
written into the notes as one.

POWER. State it before running. 1,143 events across ~30 clubs is ~38 per
club per four seasons; that is thin, and the honest move may be to pool
clubs and ask whether the follower is predictable AT ALL before asking
whether it is predictable per club.

## STEP ONE — THE HANDOFF, IF STEP ZERO SURVIVES

Model an opener start as a SEQUENCE, not as one short starter:

    (opener, planned ~1-2 innings) -> (bulk arm, long relief) -> normal pen

The opener half is nearly free: `relief.py`'s continuation hazard already
does short outings, and the opener enters with 0 out at the top of the
first, which is the cell it is best conditioned on. The work is the BULK
ARM — how long he goes, and at what rates.

WHAT IS NEW HERE and is not in `relief.py`: **INTENT.** A scheduled opener
and a reliever summoned in the fifth are different objects with the same
outs. `relief.py` conditions on entry STATE, which cannot distinguish them.
Add entry INNING (or a boolean "entered at the top of the first") as a
conditioning dimension and recount the hazard. That is one more column in
an existing count, not a new model.

## STEP TWO — THE SAME PITCHER IN TWO ROLES

The bulk arm's rates are the second half of the operator's question: "how
to adjust long reliever positions from starter data." The published answer
(a reliever gains a couple of points of K% over his starter self) is
EXACTLY the shape of imported constant this project has found wrong every
single time. Count it here.

DESIGN, and it is clean because it is WITHIN-PITCHER: 228 pitchers appeared
BOTH as a starter and in relief in 2026 alone. For each, compare his rates
in the two roles in the SAME season, then pool the differences. Paired,
so club and season and talent all cancel.

    k_pct, bb_pct, hr_pct, babip   as starter  vs  as reliever

REPORT the difference per stat with a standard error, and the split-half
reliability of the per-pitcher difference. **Ship the POOLED number if the
per-pitcher one does not repeat** — the same posture `advance.py` took when
the per-club gate failed and the league number stayed.

FALSIFIER: if the pooled role difference is inside one se of zero, the bulk
arm just uses his own rates and STEP TWO is done in an afternoon. That is a
perfectly good result and it makes STEP ONE cheaper.

## STEP THREE — ONE "SHORT YARDAGE" MODEL? NO. ADD A DIMENSION INSTEAD.

The operator asked whether openers and relievers want a shared model. My
read is that the shared model ALREADY EXISTS and is `relief.py` — outing
length conditioned on entry state, counted, not fitted, with a mid-inning
hook beside it. Building a second one alongside it would re-answer a
question that has an answer, and would introduce a second constant for the
same quantity, which is how one of them drifts.

**What is genuinely missing is not a model, it is a CONDITIONING VARIABLE:
intent.** An opener is a PLANNED short outing; a mop-up man in a blowout is
an unplanned long one; a setup arm is a planned one-inning outing. All
three are "short yardage" and they behave differently, and the thing that
separates them is why he was brought in, which is readable from entry
inning and entry margin — both of which the engine already knows at the
moment it has to decide.

So: extend `relief.py`'s conditioning to (entry_outs, entry_inning,
entry_margin_bucket) and recount. Check the cells for sample size first;
if the three-way split is too thin, collapse margin.

## STEP FOUR — CLOSERS, AND A WARNING BEFORE ANYONE BUILDS ONE

The operator's case: usually one inning, feast or famine, and can mitigate
an entire half-inning. Sized on 2026: 956 save-credited outings of <=3 outs
by 210 arms; 798 long relief outings of >=7 outs by 288 arms.

**SCREEN WITH `leverage.py` BEFORE BUILDING.** `USE_PEN_ROLES` and
`PEN_PICK` already route better arms into close games by margin bucket, so
the question is not "do closers differ" — they do — but "how much run
separation is left AFTER role-based deployment already fires." Reliability
without sensitivity is how park died three times in this repo.

**AND THE FEAST-OR-FAMINE HALF IS PROBABLY DEAD ON ARRIVAL AS A
PER-PITCHER TERM.** Per-pitcher and per-club dispersion have already been
measured here and do not repeat: split-half reliability 0.07 over 107 arms,
powered to see 0.32. A per-CLOSER variance term is that same dead thing.

What has NOT been tested is a ROLE-LEVEL dispersion difference — closers as
a CLASS against middle relief as a CLASS. That is a different claim with a
much smaller parameter count and it is legitimately open. Pre-register it
as such, and positive-control the screen by injecting a known dispersion
gap at the claimed size, because a mis-specified dispersion test and an
absent effect look identical (CLAUDE.md).

## ORDER, AND WHAT SHIPS

  1. STEP ZERO. It is a count, it is cheap, and it can end the item.
  2. STEP TWO. Also a count, independent of step zero, and it makes step
     one cheaper whichever way it lands. Do it second so that a null in
     step zero still leaves a usable result on the board.
  3. STEP ONE, only if zero survives.
  4. STEP THREE as a recount inside `relief.py`, not a new module.
  5. STEP FOUR last, and only through `leverage.py`.

SCORING, for all of it: the run distribution in AFFECTED GAMES against what
actually happened — the prefix ladder restricted to that population. Not
the market, and not a slate-wide loss, which cannot resolve a 5% population.
Run the battery around any change that touches `relief.py` or `game.py` and
report every row that moved, per rule 15.

THE ONE-LINE VERSION IF YOU READ NOTHING ELSE: count whether the bulk arm
is predictable, count what a pitcher's rates do when his role changes, and
only then decide whether an opener is worth simulating as two pitchers.

## AN OPERATIONAL STOPGAP, INDEPENDENT OF ALL OF THE ABOVE

On 2026-09-09, 54 of 126 game-level rungs (43%) sat in a game containing a
flagged arm and NONE of them carried a warning — the flag prints on the
pitcher's own K and outs rows only. Totals, team totals and F5 inherit the
identical defect and are the rows an operator actually bets. Propagate the
flag to every game-level rung in an affected game. Display only, no
modelling, and it is worth doing before any of the above.
