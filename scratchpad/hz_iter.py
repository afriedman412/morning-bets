"""ITERATE THE BOUNDARY TABLE AGAINST THE MODEL'S OWN STATES. TODO 7a.

    venv/bin/python -m scratchpad.hz_iter [n_sims] [max_iters]

QUESTION    `PITCH_HAZARD_BND` was solved conditional on REAL game states
            and applied to OURS, which are calmer — cell error 0.0314
            against the parametric curve's 0.0265. What value does each
            bucket need so that OUR SIMULATED GAMES produce the REAL
            removal rate?

NOT A RE-CENTRING. The aggregate is not the target; each bucket must hit
its own real rate inside our games. The update is measured entirely
against real baseball — it just checks the answer where it gets used
rather than where it was counted.

TRAIN ONLY. The first version of this script targeted May-June rates and
it was wrong in a way worth recording, because the bug is invisible
unless you look for it:

    THE BOUNDARY HAZARD HAS A STRONG SEASONAL SHAPE AND THE MODEL HAS NO
    CALENDAR. Pooled over the 50-78 pitch buckets, train rows:

        Mar 0.2205   Apr 0.0684   May 0.0663   Jun 0.0715
        Jul 0.0754   Aug 0.0757   Sep 0.1041   Oct 0.1027

    Starters are not stretched out in March and are managed hardest in
    September. May-June is the TROUGH (0.0688) and every scoring run in
    this project — the battery's four folds, `hz_cv`, `shape.py` — is
    July-onward (0.0853). Fitting in the trough and scoring outside it
    builds a 24% under-pull into the table, and it showed up exactly
    there: the May-June fit under-pulled at 60/70/78 on the 2026 holdout
    and the o18.5/o20.5 lines overshot in two folds.

WHY THE WINDOWS START IN MAY AND NOT IN APRIL, and it is a DATA limit
rather than a modelling choice. Rates are frozen at each window's start,
the battery's idiom, and at an APRIL 1 freeze almost no arm has cleared
`MIN_PEN_APPS` yet: 2026-04-01 resolves to 17 pen clubs and 30 arms
(median 2 per club), 2023-04-01 to 103 arms. `build_side` draws 8, and
`Side.current` CLAMPS to the last arm when the pen runs out and returns
the STARTER when it is empty — so an April-frozen replay is close to the
bullpen-free engine TODO 20 records. A May 1 freeze gives 9-10 arms a
club and a July 1 freeze 12-13, both of which support the draw.

So the fitted population is MAY THROUGH SEPTEMBER, pooling to 0.0775
against the scored window's 0.0853 — the residual under-pull is ~9%
rather than the 24% the trough fit carried, and it is MEASURED and
recorded rather than hidden. Closing it needs a calendar term in the
hook, which is a separate item and not this one.

Windows are May-July and July-October of 2023-2025 plus May-July of
2026, and the target rates are counted on EXACTLY those date ranges, so
the simulated states and the real rates describe one population. Every
row predates 2026-07-01.

THE UPDATE. Realised hazard in a bucket is the mean probability the curve
returns over the decisions the model makes there (`game.py` fires on
`rng.random() < p`, so averaging p is the realised rate). Each iteration
moves the bucket by the logit gap to the real rate, clipped to +-1.5.
Fixed seeds across iterations: the map from table to realised rates is
deterministic, so convergence is not chasing simulation noise.
"""
from __future__ import annotations

import json
import math
import multiprocessing as mp
import random
import sys
from collections import defaultdict

from src.context import sim

from src.context import calibrate as cal, game  # noqa: E402
from src.context.sources import rates as rate_src  # noqa: E402
from scratchpad.dispersion import perturb  # noqa: E402
from scratchpad.pitch_hazard import EDGES, ROWS  # noqa: E402
from src.context.holdout import HOLDOUT  # noqa: E402

WINDOWS = ((2023, "2023-05-01", "2023-07-01"),
           (2023, "2023-07-01", "2023-10-01"),
           (2024, "2024-05-01", "2024-07-01"),
           (2024, "2024-07-01", "2024-10-01"),
           (2025, "2025-05-01", "2025-07-01"),
           (2025, "2025-07-01", "2025-10-01"),
           (2026, "2026-05-01", "2026-07-01"))
