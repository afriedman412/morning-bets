"""Local Flask app to browse daily bets + results."""
from __future__ import annotations

import json
import re
import webbrowser
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from threading import Timer

from flask import Flask, abort, redirect, render_template, request

from src import db, mybets
from src.panel import bankroll_status

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
    period = (b.get("period") or "full")
    prefix = "F5 " if period == "f5" else ""

    def _line(val: float) -> str:
        s = str(val)
        if inferred:
            return f'<i>{s}</i> <span class="inferred">(inferred)</span>'
        return s

    if b["bet_type"] == "ml":
        return f"{prefix}{b['side']} ML"
    if b["bet_type"] == "spread":
        if b["line"] is None:
            return f"{prefix}{b['side']} spread"
        sign = "+" if b["line"] > 0 else ""
        return f"{prefix}{b['side']} {sign}{_line(b['line'])}"
    if b["bet_type"] == "total":
        side = (b["side"] or "").title()
        if b["line"] is None:
            return f"{prefix}{side}".strip()
        return f"{prefix}{side} {_line(b['line'])}".strip()
    if b["bet_type"] == "team_total":
        team = b["player_name"] or ""
        side = (b["side"] or "").title()
        if b["line"] is None:
            return f"{prefix}{team} team total {side}".strip()
        return f"{prefix}{team} team total {side} {_line(b['line'])}".strip()
    parts = []
    if b["player_name"]:
        parts.append(b["player_name"])
    parts.append(b["stat"] or "")
    if b["side"]:
        parts.append(b["side"])
    if b["line"] is not None:
        parts.append(_line(b["line"]))
    return " ".join(p for p in parts if p)


def _slugify(label: str) -> str:
    """URL-safe slug for a source_label (deterministic, reversible via scan)."""
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def _roster() -> list[dict]:
    """All source_labels with a stable slug, busiest first.

    Panel members (staked bets) are flagged so the UI can group them with,
    but still distinguish them from, the YouTube cappers.
    """
    with db.connect() as c:
        rows = c.execute(
            "SELECT source_label AS label, COUNT(*) AS n, "
            "SUM(stake_cents IS NOT NULL) AS staked "
            "FROM bets GROUP BY source_label ORDER BY n DESC"
        ).fetchall()
    return [
        {
            "label": r["label"],
            "slug": _slugify(r["label"]),
            "n": r["n"],
            "is_panel": bool(r["staked"]),
        }
        for r in rows
    ]


def _label_for_slug(slug: str) -> str | None:
    for r in _roster():
        if r["slug"] == slug:
            return r["label"]
    return None


def _history_by_day(bankroll: dict) -> list[dict]:
    """Group a bankroll_status() history into per-day rows, newest first."""
    by_day: dict[str, dict] = {}
    for h in bankroll["history"]:
        d = by_day.setdefault(
            h["date"],
            {"date": h["date"], "picks": [], "staked_cents": 0,
             "profit_cents": 0, "close_cents": 0},
        )
        d["picks"].append(h)
        if h.get("stake_cents"):
            d["staked_cents"] += h["stake_cents"]
        d["profit_cents"] += h["profit_cents"]
        d["close_cents"] = h["bankroll_after_cents"]
    return sorted(by_day.values(), key=lambda x: x["date"], reverse=True)


@app.context_processor
def _inject_roster():
    """Make the capper/panel roster available to every template's sidebar."""
    return {"roster": _roster(), "source_slug": _slugify}


@app.route("/")
def index():
    days = _dates_with_bets()
    return render_template("index.html", days=days, all_days=days)


def _format_cents(cents: int | None) -> str:
    if cents is None:
        return "—"
    sign = "-" if cents < 0 else ""
    dollars = abs(cents) / 100
    return f"{sign}${dollars:,.2f}"


@app.template_filter("money")
def _money_filter(cents: int | None) -> str:
    return _format_cents(cents)


@app.template_filter("signed_money")
def _signed_money_filter(cents: int | None) -> str:
    if cents is None:
        return "—"
    if cents == 0:
        return "$0"
    sign = "+" if cents > 0 else "-"
    return f"{sign}${abs(cents) / 100:,.2f}"


@app.template_filter("odds")
def _odds_filter(odds: int | None) -> str:
    if odds is None:
        return ""
    return f"+{odds}" if odds > 0 else str(odds)


@app.route("/me/")
def me_index():
    status = mybets.my_bets_status()
    for d in status["days"]:
        for p in d["picks"]:
            p["description"] = _format_bet(p)
    return render_template(
        "me.html",
        status=status,
        all_days=_dates_with_bets(),
        date_str=None,
        sidebar_items=None,
        me_active=True,
        local=app.config.get("LOCAL", False),
    )


