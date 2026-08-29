"""Does the state of the BULLPEN predict when a starter is removed?

    venv/bin/python -m scratchpad.pen_state [--rebuild]

QUESTION    Conditional on everything the hook already reads, does how much
            a club's relievers have thrown lately — and how good they are —
            change the removal decision? Unit of observation: one real
            starter removal decision.

WHY IT IS THE LIVE LEAD. Both fits on 2026-08-29 found the BOUNDARY curve
takes no in-game state at all: signed margin +0.7 sigma, |margin|
sign-flipping across seasons, strikeout rate -2.1 with no season
individually significant. Meanwhile the boundary share is 0.609 against a
real 0.669 and is the largest unexplained gap left in the model. "Does he
come back out for the seventh" is plausibly not a reaction to the game at
all but a RESOURCE decision — can the manager afford the pen tonight — and
that is the one thing no column here has ever carried.

Neither hook curve takes any bullpen argument. `grep` for fatigue across
`game.py` and `sim.py` returns nothing: the pen is redrawn independently
every game AND every draw, so nothing records that an arm threw yesterday.

HYPOTHESES, ALL SIGNED BEFORE RUNNING. On the BOUNDARY decision:

    pen_pitches_1, pen_pitches_3   NEGATIVE. A pen that threw a lot
                                   recently is a pen the manager wants to
                                   protect, so the starter goes back out.
    arms_1                         NEGATIVE, same mechanism by a different
                                   count.
    days_rest                      POSITIVE. A rested pen is a usable pen.
    pen_strength                   POSITIVE. Confidence in the relief corps
                                   makes the hook quicker — the reason to
                                   leave a starter in is partly that the
                                   alternative is worse.

FALSIFIER: coefficients inside the resolvable band, or signs that do not
hold across the four seasons. Either says the boundary decision is not
about the bullpen and the 0.669 gap needs a different explanation.

THE CONFOUND THAT MATTERS, AND IT RUNS THE WRONG WAY. A club whose pen
threw 120 pitches yesterday probably played a long or losing game
yesterday, which correlates with the club being bad, which correlates with
its STARTER being bad — and a bad starter gets pulled EARLIER. That pushes
`pen_pitches` POSITIVE and therefore works AGAINST the hypothesis. A
negative coefficient survives it; a positive one is uninterpretable.
`leash` (the starter's own recent length) is in the control set to absorb
what it can.

NOT A SIMULATION. This measures real decisions only. Whether it is worth
wiring is a separate question that this does not answer, and a bullpen
model that carries fatigue does not exist yet.
"""
from __future__ import annotations

#: NEVER FIT ON ROWS THAT WILL BE SCORED ON. Same cutoff `shape.py` and
#: `fitf5` evaluate from — one cutoff for the whole project, because two is
#: how one of them drifts. See CLAUDE.md; this was got wrong on 2026-08-29.
HOLDOUT_CUT = "2026-07-01"


def train_only(rows):
    """Rows strictly before the holdout. Call it before ANY fit."""
    return [r for r in rows if r.get("date", "") < HOLDOUT_CUT]


import json
import os
import sys
from collections import defaultdict

import numpy as np

from src import db
from src.context import boundary
from src.context.sources import pbp
from scratchpad.hook_margin import control, fit, power, report, xy

CACHE = "/tmp/pen_usage.json"
ROWS = "/tmp/hook_rows.json"

#: Everything the two curves already read, so the bullpen columns are asked
#: what they ADD. `leash` is in deliberately — see the confound note.
BND_BASE = ("pitches", "runs", "br", "inning", "bf", "tto", "abs_margin",
            "leash")
MID_BASE = ("pitches", "inn_br", "runs", "onbase", "inning", "bf",
            "abs_margin", "leash")


