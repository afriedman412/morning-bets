"""Checks for the hourly market/slate collector.

OFFLINE, like the rest of the suite: `snapshot` takes both fetchers as
arguments and every check here injects them.
"""
from __future__ import annotations

import gzip
import json
import os
import tempfile

from scratchpad import ticks


def _slate_row(gid, away_lu=(), home_lu=(), away_sp="A", home_sp="H",
               status="Scheduled"):
    return {"game_id": gid, "status": status,
            "away": {"abbr": "AAA", "starter": away_sp,
                     "lineup": list(away_lu)},
            "home": {"abbr": "HHH", "starter": home_sp,
                     "lineup": list(home_lu)}}


def check_append_and_read_round_trip():
    with tempfile.TemporaryDirectory() as d:
        a = {"t": "2026-09-19T14:00:00Z", "date": "2026-09-19", "slate": [],
             "markets": {}, "failed": {}}
        b = dict(a, t="2026-09-19T15:00:00Z")
        ticks.append(a, d)
        ticks.append(b, d)
        got = ticks.read_day("2026-09-19", d)
        assert [r["t"] for r in got] == [a["t"], b["t"]], got


def check_append_never_rewrites_an_earlier_record():
    """A second append must leave the first byte-identical.

    The whole point of gzip members over a rewritten file: a crash can
    cost the current hour and nothing already banked.
    """
    with tempfile.TemporaryDirectory() as d:
        rec = {"t": "1", "date": "2026-09-19", "slate": [], "markets": {},
               "failed": {}}
        p = ticks.append(rec, d)
        first = open(p, "rb").read()
        ticks.append(dict(rec, t="2"), d)
        after = open(p, "rb").read()
        assert after[:len(first)] == first, "earlier member was rewritten"
        assert len(ticks.read_day("2026-09-19", d)) == 2


def check_read_day_is_empty_when_nothing_is_stored():
    with tempfile.TemporaryDirectory() as d:
        assert ticks.read_day("2026-09-19", d) == []


def check_a_posted_lineup_is_a_change_and_an_empty_one_is_not():
    prev = ticks.lineup_state([_slate_row("g1")])
    same = ticks.lineup_state([_slate_row("g1")])
    assert ticks.changes(prev, same) == []

    cur = ticks.lineup_state([_slate_row("g1", away_lu=list("123456789"))])
    ch = ticks.changes(prev, cur)
    assert len(ch) == 1, ch
    assert ch[0]["kind"] == "lineup_posted" and ch[0]["side"] == "away"


def check_a_swap_after_posting_is_a_change_too():
    """Lineups are state, not an event — the second move must register."""
    posted = ticks.lineup_state([_slate_row("g1", away_lu=list("123456789"))])
    swapped = ticks.lineup_state(
        [_slate_row("g1", away_lu=list("12345678") + ["X"])])
    ch = ticks.changes(posted, swapped)
    assert [c["kind"] for c in ch] == ["lineup_changed"], ch


def check_a_scratched_starter_registers():
    """Not additive: a late scratch reprices the whole game."""
    prev = ticks.lineup_state([_slate_row("g1", away_sp="Gasser")])
    cur = ticks.lineup_state([_slate_row("g1", away_sp="Someone Else")])
    ch = ticks.changes(prev, cur)
    assert [c["kind"] for c in ch] == ["starter"], ch
    assert ch[0]["was"] == "Gasser" and ch[0]["now"] == "Someone Else"


def check_a_game_seen_for_the_first_time_is_not_a_change():
    prev = ticks.lineup_state([_slate_row("g1")])
    cur = ticks.lineup_state([_slate_row("g1"),
                              _slate_row("g2", away_lu=list("123456789"))])
    assert ticks.changes(prev, cur) == []


def check_a_failed_series_is_recorded_and_the_rest_are_kept():
    """The hour cannot be re-fetched, so a partial snapshot is still
    written — but `failed` must carry the reason."""
    def bad(series):
        if series == "KXMLBHR":
            raise RuntimeError("502")
        return [{"ticker": series + "-1"}]

    rec = ticks.snapshot("2026-09-19", fetch_slate=lambda d: [_slate_row("g1")],
                         fetch_markets=bad)
    assert "KXMLBHR" in rec["failed"], rec["failed"]
    assert "RuntimeError: 502" in rec["failed"]["KXMLBHR"]
    assert "KXMLBHR" not in rec["markets"]
    assert len(rec["markets"]) >= 10, len(rec["markets"])
    assert rec["slate"], "a series failure must not lose the slate"


