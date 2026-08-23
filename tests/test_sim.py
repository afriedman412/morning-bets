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

LG = {
    "season": 2026, "pa": 100000,
    "k_pct": 0.226, "bb_pct": 0.089, "hr_pct": 0.033, "babip": 0.294,
    "hit_mix": {"1b": 0.764, "2b": 0.216, "3b": 0.020},
    "runs_per_9": 4.63,
}


def _pitcher(**kw):
    return sim.PitcherRates(**{"name": "P", "k_pct": 0.226, "bb_pct": 0.089,
                               "hr_pct": 0.033, "babip": 0.294, "pa": 600,
                               **kw})


def _lineup(n=9, **kw):
    return [sim.BatterRates(**{"name": f"B{i}", "k_pct": 0.226,
                               "bb_pct": 0.089, "hr_pct": 0.033,
                               "babip": 0.294, "pa": 500, **kw})
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
    assert seen <= {sim.K, sim.BB, sim.HR, sim.B1, sim.B2, sim.B3, sim.OUT}, \
        seen


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
