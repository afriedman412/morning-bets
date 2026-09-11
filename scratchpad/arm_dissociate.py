"""A REAL DECISION RESIDUAL THAT BUYS NO OUTS — which is it?

    venv/bin/python -m scratchpad.arm_dissociate [n_sims] [--limit N]

THE FINDING THAT OPENED THIS. TODO 32's per-arm offsets are measured, they
repeat year over year (r +0.558 boundary / +0.397 mid), and the offset-to-
outs sweep says a one-sd arm is worth ~0.37 outs against 2.05 outs of real
between-arm spread. That predicts a per-start outs correlation gain of +0.02
to +0.09. The measured gain is +0.0008 +/- 0.0052 — not small, ZERO. A real,
repeatable per-arm quantity is carrying no information about how long the man
actually lasts, and that dissociation is the thing to explain.

THREE CANDIDATES, and this separates them by arithmetic rather than by
argument. Each predicts a different pattern in the table below.

  E1  THE OFFSET IS ABOUT WHICH DECISION, NOT ABOUT LENGTH. An arm pulled
      mid-inning where the model pulls him at the boundary records the same
      outs. PREDICTS: the two curves' offsets disagree in sign for the arms
      that matter, and their implied outs cancel.
  E2  THE OFFSET IS FITTED WHERE THE INFORMATION IS, NOT WHERE THE OUTS ARE.
      A single log-odds shift is dominated by decisions near p = 0.5 (Fisher
      information is p(1-p)), but a start's LENGTH is decided by the
      cumulative hazard over eighty low-p decisions. The same delta moves
      absolute probability by 0.003 at p = 0.01 and by 0.075 at p = 0.5. So
      the offset can be real on a rate scale and worth nothing in outs.
      PREDICTS: an offset refitted on the DECISIVE decisions only (late, high
      pitch count) differs materially from the pooled one.
  E3  THE PER-ARM OUTS ERROR IS NOT THE HOOK AT ALL. It is pitch efficiency
      — a man at 3.5 pitches per batter reaches 100 two innings after one at
      4.5 — and the hook is the wrong place to correct it. PREDICTS: the
      per-arm OUTS residual is uncorrelated with the per-arm DECISION
      residual, and correlated with his pitches per batter instead.

WHAT IS COMPUTED. One replay pass over the holdout with every per-arm term
OFF, aggregated to one row per arm: his actual mean outs, the model's, and
the residual between them. That residual is the quantity `leash.py` fits.
It is then correlated against, in order:

    the SHIPPED leash offset          — must be POSITIVE (it was fitted on
                                        this, so a zero here would mean the
                                        leash is broken, not subtle)
    the new boundary offset           — E3 predicts ~0
    the new mid offset                — E3 predicts ~0
    their IMPLIED outs               — the sweep's conversion applied
    his pitches per batter            — E3's alternative carrier

THE SHIPPED LEASH IS THE POSITIVE CONTROL (rule 7). If the outs residual
does not correlate with the one term in the engine that was built from it,
this harness is broken and no null from it is reportable.
"""
from __future__ import annotations

import json
import math
import multiprocessing as mp
import os
import random
import statistics as st
import sys
import zlib
from collections import defaultdict

from src.context import armhook, calibrate as cal, leash, sim
from src.context.holdout import HOLDOUT
from src.context.sources import rates as rate_src

_CASES: dict = {}
_PENS: dict = {}
_SIMS = 24


def _init(cases, pens, sims):
    global _CASES, _PENS, _SIMS
    _CASES, _PENS, _SIMS = cases, pens, sims
    # EVERY per-arm term off: the residual must be measured against the bare
    # hook or it is a residual against a correction already applied, which is
    # the double-count `leash._sim_one` guards with `apply_leash=False`.
    sim.USE_ARM_HOOK = False
    sim.USE_LEASH = False
    sim.reload_offsets()


def _one(gid):
    pair = _CASES[gid]
    lg = sim.league()
    draws = [cal.replay(pair, lg, _PENS,
                        random.Random(zlib.crc32(f"{gid}|{d}".encode())))
             for d in range(_SIMS)]
    out = []
    for idx, side in ((0, "away_sp"), (1, "home_sp")):
        s = pair[idx][0]
        m = st.fmean(getattr(g, side).outs for g in draws)
        out.append((s["player_name"], s.get("o"), m))
    return out


