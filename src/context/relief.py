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

AND THE QUESTION HAS TO BE THE ONE THE ENGINE ASKS. The intent tables were
first counted as "he pitched in that inning, did he pitch in the next one",
which is not it: the engine rolls this only for an arm who has just recorded
the third out, and only when another inning will be played. Counting the
other two populations charges mid-inning removal twice and scores a man who
closed out a game as declining to come back out. `asked()` holds the
argument; both errors ran the same way and the late clean-entry cell — the
one nearly every reliever in every game hits — was low by 8 points.
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

#: INTENT (added 2026-09-09, PLAN-opener-bullpen.md step three). The pooled
#: tables above average over WHY the arm is out there, and entry inning is
#: where that intent is readable: with a clean-inning entry, an arm brought
#: in during innings 1-3 continues 79% of the time (he is the bulk man
#: behind an opener or an early exit), innings 4-6 44%, innings 7+ 18%. The
#: pre-intent pooled 20.1% is dominated by late innings and is wrong by a
#: factor of four for exactly the games the opener item is about.
#: The follower of a planned opener averages 9.50 outs against 3.96 for an
#: ordinary first reliever, and WHO he is does not predict (split-half at
#: the null against a positive-controlled harness), so intent is carried by
#: the entry state alone — which is all the engine knows anyway.
#:
#: Margin earns its cell the same way `entry_outs` does: the long man in a
#: blowout stays out there (E1 clean entry: 43.7% close vs 54.1% blown
#: open). Keyed (intent bucket, entry_outs, blowout) where blowout is
#: |margin at entry| >= 4.
#:
#: RE-COUNTED 2026-09-09 ON THE DENOMINATOR THE ENGINE ASKS — see `asked`,
#: which is where the argument lives. The first version counted "he pitched
#: in the inning; did he pitch in the next one" over every stint in the
#: table, which charges mid-inning removal a second time and scores an arm
#: who closed out the game as having declined an inning that never existed.
#: Both errors push one way, so every cell here ROSE, and worst for the arms
#: who face the most batters — the late clean entry, which nearly every
#: reliever in every game hits, went 9.9% -> 18.0%.
#:
#: Now counted on 62,278 stints BEFORE `HOLDOUT` (the first version used
#: every row, including the ones it is scored on). Thinnest cell 153.
CONTINUE_INTENT = {
    (0, 0, False): 0.7949, (0, 0, True): 0.8497,
    (0, 1, False): 0.7489, (0, 1, True): 0.8103,
    (0, 2, False): 0.7403, (0, 2, True): 0.8125,
    (1, 0, False): 0.4367, (1, 0, True): 0.5405,
    (1, 1, False): 0.5866, (1, 1, True): 0.6917,
    (1, 2, False): 0.7230, (1, 2, True): 0.7754,
    (2, 0, False): 0.1803, (2, 0, True): 0.2993,
    (2, 1, False): 0.4216, (2, 1, True): 0.4720,
    (2, 2, False): 0.5823, (2, 2, True): 0.6411,
}

#: Continuation after j full extra innings, keyed (intent bucket, j,
#: blowout), same recount and same denominator. The early entry does not
#: fade the way the old table said: 79% after one extra inning and still
#: 75% after three, where the old convention read 70% and 62% because every
#: mid-inning hook was being counted against it twice.
#:
#: THE CAP MOVED WITH THE DENOMINATOR. Uncensoring drops the arms who
#: finished the game, which is most of a late entry's deep rows, so E2 now
#: runs out after j=1 and E1 after j=3 — cells that were being published off
#: rows the engine never asks about. Missing cells walk DOWN in j (see
#: `continues`), so the deepest measured cell carries, the same posture as
#: `CONTINUE_TAIL`.
EXTRA_INTENT = {
    (0, 1, False): 0.7896, (0, 1, True): 0.7099,
    (0, 2, False): 0.8091, (0, 2, True): 0.6186,
    (0, 3, False): 0.7513, (0, 3, True): 0.6311,
    (0, 4, False): 0.5619, (0, 4, True): 0.5510,
    (0, 5, False): 0.3582,
    (1, 1, False): 0.3091, (1, 1, True): 0.4188,
    (1, 2, False): 0.4566, (1, 2, True): 0.4617,
    (1, 3, False): 0.4863, (1, 3, True): 0.5769,
    (2, 1, False): 0.1118, (2, 1, True): 0.2905,
}

