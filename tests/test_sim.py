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

from src.context import sim
from src.context.sources import rates as rate_src

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
def check_pa_outcomes_are_all_known_constants():
    rng = random.Random(3)
    seen = set()
    for _ in range(3000):
        seen.add(sim.pa_outcome(_lineup(1)[0], _pitcher(), LG, rng))
    assert seen <= {sim.K, sim.BB, sim.HR, sim.B1, sim.B2, sim.B3, sim.OUT,
                    sim.SAC, sim.HBP}, seen


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
    runs = sim._advance(bases, sim.HR, rng)
    assert runs == 4, runs
    assert bases == [False, False, False], bases


def check_walk_with_bases_loaded_forces_exactly_one_run():
    rng = random.Random(1)
    bases = [True, True, True]
    assert sim._advance(bases, sim.BB, rng) == 1
    assert bases == [True, True, True]


def check_walk_with_a_gap_forces_nobody():
    rng = random.Random(1)
    bases = [False, True, False]
    assert sim._advance(bases, sim.BB, rng) == 0
    assert bases == [True, True, False], bases


def check_double_does_not_strand_the_runner_from_first_on_third_always():
    """Regression: both branches of the double put the runner from first on
    third, making the 45%-scores case dead code and costing runs. The
    simulator read 3.59 runs per nine against a real 4.03 until this was
    fixed."""
    scored = held = 0
    for seed in range(400):
        rng = random.Random(seed)
        bases = [True, False, False]
        r = sim._advance(bases, sim.B2, rng)
        if r:
            scored += 1
        else:
            held += 1
            assert bases == [False, True, True], bases
    assert scored > 0 and held > 0, (scored, held)


def check_runner_on_third_always_scores_on_a_single():
    for seed in range(50):
        rng = random.Random(seed)
        bases = [False, False, True]
        assert sim._advance(bases, sim.B1, rng) >= 1


def check_advance_never_produces_negative_or_impossible_runs():
    rng = random.Random(4)
    for _ in range(4000):
        bases = [rng.random() < 0.4 for _ in range(3)]
        before = sum(bases)
        o = rng.choice([sim.B1, sim.B2, sim.B3, sim.HR, sim.BB, sim.OUT])
        runs = sim._advance(list(bases), o, rng)
        assert 0 <= runs <= before + 1, (bases, o, runs)


# ── the hook ───────────────────────────────────────────────────────────
def check_removal_probability_is_monotone_in_every_term():
    h = sim.Hook()
    base = h.removal_p(80, 2, 5)
    assert h.removal_p(110, 2, 5) > base       # more pitches
    assert h.removal_p(80, 6, 5) > base        # more runs
    assert h.removal_p(80, 2, 7) > base        # later inning
    assert h.removal_p(80, 2, 5, baserunners=12) > base


def check_mid_inning_removal_responds_to_traffic_and_damage():
    """Runs are a LAGGING indicator — a starter who has put five men on and
    allowed nothing is about to be pulled. The runner and damage terms are
    what let the model see that."""
    h = sim.Hook()
    quiet = h.mid_removal_p(70, 0, 0, 0.0)
    traffic = h.mid_removal_p(70, 0, 2, 0.0)
    damage = h.mid_removal_p(70, 0, 0, 4.0)
    assert traffic > quiet, (quiet, traffic)
    assert damage > quiet, (quiet, damage)


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
        return sum(sim.simulate_start(_pitcher(), _lineup(), LG, hook,
                                      rng).outs for _ in range(400)) / 400
    assert mean_outs(-1.0) > mean_outs(0.0) > mean_outs(1.0)


def check_for_start_adds_club_and_pitcher_offsets():
    base = sim.Hook()
    sim._PATIENCE = {"XXX": 0.5}
    sim._LEASH = {"Somebody": -0.2}
    try:
        h = sim.for_start(base, "XXX", "Somebody")
        assert abs(h.team_offset - 0.3) < 1e-9, h.team_offset
        assert sim.for_start(base, "NOPE", "Nobody").team_offset == 0.0
    finally:
        sim._PATIENCE = sim._LEASH = None


def check_unknown_club_falls_back_to_the_league_hook():
    """Missing resolves to neutral, never to a guess — the same rule the
    rest of the context layer follows for absent group values."""
    sim._PATIENCE, sim._LEASH = {}, {}
    try:
        assert sim.patience("ZZZ") == 0.0
        assert sim.leash("Nobody At All") == 0.0
    finally:
        sim._PATIENCE = sim._LEASH = None


