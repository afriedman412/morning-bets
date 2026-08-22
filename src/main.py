"""Morning Bets: pull YouTube transcripts and write per-game markdown summaries."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import anthropic
import yt_dlp
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi

from src import db
from src.grading import (
    todays_matchups, fill_missing_lines, fill_missing_prop_lines, cache_day,
    resolve_canonical_matchup, normalize_stat, repair_stat_line,
    repair_stat_position,
)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── config ──────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SENT_FILE = PROJECT_ROOT / "sent.json"
BETS_DIR = PROJECT_ROOT / "bets"


def _warn_if_truncated(message, where: str) -> None:
    """Loudly flag a response that hit the output-token ceiling. These calls
    write summaries game-by-game, so a max_tokens cut silently drops the tail
    of the slate — usually the later games. Better to see it than to lose them."""
    if getattr(message, "stop_reason", None) == "max_tokens":
        print(
            f"  !! WARNING: {where} hit max_tokens — output truncated; "
            f"later games in the slate may have been dropped. "
            f"Consider raising max_tokens."
        )


def _is_mlb(title: str) -> bool:
    """True when a title is MLB content.

    Several of these channels post WNBA/CFL/CFB shows on the same day with
    near-identical title formats. Those used to pass the per-channel filter,
    get a transcript pulled and a summary paid for, and then get discarded by
    persist_bets' sport check — burning spend and producing zero bets.
    """
    t = title.lower()
    other_sports = (
        "wnba", "nfl", "cfl", "cfb", "college football", "nhl",
        "soccer", "ufc", "tennis", "golf", "nascar",
    )
    if any(s in t for s in other_sports):
        return False
    return "mlb" in t or "baseball" in t


def _is_nba(title: str) -> bool:
    """True when a title is NBA content.

    'wnba' is checked first and rejected outright, since it contains 'nba'
    as a substring — several of these channels post WNBA daily through the
    NBA offseason.
    """
    t = title.lower()
    if "wnba" in t:
        return False
    other_sports = (
        "mlb", "baseball", "nfl", "cfl", "cfb", "college football", "nhl",
        "soccer", "ufc", "tennis", "golf", "nascar",
    )
    if any(s in t for s in other_sports):
        return False
    return "nba" in t or "basketball" in t


CHANNELS = {
    "oddsshopper": {
        "url": "https://www.youtube.com/@OddsShopper",
        "match": lambda title: all(
            kw.lower() in title.lower()
            for kw in ["lindy", "leans", "locks"]
        ),
        "label": "Lindy's Leans Likes & Locks",
        "prompt_extra": (
            "Lindy's whole format is LEANS, LIKES, and LOCKS — three "
            "tiers in ascending confidence. Tag every pick with its tier "
            "as [LEAN], [LIKE], or [LOCK].\n\n"
            "CRITICAL: Lindy's lean language is INCLUSIVE. Treat all of "
            "these as picks (default to [LEAN] when tier isn't explicit):\n"
            "  • 'I'm looking at the under/over/X'\n"
            "  • 'I'm leaning toward X'\n"
            "  • 'I'm interested in X' / 'lots of interest in X'\n"
            "  • 'I haven't pulled the trigger YET but...' (he means he "
            "will, just waiting on line movement)\n"
            "  • 'X is in play' / 'I like X here'\n\n"
            "ONLY exclude a pick if he explicitly fades or passes:\n"
            "  • 'I'm passing on X' / 'no interest'\n"
            "  • 'I don't like X' / 'fade this'\n"
            "  • 'too juiced for me' (without endorsing the side)\n\n"
            "If the tier isn't explicitly stated but the pick is "
            "endorsed, use [UNCLEAR]. Do not drop picks just because he "
            "hasn't placed the wager yet."
        ),
    },
    "daftpreviews": {
        "url": "https://www.youtube.com/@daftpreviews",
        # NBA-only source (its 51 historical bets are all 6/3-6/13, the NBA
        # Finals). Was `lambda title: True`, which accepted every upload —
        # so once the channel switched to WNBA for the summer it ingested a
        # transcript and paid for a summary every day for zero bets.
        # Expect this to stay dormant until the NBA season resumes.
        "match": lambda title: _is_nba(title),
        "label": "Daft Previews",
    },
    "pickdawgz": {
        "url": "https://www.youtube.com/@PickDawgz",
        "match": lambda title: "ron's rundown" in title.lower(),
        "label": "PickDawgz - Ron's Rundown",
    },
    "callingourshot_mlb": {
        "url": "https://www.youtube.com/@CallingOurShot",
        "match": lambda title: (
            "mlb best picks and predictions" in title.lower()
        ),
        "label": "Calling Our Shot - MLB",
    },
    "callingourshot_nba": {
        "url": "https://www.youtube.com/@CallingOurShot",
        "match": lambda title: (
            "best picks & predictions" in title.lower()
            and "mlb" not in title.lower()
        ),
        "label": "Calling Our Shot - NBA",
    },
    "oddsshopper_livewithlindy": {
        "url": "https://www.youtube.com/@OddsShopper",
        "tab": "streams",
        "match": lambda title: "live with lindy" in title.lower(),
        "label": "Live With Lindy",
    },
    "oddsshopper_snipesession": {
        "url": "https://www.youtube.com/@OddsShopper",
        "tab": "streams",
        # "Snipe Session" no longer exists; the slot is now the daily home-run
        # show from The Yard. Repointed rather than retired because it is
        # live HR-prop content and this label has zero historical rows, so
        # nothing is orphaned by the rename.
        "match": lambda title: any(
            k in title.lower()
            for k in ("daily dingers", "the yard", "going deep")
        ),
        "label": "OddsShopper - Daily Dingers (HR props)",
    },
    "wagertalk_drewsdiamond": {
        "url": "https://www.youtube.com/@WagerTalk",
        "match": lambda title: "drew's daily diamond" in title.lower(),
        "label": "WagerTalk - Drew's Daily Diamond",
    },
    "wagertalk_stevemerril": {
        "url": "https://www.youtube.com/@WagerTalk",
        "match": lambda title: "steve merril" in title.lower(),
        "label": "WagerTalk - Steve Merril",
    },
    "wagertalk_bestmlbbets": {
        "url": "https://www.youtube.com/@WagerTalk",
        "match": lambda title: "best mlb bets" in title.lower(),
        "label": "WagerTalk - Best MLB Bets",
    },
    "wagertalk_giannithegreek": {
        "url": "https://www.youtube.com/@WagerTalk",
        # Gianni's show is gone from the channel. Repointed to WagerTalk's
        # uncaptured First Five show, which is first-5-innings content the
        # grader already supports via period='f5'. Zero historical rows under
        # the old label, so the rename orphans nothing.
        "match": lambda title: (
            "first five" in title.lower() and _is_mlb(title)
        ),
        "label": "WagerTalk - First Five",
        "prompt_extra": (
            "This show covers FIRST FIVE INNINGS (F5) bets. Unless a pick "
            "is explicitly stated as a full-game wager, tag it as an F5 "
            "bet so it is graded against the first-5-innings score."
        ),
    },
    "bettingpros": {
        "url": "https://www.youtube.com/@BettingPros",
        "match": lambda title: "bets for" in title.lower(),
        "label": "BettingPros - Daily Top Bets",
    },
    "guybostonsports": {
        "url": "https://www.youtube.com/@GuyBostonSports",
        # Was `"predictions, & player props"`. The channel writes "and", not
        # "&", so this silently matched nothing from 2026-06-23 onward —
        # after contributing 401 bets at 172-144 (54.4%), the best record of
        # any source. They post a WNBA video daily in the same format, hence
        # the _is_mlb guard.
        "match": lambda title: (
            "mlb picks today" in title.lower() and _is_mlb(title)
        ),
        "label": "Guy Boston Sports - MLB",
    },
    "silverbackbets": {
        "url": "https://www.youtube.com/@silverbackbets",
        # Required two substrings that never co-occur ("mlb picks and
        # predictions" AND "best mlb bets today"); real titles alternate
        # between those phrasings. Dead since 2026-06-25.
        "match": lambda title: (
            "mlb picks" in title.lower() and _is_mlb(title)
        ),
        "label": "Silverback Bets - MLB",
    },
    "docssports_craigtrapp": {
        "url": "https://www.youtube.com/@Docs_Sports_Picks",
        # Craig Trapp covers several sports; ~2/3 of matched videos were WNBA.
        "match": lambda title: (
            "craig trapp" in title.lower() and _is_mlb(title)
        ),
        "label": "Doc's Sports - Craig Trapp MLB",
    },
}

# ── helpers ─────────────────────────────────────────────────────────────


def load_sent() -> dict:
    if SENT_FILE.exists():
        return json.loads(SENT_FILE.read_text())
    return {}


def save_sent(sent: dict) -> None:
    SENT_FILE.write_text(json.dumps(sent, indent=2))


def find_video(channel_key: str) -> dict | None:
    """Find today's target video for a channel."""
    cfg = CHANNELS[channel_key]

    flat_opts = {
        "extract_flat": True,
        "playlistend": 50,
        "quiet": True,
        "no_warnings": True,
    }
    tab = cfg.get("tab", "videos")
    with yt_dlp.YoutubeDL(flat_opts) as ydl:
        info = ydl.extract_info(f"{cfg['url']}/{tab}", download=False)
    entries = info.get("entries") or []

    today = date.today()
    acceptable = {today.strftime("%Y%m%d")}
    if tab != "streams":
        acceptable.add((today - timedelta(days=1)).strftime("%Y%m%d"))

    full_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    for entry in entries:
        title = entry.get("title") or ""
        video_id = entry.get("id") or ""
        if not (title and video_id and cfg["match"](title)):
            continue
        try:
            with yt_dlp.YoutubeDL(full_opts) as ydl:
                full = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}",
                    download=False,
                )
        except Exception:
            continue
        # For finished livestreams, upload_date can lag the actual air date
        # by a day. Use release_date (when the stream went live) instead.
        live_status = full.get("live_status")
        if live_status in ("was_live", "is_live"):
            video_date = full.get("release_date") or full.get("upload_date")
        else:
            video_date = full.get("upload_date")
        if video_date not in acceptable:
            continue
        if not title_is_about_today(title, today):
            print(f"  Skipping (title not for today): {title}")
            continue
        return {"video_id": video_id, "title": title}

    return None


