"""Grade pending bets by fetching final scores + boxscores and comparing."""
from __future__ import annotations

import json
import re
import sqlite3
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import anthropic
import os

from dotenv import load_dotenv

from src import db

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BETS_DIR = PROJECT_ROOT / "bets"
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]


# ── nickname / alias map ────────────────────────────────────────────────
PLAYER_ALIASES = {
    "sga": "Shai Gilgeous-Alexander",
    "shai": "Shai Gilgeous-Alexander",
    "wemby": "Victor Wembanyama",
    "the joker": "Nikola Jokic",
    "joker": "Nikola Jokic",
    "dame": "Damian Lillard",
    "kat": "Karl-Anthony Towns",
    "ant": "Anthony Edwards",
    "judge": "Aaron Judge",
}


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": "morning-bets/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


# ── MLB (statsapi.mlb.com) ──────────────────────────────────────────────
ET = ZoneInfo("America/New_York")


def _format_et(iso_utc: str | None) -> str | None:
    """ISO UTC string -> '4:05 PM ET' in Eastern, or None."""
    if not iso_utc:
        return None
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return dt.astimezone(ET).strftime("%-I:%M %p ET")


def mlb_schedule(date_str: str) -> list[dict]:
    """Return list of MLB games for date_str (YYYY-MM-DD).

    Each dict has: game_id, sport, date, away_team, home_team, away_score,
    home_score, status, start_time.
    """
    url = (
        "https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&date={date_str}&hydrate=team"
    )
    data = _fetch_json(url)
    out = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            teams = g["teams"]
            out.append({
                "game_id": f"mlb-{g['gamePk']}",
                "sport": "mlb",
                "date": date_str,
                "away_team": teams["away"]["team"]["name"],
                "home_team": teams["home"]["team"]["name"],
                "away_team_abbr": teams["away"]["team"].get("abbreviation"),
                "home_team_abbr": teams["home"]["team"].get("abbreviation"),
                "away_score": teams["away"].get("score"),
                "home_score": teams["home"].get("score"),
                "status": g["status"]["detailedState"],
                "start_time": g.get("gameDate"),
            })
    return out


def mlb_boxscore(game_id: str) -> dict:
    """Return parsed boxscore: {'batting': [rows], 'pitching': [rows]}."""
    pk = game_id.removeprefix("mlb-")
    bs = _fetch_json(
        f"https://statsapi.mlb.com/api/v1/game/{pk}/boxscore"
    )
    batting, pitching = [], []
    for side in ("away", "home"):
        team_abbr = bs["teams"][side]["team"].get("abbreviation") \
            or bs["teams"][side]["team"]["name"]
        for pid, p in bs["teams"][side]["players"].items():
            name = p["person"]["fullName"]
            bat = p.get("stats", {}).get("batting") or {}
            if bat.get("plateAppearances", 0) > 0 \
                    or bat.get("atBats", 0) > 0:
                h = bat.get("hits", 0)
                d2 = bat.get("doubles", 0)
                t3 = bat.get("triples", 0)
                hr = bat.get("homeRuns", 0)
                batting.append({
                    "game_id": game_id,
                    "player_name": name,
                    "team": team_abbr,
                    "ab": bat.get("atBats", 0),
                    "r": bat.get("runs", 0),
                    "h": h,
                    "1b": h - d2 - t3 - hr,
                    "2b": d2,
                    "3b": t3,
                    "hr": hr,
                    "rbi": bat.get("rbi", 0),
                    "bb": bat.get("baseOnBalls", 0),
                    "so": bat.get("strikeOuts", 0),
                    "sb": bat.get("stolenBases", 0),
                    "tb": bat.get("totalBases", 0),
                })
            pit = p.get("stats", {}).get("pitching") or {}
            if pit.get("battersFaced", 0) > 0 or pit.get("outs", 0) > 0:
                if pit.get("wins"):
                    decision = "W"
                elif pit.get("losses"):
                    decision = "L"
                elif pit.get("saves"):
                    decision = "SV"
                else:
                    decision = None
                pitching.append({
                    "game_id": game_id,
                    "player_name": name,
                    "team": team_abbr,
                    "outs_recorded": pit.get("outs", 0),
                    "h": pit.get("hits", 0),
                    "r": pit.get("runs", 0),
                    "er": pit.get("earnedRuns", 0),
                    "k": pit.get("strikeOuts", 0),
                    "bb": pit.get("baseOnBalls", 0),
                    "hr": pit.get("homeRuns", 0),
                    "decision": decision,
                })
    return {"batting": batting, "pitching": pitching}


