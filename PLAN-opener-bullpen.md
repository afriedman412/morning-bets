# PLAN — the opener, the bulk arm, and whether relief roles need models

**STATUS 2026-09-09: RUN. Steps zero, two, three, four and the stopgap are
done — results in `NOTES-context-layer.md` under this date. Step zero was
a positive-controlled null on WHO follows (do not model the named bulk
arm) and a huge positive on INTENT (the follower goes 9.50 outs), which
shipped as `USE_RELIEF_INTENT` via step three. Step one's named-handoff
version is dead per the step-zero stop; its content survives in the
intent tables. The falsifier below ran as `scratchpad/opener_score.py`.**

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

## STEP FOUR — CLOSERS. THE LEVEL IS COVERED; THE SLOT IS NOT.

REVISED 2026-09-09 after the operator pushed back and I read `PEN_PICK`
properly instead of asserting from memory. Half my original objection was
wrong and the correction is the whole item.

**WHAT IS ALREADY THERE, and it is more than I credited.** `PEN_PICK` is
counted on 24,181 real relief entries from inning 7 on: the chosen arm's
QUALITY PERCENTILE among the arms still unused that night, in fifths, by
the pitching side's margin at entry. Protecting a lead managers take the
top fifth 44.15% of the time; in a blowout they lean to the BOTTOM
(bin5 0.236) — good arms are SAVED, not merely deployed.

**AND BETWEEN-CLUB CLOSER QUALITY ALREADY FLOWS THROUGH.** The pool is the
club's OWN arms carrying their OWN rates, so an elite closer is in there as
himself; the percentile is only the SELECTION mechanism. "Some clubs have a
much better closer than others" is represented today as a level effect. Do
not rebuild it.

**READ THIS MODULE'S OWN HISTORY BEFORE TRUSTING THE INTUITION.** The
original plan's deterministic rule — close game, therefore best available
arm — was REFUTED BY ITS OWN COUNT: real P(best remaining | close) is
0.18-0.23 against a draw order's natural 0.157. Managers are far less
deterministic than "bring in the closer" feels. Whatever gets counted here,
expect the profile to be a distribution and not a rule.

**THE ACTUAL GAP, and it is narrow and specific: THE PROFILE IS KEYED ON
MARGIN ALONE.** `PEN_PICK_LATE = 7`, and one set of five "lead" weights
covers innings 7, 8 and 9 identically. A real closer appears almost only in
the ninth. Ours can be drawn in the seventh of a one-run game, be spent,
and leave a lesser arm holding the save situation. The operator's framing
is the right one — a closer's defining feature is that he reliably removes
a half-inning IN A PARTICULAR SLOT — and the slot is the one thing the
model does not have.

**THE CHEAP FIRST TEST.** Count P(the club's actual closer gets the ball |
inning 9, lead of 1-3) exactly the way `scratchpad/pen_pick.py` counted
everything else, and compare it against the "lead" bucket's 44.15% top
fifth. If the ninth is materially more concentrated than innings 7-8, the
missing thing is an INNING DIMENSION ON AN EXISTING COUNT — and
`game.next_arm` ALREADY RECEIVES `inning`, so the plumbing is threaded and
only the count is absent. That is one more conditioning column, the same
answer STEP THREE gives for intent, and not a new model.

FALSIFIER: if the ninth-inning lead profile is inside noise of the pooled
7-9 lead profile, the slot is not real and STEP FOUR closes. Report the
between-season correlation of the five weights the way `PEN_PICK` already
does — the lead/tied/mid shapes hold at +0.98, so there is a standard to
meet and a precedent for calling a flat shape flat.

**WHAT STAYS DEAD: A PER-CLOSER VARIANCE TERM.** "Feast or famine" as a
PER-PITCHER property is already measured and does not repeat — split-half
reliability 0.07 over 107 arms, powered to see 0.32. Do not fit a
dispersion parameter per closer; it is that same dead thing wearing a save.

**WHAT IS LEGITIMATELY OPEN IS THE ROLE-LEVEL VERSION**, which is a
different claim with a far smaller parameter count: is the SHAPE of a
one-inning outcome distribution different for closers AS A CLASS than for
setup arms AS A CLASS, at the same entry state? That is the sharp reading
of "reliably takes out a half-inning and occasionally blows up" — it is
about bimodality conditional on ROLE, not about pitcher-to-pitcher spread,
and the 0.07 measurement does not touch it. Positive-control the screen by
injecting a known shape difference at the claimed size, because a
mis-specified dispersion test and an absent effect look identical.

ORDER WITHIN THIS STEP: count the ninth-inning slot first. It is the one
with a mechanism already built to receive it. The role-level shape question
is second and only worth running if the slot count survives.

## ORDER, AND WHAT SHIPS

  1. STEP ZERO. It is a count, it is cheap, and it can end the item.
  2. STEP TWO. Also a count, independent of step zero, and it makes step
     one cheaper whichever way it lands. Do it second so that a null in
     step zero still leaves a usable result on the board.
  3. STEP ONE, only if zero survives.
  4. STEP THREE as a recount inside `relief.py`, not a new module.
  5. STEP FOUR — the ninth-inning slot count. It is INDEPENDENT of
     everything above and touches a different module (`pen_pick.py` /
     `PEN_PICK`), so it can run in parallel with the opener work rather
     than queue behind it. Listed last by priority, not by dependency.
     The original instruction here said "only through `leverage.py`";
     that was written when I believed `PEN_PICK` already covered the
     slot. It does not, so the count comes first and the leverage screen
     belongs on the ROLE-LEVEL SHAPE question at the end of step four,
     where reliability without sensitivity is still the risk.

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