@app.route("/me/tail", methods=["POST"])
def me_tail():
    if not app.config.get("LOCAL", False):
        abort(403)
    bet_id = int(request.form["bet_id"])
    stake_dollars = float(request.form["stake"])
    odds = int(request.form.get("odds") or -110)
    stake_cents = int(round(stake_dollars * 100))
    if stake_cents <= 0:
        abort(400)
    mybets.tail_bet(bet_id, stake_cents, odds)
    return redirect(request.form.get("next") or "/")


@app.route("/me/untail", methods=["POST"])
def me_untail():
    if not app.config.get("LOCAL", False):
        abort(403)
    bet_id = int(request.form["bet_id"])
    mybets.untail_bet(bet_id)
    return redirect(request.form.get("next") or "/")


@app.route("/cappers/")
def cappers_index():
    """Roster of every capper + panel member, with headline stats."""
    cards = []
    for r in _roster():
        b = bankroll_status(r["label"])
        counts = b["counts"]
        decided = counts["W"] + counts["L"]
        delta = b["current_cents"] - b["starting_cents"]
        cards.append({
            "label": r["label"],
            "slug": r["slug"],
            "is_panel": r["is_panel"],
            "counts": counts,
            "win_pct": (counts["W"] * 100 / decided) if decided else None,
            "total_staked_cents": b["total_staked_cents"],
            "delta_cents": delta if b["total_staked_cents"] else None,
            "roi_pct": (
                delta * 100 / b["total_staked_cents"]
            ) if b["total_staked_cents"] else None,
        })
    return render_template(
        "cappers.html",
        cards=cards,
        all_days=_dates_with_bets(),
        date_str=None,
        sidebar_items=None,
        cappers_active=True,
    )


@app.route("/source/<slug>/")
def source_page(slug: str):
    """One capper/panel member's activity — bets per day, newest first."""
    label = _label_for_slug(slug)
    if label is None:
        abort(404)
    b = bankroll_status(label)
    for h in b["history"]:
        h["description"] = _format_bet(h)
    b["days"] = _history_by_day(b)
    counts = b["counts"]
    decided = counts["W"] + counts["L"]
    delta = b["current_cents"] - b["starting_cents"]
    b["is_panel"] = b["total_staked_cents"] > 0
    b["win_pct"] = (counts["W"] * 100 / decided) if decided else None
    b["delta_cents"] = delta
    b["roi_pct"] = (
        delta * 100 / b["total_staked_cents"]
    ) if b["total_staked_cents"] else None
    return render_template(
        "source.html",
        b=b,
        display_label=label,
        all_days=_dates_with_bets(),
        date_str=None,
        sidebar_items=None,
        current_source_slug=slug,
    )


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

    tails = mybets.tail_map()
    enriched = [
        {**b, "description": _format_bet(b), "tail": tails.get(b["id"])}
        for b in bets
    ]

    def _abbr(matchup: str) -> str:
        """Return 'AWAY @ HOME' abbreviation if we have team_abbr cached."""
        mlow = (matchup or "").lower()
        for g in games.values():
            away = (g["away_team"] or "").lower()
            home = (g["home_team"] or "").lower()
            if away.split()[-1] in mlow and home.split()[-1] in mlow:
                a = g.get("away_team_abbr")
                h = g.get("home_team_abbr")
                if a and h:
                    return f"{a} @ {h}"
        return matchup or "(no matchup)"

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

    # Sidebar items: by-game uses team abbreviations; by-source uses labels.
    if view == "source":
        sidebar_items = [
            (i + 1, name) for i, (name, _, _) in enumerate(rendered_groups)
        ]
    else:
        sidebar_items = [
            (i + 1, _abbr(name))
            for i, (name, _, _) in enumerate(rendered_groups)
        ]

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
        sidebar_items=sidebar_items,
        sources=_sources_for_date(date_str),
        all_days=_dates_with_bets(),
        local=app.config.get("LOCAL", False),
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

        # Cappers roster + one activity page per capper/panel member.
        cappers_dir = out_dir / "cappers"
        cappers_dir.mkdir(exist_ok=True)
        resp = c.get("/cappers/")
        if resp.status_code != 200:
            raise RuntimeError(
                f"failed to render /cappers/: {resp.status_code}"
            )
        (cappers_dir / "index.html").write_bytes(resp.data)
        written += 1

        for r in _roster():
            src_dir = out_dir / "source" / r["slug"]
            src_dir.mkdir(parents=True, exist_ok=True)
            resp = c.get(f"/source/{r['slug']}/")
            if resp.status_code != 200:
                raise RuntimeError(
                    f"failed to render /source/{r['slug']}/: "
                    f"{resp.status_code}"
                )
            (src_dir / "index.html").write_bytes(resp.data)
            written += 1

        # My bets page — rendered read-only for the published site.
        me_dir = out_dir / "me"
        me_dir.mkdir(exist_ok=True)
        resp = c.get("/me/")
        if resp.status_code != 200:
            raise RuntimeError(
                f"failed to render /me/: {resp.status_code}"
            )
        (me_dir / "index.html").write_bytes(resp.data)
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
    app.config["LOCAL"] = True
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