def transcript_is_about_today(transcript: str, today: date) -> bool:
    """Confirm via Haiku that the transcript actually covers today's games.

    Catches the case where the title passed the date check but the host
    opens with 'welcome to Tuesday's picks' or similar — a video that was
    backdated, re-uploaded, or whose title is misleading.
    """
    if not transcript:
        return True
    snippet = transcript[:2000]
    day_of_week = today.strftime("%A")
    month_day = today.strftime("%B %-d")  # e.g. "June 4"
    short = today.strftime("%-m/%-d")
    prompt = (
        f"Today is {day_of_week}, {month_day} ({short}).\n\n"
        f"Below is the opening of a sports-betting video transcript. "
        f"Classify whether the host explicitly anchors the video to a "
        f"DIFFERENT specific day.\n\n"
        f"Reply with exactly one word, no preamble:\n"
        f"  MATCH — host names the right day ({day_of_week} or "
        f"{month_day}), or no date is mentioned at all.\n"
        f"  MISMATCH — host clearly names a different specific day "
        f"(e.g. says 'today is Tuesday' when today is Wednesday).\n\n"
        f"'Yesterday' or 'tomorrow' references are NOT mismatches — "
        f"they're past/future context. Year is irrelevant.\n\n"
        f"TRANSCRIPT:\n{snippet}\n\n"
        f"Answer (single word, MATCH or MISMATCH):"
    )
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=6,
            messages=[{"role": "user", "content": prompt}],
        )
        word = msg.content[0].text.strip().upper()
        # Treat anything other than a clear MISMATCH as match.
        return not word.startswith("MISMATCH")
    except Exception:
        return True  # fail open


