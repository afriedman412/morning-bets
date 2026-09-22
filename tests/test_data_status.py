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
    """The four deleted on 2026-09-09 must stay named, so a reinstall shows.

    INVERTED TWICE NOW. There was no scheduler, so absence was correct;
    since 2026-09-20 `backfill` and `hourly` ARE supposed to run, so for
    those two absence is the failure. A name in neither tuple is a stray.
    Emptying either tuple makes one of the three undetectable.
    """
    for j in ("com.morningbets.grade", "com.morningbets.process",
              "com.morningbets.discover", "com.morningbets.context"):
        assert j in ds.RETIRED, j
    for j in ("com.morningbets.backfill", "com.morningbets.hourly"):
        assert j in ds.EXPECTED, j
    out = ds.job_health()
    assert isinstance(out, list)
    for name, state, kind in out:
        assert name.startswith("com.morningbets."), name
        assert kind in ("expected", "retired", "unknown"), (name, kind)
        assert isinstance(state, str) and state, (name, state)


def check_every_expected_job_is_reported_loaded_or_not():
    """A MISSING expected job is the new silent failure and must appear.

    Reporting only what is loaded — the old behaviour — would let the
    hourly pull fall over and say nothing, while the page went on serving
    the last board it got as though it were current.
    """
    named = {n for n, _, k in ds.job_health() if k == "expected"}
    assert named == set(ds.EXPECTED), named


def check_a_stray_job_is_flagged_even_under_an_undeclared_name():
    """Matched by PREFIX, not against a list of four literals.

    The old check compared `parts[2] in JOBS`, so a stray plist under any
    name nobody had thought of was invisible — which is the hole the
    guard existed to close.
    """
    rows = ds._classify_jobs({"com.morningbets.somethingelse": "running"})
    kinds = {n: k for n, _, k in rows}
    assert kinds["com.morningbets.somethingelse"] == "unknown", kinds
    assert kinds["com.morningbets.grade"] == "retired" \
        if "com.morningbets.grade" in kinds else True
    # and the expected pair is still reported, here as absent
    missing = [s for n, s, k in rows if k == "expected"]
    assert missing == ["NOT LOADED", "NOT LOADED"], missing


def check_a_row_without_a_reading_is_not_reported_as_current():
    """The weather bug's detector: `_last_useful_date` must ignore rows
    whose content column is NULL.

    WHAT IT WOULD HAVE CAUGHT. `mlb_weather` held rows for 2026-09-07,
    -08 and -09 with `temp_f` NULL on all 41 — written pregame, before
    statsapi populates the forecast — and every freshness check keyed on
    MAX(date), so the table reported a 0-day lag for four days while
    `TEMP_HR_MULT` and `WIND_HR_MULT` contributed exactly 1.0 to every
    game. A ROW IS NOT A READING, and this is the only check in the
    project that knows the difference.
    """
    import sqlite3
    from scratchpad import data_status as ds
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("create table w (date text, temp_f integer)")
    c.executemany("insert into w values (?,?)",
                  [("2026-09-05", 77), ("2026-09-06", 81),
                   ("2026-09-07", None), ("2026-09-08", None),
                   ("2026-09-09", None)])
    assert ds._max_date(c, "w") == "2026-09-09"
    got = ds._last_useful_date(c, "w", "temp_f")
    assert got == "2026-09-06", \
        f"content date should ignore the null rows, got {got!r}"
    # And the two together are what the report shows: the table looks
    # current on rows and is three days behind on readings.
    assert ds.assess(ds._max_date(c, "w"), "2026-09-09")[0] == "ok"
    assert ds.assess(got, "2026-09-09")[0] == "STALE"


def check_a_loaded_job_that_exits_nonzero_is_a_failure():
    """LOADED IS NOT RUNNING AND RUNNING IS NOT SUCCEEDING.

    The 2026-09-09 death in one line: three jobs exited 1 every day into
    a log nobody read, while anything that looked only at whether they
    existed said the pipeline was fine. Reproduced 2026-09-20 — `hourly`
    came back `last exit 126` (macOS refusing a launchd agent access to
    ~/Documents) and the first cut of the report printed it as a status
    line, not a problem.
    """
    rows = ds._classify_jobs({"com.morningbets.hourly": "last exit 126",
                              "com.morningbets.backfill": "last exit 0"})
    state = {n: s for n, s, _ in rows}
    assert state["com.morningbets.hourly"] == "last exit 126"

    # `job_is_bad` is the SHIPPED predicate, not a copy of it here — a
    # test that reimplements the rule passes happily while the printed
    # report says the opposite.
    flagged = {n for n, s, k in rows if ds.job_is_bad(s, k)}
    assert flagged == {"com.morningbets.hourly"}, flagged
    # and a running job is not flagged just for being present
    ok = ds._classify_jobs({"com.morningbets.hourly": "running",
                            "com.morningbets.backfill": "last exit 0"})
    assert not {n for n, s, k in ok if ds.job_is_bad(s, k)}
    # a missing one, and a stray, are both findings too
    assert ds.job_is_bad("NOT LOADED", "expected")
    assert ds.job_is_bad("running", "unknown")
    assert ds.job_is_bad("running", "retired")


def check_a_file_sidecar_is_read_for_freshness_like_a_table():
    """A SHIPPED INPUT THAT LIVES IN A FILE STILL HAS TO BE REPORTED.

    Found 2026-09-22 from the other end: `velo_starts.json` had stopped
    at a pitcher's 09-11 start while every table in the report read 0d,
    so the K and BB kicks on the live board were a start behind and
    nothing anywhere said so. It is not in `context.db`, so the
    MAX(date) machinery could not see it at all.

    The two sidecars go through one reader, and an unreadable file
    returns None rather than raising — `assess(None, ...)` is already the
    loudest status there is, and a report that dies on a corrupt JSON
    tells you less than one that prints `(empty)`.
    """
    import json as _json
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = f"{d}/rows.json"
        with open(p, "w") as fh:
            _json.dump([{"name": "A", "date": "2026-09-11"},
                        {"name": "B", "date": "2026-09-16"},
                        {"name": "C"}], fh)          # a row with no date
        assert ds._json_max_date(p) == "2026-09-16"

        # STALE IS THE CASE THAT BOUGHT THIS CHECK: the newest row trails
        # the newest finished game and the report has to say so.
        assert ds.assess("2026-09-16", "2026-09-20")[0] != "ok"
        assert ds.assess("2026-09-20", "2026-09-20")[0] == "ok"

        # missing, unparseable, and empty are all None, never a crash
        assert ds._json_max_date(f"{d}/nope.json") is None
        with open(f"{d}/bad.json", "w") as fh:
            fh.write("{not json")
        assert ds._json_max_date(f"{d}/bad.json") is None
        with open(f"{d}/empty.json", "w") as fh:
            _json.dump([], fh)
        assert ds._json_max_date(f"{d}/empty.json") is None

    # and the velo table is actually WIRED INTO the report — the reader
    # existing is not the same as `collect` calling it.
    names = [n for n, _ in ds.collect()["sources"]]
    assert any("velo" in n for n in names), names
