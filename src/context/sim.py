"""Simulate a start plate appearance by plate appearance.

WHY THIS EXISTS. The estimator this replaces counts how many of a pitcher's
last six starts would have won a bet and shrinks that toward the market. Six
observations cannot distinguish a 50% line from a 65% one — measured power
at alpha 0.05 is 8% — so every disagreement it reports is either enormous or
noise, and no threshold rule fixes that. The information is not in the
sample. A simulation gets its numbers from the pitcher's ~600 plate
appearances, each batter's ~500, and the specific nine he faces tonight,
which the count-the-starts approach ignores entirely.

WHAT IT DOES NOT FIX. Sampling noise goes away; model error does not, and
model error is correlated — a hook that fires eight pitches late is wrong
the same way at every start on the board, and no amount of resampling
reveals it. That is what `calibrate.py` is for, and why the first validation
is against the league's own distribution rather than against any bet.

THE HOOK IS THE MODEL. Outs are mostly a manager decision. Two starters with
identical stuff go 15 and 21 because of pitch count, score and bullpen, and
the local record says so plainly: 66% of starts end on an inning boundary,
444 of 2,010 end at exactly 18 outs against 54 at 19. So the removal rule
carries more weight here than the pitching does, and it is the part most
worth distrusting.

WHAT IS FITTED AND WHAT IS GUESSED. League rates, the hit-type mix and BABIP
are computed from the local boxscore cache — real numbers, no invention.
The hook parameters and the pitch-cost constants are parametric forms tuned
to reproduce observed marginals, which is weaker than fitting them to game
state and is the specific thing play-by-play would buy later. Nothing here
needs the network.
"""
from __future__ import annotations

import contextlib
import math
import random
from dataclasses import dataclass, field, replace

from src import db
from src.context import scope

# ── league baselines, from the local boxscore cache ────────────────────
#
# Recomputed per season rather than hardcoded. A constant copied from a
# baseball-reference page in one run environment and a different season is
# exactly the kind of invented number this project keeps finding in its own
# code, and these cost one query.

_LEAGUE_CACHE: dict[tuple, dict] = {}

_PITCHING_Q = """
select sum(outs_recorded) o, sum(h) h, sum(bb) bb, sum(k) k, sum(hr) hr,
       sum(r) r
from mlb_pitching p join games g on g.game_id = p.game_id
where g.sport = 'mlb' and g.status = 'Final' {where}
"""

_BATTING_Q = """
select sum(ab) ab, sum(bb) bb, sum(h) h, sum(so) so, sum(hr) hr,
       sum("2b") d, sum("3b") t
from mlb_batting mb join games g on g.game_id = mb.game_id
where g.sport = 'mlb' and g.status = 'Final' {where}
"""


_SP_Q = """
select sum(p.outs_recorded) o, sum(p.h) h, sum(p.bb) bb, sum(p.k) k,
       sum(p.hr) hr
from mlb_pitching p join games g on g.game_id = p.game_id
where g.sport = 'mlb' and g.status = 'Final' and p.is_starter = 1 {where}
  and p.player_name in (
      select p2.player_name from mlb_pitching p2
      join games g2 on g2.game_id = p2.game_id
      where p2.is_starter is not null {season_where}
      group by p2.player_name
      having sum(case when p2.is_starter = 1 then 1 else 0 end) >= 5)
"""


def _starter_league(conn=None, before: str | None = None,
                    season=None) -> dict | None:
    """Rate baselines from ROTATION STARTERS, per batter faced.

    The population the simulator simulates. Openers are excluded on the
    same 5-start bar `calibrate.ROTATION_MIN_GS` uses.

    SEASON-SCOPED IN BOTH PLACES, and it took loading 2025 to notice it was
    scoped in neither. These three rates — k_pct, bb_pct, hr_pct — OVERWRITE
    the batting-side figures in `league()`, so an unscoped baseline here
    pools two seasons into the anchor every simulated rate is log5'd
    against. It showed up as `pa` and `runs_per_9` identical while K, BB and
    HR all moved, which is only possible if the two came from different
    queries.
    """
    season = scope.resolve(season)
    where = f"and g.date like '{season}%'" if season else ""
    if before:
        where += f" and g.date < '{before}'"

    def _run(c):
        return c.execute(_SP_Q.format(
            where=where,
            season_where=(f"and g2.date like '{season}%'" if season else ""))
        ).fetchone()
    if conn is not None:
        r = _run(conn)
    else:
        with db.connect() as c:
            r = _run(c)
    if not r or not r["o"]:
        return None
    bf = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
    # Balls in play, not OUTS — see `rates.BIP_PER_OUT_UNIT`. The anchor and
    # the pitcher rates have to use one denominator or log5 resolves a rate
    # against a differently-measured league.
    from src.context.sources import rates as _rt
    bip = _rt.balls_in_play(bf, r["k"], r["bb"], r["hr"])
    return {
        "k_pct": (r["k"] or 0) / bf,
        "bb_pct": (r["bb"] or 0) / bf,
        "hr_pct": (r["hr"] or 0) / bf,
        "babip": (((r["h"] or 0) - (r["hr"] or 0)) / bip) if bip > 0 else 0.294,
    }


def league(season: int | None = None, conn=None,
           before: str | None = None) -> dict:
    """Season-to-date league rates for the simulator.

    The batting-side figures are computed first, per AB + BB, and are then
    OVERWRITTEN by `_starter_league` — rotation starters, per batter faced.
    They survive only as the denominator for `batter_scale`, which is what
    converts hitters onto the same footing.

    An earlier version of this docstring argued that the AB + BB
    approximation was harmless because "a common factor largely divides out"
    of the log5 ratio. That was wrong and it cost a day: the factor is only
    common if both sides share a denominator, and the pitcher rates never
    did. It inflated simulated walks by 6-8%.

    So do not read `k_pct` here as a published statistic, and do not assume
    it describes all pitchers — it describes rotation starters, which is the
    only population this module ever simulates.
    """
    # KEYED ON `before` TOO. Keying on season alone meant the first caller
    # decided the baselines for the whole process, so a train-only fit that
    # ran after any full-season call silently got full-season numbers.
    key = (season, before)
    if key in _LEAGUE_CACHE:
        return _LEAGUE_CACHE[key]

    # None means THIS SEASON — `context.scope`. League baselines are the
    # clearest case for scoping: the ball is not the same year to year.
    #
    # THE RAW ARGUMENT IS KEPT because `resolve` is NOT idempotent: None
    # means "unspecified" on the way in and "every season" on the way out,
    # so resolving an already-resolved value turns ALL_SEASONS back into the
    # current one. That bug shipped for ten minutes and presented as a
    # pooled `pa` of 222,533 sitting next to pure-2026 rates.
    raw_season = season
    season = scope.resolve(season)
    where = f"and g.date like '{season}%'" if season else ""
    if before:
        # Strictly before, so a train-window fit is anchored to numbers that
        # have not seen the test window. Train starters walk 0.0823 per
        # batter faced against a full-season 0.0812 — small, and exactly the
        # kind of leak that makes an out-of-sample test quietly in-sample.
        where += f" and g.date < '{before}'"

    def _run(c):
        p = c.execute(_PITCHING_Q.format(where=where)).fetchone()
        b = c.execute(_BATTING_Q.format(where=where)).fetchone()
        return p, b

    if conn is not None:
        p, b = _run(conn)
    else:
        with db.connect() as c:
            p, b = _run(c)

    pa = (b["ab"] or 0) + (b["bb"] or 0)
    if not pa:
        raise ValueError(f"no batting rows for season {season}")
    hits = b["h"] or 0
    singles = hits - (b["d"] or 0) - (b["t"] or 0) - (b["hr"] or 0)
    bip = (b["ab"] or 0) - (b["so"] or 0) - (b["hr"] or 0)

    out = {
        "season": season,
        "pa": pa,
        "k_pct": (b["so"] or 0) / pa,
        "bb_pct": (b["bb"] or 0) / pa,
        "hr_pct": (b["hr"] or 0) / pa,
        # Balls in play that fall in. The model draws hits from this rather
        # than from batting average so that strikeouts and home runs, both
        # already drawn, are not counted a second time.
        "babip": ((hits - (b["hr"] or 0)) / bip) if bip else 0.295,
        # Conditional on a non-homer hit. Extra-base rates move much less
        # between hitters than the overall hit rate does, so this is applied
        # league-wide and the individual variation is carried by BABIP.
        "hit_mix": {
            "1b": singles / (hits - (b["hr"] or 0)) if hits else 0.76,
            "2b": (b["d"] or 0) / (hits - (b["hr"] or 0)) if hits else 0.22,
            "3b": (b["t"] or 0) / (hits - (b["hr"] or 0)) if hits else 0.02,
        },
        "runs_per_9": ((p["r"] or 0) * 27) / (p["o"] or 1),
    }

    # ---- everything on the population we actually simulate ----
    #
    # log5 returns the LEAGUE value when batter and pitcher are both
    # average, so the league baseline is the simulator's floor. Feeding it
    # the whole pitcher pool's rate pulls every simulated start toward a
    # population we never simulate: rotation starters walk 0.0784 per batter
    # faced, all starters 0.0801, the full pool 0.0859. Using 0.0886 — the
    # pool, on the BATTING denominator — inflated simulated walks by 6-8%.
    #
    # So the baselines come from rotation starters on the pitching
    # denominator, and the BATTER rates are scaled onto that same footing.
    # Scaling the pitchers instead was tried and made walks worse: the
    # pitcher rates were already on the right denominator, it was the
    # reference that was wrong.
    sp = _starter_league(conn, before=before, season=raw_season)
    if sp:
        out["batter_scale"] = {
            k: (sp[k] / out[k]) if out.get(k) else 1.0
            for k in ("k_pct", "bb_pct", "hr_pct", "babip")
        }
        out.update({k: sp[k] for k in
                    ("k_pct", "bb_pct", "hr_pct", "babip")})
    else:
        out["batter_scale"] = {k: 1.0 for k in
                               ("k_pct", "bb_pct", "hr_pct", "babip")}
    _LEAGUE_CACHE[key] = out
    return out


# ── log5 ───────────────────────────────────────────────────────────────
def log5(batter: float, pitcher: float, lg: float) -> float:
    """Matchup rate from a batter rate, a pitcher rate and the league's.

    The odds-ratio construction. A batter who strikes out at league average
    against a pitcher who strikes out at league average returns league
    average; a good hitter against a good pitcher lands between them rather
    than at either. Averaging the two rates would be the naive alternative
    and it gets the tails badly wrong — a .400 hitter against a pitcher who
    allows .200 is not a .300 matchup.
    """
    if lg <= 0 or lg >= 1:
        return max(0.0, min(1.0, (batter + pitcher) / 2))
    b = min(max(batter, 1e-6), 1 - 1e-6)
    p = min(max(pitcher, 1e-6), 1 - 1e-6)
    num = (b * p) / lg
    den = num + ((1 - b) * (1 - p)) / (1 - lg)
    return num / den if den else lg


def odds_mult(p: float, m: float, lg: float) -> float:
    """A RATE multiplier applied to an odds-ratio construction.

    `log5` combines three rates as ODDS. Multiplying its probability output
    is therefore not a consistent change to the underlying rates: a 1.05x on
    a .05 probability is nearly a 1.05x on the odds, and on a .45 probability
    it is not close. The same park factor then means something different in a
    high-strikeout matchup than a low one, and the distortion is worst in the
    TAILS, which is where prop lines sit.

    It can also leave [0, 1], which is the only reason the branches below
    ever needed clamping — and they clamped three different ways, with the
    unclamped ones silently suppressing the branch after them.

    This is the operation that stays inside the construction. `m` is picked
    to mean what a park factor or an arsenal multiplier is documented to
    mean: a league-average matchup in an `m` park comes out at EXACTLY
    `m * lg`. Away from the league rate it bends rather than scaling, which
    is the correct behaviour and the whole point — a .45 strikeout matchup
    cannot absorb a 1.2x the way a .05 one can.

    Cannot return a value outside (0, 1) for any finite positive `m`.
    """
    if m == 1.0 or not 0.0 < p < 1.0 or not 0.0 < lg < 1.0:
        return p
    ml = min(max(m * lg, 1e-9), 1.0 - 1e-9)
    ratio = (ml / (1.0 - ml)) / (lg / (1.0 - lg))
    o = (p / (1.0 - p)) * ratio
    return o / (1.0 + o)


# ── the plate appearance ───────────────────────────────────────────────
#
# Outcomes are drawn in a fixed order — strikeout, walk, home run, then
# ball-in-play — because each is conditioned on the previous one not
# happening. Drawing them independently and resolving collisions would
# double-count: a plate appearance cannot be both a strikeout and a homer,
# and the naive fix (renormalise afterwards) silently changes every rate.

K, BB, HR, B1, B2, B3, OUT, SAC, HBP, ROE = ("K", "BB", "HR", "1B", "2B",
                                             "3B", "OUT", "SAC", "HBP", "ROE")


def _sigmoid(z: float) -> float:
    try:
        return 1.0 / (1.0 + pow(2.718281828459045, -z))
    except OverflowError:
        return 0.0 if z < 0 else 1.0

#: Pitches thrown, by how the plate appearance ended.
#:
#: FITTED, at last, against 2,070 starts of real counts. `numberOfPitches`
#: was in the statsapi boxscore all along and `grading.py` was discarding
#: it; `sources/pitches.py` backfills it. Least squares with no intercept,
#: mean absolute error 6.9 pitches on an 83.6-pitch start.
#:
#: The docstring this replaces claimed these "reproduce the observed
#: distribution of starter pitch counts" while also stating the cache had no
#: pitch counts. Both could not be true. They came from published averages,
#: and they were close — but biased in one direction: CONTACT outcomes cost
#: fewer pitches than assumed (hits -0.39, balls in play -0.25) and
#: strikeouts slightly more. Net, the model billed 3.94 pitches per plate
#: appearance against a real 3.839, over-counting by 2.6% and pushing every
#: starter toward the hook's threshold early. That is a mechanical
#: contributor to the measured early-exit gap (31.2% against a real 25.6%).
#:
#: Doubles and triples are not separately identified — the boxscore gives
#: hits, not hit types, to a pitcher — so they inherit the non-homer hit
#: coefficient. SAC and ROE are likewise unidentified and keep sensible
#: neighbours.
#: Pitches charged per outcome. COUNTED on 150,907 plate appearances of
#: 2026 play-by-play, 2026-08-29 (`scratchpad/pitch_cost.py`), replacing
#: values that were off by up to 19%:
#:
#:     outcome     was   counted        n
#:     K          4.97      4.85   33,469
#:     BB         5.48      5.72   13,181
#:     HBP        3.67      3.09    1,721   <- 19% high
#:     HR         3.76      3.28    4,610   <- 15% high
#:     1B         3.01      3.35   21,386
#:     2B         3.01      3.33    6,234
#:     3B         3.01      3.36      548
#:     OUT        3.25      3.37   67,298
#:     SAC        3.00      2.77    1,592
#:     ROE        3.25      3.46      868
#:
#: The old values charged one flat 3.01 to every hit and too much for a
#: home run and a hit-by-pitch — both of which end an at-bat EARLY, which
#: is the tell that they were imported rather than counted.
#:
#: IT IS A LEVEL ERROR AND THE HOOK KEYS ON IT. Summed over a start the old
#: table predicted 83.6 pitches against an actual 85.6, so every simulated
#: starter arrived at the removal decision two pitches young.
#:
#: **DETERMINISTIC ON PURPOSE, and that was checked rather than assumed.**
#: The obvious next thought is to draw the cost from a distribution — real
#: pitches per plate appearance carry sd 1.4 to 1.9. Measured, that is
#: WRONG: the table already produces a start-level spread of 15.0 pitches
#: against a real 14.2, so it is if anything slightly too wide already, and
#: adding independent per-PA noise over ~25 plate appearances would take it
#: to ~17.5. Real pitch counts are CORRELATED WITHIN A START — an efficient
#: pitcher is efficient all night — so independent noise is the wrong
#: shape. What remains wrong is per-start ACCURACY (residual sd 8.2), and
#: that is a per-pitcher efficiency term, not noise.
PITCH_COST = {K: 4.85, BB: 5.72, HR: 3.28, B1: 3.35, B2: 3.33, B3: 3.36,
              OUT: 3.37, SAC: 2.77, HBP: 3.09, ROE: 3.46}

#: How much trouble each outcome represents, for the hook. NOT run value —
#: this is "how alarmed is the dugout", which is a different quantity. Runs
#: allowed is a LAGGING indicator: a starter who has put five men on and
#: allowed nothing is about to be removed, and a rule keyed on runs thinks
#: he is cruising. Baserunners lead, runs follow.
#:
#: A home run scores more damage than a double despite clearing the bases,
#: because it is the outcome that most reliably shortens a manager's
#: patience. The relative weights are tuned; their ORDER is not in question.
#: A reached-on-error is a baserunner the dugout did not concede, so it
#: carries a runner's damage but not a hit's — the manager is annoyed at his
#: defence, not at his pitcher.
DAMAGE = {BB: 1.0, B1: 1.0, B2: 1.7, B3: 2.3, HR: 3.0, K: 0.0, OUT: 0.0,
          SAC: 0.0, HBP: 1.0, ROE: 0.5}

# ── outs the model could not produce ───────────────────────────────────
#
# Measured: the simulator converts 1.1% fewer batters into outs than reality
# does — 0.7017 outs per batter against 0.7094 — while facing the same
# number of them (22.87 vs 22.88). It manufactures the difference as
# baserunners, which then trips the hook early and shortens the start. Two
# out-sources it structurally cannot produce account for nearly all of it.
#
# SACRIFICES are plate appearances that are automatic outs. The sim has no
# concept of them, so they land in the ball-in-play bucket and get a .294
# BABIP roll, turning about 29% of them into hits that were never in doubt.
# Published league share is ~1.0% of plate appearances (SH ~0.3, SF ~0.7).
#
# CAUGHT STEALING is an out with no batter attached, and it counts toward a
# pitcher's innings pitched. Derived locally: 1,301 steals over 23,338 times
# on base, and at the league ~79% success rate that implies ~346 runners
# caught — 0.0148 per runner reaching, or about 0.10 outs a start.
#
# Neither is tuned. Both come from the local cache or from published league
# shares, and both were sized BEFORE being implemented.

#: Share of plate appearances that are a sacrifice bunt or fly. An
#: automatic out; never a BABIP event.
#:
#: BY ROLE, because it is not one number. Counted per plate appearance off
#: play-by-play, 2026 (`scratchpad/hbp_sac.py`):
#:
#:     season   SP SAC   RP SAC
#:     2023     0.00794  0.01014
#:     2024     0.00783  0.01123
#:     2025     0.00864  0.01218
#:     2026     0.00888  0.01272
#:
#: Relievers see 43% more sacrifices than starters and both are trending
#: up — late innings are when a run is worth bunting for. The flat constant
#: below is retained as the fallback for an arm with no role attached.
SAC_RATE = 0.010
SAC_RATE_SP = 0.00888
SAC_RATE_RP = 0.01272
#: Share of plate appearances ending in a hit by pitch. A free baserunner
#: the model never had.
#:
#: Why its absence mattered more than 1% suggests: the calibration target is
#: runs per HIT-OR-WALK, measured in a world that also has hit batsmen and
#: reached-on-errors putting men on. Their runs land in the real numerator
#: and could never land in ours, so the target was unreachable by
#: construction — which is why no advancement rate could close it.
#:
#: Tracked separately from walks so `bb` still matches the boxscore.
#:
#: MEASURED, not published: 0.0098 per batter faced over 2,070 starts, from
#: the `hitByPitch` field the boxscore was already returning.
#:
#: THAT MEASUREMENT WAS ON STARTERS AND IS APPLIED TO EVERY ARM. Counted per
#: plate appearance off play-by-play (`scratchpad/hbp_sac.py`), relievers hit
#: batters 21-34% more often than starters in every season on file:
#:
#:     season   SP HBP   RP HBP    gap
#:     2023     0.01003  0.01342   +34%
#:     2024     0.00991  0.01273   +28%
#:     2025     0.00944  0.01208   +28%
#:     2026     0.01044  0.01262   +21%
#:
#: So the pooled rate reads 11.9% above the shipped constant and the shipped
#: constant is roughly RIGHT for the population it was measured on. This was
#: a population mismatch, not a level error, and the correct fix is to let
#: the rate depend on who is pitching — which the engine already knows.
#:
#: A hit-by-pitch is a BASERUNNER and this model is 6% short on runs with the
#: right number of hits, strikeouts and home runs, so under-counting them on
#: 43% of plate appearances is not a rounding error.
HBP_RATE = 0.0098
HBP_RATE_SP = 0.01044
HBP_RATE_RP = 0.01262
#: Chance a runner on first is caught stealing, per plate appearance he is
#: aboard for. Removes the runner AND records an out.
#: RE-MEASURED 2026-08-27 ON THE DENOMINATOR IT IS ACTUALLY USED WITH. The
#: 0.0148 came from "1,301 steals over 23,338 TIMES ON BASE" — but
#: `baserunning` only rolls when first is occupied and SECOND IS EMPTY, a
#: strictly smaller population, so a rate derived over all times on base is
#: too low by the ratio between them. Same class of error as the wild-pitch
#: rate, which was translated onto the wrong denominator too.
#:
#: Counted per opportunity in exactly that state (`scratchpad/role_audit.py`),
#: and gated on era because the 2023 rule changes moved stealing:
#:
#:     season      SB       CS        n
#:     2023    0.0672   0.0151   48,019
#:     2024    0.0718   0.0169   46,985
#:     2025    0.0681   0.0172   47,136
#:     2026    0.0651   0.0175   36,722
#:
#: Stable, so the 2026 values are used rather than a pool. Both rise ~17%,
#: which is why this is close to run-neutral: more attempts, same success
#: ratio. What it changes is the SHAPE — 17% more runners moving into
#: scoring position.
#:
#: NOT FIXED, and it bounds what any rate here can buy: 14.5% of real steal
#: events happen in states this model cannot produce at all — steals of
#: third and double steals. That is a missing mechanism, not a mistuned
#: rate.
CS_RATE = 0.0175
#: Chance he steals second instead. Derived the same way: 1,301 steals over
#: 23,338 times on base.
#:
#: ADDING CS WITHOUT THIS WAS A BUG OF MINE. For half a day the simulator
#: took every downside of baserunning and none of the upside — runners were
#: thrown out and never advanced — which showed up as runs per baserunner
#: 10% light while the baserunner count itself was correct. The giveaway
#: was that no plausible advancement rate could close the gap: pushing
#: "scores from second on a single" to 0.75 against a published ~0.60 still
#: left it 3.6% short. When a parameter cannot reach the target, the
#: mechanism is missing rather than mistuned.
SB_RATE = 0.0651

