"""Answer questions about the boards and how they graded, with tools.

    venv/bin/python -m scratchpad.ask "how have the K rungs done since the 10th"

The dashboard's chat panel (`board_server` POST /ask) and this CLI both
call `answer()`. Claude gets no numbers in its context up front — every
figure in an answer comes back from a tool call it made, and the trace of
those calls is returned alongside the answer and rendered under it on the
page. That is the whole design: an answer you cannot audit is worth less
than no answer, and a model asked about baseball will happily supply a
league-average strikeout rate from memory.

THE TOOLS ARE PLAIN FUNCTIONS AND THE SCHEMAS ARE A SEPARATE LIST. Nothing
in `TOOLS` or `IMPL` imports Flask or Anthropic, so the same six lookups
can be served over MCP (~40 lines of adapter) without a second
implementation of any of them.

WHAT IT CAN SEE, and the order is deliberate — the specific tools first so
a question with a typed answer never reaches the SQL hatch:

  * `boards_available`  which dates have a board, and which file is it
  * `board_rows`        the rungs on one board, filtered
  * `grading_summary`   Brier vs Kalshi, bet-the-gap, calibration
  * `settled_rungs`     one row per graded rung: priced, actual, won
  * `database_schema`   tables and columns of the two databases
  * `query`             read-only SQL, for everything the five miss

`grading_summary` and `settled_rungs` are `grade_boards`' own functions,
not a re-implementation, so the panel and
`venv/bin/python -m scratchpad.grade_boards` cannot print two different
Briers for the same range.

THE SQL HATCH IS READ-ONLY THREE TIMES OVER, because a chat box wired to
a database is the one place in this repo where a generated string reaches
`morning_bets.db`: both files open through a `mode=ro` URI, an sqlite3
AUTHORIZER rejects every operation except reads (which also kills ATTACH,
the way a read-only connection would otherwise be talked into writing
somewhere else), and a progress handler aborts a query that runs away.
`check_the_sql_hatch_*` in `tests/test_ask.py` hold all three.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

from scratchpad import boards, grade_boards as gb

ROOT = Path(__file__).resolve().parent.parent

MODEL = "claude-opus-5"
MAX_TURNS = 8          # tool round trips before the loop gives up
MAX_HISTORY = 12       # prior chat messages replayed into a request

#: One sqlite3 op is one page read, so this is generous for any indexed
#: lookup and still stops a cross join from hanging the page.
SQL_OPS_LIMIT = 2_000_000


# ── the numbers ────────────────────────────────────────────────────────

def boards_available() -> dict:
    """Every date with a board, newest first."""
    files = boards.board_files()
    out = []
    for d in sorted(files, reverse=True):
        paths = files[d]
        try:
            games = boards.load(paths[-1])["games"]
            n_games, n_rows = len(games), sum(len(g["rows"]) for g in games)
        except Exception as e:                    # a half-written re-run
            n_games, n_rows = None, f"unreadable: {e}"
        out.append(dict(date=d, file=os.path.basename(paths[-1]),
                        versions=[os.path.basename(p) for p in paths],
                        games=n_games, rungs=n_rows))
    return dict(dates=out)


def board_rows(date: str, cls: str | None = None, team: str | None = None,
               pitcher: str | None = None, min_gap: float | None = None,
               limit: int = 40) -> dict:
    """The rungs on one date's board of record."""
    path = boards.board_of_record(date)
    if path is None:
        return dict(error=f"no board for {date}",
                    have=sorted(boards.board_files(), reverse=True)[:10])
    d = boards.load(path)
    rows = []
    for g in d["games"]:
        game = f'{g["away"]} @ {g["home"]}'
        if team and team.upper() not in (g["away"].upper(), g["home"].upper()):
            continue
        for r in g["rows"]:
            if cls and r["cls"] != cls:
                continue
            if pitcher and pitcher.lower() not in r["bet"].lower():
                continue
            if min_gap is not None and (r["gap"] is None
                                        or abs(r["gap"]) < min_gap):
                continue
            rows.append(dict(
                game=game, away_sp=g["ap"], home_sp=g["hp"], cls=r["cls"],
                bet=r["bet"], p_over_ours=r["p_over"],
                p_over_kalshi=r["p_kalshi"], gap_points=r["gap"],
                our_over=r["over"], our_under=r["under"],
                kalshi_over=r["kalshi"], dollars_traded=r.get("vol"),
                offband=r["offband"], thin=r["thin"], gate=r.get("gate")))
    rows.sort(key=lambda r: -abs(r["gap_points"] or 0))
    return dict(date=date, file=os.path.basename(path),
                lineups=f'{d.get("lineups_posted")} of '
                        f'{d.get("games_scheduled")} posted',
                sims=d.get("sims"), matched=len(rows),
                truncated=max(0, len(rows) - limit), rows=rows[:limit])


