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
    OUTS         the model's WEAKEST market, and the correction below is
                 STALE. Read the block on `outs_adjust` before quoting one.
    F5           the stated product, and the only thing here that has ever
                 beaten a settled price on realised outcomes (0.1890 Brier
                 against Kalshi's 0.1919 over 455 contracts, unconfirmed at
                 that sample).

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
"""
from __future__ import annotations

import statistics as st
import sys
from datetime import date as _date

from src import kalshi, roster
from src.context import price, sim
from src.context.sources import rates as rate_src
from scratchpad.outs_adjust import HOLDOUT_MEAN_OUTS, correction

K_LINES = (2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5)
OUTS_LINES = (11.5, 12.5, 13.5, 14.5, 15.5, 16.5, 17.5, 18.5, 19.5, 20.5)
#: Per-club F5 runs, then the F5 GAME total. Different quantities, and the
#: second is the one Kalshi lists (`KXMLBF5TOTAL`).
F5_TEAM_LINES = (0.5, 1.5, 2.5, 3.5, 4.5)
F5_GAME_LINES = (3.5, 4.5, 5.5, 6.5)

#: Default price band, in American odds, applied to the FAIR price on both
#: sides. See THE BAND in the docstring.
BAND = 170.0


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


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    flags = [a for a in argv if a.startswith("--")]
    d = args[0] if args else _date.today().isoformat()
    n = int(args[1]) if len(args) > 1 else 20000
    band = None if "--all" in flags else BAND
    for f in flags:
        if f.startswith("--band"):
            band = float(f.split("=", 1)[1]) if "=" in f else BAND

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
    band_s = ("all lines" if band is None
              else f"fair price inside +/-{band:.0f}")
    print(f"BOARD — {d}   {len(games)} games with both starters named   "
          f"{n:,} sims each   {band_s}\n")

    import multiprocessing as mp
    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, min(len(games), (mp.cpu_count() or 2) - 1))) as pool:
        out = pool.map(_summarise, range(len(games)))

    # PASS ONE: build every row, so the Kalshi fetch is one pass over the
    # tickers we actually need rather than one per pitcher.
    rows, f5_rows, declined = [], [], []
    for g, r in zip(games, out):
        a, h = g["away"], g["home"]
        tag = f"{a['abbr']} @ {h['abbr']}"
        if r["why"]:
            who = f"{a['starter']} / {h['starter']}"
            declined.append((tag, who, r["why"]))
            continue
        for side in ("away", "home"):
            s = r["sides"][side]
            opp = h["abbr"] if side == "away" else a["abbr"]
            p = pr.get(s["name"]) or {}
            pa = p.get("pa")
            for stat, lines in (("k", K_LINES), ("outs", OUTS_LINES)):
                for ln, po in _ladder(s[stat], lines, band):
                    rows.append({
                        "player": s["name"], "opp": opp, "tag": tag,
                        "stat": stat, "line": ln, "over": po,
                        "proj": st.mean(s[stat]),
                        "pa": pa, "w": price.shrink_weight(pa) if pa else None,
                        "confirmed": bool(
                            (h if side == "away" else a).get("lineup")),
                    })
            if s["f5"]:
                for ln, po in _ladder(s["f5"], F5_TEAM_LINES, band):
                    f5_rows.append({"tag": tag, "who": g[side]["abbr"],
                                    "kind": "team", "line": ln, "over": po,
                                    "proj": st.mean(s["f5"])})
        if r["f5_game"]:
            for ln, po in _ladder(r["f5_game"], F5_GAME_LINES, band):
                f5_rows.append({"tag": tag, "who": "GAME", "kind": "game",
                                "line": ln, "over": po,
                                "proj": st.mean(r["f5_game"])})

    mids = {}
    for stat in ("k", "outs"):
        want = {(x["player"], x["line"]) for x in rows if x["stat"] == stat}
        mids[stat] = _kalshi_mids(stat, d, want) if want else {}

    # PASS TWO: print, grouped by pitcher, K then outs.
    print(f"  {'pitcher':<20}{'opp':<5}{'proj':>6}  {'bet':<11}{'P(ov)':>8}"
          f"{'fair OV':>9}{'fair UN':>9}{'kalshi':>8}{'edge':>7}  note")
    for player in sorted({x["player"] for x in rows}):
        mine = [x for x in rows if x["player"] == player]
        for x in sorted(mine, key=lambda y: (y["stat"], y["line"])):
            mid = mids[x["stat"]].get((x["player"], x["line"]))
            edge = f"{x['over'] - mid:+.3f}" if mid is not None else "    -"
            note = []
            if x["w"] is not None and x["w"] < price.THIN_WEIGHT:
                note.append(f"THIN own {x['w']:.2f}")
            if not x["confirmed"]:
                note.append("proj lineup")
            if x["stat"] == "outs":
                adj = min(max(x["over"] + correction(x["line"]), 0.001), 0.999)
                note.append(f"adj ov {adj:.3f} [STALE]")
                if abs(x["proj"] - HOLDOUT_MEAN_OUTS) > 2:
                    note.append("far from correction mean")
            bet = f"{x['stat']} o{x['line']:g}"
            print(f"  {player[:18]:<20}{x['opp']:<5}{x['proj']:>6.1f}  "
                  f"{bet:<11}{x['over']:>8.3f}"
                  f"{american(x['over']):>9}{american(1 - x['over']):>9}"
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
    print("   * OUTS IS THE WEAKEST MARKET HERE and the `adj ov` column is")
    print("     STALE: the correction table was measured before the")
    print("     high-pitch hook branch shipped. TODO 8d. Do not quote it.")
    print("   * Strikeouts beat the OPEN and not the CLOSE. Bet early or")
    print("     not at all.")
    print("   * `THIN` means under 60% of the rate priced is the pitcher's")
    print("     own record; the rest is the shrink target, and a gap on one")
    print("     of these can be OUR SHRINKAGE rather than his talent.")
    print("   * Lineups are PROJECTED unless a card is posted, and that is")
    print("     the weakest link in the path.")
    print("   * NEVER price a game in progress. `gamestate` guards the live")
    print("     fetches; a started game should not appear above at all.")


if __name__ == "__main__":
    main(sys.argv[1:])