#: Share of ball-in-play outs that become double plays when there is a
#: runner on first and fewer than two out. Matters for outs props directly:
#: a double play is two of them from one batter.
#:
#: THIS VALUE IS ATTACHED TO THE WRONG DENOMINATOR AND ALWAYS WAS. 0.11 is
#: `GIDP%` as normally published, which is double plays per OPPORTUNITY —
#: every plate appearance with a man on first and under two out. Measured
#: here it is .089/.095 by out count, right next to 0.11, so the number
#: itself was fine. But the roll below only happens once a ball in play has
#: ALREADY become an out, which is about half as many chances, and the rate
#: in THAT denominator measures .209/.224. The simulator has been turning
#: roughly half the double plays it should.
#:
#: Left as the shipped default under a switch rather than simply corrected,
#: because the F5 fit picked 0.11 in the model's own denominator over a grid
#: that reached 0.19. Something is compensating and doubling it blind would
#: break whatever that is. The scoring run decides.
#: MEASURED IN THE MODEL'S OWN DENOMINATOR. This keeps the name `GIDP_RATE`
#: because `fitf5` searches it and `sim.rules` overrides it by name — the
#: first version of this change introduced `GIDP_ON_OUT` alongside and left
#: `GIDP_RATE` wired to nothing, so the fit would have explored a parameter
#: that no longer reached the model. `check_evaluate_applies_its_parameters`
#: caught it, which is the entire reason that check exists.
#:
#: RE-MEASURED 2026-08-26 ON 2025+2026 ONLY, and the season restriction is
#: the finding rather than a detail. Counted per season, man on first, under
#: two out, in the model's own denominator:
#:
#:     season    0 out     1 out
#:     2023     0.2307    0.2531
#:     2024     0.2303    0.2300
#:     2025     0.2132    0.2327
#:     2026     0.2129    0.2276
#:
#: The 0-out rate STEPS between 2024 and 2025 — 0.230 to 0.213, about 3.3
#: sigma on ~6,900 rows a season — so the era gate FAILS and pooling four
#: seasons would import a rate this league no longer has. 2025+2026 pooled
#: gives 0.2131 and 0.2305, against the 0.209/0.224 measured on 2026 alone.
#:
#: Note TTO passed the same gate on the same pass over the same games
#: (`scratchpad/season_gate.py`), so this is not a blanket "history is
#: different" result — the two quantities genuinely differ.
GIDP_RATE = {0: 0.2131, 1: 0.2305, 2: 0.0}
USE_MEASURED_GIDP = True
#: The published per-opportunity number, on the wrong denominator.
LEGACY_GIDP_RATE = 0.11


def gidp_rate(outs: int) -> float:
    return _rate(GIDP_RATE if USE_MEASURED_GIDP else LEGACY_GIDP_RATE, outs)

# ── the runs the model could not produce ───────────────────────────────
#
# THE LAST BIG MISSING MECHANISM, and it was found the way the absent
# hit-by-pitch was: by a fit driving a parameter to the edge of its grid
# rather than by inspection. Simulating whole games showed the run level
# 6.7% light (8.09 a game against 8.67) while the SHAPE was right once the
# bullpen was sampled properly. A uniform 6.7% shortfall with correct
# dispersion is not a mistuned rate; it is a missing source of runs.
#
# It is fielding errors. The simulator converts every ball in play into a
# hit or an out, so a defence that boots one cannot exist, and unearned runs
# are 7.64% of all runs in the local record — 9,273 total against 8,565
# earned. 8.09 / (1 - 0.0764) = 8.76 against an actual 8.67.
#
# Modelled as a would-be OUT that becomes a baserunner instead: no hit, no
# out recorded, batter on first. That is what reaching on an error IS, and
# it is why an error hurts twice — the run that scores and the out that did
# not.

#: Share of ball-in-play OUTS on which the batter reaches on an error.
#:
#: COUNTED 2026-08-27, replacing a value CALIBRATED against the unearned-run
#: share. The old comment above it did the arithmetic in the open —
#: "8.09 / (1 - 0.0764) = 8.76 against an actual 8.67" — which is an error
#: rate set to lift the RUN LEVEL, not an error rate. Counted directly, in
#: the denominator this constant is actually rolled against:
#:
#:     season    errors   bip outs     rate
#:     2023       1,216     89,427    0.0134
#:     2024       1,243     89,522    0.0137
#:     2025       1,115     90,025    0.0122
#:     2026         879     69,626    0.0125
#:     25+26      1,994    159,651    0.0123
#:
#: The fudge ran 46% high and put 3.5 fake baserunners per 1,000 plate
#: appearances into the model (`scratchpad/traffic.py`: ROE 8.7 simulated
#: against a real 5.2).
#:
#: ERA-GATED like `GIDP_RATE`, and it steps in the same place: 2023/24 sit
#: at ~0.0136 and 2025/26 at ~0.0123, about 3.4 sigma. Both defensive
#: quantities changed between 2024 and 2025.
#:
#: **THIS MAKES THE RUN DEFICIT WORSE AND THAT IS THE POINT.** Part of the
#: model's run total was these baserunners. Removing them exposes how much
#: of the 3%-light figure was being masked, which is information the fudge
#: was concealing. A measured quantity replacing a calibrated one does not
#: have to prove itself on the score — see CLAUDE.md.
ROE_PER_OUT = 0.0123


@dataclass
class PitcherRates:
    """Per-PA rates for the starter. Everything the PA model needs."""
    name: str = ""
    k_pct: float = 0.22
    bb_pct: float = 0.088
    hr_pct: float = 0.033
    babip: float = 0.295
    #: Batters faced behind these rates. Carried so a caller can widen the
    #: distribution for a pitcher with 80 PA on record versus one with 600.
    pa: int = 0
    #: Per-arm hit-by-pitch and sacrifice rates. None falls back to the
    #: flat league constants, so an arm with no role attached behaves
    #: exactly as before.
    hbp_rate: float | None = None
    sac_rate: float | None = None
    #: {"L": rates, "R": rates} — HIS rates against each batter side. The
    #: other half of the matchup, and it did not exist before 2026-08-27:
    #: every handedness attempt in this project conditioned the batter and
    #: left the pitcher on his blended line. A left-hander who is death on
    #: left-handed bats and ordinary against righties is a real and common
    #: type and none of it was modelled. None means use the blended rates.
    vs_side: dict | None = None


@dataclass
class BatterRates:
    name: str = ""
    k_pct: float = 0.22
    bb_pct: float = 0.088
    hr_pct: float = 0.033
    babip: float = 0.295
    pa: int = 0
    #: THE SIDE HE BATS FROM against the arm currently modelled, and the
    #: league rates for that (batter side, pitcher hand) cell. Both empty by
    #: default and the plate appearance is bit-identical when they are.
    #:
    #: log5 returns the truth only when the batter rate, the pitcher rate
    #: and the LEAGUE BASELINE all sit on the same population. Conditioning
    #: the batter on the pitcher's hand while leaving the other two
    #: unconditional biases the L-vs-L cell by +0.0013 on K% — small, but a
    #: bias rather than noise, and it grows with the size of the split.
    side: str = ""
    lg_cell: dict | None = None
    #: Multiplier on contact quality from the arsenal projection — this
    #: hitter's projection against this starter's actual pitch mix, over
    #: his projection against a LEAGUE-AVERAGE mix. 1.0 means the mix is
    #: neutral for him.
    #:
    #: Relative to the league arsenal and NOT to his own season line: his
    #: overall quality already lives in the rates above, and dividing by it
    #: would count him twice. This is where `batter.vs_arsenal` enters the
    #: simulation, and until it was wired it fed nothing.
    arsenal_mult: float = 1.0
    #: The same idea on the strikeout channel, from projected whiff rate.
    #: Separate because a mix can miss bats without producing weak contact —
    #: a slider-heavy righty and a sinker-heavy one fail differently.
    arsenal_k_mult: float = 1.0


#: Neutral park. Every factor is a multiplier on a rate, 1.0 = league.
#: Savant publishes these as indices where 100 is average, so a caller
#: converts with index/100 — see `park_mults`.
#: `bb` was added 2026-08-29. Savant has always served a walk park
#: index and `sources/park.py` has always fetched it — it had nowhere
#: to go, so every park test ever run here excluded walks by
#: construction. Spread across 29 venues is 91 to 114, sd 5.0, which
#: is the same order as the home-run factors that ARE used.
NEUTRAL_PARK = {"hr": 1.0, "k": 1.0, "bip": 1.0, "bb": 1.0}


def park_mults(factors: dict | None) -> dict:
    """Savant park indices -> rate multipliers, or neutral when unknown.

    None in, neutral out. A venue Savant does not rate must NOT fall back to
    the home club's park: the Athletics played 38 home games this season at
    a site with no published factors, and borrowing Oakland's for them would
    be confidently wrong 38 times.
    """
    if not factors:
        return dict(NEUTRAL_PARK)
    def m(key, default=100):
        v = factors.get(key)
        return (v / 100.0) if v else (default / 100.0)
    return {"hr": m("hr"), "k": m("so"), "bip": m("bacon", 100),
            # Savant's walk index. Fetched by `sources/park.py` since the
            # beginning and dropped on the floor here until 2026-08-29.
            "bb": m("bb")}


#: TIMES THROUGH THE ORDER. Multipliers on a starter's own rates by how
#: many times he has already faced this lineup, COUNTED on 85,909 starter
#: plate appearances by `src.context.tto`.
#:
#: The strikeout collapse is the whole effect: 1.105 on the first pass
#: against 0.893 on the third, a 19% relative decline. Walks and home runs
#: drift up by 3-4%; BABIP is flat.
#:
#: RE-CENTRED so the PA-weighted mean is 1.000, which is not optional. The
#: model's input `k_pct` is a season rate ALREADY averaged over every pass a
#: starter throws, so multipliers anchored at pass-1 = 1.0 would raise every
#: pitcher's strikeout rate and shift the run level.
#:
#: Pass 4+ folds into pass 3: it is 0.4% of plate appearances and its raw
#: numbers are erratic (a walk multiplier of 0.755 on 351 PAs).
#:
#: NOT FITTABLE, and deliberately absent from `FITTABLE`.
TTO_MULT = {
    1: {"k_pct": 1.1053, "bb_pct": 0.9955, "hr_pct": 0.9653,
        "babip": 0.9845},
    2: {"k_pct": 0.9420, "bb_pct": 0.9893, "hr_pct": 1.0137,
        "babip": 1.0141},
    3: {"k_pct": 0.8926, "bb_pct": 1.0352, "hr_pct": 1.0394,
        "babip": 1.0029},
}

#: Off restores a starter who never tires and is never learned. That was the
#: state in which three separate measurements found the removal rule to have
#: nothing to give — with no degradation, pulling a pitcher costs nothing.
USE_TTO = True


def tto_mult(tto: int | None) -> dict | None:
    """Multipliers for a given pass, or None when TTO does not apply.

    `None` is passed by callers that do not track the pass — relievers have
    no meaningful lineup pass — and must leave the rates untouched rather
    than defaulting to the first pass, which would silently apply a 1.105
    strikeout bonus to every arm out of the bullpen.
    """
    if not USE_TTO or not tto:
        return None
    return TTO_MULT.get(min(max(tto, 1), 3))


#: Rate multipliers by FIELD STATE, keyed `(men on base, outs)`.
#:
#: WHY THIS EXISTS. Until 2026-08-29 a plate appearance resolved identically
#: with the bases empty and the bases loaded — `pa_from` took a resolved
#: matchup and a times-through-order index and nothing else. Counted on
#: 112,809 real plate appearances (`scratchpad/basestate.py`, intentional
#: walks and sacrifice bunts excluded because both are runners-on-only
#: plays that would manufacture the effect):
#:
#:     channel    empty   runners on      rel   sigma
#:     k         0.2279       0.2160    -5.2%    -4.7
#:     bb        0.0850       0.0920    +8.2%    +4.1
#:     hbp       0.0104       0.0128   +23.0%    +3.7
#:     h         0.2138       0.2236    +4.6%    +3.9
#:
#: Real offence is materially better with men on, and the model had no
#: channel for it. That matters beyond the level: it is a FEEDBACK LOOP —
#: a baserunner improves the next plate appearance, which produces more
#: baserunners — and a feedback loop is what generates fat tails at both
#: ends. The standing unexplained defect is that reality has more shutouts
#: AND more blowups while the model bunches in the middle, recorded as
#: "plate appearances resolve independently and real ones arrive together".
#: This is that mechanism.
#:
#: EMPTY IS NEUTRAL AND THAT IS DELIBERATE. The table ships empty so the
#: PLUMBING can be verified bit-identical before any number goes in it —
#: the same discipline the `odds_mult` migration used. Populating it is a
#: separate change with its own measurement and its own A/B.
#:
#: HOME RUNS are the one channel absent, and on purpose — see below.
#: `hbp_pct` joined on 2026-08-29 and is the reason `cond` is recomputed in
#: `pa_from`: a hit batsman is drawn off the top, so scaling it without
#: rescaling the renormaliser in the same breath leaves every rate below it
#: divided by the wrong number.
STATE_MULT: dict = {
    (0, 0): {"k_pct": 0.9849, "bb_pct": 0.9505, "babip": 0.9873,
             "hbp_pct": 0.9397, "hr_pct": 1.0584},
    (0, 1): {"k_pct": 1.0391, "bb_pct": 0.9605, "babip": 0.9781,
             "hbp_pct": 0.9056, "hr_pct": 0.9938},
    (0, 2): {"k_pct": 1.0706, "bb_pct": 1.0186, "babip": 0.9742,
             "hbp_pct": 0.9109, "hr_pct": 0.9567},
    (1, 0): {"k_pct": 0.9206, "bb_pct": 0.9907, "babip": 1.0553,
             "hbp_pct": 1.1985, "hr_pct": 0.9977},
    (1, 1): {"k_pct": 0.9611, "bb_pct": 1.0464, "babip": 1.0451,
             "hbp_pct": 1.0718, "hr_pct": 0.9955},
    (1, 2): {"k_pct": 0.9975, "bb_pct": 1.1037, "babip": 0.9952,
             "hbp_pct": 0.9923, "hr_pct": 0.9742},
    (2, 0): {"k_pct": 0.9289, "bb_pct": 0.9706, "babip": 1.0650,
             "hbp_pct": 1.1102, "hr_pct": 1.0102},
    (2, 1): {"k_pct": 0.9432, "bb_pct": 0.9708, "babip": 1.0360,
             "hbp_pct": 1.2094, "hr_pct": 0.9421},
    (2, 2): {"k_pct": 1.0207, "bb_pct": 1.1094, "babip": 0.9905,
             "hbp_pct": 1.1450, "hr_pct": 0.9774},
    (3, 0): {"k_pct": 0.9615, "bb_pct": 0.7812, "babip": 1.0294,
             "hbp_pct": 0.9862, "hr_pct": 0.9899},
    (3, 1): {"k_pct": 0.9845, "bb_pct": 0.7583, "babip": 1.0446,
             "hbp_pct": 1.3148, "hr_pct": 0.9921},
    (3, 2): {"k_pct": 1.0054, "bb_pct": 0.9857, "babip": 0.9647,
             "hbp_pct": 1.1449, "hr_pct": 0.9945},
}

#: HOW THE TABLE ABOVE WAS BUILT, because "measured" has to be checkable.
#:
#: Counted on 748,905 plate appearances over 9,978 games of 2023-2026
#: (`scratchpad/state_seasons.py`), JOINTLY on (men on, outs) — the earlier
#: tables varied one at a time and cannot separate them, since a two-out
#: plate appearance is likelier to have runners on and vice versa.
#:
#: MULTIPLIERS ARE COMPUTED WITHIN A SEASON AND POOLED AFTERWARDS, and that
#: ordering matters. The league drifts — 2023 struck out at 0.2299 against
#: 2026's 0.2224 — so pooling raw COUNTS and taking one ratio lets a
#: season's baseline leak into the cells. A ratio to that season's own
#: overall rate is the quantity that is comparable across years.
#:
#: Each multiplier is the cell's rate over the OVERALL rate, which makes the
#: table self-normalising: sum of freq(s) x rate(s) IS the overall rate by
#: definition. Verified — the frequency-weighted mean came back 1.0000 on
#: every channel before shrinkage and is renormalised to exactly 1.0 after.
#:
#: GATED ON WHETHER A CELL REPEATS FROM YEAR TO YEAR, which is the check
#: `advance.py` applies per club and FAILS. Correlation of the twelve cell
#: multipliers between seasons, averaged over the six pairs:
#:
#:     stat       all 12    fat 8      tau   mean se   weight kept
#:     k_pct       0.859    0.945   0.0437    0.0146       0.91
#:     bb_pct      0.908    0.866   0.1121    0.0245       0.96
#:     hr_pct      0.172    0.519   0.0272    0.0439       0.48
#:     babip       0.432    0.850   0.0372    0.0154       0.88
#:     hbp_pct     0.550    0.764   0.1606    0.0807       0.84
#:
#: THE TWO COLUMNS DISAGREE AND THE FAT ONE IS RIGHT. An unweighted
#: correlation over twelve cells gives the three bases-loaded cells — 3,149
#: plate appearances between them against 185,488 in the leadoff cell — the
#: same vote as the cell that decides the channel, so their own noise reads
#: as a channel that does not repeat. Restricted to the eight cells above
#: 30,000 plate appearances, every channel repeats. A correlation over
#: twelve points has se ~0.27 anyway; read the direction, not the decimal.
#:
#: THEN SHRUNK TOWARD 1.0 BY EACH CELL'S OWN BINOMIAL NOISE
#: (`scratchpad/state_shrink.py`), tau^2 = observed variance minus mean
#: noise variance. A cell seen 3,149 times must not shout as loudly as one
#: seen 185,488 times.
#:
#: **HOME RUNS ARE BACK, AND THIS IS WHY THE RESCAN WAS WORTH DOING.** On
#: 2026 alone their entire spread was their own sampling error, tau came
#: back 0.0000 and the channel shipped as all-ones — correctly, on that
#: data. On five times the data tau is 0.0272 and the channel keeps 48%:
#: 1.058 with the bases empty and nobody out, falling to 0.942 at two on
#: and one out. Ordinary baseball — a pitcher challenges a hitter with
#: nobody aboard and works away from the barrel with men on. THE OLD NULL
#: WAS NOT WRONG, IT WAS UNDERPOWERED, which is the distinction this
#: project keeps having to relearn.
#:
#: WHAT THE OTHER NUMBERS SAY, and all of it is ordinary baseball: with men
#: on, strikeouts fall and balls in play find more holes (the defence is
#: holding runners). Strikeouts rise with the out count independently of the
#: bases, which is the effect the one-at-a-time tables confounded with
#: traffic. Walks rise with a man on and COLLAPSE with the bases loaded —
#: 0.781 and 0.758 at (3, 0) and (3, 1) — because a walk there forces in a
#: run and nobody pitches around anyone. That effect was 0.970/0.947 on 2026
#: alone and is one of the two the rescan sharpened most.
#:
#: HIT-BY-PITCH is the other, and it has the largest tau of the five.
#: Pitchers hit more batters with men on: all three empty cells sit at
#: 0.906-0.940 and every occupied one bar (1, 2) is above 1.07, topping out
#: at 1.31 with the bases loaded and one out. Working from the stretch, more
#: breaking balls in the dirt, less margin to miss over the plate. It keeps
#: 84% of its spread now against 36% on 2026 alone.
#:
#: WIRING IT REQUIRED `cond`. HBP is drawn off the top, so its rate is also
#: the renormaliser for everything below it — see `pa_from`, where the two
#: move together and cannot disagree.

