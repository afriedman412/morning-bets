"""THE BOARD, rebuilt lean — the slate in American odds, one block per game.

    venv/bin/python -m scratchpad.board [DATE] [SIMS] [--all]

Markets: full-game total, team totals, F5 total, and each starter's K and
outs lines — all read off ONE set of simulated games per matchup, so a K
line and the total its start sits inside cannot contradict each other.

WHAT CHANGED FROM THE DELETED BOARD (02d88e9), by operator request
2026-09-07: odds only, never probabilities or cents; one compact block per
game instead of a ladder dump per pitcher; no HTML view. The ±170 band is
unchanged — a line priced outside it is not one you will find a usable
number on — and it keeps the board to the common lines at real books
rather than Kalshi's full ladder of reaches.

THE OUTS CORRECTION PRICES THE LINE, same rule as before: the displayed
fair odds are corrected (`scratchpad/outs_adjust`), with the raw number in
the note. Kalshi mids attach to K and outs where a book inside MAX_SPREAD
exists; totals have no name-shaped ticker and print fair-only.

NOT A BET LIST. `BETTING.md` governs firing; the standing rules travel in
the footer.
"""
from __future__ import annotations

import statistics as st
import sys
import time
from datetime import date as _date

from src import roster
from src.context import plans, sim, slate
from src.context.sources import rates as rate_src
from scratchpad import kalshi
from scratchpad.outs_adjust import MEASURED_ON, correction

K_LINES = (2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5)
OUTS_LINES = (12.5, 13.5, 14.5, 15.5, 16.5, 17.5, 18.5, 19.5, 20.5)
TOTAL_LINES = (6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.5)
TEAM_LINES = (2.5, 3.5, 4.5, 5.5)
F5_LINES = (3.5, 4.5, 5.5, 6.5)

#: Fair price must be inside +/-BAND on BOTH sides. p in [1-hi, hi] where
#: hi = BAND/(BAND+100). The shopping filter, not a quality filter.
BAND = 170.0


def american(p: float) -> str:
    if p <= 0 or p >= 1:
        return "-"
    if p > 0.5:
        return f"{-100 * p / (1 - p):+.0f}"
    return f"{100 * (1 - p) / p:+.0f}"


def in_band(p: float, band: float | None) -> bool:
    if band is None:
        return 0 < p < 1
    hi = band / (band + 100.0)
    return (1 - hi) <= p <= hi


def _rungs(vals, lines, band, keep=2):
    """[(line, P(over))]: in-band lines, the `keep` nearest even money.

    A .0 line can PUSH; P(over) is P(v > line) and the push mass is priced
    to neither side, which is how a book quotes it (bet refunded). The
    band test uses P(over | no push) so a heavy push cannot smuggle a
    lopsided line through.

    `keep` is the second filter on top of the band, per the 2026-09-07
    operator request: a book hangs ONE line, so the board shows the rung
    a book would hang plus its neighbour, not the whole in-band ladder.
    """
    n = len(vals)
    out = []
    for ln in lines:
        over = sum(1 for v in vals if v > ln)
        push = sum(1 for v in vals if v == ln)
        if n == push:
            continue
        p = over / (n - push)
        if in_band(p, band):
            out.append((ln, p))
    out.sort(key=lambda t: abs(t[1] - 0.5))
    return sorted(out[:keep])


def _fmt(label, p, mid=None, note=""):
    ks = american(mid) if mid is not None else "-"
    return (f"  {label:<26}{american(p):>7} /{american(1 - p):>6}"
            f"{ks:>8}   {note}")


_CTX: dict = {}  # set pre-fork; a spawn child would reset USE_* flags

#: HOW THE SLATE IS CUT UP FOR THE POOL, counted on this machine
#: 2026-09-24 at the shipped 20,000 sims on a 12-game slate, three runs
#: an arm. The unit of work used to be ONE GAME, and that lost twice:
#:
#:   * TWO WAVES, MOSTLY IDLE. 12 games over 11 workers is one full wave
#:     and then a wave carrying a single game while ten cores sit out.
#:     A 16-game slate is the same shape and worse — five idle.
#:   * OVERSUBSCRIPTION. `cpu_count()` is 12 LOGICAL on 6 PHYSICAL cores
#:     here, so `cpu_count() - 1` put eleven python processes on six real
#:     ones and every one of them ran slower.
#:
#: So each game's draws are split `CHUNKS_PER_GAME` ways, which makes the
#: tasks small enough that the tail wave costs a quarter of a game rather
#: than a whole one. It is affordable because the per-call setup is
#: 0.128s against ~60s of drawing — measured, not assumed; the 6.8s that
#: LOOKS like setup is one-time lazy loading and `_warm` below kills it.
CHUNKS_PER_GAME = 4


