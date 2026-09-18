"""Re-price slate games whose starter is an ANNOUNCED opener/short start.

The live path cannot see tonight's plan: `game.opener_record` is history
-based, so a rotation arm announced for three innings (or a first-time
opener the role gate misses) is simulated as a full starter, and the named
bulk arm never reaches `build_side(bulk=...)` at all — `slate.py` does not
pass one. This driver is the operator side channel for that announcement,
the same posture as `probables`: OPERATOR INPUT, applied loudly, for one
date.

    venv/bin/python -m scratchpad.reprice_openers DATE \
        AWY@HOM SIDE FX "Bulk Name"  [AWY@HOM SIDE FX "Bulk Name"] ...

FX is the planned outs for the opener (an int — "pitching 3 innings" is 9),
or the literal `pool` for the counted first-time-opener exit curve
(`game.OPENER_POOL_DIST`) when only "he is opening" is known.

What it does per designated side, per draw: builds the side exactly as
`slate.simulate_slate_game` does, passes the bulk arm's rates so
`Side.to_bulk` hands him the ball, overrides `forced_exit_outs` with the
announced plan, and gives the bulk arm his own hook — club base, his own
leash, plus the counted `BULK_OUTS_DELTA` — instead of the opener's.

Output compares every rung the morning board printed for the game (from
`bets/<date>_board.json`) against the re-priced fair, and prints a fresh
K/outs ladder for the opener with live Kalshi mids, because his real
ladder sits far below the lines the morning board kept. The bulk arm gets
no ladder: `GameResult` records the STARTER'S line only, which is also the
line the market settles on.

The starter's printed line stays the OPENER'S (`Side.line` is deliberately
not replaced on handover), so his K/outs rungs here are directly
comparable to Kalshi's market on his name.
"""
from __future__ import annotations

import json
import random
import statistics as st
import sys

from src import roster
from src.context import calibrate, game, leash, sim, slate
from src.context.sources import rates as rate_src
from src.context.sources import weather as weather_src
from scratchpad.board import BAND, K_LINES, _mids, _vol, american, in_band
from scratchpad.outs_adjust import correction

#: The opener's real outs ladder sits far below the board's OUTS_LINES
#: floor of 12.5, so the fresh ladder sweeps the whole range.
FULL_OUTS = tuple(x + 0.5 for x in range(2, 21))


def _pitcher(name: str, pr: dict) -> sim.PitcherRates | None:
    """One arm's PitcherRates, built exactly as `simulate_slate_game` does."""
    p = pr.get(name)
    if not p:
        return None
    try:
        from src.context.sources import battedball
        gb = battedball.gb_pct_map("pit").get(name)
        air = battedball.air_pct_map("pit").get(name)
    except Exception:
        gb = air = None
    return sim.PitcherRates(
        name=name, k_pct=p["k_pct"], bb_pct=p["bb_pct"], hr_pct=p["hr_pct"],
        babip=p["babip"], pa=p["pa"], hand=roster.throws(name) or "",
        gb_pct=gb, air_pct=air)