# ── whole starts ───────────────────────────────────────────────────────
def check_start_is_internally_consistent():
    rng = random.Random(6)
    for _ in range(300):
        r = sim.simulate_start(_pitcher(), _lineup(), LG, sim.Hook(), rng)
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
    a = sim.simulate(_pitcher(), _lineup(), LG, n=50, seed=42)
    b = sim.simulate(_pitcher(), _lineup(), LG, n=50, seed=42)
    assert [x.outs for x in a] == [x.outs for x in b]
    assert [x.k for x in a] == [x.k for x in b]


def check_different_seeds_give_different_draws():
    a = sim.simulate(_pitcher(), _lineup(), LG, n=50, seed=1)
    b = sim.simulate(_pitcher(), _lineup(), LG, n=50, seed=2)
    assert [x.outs for x in a] != [x.outs for x in b]


def check_better_lineup_shortens_the_start():
    good = _lineup(k_pct=0.14, bb_pct=0.13, hr_pct=0.06, babip=0.34)
    weak = _lineup(k_pct=0.32, bb_pct=0.05, hr_pct=0.012, babip=0.25)
    a = sim.simulate(_pitcher(), good, LG, n=500, seed=8)
    b = sim.simulate(_pitcher(), weak, LG, n=500, seed=8)
    ma = sum(x.outs for x in a) / len(a)
    mb = sum(x.outs for x in b) / len(b)
    assert mb > ma + 0.5, (ma, mb)


def check_park_factor_only_moves_home_runs():
    a = sim.simulate(_pitcher(), _lineup(), LG, n=800, seed=8, hr_park=0.6)
    b = sim.simulate(_pitcher(), _lineup(), LG, n=800, seed=8, hr_park=1.6)
    assert sum(x.hr for x in b) > sum(x.hr for x in a)


def check_prob_over_is_a_probability_and_monotone_in_the_line():
    res = sim.simulate(_pitcher(), _lineup(), LG, n=600, seed=12)
    prev = 1.1
    for line in (8.5, 11.5, 14.5, 17.5, 20.5):
        p = sim.prob_over(res, "outs", line)
        assert 0.0 <= p <= 1.0, p
        assert p <= prev, (line, p, prev)
        prev = p


