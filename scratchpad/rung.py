"""Audit ONE rung of the board against ONE price you can actually get.

    venv/bin/python -m scratchpad.rung 2026-09-24 "Singer k 3.5" under +106
    venv/bin/python -m scratchpad.rung 2026-09-24 "KC total 3.5"  over -136
    venv/bin/python -m scratchpad.rung 2026-09-24 "CWS@KC total 8.5" over -120

Read-only, and it NEVER re-simulates. The board .txt is the artefact of
record and its 20,000 draws cost real time, so this reads the JSON that
was parsed from it — the same discipline as `board_json`. A second engine
call would let this and the board disagree on seed alone.

WHAT BOUGHT THIS. Five rungs were audited by hand on 2026-09-24, one per
question, with slightly different ad-hoc SQL each time. Three of the five
turned on the same variable (batters faced, which is on none of our
tables as a board column) and one of the hand queries crashed on a TEXT
column. That is the fourth-inning and 60-85-pitch failure again: one
question asked five ways, five chances to ask it differently.

The sections, in the order the question actually gets asked:

  PRICE     your price -> breakeven, and the edge against OUR number.
            BETTING.md's first reading rule: the board's edge column is
            measured against the Kalshi MID, which is not a number
            anybody can bet. What you keep is `our probability minus the
            breakeven of the price you got`.
  TILT      the slate's mean gap in THIS market class, and what is left
            of the edge once it is removed. A uniform one-way gap is our
            level far more often than it is an edge (BETTING.md rule 4),
            and the tilt moves day to day, so it is recomputed per board.
  ROLE      season start share against career, and the last five starts'
            outs. `slate.priceable` counts the WHOLE four-season cache,
            so a converted reliever reads as a swingman forever — and a
            September role change is invisible to a season share either
            way. Leahy was 29-for-29 starts and on a three-inning leash.
  DRIFT     the rate the simulator was handed against what he has
            ACTUALLY done, in windows, with a LAYOFF split when there is
            one. Pivetta was priced .2758 with a September of .2037;
            Sandlin .2278 with a September of .2308. Same THIN flag,
            opposite verdicts, and only this table separates them.
  WORKLOAD  batters faced per start, COUNTED. Decisive in three of the
            five questions and absent from the board: a strikeout prop
            pays on batters, not innings, and a traffic pitcher faces 24
            of them in a 10-out start.
  SCENARIOS P(side) across that workload range and those rates, with the
            breakeven marked.

The scenario grid is BINOMIAL — no hook, no TTO decay, no base-out state
— so expect it a few points off the board. When it is far off, that is
the finding, not a defect in the grid: `implied` in the WORKLOAD block
backs out the flat per-PA rate that would reproduce the board's own
number at his usual workload, and a big gap between `implied` and every
row of DRIFT means the sim's workload or its TTO decay is carrying the
difference, not its rate.

NOTHING HERE IS FITTED AND NOTHING HERE RECOMMENDS. Every row is either
read off the board or counted on this league; the operator makes the
call. See BETTING.md for what each market is worth.
"""
from __future__ import annotations

import math
import sys

from scratchpad import board_json, boards
from src.context import arm, store

#: A gap this long between starts is a layoff, and the rate on the far
#: side of it gets its own DRIFT row. Pivetta's was 148 days and his
#: strikeout rate came back 27% lower; a window that averages across it
#: prices the pitcher who left, not the one who returned.
LAYOFF_DAYS = 30

#: Off-band rungs are excluded from the tilt. They sit outside the board's
#: +/-170 print band, where probabilities are extreme and a gap in POINTS
#: compresses toward zero — including them drags the slate mean toward
#: nothing and understates the correction.
TILT_EXCLUDES_OFFBAND = True


# ------------------------------------------------------------ selection

