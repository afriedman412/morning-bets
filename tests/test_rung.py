"""Checks for the rung auditor, `src.context.rung`.

The SQL runs against a REAL in-memory sqlite with a real ATTACHed `bets`
schema, not a stub that returns canned rows whatever the query says —
three of these checks exist to pin a literal INSIDE the SQL, and a stub
would pass with the literal removed.

Every check here guards a way of being SILENTLY WRONG. The auditor
prints a number the operator bets on; a crash is cheap and a plausible
wrong cell is not.
"""
import sqlite3

from src.context import rung


# ------------------------------------------------------------- fixtures

def _row(bet, p_over, cls, gap=None, offband=False, **kw):
    r = {"bet": bet, "p_over": p_over, "cls": cls, "gap": gap,
         "offband": offband, "thin": False, "proj": False, "gate": None,
         "kalshi": None, "p_kalshi": None, "vol": None, "clv": None,
         "over": "-110", "under": "+110", "raw": None, "bump": False}
    r.update(kw)
    return r


def _board(*games):
    return {"date": "2026-09-24", "sims": 20000, "games": list(games)}


def _game(away, home, rows):
    return {"away": away, "home": home, "ap": "A", "hp": "B",
            "lineups": "PROJECTED lineups", "mean": 9.0, "rows": rows}


