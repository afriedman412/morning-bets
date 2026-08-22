"""Grade pending bets by fetching final scores + boxscores and comparing."""
from __future__ import annotations

import json
import re
import sqlite3
import time
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
    # Extraction misspellings seen in the wild. The token-overlap fallback in
    # resolve_player_row would usually rescue these, but only on the strength
    # of a first initial ('aj'), which is not a safe thing to match on.
    "aj smith-shaver": "AJ Smith-Shawver",
}


# ESPN rejects a bare token and rejects browser impersonation; an
# identifying UA with a contact URL is accepted, and is the polite form.
USER_AGENT = (
    "morning-bets/1.0 (+https://github.com/afriedman412/morning-bets)"
)


def _fetch_json(url: str, attempts: int = 4) -> dict:
    """GET JSON, retrying transient rejections with backoff.

    Two separate things were breaking ESPN calls. First, the User-Agent:
    ESPN 403s a bare 'morning-bets/1.0' and also 403s anything pretending
    to be a browser, but accepts an identifying UA that carries a contact
    URL. That block was constant, not occasional, and is what disabled
    consensus odds and NBA grading outright. Second, genuine transient
    5xx/429s, which the retry below absorbs.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last: Exception | None = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (403, 429, 500, 502, 503, 504):
                raise
        except urllib.error.URLError as e:
            last = e
        if i < attempts - 1:
            time.sleep(2 ** i)  # 1s, 2s, 4s
    raise last  # type: ignore[misc]


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
            # A postponed game keeps its gamePk and appears on BOTH the
            # original date (status 'Postponed') and the makeup date
            # (status 'Final'), with officialDate pointing at the day it
            # actually counts. Since games.game_id is the primary key, one
            # row cannot live on two dates — taking only the entry whose
            # officialDate matches the day we asked for keeps each game on
            # exactly one date and makes the upsert idempotent. Without
            # this, whichever date was cached last silently stole the game
            # from the other.
            official = g.get("officialDate")
            if official and official != date_str:
                continue
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


def mlb_linescore_f5(game_id: str) -> tuple[int, int] | None:
    """Return (away_runs, home_runs) through 5 innings for a completed game.

    Returns None if the linescore isn't available or the game didn't
    reach the top/bottom of the 5th (e.g. rain-shortened before F5).
    """
    pk = game_id.removeprefix("mlb-")
    ls = _fetch_json(
        f"https://statsapi.mlb.com/api/v1/game/{pk}/linescore"
    )
    innings = ls.get("innings") or []
    if len(innings) < 5:
        return None
    away = 0
    home = 0
    for inn in innings[:5]:
        a = (inn.get("away") or {}).get("runs")
        h = (inn.get("home") or {}).get("runs")
        if a is None or h is None:
            return None
        away += int(a)
        home += int(h)
    return away, home


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
        date=excluded.date,
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


def cache_mlb_f5(
    conn: sqlite3.Connection, game_id: str,
) -> tuple[int, int] | None:
    """Fetch first-5-inning runs for a completed MLB game and cache them.

    Returns (away_f5, home_f5) if available, else None. Skips the fetch
    if we've already cached both values.
    """
    row = conn.execute(
        "SELECT away_score_f5, home_score_f5 FROM games WHERE game_id=?",
        (game_id,),
    ).fetchone()
    if row and row["away_score_f5"] is not None \
            and row["home_score_f5"] is not None:
        return row["away_score_f5"], row["home_score_f5"]
    try:
        result = mlb_linescore_f5(game_id)
    except Exception as e:
        print(f"  F5 linescore fetch failed for {game_id}: {e}")
        return None
    if result is None:
        return None
    away_f5, home_f5 = result
    conn.execute(
        "UPDATE games SET away_score_f5=?, home_score_f5=? WHERE game_id=?",
        (away_f5, home_f5, game_id),
    )
    return away_f5, home_f5


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

# Sportsbooks, ESPN and statsapi disagree on abbreviations for the same
# club — Arizona is 'AZ' to statsapi but 'ARI' on every bet slip, the White
# Sox are 'CWS' or 'CHW' depending on who you ask. Token overlap alone then
# scores 1 instead of 2 and the matchup silently fails to resolve, which
# leaves the bet permanently UNGRADABLE. Expanding a known abbreviation to
# its full club name before tokenizing removes the whole class of failure.
TEAM_ABBRS = {
    # MLB
    "ARI": "Arizona Diamondbacks", "AZ": "Arizona Diamondbacks",
    "ATL": "Atlanta Braves", "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox", "CHC": "Chicago Cubs",
    "CWS": "Chicago White Sox", "CHW": "Chicago White Sox",
    "CIN": "Cincinnati Reds", "CLE": "Cleveland Guardians",
    "COL": "Colorado Rockies", "DET": "Detroit Tigers",
    "HOU": "Houston Astros", "KC": "Kansas City Royals",
    "KCR": "Kansas City Royals", "LAA": "Los Angeles Angels",
    "LAD": "Los Angeles Dodgers", "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers", "MIN": "Minnesota Twins",
    "NYM": "New York Mets", "NYY": "New York Yankees",
    "ATH": "Athletics", "OAK": "Athletics",
    "PHI": "Philadelphia Phillies", "PIT": "Pittsburgh Pirates",
    "SD": "San Diego Padres", "SDP": "San Diego Padres",
    "SF": "San Francisco Giants", "SFG": "San Francisco Giants",
    "SEA": "Seattle Mariners", "STL": "St. Louis Cardinals",
    "TB": "Tampa Bay Rays", "TBR": "Tampa Bay Rays",
    "TEX": "Texas Rangers", "TOR": "Toronto Blue Jays",
    "WSH": "Washington Nationals", "WAS": "Washington Nationals",
    # NBA
    "BKN": "Brooklyn Nets", "BRK": "Brooklyn Nets",
    "CHA": "Charlotte Hornets", "CHI": "Chicago Bulls",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets",
    "GS": "Golden State Warriors", "GSW": "Golden State Warriors",
    "IND": "Indiana Pacers", "LAC": "Los Angeles Clippers",
    "MEM": "Memphis Grizzlies", "NO": "New Orleans Pelicans",
    "NOP": "New Orleans Pelicans", "NY": "New York Knicks",
    "NYK": "New York Knicks", "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic", "PHX": "Phoenix Suns",
    "PHO": "Phoenix Suns", "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings", "SA": "San Antonio Spurs",
    "SAS": "San Antonio Spurs", "UTA": "Utah Jazz",
    "UTH": "Utah Jazz",
}


def _tokens(s: str) -> set[str]:
    """Lowercase word tokens, with known team abbreviations expanded.

    Only UPPERCASE runs are treated as abbreviations, so ordinary prose
    ('was', 'no', 'sf') can't accidentally conjure a team.
    """
    raw = TEAM_TOKEN_RE.findall(s or "")
    out = {t.lower() for t in raw if len(t) >= 3}
    for t in raw:
        full = TEAM_ABBRS.get(t.upper()) if t.isupper() else None
        if full:
            out |= {w.lower() for w in TEAM_TOKEN_RE.findall(full)
                    if len(w) >= 3}
    return out


def canonical_team(name: str | None) -> str | None:
    """Collapse a team reference to a single spelling.

    Only an exact abbreviation is rewritten — 'CWS' and 'CHW' both become
    'Chicago White Sox'. Anything else comes back trimmed but untouched: a
    partial name like 'White Sox' has no safe expansion, and guessing one
    would merge bets that aren't actually the same.
    """
    s = (name or "").strip()
    if not s:
        return None
    return TEAM_ABBRS.get(s.upper(), s)


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


def same_party(a: str | None, b: str | None) -> bool:
    """True when two team/player references point at the same side.

    A bet slip says 'BAL' where a capper row says 'Baltimore Orioles'.
    Exact string comparison calls those different bets, so team references
    compare on expanded name tokens instead.
    """
    a, b = (a or "").strip(), (b or "").strip()
    if a.lower() == b.lower():
        return True
    if not a or not b:
        return False
    # 'over'/'under' are sides, not teams — they must stay exact.
    if {a.lower(), b.lower()} & {"over", "under"}:
        return False
    return bool(_tokens(a) & _tokens(b))


def _compare_total(line: float, side: str | None, actual: float) -> str:
    """Grade an over/under. Returns UNGRADABLE if the side is missing.

    A total with no over/under is not a bet, and the old code assumed any
    non-'over' side meant 'under' — so a null side silently graded as an
    under, or crashed on .lower(). Extraction does occasionally emit one
    (a capper naming a total without saying which way they lean).
    """
    s = (side or "").strip().lower()
    if s not in ("over", "under"):
        return "UNGRADABLE"
    if actual == line:
        return "PUSH"
    over = actual > line
    return ("W" if over else "L") if s == "over" else ("L" if over else "W")


def _period_scores(
    bet: sqlite3.Row, game: sqlite3.Row,
) -> tuple[int | None, int | None]:
    """Return (away_score, home_score) for the bet's period.

    For period='f5', returns the cached first-5-inning runs (may be None
    if not yet cached / not applicable). Falls back to full-game scores
    for period='full' or any unrecognized value.
    """
    period = (bet["period"] if "period" in bet.keys() else "full") or "full"
    if period == "f5":
        return (
            game["away_score_f5"] if "away_score_f5" in game.keys() else None,
            game["home_score_f5"] if "home_score_f5" in game.keys() else None,
        )
    return game["away_score"], game["home_score"]


def grade_team_bet(
    conn: sqlite3.Connection,
    bet: sqlite3.Row,
    game: sqlite3.Row,
) -> tuple[str, float | None]:
    away_score, home_score = _period_scores(bet, game)

    if bet["bet_type"] == "total":
        if away_score is None or home_score is None:
            return "UNGRADABLE", None
        total = (away_score or 0) + (home_score or 0)
        if bet["line"] is None:
            return "UNGRADABLE", float(total)
        return _compare_total(bet["line"], bet["side"], total), float(total)

    if bet["bet_type"] == "team_total":
        # player_name holds the team name for team_total bets.
        team = bet["player_name"] or ""
        picked_home = _team_in_matchup(game["home_team"], team)
        picked_away = _team_in_matchup(game["away_team"], team)
        if not (picked_home or picked_away):
            return "UNGRADABLE", None
        team_score = home_score if picked_home else away_score
        if team_score is None:
            return "UNGRADABLE", None
        if bet["line"] is None:
            return "UNGRADABLE", float(team_score)
        return (
            _compare_total(bet["line"], bet["side"] or "", team_score),
            float(team_score),
        )

    side = bet["side"] or ""
    if away_score is None or home_score is None:
        return "UNGRADABLE", None
    home_won = (home_score or 0) > (away_score or 0)
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
        margin = (home_score or 0) - (away_score or 0)
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

# Capper bets go through EXTRACT_PROMPT, which pins the vocabulary above.
# Panel nominations don't — the personas emit free-form JSON and spell stats
# however they please, so 'strikeouts' and 'k' arrive as different bets. That
# survived dedup as two candidates, split the vote, and let one thesis take
# two slots on a five-bet card. Everything downstream keys off the canonical
# spelling (the field maps above, kalshi.SERIES_BY_STAT), so normalize on the
# way in.
STAT_ALIASES = {
    # pitching
    "strikeouts": "k", "strikeout": "k", "ks": "k", "punchouts": "k",
    "pitcher_strikeouts": "k", "so_pitcher": "k",
    "outs_recorded": "outs",
    "hits_allowed": "h_allowed", "runs_allowed": "r_allowed",
    "earned_runs": "er", "er_allowed": "er", "walks_allowed": "bb_allowed",
    "home_runs_allowed": "hr_allowed",
    # batting
    "hits": "h", "runs": "r", "rbis": "rbi", "walks": "bb",
    "total_bases": "tb", "bases": "tb", "stolen_bases": "sb",
    "home_runs": "hr", "homers": "hr", "homeruns": "hr",
    "doubles": "2b", "triples": "3b", "singles": "1b",
    "at_bats": "ab",
    # nba
    "points": "pts", "rebounds": "reb", "assists": "ast", "steals": "stl",
    "blocks": "blk", "turnovers": "to", "minutes": "min",
    "threes": "fg3m", "three_pointers": "fg3m", "3pm": "fg3m",
}

# Deliberately absent: 'ip'. Innings pitched is not outs recorded (6.2 IP is
# 20 outs, not 6.2), so aliasing it would silently mis-grade the line.


# Plausible line ranges for the two pitcher stats that get confused with each
# other. A starting pitcher's outs prop lives around 14-20 and a strikeout
# prop around 4-9; the ranges don't overlap, so a line far outside its stat's
# range is a mislabel rather than a bet. Lindy's 'Ashcraft over 5.5 outs' on
# 8/18 was a strikeout prop — a starter recording 6 outs is near-certain, and
# the -108 attached to it should have been about -2000. All three personas
# wrote theses defending it anyway, so nothing downstream catches this.
# Bounds are a plausibility gate, not a tight fit: wide enough that a real
# line never trips them, narrow enough to catch a mistranscribed magnitude.
# Upper bounds sit at or above the highest ACTUAL result ever graded for the
# stat, so a line the market could really hang is always inside.
STAT_LINE_BOUNDS = {
    # MLB pitching. 'outs' starts at 6.5 rather than 0.5 so a short-start or
    # opener prop still fits while 1.5 does not — that is the whole point:
    # "under 15 outs" reaches the transcript as "under 1.5 outs".
    # The ceiling is 24.5, not 27 (a complete game), because 27 leaves room
    # for x10 to "fix" a 2.5 into 25 — a line no book hangs — while 4.5 has
    # no magnitude fix and correctly falls through to the k swap. Capping
    # below 25 makes every low outs value resolve the same way.
    "outs": (6.5, 24.5),
    "k": (0.5, 15.5),        # 1.5 IS real for a reliever — Matz went under
    "er": (0.5, 9.5),
    "r_allowed": (0.5, 9.5),
    "h_allowed": (0.5, 12.5),
    "bb_allowed": (0.5, 6.5),
    "hr_allowed": (0.5, 3.5),
    # MLB batting
    "ab": (0.5, 6.5),
    "r": (0.5, 3.5),
    "h": (0.5, 4.5),
    "1b": (0.5, 3.5),
    "2b": (0.5, 2.5),
    "3b": (0.5, 1.5),
    "hr": (0.5, 3.5),
    "rbi": (0.5, 4.5),
    "bb": (0.5, 3.5),
    "so": (0.5, 4.5),
    "sb": (0.5, 3.5),
    "tb": (0.5, 10.5),
    # NBA
    "pts": (0.5, 60.5),
    "reb": (0.5, 25.5),
    "ast": (0.5, 20.5),
    "stl": (0.5, 6.5),
    "blk": (0.5, 6.5),
    "to": (0.5, 8.5),
    "fg3m": (0.5, 10.5),
    "min": (0.5, 48.5),
}
# The stat each one gets mistaken for, when a magnitude fix does not apply.
STAT_LINE_SWAP = {"outs": "k", "k": "outs"}


# The same counting stat exists on both sides of the ball, under different
# keys, and the extraction vocabulary makes the pitcher form the default for
# strikeouts — EXTRACT_PROMPT says "'strikeouts' resolves to 'k'; a batter
# strikeout prop has to say 'so'". So a batter's K prop lands on 'k' unless
# something knows better.
POSITION_STAT_SWAP = {
    "k": "so", "so": "k",
    "h_allowed": "h", "h": "h_allowed",
    "bb_allowed": "bb", "bb": "bb_allowed",
    "r_allowed": "r", "r": "r_allowed",
    "hr_allowed": "hr", "hr": "hr_allowed",
}
_PITCHER_STATS = {
    "k", "outs", "er", "r_allowed", "h_allowed", "bb_allowed", "hr_allowed",
    "decision",
}
_BATTER_STATS = {
    "ab", "r", "h", "1b", "2b", "3b", "hr", "rbi", "bb", "so", "sb", "tb",
}


def repair_stat_position(
    stat: str | None, player: str | None,
) -> tuple[str | None, str | None]:
    """Swap a stat that contradicts who the player actually is.

    Returns (stat, note). Bounds cannot catch this class: 'Masataka Yoshida
    k over 1.5' is a perfectly valid pitcher-strikeout line, and Yoshida is
    a DH. Only the roster knows.

    Silent whenever the position is unknown or two-way — an unresolved
    nickname must never become a relabelled bet, and Ohtani genuinely
    carries props on both sides.
    """
    from src import roster

    s = (stat or "").strip().lower()
    if s not in _PITCHER_STATS and s not in _BATTER_STATS:
        return stat, None
    try:
        pitcher = roster.is_pitcher(player or "")
    except Exception:
        return stat, None  # roster unavailable — never block ingestion
    if pitcher is None:
        return stat, None

    wrong_side = (
        (s in _PITCHER_STATS and pitcher is False)
        or (s in _BATTER_STATS and pitcher is True)
    )
    if not wrong_side:
        return stat, None

    who = "a pitcher" if pitcher else "a position player"
    alt = POSITION_STAT_SWAP.get(s)
    if alt:
        return alt, (
            f"{player} is {who} but the stat is '{s}' — read as '{alt}'"
        )
    return stat, (
        f"{player} is {who} but the stat is '{s}', which has no counterpart "
        f"on that side — left alone"
    )


def _is_bettable_line(v: float) -> bool:
    """True for a number a book would actually post: a half-point step.

    Props are hung at 5.5, 15, 0.5 — never 1.55. Used to reject a magnitude
    "fix" that lands in range but on an unpostable number.
    """
    return abs(v * 2 - round(v * 2)) < 1e-9


def bounds_for(stat: str | None) -> tuple[float, float] | None:
    """Feasible (lo, hi) for a stat, deriving combos from their parts.

    'h+r+rbi' is not enumerated — its ceiling is the sum of its components,
    which is how any combo the extractor invents gets a bound for free.
    """
    s = (stat or "").strip().lower()
    if s in STAT_LINE_BOUNDS:
        return STAT_LINE_BOUNDS[s]
    parts = [p for p in s.split("+") if p]
    if len(parts) > 1 and all(p in STAT_LINE_BOUNDS for p in parts):
        return (0.5, sum(STAT_LINE_BOUNDS[p][1] for p in parts))
    return None


def repair_stat_line(
    stat: str | None, line: float | None,
) -> tuple[str | None, float | None, str | None]:
    """Fix a line that is impossible for its stat.

    Returns (stat, line, note); note is None when nothing looked wrong.
    Repairs are tried in order of how small a claim they make:

      1. MAGNITUDE, stat intact. "under 15 outs" reaches the transcript as
         "under 1.5 outs" because 'fifteen' comes through as 'one five', and
         the artifact runs the other way too ('one point five' -> 15, which
         is why an h+r+rbi line of 15 is really 1.5). Tried first because
         keeping the stat the source named is a smaller correction than
         relabelling the bet.
      2. STAT, line intact — the line is impossible here but valid for the
         stat this one is confused with.
      3. Neither: flagged and left alone. An unrecognizable line is never
         guessed at.

    The old version tried the swap first and had no magnitude case at all,
    so 'outs 1.5' became 'k 1.5' — a starter under 1.5 strikeouts, when the
    transcript plainly said 15 outs. Low k lines are genuinely real (Steven
    Matz went under 1.5 on 8/14), so bounds alone cannot separate the two;
    the ordering is what does it.

    Every repair returns a note, and persist_bets prints it, so a false
    positive is visible rather than silent.
    """
    s = (stat or "").strip().lower()
    bounds = bounds_for(s)
    if bounds is None or line is None:
        return stat, line, None
    lo, hi = bounds
    if lo <= line <= hi:
        return stat, line, None

    for factor, how in ((10.0, "x10"), (0.1, "/10")):
        shifted = round(line * factor, 2)
        # A shift only counts if it produces a number a book would actually
        # hang. Without this, 'so 15.5' divides to 1.55 — in range for a
        # batter strikeout prop, but not a line anyone can bet, so the
        # "repair" would invent a wager rather than recover one.
        if not _is_bettable_line(shifted):
            continue
        if lo <= shifted <= hi:
            return stat, shifted, (
                f"line {line:g} is outside the {s} range {lo:g}-{hi:g}; "
                f"{how} gives {shifted:g}, which fits — read as {shifted:g}"
            )

    alt = STAT_LINE_SWAP.get(s)
    if alt:
        alo, ahi = STAT_LINE_BOUNDS[alt]
        if alo <= line <= ahi:
            return alt, line, (
                f"line {line:g} is outside the {s} range {lo:g}-{hi:g} "
                f"but valid for {alt} — read as {alt}"
            )
    return stat, line, (
        f"line {line:g} is outside the {s} range {lo:g}-{hi:g} "
        f"and no magnitude fix lands in range — left alone"
    )


def normalize_stat(stat: str | None) -> str | None:
    """Canonical stat key, combo props included ('h+r+rbi').

    'strikeouts' resolves to the pitching key 'k'; a batter strikeout prop
    has to say 'so'. That asymmetry is inherited from the extraction
    vocabulary, which has always split the two.
    """
    s = (stat or "").strip().lower()
    if not s:
        return None
    parts = [p.strip().replace(" ", "_") for p in s.split("+") if p.strip()]
    if not parts:
        return None
    return "+".join(STAT_ALIASES.get(p, p) for p in parts)


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
        # One sport's provider being down must not abort the other, and must
        # not abort grading. ESPN in particular 403s intermittently, which
        # previously killed the whole grade run — including MLB bets whose
        # data had already been fetched successfully from statsapi.
        try:
            games = schedule_fn(date_str)
        except Exception as e:
            print(f"  {sport} schedule fetch failed, skipping {sport}: {e}")
            continue
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
                if sport == "mlb":
                    cache_mlb_f5(conn, g["game_id"])


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
            # Missing game data is a "not yet", not a verdict. Writing
            # UNGRADABLE here is terminal — grade_pending only ever revisits
            # PENDING rows — so a transient outage (laptop wakes before wifi
            # associates, provider 403s, game running late) would silently
            # void the whole slate with no way back. Leaving these PENDING
            # lets the next run pick them up once the data lands.
            if not game_id:
                result, actual = "PENDING", None
            else:
                game = conn.execute(
                    "SELECT * FROM games WHERE game_id=?", (game_id,),
                ).fetchone()
                status = (game["status"] if game else "").lower()
                game_final = "final" in status or "completed" in status
                if not game or not game_final:
                    result, actual = "PENDING", None
                elif bet["bet_type"] in (
                    "ml", "spread", "total", "team_total",
                ):
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
        # A row left PENDING is untouched — no graded_at stamp, nothing to
        # undo — so the next run retries it cleanly.
        if result != "PENDING":
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
        "period": b.get("period") or "full",
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
- Include the line value in the bet description (e.g. "Over 9.5", "Yankees ML", "Hartenstein over 19 PRA", "Cubs team total over 4.5").
- For bet_type="team_total", the player_name field holds the team name — render as "<team> team total <over/under> <line>".
- If period="f5", prefix the bet with "F5" — e.g. "F5 Over 4.5", "F5 Yankees -0.5 runline", "F5 Cubs team total over 2.5". Keep F5 bets separate from full-game bets on the same market; do not combine them.
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


def _odds_int(v) -> int | None:
    """'-121' / '+105' / 'EVEN' -> int, or None."""
    if v is None:
        return None
    s = str(v).strip().replace("+", "")
    if s.upper() in ("EVEN", "EV", "PK"):
        return 100
    try:
        return int(float(s))
    except ValueError:
        return None


def _line_float(v) -> float | None:
    """'o9' / '+1.5' / '-1.5' -> float, or None."""
    if v is None:
        return None
    s = str(v).strip().lstrip("ou").replace("+", "")
    try:
        return float(s)
    except ValueError:
        return None


def _leg(node: dict | None) -> dict:
    """Pull the live price+line out of an ESPN odds leg.

    ESPN gives 'open' and 'close' per leg; for a game that has not started,
    'close' is the current price. Prefer it and fall back to 'open'.
    """
    node = node or {}
    src = node.get("close") or node.get("open") or {}
    return {
        "odds": _odds_int(src.get("odds")),
        "line": _line_float(src.get("line")),
    }


def fetch_mlb_market(date_str: str) -> list[dict]:
    """Real per-game sportsbook prices for a date, straight from ESPN.

    ESPN's scoreboard carries a live DraftKings book — moneyline, runline
    and total, each with both sides priced. This is the antidote to models
    quoting a number they'd prefer: every game-line bet can be checked
    against, and repriced from, an actual market.

    Returns one dict per game with the teams plus `ml`, `runline` and
    `total`, each {away/home or over/under: {odds, line}}.
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
        details = o.get("details") or ""
        ml = o.get("moneyline") or {}
        rl = o.get("pointSpread") or {}
        tot = o.get("total") or {}
        out.append({
            "away_team": away["team"]["displayName"],
            "home_team": home["team"]["displayName"],
            "away_abbr": away["team"].get("abbreviation"),
            "home_abbr": home["team"].get("abbreviation"),
            "book": (o.get("provider") or {}).get("name"),
            "over_under": o.get("overUnder"),
            "runline_favored_abbr": details.split()[0] if details else None,
            "ml": {"away": _leg(ml.get("away")),
                   "home": _leg(ml.get("home"))},
            "runline": {"away": _leg(rl.get("away")),
                        "home": _leg(rl.get("home"))},
            "total": {"over": _leg(tot.get("over")),
                      "under": _leg(tot.get("under"))},
        })
    return out


