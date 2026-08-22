"""Panel of Experts: 3 LLM personas pick MLB bets each morning.

Each persona reads today's slate, the cappers' consensus, savant baselines,
and its own last-30-day record, then issues 1-5 picks with reasoning. Picks
flow through the same extract -> persist -> grade pipeline as YouTube cappers
(source_label is "Panel: <name>") and also get rendered to a standalone
`bets/YYYY_MM_DD_panel.md` for at-a-glance reading.
"""
from __future__ import annotations

import csv
import io
import json
import os
import random
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from src import db, parallel
from src.grading import cache_day, todays_matchups, _format_et
from src.main import extract_structured_bets, persist_bets

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BETS_DIR = PROJECT_ROOT / "bets"
CACHE_DIR = PROJECT_ROOT / ".cache"

MODEL = "claude-sonnet-4-6"
HISTORY_DAYS = 30
WEB_SEARCH_MAX_USES = 6


# ── personas ────────────────────────────────────────────────────────────
PERSONAS: dict[str, dict[str, str]] = {
    "Quant": {
        "label": "Panel: Quant",
        "system": (
            "You are QUANT, a tech-minded, stats-forward MLB bettor. You "
            "weight underlying metrics (xwOBA over BA, K% over raw Ks, "
            "FIP/SIERA over ERA, barrel% and hard-hit% over recent "
            "hot streaks). You distrust small samples and recency bias. "
            "You hunt for gaps between your model of true talent and the "
            "posted line. You think in expected value, not vibes.\n\n"
            "Use the supplied savant data as your baseline. Use web_search "
            "to dig deeper on starter arsenals, park-adjusted metrics, "
            "and platoon splits when relevant. Skip the search if the "
            "supplied context already settles the question.\n\n"
            "Prefer player props and totals over moneylines. Cite "
            "specific numbers in your reasoning. Use the confidence 1-10 "
            "score honestly — if your 5th pick is a shrug, score it a 2."
        ),
    },
    "Cynic": {
        "label": "Panel: Cynic",
        "system": (
            "You are CYNIC, a grizzled MLB handicapper who's seen every "
            "model get cooked by reality. You believe in: divisional "
            "history, ballpark personality, ump tendencies, bullpen "
            "fatigue, travel and time-zone drag, day-after-night-game "
            "lineups, weather (wind direction at Wrigley, marine layer "
            "at Oracle, altitude at Coors), and the public being on the "
            "wrong side when a line moves against the money.\n\n"
            "You distrust 'expected' stats — a guy is what his slash "
            "line says, not what some model wishes he was. You distrust "
            "the Quant. You like fading crowded public sides.\n\n"
            "Use web_search to check weather, lineups, ump assignments, "
            "and line movement. The supplied savant data is fine for "
            "context but isn't gospel.\n\n"
            "Lean into spreads, runlines, and game totals. Cite the angle "
            "— 'Coors wind blowing out, both starters with HR/9 over 1.5' "
            "is good; 'I like the over' is not. Use the 1-10 confidence "
            "score honestly — your 5th pick can be a 2 if the slate's "
            "thin."
        ),
    },
    "Careful": {
        "label": "Panel: Careful",
        "system": (
            "You are CAREFUL, a disciplined MLB bettor. Your edge is "
            "calibration — knowing what you don't know. You still have to "
            "submit 5 picks every day, but the confidence score is where "
            "your discipline shows: score your top conviction high and "
            "score your forced 5th pick low. Your rules:\n"
            "  • Only score a pick 6+ when at least two independent "
            "angles converge (e.g. a stats edge AND a situational edge).\n"
            "  • Never score a pick above 4 if you'd take the juiced "
            "price (-150 cap is the system rule; you avoid even "
            "-130 favorites unless something special).\n"
            "  • If the cappers and Quant and Cynic disagree wildly on "
            "a game, that's a sign of uncertainty — pick something safe "
            "with a low score.\n"
            "  • Coin-flip props and bad-weather games get 1-3 scores.\n\n"
            "Use web_search sparingly — only when a specific question "
            "would change your action. State your reasoning concisely; "
            "if you can't articulate the edge in one sentence, score "
            "the pick low. Each pick should name the convergent angles."
        ),
    },
}


# ── savant baselines (cached daily) ────────────────────────────────────
def _fetch_text(url: str) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "morning-bets-panel/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / name


