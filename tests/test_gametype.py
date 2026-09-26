"""Spring training is not baseball to the engine — `sources/gametype.py`."""
import sqlite3

from src.context.sources import gametype


def check_only_spring_exhibition_and_all_star_leave_the_mlb_label():
    """Regular season AND every postseason type stay `mlb`: postseason is
    `rates.EXCLUDE_POSTSEASON`'s question, by date, and is off until
    measured. A wrong mapping here silently drops October from every rate."""
    assert gametype.sport_for("R") == "mlb"
    for t in ("F", "D", "L", "W"):
        assert gametype.sport_for(t) == "mlb", t
    assert gametype.sport_for(None) == "mlb"
    assert gametype.sport_for("S") == "mlb-s"
    assert gametype.sport_for("E") == "mlb-e"
    assert gametype.sport_for("A") == "mlb-a"


def check_the_ingest_labels_a_spring_game_from_its_game_type():
    """`grading.mlb_schedule` must carry the schedule's gameType into
    `sport`, or next March re-imports the exhibitions as baseball. The
    first version hardcoded 'mlb'; deleting the mapping fails this."""
    from src import grading

    def fake(url):
        return {"dates": [{"date": "2027-03-10", "games": [
            {"gamePk": 1, "gameType": "S", "officialDate": "2027-03-10",
             "status": {"detailedState": "Final"}, "gameDate": "x",
             "teams": {"away": {"team": {"name": "A", "abbreviation": "A"},
                                "score": 1},
                       "home": {"team": {"name": "B", "abbreviation": "B"},
                                "score": 2}}},
            {"gamePk": 2, "gameType": "R", "officialDate": "2027-03-10",
             "status": {"detailedState": "Final"}, "gameDate": "x",
             "teams": {"away": {"team": {"name": "A", "abbreviation": "A"},
                                "score": 1},
                       "home": {"team": {"name": "B", "abbreviation": "B"},
                                "score": 2}}},
        ]}]}
    orig = grading._fetch_json
    grading._fetch_json = fake
    try:
        rows = {r["game_id"]: r["sport"] for r in grading.mlb_schedule("2027-03-10")}
    finally:
        grading._fetch_json = orig
    assert rows == {"mlb-1": "mlb-s", "mlb-2": "mlb"}, rows


def check_relabel_touches_only_listed_mlb_games_and_reverts_exactly():
    """Apply relabels a listed regular-labelled game, skips a game that is
    not in the records, skips one already relabelled (idempotent), and
    never touches an unlisted game; revert puts every relabelled row back
    and nothing else."""
    c = sqlite3.connect(":memory:")
    c.execute("create table games (game_id text primary key, sport text, "
              "date text)")
    c.executemany("insert into games values (?,?,?)", [
        ("mlb-1", "mlb", "2025-03-10"), ("mlb-2", "mlb", "2025-04-10"),
        ("mlb-3", "mlb-s", "2025-03-11"), ("nba-9", "nba", "2025-03-10")])
    ids = {"mlb-1": "S", "mlb-3": "S", "mlb-404": "E"}
    changed = gametype.apply(c, ids)
    assert changed == [("mlb-1", "mlb-s")], changed
    got = dict(c.execute("select game_id, sport from games"))
    assert got == {"mlb-1": "mlb-s", "mlb-2": "mlb", "mlb-3": "mlb-s",
                   "nba-9": "nba"}, got
    assert gametype.apply(c, ids) == [], "second apply must be a no-op"
    assert gametype.revert(c) == 2
    got = dict(c.execute("select game_id, sport from games"))
    assert got == {"mlb-1": "mlb", "mlb-2": "mlb", "mlb-3": "mlb",
                   "nba-9": "nba"}, got


def check_nonregular_ids_are_cached_and_cover_all_three_types(tmp_path=None):
    """One schedule call per type per season, cached so a re-run is
    offline; the fetch must be asked for S, E and A."""
    import pathlib, tempfile
    asked = []

    def fake(url):
        asked.append(url.rsplit("=", 1)[1])
        return {"dates": [{"games": [{"gamePk": len(asked)}]}]}
    orig = gametype.CACHE
    gametype.CACHE = pathlib.Path(tempfile.mkdtemp())
    try:
        ids = gametype.nonregular_ids(2031, fetch=fake)
        assert sorted(asked) == ["A", "E", "S"], asked
        assert ids == {"mlb-1": "S", "mlb-2": "E", "mlb-3": "A"}, ids
        again = gametype.nonregular_ids(2031, fetch=fake)
        assert again == ids and len(asked) == 3, "second call hit the network"
    finally:
        gametype.CACHE = orig