def _workers(n_games: int) -> int:
    """Pool size. Two thirds of the logical count, which is this box's
    six physical cores plus a couple of hyperthreads — measured faster
    than both 6 and 11. `BOARD_WORKERS` overrides it on other hardware."""
    import multiprocessing as mp
    import os
    override = os.environ.get("BOARD_WORKERS")
    if override:
        return max(1, int(override))
    return max(1, min(n_games * CHUNKS_PER_GAME,
                      round((mp.cpu_count() or 2) * 2 / 3)))


def _jobs(n_games: int, n_sims: int) -> list[tuple[int, int, int]]:
    """(game, draws, seed) per task, the draws split so they still sum to
    exactly `n_sims` — a floor division would quietly price 19,999.

    EVERY CHUNK NEEDS ITS OWN SEED. `simulate_slate_game` defaults to
    `seed=0` and builds `random.Random(seed)` itself, so four chunks of
    one game at the default would draw the SAME 5,000 games four times
    and the board would print a 5,000-draw distribution labelled 20,000.
    """
    out = []
    for i in range(n_games):
        base, extra = divmod(n_sims, CHUNKS_PER_GAME)
        for c in range(CHUNKS_PER_GAME):
            n = base + (1 if c < extra else 0)
            if n:
                out.append((i, n, c))
    return out


def _warm() -> None:
    """One cheap draw in the PARENT, before the fork.

    The first `simulate_slate_game` in a process costs 6.8s of lazy
    loading — the velo table, the advancement counts, the lineup and
    role lookups, tonight's weather and plate umpire. `build` warmed the
    RATES in the parent and nothing else, so every forked child paid the
    rest again. Doing it once here means fork hands each child the warm
    copy. Best-effort: a slate whose first game cannot simulate is the
    pool's problem to report, not this function's.
    """
    try:
        slate.simulate_slate_game(
            _CTX["games"][0], _CTX["d"], _CTX["lg"], _CTX["pr"], _CTX["br"],
            _CTX["league_bats"], _CTX["pens"], n_sims=1)
    except Exception:
        pass


def _one(job):
    i, n_sims, seed = job
    c = _CTX
    g = c["games"][i]
    try:
        res, why = slate.simulate_slate_game(
            g, c["d"], c["lg"], c["pr"], c["br"], c["league_bats"],
            c["pens"], n_sims=n_sims, seed=seed)
    except Exception as e:  # a bad game must not sink the slate
        return i, {"why": f"{type(e).__name__} {e}"}
    if not res:
        return i, {"why": why}
    return i, {
        "why": None,
        "total": [r.total for r in res],
        "away": [r.away for r in res],
        "home": [r.home for r in res],
        "f5": [r.total_f5 for r in res],
        "k": {s: [getattr(r, f"{s}_sp").k for r in res]
              for s in ("away", "home")},
        "outs": {s: [getattr(r, f"{s}_sp").outs for r in res]
                 for s in ("away", "home")},
    }


def _merge(n_games: int, parts) -> list[dict]:
    """Chunks back into one result per game, in slate order.

    A CHUNK THAT FAILED FAILS ITS WHOLE GAME. Declining is the house rule
    — both starters or neither — and a game silently priced off three of
    its four chunks would look exactly like one priced off all four.
    """
    out: list[dict] = [{"why": "no draws returned"} for _ in range(n_games)]
    acc: dict[int, dict] = {}
    failed: dict[int, str] = {}
    for i, part in parts:
        if part["why"]:
            failed.setdefault(i, part["why"])
            continue
        cur = acc.get(i)
        if cur is None:
            cur = acc[i] = {"why": None, "k": {"away": [], "home": []},
                            "outs": {"away": [], "home": []},
                            **{f: [] for f in ("total", "away", "home", "f5")}}
        for f in ("total", "away", "home", "f5"):
            cur[f].extend(part[f])
        for f in ("k", "outs"):
            for side in ("away", "home"):
                cur[f][side].extend(part[f][side])
    for i, cur in acc.items():
        out[i] = cur
    # LAST, so a decline is STICKY. Written as an overwrite of whatever
    # the good chunks accumulated, because the pool does not promise an
    # order and a failure that arrived first must not be priced over.
    for i, why in failed.items():
        out[i] = {"why": why}
    return out