def title_is_about_today(title: str, today: date) -> bool:
    """Ask Claude if a video title plausibly refers to today's games."""
    target = today.strftime("%A %B %-d, %Y")
    short = today.strftime("%-m/%-d")
    prompt = (
        f"A YouTube sports-betting video has this title. Decide whether it "
        f"could plausibly be about events on {target} (i.e. {short}).\n\n"
        f"TITLE: {title}\n\n"
        f"Reply with one word: YES if it could be about that date "
        f"(including titles with no date, generic 'today', or a specific "
        f"game/series scheduled for that date), or NO if it clearly "
        f"refers to a different specific date (e.g. yesterday's date or "
        f"a different day of week)."
    )
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip().upper().startswith("Y")
    except Exception:
        # Fail open — don't block a video on a Claude outage.
        return True


def get_transcript(video_id: str) -> str:
    """Pull the transcript text for a YouTube video.

    Routes through a Webshare residential proxy if WEBSHARE_USERNAME +
    WEBSHARE_PASSWORD are set in env; otherwise hits YouTube directly.
    Retries on transient network errors (IncompleteRead, conn reset, etc.).
    """
    import time

    proxy_user = os.environ.get("WEBSHARE_USERNAME")
    proxy_pw = os.environ.get("WEBSHARE_PASSWORD")
    if proxy_user and proxy_pw:
        from youtube_transcript_api.proxies import WebshareProxyConfig
        ytt_api = YouTubeTranscriptApi(
            proxy_config=WebshareProxyConfig(
                proxy_username=proxy_user,
                proxy_password=proxy_pw,
            ),
        )
    else:
        ytt_api = YouTubeTranscriptApi()

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            transcript = ytt_api.fetch(video_id)
            lines = [snippet.text for snippet in transcript]
            return " ".join(lines)
        except Exception as e:
            msg = str(e).lower()
            transient = (
                "incompleteread" in msg
                or "connection" in msg
                or "timeout" in msg
                or "reset" in msg
                or "broken pipe" in msg
            )
            if not transient:
                raise
            last_err = e
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise last_err  # type: ignore[misc]


def summarize(
    title: str,
    transcript: str,
    label: str,
    prompt_extra: str = "",
) -> str:
    """Use Claude to summarize a betting video transcript."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    extra_block = f"\n\nCHANNEL-SPECIFIC INSTRUCTIONS: {prompt_extra}" if prompt_extra else ""

    prompt = f"""Below is the transcript of a daily sports betting video titled "{title}" from {label}.

IMPORTANT: Only include picks and information that are EXPLICITLY stated in the transcript below. Do NOT infer, fabricate, or add any picks, players, stats, or reasoning that are not directly mentioned. If something is unclear in the transcript, note that it's unclear rather than guessing.

Please provide a clear, concise summary that captures:
- All specific picks/bets mentioned (teams, spreads, totals, moneylines)
- The confidence level for each pick if mentioned (lean, like, lock, etc.)
- Any key reasoning or stats cited for the picks
- Which games/matchups are covered

