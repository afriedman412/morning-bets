"""Consensus recommender: the three panel personas nominate, debate, and
converge on a shared card of NUM_PICKS bets.

Replaces the old accuracy-weighted single-shot recommender (which ranked the
capper slate by each source's historical W-L in slices relevant to the pick).
The flow is now:

  R0  nominate  — each persona reads the full slate and proposes its own best
                  NUM_PICKS-bet card                     (3 calls, search on)
  R1  debate    — each persona scores every candidate 0-10, may veto (3 calls)
      tally     — Python: drop multi-veto candidates, rank by mean score
      converged?— Python: #4 leads #5 by CONVERGENCE_GAP, no veto in the top 4
  R2  rebuttal  — contested candidates only, with the others' reasons (3 calls)
  close         — sorted()[:NUM_PICKS], at most one bet per matchup

Termination is structural, not negotiated. MAX_DEBATE_ROUNDS is a constant; the
personas only ever emit scores and vetoes (they are never asked "are we done");
and the final selection is a sort, so it returns even when all three disagree.
Worst case is 9 API calls, best case 6.

Every round after R0 references bets by candidate id only — no persona ever
re-types a matchup string, which is what the old prompt's four paragraphs of
anchoring rules were fighting.
"""
from __future__ import annotations

import json
import os
import random
import re
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from src import db, parallel
from src.grading import cache_day, fetch_mlb_market, same_party

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BETS_DIR = PROJECT_ROOT / "bets"
CACHE_DIR = PROJECT_ROOT / ".cache"

MODEL = "claude-sonnet-4-6"
RECOMMENDER_LABEL = "Recommendation"
SIM_LABEL = "Consensus (sim)"

NUM_PICKS = 5
MAX_PER_MATCHUP = 1
MAX_DEBATE_ROUNDS = 2          # hard ceiling — not a model decision
CONVERGENCE_GAP = 1.0          # #5 must lead #6 by this to stop after R1
VETO_PENALTY = 1.5             # score penalty for a single veto
VETO_ELIMINATION = 2           # this many vetoes eliminates a candidate
# 3 personas x this many nominations, minus overlap, minus MAX_PER_MATCHUP.
# At 5 the personas converged hard enough that 15 nominations collapsed to 7
# distinct candidates and the one-per-matchup rule trimmed those to a 4-bet
# card. 6 widens the pool without reaching much further down each persona's
# own ranking.
NOMINATIONS_PER_PERSONA = 6
MIN_DISTINCT_BET_TYPES = 2     # each persona's card must span >= this many

# Sources the user actually rates, as a nudge on the consensus score rather
# than a hard override — the personas still have to like the bet. Keyed by
# source_label, then by that source's own confidence tier ('*' = any tier).
# A factor of 1.0 adds PUSH_WEIGHT to the candidate's adjusted score.
SOURCE_PUSH = {
    "Lindy's Leans Likes & Locks": {
        "LOCK": 1.00,
        "LIKE": 0.75,
        "LEAN": 0.50,
        "*": 0.50,
    },
    "Calling Our Shot - MLB": {"*": 0.35},
}
# Scored on the personas' 1-10 scale, so a full push is worth one point —
# enough to break a tie or lift a bet a rung, not enough to buy a slot the
# personas actively dislike. VETO_PENALTY (1.5) still outweighs it.
PUSH_WEIGHT = 1.0

# Bet types the user never places, so they must not occupy a card slot.
# Matched on the canonical stat key, exactly — 'h+r+rbi' is not an HR bet.
EXCLUDED_STATS = {"hr"}

# Conviction and price are decided separately, then multiplied.
#
# CONVICTION comes from RANK, not the raw score. The 22-day backtest found
# the card's top 2 hit 55.8% (+6.6% ROI) while ranks 3-4 hit 38.1% (-27.3%)
# — the ranking carries signal but the tail does not deserve equal money.
UNIT_CENTS = 5000               # 1 unit = $50, unchanged
BASE_UNITS_BY_RANK = {1: 1.0, 2: 1.0, 3: 0.5, 4: 0.5, 5: 0.25}
TIER_BY_RANK = {1: "LOCK", 2: "LOCK", 3: "LIKE", 4: "LIKE", 5: "LEAN"}
FALLBACK_UNITS = 0.25
DEFAULT_ODDS = -110

# PRICE then scales that stake. By the time the card is read the number has
# usually moved against us, and refusing to bet a moved line throws away a
# pick we still like. Instead the stake follows what the price actually
# pays: factor = net payout / net payout at -110. So -110 is 1.00x, a
# plus-money price earns more, and juice bleeds the stake down.
PRICE_REF_ODDS = -110
PRICE_FACTOR_CAP = 1.25         # don't let a longshot balloon the stake
PRICE_FACTOR_FLOOR = 0.25
# Past this the payout no longer justifies the risk at any conviction, so
# the bet does not go on the card at all. Was -250, which still let a -376
# prop take a slot (8/22, Ryan Weathers k under 5.5) because the guard only
# zeroed the stake instead of freeing the slot — see fill_card().
PRICE_PASS_THRESHOLD = -200
# 0.25 was too coarse to express the adjustment: a pick whose real price
# came back 227 points worse than quoted still rounded to the same stake.
# 0.1u is $5 on a $50 unit — placeable, and actually responsive.
UNIT_INCREMENT = 0.1
WEB_SEARCH_MAX_USES = 8
WEB_SEARCH_TOOL = "web_search_20260209"  # dynamic filtering (Sonnet 4.6+)

PERSONA_ORDER = ("Quant", "Cynic", "Careful")


# ── usage accounting ───────────────────────────────────────────────────
class Usage:
    """Accumulates token + search usage so a run reports its own cost."""

    CACHE_WRITE_MULT = 1.25
    CACHE_READ_MULT = 0.10
    SEARCH_PER_1K = 10.00

    def __init__(self) -> None:
        self.input = 0
        self.output = 0
        self.cache_write = 0
        self.cache_read = 0
        self.searches = 0
        self.calls = 0
        self._lock = threading.Lock()

    def add(self, reply) -> None:
        """Takes a normalized llm.Reply, not a provider-specific response.

        Locked because the three personas call this from separate threads
        now, and `self.input += n` is a load-add-store, not an atomic op —
        two threads interleaving there silently drop a whole call's tokens
        from the cost line, which is the one number a run reports about
        itself.
        """
        with self._lock:
            self.calls += 1
            self.input += reply.input_tokens
            self.output += reply.output_tokens
            self.cache_write += reply.cache_write
            self.cache_read += reply.cache_read
            self.searches += reply.searches

    @property
    def cost(self) -> float:
        from src import llm
        try:
            inp, out = llm.rates(llm.model_id())
        except RuntimeError:
            return 0.0
        return (
            self.input / 1e6 * inp
            + self.cache_write / 1e6 * inp * self.CACHE_WRITE_MULT
            + self.cache_read / 1e6 * inp * self.CACHE_READ_MULT
            + self.output / 1e6 * out
            + self.searches / 1000 * self.SEARCH_PER_1K
        )

    def summary(self) -> str:
        from src import llm
        c = self.cost
        price = f"${c:.2f}" if c else "$? (pricing unset)"
        return (
            f"{self.calls} calls | {llm.describe()} | in {self.input:,} "
            f"(cache w{self.cache_write:,} r{self.cache_read:,}) | "
            f"out {self.output:,} | {self.searches} searches | {price}"
        )