def reprice(g, d, lg, pr, br, league_bats, pens, des_side, fx_plan,
            bulk_name, n_sims=20000, seed=0):
    """(results, reason) for one matchup with the announced arrangement."""
    specs = {}
    for side, opp in (("away", "home"), ("home", "away")):
        s, o = g[side], g[opp]
        name = s["starter"]
        if not name:
            return None, f"no probable starter for {s['abbr']}"
        p = _pitcher(name, pr)
        if p is None:
            return None, f"no rates on record for {name}"
        names = o["lineup"] or slate.projected_lineup(o["abbr"], d)
        if len(names) < 9:
            return None, f"could not build a lineup for {o['abbr']}"
        faces = calibrate.adjust_lineup(
            slate._build(names, br, league_bats), side == "home")
        hook = sim.for_start(sim.Hook(), s["abbr"], name)
        if side == "home" and calibrate.HOME_HOOK:
            hook = sim.Hook(**{
                **hook.__dict__,
                "team_offset": hook.team_offset + calibrate.HOME_HOOK})
        specs[side] = (p, faces, s["abbr"], hook)

    bulk_rates = _pitcher(bulk_name, pr)
    if bulk_rates is None:
        return None, f"no rates on record for bulk arm {bulk_name}"
    # The bulk arm's OWN hook — club base, his own leash, the counted role
    # delta — built once like the starters' hooks, since `apply_leash=False`
    # stops `build_side` doing it and its internal fallback would hand him
    # the opener's personal leash instead.
    abbr = g[des_side]["abbr"]
    bh = sim.for_start(sim.Hook(), abbr, bulk_name)
    if des_side == "home" and calibrate.HOME_HOOK:
        bh = sim.Hook(**{**bh.__dict__,
                         "team_offset": bh.team_offset + calibrate.HOME_HOOK})
    bh = sim.Hook(**{**bh.__dict__,
                     "team_offset": bh.team_offset
                     + leash.offset_for(game.BULK_OUTS_DELTA)})

    park = (calibrate.park_for(g["venue_id"]) if calibrate.USE_PARK else None)
    wx = {r["game_id"]: r for r in weather_src.fetch_date(d)}
    w = wx.get(g["game_id"]) or {}
    hr_air = sim.air_hr_mult(w.get("temp_f"), w.get("carry"),
                             w.get("wind_mph"))
    ump = (1.0, 1.0)
    if sim.USE_UMP_KBB:
        from src import db
        from src.context.sources import officials as officials_src
        try:
            officials_src.fetch_date(d)
        except Exception:
            pass
        with db.connect() as c:
            r = c.execute("select plate_ump_id from game_officials"
                          " where game_id=?", (g["game_id"],)).fetchone()
        ump = sim.ump_kbb_mult(r["plate_ump_id"] if r else None)

    pool = [o for o, n in sorted(game.OPENER_POOL_DIST.items())
            for _ in range(n)]
    rng = random.Random(seed)
    out = []
    for _ in range(n_sims):
        sides = {}
        for side in ("away", "home"):
            pitcher, faces, sabbr, hook = specs[side]
            sd = game.build_side(
                pitcher, pens.get((sabbr or "").upper(), []), faces, hook,
                rng, team=sabbr, apply_leash=False, date=d,
                bulk=bulk_rates if side == des_side else None)
            if side == des_side:
                sd.bulk_hook = bh
                sd.forced_exit_outs = (
                    pool[rng.randrange(len(pool))] if fx_plan == "pool"
                    else int(fx_plan))
            sides[side] = sd
        out.append(game.simulate_game(sides["away"], sides["home"], lg, rng,
                                      park=park, track=(5,),
                                      hr_air=hr_air, ump_kbb=ump))
    return out, ""


def _p_over(vals, ln):
    push = sum(1 for v in vals if v == ln)
    if push == len(vals):
        return None
    return sum(1 for v in vals if v > ln) / (len(vals) - push)


def _vals_for(bet, g, res):
    """The simulated array a printed rung settles on, from its label."""
    away, home = g["away"]["abbr"], g["home"]["abbr"]
    ap, hp = g["away"]["starter"], g["home"]["starter"]
    parts = bet.rsplit(" ", 1)
    label, ln = parts[0], float(parts[1])
    if label == "total":
        return [r.total for r in res], ln, None
    if label == "F5 total":
        return [r.total_f5 for r in res], ln, None
    if label == f"{away} total":
        return [r.away for r in res], ln, None
    if label == f"{home} total":
        return [r.home for r in res], ln, None
    for nm, sp in ((ap, "away_sp"), (hp, "home_sp")):
        for stat in ("k", "outs"):
            if label == f"{nm} {stat}":
                return ([getattr(getattr(r, sp), stat) for r in res],
                        ln, stat)
    return None, ln, None


