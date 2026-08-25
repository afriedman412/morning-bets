"""Checks for the prefix ladder.

Offline: builds its own cases, so neither DB is opened.

The ladder's entire value is that each prefix adds ONE mechanism, so an
error appearing at F7 and not F3 localises the defect to relief. That
inference is only valid if the prefixes are comparable ACROSS model states,
which is a statement about seeding rather than about baseball.
"""
from __future__ import annotations

from src.context import game, ladder, sim
from tests.test_sim import LG, _lineup, _pitcher


def _cases(n=6):
    """`n` synthetic games, each with a home and an away side."""
    by = {}
    for i in range(n):
        gid = f"G{i}"
        by[gid] = [
            ({"game_id": gid, "is_home": True, "team": "HOM"},
             _pitcher(name=f"h{i}"), _lineup()),
            ({"game_id": gid, "is_home": False, "team": "AWY"},
             _pitcher(name=f"a{i}"), _lineup()),
        ]
    return by


def check_the_first_inning_is_immune_to_a_bullpen_flag():
    """No reliever can exist in the first inning, so a bullpen mechanism
    must not move F1 — at all, on identical seeds.

    This is the check that catches SHARED RNG STATE. With one generator
    across the whole game loop, changing anything downstream shifts the
    stream for every later game, and F1 drifts by a large fraction of the
    effect being measured. The ladder then attributes relief error to the
    rate model, which is precisely the inference it exists to support.

    THE PEN IS DELIBERATELY EMPTY, so no reliever ever actually pitches and
    F1 immunity is EXACT rather than approximate. That isolates the question
    to seeding. On real pens F1 can move a little for an honest reason — a
    starter knocked out in the first hands the ball over inside F1 — and a
    check that tolerated that could not tell the two causes apart.
    """
    by = _cases()
    pens = {"HOM": [], "AWY": []}
    orig = game.USE_MEASURED_RELIEF_HOOK
    try:
        game.USE_MEASURED_RELIEF_HOOK = False
        a = ladder.simulate_prefixes(by, pens, dict(LG), n_sims=8, seed=3)
        game.USE_MEASURED_RELIEF_HOOK = True
        b = ladder.simulate_prefixes(by, pens, dict(LG), n_sims=8, seed=3)
    finally:
        game.USE_MEASURED_RELIEF_HOOK = orig
    for gid in a:
        assert a[gid][1] == b[gid][1], (gid, a[gid][1], b[gid][1])


def check_prefixes_are_nested():
    """F1 <= F3 <= F5 <= F7 on every game, because they are read off ONE
    simulated game. If a later prefix ever came in below an earlier one the
    prefixes would be separate simulations and the whole diagnosis would be
    comparing different games to each other."""
    by = _cases(4)
    out = ladder.simulate_prefixes(by, {"HOM": [], "AWY": []}, dict(LG),
                                   n_sims=6, seed=5)
    for gid, pref in out.items():
        vals = [pref[p] for p in ladder.PREFIXES]
        assert vals == sorted(vals), (gid, vals)