def usage():
    """{(game_id, 'home'|'away'): {relief pitches, arms, per-arm}}.

    `side` is the PITCHING club, matching `boundary.decisions`: on a top
    half the HOME club is in the field, so side 'home' means the home team
    is pitching.
    """
    if os.path.exists(CACHE) and "--rebuild" not in sys.argv:
        return {tuple(k.split("|")): v
                for k, v in json.load(open(CACHE)).items()}
    out: dict = {}
    n = 0
    for gid in pbp.final_games():
        if not pbp.have(gid):
            continue
        data = pbp.fetch(gid)
        if not data:
            continue
        n += 1
        starter: dict = {}
        pit: dict = defaultdict(lambda: defaultdict(int))
        for play in (data.get("allPlays") or []):
            res = play.get("result") or {}
            if (res.get("eventType") or "") in boundary.SKIP:
                continue
            mu = play.get("matchup") or {}
            pid = (mu.get("pitcher") or {}).get("id")
            if not pid:
                continue
            side = "home" if (play.get("about") or {}).get(
                "isTopInning") else "away"
            starter.setdefault(side, pid)
            pit[side][pid] += sum(1 for e in (play.get("playEvents") or [])
                                  if e.get("isPitch"))
        for side, arms in pit.items():
            rel = {str(p): c for p, c in arms.items()
                   if p != starter.get(side)}
            out[(gid, side)] = {"pitches": sum(rel.values()),
                                "arms": len(rel), "per": rel}
        if n % 1000 == 0:
            print(f"  {n} games", flush=True)
    json.dump({f"{g}|{s}": v for (g, s), v in out.items()},
              open(CACHE, "w"))
    return out


def club_games():
    """{team: [(date, game_id, side)]} sorted, plus a game->date map."""
    # ALL SCHEDULED GAMES, not just Final ones. A club's row for TODAY is
    # computed from its PREVIOUS games, so today's game needs a slot in the
    # ordering even though it has not been played. Restricting to Final —
    # which the first version did — left every live slate with no row at
    # all, so the mechanism was inert exactly where it would be bet.
    q = ("select game_id, date, away_team, home_team from games "
         "where sport='mlb' order by date")
    by: dict = defaultdict(list)
    dates: dict = {}
    with db.connect() as c:
        for r in c.execute(q):
            dates[r["game_id"]] = r["date"]
            by[r["away_team"]].append((r["date"], r["game_id"], "away"))
            by[r["home_team"]].append((r["date"], r["game_id"], "home"))
    return by, dates