# ── context assembly ───────────────────────────────────────────────────
def _require_cached(name: str) -> None:
    """In as-of mode a missing snapshot is an error, never a live fetch."""
    if not (CACHE_DIR / name).exists():
        raise FileNotFoundError(
            f"as-of mode: {name} not in .cache/ — refusing to fetch today's "
            f"data for a past date (that would be lookahead bias)."
        )


def _all_batters_block(batter_idx: dict[str, dict]) -> str:
    """Every qualified batter, not just the capper-mentioned handful.

    The old panel builder filtered to players a capper named, which on a
    typical slate meant ~4 of 251 batters had any data attached — which is
    why batter props barely appeared on the board.
    """
    rows = [
        f"- {name.title()}: BA {x['ba']} (xBA {x['xba']}), "
        f"SLG {x['slg']} (xSLG {x['xslg']}), "
        f"wOBA {x['woba']} (xwOBA {x['xwoba']}), PA {x['pa']}"
        for name, x in sorted(batter_idx.items())
    ]
    return "\n".join(rows) if rows else "(no batter data)"


def _market_block_offline(conn: sqlite3.Connection, date_str: str) -> str:
    """Reconstruct that morning's market lines from the bets table.

    Used in as-of mode. Re-fetching ESPN for a past date would return
    *closing* lines; the lines the cappers quoted (and the consensus totals
    fill_missing_lines wrote that morning) are the point-in-time truth.
    """
    rows = conn.execute(
        "SELECT matchup, bet_type, side, line, COUNT(*) n "
        "FROM bets WHERE date=? AND sport='mlb' AND line IS NOT NULL "
        "AND bet_type IN ('total','spread') AND matchup IS NOT NULL "
        "GROUP BY matchup, bet_type, line ORDER BY matchup, n DESC",
        (date_str,),
    ).fetchall()
    by_match: dict[str, dict[str, float]] = {}
    for r in rows:
        d = by_match.setdefault(r["matchup"], {})
        d.setdefault(r["bet_type"], r["line"])
    if not by_match:
        return "(no market lines recoverable for this date)"
    out = []
    for m, d in by_match.items():
        bits = []
        if "total" in d:
            bits.append(f"total {d['total']}")
        if "spread" in d:
            bits.append(f"runline {d['spread']}")
        out.append(f"- {m}: {'; '.join(bits)}")
    return "\n".join(out)


def build_context(
    date_str: str, as_of: bool = False,
) -> tuple[str, list[dict], list[dict]]:
    """Return (shared_context_block, slate, capper_bets).

    The shared block is byte-identical across all three personas so it can
    carry a cache_control breakpoint: it is re-read on every search iteration
    within a turn and by every persona, which is where the cost lives.
    """
    from src import panel

    year = datetime.strptime(date_str, "%Y-%m-%d").year
    if as_of:
        _require_cached(f"savant_batter_xstats_{year}_{date_str}.csv")
        _require_cached(f"savant_pitch_arsenal_{year}_{date_str}.csv")

    batter_idx = panel._batter_blob(
        panel.savant_batter_expected(year, date_str),
    )
    arsenal_idx = panel._pitcher_arsenal_blob(
        panel.savant_pitcher_arsenal(year, date_str),
    )
    slate = panel.mlb_schedule_with_probables(date_str)
    capper_bets = panel.capper_bets_for_date(date_str)

    if as_of:
        with db.connect() as conn:
            market = _market_block_offline(conn, date_str)
    else:
        market = panel._consensus_block(date_str)

    block = "\n\n".join([
        "TODAY'S MLB SLATE (games, probables, venue, weather):\n"
        + panel._slate_block(slate),
        "CURRENT MARKET LINES:\n" + market,
        "WHAT THE YOUTUBE CAPPERS ARE SAYING:\n"
        + panel._capper_block(capper_bets),
        "SAVANT PER-PITCH ARSENAL FOR TODAY'S PROBABLE STARTERS:\n"
        + panel._starter_blob(slate, arsenal_idx),
        "SAVANT EXPECTED STATS — ALL QUALIFIED BATTERS:\n"
        + _all_batters_block(batter_idx),
    ])
    return block, slate, capper_bets


# ── candidate identity ─────────────────────────────────────────────────
def _norm(v) -> str:
    return (str(v).strip().lower() if v not in (None, "") else "")


def _norm_line(v) -> float | None:
    """The line as a float, or None.

    `line` was the one key field never normalized, so null / '' / a bare 0
    on a moneyline all compared unequal and split one bet into two
    candidates.
    """
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _payout(american: int | float) -> float:
    """Decimal profit per unit staked, so +115 and -105 are comparable."""
    a = float(american)
    return a / 100 if a > 0 else 100 / abs(a)


def _worst_odds(a, b):
    """The less generous of two quotes for the same bet.

    Once duplicates collapse, one candidate can hold two persona-quoted
    prices — on 8/16 the same White Sox moneyline was nominated at +115 and
    at +103, and the write-up argued for the bet using the better number.
    Assuming the friendlier quote is exactly how a bet gets sized on a price
    that isn't there, so keep the one that hurts.
    """
    if a is None:
        return b
    if b is None:
        return a
    return a if _payout(a) <= _payout(b) else b


