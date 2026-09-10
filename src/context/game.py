"""A whole game, both sides, nine innings — the thing that was missing.

WHAT DID NOT EXIST BEFORE THIS. The engine this replaced,
`sim.simulate_start`, modelled ONE PITCHER and returned the moment the hook
fired. Innings after the pull were never simulated at all, so a full team
total could not be produced: the project had pitcher props, it had
first-five via a stub, and it had no game. Both are deleted as of
2026-08-25 and this is the only engine.

TWO SIDES, RUN IN TANDEM. Away pitching faces the home nine, home pitching
faces the away nine, and given the lineups those are independent — there is
no interaction to model. The only reason to interleave them is ORDERING: a
manager decides in the bottom of the fifth knowing what his own offence has
done, so both sides have to advance half-inning by half-inning for a live
score to exist. Same independent draws, just alternated.

That live score is what makes the removal rule modelable at all. Until now
`mid_removal_p` could see pitches, runs allowed, runners on and inning
damage, but NOT the margin — a single pitching side simulated in isolation
has no idea whether it is winning. `Hook.per_margin` and `mid_per_margin`
exist now and both default to ZERO, so this changes nothing until it is
measured against observed removal timing.

THE BULLPEN IS SAMPLED, NOT AVERAGED. The deleted `f5.relief_rates()`
collapsed 374 relief arms into one set of rates. That was a defensible stub
for first-five, where relief appears about a quarter of the time and usually
for under an inning; it is badly wrong across a full game, where the bullpen
throws roughly 40% of the innings EVERY time. The measured defect in the run
distribution is that it is COMPRESSED — too many shutouts and too few
crooked numbers at once — and a league-average arm every night is precisely
how that happens. The real arms span K% 0.165 to 0.304 with sd 0.037, and
that spread was being computed and thrown away.

INHERITED RUNNERS ARE NO LONGER A FUDGE. The deleted `f5._side_runs`
credited a departing starter's stranded runners at a flat
`INHERITED_SCORE_RATE` of 0.33 because it never simulated the reliever
finishing the inning. This does simulate him, so those runners score or do
not score for the reasons they actually would — the base-out state is handed
over intact.
"""
from __future__ import annotations

import bisect
import datetime
import random
from dataclasses import dataclass, field, replace

from src.context import leash as _leash
from src.context import relief, removal, sim, velo
from src.context.sources import rates as rate_src

#: How many relief arms a club is assumed to have available. Real bullpens
#: carry 8, and a nine-inning game essentially never needs more than four
#: after a starter, so this only bites in a disaster.
PEN_DEPTH = 8

#: Relief outings run to their MEASURED length instead of a flat one inning
#: each. Off restores the pre-measurement engine exactly, because every
#: mechanism here has to stay separately scoreable — the winning combination
#: is not necessarily the newest state. Same shape as
#: `sim.USE_MEASURED_ADVANCEMENT`.
USE_MEASURED_RELIEF_LENGTH = True

#: Relievers can be pulled MID-INNING, the way 58.2% of real mid-inning
#: handovers happen. Off, only a starter's hook can produce one, which caps
#: the model at 41.8% of them. Separate from `USE_MEASURED_RELIEF_LENGTH`
#: because the two pull in opposite directions on how many arms a game uses
#: and have to stay independently scoreable.
USE_MEASURED_RELIEF_HOOK = True

#: The relief continuation hazard conditions on INTENT — the inning and
#: margin the arm ENTERED at — not just the base-out state
#: (PLAN-opener-bullpen.md, 2026-09-09). The pooled 20.1% clean-entry
#: continuation is dominated by late innings: an arm entering in innings
#: 1-3 (the bulk man behind an opener or an early exit) really continues
#: 76% and averages 9.50 outs against a first reliever's 3.96, and the old
#: table cut him off at one inning like a setup man. Off restores the
#: pooled tables. Only meaningful with `USE_MEASURED_RELIEF_LENGTH` on.
USE_RELIEF_INTENT = True

#: A flagged short-yardage starter gets HIS OWN exit distribution — a
#: bootstrap from his own recorded outs per start — instead of the hook
#: (TODO 15, PLAN-opener-bullpen.md). The hook plus leash cannot reach him:
#: `OFFSET_CLAMP` bounds the per-pitcher adjustment at about +/-3.3 outs
#: and an opener averaging 3.4 outs needs ~-12, so the model handed every
#: opener a generic starter's ~16 outs and the relief intent tables fired
#: on fictional late entry states in exactly the games they were built
#: for. The gate is the same cell `slate.priceable` declines to quote
#: (average under `OPENER_AVG_OUTS` outs a start), so the arm the board
#: flags and the arm the engine re-models are the same arm.
USE_OPENER_EXIT = True

#: The short-yardage cell: mean outs a start below this marks an arm whose
#: length the hook cannot represent. THE SAME NUMBER as
#: `slate.MIN_AVG_OUTS`, which reads it from here — two copies of this
#: constant is how the board flags one population and the engine re-models
#: a different one.
OPENER_AVG_OUTS = 11.0

#: THE BULK ARM BEHIND AN OPENER IS A STARTER, SO RUN HIM DOWN THE STARTER'S
#: PATH (TODO 15). Counted prospectively off the follower's own trailing 30
#: appearances (`scratchpad/bulk_type.py`, 687 planned openers): 31.3% of
#: the time a bona fide starter follows, 20.2% a swingman, 48.5% a pure
#: bullpen game. And the starter type is HOOKED EARLY rather than pitching
#: differently — paired against his own normal starts, -3.15 outs (se 0.30)
#: and -15.56 pitches (se 1.43), about ten sigma each.
#:
#: WHAT `starter_out` COSTS HIM, and it is more than the leash. Five things
#: key on that flag — which arm's rates are used, times through the order,
#: mid-inning removal, the boundary hook and the continuation hazard — so a
#: rotation starter working as a bulk arm was being run as a one-inning
#: reliever with NO TTO DECAY AT ALL, while really facing the order nearly
#: twice. Not tripping the flag puts him back on all five.
#:
#: NOT A PAIRED A/B, and for a reason worth stating rather than hiding: off,
#: the ball goes to the pen and a different pitcher throws the rest of the
#: game. `next_arm` draws no random number before `PEN_PICK_LATE` and an
#: opener exits long before the seventh, so the streams are aligned AT the
#: switch and diverge after it because the mechanism differs — which is what
#: a mechanism flag is supposed to do.
USE_BULK_STARTER = True

#: How much SHORTER than his own normal start the bulk arm is left in.
#: Converted to a hook offset through `leash.offset_for`, which is the same
#: road every per-pitcher leash adjustment already travels, and it is well
#: inside `leash.OFFSET_CLAMP` — unlike the opener himself, who needs about
#: -12 outs and gets the bootstrap in `USE_OPENER_EXIT` instead.
BULK_OUTS_DELTA = -3.15
#: Starts on record before the bootstrap is trusted at all. Below this the
#: arm keeps the generic hook — a one-start record is a coin, not a
#: distribution — unless his RELIEF USAGE identifies him (below).
OPENER_MIN_STARTS = 2

#: THE RECORD GOES STALE, and a flat mean over four seasons cannot see a
#: role change in either direction (TODO 15, `scratchpad/opener_decay.py`).
#: Both directions were costing: the gate MISSED 36.4% of real opener
#: starts because a converted arm still carried three seasons of sixteen-out
#: starts, and FIRED on rotation starts for months after the reverse
#: conversion — 23.3% of the starts it fired on went fifteen outs or more.
#:
#: Weighting each prior start by 0.5 ** (days_ago / HALF) fixes both with
#: one number. Chosen on TRAIN rows by RMSE against the arm's actual outs
#: — an interior optimum of a grid running 20 to 540 days, so it is not a
#: grid-edge parameter — and confirmed on the holdout, where it takes
#: overall RMSE 3.8420 -> 3.7737 (-2.4 sd paired) and the short-record
#: population, which is where the gate fires, 4.2811 -> 3.5687.
#:
#: THIS IS A MEASUREMENT OF STALENESS, NOT A FITTED LEVEL. The half-life
#: was fitted to predict the quantity it is used to predict — how long he
#: goes tonight — the same posture `stabilise.py` takes with its four
#: shrinkage constants. Nothing here was tuned against a run loss.
#:
#: As a classifier it dominates the flat mean on BOTH axes rather than
#: trading them off, which is why it ships without a threshold change:
#: recall 63.6% -> 70.4%, false alarms 23.3% -> 21.1% (train rows).
OPENER_HALF_LIFE_DAYS = 120.0

#: Off restores the flat mean exactly, so OFF is bit-for-bit the pre-decay
#: engine and the scored baseline is recoverable.
#:
#: BUT THIS FLAG IS NOT A PAIRED A/B, unlike `USE_OPENER_EXIT` beside it,
#: and the difference is worth stating rather than discovering. Those flags
#: draw the exit unconditionally and gate only its USE, so both states
#: consume one identical stream. This one changes WHICH ARMS ARE FLAGGED,
#: and `build_side` draws an exit only for a flagged arm — so in exactly
#: the games where the gate's answer changes, the stream diverges and
#: everything downstream of it moves. That is inherent to the change, not
#: an oversight: flagging a different population cannot be stream-neutral.
#: Judge it on the battery diff over four folds, not on a paired draw.
#:
#: Weighting the bootstrap DRAW by the same decay is the obvious next step
#: and is deliberately NOT bundled here — it needs a different call into
#: the rng, and two mechanisms behind one flag cannot be told apart.
USE_OPENER_DECAY = True

#: The no-record fallback (operator's insight, 2026-09-09: nothing says
#: "bullpen" like almost never pitching in the 3rd). An arm with fewer
#: than `OPENER_MIN_STARTS` starts whose CURRENT role is late-inning
#: relief is a first-time opener, and the shipped gate cannot see him —
#: 333 such starts over four seasons averaged 6.16 outs while the hook
#: handed them ~15. He gets the exit distribution below, counted on
#: exactly that population (rule 9). Where a record and the role
#: CONTRADICT (a demoted starter opening), the record wins and no
#: fallback fires: measured, those arms really go 12.8 outs against
#: their record's 13.4, and own-record beats the opener pool by 6 sigma
#: (`scratchpad/opener_class.py`).
#:
#: Role is read off the arm's last `OPENER_ROLE_WINDOW` appearances in
#: `mlb_stints`: at least `OPENER_ROLE_MIN_RELIEF` relief entries, a
#: relief share of `OPENER_ROLE_RELIEF_SHARE` or more, and no more than
#: `OPENER_ROLE_EARLY_SHARE` of those entries beginning by the 3rd —
#: early entries are a LONG MAN, a different animal (mean 11.99 outs).
#: A missing stints table or an unknown arm classifies as nothing and
#: the engine behaves exactly as before — the missing-group rule.
OPENER_ROLE_WINDOW = 30
OPENER_ROLE_MIN_RELIEF = 10
OPENER_ROLE_RELIEF_SHARE = 0.8
OPENER_ROLE_EARLY_SHARE = 0.15

#: The no-record fallback's own switch, so it scores separately from the
#: own-record bootstrap above (both under `USE_OPENER_EXIT`). Off, a
#: usage-identified first-time opener keeps the full hook. The draw is
#: consumed either way — see `build_side` — so the A/B streams stay
#: paired across this flag exactly as they do across `USE_OPENER_EXIT`.
USE_OPENER_POOL = True

#: {outs: count} over the 333 no-record opener-class starts, 2023-2026.
#: Counted by `scratchpad/opener_class.py --table`, no loss function —
#: recount after a backfill the way `relief.tally` recounts its tables.
#: The shape is the operator's "exactly 3 or 6 outs" measured: modal 3
#: (planned one inning), a spike at 6, a thin bulk tail.
OPENER_POOL_DIST: dict[int, int] = {
    1: 4, 2: 19, 3: 122, 4: 24, 5: 13, 6: 49, 7: 7, 8: 11, 9: 24,
    10: 8, 11: 5, 12: 5, 13: 4, 14: 6, 15: 23, 16: 2, 17: 1, 18: 5,
    20: 1,
}

