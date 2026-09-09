"""Checks for the data freshness report.

The staleness ARITHMETIC is tested rather than the database contents: what
is in the tables changes every night, and a check that asserted a
particular max date would fail for the one reason that is not a defect.
"""
from scratchpad import data_status as ds


def check_an_empty_source_is_not_reported_as_current():
    """`None` must read EMPTY, never a lag of zero.

    THE BUG THIS GUARDS is the whole reason the module exists: a source
    that never loaded and a source refreshed this morning must not print
    the same thing. An earlier shape returned a bare integer and an empty
    table came out as lag 0, which is indistinguishable from perfect.
    """
    status, lag = ds.assess(None, "2026-09-08")
    assert status == "EMPTY", status
    assert lag is None, lag


def check_staleness_is_measured_against_the_newest_game_not_the_clock():
    """The reference is the last finished game.

    In February every source is months behind the wall clock and none of
    them is stale — there are no games. Measuring against the newest
    result is what makes the report readable out of season, and it is why
    `assess` takes `ref` rather than calling `date.today()`.
    """
    # Same data, two very different wall-clock days: identical verdict.
    assert ds.assess("2026-09-08", "2026-09-08")[0] == "ok"
    assert ds.assess("2026-02-01", "2026-02-01")[0] == "ok"


def check_the_budget_is_one_day_and_it_binds():
    """One day of slack, and the second day is stale.

    A source refreshed after last night's games is current, and a game
    finishing near midnight UTC can land a day late. Two days cannot be
    explained that way.
    """
    assert ds.assess("2026-09-07", "2026-09-08") == ("ok", 1)
    assert ds.assess("2026-09-06", "2026-09-08") == ("STALE", 2)
    # And the budget is a parameter, not a hardcode buried in the compare.
    assert ds.assess("2026-09-06", "2026-09-08", budget=2)[0] == "ok"


def check_a_returning_scheduled_job_would_be_noticed():
    """All four jobs were deleted on 2026-09-09; the names must survive.

    THE POINT IS INVERTED FROM WHAT IT WAS. There is no scheduler now, so
    absence is correct and `job_health` reports only what is actually
    loaded. Keeping the names is what lets the report notice one coming
    BACK — a plist reinstalled by hand would otherwise pull data on its
    own schedule while every session assumed nothing did, which is the
    silent drift this module exists to break.

    Emptying `JOBS` would make that undetectable and is what this guards.
    """
    for j in ("com.morningbets.grade", "com.morningbets.process",
              "com.morningbets.discover", "com.morningbets.context"):
        assert j in ds.JOBS, j
    # Only loaded jobs come back, and never a fabricated "not loaded" row —
    # that distinction is what makes a returning job visible.
    out = ds.job_health()
    assert isinstance(out, list)
    for name, state in out:
        assert name in ds.JOBS, name
        assert isinstance(state, str) and state, (name, state)
        assert state != "not loaded", \
            "job_health must report only what is loaded"