# ── NBA (ESPN) ──────────────────────────────────────────────────────────
def nba_schedule(date_str: str) -> list[dict]:
    yyyymmdd = date_str.replace("-", "")
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/"
        f"scoreboard?dates={yyyymmdd}"
    )
    data = _fetch_json(url)
    out = []
    for e in data.get("events", []):
        comps = e["competitions"][0]["competitors"]
        home = next(c for c in comps if c["homeAway"] == "home")
        away = next(c for c in comps if c["homeAway"] == "away")
        out.append({
            "game_id": f"nba-{e['id']}",
            "sport": "nba",
            "date": date_str,
            "away_team": away["team"]["displayName"],
            "home_team": home["team"]["displayName"],
            "away_team_abbr": away["team"].get("abbreviation"),
            "home_team_abbr": home["team"].get("abbreviation"),
            "away_score": int(away["score"]) if away.get("score") else None,
            "home_score": int(home["score"]) if home.get("score") else None,
            "status": e["status"]["type"]["name"],
            "start_time": e.get("date"),
        })
    return out


def _parse_made_att(s: str) -> tuple[int, int]:
    if not s or "-" not in s:
        return 0, 0
    a, b = s.split("-", 1)
    try:
        return int(a), int(b)
    except ValueError:
        return 0, 0


def nba_boxscore(game_id: str) -> dict:
    eid = game_id.removeprefix("nba-")
    bs = _fetch_json(
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/"
        f"summary?event={eid}"
    )
    rows = []
    for team_blk in bs["boxscore"]["players"]:
        abbr = team_blk["team"]["abbreviation"]
        stat = team_blk["statistics"][0]
        labels = stat["labels"]
        idx = {label: i for i, label in enumerate(labels)}
        for a in stat["athletes"]:
            if a.get("didNotPlay"):
                continue
            s = a["stats"]
            if not s:
                continue
            try:
                minutes = int(s[idx["MIN"]]) if s[idx["MIN"]] else 0
            except ValueError:
                minutes = 0
            fgm, fga = _parse_made_att(s[idx.get("FG", -1)] if "FG" in idx else "")
            fg3m, fg3a = _parse_made_att(
                s[idx.get("3PT", -1)] if "3PT" in idx else "")
            ftm, fta = _parse_made_att(
                s[idx.get("FT", -1)] if "FT" in idx else "")

            def _int(key: str) -> int:
                if key not in idx:
                    return 0
                v = s[idx[key]]
                try:
                    return int(v)
                except (ValueError, TypeError):
                    return 0

            rows.append({
                "game_id": game_id,
                "player_name": a["athlete"]["displayName"],
                "team": abbr,
                "min": minutes,
                "pts": _int("PTS"),
                "reb": _int("REB"),
                "oreb": _int("OREB"),
                "dreb": _int("DREB"),
                "ast": _int("AST"),
                "stl": _int("STL"),
                "blk": _int("BLK"),
                "to_": _int("TO"),
                "fgm": fgm,
                "fga": fga,
                "fg3m": fg3m,
                "fg3a": fg3a,
                "ftm": ftm,
                "fta": fta,
                "plus_minus": _int("+/-"),
            })
    return {"nba": rows}


# ── caching ─────────────────────────────────────────────────────────────
def upsert_game(conn: sqlite3.Connection, game: dict) -> None:
    conn.execute(
        """INSERT INTO games
        (game_id, sport, date, away_team, home_team,
         away_team_abbr, home_team_abbr, away_score, home_score, status)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(game_id) DO UPDATE SET
        away_team_abbr=excluded.away_team_abbr,
        home_team_abbr=excluded.home_team_abbr,
        away_score=excluded.away_score,
        home_score=excluded.home_score,
        status=excluded.status""",
        (game["game_id"], game["sport"], game["date"],
         game["away_team"], game["home_team"],
         game.get("away_team_abbr"), game.get("home_team_abbr"),
         game.get("away_score"), game.get("home_score"),
         game.get("status")),
    )