def fetch_mlb_consensus(date_str: str) -> list[dict]:
    """Back-compat view of fetch_mlb_market for fill_missing_lines."""
    return fetch_mlb_market(date_str)


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
        "AND line IS NULL AND bet_type IN ('total', 'spread') "
        "AND COALESCE(period, 'full')='full'",
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


def fill_missing_prop_lines(
    conn: sqlite3.Connection, date_str: str,
) -> tuple[int, int]:
    """Fill prop lines and prices the source never stated, from Kalshi.

    fill_missing_lines() covers game totals and runlines off ESPN consensus,
    but ESPN publishes nothing at prop level, so a prop a capper read off a
    screen ("Castillo under in outs") kept line=NULL from ingest all the way
    through grading and scored UNGRADABLE. Calling Our Shot alone has 26 of
    those, a third of its pitcher-outs picks.

    Two rules keep this honest:
      * A line is only ever *filled*, never overwritten, and is flagged with
        line_inferred=1 exactly as the consensus fill does.
      * An existing american_odds is never overwritten either — a price the
        source actually quoted beats an exchange midpoint.

    The strike is filled even from a wide book, because which contract is
    listed is a fact about the market. The *price* is not: a wide book is
    evidence rather than a quote, so odds only come from a `usable` one.

    Returns (lines_filled, odds_filled).
    """
    from src import kalshi, parallel
    from src.context import gamestate

    rows = conn.execute(
        "SELECT id, player_name, stat, side, line, american_odds, "
        "matchup FROM bets "
        "WHERE date=? AND sport='mlb' AND bet_type IN ('prop','combo') "
        "AND player_name IS NOT NULL "
        "AND (line IS NULL OR american_odds IS NULL)",
        (date_str,),
    ).fetchall()
    if not rows:
        return 0, 0

    # One lookup per distinct prop, not per row — the same pick from four
    # cappers is one question for the exchange.
    jobs: dict[tuple, list] = {}
    skipped_live = 0
    for r in rows:
        if (r["stat"] or "").lower() not in kalshi.SERIES_BY_STAT:
            continue  # Kalshi has no series for this stat (er, decision, ...)
        # Once first pitch happens the exchange is quoting a contract part
        # way to settlement, not a line. Filling a null from that writes a
        # number nothing downstream can tell is fiction.
        if not gamestate.is_pregame(r["matchup"], date_str):
            skipped_live += 1
            continue
        jobs.setdefault(
            (r["player_name"], r["stat"], (r["side"] or "").lower(),
             r["line"]), [],
        ).append(r)
    if skipped_live:
        print(f"  skipped {skipped_live} prop(s) — game already underway")
    if not jobs:
        return 0, 0

    def _lookup(k: tuple):
        player, stat, side, line = k
        if line is None:
            return kalshi.discover_prop(player, stat, side, date_str)
        return kalshi.price_prop(player, stat, line, side)

    # Network only; every UPDATE below runs on this thread.
    found = parallel.gather(_lookup, list(jobs), workers=4)

    lines = odds = 0
    for k, got, err in found:
        if err or not got:
            continue
        new_line = got.get("line")
        price = got.get("mid_american")
        for r in jobs[k]:
            if r["line"] is None and new_line is not None:
                conn.execute(
                    "UPDATE bets SET line=?, line_inferred=1 WHERE id=?",
                    (float(new_line), r["id"]),
                )
                lines += 1
            if (r["american_odds"] is None and price is not None
                    and got.get("usable")):
                conn.execute(
                    "UPDATE bets SET american_odds=? WHERE id=?",
                    (int(price), r["id"]),
                )
                odds += 1
    return lines, odds


