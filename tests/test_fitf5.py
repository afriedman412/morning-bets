"""Checks for the F5 fitting objective, the rules seam, and f5 itself.

Offline like the rest: nothing here opens the database. `side_cases` is the
one function that must, so it is exercised through hand-built case dicts
that carry the same keys.

The bugs these guard are the ones this kind of code actually ships: a
scoring rule that is not proper, a home/away side read off the wrong column,
an override that silently does nothing, and a Monte Carlo debias that
flatters the model instead of correcting it.
"""
from __future__ import annotations

import random

from src.context import f5, fitf5, sim
from tests.test_sim import LG, _lineup, _pitcher


# ── sim.rules ──────────────────────────────────────────────────────────
def check_rules_overrides_and_restores():
    """The seam the fit needs: change a constant, put it back."""
    before = sim.FIRST_TO_THIRD_ON_1B
    with sim.rules(FIRST_TO_THIRD_ON_1B=0.99):
        assert sim.FIRST_TO_THIRD_ON_1B == 0.99
    assert sim.FIRST_TO_THIRD_ON_1B == before


def check_rules_restores_after_an_exception():
    """A failed evaluation must not leave the module mutated.

    Without the try/finally, one exception inside a coordinate descent
    poisons every candidate scored after it — and the search still completes
    and still reports a winner.
    """
    before = sim.SECOND_SCORES_ON_1B
    try:
        with sim.rules(SECOND_SCORES_ON_1B=0.01):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert sim.SECOND_SCORES_ON_1B == before


def check_rules_rejects_an_unknown_name():
    """A typo must raise, not be ignored.

    An ignored override is invisible: every candidate scores identically,
    the surface reads flat, and the parameter gets written off as not
    mattering when it was never applied.
    """
    try:
        with sim.rules(FIRST_TO_THRID_ON_1B=0.5):
            pass
    except ValueError:
        return
    raise AssertionError("a misspelled constant was accepted")


def check_rules_actually_reaches_the_simulation():
    """Restoring correctly is worthless if the sim never reads the global.

    Advancement at zero must strand runners that advancement at one scores,
    so runs have to fall. This is the check that fails if `_advance` is ever
    refactored to capture the constants at import time.
    """
    lg = dict(LG)
    p, nine = _pitcher(), _lineup()

    def runs(**over):
        with sim.rules(**over):
            rng = random.Random(4)
            return sum(sim.simulate_start(p, nine, lg, sim.Hook(), rng).runs
                       for _ in range(150))

    cold = runs(FIRST_TO_THIRD_ON_1B=0.0, SECOND_SCORES_ON_1B=0.0,
                FIRST_SCORES_ON_2B=0.0, RUNNER_ADVANCES_ON_OUT=0.0)
    hot = runs(FIRST_TO_THIRD_ON_1B=1.0, SECOND_SCORES_ON_1B=1.0,
               FIRST_SCORES_ON_2B=1.0, RUNNER_ADVANCES_ON_OUT=1.0)
    assert hot > cold * 1.1, (cold, hot)


# ── the scoring rule ───────────────────────────────────────────────────
def check_rps_rewards_the_truth():
    """A distribution centred on what happened must score better than one
    that is not. The minimum sanity bar for a loss function."""
    right = fitf5._rps([2] * 400, 2, fitf5.SIDE_LINES)
    wrong = fitf5._rps([7] * 400, 2, fitf5.SIDE_LINES)
    assert right < wrong, (right, wrong)


def check_rps_is_proper():
    """Honesty must beat shading — the property that makes this fittable.

    A model whose true belief is the sampled distribution cannot improve its
    expected score by reporting anything else. Checked against a spread of
    misreports on a known distribution: if any of them wins, the search will
    find it and the fitted parameters will encode a lie.
    """
    rng = random.Random(11)
    truth = [rng.choice([0, 1, 1, 2, 2, 3, 4, 5]) for _ in range(4000)]
    outcomes = [rng.choice(truth) for _ in range(3000)]

    def expected(pred):
        return sum(fitf5._rps(pred, a, fitf5.SIDE_LINES)
                   for a in outcomes) / len(outcomes)

    honest = expected(truth)
    for shift in (-2, -1, 1, 2):
        shaded = expected([max(0, v + shift) for v in truth])
        assert honest < shaded, (shift, honest, shaded)


