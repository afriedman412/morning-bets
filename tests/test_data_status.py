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


def check_every_scheduled_job_is_named_in_the_report():
    """`JOBS` must list every launchd job, including the dead ones.

    Dropping a job from this tuple once it starts failing is how the
    report would come to say ALL CURRENT while nothing was running —
    exactly the silence it exists to break. `com.morningbets.discover` and
    `com.morningbets.context` point at `src.main` and
    `src.context.snapshot`, both deleted with the betting layer, and they
    stay listed until they are repointed or unloaded.
    """
    assert "com.morningbets.discover" in ds.JOBS
    assert "com.morningbets.context" in ds.JOBS
    assert "com.morningbets.grade" in ds.JOBS
    # job_health never raises, even where launchctl does not exist — the
    # report has to work on a machine that is not this one.
    out = ds.job_health()
    assert isinstance(out, list)
    for name, state in out:
        assert name in ds.JOBS, name
        assert isinstance(state, str) and state, (name, state)
