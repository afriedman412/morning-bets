"""Daily digest email: today's consensus card + yesterday's graded results.

Mirrors auto-matcha/matcha/emailer.py — STARTTLS on smtp.gmail.com, login
with EMAIL_FROM + GOOGLE_APP_PW (the steadynappin app password).

    venv/bin/python -m src.emailer              # today
    venv/bin/python -m src.emailer 2026-08-04   # a specific date
    venv/bin/python -m src.emailer --dry        # render to stdout, send nothing
"""
from __future__ import annotations

import os
import re
import smtplib
import sys
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from html import escape, unescape
from pathlib import Path

from dotenv import load_dotenv

from src import db
from src.panel import PERSONAS, bankroll_status, settle_bet
from src.recommend import (
    RECOMMENDER_LABEL, TIER_BY_RANK, UNIT_CENTS, _bet_description,
)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
EMAIL_FROM = os.environ.get("EMAIL_FROM", "steadynappin@gmail.com")
EMAIL_TO = os.environ.get("EMAIL_TO", "")

TIER_COLOR = {"LOCK": "#1a7f37", "LIKE": "#0969da", "LEAN": "#9a6700"}
RESULT_COLOR = {"W": "#1a7f37", "L": "#cf222e", "PUSH": "#6e7781"}


def _e(s) -> str:
    return escape(str(s or ""))


def _to_text(html_body: str) -> str:
    """Plain-text alternative. Entities must be unescaped after tag removal,
    or the text part shows literal '&nbsp;' and '&amp;' to anyone whose
    client prefers text/plain."""
    t = re.sub(r"<li[^>]*>", "\n  - ", html_body)
    t = re.sub(r"<(br|/p|/h2|/h3|/div|/tr)[^>]*>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n[ \t]+", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _money(cents: int | None) -> str:
    c = cents or 0
    return f"{'-' if c < 0 else ''}${abs(c) / 100:,.2f}"


def _units(cents: int | None) -> str:
    """Stake in units. 1 unit = UNIT_CENTS, matching the recommender."""
    return f"{(cents or 0) / UNIT_CENTS:.1f}u"


# ── data ───────────────────────────────────────────────────────────────
def _card(
    conn, date_str: str, label: str = RECOMMENDER_LABEL,
) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT matchup, player_name, stat, line, side, bet_type, period, "
        "confidence, rationale, stake_cents, american_odds, result, "
        "actual_value FROM bets WHERE date=? AND source_label=? ORDER BY id",
        (date_str, label),
    ).fetchall()]


def _slate_stats(conn, date_str: str) -> dict:
    g = conn.execute(
        "SELECT COUNT(*) FROM games WHERE sport='mlb' AND date=?",
        (date_str,),
    ).fetchone()[0]
    r = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT source_label) FROM bets "
        "WHERE date=? AND source_label NOT LIKE 'Panel:%' "
        "AND source_label NOT LIKE 'Consensus%' AND source_label!=?",
        (date_str, RECOMMENDER_LABEL),
    ).fetchone()
    return {"games": g, "capper_bets": r[0], "sources": r[1]}


# ── rendering ──────────────────────────────────────────────────────────
# Stakes are no longer fixed per band — rank sets a base unit size and the
# live book price scales it, so the note describes the conviction tier only.
BANDS = [
    (1, 2, "Conviction", "full unit, price-adjusted"),
    (3, 4, "Lean", "half unit, price-adjusted"),
    (5, 5, "Straggler", "quarter unit, price-adjusted"),
]


def _band_header(title: str, note: str) -> str:
    return f"""
    <tr><td colspan="3" style="padding:16px 8px 4px;font-size:11px;
        letter-spacing:.08em;text-transform:uppercase;color:#888;
        border-bottom:1px solid #eee">
      {_e(title)} <span style="text-transform:none;letter-spacing:0;
        color:#aaa">· {_e(note)}</span></td></tr>"""


_PERSONA_RE = re.compile(r"^([A-Z][A-Za-z]+)\s*\((\d+(?:\.\d+)?)\):\s*(.*)$")


def _rationale_html(rationale: str | None) -> str:
    """One line per persona, untruncated.

    `rationale` is stored as ' | '.join of each persona's scored reason. It
    used to be dumped as a single blob clipped at 420 chars, which cut the
    second persona off mid-sentence — each take runs 250-330 chars, so three
    of them never fit.
    """
    if not rationale:
        return ""
    rows = []
    for part in rationale.split(" | "):
        part = part.strip()
        if not part:
            continue
        m = _PERSONA_RE.match(part)
        if m:
            who, score, text = m.group(1), m.group(2), m.group(3)
            rows.append(
                f'<div style="margin-top:5px">'
                f'<span style="color:#24292f;font-weight:600">{_e(who)}</span>'
                f'<span style="color:#999">&nbsp;{_e(score)}/10</span>'
                f'<span style="color:#555">&nbsp;— {_e(text)}</span></div>'
            )
        else:
            rows.append(f'<div style="margin-top:5px;color:#555">'
                        f'{_e(part)}</div>')
    return (
        '<div style="font-size:12px;line-height:1.5;margin-top:8px">'
        + "".join(rows) + "</div>"
    )


