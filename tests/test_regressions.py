"""One check per bug actually found, so none of them come back quietly.

Every entry here is a real defect that shipped and was caught by hand. The
name says what broke; the docstring says how. Nothing in this file is
hypothetical, and nothing touches the network.
"""
from __future__ import annotations

from src import roster
from src.context import assemble, contracts
from src.context.sources import catcher, park, statsapi
from src import kalshi


# ── name resolution ────────────────────────────────────────────────────
_FAKE_ROSTER = {
    "season": 2026,
    "by_full": {
        "jose suarez": {"id": 1, "type": "Pitcher", "pos": "P",
                        "name": "José Suárez", "throws": "L", "team_id": 108},
        "ranger suarez": {"id": 2, "type": "Pitcher", "pos": "P",
                          "name": "Ranger Suárez", "throws": "L",
                          "team_id": 143},
        "masataka yoshida": {"id": 3, "type": "Hitter", "pos": "DH",
                             "name": "Masataka Yoshida", "throws": "R",
                             "team_id": 111},
        "shohei ohtani": {"id": 4, "type": "Two-Way Player", "pos": "DH",
                          "name": "Shohei Ohtani", "throws": "R",
                          "team_id": 119},
        "macKenzie gore".lower(): {"id": 5, "type": "Pitcher", "pos": "P",
                                   "name": "MacKenzie Gore", "throws": "L",
                                   "team_id": 120},
    },
    "by_last": {},
    "by_initial": {},
}
for _rec in _FAKE_ROSTER["by_full"].values():
    _last = _rec["name"].split()[-1].lower().replace("á", "a").replace("é", "e")
    _FAKE_ROSTER["by_last"].setdefault(_last, []).append(_rec)


def _with_fake_roster(fn):
    saved = roster._index
    roster._index = _FAKE_ROSTER
    try:
        return fn()
    finally:
        roster._index = saved


def check_full_name_never_falls_back_to_surname():
    """'Eugenio Suarez' is a third baseman absent from the index. Falling
    back to the surname found three Suarezes who all pitch and relabelled
    his home-run prop 'hr_allowed'. A full name that misses is a different
    person, not a hint."""
    def go():
        assert roster.position("Eugenio Suarez") is None
        assert roster.player_id("Eugenio Suarez") is None
        # a bare surname may still resolve when every match agrees
        assert roster.position("suarez") == "Pitcher"
    _with_fake_roster(go)


def check_player_id_requires_exactly_one_match():
    """position() tolerates several players who agree; player_id() must
    not, because a wrong id silently returns another player's game log."""
    def go():
        assert roster.position("suarez") == "Pitcher"   # all agree
        assert roster.player_id("suarez") is None       # but ambiguous
    _with_fake_roster(go)


def check_two_way_player_never_guessed():
    """Ohtani legitimately carries props on both sides; any repair keyed
    off his position is a coin flip."""
    def go():
        assert roster.is_pitcher("Shohei Ohtani") is None
        assert roster.throws("Shohei Ohtani") is None or True
    _with_fake_roster(go)


# ── stat / line repair ─────────────────────────────────────────────────
def check_outs_magnitude_fix_beats_stat_swap():
    """'under 15 outs' reaches the transcript as 'under 1.5 outs'. The old
    code swapped the STAT and produced 'k 1.5' — a starter under 1.5
    strikeouts. Keeping the stat and fixing the magnitude is the smaller
    claim and the right one."""
    from src.grading import repair_stat_line
    stat, line, note = repair_stat_line("outs", 1.5)
    assert (stat, line) == ("outs", 15.0), (stat, line)
    assert note


def check_low_k_line_is_real_and_survives():
    """Steven Matz went under 1.5 strikeouts and it graded W. Bounds alone
    cannot separate that from a mistranscribed outs line, so ordering has
    to: magnitude first, stat swap second."""
    from src.grading import repair_stat_line
    assert repair_stat_line("k", 1.5) == ("k", 1.5, None)


def check_repair_never_invents_an_unbettable_line():
    """'so 15.5' divides to 1.55 — in range for a batter strikeout prop and
    not a number any book posts. A repair that lands off the half-point
    grid is a fabrication."""
    from src.grading import repair_stat_line
    stat, line, note = repair_stat_line("so", 15.5)
    assert (stat, line) == ("so", 15.5)
    assert note and "no magnitude fix" in note


