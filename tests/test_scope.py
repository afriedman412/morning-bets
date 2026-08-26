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
    # With a second season loaded these MUST diverge, and the plate
    # appearances behind them must too. An early version of this check
    # asserted they were equal, which was right for a one-season database
    # and became the thing hiding a double-resolve bug: `resolve` is not
    # idempotent, so ALL_SEASONS resolved twice came back as the current
    # season and the pooled call returned 2026 rates over a pooled count.
    if pooled["pa"] > lg["pa"]:
        assert lg["k_pct"] != pooled["k_pct"], "pooled rates equal scoped"
        assert lg["hr_pct"] != pooled["hr_pct"]


def check_resolve_is_not_applied_twice():
    """ALL_SEASONS must survive a round trip through a caller that scopes.

    None means "unspecified" going in and "every season" coming out, so the
    two collide: resolving an already-resolved ALL_SEASONS yields the
    current season. Any function that both scopes itself and passes a season
    on must forward the RAW argument, which is what `sim.league` does.
    """
    import inspect
    src = inspect.getsource(sim.league)
    assert "raw_season" in src, \
        "league() must keep the unresolved argument to pass on"
    assert "_starter_league(conn, before=before, season=raw_season)" in src


def check_the_rotation_gate_is_season_scoped():
    """"Did he start five times" must mean five times THIS season.

    Found by digest, not by reasoning: loading 2025 moved the 2026 case
    count 3,629 -> 3,709 with no code change. A pitcher who started twenty
    times in 2025 and three times in 2026 was clearing the 2026 rotation
    bar, because the subquery counted starts across every season in the
    table.

    Asserted on the SQL rather than the count, because the count only
    reveals it while two seasons are loaded and the clause is what is
    actually wrong.
    """
    q = cal._ROTATION_JOIN.format(
        gs=cal.ROTATION_MIN_GS,
        season_where=f"and g2.date like '{scope.CURRENT_SEASON}%'")
    assert f"g2.date like '{scope.CURRENT_SEASON}%'" in q
    assert "join games g2" in q, "the gate cannot filter by date without it"


def check_starter_league_baselines_are_season_scoped():
    """The anchor every simulated rate is log5'd against.

    `_starter_league` overwrites k_pct, bb_pct and hr_pct in `league()`, and
    it took no season argument at all — so with two seasons loaded the
    anchor pooled both. The signature it wore made this invisible: `pa` and
    `runs_per_9` come from the batting query and stayed correct while the
    three overwritten rates moved, which is only possible if two queries
    disagree about which rows they cover.
    """
    import inspect
    assert "season" in inspect.signature(sim._starter_league).parameters, \
        "it cannot be scoped if it cannot be told the season"
    assert "{season_where}" in sim._SP_Q, \
        "the rotation subquery inside _SP_Q must take a season filter"
    a = sim._starter_league(season=scope.CURRENT_SEASON)
    b = sim._starter_league(season=scope.ALL_SEASONS)
    assert a and b
    # Identical while one season is loaded; the moment a second is, these
    # must diverge. Either way the call has to accept the argument.
    assert a["k_pct"] is not None and b["k_pct"] is not None
