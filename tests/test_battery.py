"""The battery's wiring contract: a run is attributable to a configuration
only if the header prints EVERY switch, live.

The battery exists so a change scores against everything at once, and the
one way that can silently fail is a run made under the wrong flags being
read as the shipped engine. So the contract is checked in both directions:
the flag inventory is TOTAL (a new `USE_*` cannot be added without
appearing), and the values are LIVE (verified by mutation — flip a flag,
the header changes — because a check that guards nothing looks identical
to one that does).
"""
from src.context import calibrate as cal, game, sim
from scratchpad import battery


def check_battery_header_lists_every_flag():
    """Every USE_* in sim, game and calibrate appears in the header."""
    got = battery.flags()
    for mod, name in ((sim, "sim"), (game, "game"), (cal, "calibrate")):
        for k in vars(mod):
            if k.startswith("USE_"):
                assert f"{name}.{k}" in got, f"{name}.{k} missing from " \
                    "the battery header — a run under this flag would be " \
                    "mis-attributed"
    # The two non-USE_ knobs that change what a run means.
    assert "calibrate.NEUTRALISE_PARK" in got
    assert "calibrate.HOME_HOOK" in got


def check_battery_header_is_live_not_a_copy():
    """MUTATION: flipping a flag changes the header. A header read off a
    snapshot taken at import time would pass the inventory check above and
    still mis-attribute every run after the first flag flip."""
    before = battery.flags()["sim.USE_LEASH"]
    sim.USE_LEASH = not before
    try:
        assert battery.flags()["sim.USE_LEASH"] == (not before), \
            "the battery header did not follow a live flag flip"
    finally:
        sim.USE_LEASH = before


def check_battery_wrappers_do_not_change_the_game():
    """The logging wrappers must be observationally inert: same rng stream,
    same outcomes, wrapped or not. A wrapper that consumed randomness would
    silently unpair every seed in the battery."""
    import random

    from tests.test_sim import LG, _lineup, _pitcher

    def one_game(seed):
        rng = random.Random(seed)
        A = game.build_side(_pitcher(), [], _lineup(), sim.Hook(), rng,
                            apply_leash=False)
        H = game.build_side(_pitcher(), [], _lineup(), sim.Hook(), rng,
                            apply_leash=False)
        r = game.simulate_game(A, H, LG, rng, track=(5,))
        return (r.away, r.home, r.away_sp.outs, r.away_sp.k,
                r.home_sp.outs, r.home_sp.k)

    bare = [one_game(s) for s in range(5)]
    orig_apply = sim.apply_pa
    orig_bnd = sim.Hook.removal_p
    orig_mid = sim.Hook.mid_removal_p
    battery._WRAPPED[0] = False
    battery._install()
    try:
        wrapped = [one_game(s) for s in range(5)]
    finally:
        sim.apply_pa = orig_apply
        sim.Hook.removal_p = orig_bnd
        sim.Hook.mid_removal_p = orig_mid
        battery._WRAPPED[0] = False
        battery._PA_LOG.clear()
        battery._HOOK_LOG.clear()
    assert bare == wrapped, "the battery's wrappers changed simulation " \
        "outcomes — they must be observationally inert"


def check_the_save_row_counts_a_held_lead_on_both_sides():
    """The save rows exist because every bullpen instrument shipped on
    2026-09-09 was a PROXY — outing length, selection percentile, closer
    usage rate — and none said whether the model wins the games a real
    bullpen wins.

    Both sides of the battery must agree on what a save situation IS, or the
    row compares two different populations and reads as a permanent defect.
    They share `battery.save_cell`, and this exercises THAT rather than a
    copy of its arithmetic — the first version of this check carried its own
    copy and would have passed through any change to the real thing.
    """
    # A one-run lead after eight, protected: away 4-3 after 8, final 4-3.
    assert battery.save_cell(4, 3, 4, 3) == {
        "n": 1, "held": 1, "r0": 1, "r2": 0}
    # Same lead, blown by two in the bottom of the ninth.
    assert battery.save_cell(4, 3, 4, 5) == {
        "n": 1, "held": 0, "r0": 0, "r2": 1}
    # The HOME club leading is the mirror, and getting this crossed is the
    # single likeliest way to build the row backwards.
    assert battery.save_cell(3, 4, 3, 4) == {
        "n": 1, "held": 1, "r0": 1, "r2": 0}
    # A four-run lead is not a save situation and must not be counted.
    assert battery.save_cell(7, 3, 7, 3)["n"] == 0
    # Tied after eight is not one either.
    assert battery.save_cell(3, 3, 4, 3)["n"] == 0
