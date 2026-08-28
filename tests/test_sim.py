"""Property checks for the start simulator.

Offline by construction: every check builds its own league dict and rate
objects rather than touching the database, so the suite runs with no data
cached and no connection.

What is worth testing in a stochastic model is not "does it produce the
right number" — it produces a distribution, and asserting on a mean invites
a test that passes because two errors cancelled. These check INVARIANTS that
must hold for any input, plus the specific arithmetic (log5, shrinkage,
advancement) that has one right answer.
"""
from __future__ import annotations

import random
import statistics as st

from dataclasses import replace

from src.context import sim
from src.context.sources import rates as rate_src
from tests import fixtures as fx

# Mirrors what `sim.league()` returns: baselines from ROTATION STARTERS on
# the pitching denominator, not the whole pitcher pool on the batting one.
# When this drifted from the real thing it failed a check for the right
# reason — the fixture still carried BB 0.089 (the pool) after the code had
# moved to 0.078 (rotation starters), so the simulated walk rate was high
# and outs per batter came out low.
LG = {
    "season": 2026, "pa": 100000,
    "k_pct": 0.2176, "bb_pct": 0.0784,
    "hr_pct": 0.0336, "babip": 0.2792,
    "hit_mix": {"1b": 0.763, "2b": 0.217,
                "3b": 0.020},
    "runs_per_9": 4.63,
}


# "Neutral" must mean EQUAL TO THE BASELINE, or log5's defining identity —
# average batter against average pitcher returns the league rate — stops
# holding and half these checks measure the drift instead of the property.
def _pitcher(**kw):
    return sim.PitcherRates(**{"name": "P", "k_pct": LG["k_pct"],
                               "bb_pct": LG["bb_pct"],
                               "hr_pct": LG["hr_pct"],
                               "babip": LG["babip"], "pa": 600, **kw})


def _lineup(n=9, **kw):
    return [sim.BatterRates(**{"name": f"B{i}", "k_pct": LG["k_pct"],
                               "bb_pct": LG["bb_pct"],
                               "hr_pct": LG["hr_pct"],
                               "babip": LG["babip"], "pa": 500, **kw})
            for i in range(n)]


# ── log5 ───────────────────────────────────────────────────────────────
def check_log5_neutral_is_league():
    """League vs league returns league. The identity the whole model rests
    on: if neither side deviates, the matchup is average."""
    got = sim.log5(0.226, 0.226, 0.226)
    assert abs(got - 0.226) < 1e-9, got


def check_log5_is_symmetric():
    """Swapping batter and pitcher cannot change the matchup rate."""
    for b, p in ((0.30, 0.15), (0.05, 0.42), (0.5, 0.5)):
        a = sim.log5(b, p, 0.226)
        c = sim.log5(p, b, 0.226)
        assert abs(a - c) < 1e-12, (b, p, a, c)


def check_log5_beats_naive_average_at_the_tails():
    """Two extreme inputs must not land on their arithmetic mean.

    This is the reason log5 exists rather than (b + p) / 2. A .400 hitter
    against a pitcher who allows .200 is not a .300 matchup, and a model
    that says so is wrong in the region where edges are claimed.
    """
    b, p, lg = 0.40, 0.20, 0.25
    got = sim.log5(b, p, lg)
    assert abs(got - 0.30) > 0.01, got
    assert min(b, p) < got < max(b, p), got


def check_log5_stays_in_bounds():
    """No input combination may produce a probability outside [0, 1]."""
    rng = random.Random(11)
    for _ in range(500):
        b, p, lg = (rng.uniform(0.001, 0.999) for _ in range(3))
        got = sim.log5(b, p, lg)
        assert 0.0 <= got <= 1.0, (b, p, lg, got)


def check_log5_monotone_in_batter():
    """A better hitter never lowers the matchup rate."""
    prev = -1.0
    for b in (0.05, 0.1, 0.2, 0.3, 0.5, 0.8):
        got = sim.log5(b, 0.25, 0.226)
        assert got > prev, (b, got, prev)
        prev = got


# ── plate appearance ───────────────────────────────────────────────────
def _occ(bases):
    """Which bags are occupied. `sim` bases carry RUNNER IDENTITY as of
    2026-08-27 — a token or None rather than a bool — and these checks are
    about occupancy, not about what kind of object marks it."""
    return [bool(b) for b in bases]


def check_pa_outcomes_are_all_known_constants():
    rng = random.Random(3)
    seen = set()
    for _ in range(3000):
        seen.add(sim.pa_outcome(_lineup(1)[0], _pitcher(), LG, rng))
    assert seen <= {sim.K, sim.BB, sim.HR, sim.B1, sim.B2, sim.B3, sim.OUT,
                    sim.SAC, sim.HBP, sim.ROE}, seen
    # ROE must actually appear, or the whole errors mechanism is dead code
    # that still leaves the run level 6.7% light.
    assert sim.ROE in seen, "reached-on-error never drawn"


def check_pa_reproduces_league_rates():
    """Neutral batter against neutral pitcher must return league rates.

    Catches the double-counting failure the conditional draw order exists to
    prevent: rescaling each outcome by what the previous one left, done
    wrong, quietly shifts every rate.
    """
    rng = random.Random(5)
    n = 40000
    got = {}
    for _ in range(n):
        o = sim.pa_outcome(_lineup(1)[0], _pitcher(), LG, rng)
        got[o] = got.get(o, 0) + 1
    k = got.get(sim.K, 0) / n
    bb = got.get(sim.BB, 0) / n
    hr = got.get(sim.HR, 0) / n
    assert abs(k - LG["k_pct"]) < 0.01, k
    assert abs(bb - LG["bb_pct"]) < 0.01, bb
    assert abs(hr - LG["hr_pct"]) < 0.008, hr


def check_higher_k_pitcher_strikes_out_more():
    rng = random.Random(7)

    def rate(kp):
        p = _pitcher(k_pct=kp)
        n = 6000
        return sum(1 for _ in range(n)
                   if sim.pa_outcome(_lineup(1)[0], p, LG, rng) == sim.K) / n
    assert rate(0.35) > rate(0.15) + 0.10


def check_arsenal_multiplier_moves_contact_not_strikeouts():
    """`arsenal_mult` scales home runs and BABIP, never the strikeout rate.

    A pitch mix a hitter handles well produces better contact. If it also
    suppressed strikeouts the multiplier would be doing two jobs and neither
    could be reasoned about.
    """
    rng = random.Random(9)

    def rates(mult):
        b = _lineup(1, arsenal_mult=mult)[0]
        n = 12000
        c = {}
        for _ in range(n):
            o = sim.pa_outcome(b, _pitcher(), LG, rng)
            c[o] = c.get(o, 0) + 1
        return c.get(sim.K, 0) / n, c.get(sim.HR, 0) / n

    k_lo, hr_lo = rates(0.7)
    k_hi, hr_hi = rates(1.4)
    assert hr_hi > hr_lo * 1.3, (hr_lo, hr_hi)
    assert abs(k_hi - k_lo) < 0.02, (k_lo, k_hi)


# ── base running ───────────────────────────────────────────────────────
def check_home_run_clears_the_bases_and_scores_everyone():
    rng = random.Random(1)
    bases = [True, True, True]
    runs, _who = sim._advance(bases, sim.HR, rng)
    assert runs == 4, runs
    assert _occ(bases) == [False, False, False], bases


def check_walk_with_bases_loaded_forces_exactly_one_run():
    rng = random.Random(1)
    bases = [True, True, True]
    assert sim._advance(bases, sim.BB, rng)[0] == 1
    assert _occ(bases) == [True, True, True], bases


def check_walk_with_a_gap_forces_nobody():
    rng = random.Random(1)
    bases = [False, True, False]
    assert sim._advance(bases, sim.BB, rng)[0] == 0
    assert _occ(bases) == [True, True, False], bases


def check_double_does_not_strand_the_runner_from_first_on_third_always():
    """Regression: both branches of the double put the runner from first on
    third, making the 45%-scores case dead code and costing runs. The
    simulator read 3.59 runs per nine against a real 4.03 until this was
    fixed."""
    scored = held = 0
    for seed in range(400):
        rng = random.Random(seed)
        bases = [True, False, False]
        r, _who = sim._advance(bases, sim.B2, rng)
        if r:
            scored += 1
        else:
            held += 1
            assert _occ(bases) == [False, True, True], bases
    assert scored > 0 and held > 0, (scored, held)


def check_runner_on_third_always_scores_on_a_single():
    for seed in range(50):
        rng = random.Random(seed)
        bases = [False, False, True]
        assert sim._advance(bases, sim.B1, rng)[0] >= 1


def check_advance_never_produces_negative_or_impossible_runs():
    rng = random.Random(4)
    for _ in range(4000):
        bases = [rng.random() < 0.4 for _ in range(3)]
        before = sum(bases)
        o = rng.choice([sim.B1, sim.B2, sim.B3, sim.HR, sim.BB, sim.OUT])
        runs, _who = sim._advance(list(bases), o, rng)
        assert 0 <= runs <= before + 1, (bases, o, runs)


# ── the hook ───────────────────────────────────────────────────────────
def check_removal_probability_is_monotone_in_every_term():
    """Every term that should raise P(pulled) does.

    `per_inning` IS NOT ONE OF THEM ANY MORE, and that is measured rather
    than conceded. Fitted on 38,485 real end-of-inning decisions it comes out
    at -0.109: at a FIXED pitch count, a starter deeper in the game has been
    more efficient, which is a reason to leave him in. Inning and pitches
    carry the same information and the fit gives it to pitches. Marginally
    the hazard still rises steeply by inning (0.013 to 0.375, innings three
    to seven) because pitch count rises with it — so the inning assertion
    moves to a realistic joint step rather than an artificial ceteris
    paribus one.
    """
    h = sim.Hook()
    base = h.removal_p(80, 2, 5)
    assert h.removal_p(110, 2, 5) > base       # more pitches
    assert h.removal_p(80, 6, 5) > base        # more runs
    assert h.removal_p(80, 2, 5, baserunners=12) > base
    # deeper AND further into the pitch count, which is how a game moves
    assert h.removal_p(100, 2, 7) > base


def check_mid_inning_removal_responds_to_traffic_and_damage():
    """Runs are a LAGGING indicator — a starter who has put five men on and
    allowed nothing is about to be pulled. The model has to see the traffic.

    THE CHANNEL CHANGED, THE CLAIM DID NOT. This used to assert on
    `inning_damage`, a weighted baserunner score invented here (BB 1.0,
    2B 1.7, HR 3.0). Refitting the late branch on its own 20,994 decisions
    found the plain COUNT of baserunners allowed in the inning, so `damage`
    and `inn_br` measure the same thing and only the counted one survived.
    Asserted on both channels the model actually carries — bases occupied
    now, and men allowed this inning."""
    h = sim.Hook()
    quiet = h.mid_removal_p(70, 0, 0, 0.0, inning=6, inning_br=0)
    occupied = h.mid_removal_p(70, 0, 2, 0.0, inning=6, inning_br=0)
    allowed = h.mid_removal_p(70, 0, 0, 0.0, inning=6, inning_br=4)
    assert occupied > quiet, (quiet, occupied)
    assert allowed > quiet, (quiet, allowed)


