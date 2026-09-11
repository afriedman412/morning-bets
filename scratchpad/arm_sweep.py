"""WHAT DOES A LOG-ODDS OFFSET BUY IN OUTS ON *THIS* ENGINE?

    venv/bin/python -m scratchpad.arm_sweep [n_sims] [--limit N]

QUESTION. `leash.OUTS_PER_OFFSET` is a MEASURED table — mean simulated outs
at each `Hook.team_offset` — and every leash offset on disk was converted
through it. It was measured over 900 starts x 60 draws on the engine of
2026-08-23. Since then the boundary and mid-inning hazards were REPLACED by
counted tables (`USE_PITCH_HAZARD_BND`, 2026-09-09), the mid-inning relief
hook was re-keyed, and `for_pitcher` began setting a per-arm `pitch_center`
and `hard_pitch_cap`. Does an offset still buy what the table says?

WHY IT MATTERS TWICE OVER.

  1. IF THE DERIVATIVE HAS SHRUNK, the shipped `sim.leash` is delivering
     fewer outs than its own table claims, and every offset in
     `hook_leash.json` is mis-converted — not stale in the sense the
     `hook_hash` guard catches (the coefficients it hashes may be
     untouched) but mis-scaled, which no guard here looks for.
  2. IT IS THE FIRST CANDIDATE EXPLANATION FOR TODO 32's NULL. The per-arm
     decision offsets are real and measured (year-over-year r +0.558 /
     +0.397, sd 0.25 log-odds) and they moved the per-start outs
     correlation by +0.0008 +/- 0.0052 — essentially EXACTLY zero, where
     the arithmetic predicted +0.01 to +0.03. A hazard steep enough in
     pitch count absorbs a small offset: the pull moves by a fraction of a
     batter rather than by an inning, and the start lands on the same out.
     That would mean the hook CANNOT EXPRESS per-arm variation, which is a
     different defect from not knowing it — and the opposite prescription.

WHAT IS SWEPT. Four knobs, because they are not interchangeable and the
difference is the finding:

    team_offset      the OLD table's quantity — BOTH curves at once
    arm_bnd_offset   the boundary curve alone
    arm_mid_offset   the mid-inning curve alone
    both arm slots   what TODO 32's term actually applies

Paired seeds across every point, so two offsets differ only by the knob.
The comparison against `leash.OUTS_PER_OFFSET` is printed inline at the
points the table carries.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import random
import statistics as st
import sys
import zlib

from src.context import calibrate as cal, leash, sim
from src.context.holdout import HOLDOUT
from src.context.sources import rates as rate_src

_CASES: dict = {}
_PENS: dict = {}
_SIMS = 24
_KNOB = "team_offset"
_VAL = 0.0

POINTS = (-2.0, -1.0, -0.6, -0.3, -0.25, 0.0, 0.25, 0.3, 0.6, 1.0, 2.0)


def _init(cases, pens, sims, knob, val):
    global _CASES, _PENS, _SIMS, _KNOB, _VAL
    _CASES, _PENS, _SIMS, _KNOB, _VAL = cases, pens, sims, knob, val


def _one(gid):
    pair = _CASES[gid]
    lg = sim.league()
    if _KNOB == "both":
        hook = sim.Hook(arm_bnd_offset=_VAL, arm_mid_offset=_VAL)
    else:
        hook = sim.Hook(**{_KNOB: _VAL})
    outs = []
    for d in range(_SIMS):
        rng = random.Random(zlib.crc32(f"{gid}|{d}".encode()))
        g = cal.replay(pair, lg, _PENS, rng, hook=hook)
        outs += [g.away_sp.outs, g.home_sp.outs]
    return outs


def run(sims: int, limit: int | None) -> None:
    cases = cal.paired_cases(season=2026, since=HOLDOUT, rates_before=HOLDOUT)
    gids = sorted(cases)
    if limit:
        gids = gids[:limit]
    cases = {g: cases[g] for g in gids}
    pens = rate_src.bullpens(sim.league(), before=HOLDOUT)
    print(f"  {len(gids)} games x {sims} draws x {len(POINTS)} points "
          f"x 4 knobs")
    table = dict(leash.OUTS_PER_OFFSET)

    for knob in ("team_offset", "arm_bnd_offset", "arm_mid_offset", "both"):
        print(f"\n  {knob}")
        print(f"    {'offset':>8}{'mean outs':>11}{'d_outs':>9}"
              f"{'sd':>8}{'OUTS_PER_OFFSET':>18}{'ratio':>8}")
        # ZERO FIRST. Iterating POINTS in order left every negative offset
        # differencing against itself and printing +0.000 — the harness bug
        # that made the first run of this table unreadable on exactly the
        # half (longer leashes) it was built to check.
        zero = None
        for v in (0.0,) + tuple(p for p in POINTS if p != 0.0):
            ctx = mp.get_context("fork")
            with ctx.Pool(max(1, (os.cpu_count() or 4) - 2),
                          initializer=_init,
                          initargs=(cases, pens, sims, knob, v)) as pool:
                rows = pool.map(_one, gids, chunksize=8)
            allouts = [x for r in rows for x in r]
            m = st.mean(allouts)
            if v == 0.0:
                zero = m
            d = m - (zero if zero is not None else m)
            want = table.get(v)
            ratio = (d / want) if want else None
            print(f"    {v:>+8.2f}{m:>11.3f}{d:>+9.3f}"
                  f"{st.pstdev(allouts):>8.3f}"
                  f"{(f'{want:+.2f}' if want is not None else '—'):>18}"
                  f"{(f'{ratio:.2f}' if ratio else '—'):>8}")


def main() -> None:
    args = sys.argv[1:]
    pos = [a for a in args if not a.startswith("-")]
    sims = int(pos[0]) if pos else 24
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    run(sims, limit)


if __name__ == "__main__":
    main()
