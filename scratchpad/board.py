"""THE LINE-SHOPPING BOARD — every startable line on a slate, one screen.

    venv/bin/python -m scratchpad.board [DATE] [n_sims] [--band 170] [--all]

WHAT THIS IS. The board built ad-hoc on 2026-08-29/30 across a dozen inline
`python -c` invocations, made repeatable. It prices STRIKEOUTS, OUTS and
FIRST-FIVE for every game on the slate off ONE set of simulated games, so a
starter's K line, his outs line and the F5 total his own start sits inside
cannot contradict each other. That single-draw property is the whole reason
this is a module and not three scripts.

    STRIKEOUTS   the model's strongest market. Scored against settled
                 prices: 32.9% better than Kalshi's OPEN at predicting the
                 close, worthless against the CLOSE. Bet it early.
    OUTS         the model's WEAKEST market even with a current
                 correction. Read the block on `outs_adjust` before
                 quoting one.
    F5           the stated product, and the only thing here that has ever
                 beaten a settled price on realised outcomes (0.1890 Brier
                 against Kalshi's 0.1919 over 455 contracts, unconfirmed at
                 that sample).

THE CORRECTION PRICES THE LINE; IT IS NOT AN ANNOTATION. Fixed 2026-08-30
after the operator asked why every outs under looked like a huge edge. The
edge column was `raw_over - kalshi_mid` while the measured correction sat in
a note nobody could act on, so the whole outs block was tilted toward unders
by the exact size of the bias the correction exists to remove: mean edge
-0.039 at 2.4 sigma over 16 rows, going to +0.004 at 0.2 sigma once applied.
It hid overs as well as inventing unders (Imanaga o15.5 +0.049 -> +0.101).
`priced` is what a row is compared against a market on; `over` stays RAW
because it is what the simulator said and the simulator's own numbers are
never corrected in place.

WHAT IT IS NOT. It is not a bet list. It prints fair prices and the market's
where one exists; deciding to fire is the operator's job and `BETTING.md` is
the page that governs it.

THE BAND. `--band 170` keeps only rows whose fair price is inside +/-170 on
both sides, which is exactly `0.3704 <= P(over) <= 0.6296`. Both sides are in
or out together, so there is only one filter. `--all` disables it. The band
is not a quality filter — it is a shopping filter, because a line priced
outside it is not one you will find a usable number on. Widened from 150 on
2026-08-30: at 150 the ladder was cutting off rows that a book will still
quote, and the point of the filter is what is shoppable, not what is close.

THE HALF-INNING TRAP, and it cost a day on 2026-08-29. `GameResult.prefix`
is the GAME total through N innings; `prefix_side[N]` is a PAIR and its
order is (away team's runs, home team's runs) — obtained by SWAPPING, since
`game.py` stores runs ALLOWED per side. Read it the other way round and
every F5 team total on the board belongs to the wrong club.

VERIFIED 2026-08-30 on the live slate: 14 games, Kalshi mids attach on both
prop series, and the away/home F5 split is the right way round — three other
consumers (`homeroad`, `where_runs`, `ceiling`) document `prefix_side` as
(away TEAM score, home TEAM score) and this reads it that way.

TWO VIEWS, ONE PAYLOAD. `build()` simulates and prices; `print_board()` and
`board_html.render()` are both readers of what it returns. `--html [PATH]`
writes the page, `--html-only` skips the terminal dump. A view that recomputes
anything is a view that can disagree with the other one, which is the failure
this split exists to prevent — so the samples travel in the payload rather
than the summary statistics, and both views bin them the same way.
"""
from __future__ import annotations

import statistics as st
import sys
from datetime import date as _date

from src import kalshi, roster
from src.context import price, sim
from src.context.sources import rates as rate_src
from scratchpad.outs_adjust import (HOLDOUT_MEAN_OUTS, MEASURED_ON,
                                    correction)

K_LINES = (2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5)
OUTS_LINES = (11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5, 18.5, 19.5, 20.5)
#: Per-club F5 runs, then the F5 GAME total. Different quantities, and the
#: second is the one Kalshi lists (`KXMLBF5TOTAL`).
F5_TEAM_LINES = (0.5, 1.5, 2.5, 3.5, 4.5)
F5_GAME_LINES = (3.5, 4.5, 5.5, 6.5)

#: Default price band, in American odds, applied to the FAIR price on both
#: sides. See THE BAND in the docstring.
BAND = 170.0

#: Where `--html` writes with no path given. Dated, because a board is only
#: true for one slate and overwriting yesterday's loses the record.
HTML_OUT = "scratchpad/board_{date}.html"