def check_rps_debias_removes_the_sim_count_effect():
    """The same true distribution must score the same at 10 draws and 200.

    Undebiased it does not — the estimate carries p(1-p)/n and squaring adds
    it straight to the score, which reads as a model that improves when you
    only ever changed the sim count. Measured 1.434 / 1.411 / 1.380 at
    20 / 40 / 80 sims before this was corrected.

    An EXPECTATION is what the correction fixes, so this averages over many
    replications. A single pair of samples is dominated by its own sampling
    noise, which is how the first version of this check failed while the
    code under it was right. Undebiased, the gap here is about 0.074 against
    a tolerance of 0.03.
    """
    rng = random.Random(3)
    dist = [0, 1, 1, 2, 2, 3, 4]

    def mean_score(n, reps=1500):
        return sum(fitf5._rps([rng.choice(dist) for _ in range(n)], 2,
                              fitf5.SIDE_LINES) for _ in range(reps)) / reps

    small, big = mean_score(10), mean_score(200)
    assert abs(small - big) < 0.03, (small, big)


def check_rps_debias_never_goes_negative():
    """The correction cannot outrun the error it corrects.

    Worth pinning, because the obvious worry about subtracting a variance is
    that a confident-and-wrong distribution scores below a correct one. It
    cannot happen: at p = k/n the squared error is (n-k)^2/n^2 and the
    correction is k(n-k)/(n^2(n-1)), and they cross exactly at k = n-1 where
    both equal 1/n^2. So a clamp would only ever fire on a bug, and adding
    one would hide it.
    """
    for n in (5, 20, 200):
        for k in range(n + 1):
            vals = [3] * k + [0] * (n - k)          # p(over 1.5) = k/n
            for actual in (0, 3):
                got = fitf5._rps(vals, actual, (1.5,))
                assert got >= -1e-12, (n, k, actual, got)


# ── the objective ──────────────────────────────────────────────────────
def _case(runs, seed=1, offset=0.0, game="G1", **kw):
    return {"game_id": game, "date": "2026-08-01", "team": "XXX",
            "is_home": True, "pitcher": _pitcher(), "lineup": _lineup(),
            "runs": runs, "covered": True, "offset": offset, "seed": seed,
            **kw}


def check_evaluate_is_deterministic():
    """Same parameters, same seed, same score. Common random numbers are the
    only reason a coordinate descent on this objective converges at all."""
    cases = [_case(2, seed=i) for i in range(6)]
    a = fitf5.evaluate(cases, None, n_sims=12, lg=dict(LG))
    b = fitf5.evaluate(cases, None, n_sims=12, lg=dict(LG))
    assert a["loss"] == b["loss"], (a["loss"], b["loss"])


def check_evaluate_applies_its_parameters():
    """Changing a fitted constant must change the score.

    Guards the wiring, not the model: `evaluate` splits its parameter dict
    between a Hook and `sim.rules`, and a key routed to neither would leave
    the objective flat in that direction while the search happily explored
    it.
    """
    cases = [_case(2, seed=i) for i in range(8)]
    base = fitf5.evaluate(cases, None, n_sims=20, lg=dict(LG))
    for k, v in (("FIRST_SCORES_ON_2B", 0.95), ("intercept", -2.0)):
        moved = fitf5.evaluate(cases, {k: v}, n_sims=20, lg=dict(LG))
        assert moved["loss"] != base["loss"], k


def check_evaluate_pairs_only_complete_games():
    """A game total needs BOTH starters. One-sided games must not be scored
    as if the missing half allowed zero, which would drag every total
    downward and pull the fit toward a high-scoring model to compensate."""
    cases = [_case(2, seed=1, game="A"), _case(3, seed=2, game="A"),
             _case(1, seed=3, game="B")]
    res = fitf5.evaluate(cases, None, n_sims=10, lg=dict(LG))
    assert res["n_sides"] == 3 and res["n_games"] == 1, res