def _pick_row(i: int, p: dict) -> str:
    tier = (p.get("confidence") or TIER_BY_RANK.get(i, "LEAN")).upper()
    color = TIER_COLOR.get(tier, "#333")
    odds = p.get("american_odds")
    odds_s = f"{odds:+d}" if odds else "—"
    res = p.get("result")
    res_html = ""
    if res in ("W", "L", "PUSH"):
        av = p.get("actual_value")
        av_s = f" ({av:g})" if av is not None else ""
        res_html = (
            f'<span style="color:{RESULT_COLOR[res]};font-weight:700">'
            f'{res}{_e(av_s)}</span>'
        )
    return f"""
    <tr>
      <td style="padding:10px 8px;border-bottom:1px solid #eee;
                 vertical-align:top;width:28px;color:#888">{i}</td>
      <td style="padding:10px 8px;border-bottom:1px solid #eee;
                 vertical-align:top">
        <div style="font-weight:700;font-size:15px">
          {_e(_bet_description(p))}
          <span style="color:#888;font-weight:400">&nbsp;{_e(odds_s)}</span>
        </div>
        <div style="color:#666;font-size:13px;margin-top:2px">
          {_e(p.get('matchup'))}
        </div>
        {_rationale_html(p.get('rationale'))}
      </td>
      <td style="padding:10px 8px;border-bottom:1px solid #eee;
                 vertical-align:top;text-align:right;white-space:nowrap">
        <span style="background:{color};color:#fff;border-radius:3px;
                     padding:2px 6px;font-size:11px;font-weight:700">
          {_e(tier)}</span><br>
        <span style="font-size:14px;color:#333;font-weight:600">
          {_e(_units(p.get('stake_cents')))}</span><br>
        <span style="font-size:12px;color:#666">
          {_e(_money(p.get('stake_cents')))}</span><br>
        {res_html}
      </td>
    </tr>"""


def _results_block(rows: list[dict]) -> str:
    if not rows:
        return '<p style="color:#888">No card was generated.</p>'
    graded = [r for r in rows if r["result"] in ("W", "L", "PUSH")]
    if not graded:
        return '<p style="color:#888">Not graded yet.</p>'
    w = sum(1 for r in graded if r["result"] == "W")
    ls = sum(1 for r in graded if r["result"] == "L")
    p = sum(1 for r in graded if r["result"] == "PUSH")
    pnl = sum(
        settle_bet(r["result"], r["stake_cents"], r["american_odds"])
        for r in graded
    )
    color = "#1a7f37" if pnl > 0 else ("#cf222e" if pnl < 0 else "#6e7781")
    lines = "".join(
        f'<li style="margin:3px 0"><span style="color:'
        f'{RESULT_COLOR[r["result"]]};font-weight:700">{r["result"]}</span>'
        f' &nbsp;{_e(_bet_description(r))} '
        f'<span style="color:#888">({_e(r.get("matchup"))})</span></li>'
        for r in graded
    )
    return (
        f'<p style="font-size:16px;margin:4px 0 10px">'
        f'<b>{w}-{ls}-{p}</b> &nbsp;·&nbsp; '
        f'<span style="color:{color};font-weight:700">{_money(pnl)}</span>'
        f'</p><ul style="margin:0;padding-left:18px;font-size:13px">'
        f'{lines}</ul>'
    )