def _vol(v: float) -> str:
    """'vol $8.5k' — traded dollars, as a note token.

    It rides in the NOTE column because board_json reads the printed
    columns with a regex and the note is its free-text group; a new
    column would silently drop every rung. $0 prints on purpose: an
    untraded book is the finding (a resting algo quote, not a market),
    and it is exactly what separated Lowder from Foster Griffin on
    2026-09-15 ($122 against $10k on the same slate).
    """
    if v >= 10000:
        return f"vol ${v / 1000:.0f}k"
    if v >= 1000:
        return f"vol ${v / 1000:.1f}k"
    return f"vol ${v:.0f}"


def _clv(delta: float) -> str:
    """'clv +3.2c' — how far the book has moved since its FIRST trade.

    Cents because a Kalshi contract settles at a dollar, so a probability
    point IS a cent. The sign is the OVER's: positive means the market has
    drifted toward the over since it opened, whichever side we happen to
    like. It rides in the note for the same reason `_vol` does — a new
    printed column would silently drop every rung out of board_json.

    NOT AN OBJECTIVE, AND THE DOCS ARE EMPHATIC. Our resolution was below
    the OPENING price's in July and August while we still beat the open on
    CLV, so this number can improve while the simulation gets worse. It is
    here to be looked at, never to decide whether a mechanism helped.
    """
    return f"clv {delta * 100:+.1f}c"


def _opens(tickers: dict, workers: int = 8) -> dict:
    """{key: opening probability} from each market's first PREGAME trade.

    `price_path` does the real work, including the cutoff that matters:
    Kalshi keeps trading through the game and settles at 0 or 1, so a
    trade after first pitch is the box score wearing a probability. Only
    trades strictly before the start count.

    A market with fewer than two pregame trades has no opening number and
    is simply absent — blank is the honest reading for a rung nobody has
    traded, and 695 of 2,467 markets had no volume at all on 2026-09-19.
    One dead fetch must not cost the board, so an error is absent too.
    """
    from src import parallel
    if not tickers:
        return {}
    keys = list(tickers)
    out = {}
    for i, got, err in parallel.gather(
            lambda j: kalshi.price_path(tickers[keys[j]], "over"),
            range(len(keys)), workers=workers):
        if err is None and got:
            out[keys[i]] = got["open_prob"]
    return out


def _mids(stat: str, d: str, wanted: set, tickers: dict | None = None) -> dict:
    """{(pitcher, line): (kalshi mid, traded $)}. Books wider than
    MAX_SPREAD dropped.

    `tickers` is an OPTIONAL out-parameter: pass a dict and it collects
    {("prop", stat, name, line): ticker} for every rung that priced, which
    is what `_opens` needs to look up an opening trade. It is an
    out-parameter rather than a third element of the tuple because
    `reprice_openers` unpacks this two-wide and a shape change would break
    it silently — the keys are stat-qualified because (name, line) alone
    collides between the k and outs ladders.
    """
    series = kalshi.SERIES_BY_STAT.get(stat)
    if not series or not wanted:
        return {}
    ids = {pid: nm for nm in {n for n, _ in wanted}
           if (pid := roster.player_id(nm))}
    out = {}
    try:
        markets = kalshi.markets(series)
    except Exception as e:
        print(f"  (kalshi {series} unavailable: {type(e).__name__})")
        return {}
    rows = []
    for m in markets:
        tk = m["ticker"]
        if kalshi.ticker_date(tk) != d:
            continue
        parsed = kalshi._parse(m)
        if not parsed:
            continue
        name, threshold = parsed
        key = (name, threshold - 0.5)
        if key not in wanted:
            pid = roster.player_id(name)
            key = (ids.get(pid), threshold - 0.5) if pid else None
            if key is None or key not in wanted:
                continue
        rows.append((key, m))
    for (key, m), (bid, ask) in zip(rows, kalshi.quotes([m for _, m in rows])):
        if bid is None or ask is None or (ask - bid) > kalshi.MAX_SPREAD:
            continue
        out[key] = ((bid + ask) / 2, float(m.get("volume_fp") or 0))
        if tickers is not None:
            tickers[("prop", stat, key[0], key[1])] = m["ticker"]
    return out


