"""Checks for the deployment measurement.

Offline: every check builds its own outings, so the DB is never opened.

The measurement's whole claim is that a reliever's role can be projected
from games ALREADY PLAYED. That claim lives entirely in how the split-half
is constructed — chronological, per pitcher, with a floor on sample size —
so those are what get pinned. A split-half that quietly sorted or pooled
would still return a plausible correlation, and a plausible correlation is
what would get believed.
"""
from __future__ import annotations

from src.context import deploy


def _o(team="AAA", name="R", inning=8, margin=1, outs_recorded=3, **kw):
    d = {"team": team, "name": name, "inning": inning, "margin": margin,
         "outs": 0, "on_1b": 0, "on_2b": 0, "on_3b": 0, "batters": 4,
         "outs_recorded": outs_recorded, "runs": 0, "ord": 1,
         "last_inning": inning, "date": "2026-05-01"}
    d.update(kw)
    return d


def check_leverage_needs_both_late_and_close():
    assert deploy.leverage(_o(inning=9, margin=1))
    assert deploy.leverage(_o(inning=7, margin=-3))
    assert not deploy.leverage(_o(inning=9, margin=7))    # blowout
    assert not deploy.leverage(_o(inning=5, margin=1))    # not his job yet


def check_split_half_separates_a_real_role_from_noise():
    """Consistent usage must correlate; alternating usage must not."""
    steady = []
    for i, inn in enumerate((6, 7, 8, 9)):
        steady += [_o(name=f"steady{i}", inning=inn)
                   for _ in range(deploy.MIN_OUTINGS)]
    r, n = deploy.split_half(steady, lambda o: o["inning"])
    assert n == 4 and r > 0.95, (r, n)

    # Every pitcher averages the same thing, so there is nothing to
    # correlate and the measure must not manufacture a number.
    flat = []
    for i in range(4):
        flat += [_o(name=f"flat{i}", inning=7 if j % 2 else 9)
                 for j in range(deploy.MIN_OUTINGS)]
    r2, _ = deploy.split_half(flat, lambda o: o["inning"])
    assert r2 is None or abs(r2) < 0.2, r2


def check_split_half_respects_the_order_it_is_given():
    """The halves are FIRST half and SECOND half IN TIME, because the whole
    claim is that games already played predict tomorrow's.

    THE OBVIOUS VERSION OF THIS CHECK IS VACUOUS. One arm promoted
    mid-season and one demoted, asserting the halves disagree, passes just
    as happily when the outings are sorted first — sorting turns every
    pitcher into a promotion, which drove the correlation to -1.0 against
    an honest -0.93. It was the assertion that could not tell them apart,
    not the mutation that was subtle.

    So: give every pitcher the SAME MULTISET of innings and vary only the
    order. Sorting collapses them all to one identical pattern, the spread
    across pitchers goes to zero, and there is nothing left to correlate —
    a structurally different answer rather than a slightly different
    number.
    """
    lo, hi = 6, 9
    seqs = {
        "promoted": [lo] * 6 + [hi] * 6,
        "demoted": [hi] * 6 + [lo] * 6,
        "drifting_up": [lo] * 4 + [hi] * 2 + [lo] * 2 + [hi] * 4,
        "drifting_down": [hi] * 4 + [lo] * 2 + [hi] * 2 + [lo] * 4,
    }
    rows = [_o(name=nm, inning=v) for nm, seq in seqs.items() for v in seq]
    r, n = deploy.split_half(rows, lambda o: o["inning"])
    assert n == 4, n
    assert r is not None and r < -0.9, r


def check_split_half_ignores_thin_samples():
    """Below the floor the halves are sampling noise, and a correlation of
    noise against noise reads as a role that is not there."""
    rows = [_o(name=f"p{i}", inning=6 + i % 4)
            for i in range(3) for _ in range(deploy.MIN_OUTINGS - 1)]
    r, n = deploy.split_half(rows, lambda o: o["inning"])
    assert n == 0 and r is None, (r, n)


def check_pitchers_are_keyed_by_team_as_well_as_name():
    """A traded reliever is two roles, and two clubs' relievers can share a
    name. Pooling on name alone would average a setup man with a mop-up
    man and call the result unstable."""
    rows = ([_o(team="AAA", name="R", inning=9)
             for _ in range(deploy.MIN_OUTINGS)]
            + [_o(team="BBB", name="R", inning=6)
               for _ in range(deploy.MIN_OUTINGS)]
            + [_o(team="CCC", name="S", inning=7)
               for _ in range(deploy.MIN_OUTINGS)])
    _, n = deploy.split_half(rows, lambda o: o["inning"])
    assert n == 3, n


def check_the_measurement_only_looks_at_relievers():
    """`appearance_order > 0` is in the query, not in Python. A starter's
    entry state is always inning 1, nobody on, tied — pooling him in would
    drag every role measurement toward that constant."""
    import inspect
    assert "appearance_order > 0" in inspect.getsource(deploy)