def cache_mlb_box(conn: sqlite3.Connection, box: dict) -> None:
    for row in box["batting"]:
        cols = list(row.keys())
        quoted = [f'"{c}"' for c in cols]
        conn.execute(
            f"INSERT OR REPLACE INTO mlb_batting "
            f"({','.join(quoted)}) VALUES ({','.join('?' * len(cols))})",
            [row[c] for c in cols],
        )
    for row in box["pitching"]:
        cols = list(row.keys())
        conn.execute(
            f"INSERT OR REPLACE INTO mlb_pitching "
            f"({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [row[c] for c in cols],
        )


def cache_nba_box(conn: sqlite3.Connection, box: dict) -> None:
    for row in box["nba"]:
        cols = list(row.keys())
        conn.execute(
            f"INSERT OR REPLACE INTO nba_player_stats "
            f"({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [row[c] for c in cols],
        )


# ── resolution helpers ──────────────────────────────────────────────────
TEAM_TOKEN_RE = re.compile(r"[A-Za-z']+")


def _tokens(s: str) -> set[str]:
    return {t.lower() for t in TEAM_TOKEN_RE.findall(s or "")
            if len(t) >= 3}


def resolve_game(
    conn: sqlite3.Connection,
    matchup: str,
    sport: str,
    date_str: str,
) -> str | None:
    """Find a game_id whose teams match the matchup string."""
    tokens = _tokens(matchup)
    if not tokens:
        return None
    rows = conn.execute(
        "SELECT game_id, away_team, home_team FROM games "
        "WHERE sport=? AND date=?",
        (sport, date_str),
    ).fetchall()
    best, best_score = None, 0
    for r in rows:
        gt = _tokens(r["away_team"]) | _tokens(r["home_team"])
        overlap = len(tokens & gt)
        if overlap > best_score:
            best, best_score = r["game_id"], overlap
    return best if best_score >= 1 else None


def _normalize_name(name: str) -> str:
    n = name.lower().strip()
    if n in PLAYER_ALIASES:
        return PLAYER_ALIASES[n].lower()
    return n


def resolve_player_row(
    conn: sqlite3.Connection,
    table: str,
    game_id: str,
    player_name: str,
) -> sqlite3.Row | None:
    target = _normalize_name(player_name)
    rows = conn.execute(
        f"SELECT * FROM {table} WHERE game_id=?", (game_id,),
    ).fetchall()
    # exact lowercased match
    for r in rows:
        if r["player_name"].lower() == target:
            return r
    # last-name match
    last = target.rsplit(" ", 1)[-1] if " " in target else target
    for r in rows:
        if r["player_name"].lower().endswith(" " + last):
            return r
    # token-overlap fallback
    target_tokens = set(target.split())
    best, best_score = None, 0
    for r in rows:
        rn = set(r["player_name"].lower().replace(".", "").split())
        score = len(target_tokens & rn)
        if score > best_score:
            best, best_score = r, score
    return best if best_score >= 1 else None


# ── grading ─────────────────────────────────────────────────────────────
def _team_in_matchup(team_name: str, matchup_or_side: str) -> bool:
    return bool(_tokens(team_name) & _tokens(matchup_or_side))


def _compare_total(line: float, side: str, actual: float) -> str:
    if actual == line:
        return "PUSH"
    over = actual > line
    if side.lower() == "over":
        return "W" if over else "L"
    return "L" if over else "W"


def grade_team_bet(
    conn: sqlite3.Connection,
    bet: sqlite3.Row,
    game: sqlite3.Row,
) -> tuple[str, float | None]:
    if bet["bet_type"] == "total":
        total = (game["away_score"] or 0) + (game["home_score"] or 0)
        if bet["line"] is None:
            return "UNGRADABLE", float(total)
        return _compare_total(bet["line"], bet["side"], total), float(total)

    side = bet["side"] or ""
    home_won = (game["home_score"] or 0) > (game["away_score"] or 0)
    picked_home = _team_in_matchup(game["home_team"], side)
    picked_away = _team_in_matchup(game["away_team"], side)
    if not (picked_home or picked_away):
        return "UNGRADABLE", None

    if bet["bet_type"] == "ml":
        won = (picked_home and home_won) or (picked_away and not home_won)
        return ("W" if won else "L"), None

    if bet["bet_type"] == "spread":
        if bet["line"] is None:
            return "UNGRADABLE", None
        margin = (game["home_score"] or 0) - (game["away_score"] or 0)
        # margin > 0 = home wins by margin
        if picked_home:
            adjusted = margin + bet["line"]
        else:
            adjusted = -margin + bet["line"]
        if adjusted == 0:
            return "PUSH", None
        return ("W" if adjusted > 0 else "L"), None

    return "UNGRADABLE", None