def main(argv):
    if len(argv) < 5 or (len(argv) - 1) % 4:
        print(__doc__)
        return 1
    d = argv[0]
    plans = {}
    for i in range(1, len(argv), 4):
        m, side, fx, bulk = argv[i:i + 4]
        if side not in ("away", "home"):
            print(f"side must be away|home, got {side}")
            return 1
        if fx != "pool":
            int(fx)  # fail loudly now, not mid-simulation
        plans[m.upper()] = (side, fx, bulk)

    lg = sim.league()
    pr = rate_src.pitcher_rates(lg, before=d)
    br = rate_src.batter_rates(lg, before=d)
    pens = rate_src.bullpens(lg, before=d)
    league_bats = sim.BatterRates(
        name="league", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
        hr_pct=lg["hr_pct"], babip=lg["babip"])

    stem = d.replace("-", "_")
    board = json.load(open(f"bets/{stem}_board.json"))
    by_code = {f"{b['away']}@{b['home']}": b for b in board["games"]}

    found = {f"{g['away']['abbr']}@{g['home']['abbr']}": g
             for g in slate.slate(d)}
    for code, (side, fx, bulk) in plans.items():
        g = found.get(code)
        if g is None:
            print(f"{code}: not on the {d} slate")
            continue
        opener = g[side]["starter"]
        print(f"\n{code}   {g['away']['starter']} v {g['home']['starter']}")
        print(f"  OPERATOR PLAN: {opener} opens "
              f"({'pooled opener exit' if fx == 'pool' else fx + ' outs'}), "
              f"{bulk} in bulk relief   [{20000:,} sims]")
        res, why = reprice(g, d, lg, pr, br, league_bats, pens,
                           side, fx, bulk)
        if not res:
            print(f"  DECLINED: {why}")
            continue
        morning = by_code.get(code)
        mean = st.mean(r.total for r in res)
        print(f"  mean total {mean:.1f}  (board had {morning['mean']})\n")
        print(f"  {'bet':<26}{'replan':>13}   {'board':>13}  kalshi")
        for row in (morning["rows"] if morning else []):
            vals, ln, stat = _vals_for(row["bet"], g, res)
            if vals is None:
                continue
            p = _p_over(vals, ln)
            if p is None:
                continue
            note = ""
            if stat == "outs":
                raw = p
                p = min(max(p + correction(ln), 0.001), 0.999)
                note = f"raw {american(raw)}"
            old = f"{row['over']:>6} /{row['under']:>6}"
            print(f"  {row['bet']:<26}{american(p):>6} /"
                  f"{american(1 - p):>6}   {old}  "
                  f"{row['kalshi'] or '-':>6}   {note}")
        # The opener's real ladder, with live mids — the board's rungs were
        # chosen around a full start and mostly miss where he now lands.
        sp = "away_sp" if side == "away" else "home_sp"
        for stat, lines in (("k", K_LINES), ("outs", FULL_OUTS)):
            vals = [getattr(getattr(r, sp), stat) for r in res]
            mids = _mids(stat, d, {(opener, ln) for ln in lines})
            print(f"\n  {opener} {stat} ladder (replanned):")
            for ln in lines:
                p = _p_over(vals, ln)
                if p is None:
                    continue
                note = ""
                if stat == "outs":
                    raw = p
                    p = min(max(p + correction(ln), 0.001), 0.999)
                    note = f"raw {american(raw)}"
                mid, vol = mids.get((opener, ln)) or (None, None)
                if not in_band(p, BAND) and mid is None:
                    continue
                if not in_band(p, BAND):
                    note = (note + "  " if note else "") + "off-band"
                if vol is not None:
                    note = (note + "  " if note else "") + _vol(vol)
                print(f"    {stat} {ln:<20}{american(p):>6} /"
                      f"{american(1 - p):>6}  "
                      f"{american(mid) if mid is not None else '-':>6}   "
                      f"{note}")
    print("\nBulk arms carry no ladder: the sim records the starter's line"
          " only, and so does the market.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
