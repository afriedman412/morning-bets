"""Checks for the measured relief-outing length.

Offline: every check builds its own outings, so the DB is never opened.

The finding this module exists to carry is that the continuation hazard is
conditioned on the state the reliever ENTERED in — 20% of arms handed a
clean inning come back out against 63% of those brought in with two down —
so a single pooled constant cannot represent both. What gets pinned here is
that conditioning, because a regression to one pooled number would still
produce a plausible mean outing length and a plausible mean is exactly what
would get believed.
"""
from __future__ import annotations

from src.context import relief


def _o(entry_inning=7, entry_outs=0, last_inning=7, outs_recorded=3, **kw):
    d = {"entry_inning": entry_inning, "entry_outs": entry_outs,
         "last_inning": last_inning, "outs_recorded": outs_recorded,
         "on_1b": 0, "on_2b": 0, "on_3b": 0, "entry_margin": 1}
    d.update(kw)
    return d


def check_continuation_rises_with_the_out_count_at_entry():
    """The whole finding: entry state decides how long he stays.

    An arm brought in for one out has not finished his job when the inning
    ends; an arm handed a clean inning has. If this ever flattens, the
    mechanism has been replaced by a pooled constant and the module is not
    doing what it claims.
    """
    clean = relief.continues(0, 0)
    one = relief.continues(1, 0)
    two = relief.continues(2, 0)
    assert clean < one < two, (clean, one, two)
    # and not trivially: the spread is the point, so it must be a big one.
    assert two - clean > 0.30, (clean, two)


def check_extra_innings_use_the_extra_table_not_the_entry_table():
    """Once he is past the inning he entered, `entry_outs` stops deciding.

    The easy regression is to keep indexing the entry table forever, which
    would make a two-out entry immortal — 63% per inning, compounding.
    """
    for entry_outs in (0, 1, 2):
        got = relief.continues(entry_outs, 1)
        assert got == relief.CONTINUE_AFTER_EXTRA[1], (entry_outs, got)


def check_a_long_outing_falls_back_to_the_tail_rate():
    """Beyond the measured span the sample is too thin to condition on."""
    assert relief.continues(0, 99) == relief.CONTINUE_TAIL


def check_an_out_of_range_entry_count_does_not_raise():
    """`entry_outs` arrives from a live frame, so it must be clamped.

    Three outs ends the inning, but a defensive clamp is cheaper than a
    KeyError in the middle of a 1,500-game pricing run.
    """
    assert 0.0 <= relief.continues(3, 0) <= 1.0
    assert 0.0 <= relief.continues(-1, 0) <= 1.0


def check_tally_counts_a_continuation_by_the_innings_spanned():
    """`last_inning > entry_inning` is the definition, not `outs_recorded`.

    A reliever who records four outs may have done it inside one inning
    after an error, and one who records two may still have appeared in two
    innings. Counting outs instead of innings would answer a different
    question and would look just as reasonable.

    The rows that separate the definitions have to DISAGREE, or the check
    passes under either one — the first version of this test built three
    rows on which both counts returned 1 of 3 and it caught nothing.
    """
    rows = [
        # Finished the 7th, faced one man in the 8th, pulled: spans two
        # innings on three outs. Counting outs would call this no
        # continuation.
        _o(entry_inning=7, last_inning=8, outs_recorded=3),
        _o(entry_inning=7, last_inning=8, outs_recorded=3),
        # Four outs inside one inning after a dropped third strike.
        # Counting outs would call this a continuation.
        _o(entry_inning=7, last_inning=7, outs_recorded=4),
    ]
    t = relief.tally(rows)
    rate, cont, n = t["entry"][0]
    assert (cont, n) == (2, 3), (cont, n)
    assert abs(rate - 2 / 3) < 1e-9, rate


def check_tally_separates_the_entry_states():
    """Pooling the three entry states is the bug the module exists to fix."""
    rows = ([_o(entry_outs=0, last_inning=7)] * 4
            + [_o(entry_outs=2, entry_inning=7, last_inning=8)] * 4)
    t = relief.tally(rows)
    assert t["entry"][0][0] == 0.0, t["entry"][0]
    assert t["entry"][2][0] == 1.0, t["entry"][2]


def check_mid_inning_entry_counts_runners_as_well_as_outs():
    """A starter pulled after a leadoff walk hands over 0 outs and a runner.

    Counting only `entry_outs > 0` calls that a clean inning and understates
    mid-inning entries — 26.5% against the real 30.4%.
    """
    rows = [_o(entry_outs=0, on_1b=1), _o(entry_outs=0), _o(entry_outs=2),
            _o(entry_outs=0)]
    t = relief.tally(rows)
    assert abs(t["mid_inning"] - 0.5) < 1e-9, t["mid_inning"]


def check_a_just_arrived_reliever_is_nearly_immune():
    """The "not pulled in the same breath he arrived" rule is MEASURED, not
    hard-coded — 1.5% over his first two batters against a 14.1% peak once
    he has faced the men he came in for.

    `game.py` used to encode that protection as a flat rule and could then
    never pull a reliever at all. The shape has to live in the table.
    """
    fresh = relief.mid_removal(0, 0)
    settled = relief.mid_removal(2, 4)
    assert fresh < settled / 4, (fresh, settled)


def check_the_removal_hazard_is_not_monotone_in_batters_faced():
    """It peaks and then falls: the arms still out there after nine batters
    are the ones handling it. A monotone curve would be a modelling
    assumption, and the league does not have one."""
    peak = relief.mid_removal(0, 4)
    late = relief.mid_removal(0, 12)
    assert peak > late, (peak, late)


def check_removal_inputs_are_clamped():
    """`runs` and `batters` arrive from a live line and must not raise."""
    assert 0.0 <= relief.mid_removal(99, 99) <= 1.0
    assert 0.0 <= relief.mid_removal(-1, -1) <= 1.0