MIN_MODEL = 200   #: decisions the model must make in a bucket to update it
CLIP = 1.5

#: THE STARTING POINT, hardcoded rather than read off `sim.PITCH_HAZARD_BND`
#: so a re-run reproduces the same answer whatever happens to be shipped at
#: the time. These are `pitch_hazard.py`'s values — solved against REAL
#: states, which is the thing this script exists to correct.
SEED_TABLE = ((0, -5.3504), (25, -5.3196), (40, -5.7343),
              (50, -5.2571), (60, -4.6492), (70, -3.8836),
              (78, -3.1352), (85, -2.2086), (90, -1.2026),
              (95, 0.2150), (100, 1.3943))

#: THE STARTING POINT, hardcoded rather than read off `sim.PITCH_HAZARD_BND`
#: so a re-run reproduces the same answer whatever is shipped at the time.
#: These are `pitch_hazard.py`'s values — solved on real states, which is
#: the thing this script exists to correct.
SEED_TABLE = ((0, -5.3504), (25, -5.3196), (40, -5.7343),
              (50, -5.2571), (60, -4.6492), (70, -3.8836),
              (78, -3.1352), (85, -2.2086), (90, -1.2026),
              (95, 0.2150), (100, 1.3943))

_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 4
_LOG: list = []


def bucket(p):
    for lo, hi in zip(EDGES, EDGES[1:]):
        if lo <= p < hi:
            return lo
    return EDGES[-2]


def _wrap():
    # ONCE PER PROCESS. Re-wrapping per game stacked the logger N deep, so
    # a worker's Nth game logged every decision N times — later games got
    # N times the weight. Found here, and `hz_cells.py` shipped its cell
    # errors with the same defect.
    if getattr(sim.Hook.removal_p, "_is_wrapped", False):
        return
    bnd = sim.Hook.removal_p

    def rp(self, pitches, *a, **k):
        p = bnd(self, pitches, *a, **k)
        _LOG.append((bucket(pitches), p))
        return p

    rp._is_wrapped = True
    sim.Hook.removal_p = rp


def _one(args):
    i, gid = args
    _LOG.clear()
    _wrap()
    v = _CASES[gid]
    home = next(x for x in v if x[0]["is_home"])
    away = next(x for x in v if not x[0]["is_home"])
    an = cal.adjust_lineup(away[2], False)
    hn = cal.adjust_lineup(home[2], True)
    for draw in range(_SIMS):
        rng = random.Random(7 + i * 100003 + draw)
        za, zh = rng.gauss(0, 1), rng.gauss(0, 1)
        A = game.build_side(perturb(away[1], za, 0.0),
                            _PENS.get((away[0]["team"] or "").upper(), []),
                            hn, sim.Hook(), rng, team=away[0]["team"],
                            date=away[0].get("date"))
        H = game.build_side(perturb(home[1], zh, 0.0),
                            _PENS.get((home[0]["team"] or "").upper(), []),
                            an, sim.Hook(), rng, team=home[0]["team"],
                            date=home[0].get("date"))
        game.simulate_game(A, H, _LG, rng)
    agg = defaultdict(lambda: [0.0, 0])
    for b, p in _LOG:
        agg[b][0] += p
        agg[b][1] += 1
    return dict(agg)


def load_windows():
    """One (cases, league, pens) triple per season window, cached across
    iterations — building rates is the expensive part, not the pool.

    `season=` IS PASSED EXPLICITLY on the pen call. Without it the season
    resolves to the CURRENT one and a `before` two years earlier used to
    return nothing — the defect behind TODO 20, where three of four folds
    in every cross-fold result on record ran with no bullpen at all.
    `rates._where` now handles it, and naming the season anyway means this
    harness does not depend on that fix staying correct.

    THE PEN COUNT IS PRINTED, not assumed. An empty or near-empty pen is
    silent at every layer below this one: `build_side` draws what it is
    given and `Side.current` falls back to the starter.
    """
    out = []
    for season, since, before in WINDOWS:
        pairs = cal.paired_cases(season=season, since=since, before=before,
                                 rates_before=since)
        lg = sim.league(season=season, before=since)
        pens = rate_src.bullpens(lg, season=season, before=since)
        arms = sum(len(v) for v in pens.values())
        assert len(pens) >= 28 and arms >= 200, (since, len(pens), arms)
        out.append((season, {g: pairs[g] for g in sorted(pairs)}, lg, pens))
        print(f"  {season} {since}..{before}: {len(pairs):>4} paired games, "
              f"{len(pens)} pen clubs, {arms} arms")
    return out


