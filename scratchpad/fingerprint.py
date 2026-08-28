"""One hash over many simulated games — did a refactor change the numbers?

    venv/bin/python -m scratchpad.fingerprint [n_games] [n_sims]

The verification standard this project already used once, for `odds_mult`,
but never as a tool: run a fixed set of games at fixed seeds, digest every
number that comes out, and demand an EXACT match across the change. A paired
A/B can only say "inside noise"; this says "identical", which is the only
honest claim for a change that is supposed to be structural.

Use it whenever a change is asserted to be behaviour-preserving. Asserting
bit-identity in a docstring and not checking it is how a refactor ships a
quiet regression that every aggregate absorbs.
"""
from __future__ import annotations

import hashlib
import random
import sys
import zlib

from src.context import calibrate as cal, sim
from src.context.sources import rates as rate_src


def digest(n_games=400, n_sims=6, season=2026) -> str:
    lg = sim.league()
    pens = rate_src.bullpens(lg)
    pairs = sorted(cal.paired_cases(season=season).items())[:n_games]
    h = hashlib.sha256()
    for gid, (away, home) in pairs:
        # NOT `hash(gid)`. Python randomises string hashing per process, so
        # a seed built from it differs between two runs of this script and
        # the digests can never match — which is exactly what happened the
        # first time this was used, and it read as "the refactor changed the
        # numbers". `crc32` is stable across processes and machines.
        rng = random.Random(zlib.crc32(gid.encode()) & 0xFFFFFF)
        for _ in range(n_sims):
            r = cal.replay((away, home), lg, pens, rng)
            for ln in (r.away_sp, r.home_sp):
                h.update(f"{ln.k},{ln.bb},{ln.h},{ln.hr},{ln.outs},"
                         f"{ln.earned},{ln.runs},{ln.pitches},"
                         f"{ln.stolen_bases},{ln.caught_stealing},"
                         f"{ln.wp_pb}|".encode())
            h.update(f"{r.away},{r.home},{r.away_f5},{r.home_f5}#".encode())
    return h.hexdigest()


if __name__ == "__main__":
    g = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    s = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    print(f"  {g} games x {s} sims")
    print(f"  {digest(g, s)}")