def _load_cached_csv(cache_name: str, url: str) -> list[dict]:
    """Fetch a CSV, cached once per calendar day.

    Cache filename must include today's date, so a new day always triggers
    a fresh pull and re-runs within a day are deterministic.
    """
    p = _cache_path(cache_name)
    if p.exists():
        text = p.read_text()
    else:
        text = _fetch_text(url)
        p.write_text(text)
    # Savant CSV exports start with a UTF-8 BOM; strip it so the first
    # header key isn't '﻿last_name, first_name'.
    if text.startswith("﻿"):
        text = text.lstrip("﻿")
    return list(csv.DictReader(io.StringIO(text)))


def savant_batter_expected(year: int, today: str) -> list[dict]:
    """xwOBA / xBA / xSLG leaderboard for qualified batters."""
    url = (
        "https://baseballsavant.mlb.com/leaderboard/expected_statistics"
        # min=1 rather than min=q: the qualified filter drops every part-time
        # bat, and props get written on exactly those. Andrew Vaughn had a
        # capper prop on 8/22 and no xstats row, because 'qualified' means
        # 3.1 PA per team game and he is short of it.
        f"?type=batter&year={year}&position=&team=&min=1&csv=true"
    )
    return _load_cached_csv(
        f"savant_batter_xstats_{year}_{today}.csv", url,
    )


def savant_pitcher_arsenal(year: int, today: str) -> list[dict]:
    """Per-pitch-type stats for pitchers with >=10 of that pitch this year."""
    url = (
        "https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats"
        f"?year={year}&min=10&type=pitcher&hand=&pitch_type=ALL&csv=true"
    )
    return _load_cached_csv(
        f"savant_pitch_arsenal_{year}_{today}.csv", url,
    )


def _name_key(first: str, last: str) -> str:
    return f"{first.strip().lower()} {last.strip().lower()}"


def _batter_blob(rows: list[dict]) -> dict[str, dict]:
    """Index batters by 'first last' lower-case name."""
    out: dict[str, dict] = {}
    for r in rows:
        # CSV column: "last_name, first_name" -> single field
        full = r.get("last_name, first_name") or r.get(" first_name") or ""
        if "," in full:
            last, first = [s.strip() for s in full.split(",", 1)]
        else:
            parts = full.split()
            if len(parts) < 2:
                continue
            last, first = parts[-1], " ".join(parts[:-1])
        out[_name_key(first, last)] = {
            "pa": r.get("pa"),
            "ba": r.get("ba"),
            "xba": r.get("est_ba"),
            "slg": r.get("slg"),
            "xslg": r.get("est_slg"),
            "woba": r.get("woba"),
            "xwoba": r.get("est_woba"),
        }
    return out


def _pitcher_arsenal_blob(rows: list[dict]) -> dict[str, list[dict]]:
    """Index pitchers by name -> list of per-pitch stats."""
    out: dict[str, list[dict]] = {}
    for r in rows:
        full = r.get("last_name, first_name") or ""
        if "," not in full:
            continue
        last, first = [s.strip() for s in full.split(",", 1)]
        key = _name_key(first, last)
        out.setdefault(key, []).append({
            "pitch": r.get("pitch_name"),
            "usage_pct": r.get("pitch_usage"),
            "whiff_pct": r.get("whiff_percent"),
            "k_pct": r.get("k_percent"),
            "xwoba": r.get("est_woba"),
            "hard_hit_pct": r.get("hard_hit_percent"),
        })
    return out