def build_digest(
    date_str: str, label: str = RECOMMENDER_LABEL,
) -> tuple[str, str]:
    """Return (subject, html) for the given date.

    `label` exists so a backtest label can be previewed without touching the
    production one.
    """
    d = date.fromisoformat(date_str)
    prev = (d - timedelta(days=1)).isoformat()
    pretty = d.strftime("%A %-m/%-d/%y")

    with db.connect() as conn:
        card = _card(conn, date_str, label)
        yesterday = _card(conn, prev, label)
        slate = _slate_stats(conn, date_str)
    bank = bankroll_status(label)

    if card:
        # Group into the 2 / 2 / 1 stake bands so the card's structure is
        # explicit rather than implied by row order.
        parts = []
        for lo, hi, title, note in BANDS:
            in_band = [
                (i, p) for i, p in enumerate(card, 1) if lo <= i <= hi
            ]
            if not in_band:
                continue
            parts.append(_band_header(title, note))
            parts += [_pick_row(i, p) for i, p in in_band]
        # Any pick beyond the defined bands still renders.
        extra = [(i, p) for i, p in enumerate(card, 1) if i > BANDS[-1][1]]
        if extra:
            parts.append(_band_header("Additional", ""))
            parts += [_pick_row(i, p) for i, p in extra]
        picks = "".join(parts)
        total = sum(p.get("stake_cents") or 0 for p in card)
        card_html = (
            f'<table style="width:100%;border-collapse:collapse">{picks}'
            f'</table><p style="color:#666;font-size:13px;margin-top:8px">'
            f'Total exposure: <b>{_money(total)}</b></p>'
        )
        subject = f"Morning Bets — {pretty} — {len(card)} picks"
    else:
        card_html = (
            '<p style="color:#888">No consensus card for today yet. '
            'Run <code>make panel</code> to generate one.</p>'
        )
        subject = f"Morning Bets — {pretty} — no card"

    roi = (
        bank["current_cents"] - bank["starting_cents"]
    ) / max(1, bank["starting_cents"]) * 100
    bcolor = "#1a7f37" if roi >= 0 else "#cf222e"

    html = f"""<div style="font-family:-apple-system,BlinkMacSystemFont,
'Segoe UI',Helvetica,Arial,sans-serif;max-width:680px;margin:0 auto;
color:#24292f">
  <h2 style="margin:0 0 2px">Morning Bets</h2>
  <div style="color:#666;font-size:14px;margin-bottom:18px">{_e(pretty)}
    &nbsp;·&nbsp; {slate['games']} games &nbsp;·&nbsp;
    {slate['capper_bets']} capper bets from {slate['sources']} sources</div>

  <h3 style="border-bottom:2px solid #24292f;padding-bottom:4px">
    Today's card</h3>
  {card_html}

  <h3 style="border-bottom:2px solid #24292f;padding-bottom:4px;
             margin-top:26px">Yesterday ({_e(prev)})</h3>
  {_results_block(yesterday)}

  <h3 style="border-bottom:2px solid #24292f;padding-bottom:4px;
             margin-top:26px">Bankroll</h3>
  <p style="font-size:15px;margin:4px 0">
    <b>{_money(bank['current_cents'])}</b>
    <span style="color:{bcolor}">({roi:+.1f}%)</span>
    <span style="color:#888;font-size:13px">
      &nbsp;from {_money(bank['starting_cents'])} ·
      {bank['counts'].get('W', 0)}-{bank['counts'].get('L', 0)}-
      {bank['counts'].get('PUSH', 0)} all-time</span></p>

  <p style="color:#999;font-size:11px;margin-top:28px;border-top:1px solid
     #eee;padding-top:10px">Generated by morning-bets. Picks are the
     consensus of {len(PERSONAS)} personas after a bounded debate; stakes
     follow card rank.</p>
</div>"""
    return subject, html


# ── send ───────────────────────────────────────────────────────────────
def send_email(to_addresses, subject, body_html, body_text=None) -> bool:
    if not to_addresses:
        print("No recipients specified")
        return False
    pw = os.environ.get("GOOGLE_APP_PW")
    if not pw:
        print("GOOGLE_APP_PW not set — cannot send.")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("Morning Bets", EMAIL_FROM))
    msg["To"] = ", ".join(to_addresses)
    # Without Date and Message-ID, Gmail accepts the message at SMTP and then
    # files it as spam — their absence is a standard bulk-mail heuristic and
    # email.mime does not add them for you.
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=EMAIL_FROM.split("@")[-1])
    msg["Reply-To"] = EMAIL_FROM
    msg["Auto-Submitted"] = "auto-generated"
    if body_text is None:
        body_text = _to_text(body_html)
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_FROM, pw)
            server.sendmail(EMAIL_FROM, to_addresses, msg.as_string())
        print(f"Digest sent to {', '.join(to_addresses)}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"Failed to send email: {e}")
        return False


def already_sent(date_str: str) -> bool:
    db.init()
    with db.connect() as conn:
        return conn.execute(
            "SELECT 1 FROM digests WHERE date=?", (date_str,),
        ).fetchone() is not None


def _mark_sent(date_str: str, to: list[str]) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO digests (date, sent_at, recipients) "
            "VALUES (?,?,?)",
            (date_str,
             datetime.now(timezone.utc).isoformat(timespec="seconds"),
             ", ".join(to)),
        )


def run(date_str: str | None = None, dry: bool = False,
        if_needed: bool = False) -> bool:
    d = date_str or date.today().isoformat()
    datetime.strptime(d, "%Y-%m-%d")  # validate
    # A manual `make morning` and the scheduled run would otherwise both
    # mail the same card. Whichever gets there first wins; the other no-ops.
    if if_needed and not dry and already_sent(d):
        print(f"Digest for {d} already sent — skipping.")
        return True
    subject, html = build_digest(d)
    if dry:
        print(f"SUBJECT: {subject}\n")
        print(html)
        return True
    to = [a.strip() for a in EMAIL_TO.split(",") if a.strip()]
    ok = send_email(to, subject, html)
    if ok:
        _mark_sent(d, to)
    return ok


if __name__ == "__main__":
    args = sys.argv[1:]
    dry = "--dry" in args
    if_needed = "--if-needed" in args
    positional = [a for a in args if not a.startswith("--")]
    ok = run(positional[0] if positional else None, dry=dry,
             if_needed=if_needed)
    sys.exit(0 if ok else 1)
