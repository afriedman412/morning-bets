"""Import bet-slip screenshots mailed to a tagged address.

Flow: screenshot a slip on your phone, share it to email, send it to
EMAIL_FROM's +bets alias. This module polls IMAP for unread mail delivered
to that alias, reads any image attachments with Claude vision, and records
what it finds as a tailed bet.

The interesting part is the match step. A slip is either something a capper
or the panel already suggested — in which case we want the existing `bets`
row so the pick keeps its provenance and rationale — or it is a bet you
made on your own, which needs a new row under `Placed`. Either way the
result is a `my_bets` tail carrying the real stake and the real price off
the slip, so `mybets.my_bets_status()` reports actual P/L rather than the
flat -110 the rest of the system assumes.

Grading needs no changes: `grade_pending()` walks the `bets` table, and
both branches above put a row there.

    venv/bin/python -m src.inbox                    # poll and import
    venv/bin/python -m src.inbox --dry              # parse only, write nothing
    venv/bin/python -m src.inbox slip.png           # a local file (testing)
    venv/bin/python -m src.inbox --date=2026-08-07  # force the slate date
"""
from __future__ import annotations

import base64
import email
import hashlib
import imaplib
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from email.message import Message
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from src import db
from src.grading import resolve_canonical_matchup, same_party
from src.main import EXTRACT_PROMPT, _normalize_matchup
from src.mybets import tail_bet
from src.recommend import RECOMMENDER_LABEL

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
IMAP_HOST = os.environ.get("IMAP_HOST", "imap.gmail.com")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "steadynappin@gmail.com")

# Gmail delivers user+tag@gmail.com to user@gmail.com, so the tagged alias
# needs no separate account or credential — just a filter on the headers.
_local, _, _domain = EMAIL_FROM.partition("@")
INBOX_ADDRESS = os.environ.get(
    "INBOX_ADDRESS", f"{_local}+bets@{_domain}",
).lower()

PLACED_LABEL = "Placed"
DEFAULT_ODDS = -110

# Claude vision reads these; iOS screenshots are PNG, but photos shared out
# of the Photos app can arrive as HEIC, which the API will not accept.
SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# Reuse the canonical stat keys and bet-type rules from the video extractor
# rather than restating them — one place to change a stat key.
_marker = "Schema for each pick:"
if _marker not in EXTRACT_PROMPT:  # pragma: no cover - guards a refactor
    raise RuntimeError(
        f"EXTRACT_PROMPT no longer contains {_marker!r}; "
        "src/inbox.py needs updating"
    )
_SCHEMA_BLOCK = _marker + EXTRACT_PROMPT.split(_marker, 1)[1]

SLIP_PROMPT = """You are reading a screenshot from a sportsbook app \
(DraftKings, FanDuel, BetMGM, Caesars, Fanatics, ESPN Bet, etc.). It is \
either a single bet slip, or — more often — a "My Bets" / "Upcoming" / \
"Settled" list showing SEVERAL independent wagers stacked vertically.

Extract EVERY wager visible. Output ONLY a JSON object, no prose:

{
  "book": sportsbook name if visible, else null,
  "event_date": "YYYY-MM-DD" if an actual date is printed, else null,
  "bets": [ ...one object per bet, using the schema below... ]
}

Screenshot-specific rules, which override the schema notes where they
conflict:
- Each row of a My Bets list is its own separate wager with its own stake \
and its own price. A list of separate bets is NOT a parlay.
- Add one extra field per bet, `parlay_group`: null for a straight single \
bet, or a shared integer (0, 1, 2...) for legs that belong to the SAME \
parlay/SGP — that is, legs grouped under ONE combined price and ONE stake. \
Only use a non-null value when the legs genuinely share a single wager.
- Fill BOTH `american_odds` and `stake_cents` from what is printed. \
"$20.00" -> 2000. The dollar figure on a My Bets row is the amount \
WAGERED. Do not use a "To Win" or "Total Payout" figure as the stake.
- Record the price as printed. If a row shows a "profit boost" badge, \
ignore the badge — do not adjust the odds.
- Teams are usually abbreviations in AWAY - HOME order, e.g. \
"MIN - KC · 7:40 PM". Emit `matchup` as "MIN @ KC", keeping the \
abbreviations and preserving away-then-home order.
- A row like "KC · Moneyline" is bet_type "ml", side "KC", line null.
- A row like "BOS -1.5 · Run Line" is bet_type "spread", side "BOS", \
line -1.5.
- A row like "Over 7.5 · Total" with no player named is bet_type "total", \
side "over", line 7.5, player_name null.
- A row like "Over 7.5 · Dylan Cease Strikeouts" is bet_type "prop", \
player_name "Dylan Cease", stat "k", side "over", line 7.5.
- Times without a date (e.g. "7:40 PM") do NOT establish event_date. \
Leave event_date null unless a real calendar date is printed.
- `confidence` and `rationale` are never on a screenshot. Always null.
- If the image is not a betting screen at all, return {"bets": []}.

""" + _SCHEMA_BLOCK