def american(p: float) -> str:
    if p <= 0 or p >= 1:
        return "-"
    if p > 0.5:
        return f"{-100 * p / (1 - p):+.0f}"
    return f"{100 * (1 - p) / p:+.0f}"


def in_band(p: float, band: float | None) -> bool:
    """Is the fair price inside +/-`band` on BOTH sides?

    A price of -band corresponds to p = band/(band+100) and +band to its
    complement, so one inequality covers both sides.
    """
    if band is None:
        return True
    hi = band / (band + 100.0)
    return (1 - hi) <= p <= hi


#: Set once in the parent and inherited by every FORKED child. A Pool cannot
#: pickle a closure, and a `spawn` child would re-import at DEFAULT globals
#: and silently revert every USE_* flag in `sim.py` — which is how a wired
#: mechanism reads as absent. Same reason `card.py` does it this way.
_CTX: dict = {}


def _summarise(i):
    """Simulate game `i` and return SAMPLES, not 20,000 `GameResult`s."""
    c = _CTX
    g = c["games"][i]
    try:
        res, why = price.simulate_slate_game(
            g, c["d"], c["lg"], c["pr"], c["br"], c["league_bats"],
            c["pens"], n_sims=c["n"])
    except Exception as e:
        return {"why": f"{type(e).__name__} {e}"}
    if not res:
        return {"why": why}
    out = {"why": None, "sides": {}}
    have_f5 = [r for r in res
               if getattr(r, "prefix_side", None) and 5 in r.prefix_side]
    # ORDER: (away team runs, home team runs). See the docstring.
    f5_away = [r.prefix_side[5][0] for r in have_f5]
    f5_home = [r.prefix_side[5][1] for r in have_f5]
    out["f5_game"] = [a + h for a, h in zip(f5_away, f5_home)] or None
    for idx, side in enumerate(("away", "home")):
        sp = [getattr(r, f"{side}_sp") for r in res]
        out["sides"][side] = {
            "name": g[side]["starter"],
            "k": [s.k for s in sp],
            "outs": [s.outs for s in sp],
            # Carried for the page only; the terminal board never prints it.
            "pitches": [s.pitches for s in sp],
            "f5": (f5_away if side == "away" else f5_home) or None,
        }
    return out


def _kalshi_mids(stat: str, d: str, wanted: set) -> dict:
    """{(name, line): mid} for the markets we are about to print.

    The book is fetched ONLY for tickers matching a row that survives the
    band filter — one HTTP call per ticker, and the full slate is hundreds.
    A book wider than `kalshi.MAX_SPREAD` is dropped rather than midpointed:
    it is two people shouting across a room, not a price.
    """
    series = kalshi.SERIES_BY_STAT.get(stat)
    if not series:
        return {}
    ids = {}
    for nm in {n for n, _ in wanted}:
        pid = roster.player_id(nm)
        if pid:
            ids[pid] = nm
    out = {}
    try:
        markets = kalshi.markets(series)
    except Exception as e:
        print(f"  (kalshi {series} unavailable: {type(e).__name__} {e})")
        return {}
    for m in markets:
        tk = m["ticker"]
        if kalshi.ticker_date(tk) != d:
            continue
        parsed = kalshi._parse(m)
        if not parsed:
            continue
        name, threshold = parsed
        line = threshold - 0.5
        key = (name, line)
        if key not in wanted:
            pid = roster.player_id(name)
            alt = (ids.get(pid), line) if pid else None
            if alt is None or alt not in wanted:
                continue
            key = alt
        bid, ask = kalshi.book(tk)
        if bid is None or ask is None or (ask - bid) > kalshi.MAX_SPREAD:
            continue
        out[key] = (bid + ask) / 2
    return out


def _ladder(vals, lines, band):
    """[(line, P(over))] for the lines whose fair price is inside the band."""
    n = len(vals)
    return [(ln, sum(1 for v in vals if v > ln) / n)
            for ln in lines
            if in_band(sum(1 for v in vals if v > ln) / n, band)]


def price_row(stat, line, over, proj, **kw):
    """One priced row. PURE, so the pricing rule is testable without a slate.

    It was not pure until 2026-08-30 and that is how the correction ended up
    annotating rows instead of pricing them: the only checks that could
    reach the rule were rendering checks, and they pass whatever number they
    are handed. Extracted so `check_outs_rows_are_priced_after_the_...`
    exercises THIS, not a fixture that reimplements it.

    `over` stays RAW — it is what the simulator said. `priced` is what a
    market is compared against, and for outs those differ.
    """
    row = {"stat": stat, "line": line, "over": over, "proj": proj,
           "mid": None, "edge": None, "priced": over,
           "thin_at": price.THIN_WEIGHT, **kw}
    if stat == "outs":
        row["adj"] = min(max(over + correction(line), 0.001), 0.999)
        row["priced"] = row["adj"]
        row["far"] = abs(proj - HOLDOUT_MEAN_OUTS) > 2
    return row


