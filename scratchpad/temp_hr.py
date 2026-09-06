"""COUNT home runs per ball in play by temperature, for plan item 5.

    venv/bin/python -m scratchpad.temp_hr [--backfill]

COVERAGE FIRST: the share of pre-cut games with a temperature is printed
before any rate, because a count over the games that happen to have
weather is a different population than "the league" until shown
otherwise.

Rows are pre-July of all four seasons (rule 6 per fold), which makes the
generalisation out-of-sample BY CONSTRUCTION: the relation is counted on
SPRING temperatures and scored on SUMMER holdouts. The covariate is
exogenous (weather does not depend on outcomes), so the 4b/4c leakage
class does not apply.

The denominator is the battery's `bip` exactly — hits (incl. HR) +
in-play outs + sacs + errors — so the counted table and the scoring
rows cannot disagree about what a ball in play was.

Also printed, for the record and not for wiring: HR/BIP by signed wind
carry, and the dome/roof-closed split (their reported temps are
controlled air, kept in their bins).
"""
from __future__ import annotations

import json
import multiprocessing as mp
import statistics as st
import sys
from collections import defaultdict
from itertools import combinations

from src import db
from src.context.sources import pbp, weather
from scratchpad.battery import EV_HIT, EV_INPLAY_OUT, EV_SAC

CACHE = "scratchpad/temp_hr_rows.json"
CUTS = {s: f"{s}-07-01" for s in (2023, 2024, 2025, 2026)}

#: 10F bins; the ends are open because <45 and >95 are thin.
EDGES = (55, 65, 75, 85)
LABELS = ("<55", "55-64", "65-74", "75-84", "85+")


def tbin(t: int) -> int:
    return sum(t >= e for e in EDGES)


def _one(args):
    gid, season = args
    hr = bip = 0
    try:
        for play, _b, _o, _a, _h in pbp.plays(gid):
            ev = (play.get("result") or {}).get("eventType") or ""
            if (ev in EV_HIT or ev in EV_INPLAY_OUT or ev in EV_SAC
                    or ev == "field_error"):
                bip += 1
                hr += ev == "home_run"
    except Exception:
        return None
    return (gid, season, hr, bip)


def backfill():
    with db.connect() as c:
        games = [(r["game_id"], int(r["date"][:4])) for r in
                 c.execute("select game_id, date from games where "
                           "sport='mlb' and status='Final' "
                           "and substr(date,6,5) < '07-01' order by date")]
    games = [(g, s) for g, s in games if s in CUTS and pbp.have(g)]
    print(f"  {len(games):,} pre-cut cached games", flush=True)
    with mp.get_context("fork").Pool(8) as p:
        got = [g for g in p.map(_one, games, chunksize=16) if g]
    json.dump(got, open(CACHE, "w"))
    print(f"  wrote {len(got):,} games to {CACHE}")
    return got


def _odds(p):
    return p / (1 - p)


