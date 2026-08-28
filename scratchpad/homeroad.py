"""HOME-FIELD ADVANTAGE IN RUNS — counted, and against what the model does.

    venv/bin/python -m scratchpad.homeroad [n_sims] [--cut DATE] [--all]

QUESTION (TODO 11d). After the half-innings were corrected on 2026-08-29 the
model has the HOME club outscoring the away club by 0.17 runs a game, while
reality has it the other way by 0.04 — a 0.21-run disagreement on per-club
totals, which are the stated product.

WHY THE HOME/ROAD CONSTANTS ARE THE FIRST SUSPECT, AND IT IS THE STANDING
LESSON IN THIS PROJECT. `HOME_OPP_K` 1.034 and `HOME_OPP_CONTACT` 0.981 were
MEASURED, but on RATES:

    K rate    home 0.2253 vs away 0.2110   +6.8%   z +3.49
    hit rate  home 0.2164 vs away 0.2253   -3.9%   z -2.15

and half the contrast is applied each way. What was never checked is the RUN
consequence — "fit the quantity that settles, not the upstream proxy" is the
most-repeated line in these docs, and a rate split is exactly an upstream
proxy. A +6.8% strikeout swing plus a -3.9% contact swing is a LARGE effect
in run terms, and nothing ever asked whether the league's actual home/away
run split is that big.

THE CLEAN WINDOW IS INNINGS 1-8. Both clubs bat in every one of them, so the
ninth-inning forfeit — the home club not batting when it already leads, which
is worth ~0.25 runs against its own total — is excluded BY CONSTRUCTION
rather than modelled and subtracted. Comparing full-game totals conflates the
two, and that conflation is what made 11d look ambiguous.

THREE ARMS, and the third is the attribution:

    ACTUAL        counted off the play-by-play
    MODEL         as shipped
    MODEL, OFF    `USE_HOME_ROAD = False`

The OFF arm is a POSITIVE CONTROL IN REVERSE: if the shipped spread is
caused by these constants, switching them off must collapse it toward the
actual-club-quality baseline. If the spread survives with them off, they are
not the mechanism and this whole line is wrong — that is the pre-registered
falsifier and it is checked before anything is changed.

WHAT IS PAIRED AND WHAT IS NOT. Real clubs differ in quality, so
`home - away` is not zero even with no home advantage at all; it reflects who
happened to be playing. The MODEL-MINUS-ACTUAL difference is therefore taken
PAIRED ON THE SAME GAME, which cancels club quality exactly. The `--all`
scan is for the LEVEL of real home-field advantage and is unpaired by nature.

POWER, STATED FIRST. Per-club runs in innings 1-8 have sd ~2.9, so the
within-game difference has sd ~4.1 and 926 games give se ~0.135 on the raw
`home - away`. That is NOT enough to resolve 0.21 on its own — which is
exactly why 11d was logged at 1.5-2 sigma and not as a finding. The MODEL
side, however, is an average over `n_sims` draws, so the paired
MODEL-MINUS-ACTUAL contrast is far sharper, and the MODEL-vs-MODEL-OFF
contrast shares its draws and is sharper still. Read those two, not the raw
level. `--all` over ~9,900 cached games puts se on the real level near 0.041.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import random
import statistics as st
import sys
import zlib

from src import db
from src.context import calibrate as cal, sim
from src.context.sources import pbp, rates as rate_src

CUT = "2026-05-15"
_CASES: dict = {}
_LG: dict = {}
_PENS: dict = {}


def _actual_18(gid: str) -> tuple[float, float] | None:
    """(away club runs, home club runs) in INNINGS 1-8, off the play-by-play.

    Runs on a play are the score CHANGE across it — the reading that survives
    an rbi being withheld on a double play or an error, and the same
    convention `where_runs` and `ninth.py` use.
    """
    aw_r = ho_r = 0
    seen = False
    for play, _b, _o, aw, ho in pbp.plays(gid):
        ab = play.get("about") or {}
        inn, half = ab.get("inning"), ab.get("halfInning")
        res = play.get("result") or {}
        if res.get("awayScore") is None or not inn:
            continue
        seen = True
        if inn > 8:
            continue
        got = res["awayScore"] + res["homeScore"] - (aw + ho)
        if got <= 0:
            continue
        if half == "top":
            aw_r += got
        else:
            ho_r += got
    return (aw_r, ho_r) if seen else None


def _model_18(gid: str, n_sims: int, home_road: bool) -> tuple[float, float]:
    rng = random.Random((zlib.crc32(gid.encode()) & 0xFFFF) * 1009)
    old = cal.USE_HOME_ROAD
    cal.USE_HOME_ROAD = home_road
    try:
        a = h = 0.0
        for _ in range(n_sims):
            r = cal.replay(_CASES[gid], _LG, _PENS, rng, track=(8,))
            # `prefix_side[8]` is (away TEAM score, home TEAM score) through
            # the eighth — already uncrossed, unlike a Side's `runs`.
            pa, ph = r.prefix_side.get(8, (0, 0))
            a += pa
            h += ph
        return a / n_sims, h / n_sims
    finally:
        cal.USE_HOME_ROAD = old


def _one(args):
    gid, n_sims = args
    act = _actual_18(gid)
    if act is None:
        return None
    return {"gid": gid, "act": act,
            "on": _model_18(gid, n_sims, True),
            "off": _model_18(gid, n_sims, False)}


def _all_one(gid):
    return _actual_18(gid)


#: Event types, matching `scratchpad/state_seasons.py` so the two scans
#: cannot disagree about what a plate appearance is.
PA_EV = {"strikeout", "strikeout_double_play", "walk", "intent_walk",
         "hit_by_pitch", "single", "double", "triple", "home_run",
         "field_out", "force_out", "grounded_into_double_play",
         "double_play", "triple_play", "sac_fly", "sac_bunt", "field_error",
         "fielders_choice", "fielders_choice_out", "catcher_interf",
         "sac_fly_double_play", "sac_bunt_double_play", "other_out"}
K_EV = {"strikeout", "strikeout_double_play"}
HIT_EV = {"single", "double", "triple", "home_run"}


def _rate_one(gid):
    """K and hit counts split by WHICH CLUB IS PITCHING, innings 1-8.

    The top half is the HOME club pitching and the bottom half is the AWAY
    club pitching, so `halfInning` IS the split — no roster lookup needed.
    Innings 1-8 only, matching the run window above: the ninth is forfeited
    asymmetrically and would bias a top/bottom comparison by composition.
    """
    out = {"home": [0, 0, 0, 0, 0], "away": [0, 0, 0, 0, 0]}
    # pa, k, hits, walks, home runs
    try:
        for play, _b, _o, _a, _h in pbp.plays(gid):
            ab = play.get("about") or {}
            inn, half = ab.get("inning"), ab.get("halfInning")
            if not inn or inn > 8:
                continue
            ev = (play.get("result") or {}).get("eventType") or ""
            if ev not in PA_EV:
                continue
            c = out["home" if half == "top" else "away"]
            c[0] += 1
            c[1] += ev in K_EV
            c[2] += ev in HIT_EV
            c[3] += ev in ("walk", "intent_walk", "hit_by_pitch")
            c[4] += ev == "home_run"
    except Exception:
        return None
    return out


def scan_rates():
    """Recount the split the two constants were SET from."""
    with db.connect() as c:
        gids = [r["game_id"] for r in c.execute(
            "select game_id from games where sport='mlb' and status='Final'"
            " order by date")]
    gids = [g for g in gids if pbp.have(g)]
    with mp.get_context("fork").Pool(max(1, (os.cpu_count() or 4) - 2)) as p:
        got = [g for g in p.map(_rate_one, gids, chunksize=16) if g]
    agg = {"home": [0] * 5, "away": [0] * 5}
    for g in got:
        for k in agg:
            for i in range(5):
                agg[k][i] += g[k][i]
    hp, hk, hh, hb, hhr = agg["home"]
    ap, ak, ah, ab, ahr = agg["away"]
    print(f"  THE RATE SPLIT THE CONSTANTS WERE SET FROM, RECOUNTED")
    print(f"  {len(got):,} games, {hp + ap:,} plate appearances,"
          f" innings 1-8\n")
    print(f"  {'quantity':<14}{'home':>9}{'away':>9}{'ratio':>9}"
          f"{'se':>8}{'z':>7}{'shipped':>9}")
    for lbl, (hn, an), ship in (("K per PA", (hk, ak), 1.026 ** 2),
                                ("hits per PA", (hh, ah), 0.990 ** 2),
                                ("walks+hbp/PA", (hb, ab), 1.0),
                                ("HR per PA", (hhr, ahr), 1.0)):
        hr_, ar_ = hn / hp, an / ap
        # se of the RATIO by the delta method on two binomials.
        vh = hr_ * (1 - hr_) / hp
        va = ar_ * (1 - ar_) / ap
        ratio = hr_ / ar_
        se = ratio * ((vh / hr_ ** 2) + (va / ar_ ** 2)) ** 0.5
        print(f"  {lbl:<14}{hr_:>9.4f}{ar_:>9.4f}{ratio:>9.4f}"
              f"{se:>8.4f}{(ratio - 1) / se:>+7.1f}{ship:>9.4f}")
        # HALF THE CONTRAST EACH WAY, which is what the constant holds.
        print(f"  {'  -> constant':<14}{ratio ** 0.5:>9.5f}"
              f"   (shipped {ship ** 0.5:.5f}, "
              f"{(ratio ** 0.5 - ship ** 0.5) / (0.5 * se):+.1f} sigma)")
    print("\n  WALKS AND HOME RUNS CARRY NO CONSTANT — `shipped` reads 1.0")
    print("  for them because the model has no home/away channel there at")
    print("  all. A split in those rows is a MISSING MECHANISM and is the")
    print("  honest explanation for any run-level shortfall.")
    print("\n  `shipped` is the FULL contrast the live constant implies —")
    print("  HOME_OPP_K 1.034 is half of it each way, so the comparable")
    print("  number is its square. A recount that lands on the shipped")
    print("  value means the constants were right and thinly measured.")


def paired(diffs):
    m = st.mean(diffs)
    se = st.pstdev(diffs) / len(diffs) ** 0.5 if len(diffs) > 1 else 0.0
    return m, se, (m / se if se else 0.0)


def _spread(rows, key):
    """home minus away, innings 1-8, under one arm."""
    return [r[key][1] - r[key][0] for r in rows]


def scan_all():
    """Real home-field advantage on every cached game. THE LEVEL."""
    with db.connect() as c:
        gids = [r["game_id"] for r in c.execute(
            "select game_id from games where sport='mlb' and status='Final'"
            " order by date")]
    gids = [g for g in gids if pbp.have(g)]
    print(f"  {len(gids):,} cached games\n", flush=True)
    with mp.get_context("fork").Pool(max(1, (os.cpu_count() or 4) - 2)) as p:
        got = [g for g in p.map(_all_one, gids, chunksize=16) if g]
    aw = st.mean(a for a, _h in got)
    ho = st.mean(h for _a, h in got)
    d = [h - a for a, h in got]
    m, se, z = paired(d)
    print("  REAL HOME-FIELD ADVANTAGE, innings 1-8 (both clubs always bat)")
    print(f"  {'away club':<22}{aw:>9.3f}")
    print(f"  {'home club':<22}{ho:>9.3f}")
    print(f"  {'home - away':<22}{m:>9.3f}   se {se:.3f}   z {z:+.1f}"
          f"   n={len(got):,}")
    return m


def main(argv):
    global _CASES, _LG, _PENS, CUT
    if "--cut" in argv:
        i = argv.index("--cut")
        CUT = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    do_all = "--all" in argv
    argv = [a for a in argv if a != "--all"]
    n_sims = int(argv[0]) if argv and argv[0].isdigit() else 20

    if do_all:
        scan_all()
        print()
        scan_rates()
        print()

    _LG = sim.league()
    _PENS = rate_src.bullpens(_LG, before=CUT)
    _CASES = cal.paired_cases(season=2026, since=CUT, rates_before=CUT)
    print(f"  HOLDOUT: rates before {CUT}, {len(_CASES)} games x {n_sims}"
          f" sims x 2 arms\n", flush=True)
    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, (os.cpu_count() or 4) - 2)) as pool:
        rows = [r for r in pool.map(_one, [(g, n_sims) for g in _CASES],
                                    chunksize=8) if r]

    print(f"  INNINGS 1-8 ONLY — the ninth-inning forfeit is excluded by")
    print(f"  construction, so this is home-field advantage alone."
          f"  {len(rows)} games\n")
    print(f"  {'arm':<22}{'away':>9}{'home':>9}{'home-away':>11}{'se':>8}")
    for lbl, key in (("actual", "act"), ("model, as shipped", "on"),
                     ("model, home/road OFF", "off")):
        aw = st.mean(r[key][0] for r in rows)
        ho = st.mean(r[key][1] for r in rows)
        m, se, _z = paired(_spread(rows, key))
        print(f"  {lbl:<22}{aw:>9.3f}{ho:>9.3f}{m:>11.3f}{se:>8.3f}")

    print("\n  PAIRED CONTRASTS — the sharp readings, same games\n")
    print(f"  {'contrast':<34}{'gap':>9}{'se':>8}{'z':>7}")
    on_a = _spread(rows, "on")
    off_a = _spread(rows, "off")
    ac_a = _spread(rows, "act")
    for lbl, d in (
            ("model(on) - actual", [x - y for x, y in zip(on_a, ac_a)]),
            ("model(off) - actual", [x - y for x, y in zip(off_a, ac_a)]),
            ("model(on) - model(off)  [the constants]",
             [x - y for x, y in zip(on_a, off_a)])):
        m, se, z = paired(d)
        print(f"  {lbl:<34}{m:>+9.3f}{se:>8.3f}{z:>+7.1f}")

    print("\n  READ THE LAST ROW FIRST. It is what the two constants are")
    print("  WORTH in runs, on shared draws. If `model(on) - actual` is")
    print("  positive and of similar size, the constants are overstated by")
    print("  about that much and the fix is to rescale them. If turning")
    print("  them off does NOT collapse the gap, they are not the mechanism")
    print("  and 11d lives somewhere else — that is the falsifier.")


if __name__ == "__main__":
    main(sys.argv[1:])
