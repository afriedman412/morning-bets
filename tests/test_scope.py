"""Season scoping — the guard that makes loading a second season safe.

Every check here exists because of one hazard: `season=None` used to mean
EVERY SEASON, 48 of 52 call sites relied on the default, and the database
happened to hold exactly one season. Loading 2025 would have turned that
into silent pooling — a pitcher's K% averaged across a winter of change, the
league baselines averaged across two different balls — with nothing raising
and no way afterwards to separate a pooling bug from a real 2025 effect.
"""
from src.context import calibrate as cal
from src.context import scope, sim
from src.context.sources import rates as rate_src


def check_unqualified_queries_mean_the_current_season():
    """None is THIS season. 'all' is every season and must be asked for."""
    assert scope.resolve(None) == scope.CURRENT_SEASON
    assert scope.resolve(scope.ALL_SEASONS) is None
    assert scope.resolve(2025) == 2025


def check_every_season_filter_goes_through_scope():
    """The three places that build a season filter all honour the default.

    Asserted on the SQL each one produces rather than on a simulated number,
    because the failure being guarded is a missing filter, and a missing
    filter is invisible while the database holds one season. These would all
    pass on today's data with the resolve() calls deleted — so they are
    written against the clause, which would not.
    """
    season = scope.CURRENT_SEASON
    # rates.py
    assert f"g.date like '{season}%'" in rate_src._where(None, None)
    assert "g.date like" not in rate_src._where(scope.ALL_SEASONS, None)
    # calibrate.py — actual_starts builds its own clause, so it is checked
    # through the rows it returns rather than through a private string.
    rows = cal.actual_starts(limit=40)
    assert rows, "no starts came back at all"
    assert all(r["date"].startswith(str(season)) for r in rows), \
        sorted({r["date"][:4] for r in rows})


def check_league_baselines_are_season_scoped():
    """`sim.league()` records which season it measured.

    The recorded label is the whole point: a league dict that cannot say
    what it covers cannot be caught pooling. Before this change it carried
    `season: None` while describing one season, which is the same value it
    would carry while describing two.
    """
    lg = sim.league()
    assert lg["season"] == scope.CURRENT_SEASON, lg["season"]
    pooled = sim.league(scope.ALL_SEASONS)
    assert pooled["season"] is None
    # Only one season is loaded today, so the two must agree on every rate.
    # This check turns into a real comparison the moment 2025 lands, and it
    # is meant to: if it starts failing then, that is the pooling it guards.
    for k in ("k_pct", "bb_pct", "hr_pct", "babip"):
        assert abs(lg[k] - pooled[k]) < 1e-12, (k, lg[k], pooled[k])