#: Deepest j measured for any margin in each bucket; deeper outings carry
#: it, and a bucket missing THAT margin's cell walks further down.
_EXTRA_MAX_J = {0: 5, 1: 3, 2: 1}


#: Rows below this and a cell is a rumour; the lookup walks to a shallower
#: `j` instead. Same floor the pooled `extra` recount has always used.
MIN_CELL = 30


def intent_bucket(entry_inning: int) -> int:
    """0 = planned long outing (innings 1-3), 1 = middle, 2 = late."""
    return 0 if entry_inning <= 3 else (1 if entry_inning <= 6 else 2)


def continues(entry_outs: int, extra_innings: int,
              entry_inning: int | None = None,
              entry_margin: int | None = None) -> float:
    """P(this reliever comes back out for one more inning).

    `entry_outs` is how many outs were recorded when he entered — 0 for a
    clean inning, 1 or 2 for a mid-inning entry. `extra_innings` is how many
    FULL innings he has thrown since the one he entered, so 0 the first time
    this is asked of him.

    With `entry_inning` and `entry_margin` the intent tables answer —
    conditioning matches the count exactly: both are the state AT ENTRY,
    not at the decision. Without them the pre-intent pooled tables answer,
    which is also the `USE_RELIEF_INTENT`-off state.
    """
    k = min(max(entry_outs, 0), 2)
    if entry_inning is not None:
        e = intent_bucket(max(entry_inning, 1))
        b = abs(entry_margin or 0) >= 4
        if extra_innings <= 0:
            return CONTINUE_INTENT[(e, k, b)]
        # Walk DOWN in j to the deepest cell that was actually counted for
        # this margin. A KeyError here would be a table with a hole in it,
        # which is what the old fixed cap turned into once uncensoring took
        # the deep late-entry cells away.
        j = min(extra_innings, _EXTRA_MAX_J[e])
        while j > 1 and (e, j, b) not in EXTRA_INTENT:
            j -= 1
        return EXTRA_INTENT[(e, j, b)]
    if extra_innings <= 0:
        return CONTINUE_AFTER_ENTRY_INNING[k]
    return CONTINUE_AFTER_EXTRA.get(extra_innings, CONTINUE_TAIL)


def outings(conn=None, before: str | None = None) -> list[dict]:
    """Every relief stint, with the fields the hazard is counted over.

    `game_id`, `team` and `date` are here for the two denominators below,
    not for the rates themselves: the side's last inning on the mound says
    whether the arm ever had a next inning to come out for, and `before`
    holds the intent tables to training rows (rule 6).
    """
    q = """
        select game_id, team, date, appearance_order, entry_inning,
               entry_outs, outs_recorded, last_inning, on_1b, on_2b, on_3b,
               entry_margin
        from mlb_stints
    """

    def _run(c):
        rows = [dict(r) for r in c.execute(q)]
        # The side's last inning on the mound comes from EVERY stint, the
        # starter included, so the relief filter is applied afterwards.
        end: dict = {}
        for r in rows:
            k = (r["game_id"], r["team"])
            end[k] = max(end.get(k, 0), r["last_inning"] or 0)
        out = []
        for r in rows:
            if r["appearance_order"] <= 0:
                continue
            r["side_last_inning"] = end[(r["game_id"], r["team"])]
            out.append(r)
        return out
    if conn is not None:
        rows = _run(conn)
    else:
        with store.connect(attach=False) as c:
            rows = _run(c)
    if before is not None:
        rows = [r for r in rows if (r.get("date") or "") < before]
    return rows


