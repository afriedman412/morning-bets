"""Pure-function checks: arithmetic, ordering, and boundary behaviour.

Nothing here touches the network or the database. These are the properties
that should hold by construction, as opposed to test_regressions.py, which
is a list of things that actually broke.
"""
from __future__ import annotations

import shutil

from src import parallel
from src.grading import _is_bettable_line, bounds_for
from src.context import gamestate, slate as slate_src
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


# ── empirical estimate ─────────────────────────────────────────────────


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
#
# The rule these guard survived the betting layer: `slate.simulate_slate_game`
# refuses a game that is not pregame, and it reads the SAME set. A stale
# number costs little; simulating a live game writes fiction nothing
# downstream can detect.
def check_started_games_are_not_pregame():
    for det in ("Final", "In Progress", "Game Over", "Suspended"):
        assert det not in gamestate.PREGAME_STATES


def check_pregame_states_pass():
    for det in ("Scheduled", "Pre-Game", "Warmup"):
        assert det in gamestate.PREGAME_STATES


def check_the_slate_refuses_a_live_game():
    """Verified by mutation: drop the guard and this is what fails."""
    import inspect
    src = inspect.getsource(slate_src.simulate_slate_game)
    assert "PREGAME_STATES" in src
    res, why = slate_src.simulate_slate_game(
        {"status": "In Progress"}, "2026-09-05", None, None, None, None, None)
    assert res is None and "never price a live one" in why


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
        assert abs(slate_src.shrink_weight(pa) - pa / (pa + k)) < 1e-12, pa
    # Snell's actual line, and the number that should have been on screen.
    snell = slate_src.shrink_weight(85)
    assert abs(snell - 0.3917) < 5e-4, snell


def check_shrink_weight_is_zero_for_a_pitcher_with_no_record():
    """None and 0 must not divide, and must not read as 'all his own'."""
    assert slate_src.shrink_weight(None) == 0.0
    assert slate_src.shrink_weight(0) == 0.0


def check_the_thin_bar_is_above_what_min_bf_admits():
    """The gate and the flag have to disagree or the flag is decorative.

    `MIN_BF` is 80 batters faced, which is a weight of 0.38 — so the
    existing filter admits arms that are mostly shrink target by
    construction. If THIN_WEIGHT ever drops below that, every row the gate
    lets through is unmarked and this column stops carrying information.
    """
    at_the_gate = slate_src.shrink_weight(slate_src.MIN_BF)
    assert at_the_gate < slate_src.THIN_WEIGHT, (at_the_gate, slate_src.THIN_WEIGHT)
    # And it must not be so high that a full season is flagged: a starter
    # with 600 batters faced is 82% his own and is not a thin-sample arm.
    assert slate_src.shrink_weight(600) > slate_src.THIN_WEIGHT
