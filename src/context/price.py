"""Price today's board with the simulator and compare to Kalshi.

READ THIS AS A DEFECT REPORT BEFORE READING IT AS AN EDGE. Nearly every
large divergence this project has chased turned out to be our own bug —
relief appearances contaminating a starter's average, outcome leakage in the
first CLV pass, a starter heuristic that deleted the left tail. The market
prices the consensus construction and prices it well. A 30-point gap is
overwhelmingly more likely to mean we resolved the wrong pitcher, or built a
lineup out of last week's bench, than that Kalshi is wrong.

WHAT THIS IS AND IS NOT EVIDENCE OF. The simulator is calibrated — measured
Brier skill of 13-20% against the base rate on K lines, bias under 1.6% —
which means its probabilities are honest. That is a precondition for
comparing to a price and not a substitute for it. A perfectly calibrated
model that agrees with the book everywhere earns nothing; the only thing
worth looking at is where an honest number and a real price disagree, and
even then the first question is which of them is broken.

Lineups are PROJECTED, not confirmed, when run in the morning. That is the
largest source of error here and it is flagged per row.
"""
from __future__ import annotations

import json
import random
import urllib.request
from datetime import date, timedelta

from src import db, kalshi, roster
from src.context import calibrate, game, gamestate, sim
from src.context.sources import rates as rate_src

BASE = "https://statsapi.mlb.com/api/v1"
TIMEOUT = 25
#: Simulations per market. Monte Carlo error at p=0.5 is sqrt(.25/n), so
#: 8,000 gives about +/-0.6 points — comfortably below any gap worth acting
#: on, and the whole slate still prices in well under a minute.
N_SIMS = 8000
#: Days of recent playing time used to project a lineup when none is posted.
LINEUP_WINDOW = 21

# ── who we are willing to price ────────────────────────────────────────
#
# The first slate priced against Kalshi produced a 50-point gap on Lake
# Bachar — 5 starts in 24 appearances, averaging 7.2 outs. He is an OPENER,
# and the simulator gave him a full starter's leash and ran him to sixteen
# outs. Matt Wilkinson had SEVEN batters faced on record, got league-average
# rates by shrinkage, and came out at 96% on over 8.5 outs against a market
# at 49.5%.
#
# Neither is a calibration miss. Both are the model being asked a question
# it has no basis to answer and answering confidently anyway. Refusing to
# price is the correct output, and saying so out loud beats emitting a
# number that looks like the others.

#: Starts on the season before this pitcher's own history means anything.
MIN_STARTS = 3
#: Batters faced before his rates are his rather than the league's.
MIN_BF = 80
#: Average outs per start below which he is an opener or a bulk arm, not
#: someone a book offers a normal starter line on.
MIN_AVG_OUTS = 11.0
#: Share of appearances that must be starts. A swingman's rates describe
#: neither role.
MIN_START_SHARE = 0.5


def slate(date_str: str) -> list[dict]:
    """Today's games with probable starters, venue and both club codes."""
    url = (f"{BASE}/schedule?sportId=1&date={date_str}"
           f"&hydrate=probablePitcher,venue,lineups,team")
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
        d = json.loads(r.read())
    out = []
    for day in d.get("dates") or []:
        for g in day.get("games") or []:
            t = g.get("teams") or {}
            lu = g.get("lineups") or {}
            row = {
                "game_id": f"mlb-{g.get('gamePk')}",
                "venue_id": (g.get("venue") or {}).get("id"),
                "status": ((g.get("status") or {}).get("detailedState")),
                "start_utc": g.get("gameDate"),
            }
            for side in ("away", "home"):
                s = t.get(side) or {}
                pp = s.get("probablePitcher") or {}
                row[side] = {
                    # `abbreviation` only appears when the team is hydrated;
                # the bare schedule payload carries id and name alone, and
                # a None here silently empties every projected lineup.
                "abbr": ((s.get("team") or {}).get("abbreviation")
                         or (s.get("team") or {}).get("teamCode")),
                    "starter": pp.get("fullName"),
                    "starter_id": pp.get("id"),
                    "lineup": [p.get("fullName")
                               for p in (lu.get(f"{side}Players") or [])],
                }
            out.append(row)
    return out