#: OFF. The learned removal model — a per-decision logistic on 63,531 real
#: hooks, AUC 0.912 against `sim.Hook`'s 0.876 — replaces BOTH of the hook's
#: branches with one roll per plate appearance.
#:
#: IT WAS SHIPPED ON A FALSE PREMISE AND IT COSTS THE DISTRIBUTION. The
#: premise, written here, was that the model's target spans the inning
#: boundary so one roll covers what `mid_removal_p` and `removal_p` did
#: separately. It does not: `_half_inning` breaks out of its loop on the
#: third out BEFORE the roll happens, so the inning-ending plate appearance
#: never got a decision at all. Instrumented, 72,426 hook calls across 2,000
#: games came back at outs 0/1/2 and never once at a boundary.
#:
#: Even with that fixed (`USE_BOUNDARY_HOOK`) one model gives ONE probability
#: at two moments whose real rates differ 2.2x — 6.30% at a boundary against
#: 2.83% mid-inning. Starts end on a completed inning 34.6% of the time with
#: it and 71.3% without, against a real 63.2%.
#:
#: The two branches are the right shape and `calibrate.loss` already targets
#: the boundary share, which is why they were within 0.2 points of it when
#: last fitted. The learned model was validated on removal-decision AUC — an
#: upstream proxy — and discarded a calibration nobody re-checked.
#:
#: Kept switchable rather than deleted: it is a candidate that has to earn
#: its way back in on the outs DISTRIBUTION, not on AUC.
USE_LEARNED_HOOK = False

#: The AUTOMATIC RUNNER. Every half-inning from the tenth starts with a man
#: on second and nobody out. MLB has done this since 2020 and permanently
#: since 2023; this simulator played extras under the old rules until
#: 2026-08-29, which is 8.3% of games.
#:
#: COUNTED ON OUR OWN 2026 LINE SCORES, which is what makes it a defect
#: rather than a rules footnote:
#:
#:     games past nine              167 of 2,006   (8.3%)
#:     mean innings in those        10.34
#:     runs per EXTRA half-inning    1.049   (448 halves)
#:     runs per REGULATION half      0.498   (35,207 halves)
#:
#: A real extra half-inning scores 2.11x a regulation one and the model was
#: producing a regulation one. Worth ~0.12 runs a game on a FULL-GAME total,
#: concentrated as ~1.1 runs in the games that go long.
#:
#: IT CANNOT REACH F5 OR A STARTER'S LINE, which is exactly why nothing
#: caught it: full-game totals and moneylines are the two markets that have
#: never been scored against a settled price.
#: ON. Every half-inning from the tenth starts with a man on second and
#: nobody out — MLB since 2020, permanently since 2023. This simulator
#: played extras under the old rules until 2026-08-29.
#:
#: SCORED, 537 holdout games x 20 sims, paired on seeds:
#:
#:                            OFF       ON    ACTUAL   se(act)
#:     share past nine      0.078    0.078     0.083     0.006
#:     mean innings then   11.170   10.228    10.340     0.050
#:     runs per extra half  0.354    0.671     1.049     0.070
#:     game total           8.611    8.620
#:
#: Extra-inning LENGTH is essentially fixed — 11.17 was 16 sigma off and
#: 10.23 is within two. Runs per half improves sharply. The SHARE reaching
#: extras does not move, and the GAME TOTAL moves +0.009: the runner adds
#: runs per inning and removes innings, and those nearly cancel. **The
#: value is in the SHAPE of extras, not the level.**
#:
#: **IT WAS PARKED FOR A DAY ON A MEASUREMENT BUG, which is the lesson.**
#: The first pass read "auto ON pushes the share from 5.4% to 3.3% against
#: a real 8.3%" and that was entirely `simulate_game` skipping the track
#: block on the `break` that ends a game when the home side wins in its
#: half. Games that ended on the winning half read as nine innings and fell
#: out of the extras sample — NON-RANDOMLY, since they are exactly the
#: games that ended. Fixed by `_track` firing on every exit path, after
#: which both arms read 0.078 and the share was never the problem.
#:
#: `runs per extra half` is a FLOOR, not a point estimate: the denominator
#: counts two halves per extra inning and a game ending in the first half
#: played one. The isolated half-inning with the runner produces 0.969
#: against a league run expectancy of ~1.05, which is the honest figure.
#:
#: The automatic runner is UNEARNED — `fr.errored` is set, which routes the
#: half's runs away from earned. Approximation: MLB would still charge the
#: batter's own run. It reaches only a reliever's ER in extras, which
#: nothing here prices.
USE_AUTO_RUNNER = True

#: **OFF, AND THE REORDER IS A STRUCTURAL NO-OP. Do not try this again.**
#:
#: The proposal was to roll steals, wild pitches and passed balls BEFORE
#: the plate appearance instead of after, on the argument that (a) the
#: at-bat should resolve against the post-steal state, (b) an inning-ending
#: caught stealing should VOID the at-bat rather than follow it, and (c)
#: the lineup pointer should not advance on that voided at-bat.
#:
#: BUILT AND SCORED. Predicted -0.18 plate appearances a game; measured
#: +0.037, which is noise on 74.9.
#:
#: **(a) IS A REAL DEFECT AND THE FIX IS WORTH NOTHING. Those are separate
#: statements.** An at-bat does resolve against a state one event stale —
#: at-bat N sees at-bat N-1's steals, not its own — and reordering fixes
#: exactly that. It buys nothing because the staleness shifts UNIFORMLY:
#: moving which at-bat owns each steal by one slot is a relabelling, and
#: the same at-bats meet the same distribution of base states either way.
#: The aggregate rates are identical by construction.
#:
#: (b) IS NOT REACHABLE AT THIS GRANULARITY AT ALL. The at-bat reality
#: erases is the one IN PROGRESS when the runner is thrown out, and a
#: plate-appearance-granular model has no in-progress at-bat. Voiding it
#: needs pitch-level simulation, which is a different engine.
#:
#: Kept switchable rather than deleted so the null stays scoreable, and
#: because the reordering argument will be made again by someone reading
#: `_half_inning` for the first time.
USE_RUNNERS_FIRST = False


#: WHICH ARM GETS THE BALL, late — plan item 6. The pen was sampled by
#: appearances and then walked IN DRAW ORDER, so reliever quality was
#: independent of the score: the closer could mop up a blowout and the
#: twelfth man protect a one-run lead. Counted on 24,181 real relief
#: entries in inning >= 7 (`scratchpad/pen_pick.py`, pre-July rows of
#: all four seasons): the chosen arm's QUALITY PERCENTILE among the
#: arms still unused that night, in fifths, by the pitching side's
#: margin at entry. Bin 1 is the best fifth. Protecting a lead managers
#: take the top fifth 44% of the time; trailing they are nearly flat;
#: in a blowout they lean to the BOTTOM of the pen (bin5 0.236) —
#: good arms are SAVED, not just deployed. The lead/tied/mid shapes
#: hold at +0.98 between-season correlation of the five weights; trail
#: and blowout are flat shapes whose lower correlations are noise
#: around flat. The plan's original deterministic rule ("close -> best
#: available") is refuted by its own count — real P(best remaining |
#: close) is 0.18-0.23 against the draw order's natural 0.157, and the
#: big miss was the blowout side (0.084), so the shipped mechanism
#: draws from the counted profile instead of forcing the top.
#:
#: Quality is K%-BB% — the rank `deploy.py` found projects (its
#: high-leverage share holds at r +0.55 split-half). Percentile, not
#: absolute rank, so the profile transfers from the real ~12-arm pen it
#: was counted on to the 8-arm pool the model samples.
PEN_PICK = {
    "lead":    (0.4415, 0.1989, 0.1330, 0.1117, 0.1149),
    "tied":    (0.3823, 0.2143, 0.1427, 0.1149, 0.1459),
    "trail":   (0.2307, 0.2069, 0.1957, 0.1687, 0.1981),
    "mid":     (0.3407, 0.2035, 0.1544, 0.1280, 0.1734),
    "blowout": (0.2067, 0.1855, 0.1848, 0.1874, 0.2357),
}
#: Entry innings the profile was counted on; earlier the manager is
#: covering for a short start, which is a different decision.
PEN_PICK_LATE = 7
USE_PEN_ROLES = True

#: THE SAME PROFILE, KEYED ON THE INNING TOO (TODO 21, raised by the
#: operator). `PEN_PICK` above was counted POOLED over innings 7-9, and the
#: real structure is setup in the 7th and 8th, closer in the 9th — so the
#: pooled weight is wrong at BOTH ends rather than merely blurred, and the
#: engine could spend a club's best arm two innings early.
#:
#: Protecting a lead, the share of entries that take the best remaining arm:
#:
#:     inning        7th      8th      9th+     pooled (shipped)
#:       lead     0.3356   0.4108   0.5750       0.4415
#:       tied     0.3213   0.3642   0.4356       0.3823
#:       mid      0.2462   0.3014   0.4906       0.3407
#:
#: The lead row moves +0.2394 from the 7th to the 9th at 15.3 sd, and every
#: bucket rises monotonically — including the blowout, where managers lean
#: to the bottom of the pen throughout. `scratchpad/pen_pick_inning.py`,
#: same quality-percentile construction as `pen_pick.py` (rank among the
#: arms still unused tonight, in fifths, bin 1 = best remaining) so the two
#: counts are comparable line for line. Pre-holdout rows of all four
#: seasons; thinnest cell 771.
#:
#: WHAT THIS IS NOT: a closer OBJECT. `closer_slot.py` measured that the
#: club's top-fifth K%-BB% arm already takes the save slot 73.3% of the
#: time, so `PEN_PICK` was largely drawing the right man — in the wrong
#: inning. The missing thing was the SLOT, which is one more key, not a
#: named role. And he must stay in the pen for the earlier innings: almost
#: 30% of a closer's work is before the ninth (8th 18%, 7th 6%, 6th 4%).
PEN_PICK_BY_INNING = {
    ("lead", "7"): (0.3356, 0.2220, 0.1601, 0.1318, 0.1505),
    ("lead", "8"): (0.4108, 0.2172, 0.1512, 0.1172, 0.1034),
    ("lead", "9+"): (0.5750, 0.1567, 0.0891, 0.0865, 0.0927),
    ("tied", "7"): (0.3213, 0.2438, 0.1514, 0.1237, 0.1597),
    ("tied", "8"): (0.3642, 0.2292, 0.1585, 0.1179, 0.1302),
    ("tied", "9+"): (0.4356, 0.1825, 0.1275, 0.1075, 0.1469),
    ("trail", "7"): (0.2169, 0.2082, 0.2024, 0.1631, 0.2094),
    ("trail", "8"): (0.2331, 0.2150, 0.1964, 0.1659, 0.1896),
    ("trail", "9+"): (0.2568, 0.1881, 0.1764, 0.1881, 0.1907),
    ("mid", "7"): (0.2462, 0.2144, 0.1800, 0.1497, 0.2097),
    ("mid", "8"): (0.3014, 0.2101, 0.1713, 0.1394, 0.1777),
    ("mid", "9+"): (0.4906, 0.1826, 0.1072, 0.0913, 0.1282),
    ("blowout", "7"): (0.1805, 0.1919, 0.1890, 0.1976, 0.2411),
    ("blowout", "8"): (0.1968, 0.1894, 0.1809, 0.1883, 0.2445),
    ("blowout", "9+"): (0.2415, 0.1751, 0.1854, 0.1771, 0.2209),
}

#: Off restores the pooled table exactly, so OFF is the pre-item engine.
#: No random variate is involved either way — this changes which WEIGHTS a
#: uniform is walked against, not how many are drawn — so it is a clean
#: paired A/B and the streams stay aligned.
USE_PEN_INNING = True