def grading_summary(since: str | None = None,
                    through: str | None = None) -> dict:
    """How the boards in a date range scored against what happened."""
    through = through or _last_board_date()
    rows, unresolved, used = gb.graded_rungs(through, since=since)
    if not rows:
        return dict(error=f"no graded boards in {since or 'start'}..{through}")
    live = [r for r in rows if not r["push"]]
    return dict(
        range=f"{min(used)}..{max(used)}", boards=len(used),
        files={d: os.path.basename(p) for d, p in used.items()},
        rungs_settled=len(rows), pushes=len(rows) - len(live),
        with_kalshi=sum(1 for r in live if r["p_k"] is not None),
        unresolved=unresolved,
        head_to_head=gb.head_to_head(rows),
        bet_the_gap=gb.bet_the_gap(rows),
        calibration=gb.calibration(rows),
        notes=["head_to_head is PAIRED — only rungs Kalshi also quoted. "
               "diff is ours minus theirs, so POSITIVE means we scored "
               "worse. Compare diff against its own se before calling it "
               "anything.",
               "bet_the_gap is a counterfactual at the morning mid, not a "
               "record of bets placed, and it is not the objective."])


def settled_rungs(since: str | None = None, through: str | None = None,
                  cls: str | None = None, date: str | None = None,
                  team: str | None = None, pitcher: str | None = None,
                  min_gap: float | None = None, limit: int = 40) -> dict:
    """Individual graded rungs: what was priced, what happened, who won."""
    if date:
        since = through = date
    through = through or _last_board_date()
    rows, _, used = gb.graded_rungs(through, since=since)
    out = []
    for r in rows:
        if cls and r["cls"] != cls:
            continue
        if team and team.upper() not in r["game"].upper() \
                and not r["bet"].upper().startswith(team.upper()):
            continue
        if pitcher and pitcher.lower() not in r["bet"].lower():
            continue
        gap = (None if r["p_k"] is None
               else round((r["p_us"] - r["p_k"]) * 100, 1))
        if min_gap is not None and (gap is None or abs(gap) < min_gap):
            continue
        out.append(dict(
            date=r["date"], game=r["game"], cls=r["cls"], bet=r["bet"],
            line=r["line"], actual=r["actual"],
            p_over_ours=r["p_us"], p_over_kalshi=r["p_k"],
            gap_points=gap, push=r["push"],
            over_hit=None if r["push"] else bool(r["hit"]),
            our_side=("push" if r["push"] else
                      "over" if r["p_us"] > 0.5 else "under"),
            our_side_won=(None if r["push"] else
                          bool(r["hit"]) == (r["p_us"] > 0.5)),
            gap_side_won=(None if r["push"] or gap is None else
                          bool(r["hit"]) == (gap > 0))))
    out.sort(key=lambda r: (r["date"], -abs(r["gap_points"] or 0)))
    return dict(range=f"{min(used)}..{max(used)}" if used else None,
                matched=len(out), truncated=max(0, len(out) - limit),
                rows=out[:limit],
                note="our_side is the side we priced above even money; "
                     "gap_side is the side we priced above KALSHI, which "
                     "is the disagreement and is often the other one.")


def _last_board_date() -> str:
    files = boards.board_files()
    return max(files) if files else "1970-01-01"


# ── the escape hatch ───────────────────────────────────────────────────