NBA_STAT_FIELDS = {
    "pts": "pts", "reb": "reb", "oreb": "oreb", "dreb": "dreb",
    "ast": "ast", "stl": "stl", "blk": "blk", "to": "to_",
    "fgm": "fgm", "fga": "fga", "fg3m": "fg3m", "fg3a": "fg3a",
    "ftm": "ftm", "fta": "fta", "min": "min",
    "plus_minus": "plus_minus",
}

MLB_BAT_FIELDS = {
    "ab": "ab", "r": "r", "h": "h", "1b": "1b", "2b": "2b", "3b": "3b",
    "hr": "hr", "rbi": "rbi", "bb": "bb", "so": "so", "sb": "sb", "tb": "tb",
}

MLB_PITCH_FIELDS = {
    "outs": "outs_recorded",
    "k": "k",
    "bb_allowed": "bb",
    "h_allowed": "h",
    "r_allowed": "r",
    "er": "er",
    "hr_allowed": "hr",
}


def _sum_stat_components(row: sqlite3.Row, stat: str,
                         field_map: dict[str, str]) -> float | None:
    components = stat.split("+")
    total = 0.0
    for c in components:
        c = c.strip().lower()
        if c not in field_map:
            return None
        v = row[field_map[c]]
        if v is None:
            return None
        total += v
    return total


def grade_prop_bet(
    conn: sqlite3.Connection,
    bet: sqlite3.Row,
    game_id: str,
    sport: str,
) -> tuple[str, float | None]:
    if bet["line"] is None or bet["side"] is None:
        return "UNGRADABLE", None
    stat = (bet["stat"] or "").lower()
    if sport == "nba":
        row = resolve_player_row(
            conn, "nba_player_stats", game_id, bet["player_name"] or "")
        if row is None:
            return "UNGRADABLE", None
        actual = _sum_stat_components(row, stat, NBA_STAT_FIELDS)
    elif sport == "mlb":
        # try batting first, then pitching based on stat tokens
        first = stat.split("+")[0]
        if first in MLB_PITCH_FIELDS:
            row = resolve_player_row(
                conn, "mlb_pitching", game_id, bet["player_name"] or "")
            field_map = MLB_PITCH_FIELDS
        else:
            row = resolve_player_row(
                conn, "mlb_batting", game_id, bet["player_name"] or "")
            field_map = MLB_BAT_FIELDS
        if row is None:
            return "UNGRADABLE", None
        actual = _sum_stat_components(row, stat, field_map)
    else:
        return "UNGRADABLE", None

    if actual is None:
        return "UNGRADABLE", None
    return _compare_total(bet["line"], bet["side"], actual), float(actual)


# ── orchestration ───────────────────────────────────────────────────────
def cache_day(conn: sqlite3.Connection, date_str: str) -> None:
    """Fetch all MLB + NBA games for a date and cache games + boxscores."""
    for sport, schedule_fn, box_fn, cache_fn in (
        ("mlb", mlb_schedule, mlb_boxscore, cache_mlb_box),
        ("nba", nba_schedule, nba_boxscore, cache_nba_box),
    ):
        games = schedule_fn(date_str)
        for g in games:
            upsert_game(conn, g)
            if g["status"].lower() in (
                "final", "status_final", "completed early",
            ):
                try:
                    box = box_fn(g["game_id"])
                    cache_fn(conn, box)
                except Exception as e:
                    print(f"  Boxscore fetch failed for {g['game_id']}: {e}")


