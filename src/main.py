"""Morning Bets: pull YouTube transcripts and write per-game markdown summaries."""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

import anthropic
import yt_dlp
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi

from src import db
from src.grading import todays_matchups, fill_missing_lines

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── config ──────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SENT_FILE = PROJECT_ROOT / "sent.json"
BETS_DIR = PROJECT_ROOT / "bets"

CHANNELS = {
    "oddsshopper": {
        "url": "https://www.youtube.com/@OddsShopper",
        "match": lambda title: all(
            kw.lower() in title.lower()
            for kw in ["lindy", "leans", "locks"]
        ),
        "label": "Lindy's Leans Likes & Locks",
        "prompt_extra": (
            "Lindy tiers every pick as a LEAN, LIKE, or LOCK "
            "(in ascending confidence). Tag every single pick with its "
            "tier — prefix each bullet with [LEAN], [LIKE], or [LOCK]. "
            "If the tier for a pick is not explicitly stated in the "
            "transcript, mark it [UNCLEAR] rather than guessing."
        ),
    },
    "daftpreviews": {
        "url": "https://www.youtube.com/@daftpreviews",
        "match": lambda title: True,
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
        "match": lambda title: "snipe session" in title.lower(),
        "label": "OddsShopper Snipe Session",
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
        "match": lambda title: "gianni the greek" in title.lower(),
        "label": "WagerTalk - Gianni the Greek",
    },
    "bettingpros": {
        "url": "https://www.youtube.com/@BettingPros",
        "match": lambda title: "bets for" in title.lower(),
        "label": "BettingPros - Daily Top Bets",
    },
    "guybostonsports": {
        "url": "https://www.youtube.com/@GuyBostonSports",
        "match": lambda title: (
            "predictions, & player props" in title.lower()
        ),
        "label": "Guy Boston Sports - MLB",
    },
    "silverbackbets": {
        "url": "https://www.youtube.com/@silverbackbets",
        "match": lambda title: (
            "mlb picks and predictions" in title.lower()
            and "best mlb bets today" in title.lower()
        ),
        "label": "Silverback Bets - MLB",
    },
    "docssports_craigtrapp": {
        "url": "https://www.youtube.com/@Docs_Sports_Picks",
        "match": lambda title: "craig trapp" in title.lower(),
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
    """
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
    transcript = ytt_api.fetch(video_id)
    lines = [snippet.text for snippet in transcript]
    return " ".join(lines)


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
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
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
  "bet_type": "ml" | "spread" | "total" | "prop" | "combo",
  "confidence": "LEAN" | "LIKE" | "LOCK" | null,
  "rationale": "one-sentence paraphrase of the source's SPECIFIC reasoning — must cite stats, named players, matchups, or concrete trends. Leave null if the source only gave generic phrases like 'they like this', 'going with this one', 'already bet', 'value pick', or no reasoning at all. Be strict: when in doubt, leave null. Do NOT invent rationale."
}

Rules:
- Set sport="other" for anything that's not MLB or NBA (NFL, NHL, WNBA, college basketball, golf, soccer, UFC, tennis, etc.). WNBA specifically is NOT NBA — tag it "other" even though both are basketball.
- For "Aaron Judge home run" or "Castle to score a TD"-type anytime bets, use line=0.5, side="over", stat="hr" (or relevant stat).
- For combo props like "PRA" (pts+reb+ast) or "P+A", use bet_type="combo" and join components with "+".
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
    text = message.content[0].text.strip()
    # Tolerate fenced code blocks
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


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
             r["matchup"], r["bet_type"])
            for r in conn.execute(
                "SELECT player_name, stat, side, line, matchup, bet_type "
                "FROM bets WHERE date=? AND source_label=?",
                (date_str, source_label),
            ).fetchall()
        }

    rows = []
    seen = set(existing)
    for b in bets_data:
        sport = b.get("sport")
        if sport not in ("mlb", "nba"):
            continue  # drop WNBA / NHL / golf / etc. — we don't grade them
        bt = b.get("bet_type") or "prop"
        key = (
            b.get("player_name"), b.get("stat"), b.get("side"),
            b.get("line"), b.get("matchup"), bt,
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append((
            date_str, source_label, video_id,
            json.dumps(b, ensure_ascii=False),
            sport, b.get("matchup"), b.get("player_name"),
            b.get("stat"), b.get("line"), b.get("side"),
            bt, b.get("confidence"), b.get("rationale"),
        ))

    if not rows:
        return 0
    with db.connect() as conn:
        conn.executemany(
            """INSERT INTO bets
            (date, source_label, source_video_id, raw_text,
             sport, matchup, player_name, stat, line, side,
             bet_type, confidence, rationale)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
- Never create a header from a single team name (e.g. "Chicago Cubs", "Tampa Bay"). A single-team bet like "Cubs moneyline" goes under the actual matchup that includes the Cubs.
- Group all bets by matchup, not by source.
- A "bet" includes spreads, totals, moneylines, and player props.
- If multiple sources called the same bet, combine them on one line with all sources listed; give each source its own rationale sub-bullet.
- Preserve confidence tiers from Lindy (LEAN/LIKE/LOCK) as bracketed tags after the source name.
- Rationale sub-bullets should be ONE concise sentence each, paraphrased from the source's reasoning (key stats, matchups, trends, etc.). Skip the rationale sub-bullet entirely for a source that gave no reasoning — do NOT invent one.
- Only include picks and reasoning that were EXPLICITLY stated in the source summaries. Do NOT infer.
- If a source covered a game but didn't name a specific bet, skip it for that game.
- Order games by how many sources covered them (most covered first).
{matchups_block}
SOURCES:
{source_blocks}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ── main ────────────────────────────────────────────────────────────────
def _all_sent_video_ids(sent: dict) -> set[str]:
    """Collect every video ID we've already sent, across all dates."""
    ids: set[str] = set()
    for day_entries in sent.values():
        ids.update(day_entries.values())
    return ids


def run() -> None:
    db.init()
    today = date.today()
    today_key = today.isoformat()
    today_filename = today.strftime("%Y_%m_%d")
    matchups = todays_matchups(today_key)
    if matchups:
        print(f"Loaded {len(matchups)} matchup(s) for {today_key}.")

    sent = load_sent()
    already_sent_ids = _all_sent_video_ids(sent)
    today_sent = sent.get(today_key, {})

    bets_json_path = BETS_DIR / f"{today_filename}.json"
    bets_md_path = BETS_DIR / f"{today_filename}.md"
    existing_summaries: list[dict] = (
        json.loads(bets_json_path.read_text())
        if bets_json_path.exists() else []
    )

    new_summaries: list[dict] = []

    for channel_key, cfg in CHANNELS.items():
        print(f"[{cfg['label']}] Searching for today's video...")
        video = find_video(channel_key)

        if not video:
            print("  No video found yet.")
            continue

        if video["video_id"] in already_sent_ids:
            print(f"  Already processed: {video['title']}")
            continue

        print(f"  Found: {video['title']}")
        print("  Pulling transcript...")

        try:
            transcript = get_transcript(video["video_id"])
        except Exception as e:
            print(f"  Could not get transcript: {e}")
            continue

        print("  Summarizing with Claude...")
        try:
            summary = summarize(
                video["title"],
                transcript,
                cfg["label"],
                cfg.get("prompt_extra", ""),
            )
        except Exception as e:
            print(f"  Summarization failed: {e}")
            continue

        new_summaries.append({
            "channel_key": channel_key,
            "label": cfg["label"],
            "title": video["title"],
            "video_id": video["video_id"],
            "summary": summary,
        })
        today_sent[channel_key] = video["video_id"]

        print("  Extracting structured bets...")
        try:
            structured = extract_structured_bets(summary, matchups)
            n = persist_bets(
                today_key, cfg["label"], video["video_id"], structured,
            )
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
    run()
