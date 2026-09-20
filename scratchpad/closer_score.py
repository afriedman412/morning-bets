"""IS THE BEST ARM STILL THERE IN THE NINTH? — TODO 21, `USE_PEN_INNING`.

    venv/bin/python -m scratchpad.closer_score [n_sims] [--off]

The item is a SELECTION defect, so it is scored on selection: for every
relief entry in innings 7, 8 and 9+, the quality percentile of the arm the
engine chose among the arms it still had — the same construction
`pen_pick.py` and `pen_pick_inning.py` count on real games, so the simulated
column and the real column mean the same thing.

WHY NOT RUNS. Late-inning runs are the downstream reading and the battery
already carries them; what a pooled table does is put the right arm in the
wrong inning, which shows up in WHO, not in the total. Reading this on runs
would be applying a fitting standard to a counted table — the drift
`CLAUDE.md` warns about — and the effect is 0.24 of a share point on a
population that is a fifth of relief entries.
"""
from __future__ import annotations

import random
import sys
from collections import defaultdict

from src.context import calibrate as cal
from src.context import game, sim, store
from src.context.sources import rates as rate_src

FOLDS = [(2023, "2023-07-01"), (2024, "2024-07-01"),
         (2025, "2025-07-01"), (2026, "2026-07-01")]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 10


BUCKETS = ("lead", "tied", "trail", "mid", "blowout")


def real_profile() -> tuple[dict, dict]:
    """Real bin1 share, POOLED over margin and PER margin bucket.

    BOTH, because the pooled comparison is confounded and the first version
    of this script only had that one. Selection is keyed on margin, so if the
    engine arrives at the ninth in different margin states than reality does,
    the pooled share moves without the selection rule being wrong at all —
    trailing in the ninth the real best-arm share is 0.2568 and protecting a
    lead it is 0.5750, so the MIX alone can swing it by thirty points.
    """
    from scratchpad import pen_pick_inning as ppi
    pctl, _ = ppi.count()
    pooled: dict = {}
    cell: dict = {}
    for i_ in ("7", "8", "9+"):
        n = sum(pctl[(b, i_)]["n"] for b in BUCKETS)
        if n:
            pooled[i_] = (sum(pctl[(b, i_)][0] for b in BUCKETS) / n, n)
        for b in BUCKETS:
            m = pctl[(b, i_)]["n"]
            if m:
                cell[(b, i_)] = (pctl[(b, i_)][0] / m, m)
    return pooled, cell


def main() -> None:
    if "--off" in sys.argv:
        game.USE_PEN_INNING = False
        print("*** USE_PEN_INNING OFF — the pooled table")
    real = real_profile()
    got: dict = defaultdict(lambda: defaultdict(int))
    orig = game.Side.next_arm

    def spy(self, entry_outs=0, rng=None, inning=0, margin=None):
        # BEFORE the call, so the pool is the arms he still had — the same
        # denominator the real count uses ("still unused tonight").
        slot = 0 if not self.starter_out else self.pen_i + 1
        pool = list(self.pen[slot:])
        orig(self, entry_outs, rng, inning, margin)
        if inning >= game.PEN_PICK_LATE and len(pool) > 1:
            chosen = self.current
            ranked = sorted(pool, key=lambda a: a.bb_pct - a.k_pct)
            if chosen in ranked:
                pct = ranked.index(chosen) / (len(ranked) - 1)
                k = game._pick_inning(inning)
                got[k][min(int(pct * 5), 4)] += 1
                got[k]["n"] += 1

    game.Side.next_arm = spy
    try:
        for yr, cut in FOLDS:
            pairs = cal.paired_cases(season=yr, rates_before=cut, since=cut)
            lg = sim.league(season=yr, before=cut)
            pens = rate_src.bullpens(lg, season=yr, before=cut)
            for gi, (gid, pair) in enumerate(sorted(pairs.items())):
                for i in range(N):
                    rng = random.Random(yr * 1000003 + gi * 1009 + i)
                    cal.replay(pair, lg, pens, rng)
            print(f"fold {yr}: {len(pairs)} games", flush=True)
    finally:
        game.Side.next_arm = orig

    print("\nQUALITY PERCENTILE OF THE ARM CHOSEN, by entry inning")
    print(f"  {'inn':<5}{'src':<6}{'n':>8}" +
          "".join(f"{f'bin{i+1}':>8}" for i in range(5)))
    for k in ("7", "8", "9+"):
        if k in real:
            print(f"  {k:<5}{'real':<6}{'':>8}" +
                  "".join(f"{x:>8.4f}" for x in real[k]))
        n = got[k]["n"]
        if n:
            print(f"  {'':<5}{'sim':<6}{n:>8}" +
                  "".join(f"{got[k][i] / n:>8.4f}" for i in range(5)))
    print("\n  bin1 is the best arm he still had. The item is that the sim's")
    print("  bin1 must RISE from the 7th to the 9th the way reality does.")


if __name__ == "__main__":
    main()