def build(d, n=20000, band=BAND):
    """Simulate and price the slate. The ONE computation both views read.

    Returns the payload documented at the top of this module: per game, the
    raw samples for every priced quantity plus the ladder rows with Kalshi's
    mid and our edge already attached.
    """
    lg = sim.league()
    # Rates strictly BEFORE the date: a start cannot inform its own price.
    pr = rate_src.pitcher_rates(lg, before=d)
    games = [g for g in price.slate(d)
             if (g.get("away") or {}).get("starter")
             and (g.get("home") or {}).get("starter")]
    _CTX.update(
        d=d, n=n, games=games, lg=lg, pr=pr,
        br=rate_src.batter_rates(lg, before=d),
        pens=rate_src.bullpens(lg, before=d),
        league_bats=sim.BatterRates(
            name="league", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
            hr_pct=lg["hr_pct"], babip=lg["babip"]),
    )
    import multiprocessing as mp
    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, min(len(games), (mp.cpu_count() or 2) - 1))) as pool:
        out = pool.map(_summarise, range(len(games)))

    # PASS ONE: build every row, so the Kalshi fetch is one pass over the
    # tickers we actually need rather than one per pitcher.
    priced, declined = [], []
    for g, r in zip(games, out):
        a, h = g["away"], g["home"]
        tag = f"{a['abbr']} @ {h['abbr']}"
        if r["why"]:
            who = f"{a['starter']} / {h['starter']}"
            declined.append((tag, who, r["why"]))
            continue
        block = {"tag": tag, "away": a["abbr"], "home": h["abbr"], "n": n,
                 "f5_game": r["f5_game"], "f5_rows": [], "sides": {}}
        for side in ("away", "home"):
            s = r["sides"][side]
            opp = h["abbr"] if side == "away" else a["abbr"]
            pa = (pr.get(s["name"]) or {}).get("pa")
            w = price.shrink_weight(pa) if pa else None
            confirmed = bool((h if side == "away" else a).get("lineup"))
            rows = []
            for stat, lines in (("k", K_LINES), ("outs", OUTS_LINES)):
                for ln, po in _ladder(s[stat], lines, band):
                    rows.append(price_row(
                        stat, ln, po, st.mean(s[stat]), player=s["name"],
                        opp=opp, tag=tag, pa=pa, w=w, confirmed=confirmed))
            block["sides"][side] = {
                **s, "opp": opp, "pa": pa, "w": w, "thin_at": price.THIN_WEIGHT,
                "confirmed": confirmed, "rows": rows}
            if s["f5"]:
                for ln, po in _ladder(s["f5"], F5_TEAM_LINES, band):
                    block["f5_rows"].append(
                        {"tag": tag, "who": g[side]["abbr"], "kind": "team",
                         "line": ln, "over": po, "proj": st.mean(s["f5"])})
        if r["f5_game"]:
            for ln, po in _ladder(r["f5_game"], F5_GAME_LINES, band):
                block["f5_rows"].append(
                    {"tag": tag, "who": "GAME", "kind": "game", "line": ln,
                     "over": po, "proj": st.mean(r["f5_game"])})
        priced.append(block)

    all_rows = [r for g in priced for s in g["sides"].values()
                for r in s["rows"]]
    for stat in ("k", "outs"):
        want = {(x["player"], x["line"]) for x in all_rows
                if x["stat"] == stat}
        mids = _kalshi_mids(stat, d, want) if want else {}
        for x in all_rows:
            if x["stat"] != stat:
                continue
            mid = mids.get((x["player"], x["line"]))
            if mid is not None:
                x["mid"], x["edge"] = mid, x["priced"] - mid

    return {"date": d, "n": n, "band": band, "games": priced,
            "declined": declined, "max_spread": kalshi.MAX_SPREAD * 100,
            # Travels in the payload so the page can state it. A correction
            # is only as current as the hook underneath it.
            "corrected_on": MEASURED_ON}