DBS = {"main": ROOT / "morning_bets.db", "ctx": ROOT / "context.db"}

#: Every sqlite3 authorizer action that only reads. Anything absent —
#: INSERT, UPDATE, DELETE, DROP, ATTACH, CREATE — is denied before the
#: statement runs.
_READ_ONLY = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
              sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}

#: PRAGMA is denied as a class, with two introspection reads let back
#: through by NAME so `database_schema` can run on the same guarded
#: connection as everything else. A pragma that changes anything —
#: `writable_schema`, `journal_mode` — is not on this list and the
#: authorizer never sees a reason to allow it.
_READ_PRAGMAS = {"table_info", "table_list"}


def _allow(action, arg1, *rest):
    if action in _READ_ONLY:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and arg1 in _READ_PRAGMAS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DBS['main']}?mode=ro", uri=True)
    con.execute("attach database ? as ctx", (f"file:{DBS['ctx']}?mode=ro",))
    # Set AFTER the attach — the authorizer denies ATTACH itself, which is
    # the point: the model cannot reach a third file, writable or not.
    con.set_authorizer(_allow)
    n = [0]

    def tick():
        n[0] += 1
        return 1 if n[0] > SQL_OPS_LIMIT // 1000 else 0
    con.set_progress_handler(tick, 1000)
    return con


def database_schema(table: str | None = None) -> dict:
    """Tables and columns. `main` is morning_bets.db, `ctx` is context.db."""
    con = _connect()
    try:
        out = {}
        for schema in ("main", "ctx"):
            for (name,) in con.execute(
                    f"select name from {schema}.sqlite_master "
                    "where type='table' order by name"):
                if table and table.lower() not in name.lower():
                    continue
                cols = [(r[1], r[2]) for r in
                        con.execute(f'pragma {schema}.table_info("{name}")')]
                out[f"{schema}.{name}"] = [f"{c} {t}" for c, t in cols]
        return dict(tables=out, note="qualify ctx tables as ctx.<table>; "
                    "main tables need no prefix")
    finally:
        con.close()


def query(sql: str, limit: int = 50) -> dict:
    """Run one read-only SELECT against the two databases."""
    limit = max(1, min(int(limit), 200))
    con = _connect()
    try:
        cur = con.execute(sql)
        cols = [c[0] for c in (cur.description or [])]
        rows = [dict(zip(cols, r)) for r in cur.fetchmany(limit + 1)]
        return dict(columns=cols, rows=rows[:limit],
                    truncated=len(rows) > limit, returned=len(rows[:limit]))
    except sqlite3.DatabaseError as e:
        msg = str(e)
        if "not authorized" in msg:
            msg += (" — this connection reads and nothing else. No INSERT, "
                    "UPDATE, DELETE, ATTACH, or any PRAGMA beyond "
                    "table_info.")
        return dict(error=msg, sql=sql)
    finally:
        con.close()


# ── what Claude sees ───────────────────────────────────────────────────

IMPL = {"boards_available": boards_available, "board_rows": board_rows,
        "grading_summary": grading_summary, "settled_rungs": settled_rungs,
        "database_schema": database_schema, "query": query}

_DATE = {"type": "string", "description": "ISO date, YYYY-MM-DD"}
_CLS = {"type": "string", "enum": ["total", "team", "f5", "k", "outs"],
        "description": "market class: total = full-game total, team = a "
                       "club's team total, f5 = first-five total, k = a "
                       "starter's strikeouts, outs = a starter's outs"}