def projected_lineup(team_abbr: str, as_of: str, conn=None) -> list[str]:
    """The nine most-used hitters for a club, most recent window first.

    Used only when no lineup is posted. `assemble` treats a confirmed
    lineup as required for batter props for exactly this reason — a
    projection is a guess — but for a PITCHER prop the identity of the
    eighth hitter moves the answer very little, so a projection is
    proportionate here where it would not be there.
    """
    cut = (date.fromisoformat(as_of)
           - timedelta(days=LINEUP_WINDOW)).isoformat()
    q = """
      select mb.player_name nm, sum(mb.ab + mb.bb) pa
      from mlb_batting mb join games g on g.game_id = mb.game_id
      where g.sport = 'mlb' and g.status = 'Final'
        and mb.team = ? and g.date >= ? and g.date < ?
      group by mb.player_name order by pa desc limit 9
    """

    def _run(c):
        return [r["nm"] for r in c.execute(q, (team_abbr, cut, as_of))]
    if conn is not None:
        return _run(conn)
    with db.connect() as c:
        return _run(c)


_PROFILE_Q = """
  select sum(case when p.is_starter = 1 then 1 else 0 end) gs,
         count(*) app,
         avg(case when p.is_starter = 1 then p.outs_recorded end) avg_outs
  from mlb_pitching p join games g on g.game_id = p.game_id
  where p.player_name = ? and g.sport = 'mlb' and g.status = 'Final'
    and g.date < ?
"""


def priceable(name: str, pa: int, as_of: str, conn=None):
    """(ok, reason). Why we will or will not put a number on this pitcher."""
    def _run(c):
        return dict(c.execute(_PROFILE_Q, (name, as_of)).fetchone())
    if conn is not None:
        r = _run(conn)
    else:
        with db.connect() as c:
            r = _run(c)
    gs, app, avg = r["gs"] or 0, r["app"] or 0, r["avg_outs"]
    if gs < MIN_STARTS:
        return False, f"only {gs} start(s) on record"
    if pa < MIN_BF:
        return False, f"only {pa} batters faced"
    if avg is not None and avg < MIN_AVG_OUTS:
        return False, f"averages {avg:.1f} outs a start — opener"
    if app and gs / app < MIN_START_SHARE:
        return False, f"{gs}/{app} appearances are starts — swingman"
    return True, ""


def _build(names, br, league_bats):
    out = []
    for nm in names:
        b = br.get(nm)
        out.append(sim.BatterRates(
            name=nm, k_pct=b["k_pct"], bb_pct=b["bb_pct"],
            hr_pct=b["hr_pct"], babip=b["babip"], pa=b["pa"])
            if b else league_bats)
    return out