#: ON. Measured, shrunk, and scored on the SHAPE rather than the mean.
#:
#: Scored on 537 holdout games, 21,480 simulated sides an arm, against a
#: 3x-amplified positive control:
#:
#:     F5 per side          OFF      ON   CTRLx3   ACTUAL    se(actual)
#:     mean               2.425   2.458    2.500    2.437         0.071
#:     sd                 2.254   2.286    2.326    2.313
#:     shutout share      0.215   0.213    0.211    0.219         0.012
#:     five-plus share    0.164   0.169    0.175    0.176         0.012
#:
#: The spread and the five-plus share both move toward reality. The mean
#: and the shutout share move by 0.3 sigma and 0.2 se respectively — that
#: is noise, and an earlier version of this comment called both of them
#: results. F5 CRPS is neutral (+0.00169 +/- 0.00235 over four salts),
#: which is the EXPECTED reading for a change this size: CRPS is dominated
#: by the bulk and cannot resolve a shape move in the tails.
#:
#: **THE PREDICTION THAT FAILED WAS MINE, NOT THE MECHANISM'S.** It was
#: registered as "both tails fatten" on the generic intuition that
#: clustering produces feast or famine. Reading the measured table back
#: shows there was never a route to more shutouts in it: the bases-empty
#: nobody-out cell — where every inning begins — comes out NEUTRAL
#: (k 0.987). The table makes a rally easier to CONTINUE and does nothing
#: to make one harder to START. That is an amplifier, and an amplifier
#: moves one side. Import the intuition, get the wrong falsifier.
#:
#: NOT SCALED TO PIN THE MEAN, and deliberately. Solving for a scalar that
#: lands the level on a target is fitting a counted quantity back to a
#: search, and the level it would be defending is 0.3 sigma from where it
#: already is.
USE_FIELD_STATE = True


def state_mult(state: tuple | None) -> dict | None:
    """Multipliers for a base-out state, or None when it does not apply.

    `None` means leave the rates alone, and an empty `STATE_MULT` therefore
    makes this path a no-op rather than a neutral multiplication — worth
    being exact about, because `odds_mult` returns its input unchanged only
    when `m` is EXACTLY 1.0.
    """
    if not USE_FIELD_STATE or not state or not STATE_MULT:
        return None
    return STATE_MULT.get(state)


@dataclass(slots=True)
class Matchup:
    """EVERYTHING one plate appearance depends on, resolved in one place.

    THE PROBLEM THIS SOLVES. A plate appearance's inputs used to come from
    five places at once: fields on the batter, fields on the pitcher, a
    league dict threaded down through several call layers, module globals,
    and function arguments. Nothing owned the question "what does this at-bat
    actually depend on", so every new value found its own route down and
    picked whichever object was already going there.

    That is not cosmetic and it cost two bugs on 2026-08-27. `lg_cell` — a
    LEAGUE baseline — ended up living on a `BatterRates`, because the batter
    was the object that happened to flow to the right place. And
    `calibrate.adjust_lineup` rebuilt every `BatterRates` listing its fields
    by hand, so it silently dropped `side` and `lg_cell` and the handedness
    matchup arm came out identical to four decimal places, which reads as a
    null and is plumbing.

    With this, a new adjustment touches `resolve` and nothing else. Nobody
    constructing a batter needs to know handedness or park or arsenal exist.

    THE THREE log5 TERMS ARE HELD SEPARATELY AND ON THE SAME POPULATION.
    Conditioning the batter while leaving the pitcher and the baseline
    unconditional is the error that made handedness read as a wash for a
    day; keeping them adjacent makes that visible instead of scattered.
    """
    #: The three log5 terms per channel: batter, pitcher, league baseline.
    b_k: float = 0.22
    b_bb: float = 0.088
    b_hr: float = 0.033
    b_bab: float = 0.295
    p_k: float = 0.22
    p_bb: float = 0.088
    p_hr: float = 0.033
    p_bab: float = 0.295
    lg_k: float = 0.22
    lg_bb: float = 0.088
    lg_hr: float = 0.033
    lg_bab: float = 0.295
    #: Rate multipliers — park times arsenal — applied through `odds_mult`,
    #: NOT to the probability. 1.0 is the shipped value for both today.
    m_k: float = 1.0
    m_hr: float = 1.0
    m_bip: float = 1.0
    #: Walks were the one channel with NO multiplier slot, so `bb` was bare
    #: `log5(...) / cond` while the other three went through `odds_mult`.
    #: That silently excluded walks from park, from arsenal and from any
    #: field-state term — a missing channel reads as a null, not as an
    #: error, which is the failure mode this project is worst at seeing.
    m_bb: float = 1.0
    #: Drawn off the top, per ARM. `cond` is carried rather than recomputed
    #: so it can never disagree with the two rates it renormalises.
    sac: float = 0.010
    hbp: float = 0.0098
    cond: float = 1.0
    #: The 1B/2B/3B split of a hit, which is a league property and the one
    #: thing here that is not a matchup.
    hit_mix: dict = field(default_factory=dict)


def resolve(b: BatterRates, p: PitcherRates, lg: dict,
            park: dict | None = None, hr_park: float = 1.0) -> Matchup:
    """Assemble one batter-pitcher pairing. THE ONLY PLACE INPUTS ARE PICKED.

    Called when a pitcher takes the mound rather than per plate appearance —
    nine of these, reused for every time through the order. `pa_outcome`
    carries a note that per-PA object construction was REMOVED as too
    expensive, and resolving here respects that: the object is built once
    per pairing and the per-PA path allocates nothing.

    Times through the order is deliberately NOT folded in. It scales the
    pitcher's rates and changes on every lineup pass, so baking it in would
    need three variants per batter; it stays a late input adjustment applied
    in `pa_from`, which is what it already was.
    """
    pk = park or NEUTRAL_PARK
    # BOTH SIDES AND THE BASELINE, or none of them. log5 returns the truth
    # only when the batter rate, the pitcher rate and the league baseline
    # all sit on the same population.
    p_k, p_bb, p_hr, p_bab = p.k_pct, p.bb_pct, p.hr_pct, p.babip
    if b.side and p.vs_side:
        ps = p.vs_side.get(b.side)
        if ps:
            p_k, p_bb = ps["k_pct"], ps["bb_pct"]
            p_hr, p_bab = ps["hr_pct"], ps["babip"]
    lgm = b.lg_cell or lg
    sac_r = SAC_RATE if p.sac_rate is None else p.sac_rate
    hbp_r = HBP_RATE if p.hbp_rate is None else p.hbp_rate
    return Matchup(
        b_k=b.k_pct, b_bb=b.bb_pct, b_hr=b.hr_pct, b_bab=b.babip,
        p_k=p_k, p_bb=p_bb, p_hr=p_hr, p_bab=p_bab,
        lg_k=lgm["k_pct"], lg_bb=lgm["bb_pct"],
        lg_hr=lgm["hr_pct"], lg_bab=lgm["babip"],
        m_bb=pk.get("bb", 1.0),
        m_k=pk["k"] * b.arsenal_k_mult,
        m_hr=hr_park * pk["hr"] * b.arsenal_mult,
        m_bip=pk["bip"] * b.arsenal_mult,
        sac=sac_r, hbp=hbp_r, cond=1.0 - sac_r - hbp_r,
        hit_mix=lg["hit_mix"])


def pa_outcome(
    b: BatterRates, p: PitcherRates, lg: dict, rng: random.Random,
    hr_park: float = 1.0, park: dict | None = None, tto: int | None = None,
    state: tuple | None = None,
) -> str:
    """One plate appearance, resolving the matchup first.

    THE CONVENIENCE PATH. Every caller that plays a real game should resolve
    once per pitcher change and call `pa_from`; this exists for tests and
    one-off questions where a single plate appearance is the whole point.
    """
    return pa_from(resolve(b, p, lg, park, hr_park), rng, tto, state)


def pa_from(mu: Matchup, rng: random.Random, tto: int | None = None,
            state: tuple | None = None) -> str:
    """One plate appearance from a resolved matchup. Returns an outcome.

    `state` is `(men on base, outs)` and enters as an ODDS multiplier
    through `odds_mult`, NOT the way `tto` does. The difference is not
    stylistic. Times through the order scales the PITCHER'S input rate,
    which is the right shape for "this man is wearing down". The field-state
    effect was measured as a LEAGUE RATE PER STATE — 0.2279 strikeouts with
    the bases empty against 0.2160 with men on — and `odds_mult` is built so
    a league-average matchup at multiplier `m` lands on exactly `m * lg`.
    So the measurement maps onto the mechanism with nothing to reconcile.
    """
    p_k, p_bb, p_hr, p_bab = mu.p_k, mu.p_bb, mu.p_hr, mu.p_bab
    m = tto_mult(tto)
    if m is not None:
        p_k *= m["k_pct"]
        p_bb *= m["bb_pct"]
        p_hr *= m["hr_pct"]
        p_bab *= m["babip"]
    # EXACTLY 1.0 WHEN THERE IS NOTHING TO APPLY, because `odds_mult`
    # short-circuits on `m == 1.0` and returns its input untouched. That is
    # what makes the empty table bit-identical to the state-blind model
    # rather than merely very close.
    s_k = s_bb = s_hr = s_bab = s_hbp = 1.0
    s = state_mult(state)
    if s is not None:
        s_k = s.get("k_pct", 1.0)
        s_bb = s.get("bb_pct", 1.0)
        s_hr = s.get("hr_pct", 1.0)
        s_bab = s.get("babip", 1.0)
        s_hbp = s.get("hbp_pct", 1.0)
    # THE HIT-BY-PITCH AND ITS RENORMALISER MOVE TOGETHER OR NOT AT ALL.
    # `cond` is carried on the matchup precisely so it can never disagree
    # with the rate it conditions on, and scaling one without the other
    # would divide every rate below by a denominator that no longer matches
    # what was drawn. A PLAIN MULTIPLIER, not `odds_mult`: there is no log5
    # pairing behind `hbp` — it is a league rate per arm — and the cell
    # multipliers were counted as exactly this ratio.
    #
    # Guarded on `!= 1.0` so an absent key leaves `hbp` and `cond` as the
    # objects they were, bit-identical rather than merely very close. That
    # is the same short-circuit `odds_mult` uses and the reason an empty
    # table reproduces the state-blind model exactly.
    hbp, cond = mu.hbp, mu.cond
    if s_hbp != 1.0:
        hbp = mu.hbp * s_hbp
        cond = 1.0 - mu.sac - hbp
    # Off the top: a sacrifice is a plate appearance that was never going to
    # be a strikeout or a walk, so it conditions everything below it.
    if rng.random() < mu.sac:
        return SAC
    if rng.random() < hbp:
        return HBP
    # Sacrifices and hit-by-pitches were taken off the top, so everything
    # below is conditional on neither firing. Without this rescale the
    # marginal rates all come out light by exactly SAC_RATE + HBP_RATE —
    # measured as K/9 8.16 against a real 8.44 when it was missing.
    # `/ cond` is NOT a modelling multiplier and stays as division: it is a
    # conditional-probability renormalisation, P(K | not sac, not hbp), and
    # it cannot exceed 1 because a strikeout is disjoint from both.
    k = odds_mult(log5(mu.b_k, p_k, mu.lg_k), mu.m_k * s_k, mu.lg_k) / cond
    if rng.random() < k:
        return K

    # Remaining probabilities are conditional on not having struck out, so
    # each is rescaled by what is left rather than used as a raw PA rate.
    #
    # THIS RAISES RATHER THAN CLAMPING, and the difference is the whole
    # lesson of the day. Probabilities that sum past one mean a CALLER
    # handed the model rates that cannot coexist — it is a bug upstream, not
    # a runtime state to smooth over. Clamping produces a defined but
    # meaningless answer: walks take the entire remainder and home runs and
    # balls in play stop existing, which is the silent-channel-goes-to-zero
    # failure this project cannot detect downstream, because a missing home
    # run rate just looks like a low one and a fitted constant absorbs it.
    #
    # Free to be strict: measured at ZERO occurrences in 529,581 plate
    # appearances, so nothing real trips it. It takes a .62 matchup
    # strikeout rate alongside a .69 walk rate. The next mechanism that
    # inflates a rate will find out immediately instead of three weeks
    # later.
    rest = 1.0 - k
    bb = odds_mult(log5(mu.b_bb, p_bb, mu.lg_bb), mu.m_bb * s_bb,
                   mu.lg_bb) / cond
    if bb > rest:
        raise ValueError(
            f"walk probability {bb:.4f} exceeds the {rest:.4f} left after a "
            f"{k:.4f} strikeout rate — these rates cannot coexist. "
            f"batter bb {mu.b_bb:.4f} k {mu.b_k:.4f}, "
            f"pitcher bb {p_bb:.4f} k {p_k:.4f}")
    if rest > 0 and rng.random() < bb / rest:
        return BB

    rest -= bb
    hr = odds_mult(log5(mu.b_hr, p_hr, mu.lg_hr), mu.m_hr * s_hr,
                   mu.lg_hr) / cond
    if hr > rest:
        raise ValueError(
            f"home run probability {hr:.4f} exceeds the {rest:.4f} left "
            f"after a {k:.4f} strikeout and {bb:.4f} walk rate — these "
            f"rates cannot coexist. batter hr {mu.b_hr:.4f}, "
            f"pitcher hr {p_hr:.4f}, multiplier {mu.m_hr:.4f}")
    if rest > 0 and rng.random() < hr / rest:
        return HR

    # Ball in play. The arsenal multiplier applies here too: a mix this
    # hitter handles well produces harder contact, not just more homers.
    babip = odds_mult(log5(mu.b_bab, p_bab, mu.lg_bab), mu.m_bip * s_bab,
                      mu.lg_bab)
    if rng.random() >= babip:
        # A ball in play the defence should have converted and did not.
        # Drawn HERE rather than from the whole plate appearance because an
        # error is specifically a fielding failure on a batted ball: a
        # strikeout or a walk cannot become one.
        return ROE if rng.random() < ROE_PER_OUT else OUT
    mix, r = mu.hit_mix, rng.random()
    if r < mix["1b"]:
        return B1
    return B2 if r < mix["1b"] + mix["2b"] else B3


# ── the hook ───────────────────────────────────────────────────────────
#
# Fitted to marginals, not to game state, and that is the honest limit of
# building this without play-by-play. The local record gives the hazard by
# inning (8% after the 3rd, 20% after the 4th, 46% after the 5th, 70% after
# the 6th, 84% after the 7th) and the effect of runs allowed on final length
# (16.4 outs at zero runs, 13.9 at five or more). What it cannot give is the
# state AT REMOVAL — only the totals — so the form below is asserted and its
# parameters tuned until the simulated marginals match those observed.
#
# Two properties are taken from the data rather than assumed:
#   * The decision happens between innings. Two thirds of starts end on a
#     boundary, so mid-inning removal is a separate, rarer event.
#   * Runs matter more than pitches at the low end. A starter at 70 pitches
#     having allowed six is gone; one at 95 having allowed none often is not.


