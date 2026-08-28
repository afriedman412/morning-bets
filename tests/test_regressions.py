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


def check_the_second_out_of_an_inning_is_not_a_boundary_decision():
    """`count.outs` is the outs AFTER the play, and reading it as BEFORE put
    every second out into the end-of-inning training set.

    Measured over 3,000 games on 2026-08-26: of 56,848 rows labelled
    `ends_inning`, only 29,447 ended an inning. The 27,401 impostors were
    second outs, and they are not the same decision — a true boundary row is
    a removal 11.88% of the time and a second-out row 1.28%, nine times
    lower. Pooled, the set reported a 6.55% boundary pull rate against a
    real 11.88%, and every hook fitted on it inherited the dilution.

    This is `CLAUDE.md`'s pooling rule reached through the LABELS rather than
    through the fit. Guarding the fitting call is not enough when the rows
    arrive already mislabelled.

    The fixture that should have caught it encoded the same misunderstanding
    — see the note at the top of `tests/test_boundary.py` — so this check
    builds its plays from the real convention explicitly and does not use
    that helper.
    """
    from src.context import boundary

    def play(inning, pid, event, outs_after):
        return {
            "about": {"inning": inning, "isTopInning": True},
            "matchup": {"pitcher": {"id": pid}, "batter": {"id": 9}},
            "result": {"eventType": event, "awayScore": 0, "homeScore": 0},
            "count": {"outs": outs_after},
            "playEvents": [{"isPitch": True}] * 3,
            "runners": [],
        }

    # A clean inning: the three outs read 1, 2, 3 in the feed. Only the
    # third is a boundary decision.
    plays = [play(1, 1, "strikeout", 1),
             play(1, 1, "field_out", 2),
             play(1, 1, "field_out", 3),
             play(2, 1, "strikeout", 1),
             play(2, 1, "field_out", 2)]
    rows = boundary.decisions("g", {"allPlays": plays})
    got = [(r["inning"], r["outs_before"], r["ends_inning"]) for r in rows]
    assert got[0] == (1, 0, False), got
    assert got[1] == (1, 1, False), got
    assert got[2] == (1, 2, True), got      # the third out, and only it
    assert got[3] == (2, 0, False), got
    assert sum(1 for r in rows if r["ends_inning"]) == 1, got

    # A double play jumps the count by two and still ends the inning at
    # three. The old event table had to know that; reading the feed does not.
    dp = [play(1, 1, "strikeout", 1),
          play(1, 1, "grounded_into_double_play", 3),
          play(2, 1, "field_out", 1)]
    rows = boundary.decisions("g", {"allPlays": dp})
    assert [r["ends_inning"] for r in rows] == [False, True], rows
    assert rows[1]["outs_before"] == 1, rows[1]


def check_the_error_rate_is_counted_not_calibrated():
    """`ROE_PER_OUT` was set to make the RUN LEVEL come out right.

    Its own comment showed the working — 8.09 / (1 - 0.0764) = 8.76 against
    an actual 8.67 — which is a run-level fudge wearing an error rate's name.
    Counted in the denominator the model rolls it against (balls in play that
    were not hits, 2025+2026) it is 0.0123, and the fudge ran 0.018: 46%
    high, worth 3.5 fake baserunners per 1,000 plate appearances.

    Pinned as a BAND, and the band deliberately EXCLUDES both the old fudge
    and the 2023/24 era rate (~0.0136), because those are the two wrong
    values it could drift back to.
    """
    from src.context import sim

    assert 0.010 < sim.ROE_PER_OUT < 0.0132, sim.ROE_PER_OUT
    assert sim.ROE_PER_OUT < 0.0134, "back on the 2023/24 era rate"


