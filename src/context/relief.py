"""How long a relief outing actually lasts, counted on THIS league.

`game.py` gives every reliever exactly one inning: `_end_of_inning` calls
`side.next_arm()` unconditionally once the starter is out. Measured against
13,248 relief outings that is wrong in a way that matters for a total —
the real mean is 3.473 outs, not 3.000, only 70.7% of outings end in the
inning they began, and the model uses more arms per game than the league
does. How many arms a game burns is a VARIANCE question, and variance is
what a total settles on.

The quantity the engine needs at the end of an inning is a continuation
hazard: this reliever has finished the inning, does he come back out? It is
conditioned on exactly what the engine knows at that point — how many outs
were already recorded when he entered, and how many full innings he has
since thrown. Nothing here is fitted. There is no loss function behind this
module and there must not be one; `tally()` recounts the constants from
`mlb_stints` so they stay checkable against the league rather than against
a score.

The strong conditioning on `entry_outs` is the whole finding, and it is not
a small effect:

    entered with 0 out   continues 20.1%    n=9734
    entered with 1 out   continues 44.8%    n=1572
    entered with 2 out   continues 62.7%    n=1942

which reads as a manager's intent. An arm brought in for one out has not
done his job when the inning ends; an arm handed a clean inning has. A
single pooled constant cannot represent both, the same way one pooled
advance-on-out constant could not represent a runner on first and a runner
on second.

    venv/bin/python -m src.context.relief

reprints the tables from the database.
"""
from collections import defaultdict

from src.context import store

#: P(this reliever pitches the NEXT inning too | he entered with `k` outs
#: already recorded and has just finished that inning). Counted over every
#: relief stint in `mlb_stints`; see the module docstring for the counts.
CONTINUE_AFTER_ENTRY_INNING = {0: 0.2013, 1: 0.4478, 2: 0.6267}

#: P(he goes out AGAIN | he has already thrown `j` full innings beyond the
#: one he entered). Rises with `j` because of selection rather than stamina
#: — by the second extra inning the population is long men, not setup arms.
CONTINUE_AFTER_EXTRA = {1: 0.2147, 2: 0.3974, 3: 0.4411}

#: Beyond the measured span the sample is too thin to condition on, so the
#: last measured rate carries. A reliever in his fifth inning of work is
#: rare enough that the tail costs nothing either way.
CONTINUE_TAIL = 0.4411


def continues(entry_outs: int, extra_innings: int) -> float:
    """P(this reliever comes back out for one more inning).

    `entry_outs` is how many outs were recorded when he entered — 0 for a
    clean inning, 1 or 2 for a mid-inning entry. `extra_innings` is how many
    FULL innings he has thrown since the one he entered, so 0 the first time
    this is asked of him.
    """
    if extra_innings <= 0:
        return CONTINUE_AFTER_ENTRY_INNING.get(min(max(entry_outs, 0), 2),
                                               CONTINUE_AFTER_ENTRY_INNING[0])
    return CONTINUE_AFTER_EXTRA.get(extra_innings, CONTINUE_TAIL)


def outings(conn=None) -> list[dict]:
    """Every relief stint, with the fields the hazard is counted over."""
    q = """
        select entry_inning, entry_outs, outs_recorded, last_inning,
               on_1b, on_2b, on_3b, entry_margin
        from mlb_stints
        where appearance_order > 0
    """

    def _run(c):
        return [dict(r) for r in c.execute(q)]
    if conn is not None:
        return _run(conn)
    with store.connect(attach=False) as c:
        return _run(c)


