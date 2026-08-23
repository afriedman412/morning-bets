"""Pure-function checks: arithmetic, ordering, and boundary behaviour.

Nothing here touches the network or the database. These are the properties
that should hold by construction, as opposed to test_regressions.py, which
is a list of things that actually broke.
"""
from __future__ import annotations

import shutil

from src import parallel
from src.context import estimate, snapshot
from src.context.movement import _is_pregame
from src.grading import _is_bettable_line, bounds_for
from src import kalshi


# ── parallel ───────────────────────────────────────────────────────────
def check_gather_preserves_input_order():
    """build_pool appends to `nominators` in iteration order and that list
    is rendered into the debate prompt, so completion order would make a
    given day irreproducible."""
    import time

    def work(n):
        time.sleep(0.05 * n)   # reverse of input order
        return n
    got = parallel.gather(work, [3, 2, 1])
    assert [item for item, _, _ in got] == [3, 2, 1]
    assert [res for _, res, _ in got] == [3, 2, 1]


def check_gather_returns_errors_instead_of_raising():
    """One persona's 500 must not cost the whole round."""
    def work(n):
        if n == 2:
            raise RuntimeError("boom")
        return n
    got = parallel.gather(work, [1, 2, 3])
    assert got[1][1] is None
    assert isinstance(got[1][2], RuntimeError)
    assert got[0][1] == 1 and got[2][1] == 3


def check_gather_handles_empty():
    assert parallel.gather(lambda x: x, []) == []


# ── odds arithmetic ────────────────────────────────────────────────────
def check_implied_prob_both_signs():
    assert abs(estimate.implied_prob(-110) - 0.5238) < 1e-3
    assert abs(estimate.implied_prob(+150) - 0.4000) < 1e-3
    assert estimate.implied_prob(None) is None


def check_fair_odds_roundtrips():
    for p in (0.25, 0.4, 0.5238, 0.75):
        o = estimate.fair_odds(p)
        assert abs(estimate.implied_prob(o) - p) < 0.01, (p, o)


def check_kalshi_american_matches_estimate():
    """Two modules convert probability to American odds; they must agree."""
    for p in (0.2, 0.45, 0.55, 0.8):
        assert kalshi.american(p) == estimate.fair_odds(p), p


# ── empirical estimate ─────────────────────────────────────────────────
def check_over_under_counts_the_right_side():
    d = estimate.over_under([10, 20, 20, 20, 20], 15.5, "over")
    assert d["hits"] == 4 and d["n"] == 5
    d = estimate.over_under([10, 20, 20, 20, 20], 15.5, "under")
    assert d["hits"] == 1


def check_pushes_are_excluded_not_counted_as_losses():
    """A result landing exactly on the line is a push; counting it as a
    loss understates every whole-number line."""
    d = estimate.over_under([15, 15, 20, 20, 10, 10], 15, "over")
    assert d["pushes"] == 2
    assert d["n"] == 4


def check_shrink_pulls_small_samples_off_the_extremes():
    """6-for-6 is not a certainty; without shrinkage a thin sample prints
    a huge edge."""
    d = estimate.over_under([20] * 6, 15.5, "over")
    assert d["raw_rate"] == 1.0
    assert 0.6 < d["p"] < 0.85, d["p"]


def check_estimate_declines_below_min_starts():
    assert estimate.over_under([20, 20, 20], 15.5, "over") is None


def check_bootstrap_is_deterministic_for_a_seed():
    a = estimate.bootstrap_p([15, 16, 16, 17, 14], 15.5, "over", seed=7)
    b = estimate.bootstrap_p([15, 16, 16, 17, 14], 15.5, "over", seed=7)
    assert a["mean"] == b["mean"] and a["p10"] == b["p10"]


def check_jitter_widens_the_distribution():
    """More injected noise must not narrow the spread."""
    tight = estimate.bootstrap_p([16] * 6, 15.5, "over", jitter=0.0)
    loose = estimate.bootstrap_p([16] * 6, 15.5, "over", jitter=3.0)
    assert (loose["p90"] - loose["p10"]) >= (tight["p90"] - tight["p10"])