def simulate_slate_game(g, d, lg, pr, br, league_bats, pens, n_sims=N_SIMS,
                        seed=0):
    """`n_sims` simulated games for one slate matchup. -> (results, reason).

    BOTH STARTERS OR NEITHER, and that is the whole point of this function.
    Until 2026-08-25 this module priced a pitcher through `sim.simulate`,
    which modelled ONE PITCHING SIDE IN ISOLATION: it could not see its own
    team's runs, so the margin terms on the hook were structurally
    unreachable, and it was a different model from the one every calibration
    table in the notes was produced on. There is one engine now.

    A missing opposing starter is a DECLINE, not a league-average stand-in.
    Inventing the other club invents the score, and the score is what the
    hook and the bullpen are conditioned on. Same posture the module already
    takes on openers and live games: say nothing rather than emit a number
    that looks like the others.

    EVERY BET HAS TWO SIDES, so this is also cheaper than what it replaces.
    Both starters come out of ONE simulated game — `away_sp` and `home_sp`
    off the same `GameResult` — where the old path simulated each pitcher
    separately and paid twice for the same matchup.

    NOTE WHAT `priceable` IS AND IS NOT APPLIED TO. It gates the pitcher
    being QUOTED, and it is `price_slate`'s job, not this one's. An opener
    on the other side is still a real opponent and gets simulated — with a
    starter's hook, which is a known and recorded limitation ("openers as a
    population"). Refusing to simulate him would decline his opponent's
    market too, which is a worse answer than a slightly long opposing start.
    """
    if g["status"] not in gamestate.PREGAME_STATES:
        return None, f"game is {g['status']} — never price a live one"

    specs = {}
    for side, opp in (("away", "home"), ("home", "away")):
        s, o = g[side], g[opp]
        name = s["starter"]
        if not name:
            return None, f"no probable starter for {s['abbr']}"
        p = pr.get(name)
        if not p:
            return None, f"no rates on record for {name}"
        names = o["lineup"] or projected_lineup(o["abbr"], d)
        if len(names) < 9:
            return None, f"could not build a lineup for {o['abbr']}"
        # NAMED BY WHO FACES IT. `faces` is the OPPOSING nine — the batters
        # this pitcher has to get out. `a_nine` read as "the away team's
        # nine", held the opposite, and put seven modules on the wrong
        # lineup for eight days.
        faces = calibrate.adjust_lineup(_build(names, br, league_bats),
                                        side == "home")
        specs[side] = (sim.PitcherRates(
            name=name, k_pct=p["k_pct"], bb_pct=p["bb_pct"],
            hr_pct=p["hr_pct"], babip=p["babip"], pa=p["pa"]), faces,
            s["abbr"])

    park = (calibrate.park_for(g["venue_id"])
            if calibrate.USE_PARK else None)
    rng = random.Random(seed)
    out = []
    for _ in range(n_sims):
        sides = {}
        for side in ("away", "home"):
            pitcher, faces, abbr = specs[side]
            # `hook=None` with the leash on is what `calibrate.replay` does:
            # `build_side` calls `sim.for_start` itself, so the club and
            # per-pitcher offsets arrive by the one code path that is tested.
            sd = game.build_side(pitcher, pens.get((abbr or "").upper(), []),
                                 faces, None, rng, team=abbr)
            sides[side] = sd
        if calibrate.HOME_HOOK:
            h = sides["home"].hook
            sides["home"].hook = sim.Hook(**{
                **h.__dict__,
                "team_offset": h.team_offset + calibrate.HOME_HOOK})
        out.append(game.simulate_game(sides["away"], sides["home"], lg, rng,
                                      park=park))
    return out, ""


def starter_line(results, is_home):
    """The starter's simulated lines for one side of the matchup."""
    return [(r.home_sp if is_home else r.away_sp) for r in results]