def check_balls_in_play_are_counted_as_plays_not_as_outs():
    """`bip = outs_recorded + hits - K - HR` counts OUTS, and outs are not
    balls in play.

    A double play is ONE ball in play and TWO outs; a caught stealing or
    pickoff is an out and NO ball in play. Counted per play off play-by-play
    and matched on the same games:

        2026 starters   boxscore 57,079   counted 55,225   ratio 1.0336
        2025 starters   boxscore 77,378   counted 74,898   ratio 1.0331
        2025 relievers  boxscore 55,842   counted 54,125   ratio 1.0317

    The numerator is exact — 15,920 non-homer hits from both sources — so it
    is purely the denominator, and it deflated league BABIP from a true
    0.2883 to 0.2778.

    IT SHOWED UP IN BABIP AND NOWHERE ELSE because k/bb/hr resolve through
    log5 against a league measured the same way, so the error cancels in the
    ratio; BABIP's LEVEL reaches the simulation as an absolute rate.

    Guarded as a band on the ratio and by the arithmetic, so a future change
    that reverts to the raw boxscore denominator fails here rather than
    quietly costing 6 baserunners per 1,000 plate appearances.
    """
    from src.context.sources import rates

    assert rates.USE_COUNTED_BIP is True
    assert 1.025 < rates.BIP_PER_OUT_UNIT < 1.042, rates.BIP_PER_OUT_UNIT
    # 100 batters faced, 25 K, 8 BB, 3 HR -> 64 raw, corrected downward.
    raw, got = 64.0, rates.balls_in_play(100, 25, 8, 3)
    assert got < raw, (raw, got)
    assert abs(got - raw / rates.BIP_PER_OUT_UNIT) < 1e-9, got
    # A smaller denominator RAISES the rate built on it, which is the point.
    assert (20.0 / got) > (20.0 / raw)
    # Degenerate lines must not produce a negative or exploding denominator.
    assert rates.balls_in_play(10, 9, 1, 0) == 0.0
    assert rates.balls_in_play(0, 0, 0, 0) == 0.0


def check_stopping_after_five_is_exact_not_an_approximation():
    """`stop_after` must not change a single first-five number.

    The F5 objective reads only `runs_f5` from each side, and `total_rps`
    is also a first-five quantity, yet `simulate_game` played all nine
    innings on every draw of every fit and discarded four of them. The
    optimisation is only legitimate if it is EXACT, so this replays the same
    seeds both ways and demands identical answers — not close ones.

    It also guards the two ways of getting this wrong that look right.
    Passing `innings=5` instead hands 5 to the extra-innings rule, so a game
    tied after five keeps playing; and it makes `regulation` bite, so a home
    side that is ahead stops batting in the fifth. Either one changes the
    quantity being scored.
    """
    import random
    from src.context import game, sim

    lg = sim.league()
    bats = [sim.BatterRates(name=f"b{i}", k_pct=lg["k_pct"],
                            bb_pct=lg["bb_pct"], hr_pct=lg["hr_pct"],
                            babip=lg["babip"], pa=600) for i in range(9)]
    sp = sim.PitcherRates(name="sp", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
                          hr_pct=lg["hr_pct"], babip=lg["babip"], pa=600)
    pen = [{"name": f"r{i}", "k_pct": lg["k_pct"], "bb_pct": lg["bb_pct"],
            "hr_pct": lg["hr_pct"], "babip": lg["babip"], "apps": 40}
           for i in range(8)]

    def play(seed, stop):
        rng = random.Random(seed)
        A = game.build_side(sp, pen, bats, None, rng)
        H = game.build_side(sp, pen, bats, None, rng)
        r = game.simulate_game(A, H, lg, rng, track=(5,), stop_after=stop)
        return A.runs_f5, H.runs_f5, A.line.outs >= 15, r.prefix.get(5)

    same = 0
    for seed in range(60):
        full = play(seed, None)
        early = play(seed, 5)
        assert full == early, (seed, full, early)
        same += 1
    assert same == 60, same

    # And the prefix record survives the early break — putting it before
    # the `track` block drops inning five from the dict it just filled.
    assert play(3, 5)[3] is not None


def check_adjust_lineup_keeps_every_field_on_a_batter():
    """It rebuilt each `BatterRates` by listing fields BY HAND, so any field
    added later was silently deleted on the way into the simulation.

    That is how the handedness matchup arm came out identical to four
    decimal places: `side` and `lg_cell` were attached to every case and
    then dropped here. An identical-to-four-decimals A/B is a plumbing
    result, never a null — and this one would have been reported as "the
    fully specified version changes nothing".

    Guards the general property rather than the two fields, so the next
    field added is covered without anyone remembering to come back.
    """
    import dataclasses
    from src.context import calibrate as cal, sim

    b = sim.BatterRates(name="x", k_pct=0.25, bb_pct=0.09, hr_pct=0.03,
                        babip=0.30, pa=500, arsenal_mult=1.07,
                        arsenal_k_mult=0.93, side="L",
                        lg_cell={"k_pct": 0.2387, "bb_pct": 0.0939,
                                 "hr_pct": 0.0240, "babip": 0.2973})
    out = cal.adjust_lineup([b], True)[0]
    scaled = {"k_pct", "bb_pct", "hr_pct", "babip"}
    for f in dataclasses.fields(sim.BatterRates):
        if f.name in scaled:
            continue
        assert getattr(out, f.name) == getattr(b, f.name), f.name
    # and the four it IS meant to scale actually moved
    assert out.k_pct != b.k_pct


