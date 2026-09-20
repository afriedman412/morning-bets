"""Sweep ONE hook coefficient across OFF / SHIPPED / amplified.

    venv/bin/python -m scratchpad.hook_ab <param> [n_sims] [multiple]

    venv/bin/python -m scratchpad.hook_ab late_mid_per_k_rate 20 4

Generalises `blowout_ab.py`, which did this for `mid_per_abs_margin` alone.
Every arm is PAIRED on seeds, so a difference between columns is the
mechanism and not the dice.

THE COLUMN THAT MATTERS HERE IS K BY START LENGTH, which no other harness
in this project prints. TODO item 7's defect is a JOINT one — the strikeout
LEVEL is right (4.84 against 4.84) and the LENGTH is right (15.8 against
15.8), and the model still cannot produce a nine-strikeout game, because in
reality a long start is SELECTED for missing bats and in the simulator it is
not. Only the conditional table shows that; both marginals look healthy.

READ THE CONTROL FIRST. A term that is wired but never reaches the decision
and a term that is genuinely small produce the same near-flat shipped
column, and only the amplified arm separates them.
"""
from __future__ import annotations

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
_PARAM = ""
_VAL = 0.0

#: Start-length buckets, matching the table TODO item 7 quotes so the two
#: are directly comparable rather than nearly comparable.
BUCKETS = ((0, 9), (9, 12), (12, 15), (15, 18), (18, 21), (21, 28))


def _one(args):
    i, gid = args
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
                            hn, sim.Hook(**{_PARAM: _VAL}), rng,
                            team=away[0]["team"])
        H = game.build_side(home[1],
                            _PENS.get((home[0]["team"] or "").upper(), []),
                            an, sim.Hook(**{_PARAM: _VAL}), rng,
                            team=home[0]["team"])
        r = game.simulate_game(A, H, _LG, rng, track=(5,))
        f5 = r.prefix_side.get(5)
        for j, sp in enumerate((r.away_sp, r.home_sp)):
            row = {"outs": sp.outs, "k": sp.k, "boundary": sp.outs % 3 == 0}
            if f5:
                row["f5"] = f5[1 - j]
            out.append(row)
    return out


def summarise(rows):
    f5 = [r["f5"] for r in rows if "f5" in r]
    k = [r["k"] for r in rows]
    o = [r["outs"] for r in rows]
    d = {"outs": st.mean(o), "outs_sd": st.pstdev(o),
         "bnd": st.mean(1.0 if r["boundary"] else 0.0 for r in rows),
         "k": st.mean(k), "k_sd": st.pstdev(k),
         "k9": st.mean(1.0 if v >= 9 else 0.0 for v in k),
         "f5_mean": st.mean(f5) if f5 else 0.0}
    for lo, hi in BUCKETS:
        sub = [r for r in rows if lo <= r["outs"] < hi]
        d[f"kb{lo}"] = st.mean(r["k"] for r in sub) if sub else 0.0
    return d


def actuals():
    """The real starts on the same games — the BINDING sample."""
    rows = []
    for v in _CASES.values():
        for s in v:
            if s[0].get("o") is not None and s[0].get("k") is not None:
                rows.append({"outs": s[0]["o"], "k": s[0]["k"],
                             "boundary": s[0]["o"] % 3 == 0})
    return rows


def main(argv):
    global _CASES, _PENS, _LG, _SIMS, _PARAM, _VAL
    _PARAM = argv[0]
    _SIMS = int(argv[1]) if len(argv) > 1 else 20
    mult = float(argv[2]) if len(argv) > 2 else 4.0
    shipped = getattr(sim.Hook(), _PARAM)

    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    gids = sorted(pairs)
    _CASES = {g: pairs[g] for g in gids}
    _LG = sim.league(before=HOLDOUT)
    _PENS = rate_src.bullpens(_LG, before=HOLDOUT)
    act = actuals()
    A = summarise(act)

    print(f"  sweeping sim.Hook.{_PARAM}, shipped {shipped:+.4f}")
    print(f"  {len(gids)} games x {_SIMS} sims "
          f"({2 * len(gids) * _SIMS:,} simulated starts per arm)")
    print(f"  POWER: the actual side is {len(act):,} real starts and is the "
          f"binding sample.\n  se on the boundary share "
          f"{(A['bnd'] * (1 - A['bnd']) / len(act)) ** 0.5:.4f}; "
          f"on P(K>=9) {(A['k9'] * (1 - A['k9']) / len(act)) ** 0.5:.4f}.\n")

    arms = (("OFF", 0.0), ("SHIPPED", shipped), (f"x{mult:g}", shipped * mult))
    got = {}
    for name, val in arms:
        _VAL = val
        with mp.get_context("fork").Pool(
                max(1, (mp.cpu_count() or 2) - 1)) as p:
            rows = [r for g in p.map(_one, list(enumerate(gids))) for r in g]
        got[name] = summarise(rows)
        got[name]["val"] = val

    print(f"  {'':<24}" + "".join(f"{a[0]:>11}" for a in arms)
          + f"{'ACTUAL':>10}")
    rows = [("coefficient", "val", None),
            ("boundary share", "bnd", A["bnd"]),
            ("starter outs", "outs", A["outs"]),
            ("  sd", "outs_sd", st.pstdev([r["outs"] for r in act])),
            ("starter K", "k", A["k"]),
            ("  sd", "k_sd", st.pstdev([r["k"] for r in act])),
            ("  P(K >= 9)", "k9", A["k9"]),
            ("F5 runs / side", "f5_mean", None)]
    for label, key, a in rows:
        av = f"{a:>10.4f}" if a is not None else f"{'':>10}"
        print(f"  {label:<24}"
              + "".join(f"{got[n[0]][key]:>11.4f}" for n in arms) + av)

    print(f"\n  E[K] BY START LENGTH — the joint defect, and the reason a "
          f"healthy\n  marginal K and a healthy marginal length can coexist "
          f"with a dead tail.")
    print(f"  {'bucket':<24}" + "".join(f"{a[0]:>11}" for a in arms)
          + f"{'ACTUAL':>10}")
    for lo, hi in BUCKETS:
        sub = [r for r in act if lo <= r["outs"] < hi]
        if len(sub) < 20:
            continue
        av = st.mean(r["k"] for r in sub)
        print(f"  {f'{lo}-{hi - 1} outs  (n={len(sub)})':<24}"
              + "".join(f"{got[n[0]][f'kb{lo}']:>11.3f}" for n in arms)
              + f"{av:>10.3f}")


if __name__ == "__main__":
    main(sys.argv[1:])