Format the summary as a clean bulleted list grouped by game/matchup.
Do NOT include a title or header — just go straight into the picks.{extra_block}

TRANSCRIPT:
{transcript}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    _warn_if_truncated(message, f"summarize({label})")
    return message.content[0].text


EXTRACT_PROMPT = """Below is a per-source summary of sports betting picks for one daily betting video.

You may also see a "TODAY'S MATCHUPS" section listing every MLB and NBA game scheduled today. Use it as ground truth when filling the `matchup` field — match each pick to the actual game its player or team belongs to. If a pick's matchup isn't obvious from the summary text, use the player's team membership (your general knowledge) plus the matchups list to determine which game it belongs to.

Your job: extract every distinct pick into a structured JSON array. One object per pick. Output ONLY the JSON array, no prose.

Schema for each pick:
{
  "sport": "mlb" | "nba" | "other",
  "matchup": short string like "Yankees vs A's" or "Spurs vs Thunder Game 7" (or null if not tied to a game),
  "player_name": full name like "Aaron Judge" (null for team bets),
  "stat": canonical stat key. Use these EXACTLY:
    NBA: pts, reb, oreb, dreb, ast, stl, blk, to, fgm, fga, fg3m, fg3a, ftm, fta, min, plus_minus
    MLB batting: ab, r, h, "1b", "2b", "3b", hr, rbi, bb, so, sb, tb
    MLB pitching: outs, k, bb_allowed, h_allowed, r_allowed, er, hr_allowed, decision
    Team bets: ml, spread, total
    Combo props: join with "+" e.g. "pts+reb+ast", "pts+ast", "h+r+rbi"
  "line": number (e.g. 7.5 for "over 7.5"); for ML use null; for "anytime HR" use 0.5; for spreads, negative for favorite (-3.5) positive for dog (+3.5),
  "side": "over" | "under" | team name (for ML/spread),
  "bet_type": "ml" | "spread" | "total" | "team_total" | "prop" | "combo",
  "period": "full" | "f5". Default to "full". Use "f5" for MLB first-half / first-five-innings bets ("F5 over 4.5", "first 5 innings run line", "1st half under 4"). NBA first-half doesn't apply here yet — leave as "full" if not clearly F5.,
  "confidence": "LEAN" | "LIKE" | "LOCK" | null,
  "rationale": "one-sentence paraphrase of the source's SPECIFIC reasoning — must cite stats, named players, matchups, or concrete trends. Leave null if the source only gave generic phrases like 'they like this', 'going with this one', 'already bet', 'value pick', or no reasoning at all. Be strict: when in doubt, leave null. Do NOT invent rationale.",
  "stake_cents": integer cents staked on this bet, or null if the source didn't specify a dollar amount. Most YouTube cappers don't — leave null. Panel-of-experts writeups DO specify a stake (e.g. "Stake: $25" → 2500, "$50" → 5000, "$0 (skip)" → 0).,
  "american_odds": integer American odds at which the bet was placed (e.g. -116, 130, -200), or null if no price was stated. Leave null when in doubt. Watch for prices in parens after the bet, like "Yankees -1.5 (+125)" → 125.
}

Rules:
- Set sport="other" for anything that's not MLB or NBA (NFL, NHL, WNBA, college basketball, golf, soccer, UFC, tennis, etc.). WNBA specifically is NOT NBA — tag it "other" even though both are basketball.
- For "Aaron Judge home run" or "Castle to score a TD"-type anytime bets, use line=0.5, side="over", stat="hr" (or relevant stat).
- For combo props like "PRA" (pts+reb+ast) or "P+A", use bet_type="combo" and join components with "+".
- TEAM TOTAL vs GAME TOTAL — critical distinction: a "team total" is the runs/points scored by ONE team only ("Yankees team total over 4.5", "Rockies over 3.5 runs", "Lakers team total over 112.5"). Use bet_type="team_total", player_name=<team name>, side="over"|"under", line=<number>, stat=null. A game total ("over 8.5", "under 220.5" with no team named) is bet_type="total" with player_name=null. If the source says just "over 4.5" and the context makes clear it's one team's total (e.g. listed under a single team's props), treat it as team_total.
- If a pick is mentioned but the line wasn't stated, still emit it with line=null. (Grader will mark UNGRADABLE.)
- Skip parlays, futures, season-long bets, and non-specific commentary.
- Use the EXACT stat keys above. Don't invent new ones.
- ALWAYS fill in `matchup` for every bet. Match it to the corresponding game from the TODAY'S MATCHUPS list when possible (use the exact "Away @ Home" string from that list). Never leave matchup null when the game is identifiable — that includes flat lists of player props grouped by bet type (e.g. "Home Run Bets:", "Strikeout Parlay:"), where the matchup must be inferred per player.
- Prefer the player's full name when stated. If only a nickname/abbreviation is used in the summary (e.g. "SGA", "Wemby"), keep that — grading will handle aliases.
"""