def candidates(board: dict, selector: str) -> list[tuple[dict, dict]]:
    """Every (game, row) whose 'AWY@HOM bet' contains `selector`.

    Case-blind, and whitespace in the selector is collapsed so
    'CWS@KC total 8.5' and 'cws @ kc  total 8.5' find the same rung.

    AN EXACT MATCH ON THE BET WINS OVER ANY NUMBER OF SUBSTRING MATCHES,
    the same rule `arm.resolve_name` uses for names. Without it every
    WHOLE-NUMBER total is unaskable: 'total 9' is a substring of
    'total 9.5', so the one rung a book prints as a push could never be
    named — and those are exactly the rungs an operator asks about,
    because a push is a free roll.
    """
    want = " ".join(selector.lower().split())
    out, exact = [], []
    for g in board["games"]:
        for r in g["rows"]:
            bet = r["bet"].lower()
            hay = f"{g['away']}@{g['home']} {bet}".lower()
            if want in hay:
                out.append((g, r))
            if want in (bet, hay):
                exact.append((g, r))
    return exact or out


def resolve(board: dict, selector: str):
    """(game, row) or None — NEVER a guess when several rungs match.

    Same rule as `arm.resolve_name`: convenience that cannot be wrong.
    'Singer k 3' matches k 3.5 and k 3.5's neighbours on some boards, and
    silently auditing the wrong rung is worse than asking again.
    """
    hits = candidates(board, selector)
    return hits[0] if len(hits) == 1 else None


# ------------------------------------------------------------- the maths

def breakeven(price: str) -> float:
    """American odds -> the win rate that makes the bet break even.

    Deliberately `board_json.prob`, not a second copy: the board's own
    parser turns a price into a probability and two implementations of
    one formula is how they come to disagree about -100.
    """
    return board_json.prob(price)


def side_prob(row: dict, side: str) -> float:
    """OUR probability for the side being bet.

    `p_over` is push-adjusted where the board printed an integer total —
    `board_json` prices those as P(cover) / (P(cover) + P(miss)) — so the
    complement is the correct push-adjusted under and needs no second
    correction here.
    """
    p = row["p_over"]
    return p if side == "over" else 1.0 - p


def tilt(board: dict, cls: str) -> tuple[float, int]:
    """(mean gap in points on the OVER, n) for one market class.

    The rung under audit is included. With 20 to 112 rungs in a class its
    own contribution is smaller than the rounding, and excluding it would
    make the correction depend on which rung was asked about.
    """
    gaps = [r["gap"] for g in board["games"] for r in g["rows"]
            if r["cls"] == cls and r["gap"] is not None
            and not (TILT_EXCLUDES_OFFBAND and r["offband"])]
    return (sum(gaps) / len(gaps) if gaps else 0.0), len(gaps)


def binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k), inclusive. `arm`'s, so an off-by-one cannot differ."""
    return arm._binom_cdf(k, n, p)


def p_over_line(n: int, rate: float, line: float) -> float:
    """P(count > line) at n trials, for a HALF-POINT line.

    Raises on an integer line rather than guessing. A whole number is a
    PUSH on every book that prints one, and `floor` would silently price
    'over 4' as P(X >= 5) on one reading and P(X > 4) on another — the
    same off-by-one that `arm`'s cdf check guards, one layer up.
    """
    if abs(line - math.floor(line) - 0.5) > 1e-9:
        raise ValueError(f"line {line} is not a half-point line")
    return 1.0 - binom_cdf(int(math.floor(line)), n, rate)


def implied_rate(p_over: float, n: int, line: float) -> float | None:
    """The flat per-PA rate reproducing `p_over` at n batters.

    A DIAGNOSTIC, not a measurement: the board draws a distribution over
    batters faced and decays the rate by times-through-the-order, and
    this collapses both into one number. Read it only against the DRIFT
    rows — far from all of them means the sim's workload or its TTO decay
    is doing the work, which is the one question the board cannot answer
    about itself.
    """
    if not 0.0 < p_over < 1.0 or n <= 0:
        return None
    lo, hi = 1e-6, 0.999
    if p_over_line(n, hi, line) < p_over:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if p_over_line(n, mid, line) < p_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def wilson_se(hits: int, n: int) -> float:
    """Plain binomial se of a rate. Zero n reads as zero, not a crash."""
    if not n:
        return 0.0
    p = hits / n
    return math.sqrt(max(p * (1 - p), 0.0) / n)


# ------------------------------------------------------------- the data