def check_distribution_quantiles_are_ordered():
    d = sim.distribution(sim.simulate(_pitcher(), _lineup(), LG, n=400,
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
        r = sim.simulate_start(_pitcher(k_pct=0.45), _lineup(k_pct=0.40),
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
    res = sim.simulate(p, lineup, LG, n=2500, seed=22)
    k = sum(r.k for r in res)
    bf = sum(r.batters for r in res)
    assert abs(k / bf - want) < 0.012, (k / bf, want)


def check_strikeout_pitcher_produces_more_strikeouts():
    lo = sim.simulate(_pitcher(k_pct=0.15), _lineup(), LG, n=600, seed=23)
    hi = sim.simulate(_pitcher(k_pct=0.35), _lineup(), LG, n=600, seed=23)
    mlo = sum(r.k for r in lo) / len(lo)
    mhi = sum(r.k for r in hi) / len(hi)
    assert mhi > mlo + 2.0, (mlo, mhi)


def check_lineup_contact_reduces_strikeouts():
    """The opposing nine matter, which is the whole reason for simulating
    rather than counting a pitcher's last six starts — that approach cannot
    see who he is facing."""
    whiffy = _lineup(k_pct=0.32)
    contact = _lineup(k_pct=0.14)
    a = sim.simulate(_pitcher(), whiffy, LG, n=600, seed=24)
    b = sim.simulate(_pitcher(), contact, LG, n=600, seed=24)
    assert sum(r.k for r in a) > sum(r.k for r in b) * 1.3


def check_k_distribution_is_wider_than_a_point_estimate_suggests():
    """Two starts with the same expected K are not the same bet. If the
    simulated spread collapses, every threshold away from the mean gets
    priced as a near-certainty."""
    d = sim.distribution(sim.simulate(_pitcher(k_pct=0.26), _lineup(),
                                      LG, n=1500, seed=25), "k")
    assert d["p90"] - d["p10"] >= 4, d


def check_k_prob_over_is_monotone_in_the_line():
    res = sim.simulate(_pitcher(), _lineup(), LG, n=800, seed=26)
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
        r = [sim.simulate_start(_pitcher(), _lineup(), LG, h, rng)
             for _ in range(2000)]
        n = len(r)
        return sum(x.k for x in r) / n, sum(x.batters for x in r) / n

    k_long, bf_long = stats(-1.0)
    k_short, bf_short = stats(1.0)
    assert k_long > k_short, (k_long, k_short)
    assert bf_long > bf_short, (bf_long, bf_short)
    implied = (bf_long - bf_short) * LG["k_pct"]
    assert abs((k_long - k_short) - implied) < 0.15, \
        (k_long - k_short, implied)


def check_k_and_outs_move_together_across_starts():
    """Within the simulation, longer outings must carry more strikeouts.
    A negative or flat relationship means the hook and the rate model have
    come uncoupled."""
    res = sim.simulate(_pitcher(), _lineup(), LG, n=1200, seed=28)
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
    res = sim.simulate(_pitcher(), _lineup(), LG, n=400, seed=31)
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


# ── input uncertainty (measured harmful; kept off) ─────────────────────
def check_posterior_draw_is_centred_on_the_rate():
    rng = random.Random(41)
    draws = [sim._draw(0.30, 600, rng) for _ in range(3000)]
    assert abs(sum(draws) / len(draws) - 0.30) < 0.01


def check_posterior_is_wider_for_a_thinner_sample():
    """A 600-PA starter's rate barely moves; a 60-PA one moves a lot. If
    this inverts, the model would be most confident about the players it
    knows least."""
    import statistics as st
    rng = random.Random(42)
    wide = st.pstdev([sim._draw(0.30, 60, rng) for _ in range(2000)])
    tight = st.pstdev([sim._draw(0.30, 600, rng) for _ in range(2000)])
    assert wide > tight * 1.8, (wide, tight)


def check_posterior_floor_bounds_a_tiny_sample():
    """Without MIN_POSTERIOR_PA a 5-PA hitter gets a posterior so wide the
    draw is pure noise — that overstates uncertainty rather than
    representing it."""
    import statistics as st
    rng = random.Random(43)
    sd = st.pstdev([sim._draw(0.30, 5, rng) for _ in range(2000)])
    ref = st.pstdev([sim._draw(0.30, sim.MIN_POSTERIOR_PA, rng)
                     for _ in range(2000)])
    assert abs(sd - ref) < 0.02, (sd, ref)


def check_uncertainty_knobs_default_off():
    """MEASURED HARMFUL, do not switch on without re-measuring.

    Drawing rates and jittering the hook per start was built to cure the
    model's compressed probabilities and does the opposite: widening a
    single start's distribution pushes its P(over) TOWARD the base rate,
    which is the direction the defect already runs. On 600 starts at outs
    15.5, Brier skill fell 10.3% -> 9.5% (hook sigma) and -> 9.3% (rate
    draws), with sd(p) falling 0.120 -> 0.114.

    The compression is missing SIGNAL, not missing noise.
    """
    assert sim.HOOK_SIGMA == 0.0, sim.HOOK_SIGMA
    assert sim.DRAW_RATES is False


def check_defaults_reproduce_point_estimate_simulation():
    """With both knobs off, `simulate` must be bit-identical to simulating
    the same seed directly — otherwise every calibration number recorded
    before they existed is silently invalidated."""
    p, l = _pitcher(), _lineup()
    a = sim.simulate(p, l, LG, n=40, seed=77)
    rng = random.Random(77)
    b = [sim.simulate_start(p, l, LG, sim.Hook(), rng) for _ in range(40)]
    assert [x.outs for x in a] == [x.outs for x in b]
    assert [x.k for x in a] == [x.k for x in b]


# ── multi-stat calibration coverage ────────────────────────────────────
def check_earned_runs_maps_to_simulated_runs_not_total_runs():
    """The simulation models no errors, so every run it produces is earned.
    Scoring it against total runs would charge the model for defence it
    never simulated and read as a systematic under-prediction."""
    from src.context import calibrate as cal
    assert cal._STAT_ATTR["er"] == "runs"
    assert cal._STAT_COL["er"] == "er"


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
    m = sim.park_mults({"hr": 100, "so": 100, "bacon": 100})
    assert m == {"hr": 1.0, "k": 1.0, "bip": 1.0}, m


def check_park_moves_the_right_outcomes():
    """A high-strikeout park raises K; a homer park raises HR. If the keys
    were crossed, Coors would suppress offence."""
    hot = sim.park_mults({"hr": 125, "so": 90, "bacon": 113})
    cold = sim.park_mults({"hr": 75, "so": 116, "bacon": 94})
    assert hot["hr"] > cold["hr"] and hot["k"] < cold["k"]

    def counts(park):
        rng = random.Random(51)
        res = [sim.simulate_start(_pitcher(), _lineup(), LG, sim.Hook(),
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
    a = [sim.simulate_start(p, l, LG, sim.Hook(), random.Random(9))
         for _ in range(30)]
    b = [sim.simulate_start(p, l, LG, sim.Hook(), random.Random(9),
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


def check_leash_covers_thin_starters_not_just_established_ones():
    """An 8-start bar left ~150 pitchers on the league default leash, which
    is what let a two-inning opener be simulated out to sixteen outs.
    LEASH_SHRINK_K discounts three starts to about a fifth of their apparent
    residual, which beats pretending he is league-average."""
    import inspect

    from src.context import calibrate as cal
    sig = inspect.signature(cal.fit_pitcher_leash)
    assert sig.parameters["min_starts"].default <= 3, \
        "leash coverage narrowed again; openers will get a starter's leash"
    assert cal.LEASH_SHRINK_K >= 8, cal.LEASH_SHRINK_K


def check_declining_to_price_is_reported_not_silent():
    """A skipped pitcher must be named with a reason. Silently dropping him
    reads identically to 'no market existed', and the whole point of the
    gate is that the model knows it cannot answer."""
    import inspect

    from src.context import price
    src = inspect.getsource(price.price_slate)
    assert "skipped[name] = why" in src
    assert "declined to price" in src


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
        r = sim.simulate_start(_pitcher(), _lineup(), LG, sim.Hook(), rng)
        scored += r.runs
        advanced += r.sacrifices
    assert advanced > 0, "no sacrifices recorded across 300 starts"


def check_caught_stealing_records_an_out_with_no_batter():
    """CS counts toward a pitcher's innings pitched, so omitting it cost
    about 0.10 outs a start. It must consume an out WITHOUT consuming a
    plate appearance — if it increments `batters` the fix is wrong."""
    res = sim.simulate(_pitcher(), _lineup(), LG, n=3000, seed=72)
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
    res = sim.simulate(_pitcher(), _lineup(), LG, n=4000, seed=73)
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
    res = sim.simulate(_pitcher(), _lineup(), LG, n=2500, seed=81)
    sb = sum(r.stolen_bases for r in res) / len(res)
    cs = sum(r.caught_stealing for r in res) / len(res)
    assert sb > cs, (sb, cs)


def check_hit_by_pitch_is_tracked_apart_from_walks():
    """HBP must not be folded into `bb`, or the walk total stops matching
    the boxscore — which is the number the calibration checks."""
    res = sim.simulate(_pitcher(), _lineup(), LG, n=2500, seed=82)
    hbp = sum(r.hbp for r in res) / len(res)
    assert 0.10 < hbp < 0.45, hbp
    assert sim.DAMAGE[sim.HBP] == sim.DAMAGE[sim.BB]


def check_rates_are_conditioned_on_the_off_the_top_draws():
    """Sacrifices and hit-by-pitches are drawn before the strikeout branch,
    so everything after is conditional on neither firing. Without dividing
    by (1 - SAC_RATE - HBP_RATE) every marginal rate comes out light by
    exactly that much — measured as K/9 8.16 against a real 8.44."""
    import inspect
    src = inspect.getsource(sim.pa_outcome)
    assert "cond = 1.0 - SAC_RATE - HBP_RATE" in src
    assert src.count("/ cond") >= 3, "not every branch is rescaled"


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
    assert sim.FIRST_TO_THIRD_ON_1B < 0.45, sim.FIRST_TO_THIRD_ON_1B
    assert sim.SECOND_SCORES_ON_1B < 0.80, sim.SECOND_SCORES_ON_1B
    assert sim.FIRST_SCORES_ON_2B <= 0.65, sim.FIRST_SCORES_ON_2B