def check_paired_se_beats_combining_independent_ones():
    """The error bar on a difference must use the pairing.

    Two candidates are scored over the same sides with the same seeds, so
    their losses move together across salts. Combining their separate
    standard errors as if they were independent inflates the bar — measured
    2.6x on the real objective, enough that the search rejects every move
    and reports that no parameter matters.

    Built here from correlated series with a small constant offset: the
    paired error must be far smaller than the independent combination, and
    the paired mean must recover the offset exactly.
    """
    a = [1.30, 1.34, 1.28, 1.36, 1.31]
    b = [x - 0.005 for x in a]                 # same noise, real shift
    delta, se = fitf5._paired_se(a, b)
    assert abs(delta + 0.005) < 1e-9, delta
    assert se < 1e-9, se
    _, sa = fitf5._mean_se(a)
    _, sb = fitf5._mean_se(b)
    independent = (sa ** 2 + sb ** 2) ** 0.5
    assert independent > 0.01, independent
    assert se < independent / 10, (se, independent)


def check_accept_rejects_an_improvement_inside_the_noise():
    """The failure this guards is silent: accept-any-improvement converges,
    prints a lower loss, and the holdout does not reproduce it.

    Here the candidate is better on average but by less than the scatter of
    the paired differences, which is exactly the case a plain `<` accepts
    and should not.
    """
    cur = [1.30, 1.34, 1.28, 1.36]
    win = [1.29, 1.36, 1.24, 1.39]          # mean better, wildly inconsistent
    take, delta, se = fitf5.accept(cur, win)
    assert delta < 0, delta               # it IS an improvement on average
    assert not take, (delta, se)          # and it must still be refused


def check_accept_takes_a_consistent_improvement():
    """The bar must still let a real move through, or the search cannot
    move at all and 'nothing matters' becomes an artifact of the rule."""
    cur = [1.30, 1.34, 1.28, 1.36]
    win = [x - 0.02 for x in cur]
    take, delta, se = fitf5.accept(cur, win)
    assert take and abs(delta + 0.02) < 1e-9, (take, delta, se)


def check_accept_refuses_a_tie():
    """Identical loss vectors are not an improvement. Guards the boundary:
    a `<=` here would walk the parameters at random through flat regions."""
    v = [1.30, 1.34, 1.28, 1.36]
    take, delta, _ = fitf5.accept(v, list(v))
    assert not take and delta == 0.0, (take, delta)


def check_defaults_cover_every_searched_parameter():
    """Every name in the grid must resolve to a shipped starting value.

    A parameter present in GRID but absent from PARAMS is never searched; one
    in PARAMS with no default raises mid-fit, after minutes of work.
    """
    d = fitf5.defaults()
    # GRID must cover everything that CAN be searched, including the hook
    # terms `--with-hook` switches back on, and nothing else.
    assert set(fitf5.GRID) == set(fitf5.HOOK_KEYS) | set(fitf5.RULE_KEYS), (
        set(fitf5.GRID) ^ (set(fitf5.HOOK_KEYS) | set(fitf5.RULE_KEYS)))
    assert set(fitf5.PARAMS) <= set(fitf5.GRID), fitf5.PARAMS
    for k in fitf5.PARAMS:
        assert k in d, k
    # Every rule key must be reachable through the seam, or `sim.rules`
    # raises mid-fit after minutes of work.
    for k in fitf5.RULE_KEYS:
        assert k in sim.FITTABLE, k
    for k in fitf5.HOOK_KEYS:
        assert hasattr(sim.Hook(), k), k


def check_the_fit_does_not_move_the_hook_by_default():
    """The goal is an accurate game simulation, not a tuned removal rule.

    Measured, every hook term is flat inside its own error bar on this
    objective, and the hook reaches an F5 number only when the starter fails
    to finish the fifth — which he does about a quarter of the time. So the
    default search moves run-production constants only. This pins the
    default rather than the capability: `--with-hook` still exists.
    """
    assert set(fitf5.PARAMS) == set(fitf5.RULE_KEYS), fitf5.PARAMS
    for k in fitf5.HOOK_KEYS:
        assert k not in fitf5.PARAMS, k


