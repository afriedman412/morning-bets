"""Morning Bets: pull YouTube transcripts and email Claude summaries."""
from __future__ import annotations

import json
import os
import re
import smtplib
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import anthropic
import scrapetube
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── config ──────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_APP_PW = os.environ["GOOGLE_APP_PW"]
EMAIL_FROM = os.environ["EMAIL_FROM"]
EMAIL_TO = os.environ["EMAIL_TO"]

SENT_FILE = Path(__file__).resolve().parent.parent / "sent.json"

CHANNELS = {
    "oddsshopper": {
        "url": "https://www.youtube.com/@OddsShopper",
        "channel_id": None,  # resolved by scrapetube from URL
        "match": lambda title: all(
            kw.lower() in title.lower()
            for kw in ["lindy", "leans", "locks"]
        ),
        "label": "Lindy's Leans Likes & Locks",
        "only_video": False,  # channel posts many videos; match by title
    },
    "daftpreviews": {
        "url": "https://www.youtube.com/@daftpreviews",
        "channel_id": None,
        "match": lambda title: True,  # any video — just grab the latest
        "label": "Daft Previews",
        "only_video": True,  # expect exactly one video today
    },
}

GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587


# ── helpers ─────────────────────────────────────────────────────────────
def load_sent() -> dict:
    if SENT_FILE.exists():
        return json.loads(SENT_FILE.read_text())
    return {}


def save_sent(sent: dict) -> None:
    SENT_FILE.write_text(json.dumps(sent, indent=2))


def is_today(video: dict) -> bool:
    """Check if a video was published today (or within last 24h as fallback)."""
    # scrapetube returns publishedText like "1 hour ago", "3 hours ago", etc.
    text = video.get("publishedTimeText", {}).get("simpleText", "")
    if not text:
        return False
    text_lower = text.lower()
    # "X hours ago", "X minutes ago", "just now" → today
    if any(unit in text_lower for unit in ["minute", "hour", "just now", "second"]):
        return True
    # "1 day ago" is borderline — include it for early morning runs
    if "1 day ago" in text_lower:
        return True
    return False


def find_video(channel_key: str) -> dict | None:
    """Find today's target video for a channel."""
    cfg = CHANNELS[channel_key]
    # scrapetube.get_channel accepts channel_url
    videos = scrapetube.get_channel(channel_url=cfg["url"], limit=15)

    for video in videos:
        title = video.get("title", {}).get("runs", [{}])[0].get("text", "")
        if not title:
            # fallback: some scrapetube versions use accessibility label
            title = (
                video.get("title", {})
                .get("accessibility", {})
                .get("accessibilityData", {})
                .get("label", "")
            )
        video_id = video.get("videoId", "")

        if not is_today(video):
            if cfg["only_video"]:
                # For channels that post only one video/day, keep scanning
                continue
            else:
                continue

        if cfg["match"](title):
            return {"video_id": video_id, "title": title}

    return None


def get_transcript(video_id: str) -> str:
    """Pull the transcript text for a YouTube video."""
    ytt_api = YouTubeTranscriptApi()
    transcript = ytt_api.fetch(video_id)
    lines = [snippet.text for snippet in transcript]
    return " ".join(lines)


def summarize(title: str, transcript: str, label: str) -> str:
    """Use Claude to summarize a betting video transcript."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Below is the transcript of a daily sports betting video titled "{title}" from {label}.

Please provide a clear, concise summary that captures:
- All specific picks/bets mentioned (teams, spreads, totals, moneylines)
- The confidence level for each pick if mentioned (lean, like, lock, etc.)
- Any key reasoning or stats cited for the picks
- Which games/matchups are covered

Format the summary as a clean bulleted list grouped by game/matchup.

TRANSCRIPT:
{transcript}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def send_email(subject: str, body_html: str) -> bool:
    """Send an email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    # plain text fallback
    body_text = re.sub(r"<[^>]+>", "", body_html)
    body_text = re.sub(r"\s+", " ", body_text).strip()

    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_FROM, GOOGLE_APP_PW)
            server.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
        print(f"  ✓ Email sent to {EMAIL_TO}")
        return True
    except Exception as e:
        print(f"  ✗ Failed to send email: {e}")
        return False


def build_email(summaries: list[dict]) -> tuple[str, str]:
    """Build subject + HTML body from a list of summaries."""
    today = date.today().strftime("%A %-m/%-d")
    subject = f"Morning Bets – {today}"

    sections = ""
    for s in summaries:
        # Convert markdown-ish summary to HTML
        summary_html = s["summary"].replace("\n", "<br>")
        sections += f"""
        <div style="margin-bottom: 30px;">
            <h2 style="color: #1a1a2e; border-bottom: 2px solid #e94560; padding-bottom: 6px;">
                {s['label']}
            </h2>
            <p style="color: #666; font-size: 13px; margin: 4px 0 12px;">
                <a href="https://youtube.com/watch?v={s['video_id']}">{s['title']}</a>
            </p>
            <div style="font-size: 14px; line-height: 1.6;">
                {summary_html}
            </div>
        </div>
        """

    body_html = f"""
    <html>
    <body style="font-family: -apple-system, system-ui, Segoe UI, Roboto, sans-serif;
                 max-width: 700px; margin: 0 auto; padding: 20px;">
        <h1 style="color: #0f3460;">Morning Bets – {today}</h1>
        {sections}
        <p style="margin-top: 30px; color: #999; font-size: 11px;">
            Auto-generated from YouTube transcripts via Claude.
        </p>
    </body>
    </html>
    """
    return subject, body_html


# ── main ────────────────────────────────────────────────────────────────
def run() -> None:
    today_key = date.today().isoformat()
    sent = load_sent()
    today_sent = sent.get(today_key, {})

    summaries: list[dict] = []

    for channel_key, cfg in CHANNELS.items():
        if channel_key in today_sent:
            print(f"[{cfg['label']}] Already processed today, skipping.")
            continue

        print(f"[{cfg['label']}] Searching for today's video...")
        video = find_video(channel_key)

        if not video:
            print(f"  No video found yet.")
            continue

        print(f"  Found: {video['title']}")
        print(f"  Pulling transcript...")

        try:
            transcript = get_transcript(video["video_id"])
        except Exception as e:
            print(f"  ✗ Could not get transcript: {e}")
            continue

        print(f"  Summarizing with Claude...")
        try:
            summary = summarize(video["title"], transcript, cfg["label"])
        except Exception as e:
            print(f"  ✗ Summarization failed: {e}")
            continue

        summaries.append({
            "label": cfg["label"],
            "title": video["title"],
            "video_id": video["video_id"],
            "summary": summary,
        })
        today_sent[channel_key] = video["video_id"]

    if summaries:
        subject, body_html = build_email(summaries)
        if send_email(subject, body_html):
            # Only mark as sent if email succeeded
            sent[today_key] = today_sent
            # Clean up old entries (keep last 7 days)
            cutoff = (date.today() - timedelta(days=7)).isoformat()
            sent = {k: v for k, v in sent.items() if k >= cutoff}
            save_sent(sent)
    else:
        print("Nothing new to send.")


if __name__ == "__main__":
    run()
