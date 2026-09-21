"""The hitter prior season — item 39. Offline: the prior is handed in."""
import sqlite3

from src.context.sources import rates as rs

LG = {"k_pct": 0.22, "bb_pct": 0.08, "hr_pct": 0.03, "babip": 0.30}


def _db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("create table games (game_id text primary key, sport text, "
              "date text, status text)")
    c.execute("create table mlb_batting (game_id text, player_name text, "
              "ab int, bb int, h int, so int, hr int)")
    return c


def _line(c, gid, date, who, ab, so):
    c.execute("insert or ignore into games values (?,?,?,?)",
              (gid, "mlb", date, "Final"))
    c.execute("insert into mlb_batting values (?,?,?,?,?,?,?)",
              (gid, who, ab, 0, ab // 4, so, 0))


def _fixture():
    """Two hitters with the SAME 20-PA April line (5 K) and the same
    rolling-year record; only the prior differs."""
    c = _db()
    for who in ("Whiff", "Contact"):
        for i in range(30):
            _line(c, f"p{i}", f"2024-0{5 + i // 10}-{i % 10 + 1:02d}", who, 20, 5)
        _line(c, "a1", "2025-04-05", who, 20, 5)
    return c


def check_last_season_is_the_target_not_the_league():
    """Same current line, same record: the man whose prior says 32% K is
    shrunk HIGHER than the man whose prior says 14%. Flag off (or no
    prior) they are identical — the whole change is the target."""
    c = _fixture()
    prior = {"Whiff": {"name": "Whiff", "pa": 500.0, "k_pct": 0.32,
                       "bb_pct": 0.08, "hr_pct": 0.03, "babip": 0.30},
             "Contact": {"name": "Contact", "pa": 500.0, "k_pct": 0.14,
                         "bb_pct": 0.08, "hr_pct": 0.03, "babip": 0.30}}
    orig_park = rs._park_neutralised
    rs._park_neutralised = lambda out, *a, **k: out
    try:
        got = rs.batter_rates(LG, season=2025, before="2025-04-08", conn=c,
                              prior=prior)
        assert got["Whiff"]["k_pct"] > got["Contact"]["k_pct"], got
        # exact: T = shrink(prior, lg x thin, 500), rate = shrink(obs, T, 20)
        pooled = rs._pooled_pa(2025, "2025-04-08", conn=c)
        key = None if pooled is None else pooled.get("Whiff", 0.0)
        base = LG["k_pct"] * rs.thin_mult("k_pct", key)
        kb = rs.stabilise_k("k_pct", "bat")
        T = (500 / (500 + kb)) * 0.32 + (kb / (500 + kb)) * base
        exp = (20 / (20 + kb)) * (5 / 20) + (kb / (20 + kb)) * T
        assert abs(got["Whiff"]["k_pct"] - exp) < 1e-9, (got["Whiff"], exp)
        none = rs.batter_rates(LG, season=2025, before="2025-04-08", conn=c,
                               prior={})
        assert abs(none["Whiff"]["k_pct"] - none["Contact"]["k_pct"]) < 1e-12
        rs.USE_BATTER_PRIOR = False
        off = rs.batter_rates(LG, season=2025, before="2025-04-08", conn=c)
        assert abs(off["Whiff"]["k_pct"] - none["Whiff"]["k_pct"]) < 1e-12
    finally:
        rs.USE_BATTER_PRIOR = True
        rs._park_neutralised = orig_park


def check_a_thin_prior_is_shrunk_by_its_own_sample():
    """A 30-PA cameo last year must not shout: its target sits near the
    league, a 600-PA season's sits near itself."""
    c = _fixture()
    thin = {"Whiff": {"name": "Whiff", "pa": 30.0, "k_pct": 0.40,
                      "bb_pct": 0.08, "hr_pct": 0.03, "babip": 0.30}}
    full = {"Whiff": {"name": "Whiff", "pa": 600.0, "k_pct": 0.40,
                      "bb_pct": 0.08, "hr_pct": 0.03, "babip": 0.30}}
    orig_park = rs._park_neutralised
    rs._park_neutralised = lambda out, *a, **k: out
    try:
        a = rs.batter_rates(LG, season=2025, before="2025-04-08", conn=c, prior=thin)
        b = rs.batter_rates(LG, season=2025, before="2025-04-08", conn=c, prior=full)
        assert b["Whiff"]["k_pct"] > a["Whiff"]["k_pct"], (a["Whiff"], b["Whiff"])
    finally:
        rs._park_neutralised = orig_park


def check_the_prior_is_built_from_last_season_league_adjusted_and_cached():
    """`_batter_prior` reads season-1 through `batter_rates` with the
    thin key pinned to that season's end, re-bases it onto this season's
    league, caches by season, and returns {} while it is itself loading
    (the re-entrancy that would otherwise walk back through every season
    on record)."""
    from src.context import sim
    c = _fixture()
    calls = []
    orig_league = sim.league
    orig_park = rs._park_neutralised
    rs._park_neutralised = lambda out, *a, **k: out
    sim.league = lambda yr, conn=None, before=None: {"season": yr, "k_pct": 0.20,
                                                      "bb_pct": 0.08, "hr_pct": 0.03,
                                                      "babip": 0.30} if yr == 2024 else None
    orig_br = rs.batter_rates
    def spy(lg, season=None, before=None, conn=None, prior=None):
        calls.append((season, before)); return orig_br(lg, season, before, conn, prior)
    rs.batter_rates = spy
    try:
        rs._BAT_PRIOR, rs._BAT_PRIOR_FOR = {}, None
        got = rs._batter_prior(2025, LG, conn=c)
        assert calls == [(2024, "2024-12-31")], calls
        assert "Whiff" in got and got["Whiff"]["pa"] == 600, got.get("Whiff")
        # league-adjusted: 2024 rates were built against k 0.20, now 0.22
        raw = orig_br({"season": 2024, "k_pct": 0.20, "bb_pct": 0.08,
                       "hr_pct": 0.03, "babip": 0.30}, 2024, "2024-12-31",
                      conn=c, prior={})
        assert abs(got["Whiff"]["k_pct"] - raw["Whiff"]["k_pct"] * 0.22 / 0.20) < 1e-9
        again = rs._batter_prior(2025, LG, conn=c)
        assert again is got and len(calls) == 1, "not cached"
        rs._BAT_LOADING = True
        try:
            assert rs._batter_prior(2026, LG, conn=c) == {}
        finally:
            rs._BAT_LOADING = False
    finally:
        sim.league = orig_league
        rs.batter_rates = orig_br
        rs._park_neutralised = orig_park
        rs._BAT_PRIOR, rs._BAT_PRIOR_FOR = {}, None
