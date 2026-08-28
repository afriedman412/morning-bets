"""Price ONE user-supplied card: moneylines, game totals, strikeout props.

    venv/bin/python -m scratchpad.card [DATE] [n_sims]

`tonight.py` prints totals and `price.py` prints pitcher markets, but a card
mixes the two and a moneyline is in NEITHER — `GameResult` carries `away`/
`home` runs, so a win probability is one comparison away and nothing was
reading it. This walks `price.simulate_slate_game` exactly as `tonight.py`
does, so a moneyline, a total and a starter's K line on the same game come
out of the SAME simulated draws and cannot contradict each other.

READ THE OPERATOR'S PAGE IN `RESUME.md` BEFORE USING A NUMBER FROM HERE.
The two that bite: 20,000 sims minimum before comparing to a price, and the
model is ~4% light on runs in July/August because the seasonal home-run term
is measured and NOT shipped.
"""
from __future__ import annotations

import statistics as st
import sys
from datetime import date as _date

from src.context import price, sim
from src.context.sources import rates as rate_src


def american(p: float) -> str:
    if p <= 0 or p >= 1:
        return "-"
    return f"{-100 * p / (1 - p):+.0f}" if p > 0.5 else f"{100 * (1 - p) / p:+.0f}"


def implied(odds: float) -> float:
    """American odds -> break-even probability (with the vig still in it)."""
    return 100.0 / (odds + 100.0) if odds > 0 else -odds / (-odds + 100.0)


#: Set once in the parent and inherited by every FORKED child. A Pool
#: cannot pickle a closure, and a `spawn` child would re-import at DEFAULT
#: globals and silently revert every USE_* flag.
_CTX: dict = {}

TOTAL_LINES = (6.5, 7.5, 8.5, 9.5, 10.5)
K_LINES = (4.5, 5.5, 6.5, 7.5, 8.5)


def _summarise(i):
    """Simulate game `i` and return a SMALL summary, not 20,000 results.

    Reducing in the child matters: piping the raw `GameResult` list back
    costs more than the simulation for a card this size.
    """
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
    tot = [r.away + r.home for r in res]
    f5 = [sum(r.prefix_side[5]) for r in res
          if getattr(r, "prefix_side", None) and 5 in r.prefix_side]
    # A tie cannot settle a moneyline. Extra innings are simulated, so ties
    # are rare rather than absent; split them so the two sides sum to one
    # instead of silently favouring the home team.
    hw = sum(1 for r in res if r.home > r.away)
    tie = sum(1 for r in res if r.home == r.away)
    n = len(res)
    out = {
        "why": None,
        "total": st.mean(tot),
        # A MISSING F5 IS None, NEVER 0.00 — it read zero for every game on
        # the board until 2026-08-28 and a zero hides that far better than
        # a dash would have.
        "f5": st.mean(f5) if f5 else None,
        "sd": st.pstdev(tot),
        "tie": tie / n,
        "p_home": (hw + 0.5 * tie) / n,
        "over": {ln: sum(1 for t in tot if t > ln) / n for ln in TOTAL_LINES},
        "k": [],
    }
    # STRIKEOUT PROPS off the SAME draws, so a K line and the total it sits
    # inside cannot contradict each other. `StartResult.k` is the starter's
    # own line; relievers' are discarded on the arm change, which does not
    # matter for a starter prop.
    for side in ("away", "home"):
        ks = [getattr(r, f"{side}_sp").k for r in res]
        out["k"].append({
            "name": g[side]["starter"],
            "mean": st.mean(ks),
            "sd": st.pstdev(ks),
            "over": {ln: sum(1 for k in ks if k > ln) / n for ln in K_LINES},
        })
    return out


def main(argv):
    d = argv[0] if argv else _date.today().isoformat()
    n = int(argv[1]) if len(argv) > 1 else 400
    games = price.slate(d)
    lg = sim.league()
    only = {s.upper() for s in argv[2:]}
    if only:
        games = [g for g in games
                 if {(g.get("away") or {}).get("abbr"),
                     (g.get("home") or {}).get("abbr")} & only]
    _CTX.update(
        d=d, n=n, games=games, lg=lg,
        pr=rate_src.pitcher_rates(lg),
        br=rate_src.batter_rates(lg),
        pens=rate_src.bullpens(lg),
        league_bats=sim.BatterRates(
            name="league", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
            hr_pct=lg["hr_pct"], babip=lg["babip"]),
    )
    print(f"  {d}: {len(games)} games, {n} sims each\n")

    import multiprocessing as mp
    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, min(len(games), (mp.cpu_count() or 2) - 1))) as pool:
        out = pool.map(_summarise, range(len(games)))

    for g, r in zip(games, out):
        a, h = g.get("away") or {}, g.get("home") or {}
        tag = f"{a.get('abbr')} @ {h.get('abbr')}"
        sp = f"{a.get('starter') or '-'} / {h.get('starter') or '-'}"
        if r["why"]:
            print(f"  {tag:<12}{sp:<44}DECLINED — {r['why']}")
            continue
        f5 = f"{r['f5']:.2f}" if r["f5"] is not None else "-"
        print(f"  {tag:<12}{sp:<44}")
        print(f"      total {r['total']:5.2f}  F5 {f5:>5}"
              f"  sd {r['sd']:4.2f}   ties {r['tie']:.3f}")
        ph = r["p_home"]
        print(f"      ML    {a.get('abbr')} {1 - ph:.3f} ({american(1 - ph)})"
              f"   {h.get('abbr')} {ph:.3f} ({american(ph)})")
        line = "      over  "
        for ln in TOTAL_LINES:
            line += f"{ln}:{r['over'][ln]:.3f} "
        print(line)
        for k in r["k"]:
            row = f"      K {k['name']:<22} mean {k['mean']:5.2f}  "
            for ln in K_LINES:
                row += f"o{ln}:{k['over'][ln]:.3f} "
            print(row)
        print()
    print("  CAVEATS — see the operator's page in RESUME.md:")
    print("   * Full-game totals and moneylines have NEVER been scored")
    print("     against settled prices here. F5 team totals are the product.")
    print("   * July/August runs are biased LOW ~0.15-0.20 per side: the")
    print("     seasonal home-run term is measured and not shipped.")
    print("   * Lineups are PROJECTED unless a card is posted, and that is")
    print("     the weakest link in the whole path.")


if __name__ == "__main__":
    main(sys.argv[1:])
