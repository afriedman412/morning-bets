"""Is he throwing well TONIGHT? The within-game state the model never had.

Every plate appearance in this simulator is drawn from the same season rates
plus a deterministic TTO multiplier. There is no way for a pitcher to be
worse than his own baseline on a given evening, and that absence is why the
whole removal branch measured flat three separate ways: in the model,
pulling a starter swaps an average starter for an average reliever, which is
worth nothing (K-BB 0.1358 against 0.1333). In reality a manager pulls a
starter who has stopped being himself, and THAT swap is an upgrade.

MEASURED, and the result is sharper than expected. Over 3,476 starts and 261
pitchers, everything residualised against the pitcher's own season mean so
it cannot be measuring who is good:

    pass-1 DAMAGE  -> pass-2 runs                     r = +0.0565
    pass-1 RUNS    -> pass-2 runs                     r = +0.0078
    pass-1 damage, RUNS PARTIALLED OUT -> pass-2 runs r = +0.0814  (4.7 sigma)

Two things follow and both matter.

RUNS ALLOWED PREDICT ALMOST NOTHING. r = +0.008 for the next pass. And runs
are what `Hook.removal_p` and `Hook.mid_removal_p` key on, so the removal
rule is built on the least informative signal available to it.

THE INFORMATIVE PART IS THE CONTACT THAT DID NOT SCORE. Partialling runs out
makes the correlation BIGGER, +0.0565 -> +0.0814. A pitcher being squared up
without paying for it yet is the one in trouble, and the runs column hides
exactly that.

In runs, which is what decides whether this is worth having: a one-sd bad
first pass costs +0.096 runs over the next nine batters, and the
10th-to-90th-percentile spread is 0.250 runs. The leverage screen's
build/no-build bar is 0.05.

WHAT THIS IS NOT. It is not a fitted correction against the settlement
value; the slope is counted from play-by-play and there is no loss function
behind it. It is also not a claim that hard contact CAUSES later runs —
tired arms, bad command and a hitter-friendly night all produce the same
signature. The model only needs the association to hold, which it does.
"""
from __future__ import annotations

from src.context import sim

#: Run value of each plate-appearance outcome, for accumulating damage. The
#: same shape as `sim.DAMAGE`, kept separate because that table is consumed
#: by the hook's inning-local term and this one is cumulative over a start.
DAMAGE = {sim.K: 0.0, sim.OUT: 0.0, sim.SAC: 0.0, sim.BB: 1.0, sim.HBP: 1.0,
          sim.B1: 1.0, sim.B2: 1.7, sim.B3: 2.3, sim.HR: 3.0, sim.ROE: 0.5}

#: Runs per batter, per unit of damage-per-batter above a pitcher's own
#: baseline. Counted, not fitted: the slope of next-pass runs on this-pass
#: damage residual, with runs already allowed partialled out.
SLOPE = 0.0786

#: Spread of the damage residual across starts, per batter. Used to clamp:
#: beyond about three sd the relationship is extrapolation off the end of
#: the measured range and a blowout would otherwise send the rates somewhere
#: the data never went.
RESIDUAL_SD = 0.1359
CLAMP_SD = 3.0

#: Batters the slope was MEASURED over — one time through the order. A
#: residual taken over fewer men is the same signal buried in more noise, so
#: applying the full slope to it over-reacts: six loud batters would imply
#: 0.288 runs over the next nine, larger than the entire measured
#: 10th-to-90th spread of 0.250. Scale down below the measured window and
#: never above it, since the slope was fitted with that much noise in the
#: predictor and a cleaner estimate does not license a bigger coefficient.
MEASURED_OVER = 9

#: Expected damage per batter for a league-average starter, which is the
#: baseline a start is measured against when the pitcher's own is unknown.
#: Derived from the league rate table rather than stored, so it moves when
#: the league does.
def league_damage(lg: dict) -> float:
    """Expected damage per plate appearance at league-average rates."""
    k, bb, hr = lg["k_pct"], lg["bb_pct"], lg["hr_pct"]
    bip = max(1.0 - k - bb - hr, 0.0)
    hits = bip * lg["babip"]
    # Hits split by the league mix; the rest of the balls in play are outs.
    mix = lg.get("hit_mix") or {"1b": 0.70, "2b": 0.22, "3b": 0.02}
    return (bb * DAMAGE[sim.BB] + hr * DAMAGE[sim.HR]
            + hits * (mix["1b"] * DAMAGE[sim.B1]
                      + mix["2b"] * DAMAGE[sim.B2]
                      + mix.get("3b", 0.02) * DAMAGE[sim.B3]))


#: Off restores a pitcher who is the same all night. That is the state in
#: which the hook measured flat three ways.
USE_FORM = True


class Form:
    """Running damage for one pitcher in one game.

    `penalty()` is the extra runs per batter his current form implies, which
    the caller turns into a rate adjustment. Nothing here mutates the
    pitcher — a `PitcherRates` is shared across simulated games and writing
    to it would leak one draw's bad night into the next.
    """

    __slots__ = ("damage", "batters", "baseline")

    def __init__(self, baseline: float):
        self.damage = 0.0
        self.batters = 0
        self.baseline = baseline

    def record(self, outcome: str) -> None:
        self.damage += DAMAGE.get(outcome, 0.0)
        self.batters += 1

    def residual(self) -> float:
        """Damage per batter above this pitcher's expected rate.

        Zero until he has faced enough men to mean anything. One batter of
        damage is a home run or nothing, and letting that move the rates
        would make the first plate appearance of a game the loudest signal
        in it.
        """
        if self.batters < 6:
            return 0.0
        r = self.damage / self.batters - self.baseline
        lim = CLAMP_SD * RESIDUAL_SD
        return max(-lim, min(lim, r))

    def confidence(self) -> float:
        """How much of the slope this many batters supports. See
        `MEASURED_OVER`."""
        return min(1.0, self.batters / MEASURED_OVER)

    def penalty(self) -> float:
        """Extra runs per batter implied by how he is throwing tonight."""
        if not USE_FORM:
            return 0.0
        return SLOPE * self.residual() * self.confidence()