def starts(con, pid: int) -> list[dict]:
    """One row per START, oldest first, with COUNTED batters faced.

    `mlb_stints.batters` is counted off the play-by-play. The boxscore
    alternative — outs + hits + walks, which `arm.game_log` uses because
    it has no stints join — misses hit batsmen and men who reached on an
    error, and ran up to 3 batters light on a single 2026 start (0.6% of
    league PA, but the error is per-start and signed). Batters faced is
    the variable three of the five hand audits turned on, so it is the
    counted one here.

    `sport = 'mlb'` because gametype.py relabels spring training and
    every query has to say so or it re-admits March.
    """
    rows = con.execute(
        "select s.date d, s.batters bf, s.outs_recorded o,"
        "       p.k, p.pitches pc"
        " from mlb_stints s"
        " join bets.games g on g.game_id = s.game_id"
        " join bets.mlb_pitching p on p.game_id = s.game_id"
        "      and p.player_name = s.player_name"
        " where s.pitcher_id = ? and s.appearance_order = 0"
        "   and g.sport = 'mlb'"
        " order by s.date", (pid,)).fetchall()
    return [dict(d=r["d"], bf=r["bf"], o=r["o"], k=r["k"], pc=r["pc"])
            for r in rows]


def layoff_split(log: list[dict]) -> int | None:
    """Index of the first start after a gap of >= LAYOFF_DAYS, or None."""
    from datetime import date as _d
    for i in range(1, len(log)):
        a = _d.fromisoformat(log[i - 1]["d"])
        b = _d.fromisoformat(log[i]["d"])
        if (b - a).days >= LAYOFF_DAYS:
            return i
    return None


def windows(log: list[dict]) -> list[tuple[str, list[dict]]]:
    """The DRIFT windows, widest first, skipping ones that repeat.

    Starts-based rather than date-based on purpose: a starts window
    survives a layoff, and a 30-day window silently becomes a one-start
    window for anybody who missed a month.
    """
    out: list[tuple[str, list[dict]]] = [("season", log)]
    for n in (10, 5, 3):
        if len(log) > n:
            out.append((f"last {n} starts", log[-n:]))
    i = layoff_split(log)
    if i is not None and i < len(log):
        gap = (_days(log[i - 1]["d"], log[i]["d"]))
        out.append((f"since {gap}d layoff", log[i:]))
    # De-dupe on the ROW SET, keeping the LAST label for a set rather
    # than the first: a layoff window that happens to equal 'last 3
    # starts' is the same three starts under a name that says WHY they
    # are the interesting three. Pivetta's post-layoff window was exactly
    # his last three, so first-wins hid the layoff entirely.
    keyed: dict[tuple, tuple[str, list[dict]]] = {}
    for lab, rows in out:
        if rows:
            keyed[tuple(r["d"] for r in rows)] = (lab, rows)
    return list(keyed.values())


def _days(a: str, b: str) -> int:
    from datetime import date as _d
    return (_d.fromisoformat(b) - _d.fromisoformat(a)).days


def team_runs(con, abbr: str, since: str, f5: bool = False) -> dict:
    """Runs SCORED by a club, split all/home/last-30, plus allowed.

    Every row keys on `sport = 'mlb'` and on the ABBR columns, because
    `home_team` carries the full name and 'D-backs' against 'Arizona
    Diamondbacks' has already cost this project four fields.
    """
    sc, sa = ("home_score_f5", "away_score_f5") if f5 else \
             ("home_score", "away_score")
    rows = con.execute(
        f" select g.date d, g.home_team_abbr h, g.away_team_abbr a,"
        f"        g.{sc} hs, g.{sa} as_"
        f"  from bets.games g"
        f"  where g.sport = 'mlb' and g.date >= ? and g.{sc} is not null"
        f"    and (g.home_team_abbr = ? or g.away_team_abbr = ?)"
        f"  order by g.date", (since, abbr, abbr)).fetchall()
    scored = [(r["hs"] if r["h"] == abbr else r["as_"]) for r in rows]
    home = [r["hs"] for r in rows if r["h"] == abbr]
    allowed = [(r["as_"] if r["h"] == abbr else r["hs"]) for r in rows]
    return {"all": scored, "home": home, "last30": scored[-30:],
            "allowed": allowed}


