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

import random
from dataclasses import dataclass, field, replace

from src.context import relief, removal, sim
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
    #: The starter's own line, so props and F5 still read off one pitcher.
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
                         (ln.rbi_by, self.bat_rbi)):
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
        """{batter name: {"r": runs, "rbi": runs driven in}}, whole game.

        NON-MUTATING, and that is the point: it merges what has been folded
        with the arm currently on the mound, so it is correct whenever it is
        called and calling it twice cannot double count. A fold-on-read
        would be one forgotten copy away from exactly that.
        """
        out: dict = {}
        live = self.cur_line
        for tag, folded, now in (("r", self.bat_scored, live.scored_by),
                                 ("rbi", self.bat_rbi, live.rbi_by)):
            for src in (folded, now):
                for who, n in src.items():
                    out.setdefault(who, {"r": 0, "rbi": 0})[tag] += n
        return out

    @property
    def current(self) -> sim.PitcherRates:
        if not self.starter_out:
            return self.starter
        if not self.pen:
            return self.starter
        return self.pen[min(self.pen_i, len(self.pen) - 1)]

    def next_arm(self, entry_outs: int = 0) -> None:
        """Go to the pen, or to the next arm in it.

        `entry_outs` is the base-out state the incoming arm walks into, and
        it is the strongest predictor of how long he stays — 20% of arms
        handed a clean inning come back out, against 63% of those brought in
        with two down.
        """
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
        tto = None if side.starter_out else side.line.batters // 9 + 1
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
                side.lineup[slot], side.current, lg, park)
        # THE FIELD STATE the hitter actually walks into. `fr.bases`
        # holds runner tokens, so truthiness is the occupancy count.
        o = sim.pa_from(mu, rng, tto=tto,
                        state=(sum(1 for b in fr.bases if b), outs_before))

        before = side.cur_line.runs
        sim.apply_pa(o, side.cur_line, fr, rng,
                     batter=side.lineup[slot].name)
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
                    and roll < relief.mid_removal(rl.runs, rl.batters)):
                side.next_arm(fr.outs)
        elif not side.starter_out and USE_LEARNED_HOOK:
            if rng.random() < removal.predict(
                    _state(side, fr, inning, margin)):
                ln = side.line
                ln.pulled_mid_inning = True
                ln.left_on_base, ln.outs_when_pulled = fr.on_base, fr.outs
                if not ln.covered_f5:
                    ln.runs_f5, ln.outs_f5 = ln.runs, ln.outs
                side.next_arm(fr.outs)
        elif not side.starter_out:
            ln = side.line
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
                side.next_arm(fr.outs)

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
    ln = side.line
    # He finished the inning, so nothing is inherited and no runner is left
    # behind — the distinction the mid-inning path exists to carry.
    if not ln.covered_f5:
        ln.runs_f5, ln.outs_f5 = ln.runs, ln.outs
    side.next_arm(0)


def _state(side: "Side", fr, inning: int, margin: int) -> dict:
    """What the manager can see, in the learned model's feature names."""
    ln = side.line
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
    ln = side.line
    if side.starter_out:
        # Does he come back out? Measured on 13,248 relief outings and
        # conditioned on the state he entered in — a flat give-way puts the
        # mean relief outing at 3.000 outs against a real 3.473, and burns
        # more arms per game than the league does.
        if USE_MEASURED_RELIEF_LENGTH:
            p = relief.continues(side.cur_entry_outs, side.cur_extra_innings)
            if rng.random() < p:
                side.cur_extra_innings += 1
                return
        side.next_arm()
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
        side.next_arm()


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
    #: {batter name: {"r": runs, "rbi": runs driven in}} per TEAM, over the
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
                  stop_after: int | None = None) -> GameResult:
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
               date: str | None = None) -> Side:
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
    return Side(starter=starter, pen=arms, lineup=lineup, hook=h,
                pen_state=sim.pen_state(team, date),
                layoff_gap=sim.layoff_gap(starter.name, date),
                forced_exit_outs=_draw_early_exit(h, rng))


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
        r = row["_rates"] = sim.PitcherRates(
            name=row["name"], k_pct=row["k_pct"], bb_pct=row["bb_pct"],
            hr_pct=row["hr_pct"], babip=row["babip"], pa=row.get("pa", 0))
    return r
