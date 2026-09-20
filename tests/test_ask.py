"""The board's chat panel: the lookups, the loop, and the SQL hatch.

Offline by construction. The Anthropic client is INJECTED — `_Scripted`
plays a fixed list of responses and records what it was sent — so these
checks exercise the real loop (tool dispatch, error round trips, the
give-up path) without a key or a socket. The lookups run against a
temporary bets/ and a temporary database built here, never the repo's
own, so a backfill cannot change what a check asserts.

Each was verified by mutation: break the guarded behaviour, watch that
check alone fail.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

from scratchpad import ask, boards, grade_boards as gb
from scratchpad.gen_board_html import build


# ── a scripted model ───────────────────────────────────────────────────

class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _text(t):
    return _Block(type="text", text=t)


def _use(name, inp, id="tu1"):
    return _Block(type="tool_use", name=name, input=inp, id=id)


class _Scripted:
    """An Anthropic client that plays `turns` and records every request."""

    def __init__(self, *turns, stop="end_turn"):
        self.turns, self.sent, self.stop = list(turns), [], stop
        self.messages = self

    usage = _Block(input_tokens=100, output_tokens=20,
                   cache_read_input_tokens=90)

    def create(self, **kw):
        # SNAPSHOT the message list. `answer` keeps appending to the same
        # one, so holding the reference would show every request as the
        # finished conversation and quietly pass a check that the tool
        # results came back in the right shape.
        self.sent.append(dict(kw, messages=list(kw["messages"])))
        content = self.turns[min(len(self.sent) - 1, len(self.turns) - 1)]
        return _Block(content=list(content), stop_reason=self.stop,
                      usage=self.usage)


# ── the loop ───────────────────────────────────────────────────────────


def check_the_answer_is_built_out_of_tool_calls_and_says_which():
    """A question goes out with the tools and the cached system prompt
    attached; the tool actually runs; its result goes back as a
    tool_result carrying the tool_use id; and the trace names the call
    so the reader can audit the number."""
    c = _Scripted([_use("database_schema", {"table": "games"})],
                  [_text("`games` has a date column.")])
    out = ask.answer("what tables are there", client=c)

    assert out["answer"] == "`games` has a date column."
    assert [t["tool"] for t in out["trace"]] == ["database_schema"]
    assert out["trace"][0]["error"] is False
    first = c.sent[0]
    assert {t["name"] for t in first["tools"]} == set(ask.IMPL)
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["model"] == ask.MODEL
    back = c.sent[1]["messages"][-1]
    assert back["role"] == "user"
    assert back["content"][0]["tool_use_id"] == "tu1"
    assert "games" in back["content"][0]["content"]


def check_parallel_tool_results_go_back_in_one_user_message():
    """Two calls in one turn must answer in ONE message. Splitting them
    teaches the model to stop calling tools in parallel, which is a
    silent doubling of the round trips a question costs."""
    c = _Scripted([_use("boards_available", {}, "a"),
                   _use("database_schema", {}, "b")],
                  [_text("done")])
    ask.answer("two at once", client=c)
    sent = [m for m in c.sent[1]["messages"] if m["role"] == "user"]
    assert len(sent) == 2, [m["role"] for m in c.sent[1]["messages"]]
    ids = [b["tool_use_id"] for b in sent[-1]["content"]]
    assert ids == ["a", "b"], ids


def check_a_failing_lookup_is_a_tool_result_not_a_crash():
    """A bad column name in generated SQL is a NORMAL event in this loop
    — the model fixes it next turn. Every failure mode comes back as
    is_error rather than a 500: an unknown tool, wrong arguments, and a
    tool that raises."""
    for call, why in ((_use("no_such_tool", {}), "unknown tool"),
                      (_use("board_rows", {"nope": 1}), "bad argument"),
                      (_use("query", {"sql": "select * from nope"}),
                       "bad sql")):
        c = _Scripted([call], [_text("recovered")])
        out = ask.answer("q", client=c)
        assert out["answer"] == "recovered", why
        assert out["trace"][0]["error"] is (why != "bad sql"), why
        result = c.sent[1]["messages"][-1]["content"][0]
        assert "error" in result["content"], why


def check_tokens_are_counted_over_the_whole_question():
    """ONE question is several requests. Reporting the last one's usage
    understates what the panel costs by a factor of the round trips, and
    the round trips are the point of it."""
    c = _Scripted([_use("boards_available", {})], [_text("done")])
    got = ask.answer("q", client=c)["usage"]
    assert got == dict(input=200, output=40, cache_read=180), got


def check_the_loop_gives_up_rather_than_spinning():
    """A model that keeps calling tools must stop costing money. The
    give-up answer says so rather than inventing a conclusion."""
    c = _Scripted([_use("boards_available", {})])
    out = ask.answer("q", client=c, max_turns=3)
    assert len(c.sent) == 3, len(c.sent)
    assert out["stop_reason"] == "max_turns"
    assert "Gave up" in out["answer"]
    assert len(out["trace"]) == 3


def check_the_board_being_read_reaches_the_model():
    """'tonight' has no meaning without the page's own date, and a
    guessed one silently answers about a different slate."""
    c = _Scripted([_text("ok")])
    ask.answer("biggest gap tonight", date="2026-09-19", client=c)
    first = c.sent[0]["messages"][0]["content"]
    assert "2026-09-19" in first and "biggest gap tonight" in first


def check_history_is_replayed_and_capped():
    """Follow-ups need the thread; an afternoon of them must not resend
    an unbounded one."""
    hist = [{"role": "user" if i % 2 == 0 else "assistant",
             "content": f"m{i}"} for i in range(40)]
    c = _Scripted([_text("ok")])
    ask.answer("and?", history=hist, client=c)
    msgs = c.sent[0]["messages"]
    assert len(msgs) == ask.MAX_HISTORY + 1, len(msgs)
    assert msgs[0]["content"] == f"m{40 - ask.MAX_HISTORY}"


# ── the SQL hatch ──────────────────────────────────────────────────────


def check_the_sql_hatch_refuses_every_write():
    """The one place in this repo where a GENERATED string reaches
    morning_bets.db. Read-only three times over; this is the authorizer
    layer, which holds even if a URI ever loses its mode=ro."""
    for sql in ("delete from games",
                "update games set away_score = 99",
                "insert into games (game_id) values ('x')",
                "drop table games",
                "create table t (a int)",
                "create temp table t as select 1"):
        got = ask.query(sql)
        assert "not authorized" in got.get("error", ""), (sql, got)


def check_the_sql_hatch_denies_attach_and_write_pragmas():
    """ATTACH is how a read-only connection gets talked into writing
    somewhere else, and `writable_schema` is how it gets talked into
    writing here. Read-only introspection stays, because
    `database_schema` runs on this same connection."""
    assert "not authorized" in ask.query(
        "attach database '/tmp/x.db' as x").get("error", "")
    assert "not authorized" in ask.query(
        "pragma writable_schema = 1").get("error", "")
    assert "not authorized" in ask.query(
        "pragma journal_mode = delete").get("error", "")
    ok = ask.query("select name from sqlite_master limit 1")
    assert "error" not in ok, ok


def check_a_second_statement_never_rides_along():
    """`select 1; delete from games` is the oldest trick there is."""
    got = ask.query("select 1; delete from games")
    assert "one statement" in got.get("error", "").lower(), got


def check_query_caps_what_it_returns():
    """An unbounded SELECT must not put 88,000 boxscore rows through a
    context window."""
    got = ask.query("select * from mlb_pitching", limit=3)
    assert got["returned"] == 3 and got["truncated"] is True, got
    assert ask.query("select * from mlb_pitching",
                     limit=10_000)["returned"] <= 200


# ── the graded tables ──────────────────────────────────────────────────


def _graded(**kw):
    r = dict(date="2026-09-10", cls="k", bet="Arm One k 5.5", board="b.json",
             game="AAA @ BBB", line=5.5, actual=7, p_us=0.60, p_k=0.50,
             push=False, hit=1)
    r.update(kw)
    return r


def check_head_to_head_is_paired_and_signed_our_way():
    """Ours minus theirs, so POSITIVE means we scored WORSE — the sign
    an operator reads first. The se is of the per-rung DIFFERENCE, not
    of either Brier: the two are read off the same outcome."""
    # both overs hit; we said 90%, they said even money
    rows = [_graded(hit=1, p_us=0.9, p_k=0.5),
            _graded(hit=1, p_us=0.9, p_k=0.5)]
    [got] = gb.head_to_head(rows, classes=("k",))
    assert got["n"] == 2
    assert abs(got["brier_us"] - 0.01) < 1e-9, got
    assert abs(got["brier_kalshi"] - 0.25) < 1e-9, got
    assert abs(got["diff"] + 0.24) < 1e-9, "we won; the diff must be -0.24"
    # and the other way round: worse than the mid reads POSITIVE
    worse = gb.head_to_head([_graded(hit=0, p_us=0.9, p_k=0.5)],
                            classes=("k",))[0]
    assert abs(worse["diff"] - 0.56) < 1e-9, worse


def check_pushes_and_unquoted_rungs_stay_out_of_the_tables():
    """A push is not a result and a rung Kalshi never quoted is not a
    head to head — scoring either one against nothing is how a record
    gets padded. Calibration keeps unquoted rungs: it is ours alone."""
    rows = [_graded(), _graded(push=True), _graded(p_k=None)]
    [h2h] = gb.head_to_head(rows, classes=("ALL",))
    assert h2h["n"] == 1, h2h
    assert gb.bet_the_gap(rows, thresholds=(0.05,))[0]["n"] == 1
    [cal] = gb.calibration(rows, min_n=1)
    assert cal["n"] == 2, "the push should drop, the unquoted rung stay"


def check_bet_the_gap_takes_our_side_at_the_mid():
    """The counterfactual is OUR side of the disagreement, priced at
    Kalshi's mid. When we price the over lower, the bet is the UNDER at
    one minus the mid — getting that backwards would invert the P&L."""
    # we say 30% over, they say 50%: bet the under at 0.50, and the
    # under wins (hit=0), so the unit returns +1.00
    [got] = gb.bet_the_gap([_graded(p_us=0.30, p_k=0.50, hit=0)],
                           thresholds=(0.05,))
    assert got["n"] == 1 and got["won"] == 1
    assert abs(got["pl"] - 1.0) < 1e-9, got
    # same disagreement, the over lands: one unit lost
    [got] = gb.bet_the_gap([_graded(p_us=0.30, p_k=0.50, hit=1)],
                           thresholds=(0.05,))
    assert got["won"] == 0 and abs(got["pl"] + 1.0) < 1e-9, got
    # inside the threshold, nothing is bet
    assert gb.bet_the_gap([_graded(p_us=0.52, p_k=0.50)],
                          thresholds=(0.05,)) == []


# ── the lookups, against a fixture repo ────────────────────────────────


def _row(bet, cls, p_over, p_kalshi):
    return {"bet": bet, "cls": cls, "over": "-120", "under": "+120",
            "kalshi": "+100", "offband": False, "thin": False, "proj": False,
            "gate": None, "raw": None, "vol": 1200.0, "bump": False,
            "p_over": p_over, "p_kalshi": p_kalshi,
            "gap": None if p_kalshi is None
            else round((p_over - p_kalshi) * 100, 1)}


def _fixture(td):
    """One board and the game it settled on, in a throwaway repo."""
    board = {"date": "2026-09-10", "sims": 20000, "declined": [],
             "lineups_posted": 1, "games_scheduled": 1,
             "games": [{"away": "AAA", "home": "BBB", "ap": "Arm One",
                        "hp": "Arm Two", "lineups": "posted", "mean": 9.0,
                        "rows": [_row("total 8.5", "total", 0.60, 0.50),
                                 _row("AAA total 3.5", "team", 0.40, 0.55),
                                 _row("BBB total 4.5", "team", 0.60, 0.70),
                                 _row("Arm One k 5.5", "k", 0.30, 0.50),
                                 _row("Arm One k 6.5", "k", 0.20, None)]}]}
    with open(os.path.join(td, "2026_09_10_board.json"), "w") as f:
        json.dump(board, f)
    db = os.path.join(td, "mb.db")
    con = sqlite3.connect(db)
    con.execute("""create table games (date, away_team_abbr, home_team_abbr,
                   game_id, away_score, home_score, away_score_f5,
                   home_score_f5, status)""")
    con.execute("insert into games values "
                "('2026-09-10','AAA','BBB','g1',2,7,1,3,'Final')")
    con.execute("""create table mlb_pitching (game_id, player_name, k,
                   outs_recorded, is_starter)""")
    con.execute("insert into mlb_pitching values ('g1','Arm One',4,15,1)")
    con.commit()
    con.close()
    return db


def _repointed(td, db):
    """Point every module-level path at the fixture, and back after."""
    saved = (boards.BETS_DIR, gb.BETS_DIR, gb.DB)
    boards.BETS_DIR, gb.BETS_DIR, gb.DB = td, td, db
    return saved


def check_board_rows_filters_and_names_the_file_it_read():
    """Two pickers decide 'board of record' in this repo — this one and
    grade_boards' version-rank — so every answer carries the file it
    came from rather than only a date."""
    with tempfile.TemporaryDirectory() as td:
        saved = _repointed(td, _fixture(td))
        try:
            got = ask.board_rows("2026-09-10")
            assert got["file"] == "2026_09_10_board.json", got
            assert got["matched"] == 5 and got["lineups"] == "1 of 1 posted"
            # k 5.5 is 20 points from the mid, the team total 15, the
            # game total 10, and the unquoted rung sorts last
            assert [r["bet"] for r in got["rows"]] == \
                ["Arm One k 5.5", "AAA total 3.5", "total 8.5",
                 "BBB total 4.5", "Arm One k 6.5"], \
                "sort must be by distance from the mid"
            assert ask.board_rows("2026-09-10", cls="k")["matched"] == 2
            assert ask.board_rows("2026-09-10", team="ZZZ")["matched"] == 0
            assert ask.board_rows("2026-09-10", pitcher="arm one",
                                  min_gap=10)["matched"] == 1
            assert ask.board_rows("2026-09-10", limit=1)["truncated"] == 4
            assert "error" in ask.board_rows("2026-09-11")
        finally:
            boards.BETS_DIR, gb.BETS_DIR, gb.DB = saved


def check_settled_rungs_keeps_our_side_apart_from_the_gap_side():
    """The side we priced over even money and the side we priced above
    KALSHI are different questions and usually different sides. Reading
    the disagreement off our own probability is how a losing rung gets
    reported as a win."""
    with tempfile.TemporaryDirectory() as td:
        saved = _repointed(td, _fixture(td))
        try:
            got = ask.settled_rungs(date="2026-09-10")
            by = {r["bet"]: r for r in got["rows"]}
            assert got["matched"] == 5, got
            # 9 runs scored against a 8.5 line: the over hit
            t = by["total 8.5"]
            assert t["actual"] == 9 and t["over_hit"] is True
            assert t["our_side"] == "over" and t["our_side_won"] is True
            assert t["gap_side_won"] is True
            # AAA scored 2 against 3.5, and we priced the under while
            # sitting BELOW Kalshi — our side won, the gap side too
            a = by["AAA total 3.5"]
            assert a["our_side"] == "under" and a["our_side_won"] is True
            assert a["gap_points"] == -15.0 and a["gap_side_won"] is True
            # THE ONE THAT SEPARATES THEM: BBB scored 7 against 4.5, so
            # the over landed. We priced that over at 60% — our side, and
            # it won — while Kalshi had it at 70%, so the DISAGREEMENT
            # was the under and the gap side lost. Reading one off the
            # other reports this rung backwards.
            b = by["BBB total 4.5"]
            assert b["our_side"] == "over" and b["our_side_won"] is True
            assert b["gap_points"] == -10.0 and b["gap_side_won"] is False
            # 4 K against 5.5: under. We priced the under (0.30) but
            # BELOW Kalshi's 0.50 — both sides agree here and both won
            k = by["Arm One k 5.5"]
            assert k["actual"] == 4 and k["our_side_won"] is True
            # the unquoted rung settles but has no disagreement
            assert by["Arm One k 6.5"]["gap_side_won"] is None
            assert by["Arm One k 6.5"]["our_side_won"] is True
            assert ask.settled_rungs(date="2026-09-10",
                                     cls="k")["matched"] == 2
            assert ask.settled_rungs(date="2026-09-10",
                                     min_gap=14)["matched"] == 2
            assert ask.settled_rungs(date="2026-09-10",
                                     team="BBB")["matched"] == 5
        finally:
            boards.BETS_DIR, gb.BETS_DIR, gb.DB = saved


def check_grading_summary_reports_the_boards_behind_it():
    """An aggregate without its n and its date range is not auditable,
    and the notes carry the two readings that get inverted: the sign of
    the diff, and what bet_the_gap is not."""
    with tempfile.TemporaryDirectory() as td:
        saved = _repointed(td, _fixture(td))
        try:
            got = ask.grading_summary()
            assert got["range"] == "2026-09-10..2026-09-10"
            assert got["boards"] == 1 and got["rungs_settled"] == 5
            assert got["with_kalshi"] == 4
            assert got["files"] == {"2026-09-10": "2026_09_10_board.json"}
            assert any(r["cls"] == "ALL" for r in got["head_to_head"])
            assert any("POSITIVE means we scored worse" in n
                       for n in got["notes"])
            assert "error" in ask.grading_summary(since="2026-09-11")
        finally:
            boards.BETS_DIR, gb.BETS_DIR, gb.DB = saved


# ── the panel and its route ────────────────────────────────────────────


def check_the_panel_renders_only_where_something_can_answer_it():
    """A static page is read off disk days later, often with no server
    running; a box that posts to a /ask nobody serves is worse than no
    box. The panel needs the board's own date to resolve 'tonight'."""
    from tests.test_board_web import _payload
    static = build(_payload())
    served = build(_payload(), chat=True)
    assert 'id="chat-log"' not in static
    assert 'id="chat-log"' in served
    assert 'data-date="2026-09-19"' in served