def _db():
    """context.db with a real ATTACHed `bets`, both in memory."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("attach database ':memory:' as bets")
    con.execute("create table mlb_stints"
                " (game_id int, pitcher_id int, player_name text,"
                "  date text, appearance_order int, batters int,"
                "  outs_recorded int)")
    con.execute("create table bets.games"
                " (game_id int, sport text, date text,"
                "  home_team_abbr text, away_team_abbr text,"
                "  home_score int, away_score int,"
                "  home_score_f5 int, away_score_f5 int)")
    con.execute("create table bets.mlb_pitching"
                " (game_id int, player_name text, k int, pitches int)")
    return con


def _start(con, gid, date, bf, outs, k, order=0, sport="mlb"):
    con.execute("insert into mlb_stints values (?,?,?,?,?,?,?)",
                (gid, 7, "A Pitcher", date, order, bf, outs))
    con.execute("insert into bets.games"
                " (game_id, sport, date) values (?,?,?)",
                (gid, sport, date))
    con.execute("insert into bets.mlb_pitching values (?,?,?,?)",
                (gid, "A Pitcher", k, 90))


# ---------------------------------------------------------------- price

def check_breakeven_is_the_boards_own_formula():
    """One price -> one probability, shared with `board_json`.

    Hand values: -110 risks 110 to win 100, so it must clear 11/21.
    +100 and -100 are the same bet and must agree to the bit — a second
    implementation of this formula is how they come to disagree there.
    """
    assert abs(rung.breakeven("-110") - 11 / 21) < 1e-12
    assert abs(rung.breakeven("+100") - 0.5) < 1e-12
    assert abs(rung.breakeven("-100") - 0.5) < 1e-12
    assert abs(rung.breakeven("+150") - 0.4) < 1e-12


def check_the_under_is_the_complement_and_is_not_re_pushed():
    """under = 1 - p_over, with NO second push correction.

    `board_json` already prices an integer total as
    P(cover)/(P(cover)+P(miss)), so p_over is push-adjusted when it
    arrives. Re-normalising here would push the under back toward the
    raw P(under) and quietly overstate it on every whole-number total —
    'total 9' is the rung this fires on.
    """
    r = _row("total 9", 0.4975, "total")
    assert abs(rung.side_prob(r, "over") - 0.4975) < 1e-12
    assert abs(rung.side_prob(r, "under") - 0.5025) < 1e-12
    assert abs(rung.side_prob(r, "over")
               + rung.side_prob(r, "under") - 1.0) < 1e-12


# ----------------------------------------------------------------- tilt

def check_the_tilt_excludes_off_band_rungs():
    """Off-band rungs must not enter the slate mean.

    They sit outside the +/-170 print band where probabilities are
    extreme and a gap in POINTS compresses toward zero. Including them
    drags the mean toward nothing, which UNDERSTATES the correction and
    leaves a tilted rung looking like information.

    The fixture is deliberately asymmetric: the off-band gaps are large
    and one-sided, so dropping the exclusion moves the answer a long way
    rather than a rounding.
    """
    b = _board(_game("AWY", "HOM", [
        _row("total 8.5", 0.55, "total", gap=+4.0),
        _row("total 9.5", 0.44, "total", gap=+6.0),
        _row("total 12.5", 0.02, "total", gap=+40.0, offband=True),
    ]))
    t = rung.tilt(b, "total")
    assert t["n"] == 2, t
    assert abs(t["mean"] - 5.0) < 1e-9, t


def check_a_class_with_no_mids_does_not_divide_by_zero():
    """No priced rung is a real state — an untraded class reads 0, not a
    crash, because the auditor must still print PRICE and the counts."""
    b = _board(_game("AWY", "HOM", [_row("total 8.5", 0.55, "total")]))
    t = rung.tilt(b, "total")
    assert t["n"] == 0 and t["median"] == 0.0 and not t["uniform"], t


def _ladder(name, gap, n=1):
    """n K rungs for one pitcher, all at one gap."""
    return [_row(f"{name} k {k + 2.5}", 0.5, "k", gap=gap)
            for k in range(n)]


def check_one_pitcher_with_six_rungs_counts_once():
    """The tilt's unit is the pitcher, not the rung.

    2026-09-26: May's six rungs at +45 and Yesavage's six at +31 made the
    K class read +6.9 over a slate whose other pitchers averaged -0.2.
    Here one arm's six rungs at +10 against four flat arms must leave the
    median at zero, whatever the rung-weighted mean says.
    """
    b = _board(_game("AWY", "HOM", _ladder("Big Gap", 10.0, n=6)
                     + _ladder("Flat One", 0.0) + _ladder("Flat Two", 0.0)
                     + _ladder("Flat Three", 0.0)
                     + _ladder("Flat Four", 0.0)))
    t = rung.tilt(b, "k")
    assert t["units"] == 5 and t["n"] == 10, t
    assert abs(t["mean"] - 6.0) < 1e-9, t
    assert t["median"] == 0.0, t
    assert t["top"][0] == ("Big Gap", 10.0), t


def check_a_gap_carried_by_two_arms_is_not_a_level():
    """Two extreme arms and a mixed rest is MIXED — no de-tilted edge.

    The 2026-09-26 shape in miniature: two large one-way units, the rest
    split both ways. Subtracting that as our level inflated Bibee's under
    from +8 to +15. Both extremes are named so the reader sees why.
    """
    b = _board(_game("AWY", "HOM",
                     _ladder("May", 45.0, n=6) + _ladder("Yesavage", 31.0, n=6)
                     + _ladder("A", 3.0) + _ladder("B", -3.0)
                     + _ladder("C", 2.0) + _ladder("D", -2.0)
                     + _ladder("E", -1.0)))
    t = rung.tilt(b, "k")
    assert t["mean"] > 20, t
    assert not t["uniform"], t
    assert [lab for lab, _ in t["top"]] == ["May", "Yesavage"], t


def check_a_broad_one_way_gap_is_a_level():
    """Nine of ten units the same way is exactly BETTING.md rule 4's case,
    and the de-tilt must still fire on it."""
    rows = [x for i in range(9) for x in _ladder(f"P{i}", 5.0 + i * 0.1)]
    rows += _ladder("P9", -1.0)
    t = rung.tilt(_board(_game("AWY", "HOM", rows)), "k")
    assert t["uniform"], t
    assert abs(t["share"] - 0.9) < 1e-9, t
    assert 5.0 < t["median"] < 6.0, t


def check_too_few_units_never_read_as_a_level():
    """Three units all one way is not a slate — a Sunday with three games
    priced must not subtract its tiny sample from every rung."""
    rows = [x for i in range(3) for x in _ladder(f"P{i}", 6.0)]
    t = rung.tilt(_board(_game("AWY", "HOM", rows)), "k")
    assert t["share"] == 1.0 and not t["uniform"], t


def check_the_same_total_in_two_games_is_two_units():
    """'total' is the subject in every game, so the unit carries the game
    — otherwise a whole slate of full totals collapses to one unit."""
    b = _board(_game("A", "B", [_row("total 8.5", 0.5, "total", gap=4.0)]),
               _game("C", "D", [_row("total 8.5", 0.5, "total", gap=-4.0)]))
    t = rung.tilt(b, "total")
    assert t["units"] == 2, t
    assert {lab for lab, _ in t["top"]} == {"A@B total", "C@D total"}, t


# ------------------------------------------------------------ selection

def check_several_matching_rungs_never_resolve_to_one():
    """Ambiguity refuses rather than auditing the wrong rung.

    Same rule as `arm.resolve_name`. 'Singer k 3' is a substring of
    'Brady Singer k 3.5' and of nothing else on most boards, but on a
    board carrying 'k 3.5' for two Singers it matches both, and silently
    auditing whichever sorted first is worse than asking again.
    """
    b = _board(
        _game("CIN", "ATL", [_row("Brady Singer k 3.5", 0.47, "k")]),
        _game("SEA", "TEX", [_row("Other Singer k 3.5", 0.51, "k")]))
    assert len(rung.candidates(b, "Singer k 3.5")) == 2
    assert rung.resolve(b, "Singer k 3.5") is None
    # Unambiguous once the game is named, and whitespace is collapsed.
    assert rung.resolve(b, "CIN@ATL  Brady Singer k 3.5") is not None
    assert rung.resolve(b, "brady singer k 3.5") is not None


# ------------------------------------------------------------ the grids

def check_a_half_point_over_counts_the_next_whole_number():
    """P(over 3.5) is P(X >= 4), not P(X >= 3) or P(X >= 5).

    An off-by-one here shifts every cell of the scenario grid by a whole
    strikeout, which is the difference between a bet and a pass on the
    rungs this tool exists for. Hand value: X ~ B(4, 0.5),
    P(X >= 4) = 1/16.
    """
    assert abs(rung.p_over_line(4, 0.5, 3.5) - 1 / 16) < 1e-12
    # P(X >= 1) at n=4, p=0.5 is 15/16 — the 0.5 line counts a lone one.
    assert abs(rung.p_over_line(4, 0.5, 0.5) - 15 / 16) < 1e-12


def check_a_whole_number_line_is_refused_not_guessed():
    """An integer line is a PUSH and has no single right reading here."""
    try:
        rung.p_over_line(20, 0.2, 4.0)
    except ValueError:
        return
    raise AssertionError("an integer line must raise, not guess")


def check_the_implied_rate_inverts_the_grid():
    """`implied_rate` must be the exact inverse of `p_over_line`.

    It is the one number in the report that is not read off the board or
    counted, so it has to round-trip: feed a rate through the grid, take
    the probability back, and the rate must return.
    """
    p = rung.p_over_line(22, 0.2431, 4.5)
    back = rung.implied_rate(p, 22, 4.5)
    assert back is not None and abs(back - 0.2431) < 1e-5, back
    # Unreachable probabilities resolve to None rather than to 0.999.
    assert rung.implied_rate(1.0, 22, 4.5) is None
    assert rung.implied_rate(0.0, 22, 4.5) is None


# --------------------------------------------------------------- windows

def check_a_layoff_is_found_and_keeps_its_name():
    """A gap >= LAYOFF_DAYS splits the log AND survives de-duplication.

    THE BUG THIS GUARDS shipped in the first draft: Pivetta's
    post-layoff window was exactly his last three starts, the de-dupe
    kept the FIRST label for a row set, and 'last 3 starts' silently
    replaced 'since 148d layoff'. The report then showed the collapsed
    rate with nothing saying a five-month absence caused it — which is
    the single fact that separated his rung from Sandlin's.
    """
    log = [dict(d="2026-04-01", bf=20, o=15, k=5, pc=80),
           dict(d="2026-04-07", bf=20, o=15, k=5, pc=80),
           dict(d="2026-09-07", bf=17, o=15, k=2, pc=63),
           dict(d="2026-09-13", bf=17, o=12, k=5, pc=69),
           dict(d="2026-09-18", bf=20, o=15, k=4, pc=76)]
    assert rung.layoff_split(log) == 2
    labels = [lab for lab, _ in rung.windows(log)]
    assert any("layoff" in x for x in labels), labels
    # The three post-layoff starts ARE the last three, and the window
    # that survives must be the one that says why.
    rows = dict(rung.windows(log))
    lay = [r for lab, r in rung.windows(log) if "layoff" in lab][0]
    assert [r["d"] for r in lay] == ["2026-09-07", "2026-09-13",
                                     "2026-09-18"]
    assert "last 3 starts" not in rows


def check_no_layoff_means_no_layoff_row():
    """Consecutive starts must not manufacture a split — a null here is
    a claim too, and a phantom layoff row would invent a regime change."""
    log = [dict(d=f"2026-09-{d:02d}", bf=20, o=15, k=5, pc=80)
           for d in (1, 6, 12, 18)]
    assert rung.layoff_split(log) is None
    assert not any("layoff" in lab for lab, _ in rung.windows(log))


# ----------------------------------------------------------------- SQL

def check_the_start_is_appearance_order_zero():
    """`appearance_order` is 0-INDEXED and the start is order 0.

    The same literal `arm` guards, re-pinned because this module has its
    own copy of the SQL: a `=1` filter counts SECOND pitchers, and every
    counted row in DRIFT, WORKLOAD and OUTS would then describe a
    reliever's night under a starter's name.
    """
    con = _db()
    _start(con, 1, "2026-09-01", 22, 15, 5, order=0)
    _start(con, 2, "2026-09-07", 21, 18, 6, order=0)
    _start(con, 3, "2026-09-12", 4, 3, 1, order=1)   # a relief outing
    got = rung.starts(con, 7)
    assert [r["d"] for r in got] == ["2026-09-01", "2026-09-07"], got


def check_spring_training_is_excluded():
    """`sport = 'mlb'` or March walks back in.

    `gametype.py` relabels exhibitions `mlb-s`; a query that forgets the
    filter counts them, and a pitcher's April line becomes mostly March.
    """
    con = _db()
    _start(con, 1, "2026-03-05", 12, 9, 4, sport="mlb-s")
    _start(con, 2, "2026-04-01", 22, 15, 5)
    got = rung.starts(con, 7)
    assert [r["d"] for r in got] == ["2026-04-01"], got


def check_batters_faced_is_counted_not_derived():
    """bf comes from `mlb_stints.batters`, never outs + hits + walks.

    The boxscore derivation misses hit batsmen and men who reached on an
    error and ran 3 light on a real 2026 start. Batters faced is the
    variable three of the five hand audits turned on and the whole
    scenario grid is indexed by it, so the counted column is the one
    that has to arrive. The fixture's stint says 26 while any
    outs-based reconstruction of this row would say 15.
    """
    con = _db()
    _start(con, 1, "2026-09-01", 26, 15, 5)
    assert rung.starts(con, 7)[0]["bf"] == 26


def check_team_runs_key_on_the_abbr_columns():
    """Runs join on `*_team_abbr`, and scored/allowed never swap sides.

    `home_team` carries the full name — 'Arizona Diamondbacks' against a
    row reading 'D-backs' has already cost this project four fields. And
    a scored/allowed swap is invisible in the output: both are plausible
    run totals, and the rung would simply be audited against the wrong
    club's offence.
    """
    con = _db()
    con.executemany(
        "insert into bets.games (game_id, sport, date, home_team_abbr,"
        " away_team_abbr, home_score, away_score) values (?,?,?,?,?,?,?)",
        [(1, "mlb", "2026-05-01", "KC", "CWS", 7, 2),
         (2, "mlb", "2026-05-02", "CWS", "KC", 1, 6),
         (3, "mlb-s", "2026-03-02", "KC", "CWS", 9, 9)])
    d = rung.team_runs(con, "KC", "2026-04-01")
    assert d["all"] == [7, 6], d["all"]         # scored, home then away
    assert d["home"] == [7], d["home"]          # only the home game
    assert d["allowed"] == [2, 1], d["allowed"]
    # The spring game is excluded from every list.
    assert 9 not in d["all"] and 9 not in d["allowed"]


def check_an_exact_bet_beats_every_substring_match():
    """'total 9' must reach 'total 9', not refuse because of 'total 9.5'.

    THE BUG THIS GUARDS shipped in the first draft and made every
    WHOLE-NUMBER total unaskable: the selector is a substring match, and
    every integer total is a prefix of its own half-point neighbour, so
    the ambiguity guard refused the one rung that carries a push. Same
    rule as `arm.resolve_name` — an exact match wins outright.
    """
    b = _board(_game("CWS", "KC", [
        _row("total 9", 0.4975, "total"),
        _row("total 9.5", 0.4444, "total")]))
    assert len(rung.candidates(b, "total 9")) == 1
    got = rung.resolve(b, "total 9")
    assert got is not None and got[1]["bet"] == "total 9"
    # The half-point neighbour is still reachable, and a genuinely
    # ambiguous selector still refuses.
    assert rung.resolve(b, "total 9.5")[1]["bet"] == "total 9.5"
    assert rung.resolve(b, "total") is None


def check_a_push_leaves_the_denominator():
    """A game landing ON a whole-number line is neither side.

    THE BUG THIS GUARDS: `n - over` counted every push as an under, so a
    counted 'over 9' row was light by the push rate. This engine puts
    10.7% of its draws exactly on 9 — larger than most edges this tool
    adjudicates, and in the direction that makes an over look worse than
    it is. Half-point lines cannot push and must be unaffected.
    """
    import io
    import contextlib

    def row(vals, line, side):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rung._rr(vals, line, side, "x")
        return buf.getvalue()

    # 8, 9, 9, 10: one over, one under, TWO pushes -> 50%, not 25%.
    assert "over 50.0%" in row([8, 9, 9, 10], 9, "over")
    assert "under 50.0%" in row([8, 9, 9, 10], 9, "under")
    assert "2 push" in row([8, 9, 9, 10], 9, "over")
    # The mean still reports over EVERY game, pushes included.
    assert "mean  9.00" in row([8, 9, 9, 10], 9, "over")
    # A half-point line cannot push and keeps the FULL denominator:
    # 9, 9 and 10 all clear 8.5, so three of four, not two of two.
    assert "n=   4" in row([8, 9, 9, 10], 8.5, "over")
    assert "over 75.0%" in row([8, 9, 9, 10], 8.5, "over")
    assert "push" not in row([8, 9, 9, 10], 8.5, "over")
