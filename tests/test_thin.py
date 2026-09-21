"""The thin-record shrink target for hitters — `rates.THIN_TARGET`."""
import sqlite3

from src.context.sources import rates as rs


def check_thin_target_ships_on_and_is_the_counted_shape():
    """On by default; thin hitters strike out more, walk less and homer
    less than the league, regulars the reverse, monotone in the record
    for K and HR; BABIP untouched (it failed the era gate)."""
    assert rs.USE_THIN_TARGET
    k, bb, hr = (rs.THIN_TARGET[s] for s in ("k_pct", "bb_pct", "hr_pct"))
    assert k[0] > k[1] > k[2] > 1.0 > k[4], k
    assert hr[0] < hr[1] < hr[2] < hr[3] < hr[4] and hr[0] < 1.0 < hr[4], hr
    assert bb[0] < 1.0 < bb[4], bb
    assert rs.thin_mult("babip", 10) == 1.0
    assert rs.thin_mult("k_pct", None) == 1.0, "no key, no target"
    assert rs.thin_mult("k_pct", 0) == k[0] and rs.thin_mult("k_pct", 49) == k[0]
    assert rs.thin_mult("k_pct", 50) == k[1] and rs.thin_mult("k_pct", 600) == k[4]
    orig = rs.USE_THIN_TARGET
    rs.USE_THIN_TARGET = False
    try:
        assert rs.thin_mult("k_pct", 0) == 1.0
    finally:
        rs.USE_THIN_TARGET = orig


def _db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("create table games (game_id text primary key, sport text, "
              "date text, status text)")
    c.execute("create table mlb_batting (game_id text, player_name text, "
              "ab int, bb int, h int, so int, hr int)")
    return c


def _line(c, gid, date, who, ab, so, sport="mlb"):
    c.execute("insert or ignore into games values (?,?,?,?)",
              (gid, sport, date, "Final"))
    c.execute("insert into mlb_batting values (?,?,?,?,?,?,?)",
              (gid, who, ab, 0, ab // 4, so, 0))


def check_a_thin_record_is_pulled_toward_its_own_population():
    """Two hitters with the SAME season line — 20 PA, 5 strikeouts — one
    a veteran with 800 PA on record from prior seasons, one with nothing
    before this season. The veteran is pulled toward 0.963 x league, the
    rookie toward 1.198 x league, so the rookie's shrunk K rate is higher.
    Flag off they are identical. A spring-training line must NOT count
    toward the record (sport != 'mlb')."""
    c = _db()
    for i in range(40):                      # veteran, inside the year
        _line(c, f"g{i}", f"2024-0{5 + i // 10}-{i % 10 + 1:02d}", "Vet", 20, 5)
    for i in range(30):                      # and rows OLDER than a year
        _line(c, f"o{i}", f"2024-0{1 + i // 10}-{i % 10 + 1:02d}", "Vet", 20, 5)
    for i in range(20):                      # rookie's spring exhibitions
        _line(c, f"s{i}", f"2025-03-{i + 1:02d}", "Rook", 20, 0, sport="mlb-s")
    for i in range(1):                       # both: one identical April line
        _line(c, "a1", "2025-04-05", "Vet", 20, 5)
        _line(c, "a1", "2025-04-05", "Rook", 20, 5)
    lg = {"k_pct": 0.22, "bb_pct": 0.08, "hr_pct": 0.03, "babip": 0.30}
    orig_park = rs._park_neutralised
    rs._park_neutralised = lambda out, *a, **k: out
    try:
        pooled = rs._pooled_pa(2025, "2025-04-08", conn=c)
        assert pooled == {"Vet": 820, "Rook": 20}, \
            (pooled, "rows older than 365 days are outside the key")
        got = rs.batter_rates(lg, season=2025, before="2025-04-08", conn=c)
        assert got["Rook"]["k_pct"] > got["Vet"]["k_pct"], got
        # exact: same observed, same n, targets 1.198 vs 0.963 x league
        n = 20; k = rs.stabilise_k("k_pct", "bat"); w = n / (n + k)
        obs = 5 / 20
        exp_rook = w * obs + (1 - w) * lg["k_pct"] * rs.THIN_TARGET["k_pct"][0]
        exp_vet = w * obs + (1 - w) * lg["k_pct"] * rs.THIN_TARGET["k_pct"][4]
        assert abs(got["Rook"]["k_pct"] - exp_rook) < 1e-9, (got["Rook"], exp_rook)
        assert abs(got["Vet"]["k_pct"] - exp_vet) < 1e-9, (got["Vet"], exp_vet)
        rs.USE_THIN_TARGET = False
        off = rs.batter_rates(lg, season=2025, before="2025-04-08", conn=c)
        assert abs(off["Rook"]["k_pct"] - off["Vet"]["k_pct"]) < 1e-12, off
    finally:
        rs.USE_THIN_TARGET = True
        rs._park_neutralised = orig_park


def check_no_prior_season_on_record_means_no_target():
    """The database's first season cannot form the 365-day key, so
    every hitter is shrunk toward the plain league — silent-neutral, and
    the case that collapsed the 2023 home run level when the first
    version keyed on 'everything on record'. A live board always has
    last season, so this fires only in a backtest."""
    c = _db()
    _line(c, "a1", "2023-04-05", "Vet", 20, 5)
    _line(c, "a1", "2023-04-05", "Rook", 20, 5)
    _line(c, "a2", "2023-04-06", "Vet", 20, 5)
    lg = {"k_pct": 0.22, "bb_pct": 0.08, "hr_pct": 0.03, "babip": 0.30}
    orig_park = rs._park_neutralised
    rs._park_neutralised = lambda out, *a, **k: out
    try:
        assert rs._pooled_pa(2023, "2023-04-08", conn=c) is None
        got = rs.batter_rates(lg, season=2023, before="2023-04-08", conn=c)
        n = 40; k = rs.stabilise_k("k_pct", "bat"); w = n / (n + k)
        exp = w * (10 / 40) + (1 - w) * lg["k_pct"]
        assert abs(got["Vet"]["k_pct"] - exp) < 1e-9, (got["Vet"], exp)
    finally:
        rs._park_neutralised = orig_park
