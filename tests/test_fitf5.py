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

from src.context import calibrate as cal
from src.context import fitf5, game, sim
from tests import fixtures as fx
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
            return sum(fx.one_side(p, nine, lg, sim.Hook(), rng).runs
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
def _case(runs, seed=1, offset=0.0, game="G1", home=True, **kw):
    return {"game_id": game, "date": "2026-08-01",
            "team": "HOM" if home else "AWY",
            "is_home": home, "pitcher": _pitcher(), "lineup": _lineup(),
            "runs": runs, "covered": True, "offset": offset, "seed": seed,
            **kw}


def _pair(runs=2, game="G1", seed=1):
    """A complete game: one home side and one away side.

    `evaluate` scores GAMES now, not sides — `game.py` simulates both halves
    at once — so a fixture of same-side cases produces no pairs at all and
    every score comes back zero.
    """
    return [_case(runs, seed=seed, game=game, home=True),
            _case(runs, seed=seed + 1, game=game, home=False)]


def check_evaluate_is_deterministic():
    """Same parameters, same seed, same score. Common random numbers are the
    only reason a coordinate descent on this objective converges at all."""
    cases = _pair(2, game="A") + _pair(3, game="B", seed=9)
    a = fitf5.evaluate(cases, None, n_sims=12, lg=dict(LG))
    b = fitf5.evaluate(cases, None, n_sims=12, lg=dict(LG))
    assert a["loss"] == b["loss"], (a["loss"], b["loss"])


def check_evaluate_applies_its_parameters():
    """Changing a fitted constant must change the score.

    Guards the wiring, not the model: `evaluate` splits its parameter dict
    between a Hook and `sim.rules`, and a key routed to neither would leave
    the objective flat in that direction while the search happily explored
    it.

    THE FIXTURE MUST SUPPLY A BULLPEN. `evaluate` looks arms up by team, and
    these cases use fake team names, so `Side.pen` came back empty — and an
    empty pen makes `Side.current` fall back to the starter for the whole
    game. `intercept` then has no channel to run production whatsoever, and
    the check only ever passed because changing it shifted the RNG stream.
    That is a guards-nothing check: it broke the moment an unrelated change
    consumed a draw per plate appearance and realigned the two streams.
    """
    cases = (_pair(2, game="A") + _pair(3, game="B", seed=9)
             + _pair(1, game="C", seed=21))
    # A pen clearly worse than the starter, so WHO is pitching moves runs.
    pen = [{"name": f"R{i}", "k_pct": 0.05, "bb_pct": 0.25, "hr_pct": 0.10,
            "babip": 0.40, "apps": 40} for i in range(6)]
    real_bullpens = fitf5.rate_src.bullpens
    fitf5.rate_src.bullpens = lambda lg, **kw: {"HOM": pen, "AWY": pen}
    # `intercept` is a `sim.Hook` field, and the learned removal model
    # bypasses the Hook entirely — with it on, no hook parameter can move
    # any loss, which is a fact about the model rather than a broken fit.
    hook_orig, game.USE_LEARNED_HOOK = game.USE_LEARNED_HOOK, False
    try:
        _check_parameters_move_the_loss(cases)
    finally:
        fitf5.rate_src.bullpens = real_bullpens
        game.USE_LEARNED_HOOK = hook_orig


def _check_parameters_move_the_loss(cases):
    base = fitf5.evaluate(cases, None, n_sims=20, lg=dict(LG))
    # WP_PB_RATE rather than GIDP_RATE: the double-play rate became a
    # MEASURED table keyed by out count and left the search, so it is no
    # longer routed through `sim.rules` and would make this check vacuous.
    # It failed for exactly that reason when the measurement landed, which
    # is what it is for.
    for k, v in (("WP_PB_RATE", 0.20), ("intercept", -2.0)):
        moved = fitf5.evaluate(cases, {k: v}, n_sims=20, lg=dict(LG))
        assert moved["loss"] != base["loss"], k


def check_evaluate_pairs_only_complete_games():
    """A game total needs BOTH starters. One-sided games must not be scored
    as if the missing half allowed zero, which would drag every total
    downward and pull the fit toward a high-scoring model to compensate."""
    # Game A is complete; game B has only one side and must be dropped
    # entirely — a half-game cannot be simulated by an engine that plays
    # both halves, and scoring it as if the missing side allowed zero would
    # drag every total downward.
    cases = _pair(2, game="A") + [_case(1, seed=3, game="B")]
    res = fitf5.evaluate(cases, None, n_sims=10, lg=dict(LG))
    assert res["n_games"] == 1 and res["n_sides"] == 2, res


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


# ── recency weighting ──────────────────────────────────────────────────
class _Rows(list):
    """A fake cursor. `pitcher_rates` calls `.fetchall()` on the result of
    `.execute()`, while the weighted path iterates it directly — so the stub
    has to be both a list and a cursor."""

    def fetchall(self):
        return list(self)


def check_recency_off_reproduces_the_flat_aggregate():
    """`half_life=None` must fall through EXACTLY, not approximately.

    The switch is the safety property: recency ships off because every
    imported baseball effect this project measured came back zero, and a
    default path that quietly differed would make that default a change
    nobody chose.
    """
    from src.context.sources import rates as R
    lg = {"k_pct": 0.22, "bb_pct": 0.078, "hr_pct": 0.033, "babip": 0.29}
    rows = [
        {"name": "A", "date": "2026-08-01", "o": 18, "h": 5, "bb": 2,
         "k": 6, "hr": 1, "apps": 1},
        {"name": "A", "date": "2026-06-01", "o": 15, "h": 8, "bb": 3,
         "k": 3, "hr": 2, "apps": 1},
    ]

    class _C:
        def execute(self, *_):
            return _Rows(rows)
    flat = R.pitcher_rates(lg, conn=_C())
    same = R.pitcher_rates_recent(lg, half_life=None, conn=_C())
    assert same == flat, (same, flat)


def check_recency_moves_rates_toward_the_recent_games():
    """A pitcher who changed must read closer to what he is doing now.

    Built so the two halves disagree sharply: recent starts are all
    strikeouts, older ones almost none. Weighted, the rate has to sit above
    the flat pool.
    """
    from src.context.sources import rates as R
    lg = {"k_pct": 0.22, "bb_pct": 0.078, "hr_pct": 0.033, "babip": 0.29}
    rows = ([{"name": "A", "date": "2026-08-20", "o": 18, "h": 3, "bb": 1,
              "k": 12, "hr": 0, "apps": 1}] * 5
            + [{"name": "A", "date": "2026-05-01", "o": 18, "h": 6, "bb": 3,
                "k": 1, "hr": 1, "apps": 1}] * 5)

    class _C:
        def execute(self, *_):
            return _Rows(rows)
    flat = R.pitcher_rates(lg, conn=_C())["A"]["k_pct"]
    rec = R.pitcher_rates_recent(lg, half_life=14, conn=_C())["A"]["k_pct"]
    assert rec > flat + 0.02, (flat, rec)


def check_recency_shrinks_on_the_effective_sample():
    """Discounting the evidence must also discount the confidence.

    Weighting the numerator while shrinking on the RAW batters faced would
    keep full-season confidence behind a fraction of the data, which turns a
    recency filter into an overreaction to one bad outing. The effective
    sample must be smaller than the raw one whenever any game is discounted.
    """
    from src.context.sources import rates as R
    lg = {"k_pct": 0.22, "bb_pct": 0.078, "hr_pct": 0.033, "babip": 0.29}
    rows = [{"name": "A", "date": "2026-08-20", "o": 18, "h": 4, "bb": 2,
             "k": 8, "hr": 1, "apps": 1},
            {"name": "A", "date": "2026-05-01", "o": 18, "h": 4, "bb": 2,
             "k": 8, "hr": 1, "apps": 1}]

    class _C:
        def execute(self, *_):
            return _Rows(rows)
    got = R.pitcher_rates_recent(lg, half_life=14, conn=_C())["A"]
    assert got["eff_pa"] < got["pa"], (got["eff_pa"], got["pa"])


def check_recency_ages_from_the_window_not_from_today():
    """Scoring a July date must not discount July as stale.

    Measuring age from the wall clock would make every backtest weaker than
    production, and the further back the window the worse it gets — the kind
    of bug that shows up as "the model used to be better".
    """
    from src.context.sources import rates as R
    lg = {"k_pct": 0.22, "bb_pct": 0.078, "hr_pct": 0.033, "babip": 0.29}
    old = [{"name": "A", "date": "2020-04-10", "o": 18, "h": 3, "bb": 1,
            "k": 12, "hr": 0, "apps": 1},
           {"name": "A", "date": "2020-04-08", "o": 18, "h": 3, "bb": 1,
            "k": 12, "hr": 0, "apps": 1}]

    class _C:
        def execute(self, *_):
            return _Rows(old)
    got = R.pitcher_rates_recent(lg, half_life=14, conn=_C())["A"]
    # Two games two days apart in 2020: neither is stale RELATIVE TO THE
    # OTHER, so the effective sample must be close to the raw one.
    assert got["eff_pa"] > got["pa"] * 0.9, (got["eff_pa"], got["pa"])


def check_every_grid_contains_its_own_shipped_value():
    """A grid missing its incumbent freezes that parameter silently.

    `scan` finds the incumbent by exact value; if it is absent, `cur` is None
    and `take` can never fire. The parameter burns a full scan every sweep
    and reports "no move", which is indistinguishable in the output from a
    real null. WP_PB_RATE did exactly this for two runs after its value was
    corrected to 0.0155 and its grid was not.
    """
    fitf5.check_grids()          # raises if any grid omits its incumbent


def check_check_grids_actually_catches_a_missing_incumbent():
    """The guard has to fire, not just exist."""
    real = fitf5.GRID["WP_PB_RATE"]
    fitf5.GRID["WP_PB_RATE"] = [0.99, 0.98]
    try:
        fitf5.check_grids()
    except ValueError:
        return
    finally:
        fitf5.GRID["WP_PB_RATE"] = real
    raise AssertionError("a grid missing its incumbent was accepted")


def check_league_baselines_respect_the_cutoff():
    """The league baseline is training data and must honour `before`.

    log5 returns the league value whenever both sides are average, so this
    anchors every simulated rate. Computing it over all cached games let the
    test window into a fit labelled train-only — quiet leakage, because the
    obvious knob (player rates) was set correctly.
    """
    full = sim.league()
    early = sim.league(before="2026-06-01")
    assert full["bb_pct"] != early["bb_pct"], (full["bb_pct"],
                                               early["bb_pct"])
    assert full["k_pct"] != early["k_pct"]


def check_league_cache_is_keyed_on_the_cutoff():
    """Keyed on season alone, the FIRST caller fixed the baselines for the
    whole process — so a train-only fit running after any full-season call
    silently got full-season numbers, with no error and no clue."""
    a = sim.league(before="2026-06-01")
    b = sim.league()
    c = sim.league(before="2026-06-01")
    assert a["bb_pct"] == c["bb_pct"], "cutoff result was clobbered"
    assert a["bb_pct"] != b["bb_pct"], "cutoff had no effect"


def check_build_cases_passes_the_cutoff_to_the_league():
    """Guards the wiring. The league can honour `before` and still never be
    told about it, which looks identical from the outside."""
    import inspect
    src = inspect.getsource(cal.build_cases)
    assert "sim.league(rs, before=rb)" in src, src[:200]
    # `rs` is the rates season, which defaults to `season` but can be set
    # apart from it — 2026 starts priced off rates that remember 2025. The
    # league baseline has to follow the RATES, not the starts, or the anchor
    # and the numbers log5'd against it come from different populations.
    assert "rs = season if rates_season is _SAME_SEASON else rates_season" \
        in src


def check_worker_state_crosses_the_fork():
    """A flag set in the parent must be honoured inside the salt workers.

    `losses` fans its salts out to processes. Python defaults to SPAWN on
    macOS, and a spawned child re-imports every module at its DEFAULT global
    state — so `sim.USE_TTO` and every other switch would silently revert
    inside the workers. The search would then score every candidate under
    default rules and return a flat surface, which reads exactly like "this
    parameter does not matter". `rules()` raises on unknown names to prevent
    that same failure arriving through a typo; this prevents it arriving
    through a process boundary.

    Toggling a flag that genuinely changes the simulation MUST change the
    loss vector. If it does not, the workers are not seeing the parent.
    """
    cases = _pair(2, game="A") + _pair(3, game="B", seed=9)
    lg = dict(LG)
    orig = sim.USE_TTO
    try:
        sim.USE_TTO = False
        off = fitf5.losses(cases, None, 12, lg, salts=(0, 7919))
        sim.USE_TTO = True
        on = fitf5.losses(cases, None, 12, lg, salts=(0, 7919))
    finally:
        sim.USE_TTO = orig
    assert off != on, (off, on)


def check_the_salt_fan_out_agrees_with_running_it_serially():
    """Parallel must be a pure speedup, not a different answer."""
    cases = _pair(2, game="A") + _pair(1, game="C", seed=21)
    lg = dict(LG)
    salts = (0, 7919, 15013)
    orig = fitf5.PARALLEL_WORKERS
    try:
        fitf5.PARALLEL_WORKERS = 1
        serial = fitf5.losses(cases, None, 10, lg, salts=salts)
        fitf5.PARALLEL_WORKERS = 3
        par = fitf5.losses(cases, None, 10, lg, salts=salts)
    finally:
        fitf5.PARALLEL_WORKERS = orig
    assert serial == par, (serial, par)