def report(rows):
    wx = weather.by_game()
    joined = []
    roofless = 0
    for gid, season, hr, bip in rows:
        w = wx.get(gid) or {}
        joined.append((season, w.get("temp_f"), w.get("carry"),
                       w.get("wind_mph"), w.get("roof_closed"), hr, bip))
    have_t = [r for r in joined if r[1] is not None]
    print(f"\n  COVERAGE: {len(have_t):,} of {len(joined):,} pre-cut games "
          f"have a temperature ({len(have_t) / len(joined):.1%}); "
          f"roof closed in {sum(r[4] or 0 for r in have_t):,}")
    seasons = sorted({r[0] for r in have_t})
    HR = sum(r[5] for r in have_t)
    BIP = sum(r[6] for r in have_t)
    lg = HR / BIP
    print(f"  league HR/BIP {lg:.4f} on {BIP:,} balls in play"
          + "".join(f"   {s} "
                    f"{sum(r[5] for r in have_t if r[0] == s) / sum(r[6] for r in have_t if r[0] == s):.4f}"
                    for s in seasons))

    print(f"\n  HR/BIP by temperature ({'/'.join(LABELS)})")
    print(f"  {'bin':<8}{'games':>7}{'bip':>9}{'rate':>8}{'se':>8}"
          f"{'odds x':>8}" + "".join(f"{s:>8}" for s in seasons))
    mults = []
    for b, lab in enumerate(LABELS):
        sub = [r for r in have_t if tbin(r[1]) == b]
        sb = sum(r[6] for r in sub)
        p = sum(r[5] for r in sub) / sb
        se = (p * (1 - p) / sb) ** 0.5
        om = _odds(p) / _odds(lg)
        mults.append(om)
        cols = []
        for s in seasons:
            ss = [r for r in sub if r[0] == s]
            sl = [r for r in have_t if r[0] == s]
            slr = sum(r[5] for r in sl) / sum(r[6] for r in sl)
            cols.append(_odds(sum(r[5] for r in ss)
                              / sum(r[6] for r in ss)) / _odds(slr)
                        if ss else None)
        print(f"  {lab:<8}{len(sub):>7,}{sb:>9,}{p:>8.4f}{se:>8.4f}"
              f"{om:>8.3f}"
              + "".join(f"{c:>8.3f}" if c is not None else f"{'-':>8}"
                        for c in cols))

    per = {}
    for s in seasons:
        sl = [r for r in have_t if r[0] == s]
        slr = sum(r[5] for r in sl) / sum(r[6] for r in sl)
        v = []
        for b in range(5):
            ss = [r for r in sl if tbin(r[1]) == b]
            v.append(_odds(sum(r[5] for r in ss) / sum(r[6] for r in ss))
                     / _odds(slr) if ss and sum(r[6] for r in ss) else None)
        per[s] = v
    cors = []
    for a, b in combinations(seasons, 2):
        xs = [(x, y) for x, y in zip(per[a], per[b])
              if x is not None and y is not None]
        if len(xs) > 2:
            cors.append(st.correlation([x for x, _ in xs],
                                       [y for _, y in xs]))
    print(f"\n  era gate: mean between-season correlation of the odds "
          f"ratios {st.mean(cors):.3f} over {len(cors)} pairs")

    # Domes as their own control: closed-roof air is ~constant, so their
    # rate should sit near the league whatever the reported temp says.
    dome = [r for r in have_t if r[4]]
    if dome:
        db_ = sum(r[6] for r in dome)
        dp_ = sum(r[5] for r in dome)
        print(f"  roof closed: HR/BIP {dp_ / db_:.4f} on {db_:,} bip "
              f"({len(dome):,} games), odds x {_odds(dp_ / db_) / _odds(lg):.3f}")

    print("\n  HR/BIP by wind (open air only) — counted for the record")
    open_air = [r for r in have_t if not r[4] and r[2] is not None]
    for lab, cond in (("in  5+", lambda r: r[2] < 0 and r[3] >= 5),
                      ("calm/cross", lambda r: r[2] == 0 or r[3] < 5),
                      ("out 5+", lambda r: r[2] > 0 and r[3] >= 5)):
        sub = [r for r in open_air if cond(r)]
        if not sub:
            continue
        sb = sum(r[6] for r in sub)
        p = sum(r[5] for r in sub) / sb
        se = (p * (1 - p) / sb) ** 0.5
        print(f"  {lab:<11}{len(sub):>7,}{sb:>9,}{p:>8.4f}{se:>8.4f}"
              f"{_odds(p) / _odds(lg):>8.3f}")

    # ── WITHIN-VENUE, the table that actually ships ──────────────────
    #
    # The pooled count above CONFOUNDS TEMPERATURE WITH PARK: hot games
    # concentrate in particular buildings, so the pooled ratios absorb
    # park — which the engine already applies separately, per venue and
    # year. Wired pooled, the first battery run showed exactly that
    # signature: the model's slope ran ~2x the holdout's. Here each
    # game's HR is compared to ITS OWN VENUE's pre-cut baseline
    # (indirect standardisation), so identification comes from the same
    # park being hot in June and cold in April — net of venue by
    # construction, matching the code path that applies park and
    # temperature as separate multipliers.
    wx2 = weather.by_game()
    vrows = []
    for gid, season, hr, bip in rows:
        w = wx2.get(gid) or {}
        if w.get("temp_f") is not None and w.get("venue_id") is not None:
            vrows.append((season, w["temp_f"], w["venue_id"], hr, bip))
    vrate = defaultdict(lambda: [0, 0])
    for s, t, v, hr, bip in vrows:
        vrate[v][0] += hr
        vrate[v][1] += bip
    print("\n  WITHIN-VENUE: observed / venue-expected HR by temperature")
    print(f"  {'bin':<8}{'games':>7}{'obs':>7}{'exp':>9}{'ratio':>8}"
          f"{'se':>8}" + "".join(f"{s:>8}" for s in seasons))
    vm = []
    per_v = {s: [] for s in seasons}
    for b, lab in enumerate(LABELS):
        sub = [r for r in vrows if tbin(r[1]) == b]
        obs = sum(r[3] for r in sub)
        exp = sum(vrate[r[2]][0] / vrate[r[2]][1] * r[4] for r in sub)
        ratio = obs / exp
        se = ratio / obs ** 0.5
        vm.append(ratio)
        cols = []
        for s in seasons:
            ss = [r for r in sub if r[0] == s]
            o = sum(r[3] for r in ss)
            e = sum(vrate[r[2]][0] / vrate[r[2]][1] * r[4] for r in ss)
            cols.append(o / e if e else None)
            per_v[s].append(o / e if e else None)
        print(f"  {lab:<8}{len(sub):>7,}{obs:>7,}{exp:>9.1f}{ratio:>8.3f}"
              f"{se:>8.3f}"
              + "".join(f"{c:>8.3f}" if c is not None else f"{'-':>8}"
                        for c in cols))
    cors = []
    for a, b in combinations(seasons, 2):
        xs = [(x, y) for x, y in zip(per_v[a], per_v[b])
              if x is not None and y is not None]
        if len(xs) > 2:
            cors.append(st.correlation([x for x, _ in xs],
                                       [y for _, y in xs]))
    print(f"  era gate (within-venue): {st.mean(cors):.3f} over "
          f"{len(cors)} pairs")

    # THE CENTRING REFERENCE IS CLIMATE, NOT THE TRAINING WINDOW. The
    # model's baseline HR rates are built from prior FULL seasons plus
    # the current spring, so the average season's air is already inside
    # them; a table centred on the SPRING temp distribution re-adds the
    # summer premium and lifts the July-onward level (+5.2% mean mult,
    # the first battery run's level miss). The reference is the mean
    # multiplier over the PRIOR SEASONS' full-year temperature
    # distribution — climate, exogenous, no scored outcome involved.
    def _mult(t, table):
        return table[tbin(t)]
    with __import__("importlib").import_module(
            "src.context.store").connect(attach=False) as c:
        clim = [r["temp_f"] for r in c.execute(
            "select temp_f from mlb_weather where temp_f is not null "
            "and date < '2026-01-01'")]
    ref = sum(_mult(t, vm) for t in clim) / len(clim)
    out = tuple(round(m / ref, 4) for m in vm)
    print(f"\n  climate reference (prior full seasons, {len(clim):,} "
          f"games): mean raw mult {ref:.4f}")
    print("\n  CONSTANTS TO SHIP (within-venue, climate-centred):")
    print(f"  TEMP_HR_EDGES = {EDGES}")
    print(f"  TEMP_HR_MULT = {out}")

    wind_report(rows, wx2, vrate, seasons)