def real_targets():
    """Boundary decisions on EXACTLY the simulated windows, bucketed.

    Matching the two populations is the point — see the seasonal note in
    the module docstring. The holdout assertion is belt-and-braces: the
    windows are all train, and a future edit that widens one past the cut
    should fail loudly rather than fit on scored rows.
    """
    agg = defaultdict(lambda: [0, 0])
    for r in json.load(open(ROWS)):
        if not bool(r.get("ends_inning")):
            continue
        d = r.get("date") or ""
        if not any(s <= d < b for _, s, b in WINDOWS):
            continue
        assert d < HOLDOUT, f"fitting on a scored row: {d}"
        agg[bucket(r["pitches"])][0] += bool(r.get("removed"))
        agg[bucket(r["pitches"])][1] += 1
    return {b: (k / n, n) for b, (k, n) in agg.items() if n}


def one_pass(windows):
    global _CASES, _PENS, _LG
    model = defaultdict(lambda: [0.0, 0])
    ctx = mp.get_context("fork")
    for season, cases, lg, pens in windows:
        _CASES, _LG, _PENS = cases, lg, pens
        with ctx.Pool(max(1, (mp.cpu_count() or 2) - 1)) as pool:
            got = pool.map(_one, list(enumerate(sorted(cases))))
        for g in got:
            for b, (s, n) in g.items():
                model[b][0] += s
                model[b][1] += n
    return model


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def main(argv):
    global _SIMS
    pos = [a for a in argv if not a.startswith("-")]
    _SIMS = int(pos[0]) if pos else 4
    max_iters = int(pos[1]) if len(pos) > 1 else 6
    sim.USE_PITCH_HAZARD = True
    sim.USE_PITCH_HAZARD_BND = True

    targets = real_targets()
    windows = load_windows()
    tbl = dict(SEED_TABLE)
    print(f"\n  {_SIMS} sims/game, up to {max_iters} iterations\n")

    for it in range(1, max_iters + 1):
        sim.PITCH_HAZARD_BND = tuple(sorted(tbl.items()))
        model = one_pass(windows)
        print(f"  ITER {it}   "
              f"{'bucket':<8}{'model':>9}{'real':>9}{'gap':>9}"
              f"{'se':>8}{'n mdl':>9}{'n real':>8}{'update':>9}")
        done = True
        for b in EDGES[:-1]:
            if b not in targets:
                continue
            r, rn = targets[b]
            se = (max(r, 1e-6) * (1 - r) / rn) ** 0.5
            ms, mn = model.get(b, [0.0, 0])
            if mn < MIN_MODEL:
                print(f"           {b:<8}{'-':>9}{r:>9.4f}{'-':>9}"
                      f"{se:>8.4f}{mn:>9,}{rn:>8,}   (skip, thin)")
                continue
            m = ms / mn
            step = max(-CLIP, min(CLIP, logit(r) - logit(m)))
            gap = m - r
            if abs(gap) > max(se, 0.004):
                done = False
                tbl[b] = round(tbl[b] + step, 4)
                upd = f"{step:>+9.4f}"
            else:
                upd = f"{'ok':>9}"
            print(f"           {b:<8}{m:>9.4f}{r:>9.4f}{gap:>+9.4f}"
                  f"{se:>8.4f}{mn:>9,}{rn:>8,}{upd}")
        print()
        if done:
            print(f"  CONVERGED after {it} iterations")
            break

    print("PASTE INTO sim.py:")
    print("  PITCH_HAZARD_BND =", tuple(sorted(tbl.items())))


if __name__ == "__main__":
    main(sys.argv[1:])
