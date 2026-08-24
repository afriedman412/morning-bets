"""A whole game, both sides, nine innings — the thing that was missing.

WHAT DID NOT EXIST BEFORE THIS. `sim.simulate_start` models ONE PITCHER and
returns the moment the hook fires. Innings after the pull were never
simulated at all, so a full team total could not be produced: the project
had pitcher props, it had first-five via a stub, and it had no game.

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

THE BULLPEN IS SAMPLED, NOT AVERAGED. `f5.relief_rates()` collapses 374
relief arms into one set of rates. That is a defensible stub for first-five,
where relief appears about a quarter of the time and usually for under an
inning; it is badly wrong across a full game, where the bullpen throws
roughly 40% of the innings EVERY time. The measured defect in the run
distribution is that it is COMPRESSED — too many shutouts and too few
crooked numbers at once — and a league-average arm every night is precisely
how that happens. The real arms span K% 0.165 to 0.304 with sd 0.037, and
that spread was being computed and thrown away.

INHERITED RUNNERS ARE NO LONGER A FUDGE. `f5._side_runs` credits a departing
starter's stranded runners at a flat `INHERITED_SCORE_RATE` of 0.33 because
it never simulates the reliever finishing the inning. This does simulate
him, so those runners score or do not score for the reasons they actually
would — the base-out state is handed over intact.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from src.context import sim

#: How many relief arms a club is assumed to have available. Real bullpens
#: carry 8, and a nine-inning game essentially never needs more than four
#: after a starter, so this only bites in a disaster.
PEN_DEPTH = 8


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
    #: The starter's own line, so props and F5 still read off one pitcher.
    line: sim.StartResult = field(default_factory=sim.StartResult)
    #: Whoever is on now, and his line (the starter's IS `line`).
    cur_line: sim.StartResult | None = None
    runs_f5: int = 0

    def __post_init__(self):
        if self.cur_line is None:
            self.cur_line = self.line

    @property
    def current(self) -> sim.PitcherRates:
        if not self.starter_out:
            return self.starter
        if not self.pen:
            return self.starter
        return self.pen[min(self.pen_i, len(self.pen) - 1)]

    def next_arm(self) -> None:
        """Go to the pen, or to the next arm in it."""
        if not self.starter_out:
            self.starter_out = True
        else:
            self.pen_i += 1
        self.cur_line = sim.StartResult()


def _half_inning(side: Side, lg: dict, rng: random.Random, inning: int,
                 margin: int, park: dict | None,
                 walk_off: bool = False) -> None:
    """One half-inning. `margin` is this pitching side's lead, in runs.

    Runs are counted from the CHANGE in the current pitcher's line rather
    than recomputed, so the side total and the individual lines can never
    disagree — and both come from `sim.apply_pa`, which is the single copy
    of the base-out state machine.
    """
    fr = sim.Frame()
    while fr.outs < 3:
        b = side.lineup[side.idx % len(side.lineup)]
        side.idx += 1
        o = sim.pa_outcome(b, side.current, lg, rng, 1.0, park)

        before = side.cur_line.runs
        sim.apply_pa(o, side.cur_line, fr, rng)
        side.runs += side.cur_line.runs - before
        if fr.outs >= 3:
            break

        before = side.cur_line.runs
        sim.baserunning(side.cur_line, fr, rng)
        side.runs += side.cur_line.runs - before
        if fr.outs >= 3:
            break
        # A walk-off ends the game mid-inning. `walk_off` is only ever set
        # for the bottom of the ninth or later, and `side` here is the
        # PITCHING side, so its runs allowed ARE the home team's score.
        if walk_off and side.runs > side.opposing_runs:
            return

        # Mid-inning removal, starter only. A reliever who has just come in
        # to face this rally is not pulled again in the same breath, which
        # is both realistic and what keeps the pen from being burned in one
        # inning.
        if not side.starter_out:
            ln = side.line
            if (rng.random() < side.hook.mid_removal_p(
                    ln.pitches, ln.runs, fr.on_base, fr.damage, margin)
                    or ln.pitches >= side.hook.hard_pitch_cap):
                ln.pulled_mid_inning = True
                ln.left_on_base, ln.outs_when_pulled = fr.on_base, fr.outs
                if not ln.covered_f5:
                    ln.runs_f5, ln.outs_f5 = ln.runs, ln.outs
                # The reliever inherits the bases and the outs exactly as
                # they stand. Those runners now score, or do not, for the
                # reasons they actually would — no INHERITED_SCORE_RATE.
                side.next_arm()


def _end_of_inning(side: Side, rng: random.Random, inning: int,
                   margin: int) -> None:
    """The between-innings decision, starter only."""
    ln = side.line
    if side.starter_out:
        # A reliever gets the inning he entered and then gives way, which is
        # how a modern bullpen is actually used.
        side.next_arm()
        return
    ln.innings_completed = inning
    if inning == 5:
        ln.runs_f5, ln.outs_f5, ln.covered_f5 = ln.runs, ln.outs, True
    if (rng.random() < side.hook.removal_p(
            ln.pitches, ln.runs, inning, ln.h + ln.bb, margin)
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
                  max_extra: int = 9) -> GameResult:
    """One full game, both sides advancing half-inning by half-inning.

    `away` and `home` are PITCHING sides. The away side's runs allowed are
    the HOME team's score — crossing those is the obvious way to build this
    exactly backwards.
    """
    rng = rng or random.Random()
    prefix: dict = {}
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
        # Top: away pitches. Its margin is what its own offence has put up
        # (= runs the home side has allowed) minus what it has given back.
        _half_inning(away, lg, rng, inning, home.runs - away.runs, park)
        _end_of_inning(away, rng, inning, home.runs - away.runs)

        # THE BOTTOM HALF IS NOT ALWAYS PLAYED. A home team ahead after the
        # top of the ninth does not bat, and playing it anyway invents a
        # half-inning of scoring in roughly 40% of games — straight onto the
        # full-game total. Extras follow the same rule.
        if inning >= regulation and away.runs > home.runs:
            break
        home.opposing_runs = home.runs      # this team's own score
        _half_inning(home, lg, rng, inning, away.runs - home.runs, park,
                     walk_off=inning >= regulation)
        _end_of_inning(home, rng, inning, away.runs - home.runs)

        if inning == 5:
            away.runs_f5, home.runs_f5 = away.runs, home.runs
        if inning in track:
            # Runs ALLOWED by both sides is runs SCORED in the game.
            prefix[inning] = away.runs + home.runs
        # After regulation, a decided game is over.
        if inning >= innings and away.runs != home.runs:
            break

    return GameResult(
        # Runs ALLOWED by one side are runs SCORED by the other.
        away=home.runs, home=away.runs,
        away_f5=home.runs_f5, home_f5=away.runs_f5,
        away_sp=away.line, home_sp=home.line, prefix=prefix)


def build_side(starter: sim.PitcherRates, pen_pool: list[dict],
               lineup: list[sim.BatterRates], hook: sim.Hook | None,
               rng: random.Random, depth: int = PEN_DEPTH) -> Side:
    """Draw a bullpen for one club and assemble its pitching side.

    Arms are sampled WITHOUT replacement and weighted by appearances: a
    leverage reliever pitches far more often than the twelfth man, and
    drawing uniformly would hand every club a pen made mostly of its worst
    pitchers. Sampling rather than taking the top eight is deliberate — the
    game-to-game variation in WHO is available is a real source of spread in
    run scoring, and it is the spread the model is missing.
    """
    pool = list(pen_pool)
    arms = []
    while pool and len(arms) < depth:
        w = [max(a.get("apps") or 1, 1) for a in pool]
        pick = rng.choices(range(len(pool)), weights=w, k=1)[0]
        a = pool.pop(pick)
        arms.append(sim.PitcherRates(
            name=a["name"], k_pct=a["k_pct"], bb_pct=a["bb_pct"],
            hr_pct=a["hr_pct"], babip=a["babip"], pa=a.get("pa", 0)))
    return Side(starter=starter, pen=arms, lineup=lineup,
                hook=hook or sim.Hook())