TOOLS = [
    {"name": "boards_available",
     "description": "Which dates have a board, how many games and rungs "
                    "each carries, and which JSON is the board of record. "
                    "Call this first when the question names no date.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "board_rows",
     "description": "The rungs priced on one date's board: our fair odds "
                    "and probability, Kalshi's mid, the gap between them, "
                    "and dollars traded on the contract. This is what was "
                    "PRICED, not what happened.",
     "input_schema": {"type": "object", "required": ["date"], "properties": {
         "date": _DATE, "cls": _CLS,
         "team": {"type": "string", "description": "team abbreviation, "
                                                   "e.g. NYY"},
         "pitcher": {"type": "string", "description": "substring of the "
                                                      "pitcher's name"},
         "min_gap": {"type": "number", "description": "only rungs at least "
                                                      "this many POINTS "
                                                      "from the mid"},
         "limit": {"type": "integer"}}}},
    {"name": "grading_summary",
     "description": "How the boards in a date range scored against actual "
                    "results: our Brier against Kalshi's on the rungs both "
                    "quoted, the bet-the-gap counterfactual by threshold, "
                    "and our calibration by decile. Use this for any "
                    "question about how we have DONE.",
     "input_schema": {"type": "object", "properties": {
         "since": _DATE, "through": _DATE}}},
    {"name": "settled_rungs",
     "description": "One row per graded rung: the line, our probability, "
                    "Kalshi's, the actual number it settled on, and "
                    "whether our side won. Use it to name specific "
                    "results rather than aggregates.",
     "input_schema": {"type": "object", "properties": {
         "since": _DATE, "through": _DATE, "date": _DATE, "cls": _CLS,
         "team": {"type": "string"}, "pitcher": {"type": "string"},
         "min_gap": {"type": "number"}, "limit": {"type": "integer"}}}},
    {"name": "database_schema",
     "description": "Tables and columns available to `query`. Call before "
                    "writing SQL rather than guessing a column name.",
     "input_schema": {"type": "object", "properties": {
         "table": {"type": "string", "description": "filter by substring"}}}},
    {"name": "query",
     "description": "Read-only SQL over morning_bets.db (scores in "
                    "`games`, boxscores in `mlb_pitching` / `mlb_batting`) "
                    "and context.db (`ctx.mlb_stints`, `ctx.mlb_lineups`, "
                    "`ctx.mlb_weather`). For anything the other tools do "
                    "not cover — a player's actual line, a club's scoring, "
                    "a head-to-head. SELECT only.",
     "input_schema": {"type": "object", "required": ["sql"], "properties": {
         "sql": {"type": "string"},
         "limit": {"type": "integer", "description": "max rows, cap 200"}}}},
]

SYSTEM = """\
You answer questions about a baseball simulation's board: the prices it \
published each morning and how they graded against what actually happened. \
You are talking to the operator who built it, in a panel on the board page \
itself. He knows the domain; he wants numbers, not tutoring.

LOOK EVERYTHING UP. Every figure you state must come from a tool call in \
this conversation. You have no reliable memory of this league, this \
model's history, or any player's season, and a number recalled rather than \
counted is the failure mode this panel exists to avoid. If the tools \
cannot answer, say exactly that and say which lookup you tried.

WHAT THE NUMBERS MEAN
* A rung is one line: `total 8.5`, `NYY total 4.5`, `F5 total 4.5`, \
`Tarik Skubal k 6.5`, `Tarik Skubal outs 16.5`. `p_over_ours` is the \
simulation's probability the OVER settles; `p_over_kalshi` is the market \
mid's. `gap_points` is ours minus theirs in percentage points, so +9 means \
we price the over nine points higher than the market.
* Odds printed on the board are FAIR — no vig either side.
* `dollars_traded` under $500 means the Kalshi mid is a market maker's \
resting quote, not a price anyone took. Say so when a gap rests on one.
* A `gate` or `thin` flag on a rung means the disagreement is more likely \
our own error than the market's. Never lead with a flagged rung.

HOW TO READ A RESULT, and this is the part that matters
* State the standard error next to any difference you call a result. The \
head-to-head diff comes with its own se; a difference inside one se is not \
a finding, and say that plainly rather than hedging around it.
* We are BEHIND Kalshi on Brier overall and on every market class. That is \
the measured state of things. Do not soften it, and do not present the \
bet-the-gap P&L as if it answered it — beating a mid is market timing, \
accurate simulation is the objective, and the two have come apart here \
before.
* A mean that did not move says nothing about a distribution's shape.
* Small n is most of what you will be asked about. Eleven boards is a \
couple of thousand rungs and a fortnight of baseball; say when a slice is \
too thin to carry the claim being made of it.

STYLE. Terse. Lead with the number and its uncertainty. Markdown tables \
for more than three numbers, prose otherwise. No preamble, no \
restating the question, no closing offer of further help. Name the date \
range and n behind every aggregate. When a question is about tonight's \
board, the board's own date is in the first user message.\
"""