def check_the_ask_route_validates_and_surfaces_its_failures():
    """An empty question never reaches the API; a missing key is a
    sentence in the panel rather than a 500; junk history is dropped
    before it becomes a malformed request."""
    from scratchpad import board_server
    c = board_server.app.test_client()
    assert c.post("/ask", json={"question": "  "}).status_code == 400
    assert c.post("/ask", json={"question": "x" * 2001}).status_code == 400

    seen = {}

    def fake(q, history=None, date=None):
        seen.update(q=q, history=history, date=date)
        return {"answer": "42", "trace": []}

    orig = board_server.ask.answer
    board_server.ask.answer = fake
    try:
        r = c.post("/ask", json={"question": "how many", "date": "2026-09-10",
                                 "history": [{"role": "user", "content": "a"},
                                             {"role": "system", "x": 1},
                                             "junk"]})
        assert r.status_code == 200 and r.get_json()["answer"] == "42"
        assert seen["history"] == [{"role": "user", "content": "a"}]
        assert seen["date"] == "2026-09-10"

        def no_key(*a, **k):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        board_server.ask.answer = no_key
        r = c.post("/ask", json={"question": "hi"})
        assert r.status_code == 503 and "API_KEY" in r.get_json()["error"]

        def boom(*a, **k):
            raise ValueError("overloaded")
        board_server.ask.answer = boom
        r = c.post("/ask", json={"question": "hi"})
        assert r.status_code == 502 and "overloaded" in r.get_json()["error"]
    finally:
        board_server.ask.answer = orig