def price_slate(date_str: str | None = None, stats=("k", "outs"),
                n_sims: int = N_SIMS, verbose: bool = True) -> list[dict]:
    """Every Kalshi market for the date, priced by simulation."""
    d = date_str or date.today().isoformat()
    lg = sim.league()
    # Rates strictly before today: a start cannot inform its own price.
    pr = rate_src.pitcher_rates(lg, before=d)
    br = rate_src.batter_rates(lg, before=d)
    league_bats = sim.BatterRates(name="league", k_pct=lg["k_pct"],
                                  bb_pct=lg["bb_pct"], hr_pct=lg["hr_pct"],
                                  babip=lg["babip"])

    games = slate(d)
    pens = rate_src.bullpens(lg, before=d)
    by_pitcher: dict[str, dict] = {}
    for g in games:
        for side, opp in (("away", "home"), ("home", "away")):
            s, o = g[side], g[opp]
            if not s["starter"]:
                continue
            names = o["lineup"] or projected_lineup(o["abbr"], d)
            by_pitcher[s["starter"]] = {
                "game": g,
                "game_id": g["game_id"], "venue_id": g["venue_id"],
                "team": s["abbr"], "opp": o["abbr"],
                "is_home": side == "home",
                "lineup": names,
                "confirmed": bool(o["lineup"]),
                "status": g["status"], "start_utc": g["start_utc"],
            }
    if verbose:
        conf = sum(1 for v in by_pitcher.values() if v["confirmed"])
        print(f"{d}: {len(games)} games, {len(by_pitcher)} probable starters,"
              f" {conf} with a confirmed opposing lineup")

    rows: list[dict] = []
    skipped: dict[str, str] = {}
    #: One simulated set of games per MATCHUP, not per pitcher — both
    #: starters' lines come off the same `GameResult`, and the k line and the
    #: outs line for one arm are read off the same draws.
    sims: dict[str, list] = {}
    for stat in stats:
        series = kalshi.SERIES_BY_STAT.get(stat)
        if not series:
            continue
        for m in kalshi.markets(series):
            tk = m["ticker"]
            if kalshi.ticker_date(tk) != d:
                continue
            parsed = kalshi._parse(m)
            if not parsed:
                continue
            name, threshold = parsed
            line = threshold - 0.5
            ctx = by_pitcher.get(name)
            if not ctx:
                # Resolve through the roster before giving up — Kalshi and
                # statsapi do not always spell a name the same way.
                pid = roster.player_id(name)
                ctx = next((v for k, v in by_pitcher.items()
                            if roster.player_id(k) == pid and pid), None)
            if not ctx:
                continue
            p = pr.get(name)
            if not p:
                continue
            ok, why = priceable(name, p["pa"], d)
            if not ok:
                skipped[name] = why
                continue

            yes_bid, yes_ask = kalshi.book(tk)
            if yes_bid is None or yes_ask is None:
                continue
            if (yes_ask - yes_bid) > kalshi.MAX_SPREAD:
                continue
            mkt = (yes_bid + yes_ask) / 2

            gid = ctx["game_id"]
            if gid not in sims:
                # The pregame guard lives in here now. `gamestate.is_pregame`
                # takes a MATCHUP and does its own fetch; the detailed status
                # is already on the schedule payload, so it is checked
                # directly rather than once per market. Unknown resolves to
                # NOT pregame: a stale number costs little, a live one writes
                # fiction nothing downstream can detect.
                res, whynot = simulate_slate_game(
                    ctx["game"], d, lg, pr, br, league_bats, pens,
                    n_sims=n_sims)
                sims[gid] = res
                if res is None:
                    skipped[name] = whynot
            if sims[gid] is None:
                continue

            res = starter_line(sims[gid], ctx["is_home"])
            ours = sim.prob_over(res, "k" if stat == "k" else "outs", line)
            se = (ours * (1 - ours) / n_sims) ** 0.5
            rows.append({
                "stat": stat, "player": name, "line": line, "ticker": tk,
                "ours": ours, "market": mkt, "gap": ours - mkt, "se": se,
                "spread": yes_ask - yes_bid,
                "opp": ctx["opp"], "home": ctx["is_home"],
                "confirmed_lineup": ctx["confirmed"],
                "pitcher_pa": p["pa"],
            })
    rows.sort(key=lambda r: -abs(r["gap"]))
    if verbose and skipped:
        print(f"declined to price {len(skipped)} pitcher(s):")
        for nm, why in sorted(skipped.items()):
            print(f"    {nm[:24]:<26}{why}")
    return rows


def report(rows: list[dict], top: int = 30) -> None:
    if not rows:
        print("no priceable markets")
        return
    gaps = [abs(r["gap"]) for r in rows]
    mean_signed = sum(r["gap"] for r in rows) / len(rows)
    print(f"\n{len(rows)} markets priced   "
          f"mean |gap| {sum(gaps)/len(gaps):.3f}   "
          f"median {sorted(gaps)[len(gaps)//2]:.3f}   "
          f"mean signed {mean_signed:+.3f}")
    if abs(mean_signed) > 0.04:
        print("  ** a large SIGNED mean means we disagree with the whole "
              "board in one direction — that is a defect, not an edge **")
    print(f"\n  {'stat':<5}{'player':<20}{'bet':<12}{'ours':>7}{'mkt':>7}"
          f"{'gap':>8}{'+/-':>6}  opp  lineup")
    for r in rows[:top]:
        flag = "conf" if r["confirmed_lineup"] else "PROJ"
        print(f"  {r['stat']:<5}{r['player'][:18]:<20}"
              f"{f'o{r['line']:g}':<12}{r['ours']:>7.3f}{r['market']:>7.3f}"
              f"{r['gap']:>+8.3f}{r['se']:>6.3f}  {r['opp']:<4} {flag}")


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    report(price_slate(d))