# ── bounds ─────────────────────────────────────────────────────────────
def check_bettable_line_grid():
    assert all(_is_bettable_line(v) for v in (0.5, 1.0, 15.0, 17.5))
    assert not any(_is_bettable_line(v) for v in (1.55, 0.45, 2.25))


def check_combo_bounds_derive_from_components():
    """'h+r+rbi' is not enumerated; its ceiling is the sum of its parts, so
    any combo the extractor invents gets a bound for free."""
    assert bounds_for("h+r+rbi") is not None
    assert bounds_for("h+r+rbi")[1] > bounds_for("h")[1]
    assert bounds_for("nonsense+xyz") is None


# ── game state ─────────────────────────────────────────────────────────
def check_started_games_are_not_pregame():
    for st, det in (("Final", "Final"), ("Live", "In Progress")):
        assert _is_pregame({"status": st, "detailed_status": det}) is False


def check_pregame_states_pass():
    for det in ("Scheduled", "Pre-Game", "Warmup"):
        assert _is_pregame({"status": "Preview", "detailed_status": det})


def check_missing_game_is_not_pregame():
    """Unknown must resolve to 'do not price' — the cost of skipping a
    reprice is one stale number; pricing a live game is undetectable."""
    assert _is_pregame(None) is False


# ── snapshots ──────────────────────────────────────────────────────────
def check_snapshot_ordering_survives_same_second_writes():
    """Second-resolution timestamps collided and sorted arbitrarily, which
    reported a total moving 8.5->9.0 as 9.0->8.5."""
    d = "2099-01-02"
    try:
        for i, total in enumerate((8.5, 9.0, 9.5)):
            snapshot.save({
                "date": d, "context_version": 1, "assembled_at": str(i),
                "league": {}, "games": [{"matchup": "A @ B", "market": {
                    "total": {"over": {"line": total, "odds": -110},
                              "under": {"line": total, "odds": -110}}}}],
            })
        hs = snapshot.history(d)
        assert len(hs) == 3, len(hs)
        mv = snapshot.line_movement(d)["A @ B"]
        assert mv["moved"]["total"] == {"from": 8.5, "to": 9.5}, mv["moved"]
    finally:
        shutil.rmtree(snapshot.day_dir(d), ignore_errors=True)


def check_identical_snapshot_is_not_rewritten():
    d = "2099-01-03"
    snap = {"date": d, "context_version": 1, "assembled_at": "x",
            "league": {}, "games": []}
    try:
        assert snapshot.save(snap) is not None
        assert snapshot.save({**snap, "assembled_at": "later"}) is None
    finally:
        shutil.rmtree(snapshot.day_dir(d), ignore_errors=True)


def check_line_movement_needs_two_observations():
    """One snapshot yields moved={}, which reads as 'the line held' when it
    means 'we looked once'."""
    d = "2099-01-04"
    try:
        snapshot.save({"date": d, "context_version": 1, "assembled_at": "x",
                       "league": {}, "games": [{"matchup": "A @ B",
                       "market": {"total": {"over": {"line": 8.5,
                                                     "odds": -110}}}}]})
        assert snapshot.line_movement(d) == {}
    finally:
        shutil.rmtree(snapshot.day_dir(d), ignore_errors=True)


# ── kalshi helpers ─────────────────────────────────────────────────────
def check_ticker_date_parses_and_rejects_junk():
    assert kalshi.ticker_date(
        "KXMLBOUTS-26AUG221910NYMCWS-CWSL-18") == "2026-08-22"
    assert kalshi.ticker_date("garbage") is None
    assert kalshi.ticker_date("") is None


def check_threshold_for_line():
    assert kalshi.threshold_for(15.5) == 16
    assert kalshi.threshold_for(0.5) == 1
