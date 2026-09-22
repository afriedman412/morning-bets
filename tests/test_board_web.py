"""The board's web layer: file discovery, the served page, drift checks.

Three modules, one seam: `boards.py` decides which JSON is the board of
record, `board_server` renders it behind a sidebar, `check_updates`
compares it to the live slate. All checks here run on fixture payloads —
no network, no real bets/ files — and each was verified by mutation
(break the guarded behaviour, watch that check alone fail).
"""
from __future__ import annotations

import json
import os
import tempfile

from scratchpad import boards, check_updates
from scratchpad.gen_board_html import build


def _row(bet, cls, gap, p_over=0.55, **kw):
    r = {"bet": bet, "cls": cls, "over": "-120", "under": "+120",
         "kalshi": None if gap is None else "+100",
         "offband": False, "thin": False, "proj": False, "gate": None,
         "raw": None, "vol": 1000.0, "bump": False,
         "p_over": p_over,
         "p_kalshi": None if gap is None else round(p_over - gap / 100, 4),
         "gap": gap}
    r.update(kw)
    return r


def _payload(n_gaps=16):
    """One game whose rows carry n_gaps distinct non-None gaps."""
    rows = [_row("total 8.5", "total", None)]
    rows += [_row(f"Arm One k {i % 8 + 1}.5", "k", 2.0 + i)
             for i in range(n_gaps)]
    return {"date": "2026-09-19", "sims": 20000,
            "games": [{"away": "AAA", "home": "BBB", "ap": "Arm One",
                       "hp": "Arm Two", "lineups": "PROJECTED lineups",
                       "mean": 9.0, "rows": rows}],
            "declined": [], "lineups_posted": 0, "games_scheduled": 1}


# ── boards.py — which file is the board of record ──────────────────────


def check_board_of_record_is_newest_by_mtime_not_by_name():
    """A date's re-runs (_v2, _v3) supersede by WRITE TIME. Naming is
    not ordered — `_board.json` re-written after `_board_v2.json` is the
    record — and non-board JSONs (plans, probables, the old flat
    day files) must never be picked up."""
    with tempfile.TemporaryDirectory() as td:
        for name, when in (("2026_09_19_board_v2.json", 100),
                           ("2026_09_19_board.json", 200),
                           ("2026_09_18_board.json", 50),
                           ("2026_09_18.json", 999),      # old betting layer
                           ("plans.json", 999)):
            p = os.path.join(td, name)
            with open(p, "w") as f:
                json.dump({}, f)
            os.utime(p, (when, when))
        files = boards.board_files(td)
        assert sorted(files) == ["2026-09-18", "2026-09-19"], files
        rec = boards.board_of_record("2026-09-19", td)
        assert os.path.basename(rec) == "2026_09_19_board.json", rec
        assert boards.board_of_record("2026-09-01", td) is None


# ── gen_board_html — every disagreement, filtered client-side ──────────


def check_disagreement_table_carries_every_gap_not_a_top_n():
    """The lead table renders ALL rungs with a mid, each stamped with
    data-agap for the threshold input; the old top-12 cut is gone. The
    no-mid rung stays out (nothing to disagree with)."""
    page = build(_payload(n_gaps=16))
    assert page.count("data-agap=") == 2 * 16, page.count("data-agap=")
    assert 'id="gap-min"' in page and 'id="t-lead"' in page
    assert "of 16 rungs" in page
    # the odds-band filter needs both probabilities on every gap row
    assert page.count("data-po=") == 2 * 16 == page.count("data-pk=")
    assert 'id="odds-max"' in page


