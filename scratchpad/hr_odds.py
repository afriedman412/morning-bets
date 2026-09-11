"""Does this hitter go deep tonight? — the question, asked directly.

    venv/bin/python -m scratchpad.hr_odds                    # tonight
    venv/bin/python -m scratchpad.hr_odds 2026-09-11
    venv/bin/python -m scratchpad.hr_odds --team NYY
    venv/bin/python -m scratchpad.hr_odds --who "Aaron Judge"
    venv/bin/python -m scratchpad.hr_odds --sims 40000

WHAT THIS IS AND IS NOT A REBUILD OF. Nothing here models anything. The
engine ALREADY tracks home runs per batter — `GameResult.away_bats` /
`home_bats`, `{batter: {"r","rbi","h","tb","hr"}}`, folded over every arm
that pitched — and `slate.simulate_slate_game` already turns a DATE into
two real clubs with real lineups, the real bullpen, the park, the weather
and the plate umpire. This file runs that and counts.

So the answer carries everything the simulation carries, and the list is
worth reading because the ranking is not the hitters' own home run rates:
the opposing STARTER's air-ball share (`sim.AIR_HR_PIT`, shipped
2026-09-10), the platoon cell — a left-handed bat loses 22% of his home
run rate against a left-handed arm — the park, the temperature, the wind,
times through the order, and which relievers he is likely to see late.

WHAT IT IS WORTH, measured rather than asserted. The battery's `hrbat`
rows score exactly this number against what happened, four folds, 62,681
batter-games: the top decile of this prediction goes deep in ~21% of games
and the bottom decile in ~6.6%, and the claimed spread lands inside one se
of the delivered one in 2023, 2024 and 2025. **2026 IS THE EXCEPTION AND
IT IS THE SEASON BEING PRICED**: the model runs ~10% hot on this number in
2026 (`hrbat.p_hr_level` +3.9), concentrated in the hitters it likes most,
so treat a top-of-board number as the top of a range. That is TODO item
27 and it is not fixed.

**A PROJECTED LINEUP IS A GUESS AND THE OUTPUT SAYS SO.** `slate.py`'s
own rule is that a confirmed lineup is REQUIRED for a batter prop, and
this is a batter-prop tool. Measured on 1,072 club-games from 2026-08-01:
the projected nine gets 7.02 of 9 right on average and is fully correct
5.5% of the time, so about two names per club are wrong before lineups
post. Those rows are marked `~` and the header counts them. RE-RUN AFTER
LINEUPS POST — that is when this matches the backtest, because the
backtest replayed games whose nines were known.

THE NUMBER IS P(AT LEAST ONE), not expected home runs — "does he go deep"
is a yes/no, and the two differ by the multi-homer games. Both print.
"""
from __future__ import annotations

import multiprocessing as mp
import sys
import time
from collections import defaultdict

from src.context import gamestate, sim, slate
from src.context.sources import rates as rate_src, weather

N_SIMS = 20000
_CTX: dict = {}


def american(p: float) -> str:
    """Fair American odds for a probability. No vig, no market."""
    if p <= 0 or p >= 1:
        return "--"
    return f"+{round(100 * (1 - p) / p)}" if p < 0.5 \
        else f"-{round(100 * p / (1 - p))}"


def _one(i: int) -> dict:
    """One slate game, `n` draws, home runs counted per batter."""
    c = _CTX
    g = c["games"][i]
    try:
        res, why = slate.simulate_slate_game(
            g, c["d"], c["lg"], c["pr"], c["br"], c["league_bats"],
            c["pens"], n_sims=c["n"])
    except Exception as e:            # one bad game must not sink the slate
        return {"why": f"{type(e).__name__} {e}", "i": i}
    if not res:
        return {"why": why, "i": i}
    # THE CROSSING, and it is the one thing here that can silently invert:
    # `away_bats` is the AWAY TEAM's hitters, matching `away` being runs
    # SCORED by the away club. Getting this backwards would hand every
    # hitter the wrong opposing pitcher and still print a plausible board.
    out: dict = {}
    for side in ("away", "home"):
        acc: dict = defaultdict(lambda: [0, 0])
        for r in res:
            for nm, d in getattr(r, f"{side}_bats").items():
                acc[nm][0] += d["hr"] > 0
                acc[nm][1] += d["hr"]
        out[side] = {nm: (v[0] / len(res), v[1] / len(res))
                     for nm, v in acc.items()}
    # CONFIRMED OR PROJECTED, per club. `slate.slate` fills `lineup`
    # only when the feed has posted one; `simulate_slate_game` falls back
    # to `projected_lineup` otherwise, and THAT IS A GUESS — measured on
    # 1,072 club-games from 2026-08-01: the projected nine gets 7.02 of 9
    # right on average and is fully correct 5.5% of the time. `slate.py`
    # says so in `projected_lineup`'s own docstring ("assemble treats a
    # confirmed lineup as REQUIRED for batter props") and this file is a
    # batter-prop tool, so it must not print a name without saying which
    # kind of nine it came from.
    conf = {side: bool((g.get(side) or {}).get("lineup"))
            for side in ("away", "home")}
    return {"why": None, "i": i, "bats": out, "n": len(res), "conf": conf}