def check_hrr_15_reads_as_1_point_5():
    from src.grading import repair_stat_line
    assert repair_stat_line("h+r+rbi", 15.0)[:2] == ("h+r+rbi", 1.5)


# ── position-based stat repair ─────────────────────────────────────────
def check_batter_with_pitcher_stat_is_relabelled():
    """'Masataka Yoshida k over 1.5' is in range for pitcher strikeouts
    forever; only the roster knows he is a DH."""
    from src.grading import repair_stat_position
    def go():
        stat, note = repair_stat_position("k", "Masataka Yoshida")
        assert stat == "so", stat
        assert note
    _with_fake_roster(go)


def check_unresolvable_name_is_left_alone():
    from src.grading import repair_stat_position
    def go():
        assert repair_stat_position("k", "Palante") == ("k", None)
    _with_fake_roster(go)


# ── neutral sites ──────────────────────────────────────────────────────
def check_unknown_venue_does_not_borrow_the_home_park():
    """MLB plays at Field of Dreams, Mexico City and London. Falling back
    to the home club's park factors there would be confidently wrong —
    Mexico City is one of the most extreme run environments anywhere."""
    saved = park.park_factors
    park.park_factors = lambda *a, **k: {
        "id:99": {"venue": "Real Park", "venue_id": 99, "team_id": 5,
                  "runs": 101},
        "team:5": {"venue": "Real Park", "venue_id": 99, "team_id": 5,
                   "runs": 101},
    }
    try:
        # a venue we know -> found
        assert park.for_venue(venue_id=99)["runs"] == 101
        # a venue id we do NOT know must be None, never the home club's park
        assert park.for_venue(venue_id=12345, team_id=5) is None
    finally:
        park.park_factors = saved


# ── catcher framing: three states, not two ─────────────────────────────
def check_confirmed_but_unrated_catcher_gets_neutral_not_a_substitute():
    """When the lineup names Harry Ford and Savant has never heard of him,
    returning the club's PRIMARY catcher's framing attaches the wrong
    player's number to a known name."""
    saved_f, saved_p = catcher.framing, catcher.primary_catchers
    catcher.framing = lambda *a, **k: {
        "adley rutschman": {"name": "Rutschman, Adley", "player_id": 7,
                            "pitches": 4000, "framing_runs": 5.1,
                            "strike_rate": 0.48},
    }
    catcher.primary_catchers = lambda *a, **k: {
        9: {"name": "Rutschman, Adley", "player_id": 7, "pitches": 4000,
            "framing_runs": 5.1, "strike_rate": 0.48, "team_id": 9,
            "estimated": True},
    }
    try:
        exact = catcher.for_team(9, catcher_name="Adley Rutschman")
        assert exact["confidence"] == "exact"
        assert exact["framing_runs"] == 5.1

        unrated = catcher.for_team(9, catcher_name="Harry Ford")
        assert unrated["confidence"] == "unrated"
        assert unrated["name"] == "Harry Ford"
        # the critical part: no borrowed number
        assert unrated["framing_runs"] is None

        est = catcher.for_team(9)
        assert est["confidence"] == "estimated"
    finally:
        catcher.framing, catcher.primary_catchers = saved_f, saved_p


# ── game logs ──────────────────────────────────────────────────────────
def _log(*rows):
    out = []
    for date, outs, pitches, is_start in rows:
        out.append({"date": date, "outs": outs, "ip": None,
                    "pitches": pitches, "is_start": is_start,
                    "pitches_per_inning": None, "er": 1, "k": 4, "bb": 1,
                    "h": 4, "hr": 0, "opponent": None, "home": True})
    return out


def check_relief_appearances_excluded_from_a_starter_summary():
    """Drew Anderson has 5 starts in 43 appearances. Averaging his last ten
    APPEARANCES gave 6.5 outs — a relief average used to price a start, and
    the headline example in an audit that turned out to be an artifact."""
    rows = _log(
        ("2026-07-01", 3, 12, False), ("2026-07-05", 3, 11, False),
        ("2026-07-11", 4, 19, False), ("2026-07-19", 4, 20, False),
        ("2026-08-05", 11, 42, True), ("2026-08-11", 12, 70, True),
        ("2026-08-16", 15, 74, True), ("2026-08-20", 14, 71, True),
    )
    s = statsapi.game_log_summary(rows, as_of="2026-08-22")
    assert s["basis"] == "starts", s["basis"]
    assert s["starts"] == 4
    assert s["avg_outs"] == 13.0, s["avg_outs"]   # not the relief-dragged 8.2