def _pick_inning(inning: int) -> str:
    """7, 8, or 9+. Extras go with the ninth: same slot, same arms."""
    return "7" if inning <= 7 else ("8" if inning == 8 else "9+")


# ---------------------------------------------------------------------------
# THE CLOSER IS A ROLE, NOT A DRAW (TODO 21, the operator's ruling).
#
# `PEN_PICK` picks by QUALITY PERCENTILE, and a percentile can only ever
# approximate a categorical decision. `closer_slot.py` measured the size of
# the miss: the closer is his club's top-fifth K%-BB% arm just 73.3% of the
# time, so in the other 27% NO reweighting of the profile can reach him. It
# has to be encoded, and it will not emerge from better modelling of
# anything else.
#
# The counted decision, `scratchpad/closer_usage.py`, 17,596 club-games with
# a named closer before the holdout — P(the arm entering IS the named
# closer), by inning, margin and whether he worked the club's previous game:
#
#                   7th            8th            9th+
#     save        4.5 / 1.9%    14.9 / 8.9%    73.3 / 61.4%
#     tied        4.2 / 2.3%    12.7 / 4.9%    55.8 / 40.7%
#
# A TWENTYFOLD SWING from the seventh to the ninth. Availability is worth
# 12 points in the ninth on its own, which is TODO 8's "fatigue" bullet
# arriving as a SELECTION effect — as a RATE it is dead and must stay dead.
#
# AND THE MARGIN KEY IS THE SAVE RULE, recovered from the data rather than
# imported from the rulebook: P(closer) in the ninth runs 0.6724 / 0.6945 /
# 0.6894 at leads of one, two and three, then falls off a cliff — 0.5343 at
# four, 0.2305 at five, 0.0843 beyond. `_pick_bucket` splits at 2 and 4 and
# so lumps a three-run lead (a save) in with a four-run one (not); it was
# built for the quality profile and is the wrong key for a role.
CLOSER_USE = {
    ("7", "save", False): 0.0447, ("7", "save", True): 0.0190,
    ("7", "tied", False): 0.0418, ("7", "tied", True): 0.0228,
    ("7", "+4", False): 0.0441, ("7", "+4", True): 0.0234,
    ("7", "+5", False): 0.0396, ("7", "+5", True): 0.0170,
    ("7", "+6", False): 0.0236, ("7", "+6", True): 0.0158,
    ("7", "-1", False): 0.0300, ("7", "-1", True): 0.0080,
    ("7", "trail", False): 0.0273, ("7", "trail", True): 0.0059,
    ("8", "save", False): 0.1485, ("8", "save", True): 0.0885,
    ("8", "tied", False): 0.1267, ("8", "tied", True): 0.0489,
    ("8", "+4", False): 0.0984, ("8", "+4", True): 0.0292,
    ("8", "+5", False): 0.0517, ("8", "+5", True): 0.0165,
    ("8", "+6", False): 0.0358, ("8", "+6", True): 0.0111,
    ("8", "-1", False): 0.0910, ("8", "-1", True): 0.0203,
    ("8", "trail", False): 0.0768, ("8", "trail", True): 0.0127,
    ("9+", "save", False): 0.7332, ("9+", "save", True): 0.6137,
    ("9+", "tied", False): 0.5580, ("9+", "tied", True): 0.4070,
    ("9+", "+4", False): 0.6271, ("9+", "+4", True): 0.3914,
    ("9+", "+5", False): 0.3008, ("9+", "+5", True): 0.1264,
    ("9+", "+6", False): 0.1221, ("9+", "+6", True): 0.0241,
    ("9+", "-1", False): 0.2520, ("9+", "-1", True): 0.0605,
    ("9+", "trail", False): 0.1206, ("9+", "trail", True): 0.0204,
}

#: Off, the closer is an ordinary member of the sampled pen and the
#: percentile profile decides — the pre-item engine. The roll is drawn
#: either way (see `next_arm`), so the streams stay paired.
USE_CLOSER_ROLE = True


def _closer_margin(margin: int) -> str:
    """The SAVE RULE, keyed off the counted cliff rather than the rulebook.

    `margin` is the pitching side's lead, the `mlb_stints.entry_margin`
    convention. A lead of one, two or three is one cell because the data
    says so — 0.6724 / 0.6945 / 0.6894 — and four is its own because it
    breaks (0.5343).
    """
    if margin >= 6:
        return "+6"
    if margin == 5:
        return "+5"
    if margin == 4:
        return "+4"
    if margin >= 1:
        return "save"
    if margin == 0:
        return "tied"
    return "-1" if margin == -1 else "trail"


def closer_p(inning: int, margin: int, worked_yesterday: bool) -> float:
    """P(this relief entry is the club's named closer). 0 when unkeyed."""
    return CLOSER_USE.get(
        (_pick_inning(inning), _closer_margin(margin),
         bool(worked_yesterday)), 0.0)


def _pick_bucket(margin: int) -> str:
    """Signed where the behaviour is signed — margin is the PITCHING
    side's lead, the same convention `mlb_stints.entry_margin` counts."""
    a = abs(margin)
    if a > 4:
        return "blowout"
    if a > 2:
        return "mid"
    if margin > 0:
        return "lead"
    return "tied" if margin == 0 else "trail"