def asked(r: dict, j: int) -> bool:
    """Was this arm ever ASKED the question the engine asks at `j`?

    THE ENGINE ONLY ROLLS `continues` FOR AN ARM STANDING ON THE MOUND WHEN
    THE THIRD OUT IS RECORDED, AND ONLY WHEN THERE IS ANOTHER INNING TO
    PITCH. Two denominators follow, and the pooled tables above use neither:

      * HE FINISHED THE INNING. `last_inning > entry_inning + j` over
        everyone who APPEARED in inning `entry_inning + j` scores an arm
        yanked mid-inning as a non-continuation — but the engine has already
        charged him `mid_removal` for that, per plate appearance. The
        boundary table was charging removal a second time. He finished iff
        he recorded the outs the inning owed: `(3 - entry_outs) + 3j`.
      * THERE WAS A NEXT INNING. An arm who closes out the game is scored as
        declining to come back out for an inning that never existed. The
        engine's roll at that point decides nothing, so those rows do not
        belong in the denominator either — worth 6 points on a late clean
        entry, more than every other correction here put together.

    Both push the same way and both are level errors, so the shipped table
    ran low everywhere and worst for the arms who face the most batters.
    """
    eo = min(max(r.get("entry_outs") or 0, 0), 2)
    if (r.get("outs_recorded") or 0) < (3 - eo) + 3 * j:
        return False
    last = r.get("side_last_inning")
    if last is None:                     # synthetic rows: assume he was asked
        return True
    return last > (r.get("entry_inning") or 0) + j