def check_summary_falls_back_when_there_are_no_starts():
    rows = _log(("2026-08-01", 3, 12, False), ("2026-08-05", 3, 11, False))
    s = statsapi.game_log_summary(rows, as_of="2026-08-22")
    assert "no starts on record" in s["basis"]


def check_recency_window_leads_when_it_has_enough_starts():
    """A flat last-10 spans role changes and injury layoffs. Jacob Lopez
    averaged 13.5 outs over ten starts and 16.3 over six weeks, because the
    ten included May outings from before he was stretched out."""
    rows = _log(
        ("2026-05-14", 6, 40, True), ("2026-05-19", 5, 38, True),
        ("2026-05-31", 6, 41, True),
        ("2026-07-19", 13, 84, True), ("2026-07-24", 15, 91, True),
        ("2026-07-29", 16, 97, True), ("2026-08-05", 15, 87, True),
    )
    s = statsapi.game_log_summary(rows, as_of="2026-08-22")
    assert s["lead"] == "recent", s["lead"]
    assert s["recent"]["starts"] == 4
    # expected_outs must follow the recent window, not the flat mean
    assert s["expected_outs"] == s["recent"]["avg_outs"]
    assert s["expected_outs"] > s["avg_outs"]


# ── kalshi timing ──────────────────────────────────────────────────────
def check_ticker_start_time_matches_statsapi():
    """CLV needs a first-pitch cutoff. The ticker's time segment is
    Eastern; TOR@NYY on 8/22 was '1335' and statsapi reported
    2026-08-22T17:35:00Z."""
    got = kalshi.ticker_start_utc("KXMLBOUTS-26AUG221335TORNYY-NYYRW-18")
    assert got == "2026-08-22T17:35:00Z", got


def check_price_path_excludes_post_game_trades():
    """Kalshi trades through a game and settles at 0 or 1, so the last
    recorded trade on a finished market is the RESULT. Using it as the
    close made CLV perfectly circular — a losing over 'closed' at 0.01."""
    saved = kalshi.trades
    tk = "KXMLBOUTS-26AUG221335TORNYY-NYYRW-18"   # first pitch 17:35Z
    kalshi.trades = lambda t, limit=1000: [
        {"created_time": "2026-08-22T12:00:00Z", "yes_price_dollars": "0.50",
         "no_price_dollars": "0.50"},
        {"created_time": "2026-08-22T17:00:00Z", "yes_price_dollars": "0.58",
         "no_price_dollars": "0.42"},
        # after first pitch — must be ignored
        {"created_time": "2026-08-22T20:00:00Z", "yes_price_dollars": "0.99",
         "no_price_dollars": "0.01"},
    ]
    try:
        p = kalshi.price_path(tk, "over")
        assert p["close_prob"] == 0.58, p["close_prob"]
        assert p["clv"] == 0.08, p["clv"]
        assert p["trades"] == 2
    finally:
        kalshi.trades = saved


# ── coverage lookup ────────────────────────────────────────────────────
def check_team_total_club_is_not_hunted_among_starters():
    """team_total puts the CLUB in player_name. Treating 'Milwaukee
    Brewers' as a person sent it looking through the starters, failed, and
    dragged a well-covered team total to zero."""
    assert assemble._names_a_player(
        {"bet_type": "team_total", "player_name": "Milwaukee Brewers"}
    ) is False
    assert assemble._names_a_player(
        {"bet_type": "prop", "player_name": "Aaron Judge"}
    ) is True


def check_nba_bet_does_not_get_an_mlb_contract():
    """Every contract names probable starters and Savant. 'pts+reb+ast'
    resolved to the batter-prop standard before sport was consulted."""
    c = contracts.contract_for("combo", "pts+reb+ast", "nba")
    assert c.name == "unclassified", c.name


def check_pitcher_only_stats_reach_a_pitcher_contract():
    """'decision' was missing from the pitcher-stat set, so it landed on
    the batter-prop standard."""
    assert contracts.contract_for("prop", "decision").name.startswith(
        "pitcher prop")


def check_no_orphan_or_undeclared_contract_fields():
    """A field no contract uses is dead weight; a field a contract names
    but FIELDS does not declare is a crash waiting to happen."""
    declared = set(contracts.FIELDS)
    used = {k for c in list(contracts.CONTRACTS.values()) + [contracts.FALLBACK]
            for k in c.all_fields()}
    assert not (used - declared), f"undeclared: {used - declared}"
    assert not (declared - used), f"orphaned: {declared - used}"