@dataclass
class Side:
    """One team's PITCHING through a game: who is on, and what they allow."""
    starter: sim.PitcherRates
    pen: list[sim.PitcherRates]
    lineup: list[sim.BatterRates]          # the OPPOSING nine
    hook: sim.Hook = field(default_factory=sim.Hook)
    #: Runs this side has ALLOWED. The other team's score.
    runs: int = 0
    #: What the other pitching side has allowed — i.e. THIS team's score.
    #: Set by the driver each half-inning so a walk-off can be detected
    #: without passing the whole game state around.
    opposing_runs: int = 0
    idx: int = 0                            # batting-order pointer
    pen_i: int = 0
    starter_out: bool = False
    #: (arms unavailable, days of club rest) for THIS club tonight, from
    #: `sim.pen_state`. None means league-neutral and contributes zero to
    #: either hook curve. Carried on the SIDE because it is a property of
    #: the club and the date, not of the pitcher on the mound — every arm
    #: that takes the ball tonight faces the same depleted pen behind him.
    pen_state: tuple[float, float] | None = None
    #: The game's HR AIR multiplier (`sim.air_hr_mult` — temperature and
    #: wind), set by `simulate_game` on BOTH sides: the two clubs hit in
    #: the same air, the same shape park takes. 1.0 when the game has no
    #: reading, and each half of it is silent-neutral on its own.
    hr_air: float = 1.0
    #: The plate umpire's (k, bb) multipliers (`sim.ump_kbb_mult`), set by
    #: `simulate_game` on BOTH sides for the same reason as `hr_air`: one
    #: man calls the whole game for both clubs. (1.0, 1.0) when the crew
    #: is unknown — silent-neutral like every other lookup here.
    ump_kbb: tuple[float, float] = (1.0, 1.0)
    #: Days since THIS STARTER's previous start, from `sim.layoff_gap`.
    #: None means unknown, no prior start, or across a season break, and
    #: contributes exactly zero to either hook curve. See `sim.per_layoff`.
    #:
    #: Carried on the SIDE and not on the arm because both hook call sites
    #: are already guarded by `not side.starter_out` — the term was counted
    #: on starter decisions only, and a reliever must never receive it.
    layoff_gap: int | None = None
    #: RESOLVED MATCHUPS, nine of them, rebuilt when the arm changes.
    #:
    #: The point of `sim.resolve` is that a plate appearance's inputs get
    #: assembled in ONE place instead of being read out of five. Doing it
    #: per pitcher rather than per plate appearance also respects the note
    #: on `pa_outcome` that per-PA object construction was deliberately
    #: removed as too expensive — nine objects an arm, reused for every
    #: time through the order.
    #:
    #: Keyed on the pitcher OBJECT, not his name: two clubs can carry the
    #: same name, and a stale cache here would silently price every batter
    #: against the previous arm.
    _mups: list | None = None
    _mups_for: object = None
    #: How many outs were already recorded when the CURRENT reliever came in
    #: (0 for a clean inning), and how many full innings he has thrown since.
    #: Together these are what `relief.continues` conditions on, so they must
    #: be maintained wherever `next_arm` is called.
    cur_entry_outs: int = 0
    cur_extra_innings: int = 0
    #: The inning and margin the CURRENT reliever ENTERED at — the intent
    #: dimension of `relief.continues`. Margin at ENTRY, not at the
    #: decision, because that is what the table was counted on
    #: (`mlb_stints.entry_margin`); using the live margin would be a
    #: different conditioning wearing the same name.
    cur_entry_inning: int = 0
    cur_entry_margin: int = 0
    #: Runs allowed in the half-inning that just finished. The between-
    #: innings decision is made after the Frame is gone, and the early
    #: boundary branch keys on how the last inning went — a starter who has
    #: just been hit for four is a different decision from one who set them
    #: down in order.
    last_inning_runs: int = 0
    #: Set when this start was drawn as an EARLY EXIT — the outs total at
    #: which the starter comes out regardless of what the hook says. None is
    #: an ordinary start. Drawn once in `build_side`, before a pitch, because
    #: it is a mode of the start rather than a decision inside it.
    forced_exit_outs: int | None = None
    #: THE NAMED BULK ARM behind an opener, and the hook he gets — his own
    #: leash shifted by `BULK_OUTS_DELTA`. None on an ordinary start and on
    #: a pure bullpen game, which is 48.5% of planned openers; then the ball
    #: goes to the pen exactly as it always did.
    #:
    #: HE IS AN INPUT, NOT A PREDICTION. Step zero killed predicting WHO
    #: follows an opener from history. This is the announced pairing off the
    #: slate, or the recorded follower when replaying a game that has been
    #: played — the same information class as the probable starter, which
    #: the slate has always taken as given.
    bulk: sim.PitcherRates | None = None
    bulk_hook: sim.Hook | None = None
    bulk_in: bool = False
    #: THE NAMED CLOSER, and whether he worked the club's previous game.
    #: He is an ordinary member of `pen` — deliberately, because almost 30%
    #: of a closer's work comes before the ninth (8th 18%, 7th 6%, 6th 4%)
    #: and removing him from the pool would trade one wrong answer for
    #: another. What the role does is give him the SLOT, not exclusivity.
    closer: sim.PitcherRates | None = None
    closer_worked: bool = False
    #: The starter's own line, so props and F5 still read off one pitcher.
    #: IT STAYS THE OPENER'S when the bulk arm comes in — he is who the
    #: board named and whose line a start prop settles on.
    line: sim.StartResult = field(default_factory=sim.StartResult)
    #: Whoever is on now, and his line (the starter's IS `line`).
    cur_line: sim.StartResult | None = None
    runs_f5: int = 0
    #: Per-batter attribution for the nine this side FACES — which is the
    #: OPPOSING team's offence, the same crossing `GameResult` documents.
    #:
    #: IT LIVES ON THE SIDE AND NOT ON THE LINE BECAUSE `next_arm` REPLACES
    #: `cur_line`. `sim.StartResult` has carried `scored_by`/`rbi_by` since
    #: 2026-08-27 and nothing could read a whole team's offence off them:
    #: every reliever's innings went on the floor at the arm change, which
    #: is roughly a third of the runs in a game. Folded here on the way past
    #: so no caller has to remember an end-of-game step.
    bat_scored: dict = field(default_factory=dict)
    bat_rbi: dict = field(default_factory=dict)
    bat_h: dict = field(default_factory=dict)
    bat_tb: dict = field(default_factory=dict)
    bat_hr: dict = field(default_factory=dict)
    #: Runs allowed ON a home run, across every arm. Folded for the same
    #: reason the dicts are: `next_arm` drops the line it sits on.
    bat_runs_hr: int = 0
    #: Plate appearances FACED, across every arm — the opposing team's PA.
    #: THE DENOMINATOR. Every offence question here is a rate and the run
    #: total alone cannot say whether a gap is production or opportunity.
    bat_pa: int = 0

    def __post_init__(self):
        if self.cur_line is None:
            self.cur_line = self.line

    def _fold(self, ln: sim.StartResult) -> None:
        for src, dst in ((ln.scored_by, self.bat_scored),
                         (ln.rbi_by, self.bat_rbi),
                         (ln.h_by, self.bat_h),
                         (ln.tb_by, self.bat_tb),
                         (ln.hr_by, self.bat_hr)):
            for who, n in src.items():
                dst[who] = dst.get(who, 0) + n
        self.bat_runs_hr += ln.runs_hr
        self.bat_pa += ln.batters

    @property
    def runs_on_hr(self) -> int:
        """Runs allowed on a home run, whole game. Non-mutating like
        `offense()` — the arm currently on has not been folded yet."""
        return self.bat_runs_hr + self.cur_line.runs_hr

    @property
    def pa_faced(self) -> int:
        """Plate appearances faced by every arm — the opposing team's PA."""
        return self.bat_pa + self.cur_line.batters

    def offense(self) -> dict:
        """{batter: {"r", "rbi", "h", "tb", "hr"}}, whole game.

        NON-MUTATING, and that is the point: it merges what has been folded
        with the arm currently on the mound, so it is correct whenever it is
        called and calling it twice cannot double count. A fold-on-read
        would be one forgotten copy away from exactly that.
        """
        out: dict = {}
        live = self.cur_line
        for tag, folded, now in (("r", self.bat_scored, live.scored_by),
                                 ("rbi", self.bat_rbi, live.rbi_by),
                                 ("h", self.bat_h, live.h_by),
                                 ("tb", self.bat_tb, live.tb_by),
                                 ("hr", self.bat_hr, live.hr_by)):
            for src in (folded, now):
                for who, n in src.items():
                    out.setdefault(who, {"r": 0, "rbi": 0, "h": 0,
                                         "tb": 0, "hr": 0})[tag] += n
        return out

    @property
    def current(self) -> sim.PitcherRates:
        if not self.starter_out:
            return self.starter
        if not self.pen:
            return self.starter
        return self.pen[min(self.pen_i, len(self.pen) - 1)]

    def to_bulk(self) -> bool:
        """Hand the ball to the named bulk arm WITHOUT tripping `starter_out`.

        Returns False when there is no bulk arm to hand it to — no name, the
        flag is off, or he has already been used — and the caller then goes
        to the pen exactly as before.

        `line` IS DELIBERATELY NOT REPLACED. It is the opener's, and a start
        prop settles on the man the board named; the starter-path hook reads
        `cur_line` instead, which already means "whoever is on now". Getting
        that backwards would report the bulk arm's fifteen outs as the
        opener's line in every replay.

        `forced_exit_outs` is cleared because it was the OPENER's drawn exit
        — leaving it set pulls the bulk arm at the same out count the moment
        he arrives, which is a one-line way to build a mechanism that fires
        and then immediately undoes itself.
        """
        if not USE_BULK_STARTER or self.bulk is None or self.bulk_in:
            return False
        self.bulk_in = True
        self._fold(self.cur_line)
        self.cur_line = sim.StartResult()
        self.starter = self.bulk
        if self.bulk_hook is not None:
            self.hook = self.bulk_hook
        self.forced_exit_outs = None
        # Counted on a starter's days since his OWN previous start, which
        # nobody has for an arm arriving in the second inning. Unknown is
        # silent-neutral on both hook curves, which is the right answer.
        self.layoff_gap = None
        self._mups = self._mups_for = None
        return True

    def next_arm(self, entry_outs: int = 0, rng=None, inning: int = 0,
                 margin: int | None = None) -> None:
        """Go to the pen — and from inning seven, pick WHO by the counted
        selection profile rather than draw order.

        `entry_outs` is the base-out state the incoming arm walks into, and
        it is the strongest predictor of how long he stays — 20% of arms
        handed a clean inning come back out, against 63% of those brought in
        with two down.

        `inning` is the ENTRY inning — between-innings callers pass the
        completed inning plus one. THE ROLL IS DRAWN WHETHER OR NOT THE
        FLAG USES IT, same rule as the mid-inning relief hook above: a
        switch that consumes a different number of random numbers is not
        an A/B. One uniform covers both the profile bin and the position
        inside it.
        """
        slot = 0 if not self.starter_out else self.pen_i + 1
        pool = self.pen[slot:]
        if (rng is not None and margin is not None
                and inning >= PEN_PICK_LATE and len(pool) > 1):
            u = rng.random()
            # ONE UNIFORM, TWO DECISIONS, AND IT HAS TO BE ONE DRAW. A
            # second `rng.random()` here shifts every event after it, so the
            # flag's off position would stop being the pre-item engine and
            # no A/B across it would be paired —
            # `check_the_pen_roll_is_drawn_whether_or_not_the_flag_uses_it`
            # catches exactly that and caught it here.
            #
            # So the closer takes the BOTTOM `p` of the uniform and the
            # quality profile gets the rest, rescaled. With the role off, or
            # with nobody named, `p` is 0 and `v is u` — bit-for-bit the
            # engine that shipped this morning.
            p = 0.0
            if (USE_CLOSER_ROLE and self.closer is not None
                    and any(a is self.closer for a in pool)):
                p = closer_p(inning, margin, self.closer_worked)
            if u < p:
                # A ROLE, NOT A DRAW — he is named, so he is chosen, and the
                # quality profile never runs. This is the whole point of the
                # item: in the 27% of clubs whose closer is not a top-fifth
                # arm, no percentile could have reached him.
                j = next(i for i in range(slot, len(self.pen))
                         if self.pen[i] is self.closer)
                self.pen[slot], self.pen[j] = self.pen[j], self.pen[slot]
            elif USE_PEN_ROLES:
                u = (u - p) / (1.0 - p) if p else u
                # HE IS RESERVED, so he leaves the quality draw entirely.
                # THIS IS THE OTHER HALF OF THE ROLE AND WITHOUT IT THE
                # MECHANISM IS WORSE THAN NOTHING: the closer is usually his
                # club's best K%-BB% arm, so the profile kept reaching for
                # him in the seventh and the engine used him there on 19.9%
                # of entries against a real 3.3%. The role roll above only
                # accounts for 4.5 of those points; the rest was the draw
                # not knowing he was spoken for.
                #
                # This does NOT reserve him for the ninth — the table
                # already lets him work the seventh at the counted rate, and
                # his own record says almost 30% of his appearances come
                # before the ninth. It stops him being picked as though he
                # were an ordinary arm.
                cand = pool
                if p:
                    rest = [a for a in pool if a is not self.closer]
                    if len(rest) > 1:
                        cand = rest
                b = _pick_bucket(margin)
                # THE INNING IS THE SLOT. Pooled over 7-9 the weight is
                # wrong at both ends, so this is not a refinement of the
                # bucket — it is the dimension the bucket was averaging
                # over. Falls back to the pooled row if a cell is ever
                # missing, which keeps the degradation monotone.
                w = PEN_PICK[b]
                if USE_PEN_INNING:
                    w = PEN_PICK_BY_INNING.get((b, _pick_inning(inning)), w)
                c = 0.0
                for k, wk in enumerate(w):
                    if u < c + wk or k == 4:
                        break
                    c += wk
                frac = min(max((u - c) / wk, 0.0), 1.0) if wk else 0.5
                pct = min((k + frac) / 5, 1.0)
                # Best fifth first: rank 0 is the highest K%-BB% left.
                ranked = sorted(cand, key=lambda a: a.bb_pct - a.k_pct)
                choice = ranked[round(pct * (len(cand) - 1))]
                j = next(i for i in range(slot, len(self.pen))
                         if self.pen[i] is choice)
                self.pen[slot], self.pen[j] = self.pen[j], self.pen[slot]
        if not self.starter_out:
            self.starter_out = True
        else:
            self.pen_i += 1
        # FOLD BEFORE DISCARDING. `cur_line` is about to be replaced and
        # the outgoing arm's attribution goes with it otherwise.
        self._fold(self.cur_line)
        self.cur_line = sim.StartResult()
        self.cur_entry_outs = entry_outs
        self.cur_extra_innings = 0
        self.cur_entry_inning = inning
        self.cur_entry_margin = margin or 0


