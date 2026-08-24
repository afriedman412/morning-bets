"""Checks for the source adapters that had no coverage.

`mixture` matters most: the pre-registered arsenal test depends on it, and a
mixture that silently degrades to the aggregate model would produce a clean
null that means nothing. The rest guard bugs that already shipped once.
"""
from __future__ import annotations

from src.context import sim
from src.context.sources import archetype, mixture, season


# ── name matching ──────────────────────────────────────────────────────
def check_flip_name_converts_savant_to_boxscore_order():
    """Savant writes "Abel, Mick"; the boxscore cache writes "Mick Abel".

    This shipped broken: every pooled archetype rate came out 0.0 because
    nothing joined, and the table still rendered. A silent join failure that
    reads as a modelling result is the worst kind.
    """
    assert archetype.flip_name("Abel, Mick") == "Mick Abel"
    assert archetype.flip_name("Ashcraft, Braxton") == "Braxton Ashcraft"
    assert archetype.flip_name("Mick Abel") == "Mick Abel"    # idempotent
    assert archetype.flip_name("  Cease, Dylan ") == "Dylan Cease"


# ── the arsenal mixture ────────────────────────────────────────────────
def _ars(**usage):
    """A pitcher arsenal: {pitch_type: row} with usage in percent."""
    return {pt: {"pitch_usage": str(u), "k_percent": str(k), "pa": "300"}
            for pt, (u, k) in usage.items()}


def _lg(**k):
    return {pt: {"k_pct": v, "woba": 0.31, "pitches": 10000}
            for pt, v in k.items()}


def check_mixture_degrades_to_the_aggregate_model():
    """A batter with no per-pitch tendencies must return the pitcher's own
    aggregate rate, whatever his mix.

    THE PROPERTY THAT MAKES THIS SAFE TO SWITCH ON. If it did not hold, the
    mixture would move every matchup by some constant and the arsenal test
    would be measuring a level shift rather than a matchup effect.
    """
    data = {"pitchers": {"P": _ars(FF=(60, 20.0), SL=(40, 30.0))},
            "batters": {}}
    lgp = _lg(FF=0.20, SL=0.30)
    got = mixture.matchup_k("B", "P", data, lgp, b_overall=0.22,
                            p_overall=0.24, lg_overall=0.22, log5=sim.log5)
    assert got is not None
    assert abs(got - 0.24) < 1e-6, got


def check_mixture_respects_usage_weighting():
    """Throwing the strikeout pitch more often must raise the matchup rate.

    The whole reason a mixture beats a scalar multiplier: 45% sliders to a
    hitter who cannot touch sliders is not the same matchup as 15%, and a
    single multiplier cannot tell them apart once it is formed.
    """
    lgp = _lg(FF=0.20, SL=0.30)
    bat = {"B": {"SL": {"k_percent": "45.0", "pa": "300"},
                 "FF": {"k_percent": "18.0", "pa": "300"}}}
    out = {}
    for label, sl in (("slider-heavy", 70), ("fastball-heavy", 20)):
        data = {"pitchers": {"P": _ars(FF=(100 - sl, 20.0), SL=(sl, 30.0))},
                "batters": bat}
        out[label] = mixture.matchup_k(
            "B", "P", data, lgp, b_overall=0.22, p_overall=0.24,
            lg_overall=0.22, log5=sim.log5)
    assert out["slider-heavy"] > out["fastball-heavy"], out


def check_mixture_declines_on_thin_coverage():
    """Returns None rather than a guess when the arsenal is incomplete.

    The same rule the rest of the codebase follows: a guessed value that
    moves the estimate in a definite wrong direction is worse than no value,
    because the missing families would silently renormalise onto whatever
    is left.
    """
    data = {"pitchers": {"P": _ars(FF=(30, 20.0))},   # 30% of the arsenal
            "batters": {}}
    got = mixture.matchup_k("B", "P", data, _lg(FF=0.20), b_overall=0.22,
                            p_overall=0.24, lg_overall=0.22, log5=sim.log5)
    assert got is None, got


def check_mixture_shrinks_a_thin_cell_toward_the_batter_himself():
    """A batter's rate against one pitch is a few dozen plate appearances.

    Shrinking toward HIS OWN overall rate rather than the league's means an
    empty cell falls back to what we already believe about him, not to a
    stranger. A one-PA slider line must barely move the answer.
    """
    lgp = _lg(FF=0.20, SL=0.30)
    data = {"pitchers": {"P": _ars(FF=(50, 20.0), SL=(50, 30.0))},
            "batters": {"B": {"SL": {"k_percent": "90.0", "pa": "1"}}}}
    thin = mixture.matchup_k("B", "P", data, lgp, b_overall=0.22,
                             p_overall=0.24, lg_overall=0.22, log5=sim.log5)
    data["batters"]["B"]["SL"]["pa"] = "900"
    thick = mixture.matchup_k("B", "P", data, lgp, b_overall=0.22,
                              p_overall=0.24, lg_overall=0.22, log5=sim.log5)
    assert abs(thin - 0.24) < abs(thick - 0.24), (thin, thick)
    assert thick > thin, (thin, thick)


def check_mixture_returns_a_probability():
    """No input combination may escape [0, 1] — it feeds `pa_outcome`
    directly and a rate above one would silently strike out every batter."""
    lgp = _lg(FF=0.20, SL=0.30)
    for kb in ("1.0", "99.0", "0.1"):
        data = {"pitchers": {"P": _ars(FF=(50, 99.0), SL=(50, 1.0))},
                "batters": {"B": {"FF": {"k_percent": kb, "pa": "400"},
                                  "SL": {"k_percent": kb, "pa": "400"}}}}
        got = mixture.matchup_k("B", "P", data, lgp, b_overall=0.22,
                                p_overall=0.24, lg_overall=0.22,
                                log5=sim.log5)
        if got is not None:
            assert 0.0 < got <= 0.95, (kb, got)


# ── season backfill ────────────────────────────────────────────────────
def check_missing_dates_skips_what_is_already_cached():
    """A date with any cached game counts as done. Re-pulling every date on
    every run would be a thousand needless requests to somebody's free API."""
    import datetime as dt
    have = {"2026-04-02", "2026-04-04"}

    class _C:
        def execute(self, *_):
            return [{"date": d} for d in have]
    got = season.missing_dates(start=dt.date(2026, 4, 1),
                               end=dt.date(2026, 4, 5), conn=_C())
    assert got == ["2026-04-01", "2026-04-03"], got


def check_missing_dates_excludes_the_end():
    """The window is half-open, so the earliest cached date is not re-pulled
    and the two ranges cannot overlap by one."""
    import datetime as dt

    class _C:
        def execute(self, *_):
            return []
    got = season.missing_dates(start=dt.date(2026, 4, 1),
                               end=dt.date(2026, 4, 3), conn=_C())
    assert got == ["2026-04-01", "2026-04-02"], got