def _game_mids(d: str, wanted: set, tickers: dict | None = None) -> dict:
    """{(game, team, line, kind): (mid, traded $)} for totals, team totals
    and F5.

    `tickers` is the same optional out-parameter `_mids` takes, collecting
    {("game", game, team, line, kind): ticker} for `_opens`.

    These series were listed as unmapped for weeks on the grounds that
    their subtitles do not fit the player-prop shape. They do not need to:
    every game-level market carries `floor_strike` and `strike_type`, so
    the line and the side come straight off the payload. KXMLBF5TOTAL is
    the first-five total — the quantity the model fits directly — and it
    was the last one still missing.
    """
    out, rows = {}, []
    for kind in ("total", "team", "f5"):
        try:
            ms = kalshi.game_markets(kind, d)
        except Exception as e:
            print(f"  (kalshi {kind} unavailable: {type(e).__name__})")
            continue
        for m in ms:
            key = (m["game"], m["team"], m["line"], kind)
            if key not in wanted:
                continue
            rows.append((key, m["market"]))
    for (key, m), (bid, ask) in zip(rows, kalshi.quotes([m for _, m in rows])):
        if bid is None or ask is None:
            continue
        if (ask - bid) > kalshi.MAX_SPREAD:
            continue
        out[key] = ((bid + ask) / 2, float(m.get("volume_fp") or 0))
        if tickers is not None:
            tickers[("game",) + key] = m["ticker"]
    return out


def _with_prior_seasons(pr: dict, lg: dict, d: str) -> tuple[dict, dict]:
    """Fill in arms THIS season has never seen from their prior seasons.

    -> (rates, {name: last season pitched}) for the ones filled in.

    WHY IT IS A FALLBACK AND NOT A SCOPE CHANGE. Calling
    `pitcher_rates(season=ALL_SEASONS)` outright takes the map from
    1,065 pitchers to 2,323 and folds prior seasons into EVERY arm's
    rates, which moves every number on every board and is a battery
    item. This touches only names the season-scoped map does not have,
    so no arm anyone was already pricing changes by a thousandth.

    WHAT IT BUYS. DJ Herz was declined on 2026-09-21 — "no rates on
    record" — with 19 starts and 385 batters faced sitting in 2024. The
    whole game went unpriced for it, both starters or neither. A
    returnee is not an unknown.

    WHAT IT DOES NOT BUY, AND THE BOARD SAYS SO. There is no staleness
    discount anywhere in the engine: recency weighting reweights a
    pitcher's starts against EACH OTHER, so an arm whose starts are all
    equally old gets no discount at all (measured: recency-weighted and
    plain both give Herz 0.2769). Sample-size shrinkage moves him 6% of
    the way to league and that is the only haircut he takes. So his
    2024 rate is used with the SAME confidence as a rate earned this
    August. That is a real assumption, it is the operator's to make, and
    it is why these arms are flagged on the board rather than folded in
    quietly. Discounting it properly means measuring what a prior season
    predicts — the open "memory across a winter" question — not picking
    a number here.

    A genuine debutant, with no line in any season, is still missing
    from both maps and still declines. That is correct: he is unknown,
    not stale.
    """
    from src import db
    from src.context import scope
    prior = rate_src.pitcher_rates(lg, before=d, season=scope.ALL_SEASONS)
    fill = {n: r for n, r in prior.items() if n not in pr}
    if not fill:
        return pr, {}
    with db.connect() as c:
        last = {r["player_name"]: r["season"] for r in c.execute(
            "select p.player_name, max(substr(g.date,1,4)) season "
            "from mlb_pitching p join games g on g.game_id = p.game_id "
            "where g.date < ? group by p.player_name", (d,))}
    return {**fill, **pr}, {n: last.get(n, "?") for n in fill}