def opp_allowed(con, abbr: str, since: str, f5: bool = False) -> list[int]:
    return team_runs(con, abbr, since, f5)["allowed"]


# ----------------------------------------------------------- the report

def _p(s: str = "") -> None:
    print(s)


def _shipped(exact: str, date: str) -> None:
    """The k_pct the simulator was actually handed, plus the velo kick.

    Read through `rates`/`velo` exactly as `arm` reads it, because the
    number that matters is the SHRUNK, park-NEUTRALISED one — Dobnak's
    raw .1524 ships as .1815, and comparing his counted rate against the
    raw would have hidden the whole question.

    Tonight's lineup and park multipliers are NOT applied: they need the
    live slate, which is not available for an arbitrary past date, and
    the board's own number already carries them. `arm <name> <date>`
    prints the full per-PA chain when the slate is up.
    """
    try:
        from src.context import sim, velo
        from src.context.sources import rates as rate_src
        lg = sim.league()
        p = rate_src.pitcher_rates(lg, before=date).get(exact)
        if not p:
            _p("  shipped                none on record before this date")
            return
        kick = velo.kick_for(exact, date)
        _p(f"  shipped k_pct          {p['k_pct']:.4f}   raw"
           f" {p['raw_k_pct']:.4f}   {p['pa']} bf / {p['apps']} apps"
           f"   velo {kick:+.4f}")
        _p(f"  league                 {lg['k_pct']:.4f}"
           f"   (shrinkage pulls toward this)")
    except Exception as e:                       # noqa: BLE001
        # A missing rates cache must not take the counted sections with
        # it — those are the rows the audit exists for.
        _p(f"  shipped                unavailable ({type(e).__name__})")


def _rate_rows(rows: list[dict]) -> tuple[int, int, float]:
    k = sum(r["k"] for r in rows)
    bf = sum(r["bf"] for r in rows)
    return k, bf, (k / bf if bf else 0.0)


def report(date: str, selector: str, side: str, price: str,
           board_path: str | None = None) -> int:
    path = board_path or boards.board_of_record(date)
    if not path:
        _p(f"no board JSON for {date} — run the board first")
        return 1
    board = boards.load(path)

    hits = candidates(board, selector)
    if not hits:
        _p(f"no rung matching {selector!r} on {path}")
        return 1
    if len(hits) > 1:
        _p(f"AMBIGUOUS — {selector!r} matches {len(hits)} rungs:")
        for g, r in hits[:12]:
            _p(f"    {g['away']}@{g['home']}  {r['bet']}")
        _p("  narrow the selector.")
        return 1
    g, row = hits[0]

    ours = side_prob(row, side)
    be = breakeven(price)
    import os
    _p(f"RUNG  {date}  {g['away']} @ {g['home']}   {row['bet']}"
       f"   {side.upper()}")
    _p(f"  board       {side} {ours:.1%}"
       f"   (over {row['over']} / under {row['under']})")
    if row["p_kalshi"] is not None:
        kal = row["p_kalshi"] if side == "over" else 1 - row["p_kalshi"]
        vol = "" if row["vol"] is None else f"   vol ${row['vol']:,.0f}"
        clv = "" if row["clv"] is None else f"   clv {row['clv']*100:+.1f}c"
        _p(f"  kalshi      {side} {kal:.1%}   mid {row['kalshi']}{vol}{clv}")
    else:
        _p("  kalshi      no mid on this rung")
    flags = [f for f, on in (("THIN", row["thin"]),
                             ("off-band", row["offband"]),
                             ("proj lineup", row["proj"])) if on]
    if row["gate"]:
        flags.append(f"gate: {row['gate']}")
    if flags:
        _p(f"  flags       {'; '.join(flags)}")
    if row["bump"]:
        _p("  NOTE        p_over already carries BETTING.md's +2pt"
           " high-K tail bump")
    _p(f"  source      {os.path.basename(path)}"
       f"   ({board.get('sims', '?')} sims)")

    _p()
    _p(f"PRICE  {price}")
    _p(f"  breakeven        {be:.1%}")
    _p(f"  edge vs board    {(ours - be) * 100:+.1f} pts")
    if row["p_kalshi"] is not None:
        kal = row["p_kalshi"] if side == "over" else 1 - row["p_kalshi"]
        _p(f"  edge vs kalshi   {(kal - be) * 100:+.1f} pts")

    t, n = tilt(board, row["cls"])
    if n:
        # The tilt is measured on the OVER; a bet on the under keeps the
        # same level error with the sign flipped.
        signed = t if side == "over" else -t
        _p()
        _p(f"TILT  class {row['cls']!r}, {n} rungs with a mid on this board")
        _p(f"  slate mean gap   {signed:+.1f} pts on the {side}")
        own = (row["gap"] if side == "over" else -row["gap"]) \
            if row["gap"] is not None else None
        if own is not None:
            _p(f"  this rung        {own:+.1f} pts"
               f"   residual {own - signed:+.1f}")
        _p(f"  de-tilted edge   {(ours - signed / 100 - be) * 100:+.1f} pts"
           f"   (if the slate gap is our level, not information)")

    with store.connect() as con:
        if row["cls"] in ("k", "outs"):
            _pitcher(con, g, row, side, ours, be, date)
        else:
            _totals(con, g, row, side, be, date)
    return 0


