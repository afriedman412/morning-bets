"""HOW LONG DOES THE ENGINE LEAVE A RELIEVER OUT THERE? — TODO 15 part two.

    venv/bin/python -m scratchpad.pen_shape [n_sims]

`bulk_shape.py` asks this of the one arm behind an opener, which is 3.5% of
starts. The continuation-table recount is not an opener change at all — it
moved every cell for every reliever, worst for the late clean entry that
nearly every arm in every game hits — so it has to be scored on every relief
outing, over the same four folds.

THREE NUMBERS, and the third is the one that pays. Mean outs is the level.
The SHARES are the shape: a one-inning arm and a two-inning arm are the same
mean and a different bullpen. ARMS PER SIDE is what a total actually feels —
each handover is a fresh pitcher facing the top of the order, and burning one
arm too many per game puts a worse pitcher on the mound in the eighth of
every game the model prices.

MEASUREMENT NOTE, the same one `bulk_shape` carries: `Side` keeps only the
STARTER's line and folds every relief line away at handover, so this patches
`next_arm` to record the outgoing arm's outs first. Both patches restored in
a finally.
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
N = int(sys.argv[1]) if len(sys.argv) > 1 else 5


def real_relief() -> dict:
    """{(date, TEAM): [outs, ...]} for every arm after the starter."""
    out = defaultdict(list)
    with store.connect() as c:
        for r in c.execute(
                "select date, team, outs_recorded o from mlb_stints"
                " where appearance_order > 0 order by appearance_order"):
            out[(r["date"], (r["team"] or "").upper())].append(r["o"] or 0)
    return out


def _install():
    orig_next = game.Side.next_arm
    orig_sim = game.simulate_game
    seen = {}

    def next_arm(self, entry_outs=0, rng=None, inning=0, margin=None):
        self.__dict__.setdefault("_arm_outs", []).append(
            (self.cur_line.outs, self.cur_line.batters))
        return orig_next(self, entry_outs, rng, inning, margin)

    def simulate_game(A, H, *a, **k):
        seen["A"], seen["H"] = A, H
        return orig_sim(A, H, *a, **k)

    game.Side.next_arm = next_arm
    game.simulate_game = simulate_game
    cal.game.simulate_game = simulate_game
    return orig_next, orig_sim, seen


def main() -> None:
    real = real_relief()
    s_outs: list[int] = []
    r_outs: list[int] = []
    s_arms: list[int] = []
    r_arms: list[int] = []
    orig_next, orig_sim, seen = _install()
    try:
        for yr, cut in FOLDS:
            pairs = cal.paired_cases(season=yr, rates_before=cut, since=cut)
            lg = sim.league(season=yr, before=cut)
            pens = rate_src.bullpens(lg, season=yr, before=cut)
            for gi, (gid, pair) in enumerate(sorted(pairs.items())):
                # THE REAL SIDE IS COUNTED ON THE SAME GAMES, once, not once
                # per draw — a paired comparison, not two populations.
                for c_ in pair:
                    key = (c_[0].get("date"),
                           (c_[0].get("team") or "").upper())
                    got = real.get(key)
                    if got is not None:
                        r_outs.extend(got)
                        r_arms.append(len(got))
                for i in range(N):
                    rng = random.Random(yr * 1000003 + gi * 1009 + i)
                    cal.replay(pair, lg, pens, rng)
                    for s in ("A", "H"):
                        side = seen[s]
                        arms = (list(side.__dict__.get("_arm_outs", []))
                                + [(side.cur_line.outs,
                                    side.cur_line.batters)])
                        side.__dict__["_arm_outs"] = []
                        # THE PHANTOM ARM, and it is 80% of sides. The
                        # engine calls `_end_of_inning` after the LAST
                        # inning too, so a failed continuation roll warms up
                        # a reliever who never faces anyone. He is not a
                        # relief outing and `mlb_stints` has no row for him.
                        # Counting him read 4.23 arms a side against a real
                        # 3.38 and put 41% of outings at two outs or fewer —
                        # a wrong instrument, not a wrong engine.
                        rel = [o for o, bf in arms[1:] if bf > 0]
                        s_outs.extend(rel)
                        s_arms.append(len(rel))
            print(f"fold {yr}: {len(pairs)} games", flush=True)
    finally:
        game.Side.next_arm = orig_next
        game.simulate_game = orig_sim
        cal.game.simulate_game = orig_sim

    def shape(v, lbl):
        n = len(v)
        m = sum(v) / n
        print(f"  {lbl:<6} n={n:>7}   mean {m:5.2f}   "
              f"<=2 {sum(1 for x in v if x <= 2)/n:5.1%}   "
              f"3 {sum(1 for x in v if x == 3)/n:5.1%}   "
              f"4-6 {sum(1 for x in v if 4 <= x <= 6)/n:5.1%}   "
              f">=7 {sum(1 for x in v if x >= 7)/n:5.1%}")

    print(f"\nRELIEF OUTING LENGTH, outs ({N} sims a game)")
    shape(r_outs, "real")
    shape(s_outs, "sim")
    print("\nRELIEVERS USED PER SIDE")
    print(f"  real  {sum(r_arms)/len(r_arms):.3f}   n={len(r_arms):,}")
    print(f"  sim   {sum(s_arms)/len(s_arms):.3f}   n={len(s_arms):,}")


if __name__ == "__main__":
    main()