@dataclass
class Hook:
    """Removal rule. Fitted by `calibrate.tune`, not asserted.

    The defaults below came out of a coordinate descent against the league's
    observed hazard curve, boundary share and threshold rates. REFIT after
    sacrifices and caught stealing were added: those cut the baserunners the
    mid-inning terms key on, so the old fit left the hook firing too late.
    Loss fell 0.0858 -> 0.0720 on the same target, then to 0.0668 after the
    league baselines were moved onto rotation starters and steals and HBP
    were added — a softer pitch curve (scale 11 -> 15) once the walk rate
    stopped running high — so unlike the
    constants table in NOTES-context-layer.md, these were not invented. They
    are still fitted to MARGINALS rather than to game state, which is the
    honest limit of doing this without play-by-play: the model can reproduce
    how often starters are pulled after the fifth without knowing that this
    one was pulled because he had thrown 28 pitches that inning.
    """
    #: Pitch count at which removal becomes even money at an inning end.
    #: Individual leashes override this — see `for_pitcher`.
    #:
    #: Lowered 92 -> 84 once REAL pitch counts existed. The old value was
    #: fitted in inflated pitch units (PITCH_COST over-billed 2.6%), so
    #: correcting the costs without moving this sent starters to 17.3 outs
    #: against a real 15.9.
    #:
    #: 84 -> 80 on the full season, ANCHORED to the measured pitch count
    #: (train-window mean 82.9) rather than fitted to outs. Fitting it to
    #: outs instead drives it to 74, which reproduces the out total by
    #: pretending starters throw 8 fewer pitches than they do.
    #:
    #: THE RESIDUAL THIS EXPOSES. At the pitch count that matches reality
    #: the simulator records ~16.0 outs against a real 15.11 — it gets about
    #: 6% more outs per pitch than real starters. No value of this constant
    #: fixes that, because it is the same left-skew defect below.
    #:
    #: KNOWN UNFIXABLE AT THIS FORM, and worth reading before tuning it
    #: again. Real starts are LEFT-SKEWED — mean 84.0, median 89 — because
    #: managers either let a starter cruise to ~95 or knock him out early,
    #: and only 12.2% ever reach 100. A single smooth logistic cannot be
    #: bimodal: scanned over centre 84-92, scale 6-15 and cap 105-112, no
    #: combination reaches mean 84 AND median 89 AND 12.2% over 100. The
    #: closest lands P(outs>=18) at 46.9% against a real 41.1%. That is the
    #: "no parameter reaches the target, so the mechanism is missing"
    #: signature: what is absent is a disaster mode, not a better constant.
    #:
    #: FITTED ON 38,485 REAL END-OF-INNING DECISIONS, 2026-08-26. See
    #: LEGACY_BOUNDARY below for what these were and why they changed.
    #:
    #: A KNEE WAS FITTED AND NOT SHIPPED. See `KNEE_BOUNDARY` — it is a
    #: better description of what managers do and a worse description of
    #: what we price, which is the sharpest case of that split so far.
    pitch_center: float = 49.5493
    #: How sharply the pitch-count term turns on. Larger is a softer curve.
    pitch_scale: float = 12.1293
    #: Where the pitch term would turn on, if `per_pitch_over` were non-zero.
    #: SHIPS INERT — the mechanism exists and the coefficient is 0.0, so the
    #: curve is linear. `KNEE_BOUNDARY` turns it on.
    pitch_knee: float = 60.0
    #: Log-odds per pitch beyond `pitch_knee`. Zero ships a linear logit.
    per_pitch_over: float = 0.0
    #: Added to the removal log-odds per run allowed so far.
    per_run: float = 0.1097
    #: Added per inning completed. Small and NEGATIVE once pitches are in
    #: the same model: inning and pitch count carry the same information and
    #: the fit gives it to pitches. Not evidence that late innings shorten a
    #: leash — evidence that pitches already say so.
    per_inning: float = 0.2515
    #: Baseline log-odds before any of the above.
    intercept: float = -5.1370
    # -- mid-inning removal --
    #
    # A third of real starts end mid-inning, and the first version of this
    # gated on "four runs allowed", which produced a simulator that ended
    # 81% of starts on a boundary against a real 66%. Managers do not wait
    # for a blowout: they pull on a rally, with a runner on and a pitch
    # count already high. So this is a per-batter hazard on the same terms
    # as the between-innings one, plus a term for traffic on the bases.
    mid_intercept: float = -5.0
    mid_per_run: float = 0.45
    #: Per runner currently on base. The rally term — this is what makes
    #: removal happen DURING the trouble rather than after it.
    mid_per_runner: float = 0.55
    #: Per unit of DAMAGE accumulated in the current inning. Distinct from
    #: the runner term: bases loaded on three singles and bases loaded on
    #: three walks look the same to a runner count and do not feel the same
    #: from the dugout.
    mid_per_damage: float = 0.25
    #: Nobody is left in past this regardless of the arithmetic. Measured:
    #: 0.7% of real starts reach 110 and the season maximum is 120.
    hard_pitch_cap: int = 110

    #: Per baserunner allowed across the whole outing, applied between
    #: innings alongside runs. Two starters with three runs each are not the
    #: same case if one has allowed four hits and the other eleven.
    #:
    #: NOTE the fit this came from also returns `per_margin` -0.0113 and it
    #: is NOT shipped — so the shipped boundary curve is the fitted one with
    #: the margin column zeroed. Deliberate: margin is worth its own
    #: measurement rather than arriving as a passenger on a shape change.
    per_baserunner: float = 0.0555
    #: Manager patience, as a log-odds offset applied to BOTH removal
    #: decisions. Negative means a longer leash.
    #:
    #: Fitted as a RESIDUAL, which is the only honest way to do it. A club
    #: whose starters go deep may simply have good starters, and the
    #: simulation already accounts for that — so using the raw team average
    #: would count rotation quality twice and hand a good staff a patient
    #: manager it may not have. `calibrate.fit_patience` measures observed
    #: length against what the model already predicts and attributes only
    #: what is left over.
    team_offset: float = 0.0

    #: Log-odds per run of LEAD his own team holds. A manager treats a
    #: starter at 1-0 and the same starter at 8-0 completely differently, and
    #: until now the model could not tell them apart: a single pitching side
    #: was simulated in isolation with no idea what its own offence had done.
    #:
    #: BOTH DEFAULT TO ZERO, so nothing changes until this is measured. The
    #: sign is not obvious in advance — a big lead buys a starter rope
    #: because the game is safe, and also gets him lifted because there is
    #: nothing left to protect — which is exactly why it should be fitted
    #: against observed removal timing rather than asserted.
    #: BOTH MEASURED 2026-08-29 AND BOTH STAY AT ZERO. 322,205 real starter
    #: decisions, 2023-2026, each curve fitted on its own population with an
    #: unregularised logistic and standard errors from the observed Fisher
    #: information (`scratchpad/hook_margin.py`):
    #:
    #:     curve        signed margin coefficient      z
    #:     boundary        +0.00479 +/- 0.00664      +0.7
    #:     mid-inning      -0.00566 +/- 0.00611      -0.9
    #:
    #: Powered to resolve 0.020 and 0.018 log-odds per run at 3 sigma, and a
    #: 0.05 injection is recovered at +0.050 and +0.054 — so these are
    #: answers, not an absent instrument.
    #:
    #: THE SIGNED FORM IS THE MIS-SPECIFICATION, WHICH IS THE WHOLE POINT.
    #: The docstring above asks whether a manager treats a starter
    #: differently when his own club is ahead, and the answer is no. What he
    #: responds to is the game being DECIDED, in either direction, which a
    #: signed term cannot represent and which `mid_per_abs_margin` below
    #: carries at 10.4 sigma. Fitting only the signed term returns
    #: approximately zero and would have closed the question the wrong way.
    per_margin: float = 0.0
    mid_per_margin: float = 0.0
    #: THE BLOWOUT TERM: log-odds per run of |score gap| on the MID-INNING
    #: decision. Negative — the further apart the score, the less likely a
    #: manager interrupts an inning to make a change. Counted on 248,568
    #: real mid-inning decisions.
    #:
    #: -0.08240 +/- 0.00792 (z -10.4), controlled for `inning`,
    #: `outs_before` and `bf` so it cannot be a game-clock effect arriving
    #: on the wrong coefficient — uncontrolled it reads -0.07329, so the
    #: clock is not what this is.
    #:
    #: STABILITY GATE PASSED, four seasons, same sign every year and never
    #: under 4.5 sigma: -0.0887 / -0.0734 / -0.0837 / -0.0950 for
    #: 2023/2024/2025/2026.
    #:
    #: THE RAW MARGINAL POINTS THE OTHER WAY AND IS THE CONFOUNDED ONE.
    #: Pull rate by |margin| within a pitch band RISES at 60-75 pitches
    #: (0.014 -> 0.025), because |margin| is entangled with runs allowed
    #: (mean 0.71 at |m|<2 against 2.33 at |m| 4-6) — a starter losing badly
    #: is usually losing badly BECAUSE of him. Hold runs and pitches fixed
    #: and it is monotone in every row (at one run allowed, 75-95 pitches:
    #: 0.073 / 0.074 / 0.051 / 0.027 across |m| 0-1 / 2-3 / 4-5 / 6+). The
    #: Hook already carries `runs`, so the CONDITIONAL effect is the one it
    #: needs.
    #:
    #: FITTED ON EVERY MID-INNING ROW, NOT ON LATE ONES, because
    #: `early_innings` is 0 and this branch therefore fires at every inning
    #: — the population it is fitted on is the population it is evaluated
    #: on. Late rows alone give -0.10531 (z -12.4) and early rows +0.01962
    #: (z +0.5); the early number is UNDERPOWERED, not a null, since 137,139
    #: rows carry only 549 pulls and it resolves 0.109 at 3 sigma. Shipping
    #: the pooled and smaller value is the conservative reading of that.
    mid_per_abs_margin: float = -0.0824
    #: THE DOMINANCE TERM: log-odds per unit of STRIKEOUT RATE SO FAR on the
    #: mid-inning decision. Negative — the better he is going, the less
    #: likely he is interrupted. This is the mechanism TODO item 7 is about.
    #:
    #: WHY THE HOOK NEEDED ONE AT ALL. Every other input to both curves is
    #: TRAFFIC or WORKLOAD — pitches, runs, baserunners, bases occupied, the
    #: inning. Nothing told it how well he was throwing, so the simulator
    #: could not tell a dominant night from a lucky one, and a real
    #: seven-inning start is a SELECTED population earned by missing bats.
    #: Measured consequence: K per 27 outs by length runs 8.42 / 8.05 /
    #: 7.51 against a real 8.33 / 7.98 / 8.49 — the model keeps DECLINING
    #: where reality JUMPS.
    #:
    #: -1.5130 +/- 0.1587 (z -9.5) over 248,568 real mid-inning decisions,
    #: controlled for `pitches`, `bf`, `runs`, `inn_br`, `onbase`, `inning`
    #: AND `abs_margin`. That control set is the whole argument: a strikeout
    #: is an out that allowed no baserunner and costs ~4.97 pitches against
    #: ~3.25 for a ball in play, so dropping any one of those columns hands
    #: its variance straight to this one.
    #:
    #: STABILITY GATE PASSED: -1.797 / -1.111 / -1.214 / -1.830 for
    #: 2023/2024/2025/2026, every year negative, z -3.5 to -5.9.
    #:
    #: SIZE IN BASEBALL TERMS: the p10-to-p90 spread of `k_rate` is 0.444,
    #: so a dealing starter carries -0.672 log-odds against a struggling one
    #: at the SAME pitch count, runs, traffic and inning — a bit under half
    #: the odds of being pulled mid-inning.
    #:
    #: THE BOUNDARY CURVE GETS NO SUCH TERM. Same fit on its own 73,637
    #: rows gives -0.334 +/- 0.161, z -2.1, with no season individually
    #: significant (-0.4 / -0.7 / -1.0 / -1.4). Sign-stable but weak; that
    #: is a DIRECTION, not a finding, and it is recorded rather than wired.
    late_mid_per_k_rate: float = -1.5130
    #: THE BULLPEN, and it is the FIRST mechanism that belongs on BOTH
    #: curves. Margin and dominance are mid-inning only; the boundary
    #: decision took neither, and was deaf to every in-game signal tried —
    #: signed margin +0.7 sigma, |margin| sign-flipping across seasons,
    #: strikeout rate -2.1 with no season individually significant. It is
    #: not deaf. "Does he come back out" is a RESOURCE decision.
    #:
    #: Counted on 322,205 real decisions with 100% coverage
    #: (`scratchpad/pen_state.py`), fitted with these two columns alone so
    #: the coefficients match what ships:
    #:
    #:     column      boundary                 mid-inning
    #:     pen_back2   -0.09362 +/-0.0168 (-5.6)  -0.08883 +/-0.0160 (-5.6)
    #:     pen_rest    +0.18820 +/-0.0293 (+6.4)  +0.17132 +/-0.0272 (+6.3)
    #:
    #: IT IS ABOUT AVAILABILITY, NOT VOLUME, and that is the finding. Raw
    #: reliever pitch totals are NULL on both curves — yesterday's pen
    #: pitches -0.8 and -0.5, three-day pitches +1.5 and +1.6. What predicts
    #: the hook is how many arms CANNOT go: `pen_back2` counts relievers who
    #: worked on BOTH of the club's last two days, which is the real
    #: unavailability rule a manager uses. A used-up pen keeps the starter
    #: out there; a rested one gets him lifted.
    #:
    #: STABILITY GATE PASSED 8/8 — sign held in all four seasons on both
    #: curves. All four pre-registered signs correct. Control fired.
    #:
    #: BOTH CONFOUNDS RUN AGAINST THE RESULT, which is why it is believable.
    #: A club whose pen is gassed probably lost a long game yesterday, so it
    #: is a bad club with a bad starter — and a bad starter is pulled
    #: EARLIER, pushing `pen_back2` POSITIVE. It comes out negative. And an
    #: off day rests the STARTER too, which should make him go deeper and
    #: push `pen_rest` NEGATIVE. It comes out positive.
    #:
    #: CENTRED on `PEN_BACK2_BASELINE` / `PEN_REST_BASELINE`, the same rule
    #: as `K_RATE_BASELINE`: these buy discrimination between games and must
    #: not move the calibrated level.
    #:
    #: IT NEEDS NO RELIEVER DEPLOYMENT MODEL. These are CLUB-LEVEL counts
    #: read off the schedule. Which specific arm gets the call is a separate
    #: question and this does not depend on it.
    #: THE HIGH-PITCH-COUNT BRANCH. A log-odds offset added to BOTH curves
    #: once a starter passes `high_pitch_threshold`, because the shipped
    #: curves are TOO FLAT: they pull too many men in the middle of a start
    #: and too few at the end of one.
    #:
    #: COUNTED by scoring every real decision through the SHIPPED hook —
    #: not through a refitted logistic — so the miss corrected is the one
    #: that actually ships (`scratchpad/late_branch.py`):
    #:
    #:     pitches      boundary shipped/actual   mid shipped/actual
    #:      0-60           0.0093 / 0.0105          0.0029 / 0.0030
    #:      60-75          0.1123 / 0.0570          0.0268 / 0.0172
    #:      75-90          0.3542 / 0.2659          0.0783 / 0.0671
    #:      90-100         0.6406 / 0.7837          0.1721 / 0.2036
    #:      100-130        0.8087 / 0.9717          0.3101 / 0.4026
    #:
    #: Above 90 pitches the offsets are +0.8550 +/- 0.0358 (boundary, 24
    #: sigma) and +0.2893 +/- 0.0219 (mid-inning, 13 sigma). Solved by
    #: bisection to match the observed rate, not searched on a grid, so
    #: neither can pin at an edge.
    #:
    #: WHY A BRANCH AND NOT A REFIT. Refitting the WHOLE boundary curve on
    #: late rows was tried and makes the simulation worse (mean outs 16.49
    #: -> 16.74): that curve is evaluated at every pitch count, so
    #: calibrating it on late rows alone makes it under-pull early. The
    #: rule is "fit on the restricted population only when the curve fires
    #: only there and something else covers the rest" — which is exactly a
    #: branch gated above a threshold with the existing curves unchanged
    #: below. Same shape as `early_innings` at the other end of a start.
    #:
    #: THE POOLED VALUE SHIPS AND IT IS THE CONSERVATIVE ONE. The offsets
    #: RISE monotonically across seasons — boundary +0.63 / +0.84 / +0.95 /
    #: +1.01 and mid +0.02 / +0.31 / +0.34 / +0.47 for 2023-2026 — which
    #: looks like managers getting quicker with a tiring starter every
    #: year. Shipping 2026 alone would correct more and rest on a quarter
    #: of the sample; the pooled figure under-corrects today by about 15%
    #: and cannot be accused of chasing a trend. Revisit with a
    #: recency-weighted count, not by picking the last season.
    #:
    #: WHAT THIS DOES NOT FIX, and it is in the table above: the curves
    #: also OVER-pull between 60 and 90 pitches (ratio 1.97 and 1.55 at
    #: 60-75). The real defect is that one logistic is too flat across the
    #: whole range. This branch corrects the top half only.
    high_pitch_threshold: int = 90
    high_pitch_bnd: float = 0.8550
    high_pitch_mid: float = 0.2893
    per_pen_back2: float = -0.09362
    per_pen_rest: float = 0.18820
    mid_per_pen_back2: float = -0.08883
    mid_per_pen_rest: float = 0.17132

    #: THE LAYOFF, on BOTH curves. Log-odds added when a starter has been
    #: away longer than a normal turn: a STEP at `LAYOFF_MIN` days plus a
    #: per-day SLOPE beyond it. Positive — a man back from an absence is
    #: pulled sooner. Counted on 284,706 in-season starter decisions,
    #: `scratchpad/layoff.py`.
    #:
    #: WHY THE OLD NULL DID NOT SETTLE IT, and this is the whole reason the
    #: mechanism was missing. `NOTES-context-layer.md:2250` screened
    #: `days rest +0.014` on the outs residual and it was read as an
    #: absent effect. It is a LINEAR slope across a rest distribution that
    #: is 74% at five or six days with under 4% past ten — the flat middle
    #: swamps a step in the tail. Mis-specification and absence produce
    #: identical output, which is exactly what CLAUDE.md warns about.
    #:
    #: IT IS AN EXPOSURE EFFECT, NOT A STUFF EFFECT, and that is why it
    #: belongs on the hook rather than on the rates. Within-pitcher,
    #: within-season, against his own 4-9 day starts: `d_BF` is -1.2 to
    #: -1.8 batters (z -4.3 to -7.1) while `d_K/BF` is null in every
    #: bucket (z +0.3, -1.6, +1.0, +0.6). He is not worse per batter, he
    #: is left in for fewer of them.
    #:
    #:     curve        step (>= 10d)        slope (per day beyond)
    #:     boundary   +0.63863 +/-0.0889   +0.04137 +/-0.00497
    #:     mid        +0.37561 +/-0.0790   +0.02306 +/-0.00449
    #:
    #: Controlled for everything both shipped curves already read, plus
    #: `leash` — the starter's own recent length — which is the confound
    #: control. Positive control fired on both curves at the size CLAIMED:
    #: injected +0.60, recovered +0.550 (boundary) and +0.709 (mid). At
    #: +0.25 the boundary curve reads MISSED (+0.214 +/- 0.075, z 2.9) and
    #: that is the harness stating its resolution, not a bad fit.
    #:
    #: THE GAP IS READ FROM A UNION OF TWO START RECORDS and the reason is
    #: in `sim._start_dates`: a MISSING start does not weaken this feature,
    #: it INVERTS it, turning a five-day turn into a ten-day layoff. The
    #: first version of this fitted and served off sources that each miss
    #: ~9-13% of starts, which fired the term on 18.32% of holdout starts
    #: against 7.76% in the fitted population and moved a CENTRED term's
    #: level by 0.19 outs. Both sides now read the same index.
    #:
    #: THE CONFOUND RUNS AGAINST THE RESULT, which is why it is
    #: believable. A pitcher returning from the IL may simply be a worse or
    #: more fragile pitcher, and a worse pitcher is pulled earlier for
    #: reasons that have nothing to do with the layoff — that pushes these
    #: POSITIVE, the direction they came out. `leash` absorbs what it can.
    #:
    #: STABILITY GATE PASSED 8/8 on the COMBINED spec — both terms, both
    #: curves, sign held in all four seasons. Gated on the combined fit
    #: rather than each term alone, because a term can be stable by itself
    #: and unstable beside its partner:
    #:
    #:     boundary  step +3.1/+3.6/+3.9/+3.7   slope +4.2/+4.0/+6.0/+1.8
    #:     mid       step +1.9/+3.6/+2.7/+0.9   slope +2.6/+1.8/+3.3/+3.7
    #:
    #: BOTH TERMS SHIP, not just the step. The counted outs buckets look
    #: flat past ten days and a step alone was the first specification;
    #: the shape check refuted it, with the slope carrying a higher z than
    #: the step on the boundary curve (+16.2 against +14.7 when each is
    #: fitted alone). The effect grows with the absence.
    #:
    #: CENTRED on `LAYOFF_STEP_BASELINE` / `LAYOFF_SLOPE_BASELINE`, the
    #: same rule as `K_RATE_BASELINE` and the bullpen pair: a starter on a
    #: normal turn must contribute nothing and the calibrated level must
    #: not move. This buys discrimination between starts.
    #:
    #: FITTED ON IN-SEASON GAPS ONLY. A pitcher opening a season has had a
    #: spring to build up and is not the same case as one returning in
    #: August; `game.Side.layoff_gap` passes None across a season break so
    #: the term contributes nothing there rather than a guess.
    per_layoff: float = 0.63863
    per_layoff_day: float = 0.04137
    mid_per_layoff: float = 0.37561
    mid_per_layoff_day: float = 0.02306
    #: REFIT ON LATE-ONLY DECISIONS. The pooled fit averaged 20,994 late
    #: rows at a 6.29% pull rate together with 26,693 early ones at 0.65%,
    #: and the early population dominates by count — so the late curve came
    #: out far too flat. At 90+ pitches the real per-batter mid-inning pull
    #: rate is 33.80% and the pooled hook gave 7.24%, which is why nobody
    #: got yanked mid-inning late and the boundary share reached 90% in the
    #: eighth against a real 54%.
    #:
    #: Now that the early innings have their own branch, each is fitted on
    #: its own population. `mid_per_runner` and `mid_per_damage` are left at
    #: their old values but are largely subsumed by this term — baserunners
    #: ALLOWED in the inning is what the fit found, not bases occupied.
    #: THE LATE MID-INNING BRANCH CARRIES ITS OWN COEFFICIENTS rather than
    #: reusing `pitch_center`/`pitch_scale`. Those are SHARED with the
    #: boundary hook, so refitting them for one branch silently refits the
    #: other — and layering `mid_per_runner` and `mid_per_damage` on top of
    #: a fit that already contains the traffic double-counts it. Doing both
    #: at once put the hook at 53% where the measurement says 34%.
    #:
    #: Fitted on the 20,994 late mid-inning decisions alone. Reproduces
    #: 0.33/2.08/9.10/33.80% by pitch count against 0.26/1.96/9.84/32.17%.
    #: An OFFSET from `mid_intercept`, never an absolute level. The same
    #: mistake was made and fixed for the early branch earlier the same day:
    #: callers disable the hook by driving `mid_intercept` to -99 —
    #: team_offset, the patience fits and the never-pull tests all use that
    #: idiom — and a branch carrying its own absolute intercept goes on
    #: pulling people regardless.
    late_mid_offset: float = -5.5145
    late_mid_per_pitch: float = 0.0839
    late_mid_per_inning_br: float = 0.5269
    late_mid_per_run: float = 0.1165
    #: Bases OCCUPIED, distinct from baserunners allowed this inning. Both
    #: are in the decision — bases loaded having scored nobody is a hook,
    #: and so is a five-run inning that ended with the bases empty. Dropping
    #: it lost 2.71 -> 18.05% of real discrimination and broke two checks
    #: that correctly guard the hook responding to traffic on the bases.
    late_mid_per_onbase: float = 0.3002
    #: Multiplies `MID_INNING_RUN_OFFSET`. DEFAULT OFF — the mechanism is
    #: real and correctly measured, but switching it on makes
    #: `calibrate.loss` worse (0.206 -> 0.221) because the model has a
    #: SECOND defect this one amplifies. See the table's note.
    mid_per_inning_run: float = 0.0
    #: EARLY INNINGS ARE A DIFFERENT DECISION and the single mid-inning
    #: hazard cannot hold both. Measured across 47,687 mid-inning decisions,
    #: at nought runs in the current inning the real pull rate is 0.37% in
    #: innings 1-3 and 4.58% from the fourth on — a 12x different baseline —
    #: and the same pitch count means different things: 70 pitches in the
    #: third is pulled 3.7x more often than 70 pitches in the fifth.
    #:
    #: Counted from the early marginals, not searched. The curve is much
    #: SHALLOWER and sits far to the right (scale 18.8, centre 131 against
    #: the late hook's ~11-15 and ~86-92), which says pitch count barely
    #: matters before the fourth and what does is the disaster in progress.
    #:
    #: FITTED JOINTLY on the 26,693 early mid-inning decisions, over pitch
    #: count, the measured run offset and baserunners allowed this inning.
    #: Fitting the pitch marginal alone and layering the other terms on top
    #: double-counts them, because the marginal already averages over every
    #: run state — the first attempt did exactly that and produced a hook
    #: that pulled nobody.
    #:
    #: Reproduces what it was fitted to: 0.37/0.58/1.57/2.83/8.42% by runs
    #: in the inning against 0.32/0.84/1.73/3.03/7.71% modelled.
    #:
    #: DEFAULT OFF. Measured on 1,624 games: it fixes the disaster tail
    #: almost exactly — sub-two-inning starts 0.31% -> 3.16% against a real
    #: 2.68%, and the share of variance carried by sub-four-inning starts
    #: 35.8% -> 47.3% against a real 49.6% — but widens the outs SD from
    #: 3.95 to 4.47 where reality is 3.99, and costs 0.005 of loss.
    #:
    #: The tail miss is left standing rather than bought with spread. Set to
    #: 3 to enable both early branches.
    early_innings: int = 0
    #: Carried as an OFFSET from `mid_intercept`, not as its own absolute
    #: level. An absolute one silently broke every caller that disables the
    #: hook by driving `mid_intercept` to -99 — team_offset, the patience
    #: fits and the never-pull tests all use that idiom, and the early
    #: branch went on pulling people regardless.
    early_offset: float = -2.6506
    early_per_pitch: float = 0.04556
    early_per_run_offset: float = 0.0310
    early_per_inning_br: float = 0.5254
    #: THE BOUNDARY BRANCH NEEDED ONE TOO, and it is the one that matters.
    #: Real removals in the first inning are 79.8% boundary; the simulator
    #: produced 2.6%, because the boundary hook carries the same pitch-count
    #: veto — at 30 pitches its term is deeply negative and it cannot fire.
    #: With both hooks silent early, the only path out was mid-inning, so
    #: every early removal came through the wrong branch.
    #:
    #: The gap it leaves behind is NOT uniform, which is why a shared
    #: intercept shift was rejected: boundary share runs -77 points against
    #: reality in the first inning and +36 in the eighth, and one knob moves
    #: both ends together.
    #:
    #: Fitted on 22,227 early boundary decisions. Weak on its own (AUC
    #: 0.626) because a between-innings call at 40 pitches is close to a
    #: coin flip conditional on what the model can see — but the LEVEL is
    #: what was missing, not the ranking.
    early_bnd_offset: float = -0.6683
    early_bnd_per_pitch: float = 0.01616
    early_bnd_per_run_offset: float = 0.2278
    early_bnd_per_run: float = 0.1859

    #: THE EARLY-EXIT MIXTURE. Off at 0.0, which is the shipped state.
    #:
    #: A start is drawn as one of two kinds before it is simulated. With
    #: probability `early_exit_p` it is an EARLY EXIT and ends at an outs
    #: total sampled from `EARLY_EXIT_DIST`; otherwise the hook runs and
    #: cannot pull before `early_exit_floor`.
    #:
    #: WHY A MIXTURE AND NOT A STEEPER CURVE. Real starts are bimodal and a
    #: single logistic cannot be — see `pitch_center`, where a scan over the
    #: whole parameter space failed to reach the mean, the median and the
    #: 100-pitch share together. Day seven's `early_innings` branches chased
    #: the same tail inside the curves and bought it with spread (SD 4.47
    #: against a real 3.99), which is why they ship off.
    #:
    #: THE FLOOR DOES TWO JOBS and the second is the one that is easy to
    #: miss: it suppresses the hook below itself. Without that the two modes
    #: overlap — the hook would keep producing its own short starts on top
    #: of the lump — and short starts would be counted twice.
    early_exit_p: float = 0.0
    early_exit_floor: int = 0

    def removal_p(self, pitches: int, runs: int, innings: int,
                  baserunners: int = 0, margin: int = 0,
                  inning_runs: int = 0,
                  pen: tuple[float, float] | None = None,
                  layoff_gap: int | None = None) -> float:
        """P(pulled) evaluated at the end of a completed inning.

        `pen` is (arms unavailable, days of club rest) from
        `sim.pen_state`. None means league-neutral and contributes exactly
        zero — see `per_pen_back2` for why this curve has it at all.

        `layoff_gap` is days since this starter's previous START, or None
        for unknown / across a season break. See `per_layoff`.
        """
        if self.early_innings and innings <= self.early_innings:
            return _sigmoid(self.intercept + self.early_bnd_offset
                            + self.team_offset
                            + self.early_bnd_per_pitch * pitches
                            + self.early_bnd_per_run_offset
                            * inning_run_offset(inning_runs)
                            + self.early_bnd_per_run * runs
                            + self.per_margin * margin
                            # Carried into the inert branch too. It ships
                            # with `early_innings` 0 so this never fires,
                            # and leaving the term out would put a silent
                            # hole in the mechanism the day it is enabled.
                            + self._layoff(layoff_gap, self.per_layoff,
                                           self.per_layoff_day))
        base = (self.intercept - PITCH_HAZARD_BND_ANCHOR
                + pitch_hazard(pitches, PITCH_HAZARD_BND)
                if (USE_PITCH_HAZARD and USE_PITCH_HAZARD_BND) else
                (self.intercept
                 + (pitches - self.pitch_center) / self.pitch_scale
                 + self.per_pitch_over * max(0.0, pitches - self.pitch_knee)
                 + (self.high_pitch_bnd
                    if pitches >= self.high_pitch_threshold else 0.0)))
        return _sigmoid(base + self.team_offset
                        + pxi(pitches, innings, PXI_BND)
                        + self.per_run * runs
                        + self.per_baserunner * baserunners
                        + self.per_margin * margin
                        + self.per_inning * innings
                        + self._pen(pen, self.per_pen_back2,
                                    self.per_pen_rest)
                        + self._layoff(layoff_gap, self.per_layoff,
                                       self.per_layoff_day)
                        )

    @staticmethod
    def _pen(pen, c_back2: float, c_rest: float) -> float:
        """The bullpen contribution, CENTRED, shared by both curves.

        One helper rather than two copies: the centring rule is the thing
        most likely to be got right once and wrong the second time, and
        this project has a recorded case of exactly that (two copies of a
        centring rule is how one of them ended up one-sided).
        """
        if pen is None:
            return 0.0
        back2, rest = pen
        return (c_back2 * (back2 - PEN_BACK2_BASELINE)
                + c_rest * (rest - PEN_REST_BASELINE))

    @staticmethod
    def _layoff(gap: int | None, c_step: float, c_slope: float) -> float:
        """The layoff contribution, CENTRED, shared by both curves.

        `gap` is days since his previous START, or None when it is not
        known or does not apply — a season opener, or a pitcher with no
        prior start in the record. None contributes exactly zero, the same
        missing-group rule as `_pen`, `patience` and `leash`.

        One helper rather than two copies for the reason `_pen` gives: a
        centring rule is the thing most likely to be got right once and
        wrong the second time, and this project has a recorded case of
        exactly that.
        """
        if gap is None or not USE_LAYOFF:
            return 0.0
        step = 1.0 if gap >= LAYOFF_MIN else 0.0
        slope = float(max(0, min(gap, LAYOFF_GAP_CAP) - LAYOFF_MIN))
        return (c_step * (step - LAYOFF_STEP_BASELINE)
                + c_slope * (slope - LAYOFF_SLOPE_BASELINE))

    def mid_removal_p(self, pitches: int, runs: int, on_base: int,
                      inning_damage: float = 0.0, margin: int = 0,
                      inning_runs: int = 0, inning: int = 0,
                      inning_br: int = 0,
                      k_rate: float | None = None,
                      pen: tuple[float, float] | None = None,
                      layoff_gap: int | None = None) -> float:
        """P(pulled) evaluated after a batter, inning still alive.

        `inning_runs` is what is going wrong RIGHT NOW; `runs` is the whole
        start. Without the former the model cannot pull anybody early: a
        five-run first inning is about 30 pitches, where the pitch term sits
        at -3.3 log-odds (-6.3 under the tuned parameters) and no coefficient
        in the fitted range climbs out of it. The consequence was a truncated
        disaster tail — starts under two innings happen 1.6% of the time and
        the simulator produced 0.1% — and since half the real variance in
        starter length lives in that tail, the outs distribution came out too
        narrow and the tuner compensated by steepening `pitch_scale` until it
        pinned at its grid edge.
        """
        if inning and self.early_innings and inning <= self.early_innings:
            # Workload is not why anybody comes out in the first three. The
            # late branch's terms are deliberately NOT reused: these
            # coefficients were fitted together, and adding `mid_per_runner`
            # or `mid_per_damage` on top would count the same traffic twice.
            return _sigmoid(self.mid_intercept + self.early_offset
                            + self.team_offset
                            + self.early_per_pitch * pitches
                            + self.early_per_run_offset
                            * inning_run_offset(inning_runs)
                            + self.early_per_inning_br * inning_br
                            + self.mid_per_margin * margin
                            # See the boundary branch: inert today, and a
                            # silent hole the day `early_innings` moves.
                            + self._layoff(layoff_gap, self.mid_per_layoff,
                                           self.mid_per_layoff_day))
        mbase = (self.mid_intercept - PITCH_HAZARD_MID_ANCHOR
                 + pitch_hazard(pitches, PITCH_HAZARD_MID)
                 if USE_PITCH_HAZARD else
                 (self.mid_intercept + self.late_mid_offset
                  + self.late_mid_per_pitch * pitches
                  + (self.high_pitch_mid
                     if pitches >= self.high_pitch_threshold else 0.0)))
        return _sigmoid(mbase
                        + self.team_offset
                        + pxi(pitches, inning, PXI_MID)
                        + self.late_mid_per_inning_br * inning_br
                        + self.late_mid_per_run * runs
                        + self.late_mid_per_onbase * on_base
                        + self.mid_per_margin * margin
                        # THE BLOWOUT TERM. Unsigned on purpose: a manager
                        # stops interrupting innings once the game is
                        # decided, and it is decided in both directions.
                        # The signed term above measures zero.
                        + self.mid_per_abs_margin * abs(margin)
                        # THE DOMINANCE TERM, and it is CENTRED. See the
                        # parameter's docstring for why the level must not
                        # move here when it does move for the blowout term.
                        + self.late_mid_per_k_rate
                        * ((K_RATE_BASELINE if k_rate is None else k_rate)
                           - K_RATE_BASELINE)
                        + self._pen(pen, self.mid_per_pen_back2,
                                    self.mid_per_pen_rest)
                        + self._layoff(layoff_gap, self.mid_per_layoff,
                                       self.mid_per_layoff_day)
                        + self.mid_per_inning_run
                        * inning_run_offset(inning_runs))