def _pitcher(con, g, row, side, ours, be, date) -> None:
    name = row["bet"].rsplit(" k ", 1)[0].rsplit(" outs ", 1)[0]
    line = float(row["bet"].rsplit(" ", 1)[1])
    hit = arm.resolve_name(arm.ids_for(con, name), name)
    if hit is None:
        _p(f"\n(no unambiguous pitcher id for {name!r} — "
           f"counted sections skipped)")
        return
    pid, exact = hit

    _p()
    _p(f"ROLE  {exact}")
    for yr, st, ap in arm.starts_by_season(con, pid):
        mark = "   <-- this season" if yr == date[:4] else ""
        _p(f"  {yr}   {st:3d} starts / {ap:3d} appearances{mark}")
    log = [r for r in starts(con, pid) if r["d"][:4] == date[:4]]
    if not log:
        _p("  no starts this season — nothing counted below")
        return
    tail = log[-5:]
    _p(f"  last {len(tail)} starts  outs "
       f"{', '.join(str(r['o']) for r in tail)}")
    _p(f"               bf   {', '.join(str(r['bf']) for r in tail)}")
    _p(f"               K    {', '.join(str(r['k']) for r in tail)}")

    gap = layoff_split(log)
    if gap is not None:
        _p(f"  LAYOFF  {_days(log[gap - 1]['d'], log[gap]['d'])} days"
           f" between {log[gap - 1]['d']} and {log[gap]['d']}"
           f" — {len(log) - gap} start(s) since")

    if row["cls"] == "k":
        _p()
        _p("DRIFT  K per batter faced — shipped vs counted")
        _shipped(exact, date)
        for lab, rows in windows(log):
            k, bf, rate = _rate_rows(rows)
            se = math.sqrt(max(rate * (1 - rate), 0) / bf) if bf else 0
            _p(f"  {lab:22s} {rate:.4f}   {k:3d} K / {bf:4d} bf"
               f"   se {se:.4f}   ({len(rows)} starts)")

    bfs = [r["bf"] for r in log]
    recent = bfs[-5:]
    rmean = sum(recent) / len(recent)
    _p()
    _p("WORKLOAD  batters faced per start, counted from play-by-play")
    _p(f"  season mean {sum(bfs)/len(bfs):5.1f}   last {len(recent)} mean"
       f" {rmean:5.1f}   min {min(bfs)}   max {max(bfs)}")
    imp = implied_rate(row["p_over"], round(rmean), line) \
        if row["cls"] == "k" else None
    if imp is not None:
        _p(f"  board-implied per-PA rate at {round(rmean)} batters"
           f"  {imp:.4f}")
        _p("    (flat rate reproducing the board's own number; compare"
           " to DRIFT above)")

    if row["cls"] == "outs":
        _p()
        _p(f"OUTS  how often he has cleared {line}, counted")
        for lab, rows in windows(log):
            over = sum(1 for r in rows if r["o"] > line)
            n = len(rows)
            _p(f"  {lab:22s} {side} "
               f"{(over if side == 'over' else n - over) / n:.1%}"
               f"   ({over}/{n} over)   se {wilson_se(over, n):.1%}")
        _p("  a binomial grid is not printed for outs — the hook is a"
           " manager decision,")
        _p("  not n independent trials, and BETTING.md has outs measured"
           " WORSE than the market.")
        return

    cols = [(lab, _rate_rows(rows)[2]) for lab, rows in windows(log)]
    cols = [(lab, r) for lab, r in cols if r > 0][:4]
    lo = max(1, int(round(rmean)) - 2)
    _p()
    _p(f"SCENARIOS  P({side} {line} K), breakeven {be:.1%}"
       f"  — binomial, no hook/TTO")
    _p("  bf    " + "  ".join(f"{lab[:13]:>13s}" for lab, _ in cols))
    _p("        " + "  ".join(f"{r:>13.4f}" for _, r in cols))
    for n in range(lo, lo + 6):
        cells = []
        for _, r in cols:
            p = p_over_line(n, r, line)
            p = p if side == "over" else 1 - p
            cells.append(f"{p:>12.1%}{'*' if p >= be else ' '}")
        mark = " <-- recent mean" if n == round(rmean) else ""
        _p(f"  {n:3d}   " + "  ".join(cells) + mark)
    _p("  * clears the breakeven")