def _half_inning(side: Side, lg: dict, rng: random.Random, inning: int,
                 margin: int, park: dict | None,
                 walk_off: bool = False, auto_runner: bool = False) -> None:
    """One half-inning. `margin` is this pitching side's lead, in runs.

    Runs are counted from the CHANGE in the current pitcher's line rather
    than recomputed, so the side total and the individual lines can never
    disagree — and both come from `sim.apply_pa`, which is the single copy
    of the base-out state machine.
    """
    fr = sim.Frame()
    if auto_runner and USE_AUTO_RUNNER:
        # THE RULE NAMES HIM: the automatic runner is the player who made
        # the last out of the previous inning, which is the batter one slot
        # BEHIND the pointer. `side.idx` already points at who is due up,
        # so `idx - 1` is exactly that man and no new state is needed.
        #
        # An anonymous `True` token was tried first and it breaks
        # attribution: `_credit` skips `True` when recording who scored, so
        # every run the automatic runner scored went uncredited and the
        # per-batter tally stopped summing to the team total. That is a real
        # check (`check_per_batter_runs_add_up_to_the_team_score`) and it
        # caught this immediately.
        fr.bases[1] = side.lineup[(side.idx - 1) % len(side.lineup)].name
        # HIS RUN IS UNEARNED. MLB treats the automatic runner as having
        # reached on an error for earned-run purposes, and `fr.errored` is
        # the switch `_score` already reads.
        #
        # APPROXIMATION, STATED: this makes EVERY run in the half unearned,
        # where MLB would still charge the batter's own. It reaches only a
        # RELIEVER'S earned runs in extra innings — reliever lines are
        # discarded on each arm change and nothing here prices ER — so the
        # cost is nil and the alternative is per-runner earned tracking
        # through two scoring paths.
        fr.errored = True
    while fr.outs < 3:
        # RUNNER EVENTS FIRST, and this is a causal fix rather than a
        # reordering. A steal or a wild pitch happens DURING an at-bat, so
        # the hitter finishes it in the state those events left behind. The
        # roll used to sit after `apply_pa`, which cost two things:
        #
        #   * the at-bat resolved against a STALE base-out state. Harmless
        #     until 2026-08-29 because the plate appearance ignored the
        #     state entirely; live now that `STATE_MULT` ships.
        #   * an inning-ending CAUGHT STEALING arrived AFTER the at-bat, so
        #     the model played a plate appearance that reality erases and
        #     advanced the lineup a slot it should not have. Counted: 0.185
        #     inning-ending caught stealings a game.
        #
        # The first iteration is a no-op — `baserunning` returns
        # immediately on empty bases — and the trailing roll after the
        # third out disappears, which is the half that was wrong.
        if USE_RUNNERS_FIRST:
            outs_before = fr.outs
            before = side.cur_line.runs
            sim.baserunning(side.cur_line, fr, rng)
            side.runs += side.cur_line.runs - before
            if fr.outs >= 3:
                # The inning ended on the bases. No batter is charged and
                # the pointer does not move: he leads off the next inning.
                _boundary_roll(side, fr, inning, margin, rng, outs_before)
                break
        # The batting-order pointer indexes the RESOLVED matchups now, so
        # the batter object itself is no longer read here — everything the
        # plate appearance needs was assembled by `sim.resolve`.
        slot = side.idx % len(side.lineup)
        side.idx += 1
        # The learned model's `outs` feature is outs BEFORE the plate
        # appearance — a PA never starts with three — so the inning-ending
        # decision has to be rolled with this value, not with fr.outs after.
        outs_before = fr.outs
        # TTO applies to the STARTER only. A reliever has no meaningful
        # lineup pass, and passing 1 for him would hand every arm out of the
        # bullpen a 1.105 strikeout bonus.
        # PER ARM, NOT PER SIDE. `cur_line` is `line` for an ordinary start,
        # so this is unchanged there — but the bulk arm behind an opener is
        # meeting the lineup for the FIRST time whatever the opener already
        # faced, and reading the side's starter line would hand him a third
        # time through before he had faced nine men.
        tto = None if side.starter_out else side.cur_line.batters // 9 + 1
        # LAZY, PER SLOT. Resolving all nine on every arm change built ~90
        # matchups a game against ~76 plate appearances — MORE objects than
        # the per-PA version it replaced, and measured 23% slower. A
        # reliever who faces three batters needs three, not nine.
        if side._mups_for is not side.current:
            side._mups = [None] * len(side.lineup)
            side._mups_for = side.current
        mu = side._mups[slot]
        if mu is None:
            mu = side._mups[slot] = sim.resolve(
                side.lineup[slot], side.current, lg, park, side.hr_air,
                side.ump_kbb[0], side.ump_kbb[1])
        # THE FIELD STATE the hitter actually walks into. `fr.bases`
        # holds runner tokens, so truthiness is the occupancy count.
        o = sim.pa_from(mu, rng, tto=tto,
                        state=(sum(1 for b in fr.bases if b), outs_before))

        before = side.cur_line.runs
        sim.apply_pa(o, side.cur_line, fr, rng,
                     batter=side.lineup[slot].name, mu=mu)
        side.runs += side.cur_line.runs - before
        if fr.outs >= 3:
            _boundary_roll(side, fr, inning, margin, rng, outs_before)
            break

        if not USE_RUNNERS_FIRST:
            before = side.cur_line.runs
            sim.baserunning(side.cur_line, fr, rng)
            side.runs += side.cur_line.runs - before
            if fr.outs >= 3:
                _boundary_roll(side, fr, inning, margin, rng, outs_before)
                break
        # A walk-off ends the game mid-inning. `walk_off` is only ever set
        # for the bottom of the ninth or later, and `side` here is the
        # PITCHING side, so its runs allowed ARE the home team's score.
        if walk_off and side.runs > side.opposing_runs:
            return

        # Mid-inning removal. The comment that used to sit here said a
        # reliever is never pulled in the same breath he arrived, which is
        # true of his first two batters and false after that: of 4,026
        # mid-inning handovers only 41.8% come from a starter, and the other
        # 58.2% are one reliever giving way to another. The measured hazard
        # carries the "just arrived" protection itself — 1.5% for his first
        # two batters against a 14.1% peak once he has faced the men he came
        # in for — so it does not need to be hard-coded here.
        if side.starter_out:
            # THE ROLL IS DRAWN WHETHER OR NOT THE FLAG USES IT, and that is
            # the point rather than an oversight. `USE_MEASURED_RELIEF_HOOK`
            # is an A/B switch, and a switch that consumes a DIFFERENT NUMBER
            # of random numbers is not an A/B — every event after it lands on
            # a different draw, so the two arms stop being the same game.
            #
            # It was harmless only because the model almost never pulled a
            # starter inside the first inning (0.5% of half-innings), so
            # `check_the_first_inning_is_immune_to_a_bullpen_flag` passed
            # VACUOUSLY. The counted pitch hazard makes early pulls realistic
            # and the check starts failing on a stream shift that has nothing
            # to do with baseball: with an empty pen `current` returns the
            # starter, so the same arm faces the same batters either way.
            rl = side.cur_line
            roll = rng.random()
            if (USE_MEASURED_RELIEF_HOOK
                    and roll < relief.mid_removal(
                        rl.runs, rl.batters,
                        # INTENT, the same dimension the continuation hazard
                        # takes and gated on the same flag, so the two halves
                        # of "how long does this arm stay" cannot end up
                        # conditioned on different things. Entry state, not
                        # the live state — that is what the table counted.
                        entry_inning=(side.cur_entry_inning
                                      if USE_RELIEF_INTENT else None))):
                side.next_arm(fr.outs, rng, inning, margin)
        elif not side.starter_out and USE_LEARNED_HOOK:
            if rng.random() < removal.predict(
                    _state(side, fr, inning, margin)):
                ln = side.cur_line
                ln.pulled_mid_inning = True
                ln.left_on_base, ln.outs_when_pulled = fr.on_base, fr.outs
                if not ln.covered_f5:
                    ln.runs_f5, ln.outs_f5 = ln.runs, ln.outs
                side.next_arm(fr.outs, rng, inning, margin)
        elif not side.starter_out:
            ln = side.cur_line
            if (_forced_out(side, ln)
                    or (_hook_may_pull(side, ln)
                        and rng.random() < side.hook.mid_removal_p(
                            ln.pitches, ln.runs, fr.on_base, fr.damage,
                            margin, inning_runs=fr.runs, inning=inning,
                            inning_br=fr.br,
                            # HOW THE NIGHT IS GOING. `ln.k` and
                            # `ln.batters` both already include the plate
                            # appearance just resolved, which is what the
                            # fitted rows do too — `boundary.decisions`
                            # folds the current play in before emitting,
                            # because the manager obviously saw it.
                            k_rate=(ln.k / ln.batters
                                    if ln.batters else None),
                            pen=side.pen_state,
                            layoff_gap=side.layoff_gap))
                    or ln.pitches >= side.hook.hard_pitch_cap):
                ln.pulled_mid_inning = True
                ln.left_on_base, ln.outs_when_pulled = fr.on_base, fr.outs
                if not ln.covered_f5:
                    ln.runs_f5, ln.outs_f5 = ln.runs, ln.outs
                # The reliever inherits the bases and the outs exactly as
                # they stand. Those runners now score, or do not, for the
                # reasons they actually would — no INHERITED_SCORE_RATE.
                # He also inherits the OUT COUNT, which is what decides how
                # long he stays: an arm handed two down finishes the inning
                # and comes back out 63% of the time.
                #
                # UNLESS THE BULK ARM IS NAMED — then this is not a handover
                # to the pen at all, it is the second starter of a planned
                # two-man game.
                if not side.to_bulk():
                    side.next_arm(fr.outs, rng, inning, margin)

    # Every exit from the loop above is a `break`, so one assignment here
    # covers them all. The walk-off `return` skips it and that is correct —
    # the game is over and no between-innings decision follows.
    side.last_inning_runs = fr.runs


#: Off restores the defect this fixes, for A/B measurement.
USE_BOUNDARY_HOOK = True


def _boundary_roll(side: Side, fr, inning: int, margin: int,
                   rng: random.Random, outs_before: int) -> None:
    """The decision made on the plate appearance that ENDS an inning.

    THIS WAS NEVER BEING MADE. `_half_inning` breaks out of its loop the
    moment the third out lands, which is before the removal block, and
    `_end_of_inning` returns early whenever the learned hook is on. So the
    starter could only ever leave mid-inning: 72,426 instrumented hook calls
    across 2,000 games came back at outs 0, 1 and 2, and never once at an
    inning boundary.

    The learned model always knew about these decisions — `removal.py`
    counts "did not come back out for the next half-inning" as a removal, so
    boundary hooks are in its training target and its coefficients. They
    simply had no code path to fire on.

    The cost was the whole shape of the starter-length distribution. Real
    appearances end on a completed inning 64.1% of the time and the
    simulator managed about 5%, scattering the mass onto .1 and .2 exits
    that managers rarely make. Means were unaffected, which is why every
    aggregate check passed — and why anything priced at a specific outs line
    was wrong.

    Rolled with `outs_before` because that is the feature the model was fit
    on: a plate appearance never begins with three out, so an outs=3 state
    is one the coefficients have never seen.
    """
    if side.starter_out or not USE_BOUNDARY_HOOK or not USE_LEARNED_HOOK:
        return
    st = _state(side, fr, inning, margin)
    st["outs"] = outs_before
    if rng.random() >= removal.predict(st):
        return
    ln = side.cur_line
    # He finished the inning, so nothing is inherited and no runner is left
    # behind — the distinction the mid-inning path exists to carry.
    if not ln.covered_f5:
        ln.runs_f5, ln.outs_f5 = ln.runs, ln.outs
    side.next_arm(0, rng, inning + 1, margin)


