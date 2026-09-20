"""Discriminate: is the bug in `permute`, or in how the cells are read?"""
from __future__ import annotations

import random
from collections import defaultdict
from multiprocessing import Pool

from src.context.sources import pbp
from scratchpad.inn1 import _extract, permute, HOLDOUT


def split(rows, labelmap, pas):
    """pass-`pas` hit-per-BIP by label, straight from the rows."""
    got = defaultdict(lambda: [0, 0])
    for r in rows:
        if r[3] != pas or r[5] in ("k", "bb", "hbp", "hr"):
            continue
        g = got[labelmap[(r[0], r[1], r[2])]]
        g[1] += 1
        if r[5] == "hit":
            g[0] += 1
    return {k: (v[0] / v[1], v[1]) for k, v in got.items()}


def main():
    ids = [g for g in pbp.final_games(before=HOLDOUT) if pbp.have(g)][:2000]
    with Pool(8) as pool:
        got = pool.map(_extract, ids, chunksize=32)
    rows = [r for rr in got for r in rr]
    batters = {(r[0], r[1], r[2]) for r in rows}
    print(f"{len(rows):,} rows, {len(batters):,} batter-starts")

    meas = {(r[0], r[1], r[2]): r[4] for r in rows}
    variants = {"measured": meas}

    # A: the shipped within-game-side shuffle
    variants["permute()"] = {(r[0], r[1], r[2]): r[4]
                             for r in permute(rows, random.Random(11))}

    # B: a plain global coin flip per batter — cannot possibly correlate
    rng = random.Random(11)
    variants["coin flip"] = {k: ("T" if rng.random() < 0.48 else "B")
                             for k in sorted(batters)}

    # C: shuffle the measured labels globally across batters
    rng = random.Random(11)
    labs = [meas[k] for k in sorted(batters)]
    rng.shuffle(labs)
    variants["global shuffle"] = dict(zip(sorted(batters), labs))

    for name, lm in variants.items():
        a = split(rows, lm, 1)
        b = split(rows, lm, 2)
        print(f"  {name:<15} pass1 T {a['T'][0]:.4f} ({a['T'][1]:,} bip) "
              f"B {a['B'][0]:.4f} ({a['B'][1]:,})  | "
              f"pass2 T {b['T'][0]:.4f} B {b['B'][0]:.4f}")


if __name__ == "__main__":
    main()