# ── WIND, plan item 7 ────────────────────────────────────────────────────
#
# `carry * wind_mph` is the signed scalar with the physics in it (see
# `sources/weather.py`): +12 is twelve miles an hour blowing out, -12 is
# the same wind in, and a crosswind is 0 whatever its speed.
WIND_EDGES = (-10, -5, 5, 10)
WIND_LABELS = ("in 10+", "in 5-9", "calm/cross", "out 5-9", "out 10+")
#: The PRE-REGISTERED binning (item 7). The five-bin split above is
#: printed for the record and is NOT the ship candidate — see the gate.
WIND_LABELS3 = ("in 5+", "calm/cross", "out 5+")


def wbin(carry: int | None, mph: int | None) -> int:
    """Signed carry scalar -> bin. Symmetric about zero: 10+ each way is
    its own bin, 5-9 each way, everything under 5 (and every crosswind,
    whatever its speed) is calm."""
    s = (carry or 0) * (mph or 0)
    if s <= -10:
        return 0
    if s <= -5:
        return 1
    if s < 5:
        return 2
    return 3 if s < 10 else 4


def wbin3(carry: int | None, mph: int | None) -> int:
    s = (carry or 0) * (mph or 0)
    return 0 if s <= -5 else (1 if s < 5 else 2)


