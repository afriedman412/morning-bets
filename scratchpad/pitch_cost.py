"""How much pitch-count variance does the deterministic PITCH_COST discard?

    venv/bin/python -m scratchpad.pitch_cost [max_games]

QUESTION    `sim.PITCH_COST` is ONE CONSTANT PER OUTCOME — 4.97 pitches for
            a strikeout, 3.25 for an out — so a simulated start's pitch
            count is fully determined by its outcome sequence. Two starters
            with identical lines get identical pitch counts. What is the
            real spread, per plate appearance and per start?

WHY IT MATTERS MORE THAN IT SOUNDS. The HOOK keys on pitch count, and the
hook is the largest open defect in the model. If pitch count arrives with
no noise, removal timing is a deterministic function of the line, and the
hook cannot express "he is at 95 with nothing left" separately from "he is
at 70 and cruising" for two starts with the same outcomes.

HYPOTHESIS  Registered before running: per-PA sd of 1.5-2.5 pitches on a
            strikeout, and a START-level residual around 10 pitches once
            ~25 independent plate appearances add in quadrature.
            FALSIFIER: if the start-level residual is small, pitch count is
            dominated by BATTERS FACED and the constants are adequate.

TEST        Every 2026 starter plate appearance off the play-by-play cache,
            with the pitches actually thrown in it. Power is not a concern
            — this is a counting exercise over ~150,000 plate appearances —
            so the number to watch is the RESIDUAL SPREAD, not its
            significance.
            THE DECISIVE COMPARISON is per START: actual pitches against
            what `PITCH_COST` predicts from that start's own outcomes. That
            residual IS the variance the model throws away.
"""
from __future__ import annotations

import multiprocessing as mp
import statistics as st
import sys
from collections import defaultdict

from src import db
from src.context import sim
from src.context.sources import pbp

#: statsapi eventType -> the outcome constant `PITCH_COST` is keyed on.
EV = {
    "strikeout": sim.K, "strikeout_double_play": sim.K,
    "strikeout_triple_play": sim.K,
    "walk": sim.BB, "intent_walk": sim.BB,
    "hit_by_pitch": sim.HBP,
    "home_run": sim.HR, "single": sim.B1, "double": sim.B2,
    "triple": sim.B3,
    "sac_fly": sim.SAC, "sac_bunt": sim.SAC,
    "field_error": sim.ROE,
    "field_out": sim.OUT, "force_out": sim.OUT,
    "grounded_into_double_play": sim.OUT, "fielders_choice": sim.OUT,
    "fielders_choice_out": sim.OUT, "double_play": sim.OUT,
    "triple_play": sim.OUT, "sac_fly_double_play": sim.OUT,
    "other_out": sim.OUT,
}


def _one(gid):
    """-> (per-outcome pitch lists, [(actual, predicted) per start])."""
    per = defaultdict(list)
    starts = []
    try:
        d = pbp.fetch(gid)
    except Exception:
        return None
    if not d:
        return None
    first, acc = {}, defaultdict(lambda: [0, 0.0])
    for play in d.get("allPlays") or []:
        ab = play.get("about") or {}
        side = "away" if ab.get("isTopInning") else "home"
        pid = ((play.get("matchup") or {}).get("pitcher") or {}).get("id")
        if pid is None:
            continue
        first.setdefault(side, pid)
        ev = (play.get("result") or {}).get("eventType") or ""
        o = EV.get(ev)
        if o is None:
            continue
        n = sum(1 for e in (play.get("playEvents") or []) if e.get("isPitch"))
        if n == 0:
            continue
        per[o].append(n)
        if pid == first[side]:          # STARTER ONLY for the start-level row
            acc[side][0] += n
            acc[side][1] += sim.PITCH_COST[o]
    for side, (a, p) in acc.items():
        if a >= 30:
            starts.append((a, p))
    return {k: v for k, v in per.items()}, starts


def main(argv):
    cap = int(argv[0]) if argv else 2000
    with db.connect() as c:
        gids = [r["game_id"] for r in c.execute(
            "select game_id from games where sport='mlb' and status='Final'"
            " and date like '2026%' order by date")][:cap]
    with mp.get_context("fork").Pool(8) as p:
        got = [g for g in p.map(_one, gids, chunksize=16) if g]
    per = defaultdict(list)
    starts = []
    for d, s in got:
        for k, v in d.items():
            per[k].extend(v)
        starts.extend(s)

    print(f"  {len(got):,} games, {sum(len(v) for v in per.values()):,} "
          f"plate appearances, {len(starts):,} starts\n")
    print(f"  {'outcome':<8}{'n':>9}{'shipped':>9}{'actual':>9}{'sd':>7}"
          f"{'p10':>6}{'p90':>6}")
    for o in (sim.K, sim.BB, sim.HBP, sim.HR, sim.B1, sim.B2, sim.B3,
              sim.OUT, sim.SAC, sim.ROE):
        v = per.get(o)
        if not v or len(v) < 200:
            continue
        q = sorted(v)
        print(f"  {o:<8}{len(v):>9,}{sim.PITCH_COST[o]:>9.2f}"
              f"{st.mean(v):>9.2f}{st.pstdev(v):>7.2f}"
              f"{q[len(q)//10]:>6}{q[-len(q)//10]:>6}")

    # THE DECISIVE NUMBER. What the deterministic table cannot produce.
    resid = [a - p for a, p in starts]
    print(f"\n  === PER START: actual pitches vs what PITCH_COST predicts ===")
    print(f"    mean actual        {st.mean(a for a, _ in starts):>8.1f}")
    print(f"    mean predicted     {st.mean(p for _, p in starts):>8.1f}")
    print(f"    mean residual      {st.mean(resid):>+8.1f}")
    print(f"    SD OF THE RESIDUAL {st.pstdev(resid):>8.1f}"
          f"   <- variance the model discards")
    print(f"    sd of actual       {st.pstdev([a for a, _ in starts]):>8.1f}")
    print(f"    sd of predicted    {st.pstdev([p for _, p in starts]):>8.1f}")
    q = sorted(resid)
    print(f"    residual p10 {q[len(q)//10]:+.0f}   p90 {q[-len(q)//10]:+.0f}")


if __name__ == "__main__":
    main(sys.argv[1:])
