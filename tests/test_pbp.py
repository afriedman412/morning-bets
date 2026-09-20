"""Checks for the play-by-play extractor.

Offline: every check builds its own `allPlays` fixture, so nothing here
touches statsapi or the cache directory the scrape writes to.

What is worth guarding is the STATE RECONSTRUCTION, not the arithmetic.
`stints` exists to answer "what did the manager see when he went to the
pen", and every way that answer goes wrong is silent — a lost baserunner,
a margin read one play late, or the two clubs' pitchers collapsed into one
sequence — so each of those gets a check that fails when the mechanism is
removed.
"""
from __future__ import annotations

import gzip
import json
import pathlib
import tempfile

from src.context.sources import pbp


def _r(rid, start, end, out=False):
    return {"movement": {"start": start, "originBase": start, "end": end,
                         "isOut": out},
            "details": {"runner": {"id": rid}}}


def _play(inning, top, pid, outs_after, away=0, home=0, runners=()):
    return {
        "about": {"inning": inning, "isTopInning": top,
                  "halfInning": "top" if top else "bottom"},
        "matchup": {"pitcher": {"id": pid, "fullName": f"P{pid}"}},
        "result": {"awayScore": away, "homeScore": home},
        "count": {"outs": outs_after},
        "runners": list(runners),
    }


def _stints(plays):
    return pbp.stints("mlb-test", {"allPlays": plays})


def check_a_scoring_runner_does_not_erase_the_batter():
    """The bug that reconstruction is for.

    A double that scores a man from second: statsapi lists the BATTER's
    record first, so applying records in sequence puts the batter on second
    and then the scoring runner's own record clears second on the way home.
    The double vanishes from the bases and nothing complains until a walk
    two batters later fails to load them.
    """
    bases = [False, True, False]              # man on second
    runs = pbp._apply([_r(1, None, "2B"), _r(2, "2B", "score")], bases)
    assert runs == 1, runs
    assert bases == [False, True, False], bases


def check_bases_reconstruct_a_full_inning():
    bases = [False, False, False]
    pbp._apply([_r(1, None, "1B")], bases)             # single
    pbp._apply([_r(2, None, "1B"), _r(1, "1B", "2B")], bases)
    pbp._apply([_r(3, None, "1B"), _r(2, "1B", "2B"),
                _r(1, "2B", "3B")], bases)             # loaded
    assert bases == [True, True, True], bases
    runs = pbp._apply([_r(4, None, "1B"), _r(3, "1B", "2B"),
                       _r(2, "2B", "3B"), _r(1, "3B", "score")], bases)
    assert runs == 1 and bases == [True, True, True], (runs, bases)


def check_a_runner_out_after_advancing_is_off_the_bases():
    """Two records for one runner — advance, then thrown out stretching.
    The LAST record that resolves him is the one that counts."""
    bases = [True, False, False]
    runs = pbp._apply([_r(1, "1B", "2B"), _r(1, "2B", None, out=True)], bases)
    assert runs == 0 and bases == [False, False, False], bases


def check_a_new_half_inning_resets_the_bases():
    plays = [_play(1, True, 10, 0, runners=[_r(1, None, "1B")]),
             _play(1, True, 10, 3),
             _play(1, False, 20, 0)]
    s = _stints(plays)
    home = next(x for x in s if x.side == "away")   # away club pitching
    assert home.bases == (False, False, False), home.bases


def check_the_two_sides_are_tracked_separately():
    """The naive extractor keeps one `seen` pitcher and emits a change every
    half-inning, because the pitcher legitimately alternates. Two starters
    over four halves must be two stints, not four."""
    plays = []
    for inn in (1, 2):
        plays.append(_play(inn, True, 10, 3))      # home club pitching
        plays.append(_play(inn, False, 20, 3))     # away club pitching
    s = _stints(plays)
    assert len(s) == 2, [(x.side, x.name) for x in s]
    assert {x.order for x in s} == {0}, [x.order for x in s]


