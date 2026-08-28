"""The hit-by-pitch field-state channel, scored on its pre-registered
falsifier.

    venv/bin/python -m scratchpad.hbp_state_ab [n_sims]

QUESTION    `STATE_MULT` gained an `hbp_pct` column. Does the simulator now
            hit batters at the counted rate PER FIELD STATE, and does it do
            so by redistributing hit batsmen rather than adding them?

HYPOTHESIS  Pitchers hit more batters with men on — 1.30x, counted. The
            table should reproduce that ratio while leaving the overall
            rate per plate appearance untouched, because the multipliers
            are frequency-normalised to one.
            FALSIFIER, and it is the whole point of the change: if the
            OVERALL rate rises, the table is adding free baserunners. If K
            or BB fall alongside, `cond` did not follow `hbp` and every
            rate below the draw is being divided by a stale denominator.

POWER, AND THE TWO HALVES ARE NOT COMPARABLE.

  * The RATE half is exact. It walks the real state distribution through
    `pa_from` directly, so the numbers below are the mechanism's own
    arithmetic and not a sample of it. This is where the claim lives.
  * The GAME half CANNOT RESOLVE THIS and is reported to show the level did
    not break, not to score the change. A hit batsman is 1.1% of plate
    appearances and the table moves ~6% of those into higher-leverage
    states; at a ~0.15-run difference in run expectancy that is about
    0.003 runs a game. F5 run noise over a few hundred games is ~0.03. The
    change is TEN TIMES below the resolution of the test, which is the
    expected result for a measured quantity of this size and not a null.

POSITIVE CONTROL: a third arm with `hbp_pct` pushed 5x away from neutral.
A mis-specified wiring and a real-but-small effect produce identical
output, and only the control separates them.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import random
import statistics as st
import sys

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src

HOLDOUT = "2026-07-01"
_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 20
_TABLE: dict = {}


def _strip(table):
    """The shipped table WITHOUT the new column — the pre-change model."""
    return {c: {k: v for k, v in m.items() if k != "hbp_pct"}
            for c, m in table.items()}


def _amplify(table, factor):
    """Push `hbp_pct` `factor` times further from 1.0, nothing else."""
    out = {}
    for c, m in table.items():
        m = dict(m)
        if "hbp_pct" in m:
            m["hbp_pct"] = 1.0 + (m["hbp_pct"] - 1.0) * factor
        out[c] = m
    return out


# ── the rate half: exact, and where the claim lives ────────────────────
def _freq():
    """Real cell frequencies, from the counts the table was built on."""
    raw = json.load(open("scratchpad/state_counts.json"))
    out = {}
    for k, v in raw.items():
        if k == "ALL":
            continue
        out[tuple(int(x) for x in k.strip("()").split(","))] = v["pa"]
    return out


def rates(table):
    """HBP and K per plate appearance, weighted by how often each state
    actually occurs. Walks `pa_from` itself, so this is the mechanism's
    arithmetic rather than a sample of it."""
    keep, keep_flag = sim.STATE_MULT, sim.USE_FIELD_STATE
    try:
        sim.STATE_MULT, sim.USE_FIELD_STATE = table, True
        freq = _freq()
        tot = sum(freq.values())
        b = sim.BatterRates(name="B", k_pct=0.2227, bb_pct=0.0870,
                            hr_pct=0.0307, babip=0.2892, pa=500)
        p = sim.PitcherRates(name="P", k_pct=0.2227, bb_pct=0.0870,
                             hr_pct=0.0307, babip=0.2892, pa=600)
        lg = {"k_pct": 0.2227, "bb_pct": 0.0870, "hr_pct": 0.0307,
              "babip": 0.2892,
              "hit_mix": {"1b": 0.763, "2b": 0.217, "3b": 0.020}}
        mu = sim.resolve(b, p, lg)
        n = 120000
        got = {}
        for cell, w in freq.items():
            rng = random.Random(17)
            h = k = 0
            for _ in range(n):
                o = sim.pa_from(mu, rng, state=cell)
                h += o == sim.HBP
                k += o == sim.K
            got[cell] = (h / n, k / n, w / tot)
        return got
    finally:
        sim.STATE_MULT, sim.USE_FIELD_STATE = keep, keep_flag


def report_rates(arms):
    print("  RATE HALF — exact, weighted by the real state distribution\n")
    print(f"  {'on':>3}{'out':>5}{'freq':>8}"
          + "".join(f"{a[0]:>12}" for a in arms) + f"{'counted':>10}")
    counted = json.load(open("scratchpad/state_counts.json"))
    got = {name: rates(t) for name, t in arms}
    base_real = counted["ALL"]["hbp"] / counted["ALL"]["pa"]
    for cell in sorted(got[arms[0][0]]):
        c = counted[f"({cell[0]}, {cell[1]})"]
        real = c["hbp"] / c["pa"]
        f = got[arms[0][0]][cell][2]
        print(f"  {cell[0]:>3}{cell[1]:>5}{f:>8.3f}"
              + "".join(f"{got[n[0]][cell][0]:>12.4f}" for n in arms)
              + f"{real:>10.4f}")
    print()
    for name, _ in arms:
        g = got[name]
        overall = sum(v[0] * v[2] for v in g.values())
        kk = sum(v[1] * v[2] for v in g.values())
        emp = sum(v[0] * v[2] for c, v in g.items() if c[0] == 0)
        empw = sum(v[2] for c, v in g.items() if c[0] == 0)
        on = sum(v[0] * v[2] for c, v in g.items() if c[0] > 0)
        onw = sum(v[2] for c, v in g.items() if c[0] > 0)
        print(f"  {name:<12} hbp/PA {overall:.5f}   "
              f"men-on / empty {(on / onw) / (emp / empw):.3f}   "
              f"K/PA {kk:.4f}")
    # THE COUNTED COMPARISON. The overall rate must not move: the table
    # redistributes hit batsmen, it does not manufacture them.
    ce = sum(counted[f"({o}, {u})"]["hbp"] for o in (0,) for u in (0, 1, 2))
    cep = sum(counted[f"({o}, {u})"]["pa"] for o in (0,) for u in (0, 1, 2))
    con = counted["ALL"]["hbp"] - ce
    conp = counted["ALL"]["pa"] - cep
    print(f"  {'COUNTED':<12} hbp/PA {base_real:.5f}   "
          f"men-on / empty {(con / conp) / (ce / cep):.3f}")


# ── the game half: shows the level did not break ───────────────────────
def _one(args):
    i, gid = args
    sim.USE_FIELD_STATE = True
    sim.STATE_MULT = _TABLE
    v = _CASES[gid]
    home = next(x for x in v if x[0]["is_home"])
    away = next(x for x in v if not x[0]["is_home"])
    an = cal.adjust_lineup(away[2], False)
    hn = cal.adjust_lineup(home[2], True)
    out = []
    for draw in range(_SIMS):
        rng = random.Random(7 + i * 100003 + draw)
        A = game.build_side(away[1],
                            _PENS.get((away[0]["team"] or "").upper(), []),
                            hn, sim.Hook(), rng, team=away[0]["team"])
        H = game.build_side(home[1],
                            _PENS.get((home[0]["team"] or "").upper(), []),
                            an, sim.Hook(), rng, team=home[0]["team"])
        r = game.simulate_game(A, H, _LG, rng, track=(5, 9))
        f5 = r.prefix_side.get(5)
        out.append((r.away, r.home,
                    f5[0] if f5 else None, f5[1] if f5 else None,
                    r.away_sp.k, r.away_sp.outs, r.away_sp.hbp))
    return out


def main(argv):
    global _CASES, _PENS, _LG, _SIMS, _TABLE
    _SIMS = int(argv[0]) if argv else 20
    shipped = dict(sim.STATE_MULT)
    arms = (("NO HBP", _strip(shipped)),
            ("HBP", shipped),
            ("CONTROL x5", _amplify(shipped, 5.0)))
    report_rates(arms)

    print("\n  GAME HALF — a level check, NOT a score. See POWER above.\n")
    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    gids = sorted(pairs)
    _CASES = {g: pairs[g] for g in gids}
    _LG = sim.league(before=HOLDOUT)
    _PENS = rate_src.bullpens(_LG, before=HOLDOUT)
    print(f"  {len(gids)} games x {_SIMS} sims  "
          f"({len(gids) * _SIMS * 2:,} simulated sides per arm)")
    got = {}
    for name, table in arms:
        _TABLE = table
        with mp.get_context("fork").Pool(
                max(1, (mp.cpu_count() or 2) - 1)) as p:
            rows = [r for g in p.map(_one, list(enumerate(gids))) for r in g]
        sides = [v for r in rows for v in (r[2], r[3]) if v is not None]
        got[name] = {
            "f5_mean": st.mean(sides),
            "f5_sd": st.pstdev(sides),
            "shutout": sum(1 for v in sides if v == 0) / len(sides),
            "five_plus": sum(1 for v in sides if v >= 5) / len(sides),
            "total": st.mean(r[0] + r[1] for r in rows),
            "k": st.mean(r[4] for r in rows),
            "outs": st.mean(r[5] for r in rows),
            "sp_hbp": st.mean(r[6] for r in rows),
        }
    print(f"  {'':<20}" + "".join(f"{a[0]:>12}" for a in arms)
          + f"{'ACTUAL':>10}")
    for label, key, actual in (
            ("F5 runs / side", "f5_mean", 2.437),
            ("  sd", "f5_sd", 2.313),
            ("  shutout share", "shutout", 0.219),
            ("  five-plus share", "five_plus", 0.176),
            ("game total", "total", None),
            ("starter K", "k", 4.84),
            ("starter outs", "outs", 15.82),
            ("starter HBP", "sp_hbp", None)):
        a = f"{actual:>10.3f}" if actual is not None else f"{'':>10}"
        print(f"  {label:<20}"
              + "".join(f"{got[n[0]][key]:>12.3f}" for n in arms) + a)
    sim.USE_FIELD_STATE, sim.STATE_MULT = True, shipped


if __name__ == "__main__":
    main(sys.argv[1:])