def normalize_candidate(b: dict) -> dict:
    """One canonical shape per bet, so dedup sees one candidate.

    The personas write free-form JSON, and on 8/16 three of thirteen
    candidates were phantom duplicates: 'Chicago White Sox ML' twice (one
    with player_name filled, one without), 'San Diego Padres ML' likewise,
    and 'Freddy Peralta k under 6.5' against 'Freddy Peralta strikeouts
    under 6.5'. Each pair was scored separately, which splits the vote and
    lets a single thesis hold two slots — the White Sox version landed on
    the card while its twin sat at rank 9, so a five-bet card looked like
    five ideas when it wasn't.
    """
    from src.grading import canonical_team, normalize_stat

    b = dict(b)
    bt = _norm(b.get("bet_type"))
    b["stat"] = normalize_stat(b.get("stat"))
    b["line"] = _norm_line(b.get("line"))

    if bt in ("ml", "spread", "total"):
        # The club lives in `side` for these; a persona that also fills
        # player_name is describing the same wager, not a different one.
        b["player_name"] = None
    if bt == "ml":
        b["line"] = None            # a moneyline has no line; some send 0
    if bt in ("ml", "spread"):
        b["side"] = canonical_team(b.get("side"))
    if bt == "team_total":
        # Here the club is in player_name and `stat` is redundant — it
        # arrives as 'total', 'team_total', or null depending on who wrote
        # it. persist_bets already nulls it for the same reason.
        b["stat"] = None
        b["player_name"] = canonical_team(b.get("player_name"))
    if bt in ("total", "team_total"):
        s = (b.get("side") or "").strip().lower()
        b["side"] = s or None
    return b


def candidate_key(b: dict) -> tuple:
    return (
        _norm(b.get("matchup")), _norm(b.get("player_name")),
        _norm(b.get("stat")), _norm_line(b.get("line")),
        _norm(b.get("side")), _norm(b.get("bet_type")),
        _norm(b.get("period")) or "full",
    )


def _bet_description(g: dict) -> str:
    line = g.get("line")
    line_str = f" {line}" if line is not None else ""
    period = g.get("period") or "full"
    prefix = "F5 " if period == "f5" else ""
    bt = g.get("bet_type")
    if bt == "ml":
        return f"{prefix}{g.get('side')} ML"
    if bt in ("spread", "total"):
        return f"{prefix}{g.get('side')}{line_str}".strip()
    if bt == "team_total":
        team = g.get("player_name") or ""
        return f"{prefix}{team} team total {g.get('side')}{line_str}".strip()
    parts = [
        prefix.strip(), g.get("player_name"), g.get("stat"),
        g.get("side"), str(line) if line is not None else None,
    ]
    return " ".join(p for p in parts if p)


# ── prompts ────────────────────────────────────────────────────────────
NOMINATE_PROMPT = """\
TODAY: {today_pretty}

You are nominating for a SHARED card, not writing your own slate. You and two
other analysts (Quant, Cynic, Careful) will each nominate {n} bets; the pooled
nominations are then scored by all three and the top {num_picks} become the
card that actually gets bet.

So nominate the {n} bets you would most want ON A {num_picks}-BET CARD — your
highest-conviction, best-priced edges. Not your 5th-best shrug.

RULES
- Nominate EXACTLY {n} bets.
- Your {n} must span at least {min_types} distinct bet_type values. Do not
  submit four moneylines.
- MLB only. No futures, no parlays.
- NO home-run props. The bettor does not play them, so an HR nomination is a
  wasted slot — it is discarded before scoring. Nominate something else.
- BET THE OFFERED LINE. Game totals and runlines must use the number in the
  market-lines block. Player props and team totals must use a line a capper
  quoted{search_clause}. You may NOT invent a number: if the total is 8.5 and
  you like the under but think the true number is 7.5, you bet under 8.5 or
  you pass.
- Props are first-class here. You have expected-stats for every qualified
  batter and per-pitch arsenal for every probable starter — use them. Standard
  prop lines (HR over 0.5, TB over 1.5, K's at 5.5/6.5) are near-universally
  posted{price_clause}.
- Skip any moneyline or favorite priced -150 or shorter.

Output ONLY a JSON array of exactly {n} objects. No prose before or after.
{{
  "matchup": exact "Away Team @ Home Team" from the slate above,
  "player_name": string | null (team name for team_total, player for props),
  "stat": string | null (h, hr, rbi, k, outs, tb, ml, spread, total, ...),
  "line": number | null,
  "side": "over" | "under" | team name,
  "bet_type": "ml" | "spread" | "total" | "team_total" | "prop" | "combo",
  "period": "full" | "f5",
  "american_odds": integer | null (the price you found; null if none),
  "thesis": "one sentence — the edge, citing a number from the context"
}}
"""

DEBATE_PROMPT = """\
TODAY: {today_pretty}

The three of you nominated for a shared {num_picks}-bet card. Here is the
pooled candidate list. Score EVERY candidate.

CANDIDATES:
{pool_block}

Score each 0-10 on whether it belongs on the final {num_picks}-bet card:
  0-2  bad bet — wrong side, bad price, or thesis doesn't hold
  3-5  defensible but not a top-4 use of the card
  6-8  genuinely good, would be glad to have it
  9-10 the best bets on the board

You may VETO a candidate you think is actively bad. A veto needs a reason —
one without a real reason is not counted. Two vetoes eliminate a candidate, so
do not spend them lightly. Vetoing everything you merely dislike wastes them.

Judge the bet, not who nominated it. Your own nominations get no bonus; if the
others convince you a candidate of yours is weak, score it low.

Refer to candidates by their id. Do not re-type the bet.

Output ONLY a JSON array, one object per candidate id above:
{{"id": "C01", "score": 0-10, "reason": "one sentence",
  "veto": true|false, "veto_reason": string|null}}
"""

REBUTTAL_PROMPT = """\
TODAY: {today_pretty}

Round 1 scoring is in. The top of the board is settled, but these candidates
are contested — the three of you disagree, or someone vetoed. Everyone's
round-1 reasoning on exactly these is shown.

CONTESTED CANDIDATES:
{contested_block}

Re-score ONLY these. You have the others' arguments now: if someone caught
something you missed, move. Conceding is a good outcome, not a loss — but do
not move just to agree. If your original read still holds, hold it and say why.

Output ONLY a JSON array, one object per contested id:
{{"id": "C01", "score": 0-10, "reason": "one sentence",
  "veto": true|false, "veto_reason": string|null,
  "conceded": true|false}}
"""