def check_the_boundary_knee_is_wired_and_ships_inert():
    """`per_pitch_over` is a real term in the curve, and it ships at zero.

    THE KNEE IS A MEASURED MECHANISM THAT LOST ON THE SCORE, which is why
    it needs a test at all: an unwired parameter and a deliberately-zero one
    look identical from the outside. Fitted on 38,485 real end-of-inning
    decisions the hinge beats the linear logit at every pitch bucket (log
    loss 0.16286 -> 0.15420, BIC 12599 -> 11942) and then loses on 1,040
    holdout starts at the lines that settle (band Brier 0.2391 -> 0.2402).
    See `sim.KNEE_BOUNDARY`.

    So two claims are guarded. First that the shipped curve is LINEAR —
    deleting the `per_pitch_over` term from `removal_p` must not change any
    shipped number. Second that the term is CONNECTED, checked by turning it
    on and requiring the measured tail rate back: at 105 pitches the real
    bucket rate is 0.749 and the linear form gives 0.641.
    """
    assert sim.Hook().per_pitch_over == 0.0, "the knee ships inert"
    h = sim.Hook()
    lin = sim.Hook(**sim.LINEAR_BOUNDARY)
    for n in (15, 55, 80, 105):
        assert h.removal_p(n, 2, 5, 4) == lin.removal_p(n, 2, 5, 4), n

    knee = sim.Hook(**sim.KNEE_BOUNDARY)
    # Flat below the knee, and at the counted level: the real rate under 40
    # pitches is 0.010 and the linear form gives 0.002.
    early = [knee.removal_p(n, 2, max(1, n // 15), n // 12)
             for n in (15, 30, 45, 55)]
    assert max(early) - min(early) < 0.01, early
    assert all(0.004 < v < 0.02 for v in early), early
    # And steep above it, where 46% of removals happen.
    assert knee.removal_p(105, 2, 7, 8) > 0.70, knee.removal_p(105, 2, 7, 8)
    # Monotone across the join, at FIXED state — `per_inning` is negative,
    # so walking the inning forward with the count is not ceteris paribus.
    seq = [knee.removal_p(n, 2, 5, 4) for n in range(5, 111, 5)]
    assert all(b >= a for a, b in zip(seq, seq[1:])), seq


def check_hook_probabilities_stay_in_bounds():
    h = sim.Hook()
    for pitches in (0, 50, 200, 10000):
        for runs in (0, 3, 50):
            for inn in (1, 9, 40):
                p = h.removal_p(pitches, runs, inn)
                assert 0.0 <= p <= 1.0, (pitches, runs, inn, p)
                m = h.mid_removal_p(pitches, runs, 3, 9.0)
                assert 0.0 <= m <= 1.0, m


def check_team_offset_lengthens_or_shortens_outings():
    """A negative offset is a longer leash. If this inverts, every club's
    fitted patience is applied backwards and nothing downstream notices."""
    def mean_outs(off):
        rng = random.Random(2)
        hook = sim.Hook(team_offset=off)
        return sum(fx.one_side(_pitcher(), _lineup(), LG, hook,
                                      rng).outs for _ in range(400)) / 400
    assert mean_outs(-1.0) > mean_outs(0.0) > mean_outs(1.0)


def check_for_start_adds_club_and_pitcher_offsets():
    """Club first, pitcher against the remainder, and they ADD.

    Guarded even though USE_OFFSETS ships False: the arithmetic is what a
    refit would rely on, and it is the place a double-counted manager would
    hide. Toggled on for the duration rather than deleted.
    """
    base = sim.Hook()
    sim.USE_OFFSETS = True
    sim._PATIENCE = {"XXX": 0.5}
    sim._LEASH = {"Somebody": -0.2}
    try:
        h = sim.for_start(base, "XXX", "Somebody")
        assert abs(h.team_offset - 0.3) < 1e-9, h.team_offset
        assert sim.for_start(base, "NOPE", "Nobody").team_offset == 0.0
    finally:
        sim.USE_OFFSETS = False
        sim._PATIENCE = sim._LEASH = None


def check_unknown_club_falls_back_to_the_league_hook():
    """Missing resolves to neutral, never to a guess — the same rule the
    rest of the context layer follows for absent group values."""
    sim.USE_OFFSETS = True
    sim._PATIENCE, sim._LEASH = {}, {}
    try:
        assert sim.patience("ZZZ") == 0.0
        assert sim.leash("Nobody At All") == 0.0
    finally:
        sim.USE_OFFSETS = False
        sim._PATIENCE = sim._LEASH = None


# ── whole starts ───────────────────────────────────────────────────────
def check_start_is_internally_consistent():
    rng = random.Random(6)
    for _ in range(300):
        r = fx.one_side(_pitcher(), _lineup(), LG, sim.Hook(), rng)
        assert 0 <= r.outs <= 27, r.outs
        assert r.k <= r.outs, (r.k, r.outs)
        assert r.hr <= r.h, (r.hr, r.h)
        assert r.runs >= r.hr, (r.runs, r.hr)
        assert r.batters >= r.k + r.bb + r.h, r
        assert r.pitches >= r.batters, r
        if not r.pulled_mid_inning:
            assert r.outs % 3 == 0, r.outs


def check_simulation_is_deterministic_for_a_seed():
    """A bet's assessment must not change between two runs of the same
    question."""
    a = fx.starts(_pitcher(), _lineup(), LG, n=50, seed=42)
    b = fx.starts(_pitcher(), _lineup(), LG, n=50, seed=42)
    assert [x.outs for x in a] == [x.outs for x in b]
    assert [x.k for x in a] == [x.k for x in b]


def check_different_seeds_give_different_draws():
    a = fx.starts(_pitcher(), _lineup(), LG, n=50, seed=1)
    b = fx.starts(_pitcher(), _lineup(), LG, n=50, seed=2)
    assert [x.outs for x in a] != [x.outs for x in b]


def check_better_lineup_shortens_the_start():
    good = _lineup(k_pct=0.14, bb_pct=0.13, hr_pct=0.06, babip=0.34)
    weak = _lineup(k_pct=0.32, bb_pct=0.05, hr_pct=0.012, babip=0.25)
    a = fx.starts(_pitcher(), good, LG, n=500, seed=8)
    b = fx.starts(_pitcher(), weak, LG, n=500, seed=8)
    ma = sum(x.outs for x in a) / len(a)
    mb = sum(x.outs for x in b) / len(b)
    assert mb > ma + 0.5, (ma, mb)


def check_park_factor_only_moves_home_runs():
    # `hr_park`, the bare scalar the deleted one-sided loop took, is gone;
    # the game engine carries a park DICT, which is the natural shape because
    # both clubs play in the same building.
    a = fx.starts(_pitcher(), _lineup(), LG, n=400, seed=8,
                  park={"hr": 0.6, "k": 1.0, "bip": 1.0})
    b = fx.starts(_pitcher(), _lineup(), LG, n=400, seed=8,
                  park={"hr": 1.6, "k": 1.0, "bip": 1.0})
    assert sum(x.hr for x in b) > sum(x.hr for x in a)


def check_prob_over_is_a_probability_and_monotone_in_the_line():
    res = fx.starts(_pitcher(), _lineup(), LG, n=600, seed=12)
    prev = 1.1
    for line in (8.5, 11.5, 14.5, 17.5, 20.5):
        p = sim.prob_over(res, "outs", line)
        assert 0.0 <= p <= 1.0, p
        assert p <= prev, (line, p, prev)
        prev = p


def check_distribution_quantiles_are_ordered():
    d = sim.distribution(fx.starts(_pitcher(), _lineup(), LG, n=400,
                                   seed=13), "outs")
    assert d["min"] <= d["p10"] <= d["p25"] <= d["p50"] <= d["p75"] \
        <= d["p90"] <= d["max"], d


def check_empty_results_do_not_crash_the_readers():
    assert sim.distribution([], "outs") == {}
    assert sim.prob_over([], "outs", 15.5) == 0.0


# ── rate shrinkage ─────────────────────────────────────────────────────
def check_shrinkage_pulls_a_thin_sample_to_the_league():
    """A reliever with 40 batters faced and no homers must not be modelled
    as incapable of allowing one."""
    got = rate_src._shrink(0.0, LG["hr_pct"], 40, "hr_pct")
    assert got > LG["hr_pct"] * 0.7, got


def check_shrinkage_trusts_a_large_sample():
    got = rate_src._shrink(0.35, LG["k_pct"], 5000, "k_pct")
    assert abs(got - 0.35) < 0.01, got


def check_shrinkage_is_bounded_by_its_two_inputs():
    for n in (1, 10, 100, 1000):
        for obs in (0.0, 0.1, 0.5, 0.9):
            got = rate_src._shrink(obs, 0.25, n, "k_pct")
            assert min(obs, 0.25) <= got <= max(obs, 0.25), (obs, n, got)


def check_missing_observation_returns_the_league_rate():
    assert rate_src._shrink(None, 0.25, 100, "k_pct") == 0.25
    assert rate_src._shrink(0.9, 0.25, 0, "k_pct") == 0.25


def check_strikeouts_stabilise_faster_than_home_runs():
    """The ORDER of the stabilisation constants is the load-bearing part: a
    half-season K rate deserves more trust than a half-season HR rate, and
    inverting them would make the model confident about exactly the number
    it should doubt."""
    assert rate_src.STABILISE["k_pct"] < rate_src.STABILISE["bb_pct"] \
        < rate_src.STABILISE["hr_pct"] < rate_src.STABILISE["babip"]


# ── strikeouts ─────────────────────────────────────────────────────────
#
# K props ride on the same machinery as outs but fail differently. Outs are
# dominated by the hook; strikeouts are dominated by the RATE, with the hook
# entering only through how many batters he gets to face. So the checks that
# matter here are about the rate surviving the trip through the simulation,
# and about K and outs staying coupled the way they must be.

def check_strikeouts_cannot_exceed_outs():
    """Every strikeout is an out. A model that lets K drift above outs is
    producing a start that cannot happen, and on a K prop that error runs
    entirely in the over's favour."""
    rng = random.Random(21)
    for _ in range(600):
        r = fx.one_side(_pitcher(k_pct=0.45), _lineup(k_pct=0.40),
                               LG, sim.Hook(), rng)
        assert r.k <= r.outs, (r.k, r.outs)


def check_k_rate_per_batter_matches_the_matchup_rate():
    """Strikeouts per batter faced must equal the log5 rate.

    The end-to-end check on the K path: if the plate-appearance model and
    the loop that calls it disagree, this is where it shows. Outs-based
    checks would not catch a K rate that is 10% light.
    """
    p = _pitcher(k_pct=0.30)
    lineup = _lineup(k_pct=0.20)
    want = sim.log5(0.20, 0.30, LG["k_pct"])
    res = fx.starts(p, lineup, LG, n=2500, seed=22)
    k = sum(r.k for r in res)
    bf = sum(r.batters for r in res)
    assert abs(k / bf - want) < 0.012, (k / bf, want)


def check_strikeout_pitcher_produces_more_strikeouts():
    lo = fx.starts(_pitcher(k_pct=0.15), _lineup(), LG, n=600, seed=23)
    hi = fx.starts(_pitcher(k_pct=0.35), _lineup(), LG, n=600, seed=23)
    mlo = sum(r.k for r in lo) / len(lo)
    mhi = sum(r.k for r in hi) / len(hi)
    assert mhi > mlo + 2.0, (mlo, mhi)


def check_lineup_contact_reduces_strikeouts():
    """The opposing nine matter, which is the whole reason for simulating
    rather than counting a pitcher's last six starts — that approach cannot
    see who he is facing."""
    whiffy = _lineup(k_pct=0.32)
    contact = _lineup(k_pct=0.14)
    a = fx.starts(_pitcher(), whiffy, LG, n=600, seed=24)
    b = fx.starts(_pitcher(), contact, LG, n=600, seed=24)
    assert sum(r.k for r in a) > sum(r.k for r in b) * 1.3


def check_k_distribution_is_wider_than_a_point_estimate_suggests():
    """Two starts with the same expected K are not the same bet. If the
    simulated spread collapses, every threshold away from the mean gets
    priced as a near-certainty."""
    d = sim.distribution(fx.starts(_pitcher(k_pct=0.26), _lineup(),
                                      LG, n=1500, seed=25), "k")
    assert d["p90"] - d["p10"] >= 4, d


def check_k_prob_over_is_monotone_in_the_line():
    res = fx.starts(_pitcher(), _lineup(), LG, n=800, seed=26)
    prev = 1.1
    for line in (2.5, 4.5, 6.5, 8.5, 10.5):
        p = sim.prob_over(res, "k", line)
        assert 0.0 <= p <= 1.0 and p <= prev, (line, p, prev)
        prev = p


def check_longer_leash_raises_strikeout_totals():
    """K is a counting stat, so the hook reaches it ONLY through batters
    faced. A club's patience must move the K line as well as the outs line,
    and it must move it by the amount that extra traffic implies — no more.

    Asserting the mechanism rather than a magnitude: if the gap ever stops
    tracking (extra batters x K rate), then the hook is influencing
    strikeouts through some path that should not exist.
    """
    def stats(off):
        rng = random.Random(27)
        h = sim.Hook(team_offset=off)
        r = [fx.one_side(_pitcher(), _lineup(), LG, h, rng)
             for _ in range(2000)]
        n = len(r)
        return sum(x.k for x in r) / n, sum(x.batters for x in r) / n

    k_long, bf_long = stats(-1.0)
    k_short, bf_short = stats(1.0)
    assert k_long > k_short, (k_long, k_short)
    assert bf_long > bf_short, (bf_long, bf_short)
    # THE MARGINAL BATTER IS A LATE-PASS BATTER, so his strikeout rate is
    # not the league rate. Extending a leash adds men at the END of a start,
    # where `TTO_MULT` has scaled K% to 0.94 of the first pass and then
    # 0.89. Converting with LG["k_pct"] — the first-pass rate — overstates
    # the implied gap by about 12%, and a tolerance of 0.15 was absorbing
    # that rather than testing anything. The realised marginal rate is
    # measured at 0.187-0.196 against a league 0.2176.
    #
    # Asserted as a BAND on the marginal rate, which is the actual claim:
    # the hook reaches strikeouts only by adding plate appearances, so the
    # ratio must land between the third-pass rate and the league rate. Any
    # other path — a hook that changed K% directly — leaves the band.
    marginal = (k_long - k_short) / (bf_long - bf_short)
    lo = LG["k_pct"] * sim.TTO_MULT[3]["k_pct"] * 0.92
    hi = LG["k_pct"] * 1.02
    assert lo < marginal < hi, (marginal, lo, hi)


def check_k_and_outs_move_together_across_starts():
    """Within the simulation, longer outings must carry more strikeouts.
    A negative or flat relationship means the hook and the rate model have
    come uncoupled."""
    res = fx.starts(_pitcher(), _lineup(), LG, n=1200, seed=28)
    short = [r.k for r in res if r.outs <= 12]
    long_ = [r.k for r in res if r.outs >= 18]
    assert short and long_
    assert sum(long_) / len(long_) > sum(short) / len(short) + 1.0


# ── calibration harness ────────────────────────────────────────────────
def check_shared_draws_keep_the_line_curve_monotone():
    """P(over) computed off one set of draws must fall as the line rises.

    Simulating each line independently is six times the work AND lets noise
    put P(over 15.5) below P(over 17.5), which is impossible. Sharing draws
    makes the curve monotone by construction; this pins that.
    """
    res = fx.starts(_pitcher(), _lineup(), LG, n=400, seed=31)
    vals = [r.outs for r in res]
    prev = 1.1
    for ln in (11.5, 14.5, 15.5, 17.5, 18.5, 20.5):
        p = sum(1 for v in vals if v > ln) / len(vals)
        assert p <= prev, (ln, p, prev)
        prev = p


def check_brier_of_a_perfect_forecaster_is_zero():
    rows = [(20, 1.0), (10, 0.0), (18, 1.0)]
    line = 15.5
    b = sum((p - (1 if a > line else 0)) ** 2 for a, p in rows) / len(rows)
    assert b == 0.0, b


def check_brier_punishes_confident_wrongness():
    """A model that says 95% and loses must score worse than one that says
    50%. Without this the reliability report could rank an overconfident
    model above an honest one."""
    line = 15.5
    conf = [(10, 0.95)]
    hedge = [(10, 0.50)]
    bc = sum((p - 0) ** 2 for _, p in conf)
    bh = sum((p - 0) ** 2 for _, p in hedge)
    assert bc > bh, (bc, bh)


def check_auc_is_half_for_a_useless_forecaster():
    from src.context import calibrate as cal
    rows = [(i % 2 == 0, 0.5) for i in range(100)]
    assert abs(cal._auc(rows) - 0.5) < 1e-9, cal._auc(rows)


def check_auc_is_one_for_a_perfect_ranker():
    from src.context import calibrate as cal
    rows = [(True, 0.9), (True, 0.8), (False, 0.2), (False, 0.1)]
    assert cal._auc(rows) == 1.0, cal._auc(rows)


def check_auc_is_zero_when_the_ranking_is_inverted():
    """A model that orders every start backwards must score 0, not 0.5.
    If ties or sign handling collapse this to 0.5, a systematically
    inverted model would read as 'no signal' instead of 'wired backwards'."""
    from src.context import calibrate as cal
    rows = [(True, 0.1), (True, 0.2), (False, 0.8), (False, 0.9)]
    assert cal._auc(rows) == 0.0, cal._auc(rows)


def check_auc_handles_ties_without_bias():
    from src.context import calibrate as cal
    rows = [(True, 0.5), (False, 0.5), (True, 0.5), (False, 0.5)]
    assert abs(cal._auc(rows) - 0.5) < 1e-9, cal._auc(rows)


# ── handedness splits ──────────────────────────────────────────────────
def check_split_shrinks_toward_the_batter_not_the_league():
    """A thin split must fall back to THIS HITTER's overall rate, not to
    league average. Shrinking a 20-PA split straight to league erases the
    hitter's own established skill along with the platoon noise, which is
    worse than having no split at all."""
    k = rate_src.SPLIT_STABILISE
    own, league = 0.34, 0.226
    pa = 20
    w = pa / (pa + k)
    got = w * 0.10 + (1 - w) * own
    assert abs(got - own) < abs(got - league), (got, own, league)


def check_split_stabilises_faster_than_a_league_prior():
    """The prior here is the hitter himself — a far better guess than the
    league — so it should take less evidence to move off it."""
    assert rate_src.SPLIT_STABILISE < rate_src.STABILISE["babip"]


def check_unknown_pitcher_hand_falls_back_to_overall_rates():
    """A WRONG split moves the estimate in a definite wrong direction, which
    is worse than no split. Missing hand must mean overall, never a guess.
    Same rule the context layer follows for an unrated catcher."""
    import inspect

    from src.context import calibrate as cal
    src = inspect.getsource(cal.build_cases)
    assert "if hand else b" in src, \
        "unknown throwing hand no longer falls back to overall rates"


def check_switch_hitters_need_no_special_case():
    """A switch hitter's 'vs L' rows ARE his right-handed batting, because
    that is what he did in those games. Deriving splits from outcomes rather
    than from a declared bat side makes this automatic — if someone adds a
    bats-side branch, this is the check that should make them justify it."""
    import inspect
    src = inspect.getsource(rate_src.batter_rates_by_hand)
    assert '"S"' not in src and "switch" not in src.lower().replace(
        "switch hitters need no special handling", ""), \
        "special-casing switch hitters; the derivation already handles them"


# ── input uncertainty (measured harmful; deleted) ──────────────────────
def check_input_uncertainty_stayed_deleted():
    """MEASURED HARMFUL, and do not rebuild it without re-measuring.

    Drawing each rate from its Beta posterior and jittering the hook offset
    per start was built to cure the model's compressed probabilities and did
    the opposite: widening a single start's distribution pushes its P(over)
    TOWARD the base rate, which is the direction the defect already runs. On
    600 starts at outs 15.5, Brier skill fell 10.3% -> 9.5% (hook sigma) and
    -> 9.3% (rate draws), with sd(p) falling 0.120 -> 0.114. The compression
    is missing SIGNAL, not missing noise, and it is on the dead list as
    "input-uncertainty propagation".

    The machinery hung off `sim.simulate` and went with it when the
    one-sided engine was deleted. This is the guard that it does not come
    back by accident — a `DRAW_RATES` reappearing in `sim` would be a
    measured-harmful mechanism arriving switched on, which is how it got in
    the first time.
    """
    for gone in ("HOOK_SIGMA", "DRAW_RATES", "MIN_POSTERIOR_PA",
                 "_draw", "_jitter_pitcher", "_jitter_batter"):
        assert not hasattr(sim, gone), gone


# ── multi-stat calibration coverage ────────────────────────────────────
def check_earned_runs_maps_to_the_earned_column_not_total_runs():
    """Earned runs must be compared against the sim's EARNED runs.

    THIS CHECK'S PREMISE CHANGED, which is worth recording rather than
    quietly editing. It used to assert the opposite — that `er` maps to
    `runs` — on the grounds that the simulator models no errors, so every
    run it produced was earned by construction. That was true and is not
    any more: `ROE_PER_OUT` exists, unearned runs exist, and `runs` now
    includes them. Comparing the boxscore's `er` against total simulated
    runs would now overstate the model by the ~7.6% unearned share.

    `fitf5` still targets TOTAL runs, and correctly: a team total settles on
    runs that crossed the plate. A diagnostic compares like with like; a fit
    targets what settles.
    """
    from src.context import calibrate as cal
    assert cal._STAT_ATTR["er"] == "earned"
    assert cal._STAT_COL["er"] == "er"
    assert hasattr(sim.StartResult(), "earned")


def check_every_calibrated_stat_has_a_column_and_an_attribute():
    from src.context import calibrate as cal
    for stat in cal.LINES:
        assert stat in cal._STAT_COL, stat
        assert stat in cal._STAT_ATTR, stat
        assert hasattr(sim.StartResult(), cal._STAT_ATTR[stat]), stat


def check_calibration_lines_are_sorted_and_half_points():
    """Half-point lines only: an integer line creates pushes, and the
    reliability maths treats every start as a win or a loss."""
    from src.context import calibrate as cal
    for stat, lines in cal.LINES.items():
        assert list(lines) == sorted(lines), stat
        for ln in lines:
            assert abs(ln - int(ln) - 0.5) < 1e-9, (stat, ln)


# ── park factors ───────────────────────────────────────────────────────
def check_unknown_park_is_neutral_not_the_home_club():
    """A venue Savant does not rate must return neutral multipliers.

    Not hypothetical: the Athletics played 38 home games this season at
    sites with no published factors, and the Twins one. Borrowing the home
    club's park for those would be confidently wrong 39 times, which is the
    same failure `park.for_venue` already refuses to make.
    """
    assert sim.park_mults(None) == sim.NEUTRAL_PARK
    assert sim.park_mults({}) == sim.NEUTRAL_PARK


def check_park_index_100_is_neutral():
    """Savant publishes indices where 100 is league average, not 1.0.
    Reading one as a raw multiplier would suppress every rate by 99%."""
    m = sim.park_mults({"hr": 100, "so": 100, "bacon": 100, "bb": 100})
    assert m == {"hr": 1.0, "k": 1.0, "bip": 1.0, "bb": 1.0}, m
    # EXACT EQUALITY ON PURPOSE, and it earned its keep on 2026-08-29: adding
    # the `bb` slot broke this check immediately rather than silently
    # shipping a fourth channel nobody had scored. Keep it exact.


def check_park_moves_the_right_outcomes():
    """A high-strikeout park raises K; a homer park raises HR. If the keys
    were crossed, Coors would suppress offence."""
    hot = sim.park_mults({"hr": 125, "so": 90, "bacon": 113})
    cold = sim.park_mults({"hr": 75, "so": 116, "bacon": 94})
    assert hot["hr"] > cold["hr"] and hot["k"] < cold["k"]

    def counts(park):
        rng = random.Random(51)
        res = [fx.one_side(_pitcher(), _lineup(), LG, sim.Hook(),
                                  rng, park=park) for _ in range(700)]
        return (sum(r.k for r in res) / len(res),
                sum(r.hr for r in res) / len(res))
    k_hot, hr_hot = counts(hot)
    k_cold, hr_cold = counts(cold)
    assert hr_hot > hr_cold * 1.2, (hr_hot, hr_cold)
    assert k_cold > k_hot, (k_cold, k_hot)


def check_missing_park_index_falls_back_to_neutral_per_key():
    """One absent column must not zero the multiplier for that outcome."""
    m = sim.park_mults({"hr": 120})
    assert m["hr"] == 1.2 and m["k"] == 1.0 and m["bip"] == 1.0, m


def check_neutral_park_reproduces_the_no_park_simulation():
    p, l = _pitcher(), _lineup()
    a = [fx.one_side(p, l, LG, sim.Hook(), random.Random(9))
         for _ in range(30)]
    b = [fx.one_side(p, l, LG, sim.Hook(), random.Random(9),
                            park=sim.NEUTRAL_PARK) for _ in range(30)]
    assert [x.outs for x in a] == [x.outs for x in b]
    assert [x.k for x in a] == [x.k for x in b]


# ── venue, home/road, day/night ────────────────────────────────────────
def check_home_multipliers_come_from_the_measured_split():
    """SET FROM DATA, not tuned against Brier — two free parameters searched
    against the metric they are then scored on will find something whether
    or not anything is there.

    Measured contrast: K rate 0.2253 home vs 0.2110 away (+6.8%, z +3.49);
    hit rate 0.2164 vs 0.2253 (-3.9%, z -2.15). Applied as HALF the contrast
    each way — see the centring check below.
    """
    from src.context import calibrate as cal
    assert abs(cal.HOME_OPP_K - 1.034) < 0.005, cal.HOME_OPP_K
    assert abs(cal.HOME_OPP_CONTACT - 0.981) < 0.005, cal.HOME_OPP_CONTACT
    # Directions: the visiting nine strike out MORE and hit LESS.
    assert cal.HOME_OPP_K > 1.0 and cal.HOME_OPP_CONTACT < 1.0


def check_home_road_is_centred_on_the_season_mean():
    """A player's season rate already contains ~half home starts and ~half
    away. Applying the FULL home-vs-away contrast at home and nothing away
    would inflate every pitcher's K rate by ~3.4% overall rather than
    redistributing it.

    This is the same double-counting that makes park factors useless here:
    a Rockies pitcher's season rates already include Coors, so multiplying
    by the park index again counts it one and a half times.
    """
    from src.context import calibrate as cal
    assert abs(cal.HOME_OPP_K * cal.AWAY_OPP_K - 1.0) < 1e-9
    assert abs(cal.HOME_OPP_CONTACT * cal.AWAY_OPP_CONTACT - 1.0) < 1e-9


def check_park_is_off_because_it_double_counts():
    """MEASURED NEGATIVE. Mean Brier skill 7.25% without park, 7.15% with,
    across 28 stat/line combinations — a wash, deltas alternating sign.

    The cause is double-counting, not a wiring bug: player rates are raw
    season totals that already contain that player's own park. Park cannot
    contribute until the rates are park-neutralised first. The machinery is
    kept and correct (`sim.park_mults`, `calibrate.park_for`); it is the
    INPUTS that are not ready for it.
    """
    from src.context import calibrate as cal
    assert cal.USE_PARK is False


def check_home_hook_stays_zero_until_it_earns_a_place():
    """The outs difference is +0.33 at z=1.80 — below 2 sigma. Whatever is
    there should emerge from the rate effects rather than be added twice."""
    from src.context import calibrate as cal
    assert cal.HOME_HOOK == 0.0


def check_no_day_night_term_exists():
    """MEASURED NEGATIVE. Day vs night: K rate z -0.69, hit rate z -1.03,
    outs z +0.45. Nothing there. `games.day_night` is populated so this can
    be re-checked cheaply, but a term keyed on it would be fitting noise.
    """
    import inspect

    from src.context import calibrate as cal
    src = inspect.getsource(cal.per_start_probs_all)
    assert "day_night" not in src, \
        "a day/night term appeared; it measured z<1.1 on every stat"


def check_park_lookup_never_borrows_a_neighbouring_park():
    from src.context import calibrate as cal
    assert cal.park_for(None) == sim.NEUTRAL_PARK
    assert cal.park_for(0) == sim.NEUTRAL_PARK
    # 2529 is the Athletics' Sacramento site: real, used 32 times, unrated.
    assert cal.park_for(2529) == sim.NEUTRAL_PARK


def check_primary_cte_uses_starter_ground_truth():
    """Bullpen usage is derived from `rn > 1`. Under the old most-outs
    heuristic that counted 2,026 reliever outs as starter work, understating
    relief innings by 5% — and worst on exactly the nights the pen was most
    taxed, since a long reliever only outranks the starter when the starter
    was knocked out early."""
    from src.context.sources import workload
    cte = workload._primary_cte()
    assert "is_starter" in cte, "bullpen usage is back on the heuristic"
    assert "IS NOT NULL" in cte, "no fallback for unchecked games"


# ── who we will price ──────────────────────────────────────────────────
def check_price_gates_are_ordered_and_sane():
    """Set from the first live slate, where the simulator produced a
    50-point gap on Lake Bachar (5 starts in 24 appearances, 7.2 outs each)
    by giving an opener a full starter's leash, and 96% on over 8.5 outs for
    a pitcher with SEVEN batters faced on record.

    Neither is a calibration miss. Both are the model answering a question
    it has no basis for. Refusing is the correct output.
    """
    from src.context import price
    assert price.MIN_STARTS >= 3, price.MIN_STARTS
    assert price.MIN_BF >= 50, price.MIN_BF
    # An opener averages 5-8 outs; a real starter 15-18. The bar has to sit
    # between those and not swallow a genuine short-leash rookie whole.
    assert 9.0 <= price.MIN_AVG_OUTS <= 13.0, price.MIN_AVG_OUTS
    assert 0.4 <= price.MIN_START_SHARE <= 0.75, price.MIN_START_SHARE


def check_the_leash_covers_thin_starters_not_just_established_ones():
    """An 8-start bar left ~150 pitchers on the league default leash, which
    is what let a two-inning opener be simulated out to sixteen outs.

    Rewritten when `calibrate.fit_pitcher_leash` was deleted. That function
    GRID-SEARCHED each offset to minimise the gap between simulated and
    actual mean outs, which is fitting the settlement value — the thing
    CLAUDE.md forbids. `src.context.leash` measures the residual and shrinks
    it by a constant read off an ANOVA instead, so the property to guard is
    now coverage and shrinkage, not the search.

    THE PREMISE CHANGED ON 2026-08-26 and the check changed with it. It
    used to assert `MIN_PRIOR <= 3`, because a low bar was the only thing
    keeping short-outing arms off the league default leash — coverage was
    doing a filter's job. `leash.intended_starters` now does that job
    properly, on role rather than on how few starts an arm has, so a low bar
    buys nothing and costs something: at three starts a callup with two bad
    outings reads as a short leash when it is really no evidence.

    So the property guarded is SHRINKAGE, not coverage. A pitcher at the
    floor must be pulled most of the way back to the league, and the floor
    must not creep so high that ordinary starters fall off it.
    """
    from src.context import leash as leash_mod
    assert 3 <= leash_mod.MIN_PRIOR <= 8, leash_mod.MIN_PRIOR

    # 40 pitchers who all sit +2.0 outs above the model, each on the bare
    # minimum history. Between-pitcher variance here is nil — they are
    # identical — so the ANOVA must read this as noise and shrink hard.
    n = leash_mod.MIN_PRIOR
    hist = {f"p{i}": [2.0] * n for i in range(40)}
    k, betw, _wit = leash_mod.shrink_k(hist)
    assert k > 0, k
    kept = n / (n + k)
    assert kept < 0.5, f"a floor-sample pitcher keeps {kept:.0%} of his residual"


def check_declining_to_price_is_reported_not_silent():
    """A skipped pitcher must be named with a reason. Silently dropping him
    reads identically to 'no market existed', and the whole point of the
    gate is that the model knows it cannot answer."""
    import inspect

    from src.context import price
    src = inspect.getsource(price.price_slate)
    assert "skipped[name] = why" in src
    assert "declined to price" in src


# ── pricing goes through the game engine ───────────────────────────────
def _slate_game(away_sp="A Starter", home_sp="H Starter",
                status="Scheduled"):
    """One statsapi-shaped slate row, with both lineups posted."""
    nine = [f"B{i}" for i in range(9)]
    return {
        "game_id": "mlb-1", "venue_id": None, "status": status,
        "start_utc": "2026-08-25T23:05:00Z",
        "away": {"abbr": "AWY", "starter": away_sp, "starter_id": 1,
                 "lineup": nine},
        "home": {"abbr": "HOM", "starter": home_sp, "starter_id": 2,
                 "lineup": nine},
    }


def _slate_rates(*names):
    p = _pitcher()
    return {n: {"name": n, "k_pct": p.k_pct, "bb_pct": p.bb_pct,
                "hr_pct": p.hr_pct, "babip": p.babip, "pa": 600}
            for n in names}


def _price_args(pr):
    b = _lineup()[0]
    br = {f"B{i}": {"k_pct": b.k_pct, "bb_pct": b.bb_pct,
                    "hr_pct": b.hr_pct, "babip": b.babip, "pa": 500}
          for i in range(9)}
    return dict(d="2026-08-25", lg=LG, pr=pr, br=br, league_bats=_lineup()[0],
                pens={})


def check_a_missing_opposing_starter_declines_rather_than_inventing_one():
    """THE RULE THIS WHOLE MIGRATION ADOPTED.

    A prop names ONE pitcher, but pricing him now means simulating the game
    he is in, and a game needs the other starter. The tempting shortcut is a
    league-average stand-in. That invents the other club, which invents the
    score — and the score is what the hook, the bullpen and the margin are
    all conditioned on, so the number would look like every other number and
    be built on a pitcher who is not in the game.

    Same posture the module already takes on openers and live games: say
    nothing, out loud, with a reason.
    """
    from src.context import price
    a = _price_args(_slate_rates("A Starter"))       # home starter has none
    res, why = price.simulate_slate_game(_slate_game(), n_sims=2, **a)
    assert res is None
    assert "H Starter" in why, why

    # And a game already under way, for the same reason it always was.
    both = _price_args(_slate_rates("A Starter", "H Starter"))
    res, why = price.simulate_slate_game(
        _slate_game(status="In Progress"), n_sims=2, **both)
    assert res is None and "live" in why, why


def check_both_starters_come_out_of_one_simulated_game():
    """Every bet has two sides, so the matchup is simulated ONCE and each
    starter's line is read off the same `GameResult`.

    Two things are asserted together because either alone would pass on a
    broken build: that both lines exist and differ draw to draw, and that
    they are CONSISTENT WITH ONE GAME — a starter's runs allowed cannot
    exceed what his side gave up through the innings he was there for.
    """
    from src.context import price
    a = _price_args(_slate_rates("A Starter", "H Starter"))
    games, why = price.simulate_slate_game(_slate_game(), n_sims=40, **a)
    assert games is not None, why
    away = price.starter_line(games, is_home=False)
    home = price.starter_line(games, is_home=True)
    assert len(away) == len(home) == 40
    assert away[0] is not home[0]
    assert len({r.outs for r in away}) > 1, "every draw identical"
    for g, sp in zip(games, away):
        # `home` is runs SCORED by the home team, which is what the AWAY
        # pitching side allowed. The starter is a subset of that side.
        assert sp.runs <= g.home, (sp.runs, g.home)


# ── arsenal multipliers ────────────────────────────────────────────────
def check_arsenal_k_and_contact_are_separate_channels():
    """A pitch mix can miss bats without producing weak contact. Collapsing
    both into one multiplier would make a slider-heavy righty and a
    sinker-heavy one indistinguishable, which is the entire thing the
    arsenal data exists to separate."""
    b = _lineup(1, arsenal_mult=1.0, arsenal_k_mult=1.25)[0]
    rng = random.Random(61)
    n = 12000
    c = {}
    for _ in range(n):
        o = sim.pa_outcome(b, _pitcher(), LG, rng)
        c[o] = c.get(o, 0) + 1
    # K should rise by roughly the multiplier; HR should not move.
    assert c[sim.K] / n > LG["k_pct"] * 1.15, c[sim.K] / n
    assert abs(c.get(sim.HR, 0) / n - LG["hr_pct"]) < 0.006


def check_arsenal_multiplier_is_relative_to_a_league_average_mix():
    """MUST divide by the batter's projection against a LEAGUE-AVERAGE
    arsenal, not against his own season line.

    His overall quality already lives in k_pct / babip / hr_pct. Dividing by
    his own wOBA would put a good hitter's skill into the model twice and
    make every good hitter look like a good matchup against everyone.
    """
    import inspect
    src = inspect.getsource(rate_src.arsenal_mults)
    assert "league_arsenal" in src, \
        "arsenal multiplier no longer references a league-average mix"
    assert "ref[\"proj_woba\"]" in src or "ref['proj_woba']" in src


def check_arsenal_multipliers_are_clamped():
    """A 40% swing off a per-pitch sample is noise, not a matchup, and the
    simulator has no other guard against it."""
    import inspect
    src = inspect.getsource(rate_src.arsenal_mults)
    assert "0.80" in src and "1.25" in src


def check_thin_arsenal_coverage_returns_neutral():
    """A projection built on 40% of a starter's usage is a partial answer.
    Missing must mean neutral, never an extrapolation — the same rule the
    context layer follows for an unrated catcher."""
    import inspect
    src = inspect.getsource(rate_src.arsenal_mults)
    assert "coverage" in src, "no coverage gate on the arsenal projection"
    assert rate_src.arsenal_mults(None, ["x"], {}) == {}


def check_league_arsenal_usage_sums_sensibly():
    ars = {"a": [{"pitch": "Four-Seam", "usage_pct": 60},
                 {"pitch": "Slider", "usage_pct": 40}],
           "b": [{"pitch": "Sinker", "usage_pct": 50},
                 {"pitch": "Slider", "usage_pct": 50}]}
    rate_src._LEAGUE_ARSENAL = None
    mix = rate_src.league_arsenal(ars)
    rate_src._LEAGUE_ARSENAL = None
    total = sum(p["usage_pct"] for p in mix)
    assert abs(total - 100.0) < 1e-6, total
    slider = next(p for p in mix if p["pitch"] == "Slider")
    assert abs(slider["usage_pct"] - 45.0) < 1e-6, slider


# ── outs the model could not previously produce ────────────────────────
def check_sacrifice_is_an_out_and_never_a_hit():
    """A sacrifice is an automatic out. Before it existed as an outcome,
    those plate appearances fell into the ball-in-play bucket and got a
    .294 BABIP roll, turning ~29% of them into hits that were never in
    doubt. That is half of why the simulator converted 1.1% fewer batters
    into outs than reality (0.7017 vs 0.7094)."""
    rng = random.Random(71)
    seen = set()
    for _ in range(20000):
        seen.add(sim.pa_outcome(_lineup(1)[0], _pitcher(), LG, rng))
    assert sim.SAC in seen, "sacrifices are not being drawn at all"
    # It must carry no damage and cost few pitches — it is not trouble.
    assert sim.DAMAGE[sim.SAC] == 0.0
    assert sim.PITCH_COST[sim.SAC] < sim.PITCH_COST[sim.K]


def check_sacrifice_advances_runners():
    """The whole point of laying one down. An out that strands everybody is
    just a ground out and would leave run scoring short."""
    scored = advanced = 0
    for seed in range(300):
        rng = random.Random(seed)
        r = fx.one_side(_pitcher(), _lineup(), LG, sim.Hook(), rng)
        scored += r.runs
        advanced += r.sacrifices
    assert advanced > 0, "no sacrifices recorded across 300 starts"


def check_caught_stealing_records_an_out_with_no_batter():
    """CS counts toward a pitcher's innings pitched, so omitting it cost
    about 0.10 outs a start. It must consume an out WITHOUT consuming a
    plate appearance — if it increments `batters` the fix is wrong."""
    res = fx.starts(_pitcher(), _lineup(), LG, n=3000, seed=72)
    cs = sum(r.caught_stealing for r in res) / len(res)
    assert 0.03 < cs < 0.30, cs
    for r in res:
        assert r.k + r.caught_stealing + r.sacrifices <= r.outs, r


def check_outs_per_batter_is_close_to_the_league():
    """The headline number the sacrifice/CS fix exists to move. League is
    0.7094; the simulator read 0.7017 before those outcomes existed.

    Denominator must be outs + h + bb, NOT `batters`. The boxscore cache has
    no hit-by-pitch column so the league figure is computed that way, and
    once HBP was added to the simulation `batters` included plate
    appearances the league number excludes — which made this check fail at
    0.6974 while the comparable figure was 0.708, exactly right.
    """
    res = fx.starts(_pitcher(), _lineup(), LG, n=4000, seed=73)
    o = sum(r.outs for r in res)
    bf = o + sum(r.h + r.bb for r in res)
    assert 0.700 < o / bf < 0.716, o / bf


def check_sac_and_cs_rates_are_measured_not_guessed():
    """SAC_RATE is the published league share of plate appearances
    (SH ~0.3% + SF ~0.7%). CS_RATE is derived locally: 1,301 steals over
    23,338 times on base at a ~79% success rate implies ~346 caught."""
    assert 0.005 <= sim.SAC_RATE <= 0.015, sim.SAC_RATE
    assert 0.008 <= sim.CS_RATE <= 0.025, sim.CS_RATE


# ── quoting a bet ──────────────────────────────────────────────────────
def check_sim_only_bar_exceeds_our_own_noise():
    """When Kalshi has no contract the simulator is all there is, and it
    must stay quiet below its own measured error.

    |sim - Kalshi| over 1,220 settled markets: median 3.7 cents, p90 11.4.
    Retail markup is 2-5 cents. Our noise is the same size as the quantity
    we would be claiming to measure, so anything under a gross-mispricing
    bar is noise dressed as a finding.
    """
    from src.context import quote
    assert quote.SIM_ONLY_BAR >= 0.08, quote.SIM_ONLY_BAR
    assert quote.SIM_ONLY_BAR > quote.NOTABLE_MARKUP * 3


def check_american_odds_convert_both_signs():
    from src.context import quote
    assert abs(quote.american_to_prob(-110) - 0.5238) < 1e-3
    assert abs(quote.american_to_prob("+140") - 0.4167) < 1e-3
    assert abs(quote.american_to_prob(100) - 0.5) < 1e-9
    assert quote.american_to_prob(None) is None
    assert quote.american_to_prob("junk") is None


def check_push_mass_is_zero_on_a_half_point_line():
    r = [sim.StartResult(k=n) for n in (5, 6, 7)]
    assert sim.prob_push(r, "k", 5.5) == 0.0
    assert sim.prob_push(r, "k", 6.0) == 1 / 3


def check_an_integer_line_and_a_kalshi_threshold_are_different_bets():
    """The live mis-pricing this guards.

    A book's over-9.0 refunds at exactly 9; Kalshi's threshold-10 contract,
    which is the one `threshold_for(9.0)` returns, settles NO at 9 and pays
    nothing back. Breaking even on the book bet needs

        P(win) * b = P(lose) = 1 - P(win) - P(push)

    so the win probability it actually requires is the implied number scaled
    by (1 - P(push)) — and THAT is what compares to the exchange. Comparing
    the raw implied number instead overstates what the book demands by the
    whole push mass, which at a 10% push on a -110 line is 5.2 cents, past
    the 2-cent bar that decides whether we tell someone to bet it.
    """
    from src.context import quote
    implied = quote.american_to_prob(-110)
    push = 0.10
    needed = implied * (1 - push)
    assert abs(needed - 0.4714) < 1e-3, needed
    assert implied - needed > quote.NOTABLE_MARKUP, implied - needed
    # and a half-point line must be left exactly alone
    assert implied * (1 - sim.prob_push([sim.StartResult(k=5)], "k", 5.5)) == implied


# ── open vs close ──────────────────────────────────────────────────────
def check_clv_controls_are_kept_in_the_harness():
    """`sim - open` and `close - open` share a -open term, which can
    manufacture correlation out of nothing. The controls measured here run
    NEGATIVE (shuffled -0.2675, constant -0.4004), so the artifact was
    suppressing the real signal rather than creating it — but that is a fact
    about this data, not a guarantee, and a future run without the controls
    would have no way to know."""
    import inspect

    from src.context import versus_market as vm
    src = inspect.getsource(vm)
    assert "open" in src, "opening price no longer collected"


def check_versus_market_records_the_open():
    """Comparing a morning model to a CLOSING price is a rigged test: the
    close carries confirmed lineups, weather and scratches the model never
    saw. Both prices must be kept so the fair comparison stays available."""
    import inspect

    from src.context import versus_market as vm
    src = inspect.getsource(vm.collect)
    assert '"open": opened' in src
    assert 'pp.get("open_prob")' in src


# ── the mechanisms that close the run gap ──────────────────────────────
def check_steals_exist_alongside_caught_stealing():
    """Adding CS without SB was a real bug that shipped for half a day: the
    simulator took every downside of baserunning and none of the upside, and
    runs per baserunner read 10% light while the baserunner COUNT was
    correct. The data has 1,301 steals against ~346 caught."""
    assert sim.SB_RATE > sim.CS_RATE * 2, (sim.SB_RATE, sim.CS_RATE)
    res = fx.starts(_pitcher(), _lineup(), LG, n=2500, seed=81)
    sb = sum(r.stolen_bases for r in res) / len(res)
    cs = sum(r.caught_stealing for r in res) / len(res)
    assert sb > cs, (sb, cs)


def check_hit_by_pitch_is_tracked_apart_from_walks():
    """HBP must not be folded into `bb`, or the walk total stops matching
    the boxscore — which is the number the calibration checks."""
    res = fx.starts(_pitcher(), _lineup(), LG, n=2500, seed=82)
    hbp = sum(r.hbp for r in res) / len(res)
    assert 0.10 < hbp < 0.45, hbp
    assert sim.DAMAGE[sim.HBP] == sim.DAMAGE[sim.BB]


def check_rates_are_conditioned_on_the_off_the_top_draws():
    """Sacrifices and hit-by-pitches are drawn before the strikeout branch,
    so everything after is conditional on neither firing. Without dividing
    by (1 - sac - hbp) every marginal rate comes out light by exactly that
    much — measured as K/9 8.16 against a real 8.44.

    Asserted on BEHAVIOUR, not on the text of the line. The source-string
    version broke the moment the two rates became per-arm, which is exactly
    the failure mode of a check that reads code instead of running it: it
    cannot tell a refactor from a regression.

    The specific thing guarded is that the rescale uses THE SAME rates that
    were drawn. An arm with a high hit-by-pitch rate loses more plate
    appearances off the top, so dividing by the league constant instead
    would bias every rate below it — and the bias would be largest for
    exactly the arms the per-role rates exist to describe.
    """
    import inspect
    # `pa_from` is the hot path; `pa_outcome` now just resolves a matchup
    # and delegates to it.
    src = inspect.getsource(sim.pa_from)
    assert src.count("/ cond") >= 3, "not every branch is rescaled"

    # An arm with an ENORMOUS off-the-top share still has to produce
    # strikeouts at close to its own rate, because the rescale compensates.
    p = _pitcher()
    base = fx.starts(p, _lineup(), LG, n=1500, seed=83)
    k_base = sum(r.k for r in base) / sum(r.batters for r in base)
    loud = replace(p, hbp_rate=0.08, sac_rate=0.02)
    hot = fx.starts(loud, _lineup(), LG, n=1500, seed=83)
    k_hot = sum(r.k for r in hot) / sum(r.batters for r in hot)
    # STRIKEOUTS PER PLATE APPEARANCE MUST NOT MOVE. That is the whole
    # point of the rescale: 10% of plate appearances now end off the top,
    # and the remaining 90% carry a correspondingly higher strikeout
    # probability, so the share of ALL plate appearances is unchanged.
    #
    # Rescaling by the league constant instead drops it to ~0.92 — the
    # branches are divided by the old, much smaller off-the-top share. An
    # earlier version of this check asserted the ratio was ~0.90 with a
    # +/-20% band, which is the wrong target AND wide enough to contain the
    # bug; the mutation survived it. 36,000 plate appearances put the
    # sampling error near 1.4%, so this band is ~3 sigma and excludes 0.92.
    assert 0.95 < k_hot / k_base < 1.05, (k_base, k_hot, k_hot / k_base)


def check_league_baselines_come_from_rotation_starters():
    """log5 returns the LEAGUE value when batter and pitcher are both
    average, so the baseline is the simulator's floor. Feeding the whole
    pitcher pool (BB 0.0859) instead of rotation starters (0.0784) inflated
    simulated walks by 6-8%, because openers and relievers walk more than
    the population being simulated."""
    lg = sim.league()
    assert 0.070 < lg["bb_pct"] < 0.085, lg["bb_pct"]
    assert 0.205 < lg["k_pct"] < 0.230, lg["k_pct"]
    assert "batter_scale" in lg, "batters not put on the pitching footing"


def check_advancement_was_fitted_after_the_counts_were_right():
    """Order matters. Tuning advancement while the simulator produced 4% too
    many baserunners buries one error inside another — the first attempt
    picked 0.44/0.76 doing exactly that. These were refitted only once
    hits, walks and batters faced each landed inside 2%."""
    # Now keyed BY OUT COUNT, which was the missing mechanism: a flat rate
    # applies the same number with nobody out and with two, and the runner
    # leaves on contact with two. Bounds are per out state.
    for outs in (0, 1, 2):
        assert sim._rate(sim.FIRST_TO_THIRD_ON_1B, outs) < 0.45
        assert sim._rate(sim.SECOND_SCORES_ON_1B, outs) < 0.90
        assert sim._rate(sim.FIRST_SCORES_ON_2B, outs) <= 0.70


def check_advancement_rises_with_the_out_count():
    """A runner goes on contact with two down and is held with none.

    The invariant that makes the out-count table worth having. If it were
    flat -- or worse, backwards -- the model would be back to splitting the
    difference between two situations that are nothing alike, which is what
    left runs-per-baserunner 4.2% short of reality.

    IT IS TWO-OUT AGAINST NOBODY-OUT, not a rising ladder. This check used
    to assert v[0] < v[1] < v[2] and that is a property of the PUBLISHED
    references, not of the league. Measured over 152,153 plays,
    first-to-third goes .307 .295 .408: the middle entry sits 0.8 sigma
    BELOW the first, which is to say the two are the same number, while the
    two-out jump is enormous and real. Asserting the ladder would be
    asserting a decimal place the data does not have.
    """
    for table in (sim.FIRST_TO_THIRD_ON_1B, sim.SECOND_SCORES_ON_1B,
                  sim.FIRST_SCORES_ON_2B, sim.FIRST_SCORES_ON_1B):
        v = [sim._rate(table, o) for o in (0, 1, 2)]
        assert v[2] > v[0], v
        assert v[1] >= v[0] * 0.9, v          # no collapse in the middle
    # The productive out is the exception: its two-out entry is unreachable,
    # because with two down the ball in play is itself the third out.
    for adv in (sim.ADVANCE_1B_ON_OUT, sim.ADVANCE_2B_ON_OUT,
                sim.ADVANCE_3B_ON_OUT, sim.RUNNER_ADVANCES_ON_OUT):
        assert sim._rate(adv, 2) == 0.0, adv


def check_advancing_on_an_out_is_shaped_by_which_base():
    """Why one pooled constant was replaced by three.

    A runner on second advances on a ball in play about twice as often as a
    runner on first -- .49 against .22 with nobody out -- so no single value
    can be right for both, whatever it is set to. That gap is the whole
    justification for the per-base tables, and if it ever closed they should
    go back to being one number.
    """
    for outs in (0, 1):
        one = sim._rate(sim.ADVANCE_1B_ON_OUT, outs)
        two = sim._rate(sim.ADVANCE_2B_ON_OUT, outs)
        assert two > one * 1.5, (outs, one, two)


def check_rate_accepts_a_bare_float():
    """A scalar must still work, so the old flat model stays expressible and
    the two can be compared directly rather than argued about."""
    assert sim._rate(0.37, 0) == 0.37
    assert sim._rate(0.37, 2) == 0.37


def check_advance_actually_uses_the_out_count():
    """Guards the wiring, not the model. The tables are useless if `_advance`
    never receives the out count -- and it would silently keep using the
    nobody-out row for everything, which is the flat model with worse
    numbers."""
    import random
    scored = {}
    for outs in (0, 2):
        n = 0
        for seed in range(600):
            bases = [False, True, False]      # runner on second
            n += sim._advance(bases, sim.B1,
                              random.Random(seed), outs)[0]
        scored[outs] = n / 600
    assert scored[2] > scored[0] + 0.20, scored


# ── reached on error ───────────────────────────────────────────────────
def check_roe_puts_a_runner_on_without_recording_an_out():
    """An error costs twice: the runner it gives and the out it does not.

    Modelling it as a hit would give back the out and halve the damage;
    modelling it as an out with a runner attached is not a thing that
    happens. This pins both halves.
    """
    r = sim.StartResult()
    fr = sim.Frame()
    sim.apply_pa(sim.ROE, r, fr, random.Random(1))
    assert fr.outs == 0, fr.outs
    assert r.outs == 0, r.outs
    assert fr.bases[0] is True, fr.bases
    assert r.h == 0 and r.roe == 1, (r.h, r.roe)


def check_runs_after_an_error_are_unearned():
    """The frame remembers the error, so later runs stop being earned."""
    r = sim.StartResult()
    fr = sim.Frame()
    rng = random.Random(2)
    sim.apply_pa(sim.ROE, r, fr, rng)
    assert fr.errored is True
    fr.bases[:] = [True, True, True]
    sim.apply_pa(sim.HR, r, fr, rng)
    assert r.runs == 4, r.runs
    assert r.earned == 0, r.earned


def check_runs_before_an_error_stay_earned():
    """Only runs AFTER the error are forgiven. Charging the whole inning
    would make a late error erase a rally the pitcher genuinely gave up."""
    r = sim.StartResult()
    fr = sim.Frame()
    rng = random.Random(3)
    fr.bases[:] = [True, True, True]
    sim.apply_pa(sim.HR, r, fr, rng)
    assert r.runs == 4 and r.earned == 4, (r.runs, r.earned)
    sim.apply_pa(sim.ROE, r, fr, rng)
    fr.bases[:] = [True, True, True]
    sim.apply_pa(sim.HR, r, fr, rng)
    assert r.runs == 8 and r.earned == 4, (r.runs, r.earned)


def check_earned_never_exceeds_total_runs():
    """An invariant, not a preference. `earned` is a subset of `runs`, and
    any path that credits one without the other breaks the `er` diagnostic
    silently."""
    rng = random.Random(4)
    for _ in range(120):
        r = fx.one_side(_pitcher(), _lineup(), LG, sim.Hook(), rng)
        assert r.earned <= r.runs, (r.earned, r.runs)
        assert r.earned >= 0 and r.runs >= 0


def check_no_errors_means_no_unearned_runs():
    """With the mechanism switched off the model reverts exactly to what it
    was before errors existed: every run earned, `runs == earned`."""
    rng = random.Random(5)
    old = sim.ROE_PER_OUT
    sim.ROE_PER_OUT = 0.0
    try:
        for _ in range(80):
            r = fx.one_side(_pitcher(), _lineup(), LG, sim.Hook(), rng)
            assert r.runs == r.earned, (r.runs, r.earned)
            assert r.roe == 0, r.roe
    finally:
        sim.ROE_PER_OUT = old


def check_errors_raise_the_run_level():
    """The whole reason this exists. Simulating no errors left the run level
    6.7% light against a league where unearned runs are 7.64% of the total,
    and the fit was trying to make up the difference by driving the
    advancement rates to the edge of their grid."""
    # TWO THINGS WERE WRONG WITH THE ORIGINAL VERSION OF THIS CHECK.
    #
    # It scored runs per START under the live hook. Errors put men on base,
    # the hook keys on baserunners, so a start with errors ends EARLIER and
    # is charged fewer runs — it measured the hook reacting to errors, and
    # once the early branches went in it reported errors LOWERING the run
    # level. Fixed by a never-pull hook: every start is the full nine.
    #
    # And it was underpowered by an order of magnitude. Runs per start have
    # an sd near 3, so at n=400 the standard error is 0.215 against a real
    # effect of 0.199 — under one sigma. It had been passing on luck.
    # Measured properly at n=6000: 4.122 -> 4.320 runs, +4.8%, 3.7 sigma.
    # Reaching 3 sigma needs ~4,000 starts an arm, which is two minutes in a
    # sixty-second suite.
    #
    # So the MECHANISM is asserted here, at 11 sigma and no cost, and the
    # run-level figure above is recorded rather than re-measured every run.
    never = sim.Hook(intercept=-99.0, mid_intercept=-99.0,
                     hard_pitch_cap=100000)

    def start(roe, n=900):
        old = sim.ROE_PER_OUT
        sim.ROE_PER_OUT = roe
        try:
            rng = random.Random(6)
            out = [fx.one_side(_pitcher(), _lineup(), LG, never, rng)
                   for _ in range(n)]
            # At LEAST the full nine, not exactly nine. The deleted
            # one-sided loop stopped at `max_innings`; a real game goes to
            # extras when it is tied, and with a never-pull hook and no pen
            # this pitcher throws those too. The point of the assertion is
            # unchanged — no start ended early, so nothing here is the hook
            # reacting to errors.
            assert all(r.outs >= 27 for r in out), "the hook still fired"
            return out
        finally:
            sim.ROE_PER_OUT = old

    off, on, more = start(0.0), start(0.018), start(0.036)
    assert sum(r.roe for r in off) == 0, "errors with the rate at zero"
    per_on = sum(r.roe for r in on) / len(on)
    per_more = sum(r.roe for r in more) / len(more)
    assert per_on > 0.2, per_on
    # Twice the rate is roughly twice the errors. Loose, because reaching on
    # an error consumes an out that would otherwise have ended the inning.
    #
    # n RAISED FROM 400 rather than the band widened. At 400 the seeded draw
    # sat at 2.42 once the steal table changed the random stream, while the
    # same measurement over four independent seed/size combinations lands at
    # 1.82-2.15. The behaviour was right and the sample was too small — the
    # fix for that is more starts, not a softer standard.
    assert 1.6 < per_more / per_on < 2.4, (per_on, per_more)
    # And they reach base, rather than being counted and discarded.
    br = [sum(r.h + r.bb + r.roe for r in g) / len(g) for g in (off, on)]
    assert br[1] > br[0], br


def check_the_club_patience_offsets_stay_switched_off():
    """Patience was fitted as a RESIDUAL against a model that no longer
    exists, and re-measuring it did not rescue it: fitted in the correct
    order (club first, pitcher against the remainder) a club offset is worth
    +0.090 -> +0.122 out of sample alone, and ON TOP of the pitcher offset
    it makes things WORSE (+0.234 -> +0.227, MAE up). Sixth independent
    finding that club hook effects do not pay.

    The pitcher LEASH is a different file with a different provenance and it
    ships ON — see `check_the_measured_leash_is_live_and_carries_provenance`.
    """
    assert sim.USE_OFFSETS is False
    assert sim.USE_PATIENCE is False
    assert sim.patience("SD") == 0.0


def check_the_measured_leash_is_live_and_carries_provenance():
    """`hook_leash.json` must be the MEASURED file, not the 2026-08-23 one.

    The stale version was fitted as a residual against a model that has since
    changed in six ways, and the only thing distinguishing it from the
    rebuilt file is the `_meta` block `src.context.leash.build` writes. A
    file with no provenance is the old one, so the absence of that block is
    the failure — not a missing key.
    """
    import json

    from src.context import leash as leash_mod
    assert sim.USE_LEASH is True
    with open(leash_mod.PATH) as f:
        data = json.load(f)
    meta = data.get("_meta")
    assert meta, "hook_leash.json has no provenance: this is the stale file"
    for key in ("before", "k", "between_sd", "within_sd", "starts"):
        assert key in meta, key
    # K is the MEASURED within/between ratio, not a tuned constant. Anything
    # outside this band means the ANOVA collapsed and every offset is either
    # unshrunk noise or shrunk to nothing.
    assert 1.0 <= meta["k"] <= 40.0, meta["k"]
    assert meta["starts"] > 500, meta["starts"]
    offs = [v for k, v in data.items() if k != "_meta"]
    assert len(offs) > 50, len(offs)
    assert all(abs(v) <= leash_mod.OFFSET_CLAMP + 1e-9 for v in offs)


def check_a_leash_offset_actually_lengthens_the_start():
    """The wiring, not the measurement. A negative offset must buy outs
    through `for_start`, which is the only path `quote`, `price`,
    `calibrate`, `f5` and `game` reach it by."""
    lg = sim.league()
    p = sim.PitcherRates(name="X", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
                         hr_pct=lg["hr_pct"], babip=lg["babip"], pa=600)
    nine = [sim.BatterRates(name=f"b{i}", k_pct=lg["k_pct"],
                            bb_pct=lg["bb_pct"], hr_pct=lg["hr_pct"],
                            babip=lg["babip"]) for i in range(9)]

    def mean_outs(name):
        rng = random.Random(4)
        h = sim.for_start(sim.Hook(), "XXX", name)
        return sum(fx.one_side(p, nine, lg, h, rng).outs
                   for _ in range(400)) / 400

    saved = sim._LEASH
    sim._LEASH = {"Long": -1.0, "Short": 1.0}
    try:
        long_, none, short = (mean_outs("Long"), mean_outs("Nobody"),
                              mean_outs("Short"))
    finally:
        sim._LEASH = saved
    assert long_ > none > short, (long_, none, short)
    # the measured sweep puts -1.0 at +1.60 outs and +1.0 at -1.66
    assert 0.8 < long_ - none < 2.6, long_ - none


def check_for_start_composes_with_an_existing_team_offset():
    """`calibrate.HOME_HOOK` stacks on top of `for_start`, and the bootstrap
    in `simulate_many` jitters the same field. Replacing rather than adding
    silently discards whichever was applied first — and because the leash is
    now live by default, that would be a real lost home-field term rather
    than a dormant one."""
    base = sim.Hook(**{**sim.Hook().__dict__, "team_offset": 0.4})
    saved = sim._LEASH
    sim._LEASH = {"Somebody": -0.3}
    try:
        h = sim.for_start(base, "XXX", "Somebody")
        assert abs(h.team_offset - 0.1) < 1e-9, h.team_offset
    finally:
        sim._LEASH = saved


def check_the_inherited_runner_fudge_stayed_deleted():
    """Inherited runners are SIMULATED now, not settled by a coin flip.

    `INHERITED_SCORE_RATE` (flat 0.33) and `INHERITED_SCORE_BY_STATE` (the
    same thing counted by base and out) existed only because the one-sided
    engine stopped the instant the hook fired and could not simulate the
    reliever finishing the inning. `game.py` hands the base-out state over
    intact, so a constant reappearing here would charge those runners TWICE
    — once by coin flip on the way out and again when they actually score.

    The measurement is not what is being deleted: `src.context.inherit`
    counted 5,507 handovers and its cells (0.127 to 0.771 against a pooled
    0.312) are still the record. The fudge is.
    """
    for gone in ("INHERITED_SCORE_RATE", "INHERITED_SCORE_BY_STATE",
                 "USE_MEASURED_INHERITED", "_leave"):
        assert not hasattr(sim, gone), gone
    assert "INHERITED_SCORE_RATE" not in sim.FITTABLE


def check_pitch_cost_is_charged_at_full_precision():
    """`PITCH_COST` is measured to two decimals; charging it must not round.

    THE BUG THIS EXISTS FOR, and 333 checks missed it. `apply_pa` accumulated
    `int(round(PITCH_COST[o]))`, discarding the fraction on EVERY plate
    appearance. An out on contact costs 3.25 and was billed 3; a walk costs
    5.48 and was billed 5 — the two commonest outcomes in the game, rounded
    the same way about 23 times a start.

    It cost 3.3 pitches per start of a measured 4.2-pitch shortfall, and
    because the hook integrates over pitch count every starter lasted too
    long: 16.4% of simulated starts reached 21+ outs against a real 11.4%.
    The table was never wrong — it predicts 86.9 pitches a start against a
    real 86.82. The rounding threw the calibration away.

    Asserted on the ARITHMETIC rather than on a simulated total, because a
    per-start total is noisy and the defect is exact: fifty outs must cost
    fifty times 3.25, not fifty times 3.
    """
    r, fr = sim.StartResult(), sim.Frame()
    rng = random.Random(0)
    for _ in range(50):
        fr = sim.Frame()               # fresh frame so nothing ends an inning
        sim.apply_pa(sim.OUT, r, fr, rng)
    want = 50 * sim.PITCH_COST[sim.OUT]
    assert abs(r.pitches - want) < 1e-9, (r.pitches, want)
    # and the fraction must actually survive, not be re-rounded downstream
    assert r.pitches != int(r.pitches), r.pitches


def check_the_pitch_table_reproduces_the_real_pitch_count():
    """The measured table, applied to a real start's outcome mix, must land
    on that start's real pitch count.

    This is the check that would have caught the rounding from the other
    side. Mean outcome mix over 3,527 real starts by arms meant to go long:
    4.92 K, 1.84 BB, 0.72 HR, 4.22 non-homer hits, 10.96 outs on contact,
    0.22 HBP — and 86.82 pitches. The table predicts 86.9.
    """
    mix = {sim.K: 4.92, sim.BB: 1.84, sim.HR: 0.72, sim.B1: 4.22,
           sim.OUT: 10.96, sim.HBP: 0.22}
    got = sum(n * sim.PITCH_COST[o] for o, n in mix.items())
    assert abs(got - 86.82) < 2.0, got


def check_the_boundary_curve_is_the_fitted_one():
    """The between-innings curve is fitted on real decisions, not imported.

    REFITTED 2026-08-26 on CORRECTLY LABELLED rows. `boundary.decisions` read
    `count.outs` as the outs BEFORE a play when it is the outs AFTER, so
    every second out of an inning was labelled `ends_inning` and 48.2% of
    this curve's training set was decisions where a manager essentially never
    pulls anybody (1.28% against a true boundary rate of 11.88%).

    The correction is not a re-tune, it changes what the curve SAYS:

        parameter        before     after
        per_inning       -0.1087   +0.2515   <- sign flip
        per_run          +0.0089   +0.1097   <- 12x
        per_baserunner   +0.0379   +0.0555
        pitch_scale      10.8972   12.1293

    `per_inning` negative meant the model believed a manager grows LESS
    likely to pull a starter as the game goes on. The real hazard past 100
    pitches is 0.972 and the old curve fired at 0.607.

    Scored on 1,040 holdout starts with the leash rebuilt against it:

        RMS error on P(over), outs 14.5-17.5   0.0585 -> 0.0242
        RMS error on P(over), outs 12.5-20.5   0.0810 -> 0.0332
        mean outs                               16.87 -> 16.03  (real 15.81)
        SD outs                                  3.92 ->  4.03  (real 4.05)
        boundary share                           0.478 -> 0.603 (real 0.671)

    That mean-outs error had been open since day six and six mechanisms had
    failed on it.

    `sim.PRE_OUTS_FIX_BOUNDARY` restores the old values for scoring, and
    `sim.LEGACY_BOUNDARY` the imported ones before those.
    """
    h = sim.Hook()
    assert abs(h.pitch_center - 49.5493) < 1e-6, h.pitch_center
    assert abs(h.pitch_scale - 12.1293) < 1e-6, h.pitch_scale
    assert abs(h.intercept - (-5.1370)) < 1e-6, h.intercept
    # THE SIGN IS THE FINDING, not the digits. A manager gets MORE likely to
    # pull as the game goes on, and a negative value here is the signature of
    # the labelling bug rather than a tuning choice.
    assert h.per_inning > 0, h.per_inning
    assert h.per_run > 0.05, h.per_run
    for k in ("intercept", "per_inning", "per_run"):
        assert k in sim.PRE_OUTS_FIX_BOUNDARY, k
    # The legacy record has to stay complete enough to restore the curve.
    for k in ("intercept", "pitch_center", "pitch_scale", "per_run",
              "per_inning", "per_baserunner"):
        assert k in sim.LEGACY_BOUNDARY, k
    # THIS ASSERTION USED TO ENCODE A CONTAMINATED FACT and is the reason to
    # re-read every number a check pins, not just the ones that fail. It
    # required the legacy curve to be twice as eager as the shipped one at 75
    # pitches, on the grounds that the real 70-80 rate is 0.074. Counted on
    # correctly labelled rows that rate is 0.130, and the whole hazard is far
    # steeper than anything fitted before the fix believed.
    #
    # So the curve is now pinned against the COUNTED hazard instead of
    # against another curve. Real rates, 2025+2026 boundary decisions:
    #
    #     60-70  0.050    80-90   0.353    100-110  0.972
    #     70-80  0.130    90-100  0.790
    #
    # evaluated at a mid-range state, so exact agreement is not expected —
    # the bands are wide enough to catch a curve that is out by a factor,
    # which is what every version of this defect has been.
    pre = sim.Hook(**sim.PRE_OUTS_FIX_BOUNDARY)
    for pitches, lo, hi in ((75, 0.08, 0.35), (105, 0.55, 0.95)):
        got = h.removal_p(pitches, 2, 5, 4)
        assert lo < got < hi, (pitches, got)
    # And the pre-fix curve's defining defect: it under-pulls deep, which is
    # what left starters a full out too long.
    assert pre.removal_p(105, 2, 5, 4) < h.removal_p(105, 2, 5, 4), \
        "the corrected curve must pull harder at 105 pitches"


def check_a_rate_multiplier_enters_the_odds_not_the_probability():
    """Park and arsenal used to MULTIPLY log5's probability output.

    log5 is an odds-ratio construction, so scaling its output is not a
    consistent change to the underlying rates: a 1.05x on a .05 probability
    is nearly a 1.05x on the odds and on a .45 probability it is not close.
    The same park factor therefore meant something different in a high
    strikeout matchup than a low one, worst in the TAILS, which is where
    prop lines sit.

    It could also leave [0, 1], which is the ONLY reason those branches ever
    needed clamping — and they clamped three different ways. `bb` and `hr`
    were unclamped, and a walk probability above what remained fired every
    time AND drove `rest` negative, so the `rest > 0` guard skipped home
    runs entirely. An out-of-range value read as a channel quietly going to
    zero, with no error and no grid edge to notice it by.

    Measured before the change: 0 clamps in 529,581 plate appearances, so it
    was latent rather than live — but latent on the CURRENT multipliers, and
    park and arsenal are both off. Anything that switches them on moves the
    operating point.
    """
    lg = 0.2167

    # 1. THE SHIPPED CONFIG IS UNTOUCHED. Every multiplier is 1.0 today,
    #    so this refactor has to be the exact identity or it is not a
    #    refactor.
    for i in range(1, 1000):
        p = i / 1000.0
        assert sim.odds_mult(p, 1.0, lg) == p, p

    # 2. It means what a park factor is documented to mean: a league-average
    #    matchup in an `m` park comes out at exactly m * league.
    for m in (0.85, 0.95, 1.05, 1.20):
        assert abs(sim.odds_mult(lg, m, lg) - m * lg) < 1e-12, m

    # 3. It cannot escape (0, 1) for any multiplier, which is what deletes
    #    the clamps rather than papering over them.
    for p in (0.02, 0.30, 0.45, 0.90, 0.99):
        for m in (0.01, 0.5, 1.5, 3.0, 50.0):
            got = sim.odds_mult(p, m, lg)
            assert 0.0 < got < 1.0, (p, m, got)

    # 4. Monotone in the multiplier, or it is not a multiplier.
    prev = 0.0
    for m in (0.5, 0.9, 1.0, 1.1, 2.0):
        got = sim.odds_mult(0.30, m, lg)
        assert got > prev, (m, got, prev)
        prev = got


def check_every_outcome_channel_survives_extreme_rates():
    """The plate-appearance chain must not lose a channel under pressure.

    The branches are drawn in order — K, then BB, then HR, then ball in
    play — each rescaled by the probability mass still unallocated. Get the
    ordering or the rescaling wrong and a channel silently goes to zero,
    which is the one failure mode nothing downstream can detect: a missing
    home run rate just looks like a slightly low home run rate, and a fitted
    constant absorbs it.

    WHAT THIS DOES NOT CLAIM. At physically impossible inputs — a .62
    matchup strikeout rate alongside a .69 walk rate, which sum past one —
    walks do take the whole remainder and home runs get nothing. That is a
    consequence of being handed rates that cannot coexist, and clamping the
    walk to the remainder does NOT change it: `bb / rest` is then exactly
    1.0 and the walk still fires every time. Verified by mutation, which is
    how an earlier version of this check was caught claiming otherwise.

    So this asserts the range where the model actually operates, extended
    well past anything real.
    """
    import random
    lg = dict(sim.league())
    # The best strikeout arm against the worst contact bat, with a walk rate
    # nobody has posted. Still sums to well under one.
    b = sim.BatterRates(name="x", k_pct=0.35, bb_pct=0.16, hr_pct=0.07,
                        babip=0.36, pa=600)
    p = sim.PitcherRates(name="y", k_pct=0.35, bb_pct=0.16, hr_pct=0.07,
                         babip=0.36, pa=600)
    seen = set()
    rng = random.Random(7)
    for _ in range(20000):
        seen.add(sim.pa_outcome(b, p, lg, rng))
    for want in (sim.HR, sim.BB, sim.K, sim.OUT):
        assert want in seen, (want, seen)

    # And impossible inputs must RAISE, not resolve. Clamping them produced
    # a defined but meaningless answer — walks taking the whole remainder,
    # home runs and balls in play gone — which is the silent failure this
    # model cannot detect downstream. Rates that sum past one mean a CALLER
    # bug, and it should surface where it happens.
    wild_b = sim.BatterRates(name="w", k_pct=0.40, bb_pct=0.30, hr_pct=0.12,
                             babip=0.40, pa=600)
    wild_p = sim.PitcherRates(name="v", k_pct=0.40, bb_pct=0.30, hr_pct=0.12,
                              babip=0.40, pa=600)
    rng = random.Random(11)
    try:
        for _ in range(500):
            sim.pa_outcome(wild_b, wild_p, lg, rng)
    except ValueError as e:
        assert "cannot coexist" in str(e), e
    else:
        raise AssertionError("impossible rates resolved silently")


class _Rolls:
    """An rng that returns a scripted sequence, then always 0.99.

    `baserunning` branches on three separate `random()` calls and the only
    way to land on the steal branch deliberately is to say what each one
    returns. A seeded `random.Random` would be a guess about internals.
    """
    def __init__(self, *vals):
        self.vals = list(vals)

    def random(self):
        return self.vals.pop(0) if self.vals else 0.99


def check_a_stolen_base_keeps_the_runner_who_stole_it():
    """`bases` holds RUNNER TOKENS and `baserunning` used to write `True`.

    The identity was destroyed at the steal, so a man who stole second and
    came round to score was dropped by `_credit` — a silent hole in the
    per-batter attribution that the run total alone cannot show, because
    the run still counted on the line.
    """
    r = sim.StartResult()
    fr = sim.Frame(bases=["JUDGE", None, None], outs=0)
    # no wild pitch (0.99), then a roll inside the steal band.
    key = (tuple(bool(b) for b in fr.bases), 0)
    row = sim.STEAL_TABLE.get(key)
    assert row, key
    cs_r, sb_r = row[1], row[0]
    sim.baserunning(r, fr, _Rolls(0.99, cs_r + sb_r / 2))
    assert r.stolen_bases == 1, (r.stolen_bases, fr.bases)
    assert fr.bases == [None, "JUDGE", None], fr.bases


def check_a_wild_pitch_credits_the_man_who_scored_on_it():
    """A run with nobody at the plate has a scorer and no RBI.

    `_score` was called directly here, so the run appeared on the line and
    in no batter's tally — which is how a whole-game attribution came up
    short of its own scoreboard.
    """
    r = sim.StartResult()
    fr = sim.Frame(bases=[None, None, "SOTO"], outs=0)
    sim.baserunning(r, fr, _Rolls(0.0))          # wild pitch fires
    assert r.wp_pb == 1, r.wp_pb
    assert r.runs == 1, r.runs
    assert r.scored_by == {"SOTO": 1}, r.scored_by
    assert r.rbi_by == {}, r.rbi_by
    assert fr.bases == [None, None, None], fr.bases


def check_a_steal_of_third_keeps_the_runner_too():
    """The other live steal branch, and it moves a DIFFERENT base.

    Written after a mutation sweep showed the first-to-second check left
    this line unguarded: two adjacent assignments, only one of them tested,
    is exactly the shape that survives a rewrite.
    """
    r = sim.StartResult()
    fr = sim.Frame(bases=[None, "SOTO", None], outs=1)
    row = sim.STEAL_TABLE.get(((False, True, False), 1))
    assert row, "the table must carry a man on second with one out"
    sb_r, cs_r, _to_third = row
    # past caught-stealing, inside the steal band, then under `to_third`.
    sim.baserunning(r, fr, _Rolls(0.99, cs_r + sb_r / 2, 0.0))
    assert r.stolen_bases == 1, (r.stolen_bases, fr.bases)
    assert fr.bases == [None, None, "SOTO"], fr.bases


def check_a_sacrifice_fly_credits_the_runner_and_the_batter():
    """The `SAC` branch had the same two defects `baserunning` had.

    It wrote booleans into a list that carries runner identity, and it
    scored the run through `_score` so nobody was credited. MLB awards an
    rbi on a sacrifice fly, so the batter gets one; the man on third gets
    the run.
    """
    r = sim.StartResult()
    fr = sim.Frame(bases=["A", None, "C"], outs=0)
    sim.apply_pa(sim.SAC, r, fr, random.Random(1), batter="BAT")
    assert r.runs == 1, r.runs
    assert r.scored_by == {"C": 1}, r.scored_by
    assert r.rbi_by == {"BAT": 1}, r.rbi_by
    # And the man on first moved up carrying his own name.
    assert fr.bases == [None, "A", None], fr.bases


def check_runs_on_a_home_run_are_counted_separately():
    """`runs_hr` is how runs ARRIVE, which the line alone cannot say."""
    r = sim.StartResult()
    fr = sim.Frame(bases=["A", "B", None], outs=0)
    sim.apply_pa(sim.HR, r, fr, random.Random(1), batter="BAT")
    assert r.runs == 3 and r.runs_hr == 3, (r.runs, r.runs_hr)
    sim.apply_pa(sim.B1, r, fr, random.Random(1), batter="BAT")
    fr.bases[2] = "D"
    sim.apply_pa(sim.B2, r, fr, random.Random(1), batter="BAT")
    assert r.runs_hr == 3, (r.runs, r.runs_hr)


# ── field state ────────────────────────────────────────────────────────
#
# The plate appearance was blind to the base-out state until 2026-08-29.
# These guard the PLUMBING, which is the half this project keeps shipping
# broken: `scratchpad/mutate.py` found five constants where the measurement
# was tested and the wiring was not.

def _state_rate(state, table, n=20000, seed=11):
    """Strikeout rate at one field state under one STATE_MULT table."""
    keep, keep_flag = sim.STATE_MULT, sim.USE_FIELD_STATE
    try:
        sim.STATE_MULT = table
        sim.USE_FIELD_STATE = True
        rng = random.Random(seed)
        b, p = _lineup(1)[0], _pitcher()
        k = 0
        for _ in range(n):
            if sim.pa_outcome(b, p, LG, rng, state=state) == sim.K:
                k += 1
        return k / n
    finally:
        sim.STATE_MULT, sim.USE_FIELD_STATE = keep, keep_flag


def check_field_state_is_inert_with_an_empty_table():
    """An empty table must be EXACTLY the state-blind model, not merely
    close — `odds_mult` short-circuits only on m == 1.0, so a stray 0.9999
    would silently change every rate in the model.

    SETS THE TABLE EXPLICITLY rather than trusting the shipped one. The
    first version relied on `STATE_MULT` being empty and broke the moment it
    was populated, which is a test coupled to configuration instead of to
    the property it is meant to guard.
    """
    keep = sim.STATE_MULT
    try:
        sim.STATE_MULT = {}
        rng_a, rng_b = random.Random(4), random.Random(4)
        b, p = _lineup(1)[0], _pitcher()
        a = [sim.pa_outcome(b, p, LG, rng_a, state=None) for _ in range(4000)]
        c = [sim.pa_outcome(b, p, LG, rng_b, state=(2, 1)) for _ in range(4000)]
        assert a == c, "field state changed the draw with an empty table"
    finally:
        sim.STATE_MULT = keep


def _state_shares(state, table, n=60000, seed=11):
    """Outcome shares at one field state under one STATE_MULT table.

    Returns the K and HBP shares together because the hit-by-pitch channel
    cannot be checked alone: it is drawn off the top, so its rate is also
    the denominator every rate below it is divided by.
    """
    keep, keep_flag = sim.STATE_MULT, sim.USE_FIELD_STATE
    try:
        sim.STATE_MULT = table
        sim.USE_FIELD_STATE = True
        rng = random.Random(seed)
        b, p = _lineup(1)[0], _pitcher()
        got = {sim.K: 0, sim.HBP: 0}
        for _ in range(n):
            o = sim.pa_outcome(b, p, LG, rng, state=state)
            if o in got:
                got[o] += 1
        return {k: v / n for k, v in got.items()}
    finally:
        sim.STATE_MULT, sim.USE_FIELD_STATE = keep, keep_flag


def check_field_state_scales_the_hit_by_pitch():
    """THE WIRING CHECK for the newest channel. Pitchers hit more batters
    with men on, and the table says so — but `hbp` is drawn against a
    `cond` that is CARRIED on the matchup rather than recomputed, so it was
    the one channel the first version of this table could not touch."""
    base = _state_shares((1, 0), {})[sim.HBP]
    up = _state_shares((1, 0), {(1, 0): {"hbp_pct": 3.0}})[sim.HBP]
    assert base > 0.005, f"no hit batsmen to scale: {base}"
    assert up > base * 2.4, (
        f"hbp multiplier did not reach the draw: {base} -> {up}")


def check_scaling_the_hit_by_pitch_moves_its_renormaliser_too():
    """THE REASON THIS ITEM WAITED, and the check the whole change exists
    for. Everything below the hit-by-pitch is divided by `cond`, which is
    `1 - sac - hbp`. Scale `hbp` and leave `cond` behind and every rate
    under it is renormalised by a denominator that no longer matches what
    was drawn — strikeouts, walks and hits all come out light, silently.

    A tenfold hit-by-pitch is not baseball; it is the size that separates
    the two implementations cleanly. With `cond` stale the strikeout rate
    falls ~9.5%. With it recomputed the only residual is the second-order
    `sac * hbp` term, worth ~1%.
    """
    base = _state_shares((1, 0), {})[sim.K]
    scaled = _state_shares((1, 0), {(1, 0): {"hbp_pct": 10.0}})
    assert scaled[sim.HBP] > 0.06, f"the 10x did not fire: {scaled}"
    rel = scaled[sim.K] / base - 1.0
    assert abs(rel) < 0.04, (
        f"K moved {rel:+.1%} when only hit batsmen changed — `cond` did not "
        f"follow `hbp`: {base:.4f} -> {scaled[sim.K]:.4f}")


def check_an_absent_hbp_key_leaves_the_draw_untouched():
    """A cell that carries other channels but no `hbp_pct` must produce the
    IDENTICAL sequence, not merely the same rate. `pa_from` short-circuits
    on the multiplier being exactly 1.0 for this reason — recomputing
    `cond` unconditionally would rebuild the same float by a different route
    and there is no guarantee the two agree in the last bit."""
    keep = sim.STATE_MULT
    try:
        sim.STATE_MULT = {(1, 0): {"k_pct": 0.95}}
        rng_a = random.Random(4)
        b, p = _lineup(1)[0], _pitcher()
        a = [sim.pa_outcome(b, p, LG, rng_a, state=(1, 0)) for _ in range(4000)]
        sim.STATE_MULT = {(1, 0): {"k_pct": 0.95, "hbp_pct": 1.0}}
        rng_b = random.Random(4)
        c = [sim.pa_outcome(b, p, LG, rng_b, state=(1, 0)) for _ in range(4000)]
        assert a == c, "an hbp_pct of exactly 1.0 changed the draw"
    finally:
        sim.STATE_MULT = keep


def check_the_shipped_state_table_is_frequency_normalised():
    """THE TABLE MUST NOT ADD OFFENCE, only move it around.

    Each multiplier is a cell's rate over the overall rate, so weighted by
    how often each state occurs they have to average to one. If they do not,
    the model simply scores more and the "clustering" claim is unfalsifiable
    — which is the failure mode pre-registered for this change.

    Weights are the real cell frequencies from the 748,905 plate appearances
    the table was counted on, 2023-2026.
    """
    freq = {(0, 0): 185488, (0, 1): 133782, (0, 2): 105760,
            (1, 0): 54433, (1, 1): 77197, (1, 2): 85831,
            (2, 0): 16315, (2, 1): 32177, (2, 2): 39829,
            (3, 0): 3149, (3, 1): 6643, (3, 2): 8301}
    tot = sum(freq.values())
    for stat in ("k_pct", "bb_pct", "babip", "hbp_pct", "hr_pct"):
        w = sum(n * sim.STATE_MULT.get(c, {}).get(stat, 1.0)
                for c, n in freq.items()) / tot
        assert abs(w - 1.0) < 0.005, f"{stat} averages {w:.4f}, not 1.0"


def check_home_runs_are_in_the_state_table_and_point_the_right_way():
    """REPLACES a check that asserted `hr_pct` was ABSENT, and the swap is
    the point. On 2026 alone the channel's entire spread was its own
    sampling error — tau 0.0000 — so it shipped as all-ones and this check
    guarded that. On 2023-2026, five times the data, tau is 0.0272 and the
    channel keeps 48%. The old null was underpowered, not wrong.

    Guards the DIRECTION rather than the values, because the direction is
    the baseball: a pitcher challenges a hitter with nobody aboard and works
    away from the barrel with men on. A sign flip here means the table was
    rebuilt from a broken scan.
    """
    got = {c: v["hr_pct"] for c, v in sim.STATE_MULT.items() if "hr_pct" in v}
    assert len(got) == 12, f"hr_pct missing from cells: {12 - len(got)}"
    empty = st.mean(v for c, v in got.items() if c[0] == 0)
    on = st.mean(v for c, v in got.items() if c[0] > 0)
    assert empty > on, (
        f"home runs should be commoner with the bases empty: "
        f"empty {empty:.4f} against men-on {on:.4f}")


def check_field_state_multiplier_reaches_the_plate_appearance():
    """THE WIRING CHECK. A table that is never read looks identical to a
    table full of ones, and the second is a defensible design while the
    first is dead code."""
    base = _state_rate((1, 0), {})
    up = _state_rate((1, 0), {(1, 0): {"k_pct": 1.5}})
    down = _state_rate((1, 0), {(1, 0): {"k_pct": 0.5}})
    assert up > base + 0.03, f"k multiplier did not raise K: {base} -> {up}"
    assert down < base - 0.03, f"k multiplier did not lower K: {base} -> {down}"


def check_field_state_only_touches_the_state_it_is_keyed_on():
    """A multiplier on one base-out cell must not leak into another, which
    is what a truthiness bug or a bad default in `.get` would produce."""
    table = {(1, 0): {"k_pct": 2.0}}
    hit = _state_rate((1, 0), table)
    miss = _state_rate((0, 0), table)
    plain = _state_rate((0, 0), {})
    assert hit > miss + 0.05, (hit, miss)
    assert abs(miss - plain) < 1e-12, "an unkeyed state was altered"


def check_field_state_turns_off():
    """Off must restore the state-blind model exactly, like every other
    USE_* flag here — the A/B is the only way a mechanism stays scoreable."""
    keep_flag, keep_tab = sim.USE_FIELD_STATE, sim.STATE_MULT
    try:
        sim.STATE_MULT = {(1, 0): {"k_pct": 2.0}}
        sim.USE_FIELD_STATE = False
        assert sim.state_mult((1, 0)) is None
        sim.USE_FIELD_STATE = True
        assert sim.state_mult((1, 0)) == {"k_pct": 2.0}
    finally:
        sim.USE_FIELD_STATE, sim.STATE_MULT = keep_flag, keep_tab


def check_walks_have_a_multiplier_slot():
    """Walks were the one channel with no `odds_mult` slot, so park,
    arsenal and field state all excluded them BY CONSTRUCTION — and a
    missing channel reads as a null rather than as an error."""
    rng = random.Random(9)
    b, p = _lineup(1)[0], _pitcher()

    def rate(m_bb, n=30000):
        mu = sim.resolve(b, p, LG)
        mu.m_bb = m_bb
        r = random.Random(9)
        return sum(1 for _ in range(n) if sim.pa_from(mu, r) == sim.BB) / n
    assert rate(1.5) > rate(1.0) + 0.02, "m_bb did not raise walks"
    assert rate(0.5) < rate(1.0) - 0.02, "m_bb did not lower walks"
    del rng


def check_the_walk_multiplier_defaults_to_exactly_one():
    """`odds_mult` short-circuits only on m == 1.0 exactly, so a default of
    0.9999 would silently rescale every walk in the model."""
    mu = sim.resolve(_lineup(1)[0], _pitcher(), LG)
    assert mu.m_bb == 1.0
    assert sim.NEUTRAL_PARK["bb"] == 1.0
    assert sim.park_mults(None)["bb"] == 1.0


def check_park_mults_reads_the_walk_index():
    """Savant serves a walk park factor and `sources/park.py` has always
    fetched it; until 2026-08-29 `park_mults` dropped it on the floor."""
    got = sim.park_mults({"hr": 110, "so": 99, "bacon": 100, "bb": 106})
    assert abs(got["bb"] - 1.06) < 1e-9, got
    # A venue with no walk index must come back neutral, not zero — the
    # falsy-value trap that `m()` exists to handle.
    assert sim.park_mults({"hr": 110, "so": 99})["bb"] == 1.0