def tally(rows: list[dict] | None = None) -> dict:
    """Recount the published constants from the database.

    Returned as rates AND counts so a thin cell is visible rather than
    quietly authoritative.
    """
    rows = outings() if rows is None else rows
    out: dict = {"n": len(rows), "entry": {}, "extra": {}}
    if not rows:
        return out
    out["mean_outs"] = sum(r["outs_recorded"] for r in rows) / len(rows)
    out["mid_inning"] = sum(
        1 for r in rows
        if r["entry_outs"] > 0 or r["on_1b"] or r["on_2b"] or r["on_3b"]
    ) / len(rows)
    for k in (0, 1, 2):
        g = [r for r in rows if r["entry_outs"] == k]
        if not g:
            continue
        c = sum(1 for r in g if r["last_inning"] > r["entry_inning"])
        out["entry"][k] = (c / len(g), c, len(g))
    for j in (1, 2, 3):
        g = [r for r in rows if r["last_inning"] - r["entry_inning"] >= j]
        if len(g) < 30:
            continue
        c = sum(1 for r in g if r["last_inning"] - r["entry_inning"] > j)
        out["extra"][j] = (c / len(g), c, len(g))
    return out


def report(t: dict | None = None) -> None:
    t = tally() if t is None else t
    print(f"\n{t['n']:,} relief outings")
    print(f"  mean outs recorded {t['mean_outs']:.3f}"
          f"   (game.py gives a flat 3.000)")
    print(f"  entered mid-inning {t['mid_inning']:.1%}"
          f"   (game.py can only produce these off a starter's hook)")
    print("\n  CONTINUATION past the inning he entered, by entry_outs")
    for k, (r, c, n) in sorted(t["entry"].items()):
        print(f"    {k} out  {r:6.1%}   {c:>5}/{n:<5}")
    print("\n  CONTINUATION having already thrown j full extra innings")
    for j, (r, c, n) in sorted(t["extra"].items()):
        print(f"    j={j}   {r:6.1%}   {c:>5}/{n:<5}")
    print("\n  A manager's intent, not stamina: the arm brought in for one")
    print("  out has not finished his job when the inning ends.")


if __name__ == "__main__":
    report()


# ---------------------------------------------------------------------------
# Mid-inning removal of a RELIEVER.
#
# `game.py` can only produce a mid-inning pitching change off the STARTER's
# hook. Measured, that is a minority of them: of 4,026 mid-inning handovers,
# only 41.8% come from a starter and 58.2% come from one reliever giving way
# to another. The model cannot make those at all.
#
# BEWARE THE SURVIVORSHIP TRAP HERE. Conditioning on a stint's TOTAL runs or
# batters looks natural and is wrong: for a pitcher who was NOT pulled the
# total keeps accumulating after the decision point, so the buckets are not
# what the manager knew when he decided. Stint-level totals give 19.1% at
# zero runs rising to 40.5% at three, which reads plausibly and is inflated
# by exactly the arms that stayed in and kept giving up runs.
#
# The hazard below is per PLATE APPEARANCE and conditions only on what had
# already happened when the decision was taken, which is the same footing as
# `sim.Hook.mid_removal_p` for a starter.
# ---------------------------------------------------------------------------