def build():
    use = usage()
    by, dates = club_games()
    feats: dict = {}
    for team, games in by.items():
        games.sort()
        # SEASON-LEVEL LEAVE-ONE-OUT STRENGTH, so the grouping variable does
        # not contain the game it grades. One game is ~1/162 of the total,
        # so this is a formality rather than a correction — but the day-14
        # home-run finding died on exactly this kind of formality.
        season_p: dict = defaultdict(int)
        for d, g, s in games:
            u = use.get((g, s))
            if u:
                season_p[d[:4]] += u["pitches"]
        season_n: dict = defaultdict(int)
        for d, _g, _s in games:
            season_n[d[:4]] += 1
        for i, (d, g, s) in enumerate(games):
            prev = games[max(0, i - 3):i]
            u1 = use.get((prev[-1][1], prev[-1][2])) if prev else None
            p3 = sum((use.get((pg, ps)) or {}).get("pitches", 0)
                     for _pd, pg, ps in prev)
            # ARMS THAT WORKED ON BACK-TO-BACK DAYS, which is the real
            # unavailability rule managers use — not a pitch total.
            back2 = 0
            if len(prev) >= 2:
                a = set((use.get((prev[-1][1], prev[-1][2])) or
                         {}).get("per", {}))
                b = set((use.get((prev[-2][1], prev[-2][2])) or
                         {}).get("per", {}))
                back2 = len(a & b)
            heavy = sum(1 for v in (u1 or {}).get("per", {}).values()
                        if v >= 20)
            gap = 1
            if prev:
                try:
                    from datetime import date as _d
                    y1, m1, d1 = (int(x) for x in prev[-1][0].split("-"))
                    y2, m2, d2 = (int(x) for x in d.split("-"))
                    gap = (_d(y2, m2, d2) - _d(y1, m1, d1)).days
                except Exception:
                    gap = 1
            yr = d[:4]
            own = (use.get((g, s)) or {}).get("pitches", 0)
            strength = ((season_p[yr] - own) / max(season_n[yr] - 1, 1))
            # THE MISSING-GROUP RULE, and it has teeth here. `pen_back2`
            # needs the club's last TWO games to be cached. If either is
            # missing the count comes out 0 — "nobody is unavailable",
            # which reads as a FULLY RESTED pen. That is a WRONG value, not
            # a neutral one, and this project's rule is that an unknown
            # resolves to league-neutral rather than to a guess that moves
            # the estimate the wrong way. So the row is not emitted at all
            # and `sim.pen_state` falls through to the baseline.
            if len(prev) < 2 or not all(
                    (pg, ps) in use for _pd, pg, ps in prev[-2:]):
                continue
            feats[(g, s)] = {
                "pen_pitches_1": (u1 or {}).get("pitches", 0),
                "pen_arms_1": (u1 or {}).get("arms", 0),
                "pen_pitches_3": p3,
                "pen_back2": back2,
                "pen_heavy_1": heavy,
                "pen_rest": min(gap, 5),
                # Pitches a club's pen throws per game, its OTHER games only.
                # A high number is a pen that gets used, which is the
                # closest thing to "the manager trusts it" available without
                # a quality model.
                "pen_load": strength,
            }
    return feats


PEN = ("pen_pitches_1", "pen_arms_1", "pen_pitches_3", "pen_back2",
       "pen_heavy_1", "pen_rest", "pen_load")


def main():
    feats = build()
    rows = json.load(open(ROWS))
    keep = []
    for r in rows:
        f = feats.get((r["game_id"], r["side"]))
        if f:
            keep.append({**r, **f})
    print(f"\n  {len(keep):,} of {len(rows):,} decisions carry bullpen state")
    mid = [r for r in keep if not r["ends_inning"]]
    bnd = [r for r in keep if r["ends_inning"]]
    for f in PEN:
        v = np.array([r[f] for r in keep])
        print(f"    {f:<16} mean {v.mean():>7.2f}  sd {v.std():>6.2f}  "
              f"p10 {np.percentile(v, 10):>6.1f}  p90 "
              f"{np.percentile(v, 90):>6.1f}")

    for name, pop, base in (("BOUNDARY", bnd, BND_BASE),
                            ("MID-INNING", mid, MID_BASE)):
        print(f"\n{'=' * 66}\n{name}  (n {len(pop):,})\n{'=' * 66}")
        power(pop, base, ("pen_pitches_1",), f"{name} pen pitches yesterday")
        print("\n  POSITIVE CONTROL")
        control(pop, base, ("pen_pitches_1",), 0.01, "pen_pitches_1 x0.01")
        report(pop, base, PEN, f"{name} + ALL bullpen columns")

        print(f"\n  --- {name}: PER SEASON, pen_pitches_1 and pen_rest ---")
        for yr in ("2023", "2024", "2025", "2026"):
            sub = [r for r in pop if r["date"][:4] == yr]
            if len(sub) < 5000:
                continue
            X, y = xy(sub, base + ("pen_pitches_1", "pen_rest"))
            b, se = fit(X, y)
            i = len(base)
            print(f"    {yr}  n {len(sub):>7,}   "
                  f"pen_pitches_1 {b[i]:>+9.6f} (z {b[i]/se[i]:>+4.1f})   "
                  f"pen_rest {b[i+1]:>+8.5f} (z {b[i+1]/se[i+1]:>+4.1f})")


if __name__ == "__main__":
    main()