# ── vision ──────────────────────────────────────────────────────────────
def parse_slip(image_bytes: bytes, media_type: str) -> dict:
    """Read one betting screenshot into {book, event_date, bets}."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(image_bytes).decode(),
                    },
                },
                {"type": "text", "text": SLIP_PROMPT},
            ],
        }],
    )
    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    parsed = json.loads(text)
    parsed.setdefault("bets", [])
    parsed.setdefault("event_date", None)
    parsed.setdefault("book", None)
    # A single-slip screenshot may come back with the older top-level
    # `parlay` flag instead of per-bet groups; fold it into the same shape.
    if parsed.pop("parlay", False):
        for b in parsed["bets"]:
            b.setdefault("parlay_group", 0)
    for b in parsed["bets"]:
        b.setdefault("parlay_group", None)
    return parsed


# ── persistence ─────────────────────────────────────────────────────────
TEAM_BET_TYPES = ("ml", "spread", "total", "team_total")


def _find_existing_bet(conn, date_str: str, b: dict, matchup: str | None):
    """An already-known bet matching this slip leg, if any.

    Matching against capper/panel rows keeps the pick's provenance and
    rationale instead of creating a bare duplicate under 'Placed'. The
    structural fields are filtered in SQL; team and player references are
    compared in Python so abbreviations resolve.
    """
    bet_type = b.get("bet_type") or "prop"
    rows = conn.execute(
        "SELECT id, source_label, player_name, side FROM bets WHERE date=? "
        "AND IFNULL(stat,'') = IFNULL(?,'') "
        "AND IFNULL(line,-9999) = IFNULL(?,-9999) "
        "AND IFNULL(LOWER(matchup),'') = IFNULL(LOWER(?),'') "
        "AND bet_type=? AND IFNULL(period,'full')=? "
        # Prefer a real source over a row a previous slip import created,
        # and prefer the consensus card over an individual capper so the
        # day view shows plainly when a bet was tailed off the card.
        "ORDER BY (source_label = ?) ASC, (source_label = ?) DESC, id ASC",
        (
            date_str, b.get("stat"), b.get("line"), matchup, bet_type,
            b.get("period") or "full", PLACED_LABEL, RECOMMENDER_LABEL,
        ),
    ).fetchall()

    for r in rows:
        if not same_party(b.get("side"), r["side"]):
            continue
        # Team bets often carry the club in player_name on one side and
        # leave it null on the other; only insist on a player match when
        # both rows actually name someone.
        if bet_type not in TEAM_BET_TYPES:
            if not same_party(b.get("player_name"), r["player_name"]):
                continue
        elif b.get("player_name") and r["player_name"]:
            if not same_party(b.get("player_name"), r["player_name"]):
                continue
        return r
    return None


def _insert_placed_bet(conn, date_str: str, b: dict, matchup: str | None,
                       slip_sha: str) -> int:
    cur = conn.execute(
        """INSERT INTO bets
        (date, source_label, source_video_id, raw_text,
         sport, matchup, player_name, stat, line, side,
         bet_type, period, confidence, rationale,
         stake_cents, american_odds)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            date_str, PLACED_LABEL, f"slip:{slip_sha[:12]}",
            json.dumps(b, ensure_ascii=False),
            b.get("sport"), matchup, b.get("player_name"), b.get("stat"),
            b.get("line"), b.get("side"), b.get("bet_type") or "prop",
            b.get("period") or "full", None, None,
            b.get("stake_cents"), b.get("american_odds"),
        ),
    )
    return cur.lastrowid


def _resolve_date_and_matchup(
    conn, b: dict, sport: str, preferred: str | None,
) -> tuple[str, str | None]:
    """Pick the date this bet's game is actually on, and canonicalize it.

    A My Bets screen prints kickoff times but usually not dates, so the day
    has to be inferred: try each candidate day and keep the first where the
    matchup names a game actually on that slate.

    Resolution is confirmed against the games table rather than by checking
    whether the string changed — a slip that already spells out full club
    names resolves to itself, which would otherwise read as a miss.
    """
    raw = _normalize_matchup(b.get("matchup"))
    today = date.today()
    candidates = []
    for d in (preferred, b.get("event_date")):
        if d and d not in candidates:
            candidates.append(d)
    for delta in (0, 1, -1, 2):
        d = (today + timedelta(days=delta)).isoformat()
        if d not in candidates:
            candidates.append(d)

    for d in candidates:
        resolved = resolve_canonical_matchup(conn, raw, sport, d)
        if not resolved:
            continue
        on_slate = conn.execute(
            "SELECT 1 FROM games WHERE sport=? AND date=? "
            "AND (away_team || ' @ ' || home_team) = ?",
            (sport, d, resolved),
        ).fetchone()
        if on_slate:
            return d, resolved
    return candidates[0], raw