#: Log-odds ADDED to the mid-inning hook per run allowed in the CURRENT
#: half-inning, relative to a clean one. COUNTED, not fitted: the real
#: per-batter pull rate under 60 pitches, where workload is not the reason a
#: manager moves — 0.32% through a clean inning, 5.59% once four are in.
#:
#: A LEAST-SQUARES SLOPE THROUGH THESE POINTS IS THE WRONG SHAPE and was
#: tried first. The real hazard is FLAT from nought to one run (0.32% ->
#: 0.43%) and then climbs steeply; a linear fit charges +0.724 at one run
#: where the truth is +0.296. One-run innings are common — 4,150 of the
#: measured decisions against 376 at four-plus — so overstating the common
#: cell dominates. It produced starts of 7-11 outs at twice the real rate,
#: pushed the outs SD from 4.43 to 4.94 against a real 3.99, and made
#: `calibrate.loss` worse (0.206 -> 0.226) while correctly fixing the deep
#: tail it was built for.
#:
#: Fitting five measured points is exactly the move this project forbids:
#: hand a counted quantity to a search and it goes back to absorbing other
#: defects.
#:
#: THE TABLE IS RIGHT AND IT IS STILL OFF BY DEFAULT. It does exactly what
#: it was built for — starts of under two innings go 0.42% -> 1.25% against
#: a real 1.69%, and the share of variance carried by sub-four-inning starts
#: goes 41.6% -> 49.5% against a real 49.6%. But it exposes a defect that
#: predates it: the model already produces far too many starts in the 7-11
#: out range (6.18% and 5.28% against a real 3.57% and 3.69%), and this term
#: roughly doubles the excess. Real starts are bimodal — bombed out early,
#: or four innings and up — and the middle is genuinely rare. The simulator
#: has a smooth left tail either way.
#:
#: So the honest state is a correct mechanism sitting on top of a wrong
#: shape. Turning it on before the 7-11 range is understood buys the deep
#: tail at the cost of the bulk, which is the trade `calibrate.loss` is
#: reporting.
#: The league mean strikeout rate at a mid-inning removal decision, counted
#: on the same 248,568 rows `late_mid_per_k_rate` was fitted on — the MEAN
#: OF THE PER-DECISION RATE, which is the statistic the term is centred
#: against, not the ratio of the summed totals (0.2260). The two differ for
#: a reason that is the whole point of the mechanism; see below.
#:
#: THE DOMINANCE TERM IS CENTRED ON THIS, AND THE BLOWOUT TERM IS NOT.
#: The difference is deliberate and is about what each one is for:
#:
#:   * `mid_per_abs_margin` ships UNCENTRED because the level was WRONG when
#:     it arrived — mean outs sat at 15.68 against a real 15.82 — and the
#:     term moved it onto the actual without anything being solved for.
#:   * this one ships CENTRED because the level is now RIGHT. Uncentred it
#:     would subtract 1.5130 * 0.2323 = 0.351 log-odds from every
#:     mid-inning decision and suppress pulls across the board, which is a
#:     LEVEL change nobody measured riding in on a SPREAD coefficient that
#:     was.
#:
#: Centring makes the term mean-zero over the league, so it buys
#: DISCRIMINATION between starts — which is the defect — and leaves the
#: calibrated level alone. Solving the intercept to absorb an uncentred
#: shift would be fitting a level, which this project forbids.
#:
#: THE MEAN-OF-RATIOS AND THE RATIO-OF-SUMS DISAGREE, AND THAT DISAGREEMENT
#: IS THE DEFECT ITSELF — worth reading before anyone "fixes" this constant
#: to the tidier 0.2260. Measured at the hook, 20,712 simulated calls
#: against 248,568 real decisions:
#:
#:                        mean of ratios   ratio of sums
#:     REAL                      0.2276          0.2260
#:     SIM (before this term)    0.2002          0.2254
#:
#: The ratio of sums agrees to four decimals — the simulator's strikeout
#: RATE is right, as every other measurement here has said. What differs is
#: how the decisions are WEIGHTED. In reality the mean of ratios sits ABOVE
#: the ratio of sums, because a high-strikeout starter lasts longer and
#: therefore accumulates more decisions. In the simulator it sits BELOW,
#: because `PITCH_COST` bills a strikeout 4.97 pitches against 3.25 for a
#: ball in play, so a dominant night actively SHORTENS a simulated start.
#: The selection runs backwards. That is TODO item 7 in one number, and it
#: is why the sim's k_rate at the hook needs no correction as an INPUT.
K_RATE_BASELINE = 0.2276

#: League means of the two bullpen columns, over the same 322,205 decisions
#: they were fitted on. Both hook curves centre on these, so a club with an
#: ordinary pen contributes exactly nothing and the calibrated removal level
#: is untouched — the same rule as `K_RATE_BASELINE`.
#:
#: `pen_back2` runs p10 0 to p90 2; `pen_rest` p10 1 to p90 2.
PEN_BACK2_BASELINE = 0.6943
PEN_REST_BASELINE = 1.1791

#: Off restores the pre-measurement engine exactly. No random variate is
#: involved either way, so OFF is bit-identical rather than merely close.
USE_PEN_STATE = True

#: Days since a starter's previous START at or beyond which the layoff step
#: fires. Ten is where the counted outs effect first clears three sigma
#: (-0.81 outs, z -4.0) and it is the first boundary past a normal turn: a
#: five-man rotation is four to six days and seven to nine covers a skipped
#: turn or an off day. Ten means something happened.
LAYOFF_MIN = 10

#: The slope is CAPPED here so a 120-day return does not run the hook off a
#: cliff on one row. The fit used the same cap, so the shipped coefficient
#: and the fitted one describe the same feature — uncapping at serve time
#: would extrapolate a slope past every gap it was measured on. In-season
#: gaps run p50 6, p90 7, p99 42.
LAYOFF_GAP_CAP = 45

#: League means of the two layoff columns over the 284,706 in-season
#: decisions they were fitted on. Both curves centre on these, so a starter
#: on a normal turn contributes exactly zero and the calibrated removal
#: level is untouched — the same rule as `K_RATE_BASELINE` and the bullpen
#: pair.
LAYOFF_STEP_BASELINE = 0.0668
LAYOFF_SLOPE_BASELINE = 0.7262

#: Off restores the pre-layoff engine exactly, and like `USE_PEN_STATE` it
#: is bit-identical rather than close: no random variate is involved.
USE_LAYOFF = True

#: TONIGHT'S STUFF. A starter's strikeout rate is drawn once per start
#: around his own rate — some nights the slider bites and some nights it
#: does not — and until 2026-08-29 the engine had NO per-start rate
#: variation at all. Every night a pitcher was exactly himself and all the
#: spread came from the dice.
#:
#: COUNTED, NOT FITTED, and the count refuted the fitted value.
#: `scratchpad/k_dispersion.py`: 4,777 starts across three holdout windows
#: (2024/2025/2026, rates frozen before 1 July of each), 555
#: pitcher-windows with two or more starts. Each start is a
#: POISSON-BINOMIAL under the model — the expected strikeouts already carry
#: log5, the specific nine, the times-through-the-order decay and the
#: home/road split, so anything the model already contains cannot show up
#: here as dispersion.
#:
#:     raw sig2      +0.02203
#:     minus bias    -0.00167   (the estimator's own, from its zero row)
#:     COUNTED        0.02369   95% CI [0.01615, 0.03119], sd 0.00384
#:     calibrated     0.02642   -> SIGMA 0.1625, 6.2 sigma from zero
#:
#: THE FITTED VALUE WAS 0.20 AND IT IS WRONG BY 4.2 SD. It was chosen the
#: day before because it made the strikeout sd land exactly on 2.49, which
#: is solving for a spread. It overstated the mechanism by 50% in variance.
#: This is the clearest case in the project's history of a counted quantity
#: correcting a tuned one, and it went against the person who tuned it.
#:
#: THE CALIBRATED VALUE SHIPS, NOT THE RAW ONE. The positive control shows
#: the estimator UNDERSHOOTS at small sigma (0.10 comes back as 0.070), so
#: the raw 0.154 is inverted through the injected-to-recovered curve to get
#: what must be INJECTED to reproduce reality. That inversion is legitimate
#: only because the curve was built by injection rather than fitted.
#:
#: STRIKEOUTS ONLY, and the restriction is the finding. The four-channel
#: version of this — one latent quality factor also loading on walks, home
#: runs and balls in play — was measured and rejected: it widened TRAFFIC,
#: which is what the hook integrates, so it wrecked the outs distribution
#: for the strikeout gain. Loading `k_pct` alone costs 0.0064 of outs CRPS
#: against that version's 0.0278. CARRY THE CAVEAT: this counted `k_pct`
#: and nothing else. That the other channels are UNDISPERSED is NOT
#: established — only that they are not dispersed by the same factor at the
#: same size. Each deserves its own count.
START_K_SIGMA = 0.1625

#: Off restores the pre-measurement engine exactly, and it must consume no
#: random variate when off or every downstream draw shifts and the A/B
#: stops being paired.
USE_START_SHARPNESS = True


def sharpen(p: "PitcherRates", rng: random.Random,
            sigma: float | None = None) -> "PitcherRates":
    """One start's stuff, as a multiplier on the strikeout rate alone.

    CENTRED ON PURPOSE, and this is not cosmetic. A bare `exp(sigma * z)`
    has mean `exp(sigma^2 / 2)` — at 0.1625 that is +1.33% of strikeouts
    added to every start, which is a LEVEL change nobody measured riding in
    on a SPREAD that was. Subtracting `sigma^2 / 2` makes the multiplier
    mean exactly one, so this buys dispersion and leaves the calibrated
    strikeout level alone. The same rule as `K_RATE_BASELINE` above.

    The measurement was taken around each pitcher's OWN rate, so a mean-one
    multiplier is what it implies: his shipped `k_pct` is the average of his
    nightly stuff, not his floor.
    """
    s = START_K_SIGMA if sigma is None else sigma
    if not s:
        return p
    z = rng.gauss(0.0, 1.0)
    return replace(p, k_pct=p.k_pct * math.exp(s * z - s * s / 2.0))


