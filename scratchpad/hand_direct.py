"""Handedness scored on the DIRECT channels, where it has power.

    venv/bin/python -m scratchpad.hand_direct [n_sims] [salts]

WHY NOT RUNS. F5 CRPS is the quantity that settles and it is the right thing
to FIT. It is the wrong thing to DETECT with: runs sit four steps downstream
of a plate appearance — hook decisions, sequencing and bullpen draws all
intervene — so a mechanism worth a quarter of a home run rate can be
invisible in the score while being obvious in home runs allowed. Detection
and fitting are different jobs and this file does the first one.

The starter's own line is the direct read: strikeouts, walks, home runs and
hits ALLOWED, scored against what actually happened, per start.

FOUR ARMS.

    off           overall rates. What ships.
    own-prior     the SHIPPED specification — each split shrunk toward the
                  hitter's own overall rate, so a thin split means no
                  platoon effect at all.
    league-prior  the corrected specification — shrunk toward the LEAGUE
                  platoon cell for the side he bats from. Recovers about
                  twice the signal: left-handed bats come out 29.7% down on
                  home runs against left-handers where the shipped version
                  says 16.2%, against a league truth of 26%.
    league+dev    the same, plus his own measured deviation on top.

EVERY ARM IS LEAK-FREE. Splits and the league table are counted on
2023-2025 and the scored starts are 2026, so nothing can sit inside its own
predictor. That is what killed the first version of this A/B: measured
in-sample it gained 3.5 sigma, and the gain reversed to -2.3 the moment the
splits could not see the games being scored.

SCORED PAIRED on common random numbers, and on two things that answer
different questions. MAE says whether the CENTRE moved the right way. The
discrete ranked probability score says whether the whole DISTRIBUTION did,
which is what a price is made of.
"""
from __future__ import annotations

import multiprocessing as mp
import random
import statistics as st
import sys
import zlib
from src.context import calibrate as cal, fitf5, sim
from src.context.sources import rates as rate_src
from scratchpad.platoon_fix import (build, league_cells,
                                    pitcher_splits, splits)

CHANNELS = ("k", "bb", "hr", "h")

#: Lines the ranked probability score is summed over — the full support of
#: each channel, not a book's board.
SUPPORT = {"k": range(0, 15), "bb": range(0, 8),
           "hr": range(0, 5), "h": range(0, 14)}

TRAIN = (2023, 2024, 2025)
SCORE_SEASON = 2026


def _rps(vals, actual, support):
    """Discrete CRPS of a simulated distribution against one outcome."""
    n = len(vals)
    if not n:
        return 0.0
    tot = 0.0
    cum = 0
    srt = sorted(vals)
    j = 0
    for ln in support:
        while j < n and srt[j] <= ln:
            j += 1
            cum += 1
        p = cum / n
        tot += (p - (1.0 if actual <= ln else 0.0)) ** 2
    return tot


def make_table(kind, data, overall):
    if kind == "off":
        return None
    if kind == "own-prior":
        return splits(overall, data, TRAIN, dev_seasons=TRAIN,
                      dev_k=rate_src.SPLIT_STABILISE, structural=False)
    if kind == "league-prior":
        # dev_k enormous => the individual deviation is switched off and the
        # arm is the pure structural effect. Separating the two is the whole
        # point: if league-prior wins and league+dev does not, the personal
        # split is noise and only the structure was ever worth having.
        return splits(overall, data, TRAIN, dev_seasons=TRAIN,
                      dev_k=1e9, structural=True)
    if kind == "matchup":
        # The batter table is applied through `build_cases` exactly as the
        # league-prior arm does; the pitcher line and the league cell are
        # attached afterwards by `_condition`.
        return splits(overall, data, TRAIN, dev_seasons=TRAIN, dev_k=1e9,
                      structural=True)
    if kind.startswith("league x"):
        # POSITIVE CONTROL. Same mechanism, effect scaled up. If these are
        # detected and the 1x arm is not, the real effect is genuinely below
        # this screen's resolution; if they are NOT detected, the screen
        # cannot see handedness at all and its null says nothing.
        return splits(overall, data, TRAIN, dev_seasons=TRAIN, dev_k=1e9,
                      structural=True, amplify=float(kind.split("x")[1]))
    return splits(overall, data, TRAIN, dev_seasons=TRAIN, structural=True)


#: Set BEFORE the pool forks so every worker inherits them copy-on-write.
#: Passing the pairs per task would re-pickle every PitcherRates and
#: BatterRates for each chunk, which costs more than the simulation.
_PAIRS: list = []
_LG: dict = {}
_PENS: dict = {}


def _chunk(args):
    lo, hi, n_sims, salt = args
    acc = {c: [0.0, 0.0, 0] for c in CHANNELS}
    for gid, away, home in _PAIRS[lo:hi]:
        rng = random.Random((zlib.crc32(gid.encode()) & 0xFFFFFF)
                            + salt * 7919)
        draws = {(t, c): [] for t in ("a", "h") for c in CHANNELS}
        for _ in range(n_sims):
            r = cal.replay((away, home), _LG, _PENS, rng)
            for tag, ln in (("a", r.away_sp), ("h", r.home_sp)):
                for c in CHANNELS:
                    draws[(tag, c)].append(getattr(ln, c))
        for tag, case in (("a", away), ("h", home)):
            row = case[0]
            for c in CHANNELS:
                act = row[c] or 0
                v = draws[(tag, c)]
                acc[c][0] += abs(st.mean(v) - act)
                acc[c][1] += _rps(v, act, SUPPORT[c])
                acc[c][2] += 1
    return acc