# ── LLM plumbing ───────────────────────────────────────────────────────
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _parse_json_array(text: str) -> list[dict]:
    """Tolerant array extraction — R0 can't use structured outputs because
    web_search forces citations on, and citations + output_config is a 400."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("["), t.rfind("]")
        if start == -1 or end <= start:
            raise
        return json.loads(t[start:end + 1])


BALLOT_SCHEMA = {
    "type": "object",
    "properties": {
        "ballots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "score": {"type": "number"},
                    "reason": {"type": "string"},
                    "veto": {"type": "boolean"},
                    "veto_reason": {"type": ["string", "null"]},
                    "conceded": {"type": "boolean"},
                },
                "required": ["id", "score", "reason", "veto"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["ballots"],
    "additionalProperties": False,
}


def _call(
    persona: str, shared_block: str, instructions: str,
    usage: Usage, use_search: bool, max_tokens: int = 6000,
    schema: dict | None = None,
) -> str:
    """One persona call, dispatched through the provider layer.

    The shared context leads so it can be cached: Anthropic gets an explicit
    cache_control breakpoint, OpenAI's automatic prefix caching picks up the
    same ordering. The persona's own system prompt follows, which keeps the
    cacheable prefix byte-identical across all three personas.
    """
    from src import llm
    from src.panel import PERSONAS

    search_tool = None
    if use_search:
        search_tool = {
            "type": WEB_SEARCH_TOOL,
            "name": "web_search",
            "max_uses": WEB_SEARCH_MAX_USES,
        }
    elif schema and llm.provider() == "openai":
        # OpenAI strict mode requires every property to be in `required`.
        schema = llm.json_schema_for_openai(schema)

    reply = llm.call(
        shared_block=shared_block,
        persona_system=PERSONAS[persona]["system"],
        user_msg=instructions,
        max_tokens=max_tokens,
        # Structured outputs are unusable alongside Anthropic web_search:
        # search forces citations on, and citations + output_config is a 400.
        schema=None if use_search else schema,
        search_tool=search_tool,
    )
    usage.add(reply)
    if reply.truncated:
        print(f"  !! {persona} hit the token cap — output may be truncated.")
    return reply.text


# ── R0: nominate ───────────────────────────────────────────────────────
def nominate(
    date_str: str, shared_block: str, usage: Usage, use_search: bool,
) -> dict[str, list[dict]]:
    today_pretty = datetime.strptime(date_str, "%Y-%m-%d").strftime(
        "%A %-m/%-d/%y",
    )
    search_clause = (
        ", or a line you pulled via web_search" if use_search else ""
    )
    price_clause = (
        " — search for a live price" if use_search
        else ". No live pricing is available in this run; leave "
        "american_odds null if no capper quoted one"
    )
    prompt = NOMINATE_PROMPT.format(
        today_pretty=today_pretty, n=NOMINATIONS_PER_PERSONA,
        num_picks=NUM_PICKS, min_types=MIN_DISTINCT_BET_TYPES,
        search_clause=search_clause, price_clause=price_clause,
    )

    def _one(name: str) -> tuple[list[dict], list[str]]:
        """One persona's nominations, plus its log lines. Touches nothing
        shared but `usage`, which is locked."""
        logs: list[str] = []
        text = _call(name, shared_block, prompt, usage, use_search)
        clean = [
            n for n in _parse_json_array(text)
            if n.get("matchup") and n.get("bet_type")
        ]
        if not use_search:
            # No search means no way to look a price up, so a quoted price
            # is either recalled from training or invented. Drop it and let
            # _inherit_odds pull a real capper quote from the DB (or fall
            # back to -110) — otherwise a backtest reports ROI on prices
            # that never existed.
            for n in clean:
                n["american_odds"] = None
        types = {(_norm(n.get("bet_type"))) for n in clean}
        if len(types) < MIN_DISTINCT_BET_TYPES:
            logs.append(
                f"    note: {name} spanned only {len(types)} bet type(s) "
                f"(asked for {MIN_DISTINCT_BET_TYPES})"
            )
        logs.append(f"    {len(clean)} nomination(s).")
        return clean, logs

    # The slowest calls in the pipeline: a search-enabled turn each, up to
    # WEB_SEARCH_MAX_USES lookups, and nothing any of them does depends on
    # another. Logs are buffered per persona and printed after the join —
    # `make morning`'s stdout is the only record of a run, and three
    # personas printing live interleaves it into nonsense.
    print(f"  {len(PERSONA_ORDER)} personas nominating in parallel...")
    out: dict[str, list[dict]] = {}
    for name, got, err in parallel.gather(_one, PERSONA_ORDER):
        print(f"  [{name}]")
        if err:
            print(f"    failed: {err}")
            out[name] = []
            continue
        clean, logs = got
        for line in logs:
            print(line)
        out[name] = clean
    return out


def is_excluded(c: dict) -> bool:
    """Bets the user won't place — dropped before they can take a slot."""
    return (c.get("stat") or "").strip().lower() in EXCLUDED_STATS


def annotate_pushes(conn, pool: list[dict], date_str: str) -> None:
    """Set c['push'] from favored sources that called the same bet.

    The personas see capper context but nominate in their own words, so the
    link back to a source has to be rebuilt by matching the candidate
    against that day's rows — same team/player token comparison the slip
    importer uses, so 'BAL' and 'Baltimore Orioles' count as one bet.
    """
    rows = conn.execute(
        "SELECT source_label, confidence, player_name, stat, line, side, "
        "bet_type, period, matchup FROM bets WHERE date=? "
        "AND source_label IN (%s)"
        % ",".join("?" * len(SOURCE_PUSH)),
        (date_str, *SOURCE_PUSH.keys()),
    ).fetchall()

    for c in pool:
        best, note = 0.0, None
        for r in rows:
            if (c.get("bet_type") or "") != (r["bet_type"] or ""):
                continue
            if (c.get("stat") or "") != (r["stat"] or ""):
                continue
            # A capper who says "Cardinals runline" without quoting a number
            # still called that bet — and the number is often missing because
            # fill_missing_lines couldn't reach ESPN. For ml/spread the side
            # already identifies the wager, so treat a null source line as a
            # wildcard. Totals and props are the number, so they stay strict.
            wildcard_line = (
                r["line"] is None
                and (r["bet_type"] or "") in ("ml", "spread")
            )
            if not wildcard_line and (c.get("line") or 0) != (r["line"] or 0):
                continue
            if (c.get("period") or "full") != (r["period"] or "full"):
                continue
            if not same_party(c.get("side"), r["side"]):
                continue
            if c.get("player_name") and r["player_name"]:
                if not same_party(c["player_name"], r["player_name"]):
                    continue
            if not same_party(c.get("matchup"), r["matchup"]):
                continue
            tiers = SOURCE_PUSH.get(r["source_label"], {})
            factor = tiers.get(r["confidence"] or "", tiers.get("*", 0.0))
            if factor > best:
                best = factor
                note = (
                    f"{r['source_label']}"
                    f"{' ' + r['confidence'] if r['confidence'] else ''}"
                )
        c["push"] = best
        c["push_note"] = note


