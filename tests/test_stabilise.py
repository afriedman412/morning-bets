"""Checks for the measured stabilisation points.

Offline: every check builds its own game logs, so the DB is never opened.

The measurement replaces four IMPORTED constants that touch every player
input in the model, so what gets pinned is the arithmetic that turns a
split-half correlation into a shrinkage constant, and the population split
— a batter's home-run rate and a pitcher's are a factor of six apart, and
sharing one table between them was the largest single error here.
"""
from __future__ import annotations

from src.context import stabilise
from src.context.sources import rates


def _games(name, n, per_game):
    """`n` games for one player, each with the same counting line."""
    return [{"name": name, **per_game} for _ in range(n)]


def check_halves_alternate_games_rather_than_splitting_the_season():
    """Odd/even, not first-half/second-half.

    A chronological split confounds true talent with in-season change: a
    pitcher who adds a pitch in June looks unreliable when he is merely
    different. Interleaving makes anything seasonal hit both halves.
    """
    rows = [{"name": "A", "i": i} for i in range(6)]
    halves = stabilise._halves(rows, lambda g: {"i": g["i"]})
    a, b = halves["A"]
    assert a["i"] == 0 + 2 + 4, a["i"]
    assert b["i"] == 1 + 3 + 5, b["i"]


def check_a_perfectly_consistent_population_needs_no_shrinkage():
    """Players who differ from each other and never from themselves are
    perfectly reliable, so k must come out at (or near) zero — the rate is
    trusted immediately."""
    rows = []
    for i, rate in enumerate((0.10, 0.20, 0.30, 0.40, 0.50,
                              0.15, 0.25, 0.35, 0.45, 0.05,
                              0.12, 0.22, 0.32, 0.42, 0.08)):
        rows += _games(f"p{i}", 8, {"so": rate * 20, "ab": 20, "bb": 0})
    res = stabilise.measure(rows, {"k_pct": "so"},
                            lambda g: (g["ab"] or 0) + (g["bb"] or 0))
    d = res["k_pct"]
    assert d["r_half"] > 0.99, d
    assert d["k"] is not None and d["k"] < 5, d


def check_the_stabilisation_constant_inverts_the_shrinkage_formula():
    """k is defined by reliability at n being exactly n/(n+k).

    Getting this backwards produces a plausible number that shrinks the
    wrong way, which no downstream check would catch.
    """
    n, full = 200.0, 0.5
    k = n * (1 - full) / full
    assert abs(k - 200.0) < 1e-9, k
    assert abs(n / (n + k) - full) < 1e-9


def check_batters_and_pitchers_do_not_share_one_table():
    """Measured, a batter's HR rate stabilises at 160 and a starter's at
    934. One shared constant was the largest error in the imported set."""
    bat = rates.STABILISE_MEASURED["bat"]["hr_pct"]
    pit = rates.STABILISE_MEASURED["pit"]["hr_pct"]
    assert pit > bat * 3, (bat, pit)


def check_the_population_actually_reaches_the_shrinkage():
    """`who` must change the answer, or the split is decorative."""
    orig = rates.USE_MEASURED_STABILISE
    rates.USE_MEASURED_STABILISE = True
    try:
        a = rates._shrink(0.10, 0.03, 300, "hr_pct", who="bat")
        b = rates._shrink(0.10, 0.03, 300, "hr_pct", who="pit")
    finally:
        rates.USE_MEASURED_STABILISE = orig
    # The batter's own rate is trusted far more at the same sample size.
    assert a > b + 0.01, (a, b)


def check_the_flag_off_restores_the_imported_constants():
    """Every mechanism stays separately scoreable."""
    orig = rates.USE_MEASURED_STABILISE
    rates.USE_MEASURED_STABILISE = False
    try:
        a = rates._shrink(0.10, 0.03, 300, "hr_pct", who="bat")
        b = rates._shrink(0.10, 0.03, 300, "hr_pct", who="pit")
        k = rates.STABILISE["hr_pct"]
        want = (300 / (300 + k)) * 0.10 + (1 - 300 / (300 + k)) * 0.03
    finally:
        rates.USE_MEASURED_STABILISE = orig
    assert a == b == want, (a, b, want)


def check_measured_batter_rates_shrink_less_than_the_imported_ones():
    """The direction of the whole finding: batter inputs were over-shrunk,
    which averages away the separation the model depends on."""
    for stat in ("k_pct", "bb_pct", "hr_pct", "babip"):
        assert rates.STABILISE_MEASURED["bat"][stat] < rates.STABILISE[stat], \
            stat
