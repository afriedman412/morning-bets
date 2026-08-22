"""Local ops console — what the pipeline is doing, separate from the dashboard.

The dashboard (src.web, port 5050) is about bets. This is about the machinery:
which videos have been found, which have been paid for, what failed, when each
scheduled agent last ran, and whether today is ready for `make morning`.

Read-only except for two buttons — retry a failed video, and drop one from the
queue — because the whole point is to see a stuck pipeline and unstick it
without going to the terminal.

    make ops        # http://127.0.0.1:5051
"""
from __future__ import annotations

import os
import re
import subprocess
import webbrowser
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, redirect, request, url_for

from src import db
from src.main import CHANNELS

app = Flask(__name__)
LOG = Path.home() / "Library/Logs/morning-bets/run.log"
REPO = Path(__file__).resolve().parent.parent

# The agents this console knows about, in the order they run.
AGENTS = ("grade", "discover", "process")


def _ago(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - t).total_seconds()
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


def agent_status() -> list[dict]:
    """Loaded launchd agents with their last exit code."""
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:
        out = ""
    rows = []
    for name in AGENTS:
        label = f"com.morningbets.{name}"
        m = re.search(rf"^(\S+)\s+(\S+)\s+{re.escape(label)}$", out, re.M)
        rows.append({
            "name": name,
            "loaded": bool(m),
            "running": bool(m and m.group(1) != "-"),
            "exit": (m.group(2) if m else None),
        })
    return rows


def last_runs(n: int = 12) -> list[dict]:
    """Recent run banners from the log, newest first."""
    if not LOG.exists():
        return []
    runs = []
    cur = None
    for line in LOG.read_text(errors="replace").splitlines():
        b = re.match(r"^===== (\S+ \S+) (\S+) =====$", line)
        if b:
            cur = {"when": b.group(1), "what": b.group(2),
                   "exit": None, "lines": 0, "errors": []}
            runs.append(cur)
            continue
        e = re.match(r"^----- (\S+ \S+) (\S+) exit=(\d+) -----$", line)
        if e and cur:
            cur["exit"] = int(e.group(3))
            cur = None
            continue
        if cur is not None:
            cur["lines"] += 1
            if re.search(r"!!|Traceback|Error|FAILED|failed", line):
                if len(cur["errors"]) < 3:
                    cur["errors"].append(line.strip()[:160])
    return list(reversed(runs))[:n]


def queue_rows(days: int = 3) -> list[dict]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with db.connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM video_queue WHERE slate_date >= ? "
            "ORDER BY slate_date DESC, found_at DESC", (cutoff,))]


def today_state() -> dict:
    d = date.today().isoformat()
    from src.emailer import already_sent
    from src.grading import pending_count
    from src.panel import card_exists
    with db.connect() as c:
        bets = c.execute(
            "SELECT COUNT(*), COUNT(DISTINCT source_label) FROM bets "
            "WHERE date=? AND source_label NOT LIKE 'Panel:%' "
            "AND source_label NOT IN ('Recommendation','Placed')", (d,)
        ).fetchone()
        queued = c.execute(
            "SELECT COUNT(*) FROM video_queue WHERE slate_date=? "
            "AND processed_at IS NULL", (d,)).fetchone()[0]
        failed = c.execute(
            "SELECT COUNT(*) FROM video_queue WHERE slate_date=? "
            "AND processed_at IS NULL AND error IS NOT NULL", (d,)).fetchone()[0]
    y = (date.today() - timedelta(days=1)).isoformat()
    return {
        "date": d, "bets": bets[0], "sources": bets[1],
        "queued": queued, "failed": failed,
        "channels": len(CHANNELS),
        "card": card_exists(d), "digest": already_sent(d),
        "ungraded_yesterday": pending_count(y),
    }


# ── rendering ───────────────────────────────────────────────────────────
CSS = """
:root{--fg:#1a1a1a;--dim:#777;--line:#e5e5e5;--ok:#1a7f37;--bad:#cf222e;
      --warn:#9a6700;--bg:#fff;--card:#fafafa}
@media(prefers-color-scheme:dark){:root{--fg:#e6e6e6;--dim:#999;--line:#333;
      --bg:#151515;--card:#1e1e1e}}
*{box-sizing:border-box}
body{margin:0;padding:24px;font:14px/1.5 ui-sans-serif,-apple-system,sans-serif;
     color:var(--fg);background:var(--bg);max-width:1100px}
h1{font-size:18px;margin:0 0 2px}h2{font-size:13px;text-transform:uppercase;
   letter-spacing:.07em;color:var(--dim);margin:28px 0 8px;font-weight:600}
.sub{color:var(--dim);font-size:13px;margin-bottom:4px}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;
      vertical-align:top}
th{color:var(--dim);font-weight:600;font-size:12px}
.pill{display:inline-block;padding:1px 7px;border-radius:9px;font-size:11px;
      font-weight:600}
.ok{background:rgba(26,127,55,.14);color:var(--ok)}
.bad{background:rgba(207,34,46,.14);color:var(--bad)}
.warn{background:rgba(154,103,0,.16);color:var(--warn)}
.dim{color:var(--dim)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
      gap:10px}
.box{background:var(--card);border:1px solid var(--line);border-radius:7px;
     padding:11px 13px}
.box .n{font-size:21px;font-weight:650}
.box .l{font-size:11px;color:var(--dim);text-transform:uppercase;
        letter-spacing:.05em}
code{font:12px ui-monospace,monospace;color:var(--dim);word-break:break-all}
button{font:inherit;font-size:12px;padding:2px 9px;border:1px solid var(--line);
       background:var(--bg);color:var(--fg);border-radius:5px;cursor:pointer}
button:hover{border-color:var(--dim)}
form{display:inline}
.wrap{overflow-x:auto}
"""