def print_board(payload):
    """The terminal view. Reads the payload; computes nothing."""
    d, n, band = payload["date"], payload["n"], payload["band"]
    games, declined = payload["games"], payload["declined"]
    band_s = ("all lines" if band is None
              else f"fair price inside +/-{band:.0f}")
    print(f"BOARD — {d}   {len(games) + len(declined)} games with both "
          f"starters named   {n:,} sims each   {band_s}\n")

    rows = [r for g in games for s in g["sides"].values() for r in s["rows"]]
    f5_rows = [r for g in games for r in g["f5_rows"]]

    print(f"  {'pitcher':<20}{'opp':<5}{'proj':>6}  {'bet':<11}{'P(ov)':>8}"
          f"{'fair OV':>9}{'fair UN':>9}{'kalshi':>8}{'edge':>7}  note")
    for player in sorted({x["player"] for x in rows}):
        mine = [x for x in rows if x["player"] == player]
        for x in sorted(mine, key=lambda y: (y["stat"], y["line"])):
            mid = x["mid"]
            edge = f"{x['edge']:+.3f}" if mid is not None else "    -"
            note = []
            if x["w"] is not None and x["w"] < price.THIN_WEIGHT:
                note.append(f"THIN own {x['w']:.2f}")
            if not x["confirmed"]:
                note.append("proj lineup")
            if x["stat"] == "outs":
                note.append(f"raw ov {x['over']:.3f} before correction")
                if x["far"]:
                    note.append("far from correction mean")
            bet = f"{x['stat']} o{x['line']:g}"
            pv = x["priced"]
            print(f"  {player[:18]:<20}{x['opp']:<5}{x['proj']:>6.1f}  "
                  f"{bet:<11}{pv:>8.3f}"
                  f"{american(pv):>9}{american(1 - pv):>9}"
                  f"{('-' if mid is None else f'{mid:.3f}'):>8}{edge:>7}"
                  f"  {', '.join(note)}")

    if f5_rows:
        print("\n  FIRST FIVE — the stated product.\n")
        print(f"  {'game':<12}{'side':<6}{'proj':>6}{'bet':>8}{'P(ov)':>8}"
              f"{'fair OV':>9}{'fair UN':>9}")
        for x in f5_rows:
            print(f"  {x['tag']:<12}{x['who']:<6}{x['proj']:>6.2f}"
                  f"{f'o{x['line']:g}':>8}{x['over']:>8.3f}"
                  f"{american(x['over']):>9}{american(1 - x['over']):>9}")
        print("\n  F5 game totals are listed by Kalshi as KXMLBF5TOTAL and")
        print("  are NOT attached here — the ticker carries a packed segment")
        print("  rather than a name, and `f5_market._match` is the parser.")

    if declined:
        print(f"\n  DECLINED {len(declined)} game(s) — never filled with a")
        print("  league-average arm; inventing the other club invents"
              " the score:")
        for tag, sp, why in declined:
            print(f"    {tag:<12}{sp[:40]:<42}{why}")

    print("\n  CAVEATS — `BETTING.md` is the governing page.")
    print("   * OUTS IS STILL THE WEAKEST MARKET HERE. The `adj ov` column")
    print(f"     is CURRENT — re-measured {MEASURED_ON} on the shipped hook,")
    print("     1,224 holdout starts — but outs is a manager decision the")
    print("     model reproduces only in aggregate. CLV z 1.3 against 43.5.")
    print("   * Strikeouts beat the OPEN and not the CLOSE. Bet early or")
    print("     not at all.")
    print("   * `THIN` means under 60% of the rate priced is the pitcher's")
    print("     own record; the rest is the shrink target, and a gap on one")
    print("     of these can be OUR SHRINKAGE rather than his talent.")
    print("   * Lineups are PROJECTED unless a card is posted, and that is")
    print("     the weakest link in the path.")
    print("   * NEVER price a game in progress. `gamestate` guards the live")
    print("     fetches; a started game should not appear above at all.")


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    flags = [a for a in argv if a.startswith("--")]
    d = args[0] if args else _date.today().isoformat()
    n = int(args[1]) if len(args) > 1 else 20000
    band = None if "--all" in flags else BAND
    html = None
    for f in flags:
        if f.startswith("--band"):
            band = float(f.split("=", 1)[1]) if "=" in f else BAND
        if f.startswith("--html"):
            html = (f.split("=", 1)[1] if "=" in f
                    else HTML_OUT.format(date=d))

    payload = build(d, n=n, band=band)
    if "--html-only" not in flags:
        print_board(payload)
    if html:
        from scratchpad import board_html
        page = board_html.render(payload)
        with open(html, "w") as fh:
            fh.write(page)
        print(f"\n  wrote {html}  ({len(page):,} bytes)")


if __name__ == "__main__":
    main(sys.argv[1:])