def import_slip(parsed: dict, slip_sha: str, dry: bool = False,
                date_override: str | None = None) -> list[dict]:
    """Tail every bet on a parsed screenshot. One summary dict per bet."""
    out = []
    pending_tails: list[tuple[int, int, int]] = []
    used_bet_ids: set[int] = set()
    preferred = date_override or parsed.get("event_date")

    with db.connect() as conn:
        for b in parsed.get("bets", []):
            if b.get("parlay_group") is not None:
                # One combined price over N legs does not fit one-row-per-bet,
                # and grading it means grading every leg and AND-ing them.
                out.append({"skipped": "parlay leg", "bet": b})
                continue

            sport = b.get("sport")
            if sport not in ("mlb", "nba"):
                # The grader only knows MLB and NBA; anything else would sit
                # PENDING forever and drag the un-graded count with it.
                out.append({
                    "skipped": f"unsupported sport: {sport}", "bet": b,
                })
                continue

            date_str, matchup = _resolve_date_and_matchup(
                conn, b, sport, preferred,
            )

            existing = _find_existing_bet(conn, date_str, b, matchup)
            # my_bets.bet_id is UNIQUE — one tail per row. A slip can hold
            # the same wager twice though (a promo variant, or the same bet
            # taken again at a different price), and pointing both at one
            # row makes the second tail overwrite the first, silently losing
            # a real stake. The repeat gets its own row instead.
            if existing is not None and existing["id"] in used_bet_ids:
                existing = None
                repeat = True
            else:
                repeat = False

            if existing is not None:
                bet_id = existing["id"]
                origin = f"matched {existing['source_label']}"
                used_bet_ids.add(bet_id)
            elif dry:
                bet_id = None
                origin = ("second copy — own row" if repeat
                          else f"would insert as {PLACED_LABEL}")
            else:
                bet_id = _insert_placed_bet(
                    conn, date_str, b, matchup, slip_sha,
                )
                used_bet_ids.add(bet_id)
                origin = ("second copy — own %s row" % PLACED_LABEL if repeat
                          else f"new {PLACED_LABEL} row")

            stake = b.get("stake_cents")
            odds = b.get("american_odds")
            tailed = False
            if stake is None:
                origin += " (no stake on slip — not tailed)"
            elif not dry and bet_id is not None:
                # Deferred: tail_bet opens its own connection, and SQLite
                # will not grant a second writer while this transaction is
                # still open ("database is locked").
                pending_tails.append(
                    (bet_id, stake, odds if odds is not None
                     else DEFAULT_ODDS)
                )
                tailed = True

            out.append({
                "bet_id": bet_id, "date": date_str, "origin": origin,
                "tailed": tailed, "bet": b, "matchup": matchup,
            })

    for bet_id, stake, odds in pending_tails:
        tail_bet(bet_id, stake, odds)
    return out


def _record_slip(sha: str, message_id: str | None, filename: str | None,
                 n_bets: int, note: str | None) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO bet_slips "
            "(sha256, received_at, message_id, filename, n_bets, note) "
            "VALUES (?,?,?,?,?,?)",
            (sha, datetime.now(timezone.utc).isoformat(timespec="seconds"),
             message_id, filename, n_bets, note),
        )


def _already_imported(sha: str) -> bool:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM bet_slips WHERE sha256=?", (sha,),
        ).fetchone()
    return row is not None