def check_scoring_covers_the_whole_run_distribution():
    """The score must span the outcome space, not a book's liquid lines.

    Summed across the full support this is the discrete CRPS — how far the
    simulated DISTRIBUTION sits from what happened. Restricted to the lines
    a book offers, the same arithmetic becomes 'how well do we hit props'
    and tunes the model to the shape of somebody's board.

    A side allows 2.38 runs through five on average and the thresholds have
    to reach well past that, or the fit is blind to the blowups.
    """
    assert fitf5.SIDE_LINES[0] == 0.5, fitf5.SIDE_LINES
    assert max(fitf5.SIDE_LINES) >= 8.5, fitf5.SIDE_LINES
    steps = {b - a for a, b in zip(fitf5.SIDE_LINES, fitf5.SIDE_LINES[1:])}
    assert steps == {1.0}, steps          # no gaps: every count is scored
    assert max(fitf5.TOTAL_LINES) >= max(fitf5.SIDE_LINES), "totals run higher"


# ── f5 ─────────────────────────────────────────────────────────────────
def check_side_runs_returns_the_starter_line():
    """`_side_runs` hands back the StartResult so the fit can report how far
    the starter got without simulating him twice."""
    rng = random.Random(2)
    runs, r = f5._side_runs(_pitcher(), _lineup(), dict(LG), sim.Hook(),
                            rng, sim.NEUTRAL_PARK, _pitcher(name="rel"))
    assert isinstance(runs, int) and isinstance(r, sim.StartResult)
    assert r.outs <= 15, r.outs


def check_f5_never_exceeds_five_innings_of_outs():
    """The starter's share is capped at 15 outs; relief covers the rest.
    A starter credited with a sixth inning would settle an F5 bet on runs
    that market never saw."""
    rng = random.Random(6)
    for _ in range(40):
        _, r = f5._side_runs(_pitcher(k_pct=0.40), _lineup(), dict(LG),
                             sim.Hook(intercept=-99.0, mid_intercept=-99.0),
                             rng, sim.NEUTRAL_PARK, _pitcher(name="rel"))
        assert r.outs <= 15, r.outs


def check_f5_scores_are_not_crossed():
    """The AWAY starter's runs allowed are the HOME team's score.

    Getting this backwards is the single most likely way to build an F5
    model that looks fine and is exactly wrong. Checked by making one
    starter unhittable: the side he pitches for must be the one that keeps
    the opponent off the board.
    """
    lg = dict(LG)
    ace = _pitcher(name="ace", k_pct=0.90, bb_pct=0.001, hr_pct=0.0001,
                   babip=0.01)
    bad = _pitcher(name="bad", k_pct=0.02, bb_pct=0.30, hr_pct=0.15,
                   babip=0.45)
    res = f5.simulate_f5(ace, _lineup(), bad, _lineup(), lg, n=60, seed=1)
    home = sum(r.home for r in res) / len(res)
    away = sum(r.away for r in res) / len(res)
    # The away starter is the ace, so the HOME team (which he faces) is shut
    # down; the away team feasts on the home starter.
    assert home < away, (home, away)
    assert home < 1.0 and away > 3.0, (home, away)


def check_f5_relief_is_scaled_to_the_outs_it_covers():
    """Relief innings are simulated in whole innings and scaled down to the
    outs actually needed. Without the scaling a starter pulled with one out
    left gets charged a full inning of relief scoring."""
    lg = dict(LG)
    rng = random.Random(9)
    quick = sim.Hook(intercept=5.0, mid_intercept=-99.0)   # gone after one
    tot = 0
    for _ in range(60):
        runs, r = f5._side_runs(_pitcher(), _lineup(), lg, quick, rng,
                                sim.NEUTRAL_PARK, _pitcher(name="rel"))
        assert r.outs <= 15
        tot += runs
    # Five innings of league-average pitching is ~2.4 runs; a starter yanked
    # after one plus four of relief cannot plausibly average double that.
    assert 0.5 < tot / 60 < 6.0, tot / 60