def resolve_canonical_matchup(
    conn: sqlite3.Connection,
    matchup: str | None,
    sport: str,
    date_str: str,
) -> str | None:
    """Map a free-form matchup string to the canonical 'Away Team @ Home Team'
    string from the games table for that date+sport, using team name +
    abbreviation token overlap. Returns the input unchanged if no game matches
    (e.g. games table not yet populated).
    """
    if not matchup:
        return matchup
    rows = conn.execute(
        "SELECT away_team, home_team, away_team_abbr, home_team_abbr "
        "FROM games WHERE sport=? AND date=?",
        (sport, date_str),
    ).fetchall()
    if not rows:
        return matchup

    raw_tokens = re.findall(r"[A-Za-z']+", matchup)
    # _tokens expands known abbreviations to full club names, which is what
    # rescues slips written as 'LAD @ ARI' when statsapi calls Arizona 'AZ'
    # — abbr overlap alone scores 1 there and falls under the threshold.
    text_tokens = _tokens(matchup)
    abbr_tokens = {t.upper() for t in raw_tokens if 2 <= len(t) <= 4
                   and t.isupper()}

    def _side_hit(team: str, abbr: str | None) -> bool:
        if _tokens(team) & text_tokens:
            return True
        return bool(abbr and abbr.upper() in abbr_tokens)

    # Score by how many of the two CLUBS matched, not how many tokens did.
    # Counting tokens breaks once abbreviations expand: 'KC' alone yields
    # kansas/city/royals, three hits, which would clear a 2-token bar and
    # let 'MIN @ KC' match a Cubs-Royals game on the wrong date.
    best, best_score = None, 0
    for g in rows:
        score = (
            int(_side_hit(g["away_team"], g["away_team_abbr"]))
            + int(_side_hit(g["home_team"], g["home_team_abbr"]))
        )
        if score > best_score:
            best, best_score = g, score
    # Both clubs must match; one is never enough to identify a game.
    if best and best_score >= 2:
        return f"{best['away_team']} @ {best['home_team']}"
    return matchup


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


def pending_count(date_str: str) -> int:
    """How many bets on this date are still awaiting a grade.

    `result` is NOT NULL DEFAULT 'PENDING', so an ungraded row holds the
    string 'PENDING', never NULL — this must match what grade_pending()
    selects on or --if-needed silently skips every run.
    """
    db.init()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM bets WHERE date = ? AND result = 'PENDING'",
            (date_str,),
        ).fetchone()
    return row[0]


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if a != "--if-needed"]
    # --if-needed: no-op when the date is already fully graded, so `make
    # morning` can chain grading without re-hitting the stats APIs on a day
    # the standalone 9am launchd agent already handled.
    if_needed = "--if-needed" in sys.argv
    if not args:
        # Default to yesterday — most common case for the morning cron run.
        target = (date.today() - timedelta(days=1)).isoformat()
    else:
        target = args[0]
    if if_needed and pending_count(target) == 0:
        print(f"{target} already graded (nothing pending) — skipping.")
    else:
        grade(target)
