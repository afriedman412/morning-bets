"""Checks for the arm interpreter, `src.context.arm`.

The queries run against a REAL in-memory sqlite, not a stub that returns
canned rows whatever the SQL says — the whole point of two of these
checks is the literal inside the SQL.
"""
import sqlite3

from src.context import arm


def _mem():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("create table mlb_stints"
                " (pitcher_id int, player_name text, date text,"
                "  appearance_order int)")
    return con


def check_the_start_is_appearance_order_zero():
    """`appearance_order` is 0-INDEXED and the start is order 0.

    THE BUG THIS GUARDS shipped twice in one session: a `=1` filter
    counts SECOND pitchers, which read Wesneski (8-for-8 starts in 2026)
    as an opener-and-bulk arm and reversed the verdict on his swingman
    flag. One start and one relief appearance must count as exactly one
    start.
    """
    con = _mem()
    # TWO starts and ONE second-pitcher row, deliberately asymmetric: a
    # fixture with one of each counts 1 under either indexing and the
    # check guards nothing (which is how this check first shipped).
    con.executemany(
        "insert into mlb_stints values (?,?,?,?)",
        [(7, "A Starter", "2026-05-01", 0),
         (7, "A Starter", "2026-05-07", 0),
         (7, "A Starter", "2026-05-12", 1)])
    assert arm.starts_by_season(con, 7) == [("2026", 2, 3)]


def check_a_name_collision_never_guesses():
    """Two Sandlins, no exact ask -> nothing; an exact ask -> that one.

    Nick Sandlin's 2023 relief seasons were once merged into David
    Sandlin's record by a bare LIKE. Substring convenience stays, but
    only when it cannot be wrong.
    """
    two = [(1, "Nick Sandlin"), (2, "David Sandlin")]
    assert arm.resolve_name(two, "Sandlin") is None
    assert arm.resolve_name(two, "david sandlin") == (2, "David Sandlin")
    # A lone substring match is unambiguous and resolves.
    assert arm.resolve_name([(3, "Robert Gasser")], "Gasser") == \
        (3, "Robert Gasser")
    assert arm.resolve_name([], "Nobody") is None


def check_the_binomial_tail_is_a_binomial_tail():
    """P(over n.5) must complement the cdf it is built from.

    Hand value: X ~ B(2, 0.5), P(X <= 1) = 0.75. And the TONIGHT block
    reads `1 - cdf(ln)` as P(K >= ln+1), so cdf must be INCLUSIVE of its
    argument — an off-by-one here shifts every printed line by a whole
    strikeout.
    """
    assert abs(arm._binom_cdf(1, 2, 0.5) - 0.75) < 1e-12
    assert abs(arm._binom_cdf(2, 2, 0.5) - 1.0) < 1e-12
    # Inclusive: P(X <= 0) at p=0 is 1 — the zero outcome is counted.
    assert abs(arm._binom_cdf(0, 5, 0.0) - 1.0) < 1e-12
