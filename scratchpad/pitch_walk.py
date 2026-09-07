"""ONE PITCHER, ONE GAME, EVERY PITCH — step zero of PLAN-pitch-expectation.

    venv/bin/python -m scratchpad.pitch_walk --pitcher "Dylan Cease"
    venv/bin/python -m scratchpad.pitch_walk --pitcher "Dylan Cease" --game 2

What he threw, to whom, in what count, where, and what happened. No
model, no expectation, no screen — this exists so the ROW is verified by
eye before anything is fitted on three million of them. The house rule
it serves: print the actual names and values first; every input bug this
project has had was found by looking at the row, not the summary.

THE ONE SUBTLETY IN THE FEED, and it would silently corrupt every count
feature: `playEvents[i]["count"]` is the count AFTER that pitch. The
first pitch of an at-bat carries {balls:1} if it was a ball. Pre-pitch
count is tracked here from 0-0 forward, which also handles the foul-with-
two-strikes case for free.

Outcome alphabet, and the ambiguous member is named: ball / called /
whiff / foul / in-play / hbp. FOUL TIP (T) is counted as a FOUL, not a
whiff — the bat touched it and the catcher held it. Statcast's whiff
convention agrees; the row printer shows the raw code so the choice
stays visible.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os

from src import db

BALL = {"B", "*B"}
CALLED = {"C"}
WHIFF = {"S", "W"}
FOUL = {"F", "T", "L"}
INPLAY = {"X", "D", "E"}
HBP = {"H"}
ZONE_X, ZONE_LO, ZONE_HI = 0.83, 1.5, 3.5


def outcome_of(code: str) -> str:
    for name, s in (("ball", BALL), ("called", CALLED), ("whiff", WHIFF),
                    ("foul", FOUL), ("inplay", INPLAY), ("hbp", HBP)):
        if code in s:
            return name
    return "other"


def games_for(name: str, season: int | None = None):
    q = ("select g.game_id gid, g.date d, p.k, p.bb, p.outs_recorded outs"
         " from mlb_pitching p join games g on g.game_id=p.game_id"
         " where g.sport='mlb' and g.status='Final' and p.is_starter=1"
         " and p.player_name=?")
    a = [name]
    if season:
        q += " and substr(g.date,1,4)=?"
        a.append(str(season))
    with db.connect() as c:
        return [dict(r) for r in c.execute(q + " order by g.date", a)]


def pitches(gid: str, name: str):
    """Every pitch this pitcher threw in this game, in order, with the
    PRE-pitch count and the batter he was facing."""
    path = f".cache/pbp/{gid.split('-')[1]}.json.gz"
    if not os.path.exists(path):
        return None
    d = json.load(gzip.open(path))
    rows = []
    pa_i = -1
    for pl in d.get("allPlays") or []:
        mu = pl.get("matchup") or {}
        if ((mu.get("pitcher") or {}).get("fullName")) != name:
            continue
        bat = (mu.get("batter") or {}).get("fullName")
        bid = (mu.get("batter") or {}).get("id")
        hand = ((mu.get("batSide") or {}).get("code") or "?")
        inn = (pl.get("about") or {}).get("inning")
        b = s = 0                       # PRE-pitch count, tracked from 0-0
        n_in_pa = 0
        # PA index, because a consumer splitting a start in half must be
        # able to split it by PLATE APPEARANCE. Splitting by PITCH biases
        # the two halves' COUNT composition against each other (every
        # PA's first pitch is 0-0, so the halves see-saw), which turns a
        # count-dependent quantity's split-half correlation NEGATIVE.
        # Found 2026-09-07 when expected-called/pitch read r = -0.65.
        pa_i += 1
        for ev in pl.get("playEvents") or []:
            if not ev.get("isPitch"):
                continue
            det = ev.get("details") or {}
            pd = ev.get("pitchData") or {}
            br = pd.get("breaks") or {}
            co = pd.get("coordinates") or {}
            code = det.get("code")
            oc = outcome_of(code)
            n_in_pa += 1
            px, pz = co.get("pX"), co.get("pZ")
            rows.append({
                "inning": inn, "batter": bat, "batter_id": bid, "pa": pa_i,
                "bats": hand, "balls": b, "strikes": s, "pa_pitch": n_in_pa,
                "type": (det.get("type") or {}).get("code"),
                "velo": pd.get("startSpeed"), "spin": br.get("spinRate"),
                "ivb": br.get("breakVerticalInduced"),
                "hb": br.get("breakHorizontal"),
                "px": px, "pz": pz,
                # the BATTER's zone as the feed measured it, carried so a
                # consumer can place the pitch against the zone it was
                # actually thrown to (`pitch_e0.region_of`)
                "sz_top": pd.get("strikeZoneTop"),
                "sz_bot": pd.get("strikeZoneBottom"),
                "in_zone": (None if px is None or pz is None else
                            (abs(px) <= ZONE_X and ZONE_LO <= pz <= ZONE_HI)),
                "code": code, "outcome": oc,
                "ev": (ev.get("hitData") or {}).get("launchSpeed"),
                "la": (ev.get("hitData") or {}).get("launchAngle"),
                "pa_result": (pl.get("result") or {}).get("event"),
            })
            # advance the count exactly as the rulebook does
            if oc in ("ball", "hbp"):
                b += 1
            elif oc == "called" or oc == "whiff":
                s += 1
            elif oc == "foul" and s < 2:
                s += 1
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pitcher", default="Dylan Cease")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--game", type=int, default=0,
                    help="index into his starts that season")
    args = ap.parse_args()

    gs = games_for(args.pitcher, args.season)
    print(f"  {args.pitcher} {args.season}: {len(gs)} starts")
    g = gs[args.game]
    rows = pitches(g["gid"], args.pitcher)
    print(f"  game {args.game}: {g['d']}  {g['gid']}  "
          f"line: {g['k']} K, {g['bb']} BB, {g['outs']} outs")
    print(f"  {len(rows)} pitches extracted\n")

    print(f"  {'inn':>3} {'batter':<20}{'B':>2}{'-':^1}{'S':>1} "
          f"{'#':>2} {'pch':<4}{'velo':>6}{'spin':>6}{'ivb':>6}"
          f"{'px':>7}{'pz':>6} {'z':>2} {'code':<4}{'outcome':<8}"
          f"{'EV':>6}  result")
    for r in rows:
        print(f"  {r['inning']:>3} {(r['batter'] or '?')[:20]:<20}"
              f"{r['balls']:>2}-{r['strikes']:<1} "
              f"{r['pa_pitch']:>2} {r['type'] or '??':<4}"
              f"{(r['velo'] or 0):>6.1f}{(r['spin'] or 0):>6.0f}"
              f"{(r['ivb'] or 0):>6.1f}"
              f"{(r['px'] if r['px'] is not None else 0):>7.2f}"
              f"{(r['pz'] if r['pz'] is not None else 0):>6.2f} "
              f"{('Y' if r['in_zone'] else 'n' if r['in_zone'] is not None else '?'):>2} "
              f"{r['code'] or '?':<4}{r['outcome']:<8}"
              f"{(r['ev'] or 0):>6.1f}  "
              f"{r['pa_result'] if r['pa_pitch'] == 1 else ''}")

    # THE RECONCILIATION, and it is the point of this file: the pitch rows
    # must reproduce the BOX SCORE line. A K here that the box score does
    # not have means the walker is wrong, not that baseball is.
    from collections import Counter
    oc = Counter(r["outcome"] for r in rows)
    print("\n  outcome mix: " + "  ".join(f"{k}:{v}" for k, v in
                                           oc.most_common()))
    pas = []
    seen = set()
    for r in rows:
        key = (r["inning"], r["batter"], r["pa_result"])
        if key not in seen:
            seen.add(key)
            pas.append(r["pa_result"])
    ks = sum(1 for p in pas if p and "trikeout" in p)
    bbs = sum(1 for p in pas if p in ("Walk", "Intent Walk"))
    print("  reconciliation vs box score:")
    print(f"    PAs faced      {len(pas)}")
    print(f"    strikeouts     walker {ks:<4} box {g['k']}"
          f"   {'OK' if ks == g['k'] else '** MISMATCH **'}")
    print(f"    walks          walker {bbs:<4} box {g['bb']}"
          f"   {'OK' if bbs == g['bb'] else '** MISMATCH **'}")


if __name__ == "__main__":
    main()