def extract_structured_bets(
    summary_text: str,
    matchups: list[str] | None = None,
) -> list[dict]:
    """Call Claude to convert a free-text bet summary into structured rows."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    matchups_block = ""
    if matchups:
        matchups_block = (
            "\n\nTODAY'S MATCHUPS:\n"
            + "\n".join(f"- {m}" for m in matchups)
            + "\n"
        )
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        messages=[{
            "role": "user",
            "content": EXTRACT_PROMPT + matchups_block + "\nSUMMARY:\n" + summary_text,
        }],
    )
    _warn_if_truncated(message, "extract_structured_bets")
    text = message.content[0].text.strip()
    # Tolerate fenced code blocks
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def _normalize_matchup(m: str | None) -> str | None:
    """Canonicalize matchup strings so dedup catches 'vs.' / 'vs' / 'at' / '@'
    variants of the same game."""
    if not m:
        return m
    s = m.strip()
    # Replace " vs. " / " vs " / " at " with " @ " (case-insensitive)
    for sep in (" vs. ", " VS. ", " vs ", " VS ", " at ", " AT "):
        s = s.replace(sep, " @ ")
    return s


def persist_bets(
    date_str: str,
    source_label: str,
    video_id: str,
    bets_data: list[dict],
) -> int:
    """Insert structured bets into the bets table, deduping within the batch
    and against rows already persisted for the same (date, source).
    Key: (player_name, stat, side, line, matchup, bet_type).
    Returns count inserted.
    """
    with db.connect() as conn:
        existing = {
            (r["player_name"], r["stat"], r["side"], r["line"],
             _normalize_matchup(r["matchup"]), r["bet_type"],
             r["period"] or "full")
            for r in conn.execute(
                "SELECT player_name, stat, side, line, matchup, bet_type, "
                "period FROM bets WHERE date=? AND source_label=?",
                (date_str, source_label),
            ).fetchall()
        }

        rows = []
        seen = set(existing)
        for b in bets_data:
            sport = b.get("sport")
            if sport not in ("mlb", "nba"):
                continue  # drop WNBA / NHL / golf — we don't grade them
            bt = b.get("bet_type") or "prop"
            period = b.get("period") or "full"
            # The schema says team_total carries the club in player_name and
            # leaves stat null, but extraction sometimes fills stat='total'.
            # Since stat is part of the dedup key, the same wager then lands
            # twice under one capper — which reads to the personas as two
            # independent calls. Normalize before the key is built.
            b = {**b, "stat": normalize_stat(b.get("stat"))}
            # Two repairs, in this order. Position first: it decides WHICH
            # stat the bet is, and that determines the bounds the magnitude
            # check then applies. Running them the other way would test a
            # batter's strikeout line against pitcher-strikeout bounds.
            pos_stat, pos_note = repair_stat_position(
                b.get("stat"), b.get("player_name"),
            )
            if pos_note:
                print(
                    f"  !! {source_label}: {b.get('player_name')} "
                    f"{b.get('stat')} {b.get('side')} {b.get('line')} "
                    f"— {pos_note}"
                )
                b = {**b, "stat": pos_stat}
            # A line impossible for its stat is damage — a mistranscribed
            # magnitude or a mislabelled stat — so fix it here, before it
            # reaches the personas and gets three theses written about it.
            # The corrected value becomes `stated_line` below on purpose:
            # the source really did say "15 outs", and recording 1.5 as
            # their number would blame them for our transcript.
            fixed_stat, fixed_line, note = repair_stat_line(
                b.get("stat"), b.get("line"),
            )
            if note:
                print(
                    f"  !! {source_label}: {b.get('player_name')} "
                    f"{b.get('stat')} {b.get('side')} {b.get('line')} — {note}"
                )
                b = {**b, "stat": fixed_stat, "line": fixed_line}
            if bt == "team_total":
                b = {**b, "stat": None}
            matchup = _normalize_matchup(b.get("matchup"))
            # Resolve to the canonical 'Away Team @ Home Team' from the
            # games table so 'Athletics @ Cubs' and 'Oakland Athletics
            # @ Chicago Cubs' both collapse to one row.
            matchup = resolve_canonical_matchup(
                conn, matchup, sport, date_str,
            )
            key = (
                b.get("player_name"), b.get("stat"), b.get("side"),
                b.get("line"), matchup, bt, period,
            )
            if key in seen:
                continue
            seen.add(key)
            # Freeze what the source said before anything downstream can
            # fill or reprice it. `quoted_odds` is the recommender's name
            # for the same thing — it holds the persona's own price when
            # assign_stakes has already overwritten american_odds with the
            # book's. Absent key, not None, is what distinguishes "never
            # repriced" from "stated no price".
            stated_odds = b.get("quoted_odds", b.get("american_odds"))
            rows.append((
                date_str, source_label, video_id,
                json.dumps(b, ensure_ascii=False),
                sport, matchup, b.get("player_name"),
                b.get("stat"), b.get("line"), b.get("side"),
                bt, period, b.get("confidence"), b.get("rationale"),
                b.get("stake_cents"), b.get("american_odds"),
                b.get("line"), stated_odds,
            ))

    if not rows:
        return 0
    with db.connect() as conn:
        conn.executemany(
            """INSERT INTO bets
            (date, source_label, source_video_id, raw_text,
             sport, matchup, player_name, stat, line, side,
             bet_type, period, confidence, rationale,
             stake_cents, american_odds, stated_line, stated_odds)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    return len(rows)


