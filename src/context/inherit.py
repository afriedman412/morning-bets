"""What inherited runners actually do, counted on THIS league.

`sim.INHERITED_SCORE_RATE = 0.33` settles a departing starter's stranded
runners with one coin flip per runner, regardless of which base he stands on
or how many are out. That is the same shape of error the advancement tables
had before they were measured: a man on third with one out and a man on
first with none are not the same bet, and one pooled constant cannot be
right for both.

`game.py` does not use the constant — it hands the base-out state to the
reliever and the runners score for real reasons. But `sim.simulate`, the
START-LEVEL path that prices strikeouts and outs, still rolls the flat
0.33, and those runs are CHARGED to the starter, so the constant moves his
earned-run line directly.

This measures the replacement from play-by-play. For every mid-inning
pitching change it records which runners were on which bases with how many
out, then follows those specific runner IDs to the end of the half-inning
and counts who scored. Runner identity comes from `pbp.resolve`, the same
function the base-state reconstruction uses, so the two cannot disagree
about where a man ended up.

Nothing here is fitted. There is no loss function behind this module and
there must not be one — the conditioning is chosen to match the code path
in `sim._pull_mid_inning`, which is what makes replacing the constant a
measurement rather than a tune.

    venv/bin/python -m src.context.inherit [n_games]
"""
from collections import defaultdict

from src.context.sources import pbp

_BASES = ("1B", "2B", "3B")


def _handovers(game_id: str, data: dict | None = None):
    """Yield (base, outs_at_handover, scored) for every inherited runner.

    A handover is a pitching change with the inning still in progress. An
    inning-start change inherits nobody and is not one, which is why the
    occupancy map rather than the pitcher count decides.
    """
    occupant: dict[str, int] = {}
    current: dict[str, int] = {}
    half = None
    # {runner_id: (base, outs)} for runners handed to the man now pitching.
    pending: dict[int, tuple] = {}
    results: list[tuple] = []

    def flush():
        # Anyone still on base when the half-inning ended did not score.
        for base, outs in pending.values():
            results.append((base, outs, False))
        pending.clear()

    for play, bases, outs, _a, _h in pbp.plays(game_id, data):
        ab = play.get("about") or {}
        key = (ab.get("inning"), ab.get("halfInning"))
        if key != half:
            flush()
            half, occupant = key, {}
        mu = play.get("matchup") or {}
        p = (mu.get("pitcher") or {}).get("id")
        side = "home" if ab.get("isTopInning") else "away"
        if p and current.get(side) != p:
            if current.get(side) is not None and occupant and outs < 3:
                # A real handover: these men are now the new pitcher's to
                # strand, and the old pitcher's to be charged for.
                for base, rid in occupant.items():
                    pending[rid] = (base, outs)
            current[side] = p

        final, order = pbp.resolve(play.get("runners") or [])
        # Vacate every mover before placing anyone — the batter's record is
        # listed first and would otherwise clear the base a scoring runner
        # is leaving. Same discipline as `pbp._apply`.
        for rid in order:
            start = final[rid][0]
            if start in _BASES and occupant.get(start) == rid:
                del occupant[start]
        for rid in order:
            _, end, is_out = final[rid]
            if rid in pending and (end == "score" or is_out):
                base, at = pending.pop(rid)
                results.append((base, at, end == "score"))
            if is_out:
                continue
            if end in _BASES:
                occupant[end] = rid
    flush()
    return results


def tally(limit: int | None = None, verbose: bool = True) -> dict:
    """Count inherited-runner outcomes over the cached play-by-play."""
    ids = pbp.final_games()
    if limit:
        ids = ids[:limit]
    c: dict = defaultdict(lambda: [0, 0])       # key -> [scored, total]
    games = 0
    for gid in ids:
        if not pbp.have(gid):
            continue
        try:
            rows = _handovers(gid)
        except Exception:
            continue
        games += 1
        for base, outs, scored in rows:
            for key in ((base, outs), (base, None), (None, outs), (None, None)):
                c[key][1] += 1
                c[key][0] += 1 if scored else 0
        if verbose and games % 250 == 0:
            print(f"  {games} games, {c[(None, None)][1]:,} inherited runners",
                  flush=True)
    return {"games": games, "cells": {k: tuple(v) for k, v in c.items()}}


def _rate(cells, key):
    s, n = cells.get(key, (0, 0))
    return (s / n if n else None), n


def report(t: dict | None = None) -> None:
    t = tally() if t is None else t
    cells = t["cells"]
    overall, n = _rate(cells, (None, None))
    print(f"\n{t['games']:,} games, {n:,} inherited runners")
    if not n:
        return
    print(f"  overall {overall:.3f}   against the shipped flat 0.330")
    print("\n  BY BASE — one constant cannot be right for all three")
    for b in _BASES:
        r, m = _rate(cells, (b, None))
        if r is not None:
            print(f"    {b}  {r:.3f}   n={m:,}")
    print("\n  BY OUTS AT HANDOVER")
    for o in (0, 1, 2):
        r, m = _rate(cells, (None, o))
        if r is not None:
            print(f"    {o} out  {r:.3f}   n={m:,}")
    print("\n  THE CELL THE SIMULATOR ACTUALLY NEEDS (base x outs)")
    print(f"    {'':<5}{'0 out':>10}{'1 out':>10}{'2 out':>10}")
    for b in _BASES:
        cols = []
        for o in (0, 1, 2):
            r, m = _rate(cells, (b, o))
            cols.append(f"{r:.3f}" if r is not None else "--")
        print(f"    {b:<5}" + "".join(f"{x:>10}" for x in cols))


if __name__ == "__main__":
    import sys
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    report(tally(limit=lim))