def check_entry_margin_is_the_score_before_the_first_play():
    """A reliever who gives up a homer to his first batter did not walk into
    a one-run deficit. `result.awayScore/homeScore` are the score AFTER the
    play, so reading the margin off them charges the manager for a decision
    he could not have made."""
    plays = [
        _play(1, True, 10, 3, away=0, home=0),
        _play(2, True, 11, 0, away=1, home=0,      # new arm, leadoff homer
              runners=[_r(1, None, "score")]),
    ]
    s = _stints(plays)
    rel = next(x for x in s if x.order == 1)
    assert rel.margin == 0, rel.margin        # tied when he took the ball


def check_margin_is_signed_from_the_pitching_team():
    """Home up 3-1 is +2 for the home pitcher and -2 for the away one."""
    plays = [_play(5, True, 10, 3, away=1, home=3),
             _play(5, False, 20, 3, away=1, home=3),
             _play(6, True, 11, 3, away=1, home=3),
             _play(6, False, 21, 3, away=1, home=3)]
    s = _stints(plays)
    h = next(x for x in s if x.side == "home" and x.order == 1)
    a = next(x for x in s if x.side == "away" and x.order == 1)
    assert h.margin == 2, h.margin
    assert a.margin == -2, a.margin


def check_mid_inning_entry_carries_the_outs_and_the_runners():
    """The state at removal — the whole point of the scrape. A hook that
    fires with two on and one out is a different decision from one that
    fires between innings, and the boxscore cannot tell them apart."""
    plays = [
        _play(6, True, 10, 1),                                  # one out
        _play(6, True, 10, 1, runners=[_r(1, None, "1B")]),
        _play(6, True, 10, 1, runners=[_r(2, None, "1B"),
                                       _r(1, "1B", "2B")]),
        _play(6, True, 11, 2),                                  # change
    ]
    s = _stints(plays)
    rel = next(x for x in s if x.order == 1)
    assert rel.outs == 1, rel.outs
    assert rel.bases == (True, True, False), rel.bases
    assert rel.mid_inning_entry
    assert not s[0].mid_inning_entry


def check_outs_are_charged_to_the_pitcher_on_the_mound():
    plays = [_play(1, True, 10, 1), _play(1, True, 10, 2),
             _play(1, True, 11, 3)]
    s = _stints(plays)
    assert s[0].outs_recorded == 2, s[0].outs_recorded
    assert s[1].outs_recorded == 1, s[1].outs_recorded
    assert s[0].batters == 2 and s[1].batters == 1


def check_outs_reset_between_half_innings():
    """`count.outs` restarts at zero each half, so charging the difference
    against a running total that never reset would credit a pitcher with
    negative outs and silently drop them."""
    plays = [_play(1, True, 10, 3), _play(2, True, 10, 1),
             _play(2, True, 10, 3)]
    s = _stints(plays)
    assert s[0].outs_recorded == 6, s[0].outs_recorded


def check_men_on_categories_match_statsapi():
    assert pbp.men_on((False, False, False)) == "Empty"
    assert pbp.men_on((True, False, False)) == "Men_On"
    assert pbp.men_on((False, True, False)) == "RISP"
    assert pbp.men_on((True, False, True)) == "RISP"
    assert pbp.men_on((True, True, True)) == "Loaded"


def check_relief_flags_follow_the_appearance_order():
    plays = [_play(1, True, 10, 3), _play(2, True, 11, 3),
             _play(3, True, 12, 3)]
    s = _stints(plays)
    assert [x.relief for x in s] == [False, True, True]
    assert [x.innings for x in s] == [1, 1, 1]


def check_an_empty_payload_yields_nothing():
    assert pbp.stints("mlb-test", {}) == []
    assert pbp.stints("mlb-test", {"allPlays": []}) == []


def check_fetch_reads_the_cache_without_touching_the_network():
    """The scrape is ~185 MB and must never be repeated for a final game.
    Verified by pointing the cache at a temp dir with a payload no network
    call could have produced."""
    with tempfile.TemporaryDirectory() as d:
        old = pbp.CACHE
        pbp.CACHE = pathlib.Path(d)
        try:
            p = pbp.path("mlb-999")
            with gzip.open(p, "wb") as f:
                f.write(json.dumps({"allPlays": [_play(1, True, 7, 3)]})
                        .encode())
            assert pbp.have("mlb-999")
            got = pbp.fetch("mlb-999")
            assert got and got["allPlays"][0]["matchup"]["pitcher"]["id"] == 7
        finally:
            pbp.CACHE = old
