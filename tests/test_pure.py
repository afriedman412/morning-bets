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
from src.context import price
from src.context.sources import rates


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


# ── the shrinkage weight on a priced row ───────────────────────────────
#
# THE DEFECT THESE GUARD. On 2026-08-29 Blake Snell was priced off 85
# batters faced, which is 39% his own record and 61% shrink target, and he
# passed every existing filter — 4 starts, over MIN_BF, not an opener, not
# a swingman. The 19-point "edge" the board showed was our own shrinkage
# and nothing printed said so.
def check_shrink_weight_matches_the_constant_rates_actually_uses():
    """A COPY of 132 here is the failure mode, not the arithmetic.

    `STABILISE_MEASURED["pit"]["k_pct"]` moved 57 -> 132 on 2026-08-28. Any
    second home for that number goes stale silently and the column would
    then describe a shrink nobody applies.
    """
    k = rates.STABILISE_MEASURED["pit"]["k_pct"]
    assert rates.USE_MEASURED_STABILISE, "this check reads the measured path"
    for pa in (85, 311, 428, 600):
        assert abs(price.shrink_weight(pa) - pa / (pa + k)) < 1e-12, pa
    # Snell's actual line, and the number that should have been on screen.
    snell = price.shrink_weight(85)
    assert abs(snell - 0.3917) < 5e-4, snell


def check_shrink_weight_is_zero_for_a_pitcher_with_no_record():
    """None and 0 must not divide, and must not read as 'all his own'."""
    assert price.shrink_weight(None) == 0.0
    assert price.shrink_weight(0) == 0.0


def check_the_thin_bar_is_above_what_min_bf_admits():
    """The gate and the flag have to disagree or the flag is decorative.

    `MIN_BF` is 80 batters faced, which is a weight of 0.38 — so the
    existing filter admits arms that are mostly shrink target by
    construction. If THIN_WEIGHT ever drops below that, every row the gate
    lets through is unmarked and this column stops carrying information.
    """
    at_the_gate = price.shrink_weight(price.MIN_BF)
    assert at_the_gate < price.THIN_WEIGHT, (at_the_gate, price.THIN_WEIGHT)
    # And it must not be so high that a full season is flagged: a starter
    # with 600 batters faced is 82% his own and is not a thin-sample arm.
    assert price.shrink_weight(600) > price.THIN_WEIGHT


def check_a_thin_arm_is_marked_in_the_report():
    """The mark must reach the PRINTED row. A weight computed and not
    displayed is the same as no weight — that is exactly the state this
    replaced, where `pitcher_pa` was already on every row and never shown.
    """
    import io
    import contextlib
    rows = [{"stat": "k", "player": "Thin Arm", "line": 4.5, "ours": 0.30,
             "market": 0.49, "gap": -0.19, "se": 0.005, "z": -38.0,
             "opp": "MIL", "home": False, "confirmed_lineup": False,
             "pitcher_pa": 85, "shrink_w": price.shrink_weight(85)},
            {"stat": "k", "player": "Full Season", "line": 5.5, "ours": 0.52,
             "market": 0.50, "gap": 0.02, "se": 0.005, "z": 4.0,
             "opp": "TEX", "home": True, "confirmed_lineup": True,
             "pitcher_pa": 600, "shrink_w": price.shrink_weight(600)}]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        price.report(rows)
    out = buf.getvalue()
    assert "0.39*" in out, out
    assert "Thin Arm" in out and "85 BF" in out, out
    # The healthy arm must NOT be marked, or the flag says nothing.
    assert "0.82*" not in out, out
    assert "Full Season" not in out.split("arm(s) marked")[1], out