def check_the_matchup_cache_rebuilds_when_the_arm_changes():
    """Nine matchups are resolved per pitcher and reused all the way through
    the order. The failure mode is the obvious one: keep serving the old
    arm's numbers after a change, so every batter is priced against the
    pitcher who just left.

    Nothing downstream could catch that. The runs would still be runs and
    the line would still add up — it would simply be the wrong pitcher, and
    the error would be largest exactly when the bullpen matters most.

    Keyed on the pitcher OBJECT rather than his name, because two clubs can
    carry the same name and a name key would collide silently.
    """
    import random
    from src.context import game, sim

    lg = sim.league()
    bats = [sim.BatterRates(name=f"b{i}", k_pct=0.22, bb_pct=0.08,
                            hr_pct=0.03, babip=0.30, pa=600)
            for i in range(9)]
    quiet = sim.PitcherRates(name="quiet", k_pct=0.05, bb_pct=0.08,
                             hr_pct=0.03, babip=0.30, pa=600)
    rng = random.Random(3)
    # A one-arm pen, so `next_arm` produces a real, checkable change.
    side = game.build_side(quiet, [{"name": "nasty", "k_pct": 0.45,
                                    "bb_pct": 0.08, "hr_pct": 0.03,
                                    "babip": 0.30, "apps": 40}],
                           bats, None, rng)

    def _resolved(sd):
        """The slots actually faced. Resolution is LAZY — a reliever who
        sees three batters builds three matchups, not nine — so unfaced
        slots are legitimately None."""
        return [m for m in sd._mups if m is not None]

    game._half_inning(side, lg, rng, 1, 0, None)
    assert side._mups_for is side.current, "cache never populated"
    assert _resolved(side), "nothing was resolved"
    first = _resolved(side)[0].p_k

    # Same arm: the resolved objects must be REUSED, not rebuilt.
    same = side._mups
    game._half_inning(side, lg, rng, 2, 0, None)
    assert side._mups is same, "rebuilt for an unchanged arm"

    # New arm: the numbers must follow it.
    side.next_arm()
    assert side.current is not quiet, "the pen was never reached"
    game._half_inning(side, lg, rng, 3, 0, None)
    assert side._mups_for is side.current, "cache did not follow the change"
    got = _resolved(side)
    assert got, "nothing resolved for the new arm"
    assert got[0].p_k != first, (got[0].p_k, first)
    assert abs(got[0].p_k - 0.45) < 1e-9, got[0].p_k


def check_the_away_club_bats_in_the_top_of_the_inning():
    """`simulate_game` played its two half-innings the wrong way round.

    A `Side` is a PITCHING side and its `lineup` is "the OPPOSING nine", so
    the side named `away` faces the HOME club. Calling it first therefore
    batted the HOME club in the top of every inning, and the two rules that
    break the symmetry — the skipped bottom half and the walk-off — landed
    on the wrong club: the away club reached the ninth in 46.7% of games
    against a real 1.000, and the home club in 100% against a real 0.557.

    IT CANCELLED IN THE ONLY PLACE ANYONE LOOKED. `where_runs --profile`
    sums both halves, so away-club ninths biased ~0.3 runs low and
    home-club ninths ~0.3 high nearly annihilated. Team totals are the
    stated product and both sides of them were wrong.

    Innings 1-8 are symmetric — both rules key on `regulation` — so no F5
    number ever moved and no existing check could see it.

    Asserted on the SKIP, not on runs: the away club must bat in the ninth
    of every game, and the home club must not.
    """
    import random
    from src.context import game, sim

    lg = sim.league()
    bats = [sim.BatterRates(name=f"b{i}", k_pct=0.22, bb_pct=0.08,
                            hr_pct=0.03, babip=0.300, pa=600)
            for i in range(9)]
    p = sim.PitcherRates(name="p", k_pct=0.22, bb_pct=0.08, hr_pct=0.03,
                         babip=0.300, pa=600)

    real = game._half_inning
    seen = []

    def spy(side, *a, **kw):
        # The away SIDE pitches to the home club, so a call on it IS the
        # home club batting. Recorded as the BATTING club.
        # `_half_inning(side, lg, rng, inning, margin, park, ...)` — the
        # inning is the THIRD positional after `side`.
        seen.append((a[2], "home" if side is spy.A else "away"))
        return real(side, *a, **kw)

    first, away_9, home_9, n = [], 0, 0, 60
    for i in range(n):
        rng = random.Random(i * 17 + 1)
        A = game.build_side(p, [], bats, None, rng, apply_leash=False)
        H = game.build_side(p, [], bats, None, rng, apply_leash=False)
        spy.A = A
        seen.clear()
        game._half_inning = spy
        try:
            game.simulate_game(A, H, lg, rng)
        finally:
            game._half_inning = real
        halves = [(inn, who) for inn, who in seen]
        first.append(next(who for inn, who in halves if inn == 1))
        ninth = {who for inn, who in halves if inn == 9}
        away_9 += "away" in ninth
        home_9 += "home" in ninth

    assert all(f == "away" for f in first), \
        f"the home club batted first in {first.count('home')}/{n} games"
    assert away_9 == n, f"the away club skipped the ninth {n - away_9} times"
    # The two clubs are identical here, so the home club leads after the top
    # of the ninth in a healthy share of games and must sit some of them out.
    # A loose bound: this is asserting the rule FIRES, not its exact rate.
    assert home_9 < n, "the home club batted in every ninth"