#: THE REMOVAL HAZARD BY PITCH COUNT, COUNTED — the pitch backbone of both
#: hook curves, replacing `intercept`, `(pitches - pitch_center)/pitch_scale`,
#: `per_pitch_over` and the `high_pitch_*` branch.
#:
#: WHY A TABLE. The shipped pitch term was ONE smooth logistic across 20 to
#: 110 pitches, and this file already recorded that the FORM cannot fit:
#: no combination of centre, scale and cap reaches mean 84 AND median 89 AND
#: 12.2% over 100. So every patch moved mass into the next bucket — the
#: `high_pitch_*` branch fixed o18.5 and o20.5 and made o15.5/o16.5/o17.5
#: worse by a point each. A table ends that, because the buckets are
#: INDEPENDENT: there is no shared slope for a correction to travel along.
#: Same discipline as `PITCH_COST`, `STATE_MULT` and the advancement rates,
#: every one of which found the imported curve was wrong.
#:
#: WHAT THE OLD CURVE GOT WRONG, its own predictions against reality on the
#: 294,884 TRAINING decisions:
#:
#:     pitches   boundary shipped/real     mid shipped/real
#:      45-60       0.0264 / 0.0155        0.0101 / 0.0054
#:      60-70       0.0865 / 0.0416        0.0255 / 0.0134
#:      70-78       0.1907 / 0.1021        0.0507 / 0.0298
#:      78-85       0.3366 / 0.2207        0.0863 / 0.0594
#:      95-100      0.8463 / 0.9093        0.2888 / 0.2610
#:      100+        0.9074 / 0.9719        0.4076 / 0.4013
#:
#: It pulls roughly TWICE too many men between 60 and 85 pitches and too few
#: at 95+, even after the high-pitch branch had already corrected the top.
#: One shape error with two faces; the table has neither.
#:
#: SOLVED CONDITIONAL ON THE OTHER TERMS, not read off as a marginal rate.
#: The raw pull rate in a bucket already contains the average runs and
#: traffic that occur at that pitch count, so substituting it directly would
#: count those twice. Each value is the intercept that makes the mean
#: predicted probability match the observed rate GIVEN the shipped
#: runs/traffic/inning/blowout/dominance terms. Bisection, so no grid edge.
#:
#: TRAIN ROWS ONLY (before 2026-07-01). Finer buckets through the cliff,
#: where the boundary hazard runs 0.44 -> 0.70 -> 0.91 in fifteen pitches.
#: Smallest cell 1,209 rows. Monotone in every season on both branches.
#: `scratchpad/pitch_hazard.py`.
#: THE ANCHORS THE TABLE IS EXPRESSED AGAINST, and they are the whole reason
#: it composes. The table is applied as an OFFSET from the curve's own
#: intercept, never as an absolute level: callers DISABLE the hook by
#: driving `intercept` / `mid_intercept` to -99 — `team_offset`, the
#: patience fits and every never-pull test use that idiom — and a backbone
#: carrying its own absolute level goes on pulling people regardless.
#: `late_mid_offset` has a docstring saying exactly this and it was got
#: wrong here anyway; six checks caught it.
#:
#: At the shipped intercepts the offset cancels and the curve reads the
#: counted value exactly.
PITCH_HAZARD_BND_ANCHOR = -5.1370
PITCH_HAZARD_MID_ANCHOR = -5.0

PITCH_HAZARD_BND = ((0, -5.3504), (25, -5.3196), (40, -5.7343),
                    (50, -5.2571), (60, -4.6492), (70, -3.8836),
                    (78, -3.1352), (85, -2.2086), (90, -1.2026),
                    (95, 0.2150), (100, 1.3943))
PITCH_HAZARD_MID = ((0, -8.0073), (25, -7.0291), (40, -6.7298),
                    (50, -6.4396), (60, -5.5773), (70, -4.7341),
                    (78, -3.9651), (85, -3.2537), (90, -2.6494),
                    (95, -2.0617), (100, -1.3864))

#: Off restores the parametric backbone AND the `high_pitch_*` branch
#: exactly, so the two are separately scoreable. They must never both apply
#: — the branch is a correction TO the curve the table replaces.
#: OFF PENDING TWO CHECKS, and it stays off until they are answered rather
#: than shipping green-by-loosening. Turning it on fails exactly two:
#:
#:  1. `check_the_boundary_curve_is_the_fitted_one` pins removal_p(105) into
#:     (0.55, 0.95). The counted table gives 0.957 and the REAL 100-110 rate
#:     is 0.972 — so that band never contained the truth; it was drawn round
#:     the old curve. The check needs re-pinning against the counted hazard,
#:     which is what its own comment says it is for.
#:  2. `check_the_first_inning_is_immune_to_a_bullpen_flag` fails, and this
#:     one is NOT obviously the test's fault. The table raises the boundary
#:     hazard under 25 pitches from ~0.0005 to ~0.006, so first-inning pulls
#:     now actually happen — and the moment one does, toggling
#:     `USE_MEASURED_RELIEF_HOOK` moves F1 even with an EMPTY pen. The check
#:     was passing VACUOUSLY because the old curve never exercised that path.
#:     Whether the engine or the check is wrong is unresolved; it is exactly
#:     the attribution bug that check exists to catch, so it gets answered
#:     before this ships.
#: SHIPPED ON 2026-08-31, MID CURVE ONLY. See `USE_PITCH_HAZARD_BND`.
#:
#: WHAT IT BOUGHT, four-fold cross-validated on the outs ladder
#: (`scratchpad/hz_cv_mid.py`): the 12.5-17.5 band improves in ALL FOUR
#: seasons by a consistent -0.016 to -0.018, the long lines are untouched
#: (0.0157 -> 0.0152), and the mean-outs error HALVES rather than flipping
#: (0.2 outs short -> 0.08 short; taking both curves overshoots to +0.18
#: long in every season).
#:
#: RUNS ARE UNAFFECTED. Prefix ladder over 508 holdout games: F1 -0.008,
#: F3 -0.080 -> -0.078, F5 -0.036 -> -0.032, F7 -0.029 -> -0.025. Every
#: prefix moves under 0.004 runs, all inside a standard error of 0.06-0.17,
#: and every one moves TOWARD zero.
USE_PITCH_HAZARD = True

#: THE TWO CURVES SEPARATELY. The comment above says the parametric
#: backbone and the counted table are separately scoreable and until
#: 2026-08-31 nothing could actually score them apart. Measured that day,
#: bucket by bucket against real holdout rates, they behave completely
#: differently:
#:
#:    MID   cell error 0.0203 -> 0.0144. Eight buckets essentially exact
#:          through 85 pitches; misses LOW only at 90+ (-0.051, -0.058).
#:    BND   cell error 0.0265 -> 0.0314, WORSE than the curve it replaces,
#:          and under-pulling across the whole range from 60 up
#:          (-0.018, -0.020, -0.088, -0.057, -0.084).
#:
#: The boundary table under-pulling everywhere is why starters run long:
#: mean outs overshoots by +0.18 in all four seasons with both on.
#:
#: FALSE IS THE SHIPPED STATE: counted MID backbone, parametric BOUNDARY.
#: Taking both was a dead heat on all-line error (0.0215 against 0.0223)
#: and lost everywhere else — it nearly doubled the long-line error and
#: turned a 0.2-out shortfall into a 0.18-out overshoot in every season.
#: Half the change beat all of it.
USE_PITCH_HAZARD_BND = False



#: PITCH COUNT x INNING. Seventy pitches in the third is not the decision
#: seventy in the fifth is, and neither curve could say so: both read
#: `pitches` and the inning as SEPARATE ADDITIVE terms, so the difference
#: between "the wheels came off" and "he is cruising" had nowhere to live.
#: Counted on day seven (70 pitches pulled at 6.01% in the third against
#: 1.62% in the fifth, a 3.7x span) and not built until day twenty.
#:
#: SOLVED, NOT TABULATED, conditional on every other shipped term
#: (`scratchpad/pxi.py`), and CENTRED on the row-weighted mean so this
#: carries SHAPE and not LEVEL — three other terms already control how deep
#: starters go and this must not become a fourth.
#:
#: NOT PITCHES PER INNING. That compression was tried on day seven and it
#: FOLDS BACK ON ITSELF — high pitches-per-inning early means FEW total
#: pitches, giving a non-monotone 1.68% / 4.77% / 3.14% against a monotone
#: 75x span for raw pitch count. A cell table never divides, so it has no
#: such degeneracy.
#:
#: BANDS START AT 45 ON PURPOSE. Sub-45 cells solve to +0.9 and +1.1, which
#: is the DISASTER TAIL — a starter gone that early was chased or hurt, not
#: out-managed. That population belongs to the early-exit mixture, and
#: `early_exit_floor` exists to stop the hook producing those starts on top
#: of it. Day seven's `early_innings` branches fixed the tail from inside
#: the curve and paid for it in spread (outs SD 4.47 against a real 3.99).
#:
#: READ THE SIGN: negative in the fourth, positive from the sixth. The model
#: pulls too eagerly in the middle innings and lets the labouring starter
#: come back out for the sixth. `scratchpad/mid_by_inning.py` shows the same
#: defect from the other side — mid-inning exits +0.032 of all starts in the
#: fifth, -0.029 in the sixth.
PXI_BANDS = (45, 60, 75, 90)
PXI_INNINGS = (1, 4, 5, 6, 7)

PXI_BND = {(45, 1): 0.0437, (45, 4): -0.1563, (45, 5): 0.4333,
           (60, 1): 0.0828, (60, 4): -0.6350, (60, 5): -0.1248,
           (60, 6): 0.4675,
           (75, 4): -0.1315, (75, 5): -0.0642, (75, 6): 0.2557,
           (75, 7): 0.6500,
           (90, 5): 0.3059, (90, 6): 0.8109, (90, 7): 0.5068}

PXI_MID = {(45, 1): 0.0674, (45, 4): -0.4899, (45, 5): 0.1306,
           (45, 6): 1.2662,
           (60, 1): 0.0827, (60, 4): -0.4143, (60, 5): -0.1575,
           (60, 6): 0.6360, (60, 7): 0.5920,
           (75, 4): -0.1155, (75, 5): -0.0624, (75, 6): 0.4303,
           (75, 7): 0.6987,
           (90, 5): 0.0216, (90, 6): 0.4124, (90, 7): 0.5482}

#: Off pending a score, like every other counted mechanism here.
USE_PITCH_X_INNING = False


def pxi(pitches: float, inning: int, table: dict) -> float:
    """Cell offset, or zero outside the tabulated region.

    ZERO AND NOT NEAREST-NEIGHBOUR. An absent cell is one that had under
    300 training decisions, which is a cell nobody measured; extrapolating
    a neighbour into it would ship a number that was never counted. Zero
    leaves the curve exactly as it is there, which is the honest default.
    """
    if not USE_PITCH_X_INNING:
        return 0.0
    b = None
    for edge in PXI_BANDS:
        if pitches >= edge:
            b = edge
    if b is None:
        return 0.0                      # below 45: the mixture's territory
    g = None
    for edge in PXI_INNINGS:
        if inning >= edge:
            g = edge
    return table.get((b, g), 0.0)

def pitch_hazard(pitches: float, table) -> float:
    """Counted log-odds baseline at this pitch count. A STEP, not a curve.

    Deliberately not interpolated. The buckets were solved independently and
    smoothing between them would reintroduce exactly the shared slope this
    table exists to remove.
    """
    out = table[0][1]
    for lo, v in table:
        if pitches >= lo:
            out = v
        else:
            break
    return out


MID_INNING_RUN_OFFSET = {0: 0.0, 1: 0.296, 2: 1.380, 3: 1.707, 4: 2.914}


def inning_run_offset(runs: int) -> float:
    """Log-odds for `runs` allowed in the current half-inning."""
    if runs <= 0:
        return 0.0
    return MID_INNING_RUN_OFFSET.get(min(runs, 4), 2.914)


_HERE = __file__.rsplit("/", 1)[0]
_PATIENCE_PATH = _HERE + "/hook_patience.json"
_LEASH_PATH = _HERE + "/hook_leash.json"
_PENSTATE_PATH = _HERE + "/hook_penstate.json"
_PENSTATE: dict | None = None
_PATIENCE: dict | None = None
_LEASH: dict | None = None


def _load(path: str) -> dict:
    import json
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


#: Apply the on-disk club-patience and pitcher-leash offsets.
#:
#: OFF. They were fitted 2026-08-23 as RESIDUALS against the model's own
#: error, and that model no longer exists — since then: fielding errors,
#: out-dependent advancement, PITCH_COST fitted on real counts, WP_PB_RATE
#: cut 45%, pitch_center 92 -> 80, and league baselines recomputed on a
#: doubled database. A residual correcting an error that has been fixed
#: does not merely go stale, it pushes the wrong way.
#:
#: `fitf5` already ran without them by design, and the notes' own argument
#: is that they reach an F5 number through one channel that opens about a
#: quarter of the time. Refit them or delete them; until then they must not
#: quietly contaminate a market measurement.
USE_OFFSETS = False

#: THE PER-PITCHER LEASH, and the two flags are separate because the two
#: mechanisms measured differently. See `src/context/leash.py` for the whole
#: argument; the short version is that a pitcher's leave-one-out residual is
#: +0.295 on OUTS and noise on strikeouts, hits, walks and earned runs, so
#: what is wrong is how long he is left in and not how he pitches.
#:
#: Out of sample — rates before 2026-07-01, scored on the 1,125 starts after
#: it, offsets from strictly prior starts — the correlation between our
#: predicted outs and real outs goes +0.090 -> +0.234 and RMSE 3.906 ->
#: 3.808. The model-free ceiling in that window is +0.294, so this is the
#: difference between capturing a third of the available signal and three
#: quarters of it.
USE_LEASH = True

#: THE CLUB, and it stays off: this is the SIXTH independent finding that
#: team-specific hook effects do not pay. Fitted in the correct order (club
#: first, pitcher against the remainder) a club offset moves the
#: out-of-sample correlation +0.090 -> +0.122 alone, and ON TOP of the
#: pitcher offset it makes things WORSE (+0.234 -> +0.227, MAE up). The
#: club split-half looks strong (r +0.595, which passes the bullpen-role
#: gate) and that is a trap: it is measuring which ARMS a club runs out,
#: not how patient its manager is, and the pitcher offset already has that.
USE_PATIENCE = False


def patience(team: str | None) -> float:
    """Fitted log-odds offset for a club's manager. 0.0 when unknown.

    Unknown resolves to the league hook rather than to a guess, the same
    rule the rest of this codebase follows for a missing group value.
    """
    if not (USE_OFFSETS or USE_PATIENCE):
        return 0.0
    global _PATIENCE
    if _PATIENCE is None:
        _PATIENCE = _load(_PATIENCE_PATH)
    return float(_PATIENCE.get((team or "").upper(), 0.0))


def pen_state(team: str | None, date: str | None) -> tuple[float, float]:
    """(arms unavailable, days of club rest) for one club on one date.

    Returns the LEAGUE BASELINE when unknown, so a missing club or a date
    with no schedule behind it contributes exactly zero to the hook rather
    than a guess. Same missing-group rule as `patience` and `leash`.

    THE FIRST GAME OF A SEASON HAS NO YESTERDAY and legitimately falls
    through to the baseline; so does any club whose previous game is not in
    the cache. That is a real gap in coverage rather than a neutral input,
    and it is why `USE_PEN_STATE` stays switchable.
    """
    if not USE_PEN_STATE or not team or not date:
        return PEN_BACK2_BASELINE, PEN_REST_BASELINE
    global _PENSTATE
    if _PENSTATE is None:
        _PENSTATE = _load(_PENSTATE_PATH)
    v = _PENSTATE.get(f"{team.upper()}|{date}")
    if not v:
        return PEN_BACK2_BASELINE, PEN_REST_BASELINE
    return float(v[0]), float(v[1])


_STARTS: dict | None = None


def _start_dates(conn=None) -> dict:
    """{pitcher_name: sorted set of start dates} from BOTH start records.

    Cached in-process.

    WHY IT UNIONS TWO SOURCES, and this is a correctness requirement rather
    than belt-and-braces. A MISSING start does not weaken this feature, it
    INVERTS it: the gap is a difference between consecutive starts, so one
    absent row silently turns a normal five-day turn into a ten-day layoff
    and fires the step on a pitcher who never went anywhere. Measured over
    the 789 games from 2026-07-01 to 2026-08-31:

        mlb_pitching  721 of 789  (91.4%)
        mlb_stints    683 of 789  (86.6%)
        UNION         787 of 789  (99.7%)

    Neither source alone is complete and they miss different games. On
    `mlb_pitching` alone the layoff fired on 18.32% of holdout starts
    against 7.64% in the population it was fitted on, and the extra fires
    were almost all data gaps — enough to drag mean outs 15.72 -> 15.53
    against a real 15.75 and make a centred term move the level.

    KEYED BY NAME because that is the only column the two tables share —
    `mlb_pitching` carries no pitcher id. That is a knowing exception to
    the ids-not-names rule, and it is safe here only because both tables
    are populated from the same statsapi payload, so the spelling matches
    on both sides.
    """
    global _STARTS
    if _STARTS is not None:
        return _STARTS
    out: dict = {}
    with (contextlib.nullcontext(conn) if conn else db.connect()) as c:
        for r in c.execute(
                "select p.player_name as n, g.date as d "
                "from mlb_pitching p join games g on g.game_id = p.game_id "
                "where p.is_starter = 1 and g.date is not null"):
            out.setdefault(r["n"], set()).add(r["d"])
    from src.context import store
    with store.connect() as c:
        for r in c.execute(
                "select player_name as n, date as d from mlb_stints "
                "where appearance_order = 0 and date is not null"):
            out.setdefault(r["n"], set()).add(r["d"])
    _STARTS = {k: sorted(v) for k, v in out.items()}
    return _STARTS


def layoff_gap(pitcher_name: str | None, date: str | None,
               conn=None) -> int | None:
    """Days since this starter's previous START, or None.

    None — contributing exactly zero to both hook curves — for a pitcher
    with no prior start on record, a date with nothing behind it, and
    ACROSS A SEASON BREAK. The last is deliberate and is not a coverage
    gap: a pitcher opening a season has had a spring to build up and is
    not the same case as one returning in August, so the in-season
    coefficient must not be evaluated on him. `scratchpad/layoff.py` fits
    on in-season gaps for the same reason.

    Same missing-group rule as `pen_state`, `patience` and `leash`.
    """
    if not USE_LAYOFF or not pitcher_name or not date:
        return None
    ds = _start_dates(conn).get(pitcher_name)
    if not ds:
        return None
    prev = None
    for d in ds:
        if d >= date:
            break
        prev = d
    if prev is None or prev[:4] != date[:4]:
        return None
    from datetime import date as _dt
    return (_dt.fromisoformat(date) - _dt.fromisoformat(prev)).days


def reload_starts() -> None:
    """Drop the cached start index so a backfill is picked up in-process."""
    global _STARTS
    _STARTS = None


def leash(pitcher_name: str | None) -> float:
    """Measured log-odds offset for one starter. 0.0 when unknown.

    Built by `src.context.leash`, which shrinks each pitcher's trimmed mean
    outs residual by a MEASURED constant (within_var / between_var off a
    one-way ANOVA) and converts it through an interpolated table. A pitcher
    with no record contributes nothing, which is the same missing-group rule
    as everywhere else.
    """
    if not (USE_OFFSETS or USE_LEASH):
        return 0.0
    global _LEASH
    if _LEASH is None:
        _LEASH = _load(_LEASH_PATH)
    return float(_LEASH.get(pitcher_name or "", 0.0))


def reload_offsets() -> None:
    """Drop the cached files so a rebuild is picked up in-process."""
    global _PATIENCE, _LEASH
    _PATIENCE = _LEASH = None


def for_start(base: Hook, team: str | None,
              pitcher_name: str | None = None) -> Hook:
    """The hook for one specific start: league form + club + pitcher.

    The two offsets ADD because they were fitted that way — club first,
    pitcher against the remainder. Fitting both independently and adding
    them would double-count the manager.

    ADDED to `base.team_offset` rather than replacing it, so a caller that
    has already set one — `calibrate.HOME_HOOK` stacks on top of this, and
    the bootstrap in `simulate_many` jitters it — composes instead of
    silently losing whichever was applied first.
    """
    off = patience(team) + leash(pitcher_name)
    return base if not off else Hook(
        **{**base.__dict__, "team_offset": base.team_offset + off})


def for_team(base: Hook, team: str | None) -> Hook:
    """`base` with this club's fitted patience applied."""
    off = patience(team)
    return base if not off else Hook(**{**base.__dict__,
                                        "team_offset": off})


def for_pitcher(base: Hook, avg_pitches: float | None,
                max_pitches: float | None) -> Hook:
    """Shift the leash to this starter's own record.

    A club's hook point is a group number standing in for an individual, and
    the same rule the rest of this codebase follows applies: keep the
    underlying value, shrink toward it rather than replacing it. An opener
    and a workhorse do not share a pitch_center, and using the league's for
    both is the substitution bias that has already cost this project two
    bugs.
    """
    if not avg_pitches:
        return base
    center = avg_pitches + 6.0
    if max_pitches:
        center = min(center, float(max_pitches))
    # Halfway between the league default and his own, because a ten-start
    # sample of pitch counts is itself thin.
    center = (center + base.pitch_center) / 2
    cap = int(max(base.hard_pitch_cap * 0.8,
                  (max_pitches or base.hard_pitch_cap) + 8))
    return Hook(**{**base.__dict__, "pitch_center": center,
                   "hard_pitch_cap": cap})


# ── base-out state ─────────────────────────────────────────────────────
#
# Deliberately crude: bases as three booleans and fixed advancement. A full
# 24-state model with empirical advancement rates needs play-by-play, and
# the check on whether crude is good enough is whether simulated runs per
# nine matches the league's actual 4.63 — which is a real test, not a
# reassurance, because nothing here was tuned to hit it.