# ── one image, end to end ───────────────────────────────────────────────
def handle_image(data: bytes, media_type: str, filename: str | None,
                 message_id: str | None, dry: bool = False,
                 date_override: str | None = None) -> int:
    """Parse and import one image. Returns the number of bets tailed."""
    sha = hashlib.sha256(data).hexdigest()
    label = filename or sha[:12]

    if not dry and _already_imported(sha):
        print(f"  {label}: already imported — skipping")
        return 0
    if media_type not in SUPPORTED_IMAGE_TYPES:
        print(f"  {label}: unsupported image type {media_type} — skipping")
        if not dry:
            _record_slip(sha, message_id, filename, 0,
                         f"unsupported type {media_type}")
        return 0
    if len(data) > MAX_IMAGE_BYTES:
        print(f"  {label}: {len(data) // 1024}KB exceeds the API image "
              "limit — skipping")
        if not dry:
            _record_slip(sha, message_id, filename, 0, "too large")
        return 0

    parsed = parse_slip(data, media_type)
    book = parsed.get("book") or "unknown book"
    legs = parsed.get("bets", [])
    if not legs:
        print(f"  {label}: no bets found in image")
        if not dry:
            _record_slip(sha, message_id, filename, 0, "no bets found")
        return 0

    print(f"  {label}: {len(legs)} bet(s) from {book}")
    results = import_slip(parsed, sha, dry=dry, date_override=date_override)
    tailed = sum(1 for r in results if r.get("tailed"))
    for r in results:
        if "skipped" in r:
            print(f"      skip ({r['skipped']}): {_describe(r['bet'])}")
        else:
            print(f"      {_describe(r['bet'])}")
            print(f"          {r['date']}  {r['matchup']}  [{r['origin']}]")
    if not dry:
        _record_slip(sha, message_id, filename, tailed, book)
    return tailed


def _describe(b: dict) -> str:
    who = b.get("player_name") or b.get("matchup") or "?"
    stat = b.get("stat") or b.get("bet_type") or ""
    side = b.get("side") or ""
    line = b.get("line")
    line_s = "" if line is None else f" {line}"
    stake = b.get("stake_cents")
    odds = b.get("american_odds")
    money = ""
    if stake is not None:
        money = f" — ${stake / 100:.2f}"
        if odds is not None:
            money += f" @ {odds:+d}"
    return f"{who} {side} {stat}{line_s}{money}".strip()


# ── imap ────────────────────────────────────────────────────────────────
def _iter_images(msg: Message):
    for part in msg.walk():
        if part.get_content_maintype() != "image":
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        yield payload, part.get_content_type(), part.get_filename()


def poll(dry: bool = False, date_override: str | None = None) -> int:
    """Check the tagged alias for unread slips. Returns bets tailed."""
    pw = os.environ.get("GOOGLE_APP_PW")
    if not pw:
        print("GOOGLE_APP_PW not set — cannot read mail.")
        return 0

    print(f"Checking {IMAP_HOST} for unread mail to {INBOX_ADDRESS}...")
    total = 0
    M = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        M.login(EMAIL_FROM, pw)
        M.select("INBOX")
        typ, data = M.search(None, "UNSEEN")
        ids = data[0].split() if data and data[0] else []

        matched = []
        for i in ids:
            # Header-only peek keeps the message unread until it imports
            # cleanly, so a transient API failure retries tomorrow instead
            # of silently dropping the slip.
            typ, hd = M.fetch(
                i,
                "(BODY.PEEK[HEADER.FIELDS "
                "(TO CC DELIVERED-TO X-ORIGINAL-TO MESSAGE-ID)])",
            )
            raw = b"".join(p[1] for p in hd if isinstance(p, tuple))
            if INBOX_ADDRESS in raw.decode("utf-8", "replace").lower():
                matched.append(i)

        if not matched:
            print("  nothing new.")
            return 0
        print(f"  {len(matched)} message(s) to process")

        for i in matched:
            typ, raw = M.fetch(i, "(BODY.PEEK[])")
            body = b"".join(p[1] for p in raw if isinstance(p, tuple))
            msg = email.message_from_bytes(body)
            mid = msg.get("Message-ID")
            images = list(_iter_images(msg))
            if not images:
                print(f"  {mid}: no image attachments")
                continue
            ok = True
            for payload, ctype, fname in images:
                try:
                    total += handle_image(
                        payload, ctype, fname, mid, dry=dry,
                        date_override=date_override,
                    )
                except Exception as e:
                    ok = False
                    print(f"  {fname or mid}: failed — {e}")
            if ok and not dry:
                M.store(i, "+FLAGS", "\\Seen")
    finally:
        try:
            M.logout()
        except Exception:
            pass

    print(f"Tailed {total} bet(s).")
    return total


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    override = None
    args = []
    rest = [a for a in sys.argv[1:] if a != "--dry"]
    for a in rest:
        if a.startswith("--date="):
            override = a.split("=", 1)[1]
        else:
            args.append(a)

    db.init()
    if args:
        # Local-file mode, for testing the parser without sending mail.
        for path_s in args:
            p = Path(path_s)
            ctype = {
                ".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".gif": "image/gif",
                ".webp": "image/webp",
            }.get(p.suffix.lower(), "application/octet-stream")
            print(f"{p}:")
            handle_image(p.read_bytes(), ctype, p.name, None, dry=dry,
                         date_override=override)
    else:
        poll(dry=dry, date_override=override)