def build(d: str, n: int = 20000, band: float | None = BAND) -> dict:
    lg = sim.league()
    pr = rate_src.pitcher_rates(lg, before=d)  # never a start's own day
    pr, stale_arms = _with_prior_seasons(pr, lg, d)
    # A GAME WITH NO PROBABLE USED TO VANISH HERE. This was a bare list
    # comprehension, so three of fifteen games on 2026-09-11 were dropped
    # BEFORE `declined` was assembled: the board printed "12 games", the
    # DECLINED section was empty because nothing had been appended to it,
    # and nothing anywhere said the other three existed. Declining is
    # right — both starters or neither — but it has to be SAID, and it is
    # also the prompt to go fill the name in through `probables`.
    all_games = slate.slate(d)
    probable_notes = list(slate.LAST_PROBABLE_NOTES)
    games, no_probable = [], []
    for g in all_games:
        a, h = g.get("away") or {}, g.get("home") or {}
        missing = [s for s in ("away", "home")
                   if not (g.get(s) or {}).get("starter")]
        if missing:
            no_probable.append(
                (f"{a.get('abbr')} @ {h.get('abbr')}",
                 f"{a.get('starter')} / {h.get('starter')}",
                 f"no probable posted ({', '.join(missing)})"
                 " — set one with `-m src.context.probables`"))
            continue
        games.append(g)
    _CTX.update(
        d=d, n=n, games=games, lg=lg, pr=pr,
        br=rate_src.batter_rates(lg, before=d),
        pens=rate_src.bullpens(lg, before=d),
        league_bats=sim.BatterRates(
            name="league", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
            hr_pct=lg["hr_pct"], babip=lg["babip"]))
    t_sim = time.monotonic()
    import multiprocessing as mp
    ctx = mp.get_context("fork")
    if games:
        _warm()
    jobs = _jobs(len(games), n)
    with ctx.Pool(_workers(len(games) or 1)) as pool:
        parts = pool.map(_one, jobs, chunksize=1)
    out = _merge(len(games), parts)
    t_sim = time.monotonic() - t_sim

    # KALSHI FIRST, for every rung, so the rung a book actually hangs
    # prints even when OUR fair sits outside the band. Found 2026-09-07:
    # Ryan's book was at 3.5 and Cease's at 7.5 while the band kept our
    # 4.5 and 6.5 — the board hid exactly the rows where the disagreement
    # was biggest, which are the only rows worth a second look.
    t_mkt = time.monotonic()
    names = {g[s]["starter"] for g, r in zip(games, out)
             if not r["why"] for s in ("away", "home")}
    # One shared ticker map across both ladders, so the opening trades go
    # out as a single parallel batch instead of one round trip per rung.
    tks: dict = {}
    mids = {stat: _mids(stat, d, {(nm, ln) for nm in names for ln in lines},
                        tickers=tks)
            for stat, lines in (("k", K_LINES), ("outs", OUTS_LINES))}
    opens = _opens(tks)

    blocks, not_quoted = [], []
    declined = list(no_probable)
    for g, r in zip(games, out):
        a, h = g["away"], g["home"]
        tag = f"{a['abbr']} @ {h['abbr']}"
        code = f"{a['abbr']}{h['abbr']}"
        if r["why"]:
            declined.append((tag, f"{a['starter']} / {h['starter']}",
                             r["why"]))
            continue
        b = {"tag": tag, "g": g, "r": r, "rows": []}
        # THE GATE RUNS FIRST AND STAMPS THE WHOLE GAME. On 2026-09-09,
        # 54 of 126 game-level rungs sat in a game containing a flagged arm
        # and none carried a warning — the flag printed on the pitcher's
        # own K and outs rows only, while the total, team totals and F5
        # inherit the identical defect and are the rows an operator
        # actually bets. Display only; the modelling item is TODO 15.
        gate = {s: slate.priceable(g[s]["starter"],
                                   (pr.get(g[s]["starter"]) or {}).get("pa")
                                   or 0, d)
                for s in ("away", "home")}
        game_note = "  ".join(
            f"[{g[s]['starter']}: {gate[s][1]}]" for s in ("away", "home")
            if not gate[s][0])
        # A STALE ARM RIDES THE SAME RAIL AS A FLAGGED ONE, and on the
        # WHOLE BLOCK rather than his own rows: the total, team totals
        # and F5 inherit a two-season-old rate exactly as they inherit a
        # flagged arm, and those are the rows anyone actually bets. He is
        # priced — a returnee is not an unknown — but never silently.
        # Short on purpose: it repeats on every row of the block, and
        # both starters can be stale at once (WSH @ DET, 2026-09-21).
        # "not aged" is the load-bearing word — see `_with_prior_seasons`.
        stale_note = "  ".join(
            f"[{g[s]['starter']}: {stale_arms[g[s]['starter']]} rates, "
            f"not aged]"
            for s in ("away", "home") if g[s]["starter"] in stale_arms)
        if stale_note:
            game_note = f"{game_note}  {stale_note}" if game_note \
                else stale_note
        # AN APPLIED PLAN IS ANNOUNCED (`plans.py`, probables rule 2) —
        # on the whole block, because the total and F5 rows inherit the
        # replanned start exactly as they inherit a flagged arm.
        day_plans = plans.for_date(d)
        plan_note = "  ".join(
            f"[PLAN {g[s]['abbr']}: {g[s]['starter']} "
            f"{plans.describe(day_plans[g[s]['abbr']])}]"
            for s in ("away", "home") if g[s]["abbr"] in day_plans)
        if plan_note:
            game_note = f"{plan_note}  {game_note}" if game_note \
                else plan_note
        for label, key in (("total", "total"), (f"{a['abbr']} total",
                           "away"), (f"{h['abbr']} total", "home")):
            lines = TOTAL_LINES if key == "total" else TEAM_LINES
            keep = 3 if key == "total" else 2
            team = None if key == "total" else g[key]["abbr"]
            for ln, p in _rungs(r[key], lines, band, keep=keep):
                b["rows"].append(("tot", label, ln, p,
                                  (code, team, ln, "team" if team
                                   else "total"), game_note))
        for ln, p in _rungs(r["f5"], F5_LINES, band):
            b["rows"].append(("tot", "F5 total", ln, p,
                              (code, None, ln, "f5"), game_note))
        for s in ("away", "home"):
            name = g[s]["starter"]
            pa = (pr.get(name) or {}).get("pa")
            # THE ARM GATE MARKS, IT DOES NOT DECLINE. `slate.priceable`
            # answers "is this a starter you can hang a normal line on" —
            # openers, swingmen and debuts fail it, and the model prices
            # them confidently anyway: Lake Bachar on 2026-09-09 averages
            # 6.9 outs a start and came out at 61.7% to clear 4.5 K
            # against a market at 7.5%.
            #
            # Operator decision 2026-09-09: SHOW THE ROW, FLAG THE ARM.
            # Hiding a rung hides the disagreement too, and the THIN column
            # already established that the useful move is to travel the
            # caveat with the number rather than suppress it. The reason
            # ships in brackets so a reader downstream can lift it whole.
            ok, why = gate[s]
            if not ok:
                not_quoted.append((tag, name, why))
            confirmed = bool((h if s == "away" else a).get("lineup"))
            note = "" if confirmed else "proj lineup"
            # THIN: under 60% of the priced rate is his own record; a gap
            # here can be OUR SHRINKAGE rather than his talent (BETTING.md).
            if pa and slate.shrink_weight(pa) < slate.THIN_WEIGHT:
                note = (note + "  " if note else "") + "THIN"
            if not ok:
                note = (note + "  " if note else "") + f"[{why}]"
            for stat, lines in (("k", K_LINES), ("outs", OUTS_LINES)):
                vals = r[stat][s]
                rungs = _rungs(vals, lines, band)
                have = {ln for ln, _ in rungs}
                # A rung the market hangs joins regardless of the band.
                for ln in lines:
                    if ln in have or (name, ln) not in mids[stat]:
                        continue
                    push = sum(1 for v in vals if v == ln)
                    if push == len(vals):
                        continue
                    p = (sum(1 for v in vals if v > ln)
                         / (len(vals) - push))
                    rungs.append((ln, p))
                for ln, raw in sorted(rungs):
                    p, xtra = raw, ""
                    if stat == "outs":
                        p = min(max(raw + correction(ln), 0.001), 0.999)
                        xtra = f"raw {american(raw)}"
                    if not in_band(raw, band):
                        xtra = (xtra + "  " if xtra else "") + "off-band"
                    mid, vol = mids[stat].get((name, ln)) or (None, None)
                    if vol is not None:
                        xtra = (xtra + "  " if xtra else "") + _vol(vol)
                    op = opens.get(("prop", stat, name, ln))
                    if mid is not None and op is not None:
                        xtra = (xtra + "  " if xtra else "") + _clv(mid - op)
                    b["rows"].append(
                        (stat, name, ln, p, mid,
                         (note + "  " if note else "") + xtra
                         if xtra or note else ""))
        blocks.append(b)

    # Game-level mids last: collect every key the board actually printed so
    # only those orderbooks are fetched, rather than the whole ladder.
    wanted = {row[4] for b in blocks for row in b["rows"]
              if row[0] == "tot" and row[4] is not None}
    g_tks: dict = {}
    gm = _game_mids(d, wanted, tickers=g_tks)
    g_opens = _opens(g_tks)
    t_mkt = time.monotonic() - t_mkt
    for b in blocks:
        rows = []
        for row in b["rows"]:
            if row[0] != "tot":
                rows.append(row)
                continue
            mid, vol = gm.get(row[4]) or (None, None)
            note = row[5]
            if vol is not None:
                note = (note + "  " if note else "") + _vol(vol)
            op = g_opens.get(("game",) + row[4]) if row[4] else None
            if mid is not None and op is not None:
                note = (note + "  " if note else "") + _clv(mid - op)
            rows.append(row[:4] + (mid, note))
        b["rows"] = rows

    return {"date": d, "n": n, "band": band, "blocks": blocks,
            "declined": declined, "not_quoted": not_quoted,
            "probables": probable_notes,
            "t_sim": t_sim, "t_mkt": t_mkt}