def build_pool(nominations: dict[str, list[dict]]) -> list[dict]:
    """Dedupe nominations into an id'd candidate pool."""
    pool: dict[tuple, dict] = {}
    for persona, noms in nominations.items():
        for n in noms:
            # Every path into the pool goes through here, so this is the one
            # place normalization has to happen for dedup to be sound.
            n = normalize_candidate(n)
            if is_excluded(n):
                continue
            k = candidate_key(n)
            c = pool.get(k)
            if c is None:
                c = {
                    "key": k,
                    "matchup": n.get("matchup"),
                    "player_name": n.get("player_name"),
                    "stat": n.get("stat"),
                    "line": n.get("line"),
                    "side": n.get("side"),
                    "bet_type": n.get("bet_type"),
                    "period": n.get("period") or "full",
                    "american_odds": n.get("american_odds"),
                    "sport": "mlb",
                    "nominators": [],
                    "theses": [],
                }
                pool[k] = c
            c["nominators"].append(persona)
            if n.get("thesis"):
                c["theses"].append(f"{persona}: {n['thesis']}")
            if n.get("american_odds"):
                c["american_odds"] = _worst_odds(
                    c["american_odds"], n["american_odds"],
                )
    ordered = sorted(
        pool.values(), key=lambda c: (c["matchup"] or "", c["key"]),
    )
    for i, c in enumerate(ordered, 1):
        c["id"] = f"C{i:02d}"
    return ordered


def _pool_block(pool: list[dict], seed: str) -> str:
    """Candidates in date-seeded random order — position carries no signal."""
    shown = list(pool)
    random.Random(seed).shuffle(shown)
    lines = []
    for c in shown:
        nom = ", ".join(c["nominators"])
        lines.append(
            f"[{c['id']}] {c['matchup']} — {_bet_description(c)}"
            + (f" ({c['american_odds']:+d})" if c.get("american_odds") else "")
            + f"  [nominated by: {nom}]"
        )
        for t in c["theses"]:
            lines.append(f"    {t}")
    return "\n".join(lines)


# ── R1/R2: debate ──────────────────────────────────────────────────────
def collect_ballots(
    date_str: str, shared_block: str, prompt: str, usage: Usage,
) -> dict[str, dict[str, dict]]:
    """Return {persona: {candidate_id: ballot}}."""

    def _one(name: str) -> tuple[dict[str, dict], list[str]]:
        text = _call(
            name, shared_block, prompt, usage,
            use_search=False, max_tokens=5000, schema=BALLOT_SCHEMA,
        )
        data = json.loads(text)
        rows = data["ballots"] if isinstance(data, dict) else data
        scored = {
            r["id"]: r for r in rows if isinstance(r, dict) and r.get("id")
        }
        n_veto = sum(
            1 for r in scored.values()
            if r.get("veto") and (r.get("veto_reason") or "").strip()
        )
        return scored, [f"    {len(scored)} scored, {n_veto} veto(es)."]

    # Called once for R1 and again for R2, so this fan-out is worth up to
    # six serial calls over a contested day.
    print(f"  {len(PERSONA_ORDER)} personas scoring in parallel...")
    ballots: dict[str, dict[str, dict]] = {}
    for name, got, err in parallel.gather(_one, PERSONA_ORDER):
        print(f"  [{name}]")
        if err:
            print(f"    failed: {err}")
            ballots[name] = {}
            continue
        scored, logs = got
        for line in logs:
            print(line)
        ballots[name] = scored
    return ballots


def tally(
    pool: list[dict], ballots: dict[str, dict[str, dict]],
) -> list[dict]:
    """Score, apply veto rules, rank. Pure Python — no model judgement."""
    rows = []
    for c in pool:
        scores, vetoes, reasons = [], [], []
        for persona in PERSONA_ORDER:
            b = ballots.get(persona, {}).get(c["id"])
            if not b:
                continue
            try:
                scores.append(float(b.get("score", 0)))
            except (TypeError, ValueError):
                continue
            reasons.append(
                f"{persona} ({b.get('score')}): {b.get('reason', '')}"
            )
            # A veto without a stated reason is not a veto.
            if b.get("veto") and (b.get("veto_reason") or "").strip():
                vetoes.append(f"{persona}: {b['veto_reason']}")
        mean = sum(scores) / len(scores) if scores else 0.0
        push = PUSH_WEIGHT * float(c.get("push") or 0.0)
        rows.append({
            **c,
            "scores": scores,
            "mean": mean,
            "adjusted": (
                mean + push - (VETO_PENALTY if len(vetoes) == 1 else 0.0)
            ),
            "vetoes": vetoes,
            "n_vetoes": len(vetoes),
            "reasons": reasons,
        })

    survivors = [r for r in rows if r["n_vetoes"] < VETO_ELIMINATION]
    # Only enforce elimination while enough candidates remain to fill a card.
    if len(survivors) >= NUM_PICKS:
        for r in rows:
            r["eliminated"] = r["n_vetoes"] >= VETO_ELIMINATION
    else:
        for r in rows:
            r["eliminated"] = False

    rows.sort(
        key=lambda r: (r["eliminated"], -r["adjusted"], -r["mean"], r["id"]),
    )
    return rows


def eligible_ranking(ranked: list[dict]) -> list[dict]:
    """Ranked candidates that can actually reach the card.

    Applies the one-per-matchup rule greedily. Everything downstream — the
    card, the convergence gap, the contested bubble — must read this list
    rather than the raw ranking, or it measures against candidates the
    matchup constraint has already excluded.
    """
    out: list[dict] = []
    per_matchup: dict[str, int] = {}
    for r in ranked:
        if r["eliminated"]:
            continue
        m = (r["matchup"] or "").lower()
        if per_matchup.get(m, 0) >= MAX_PER_MATCHUP:
            continue
        out.append(r)
        per_matchup[m] = per_matchup.get(m, 0) + 1
    return out


def converged(ranked: list[dict]) -> tuple[bool, str]:
    live = eligible_ranking(ranked)
    if len(live) <= NUM_PICKS:
        return True, "pool is at or below card size"
    gap = live[NUM_PICKS - 1]["adjusted"] - live[NUM_PICKS]["adjusted"]
    if gap < CONVERGENCE_GAP:
        return False, (
            f"#{NUM_PICKS} leads #{NUM_PICKS + 1} by only {gap:.2f} "
            f"(need {CONVERGENCE_GAP})"
        )
    vetoed = [r["id"] for r in live[:NUM_PICKS] if r["n_vetoes"]]
    if vetoed:
        return False, f"veto still standing in the top {NUM_PICKS}: {vetoed}"
    return True, f"clear top {NUM_PICKS} (gap {gap:.2f}), no vetoes"