# ── schedule + probable pitchers ────────────────────────────────────────
def mlb_schedule_with_probables(date_str: str) -> list[dict]:
    """Schedule + probable pitcher names + venue + weather (when available).

    Augments the slimmer mlb_schedule() in src.grading.
    """
    url = (
        "https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&date={date_str}&hydrate=probablePitcher,venue,weather"
    )
    req = urllib.request.Request(
        url, headers={"User-Agent": "morning-bets-panel/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    out = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            teams = g["teams"]
            venue = g.get("venue") or {}
            weather = g.get("weather") or {}
            away_pp = teams["away"].get("probablePitcher") or {}
            home_pp = teams["home"].get("probablePitcher") or {}
            out.append({
                "game_id": f"mlb-{g['gamePk']}",
                "matchup": (
                    f"{teams['away']['team']['name']} @ "
                    f"{teams['home']['team']['name']}"
                ),
                # Carry the ids, not just the rendered names. Rebuilding a
                # club from its name means matching 'Arizona Diamondbacks'
                # against a standings row that says 'D-backs', which is a
                # string problem invented by discarding an integer that was
                # already in the payload.
                "away_team_id": teams["away"]["team"].get("id"),
                "home_team_id": teams["home"]["team"].get("id"),
                "away_team": teams["away"]["team"].get("name"),
                "home_team": teams["home"]["team"].get("name"),
                "venue_id": venue.get("id"),
                "start_time": _format_et(g.get("gameDate")),
                "venue": venue.get("name"),
                "weather": {
                    "condition": weather.get("condition"),
                    "temp_f": weather.get("temp"),
                    "wind": weather.get("wind"),
                } if weather else None,
                "away_probable": away_pp.get("fullName"),
                "home_probable": home_pp.get("fullName"),
            })
    return out


# ── capper consensus + history ─────────────────────────────────────────
def capper_bets_for_date(date_str: str) -> list[dict]:
    """All human-source MLB bets for a date, with rationale, as plain dicts.

    Everything this system generates itself has to be excluded, or it is fed
    back to the personas as independent corroboration. 'Panel:%' covered the
    three personas but not the recommender, so on any *re-run* of a day the
    previous consensus card arrived in the capper block looking like five
    more cappers agreeing — self-confirmation, and invisible on a first run
    of the day because no card exists yet. The sim labels are backtest
    output and belong out for the same reason.
    """
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT source_label, matchup, player_name, stat, line, side, "
            "bet_type, period, confidence, rationale, american_odds, "
            "line_inferred, stated_line, stated_odds "
            "FROM bets WHERE date=? AND sport='mlb' "
            "AND source_label NOT LIKE 'Panel:%' "
            "AND source_label NOT LIKE 'Consensus (sim%' "
            "AND source_label != 'Recommendation' "
            "ORDER BY matchup, source_label",
            (date_str,),
        ).fetchall()
    return [dict(r) for r in rows]


def persona_record(label: str, days: int = HISTORY_DAYS) -> dict:
    """Return a compact W-L breakdown for a persona over the last N days."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT bet_type, stat, side, result, period "
            "FROM bets WHERE source_label=? AND date>=? "
            "AND result IN ('W','L','PUSH')",
            (label, cutoff),
        ).fetchall()
    overall = {"W": 0, "L": 0, "PUSH": 0}
    by_bucket: dict[str, dict[str, int]] = {}
    for r in rows:
        overall[r["result"]] = overall.get(r["result"], 0) + 1
        bucket = r["bet_type"]
        if bucket == "prop" and r["stat"]:
            bucket = f"prop:{r['stat']}"
        elif bucket == "total" and r["side"]:
            bucket = f"total:{(r['side'] or '').lower()}"
        elif bucket == "team_total" and r["side"]:
            bucket = f"team_total:{(r['side'] or '').lower()}"
        period = (r["period"] or "full")
        if period != "full":
            bucket = f"{period}:{bucket}"
        by_bucket.setdefault(bucket, {"W": 0, "L": 0, "PUSH": 0})
        by_bucket[bucket][r["result"]] = (
            by_bucket[bucket].get(r["result"], 0) + 1
        )
    return {"days": days, "overall": overall, "by_bucket": by_bucket}


# ── persona invocation ─────────────────────────────────────────────────
PERSONA_INSTRUCTIONS = """\
TODAY: {today_pretty}

YOUR LAST-{history_days}-DAY RECORD (your own picks, graded):
{record_block}

TODAY'S MLB SLATE:
{slate_block}

CURRENT MARKET LINES (ESPN consensus):
{consensus_block}

WHAT THE YOUTUBE CAPPERS ARE SAYING:
{capper_block}

BASELINE SAVANT DATA FOR TODAY'S PROBABLE STARTERS (per-pitch arsenal):
{pitcher_block}

BASELINE SAVANT EXPECTED STATS FOR NOTABLE BATTERS IN TODAY'S SLATE:
{batter_block}

INSTRUCTIONS:
- COVER THE FULL DAY — this is a hard rule. The slate above is in RANDOM
  order, NOT sorted by start time. Do not let your 5 picks cluster in the
  early/afternoon games. The late-starting West Coast games (Dodgers,
  Padres, Giants, Angels, Athletics, Mariners at home — first pitch 9-10pm
  ET) deserve exactly as much scrutiny as the noon games. Weigh every game
  on the board equally, and let a late game earn a pick if it has the edge.
- Pick EXACTLY 5 MLB bets for today. Always 5 — no more, no fewer. Rank
  them by your conviction so your weakest pick is still your 5th-best
  shot at edge.
- Each pick gets a confidence score 1-10 (10 = highest conviction). Also
  tag it with the matching tier: [LEAN] for 1-3, [LIKE] for 4-7,
  [LOCK] for 8-10. The tier tag goes in brackets right after the bet
  so the system can parse it.
- Skip any moneyline or favorite priced -150 or shorter. We're not here
  to pick off cheap juice. If a line you want is too juiced, find a
  different angle (runline, total, prop) or move to a different game.
- BET THE OFFERED LINE. This is a hard rule: you may only bet at the
  line the MARKET actually offers. For game totals and runlines, that
  means the number in the CURRENT MARKET LINES block above. For team
  totals and player props, use the line the cappers quoted (in the
  capper block) or a line you pulled via web_search. You may NOT invent
  your own number. Example: if the total is 8.5 and you like the under
  but think the true number is 7.5, you either bet "under 8.5" as
  offered, or you PASS. Do NOT write "under 7.5" — that's not a
  bookable bet. If your entire thesis relies on a number the market
  isn't giving, the market disagrees with you; find a different edge.
- BANKROLL: You have $5,000. 1 unit = $50, which is also your max bet.
  For EACH of your 5 picks, decide a stake from this menu:
    • $0  — skip (no bet, but the pick is still on record)
    • $12.50  — quarter unit (low conviction, scores 1-3)
    • $25  — half unit (moderate conviction, scores 4-6)
    • $50  — one full unit (high conviction, scores 7-10)
  Staking $0 is encouraged when your conviction is genuinely low. Total
  daily stake should rarely exceed $150 unless you genuinely have a
  monster slate. State the stake explicitly, e.g. "Stake: $25".
- ODDS — MANDATORY: Every pick MUST include the American odds in parens
  after the bet description, e.g. "Yankees -1.5 (+125)" or
  "Schwarber BB over 0.5 (-130)". A pick without a price is invalid.
  Use web_search to pull a live quote (FanDuel / DraftKings / ESPN BET)
  if you don't already have one. ONLY if you genuinely cannot find a
  quote after searching, write "(no price found, assuming -110)" so the
  system can settle the bet at standard juice — and consider whether the
  inability to find a price means the market doesn't exist or moves so
  fast it's not worth betting.
- Stick to MLB. No futures, no parlays.
- Use web_search when it would meaningfully change your action (live
  odds, lineups, weather, ump, late scratches). Baseballmonster's
  free playerrankings.aspx has rolling 1d/7d/14d top-hitters and
  top-pitchers leaderboards — web_search them if recent form matters.
- Format each pick as a markdown bullet under a `## <Away @ Home>`
  header, e.g.:
    - **Yankees -1.5 runline (+125)** [LIKE] — Confidence 6/10 — Stake: $25
      - reasoning sentence

Begin.
"""


def _slate_block(slate: list[dict]) -> str:
    if not slate:
        return "(no games scheduled)"
    lines = []
    for g in slate:
        when = f" — {g['start_time']}" if g.get("start_time") else ""
        ven = f" @ {g['venue']}" if g.get("venue") else ""
        pp = (
            f"  Probables: {g.get('away_probable') or '?'} (away) "
            f"vs {g.get('home_probable') or '?'} (home)"
        )
        wx = ""
        if g.get("weather"):
            w = g["weather"]
            bits = [w.get("condition"), w.get("temp_f"), w.get("wind")]
            joined = ", ".join(str(b) for b in bits if b)
            if joined:
                wx = f"\n  Weather: {joined}"
        lines.append(f"- {g['matchup']}{when}{ven}\n{pp}{wx}")
    return "\n".join(lines)


def _consensus_block(date_str: str) -> str:
    """Render the current MLB market consensus (game total + runline
    favored side) per game. Empty games are skipped."""
    from src.grading import fetch_mlb_consensus
    try:
        odds = fetch_mlb_consensus(date_str)
    except Exception as e:
        return f"(consensus fetch failed: {e})"
    if not odds:
        return "(no consensus lines available)"
    lines = []
    for o in odds:
        away = o.get("away_abbr") or o.get("away_team") or "?"
        home = o.get("home_abbr") or o.get("home_team") or "?"
        total = o.get("over_under")
        fav = o.get("runline_favored_abbr")
        bits = []
        if total is not None:
            bits.append(f"total {total}")
        if fav:
            bits.append(f"runline: {fav} -1.5")
        detail = "; ".join(bits) if bits else "(no line posted)"
        lines.append(f"- {away} @ {home}: {detail}")
    return "\n".join(lines)


def _capper_block(bets: list[dict], limit: int | None = None) -> str:
    """Render every capper bet, grouped by matchup.

    `limit` used to default to 80 and silently truncate — on busy slates that
    dropped up to 25 bets before the personas ever saw them (5/31, 6/3, 6/5,
    6/10, 6/16, 6/23). It now defaults to no cap; the block is a few thousand
    tokens and sits inside the cached prefix, so the cost is negligible.
    """
    if not bets:
        return "(no capper bets ingested yet)"
    if limit is not None and len(bets) > limit:
        print(f"  !! _capper_block truncating {len(bets)} -> {limit} bets")
        bets = bets[:limit]
    # Group by matchup, keep it compact
    by_match: dict[str, list[str]] = {}
    for b in bets:
        m = b.get("matchup") or "(unknown)"
        line = b.get("line")
        period = b.get("period") or "full"
        prefix = "F5 " if period == "f5" else ""
        bet_desc = ""
        if b["bet_type"] == "ml":
            bet_desc = f"{prefix}{b['side']} ML"
        elif b["bet_type"] in ("spread", "total"):
            side = b.get("side") or ""
            body = f"{side} {line}" if line is not None else side
            bet_desc = f"{prefix}{body}".strip()
        elif b["bet_type"] == "team_total":
            team = b.get("player_name") or ""
            side = b.get("side") or ""
            body = (
                f"{team} team total {side} {line}"
                if line is not None
                else f"{team} team total {side}"
            )
            bet_desc = f"{prefix}{body}".strip()
        else:
            parts = [
                b.get("player_name"), b.get("stat"),
                b.get("side"), str(line) if line is not None else None,
            ]
            bet_desc = " ".join(p for p in parts if p)
        tier = f" [{b['confidence']}]" if b.get("confidence") else ""
        why = f" — {b['rationale']}" if b.get("rationale") else ""
        # Price and provenance, so a persona can judge the bet as offered
        # and know how much of it is the capper's own call.
        #   (line from market)  — the capper never said a number (several
        #     read picks off a screen); this is the exchange's listed
        #     strike, so it is the real line but not the source's words.
        #   (was N)             — the capper stated a number and the market
        #     has since moved off it. The thesis was argued at N.
        odds = b.get("american_odds")
        price = f" ({odds:+d})" if odds is not None else ""
        stated_line, line_now = b.get("stated_line"), b.get("line")
        if stated_line is None and line_now is not None:
            prov = " (line from market)"
        elif (stated_line is not None and line_now is not None
              and float(stated_line) != float(line_now)):
            prov = f" (was {stated_line:g})"
        else:
            prov = ""
        stated_odds = b.get("stated_odds")
        if (stated_odds is not None and odds is not None
                and stated_odds != odds):
            prov += f" (priced {stated_odds:+d})"
        by_match.setdefault(m, []).append(
            f"  • {bet_desc}{price}{prov}{tier} "
            f"({b['source_label']}){why}"
        )
    out = []
    for m, lines in by_match.items():
        out.append(f"{m}")
        out.extend(lines)
    return "\n".join(out)


def _record_block(record: dict) -> str:
    o = record["overall"]
    total = o["W"] + o["L"] + o["PUSH"]
    if total == 0:
        return "(no graded picks yet — first run)"
    lines = [
        f"Overall: {o['W']}-{o['L']}-{o['PUSH']} "
        f"({o['W'] / max(1, o['W'] + o['L']) * 100:.0f}% win rate "
        f"on decided picks)"
    ]
    for bucket, counts in sorted(record["by_bucket"].items()):
        sub_total = counts["W"] + counts["L"]
        if sub_total < 3:
            continue  # skip too-small samples
        pct = counts["W"] / max(1, sub_total) * 100
        lines.append(
            f"  • {bucket}: {counts['W']}-{counts['L']}-{counts['PUSH']} "
            f"({pct:.0f}%)"
        )
    return "\n".join(lines)


def _starter_blob(
    slate: list[dict], arsenal_idx: dict[str, list[dict]],
) -> str:
    seen: list[str] = []
    blocks: list[str] = []
    for g in slate:
        for who in (g.get("away_probable"), g.get("home_probable")):
            if not who:
                continue
            key = who.lower().strip()
            if key in seen:
                continue
            seen.append(key)
            pitches = arsenal_idx.get(key)
            if not pitches:
                blocks.append(f"- {who}: (no savant arsenal row)")
                continue
            tops = sorted(
                pitches,
                key=lambda p: float(p["usage_pct"] or 0),
                reverse=True,
            )[:4]
            pitch_lines = ", ".join(
                f"{p['pitch']} {p['usage_pct']}% (whiff "
                f"{p['whiff_pct']}%, xwOBA {p['xwoba']})"
                for p in tops
            )
            blocks.append(f"- {who}: {pitch_lines}")
    return "\n".join(blocks) if blocks else "(none)"


def _batter_blob_for_slate(
    slate: list[dict], batter_idx: dict[str, dict], capper_bets: list[dict],
) -> str:
    """Only ship savant rows for players the cappers actually mentioned —
    keeps the prompt small."""
    mentioned: set[str] = set()
    for b in capper_bets:
        name = (b.get("player_name") or "").strip().lower()
        if name:
            mentioned.add(name)
    rows = []
    for name in sorted(mentioned):
        x = batter_idx.get(name)
        if not x:
            continue
        rows.append(
            f"- {name.title()}: BA {x['ba']} (xBA {x['xba']}), "
            f"SLG {x['slg']} (xSLG {x['xslg']}), "
            f"wOBA {x['woba']} (xwOBA {x['xwoba']}), PA {x['pa']}"
        )
    return "\n".join(rows) if rows else "(no overlapping batters)"


def run_persona(
    persona_name: str,
    slate: list[dict],
    capper_bets: list[dict],
    record: dict,
    pitcher_arsenal_idx: dict[str, list[dict]],
    batter_idx: dict[str, dict],
    today_pretty: str,
    consensus_block: str,
) -> str:
    cfg = PERSONAS[persona_name]
    user_msg = PERSONA_INSTRUCTIONS.format(
        today_pretty=today_pretty,
        history_days=HISTORY_DAYS,
        record_block=_record_block(record),
        slate_block=_slate_block(slate),
        consensus_block=consensus_block,
        capper_block=_capper_block(capper_bets),
        pitcher_block=_starter_blob(slate, pitcher_arsenal_idx),
        batter_block=_batter_blob_for_slate(slate, batter_idx, capper_bets),
    )
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=5000,
        system=cfg["system"],
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": WEB_SEARCH_MAX_USES,
        }],
        messages=[{"role": "user", "content": user_msg}],
    )
    if resp.stop_reason == "max_tokens":
        print(
            f"  !! WARNING: {persona_name} write-up hit max_tokens — "
            f"truncated; late picks may be missing. Raise max_tokens."
        )
    # Concatenate all text blocks from the response (skip tool_use blocks).
    parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    return "\n".join(parts).strip()


# ── orchestration ──────────────────────────────────────────────────────
def render_panel_markdown(
    date_str: str, persona_writeups: dict[str, str],
) -> str:
    today_pretty = datetime.strptime(date_str, "%Y-%m-%d") \
        .strftime("%A %-m/%-d/%y")
    out = [f"# Panel of Experts — {today_pretty}", ""]
    for name in ("Quant", "Cynic", "Careful"):
        text = persona_writeups.get(name, "").strip()
        out.append(f"## {name}")
        out.append("")
        out.append(text if text else "_(no picks)_")
        out.append("")
    return "\n".join(out)


def run(date_str: str | None = None) -> None:
    db.init()
    today = date.fromisoformat(date_str) if date_str else date.today()
    today_key = today.isoformat()
    today_pretty = today.strftime("%A %-m/%-d/%y")
    today_fn = today.strftime("%Y_%m_%d")

    # Make sure the games table has today's schedule cached so matchup
    # resolution in persist_bets() works.
    try:
        with db.connect() as conn:
            cache_day(conn, today_key)
    except Exception as e:
        print(f"Schedule pre-cache failed: {e}")

    matchups = todays_matchups(today_key)
    print(f"Loaded {len(matchups)} matchup(s).")

    print("Fetching MLB slate with probables + weather...")
    slate = mlb_schedule_with_probables(today_key)
    print(f"  {len(slate)} game(s).")

    if not slate:
        print("No games today. Exiting.")
        return

    print("Pulling savant baselines (once per day)...")
    year = today.year
    batter_idx = _batter_blob(savant_batter_expected(year, today_key))
    arsenal_idx = _pitcher_arsenal_blob(
        savant_pitcher_arsenal(year, today_key),
    )
    print(
        f"  {len(batter_idx)} batters, "
        f"{len(arsenal_idx)} pitchers indexed."
    )

    capper_bets = capper_bets_for_date(today_key)
    print(f"Capper bets ingested so far today: {len(capper_bets)}.")

    print("Fetching consensus market lines...")
    consensus_block = _consensus_block(today_key)

    # Clear any prior panel bets for today so this run is idempotent.
    deleted = reset_panel_bets(today_key)
    if deleted:
        print(f"Cleared {deleted} prior panel bet(s) for today.")

    # Read each persona's record up front so the workers below touch the DB
    # not at all — the fan-out is only safe because every write in this
    # function happens on this thread.
    records = {name: persona_record(cfg["label"])
               for name, cfg in PERSONAS.items()}

    def _one(name: str) -> dict:
        """A persona's writeup and its extracted bets. Two chained LLM
        calls, no persistence — persist_bets() reads its dedup set and
        inserts on two separate connections, so it must not run concurrently
        with itself."""
        # Present the slate in a random order per persona so no one's picks
        # are anchored to the chronological ordering (which was silently
        # starving the late West-Coast games). Seeded by date+persona so a
        # re-run of the same day is reproducible.
        shuffled_slate = list(slate)
        random.Random(f"{today_key}:{name}").shuffle(shuffled_slate)
        writeup = run_persona(
            name, shuffled_slate, capper_bets, records[name],
            arsenal_idx, batter_idx, today_pretty,
            consensus_block,
        )
        # Extraction is caught separately: a writeup that parses badly is
        # still worth rendering to the markdown, same as before.
        try:
            return {"writeup": writeup,
                    "structured": extract_structured_bets(writeup, matchups)}
        except Exception as e:  # noqa: BLE001
            return {"writeup": writeup, "structured": None, "error": e}

    print(f"\n{len(PERSONAS)} personas thinking in parallel...")
    persona_writeups: dict[str, str] = {}
    for name, got, err in parallel.gather(_one, list(PERSONAS)):
        print(f"\n[{name}]")
        if err:
            print(f"  failed: {err}")
            persona_writeups[name] = f"_(error: {err})_"
            continue
        persona_writeups[name] = got["writeup"]
        print(f"  Got {len(got['writeup'])} chars of writeup.")
        if got.get("error"):
            print(f"  Extraction failed: {got['error']}")
            continue
        n = persist_bets(
            today_key, PERSONAS[name]["label"],
            f"panel:{today_key}:{name}", got["structured"],
        )
        print(f"  Persisted {n} bet(s).")

    md = render_panel_markdown(today_key, persona_writeups)
    out_path = BETS_DIR / f"{today_fn}_panel.md"
    out_path.write_text(md)
    print(f"\nWrote {out_path}")

    # Recommender is the 4th panel member: it picks from everything the
    # cappers + personas have on the board and shows on /panel/ alongside
    # them. Run last so the slate it sees includes today's persona picks.
    print("\nRunning recommender...")
    try:
        from src import recommend
        recommend.run(today_key)
    except Exception as e:
        print(f"  Recommender failed: {e}")


# ── bankroll tracking ──────────────────────────────────────────────────
STARTING_BANKROLL_CENTS = 500_000  # $5,000
UNIT_CENTS = 5_000  # $50 = 1 unit
PANEL_LABELS = [cfg["label"] for cfg in PERSONAS.values()] + [
    "Recommendation",
]


def american_to_profit_cents(odds: int, stake_cents: int) -> int:
    """Profit in cents on a winning American-odds bet (excludes stake)."""
    if odds >= 0:
        return int(round(stake_cents * odds / 100))
    return int(round(stake_cents * 100 / abs(odds)))


def settle_bet(
    result: str, stake_cents: int | None, odds: int | None,
) -> int:
    """P&L in cents for one bet. 0 if no stake, PENDING, or UNGRADABLE.

    If a persona staked a bet but forgot to record the price, default to
    -110 (standard juice) so the result still settles into the bankroll.
    """
    if not stake_cents:
        return 0
    if odds is None:
        odds = -110
    if result == "W":
        return american_to_profit_cents(odds, stake_cents)
    if result == "L":
        return -stake_cents
    return 0  # PUSH / PENDING / UNGRADABLE


def bankroll_status(persona_label: str) -> dict:
    """Return bankroll, P&L counts, and per-bet history for a persona."""
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, date, matchup, player_name, stat, line, side, "
            "bet_type, period, confidence, result, actual_value, "
            "stake_cents, american_odds, rationale "
            "FROM bets WHERE source_label=? "
            "ORDER BY date, id",
            (persona_label,),
        ).fetchall()]
    bankroll = STARTING_BANKROLL_CENTS
    history = []
    counts = {
        "W": 0, "L": 0, "PUSH": 0, "PENDING": 0,
        "UNGRADABLE": 0, "SKIPPED": 0,
    }
    total_staked = 0
    by_day: dict[str, dict] = {}
    for r in rows:
        stake = r.get("stake_cents")
        odds = r.get("american_odds")
        result = r["result"]
        if stake is None:
            # legacy row with no stake info — show in history, ignore in P&L
            profit = 0
            bucket = result
        elif stake == 0:
            counts["SKIPPED"] += 1
            profit = 0
            bucket = "SKIPPED"
        else:
            counts[result] = counts.get(result, 0) + 1
            total_staked += stake
            profit = settle_bet(result, stake, odds)
            bucket = result
        bankroll += profit
        history.append({
            **r,
            "profit_cents": profit,
            "bankroll_after_cents": bankroll,
            "bucket": bucket,
        })
        day = by_day.setdefault(
            r["date"],
            {"date": r["date"], "staked_cents": 0, "profit_cents": 0,
             "picks": 0, "bets": 0},
        )
        day["picks"] += 1
        if stake and stake > 0:
            day["bets"] += 1
            day["staked_cents"] += stake
        day["profit_cents"] += profit
    return {
        "label": persona_label,
        "starting_cents": STARTING_BANKROLL_CENTS,
        "current_cents": bankroll,
        "total_staked_cents": total_staked,
        "counts": counts,
        "history": history,
        "by_day": sorted(by_day.values(), key=lambda d: d["date"]),
    }


def all_bankrolls() -> list[dict]:
    """Bankroll status for every persona, in PERSONAS order."""
    return [bankroll_status(label) for label in PANEL_LABELS]


# ── housekeeping ───────────────────────────────────────────────────────
def reset_panel_bets(date_str: str) -> int:
    """Delete all Panel: * bets for a given date. Used to re-run a day cleanly.

    Returns the number of rows deleted.
    """
    with db.connect() as conn:
        cur = conn.execute(
            "DELETE FROM bets WHERE date=? AND source_label LIKE 'Panel:%'",
            (date_str,),
        )
        return cur.rowcount


def card_exists(date_str: str) -> bool:
    """True when this date already has a consensus card.

    Rebuilding a card the user has already read — and bet — changes the
    advice out from under them and costs another full persona pass, so the
    scheduled run skips a day that is already done.
    """
    # Lazy: panel and recommend import each other, same as run() below.
    from src.recommend import RECOMMENDER_LABEL
    with db.connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM bets WHERE date=? AND source_label=? LIMIT 1",
            (date_str, RECOMMENDER_LABEL),
        ).fetchone()
    return row is not None


if __name__ == "__main__":
    import sys
    # Strip every flag, not just --if-needed: a second flag used to fall
    # through into args[0] and be parsed as the date.
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if_needed = "--if-needed" in sys.argv
    want_email = "--email" in sys.argv
    if args and args[0] == "reset":
        target = args[1] if len(args) > 1 else date.today().isoformat()
        n = reset_panel_bets(target)
        print(f"Deleted {n} panel bet(s) for {target}")
    else:
        arg = args[0] if args else None
        target = arg or date.today().isoformat()
        if if_needed and card_exists(target):
            print(f"{target} already has a card — skipping panel.")
        else:
            run(arg)
            if want_email:
                # A hand-run rebuild should land in the inbox; leaving the
                # old digest as the only copy is how the card and the
                # advice actually being read drift apart.
                print("\n=== email ===")
                from src import emailer
                emailer.run(target, if_needed=False)
