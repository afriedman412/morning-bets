"""Local Flask app to browse daily bets + results."""
from __future__ import annotations

import json
import webbrowser
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from threading import Timer

from flask import Flask, abort, render_template

from src import db

PROJECT_ROOT = Path(__file__).resolve().parent.parent

app = Flask(
    __name__,
    template_folder=str(PROJECT_ROOT / "templates"),
    static_folder=str(PROJECT_ROOT / "static"),
)


def _dates_with_bets() -> list[dict]:
    with db.connect() as c:
        rows = c.execute("""
            SELECT date,
                COUNT(*) AS total,
                SUM(result='W') AS wins,
                SUM(result='L') AS losses,
                SUM(result='PUSH') AS pushes,
                SUM(result='PENDING') AS pending,
                SUM(result='UNGRADABLE') AS ungradable
            FROM bets GROUP BY date ORDER BY date DESC
        """).fetchall()
    return [dict(r) for r in rows]


def _games_for_date(date_str: str) -> dict[str, dict]:
    with db.connect() as c:
        rows = c.execute(
            "SELECT * FROM games WHERE date=?", (date_str,),
        ).fetchall()
    return {r["game_id"]: dict(r) for r in rows}


def _sources_for_date(date_str: str) -> list[dict]:
    """Read per-source video info from the JSON cache."""
    fn = date_str.replace("-", "_")
    p = PROJECT_ROOT / "bets" / f"{fn}.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except Exception:
        return []
    return [
        {
            "label": s.get("label", ""),
            "title": s.get("title", ""),
            "video_id": s.get("video_id", ""),
            "url": f"https://www.youtube.com/watch?v={s.get('video_id', '')}",
        }
        for s in data
    ]


def _bets_for_date(date_str: str) -> list[dict]:
    with db.connect() as c:
        rows = c.execute(
            "SELECT * FROM bets WHERE date=? "
            "ORDER BY matchup, source_label, id",
            (date_str,),
        ).fetchall()
    return [dict(r) for r in rows]


def _format_bet(b: dict) -> str:
    """Short human-readable HTML description of a bet."""
    inferred = bool(b.get("line_inferred"))

    def _line(val: float) -> str:
        s = str(val)
        if inferred:
            return f'<i>{s}</i> <span class="inferred">(inferred)</span>'
        return s

    if b["bet_type"] == "ml":
        return f"{b['side']} ML"
    if b["bet_type"] == "spread":
        if b["line"] is None:
            return f"{b['side']} spread"
        sign = "+" if b["line"] > 0 else ""
        return f"{b['side']} {sign}{_line(b['line'])}"
    if b["bet_type"] == "total":
        side = (b["side"] or "").title()
        return side if b["line"] is None else f"{side} {_line(b['line'])}"
    parts = []
    if b["player_name"]:
        parts.append(b["player_name"])
    parts.append(b["stat"] or "")
    if b["side"]:
        parts.append(b["side"])
    if b["line"] is not None:
        parts.append(_line(b["line"]))
    return " ".join(p for p in parts if p)


@app.route("/")
def index():
    days = _dates_with_bets()
    return render_template("index.html", days=days, all_days=days)


@app.route("/<date_str>/")
@app.route("/<date_str>/<view>/")
def day(date_str: str, view: str = "game"):
    if view not in ("game", "source"):
        abort(404)
    try:
        nice = datetime.strptime(date_str, "%Y-%m-%d") \
            .strftime("%A %-m/%-d/%y")
    except ValueError:
        abort(404)

    bets = _bets_for_date(date_str)
    if not bets:
        abort(404)
    games = _games_for_date(date_str)

    enriched = [{**b, "description": _format_bet(b)} for b in bets]

    def _final(matchup: str) -> str | None:
        for g in games.values():
            away = (g["away_team"] or "").lower()
            home = (g["home_team"] or "").lower()
            mlow = (matchup or "").lower()
            if (away.split()[-1] in mlow and home.split()[-1] in mlow):
                if g.get("away_score") is not None \
                        and "final" in (g["status"] or "").lower():
                    a = g.get("away_team_abbr") or g["away_team"]
                    h = g.get("home_team_abbr") or g["home_team"]
                    return (f"Final: {a} {g['away_score']} - "
                            f"{h} {g['home_score']}")
        return None

    if view == "source":
        # Two-level group: source -> matchup -> bets
        src_groups: dict[str, dict[str, list[dict]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for b in enriched:
            src_groups[b["source_label"]][
                b["matchup"] or "(no matchup)"
            ].append(b)
        rendered_groups = sorted(
            [
                (
                    src,
                    None,
                    sorted(
                        [(m, _final(m), bs) for m, bs in matchups.items()],
                        key=lambda x: (-len(x[2]), x[0]),
                    ),
                )
                for src, matchups in src_groups.items()
            ],
            key=lambda x: (
                -sum(len(bs) for _, _, bs in x[2]),
                x[0],
            ),
        )
    else:
        # Group by matchup (default)
        groups: dict[str, list[dict]] = defaultdict(list)
        for b in enriched:
            groups[b["matchup"] or "(no matchup)"].append(b)
        rendered_groups = sorted(
            [(m, _final(m), bs) for m, bs in groups.items()],
            key=lambda x: (-len(x[2]), x[0]),
        )

    counts = {
        "W": sum(1 for b in bets if b["result"] == "W"),
        "L": sum(1 for b in bets if b["result"] == "L"),
        "PUSH": sum(1 for b in bets if b["result"] == "PUSH"),
        "PENDING": sum(1 for b in bets if b["result"] == "PENDING"),
        "UNGRADABLE": sum(1 for b in bets if b["result"] == "UNGRADABLE"),
        "TOTAL": len(bets),
    }

    return render_template(
        "day.html",
        date_str=date_str,
        nice=nice,
        groups=rendered_groups,
        counts=counts,
        view=view,
        sources=_sources_for_date(date_str),
        all_days=_dates_with_bets(),
    )


def build_static(out_dir: Path) -> int:
    """Render every page to static HTML in out_dir. Returns file count."""
    db.init()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    with app.test_client() as c:
        resp = c.get("/")
        (out_dir / "index.html").write_bytes(resp.data)
        written += 1
        for d in _dates_with_bets():
            date_str = d["date"]
            day_dir = out_dir / date_str
            day_dir.mkdir(exist_ok=True)
            for view_path, view_name in (("/", "game"), ("/source/", "source")):
                resp = c.get(f"/{date_str}{view_path}")
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"failed to render {date_str}/{view_name}: "
                        f"{resp.status_code}"
                    )
                target = day_dir if view_name == "game" \
                    else day_dir / "source"
                target.mkdir(exist_ok=True)
                (target / "index.html").write_bytes(resp.data)
                written += 1
    return written


def main() -> None:
    db.init()
    url = "http://127.0.0.1:5050"
    print(f"Morning Bets viewer → {url}")
    Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=5050, debug=False)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        out = Path(sys.argv[2]) if len(sys.argv) > 2 \
            else PROJECT_ROOT / "site"
        n = build_static(out)
        print(f"Wrote {n} files to {out}")
    else:
        main()
