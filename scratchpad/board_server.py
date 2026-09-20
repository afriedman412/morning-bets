"""Serve every board from one Flask app instead of one-off HTML files.

    venv/bin/python -m scratchpad.board_server [--port 8060]

Reads the same `bets/*_board*.json` files `gen_board_html` reads and
renders the same page — this module adds no numbers, only navigation. The
sidebar lists every date with a board; a date expands into the page's
sections (K model, disagreements, first five, each game) and clicking
through lands on the same anchors the static page already carries. The
static path (`-m scratchpad.gen_board_html`) still works and renders
without the sidebar; the page-building code lives there and only there,
so the two cannot drift.

Where a date has several JSONs (a re-run after lineups post writes
`_v2`, `_v3`) the newest by mtime is the board of record — `boards.py`
decides, the same answer `check_updates` compares against. Older
versions stay reachable through the version links in the sidebar.

Pages re-render per request straight off the JSON (a few ms); nothing is
cached, so a re-run of the board shows up on the next refresh.

ONE ROUTE ADDS NUMBERS AND IT IS NOT A PAGE: POST /ask hands a question
to `scratchpad.ask`, which answers it out of tool calls over the board
JSONs and the two databases. It is the only thing here that costs money
per request and the only thing that reaches the network, so it is a
separate route rather than something the page does on load, and a missing
API key comes back as a sentence in the panel rather than a 500.
"""
from __future__ import annotations

import html
import os
import sys

from flask import Flask, abort, jsonify, redirect, request

from scratchpad import ask, boards
from scratchpad.gen_board_html import build

app = Flask(__name__)


def _short(iso: str) -> str:
    from datetime import date as _d
    y, m, dd = (int(x) for x in iso.split("-"))
    return _d(y, m, dd).strftime("%a %-d %b")


SECTIONS = (("k-model", "K model"), ("disagreements", "Disagreements"),
            ("f5", "First five"), ("games", "Every game"))


def _nav(active_date: str, active_path: str) -> str:
    """The sidebar: every date, the active one expanded into sections."""
    files = boards.board_files()
    out = ['<p class="side-title">Boards</p>']
    for d in sorted(files, reverse=True):
        url = f"/board/{d}"
        label = _short(d)
        if d != active_date:
            out.append(f'<details class="side-date"><summary>'
                       f'<a href="{url}">{label}</a></summary>'
                       f'<ul>{_sections(url)}</ul></details>')
            continue
        items = _sections("")
        try:
            games = boards.load(active_path)["games"]
            items += '<li class="side-sub">games</li>' + "".join(
                f'<li><a href="#g-{g["away"]}-{g["home"]}">'
                f'{g["away"]} @ {g["home"]}</a></li>' for g in games)
        except Exception:
            pass  # a malformed file still gets its section links
        vs = files[d]
        if len(vs) > 1:
            items += '<li class="side-sub">versions</li>' + "".join(
                f'<li><a href="{url}?src={html.escape(os.path.basename(p))}">'
                f'{html.escape(_vlabel(p))}</a></li>' for p in vs)
        out.append(f'<details class="side-date" open><summary>'
                   f'<a href="{url}">{label}</a></summary>'
                   f'<ul>{items}</ul></details>')
    return "".join(out)


def _sections(prefix: str) -> str:
    return "".join(f'<li><a href="{prefix}#{a}">{t}</a></li>'
                   for a, t in SECTIONS)


def _vlabel(path: str) -> str:
    stem = os.path.basename(path).removesuffix(".json")
    return stem.split("board", 1)[-1].strip("_") or "board"


@app.get("/")
def index():
    files = boards.board_files()
    if not files:
        abort(404, "no board JSONs under bets/")
    return redirect(f"/board/{max(files)}")


@app.get("/board/<date>")
def board(date):
    files = boards.board_files()
    paths = files.get(date)
    if not paths:
        abort(404, f"no board for {date}")
    path = paths[-1]
    src = request.args.get("src")
    if src:  # an older version, picked from the sidebar's version list
        match = [p for p in paths if os.path.basename(p) == src]
        if not match:
            abort(404, f"no version {src} for {date}")
        path = match[0]
    return build(boards.load(path), nav=_nav(date, path), chat=True)


@app.post("/ask")
def ask_route():
    """A question from the panel, answered with the lookup trace."""
    body = request.get_json(silent=True) or {}
    q = (body.get("question") or "").strip()
    if not q:
        return jsonify(error="ask something"), 400
    if len(q) > 2000:
        return jsonify(error="question too long"), 400
    history = [m for m in (body.get("history") or [])
               if isinstance(m, dict) and m.get("role") in ("user",
                                                            "assistant")
               and isinstance(m.get("content"), str)]
    try:
        return jsonify(ask.answer(q, history=history, date=body.get("date")))
    except RuntimeError as e:      # no key, no anthropic package
        return jsonify(error=str(e)), 503
    except Exception as e:         # an API failure is the panel's problem
        return jsonify(error=f"{type(e).__name__}: {e}"), 502


def main(argv):
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8060
    n = len(boards.board_files())
    print(f"serving {n} board dates on http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main(sys.argv[1:])