def merge_summaries(
    summaries: list[dict],
    matchups: list[str] | None = None,
) -> str:
    """Use Claude to merge per-source summaries into a per-game markdown list."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    today = date.today().strftime("%A %-m/%-d/%y")

    source_blocks = "\n\n".join(
        f"### {s['label']}\n"
        f"Video: https://youtube.com/watch?v={s['video_id']} ({s['title']})\n\n"
        f"{s['summary']}"
        for s in summaries
    )

    matchups_block = ""
    if matchups:
        matchups_block = (
            "\n\nTODAY'S MATCHUPS (use these EXACT strings as ## headers — "
            "never group bets under a single team name):\n"
            + "\n".join(f"- {m}" for m in matchups)
            + "\n"
        )

    prompt = f"""Below are bet summaries from {len(summaries)} different sports betting sources for {today}.

Merge them into a single markdown document organized BY GAME/MATCHUP. For each game, list the specific bets that were called out and which sources called each one. Preserve any confidence tier (LEAN/LIKE/LOCK) explicitly mentioned. Include the source's rationale for each pick when given.

Output format:

# Daily Bets — {today}

## [Game/Matchup]
- **[Bet]** — [Source 1] [tier if applicable], [Source 2], ...
  - [Source 1]: [concise rationale from that source]
  - [Source 2]: [concise rationale from that source]
- **[Bet]** — [Source]
  - [Source]: [rationale]

## [Next Game]
...

## Sources
- [Source label](video URL) — video title
- ...

Rules:
- Use the TODAY'S MATCHUPS list below as the authoritative source of game/matchup names. Every ## header MUST be one of those exact strings.
- Never create a header from a single team name (e.g. "Chicago Cubs", "Tampa Bay"). A single-team bet like "Cubs moneyline" or "Cubs team total over 4.5" goes under the actual matchup that includes the Cubs.
- Group all bets by matchup, not by source.
- A "bet" includes spreads, game totals, team totals (one team's runs/points over/under), moneylines, and player props. Preserve the team name in team-total bets — write "Cubs team total over 4.5", not just "over 4.5".
- If a bet is a first-half / first-5-innings bet (MLB F5), prefix the bet with "F5" — e.g. "F5 Over 4.5", "F5 Yankees -0.5 runline", "F5 Cubs team total over 2.5". Do NOT merge F5 bets with full-game bets on the same market; they're separate lines.
- If multiple sources called the same bet, combine them on one line with all sources listed; give each source its own rationale sub-bullet.
- Preserve confidence tiers from Lindy (LEAN/LIKE/LOCK) as bracketed tags after the source name.
- Rationale sub-bullets should be ONE concise sentence each, paraphrased from the source's reasoning (key stats, matchups, trends, etc.). Skip the rationale sub-bullet entirely for a source that gave no reasoning — do NOT invent one.
- Only include picks and reasoning that were EXPLICITLY stated in the source summaries. Do NOT infer.
- If a source covered a game but didn't name a specific bet, skip it for that game.
- Order games by how many sources covered them (most covered first).
{matchups_block}
SOURCES:
{source_blocks}"""

    # Output scales with sources x games: one bullet per bet plus a rationale
    # sub-bullet per source that called it. At 6000 this truncated on every
    # run with 7+ sources, silently dropping the tail of the slate — and the
    # channel-filter repairs took a normal day from 3-5 sources to 11-15.
    # A full 15-source slate lands near 6-7k output, so this leaves real
    # headroom; unused output tokens are not billed.
    # Streaming is required by the SDK once max_tokens is high enough that a
    # response could exceed the 10-minute non-streaming timeout.
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=24000,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        message = stream.get_final_message()
    _warn_if_truncated(message, "merge_summaries")
    return message.content[0].text


# ── main ────────────────────────────────────────────────────────────────
def _all_sent_video_ids(sent: dict) -> set[str]:
    """Collect every video ID we've already sent, across all dates."""
    ids: set[str] = set()
    for day_entries in sent.values():
        ids.update(day_entries.values())
    return ids


def discover(slate_date: str | None = None) -> int:
    """Find today's videos and queue them. No transcript, no Sonnet.

    Cheap enough to run through the night — a flat playlist listing plus a
    Haiku title check per candidate. Uploads land between 20:30 and 10:15,
    so hourly discovery from midnight means everything is known about long
    before anyone pays to read it.
    """
    db.init()
    today_key = slate_date or date.today().isoformat()
    sent = load_sent()
    already = _all_sent_video_ids(sent)
    found = 0

    with db.connect() as conn:
        queued = {r[0] for r in conn.execute("SELECT video_id FROM video_queue")}

    for channel_key, cfg in CHANNELS.items():
        print(f"[{cfg['label']}] checking...")
        try:
            video = find_video(channel_key)
        except Exception as e:
            print(f"  lookup failed: {e}")
            continue
        if not video:
            print("  nothing yet.")
            continue
        vid = video["video_id"]
        if vid in already or vid in queued:
            print(f"  already known: {video['title'][:60]}")
            continue
        with db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO video_queue "
                "(video_id, channel_key, label, title, slate_date, found_at) "
                "VALUES (?,?,?,?,?,?)",
                (vid, channel_key, cfg["label"], video["title"], today_key,
                 datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
        found += 1
        print(f"  QUEUED: {video['title'][:70]}")

    print(f"\nDiscovered {found} new video(s) for {today_key}.")
    return found


def pending_videos(slate_date: str | None = None) -> list[dict]:
    d = slate_date or date.today().isoformat()
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM video_queue WHERE slate_date=? AND processed_at IS NULL "
            "ORDER BY found_at", (d,))]