#: Extra-base advancement, BY OUT COUNT.
#:
#: The out count was the missing mechanism, not the rate. A single flat
#: probability applies the same number with nobody out and with two, and
#: those are not remotely the same play: with two outs the runner leaves on
#: contact, with none he is held. Measured against the training window the
#: simulator put 2.3% MORE men on base than reality and scored 4.2% FEWER of
#: them — a conversion defect, not a traffic one — and the F5 fit responded
#: by driving these constants to the ceiling of their grids, which is the
#: same signature that turned up the absent hit-by-pitch and the absent
#: fielding errors.
#:
#: Raising the flat rate cannot fix it. It would buy the two-out case by
#: over-converting the nobody-out case, which is why the fit kept straining
#: at the edge instead of settling.
#:
#: MEASURED ON THIS LEAGUE, over 152,153 plays of play-by-play, replacing
#: the published references these started as. Measuring is not fitting:
#: there is no loss function behind these, the conditioning matches the code
#: paths below exactly (see `src/context/advance.py`), and they were adopted
#: as a SET without checking what each did to the score. Fitting them
#: against runs would repeat the mistake the out-count split exists to
#: correct; counting them does not.
#:
#: The published numbers were wrong in BOTH DIRECTIONS AT ONCE, which is why
#: they had to move together. First-to-third was six to seven points light,
#: so too many runners were stranded at second; the two scoring rates were
#: four to ten points heavy, so too many of the ones who did get there came
#: home. Runs per baserunner sat at -0.2% while every component was off by
#: three to six sigma — the aggregate was right for cancelling reasons.
#:
#:     was .24 .28 .34   ->   .307 .295 .408
#:     was .42 .62 .84   ->   .411 .542 .796
#:     was .33 .45 .63   ->   .274 .346 .565
FIRST_TO_THIRD_ON_1B = {0: 0.307, 1: 0.295, 2: 0.408}
SECOND_SCORES_ON_1B = {0: 0.411, 1: 0.542, 2: 0.796}
FIRST_SCORES_ON_2B = {0: 0.274, 1: 0.346, 2: 0.565}

#: A runner SCORING FROM FIRST on a single. The model could not do it at
#: all — its single sent him to third at best — so this is a missing
#: mechanism rather than a mistuned rate, and folding it into
#: first-to-third would have hidden that. Rare, and rising sharply with the
#: out count for the same reason everything else here does: with two down he
#: is running on contact.
FIRST_SCORES_ON_1B = {0: 0.022, 1: 0.043, 2: 0.068}


def _rate(table, outs: int) -> float:
    """Look up an advancement rate for the current out count.

    Accepts a bare float so a caller (or a fit) can still pin one value
    across all out states — that is what the old model was, and keeping it
    expressible makes the two directly comparable.
    """
    if isinstance(table, (int, float)):
        return float(table)
    return table[min(max(outs, 0), 2)]


#: A ball-in-play out that is not a double play still moves runners some of
#: the time — the ground out to the right side, the sacrifice fly.
#:
#: BY OUT COUNT, for the same reason as the three above, and it was the last
#: one left flat. The F5 fit found it immediately: with the others made
#: out-dependent, this became the only knob able to absorb the remaining
#: conversion deficit and the search drove it straight to the ceiling of its
#: grid at 2.3 sigma. Fourth instance in one session of a parameter pinned
#: at a grid edge turning out to be a missing mechanism rather than a
#: mistuned constant.
#:
#: The two states are different plays, not the same play at different
#: frequencies. With nobody out a productive out is incidental — a grounder
#: to the right side that happens to move a runner up. With one out the
#: sacrifice fly is deliberate and a runner on third scores on any ball deep
#: enough. The two-out entry is never reached: the guard in `apply_pa` only
#: advances while the inning is still alive, and with two down the ball in
#: play IS the third out.
#: MIX AND MATCH. Every mechanism change here is discrete and has to stay
#: separately scoreable — the combination that wins is not necessarily the
#: newest state, and a change that loses on F5 may still be right on team
#: totals. Switching this off restores the exact pre-measurement model:
#: published tables, one pooled coin flip on an out, and no way to score
#: from first on a single. Same shape as `USE_PARK` and `USE_HOME_ROAD`.
#:
#: The PUBLISHED values live in `LEGACY_ADVANCEMENT` rather than in the
#: constants themselves so that turning the switch off does not require
#: remembering which six globals to put back.
USE_MEASURED_ADVANCEMENT = True

#: THE BOUNDARY CURVE AS IT SHIPPED UNTIL 2026-08-26, kept so the change
#: stays separately scoreable — `sim.Hook(**sim.LEGACY_BOUNDARY)` restores it.
#:
#: It was fitted by `calibrate.tune` against `sim.simulate`, the one-sided
#: engine deleted the day before, and against a pitch count billed
#: `int(round(PITCH_COST))` — about four pitches a start light. Measured
#: against 38,485 real end-of-inning decisions it fires at 0.293 where
#: reality is 0.074 (70-80 pitches) and 0.137 against 0.029 (60-70). It is
#: systematically too eager to pull.
#:
#: WHY IT SURVIVED SO LONG, and the reason the replacement looks worse on
#: `calibrate.loss`: its over-eagerness was COMPENSATING for starters who
#: last too long, because outs per plate appearance runs 1.4% high. Swapping
#: it moves mean outs 15.64 -> 16.50 against a real 15.78, and the boundary
#: share 0.643 -> 0.479 against 0.663. Both got worse.
#:
#: IT SHIPPED ANYWAY BECAUSE NEITHER OF THOSE IS A BET. Weighted by where
#: books actually hang outs lines the fitted curve is much better:
#:
#:     RMS error on P(over), lines 14.5-17.5   0.0546 -> 0.0346
#:     RMS error on P(over), lines 12.5-20.5   0.0452 -> 0.0513
#:
#: and the old curve's errors were a BIAS, negative at every line from 12.5
#: to 17.5 (-0.043 to -0.067), systematically under-pricing the over. The
#: aggregate favours the old curve only through 18.5 and 20.5 — six-plus
#: innings, which is the thin end of the board.
#:
#: WHAT WAS STILL WRONG, AND IS NOW FIXED: the logit was linear in pitches
#: and the real hazard is not. `LINEAR_BOUNDARY` restores that intermediate
#: version. It was wrong at BOTH ends and the errors do not cancel —
#:
#:     bucket     n      actual   linear   knee at 60
#:     0-40     16115     0.010    0.002       0.010
#:     50-60     4335     0.010    0.022       0.011
#:     70-80     3927     0.074    0.114       0.077
#:     90-100    1775     0.504    0.406       0.491
#:     100-110    371     0.749    0.596       0.746
#:
#: — one hinge, one extra parameter, and it tracks reality at every bucket.
#: Log loss 0.16286 -> 0.15420, AUC 0.8925 -> 0.8977, BIC 12599 -> 11942 on
#: the same 38,485 decisions. A quadratic scored the same (BIC 11955) and
#: was rejected for being non-monotone below 30 pitches.
LEGACY_BOUNDARY = {
    "intercept": -4.6, "pitch_center": 80.0, "pitch_scale": 15.0,
    "per_run": 0.60, "per_inning": 0.45, "per_baserunner": 0.10,
    "per_pitch_over": 0.0,
}

#: {outs: count} for starts that ended below the mixture's floor — the
#: EARLY-EXIT LUMP, sampled rather than modelled. Empty until
#: `Hook.early_exit_p` is non-zero, and populated by whoever sets it
#: (`scratchpad.fit_survivors` writes both together).
#:
#: COUNTED, NOT FITTED. These starts are the ones nobody can call in
#: advance, so the mixture's job is to remove them from the length estimate
#: rather than to explain them. Sampling the shape from what actually
#: happened is the whole mechanism.
EARLY_EXIT_DIST: dict[int, int] = {}

#: What ships, named so `scratchpad/score_boundary.py` can hold all three
#: side by side. Identical to the defaults above.
LINEAR_BOUNDARY = {
    "intercept": -5.1370, "pitch_center": 49.5493, "pitch_scale": 12.1293,
    "per_run": 0.1097, "per_inning": 0.2515, "per_baserunner": 0.0555,
    "per_pitch_over": 0.0,
}

#: The curve as it stood before the `count.outs` fix of 2026-08-26, when
#: 48.2% of its training rows were second outs rather than inning ends.
#: Kept ONLY so the correction stays scoreable — it is not a fallback.
#: `per_inning` NEGATIVE is the tell: it says a manager grows less likely to
#: pull as the game goes on, which is backwards, and it is what a curve
#: fitted half on rows where nobody is ever pulled will report.
PRE_OUTS_FIX_BOUNDARY = {
    "intercept": -4.2384, "pitch_center": 47.6812, "pitch_scale": 10.8972,
    "per_run": 0.0089, "per_inning": -0.1087, "per_baserunner": 0.0379,
    "per_pitch_over": 0.0,
}

#: THE KNEE. Fitted, MEASURED BETTER PER DECISION, AND NOT SHIPPED — the
#: clearest instance yet of the day-nine trap, so it is kept scoreable.
#:
#: One hinge, one extra parameter, fitted on the same 38,485 real
#: end-of-inning decisions. Per decision it is not close:
#:
#:     bucket        n    actual   linear    knee
#:     0-40      16115     0.010    0.002   0.010
#:     50-60      4335     0.010    0.022   0.011
#:     70-80      3927     0.074    0.114   0.077
#:     90-100     1775     0.504    0.406   0.491
#:     100-110     371     0.749    0.596   0.746
#:
#: log loss 0.16286 -> 0.15420, AUC 0.8925 -> 0.8977, BIC 12599 -> 11942.
#: The knee at 60 was SCANNED over 40-80, not asserted: log loss is a flat
#: bowl from 50 to 65, and 60 is where the sub-knee slope stops being
#: negative, so the curve is monotone. A quadratic scored the same and was
#: rejected for being convex — it decreases below its vertex at ~30 pitches
#: and this curve is evaluated at EVERY inning end, including a 15-pitch
#: first.
#:
#: ON 1,040 HOLDOUT STARTS, LEASH OFF, PAIRED SEEDS, IT LOSES:
#:
#:                          legacy   linear     knee   ACTUAL
#:     RMS P(over) band     0.0681   0.0252   0.0371
#:     Brier, band mean     0.2438   0.2391   0.2402
#:     mean outs             15.60    16.44    16.41    15.81
#:     SD outs                3.82     3.83     4.02     4.05
#:
#: AND IT DOES NOT DO THE ONE THING IT WAS BUILT FOR. The stated reason for
#: a non-linear term was the +0.114 error at the 18.5 line, attributed to
#: the undershot tail. The knee fixes the tail hazard exactly and moves that
#: error by NOTHING (+0.106 both ways), because it also pulls LESS at 60-80
#: — so more starters survive to reach the tail it now pulls correctly. The
#: two errors were cancelling and correcting both changes nothing.
#:
#: WHAT IT DOES BUY is spread: outs SD 3.83 -> 4.02 against a real 4.05,
#: which is a real and separate defect. Not enough to outweigh a loss on
#: both scores that settle, but the reason to keep this here rather than
#: delete it.
KNEE_BOUNDARY = {
    "intercept": -4.5637, "pitch_center": 47.6812, "pitch_scale": 264.5131,
    "pitch_knee": 60.0, "per_pitch_over": 0.127018,
    "per_run": 0.0227, "per_inning": -0.0654, "per_baserunner": 0.0610,
}

LEGACY_ADVANCEMENT = {
    "FIRST_TO_THIRD_ON_1B": {0: 0.24, 1: 0.28, 2: 0.34},
    "SECOND_SCORES_ON_1B": {0: 0.42, 1: 0.62, 2: 0.84},
    "FIRST_SCORES_ON_2B": {0: 0.33, 1: 0.45, 2: 0.63},
}

#: SUPERSEDED by the three per-base tables, and kept because the legacy
#: path still reads it — one pooled constant, every runner moving together.
RUNNER_ADVANCES_ON_OUT = {0: 0.30, 1: 0.45, 2: 0.0}
#: (indexed by outs BEFORE the play; the 2 entry is unreachable because
#: with two down the ball in play is itself the third out)

#: PER BASE, because that is the shape reality has and one constant cannot
#: hold it. Measured, the runner on second goes roughly twice as often as
#: the runner on first — .49 against .22 with nobody out — so a pooled rate
#: is wrong for both of them no matter what value it takes. The old
#: mechanism moved EVERY runner together on one coin flip, which is a
#: different play from the one that happens.
#:
#: CONDITIONED ON THE BASE AHEAD BEING FREE, which is a different quantity
#: from the marginal and is the one a simulator needs. Nobody can pass
#: anybody, so `_advance` rolls the lead runner first and only offers the
#: roll to a trailing runner once the base ahead has actually been vacated.
#: Handing it marginal rates instead would count the blocking twice — once
#: in the rate and once in the occupancy check. The gap is small and it
#: runs in OPPOSITE directions for the two bases (.235 -> .221 on first,
#: .477 -> .490 on second), which is exactly what double-counted blocking
#: looks like.
#:
#: The runner on third is unconditional: home plate is never occupied.
ADVANCE_1B_ON_OUT = {0: 0.221, 1: 0.239, 2: 0.0}
ADVANCE_2B_ON_OUT = {0: 0.490, 1: 0.439, 2: 0.0}
ADVANCE_3B_ON_OUT = {0: 0.331, 1: 0.420, 2: 0.0}

# INHERITED RUNNERS ARE NOT A CONSTANT ANY MORE. `INHERITED_SCORE_RATE`
# (a flat 0.33), `INHERITED_SCORE_BY_STATE` (the same thing counted by base
# and out count) and `USE_MEASURED_INHERITED` lived here and RETIRED WITH THE
# ONE-SIDED ENGINE on 2026-08-25. They only ever existed because
# `simulate_start` stopped the moment the hook fired and so could not
# simulate the reliever finishing the inning: a departing starter's stranded
# runners had to be settled by a coin flip. `game.py` hands the base-out
# state over intact and plays them out, so those runners now score, or do
# not, for the reasons they actually would.
#
# The MEASUREMENT is not lost and was never the same thing as the constant:
# `src.context.inherit` counted 5,507 handovers across 2,006 games and the
# cells (0.127 to 0.771, against a pooled 0.312) are recorded there and in
# the notes. What is deleted is a fudge for an engine that no longer exists.

#: Wild pitches and passed balls, per plate appearance with a runner
#: aboard. They move every runner up a base with no hit and no out.
#:
#: MEASURED AND IT WAS 1.8x TOO HIGH. Real wild pitches are 0.0057 per
#: batter faced across 2,070 starts; passed balls add roughly 20% and never
#: appear in pitching stats at all, being charged to the catcher. Dividing
#: by the 0.441 of plate appearances that actually have a runner aboard
#: gives 0.0155, against the 0.028 guessed from published per-team-game
#: rates.
#:
#: The old value was inflating runs through a channel nothing else checked —
#: free bases with no batter involved. Worth remembering as a case where a
#: published league rate was translated onto the wrong denominator, which is
#: the same class of error that cost 6-8% on walks.
#:
#: RE-MEASURED 2026-08-27 AND THE 0.0155 WAS THE SAME BUG ONE LEVEL DOWN.
#: "0.0057 per batter faced across 2,070 starts" is a STARTER number applied
#: to every arm, exactly like `HBP_RATE`. Counted per play off play-by-play
#: on 330,808 plate appearances with a runner actually aboard, using
#: `pbp.plays` for the base state BEFORE each play (`scratchpad/wp_pb.py`):
#:
#:     wild pitches  6,150   0.01785 per exposed PA
#:     passed balls    863   0.00261 per exposed PA
#:     combined              0.02046
#:
#: Passed balls are 12.8% of the total, which also closes the per-catcher
#: BLOCKING question: an eighth of an already-small quantity is ~0.002 runs.
#: Framing was measured on strikeouts and walks and is separately dead.
#:
#: NO LONGER SEARCHED. This was the only parameter `fitf5` moved, and the
#: fit had pushed it DOWN to 0.0155 while reality is 0.0205 — a fitted
#: constant drifting away from a measurable truth is a fitted constant
#: absorbing some other defect. The direction says the model over-converts
#: free bases into runs, so the search bought accuracy by handing out fewer
#: of them. Handing a measured quantity back to a search is what lets that
#: happen, so `fitf5.MEASURED` now excludes it.
WP_PB_RATE = 0.02046


#: The base-running constants a fit is allowed to move, by name.
#:
#: They live as module globals rather than as fields on a rules object
#: because every one of them is read from inside the innermost loop of the
#: plate-appearance model, and threading a dataclass through `_advance` for
#: the sake of a search that runs twice a season is the wrong trade. The
#: context manager below is the seam instead.
#:
#: The hook is NOT in here. It is a dataclass already and travels per start,
#: which is what lets one club have a quicker one than another.
FITTABLE = ("FIRST_TO_THIRD_ON_1B", "SECOND_SCORES_ON_1B",
            "FIRST_SCORES_ON_2B", "FIRST_SCORES_ON_1B",
            "RUNNER_ADVANCES_ON_OUT", "ADVANCE_1B_ON_OUT",
            "ADVANCE_2B_ON_OUT", "ADVANCE_3B_ON_OUT",
            "WP_PB_RATE", "GIDP_RATE",
            "ROE_PER_OUT")


@contextlib.contextmanager
def rules(**overrides):
    """Temporarily replace fittable constants, then put them back.

    An unknown name raises rather than being ignored. A typo'd parameter in
    a coordinate descent is invisible otherwise: the search runs, every
    candidate scores identically, and the flat surface reads as "this
    parameter does not matter" when it was never applied at all.
    """
    bad = [k for k in overrides if k not in FITTABLE]
    if bad:
        raise ValueError(f"not fittable: {bad} (known: {list(FITTABLE)})")
    prev = {k: globals()[k] for k in overrides}
    globals().update(overrides)
    try:
        yield
    finally:
        globals().update(prev)


def _n(bases, lo=0) -> int:
    """Occupied bases from `lo` on. `bases` holds RUNNER TOKENS, not bools,
    so `sum()` no longer counts them."""
    return sum(1 for b in bases[lo:] if b)


def _advance(bases: list, outcome: str, rng: random.Random,
             outs: int = 0, batter=None) -> tuple:
    """Mutate `bases` for a hit, walk or productive out. -> (runs, scorers).

    Lead runner first, so a runner held at third does not collide with one
    arriving there from first. Doing it in batting order instead is the
    obvious-looking version and it silently overwrites.

    BASES CARRY RUNNER IDENTITY as of 2026-08-27 — a token per occupied bag
    rather than a boolean. Truthiness is unchanged so every occupancy test
    still reads the same, but `sum(bases)` would now add strings, so counting
    goes through `_n`. The arithmetic and the order of random draws are
    untouched: this is bit-identical and adds only the ability to say WHO
    scored, which nothing here could do before.
    """
    runs = 0
    scorers = []
    # A BATTER WHO REACHES STILL OCCUPIES THE BAG EVEN IF UNNAMED. Callers
    # that do not pass a batter — every test, and anything using `apply_pa`
    # directly — must get the old behaviour exactly, and putting `None` on
    # first would DELETE him from the base state. `True` is the unnamed
    # token: truthy for every occupancy test, and attribution simply skips
    # it. The bases-loaded walk check caught this immediately.
    runner = True if batter is None else batter
    if outcome == HR:
        runs = 1 + _n(bases)
        scorers = [b for b in bases if b] + [batter]
        bases[:] = [None, None, None]
    elif outcome == B3:
        runs = _n(bases)
        scorers = [b for b in bases if b]
        bases[:] = [None, None, runner]
    elif outcome == B2:
        runs = _n(bases, 1)                         # 2nd and 3rd both score
        scorers = [b for b in bases[1:] if b]
        from_first_scores = bases[0] and rng.random() < _rate(
            FIRST_SCORES_ON_2B if USE_MEASURED_ADVANCEMENT
            else LEGACY_ADVANCEMENT["FIRST_SCORES_ON_2B"], outs)
        if from_first_scores:
            runs += 1
            scorers.append(bases[0])
        bases[:] = [None, runner,
                    bases[0] if (bases[0] and not from_first_scores)
                    else None]
    elif outcome == B1:
        second_scores = (SECOND_SCORES_ON_1B if USE_MEASURED_ADVANCEMENT
                         else LEGACY_ADVANCEMENT["SECOND_SCORES_ON_1B"])
        to_third = (FIRST_TO_THIRD_ON_1B if USE_MEASURED_ADVANCEMENT
                    else LEGACY_ADVANCEMENT["FIRST_TO_THIRD_ON_1B"])
        runs = 1 if bases[2] else 0                 # third always scores
        if bases[2]:
            scorers.append(bases[2])
        third = None
        if bases[1]:
            if rng.random() < _rate(second_scores, outs):
                runs += 1
                scorers.append(bases[1])
            else:
                third = bases[1]
        on_first = bases[0]
        if on_first and not third:
            # ONE DRAW, CUMULATIVE THRESHOLDS. Scoring from first and
            # stopping at third are disjoint outcomes in the data they were
            # measured from, so they have to be disjoint here too — two
            # independent rolls would let him do both.
            r = rng.random()
            # Scoring from first did not exist before the measurement, so
            # the legacy path gets zero mass and the cumulative threshold
            # collapses back to a single first-to-third roll.
            score_p = (_rate(FIRST_SCORES_ON_1B, outs)
                       if USE_MEASURED_ADVANCEMENT else 0.0)
            if r < score_p:
                runs += 1
                scorers.append(on_first)
                on_first = None
            elif r < score_p + _rate(to_third, outs):
                third = on_first
                on_first = None
        bases[:] = [runner, on_first, third]
    elif outcome == BB:
        # A walk forces only where every bag behind is occupied.
        if bases[0] and bases[1] and bases[2]:
            runs = 1
            scorers.append(bases[2])
            bases[2] = bases[1]
            bases[1] = bases[0]
            bases[0] = runner
        elif bases[0] and bases[1]:
            bases[2] = bases[1]
            bases[1] = bases[0]
            bases[0] = runner
        elif bases[0]:
            bases[1] = bases[0]
            bases[0] = runner
        else:
            bases[0] = runner
    elif outcome == OUT and not USE_MEASURED_ADVANCEMENT:
        # LEGACY: one coin flip, everybody moves together.
        if rng.random() < _rate(RUNNER_ADVANCES_ON_OUT, outs):
            if bases[2]:
                runs += 1                           # sacrifice fly
            bases[:] = [False, bases[0], bases[1]]
    elif outcome == OUT:
        # LEAD RUNNER FIRST. Each base gets its own roll, and a trailing
        # runner is only offered one once the base ahead of him has actually
        # been vacated — which is what the measured rates were conditioned
        # on. The old mechanism moved everybody on a single coin flip, which
        # is a different play from the one that happens.
        if bases[2] and rng.random() < _rate(ADVANCE_3B_ON_OUT, outs):
            runs += 1                               # sacrifice fly
            scorers.append(bases[2])
            bases[2] = None
        if (bases[1] and not bases[2]
                and rng.random() < _rate(ADVANCE_2B_ON_OUT, outs)):
            bases[1], bases[2] = None, bases[1]
        if (bases[0] and not bases[1]
                and rng.random() < _rate(ADVANCE_1B_ON_OUT, outs)):
            bases[0], bases[1] = None, bases[0]
    return runs, scorers