def wind_report(rows, wx, vrate, seasons):
    """Wind counted the way temperature ships: within venue, and NET OF
    THE TEMPERATURE MULTIPLIER ALREADY WIRED.

    THE SECOND ADJUSTMENT IS THE NEW ONE AND IT IS THE SAME CLASS OF
    MISTAKE AS THE PARK CONFOUND. Wind and temperature are correlated —
    an April day with the wind in is also a cold day — so a wind table
    counted against a flat expectation absorbs temperature, which the
    engine now applies separately. Expectation is therefore
    `venue_rate * TEMP_HR_MULT[bin(temp)]`, renormalised per venue so a
    park's own temperature composition cannot leak into the level
    either. What is left is identified by the same park, at the same
    temperature, with the wind blowing different ways.

    Open air only: `roof_closed` games are a different physical object
    and 795 of them would sit in the calm bin diluting it. They get 1.0
    at run time through the calm bin anyway (a sealed park reports 0
    mph), so nothing is lost by leaving them out of the count.
    """
    import src.context.sim as sim

    wrows = []
    for gid, season, hr, bip in rows:
        w = wx.get(gid) or {}
        if (w.get("temp_f") is None or w.get("venue_id") is None
                or w.get("roof_closed")):
            continue
        tm = sim.TEMP_HR_MULT[tbin(w["temp_f"])]
        wrows.append((season, (w.get("carry") or 0) * (w.get("wind_mph") or 0),
                      w["venue_id"], tm, hr, bip))
    # per-venue renormalisation of the temperature-adjusted expectation
    k = defaultdict(lambda: [0.0, 0.0])
    for s, b, v, tm, hr, bip in wrows:
        k[v][0] += hr
        k[v][1] += vrate[v][0] / vrate[v][1] * tm * bip
    print("\n  WIND, WITHIN-VENUE AND NET OF THE SHIPPED TEMP TABLE")
    print("  five bins, FOR THE RECORD — the ship candidate is the "
          "pre-registered three")
    _wind_table(wrows, vrate, k, seasons, WIND_LABELS,
                lambda s: (0 if s <= -10 else 1 if s <= -5
                           else 2 if s < 5 else 3 if s < 10 else 4))
    print("\n  THE PRE-REGISTERED THREE BINS (item 7's own gate)")
    wm = _wind_table(wrows, vrate, k, seasons, WIND_LABELS3,
                     lambda s: 0 if s <= -5 else (1 if s < 5 else 2))

    # Climate reference: prior seasons' FULL-YEAR wind distribution, the
    # 1.0191 analogue. The training rows are spring; the baseline rates
    # already contain an average season's air, so centring on the spring
    # wind distribution would re-add whatever spring's wind does.
    with __import__("importlib").import_module(
            "src.context.store").connect(attach=False) as c:
        clim = [(r["carry"], r["wind_mph"]) for r in c.execute(
            "select carry, wind_mph from mlb_weather where date < "
            "'2026-01-01' and roof_closed = 0")]
    ref = sum(wm[wbin3(cy, mph)] for cy, mph in clim) / len(clim)
    out = tuple(round(m / ref, 4) for m in wm)
    print(f"\n  climate reference (prior full seasons, {len(clim):,} open-air "
          f"games): mean raw mult {ref:.4f}")
    print("  CONSTANTS TO SHIP (wind, within-venue, temp-adjusted, "
          "climate-centred):")
    print(f"  WIND_HR_MULT = {out}")


def _wind_table(wrows, vrate, k, seasons, labels, binner):
    """One table over the same expectation, binned however `binner` says.
    Returns the pooled ratio per bin."""
    print(f"  {'bin':<12}{'games':>7}{'obs':>7}{'exp':>9}{'ratio':>8}"
          f"{'se':>8}" + "".join(f"{s:>8}" for s in seasons))
    wm, per_w = [], {s: [] for s in seasons}
    for b, lab in enumerate(labels):
        sub = [r for r in wrows if binner(r[1]) == b]
        obs = sum(r[4] for r in sub)
        exp = sum(vrate[r[2]][0] / vrate[r[2]][1] * r[3] * r[5]
                  * (k[r[2]][0] / k[r[2]][1]) for r in sub)
        ratio = obs / exp
        wm.append(ratio)
        cols = []
        for s in seasons:
            ss = [r for r in sub if r[0] == s]
            o = sum(r[4] for r in ss)
            e = sum(vrate[r[2]][0] / vrate[r[2]][1] * r[3] * r[5]
                    * (k[r[2]][0] / k[r[2]][1]) for r in ss)
            cols.append(o / e if e else None)
            per_w[s].append(o / e if e else None)
        print(f"  {lab:<12}{len(sub):>7,}{obs:>7,}{exp:>9.1f}{ratio:>8.3f}"
              f"{ratio / max(obs, 1) ** 0.5:>8.3f}"
              + "".join(f"{c:>8.3f}" if c is not None else f"{'-':>8}"
                        for c in cols))
    cors = []
    for a, b in combinations(seasons, 2):
        xs = [(x, y) for x, y in zip(per_w[a], per_w[b])
              if x is not None and y is not None]
        if len(xs) > 2:
            cors.append(st.correlation([x for x, _ in xs],
                                       [y for _, y in xs]))
    print(f"  era gate (wind, within-venue): {st.mean(cors):.3f} over "
          f"{len(cors)} pairs")
    print("  ORDERING GATE (item 7: park the item if it fails any season)")
    for s in seasons:
        v = [x for x in per_w[s] if x is not None]
        mono = all(a <= b for a, b in zip(v, v[1:]))
        print(f"    {s}: {'  '.join(f'{x:.3f}' for x in v)}   "
              f"{'monotone' if mono else 'NOT MONOTONE'}   "
              f"ends {'ordered' if v[0] < v[-1] else 'INVERTED'}")
    return wm


def main(argv):
    rows = backfill() if "--backfill" in argv \
        else [tuple(r) for r in json.load(open(CACHE))]
    report(rows)


if __name__ == "__main__":
    main(sys.argv[1:])
