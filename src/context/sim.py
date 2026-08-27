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
import random
from dataclasses import dataclass

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
PITCH_COST = {K: 4.97, BB: 5.48, HR: 3.76, B1: 3.01, B2: 3.01, B3: 3.01,
              OUT: 3.25, SAC: 3.0, HBP: 3.67, ROE: 3.25}

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
CS_RATE = 0.0148
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
SB_RATE = 0.0557

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
NEUTRAL_PARK = {"hr": 1.0, "k": 1.0, "bip": 1.0}


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
    return {"hr": m("hr"), "k": m("so"), "bip": m("bacon", 100)}


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


def pa_outcome(
    b: BatterRates, p: PitcherRates, lg: dict, rng: random.Random,
    hr_park: float = 1.0, park: dict | None = None, tto: int | None = None,
) -> str:
    """One plate appearance. Returns an outcome constant."""
    pk = park or NEUTRAL_PARK
    # FOUR FLOATS, NOT A NEW OBJECT. This used to build a whole
    # `PitcherRates` per plate appearance just to scale four rates, which is
    # ~76 dataclass constructions per simulated game in the innermost loop
    # of the whole model. `name` and `pa` were copied across and never read
    # below. Arithmetic and order are unchanged, so this is bit-identical.
    p_k, p_bb, p_hr, p_bab = p.k_pct, p.bb_pct, p.hr_pct, p.babip
    # BOTH SIDES AND THE BASELINE, or none of them. Selected BEFORE the
    # times-through-the-order scaling so that multiplier still applies to
    # whichever pitcher line is in use.
    lgm = lg
    if b.side and p.vs_side:
        ps = p.vs_side.get(b.side)
        if ps:
            p_k, p_bb = ps["k_pct"], ps["bb_pct"]
            p_hr, p_bab = ps["hr_pct"], ps["babip"]
    if b.lg_cell:
        lgm = b.lg_cell
    m = tto_mult(tto)
    if m is not None:
        p_k *= m["k_pct"]
        p_bb *= m["bb_pct"]
        p_hr *= m["hr_pct"]
        p_bab *= m["babip"]
    # Off the top: a sacrifice is a plate appearance that was never going to
    # be a strikeout or a walk, so it conditions everything below it.
    sac_r = SAC_RATE if p.sac_rate is None else p.sac_rate
    hbp_r = HBP_RATE if p.hbp_rate is None else p.hbp_rate
    if rng.random() < sac_r:
        return SAC
    if rng.random() < hbp_r:
        return HBP
    # Sacrifices and hit-by-pitches were taken off the top, so everything
    # below is conditional on neither firing. Without this rescale the
    # marginal rates all come out light by exactly SAC_RATE + HBP_RATE —
    # measured as K/9 8.16 against a real 8.44 when it was missing.
    # The SAME two rates that were just drawn, or the rescale corrects for
    # a draw that never happened and every rate below comes out biased.
    cond = 1.0 - sac_r - hbp_r
    k = log5(b.k_pct, p_k, lgm["k_pct"]) * pk["k"] * b.arsenal_k_mult / cond
    k = min(max(k, 1e-6), 0.95)
    if rng.random() < k:
        return K

    # Remaining probabilities are conditional on not having struck out, so
    # each is rescaled by what is left rather than used as a raw PA rate.
    rest = 1.0 - k
    bb = log5(b.bb_pct, p_bb, lgm["bb_pct"]) / cond
    if rest > 0 and rng.random() < bb / rest:
        return BB

    rest -= bb
    hr = log5(b.hr_pct, p_hr, lgm["hr_pct"]) * hr_park * pk["hr"] \
        * b.arsenal_mult / cond
    if rest > 0 and rng.random() < hr / rest:
        return HR

    # Ball in play. The arsenal multiplier applies here too: a mix this
    # hitter handles well produces harder contact, not just more homers.
    babip = min(0.95, log5(b.babip, p_bab, lgm["babip"])
                * pk["bip"] * b.arsenal_mult)
    if rng.random() >= babip:
        # A ball in play the defence should have converted and did not.
        # Drawn HERE rather than from the whole plate appearance because an
        # error is specifically a fielding failure on a batted ball: a
        # strikeout or a walk cannot become one.
        return ROE if rng.random() < ROE_PER_OUT else OUT
    mix, r = lg["hit_mix"], rng.random()
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
    per_margin: float = 0.0
    mid_per_margin: float = 0.0
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
                  inning_runs: int = 0) -> float:
        """P(pulled) evaluated at the end of a completed inning."""
        if self.early_innings and innings <= self.early_innings:
            return _sigmoid(self.intercept + self.early_bnd_offset
                            + self.team_offset
                            + self.early_bnd_per_pitch * pitches
                            + self.early_bnd_per_run_offset
                            * inning_run_offset(inning_runs)
                            + self.early_bnd_per_run * runs
                            + self.per_margin * margin)
        return _sigmoid(self.intercept + self.team_offset
                        + (pitches - self.pitch_center) / self.pitch_scale
                        + self.per_pitch_over * max(0.0,
                                                    pitches - self.pitch_knee)
                        + self.per_run * runs
                        + self.per_baserunner * baserunners
                        + self.per_margin * margin
                        + self.per_inning * innings)

    def mid_removal_p(self, pitches: int, runs: int, on_base: int,
                      inning_damage: float = 0.0, margin: int = 0,
                      inning_runs: int = 0, inning: int = 0,
                      inning_br: int = 0) -> float:
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
                            + self.mid_per_margin * margin)
        return _sigmoid(self.mid_intercept + self.late_mid_offset
                        + self.team_offset
                        + self.late_mid_per_pitch * pitches
                        + self.late_mid_per_inning_br * inning_br
                        + self.late_mid_per_run * runs
                        + self.late_mid_per_onbase * on_base
                        + self.mid_per_margin * margin
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
MID_INNING_RUN_OFFSET = {0: 0.0, 1: 0.296, 2: 1.380, 3: 1.707, 4: 2.914}


def inning_run_offset(runs: int) -> float:
    """Log-odds for `runs` allowed in the current half-inning."""
    if runs <= 0:
        return 0.0
    return MID_INNING_RUN_OFFSET.get(min(runs, 4), 2.914)


_HERE = __file__.rsplit("/", 1)[0]
_PATIENCE_PATH = _HERE + "/hook_patience.json"
_LEASH_PATH = _HERE + "/hook_leash.json"
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
WP_PB_RATE = 0.0155


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


def _advance(bases: list[bool], outcome: str, rng: random.Random,
             outs: int = 0) -> int:
    """Mutate `bases` for a hit, walk or productive out. Returns runs.

    Lead runner first, so a runner held at third does not collide with one
    arriving there from first. Doing it in batting order instead is the
    obvious-looking version and it silently overwrites.
    """
    runs = 0
    if outcome == HR:
        runs = 1 + sum(bases)
        bases[:] = [False, False, False]
    elif outcome == B3:
        runs = sum(bases)
        bases[:] = [False, False, True]
    elif outcome == B2:
        runs = sum(bases[1:])                       # 2nd and 3rd both score
        from_first_scores = bases[0] and rng.random() < _rate(
            FIRST_SCORES_ON_2B if USE_MEASURED_ADVANCEMENT
            else LEGACY_ADVANCEMENT["FIRST_SCORES_ON_2B"], outs)
        runs += 1 if from_first_scores else 0
        bases[:] = [False, True, bool(bases[0]) and not from_first_scores]
    elif outcome == B1:
        second_scores = (SECOND_SCORES_ON_1B if USE_MEASURED_ADVANCEMENT
                         else LEGACY_ADVANCEMENT["SECOND_SCORES_ON_1B"])
        to_third = (FIRST_TO_THIRD_ON_1B if USE_MEASURED_ADVANCEMENT
                    else LEGACY_ADVANCEMENT["FIRST_TO_THIRD_ON_1B"])
        runs = 1 if bases[2] else 0                 # third always scores
        third = False
        if bases[1]:
            if rng.random() < _rate(second_scores, outs):
                runs += 1
            else:
                third = True
        on_first = bool(bases[0])
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
                on_first = False
            elif r < score_p + _rate(to_third, outs):
                third = True
                on_first = False
        bases[:] = [True, on_first, third]
    elif outcome == BB:
        if bases[0] and bases[1] and bases[2]:
            runs = 1
        elif bases[0] and bases[1]:
            bases[2] = True
        elif bases[0]:
            bases[1] = True
        else:
            bases[0] = True
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
            bases[2] = False
        if (bases[1] and not bases[2]
                and rng.random() < _rate(ADVANCE_2B_ON_OUT, outs)):
            bases[1], bases[2] = False, True
        if (bases[0] and not bases[1]
                and rng.random() < _rate(ADVANCE_1B_ON_OUT, outs)):
            bases[0], bases[1] = False, True
    return runs


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
    wp_pb: int = 0


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
            self.bases = [False, False, False]

    @property
    def on_base(self) -> int:
        return sum(self.bases)


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


def apply_pa(o: str, r: StartResult, fr: Frame, rng: random.Random) -> None:
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
            if bases[2]:
                _score(r, fr, 1)                 # sacrifice fly
            bases[:] = [False, bases[0], bases[1]]
    elif o == HBP:
        r.hbp += 1
        _score(r, fr, _advance(bases, BB, rng, outs_before))  # forces
    elif o == ROE:
        # No hit, no out, batter on first — and every run after this in the
        # inning is unearned. The out that did not happen is the reason an
        # error costs more than a single: the inning is extended, not just
        # occupied.
        r.roe += 1
        fr.errored = True
        _score(r, fr, _advance(bases, B1, rng, outs_before))
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
                _score(r, fr, _advance(bases, OUT, rng, outs_before))
    else:
        if o == BB:
            r.bb += 1
        else:
            r.h += 1
            if o == HR:
                r.hr += 1
        _score(r, fr, _advance(bases, o, rng, outs_before))


def baserunning(r: StartResult, fr: Frame, rng: random.Random) -> None:
    """Wild pitches, steals and caught stealing between plate appearances.

    A runner caught stealing is an out with no batter attached and it counts
    toward innings pitched, which is why leaving it out cost roughly 0.10
    outs a start.
    """
    bases = fr.bases
    if any(bases) and rng.random() < WP_PB_RATE:
        if bases[2]:
            _score(r, fr, 1)
        bases[:] = [False, bases[0], bases[1]]
        r.wp_pb += 1
    if bases[0] and not bases[1]:
        roll = rng.random()
        if roll < CS_RATE:
            bases[0] = False
            fr.outs += 1
            r.outs += 1
            r.caught_stealing += 1
        elif roll < CS_RATE + SB_RATE:
            # Second base is open or he would not be going.
            bases[0], bases[1] = False, True
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