def check_k_table_rows_carry_the_diff_for_the_threshold_input():
    """Each fitted arm's row is stamped with |our line - market line| so
    the kdiff-min input can filter, and the count names the arm total."""
    d = _payload(n_gaps=0)
    # a ladder that crosses even money on both sides, so k_table fits it
    d["games"][0]["rows"] += [
        _row(f"Arm One k {ln}", "k", 5.0, p_over=po)
        for ln, po in ((3.5, 0.80), (4.5, 0.65), (5.5, 0.52),
                       (6.5, 0.40), (7.5, 0.30))]
    page = build(d)
    assert 'id="kdiff-min"' in page and 'id="t-k"' in page
    assert page.count("data-adiff=") == 1, page.count("data-adiff=")
    assert "of 1 arms" in page


def check_gated_rows_never_lead_the_board():
    """A flagged arm's gap is mostly our own leash error; its row prints
    in the game block, chip attached, but stays out of the ranked list."""
    d = _payload(n_gaps=4)
    d["games"][0]["rows"][2]["gate"] = "opener"
    page = build(d)
    assert "of 3 rungs" in page, "gated row leaked into the ranked count"


def check_nav_renders_only_when_the_server_passes_one():
    """The static path must keep producing the sidebar-free page."""
    static = build(_payload())
    served = build(_payload(), nav='<p class="side-title">Boards</p>')
    assert '<nav class="side">' not in static
    assert '<div class="layout">' in static
    assert '<nav class="side">' in served
    assert '<div class="layout has-side">' in served


# ── check_updates — drift against the board and the last snapshot ──────


def _live(away_starter="Arm One", lineups=False, extra=None):
    def side(abbr, starter):
        return {"abbr": abbr, "starter": starter, "starter_id": 1,
                "lineup": [f"{abbr} batter {i}" for i in range(9)]
                if lineups else []}
    games = [{"away": side("AAA", away_starter),
              "home": side("BBB", "Arm Two")}]
    if extra:
        games.append({"away": side(extra[0], "X"),
                      "home": side(extra[1], "Y")})
    return games


def check_board_diff_flags_each_drift_and_only_drift():
    board = _payload()
    assert check_updates.diff_board(board, _live()) == []
    # starter swapped out from under the priced arm
    got = check_updates.diff_board(board, _live(away_starter="Arm Nine"))
    assert any("Arm Nine" in x and "Arm One" in x for x in got), got
    # lineups posted while the board is projected -> re-run
    got = check_updates.diff_board(board, _live(lineups=True))
    assert any("re-run" in x for x in got), got
    # a matchup the board never mentioned, and one that vanished
    got = check_updates.diff_board(board, _live(extra=("CCC", "DDD")))
    assert any("not on the board" in x for x in got), got
    got = check_updates.diff_board(board, [])
    assert any("gone from the slate" in x for x in got), got
    # a declined matchup on the slate is already named, not news
    board["declined"] = ["CCC @ DDD — X / Y: no probable posted"]
    got = check_updates.diff_board(board, _live(extra=("CCC", "DDD")))
    assert got == [], got


def check_snapshot_diff_reports_changes_never_first_sightings():
    prev = check_updates.snapshot(_live())
    assert check_updates.diff_snapshot({}, prev) == []
    got = check_updates.diff_snapshot(
        prev, check_updates.snapshot(_live(away_starter="Arm Nine")))
    assert any("Arm One -> Arm Nine" in x for x in got), got
    cur = check_updates.snapshot(_live(lineups=True))
    got = check_updates.diff_snapshot(prev, cur)
    assert any("lineup posted" in x for x in got), got
    # one name swapped inside a posted nine
    cur2 = json.loads(json.dumps(cur))
    cur2["AAA @ BBB"]["home"]["lineup"][3] = "BBB pinch"
    got = check_updates.diff_snapshot(cur, cur2)
    assert any("out: BBB batter 3" in x and "in: BBB pinch" in x
               for x in got), got
    assert check_updates.diff_snapshot(cur, cur) == []


# ── board_server — routes and the sidebar ──────────────────────────────


