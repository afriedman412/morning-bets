"""Times through the order: how much worse does a starter get, counted here.

The simulator wraps the lineup and charges nothing for it. The pitcher
facing the three-hole in the first and the same pitcher facing him in the
seventh are, in the model, the identical pitcher with identical rates.

That absence is why the whole removal branch is inert. Measured on this
league, relievers are NOT better than starters (K-BB 0.1333 against 0.1358),
so pulling a starter swaps him for an equal arm and removal costs nothing.
Managers pull starters the third time through precisely because the starter
has degraded — the replacement does not need to be better in the abstract,
only better than what the starter has become. Without a degradation term the
hook, manager patience, pitcher leash and role-based deployment are all
decisions with no consequence, which is exactly what three separate
measurements found today.

THE DESIGN CONTROLS THE TWO CONFOUNDS THAT MAKE NAIVE TTO NUMBERS WRONG.

  SURVIVORSHIP. A pitcher only reaches the third time through by pitching
  well, so comparing all first-time PAs against all third-time PAs compares
  every start against the subset that went well. That biases toward showing
  LESS degradation than is there. Fixed by comparing WITHIN A START: only
  starts that reached the third pass are counted, so pitcher-day quality is
  held fixed and the comparison is the same man on the same afternoon.

  BATTER MIX. The third pass is not a random sample of hitters if the start
  ended mid-lineup. Fixed by keeping only batters this starter faced at ALL
  THREE passes, which makes the three buckets the same nine men by
  construction — the comparison is paired on the batter, not just the game.

What is NOT controlled, and should be said plainly: fatigue and familiarity
are not separable here. A pitcher deeper into a game is both more tired and
better known. This measures their sum, which is the quantity the simulator
needs, but it is not evidence for the familiarity story over the fatigue
one.

    venv/bin/python -m src.context.tto [n_games]
"""
from __future__ import annotations

import sys
from collections import defaultdict

from src.context.sources import pbp

#: statsapi eventTypes, mapped to the four rates the simulator carries.
_K = {"strikeout", "strikeout_double_play"}
_BB = {"walk", "intent_walk"}
_HBP = {"hit_by_pitch"}
_HR = {"home_run"}
_HIT = {"single", "double", "triple"}
#: Everything that is a plate appearance ending in a ball in play. Errors
#: count: the batter reached on a batted ball, which is a PA.
_INPLAY_OUT = {"field_out", "force_out", "fielders_choice_out",
               "fielders_choice", "grounded_into_double_play", "double_play",
               "triple_play", "field_error", "sac_fly", "sac_bunt",
               "sac_fly_double_play", "sac_bunt_double_play"}


def _bucket(event: str) -> str | None:
    if event in _K:
        return "k"
    if event in _BB:
        return "bb"
    if event in _HBP:
        return "hbp"
    if event in _HR:
        return "hr"
    if event in _HIT:
        return "hit"
    if event in _INPLAY_OUT:
        return "out"
    return None


def start_passes(game_id: str, data: dict | None = None) -> list[dict]:
    """Per (start, batter, pass) outcomes for starters who reached pass 3.

    One row per plate appearance, carrying which pass it was. Only batters
    faced at all three passes survive, so the buckets compare the same nine
    hitters against the same pitcher in the same game.
    """
    seen: dict = defaultdict(lambda: defaultdict(list))   # side -> bat -> [ev]
    starter: dict = {}
    out: list[dict] = []
    for play, _b, _o, _a, _h in pbp.plays(game_id, data):
        ab = play.get("about") or {}
        mu = play.get("matchup") or {}
        pid = (mu.get("pitcher") or {}).get("id")
        bid = (mu.get("batter") or {}).get("id")
        if not pid or not bid:
            continue
        side = "home" if ab.get("isTopInning") else "away"
        starter.setdefault(side, pid)
        if starter[side] != pid:
            continue                      # relievers have no lineup pass
        ev = ((play.get("result") or {}).get("eventType") or "")
        b = _bucket(ev)
        if b is None:
            continue                      # not a plate appearance
        seen[side][bid].append(b)

    for side, batters in seen.items():
        for bid, evs in batters.items():
            if len(evs) < 3:
                continue                  # not faced at all three passes
            for i, b in enumerate(evs[:3], start=1):
                out.append({"game_id": game_id, "pitcher": starter[side],
                            "batter": bid, "pass": i, "event": b})
    return out


def tally(limit: int | None = None, verbose: bool = True) -> dict:
    ids = pbp.final_games()
    if limit:
        ids = ids[:limit]
    cells: dict = defaultdict(lambda: defaultdict(int))
    games = 0
    for gid in ids:
        if not pbp.have(gid):
            continue
        try:
            rows = start_passes(gid)
        except Exception:
            continue
        games += 1
        for r in rows:
            c = cells[r["pass"]]
            c["pa"] += 1
            c[r["event"]] += 1
        if verbose and games % 500 == 0:
            print(f"  {games} games, {sum(c['pa'] for c in cells.values()):,}"
                  f" paired plate appearances", flush=True)
    return {"games": games, "cells": {k: dict(v) for k, v in cells.items()}}


def rates(cell: dict) -> dict:
    pa = cell.get("pa", 0)
    if not pa:
        return {}
    bip = pa - cell.get("k", 0) - cell.get("bb", 0) - cell.get("hbp", 0) \
        - cell.get("hr", 0)
    return {
        "pa": pa,
        "k_pct": cell.get("k", 0) / pa,
        "bb_pct": cell.get("bb", 0) / pa,
        "hr_pct": cell.get("hr", 0) / pa,
        "babip": (cell.get("hit", 0) / bip) if bip > 0 else 0.0,
    }