def contested_ids(ranked: list[dict]) -> list[str]:
    """The bubble: anything that could still swap in or out of the card."""
    live = eligible_ranking(ranked)
    lo = max(0, NUM_PICKS - 2)
    hi = min(len(live), NUM_PICKS + 4)
    ids = {r["id"] for r in live[lo:hi]}
    ids |= {r["id"] for r in live[:NUM_PICKS] if r["n_vetoes"]}
    return [r["id"] for r in live if r["id"] in ids]


def _contested_block(ranked: list[dict], ids: list[str]) -> str:
    by_id = {r["id"]: r for r in ranked}
    lines = []
    for cid in ids:
        r = by_id[cid]
        lines.append(
            f"[{r['id']}] {r['matchup']} — {_bet_description(r)}  "
            f"(round-1 mean {r['mean']:.1f})"
        )
        for reason in r["reasons"]:
            lines.append(f"    {reason}")
        for v in r["vetoes"]:
            lines.append(f"    VETO — {v}")
    return "\n".join(lines)


def merge_ballots(
    base: dict[str, dict[str, dict]], update: dict[str, dict[str, dict]],
) -> dict[str, dict[str, dict]]:
    """R2 re-scores only contested ids; everything else carries over."""
    merged = {p: dict(b) for p, b in base.items()}
    for persona, rows in update.items():
        merged.setdefault(persona, {}).update(rows)
    return merged


def tier_for(rank: int) -> str:
    """Confidence tier from card rank (see STAKE_BY_RANK_CENTS)."""
    return TIER_BY_RANK.get(rank, "LEAN")


# ── persistence ────────────────────────────────────────────────────────
def _inherit_odds(
    conn: sqlite3.Connection, date_str: str, pick: dict, label: str,
) -> int | None:
    row = conn.execute(
        "SELECT american_odds FROM bets "
        "WHERE date=? AND source_label != ? AND american_odds IS NOT NULL "
        "AND sport=? "
        "AND COALESCE(matchup,'')=COALESCE(?, '') "
        "AND COALESCE(player_name,'')=COALESCE(?, '') "
        "AND COALESCE(stat,'')=COALESCE(?, '') "
        "AND COALESCE(side,'')=COALESCE(?, '') "
        "AND (line IS ? OR line=?) "
        "AND bet_type=? AND COALESCE(period,'full')=? "
        "ORDER BY id LIMIT 1",
        (
            date_str, label, pick.get("sport"),
            pick.get("matchup"), pick.get("player_name"),
            pick.get("stat"), pick.get("side"),
            pick.get("line"), pick.get("line"),
            pick.get("bet_type"), pick.get("period") or "full",
        ),
    ).fetchone()
    return row["american_odds"] if row else None


def market_odds_for(market: list[dict], pick: dict) -> int | None:
    """The live book price for a pick, or None if the book has no such bet.

    Only game lines are covered — ESPN publishes moneyline, runline and
    total, and nothing at player-prop level. A prop returns None and keeps
    whatever price it came in with, flagged unverified.
    """
    if (pick.get("period") or "full") != "full":
        return None
    if pick.get("bet_type") in ("prop", "combo"):
        # ESPN has no prop coverage; Kalshi's exchange book is the only
        # free reference. Its midpoint is fair value, which is what should
        # drive a stake — the ask is what a taker pays and overstates cost.
        try:
            from src import kalshi
            got = kalshi.price_prop(
                pick.get("player_name"), pick.get("stat"),
                pick.get("line"), pick.get("side"),
            )
        except Exception:
            return None
        if got and got.get("usable") and got.get("mid_american") is not None:
            return got["mid_american"]
        return None
    if pick.get("bet_type") not in ("ml", "spread", "total"):
        return None
    game = None
    for g in market:
        if same_party(g["away_team"], pick.get("matchup") or "") and \
                same_party(g["home_team"], pick.get("matchup") or ""):
            game = g
            break
    if not game:
        return None

    side = pick.get("side") or ""
    if pick["bet_type"] == "total":
        leg = game["total"]["over" if side.lower() == "over" else "under"]
    else:
        key = "home" if same_party(game["home_team"], side) else "away"
        if not same_party(game["home_team"], side) and \
                not same_party(game["away_team"], side):
            return None
        leg = game["ml" if pick["bet_type"] == "ml" else "runline"][key]

    # A price only applies to the number it was quoted at. If the book has
    # moved off the pick's line, treat it as unpriced rather than pretend.
    if pick["bet_type"] != "ml" and leg.get("line") != pick.get("line"):
        return None
    return leg.get("odds")


def net_payout(american: int) -> float:
    """Profit per 1 unit risked. -110 -> 0.909, +150 -> 1.5."""
    return american / 100.0 if american > 0 else 100.0 / abs(american)


def price_factor(american: int | None) -> float:
    """Stake multiplier for a price, relative to -110.

    Returns 0.0 when the price is past PRICE_PASS_THRESHOLD, meaning the
    bet should not be placed at all.
    """
    if american is None:
        return 1.0
    if american < 0 and american <= PRICE_PASS_THRESHOLD:
        return 0.0
    f = net_payout(american) / net_payout(PRICE_REF_ODDS)
    return max(PRICE_FACTOR_FLOOR, min(PRICE_FACTOR_CAP, f))


def _round_units(u: float) -> float:
    return round(u / UNIT_INCREMENT) * UNIT_INCREMENT


def resolve_price(
    conn: sqlite3.Connection, date_str: str, pick: dict, label: str,
    market: list[dict] | None = None,
) -> int:
    """Settle one pick's price and record where the number came from.

    Split out of assign_stakes so the card can be filled with real prices
    already in hand — a bet the book has moved out of range has to lose its
    slot to the next candidate, which is impossible when pricing happens
    after selection. When `market` is supplied a game-line pick's odds are
    overwritten with the live book price; a model-supplied number is never
    trusted for something we can look up.
    """
    # Never reprice a game in progress: a live book is not a line, and the
    # stake would be sized off a number that no longer exists.
    from src.context import gamestate
    live_ok = gamestate.is_pregame(pick.get("matchup"), date_str)
    real = market_odds_for(market, pick) if (market and live_ok) else None
    if real is not None:
        pick["quoted_odds"] = pick.get("american_odds")
        pick["american_odds"] = real
        pick["odds_source"] = "market"
    elif pick.get("american_odds") is None:
        pick["american_odds"] = (
            _inherit_odds(conn, date_str, pick, label) or DEFAULT_ODDS
        )
        pick["odds_source"] = "inherited"
    else:
        pick["odds_source"] = "unverified"
    return pick["american_odds"]


def is_unplayable(odds: int | None) -> bool:
    """True for a price too short to bet at any conviction.

    Applied to every pick regardless of where its price came from. The old
    guard lived inside assign_stakes behind `odds_source == "market"`, so an
    inherited or model-quoted -300 drew a full stake untouched — the one
    -376 that reached a card was caught only because Kalshi happened to
    carry that prop.
    """
    return odds is not None and odds <= PRICE_PASS_THRESHOLD