@dataclass
class StartResult:
    outs: int = 0
    k: int = 0
    bb: int = 0
    h: int = 0
    hr: int = 0
    #: TOTAL runs allowed, unearned included. This is what a team total
    #: settles on, so it is the headline figure.
    runs: int = 0
    #: Earned runs only. Approximated as runs scoring in innings where no
    #: error has yet occurred — the official rule reconstructs the inning as
    #: it would have gone without the error, which needs a scorer's
    #: judgement the model does not have. The approximation over-counts
    #: unearned slightly, since a run that would have scored anyway is
    #: forgiven once an error precedes it.
    #:
    #: Carried so `calibrate` can keep comparing like with like against the
    #: boxscore's `er` column. Before errors existed the two were identical
    #: by construction and `runs` stood in for both.
    earned: int = 0
    #: Batters who reached on an error.
    roe: int = 0
    #: FLOAT, and it matters. `PITCH_COST` is measured to two decimals and
    #: this used to accumulate `int(round(...))` of it, discarding the
    #: fraction on EVERY plate appearance. An out on contact costs 3.25 and
    #: was billed 3; a walk costs 5.48 and was billed 5 — the two commonest
    #: outcomes, rounded the same way ~23 times a start. It cost 3.3 pitches
    #: per start of a measured 4.2-pitch shortfall, and because the hook
    #: integrates over pitch count it made every starter last too long:
    #: 16.4% of simulated starts reached 21+ outs against a real 11.4%.
    #:
    #: The table itself was never wrong. It predicts 86.9 pitches a start
    #: against a real 86.82; the rounding is what threw the calibration away.
    pitches: float = 0.0
    batters: int = 0
    #: Weighted trouble accumulated over the WHOLE START. `Frame.damage`
    #: resets every inning, which makes a starter squared up for three
    #: innings look clean whenever he is between rallies — fine for the
    #: inning-local hook term, useless as a state the learned removal model
    #: can read.
    damage: float = 0.0
    innings_completed: int = 0
    pulled_mid_inning: bool = False
    #: Outs recorded without a hit attached. Tracked so the calibration
    #: harness can confirm they land at the measured league rate instead of
    #: silently drifting with the hook.
    sacrifices: int = 0
    caught_stealing: int = 0
    stolen_bases: int = 0
    hbp: int = 0
    #: Runs allowed through the end of the fifth inning, and whether the
    #: starter was still in when it ended. F5 markets settle on the score
    #: after five, so a start that ends early leaves innings for a reliever
    #: and `covered_f5` says whether that happened.
    runs_f5: int = 0
    outs_f5: int = 0
    covered_f5: bool = False
    #: Runners aboard when the outing ended, and how many outs were already
    #: recorded in that inning. A starter pulled mid-inning strands men who
    #: still score roughly a third of the time — those runs are charged to
    #: him and they count in the F5 score, so dropping them understates
    #: relief scoring by about half.
    left_on_base: int = 0
    outs_when_pulled: int = 0
    #: Per-batter attribution, empty unless `apply_pa` is given a
    #: batter. Before 2026-08-27 the bases held booleans, so the
    #: model knew THAT someone was on and never WHO — no run could
    #: be credited to whoever scored it or drove it in.
    scored_by: dict = field(default_factory=dict)
    rbi_by: dict = field(default_factory=dict)
    wp_pb: int = 0
    #: Runs that scored ON a home run, batter included. See `apply_pa`.
    runs_hr: int = 0


@dataclass
class Frame:
    """State inside one half-inning.

    Replaced three loose locals once errors arrived and a fourth — whether
    the defence has already booted one — had to travel with them. Passing
    four values through two call sites and back is how one of them ends up
    silently not updated.
    """
    bases: list = None
    outs: int = 0
    damage: float = 0.0
    #: Runs scored in THIS half-inning. The hook's other run term is
    #: CUMULATIVE over the start, and the two are different decisions: a
    #: starter who gave up three in the first and settled looks identical to
    #: one giving up three right now unless this is carried separately.
    #: Measured under 60 pitches, where workload is not the reason, the real
    #: per-batter pull rate runs 0.32% at nought through 5.59% at four —
    #: a 17x ratio the model had no channel to express.
    runs: int = 0
    #: Baserunners ALLOWED in this half-inning. NOT `on_base`, which is how
    #: many bases are occupied right now — after a five-run inning that can
    #: be zero while six men have reached. The early hook keys on this, and
    #: wiring it to `on_base` by mistake made a 26,693-decision fit describe
    #: a quantity it was never measured on.
    br: int = 0
    #: An error has occurred this inning, so runs from here on are charged
    #: as unearned.
    errored: bool = False

    def __post_init__(self):
        if self.bases is None:
            self.bases = [None, None, None]

    @property
    def on_base(self) -> int:
        return _n(self.bases)


def _score(r: StartResult, fr: Frame, runs: int) -> None:
    """Credit runs, splitting earned from unearned by the frame's state.

    THE SINGLE PLACE RUNS ARE CREDITED, which is why the half-inning tally
    belongs here — `apply_pa` and `baserunning` both route through it, and
    incrementing at either call site alone would miss the other.
    """
    r.runs += runs
    fr.runs += runs
    if not fr.errored:
        r.earned += runs


def _credit(r: StartResult, fr: Frame, advanced: tuple, batter) -> None:
    """Score the runs AND record who scored them and who drove them in.

    `_score` stays the single place runs are credited to the line; this adds
    the attribution beside it so the two can never disagree about how many.
    Tallies are plain dicts on the line and are empty unless batters were
    passed in, so nothing that calls `apply_pa` without a batter changes.
    """
    runs, scorers = advanced
    _score(r, fr, runs)
    if not runs:
        return
    for who in scorers:
        if who is not None and who is not True:
            r.scored_by[who] = r.scored_by.get(who, 0) + 1
    if batter is not None:
        r.rbi_by[batter] = r.rbi_by.get(batter, 0) + runs


def apply_pa(o: str, r: StartResult, fr: Frame, rng: random.Random,
             batter=None) -> None:
    """Apply one plate-appearance outcome. Mutates `r` and `fr`.

    EXTRACTED so the two engines could not drift apart, and it is why
    deleting the one-sided loop was a small change: `pa_outcome`, this and
    `baserunning` were always the shared base-out state machine, and only
    the driver around them was duplicated. A second hand-written copy of the
    double-play rule or the third-out-scores-nobody rule is a bug waiting
    for the day someone fixes one of them.
    """
    bases = fr.bases
    # The out count AS THE BALL IS STRUCK, captured before anything is
    # recorded. Advancement depends on the situation the runners were
    # running in, not on the situation the play left behind — and for an
    # OUT those differ by one. Passing the post-play count zeroed the
    # sacrifice fly (one out before, two after) and drove runs per
    # baserunner from -2.6% to -3.6%.
    outs_before = fr.outs
    r.batters += 1
    r.pitches += PITCH_COST[o]
    fr.damage += DAMAGE[o]
    r.damage += DAMAGE[o]
    if o in (BB, HBP, B1, B2, B3, HR, ROE):
        fr.br += 1

    if o == SAC:
        # An automatic out that ADVANCES runners — that is the whole point
        # of laying one down. Never a BABIP roll.
        fr.outs += 1
        r.outs += 1
        r.sacrifices += 1
        if fr.outs < 3 and any(bases):
            # THROUGH `_credit`, not `_score`, and moving TOKENS. This
            # branch had the same two defects `baserunning` had: it wrote
            # booleans into a list that carries runner identity, and it
            # scored the sacrifice fly with nobody credited. A sac fly DOES
            # award an rbi, so the batter is passed through. It survived
            # the whole-game attribution check only because sacrifices are
            # about 1% of plate appearances — the check now runs enough
            # games that it cannot pass by luck.
            _credit(r, fr, ((1, [bases[2]]) if bases[2] else (0, [])),
                    batter)
            bases[:] = [None, bases[0], bases[1]]
    elif o == HBP:
        r.hbp += 1
        _credit(r, fr, _advance(bases, BB, rng, outs_before, batter), batter)
    elif o == ROE:
        # No hit, no out, batter on first — and every run after this in the
        # inning is unearned. The out that did not happen is the reason an
        # error costs more than a single: the inning is extended, not just
        # occupied.
        r.roe += 1
        fr.errored = True
        _credit(r, fr, _advance(bases, B1, rng, outs_before, batter), batter)
    elif o == K:
        r.k += 1
        fr.outs += 1
        r.outs += 1
    elif o == OUT:
        # Double play only with a runner on first and a base open for the
        # force, and it ends the inning if it is the second and third out.
        if bases[0] and fr.outs < 2 and rng.random() < gidp_rate(fr.outs):
            bases[0] = False
            fr.outs += 2
            r.outs += 2
        else:
            fr.outs += 1
            r.outs += 1
            # Productive outs only advance a runner if the inning is still
            # alive. A sacrifice fly for the third out scores nobody, and
            # crediting it would inflate runs in exactly the innings that
            # ended badly.
            if fr.outs < 3:
                _credit(r, fr, _advance(bases, OUT, rng, outs_before, batter), batter)
    else:
        if o == BB:
            r.bb += 1
        else:
            r.h += 1
            if o == HR:
                r.hr += 1
        before = r.runs
        _credit(r, fr, _advance(bases, o, rng, outs_before, batter), batter)
        if o == HR:
            # HOW RUNS ARRIVE, not just how many. A homer delivers its runs
            # in one swing to one batter; a single passes them through
            # several. The channel decomposition has only ever checked home
            # run COUNTS, and the share of RUNS they carry is a different
            # quantity — it is what decides whether rbi concentrate.
            r.runs_hr += r.runs - before



#: STEALING IN EVERY BASE STATE, counted rather than modelled in one.
#:
#: `baserunning` used to roll only when first was occupied and SECOND WAS
#: EMPTY, advancing that man to second. Measured on 2026
#: (`scratchpad/steal_states.py`), that single state covers 69.9% of real
#: steals and leaves two others with no mechanism at all: a runner on second
#: takes third at .0074-.0186 and is almost never caught, and first-and-second
#: produces MORE steals of third than of second. No value of a rate reaches
#: them — when a parameter cannot reach the target the mechanism is missing,
#: which is the standing diagnostic here and has now been right five times.
#:
#: It also flattened two real structures. Stealing is OUT-DEPENDENT (.0497
#: with nobody out against .066 with one or two), and first-and-third at two
#: outs runs at .1170 — nearly double the flat rate — because the defence
#: will not risk a throw with a man ninety feet away.
#:
#:     state    outs      opps   SB      CS      to2B  to3B
#:     1B          0     9,099   .0497   .0138    445     7
#:     1B          1    11,272   .0640   .0207    704    17
#:     1B          2    11,445   .0664   .0195    742    18
#:     2B          0     1,891   .0074   .0016      0    14
#:     2B          1     3,433   .0186   .0067      0    64
#:     2B          2     4,607   .0119   .0013      0    55
#:     1B+2B       0     2,261   .0186   .0004     19    23
#:     1B+2B       1     3,955   .0308   .0076     52    70
#:     1B+2B       2     4,854   .0161   .0023     31    47
#:     1B+3B       0       782   .0665   .0090     51     1
#:     1B+3B       1     1,689   .0710   .0124    112     5
#:     1B+3B       2     2,435   .1170   .0127    261     6
#:
#: Third occupied alone, second-and-third and bases loaded produce ZERO
#: steals in 8,434 opportunities, so they are absent by measurement.
#:
#: (sb_rate, cs_rate, share of steals that take THIRD).
STEAL_TABLE: dict = {
    ((True, False, False), 0): (0.0497, 0.0138, 0.015),
    ((True, False, False), 1): (0.0640, 0.0207, 0.024),
    ((True, False, False), 2): (0.0664, 0.0195, 0.024),
    ((False, True, False), 0): (0.0074, 0.0016, 1.0),
    ((False, True, False), 1): (0.0186, 0.0067, 1.0),
    ((False, True, False), 2): (0.0119, 0.0013, 1.0),
    ((True, True, False), 0): (0.0186, 0.0004, 0.548),
    ((True, True, False), 1): (0.0308, 0.0076, 0.574),
    ((True, True, False), 2): (0.0161, 0.0023, 0.603),
    ((True, False, True), 0): (0.0665, 0.0090, 0.019),
    ((True, False, True), 1): (0.0710, 0.0124, 0.043),
    ((True, False, True), 2): (0.1170, 0.0127, 0.022),
}

#: Off restores the single-state roll exactly, so the mechanism stays
#: separately scoreable like everything else here.
USE_STEAL_TABLE = True


def baserunning(r: StartResult, fr: Frame, rng: random.Random) -> None:
    """Wild pitches, steals and caught stealing between plate appearances.

    A runner caught stealing is an out with no batter attached and it counts
    toward innings pitched, which is why leaving it out cost roughly 0.10
    outs a start.

    THIS FUNCTION USED TO WRITE BOOLEANS BACK INTO `fr.bases`. The bases
    carry RUNNER TOKENS as of 2026-08-27 and this path was not updated, so a
    man who stole second became `True` and a man who advanced on a wild
    pitch became whatever was behind him — either way his identity was gone,
    and if he scored later `_credit` dropped him. Every write here now moves
    the TOKEN. Truthiness is unchanged at every site, so the simulation is
    bit-identical and only the attribution differs.

    The wild-pitch run is credited to whoever was on third with NO rbi: a
    run scored with nobody at the plate has a scorer and no one who drove
    him in, and silently giving it to the man on deck would corrupt exactly
    the quantity this attribution exists to measure.
    """
    bases = fr.bases
    if any(bases) and rng.random() < WP_PB_RATE:
        if bases[2]:
            _score(r, fr, 1)
            who = bases[2]
            if who is not None and who is not True:
                r.scored_by[who] = r.scored_by.get(who, 0) + 1
        bases[:] = [None, bases[0], bases[1]]
        r.wp_pb += 1
    if not USE_STEAL_TABLE:
        if bases[0] and not bases[1]:
            roll = rng.random()
            if roll < CS_RATE:
                bases[0] = None
                fr.outs += 1
                r.outs += 1
                r.caught_stealing += 1
            elif roll < CS_RATE + SB_RATE:
                bases[0], bases[1] = None, bases[0]
                r.stolen_bases += 1
        return
    # OCCUPANCY, not the tokens. `bases` holds runner identity now, so
    # `tuple(bases)` is ('Judge', None, None) and would never match a
    # key written as (True, False, False) — steals silently stopped
    # happening at all, which the steal check caught.
    row = STEAL_TABLE.get((tuple(bool(b) for b in bases), fr.outs))
    if row is None:
        return
    sb_r, cs_r, to_third = row
    roll = rng.random()
    if roll < cs_r:
        # The LEAD eligible runner is the one going, so he is the one
        # thrown out. Which base he was heading for does not matter: the
        # out is recorded and he leaves the bases either way.
        if bases[1] and not bases[2]:
            bases[1] = None
        else:
            bases[0] = None
        fr.outs += 1
        r.outs += 1
        r.caught_stealing += 1
    elif roll < cs_r + sb_r:
        # A steal of THIRD moves the man on second; anything else moves the
        # man on first. With both aboard only one goes, which is what the
        # to2B/to3B counts describe — 122 of them in 2026 and not one
        # double advance recorded as a single event.
        if bases[1] and not bases[2] and rng.random() < to_third:
            bases[1], bases[2] = None, bases[1]
        elif bases[0] and not bases[1]:
            bases[0], bases[1] = None, bases[0]
        else:
            return
        r.stolen_bases += 1


# ── THE ONE-SIDED ENGINE IS GONE ───────────────────────────────────────
#
# `simulate_start` walked ONE PITCHING SIDE plate appearance by plate
# appearance and `simulate` drew `n` of them. They were the original engine
# and `game.simulate_game` replaced them, but both were kept so results could
# be compared — and keeping both is what cost day eight. A mechanism was
# wired into one and silently absent from the other for a full day; a paired
# prefix ladder read EXACTLY +0.0000 at all four prefixes over 1,615 games
# because `game.build_side` never called `for_start`. Two models that agree
# to four decimals on 1,615 games are the same model, and an
# identical-to-four-decimals A/B is a plumbing result, never a null.
#
# WHAT THE ONE-SIDED LOOP COULD NOT DO, which is why it had to go rather than
# be maintained: no bullpen, so nothing after the hook was simulated at all;
# no opposing offence, so it never knew whether it was winning and
# `Hook.per_margin` and `mid_per_margin` were structurally unreachable and
# sat at 0.0 forever; no boundary hook; and no park applied to the GAME,
# which is the natural shape because both clubs play in the same building.
# Every measured null in the dead list — park, handedness, day/night, home
# field — was produced on it, against games that were not games.
#
# The state machine itself was never duplicated: `pa_outcome`, `apply_pa`,
# `baserunning` and `Hook` above are the shared parts and are what `game.py`
# calls. What is deleted is the second driver around them.
#
# THE INPUT-UNCERTAINTY BLOCK WENT WITH IT. `HOOK_SIGMA`, `DRAW_RATES` and
# the Beta-posterior draws hung off `simulate` and were both switched OFF —
# "input-uncertainty propagation" is one of the nine features on the dead
# list. They are recorded there, not carried here.
#
# One pitching side out of a real game, for a check or a diagnostic, is
# `tests/fixtures.one_side`. It builds two real Sides and calls
# `simulate_game`; it does not walk a plate appearance itself.


# ── reading a distribution off the simulation ──────────────────────────
def prob_over(results: list[StartResult], stat: str, line: float) -> float:
    """P(stat > line). Pushes are impossible on a half-point line."""
    vals = [getattr(r, stat) for r in results]
    return sum(1 for v in vals if v > line) / len(vals) if vals else 0.0


def prob_push(results: list[StartResult], stat: str, line: float) -> float:
    """P(stat == line), which is P(the book pushes) on an integer line.

    Zero by construction on a half-point line. It is not zero on an integer
    one, and that difference is a real bet: a book's over-9.0 refunds at
    exactly 9, while the Kalshi contract that looks like it — threshold 10 —
    settles NO at 9 and pays nothing back. Comparing the two prices without
    this term compares two different bets.
    """
    if line != int(line):
        return 0.0
    vals = [getattr(r, stat) for r in results]
    return sum(1 for v in vals if v == line) / len(vals) if vals else 0.0


def distribution(results: list[StartResult], stat: str) -> dict:
    """Summary of one stat across the simulated starts."""
    vals = sorted(getattr(r, stat) for r in results)
    n = len(vals)
    if not n:
        return {}

    def q(f):
        return vals[min(n - 1, int(f * n))]

    return {
        "stat": stat, "n": n,
        "mean": round(sum(vals) / n, 2),
        "p10": q(0.10), "p25": q(0.25), "p50": q(0.50),
        "p75": q(0.75), "p90": q(0.90),
        "min": vals[0], "max": vals[-1],
    }