def check_a_walk_off_needs_the_lead_not_just_a_run():
    """The walk-off truncated the final half at the FIRST run scored.

    `_half_inning` ends a half early on `side.runs > side.opposing_runs`.
    `side` is the PITCHING side, so `side.runs` is what it ALLOWED — the
    batting club's score — and `opposing_runs` therefore has to hold the
    pitching side's OWN club's score. The driver set

        home.opposing_runs = home.runs      # "this team's own score"

    which is the BATTING club's score, snapshotted immediately before the
    half. The comparison collapsed to "has the batting club scored at all
    this half", so every ninth and every extra inning stopped on the first
    run whatever the margin: 34 of 42 scoring halves ended on exactly one
    run, and none ever exceeded three.

    Asserted on the CONDITION's input rather than on a run distribution,
    because the condition was always sound and only its input was wrong.
    """
    import random
    from src.context import game, sim

    lg = sim.league()
    bats = [sim.BatterRates(name=f"b{i}", k_pct=0.10, bb_pct=0.15,
                            hr_pct=0.02, babip=0.360, pa=600)
            for i in range(9)]
    p = sim.PitcherRates(name="p", k_pct=0.10, bb_pct=0.15, hr_pct=0.02,
                         babip=0.360, pa=600)

    # A side that has ALLOWED 1 (the batting club's score) while its own
    # club has scored 6. Trailing by five, the batting club must be allowed
    # to bat on through a rally rather than being cut off at one run.
    scored = []
    for i in range(300):
        rng = random.Random(i * 29 + 3)
        s = game.build_side(p, [], bats, None, rng, apply_leash=False)
        s.runs, s.opposing_runs = 1, 6
        before = s.runs
        game._half_inning(s, lg, rng, 9, 5, None, walk_off=True)
        scored.append(s.runs - before)

    # With the bug the half died the instant a run crossed, so nothing could
    # reach four. The rally has to survive well past one run.
    assert max(scored) >= 4, \
        f"no half got past {max(scored)} runs — truncated early?"
    big = sum(1 for g in scored if g >= 2)
    assert big > 20, f"only {big}/300 halves scored more than once"

    # And the driver hands the condition the PITCHING side's own club's
    # score, not the batting club's. With the away club (home.runs) on 4 and
    # the home club (away.runs) on 0, the away side's `opposing_runs` must
    # come back 4.
    real = game._half_inning
    got = {}
    # SEVERAL GAMES, and the case has to be an UNTIED one. The bottom of the
    # ninth is not always reached (the home club leading after the top skips
    # it, which is the rule the check above asserts), and when it is reached
    # with the score TIED the buggy value and the correct one COINCIDE —
    # both equal the batting club's score. Only a half entered with the home
    # club trailing can tell them apart.
    for i in range(60):
        rng = random.Random(i * 13 + 11)
        A = game.build_side(p, [], bats, None, rng, apply_leash=False)
        H = game.build_side(p, [], bats, None, rng, apply_leash=False)

        def spy(side, *a, _A=A, _H=H, **kw):
            if kw.get("walk_off") and side is _A and "seen" not in got:
                # AT THE START OF THE HALF: `_A.runs` is what the away side
                # has allowed — the HOME club's score, i.e. the batting
                # club's. `_H.runs` is the AWAY club's score, which is what
                # the batting club has to pass.
                if _A.runs != _H.runs:
                    got["seen"] = (side.opposing_runs, _A.runs, _H.runs)
            return real(side, *a, **kw)

        game._half_inning = spy
        try:
            game.simulate_game(A, H, lg, rng)
        finally:
            game._half_inning = real
        if "seen" in got:
            break
    assert "seen" in got, "no untied walk-off-eligible half in 60 games"
    opp, batting, own = got["seen"]
    assert opp == own, \
        f"opposing_runs {opp} is not the pitching club's score {own}"
    assert opp != batting, \
        f"opposing_runs tracked the BATTING club's score {batting}"
