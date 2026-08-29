"""One hash over many simulated games, for verifying a change is inert.

    venv/bin/python -m scratchpad.fingerprint [n_games] [n_sims]

The discipline this project already uses for a refactor that must not
change behaviour: the `odds_mult` migration was accepted only after 400
games x 6 sims hashed identically before and after. A test that asserts
"about the same" cannot tell a correct refactor from a small real change,
and a small real change is exactly what a plumbing edit produces when it
is subtly wrong.
"""
from __future__ import annotations

import hashlib
import random
import sys

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src

HOLDOUT = "2026-07-01"


def main(argv):
    n_games = int(argv[0]) if argv else 400
    n_sims = int(argv[1]) if len(argv) > 1 else 6
    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    gids = sorted(pairs)[:n_games]
    lg = sim.league(before=HOLDOUT)
    pens = rate_src.bullpens(lg, before=HOLDOUT)
    h = hashlib.md5()
    for i, gid in enumerate(gids):
        home = next(x for x in pairs[gid] if x[0]["is_home"])
        away = next(x for x in pairs[gid] if not x[0]["is_home"])
        an = cal.adjust_lineup(away[2], False)
        hn = cal.adjust_lineup(home[2], True)
        for draw in range(n_sims):
            rng = random.Random(7 + i * 100003 + draw)
            A = game.build_side(away[1],
                                pens.get((away[0]["team"] or "").upper(), []),
                                hn, sim.Hook(), rng, team=away[0]["team"],
                                date=away[0].get("date"))
            H = game.build_side(home[1],
                                pens.get((home[0]["team"] or "").upper(), []),
                                an, sim.Hook(), rng, team=home[0]["team"],
                                date=home[0].get("date"))
            r = game.simulate_game(A, H, lg, rng, track=(5,))
            h.update(f"{r.away},{r.home},{r.away_sp.outs},{r.away_sp.k},"
                     f"{r.home_sp.outs},{r.home_sp.k},"
                     f"{r.prefix_side.get(5)}|".encode())
    print(f"  {len(gids)} games x {n_sims} sims")
    # getattr, so this runs against a checkout that predates the flag —
    # which is the entire point of a before/after fingerprint.
    print(f"  USE_FIELD_STATE={getattr(sim, 'USE_FIELD_STATE', 'absent')} "
          f"STATE_MULT="
          f"{'populated' if getattr(sim, 'STATE_MULT', None) else 'empty'}")
    print(f"  fingerprint {h.hexdigest()}")


if __name__ == "__main__":
    main(sys.argv[1:])
