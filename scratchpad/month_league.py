"""A MONTH-CONDITIONED league baseline. Measured on prior years, scored on 2026.

    venv/bin/python -m scratchpad.month_league [n_sims] [salts]
    venv/bin/python -m scratchpad.month_league --measure     # factors only

QUESTION. `sim.league()` is ONE season-wide baseline, so the model produces
the same number of runs in May as in July while the league does not. Does
conditioning it on the calendar month improve what settles?

WHY THIS IS BUILT DESPITE THE MEASUREMENT ARGUING AGAINST IT. Pooled over
four seasons only MAY replicates (-0.134 runs, -3.0%, negative every year,
z -5.0); 2026's own profile ANTICORRELATES with 2025 and 2023. So the
expectation is a small May gain and nothing elsewhere. Building it is how
that expectation gets tested rather than asserted.

THE FACTORS COME FROM 2023-2025 AND ARE APPLIED TO 2026. Fitting them on the
season being scored would guarantee a win and prove nothing, and it is the
exact leak that made the home-run compression look like a defect. Measuring
on prior years also makes this a real test of whether the month effect
GENERALISES, which is the thing actually in doubt.

AND THE FACTORS ARE MEASURED PER CHANNEL, not assumed. A run-environment
shift could be strikeouts, home runs or balls in play, and which one it is
decides how it enters. They ride the PARK path — `sim.park_mults` already
takes {"hr", "k", "bip"} and `game.simulate_game` already applies a park to
the whole game rather than to a side, which is the right shape: both clubs
play in the same month.

CENTRED WITHIN EACH SEASON, so a year that simply scored more cannot enter
as a month effect. Walks have no park slot, so a month's walk deviation is
NOT applied — recorded here because it is a real limit on the mechanism and
not an oversight.
"""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict

import multiprocessing as mp
import os
import random
import zlib

from src import db
from src.context import calibrate as cal, fitf5, sim
from src.context.sources import rates as rate_src

_CASES: dict = {}
_LG: dict = {}
_PENS: dict = {}
_PARK: dict = {}

CUT = "2026-07-01"
#: March is excluded everywhere: 146 games in 2026 and a +0.516 run outlier
#: in 2024. Four days of opening-day pitching is not a seasonal effect.
PRIOR_SEASONS = ("2023", "2024", "2025")
MONTHS = ("04", "05", "06", "07", "08", "09")

_Q = """
select substr(g.date, 1, 4) yr, substr(g.date, 6, 2) mon,
       sum(p.k) k, sum(p.bb) bb, sum(p.hr) hr, sum(p.h) h,
       sum(p.outs_recorded) + sum(p.h) + sum(p.bb) bf
from games g join mlb_pitching p on p.game_id = g.game_id
where g.sport = 'mlb' and g.status = 'Final'
group by 1, 2
"""


def measure() -> dict:
    """{month: {"hr":, "k":, "bip":}} from PRIOR seasons, centred per year."""
    rows = defaultdict(dict)
    with db.connect() as c:
        for r in c.execute(_Q):
            if r["bf"] and r["mon"] in MONTHS:
                bip = rate_src.balls_in_play(r["bf"], r["k"], r["bb"], r["hr"])
                rows[r["yr"]][r["mon"]] = {
                    "k": r["k"] / r["bf"], "hr": r["hr"] / r["bf"],
                    "bip": ((r["h"] - r["hr"]) / bip) if bip else None}
    per = defaultdict(lambda: defaultdict(list))
    for yr in PRIOR_SEASONS:
        got = rows.get(yr) or {}
        have = [m for m in MONTHS if m in got and got[m]["bip"]]
        if len(have) < 4:
            continue
        for ch in ("k", "hr", "bip"):
            base = st.mean(got[m][ch] for m in have)
            for m in have:
                per[m][ch].append(got[m][ch] / base)
    return {m: {ch: st.mean(v) for ch, v in d.items()} for m, d in per.items()}


def report(fac):
    print("  MONTH FACTORS, measured on 2023-2025, centred within each"
          " season\n")
    print(f"  {'month':<7}{'k':>9}{'hr':>9}{'bip':>9}")
    for m in sorted(fac):
        d = fac[m]
        print(f"  {m:<7}{d['k']:>9.4f}{d['hr']:>9.4f}{d['bip']:>9.4f}")
    print("\n  Above 1 means the month runs HIGH on that channel. A high-k")
    print("  month suppresses runs; high hr and high bip raise them.")