# ── the loop ───────────────────────────────────────────────────────────

def _client():
    try:
        import anthropic
    except ImportError:                              # pragma: no cover
        raise RuntimeError("the anthropic package is not installed")
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set, and .env does not "
                           "carry one — the chat panel cannot answer")
    return anthropic.Anthropic(api_key=key)


def run_tool(name: str, args: dict) -> tuple[str, bool]:
    """Call one tool by name. Returns (json payload, is_error).

    A tool that raises comes back as a tool_result with is_error set
    rather than as a 500: a bad column name in generated SQL is a normal
    event in this loop and Claude fixes it on the next turn.
    """
    fn = IMPL.get(name)
    if fn is None:
        return json.dumps({"error": f"no tool named {name}"}), True
    try:
        return json.dumps(fn(**args), default=str), False
    except TypeError as e:                  # wrong or missing argument
        return json.dumps({"error": f"bad arguments for {name}: {e}"}), True
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"}), True


def answer(question: str, history: list[dict] | None = None,
           date: str | None = None, client=None,
           max_turns: int = MAX_TURNS) -> dict:
    """One question in, an answer and the trace of its lookups out.

    `history` is prior {role, content} text turns from the panel; `date`
    is the board the reader is looking at, so "tonight" resolves without
    a guess. `client` is injected by the tests — nothing here reaches the
    network when one is supplied.
    """
    client = client or _client()
    msgs = [{"role": m["role"], "content": m["content"]}
            for m in (history or [])[-MAX_HISTORY:]]
    opening = question if not date else \
        f"[the reader is looking at the {date} board]\n\n{question}"
    msgs.append({"role": "user", "content": opening})

    trace = []
    # Accumulated across the whole loop, because ONE question is several
    # requests and the per-request number understates what the panel
    # costs by a factor of the tool round trips.
    used = dict(input=0, output=0, cache_read=0)
    for _ in range(max_turns):
        resp = client.messages.create(
            model=MODEL, max_tokens=8000,
            system=[{"type": "text", "text": SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS, messages=msgs)
        u = getattr(resp, "usage", None)
        if u is not None:
            used["input"] += getattr(u, "input_tokens", 0) or 0
            used["output"] += getattr(u, "output_tokens", 0) or 0
            used["cache_read"] += getattr(u, "cache_read_input_tokens",
                                          0) or 0
        msgs.append({"role": "assistant", "content": resp.content})
        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:
            text = "\n".join(b.text for b in resp.content if b.type == "text")
            return dict(answer=text.strip(), trace=trace, usage=used,
                        stop_reason=resp.stop_reason)
        results = []
        for b in calls:
            payload, failed = run_tool(b.name, dict(b.input))
            trace.append(dict(tool=b.name, input=b.input, error=failed,
                              bytes=len(payload)))
            results.append({"type": "tool_result", "tool_use_id": b.id,
                            "content": payload, "is_error": failed})
        # All results in ONE user message. Splitting them teaches the
        # model to stop calling tools in parallel.
        msgs.append({"role": "user", "content": results})
    return dict(answer="Gave up after %d rounds of lookups without landing "
                       "on an answer." % max_turns, trace=trace, usage=used,
                stop_reason="max_turns")


def main(argv):
    if not argv:
        print(__doc__.strip().split("\n\n")[1])
        return
    date = None
    if "--date" in argv:
        i = argv.index("--date")
        date = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    out = answer(" ".join(argv), date=date)
    for t in out["trace"]:
        print(f"  · {t['tool']}({json.dumps(t['input'])[:100]})"
              f"{'  FAILED' if t['error'] else ''}", file=sys.stderr)
    u = out.get("usage") or {}
    if u:
        print(f"  {u['input']:,} in ({u['cache_read']:,} cached) / "
              f"{u['output']:,} out", file=sys.stderr)
    print(out["answer"])


if __name__ == "__main__":
    main(sys.argv[1:])