def grade_pending(conn: sqlite3.Connection, date_str: str) -> dict:
    """Grade every PENDING bet for the given date. Returns counts."""
    counts: dict[str, int] = {}
    now = datetime.now(timezone.utc).isoformat()
    bets = conn.execute(
        "SELECT * FROM bets WHERE date=? AND result='PENDING'",
        (date_str,),
    ).fetchall()
    for bet in bets:
        if bet["sport"] not in ("mlb", "nba"):
            result, actual = "UNGRADABLE", None
        else:
            game_id = bet["game_id"] or resolve_game(
                conn, bet["matchup"] or "", bet["sport"], date_str,
            )
            if not game_id:
                result, actual = "UNGRADABLE", None
            else:
                game = conn.execute(
                    "SELECT * FROM games WHERE game_id=?", (game_id,),
                ).fetchone()
                status = (game["status"] if game else "").lower()
                game_final = "final" in status or "completed" in status
                if not game or not game_final:
                    result, actual = "UNGRADABLE", None
                elif bet["bet_type"] in ("ml", "spread", "total"):
                    result, actual = grade_team_bet(conn, bet, game)
                else:
                    result, actual = grade_prop_bet(
                        conn, bet, game_id, bet["sport"],
                    )
                if game_id and not bet["game_id"]:
                    conn.execute(
                        "UPDATE bets SET game_id=? WHERE id=?",
                        (game_id, bet["id"]),
                    )
        conn.execute(
            "UPDATE bets SET result=?, actual_value=?, graded_at=? "
            "WHERE id=?",
            (result, actual, now, bet["id"]),
        )
        counts[result] = counts.get(result, 0) + 1
    return counts


