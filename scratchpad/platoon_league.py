"""The LEAGUE platoon effect, by batter hand against pitcher hand.

    venv/bin/python -m scratchpad.platoon_league [workers]

THE SPECIFICATION ERROR THIS EXISTS TO EXPOSE. Both `rates.batter_rates_by_hand`
and the exact version built for the A/B shrink each hitter's split toward HIS
OWN OVERALL RATE. A hitter with a thin split therefore regresses to having NO
platoon effect, which is the opposite of what is true: the reliable part of
handedness is the STRUCTURAL advantage a right-handed bat has against a
left-handed arm, and the unreliable part is his personal deviation from it.

So the shipped construction models the noise and discards the signal. That is
the best available explanation for a mechanism that gains 3.5 sigma in sample
and LOSES 2.3 out of it: the individual deviation does not persist across
seasons, and there was never anything else in the adjustment.

THE TELL, missed this morning. "72 of 148 hitters have reversed splits" was
reported as evidence the population cancels. It is not. That statistic pooled
left-handed and right-handed batters, and a lefty's split has the OPPOSITE
SIGN from a righty's by definition. Roughly half reversed is exactly what a
large, real, one-directional platoon effect looks like when nobody conditions
on which side the batter stands in.

WHAT IS COUNTED HERE. Every plate appearance in the cache, split four ways by
(batter side, pitcher hand), with switch hitters resolved to the side they
ACTUALLY BATTED FROM that time up. If the four cells are close together,
handedness really is absorbed and the nulls stand. If they are far apart,
the adjustment was mis-specified and this is the number to wire in.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

from src import db
from src.context.sources import pbp

_K = ("strikeout", "strikeout_double_play")
_HIT = ("single", "double", "triple")
_BIP_OUT = ("field_out", "force_out", "fielders_choice_out",
            "grounded_into_double_play", "double_play", "triple_play",
            "field_error")


def scan(short: str):
    """(bat side, pitch hand) -> [pa, k, hits, bip, hr, bb] for one game."""
    try:
        d = pbp.fetch(short)
    except Exception:
        return None
    if not d:
        return None
    out = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    for p in (d.get("allPlays") or []):
        mu = p.get("matchup") or {}
        res = p.get("result") or {}
        bs = ((mu.get("batSide") or {}).get("code") or "")
        ph = ((mu.get("pitchHand") or {}).get("code") or "")
        if bs not in ("L", "R") or ph not in ("L", "R"):
            continue
        ev = res.get("eventType") or ""
        c = out[(bs, ph)]
        c[0] += 1
        if ev in _K:
            c[1] += 1
        if ev in _HIT:
            c[2] += 1
            c[3] += 1
        elif ev in _BIP_OUT:
            c[3] += 1
        elif ev == "home_run":
            c[4] += 1
        elif ev in ("walk", "intent_walk", "hit_by_pitch"):
            c[5] += 1
    return {f"{k[0]}{k[1]}": v for k, v in out.items()}


def main(argv):
    workers = int(argv[0]) if argv else 8
    with db.connect() as c:
        games = {r["game_id"]: r["date"] for r in
                 c.execute("select game_id, date from games"
                           " where sport = 'mlb'")}
    todo = sorted((g, d) for g, d in games.items()
                  if pbp.have(g.split("-")[-1]))
    print(f"  scanning {len(todo):,} games on {workers} workers ...",
          flush=True)
    tot = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    by_year = defaultdict(lambda: defaultdict(lambda: [0] * 6))
    with ProcessPoolExecutor(max_workers=workers) as ex:
        res = ex.map(scan, [g.split("-")[-1] for g, _ in todo], chunksize=32)
        for (g, date), got in zip(todo, res):
            if not got:
                continue
            for k, v in got.items():
                for i in range(6):
                    tot[k][i] += v[i]
                    by_year[int(date[:4])][k][i] += v[i]

    def rates(c):
        pa, k, h, bip, hr, bb = c
        return {"pa": pa, "k": k / pa, "bb": bb / pa, "hr": hr / pa,
                "babip": h / bip if bip else 0.0}

    print(f"\n  {'bat/pit':<9}{'PA':>12}{'K%':>9}{'BB%':>8}{'HR%':>8}"
          f"{'BABIP':>9}")
    for key in ("RR", "RL", "LR", "LL"):
        if key not in tot:
            continue
        r = rates(tot[key])
        print(f"  {key[0]} vs {key[1]:<5}{r['pa']:>12,}{r['k']:>9.4f}"
              f"{r['bb']:>8.4f}{r['hr']:>8.4f}{r['babip']:>9.4f}")

    print("\n  THE PLATOON ADVANTAGE — opposite hand minus same hand:")
    print(f"  {'batter':<9}{'K%':>9}{'BB%':>8}{'HR%':>8}{'BABIP':>9}")
    for bs, same, opp in (("R", "RR", "RL"), ("L", "LL", "LR")):
        if same not in tot or opp not in tot:
            continue
        a, b = rates(tot[same]), rates(tot[opp])
        print(f"  {bs}HB{'':<6}{b['k'] - a['k']:>+9.4f}"
              f"{b['bb'] - a['bb']:>+8.4f}{b['hr'] - a['hr']:>+8.4f}"
              f"{b['babip'] - a['babip']:>+9.4f}")

    # Is it STABLE across seasons? A structural effect should barely move.
    # If it swings year to year it is not the reliable half of handedness
    # and this whole argument collapses.
    print("\n  STABILITY — the same advantage, counted per season:")
    print(f"  {'season':<9}{'RHB K%':>10}{'RHB BABIP':>12}"
          f"{'LHB K%':>10}{'LHB BABIP':>12}")
    for y in sorted(by_year):
        d = by_year[y]
        if not all(k in d for k in ("RR", "RL", "LL", "LR")):
            continue
        rr, rl = rates(d["RR"]), rates(d["RL"])
        ll, lr = rates(d["LL"]), rates(d["LR"])
        print(f"  {y:<9}{rl['k'] - rr['k']:>+10.4f}"
              f"{rl['babip'] - rr['babip']:>+12.4f}"
              f"{lr['k'] - ll['k']:>+10.4f}"
              f"{lr['babip'] - ll['babip']:>+12.4f}")

    print("\n  If these cells are far apart and stable, the shipped")
    print("  construction — shrink each split toward the hitter's OWN")
    print("  overall rate — discards exactly this and keeps only the")
    print("  personal deviation, which is the half that does not persist.")


if __name__ == "__main__":
    main(sys.argv[1:])
