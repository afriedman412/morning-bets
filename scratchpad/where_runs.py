"""WHERE in the game is the run gap — the starter's innings or the pen's?

    venv/bin/python -m scratchpad.where_runs [n_sims] [--cut YYYY-MM-DD]

QUESTION. The model sends the right number of men to the plate and scores
about 3% fewer runs. `f5_decomp` put the STARTER's first five at 1.7% light.
If both hold, innings 6+ carry most of the gap on under half the runs, which
would localise the largest open defect to relief innings — a population that
has never been decomposed the way starter innings have.

THE TWO NUMBERS ARE NOT ON THE SAME FOOTING and that is the first thing to
fix. `f5_decomp` counts STARTER innings through five; the full-game figure
counts every inning and every arm. Comparing them directly is the mistake
this file exists to avoid, so both halves here are counted the same way: all
arms, split at the fifth, model against actual on the same games.

    innings 1-5   `games.away_score_f5` / `home_score_f5`, already stored
    innings 6+    final score minus that

POWER FIRST, AND IT IS THE BINDING CONSTRAINT. A team-game's runs have a
standard deviation of 3.22, so 1,062 team-games give a standard error of
0.099 on the mean — and the full-game gap being explained is 0.129. THE
HEADLINE ITSELF IS ONLY ABOUT 1.3 SIGMA at the July cut. The model side is
an average over many draws and contributes little; the binding noise is the
single realisation reality gave us. Resolving a 0.13-run gap at 2 sigma
needs roughly 2,500 team-games, so this defaults to the widest cut that
still leaves the rates out of sample.

The PAIRED difference is what is reported: the model's mean for a game minus
what that game actually did, which removes the part of the variance the
model can already explain.
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


#: Tracked prefixes stop at EIGHT and the rest is taken as a residual.
#:
#: `simulate_game` breaks out of its loop when the home team leads after the
#: top of the ninth — correctly, that half is not played — and that break
#: happens BEFORE the `if inning in track` block. So `prefix_side[9]` is
#: never set for those games and a profile that reads it counts the top of
#: the ninth, which WAS played, as nothing. It read -58.9% on the ninth and
#: it was measuring the tracking, not the model.
INNINGS = tuple(range(1, 9))


def _profile(args):
    """Per-inning runs for one game: model mean, and what actually happened.

    A finer instrument than the 1-5 / 6+ split and the one that answers the
    standing question about the FIRST inning, where the top of the order
    bats and the starter is fresh — a state the model reaches every game and
    reality reaches once.
    """
    gid, n_sims = args
    rng = random.Random((zlib.crc32(gid.encode()) & 0xFFFF) * 1009)
    m = {i: 0.0 for i in INNINGS}
    m[9] = 0.0                              # 9 AND EXTRAS, as a residual
    for _ in range(n_sims):
        r = cal.replay(_CASES[gid], _LG, _PENS, rng, track=INNINGS)
        prev_a = prev_h = 0
        for i in INNINGS:
            a, h = r.prefix_side.get(i, (prev_a, prev_h))
            m[i] += (a - prev_a) + (h - prev_h)
            prev_a, prev_h = a, h
        m[9] += (r.away - prev_a) + (r.home - prev_h)
    m = {i: v / n_sims for i, v in m.items()}
    # ACTUAL, counted off the play-by-play: runs on a play are the score
    # CHANGE across it, which is the only reading that survives an rbi
    # being withheld on a double play or an error.
    a = {i: 0 for i in INNINGS}
    a[9] = 0
    for play, _b, _o, aw, ho in pbp.plays(gid):
        res = play.get("result") or {}
        if res.get("awayScore") is None:
            continue
        got = res["awayScore"] + res["homeScore"] - (aw + ho)
        inn = (play.get("about") or {}).get("inning")
        if got > 0 and inn:
            a[inn if inn < 9 else 9] += got     # 9+ matches the model side
    return m, a


def _one(args):
    """(game_id, mean away f5, mean home f5, mean away full, mean home full)."""
    gid, n_sims = args
    # Seed varies BY GAME — a shared seed correlates the per-draw errors
    # across games and inflates the standard error of a LEVEL by ~3.4x.
    rng = random.Random((zlib.crc32(gid.encode()) & 0xFFFF) * 1009)
    a5 = h5 = af = hf = 0.0
    for _ in range(n_sims):
        r = cal.replay(_CASES[gid], _LG, _PENS, rng, track=(5,))
        # `prefix_side` is (away TEAM score, home TEAM score) — already
        # uncrossed there, unlike a Side's `runs`, which are runs ALLOWED.
        pa, ph = r.prefix_side.get(5, (0, 0))
        a5 += pa
        h5 += ph
        af += r.away
        hf += r.home
    return gid, a5 / n_sims, h5 / n_sims, af / n_sims, hf / n_sims


def paired(diffs):
    m = st.mean(diffs)
    se = st.pstdev(diffs) / len(diffs) ** 0.5
    return m, se, (m / se if se else 0.0)


def profile(n_sims):
    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, (os.cpu_count() or 4) - 2)) as pool:
        got = pool.map(_profile, [(g, n_sims) for g in _CASES], chunksize=8)
    n = len(got)
    print(f"  RUNS BY INNING (both teams), {n} games\n")
    print(f"  {'inning':>7}{'model':>9}{'actual':>9}{'gap':>9}"
          f"{'se':>8}{'z':>7}{'rel':>9}")
    for i in tuple(INNINGS) + (9,):
        d = [m[i] - a[i] for m, a in got]
        mm = st.mean(m[i] for m, _a in got)
        aa = st.mean(a[i] for _m, a in got)
        mean, se, z = paired(d)
        print(f"  {i:>7}{mm:>9.3f}{aa:>9.3f}{mean:>+9.3f}{se:>8.3f}"
              f"{z:>+7.1f}{(mean / aa if aa else 0):>+9.1%}")
    tm = st.mean(sum(m.values()) for m, _a in got)
    ta = st.mean(sum(a.values()) for _m, a in got)
    d = [sum(m.values()) - sum(a.values()) for m, a in got]
    mean, se, z = paired(d)
    print(f"  {'total':>7}{tm:>9.3f}{ta:>9.3f}{mean:>+9.3f}{se:>8.3f}"
          f"{z:>+7.1f}{mean / ta:>+9.1%}")
    print("\n  THE FIRST INNING IS THE ONE WORTH READING CLOSELY. The top of")
    print("  the order bats and the starter is fresh, and the model reaches")
    print("  that state every game while reality reaches it once — so a")
    print("  first-inning bias is a structural claim about the model and")
    print("  not a subsample.")


def main(argv):
    global _CASES, _LG, _PENS, CUT
    if "--cut" in argv:
        i = argv.index("--cut")
        CUT = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    n_sims = int(argv[0]) if argv and argv[0].isdigit() else 20
    _LG = sim.league()
    _PENS = rate_src.bullpens(_LG, before=CUT)
    _CASES = cal.paired_cases(season=2026, since=CUT, rates_before=CUT)
    print(f"  HOLDOUT: rates before {CUT}, {len(_CASES)} games x {n_sims}"
          f" sims\n", flush=True)
    if "--profile" in argv:
        profile(n_sims)
        return
    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, (os.cpu_count() or 4) - 2)) as pool:
        got = pool.map(_one, [(g, n_sims) for g in _CASES], chunksize=8)
    model = {g: v for g, *v in got}

    with db.connect() as c:
        act = {r["game_id"]: r for r in c.execute(
            "select game_id, date, away_score, home_score, away_score_f5,"
            " home_score_f5 from games where sport='mlb'")
            if r["game_id"] in _CASES}

    # BY MONTH, because two things move together and have to be separated:
    # a game further from the training cutoff has STALER rates, and a game
    # later in the season is played in a warmer run environment the model's
    # season-wide league baseline cannot see. Running the SAME games under
    # two different cuts holds the calendar fixed and moves only the rates.
    by_month: dict = {}
    # BY MONTH, because two things move together and have to be separated:
    # a game further from the training cutoff has STALER rates, and a game
    # later in the season is played in a warmer run environment the model's
    # season-wide league baseline cannot see. Running the SAME games under
    # two different cuts holds the calendar fixed and moves only the rates.
    by_month: dict = {}
    d5, dl, df = [], [], []
    m5 = a5 = ml = al = 0.0
    for gid, (ma5, mh5, maf, mhf) in model.items():
        r = act.get(gid)
        if not r or r["away_score_f5"] is None or r["away_score"] is None:
            continue
        for m_5, m_f, a_5, a_f in ((ma5, maf, r["away_score_f5"],
                                    r["away_score"]),
                                   (mh5, mhf, r["home_score_f5"],
                                    r["home_score"])):
            d5.append(m_5 - a_5)
            dl.append((m_f - m_5) - (a_f - a_5))
            df.append(m_f - a_f)
            m5 += m_5
            a5 += a_5
            ml += m_f - m_5
            al += a_f - a_5
            by_month.setdefault(r["date"][:7], []).append((m_f, a_f))
            by_month.setdefault(r["date"][:7], []).append((m_f, a_f))
    n = len(d5)
    print(f"  {n:,} team-games with a stored first-five score\n")
    print(f"  {'split':<14}{'model':>9}{'actual':>9}{'gap':>9}"
          f"{'se':>8}{'z':>7}{'rel':>9}")
    for lbl, diffs, mm, aa in (("innings 1-5", d5, m5 / n, a5 / n),
                               ("innings 6+", dl, ml / n, al / n),
                               ("whole game", df, (m5 + ml) / n,
                                (a5 + al) / n)):
        m, se, z = paired(diffs)
        print(f"  {lbl:<14}{mm:>9.3f}{aa:>9.3f}{m:>+9.3f}{se:>8.3f}"
              f"{z:>+7.1f}{m / aa:>+9.1%}")
    print(f"\n  BY MONTH OF THE GAME — same rates throughout, cut {CUT}")
    print(f"  {'month':<9}{'n':>7}{'model':>9}{'actual':>9}{'gap':>9}"
          f"{'se':>8}{'z':>7}{'rel':>9}")
    for mon in sorted(by_month):
        v = by_month[mon]
        if len(v) < 60:
            continue
        d = [m - a for m, a in v]
        mm = st.mean(m for m, _a in v)
        aa = st.mean(a for _m, a in v)
        mean, se, z = paired(d)
        print(f"  {mon:<9}{len(v):>7,}{mm:>9.3f}{aa:>9.3f}{mean:>+9.3f}"
              f"{se:>8.3f}{z:>+7.1f}{mean / aa:>+9.1%}")
    print(f"\n  BY MONTH OF THE GAME — same rates throughout, cut {CUT}")
    print(f"  {'month':<9}{'n':>7}{'model':>9}{'actual':>9}{'gap':>9}"
          f"{'se':>8}{'z':>7}{'rel':>9}")
    for mon in sorted(by_month):
        v = by_month[mon]
        if len(v) < 60:
            continue
        d = [m - a for m, a in v]
        mm = st.mean(m for m, _a in v)
        aa = st.mean(a for _m, a in v)
        mean, se, z = paired(d)
        print(f"  {mon:<9}{len(v):>7,}{mm:>9.3f}{aa:>9.3f}{mean:>+9.3f}"
              f"{se:>8.3f}{z:>+7.1f}{mean / aa:>+9.1%}")
    print("\n  READ THE `se` COLUMN BEFORE THE `gap` COLUMN. The binding")
    print("  noise is reality's single realisation, not the simulation, so")
    print("  a gap under about 2 se is a direction and not a measurement.")
    print("\n  THE HYPOTHESIS is that innings 6+ carry most of the gap. It")
    print("  needs the LATE gap to be both larger AND a bigger share of its")
    print("  own base than the first five — a uniform shortfall would show")
    print("  as two similar `rel` figures and would refute it.")


if __name__ == "__main__":
    main(sys.argv[1:])