def process(slate_date: str | None = None) -> int:
    """Turn queued videos into bets. This is the part that costs money."""
    db.init()
    today_key = slate_date or date.today().isoformat()
    pending = pending_videos(today_key)
    if not pending:
        print(f"Nothing queued for {today_key}.")
        return 0

    print(f"Processing {len(pending)} queued video(s) for {today_key}...")
    matchups = todays_matchups(today_key)
    filename = today_key.replace("-", "_")
    bets_json_path = BETS_DIR / f"{filename}.json"
    existing: list[dict] = (
        json.loads(bets_json_path.read_text())
        if bets_json_path.exists() else []
    )
    sent = load_sent()
    today_sent = sent.get(today_key, {})
    new_summaries: list[dict] = []

    for q in pending:
        cfg = CHANNELS.get(q["channel_key"], {})
        print(f"[{q['label']}] {q['title'][:60]}")
        try:
            transcript = get_transcript(q["video_id"])
            summary = summarize(q["title"], transcript, q["label"],
                                cfg.get("prompt_extra", ""))
            structured = extract_structured_bets(summary, matchups)
            n = persist_bets(today_key, q["label"], q["video_id"], structured)
            print(f"  persisted {n} bet(s).")
        except Exception as e:
            print(f"  !! failed: {type(e).__name__}: {e}")
            with db.connect() as conn:
                conn.execute(
                    "UPDATE video_queue SET error=?, attempts=attempts+1 "
                    "WHERE video_id=?", (f"{type(e).__name__}: {e}"[:400],
                                         q["video_id"]))
            continue

        new_summaries.append({
            "channel_key": q["channel_key"], "label": q["label"],
            "title": q["title"], "video_id": q["video_id"], "summary": summary,
        })
        today_sent[q["channel_key"]] = q["video_id"]
        sent[today_key] = today_sent
        save_sent(sent)
        with db.connect() as conn:
            conn.execute(
                "UPDATE video_queue SET processed_at=?, n_bets=?, error=NULL "
                "WHERE video_id=?",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 n, q["video_id"]))

    if not new_summaries:
        print("Nothing processed successfully.")
        return 0

    print("Filling missing lines from consensus odds...")
    try:
        with db.connect() as conn:
            n = fill_missing_lines(conn, today_key)
        print(f"  Inferred {n} line(s).")
    except Exception as e:
        print(f"  Consensus odds lookup failed: {e}")

    # Props ESPN cannot see. Runs after the consensus fill so a prop whose
    # line a capper *did* state keeps that number and only gets a price.
    print("Filling missing prop lines + prices from Kalshi...")
    try:
        with db.connect() as conn:
            nl, no = fill_missing_prop_lines(conn, today_key)
        print(f"  Inferred {nl} prop line(s), {no} price(s).")
    except Exception as e:
        print(f"  Kalshi prop lookup failed: {e}")

    all_summaries = existing + new_summaries
    bets_json_path.write_text(json.dumps(all_summaries, indent=2))
    print(f"Merging {len(all_summaries)} source(s)...")
    try:
        md = merge_summaries(all_summaries, matchups)
        (BETS_DIR / f"{filename}.md").write_text(md)
        print(f"  Wrote {BETS_DIR / f'{filename}.md'}")
    except Exception as e:
        print(f"  Merge failed: {e}")
    return len(new_summaries)


def run() -> None:
    """Discover then process, in one pass.

    This is what `make morning` calls. The scheduled agents run the two
    halves on different clocks — discovery hourly through the night because
    it is cheap, processing from 6am because it is not — but a manual run
    wants both, and one code path means they cannot drift apart.
    """
    db.init()
    today_key = date.today().isoformat()
    try:
        with db.connect() as conn:
            cache_day(conn, today_key)
    except Exception as e:
        print(f"Schedule pre-cache failed: {e}")
    discover(today_key)
    process(today_key)