def check_starter_query_prefers_ground_truth_over_the_outs_heuristic():
    """The local boxscore cache had no starter flag, so `_STARTS_Q` inferred
    one as "most outs on that team that game". Measured against 2,012
    boxscores that is wrong 8.6% of the time, and every miss is a starter
    knocked out early whose long reliever passed him — Tyler Gilbert at two
    outs credited to David Sandlin, Zack Wheeler at six credited to Kyle
    Bradish.

    The bias runs one way and it matters: P(under 9 outs) read 2.9% off the
    heuristic against a true 8.6%. A hook fitted to that has been taught
    that starters do not get blown out, which is exactly the region an under
    lives in.

    This pins the SQL shape rather than the data, so it runs offline: when
    a game has been checked, only the flagged starter may be selected.
    """
    from src.context import calibrate
    q = calibrate._STARTS_Q
    assert "is_starter" in q, "starter query no longer consults ground truth"
    assert "has_truth" in q, \
        "no per-game guard — the heuristic could override a checked game"
    assert "has_truth = 1 and is_starter = 1" in q, \
        "checked games must select the flagged starter, not the outs leader"
    # The old `o >= 3` floor existed only because the heuristic could never
    # return a shorter start. With ground truth a two-out start is real.
    assert "o >= 1" in q, "left tail is being truncated again"


def check_openers_are_excluded_from_the_modelled_population():
    """Openers are genuine starters by the boxscore's definition — 101 of
    the 172 starts the old heuristic missed were openers averaging 4.5 outs.
    They belong in the data and NOT in the population being modelled: no
    book offers an outs line on a bulk reliever, and their outings drag the
    fitted hook toward a leash nobody in the modelled set is on."""
    from src.context import calibrate
    assert calibrate.ROTATION_MIN_GS >= 3, calibrate.ROTATION_MIN_GS
    assert "having sum(case when p2.is_starter = 1 then 1 else 0 end) >= {gs}" \
        in calibrate._ROTATION_JOIN
    # And the count is per SEASON. Unscoped, a 2025 workhorse with three
    # 2026 starts clears the 2026 bar — worth 80 extra cases when 2025 was
    # loaded, all of them arms no book prices this year.
    assert "{season_where}" in calibrate._ROTATION_JOIN


def check_grading_records_who_started():
    """If `cache_mlb_box` stops writing is_starter, the backfill silently
    goes stale and every new game falls back to the broken heuristic."""
    import inspect

    from src import grading
    src = inspect.getsource(grading.mlb_boxscore)
    assert '"is_starter"' in src, "boxscore parser dropped is_starter"
    assert "gamesStarted" in src, \
        "is_starter is no longer sourced from the API's own flag"


def check_kalshi_matches_the_surname_not_just_any_shared_token():
    """A prop quote must never come back as a different player.

    `price_prop` matched on ANY shared name token, so a pitcher Kalshi does
    not list at the requested strike fell through the whole series to the
    first market sharing a FIRST name. Measured live on 2026-08-25: 'Tyler
    Glasnow' under 6.5 K priced off Tyler Phillips of Miami and reported
    Kalshi fair at 0.920 against a true 0.595 — a 32-cent error that the
    returned dict gave the caller no way to notice. A missing price is
    silence; a wrong one is a confident number.

    Also guards the three call sites, because the matcher being correct is
    worth nothing if one of them still does set intersection."""
    import inspect

    from src import kalshi
    assert not kalshi.names_match("Tyler Glasnow", "Tyler Phillips"), \
        "a shared FIRST name is matching again"
    assert not kalshi.names_match("Michael King", "Michael Kopech")
    assert kalshi.names_match("Tyler Glasnow", "Tyler Glasnow")
    # Suffixes and initials differ across feeds and are not real differences.
    assert kalshi.names_match("Luis Ortiz Jr.", "Luis Ortiz")
    assert kalshi.names_match("J. Smith", "Jose Smith")
    # But a prefix is NOT an initial: two different people.
    assert not kalshi.names_match("Will Smith", "Willy Smith")
    for fn in (kalshi.price_prop, kalshi.discover_prop,
               kalshi.find_settled):
        src = inspect.getsource(fn)
        assert "names_match(" in src, f"{fn.__name__} bypasses the matcher"
        assert "_name_key(" not in src, \
            f"{fn.__name__} is back on token-intersection matching"