def report(t: dict | None = None) -> None:
    t = tally() if t is None else t
    cells = t["cells"]
    print(f"\n{t['games']:,} games; batters faced at all three passes only")
    print(f"  {'pass':<7}{'PA':>9}{'K%':>9}{'BB%':>9}{'HR%':>9}{'BABIP':>9}")
    r = {}
    for p in (1, 2, 3):
        if p not in cells:
            continue
        r[p] = rates(cells[p])
        print(f"  {p:<7}{r[p]['pa']:>9,}{r[p]['k_pct']:>9.4f}"
              f"{r[p]['bb_pct']:>9.4f}{r[p]['hr_pct']:>9.4f}"
              f"{r[p]['babip']:>9.4f}")
    if 1 in r and 3 in r:
        print("\n  MULTIPLIERS relative to the first pass — what the "
              "simulator needs")
        print(f"  {'pass':<7}{'k_pct':>10}{'bb_pct':>10}{'hr_pct':>10}"
              f"{'babip':>10}")
        for p in (1, 2, 3):
            if p not in r:
                continue
            print(f"  {p:<7}" + "".join(
                f"{(r[p][s] / r[1][s] if r[1][s] else 1.0):>10.4f}"
                for s in ("k_pct", "bb_pct", "hr_pct", "babip")))
        print("\n  A starter who gets worse should show K% falling and HR% /")
        print("  BABIP rising. Flat multipliers mean the effect is not in")
        print("  this league's data and the whole removal branch stays inert.")


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    report(tally(limit=lim))


# ---------------------------------------------------------------------------
# THE COLLIDER, AND WHY THE RAW 1 -> 2 STEP MUST NOT BE USED.
#
# Keeping only starts that reached the third pass controls pitcher-day
# quality, but REACHING the third pass is earned by pitching well early. So
# pass-1 performance inside those starts is upward-biased by selection: the
# tell is that pass-1 K% comes out at 0.2409 against a league starter
# baseline of 0.2170. Comparing pass 1 to pass 3 therefore measures
# degradation PLUS regression from an inflated starting point, and reports
# a K% decline of 19% where the honest per-pass step is a few percent.
#
# Two readings survive this:
#   * pass 2 -> pass 3, since both are conditioned on the same survival
#   * pass 1 -> pass 2 measured in starts that did NOT reach pass 3,
#     which carries the opposite selection and brackets the truth
#
# `selection_check` reports the bracket. Anything wired into the simulator
# should come from the 2 -> 3 step, which is the one clean number here.
# ---------------------------------------------------------------------------

def selection_check(limit: int | None = None, verbose: bool = True) -> dict:
    """Pass-1 rates in starts that DID and DID NOT reach the third pass.

    If the two differ, the gap IS the selection, and the raw 1 -> 2 step is
    contaminated by exactly that much.
    """
    ids = pbp.final_games()
    if limit:
        ids = ids[:limit]
    deep: dict = defaultdict(int)
    shallow: dict = defaultdict(int)
    games = 0
    for gid in ids:
        if not pbp.have(gid):
            continue
        try:
            rows = _all_passes(gid)
        except Exception:
            continue
        games += 1
        for (_side, _bid), evs in rows.items():
            tgt = deep if len(evs) >= 3 else shallow
            if not evs:
                continue
            tgt["pa"] += 1
            tgt[evs[0]] += 1
    return {"games": games, "deep": dict(deep), "shallow": dict(shallow)}


def _all_passes(game_id: str, data: dict | None = None) -> dict:
    """{(side, batter): [events]} for the STARTER only, no length filter."""
    seen: dict = defaultdict(list)
    starter: dict = {}
    for play, _b, _o, _a, _h in pbp.plays(game_id, data):
        ab = play.get("about") or {}
        mu = play.get("matchup") or {}
        pid = (mu.get("pitcher") or {}).get("id")
        bid = (mu.get("batter") or {}).get("id")
        if not pid or not bid:
            continue
        side = "home" if ab.get("isTopInning") else "away"
        starter.setdefault(side, pid)
        if starter[side] != pid:
            continue
        b = _bucket(((play.get("result") or {}).get("eventType") or ""))
        if b is None:
            continue
        seen[(side, bid)].append(b)
    return seen


def selection_report(s: dict | None = None) -> None:
    s = selection_check() if s is None else s
    d, sh = rates(s["deep"]), rates(s["shallow"])
    print(f"\n{s['games']:,} games — PASS-1 rates, split by whether the "
          f"starter lasted")
    print(f"  {'':<26}{'PA':>9}{'K%':>9}{'BB%':>9}{'HR%':>9}")
    for lbl, r in (("reached 3rd pass", d), ("did NOT reach 3rd", sh)):
        if r:
            print(f"  {lbl:<26}{r['pa']:>9,}{r['k_pct']:>9.4f}"
                  f"{r['bb_pct']:>9.4f}{r['hr_pct']:>9.4f}")
    if d and sh and sh["k_pct"]:
        print(f"\n  selection on K%: {d['k_pct'] / sh['k_pct']:.3f}x")
        print("  That ratio is how much of the raw 1 -> 2 decline is the")
        print("  collider rather than the pitcher getting worse.")