def check_a_failed_slate_does_not_lose_the_markets():
    def boom(_):
        raise RuntimeError("nope")

    rec = ticks.snapshot("2026-09-19", fetch_slate=boom,
                         fetch_markets=lambda s: [{"ticker": s}])
    assert rec["failed"]["slate"].startswith("RuntimeError")
    assert rec["markets"], "slate failure emptied the markets"


def check_main_exits_nonzero_when_anything_failed():
    """Banked, then loud. The previous scheduled jobs here died by
    exiting quietly into a log nobody read."""
    import io
    import contextlib
    with tempfile.TemporaryDirectory() as d:
        real_dir, ticks.TICKS_DIR = ticks.TICKS_DIR, d
        real_snap = ticks.snapshot
        try:
            ticks.snapshot = lambda date, **kw: {
                "t": "2026-09-19T14:00:00Z", "date": date, "slate": [],
                "markets": {"A": []}, "failed": {"B": "boom"}}
            buf, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                rc = ticks.main([])
            assert rc == 1, rc
            assert "FAILED B" in err.getvalue(), err.getvalue()
            # and it still banked the hour
            date = ticks.dt.date.today().isoformat()
            assert len(ticks.read_day(date, d)) == 1
        finally:
            ticks.snapshot = real_snap
            ticks.TICKS_DIR = real_dir


def check_the_record_stores_raw_market_rows():
    """Whole rows, not a parsed subset — Kalshi has renamed the
    top-of-book schema once already."""
    row = {"ticker": "T-1", "yes_bid_dollars": "0.41",
           "yes_ask_dollars": "0.44", "volume": 12, "some_new_field": 9}
    rec = ticks.snapshot("2026-09-19", fetch_slate=lambda d: [],
                         fetch_markets=lambda s: [row])
    stored = rec["markets"]["KXMLBTOTAL"][0]
    assert stored == row, stored


def check_ticks_stays_out_of_the_model():
    """CLV is not the objective. Nothing under src/, and nothing in the
    scoring path, may import this collector."""
    import pathlib
    root = pathlib.Path(ticks.ROOT).resolve()
    offenders = []
    targets = list((root / "src").rglob("*.py"))
    targets += [root / "scratchpad" / n for n in
                ("battery.py", "fingerprint.py")]
    targets += list((root / "src" / "context").glob("fitf5.py"))
    for p in targets:
        if not p.exists():
            continue
        txt = p.read_text()
        if "scratchpad.ticks" in txt or "import ticks" in txt:
            offenders.append(str(p.relative_to(root)))
    assert not offenders, f"the price series reached the model: {offenders}"


def check_the_series_list_covers_props_and_game_levels():
    from scratchpad import kalshi
    got = set(ticks._series())
    assert set(kalshi.GAME_SERIES.values()) <= got, got
    assert set(kalshi.SERIES_BY_STAT.values()) <= got, got


def check_a_record_is_one_line_of_valid_json():
    """`--show` and anything downstream read it line by line."""
    with tempfile.TemporaryDirectory() as d:
        rec = {"t": "x", "date": "2026-09-19", "slate": [_slate_row("g1")],
               "markets": {"A": [{"ticker": "t"}]}, "failed": {}}
        p = ticks.append(rec, d)
        with gzip.open(p, "rt", encoding="utf-8") as f:
            lines = [ln for ln in f.read().split("\n") if ln.strip()]
        assert len(lines) == 1, lines
        assert json.loads(lines[0])["date"] == "2026-09-19"


def check_the_tick_dir_is_not_under_dot_cache():
    """`.cache/` reads as safe-to-delete and this tree cannot be rebuilt."""
    assert ".cache" not in ticks.TICKS_DIR.replace(os.sep, "/"), ticks.TICKS_DIR
    assert os.path.basename(ticks.TICKS_DIR.rstrip(os.sep)) == "ticks"