def print_board(payload):
    d, n, band = payload["date"], payload["n"], payload["band"]
    bs = f"±{band:.0f}" if band is not None else "all lines"
    print(f"BOARD — {d} · {len(payload['blocks'])} games · {n:,} sims"
          f" · fair inside {bs} · odds are FAIR (no vig)\n")
    stat_label = {"tot": "", "k": "k", "outs": "outs"}
    for b in payload["blocks"]:
        g, r = b["g"], b["r"]
        lu = ("lineups posted" if g["away"].get("lineup")
              and g["home"].get("lineup") else "PROJECTED lineups")
        print(f"{b['tag']}   {g['away']['starter']} v"
              f" {g['home']['starter']}   ({lu},"
              f" mean {st.mean(r['total']):.1f})")
        print(f"  {'bet':<26}{'over':>7} /{'under':>6}{'kalshi':>8}")
        for st_, who, ln, p, mid, note in b["rows"]:
            lbl = f"{who} {stat_label[st_]} {ln:g}".replace("  ", " ")
            print(_fmt(lbl, p, mid, note))
        print()
    if payload.get("not_quoted"):
        print("ARMS FLAGGED — priced, but not a normal starter's line:")
        for tag, nm, why in payload["not_quoted"]:
            print(f"  {tag:<12}{nm:<24}{why}")
        print()
    if payload["declined"]:
        print("DECLINED — never filled with a league-average arm:")
        for tag, sp, why in payload["declined"]:
            print(f"  {tag:<12}{sp[:38]:<40}{why}")
        print()
    if payload.get("probables"):
        print("MANUAL PROBABLES — operator-supplied, ahead of the feed:")
        for line in payload["probables"]:
            print(line.replace("  probables: ", "  "))
        print()
    print(f"outs corrected ({MEASURED_ON}); raw in note. K beats the OPEN"
          " only — bet early or not.")
    print("Totals Jul/Aug ran ~0.15-0.20 light a side (unshipped month"
          " term); Sept unmeasured.")
    print("Re-run after lineups post: a projected nine has cost half an"
          " edge before.")
    ts, tm = payload.get("t_sim"), payload.get("t_mkt")
    if ts is not None:
        print(f"\nwall clock: {payload['elapsed']:.0f}s total — "
              f"{ts:.0f}s simulating, {tm:.0f}s fetching markets, "
              f"{payload['elapsed'] - ts - tm:.0f}s loading rates. "
              f"RE-RUNNING IS CHEAP; do it when lineups post.")


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    d = args[0] if args else _date.today().isoformat()
    n = int(args[1]) if len(args) > 1 else 20000
    band = None if "--all" in argv else BAND
    t0 = time.monotonic()
    payload = build(d, n=n, band=band)
    payload["elapsed"] = time.monotonic() - t0
    print_board(payload)


if __name__ == "__main__":
    main(sys.argv[1:])