def training_mix(cut: str) -> dict:
    """The month factor the RATES were accumulated in, weighted by exposure.

    NEUTRALISE, THEN APPLY — the pair park taught this project. A pitcher's
    rate already contains the months he threw in, so applying tonight's
    month on top of it counts that environment twice. With rates trained
    April-June and games scored in July-August the two are very different,
    which is exactly when the pair matters.
    """
    fac = measure()
    with db.connect() as c:
        wt = defaultdict(float)
        for r in c.execute(
                "select substr(g.date,6,2) mon,"
                " sum(p.outs_recorded)+sum(p.h)+sum(p.bb) bf"
                " from games g join mlb_pitching p on p.game_id=g.game_id"
                " where g.sport='mlb' and g.status='Final'"
                " and g.date < ? and g.date like '2026%' group by 1", (cut,)):
            if r["mon"] in fac and r["bf"]:
                wt[r["mon"]] += r["bf"]
    tot = sum(wt.values()) or 1.0
    return {ch: sum(fac[m][ch] * w for m, w in wt.items()) / tot
            for ch in ("k", "hr", "bip")}


def game_park(month: str, fac: dict, base: dict) -> dict:
    """This month's environment RELATIVE to the one the rates were earned in."""
    d = fac.get(month)
    if not d:
        return dict(sim.NEUTRAL_PARK)
    return {ch: d[ch] / base[ch] for ch in ("k", "hr", "bip")}


def _one(args):
    """Paired: the SAME game and seeds, month factor off then on."""
    gid, n_sims = args
    out = []
    for park in (None, _PARK.get(gid)):
        # `replay` reads its park from `cal.park_for(home venue_id)`, so the
        # month factor goes in through that seam. Per game, inside a forked
        # worker, so nothing leaks between games.
        cal.park_for = (lambda _v, _p=park: _p) if park else cal.park_for
        rng = random.Random((zlib.crc32(gid.encode()) & 0xFFFF) * 1009)
        tot = 0.0
        for _ in range(n_sims):
            r = cal.replay(_CASES[gid], _LG, _PENS, rng,
                           use_park=park is not None)
            tot += r.away + r.home
        out.append(tot / n_sims)
    return gid, out[0], out[1]


def score(argv):
    """Run level with the month factor off and on, paired on seed."""
    global _CASES, _LG, _PENS, _PARK
    n_sims = int(argv[0]) if argv and argv[0].isdigit() else 20
    fac, base = measure(), training_mix(CUT)
    _LG = sim.league()
    _PENS = rate_src.bullpens(_LG, before=CUT)
    _CASES = cal.paired_cases(season=2026, since=CUT, rates_before=CUT)
    with db.connect() as c:
        month = {r["game_id"]: r["date"][5:7] for r in c.execute(
            "select game_id, date from games where sport='mlb'")}
    _PARK = {g: game_park(month.get(g, ""), fac, base) for g in _CASES}
    print(f"\n  SCORING: {len(_CASES)} games x {n_sims} sims, cut {CUT}")
    ex = _PARK[sorted(_CASES)[0]]
    print(f"  example applied factor  k {ex['k']:.4f}  hr {ex['hr']:.4f}"
          f"  bip {ex['bip']:.4f}", flush=True)
    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, (os.cpu_count() or 4) - 2)) as pool:
        got = pool.map(_one, [(g, n_sims) for g in _CASES], chunksize=8)
    with db.connect() as c:
        act = {r["game_id"]: (r["away_score"] or 0) + (r["home_score"] or 0)
               for r in c.execute("select game_id, away_score, home_score"
                                  " from games where sport='mlb'")}
    off = [o for _g, o, _n in got]
    on = [n for _g, _o, n in got]
    a = [act[g] for g, _o, _n in got]
    print(f"\n  {'arm':<16}{'model':>9}{'actual':>9}{'gap':>9}{'rel':>9}")
    for lbl, v in (("month OFF", off), ("month ON", on)):
        d = [x - y for x, y in zip(v, a)]
        m = st.mean(d)
        print(f"  {lbl:<16}{st.mean(v) / 2:>9.3f}{st.mean(a) / 2:>9.3f}"
              f"{m / 2:>+9.3f}{m / st.mean(a):>+9.1%}")
    dd = [x - y for x, y in zip(on, off)]
    m = st.mean(dd)
    se = st.pstdev(dd) / len(dd) ** 0.5
    print(f"\n  paired change from turning it ON  {m / 2:+.4f} runs per"
          f" team-game  (se {se / 2:.4f})")


def main(argv):
    fac = measure()
    report(fac)
    base = training_mix(CUT)
    print(f"\n  RATES were accumulated before {CUT}, weighted by exposure:")
    print(f"    k {base['k']:.4f}   hr {base['hr']:.4f}"
          f"   bip {base['bip']:.4f}")
    print("\n  APPLIED FACTOR = the game's month over that, so a rate earned")
    print("  in a cold April is re-based onto the month being played:")
    print(f"  {'month':<7}{'k':>9}{'hr':>9}{'bip':>9}")
    for m in sorted(fac):
        d = game_park(m, fac, base)
        print(f"  {m:<7}{d['k']:>9.4f}{d['hr']:>9.4f}{d['bip']:>9.4f}")
    if "--measure" in argv:
        return
    score(argv)


if __name__ == "__main__":
    main(sys.argv[1:])