def _state(side: "Side", fr, inning: int, margin: int) -> dict:
    """What the manager can see, in the learned model's feature names."""
    ln = side.cur_line
    p = side.starter
    return {
        "pitches": ln.pitches, "bf": ln.batters,
        "tto": min(ln.batters // 9 + 1, 3),
        "br": ln.h + ln.bb + ln.hbp + ln.roe,
        "damage": ln.damage, "onbase": fr.on_base,
        "inning": inning, "outs": fr.outs,
        "margin": margin, "abs_margin": abs(margin),
        "runs": ln.runs,
        "k_pct": p.k_pct, "bb_pct": p.bb_pct,
        "quality": p.k_pct - p.bb_pct,
    }


def _forced_out(side: Side, ln: sim.StartResult) -> bool:
    """Has this start reached the outs total it was drawn to end at?"""
    return (side.forced_exit_outs is not None
            and ln.outs >= side.forced_exit_outs)


def _hook_may_pull(side: Side, ln: sim.StartResult) -> bool:
    """The floor, and it is what keeps the two modes from overlapping.

    In the mixture the hook owns starts that were NOT drawn as early exits,
    and it owns them only above the floor. Letting it fire below would put
    its own short starts on top of the lump and count them twice — the
    mixture would then produce more early exits than the league does, which
    is the failure mode this guard exists for rather than a tidiness rule.
    """
    if side.forced_exit_outs is not None:
        return False
    return ln.outs >= side.hook.early_exit_floor


def _end_of_inning(side: Side, rng: random.Random, inning: int,
                   margin: int) -> None:
    """The between-innings decision, starter only."""
    ln = side.cur_line
    if side.starter_out:
        # Does he come back out? Measured on 13,248 relief outings and
        # conditioned on the state he entered in — a flat give-way puts the
        # mean relief outing at 3.000 outs against a real 3.473, and burns
        # more arms per game than the league does.
        if USE_MEASURED_RELIEF_LENGTH:
            p = relief.continues(
                side.cur_entry_outs, side.cur_extra_innings,
                entry_inning=side.cur_entry_inning if USE_RELIEF_INTENT
                else None,
                entry_margin=side.cur_entry_margin)
            if rng.random() < p:
                side.cur_extra_innings += 1
                return
        side.next_arm(0, rng, inning + 1, margin)
        return
    ln.innings_completed = inning
    if inning == 5:
        ln.runs_f5, ln.outs_f5, ln.covered_f5 = ln.runs, ln.outs, True
    if USE_LEARNED_HOOK:
        # Already rolled once per plate appearance, and the model's target
        # spans the inning boundary. Rolling again here would hook the same
        # decision twice.
        return
    if (_forced_out(side, ln)
            or (_hook_may_pull(side, ln)
                and rng.random() < side.hook.removal_p(
                    ln.pitches, ln.runs, inning, ln.h + ln.bb, margin,
                    inning_runs=side.last_inning_runs,
                    pen=side.pen_state,
                    layoff_gap=side.layoff_gap))
            or ln.pitches >= side.hook.hard_pitch_cap):
        if not ln.covered_f5:
            ln.runs_f5, ln.outs_f5 = ln.runs, ln.outs
        if not side.to_bulk():
            side.next_arm(0, rng, inning + 1, margin)


@dataclass
class GameResult:
    """`away`/`home` are runs SCORED, which is what a total settles on."""
    away: int = 0
    home: int = 0
    away_f5: int = 0
    home_f5: int = 0
    #: The two starters' lines, for props.
    away_sp: sim.StartResult = field(default_factory=sim.StartResult)
    home_sp: sim.StartResult = field(default_factory=sim.StartResult)
    #: {inning: combined runs scored through it}, for the prefix ladder.
    #: Read off ONE simulated game rather than re-simulating per prefix, so
    #: F3 is genuinely the first three innings of the game F7 came from —
    #: nested prefixes are the whole basis of diagnosing by prefix.
    prefix: dict = field(default_factory=dict)
    #: {inning: (away team score, home team score)} through that inning.
    #: The combined `prefix` above is what the ladder needs; TEAM totals are
    #: the stated product in AF_PLAN and cannot be recovered from a sum.
    #: Note the crossing: a Side's `runs` are runs ALLOWED, so the away
    #: TEAM's score is what the HOME side gave up.
    prefix_side: dict = field(default_factory=dict)
    #: {batter: {"r", "rbi", "h", "tb", "hr"}} per TEAM, over the
    #: whole game and every arm that pitched. CROSSED the same way `away`
    #: and `home` are — see the assignment in `simulate_game`.
    away_bats: dict = field(default_factory=dict)
    home_bats: dict = field(default_factory=dict)
    #: Of each team's runs, how many arrived on a home run. Crossed the
    #: same way everything else here is.
    away_hr_runs: int = 0
    home_hr_runs: int = 0
    #: Each team's plate appearances. Crossed like everything else.
    away_pa: int = 0
    home_pa: int = 0

    @property
    def total(self) -> int:
        return self.away + self.home

    @property
    def total_f5(self) -> int:
        return self.away_f5 + self.home_f5


def simulate_game(away: Side, home: Side, lg: dict,
                  rng: random.Random | None = None, innings: int = 9,
                  park: dict | None = None,
                  track: tuple = (),
                  regulation: int = 9,
                  max_extra: int = 9,
                  stop_after: int | None = None,
                  hr_air: float = 1.0,
                  ump_kbb: tuple[float, float] = (1.0, 1.0)) -> GameResult:
    """One full game, both sides advancing half-inning by half-inning.

    `away` and `home` are PITCHING sides. The away side's runs allowed are
    the HOME team's score — crossing those is the obvious way to build this
    exactly backwards.

    `stop_after` ends the game after the BOTTOM of that inning and is EXACT,
    not an approximation: nothing in innings 6-9 can reach a first-five
    number, so a caller that only reads `runs_f5` gets identical answers and
    skips roughly half the work. The whole F5 objective — both `side_rps`
    and `total_rps` — is such a caller, so every fit was simulating four
    innings per draw and discarding them.

    It is deliberately NOT the same as passing `innings=5`. That would hand
    5 to the extra-innings rule and keep playing a game tied after five, and
    it would make `regulation` bite, so the home side would stop batting
    when ahead. Both change the first five. This breaks unconditionally
    after a bottom half that is always played.
    """
    rng = rng or random.Random()
    # One reading, both sides — see `Side.hr_air` and `Side.ump_kbb`.
    away.hr_air = home.hr_air = hr_air
    away.ump_kbb = home.ump_kbb = ump_kbb
    prefix: dict = {}
    prefix_side: dict = {}

    def _track(inn: int) -> None:
        """Record the prefix for an inning. CALLED ON EVERY EXIT PATH.

        IT WAS NOT, and that is a measurement bug rather than a cosmetic
        one. The block used to sit after the `break` that ends a game when
        the home side has won in its half, so the DECIDING inning was never
        recorded — `prefix[9]` was missing for roughly 40% of games and the
        notes carried a standing warning to "take 9+ as the residual".
        Found again on 2026-08-29 measuring extra innings, where it drops
        precisely the walk-off halves and therefore the highest-scoring
        ones: runs per extra half read 0.553 against a real 1.049 while the
        half-inning itself was producing a correct 0.969.
        """
        if inn in track:
            # Runs ALLOWED by both sides is runs SCORED in the game.
            prefix[inn] = away.runs + home.runs
            prefix_side[inn] = (home.runs, away.runs)

    inning = 0
    while True:
        inning += 1
        # EXTRA INNINGS. Stopping at nine omitted them entirely, which
        # cancelled against playing a bottom half that should not happen —
        # two errors that nearly agreed on the total and were both wrong.
        # About 8-9% of games go past nine.
        if inning > innings:
            if away.runs == home.runs and inning <= innings + max_extra:
                pass                      # still tied, keep playing
            else:
                break
        # TOP OF THE INNING: THE AWAY CLUB BATS, SO THE HOME SIDE PITCHES.
        # Its margin is what its own offence has put up (= runs the away
        # side has allowed) minus what it has given back.
        #
        # THESE TWO HALVES WERE THE WRONG WAY ROUND until 2026-08-29, and
        # the crossing is why it survived. A `Side` is a PITCHING side and
        # its `lineup` is "the OPPOSING nine", so the side named `away`
        # faces the HOME club — putting it first batted the home club in the
        # top of every inning. Measured rather than argued
        # (`scratchpad/whobats.py`, 300 games): the home club batted first
        # in 300 of 300, and reached the ninth in 100% of games against the
        # away club's 46.7%, where reality is away 1.000 / home 0.557.
        #
        # INNINGS 1-8 ARE UNAFFECTED, WHICH IS WHY NOTHING CAUGHT IT. The
        # skip below and the walk-off both key on `regulation`, so before
        # the ninth the two halves are symmetric and every F5 number ever
        # measured here is untouched. What it moved was the NINTH, where the
        # skip and the walk-off apply to a club — and it put both on the
        # wrong one, biasing away-club ninths down and home-club ninths up
        # by ~0.3 runs each. Those very nearly cancel in a COMBINED total,
        # which is the only place `where_runs --profile` ever looked.
        extra = inning > innings
        _half_inning(home, lg, rng, inning, away.runs - home.runs, park,
                     auto_runner=extra)
        _end_of_inning(home, rng, inning, away.runs - home.runs)

        # THE BOTTOM HALF IS NOT ALWAYS PLAYED. A home team ahead after the
        # top of the ninth does not bat, and playing it anyway invents a
        # half-inning of scoring in roughly 40% of games — straight onto the
        # full-game total. Extras follow the same rule.
        #
        # The expression is unchanged by the swap, and that is not luck:
        # `away.runs` is what the AWAY side ALLOWED, i.e. the HOME club's
        # score. It was always the right test for "is the home club ahead" —
        # it was simply being used to skip the away club's half.
        if inning >= regulation and away.runs > home.runs:
            _track(inning)
            break
        # WHAT THE PITCHING SIDE'S OWN CLUB HAS SCORED — the number the
        # batting club must PASS for a walk-off. The away side's own club is
        # the away club, whose score is what the HOME side has allowed.
        #
        # THIS WAS `home.opposing_runs = home.runs`, which set it to the
        # BATTING club's own score snapshotted at the start of the half, so
        # `side.runs > side.opposing_runs` reduced to "the batting club has
        # scored at least one run this half" — truncating every ninth and
        # every extra inning at the FIRST RUN whatever the margin. Signature
        # confirmed on 42 of 42 scoring halves (`scratchpad/walkoff.py`);
        # the condition itself was always sound, only its input was wrong.
        away.opposing_runs = home.runs
        _half_inning(away, lg, rng, inning, home.runs - away.runs, park,
                     walk_off=inning >= regulation, auto_runner=extra)
        _end_of_inning(away, rng, inning, home.runs - away.runs)

        if inning == 5:
            away.runs_f5, home.runs_f5 = away.runs, home.runs
        _track(inning)
        # AFTER `track`, or a caller asking for both gets a prefix dict
        # silently missing its last entry.
        if stop_after is not None and inning >= stop_after:
            break
        # After regulation, a decided game is over.
        if inning >= innings and away.runs != home.runs:
            break

    return GameResult(
        # Runs ALLOWED by one side are runs SCORED by the other.
        away=home.runs, home=away.runs,
        away_f5=home.runs_f5, home_f5=away.runs_f5,
        away_sp=away.line, home_sp=home.line, prefix=prefix,
        prefix_side=prefix_side,
        # CROSSED, like the runs directly above: the away TEAM's hitters are
        # the nine the HOME side pitched to.
        away_bats=home.offense(), home_bats=away.offense(),
        away_hr_runs=home.runs_on_hr, home_hr_runs=away.runs_on_hr,
        away_pa=home.pa_faced, home_pa=away.pa_faced)


def build_side(starter: sim.PitcherRates, pen_pool: list[dict],
               lineup: list[sim.BatterRates], hook: sim.Hook | None,
               rng: random.Random, depth: int = PEN_DEPTH,
               team: str | None = None, apply_leash: bool = True,
               date: str | None = None,
               bulk: sim.PitcherRates | None = None) -> Side:
    """Draw a bullpen for one club and assemble its pitching side.

    Arms are sampled WITHOUT replacement and weighted by appearances: a
    leverage reliever pitches far more often than the twelfth man, and
    drawing uniformly would hand every club a pen made mostly of its worst
    pitchers. Sampling rather than taking the top eight is deliberate — the
    game-to-game variation in WHO is available is a real source of spread in
    run scoring, and it is the spread the model is missing.

    THE PER-START HOOK IS APPLIED HERE, and until 2026-08-25 it was not
    applied anywhere in this engine at all. Every caller passes `hook=None`,
    which fell through to a bare league `Hook()`, so `sim.for_start` — the
    club and per-pitcher offsets — reached the start-level loop and never
    reached a full game. The symptom was a paired prefix ladder reading
    EXACTLY +0.0000 at all four prefixes over 1,615 games: not "the ladder
    cannot see a hook change", which is true and expected, but the flag not
    arriving. An identical-to-four-decimals A/B is a plumbing result, never
    a null.

    `apply_leash=False` is for the tuners. `calibrate.run(flat=True)` fits
    the global hook with everyone on the league curve for the same reason:
    searching global parameters while per-pitcher offsets absorb the error
    drives them somewhere meaningless.

    HOW TO CALL THIS, and every rule here exists because a caller broke it:

      * PASS `team` AND `date`. Both feed lookups that return a NEUTRAL
        VALUE when the argument is missing — `sim.pen_state` the league
        baseline, `rate_src.defence_delta` nothing at all — so an omitted
        argument does not raise, it silently switches a shipped mechanism
        off. Bullpen availability is live on both hook curves in `price.py`
        and was contributing exactly zero in `ladder`, `fitf5`, `f5_market`
        and `scratchpad/score_boundary` for that reason alone.
        `check_every_build_side_call_passes_team_and_date` enforces it.
      * APPLY THE PER-START HOOK EXACTLY ONCE. `sim.for_start` ADDS to
        `team_offset`, so a caller that pre-applies it and then leaves
        `apply_leash` at its default gets the pitcher's leash counted twice.
        Either hand over a finished hook with `apply_leash=False` — which is
        what `price.py` does, once per matchup rather than once per draw —
        or pass a bare hook and let this apply it.
    """
    # THIS FUNCTION RUNS ONCE PER SIDE PER DRAW and was 22% of a simulated
    # game, so the two wasteful things it did are worth naming.
    #
    # The weight list was rebuilt from scratch on EVERY pick — eight passes
    # over thirty dicts to draw eight arms. It is built once and popped
    # alongside the pool, which hands `rng.choices` exactly the same
    # arguments in the same order and so is bit-identical.
    pool = list(pen_pool)
    w = [max(a.get("apps") or 1, 1) for a in pool]
    arms = []
    while pool and len(arms) < depth:
        pick = rng.choices(range(len(pool)), weights=w, k=1)[0]
        a = pool.pop(pick)
        w.pop(pick)
        arms.append(_arm(a))
    h = hook or sim.Hook()
    if apply_leash:
        h = sim.for_start(h, team, starter.name)
    if sim.USE_VELO_K:
        # THE RADAR GUN, before the nightly draw: recent fastball velocity
        # vs his own season mean, counted at +0.0157 K% per mph (item E,
        # `velo.py`). STARTER only — measured on starters, and the recorded
        # error pattern is applying that to every arm. Deterministic per
        # start: consumes no randomness, so the A/B stream stays paired,
        # and it sits BEFORE `sharpen` so tonight's stuff draw is centred
        # on the velocity-adjusted base rather than under it.
        vk = velo.kick_for(starter.name, date)
        if vk:
            starter = replace(starter,
                              k_pct=min(max(starter.k_pct + vk, 0.005), 0.65))
    if sim.USE_ZONE_BB:
        # THE COMMAND CHANNEL, same discipline: recent fixed-zone share vs
        # his own season mean into tonight's walk rate, counted at -0.1431
        # BB% per share point (`velo.bb_kick_for`). It survived the
        # box-score walk drift as a control; the walk column alone did
        # not. STARTER only, deterministic, consumes no randomness.
        zk = velo.bb_kick_for(starter.name, date)
        if zk:
            starter = replace(starter,
                              bb_pct=min(max(starter.bb_pct + zk, 0.005),
                                         0.50))
    if sim.USE_START_SHARPNESS:
        # TONIGHT'S STUFF, drawn ONCE for the start and for the STARTER
        # ONLY. Counted at sigma 0.1625 on 4,777 real starts; see
        # `sim.START_K_SIGMA`. Relievers get nothing because nothing was
        # counted for them — a one-inning outing cannot separate a flat
        # slider from three bad swings, and importing the starter's number
        # would be exactly the "measured on starters, applied to every arm"
        # error that hit-by-pitch, sacrifices and wild pitches all had.
        #
        # HERE AND NOT IN THE RATES because it is a property of the NIGHT,
        # not of the pitcher: his shipped `k_pct` is the average of his
        # nightly stuff and must keep meaning that everywhere else.
        starter = sim.sharpen(starter, rng)
    d = rate_src.defence_delta(team)
    if d:
        # TONIGHT'S GLOVES, applied to the SIDE and therefore to every arm
        # that takes the mound — starter, long man, closer. Rates arrive
        # NEUTRALISED (see `rates.defence_delta`), so this is putting a
        # defence back on rather than layering a second one over the top.
        #
        # It belongs here and not in the rates because defence is a property
        # of the club in the field, not of the pitcher's history: a man
        # traded in July carries his old infield in his line and pitches in
        # front of his new one.
        starter = replace(starter, babip=max(starter.babip - d, 0.0))
        arms = [replace(a, babip=max(a.babip - d, 0.0)) for a in arms]
    if USE_ROLE_HBP:
        # THE ARM DECIDES ITS OWN. `HBP_RATE` was measured on starters and
        # applied to every pitcher, and relievers hit batters 21-34% more
        # often in every season on file. Same for sacrifices, where the gap
        # is 43% — late innings are when a run is worth bunting for.
        # Applied here rather than in `sim` because this is the only place
        # that knows which arm is the starter.
        # A RATE ALREADY SET WINS. Overwriting unconditionally makes the
        # field unusable by any caller that wants to specify one — which
        # silently clobbered a regression check's whole premise and let its
        # mutation survive.
        def _role(arm, hbp, sac):
            return replace(arm,
                           hbp_rate=(arm.hbp_rate if arm.hbp_rate is not None
                                     else hbp),
                           sac_rate=(arm.sac_rate if arm.sac_rate is not None
                                     else sac))

        starter = _role(starter, sim.HBP_RATE_SP, sim.SAC_RATE_SP)
        arms = [_role(a, sim.HBP_RATE_RP, sim.SAC_RATE_RP) for a in arms]
    # THE NIGHT TERM, last: one latent draw scaling this starter's four
    # rates for THIS simulated game — see `sim.NIGHT_SIGMA` for why it is
    # a remainder and not a fudge. After `_role` so the multiplicative
    # draw lands on the rates the game will actually use, and here rather
    # than in `sim` because this is the only place that knows which arm
    # is the starter and holds the game's own rng.
    starter = sim.night(starter, rng)
    # DRAW ORDER IS LOAD-BEARING: `night` then the early-exit roll, exactly
    # as the old constructor evaluated them, so an engine without a flagged
    # arm consumes the identical stream.
    fx = _draw_early_exit(h, rng)
    rec = opener_record(starter.name, date)
    if rec is not None:
        # THE ROLL IS DRAWN WHETHER OR NOT THE FLAGS USE IT — the same rule
        # as the mid-inning relief hook: a switch that consumes a different
        # number of random numbers is not an A/B. The bootstrap from his own
        # starts IS the exit distribution — disasters, quick hooks and the
        # odd long day all at their own frequency — and `_forced_out` /
        # `_hook_may_pull` already keep the hook off a start that carries a
        # drawn exit. The pooled no-record curve gates on its OWN flag so
        # the two mechanisms score separately.
        dist, pooled = rec
        own = dist[rng.randrange(len(dist))]
        if USE_OPENER_EXIT and (USE_OPENER_POOL or not pooled):
            fx = own
    # THE BULK ARM'S OWN HOOK, built off the SAME base as the opener's so
    # club patience is not lost, then his own leash, then the counted role
    # delta. `leash.offset_for` is the one road an outs delta travels into a
    # hook in this codebase; a hand-rolled shift here would be a second
    # conversion to keep in step with the first.
    bh = None
    if bulk is not None:
        bh = hook or sim.Hook()
        if apply_leash:
            bh = sim.for_start(bh, team, bulk.name)
        off = _leash.offset_for(BULK_OUTS_DELTA)
        bh = sim.Hook(**{**bh.__dict__,
                         "team_offset": bh.team_offset + off})
    # THE NAMED CLOSER, and he has to actually BE in the drawn pen or the
    # role cannot fire. The pen is sampled by appearances, which usually
    # catches a 60-appearance closer and does not always — and "usually" is
    # not a role. If the draw missed him he replaces the LAST arm, which is
    # the one the sampler was least confident about anyway.
    #
    # He stays an ordinary member of the pool: the role gives him the ninth,
    # it does not reserve him from the seventh, and his own record says
    # almost 30% of his work comes earlier.
    cl = None
    cl_worked = False
    got = closer_for(date, team)
    if got:
        nm, cl_worked = got
        cl = next((a for a in arms if a.name == nm), None)
        if cl is None:
            src = next((a for a in pen_pool if (a.get("name") or "") == nm),
                       None)
            if src is not None:
                cl = _arm(src)
                if d:
                    cl = replace(cl, babip=max(cl.babip - d, 0.0))
                if USE_ROLE_HBP:
                    cl = _role(cl, sim.HBP_RATE_RP, sim.SAC_RATE_RP)
                if arms:
                    arms[-1] = cl
                else:
                    arms = [cl]
    return Side(starter=starter, pen=arms, lineup=lineup,
                hook=h,
                pen_state=sim.pen_state(team, date),
                layoff_gap=sim.layoff_gap(starter.name, date),
                forced_exit_outs=fx,
                bulk=bulk, bulk_hook=bh,
                closer=cl, closer_worked=cl_worked)


#: Club-games of history behind naming the closer, matching
#: `scratchpad/closer_slot.py`: about a month, long enough to out-vote one
#: fill-in save and short enough to notice a change before it costs.
CLOSER_WINDOW = 25

#: Days idle after which the named man is treated as GONE — hurt, demoted
#: or traded. Not fitted: it is where the cliff is. Counted on the naming
#: the engine actually uses, 6,990 pre-holdout save slots —
#:
#:     idle 0-3 days   73.5% of slots   he takes the slot 45.0%
#:     idle 4-9 days   21.9% of slots                     55.6%
#:     idle 10+ days    4.5% of slots                      2.8%
#:
#: Rare and total. Stepping down to the next arm on the same usage count
#: recovers +0.8 points of naming accuracy and lands within 0.3 of a
#: perfect-forward-knowledge ORACLE (`scratchpad/closer_slot.py`), which is
#: to say it is very nearly the whole of what a news feed could buy — and
#: it needs no feed. Note 4-9 days reads HIGHER than 0-3: that is rest, not
#: staleness, and it is already carried by the availability dimension of
#: `CLOSER_USE`.
CLOSER_STALE_DAYS = 10

def _days_between(a: str, b: str) -> int:
    """Whole days from `b` to `a`, both ISO. Dates only — no clock."""
    return (datetime.date(*(int(x) for x in a.split("-")))
            - datetime.date(*(int(x) for x in b.split("-")))).days


def name_closer(tally: dict, appeared: dict, date: str) -> str | None:
    """Top of the usage count who is not STALE, or None.

    Split out from the index so THE RULE can be checked without a database,
    the way `leash.intended_from_starts` is — the rule is the part that is
    easy to get subtly wrong, and the query is not.

    `tally` is {name: ninth-inning-with-a-lead entries in the window},
    `appeared` is {name: set of dates he pitched}. Walking the count in
    order and taking the first man who has pitched inside
    `CLOSER_STALE_DAYS` is the whole gate. None means everyone on the count
    is stale — no name, no role, and the percentile profile answers, which
    is the right degradation: better no closer than a wrong one.
    """
    for cand, _ in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0])):
        ds = appeared.get(cand)
        last = max((d for d in ds if d < date), default=None) if ds else None
        if last is not None and _days_between(date, last) < CLOSER_STALE_DAYS:
            return cand
    return None