def build(d: str, n: int = N_SIMS) -> list[dict]:
    lg = sim.league()
    games = [g for g in slate.slate(d)
             if (g.get("away") or {}).get("starter")
             and (g.get("home") or {}).get("starter")]
    _CTX.update(
        d=d, n=n, games=games, lg=lg,
        # `before=d` — never a start's own day, the same rule the board
        # runs under. A rate that has already seen tonight is not a
        # prediction of tonight.
        pr=rate_src.pitcher_rates(lg, before=d),
        br=rate_src.batter_rates(lg, before=d),
        pens=rate_src.bullpens(lg, before=d),
        league_bats=sim.BatterRates(
            name="league", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
            hr_pct=lg["hr_pct"], babip=lg["babip"]))
    with mp.get_context("fork").Pool(
            max(1, min(len(games) or 1, (mp.cpu_count() or 2) - 1))) as pool:
        return pool.map(_one, range(len(games)))


def rows(d: str, n: int = N_SIMS) -> tuple[list, list]:
    """(one row per hitter, declined games).

    NEVER PRICE A GAME IN PROGRESS, and the gate is PER GAME rather than
    per date — half a slate can be under way while the late games have
    not thrown a pitch. `gamestate.is_pregame` takes a MATCHUP and not a
    date; handing it a date makes it look up a matchup that does not
    exist and quietly return False for everything, which is what the
    first version of this file did.
    """
    out = build(d, n)
    live = gamestate.pregame_game_ids(d)
    # THE SAME LOOKUP `slate.simulate_slate_game` USES, and it has to be.
    # `weather.by_game()` reads the stored table, which only holds games
    # that have already been played — on a FUTURE date it returns nothing
    # and this column printed "--F" and an air multiplier of 1.000 while
    # the simulation behind it was using the real forecast. A display
    # that disagrees with the engine is worse than no display: it reads
    # as "the weather is neutral tonight" rather than as "not loaded".
    wx = {r["game_id"]: r for r in weather.fetch_date(d)}
    hitters, declined = [], []
    for r in out:
        g = _CTX["games"][r["i"]]
        a, h = g["away"], g["home"]
        if r["why"]:
            declined.append((f"{a['abbr']} @ {h['abbr']}", r["why"]))
            continue
        if live and g.get("game_id") not in live:
            declined.append((f"{a['abbr']} @ {h['abbr']}",
                             "under way or final — not pregame"))
            continue
        w = wx.get(g.get("game_id")) or {}
        air = sim.air_hr_mult(w.get("temp_f"), w.get("carry"),
                              w.get("wind_mph"))
        for side, opp in (("away", "home"), ("home", "away")):
            for nm, (p, mean) in r["bats"][side].items():
                hitters.append({
                    "confirmed": r["conf"][side],
                    "name": nm, "team": g[side]["abbr"],
                    "opp_sp": g[opp]["starter"], "p": p, "mean": mean,
                    "park": g.get("venue") or g.get("venue_id"),
                    "temp": w.get("temp_f"), "wind": w.get("wind_mph"),
                    "carry": w.get("carry"), "air": air,
                    "tag": f"{a['abbr']} @ {h['abbr']}"})
    hitters.sort(key=lambda x: -x["p"])
    return hitters, declined


def main(argv):
    date = next((a for a in argv if a[:1].isdigit()), None)
    if not date:
        import datetime as dt
        date = dt.date.today().isoformat()
    n = N_SIMS
    team = who = None
    for i, a in enumerate(argv):
        if a == "--sims":
            n = int(argv[i + 1])
        elif a == "--team":
            team = argv[i + 1].upper()
        elif a == "--who":
            who = argv[i + 1].lower()
    t = time.monotonic()
    hitters, declined = rows(date, n)
    if not hitters:
        print(f"  {date}: nothing priceable.")
    sel = [x for x in hitters
           if (not team or x["team"] == team)
           and (not who or who in x["name"].lower())]
    print(f"\n  DOES HE GO DEEP — {date}, {n:,} simulated games each\n")
    n_proj = sum(not x["confirmed"] for x in sel)
    if n_proj:
        print(f"    !! {n_proj} of {len(sel)} hitters are on a PROJECTED "
              "lineup, not a posted one. The projected nine gets 7.02 of "
              "9 right\n       on average and is fully correct 5.5% of "
              "the time (1,072 club-games, 2026-08).\n       Roughly two "
              "names per club are wrong. RE-RUN ONCE LINEUPS POST.\n")
    print(f"    {'hitter':<24}{'tm':<5}{'opposing starter':<22}"
          f"{'P(HR)':>8}{'fair':>8}{'xHR':>7}{'air':>7}  matchup")
    for x in sel[:60]:
        wind = f"{x['wind']}mph" if x["wind"] is not None else "--"
        flag = " " if x["confirmed"] else "~"
        print(f"   {flag}{x['name'][:23]:<24}{x['team']:<5}"
              f"{(x['opp_sp'] or '?')[:21]:<22}{x['p']:>8.1%}"
              f"{american(x['p']):>8}{x['mean']:>7.3f}{x['air']:>7.3f}"
              f"  {x['tag']} {x['temp'] or '--'}F {wind}")
    if len(sel) > 60:
        print(f"    ... {len(sel) - 60} more")
    for tag, why in declined:
        print(f"    DECLINED {tag}: {why}")
    print(f"\n  {len(sel)} hitters, {time.monotonic() - t:.0f}s. "
          "P(HR) is at least one; xHR is expected home runs. "
          "`~` = projected lineup.")
    print("  2026 caveat: the model runs ~10% hot on this number in the "
          "current season (TODO 27). Read the top of the board as a "
          "range, not a point.")


if __name__ == "__main__":
    main(sys.argv[1:])