def _corr(pairs):
    n = len(pairs)
    if n < 4:
        return 0.0, n
    mx = sum(x for x, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    num = sum((x - mx) * (y - my) for x, y in pairs)
    dx = sum((x - mx) ** 2 for x, _ in pairs) ** 0.5
    dy = sum((y - my) ** 2 for _, y in pairs) ** 0.5
    return (num / (dx * dy) if dx and dy else 0.0), n


def _d_outs_bnd(off):
    """Outs bought by a BOUNDARY offset, from `scratchpad/arm_sweep.py`:
    each curve alone delivers about half of what `team_offset` does, so the
    leash table's own conversion is halved. Measured, not assumed — and the
    sweep also found `OUTS_PER_OFFSET` itself is ~0.85 of its claim on the
    negative side, which is left in place here rather than silently fixed."""
    return leash._d_outs(off) * 0.5


def pitches_per_batter(before=None) -> dict:
    """His own pitches per batter faced, from real starts before the cut."""
    from src import db
    q = """select p.player_name nm, sum(p.pitches) pt,
                  sum(p.outs_recorded + p.h + p.bb) bf
           from mlb_pitching p join games g on g.game_id = p.game_id
           where g.sport='mlb' and g.status='Final' and p.is_starter=1
             and p.pitches is not null {w}
           group by p.player_name"""
    q = q.format(w=f" and g.date < '{before}'" if before else "")
    out = {}
    with db.connect() as c:
        for r in c.execute(q):
            if (r["bf"] or 0) > 200:
                out[r["nm"]] = r["pt"] / r["bf"]
    return out


def run(sims: int, limit: int | None) -> None:
    cases = cal.paired_cases(season=2026, since=HOLDOUT, rates_before=HOLDOUT)
    gids = sorted(cases)
    if limit:
        gids = gids[:limit]
    cases = {g: cases[g] for g in gids}
    pens = rate_src.bullpens(sim.league(), before=HOLDOUT)
    print(f"  {len(gids)} games x {sims} draws, all per-arm terms OFF")

    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, (os.cpu_count() or 4) - 2), initializer=_init,
                  initargs=(cases, pens, sims)) as pool:
        rows = pool.map(_one, gids, chunksize=8)

    by: dict = defaultdict(list)
    for r in rows:
        for nm, a, m in r:
            if a is not None:
                by[nm].append((a, m))
    # MIN STARTS, stated: an arm's outs residual over three starts is mostly
    # noise and would attenuate every correlation below toward zero — the
    # `m_er` failure CLAUDE.md records, noise in a PREDICTOR flattening a
    # slope, here noise in the TARGET flattening all of them equally.
    MIN_STARTS = 6
    resid = {nm: st.fmean(a - m for a, m in v)
             for nm, v in by.items() if len(v) >= MIN_STARTS}
    print(f"  {len(by)} arms, {len(resid)} with >= {MIN_STARTS} holdout "
          f"starts   residual sd {st.pstdev(resid.values()):.3f} outs")

    with open(armhook.PATH) as f:
        tbl = json.load(f)
    bnd, mid = tbl.get("bnd") or {}, tbl.get("mid") or {}
    with open(sim._LEASH_PATH) as f:
        lsh = {k: v for k, v in json.load(f).items() if k != "_meta"}
    ppb = pitches_per_batter(before=HOLDOUT)

    print(f"\n  corr( per-arm OUTS residual , X )     "
          f"positive = X predicts he goes LONGER than the model says")
    print(f"    {'X':<34}{'r':>8}{'n':>6}{'se':>7}")
    # NOTE THE SIGNS. A NEGATIVE hook offset means a longer leash, so a term
    # that correctly predicts a long arm correlates NEGATIVELY with a
    # positive outs residual. The implied-outs rows are in outs and so are
    # expected POSITIVE. Getting this backwards would invert the whole
    # reading, which is why both forms are printed.
    tests = (
        ("shipped leash offset (CONTROL)", lambda nm: lsh.get(nm)),
        ("shipped leash, implied outs", lambda nm: (
            leash._d_outs(lsh[nm]) if nm in lsh else None)),
        ("new boundary offset", lambda nm: bnd.get(nm)),
        ("new mid offset", lambda nm: mid.get(nm)),
        ("new offsets, implied outs", lambda nm: (
            _d_outs_bnd(bnd[nm]) + _d_outs_bnd(mid[nm])
            if nm in bnd and nm in mid else None)),
        ("his pitches per batter", lambda nm: ppb.get(nm)),
    )
    for label, fn in tests:
        pairs = [(fn(nm), resid[nm]) for nm in resid if fn(nm) is not None]
        r, n = _corr(pairs)
        se = 1 / max(n - 3, 1) ** 0.5
        print(f"    {label:<34}{r:>+8.3f}{n:>6}{se:>7.3f}")

    # E1's test: do the two curves' implied outs cancel for the arms that
    # carry both? If they did, the pooled term would be self-defeating.
    both = [nm for nm in resid if nm in bnd and nm in mid]
    if both:
        bo = [_d_outs_bnd(bnd[nm]) for nm in both]
        mo = [_d_outs_bnd(mid[nm]) for nm in both]
        tot = [b + m for b, m in zip(bo, mo)]
        print(f"\n  E1 — do the two curves cancel? over {len(both)} arms")
        print(f"    implied outs sd: boundary {st.pstdev(bo):.3f}  "
              f"mid {st.pstdev(mo):.3f}  COMBINED {st.pstdev(tot):.3f}")
        print("    combined LARGER than either means they reinforce, "
              "SMALLER means they cancel (E1).")
        r, n = _corr(list(zip(bo, mo)))
        print(f"    corr(boundary implied, mid implied) {r:+.3f}")


def main() -> None:
    args = sys.argv[1:]
    pos = [a for a in args if not a.startswith("-")]
    sims = int(pos[0]) if pos else 24
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    run(sims, limit)


if __name__ == "__main__":
    main()