def tally(rows: list[dict] | None = None) -> dict:
    """Recount the published constants from the database.

    Returned as rates AND counts so a thin cell is visible rather than
    quietly authoritative.

    THE POOLED `entry`/`extra` COUNTS KEEP THE OLD DENOMINATOR on purpose:
    they document `CONTINUE_AFTER_ENTRY_INNING` and `CONTINUE_AFTER_EXTRA`,
    which are the `USE_RELIEF_INTENT`-off path and are frozen as the
    pre-intent engine. The `intent` counts use `asked` above.
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
    out["intent"], out["intent_extra"] = {}, {}
    for (e, k, b) in CONTINUE_INTENT:
        g = [r for r in rows if intent_bucket(r["entry_inning"]) == e
             and r["entry_outs"] == k
             and (abs(r["entry_margin"]) >= 4) == b
             and asked(r, 0)]
        if not g:
            continue
        c = sum(1 for r in g if r["last_inning"] > r["entry_inning"])
        out["intent"][(e, k, b)] = (c / len(g), c, len(g))
    # `j` is swept rather than read off the shipped keys, so the recount can
    # say where the sample actually runs out instead of confirming a cap it
    # was handed. `MIN_CELL` is the same floor the pooled `extra` block uses.
    for e in (0, 1, 2):
        for b in (False, True):
            for j in range(1, 9):
                g = [r for r in rows if intent_bucket(r["entry_inning"]) == e
                     and (abs(r["entry_margin"]) >= 4) == b
                     and asked(r, j)]
                if len(g) < MIN_CELL:
                    break
                c = sum(1 for r in g
                        if r["last_inning"] - r["entry_inning"] > j)
                out["intent_extra"][(e, j, b)] = (c / len(g), c, len(g))
    return out


def report(t: dict | None = None, ti: dict | None = None) -> None:
    """`t` counts the pooled tables over every row; `ti` the intent tables.

    They are separate tallies because they are counted on different rows and
    a single one would silently mix them: the pooled tables are the frozen
    pre-intent engine over the whole table, the intent tables are training
    rows only.
    """
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
    ti = t if ti is None else ti
    if ti.get("intent"):
        print(f"\n  INTENT, recounted over {ti['n']:,} rows on the"
              " denominator the ENGINE asks (see `asked`)")
        print("\n  continuation by (entry bucket, entry_outs, blowout)")
        for key, (r, c, n) in sorted(ti["intent"].items()):
            e, k, b = key
            ship = CONTINUE_INTENT[key]
            print(f"    E{e} k={k} {'blow ' if b else 'close'}  {r:6.1%}"
                  f"  shipped {ship:6.1%}   {c:>5}/{n:<5}")
        print("\n  continuation after j extra innings")
        for key, (r, c, n) in sorted(ti["intent_extra"].items()):
            e, j, b = key
            ship = EXTRA_INTENT.get(key)
            s = "  -   " if ship is None else f"{ship:6.1%}"
            print(f"    E{e} j={j} {'blow ' if b else 'close'}  {r:6.1%}"
                  f"  shipped {s}   {c:>5}/{n:<5}")


if __name__ == "__main__":
    from src.context.holdout import HOLDOUT
    report(tally(), tally(outings(before=HOLDOUT)))


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


#: THE SAME TABLE, CONDITIONED ON INTENT (`scratchpad/mid_intent.py`,
#: 9,254 games before the holdout). `RELIEF_MID_REMOVAL` above was counted
#: over every in-inning relief plate appearance — a population of
#: one-inning arms — and applied to every arm alike, which is the
#: "measured on one role, applied to all of them" error that hit-by-pitch,
#: sacrifices and wild pitches all had. It is the BINDING CONSTRAINT on the
#: arm behind an opener: `scratchpad/bulk_shape.py` gets him to 5.00 outs
#: against a real 7.39, and switching this hook off entirely gets 7.03.
#:
#: An arm entering in innings 1-3 is about THREE TIMES less likely to be
#: pulled through the 4-12 batter range than a late entry, which is exactly
#: where a bulk arm lives:
#:
#:     batters faced      1-3    4-6    7-9  10-12  13-15  16-18    19+
#:       entered 1-3     0.5%   3.6%   4.0%   5.6%   8.7%   7.4%  15.0%
#:       entered 4-6     2.1%  11.7%  11.3%  10.0%   9.5%   9.5%  10.0%
#:       entered 7+      1.6%  11.5%  12.7%   8.9%      -      -      -
#:       flat (shipped)  1.5%   9.9%   7.3%  ------ 7.0% flat ------
#:
#: TWO THINGS THIS IS NOT. It is not a depth fix — the guess that the real
#: hazard falls past the shipped 9-batter cap is REFUTED (pooled it runs
#: 8.5/9.1/8.2/13.7 and rises at the end). And it is not an opener special
#: case — keyed on "first reliever behind a short start" the row is within
#: noise of the intent-bucket-0 row, so the bulk arm needs no cell of his
#: own. One dimension, no special case.
#:
#: Keyed (intent bucket, min(runs, 3), min(batters // 3, 6)). Counted on
#: rows before `HOLDOUT`, unlike the flat table above, which was not.
MID_INTENT = {
    (0, 0, 0): 0.0046, (0, 0, 1): 0.0344, (0, 0, 2): 0.0349,
    (0, 0, 3): 0.0442, (0, 0, 4): 0.1007, (0, 0, 5): 0.0648,
    (0, 1, 0): 0.0157, (0, 1, 1): 0.0239, (0, 1, 2): 0.0440,
    (0, 1, 3): 0.0445, (0, 1, 4): 0.0778, (0, 1, 5): 0.0905,
    (0, 2, 1): 0.0722, (0, 2, 2): 0.0508, (0, 2, 3): 0.0694,
    (0, 2, 4): 0.1064,
    (0, 3, 2): 0.0460, (0, 3, 3): 0.0909, (0, 3, 4): 0.0637,
    (0, 3, 5): 0.0557, (0, 3, 6): 0.1171,
    (1, 0, 0): 0.0191, (1, 0, 1): 0.1163, (1, 0, 2): 0.1083,
    (1, 0, 3): 0.0913, (1, 0, 4): 0.1009,
    (1, 1, 0): 0.0493, (1, 1, 1): 0.1126, (1, 1, 2): 0.1204,
    (1, 1, 3): 0.1008, (1, 1, 4): 0.1098,
    (1, 2, 0): 0.0361, (1, 2, 1): 0.1389, (1, 2, 2): 0.1097,
    (1, 2, 3): 0.1093, (1, 2, 4): 0.0875,
    (1, 3, 0): 0.0549, (1, 3, 1): 0.1091, (1, 3, 2): 0.1178,
    (1, 3, 3): 0.1043, (1, 3, 4): 0.0815, (1, 3, 5): 0.1094,
    (2, 0, 0): 0.0145, (2, 0, 1): 0.1018, (2, 0, 2): 0.0865,
    (2, 0, 3): 0.0661,
    (2, 1, 0): 0.0421, (2, 1, 1): 0.1300, (2, 1, 2): 0.1133,
    (2, 1, 3): 0.0784,
    (2, 2, 0): 0.0667, (2, 2, 1): 0.1522, (2, 2, 2): 0.1738,
    (2, 3, 0): 0.0810, (2, 3, 1): 0.1622, (2, 3, 2): 0.1978,
    (2, 3, 3): 0.0974,
}

#: The (intent, depth) MARGINAL, and it is load-bearing rather than
#: decorative: the three-way cell is thinnest exactly where the new
#: dimension matters most — an early entry that has allowed runs — and a
#: rate counted on forty rows is a rumour. A cell missing from `MID_INTENT`
#: (under 200 rows) falls through to here, and a cell missing from here
#: falls through to the flat table, so the degradation is monotone and
#: every level is something that was actually counted.
MID_INTENT_DEPTH = {
    (0, 0): 0.0051, (0, 1): 0.0363, (0, 2): 0.0401, (0, 3): 0.0563,
    (0, 4): 0.0871, (0, 5): 0.0740, (0, 6): 0.1498,
    (1, 0): 0.0215, (1, 1): 0.1171, (1, 2): 0.1127, (1, 3): 0.0998,
    (1, 4): 0.0946, (1, 5): 0.0947, (1, 6): 0.1000,
    (2, 0): 0.0162, (2, 1): 0.1151, (2, 2): 0.1269, (2, 3): 0.0892,
}

#: Off restores the flat table exactly, so OFF is bit-for-bit the
#: pre-intent engine. No random variate is involved either way — this
#: changes the PROBABILITY a roll is compared against, not the number of
#: rolls — so unlike `game.USE_OPENER_DECAY` this one IS a clean paired
#: A/B and the streams stay aligned.
USE_MID_INTENT = True


def mid_removal(runs: int, batters: int,
                entry_inning: int | None = None) -> float:
    """P(replaced before the next batter) for the reliever now pitching.

    `runs` and `batters` are what he has already given up and already faced
    IN THIS STINT — the state at the decision, not the stint total. See the
    survivorship note above; conditioning on stint totals reads plausibly
    and is inflated by the arms that stayed in and kept being scored on.

    `entry_inning` is the INTENT dimension and is the state AT ENTRY, not
    at the decision — the same conditioning `continues` takes, and for the
    same reason: that is what the table was counted on. Without it the flat
    table answers, which is also the `USE_MID_INTENT`-off state.
    """
    r = min(max(runs, 0), 3)
    if USE_MID_INTENT and entry_inning is not None:
        e = intent_bucket(max(entry_inning, 1))
        d = min(max(batters, 0) // 3, 6)
        p = MID_INTENT.get((e, r, d))
        if p is None:
            p = MID_INTENT_DEPTH.get((e, d))
        if p is not None:
            return p
    return RELIEF_MID_REMOVAL[r][min(max(batters, 0) // 3, 3)]