def check_server_serves_dates_versions_and_the_sidebar():
    """/ redirects to the newest date; a date page carries the sidebar
    with per-game anchors; ?src reaches an older version; junk 404s."""
    from scratchpad import board_server
    with tempfile.TemporaryDirectory() as td:
        old = _payload()
        old["games"][0]["ap"] = "Old Arm"
        for name, payload, when in (
                ("2026_09_18_board.json", _payload(), 50),
                ("2026_09_19_board.json", old, 100),
                ("2026_09_19_board_v2.json", _payload(), 200)):
            p = os.path.join(td, name)
            with open(p, "w") as f:
                json.dump(payload, f)
            os.utime(p, (when, when))
        orig = boards.BETS_DIR
        boards.BETS_DIR = td
        try:
            c = board_server.app.test_client()
            r = c.get("/")
            assert r.status_code == 302 and "2026-09-19" in r.location, \
                (r.status_code, r.location)
            r = c.get("/board/2026-09-19")
            body = r.get_data(as_text=True)
            assert r.status_code == 200
            assert '<nav class="side">' in body and "#g-AAA-BBB" in body
            assert "/board/2026-09-18" in body, "other dates missing"
            assert "Arm One" in body and "Old Arm" not in body, \
                "record must be the newest file"
            r = c.get("/board/2026-09-19?src=2026_09_19_board.json")
            assert "Old Arm" in r.get_data(as_text=True)
            assert c.get("/board/2026-01-01").status_code == 404
            assert c.get("/board/2026-09-19?src=nope.json"
                         ).status_code == 404
        finally:
            boards.BETS_DIR = orig


# ── the CLV column — a readout, and blank is not zero ───────────────────

def check_clv_token_round_trips_through_the_printed_note():
    """`board` prints it into the note, `board_json` reads it back.

    The two live in different modules and the only thing joining them is
    this token, so a format change in one is silent in the other.
    """
    import re
    from scratchpad import board
    for cents in (3.2, -1.0, 0.0, 12.5):
        tok = board._clv(cents / 100)
        m = re.search(r"clv ([+-][\d.]+)c", tok)
        assert m, tok
        assert abs(float(m.group(1)) - cents) < 1e-9, (tok, cents)


def check_a_note_without_clv_parses_to_none_not_zero():
    """An untraded rung and a rung that has not moved must not agree.

    None means there was no opening trade to diff against; 0.0 means the
    market opened here and stayed. Collapsing them would put every
    illiquid rung into the 'market agrees with us' bucket.
    """
    import re
    pat = r"clv ([+-][\d.]+)c"
    assert re.search(pat, "vol $8.5k  THIN") is None
    assert re.search(pat, "vol $8.5k  clv +0.0c") is not None


def check_the_clv_cell_tells_blank_from_flat():
    from scratchpad.gen_board_html import clv_cell
    blank = clv_cell({"vol": 10.0})
    flat = clv_cell({"clv": 0.0})
    moved = clv_cell({"clv": 0.032})
    assert "c-none" in blank and "&mdash;" in blank, blank
    assert "c-none" not in flat and "+0.0c" in flat, flat
    assert "+3.2c" in moved, moved
    assert "under" in clv_cell({"clv": -0.015}), "a fall must read as under"


def check_a_legacy_board_without_clv_still_renders():
    """Every board JSON written before the column existed lacks the key
    entirely, and the page must not 500 on them."""
    p = _payload()
    for g in p["games"]:
        for r in g["rows"]:
            r.pop("clv", None)
    html = build(p)
    n_rows = sum(len(g["rows"]) for g in p["games"])
    assert '<th class="c-clv">clv</th>' in html
    # A row can render in two tables (the disagreement list and its own
    # game), so this is a floor, not an equality.
    assert html.count("c-clv c-none") >= n_rows, html.count("c-clv c-none")
    assert "c</td>" not in html, "a missing key rendered as a number"