def _detect_channel(info: dict) -> tuple[str, str]:
    """Pick a (label, prompt_extra) for a manually-ingested video by matching
    the video's channel URLs against CHANNELS. Falls back to ("Manual", "").

    yt-dlp returns `channel_url` in /channel/UC... form and `uploader_url` as
    the @handle. CHANNELS stores handles, so both have to be checked — keying
    off whichever is non-empty first never matches a handle."""
    channel_urls = [
        (info.get(key) or "").lower().rstrip("/")
        for key in ("channel_url", "uploader_url")
    ]
    title = info.get("title") or ""
    candidates = [
        cfg for cfg in CHANNELS.values()
        if any(
            url and (
                cfg["url"].lower().rstrip("/") in url
                or url in cfg["url"].lower().rstrip("/")
            )
            for url in channel_urls
        )
    ]
    for cfg in candidates:
        try:
            if cfg["match"](title):
                return cfg["label"], cfg.get("prompt_extra", "")
        except Exception:
            pass
    if candidates:
        return candidates[0]["label"], candidates[0].get("prompt_extra", "")
    return "Manual", ""


def ingest(urls: list[str]) -> None:
    """Manually ingest one or more YouTube URLs into today's bets."""
    db.init()
    today = date.today()
    today_key = today.isoformat()
    today_filename = today.strftime("%Y_%m_%d")

    try:
        with db.connect() as conn:
            cache_day(conn, today_key)
    except Exception as e:
        print(f"Schedule pre-cache failed: {e}")

    matchups = todays_matchups(today_key)
    if matchups:
        print(f"Loaded {len(matchups)} matchup(s) for {today_key}.")

    sent = load_sent()
    today_sent = sent.get(today_key, {})

    bets_json_path = BETS_DIR / f"{today_filename}.json"
    bets_md_path = BETS_DIR / f"{today_filename}.md"
    existing_summaries: list[dict] = (
        json.loads(bets_json_path.read_text())
        if bets_json_path.exists() else []
    )

    new_summaries: list[dict] = []
    full_opts = {"quiet": True, "no_warnings": True, "skip_download": True}

    for url in urls:
        print(f"[manual] {url}")
        try:
            with yt_dlp.YoutubeDL(full_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            print(f"  Could not fetch video metadata: {e}")
            continue

        video_id = info.get("id") or ""
        title = info.get("title") or ""
        if not video_id:
            print("  No video ID resolved.")
            continue

        label, prompt_extra = _detect_channel(info)
        print(f"  {title}")
        print(f"  Source: {label}")

        print("  Pulling transcript...")
        try:
            transcript = get_transcript(video_id)
        except Exception as e:
            print(f"  Could not get transcript: {e}")
            continue

        print("  Summarizing with Claude...")
        try:
            summary = summarize(title, transcript, label, prompt_extra)
        except Exception as e:
            print(f"  Summarization failed: {e}")
            continue

        new_summaries.append({
            "channel_key": f"manual:{video_id}",
            "label": label,
            "title": title,
            "video_id": video_id,
            "summary": summary,
        })
        today_sent[f"manual:{video_id}"] = video_id

        print("  Extracting structured bets...")
        try:
            structured = extract_structured_bets(summary, matchups)
            n = persist_bets(today_key, label, video_id, structured)
            print(f"  Persisted {n} bet(s).")
        except Exception as e:
            print(f"  Bet extraction failed: {e}")

    if not new_summaries:
        print("Nothing new.")
        return

    print("Filling missing lines from consensus odds...")
    try:
        with db.connect() as conn:
            n = fill_missing_lines(conn, today_key)
        print(f"  Inferred {n} line(s).")
    except Exception as e:
        print(f"  Consensus odds lookup failed: {e}")

    print("Filling missing prop lines + prices from Kalshi...")
    try:
        with db.connect() as conn:
            nl, no = fill_missing_prop_lines(conn, today_key)
        print(f"  Inferred {nl} prop line(s), {no} price(s).")
    except Exception as e:
        print(f"  Kalshi prop lookup failed: {e}")

    all_summaries = existing_summaries + new_summaries
    bets_json_path.write_text(json.dumps(all_summaries, indent=2))

    print(
        f"Merging {len(all_summaries)} source(s) "
        f"into {bets_md_path.name}..."
    )
    try:
        markdown = merge_summaries(all_summaries, matchups)
    except Exception as e:
        print(f"  Merge failed: {e}")
        return
    bets_md_path.write_text(markdown)
    print(f"  Wrote {bets_md_path}")

    sent[today_key] = today_sent
    cutoff = (today - timedelta(days=7)).isoformat()
    sent = {k: v for k, v in sent.items() if k >= cutoff}
    save_sent(sent)


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    rest = [a for a in sys.argv[2:] if not a.startswith("--")]
    if cmd == "ingest":
        urls = sys.argv[2:]
        if not urls:
            print("Usage: python -m src.main ingest <url> [<url> ...]")
            sys.exit(1)
        ingest(urls)
    elif cmd == "discover":
        # Cheap: find and queue. Safe to run through the night.
        discover(rest[0] if rest else None)
    elif cmd == "process":
        # Expensive: transcript + Sonnet. Deferred to the morning.
        process(rest[0] if rest else None)
    else:
        run()