def _condition(pairs, bat_tbl, pit_tbl, cells):
    """Attach the batter's side, the matchup league cell and the pitcher's
    side-specific line to every case.

    Done HERE rather than in `build_cases` so `src/` keeps one code path.
    Scoped to the STARTER: his hand picks each hitter's side for the whole
    game, which is right for the quantity being scored — the starter's own
    line — and wrong for the relievers, who have no splits on file anyway.
    """
    from src import roster
    hit = [0, 0]
    for gid, (away, home) in pairs.items():
        for case in (away, home):
            row, pitcher, lineup = case
            ph = roster.throws(row["player_name"])
            if ph not in ("L", "R"):
                hit[1] += len(lineup)
                continue
            ps = pit_tbl.get(pitcher.name)
            if ps:
                pitcher.vs_side = {bs: ps[bs] for bs in ("L", "R")
                                   if bs in ps}
            for b in lineup:
                srow = (bat_tbl.get(b.name) or {}).get(ph)
                bs = (srow or {}).get("side")
                if bs not in ("L", "R"):
                    hit[1] += 1
                    continue
                b.side = bs
                b.lg_cell = cells.get(f"{bs}{ph}")
                hit[0] += 1
    if hit[0] < hit[1]:
        raise SystemExit(f"conditioned {hit[0]:,} lineup slots and MISSED"
                         f" {hit[1]:,} — the matchup is not being applied")
    return hit


def run_arm(kind, data, n_sims, salts, lg, workers=8):
    global _PAIRS, _LG, _PENS
    real = rate_src.batter_rates_by_hand
    overall = rate_src.batter_rates(lg)
    table = make_table(kind, data, overall)
    cal.USE_HANDEDNESS = table is not None
    if table is not None:
        rate_src.batter_rates_by_hand = lambda *a, **k: table
    try:
        cal._CASES.clear()
        pairs = cal.paired_cases(season=SCORE_SEASON)
        if kind == "matchup":
            overall_p = rate_src.pitcher_rates(lg)
            _condition(pairs,
                       splits(overall, data, TRAIN, dev_seasons=TRAIN,
                              dev_k=1e9, structural=True),
                       pitcher_splits(overall_p, data, TRAIN,
                                      dev_seasons=TRAIN),
                       league_cells(data, TRAIN, lg))
        _PAIRS = [(g, a, h) for g, (a, h) in sorted(pairs.items())]
        _LG, _PENS = lg, rate_src.bullpens(lg)
        n = len(_PAIRS)
        step = max(1, n // (workers * 2))
        jobs = [(lo, min(lo + step, n), n_sims, salt)
                for salt in salts for lo in range(0, n, step)]
        # FORK, never spawn: a spawned child re-imports at default globals,
        # `_PAIRS` comes back empty and every arm scores zero games — which
        # looks exactly like a null.
        ctx = mp.get_context("fork")
        per_salt = []
        with ctx.Pool(workers) as pool:
            out = pool.map(_chunk, jobs)
        k = len(jobs) // len(salts)
        for i in range(len(salts)):
            acc = {c: [0.0, 0.0, 0] for c in CHANNELS}
            for a in out[i * k:(i + 1) * k]:
                for c in CHANNELS:
                    for j in range(3):
                        acc[c][j] += a[c][j]
            assert acc["k"][2] == 2 * n, (acc["k"][2], 2 * n)
            per_salt.append({c: (acc[c][0] / acc[c][2], acc[c][1] / acc[c][2])
                             for c in CHANNELS})
        return pairs, per_salt
    finally:
        rate_src.batter_rates_by_hand = real
        cal.USE_HANDEDNESS = False
        cal._CASES.clear()


def main(argv):
    n_sims = int(argv[0]) if len(argv) > 0 else 40
    n_salts = int(argv[1]) if len(argv) > 1 else 4
    salts = list(range(n_salts))
    lg = sim.league()
    data = build()
    print(f"  starters' own lines, {SCORE_SEASON} starts, splits from"
          f" {TRAIN[0]}-{TRAIN[-1]}")
    print(f"  {n_sims} sims x {len(salts)} salts, paired\n")

    res = {}
    for kind in ("off", "league-prior", "matchup"):
        pairs, per_salt = run_arm(kind, data, n_sims, salts, lg)
        res[kind] = per_salt
        mae = {c: st.mean(s[c][0] for s in per_salt) for c in CHANNELS}
        rps = {c: st.mean(s[c][1] for s in per_salt) for c in CHANNELS}
        print(f"  {kind:<14}{len(pairs):>5} games   "
              + "  ".join(f"{c} {rps[c]:.4f}" for c in CHANNELS))
        if kind == "off":
            print(f"  {'':<14}{'':>5}         "
                  + "  ".join(f"{c} MAE {mae[c]:.3f}" for c in CHANNELS))

    print(f"\n  RPS vs off, paired by salt (NEGATIVE is better):")
    print(f"  {'arm':<14}" + "".join(f"{c:>18}" for c in CHANNELS))
    base = res["off"]
    for kind in ("league-prior", "matchup"):
        cells = []
        for c in CHANNELS:
            d = [b[c][1] - a[c][1] for a, b in zip(base, res[kind])]
            m, se = fitf5._mean_se(d)
            cells.append(f"{m:+.4f}({m / se if se else 0:+.1f})")
        print(f"  {kind:<14}" + "".join(f"{x:>18}" for x in cells))
    print("\n  The bracket is standard deviations of the paired difference.")
    print("  The bar is 2. Home runs are the channel to watch: that is")
    print("  where the league platoon effect is largest and where the")
    print("  shipped specification loses the most of it.")


if __name__ == "__main__":
    main(sys.argv[1:])