def check_opens_drops_a_market_with_no_pregame_trade():
    """`_opens` must omit, never invent. A market that never traded
    before first pitch has no opening number, and one dead fetch must
    not cost the rest of the board."""
    from scratchpad import board
    calls = {"a": {"open_prob": 0.41, "close_prob": 0.44, "clv": 0.03},
             "b": None}

    real = board.kalshi.price_path
    board.kalshi.price_path = lambda tk, side: (
        calls[tk] if tk in calls else (_ for _ in ()).throw(RuntimeError("x")))
    try:
        got = board._opens({("prop", "k", "A", 4.5): "a",
                            ("prop", "k", "B", 4.5): "b",
                            ("prop", "k", "C", 4.5): "boom"}, workers=2)
    finally:
        board.kalshi.price_path = real
    assert got == {("prop", "k", "A", 4.5): 0.41}, got


# ── /board auto-versions, and grading follows the page ──────────────────

def check_next_stem_never_hands_back_a_taken_name():
    """A pull must not overwrite the pull before it: the morning number
    IS the comparison. Numbering is off the highest version seen, so a
    deleted middle version cannot resurrect a used name."""
    with tempfile.TemporaryDirectory() as d:
        def stem():
            return os.path.basename(boards.next_stem("2026-09-20", d))
        assert stem() == "2026_09_20_board"
        open(os.path.join(d, "2026_09_20_board.json"), "w").close()
        assert stem() == "2026_09_20_board_v2"
        for v in (2, 3, 7):
            open(os.path.join(d, f"2026_09_20_board_v{v}.json"), "w").close()
        assert stem() == "2026_09_20_board_v8", stem()
        os.remove(os.path.join(d, "2026_09_20_board_v3.json"))
        assert stem() == "2026_09_20_board_v8", "reused a name that existed"

        # A FAILED PULL LEAVES ONLY A .txt, AND STILL CLAIMS ITS NUMBER.
        # Versioning off .json alone made failures invisible to the next
        # run: 2026-09-21 fired five times, died at the board step each
        # time and handed back `_v2` four runs running, each overwriting
        # the last one's text. The first version of this check created
        # only .json files and sailed past it.
        open(os.path.join(d, "2026_09_20_board_v8.txt"), "w").close()
        assert stem() == "2026_09_20_board_v9", stem()


def check_next_stem_is_per_date():
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "2026_09_20_board.json"), "w").close()
        assert os.path.basename(
            boards.next_stem("2026-09-21", d)) == "2026_09_21_board"


def check_grading_and_the_page_pick_the_same_board():
    """The silent one. `grade_boards` used to skip any tag outside its
    VERSION_RANK list, so an auto-versioned `_v4` would render on the
    page while grading scored a stale morning board, with no error."""
    import time
    from scratchpad import grade_boards
    with tempfile.TemporaryDirectory() as d:
        for fn in ("2026_09_19_board.json", "2026_09_19_board_v2.json",
                   "2026_09_19_board_v4.json", "2026_09_19_board_v5.json"):
            with open(os.path.join(d, fn), "w") as f:
                json.dump({"date": "2026-09-19", "games": []}, f)
            time.sleep(0.02)
        served = boards.board_of_record("2026-09-19", d)
        graded = grade_boards.pick_boards("2026-09-30", bets_dir=d)
        assert os.path.basename(graded["2026-09-19"]) \
            == os.path.basename(served) == "2026_09_19_board_v5.json", graded


def check_a_known_tag_still_outranks_by_the_published_order():
    """`pm` beats `v2` by the list, not by mtime — the old behaviour for
    every stem that already existed must not change."""
    import time
    from scratchpad import grade_boards
    with tempfile.TemporaryDirectory() as d:
        for fn in ("2026_09_19_board_pm.json", "2026_09_19_board_v2.json"):
            with open(os.path.join(d, fn), "w") as f:
                json.dump({"date": "2026-09-19", "games": []}, f)
            time.sleep(0.02)   # v2 is NEWER on disk, pm must still win
        got = grade_boards.pick_boards("2026-09-30", bets_dir=d)
        assert os.path.basename(got["2026-09-19"]) \
            == "2026_09_19_board_pm.json", got
