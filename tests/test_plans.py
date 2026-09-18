"""Checks for the operator-announced pitching plans (`plans.py`).

Offline: every check writes its own JSON under a temp dir. The wiring that
carries a plan into `build_side` is guarded in `test_wiring.py`; what is
worth guarding HERE is the store itself — that a plan survives the
roundtrip, that clearing works, and that a hand-edited typo degrades to
"no plans" instead of taking the board down, all of which `probables`
already promises and this module must keep promising.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from src.context import plans


def _tmp():
    return Path(tempfile.mkdtemp()) / "plans.json"


def check_a_plan_survives_the_roundtrip():
    p = _tmp()
    plans.set_plan("2026-09-18", "cin", 9, "Brandon Williamson", path=p)
    got = plans.for_team("2026-09-18", "CIN", path=p)
    assert got == {"outs": 9, "bulk": "Brandon Williamson"}, got


def check_team_lookup_is_case_insensitive_both_ways():
    """The operator types `stl`, the schedule feed carries `STL` — a plan
    that silently misses on case would price the board unplanned with no
    warning anywhere. The stored-key half is exercised through a
    HAND-EDITED file (a lowercase key `set_plan` would have uppercased),
    because that is the file this module promises to tolerate."""
    p = _tmp()
    plans.set_plan("2026-09-18", "stl", "pool", path=p)
    assert plans.for_team("2026-09-18", "stl", path=p) is not None
    assert plans.for_team("2026-09-18", "STL", path=p) is not None
    p.write_text('{"2026-09-18": {"cin": {"outs": 9, "bulk": null}}}')
    assert plans.for_team("2026-09-18", "CIN", path=p) is not None


def check_outs_is_an_int_or_the_pool_sentinel_and_fails_at_entry():
    """`set_plan("...", "CIN", "nine")` must raise NOW, not surface as a
    mid-simulation crash on tonight's board."""
    p = _tmp()
    plans.set_plan("2026-09-18", "CIN", "9", path=p)  # str int coerces
    assert plans.for_team("2026-09-18", "CIN", path=p)["outs"] == 9
    try:
        plans.set_plan("2026-09-18", "CIN", "nine", path=p)
    except ValueError:
        return
    raise AssertionError("a non-integer plan was accepted")


def check_an_outs_range_roundtrips_and_a_backwards_one_fails():
    """`3-6` is "an inning or two" — stored as given; `6-3` is a typo."""
    p = _tmp()
    plans.set_plan("2026-09-18", "CLE", "3-6", path=p)
    assert plans.for_team("2026-09-18", "CLE", path=p)["outs"] == "3-6"
    try:
        plans.set_plan("2026-09-18", "CLE", "6-3", path=p)
    except ValueError:
        return
    raise AssertionError("a backwards range was accepted")


def check_no_bulk_arm_means_bulk_is_none_not_missing():
    """The majority case for real openers (48.5%) — the pen takes over.
    `build_side` keys on `bulk is None`, so the field must exist."""
    p = _tmp()
    plans.set_plan("2026-09-18", "CLE", "pool", path=p)
    got = plans.for_team("2026-09-18", "CLE", path=p)
    assert got["bulk"] is None, got


def check_clearing_a_plan_removes_it_and_reports_whether_it_existed():
    p = _tmp()
    plans.set_plan("2026-09-18", "CIN", 9, path=p)
    assert plans.clear_plan("2026-09-18", "CIN", path=p) is True
    assert plans.for_team("2026-09-18", "CIN", path=p) is None
    assert plans.clear_plan("2026-09-18", "CIN", path=p) is False


def check_a_plan_expires_with_its_date():
    """Yesterday's announcement must not reach tonight's board: the lookup
    is BY DATE, and a stored plan for another date returns nothing."""
    p = _tmp()
    plans.set_plan("2026-09-17", "CIN", 9, path=p)
    assert plans.for_team("2026-09-18", "CIN", path=p) is None


def check_a_hand_edited_typo_degrades_to_no_plans():
    """Same posture as `probables.load`: operator JSON, so a stray comma
    prices the board with no plans and says so, rather than raising."""
    p = _tmp()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json")
    assert plans.load(path=p) == {}
    assert plans.for_team("2026-09-18", "CIN", path=p) is None