def render_graded_markdown(date_str: str) -> str:
    """Use Claude to render a per-game graded markdown from DB rows."""
    with db.connect() as conn:
        bets = [dict(r) for r in conn.execute(
            "SELECT * FROM bets WHERE date=? ORDER BY matchup, source_label",
            (date_str,),
        ).fetchall()]
        games = {r["game_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM games WHERE date=?", (date_str,),
        ).fetchall()}

    # Strip JSON-loaded raw_text and inline a concise dict per bet
    compact = [{
        "source": b["source_label"],
        "matchup": b["matchup"],
        "sport": b["sport"],
        "player": b["player_name"],
        "stat": b["stat"],
        "line": b["line"],
        "side": b["side"],
        "bet_type": b["bet_type"],
        "confidence": b["confidence"],
        "result": b["result"],
        "actual_value": b["actual_value"],
    } for b in bets]

    finals = [
        f"- {g['away_team']} {g['away_score']} @ "
        f"{g['home_team']} {g['home_score']} ({g['status']})"
        for g in games.values()
        if g.get("away_score") is not None
    ]

    today = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A %-m/%-d/%y")

    prompt = f"""You will format a graded sports betting recap as markdown.

Input data:
- Final scores for {date_str}:
{chr(10).join(finals) if finals else "(none)"}

- Graded bets (JSON):
{json.dumps(compact, indent=2)}

Produce a markdown document EXACTLY in this format:

# Graded Bets — {today}

## Summary
- Record: X-Y-Z (W-L-Push)
- Ungradable: N
- By source: (top sources with W-L records, sorted by wins)

## [Game/Matchup] — [final score]
- **[bet]** — [Source] [confidence tag if any] → **[W/L/PUSH/UNGRADABLE]** (actual: X)
  - [next source on same bet] → result (actual: X)
- **[next bet]** — ...

## [Next Game]
...

Rules:
- Group bets BY matchup.
- For each bet line, show: original pick description, source list (combined if multiple sources), and the result with the actual value.
- Use **bold** for the bet description and the result. Result values: **W** (won), **L** (lost), **PUSH**, **UNGRADABLE**.
- Include the line value in the bet description (e.g. "Over 9.5", "Yankees ML", "Hartenstein over 19 PRA").
- For UNGRADABLE bets, briefly note why if obvious (e.g. "no line stated", "non-MLB/NBA").
- Don't hallucinate fields. Use only what's in the JSON.
- Order matchups by total bet count (most bets first).
"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def fetch_mlb_consensus(date_str: str) -> list[dict]:
    """Pull current MLB consensus odds from ESPN scoreboard.

    Returns list of {away_team, home_team, away_abbr, home_abbr,
    over_under, runline_favored_abbr} per game.
    """
    yyyymmdd = date_str.replace("-", "")
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/"
        f"scoreboard?dates={yyyymmdd}"
    )
    data = _fetch_json(url)
    out = []
    for e in data.get("events", []):
        comp = e["competitions"][0]
        comps = comp["competitors"]
        home = next(c for c in comps if c["homeAway"] == "home")
        away = next(c for c in comps if c["homeAway"] == "away")
        odds_arr = comp.get("odds") or []
        if not odds_arr:
            continue
        o = odds_arr[0]
        favored = None
        details = o.get("details") or ""
        if details:
            favored = details.split()[0]  # e.g. "TB -162" -> "TB"
        out.append({
            "away_team": away["team"]["displayName"],
            "home_team": home["team"]["displayName"],
            "away_abbr": away["team"].get("abbreviation"),
            "home_abbr": home["team"].get("abbreviation"),
            "over_under": o.get("overUnder"),
            "runline_favored_abbr": favored,
        })
    return out


def fill_missing_lines(conn: sqlite3.Connection, date_str: str) -> int:
    """For MLB total/spread bets with line=NULL, fill from ESPN consensus.

    Sets line_inferred=1 so the UI can flag it. Returns count updated.
    """
    odds = fetch_mlb_consensus(date_str)
    if not odds:
        return 0

    rows = conn.execute(
        "SELECT id, matchup, bet_type, side FROM bets "
        "WHERE date=? AND sport='mlb' "
        "AND line IS NULL AND bet_type IN ('total', 'spread')",
        (date_str,),
    ).fetchall()

    updated = 0
    for r in rows:
        mlow = (r["matchup"] or "").lower()
        match = None
        for o in odds:
            away_tokens = _tokens(o["away_team"])
            home_tokens = _tokens(o["home_team"])
            if (any(t in mlow for t in away_tokens)
                    and any(t in mlow for t in home_tokens)):
                match = o
                break
        if not match:
            continue
        if r["bet_type"] == "total":
            if match["over_under"] is None:
                continue
            new_line = float(match["over_under"])
        else:  # spread
            # MLB runline is always 1.5; favored team is -1.5, dog is +1.5.
            side = (r["side"] or "").lower()
            fav = (match["runline_favored_abbr"] or "").lower()
            away_abbr = (match["away_abbr"] or "").lower()
            home_abbr = (match["home_abbr"] or "").lower()
            picked_fav = fav and fav in side
            picked_dog = (
                (away_abbr in side or home_abbr in side) and not picked_fav
            )
            if picked_fav:
                new_line = -1.5
            elif picked_dog:
                new_line = 1.5
            else:
                continue
        conn.execute(
            "UPDATE bets SET line=?, line_inferred=1 WHERE id=?",
            (new_line, r["id"]),
        )
        updated += 1
    return updated


def todays_matchups(date_str: str) -> list[str]:
    """Return a flat list of human-readable matchups for use as prompt context.

    Each entry looks like 'MLB: Yankees @ Athletics' or 'NBA: Spurs vs Thunder'.
    Failures fall back to empty list so extraction still proceeds.
    """
    out: list[str] = []
    try:
        for g in mlb_schedule(date_str):
            t = _format_et(g.get("start_time"))
            suffix = f" — {t}" if t else ""
            out.append(
                f"MLB: {g['away_team']} @ {g['home_team']}{suffix}"
            )
    except Exception:
        pass
    try:
        for g in nba_schedule(date_str):
            t = _format_et(g.get("start_time"))
            suffix = f" — {t}" if t else ""
            out.append(
                f"NBA: {g['away_team']} @ {g['home_team']}{suffix}"
            )
    except Exception:
        pass
    return out


def grade(date_str: str) -> Path:
    """Top-level: cache the day's games, grade pending bets, render markdown."""
    db.init()
    with db.connect() as conn:
        print(f"Caching MLB + NBA games for {date_str}...")
        cache_day(conn, date_str)
        print("Grading pending bets...")
        counts = grade_pending(conn, date_str)
        print(f"  Result counts: {counts}")

    print("Rendering graded markdown...")
    md = render_graded_markdown(date_str)
    BETS_DIR.mkdir(exist_ok=True)
    out_path = BETS_DIR / f"{date_str.replace('-', '_')}_graded.md"
    out_path.write_text(md)
    print(f"  Wrote {out_path}")
    return out_path


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        # Default to yesterday — most common case for the morning cron run.
        target = (date.today() - timedelta(days=1)).isoformat()
    else:
        target = sys.argv[1]
    grade(target)