_CLOSER_INDEX: tuple | None = None


def _closer_index(conn=None) -> tuple:
    """({(date, TEAM): (name, worked the previous game)}, ...).

    Named PROSPECTIVELY — the arm with the most ninth-inning-with-a-lead
    entries over the club's previous `CLOSER_WINDOW` games, counted strictly
    BEFORE this date, so there is no leakage. Same rule `closer_slot.ranked`
    scored, which is where the 62.7% naming accuracy comes from.
    """
    global _CLOSER_INDEX
    if _CLOSER_INDEX is not None:
        return _CLOSER_INDEX
    out: dict = {}
    try:
        from src.context import store
        with store.connect() as c:
            rows = [dict(r) for r in c.execute(
                "select game_id, date, team, player_name nm,"
                " appearance_order ao, entry_inning ei, entry_margin em"
                " from mlb_stints order by date, game_id, appearance_order")]
        by_side: dict = {}
        for r in rows:
            if r["team"]:
                by_side.setdefault(
                    (r["game_id"], r["team"].upper()), []).append(r)
        appeared: dict = {}
        for r in rows:
            if r["ao"] > 0:
                appeared.setdefault(r["nm"], set()).add(r["date"])
        games: dict = {}
        for (gid, team), side in by_side.items():
            games.setdefault(team, []).append((side[0]["date"], gid, side))
        for team, gs in games.items():
            gs.sort()
            for i, (date, _gid, _side) in enumerate(gs):
                if i < CLOSER_WINDOW:
                    continue
                tally: dict = {}
                for _d, _g, ps in gs[i - CLOSER_WINDOW:i]:
                    for r in ps:
                        if (r["ao"] > 0 and r["ei"] == 9
                                and (r["em"] or 0) > 0):
                            tally[r["nm"]] = tally.get(r["nm"], 0) + 1
                if not tally:
                    continue
                prev = gs[i - 1][0]
                # THE STALE GATE. Walk the usage count in order and take the
                # first man who has actually pitched lately; ten days idle
                # means hurt, demoted or traded, and the record agrees
                # totally — he takes the slot 2.8% of the time. Without this
                # the engine keeps handing the ninth to a man who is not on
                # the team any more.
                nm = name_closer(tally, appeared, date)
                if nm is None:
                    # Everyone on the count is stale: no name, no role, and
                    # the percentile profile answers. That is the right
                    # degradation — better no closer than a wrong one.
                    continue
                out[(date, team)] = (nm, prev in appeared.get(nm, ()))
    except Exception:
        out = {}
    _CLOSER_INDEX = (out,)
    return _CLOSER_INDEX