def _totals(con, g, row, side, be, date) -> None:
    """Runs counted for the club(s) the rung is actually about."""
    f5 = row["cls"] == "f5"
    line = float(row["bet"].rsplit(" ", 1)[1])
    since = f"{date[:4]}-04-01"
    if row["cls"] == "team":
        team = row["bet"].split(" total ")[0]
        opp = g["home"] if team == g["away"] else g["away"]
        _p()
        _p(f"RUNS  {team} scored, {date[:4]} (line {line}, {side})")
        d = team_runs(con, team, since, f5)
        for lab in ("all", "home", "last30"):
            _rr(d[lab], line, side, lab)
        _p(f"\n  opponent {opp} runs ALLOWED")
        _rr(opp_allowed(con, opp, since, f5), line, side, "all")
        return

    _p()
    _p(f"RUNS  combined, {date[:4]} (line {line}, {side})"
       + ("  — F5 scores" if f5 else ""))
    for abbr in (g["away"], g["home"]):
        d = team_runs(con, abbr, since, f5)
        tot = [a + b for a, b in zip(d["all"], d["allowed"])]
        _rr(tot, line, side, f"{abbr} games")


def _rr(vals: list[int], line: float, side: str, lab: str) -> None:
    """One counted row: n, mean, and how often the side came in.

    PUSHES LEAVE THE DENOMINATOR on a whole-number line. Landing exactly
    on 9 is neither an over nor an under, and counting it as an under
    understated every whole-number over by the push rate — 10.7% of this
    engine's draws on a 9, which is larger than most edges this tool is
    asked to adjudicate. The board already prices integer totals as
    P(cover)/(P(cover)+P(miss)), so this is what makes the counted row
    comparable to it rather than a different question.
    """
    vals = [v for v in vals if v is not None]
    if not vals:
        _p(f"  {lab:10s} no games")
        return
    pushes = sum(1 for v in vals if v == line)
    n = len(vals) - pushes
    if not n:
        _p(f"  {lab:10s} n={len(vals):4d}   every game pushed")
        return
    over = sum(1 for v in vals if v > line)
    hits = over if side == "over" else n - over
    push = f"   {pushes} push" if pushes else ""
    _p(f"  {lab:10s} n={n:4d}   mean {sum(vals)/len(vals):5.2f}"
       f"   {side} {hits/n:.1%}   se {wilson_se(hits, n):.1%}{push}")


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        _p(__doc__.split("\n\n")[1].strip())
        return 1
    date, selector, side, price = argv[0], argv[1], argv[2].lower(), argv[3]
    if side not in ("over", "under"):
        _p(f"side must be 'over' or 'under', not {side!r}")
        return 1
    board = argv[argv.index("--board") + 1] if "--board" in argv else None
    return report(date, selector, side, price, board)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