def removal_hazard(limit: int | None = None, verbose: bool = True) -> dict:
    """P(a reliever is replaced before the next batter), counted per PA.

    Walks the play-by-play so the state is the state BEFORE the decision:
    runs this reliever has already allowed in this stint, batters he has
    already faced, and whether the inning is still in progress.
    """
    from src.context.sources import pbp

    ids = pbp.final_games()
    if limit:
        ids = ids[:limit]
    cells: dict = defaultdict(lambda: [0, 0])
    games = 0
    for gid in ids:
        if not pbp.have(gid):
            continue
        try:
            seq = list(pbp.plays(gid))
        except Exception:
            continue
        games += 1
        # (side) -> [pitcher_id, runs_so_far, batters_so_far, is_reliever]
        cur: dict = {}
        order: dict = defaultdict(int)
        for i, (play, bases, outs, away, home) in enumerate(seq):
            ab = play.get("about") or {}
            side = "home" if ab.get("isTopInning") else "away"
            pid = ((play.get("matchup") or {}).get("pitcher") or {}).get("id")
            if not pid:
                continue
            st_ = cur.get(side)
            if st_ is None or st_[0] != pid:
                order[side] += 1
                cur[side] = st_ = [pid, 0, 0, order[side] > 1]
            runs_before, batters_before, is_rel = st_[1], st_[2], st_[3]

            # Does a change happen before the next play of this half-inning?
            nxt = seq[i + 1] if i + 1 < len(seq) else None
            same_half = bool(nxt) and (
                ((nxt[0].get("about") or {}).get("inning") == ab.get("inning"))
                and ((nxt[0].get("about") or {}).get("halfInning")
                     == ab.get("halfInning")))
            changed = False
            if same_half:
                npid = ((nxt[0].get("matchup") or {}).get("pitcher")
                        or {}).get("id")
                changed = bool(npid and npid != pid)

            if is_rel and same_half:
                key = (min(runs_before, 3), min(batters_before // 3, 3))
                cells[key][1] += 1
                cells[key][0] += 1 if changed else 0
                cells[(min(runs_before, 3), None)][1] += 1
                cells[(min(runs_before, 3), None)][0] += 1 if changed else 0
                cells[(None, None)][1] += 1
                cells[(None, None)][0] += 1 if changed else 0

            # Advance this pitcher's own accumulators past the play.
            res = play.get("result") or {}
            st_[1] += (res.get("awayScore", 0) + res.get("homeScore", 0)) - (
                away + home)
            st_[2] += 1
        if verbose and games % 500 == 0:
            print(f"  {games} games, {cells[(None, None)][1]:,} relief PAs",
                  flush=True)
    return {"games": games, "cells": {k: tuple(v) for k, v in cells.items()}}


def removal_report(h: dict | None = None) -> None:
    h = removal_hazard() if h is None else h
    cells = h["cells"]
    s, n = cells.get((None, None), (0, 0))
    print(f"\n{h['games']:,} games, {n:,} in-inning relief plate appearances")
    if not n:
        return
    print(f"  overall P(change before the next batter) {s / n:.3f}")
    print("\n  BY RUNS ALREADY ALLOWED IN THIS STINT (not the stint total)")
    for r in (0, 1, 2, 3):
        c = cells.get((r, None))
        if c and c[1] >= 40:
            print(f"    {r}{'+' if r == 3 else ' '} runs   {c[0]/c[1]:6.2%}"
                  f"   n={c[1]:,}")


#: P(this reliever is replaced before the next batter), counted per PLATE
#: APPEARANCE over 50,023 in-inning relief PAs, indexed
#: [min(runs so far, 3)][min(batters faced so far // 3, 3)].
#:
#: Both dimensions earn their place and the batter one is not monotone. The
#: first two batters are nearly immune — he has just been brought in for
#: this exact situation — then the hazard peaks once he has faced the men he
#: came in for, then falls away as the arms still out there are the ones
#: handling it. A single scalar reproduces none of that shape.
RELIEF_MID_REMOVAL = {
    0: {0: 0.015, 1: 0.099, 2: 0.073, 3: 0.070},
    1: {0: 0.045, 1: 0.130, 2: 0.097, 3: 0.060},
    2: {0: 0.033, 1: 0.141, 2: 0.122, 3: 0.087},
    3: {0: 0.061, 1: 0.109, 2: 0.116, 3: 0.080},
}


def mid_removal(runs: int, batters: int) -> float:
    """P(replaced before the next batter) for the reliever now pitching.

    `runs` and `batters` are what he has already given up and already faced
    IN THIS STINT — the state at the decision, not the stint total. See the
    survivorship note above; conditioning on stint totals reads plausibly
    and is inflated by the arms that stayed in and kept being scored on.
    """
    r = RELIEF_MID_REMOVAL[min(max(runs, 0), 3)]
    return r[min(max(batters, 0) // 3, 3)]
