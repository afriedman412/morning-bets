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