def _pill(ok: bool, yes: str, no: str, warn: bool = False) -> str:
    cls = "warn" if warn else ("ok" if ok else "bad")
    return f'<span class="pill {cls}">{yes if ok else no}</span>'


@app.route("/")
def index() -> str:
    st = today_state()
    agents = agent_status()
    runs = last_runs()
    q = queue_rows()

    boxes = "".join(
        f'<div class="box"><div class="n">{v}</div><div class="l">{k}</div></div>'
        for k, v in (
            ("capper bets", st["bets"]), ("sources", st["sources"]),
            ("queued", st["queued"]), ("failed", st["failed"]),
            ("channels", st["channels"]),
        )
    )

    ready = (
        f'{_pill(st["card"], "card built", "no card", warn=not st["card"])} '
        f'{_pill(st["digest"], "digest sent", "not sent", warn=not st["digest"])} '
        + (f'<span class="pill bad">{st["ungraded_yesterday"]} ungraded '
           f'yesterday</span>' if st["ungraded_yesterday"]
           else '<span class="pill ok">yesterday graded</span>')
    )

    agent_rows = "".join(
        f"<tr><td><b>{a['name']}</b></td>"
        f"<td>{_pill(a['loaded'], 'loaded', 'missing')}</td>"
        f"<td>{'running' if a['running'] else '<span class=dim>idle</span>'}</td>"
        f"<td>{'exit ' + str(a['exit']) if a['exit'] not in (None, '0') else '<span class=dim>ok</span>'}</td>"
        "</tr>" for a in agents
    )

    def qrow(r: dict) -> str:
        if r["processed_at"]:
            state = _pill(True, f"{r['n_bets']} bets", "")
            when = _ago(r["processed_at"])
        elif r["error"]:
            state = f'<span class="pill bad">failed x{r["attempts"]}</span>'
            when = _ago(r["found_at"])
        else:
            state = '<span class="pill warn">queued</span>'
            when = _ago(r["found_at"])
        act = (
            f'<form method="post" action="{url_for("retry", vid=r["video_id"])}">'
            f'<button>retry</button></form> '
            f'<form method="post" action="{url_for("drop", vid=r["video_id"])}">'
            f'<button>drop</button></form>'
        ) if not r["processed_at"] else ""
        err = (f'<div><code>{r["error"]}</code></div>' if r["error"] else "")
        return (
            f"<tr><td>{r['slate_date']}</td><td><b>{r['label']}</b>"
            f"<div class=dim>{(r['title'] or '')[:80]}</div>{err}</td>"
            f"<td>{state}</td><td class=dim>{when}</td><td>{act}</td></tr>"
        )

    queue_html = ("".join(qrow(r) for r in q) or
                  '<tr><td colspan=5 class=dim>queue empty</td></tr>')

    run_rows = "".join(
        f"<tr><td class=dim>{r['when']}</td><td><b>{r['what']}</b></td>"
        f"<td>{'<span class=pill ok>ok</span>' if r['exit'] == 0 else ('<span class=pill bad>exit ' + str(r['exit']) + '</span>' if r['exit'] is not None else '<span class=pill warn>running</span>')}</td>"
        f"<td>{'<code>' + '<br>'.join(r['errors']) + '</code>' if r['errors'] else ''}</td>"
        "</tr>" for r in runs
    ) or '<tr><td colspan=4 class=dim>no runs logged</td></tr>'

    return f"""<!doctype html><meta charset=utf-8>
<title>morning-bets ops</title>
<meta http-equiv=refresh content=60>
<style>{CSS}</style>
<h1>morning-bets · ops</h1>
<div class=sub>{st['date']} · analysis is manual — run <code>make morning</code>
 when ready</div>
<div style="margin:10px 0 18px">{ready}</div>
<div class=grid>{boxes}</div>

<h2>agents</h2>
<div class=wrap><table>
<tr><th>agent</th><th>state</th><th></th><th>last exit</th></tr>
{agent_rows}</table></div>
<div class=sub style="margin-top:6px">grade 03–11 · discover 03–17 ·
 process 06–17. Nothing else runs on a timer.</div>

<h2>video queue</h2>
<div class=wrap><table>
<tr><th>slate</th><th>source</th><th>state</th><th>when</th><th></th></tr>
{queue_html}</table></div>

<h2>recent runs</h2>
<div class=wrap><table>
<tr><th>when</th><th>job</th><th>result</th><th>errors</th></tr>
{run_rows}</table></div>
"""


@app.post("/retry/<vid>")
def retry(vid: str):
    """Clear the error so the next process pass picks it up again."""
    with db.connect() as c:
        c.execute("UPDATE video_queue SET error=NULL WHERE video_id=?", (vid,))
    return redirect(url_for("index"))


@app.post("/drop/<vid>")
def drop(vid: str):
    with db.connect() as c:
        c.execute("DELETE FROM video_queue WHERE video_id=?", (vid,))
    return redirect(url_for("index"))


def main() -> None:
    db.init()
    url = "http://127.0.0.1:5051"
    print(f"Ops console at {url}  (dashboard is separate, on :5050)")
    if os.environ.get("MORNINGBETS_OPEN", "1") == "1":
        webbrowser.open(url)
    app.run(host="127.0.0.1", port=5051, debug=False)


if __name__ == "__main__":
    main()