def fill_card(
    conn: sqlite3.Connection, date_str: str, ranked: list[dict], label: str,
    market: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Fill the card from the ranking, pricing each candidate as it is taken.

    Returns (card, passed). A candidate rejected on price does NOT consume
    its matchup slot, so another bet from the same game can still be picked.

    Selection has to know the real price. On 8/22 the personas debated Ryan
    Weathers k under 5.5 at the -130 they were quoted and the book had it at
    -376; repricing after the card was already chosen left that bet sitting
    at rank 5 with a $0 stake. A slot spent on a bet nobody will place is
    worse than a four-bet card, and worse still than the bet ranked #6.
    """
    card: list[dict] = []
    passed: list[dict] = []
    per_matchup: dict[str, int] = {}
    for r in ranked:
        if len(card) >= NUM_PICKS:
            break
        if r["eliminated"]:
            continue
        m = (r["matchup"] or "").lower()
        if per_matchup.get(m, 0) >= MAX_PER_MATCHUP:
            continue
        if is_unplayable(resolve_price(conn, date_str, r, label, market)):
            passed.append(r)
            continue
        card.append(r)
        per_matchup[m] = per_matchup.get(m, 0) + 1
    return card, passed


def assign_stakes(picks: list[dict]) -> None:
    """Rank sets conviction, the resolved price scales it.

    `picks` must be in consensus order and must already have been through
    resolve_price() — fill_card() does that.
    """
    for rank, p in enumerate(picks, 1):
        p["rank"] = rank
        p["confidence"] = TIER_BY_RANK.get(rank, "LEAN")
        base = BASE_UNITS_BY_RANK.get(rank, FALLBACK_UNITS)
        # Only size off a price we can stand behind. An unverified quote is
        # exactly the number that has been wrong by 200+ points, so letting
        # it inflate a stake would compound the error rather than hedge it.
        factor = (
            price_factor(p["american_odds"])
            if p["odds_source"] == "market" else 1.0
        )
        units = 0.0 if factor == 0.0 else max(
            UNIT_INCREMENT, _round_units(base * factor),
        )
        p["base_units"] = base
        p["price_factor"] = factor
        p["units"] = units
        p["stake_cents"] = int(round(units * UNIT_CENTS))


def reset_recommendations(
    date_str: str, label: str = RECOMMENDER_LABEL,
) -> int:
    """Clear a date's card so it can be rebuilt.

    Rows the user has actually bet are kept. my_bets.bet_id is ON DELETE
    CASCADE, so deleting a card row silently destroyed the record of a real
    wager — stake, price and all. Rebuilding the card must never be able to
    erase money that was already put down.
    """
    with db.connect() as conn:
        cur = conn.execute(
            "DELETE FROM bets WHERE date=? AND source_label=? "
            "AND id NOT IN (SELECT bet_id FROM my_bets)",
            (date_str, label),
        )
        return cur.rowcount


# ── rendering ──────────────────────────────────────────────────────────
def render_markdown(
    date_str: str, picks: list[dict], ranked: list[dict],
    nominations: dict[str, list[dict]], rounds_run: int,
    converge_note: str, usage: Usage,
    passed: list[dict] | None = None,
) -> str:
    pretty = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A %-m/%-d/%y")
    L = [f"# Consensus Card — {pretty}", ""]
    if not picks:
        L.append("_(no picks — pool was empty)_")
        return "\n".join(L)

    band = {1: "conviction", 2: "conviction", 3: "lean", 4: "lean",
            5: "straggler"}
    for i, p in enumerate(picks, 1):
        L.append(
            f"## {i}. {_bet_description(p)} [{p['confidence']}] "
            f"— consensus {p['adjusted']:.1f}/10"
        )
        L.append(f"- Matchup: {p.get('matchup') or ''}")
        L.append(
            f"- Stake: ${p.get('stake_cents', 0) / 100:.2f} "
            f"({band.get(i, 'straggler')})"
        )
        odds = p.get("american_odds")
        L.append(f"- Price: {odds:+d}" if odds else "- Price: n/a")
        L.append(f"- Nominated by: {', '.join(p['nominators'])}")
        for reason in p["reasons"]:
            L.append(f"- {reason}")
        for v in p["vetoes"]:
            L.append(f"- **Veto (overruled):** {v}")
        L.append("")

    L += ["---", "", "## Deliberation", ""]
    L.append(f"Rounds run: {rounds_run} (max {MAX_DEBATE_ROUNDS}). "
             f"Close: {converge_note}.")
    L.append("")
    L.append("### Nominations")
    for persona in PERSONA_ORDER:
        noms = nominations.get(persona, [])
        L.append(f"- **{persona}** ({len(noms)}): " + "; ".join(
            _bet_description(n) for n in noms
        ) if noms else f"- **{persona}**: _(none)_")
    L.append("")
    L.append("### Scoreboard")
    L.append("")
    L.append("| # | id | bet | matchup | mean | adj | vetoes | on card |")
    L.append("|---|----|-----|---------|------|-----|--------|---------|")
    on_card = {p["id"] for p in picks}
    passed_ids = {p["id"] for p in (passed or [])}
    for i, r in enumerate(ranked, 1):
        flag = "✓" if r["id"] in on_card else (
            "eliminated" if r["eliminated"]
            else "passed (price)" if r["id"] in passed_ids
            else ""
        )
        L.append(
            f"| {i} | {r['id']} | {_bet_description(r)} | "
            f"{r.get('matchup') or ''} | {r['mean']:.1f} | "
            f"{r['adjusted']:.1f} | {r['n_vetoes']} | {flag} |"
        )
    L.append("")
    if passed:
        L.append("### Passed on price")
        L.append("")
        L.append(
            f"Ranked high enough to make the card but priced past "
            f"{PRICE_PASS_THRESHOLD:+d}, so the slot went to the next "
            f"candidate instead."
        )
        L.append("")
        for r in passed:
            quoted = r.get("quoted_odds")
            was = f", quoted {quoted:+d}" if quoted is not None else ""
            L.append(
                f"- `{r['id']}` {_bet_description(r)} — "
                f"{r['american_odds']:+d}{was} ({r.get('odds_source', '?')})"
            )
        L.append("")

    vetoed = [r for r in ranked if r["vetoes"]]
    if vetoed:
        L.append("### Vetoes")
        for r in vetoed:
            for v in r["vetoes"]:
                L.append(f"- `{r['id']}` {_bet_description(r)} — {v}")
        L.append("")
    L.append(f"_Usage: {usage.summary()}_")
    return "\n".join(L)


# ── orchestration ──────────────────────────────────────────────────────
def run(
    date_str: str | None = None,
    label: str = RECOMMENDER_LABEL,
    use_search: bool = True,
    as_of: bool = False,
    write_markdown: bool = True,
    md_path: Path | None = None,
) -> dict:
    """Run the consensus flow for one date. Returns a result summary."""
    db.init()
    d = date.fromisoformat(date_str) if date_str else date.today()
    date_key = d.isoformat()
    usage = Usage()

    if not as_of:
        try:
            with db.connect() as conn:
                cache_day(conn, date_key)
        except Exception as e:
            print(f"Schedule pre-cache failed: {e}")

    print(f"Building context for {date_key}"
          f"{' (as-of mode)' if as_of else ''}...")
    shared_block, slate, capper_bets = build_context(date_key, as_of=as_of)
    print(f"  {len(slate)} game(s), {len(capper_bets)} capper bet(s), "
          f"{len(shared_block):,} chars of context.")
    if not slate:
        print("No games. Exiting.")
        return {"date": date_key, "picks": [], "usage": usage}

    print("\nR0 — nominate")
    nominations = nominate(date_key, shared_block, usage, use_search)
    pool = build_pool(nominations)
    print(f"  Pool: {len(pool)} distinct candidate(s).")
    if not pool:
        print("Empty pool. Exiting.")
        return {"date": date_key, "picks": [], "usage": usage}

    with db.connect() as conn:
        annotate_pushes(conn, pool, date_key)
    pushed = [c for c in pool if c.get("push")]
    if pushed:
        print(f"  Source push on {len(pushed)} candidate(s):")
        for c in sorted(pushed, key=lambda x: -x["push"]):
            print(f"    +{c['push'] * PUSH_WEIGHT:.2f}  "
                  f"{_bet_description(c)}  ({c['push_note']})")

    pretty = d.strftime("%A %-m/%-d/%y")
    print("\nR1 — debate")
    ballots = collect_ballots(
        date_key, shared_block,
        DEBATE_PROMPT.format(
            today_pretty=pretty, num_picks=NUM_PICKS,
            pool_block=_pool_block(pool, date_key),
        ),
        usage,
    )
    ranked = tally(pool, ballots)
    ok, note = converged(ranked)
    rounds_run = 1
    print(f"  Converged: {ok} — {note}")

    if not ok and MAX_DEBATE_ROUNDS >= 2:
        ids = contested_ids(ranked)
        print(f"\nR2 — rebuttal on {len(ids)} contested candidate(s)")
        update = collect_ballots(
            date_key, shared_block,
            REBUTTAL_PROMPT.format(
                today_pretty=pretty,
                contested_block=_contested_block(ranked, ids),
            ),
            usage,
        )
        ballots = merge_ballots(ballots, update)
        ranked = tally(pool, ballots)
        rounds_run = 2
        _, note = converged(ranked)
        note = f"forced close after R2 ({note})"

    # Reprice off the live book BEFORE the card is chosen — a price the book
    # has moved out of range must cost the bet its slot, not just its stake.
    # In as_of (backtest) mode there is no point-in-time market, so picks
    # keep whatever they had.
    market = None
    if not as_of:
        try:
            market = fetch_mlb_market(date_key)
        except Exception as e:
            print(f"  Market fetch failed, keeping quoted odds: {e}")
    with db.connect() as conn:
        picks, passed = fill_card(conn, date_key, ranked, label, market)

    if passed:
        print(f"\nPassed on {len(passed)} candidate(s) — price past "
              f"{PRICE_PASS_THRESHOLD:+d}:")
        for p in passed:
            quoted = p.get("quoted_odds")
            was = f" (quoted {quoted:+d})" if quoted is not None else ""
            print(f"    {p['american_odds']:+5d}{was}  "
                  f"{p['matchup']} — {_bet_description(p)}")

    assign_stakes(picks)
    for p in picks:
        # Cap is a sanity bound, not a display limit — three personas run
        # ~850 chars total, so this should never bite. The email renders
        # each persona's reason on its own line, untruncated.
        p["rationale"] = " | ".join(p["reasons"])[:4000]

    deleted = reset_recommendations(date_key, label)
    if deleted:
        print(f"Cleared {deleted} prior row(s) for {label}.")

    repriced = [p for p in picks if p.get("quoted_odds") is not None
                and p["quoted_odds"] != p["american_odds"]]
    if repriced:
        print(f"\nRepriced {len(repriced)} pick(s) off the book:")
        for p in repriced:
            print(f"    {_bet_description(p)}: quoted "
                  f"{p['quoted_odds']:+d} -> actual {p['american_odds']:+d}")

    print(f"\nCard: {len(picks)} pick(s).")
    for p in picks:
        src = {"market": "", "inherited": " ~", "unverified": " ?"}.get(
            p.get("odds_source", ""), "")
        print(
            f"  #{p['rank']} [{p['confidence']:<4}] "
            f"{p['units']:>4.2f}u  {p['american_odds']:+5d}{src:<2}  "
            f"{p['adjusted']:.1f}  "
            f"{p['matchup']} — {_bet_description(p)}"
        )

    from src.main import persist_bets
    n = persist_bets(date_key, label, f"consensus:{date_key}", picks)
    print(f"Persisted {n} pick(s) under '{label}'.")

    if write_markdown:
        md = render_markdown(
            date_key, picks, ranked, nominations, rounds_run, note, usage,
            passed=passed,
        )
        out = md_path or (
            BETS_DIR / f"{d.strftime('%Y_%m_%d')}_recommend.md"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md)
        print(f"Wrote {out}")

    print(f"\nUsage: {usage.summary()}")
    return {
        "date": date_key, "picks": picks, "ranked": ranked,
        "rounds": rounds_run, "usage": usage,
    }


if __name__ == "__main__":
    import sys
    # Flags have to come out before positional parsing or '--email' lands in
    # args[0] and gets read as the date.
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    want_email = "--email" in sys.argv
    if args and args[0] == "reset":
        target = args[1] if len(args) > 1 else date.today().isoformat()
        print(f"Deleted {reset_recommendations(target)} row(s) for {target}")
    else:
        target = args[0] if args else None
        run(target)
        if want_email:
            # Rebuilding the card by hand and then not mailing it was the
            # gap: the new card sat in the DB while the inbox still held the
            # old one. if_needed=False because a deliberate rebuild is
            # exactly the case where the digest should go again.
            print("\n=== email ===")
            from src import emailer
            emailer.run(target or date.today().isoformat(), if_needed=False)
