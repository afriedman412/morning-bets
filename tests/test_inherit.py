"""Checks for the inherited-runner measurement.

Offline: every check builds its own play-by-play, so the PBP cache is never
opened.

The measurement follows SPECIFIC RUNNER IDS across a pitching change, and
every way of getting that wrong still produces a plausible ~0.33. Counting
runs scored after the change credits the reliever's own baserunners to the
starter; forgetting to flush at the half-inning end silently scores everyone
who was stranded; treating an inning-start change as a handover invents
inherited runners out of nothing. Those are what get pinned.
"""
from __future__ import annotations

from src.context import inherit


def _mv(rid, start, end, is_out=False):
    return {"details": {"runner": {"id": rid}},
            "movement": {"start": start, "end": end, "isOut": is_out}}


def _play(pitcher, outs_after, runners=(), inning=7, top=True):
    return {"about": {"inning": inning, "halfInning": "top" if top else "bot",
                      "isTopInning": top},
            "matchup": {"pitcher": {"id": pitcher}},
            "count": {"outs": outs_after},
            "runners": list(runners)}


def _run(plays):
    return inherit._handovers("fake", {"allPlays": plays})


def check_an_inherited_runner_who_scores_is_keyed_to_his_base_and_the_outs():
    """The cell the simulator needs is (base, outs at handover)."""
    plays = [
        # Starter puts a man on second with one out.
        _play(1, 1, [_mv(100, None, "2B")]),
        # New pitcher: 100 is inherited from 2B with 1 out.
        _play(2, 1, [_mv(101, None, "1B")]),
        # 100 scores.
        _play(2, 1, [_mv(100, "2B", "score")]),
    ]
    got = _run(plays)
    assert ("2B", 1, True) in got, got


def check_a_stranded_inherited_runner_counts_as_not_scoring():
    """The half-inning ending is what resolves him, and it must resolve him
    THERE rather than at the end of the game.

    A trailing flush alone produces the same tuple for a single half-inning,
    so that cannot be what this pins. The discriminating case is a player who
    bats again later: left pending across the inning boundary, his second
    trip reaches base and scores, and a runner who was stranded is recorded
    as an inherited run.
    """
    plays = [
        _play(1, 1, [_mv(100, None, "1B")]),
        _play(2, 2, []),
        _play(2, 3, []),
        # Same player bats again two half-innings later and scores.
        _play(3, 0, [], inning=7, top=False),
        _play(4, 0, [_mv(100, None, "1B")], inning=8),
        _play(4, 0, [_mv(100, "1B", "score")], inning=8),
        _play(4, 3, [], inning=8),
    ]
    got = _run(plays)
    assert got == [("1B", 1, False)], got


def check_the_relievers_own_baserunners_are_not_inherited():
    """A man who reaches AFTER the change belongs to the new pitcher.

    Counting runs scored after a handover rather than tracking runner ids
    is the natural shortcut and it charges the starter for the reliever's
    own mistakes.
    """
    plays = [
        _play(1, 1, [_mv(100, None, "1B")]),
        _play(2, 1, [_mv(101, None, "1B")]),      # reliever's own man
        _play(2, 1, [_mv(101, "1B", "score")]),
        _play(2, 3, []),
        _play(3, 0, [], top=False),
    ]
    got = _run(plays)
    assert ("1B", 1, True) not in got, got
    assert ("1B", 1, False) in got, got          # 100 was stranded
    assert len(got) == 1, got


def check_an_inning_start_change_inherits_nobody():
    """Bases empty at the change means there is nothing to inherit.

    NOTE: the `and occupant` guard in `_handovers` is defensive rather than
    load-bearing — iterating an empty occupancy map already yields nothing,
    so removing it changes no behaviour and this check cannot detect it.
    What it does pin is the end-to-end result: a fresh inning with a new
    pitcher contributes no rows.
    """
    plays = [
        _play(1, 3, []),
        _play(2, 0, [_mv(100, None, "1B")], inning=8),
        _play(2, 0, [_mv(100, "1B", "score")], inning=8),
        _play(2, 3, [], inning=8),
    ]
    assert _run(plays) == [], _run(plays)


def check_every_runner_on_base_at_a_handover_is_recorded_on_his_own_base():
    """Bases loaded hands over three men, on three different bases.

    Recording a COUNT of inherited runners instead of a base for each is the
    shortcut that makes the flat 0.33 look defensible — it is exactly the
    information that shows 1B with two out (0.127) and 3B with none (0.771)
    are not the same bet.
    """
    plays = [
        _play(1, 1, [_mv(100, None, "1B")]),
        _play(1, 1, [_mv(100, "1B", "2B"), _mv(101, None, "1B")]),
        _play(1, 1, [_mv(100, "2B", "3B"), _mv(101, "1B", "2B"),
                     _mv(102, None, "1B")]),
        _play(2, 1, []),                      # handover, bases loaded, 1 out
        _play(2, 3, []),
        _play(3, 0, [], top=False),
    ]
    got = sorted(_run(plays))
    assert got == [("1B", 1, False), ("2B", 1, False), ("3B", 1, False)], got


def check_a_runner_who_advanced_is_inherited_on_his_CURRENT_base_only():
    """Vacate every mover before placing them, or he is inherited twice.

    A man simply advancing does NOT expose this — `pending` is keyed on
    runner id, so a stale duplicate of the same man is overwritten and the
    bug hides. It bites when a runner leaves a base nobody refills: here he
    scores from first on a double, and without the vacate pass first base
    still points at him, handing the reliever a phantom runner who is
    already home.
    """
    plays = [
        _play(1, 1, [_mv(100, None, "1B")]),
        _play(1, 1, [_mv(100, "1B", "score"), _mv(101, None, "2B")]),
        _play(2, 1, []),                      # handover: one man, on second
        _play(2, 3, []),
        _play(3, 0, [], top=False),
    ]
    got = _run(plays)
    assert got == [("2B", 1, False)], got


def check_a_runner_thrown_out_on_the_bases_did_not_score():
    """He resolves at the moment he is out, not at the half-inning flush."""
    plays = [
        _play(1, 0, [_mv(100, None, "2B")]),
        _play(2, 1, [_mv(101, None, "1B")]),
        _play(2, 2, [_mv(100, "2B", "3B", is_out=True)]),
        _play(2, 3, []),
        _play(3, 0, [], top=False),
    ]
    got = _run(plays)
    # The handover happens BEFORE any out is recorded, so the key is 0.
    assert ("2B", 0, False) in got, got
    assert not any(scored for _b, _o, scored in got), got


def check_a_runner_inherited_twice_is_counted_once():
    """Two changes in one inning must not double-count the same man.

    He is re-keyed to the LATEST handover, because the quantity being
    measured is P(scores | the state the incoming pitcher walked into) and
    that is the state `sim._pull_mid_inning` is asking about. Counting him
    once per change would inflate the denominator with the same runner.
    """
    plays = [
        _play(1, 0, [_mv(100, None, "2B")]),
        _play(2, 1, []),                      # first handover, 0 -> 1 out
        _play(3, 2, []),                      # second handover, at 1 out
        _play(3, 3, []),
        _play(4, 0, [], top=False),
    ]
    got = _run(plays)
    assert len(got) == 1, got
    assert got[0][:2] == ("2B", 1), got
