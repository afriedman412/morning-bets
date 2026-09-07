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
from datetime import date as _date

from src import roster
from src.context import sim, slate
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


def _one(i):
    c = _CTX
    g = c["games"][i]
    try:
        res, why = slate.simulate_slate_game(
            g, c["d"], c["lg"], c["pr"], c["br"], c["league_bats"],
            c["pens"], n_sims=c["n"])
    except Exception as e:  # a bad game must not sink the slate
        return {"why": f"{type(e).__name__} {e}"}
    if not res:
        return {"why": why}
    return {
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


def _mids(stat: str, d: str, wanted: set) -> dict:
    """{(pitcher, line): kalshi mid}. Books wider than MAX_SPREAD dropped."""
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
        bid, ask = kalshi.book(tk)
        if bid is None or ask is None or (ask - bid) > kalshi.MAX_SPREAD:
            continue
        out[key] = (bid + ask) / 2
    return out


def build(d: str, n: int = 20000, band: float | None = BAND) -> dict:
    lg = sim.league()
    pr = rate_src.pitcher_rates(lg, before=d)  # never a start's own day
    games = [g for g in slate.slate(d)
             if (g.get("away") or {}).get("starter")
             and (g.get("home") or {}).get("starter")]
    _CTX.update(
        d=d, n=n, games=games, lg=lg, pr=pr,
        br=rate_src.batter_rates(lg, before=d),
        pens=rate_src.bullpens(lg, before=d),
        league_bats=sim.BatterRates(
            name="league", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
            hr_pct=lg["hr_pct"], babip=lg["babip"]))
    import multiprocessing as mp
    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, min(len(games) or 1,
                             (mp.cpu_count() or 2) - 1))) as pool:
        out = pool.map(_one, range(len(games)))

    # KALSHI FIRST, for every rung, so the rung a book actually hangs
    # prints even when OUR fair sits outside the band. Found 2026-09-07:
    # Ryan's book was at 3.5 and Cease's at 7.5 while the band kept our
    # 4.5 and 6.5 — the board hid exactly the rows where the disagreement
    # was biggest, which are the only rows worth a second look.
    names = {g[s]["starter"] for g, r in zip(games, out)
             if not r["why"] for s in ("away", "home")}
    mids = {stat: _mids(stat, d, {(nm, ln) for nm in names for ln in lines})
            for stat, lines in (("k", K_LINES), ("outs", OUTS_LINES))}

    blocks, declined = [], []
    for g, r in zip(games, out):
        a, h = g["away"], g["home"]
        tag = f"{a['abbr']} @ {h['abbr']}"
        if r["why"]:
            declined.append((tag, f"{a['starter']} / {h['starter']}",
                             r["why"]))
            continue
        b = {"tag": tag, "g": g, "r": r, "rows": []}
        for label, key in (("total", "total"), (f"{a['abbr']} total",
                           "away"), (f"{h['abbr']} total", "home")):
            lines = TOTAL_LINES if key == "total" else TEAM_LINES
            keep = 3 if key == "total" else 2
            for ln, p in _rungs(r[key], lines, band, keep=keep):
                b["rows"].append(("tot", label, ln, p, None, ""))
        for ln, p in _rungs(r["f5"], F5_LINES, band):
            b["rows"].append(("tot", "F5 total", ln, p, None, ""))
        for s in ("away", "home"):
            name = g[s]["starter"]
            pa = (pr.get(name) or {}).get("pa")
            confirmed = bool((h if s == "away" else a).get("lineup"))
            note = "" if confirmed else "proj lineup"
            # THIN: under 60% of the priced rate is his own record; a gap
            # here can be OUR SHRINKAGE rather than his talent (BETTING.md).
            if pa and slate.shrink_weight(pa) < slate.THIN_WEIGHT:
                note = (note + "  " if note else "") + "THIN"
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
                    b["rows"].append(
                        (stat, name, ln, p, mids[stat].get((name, ln)),
                         (note + "  " if note else "") + xtra
                         if xtra or note else ""))
        blocks.append(b)

    return {"date": d, "n": n, "band": band, "blocks": blocks,
            "declined": declined}


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
    if payload["declined"]:
        print("DECLINED — never filled with a league-average arm:")
        for tag, sp, why in payload["declined"]:
            print(f"  {tag:<12}{sp[:38]:<40}{why}")
        print()
    print(f"outs corrected ({MEASURED_ON}); raw in note. K beats the OPEN"
          " only — bet early or not.")
    print("Totals Jul/Aug ran ~0.15-0.20 light a side (unshipped month"
          " term); Sept unmeasured.")
    print("Re-run after lineups post: a projected nine has cost half an"
          " edge before.")


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    d = args[0] if args else _date.today().isoformat()
    n = int(args[1]) if len(args) > 1 else 20000
    band = None if "--all" in argv else BAND
    print_board(build(d, n=n, band=band))


if __name__ == "__main__":
    main(sys.argv[1:])