def closer_for(date: str | None, team: str | None):
    """(name, worked the club's previous game), or None if he cannot be named.

    None covers the first `CLOSER_WINDOW` games of the record and any club
    with no ninth-inning-with-a-lead entries in the window — a committee, in
    other words. The engine then falls back to the percentile profile, which
    is the right degradation: no name, no role.
    """
    if not date or not team:
        return None
    return _closer_index()[0].get((date, (team or "").upper()))


def reload_closer_index() -> None:
    global _CLOSER_INDEX
    _CLOSER_INDEX = None


#: THE BULK ARM'S TYPE, read the way `scratchpad/bulk_type.py` counted it —
#: prospectively, off his OWN trailing appearances before this date, where a
#: REAL start is an order-0 outing of `BULK_REAL_START_OUTS` or more. That
#: definition is the point: without it a run of opener starts classifies a
#: man as a starter, and the type would be reading the very thing it is
#: supposed to predict. Window matches `OPENER_ROLE_WINDOW` so the two role
#: reads see the same span.
BULK_ROLE_WINDOW = 30
BULK_REAL_START_OUTS = 12
BULK_MIN_HISTORY = 5
BULK_STARTER_SHARE = 0.5

_BULK_INDEX: tuple | None = None


def _bulk_index(conn=None) -> tuple:
    """({(date, TEAM): follower name}, {name: [(date, was a real start)]}).

    Both off `mlb_stints`, one pass, cached for the process the same way
    `_opener_starts` is.
    """
    global _BULK_INDEX
    if _BULK_INDEX is not None:
        return _BULK_INDEX

    def _run(c):
        rows = [dict(r) for r in c.execute(
            "select game_id, date, team, player_name nm, appearance_order ao,"
            " outs_recorded o from mlb_stints"
            " order by date, game_id, appearance_order")]
        log: dict = {}
        first: dict = {}
        for r in rows:
            log.setdefault(r["nm"], []).append(
                (r["date"], r["ao"] == 0 and (r["o"] or 0)
                 >= BULK_REAL_START_OUTS))
            if r["ao"] == 1:
                key = (r["date"], (r["team"] or "").upper())
                first.setdefault(key, r["nm"])
        return first, log
    # A MISSING TABLE MEANS "NO BULK ARM", NOT A CRASH. `mlb_stints` is
    # derived from the play-by-play cache and a fresh checkout may not have
    # built it — the same degradation `_opener_roles` takes, and for the
    # same reason: a silently weaker gate beats a raise inside `build_side`.
    try:
        if conn is not None:
            _BULK_INDEX = _run(conn)
        else:
            from src.context import store
            with store.connect() as c:
                _BULK_INDEX = _run(c)
    except Exception:
        _BULK_INDEX = ({}, {})
    return _BULK_INDEX


def bulk_follower(date: str | None, team: str | None) -> str | None:
    """The named bulk arm behind tonight's opener, or None.

    None means "go to the pen" and covers the pure bullpen game, which is
    48.5% of planned openers — the majority case, and the one the existing
    relief machinery already handles.

    NOT A PREDICTION. For a game that has been played this is the recorded
    follower; live it is the announced pairing off the slate. Step zero
    killed predicting WHO follows from history, and this does not attempt
    it: the name is an input, and only his TYPE is read from his record.
    """
    if not date or not team:
        return None
    first, log = _bulk_index()
    nm = first.get((date, (team or "").upper()))
    if not nm:
        return None
    w = [s for d, s in log.get(nm, []) if d < date][-BULK_ROLE_WINDOW:]
    if len(w) < BULK_MIN_HISTORY:
        return None
    n = sum(w)
    # `n < 2` is a reliever outright: one real start in thirty appearances
    # is a spot start, not a role.
    if n < 2 or n / len(w) < BULK_STARTER_SHARE:
        return None
    return nm


def reload_bulk_index() -> None:
    """Drop the cache — the tests rebuild `mlb_stints` under it."""
    global _BULK_INDEX
    _BULK_INDEX = None


_OPENER_STARTS: dict | None = None


def _opener_starts(conn=None) -> dict:
    """{pitcher_name: sorted [(date, outs)]} for every recorded start.

    Cached in-process like `sim._start_dates`, and keyed by name for the
    same recorded reason: `mlb_pitching` carries no pitcher id, and both
    sides of every lookup are populated from the same statsapi payload.
    """
    global _OPENER_STARTS
    if _OPENER_STARTS is not None:
        return _OPENER_STARTS
    from src import db
    q = """
      select p.player_name nm, g.date d, p.outs_recorded o
      from mlb_pitching p join games g on g.game_id = p.game_id
      where g.sport = 'mlb' and g.status = 'Final' and p.is_starter = 1
    """

    def _run(c):
        out: dict = {}
        for r in c.execute(q):
            out.setdefault(r["nm"], []).append((r["d"], r["o"] or 0))
        return out
    if conn is not None:
        out = _run(conn)
    else:
        with db.connect() as c:
            out = _run(c)
    _OPENER_STARTS = {k: sorted(v) for k, v in out.items()}
    return _OPENER_STARTS


def reload_opener_starts() -> None:
    """Drop the cached indexes so a backfill is picked up in-process."""
    global _OPENER_STARTS, _OPENER_ROLES
    _OPENER_STARTS = None
    _OPENER_ROLES = None


_OPENER_ROLES: dict | None = None
_OPENER_POOL: list | None = None


def _opener_roles() -> dict:
    """{pitcher_name: (sorted dates, [(is_start, entry_inning)])} from
    `mlb_stints` — the appearance log the role is read off.

    An unreachable context.db or an absent table yields an EMPTY index,
    never an error: role classification then finds nobody and the engine
    is bit-for-bit the pre-fallback engine. The stints table is derived
    from the play-by-play cache and a fresh checkout may not have built
    it; a silently weaker gate is the correct degradation, a crash in
    `build_side` is not.
    """
    global _OPENER_ROLES
    if _OPENER_ROLES is not None:
        return _OPENER_ROLES
    out: dict = {}
    try:
        from src.context import store
        with store.connect() as c:
            rows = c.execute(
                "select player_name nm, date d, appearance_order ao,"
                " entry_inning ei from mlb_stints order by date").fetchall()
        for r in rows:
            ds, apps = out.setdefault(r["nm"], ([], []))
            ds.append(r["d"])
            apps.append((r["ao"] == 0, r["ei"] or 9))
    except Exception:
        out = {}
    _OPENER_ROLES = out
    return out


def _role_is_opener(name: str, date: str) -> bool:
    """Is this arm's CURRENT role late-inning relief? See the constants."""
    rec = _opener_roles().get(name)
    if not rec:
        return False
    ds, apps = rec
    hi = bisect.bisect_left(ds, date)
    w = apps[max(0, hi - OPENER_ROLE_WINDOW):hi]
    rel = [ei for st, ei in w if not st]
    if len(rel) < OPENER_ROLE_MIN_RELIEF or not w:
        return False
    if len(rel) / len(w) < OPENER_ROLE_RELIEF_SHARE:
        return False
    early = sum(1 for e in rel if e <= 3) / len(rel)
    return early <= OPENER_ROLE_EARLY_SHARE


def opener_record(name: str | None,
                  date: str | None) -> tuple[list[int], bool] | None:
    """(outs to bootstrap from, is_pooled) — or None for an ordinary arm.

    The list is his own starts before `date` when the short-record gate
    fires, or the pooled no-record curve when only his relief usage
    identifies him; `is_pooled` says which, so `build_side` can gate the
    two applications on their own flags while consuming the same draw.
    None switches the mechanism off entirely — the same missing-group
    rule as `pen_state`, `leash` and `layoff_gap`. The evidence is
    bounded by the GAME's date, which is what the live path knows the
    morning of and contains nothing from the game being simulated.
    """
    if not name or not date:
        return None
    rows = _opener_starts().get(name)
    prior = [(d, o) for d, o in rows if d < date] if rows else []
    outs = [o for _, o in prior]
    if len(outs) < OPENER_MIN_STARTS:
        # No usable start record — his RELIEF USAGE can still identify a
        # first-time opener, and gets him the pooled curve counted on
        # exactly this population. See `OPENER_POOL_DIST`.
        if _role_is_opener(name, date):
            global _OPENER_POOL
            if _OPENER_POOL is None:
                _OPENER_POOL = [o for o, n in sorted(OPENER_POOL_DIST.items())
                                for _ in range(n)]
            return (_OPENER_POOL, True) if _OPENER_POOL else None
        return None
    if _record_mean(prior, date) >= OPENER_AVG_OUTS:
        return None
    return outs, False


def _record_mean(prior: list[tuple[str, int]], date: str) -> float:
    """His outs a start, recent starts counting for more.

    The BOOTSTRAP SUPPORT is deliberately left flat — every start he has
    made stays in the list the exit is drawn from, and only the gate's
    threshold sees the weights. See `USE_OPENER_DECAY` for why the two are
    separated.
    """
    if not USE_OPENER_DECAY:
        return sum(o for _, o in prior) / len(prior)
    num = den = 0.0
    for d, o in prior:
        w = 0.5 ** (_days_between(date, d) / OPENER_HALF_LIFE_DAYS)
        num += w * o
        den += w
    # A club that has not played in years cannot underflow to a divide by
    # zero: fall through to the flat mean rather than invent a level.
    return num / den if den > 0 else sum(o for _, o in prior) / len(prior)


def _days_between(a: str, b: str) -> int:
    ya, ma, da = (int(x) for x in a.split("-"))
    yb, mb, dbb = (int(x) for x in b.split("-"))
    return (datetime.date(ya, ma, da) - datetime.date(yb, mb, dbb)).days


def _draw_early_exit(h: sim.Hook, rng: random.Random) -> int | None:
    """Is this start one of the ones that falls apart, and how short?

    Drawn HERE, before a pitch, because it is a mode of the start rather
    than a decision inside it — the point of the mixture is to take the
    unpredictable short starts out of the length estimate, not to model
    them. The outs total is sampled from what actually happens rather than
    from any curve.
    """
    if not h.early_exit_p or rng.random() >= h.early_exit_p:
        return None
    outs = list(sim.EARLY_EXIT_DIST)
    if not outs:
        return None
    return rng.choices(outs, weights=[sim.EARLY_EXIT_DIST[o]
                                      for o in outs], k=1)[0]


#: Let each arm carry its own hit-by-pitch and sacrifice rate instead of
#: the flat league constant. OFF restores the previous behaviour exactly,
#: so the correction stays separately scoreable like every other mechanism
#: here.
USE_ROLE_HBP = True


def _arm(row: dict) -> sim.PitcherRates:
    """The `PitcherRates` for one bullpen row, built once and remembered.

    The rows come from `sources.rates.bullpens`, which is called ONCE and
    then handed to every draw — so the same thirty dicts were being turned
    into fresh `PitcherRates` objects thousands of times over.

    Cached ON THE ROW rather than in a module dict keyed by name, because
    two clubs can carry the same name and a global cache would need
    invalidating whenever rates are recomputed for a different cutoff. The
    row IS the cutoff-specific object, so its lifetime is exactly right.

    Safe to share the result between sides and draws: nothing in the engine
    mutates a `PitcherRates`. `sim._jitter_pitcher` used to, and it was
    deleted with the one-sided engine.
    """
    r = row.get("_rates")
    if r is None:
        # The throwing hand feeds the platoon cell. Ambiguous or unknown
        # names resolve to "" and the cell stays neutral for that arm —
        # never a guessed hand, which would flip a batter's cell in a
        # definite wrong direction.
        from src import roster
        r = row["_rates"] = sim.PitcherRates(
            name=row["name"], k_pct=row["k_pct"], bb_pct=row["bb_pct"],
            hr_pct=row["hr_pct"], babip=row["babip"], pa=row.get("pa", 0),
            hand=roster.throws(row["name"]) or "",
            gb_pct=row.get("gb_pct"))
    return r
