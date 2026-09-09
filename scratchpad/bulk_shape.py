"""WHAT LENGTH DOES THE ENGINE GIVE THE ARM BEHIND AN OPENER? — TODO 15 part two.

    venv/bin/python -m scratchpad.bulk_shape [n_sims]

`bulk_type.py` counted what really happens: the follower is a real starter
51.5% of the time and goes 13.00 outs, a pure reliever 48.5% and goes 6.33.
A BIMODAL population. The engine has one mechanism for all of them —
`relief.continues` on intent bucket 0 — which is a single geometric-ish
hazard and cannot be bimodal at all.

WHY THE MEAN IS THE WRONG THING TO LOOK AT HERE, and this is rule 2 in its
purest form. The counted mix means 9.53 outs; chaining the shipped intent
hazard gives about 8.9. **Those nearly agree, and the shape cannot.** If
this instrument is read on the mean it will report a healthy mechanism, the
same way the strikeout distribution reads healthy on its mean while being
3.9 sigma wrong at nine or more. Read the SHARES: reality puts 20.3% of
followers at fifteen or more outs (a starter finishing a game the opener
began) and the engine has no way to produce them.

MEASUREMENT NOTE. `Side` keeps only the STARTER's line — every relief line
is discarded at handover (`next_arm` folds and resets `cur_line`), which is
the documented denominator trap in CLAUDE.md. So this patches `next_arm` to
record each outgoing arm's outs before the fold, and `simulate_game` to
keep the Side objects. Both patches are restored in a finally.
"""
from __future__ import annotations

import random
import sys
from src.context import calibrate as cal
from src.context import game, sim, store
from src.context.sources import rates as rate_src

FOLDS = [(2023, "2023-07-01"), (2024, "2024-07-01"),
         (2025, "2025-07-01"), (2026, "2026-07-01")]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 40


def real_followers():
    """{(date, team): outs} for the arm that actually followed the starter."""
    with store.connect() as c:
        return {(r["date"], (r["team"] or "").upper()): r["o"]
                for r in c.execute(
                    "select date, team, outs_recorded o from mlb_stints"
                    " where appearance_order = 1")}


def _install():
    orig_next = game.Side.next_arm
    orig_sim = game.simulate_game
    seen = {}

    def next_arm(self, entry_outs=0, rng=None, inning=0, margin=None):
        self.__dict__.setdefault("_arm_outs", []).append(self.cur_line.outs)
        return orig_next(self, entry_outs, rng, inning, margin)

    def simulate_game(A, H, *a, **k):
        seen["A"], seen["H"] = A, H
        return orig_sim(A, H, *a, **k)

    game.Side.next_arm = next_arm
    game.simulate_game = simulate_game
    cal.game.simulate_game = simulate_game
    return orig_next, orig_sim, seen


def _restore(orig_next, orig_sim):
    game.Side.next_arm = orig_next
    game.simulate_game = orig_sim
    cal.game.simulate_game = orig_sim


def arms_of(side) -> list[int]:
    """[starter outs, follower outs, ...] for one simulated side."""
    return list(side.__dict__.get("_arm_outs", [])) + [side.cur_line.outs]


def main() -> None:
    # ATTRIBUTION CONTROL. Chaining the shipped intent hazard by hand
    # predicts about nine outs for the follower and the engine produces
    # five, so a SECOND mechanism is shortening him. `--nohook` switches
    # off the per-plate-appearance relief hook: if the number jumps, the
    # binding constraint is `RELIEF_MID_REMOVAL`, not the continuation
    # table, and fixing only the latter would have bought nothing.
    if "--nohook" in sys.argv:
        game.USE_MEASURED_RELIEF_HOOK = False
        print("*** USE_MEASURED_RELIEF_HOOK OFF — attribution control")
    real = real_followers()
    sim_outs: list[int] = []
    real_outs: list[int] = []
    orig_next, orig_sim, seen = _install()
    try:
        for yr, cut in FOLDS:
            pairs = cal.paired_cases(season=yr, rates_before=cut, since=cut)
            lg = sim.league(season=yr, before=cut)
            pens = rate_src.bullpens(lg, season=yr, before=cut)
            hits = []
            for gid, pair in sorted(pairs.items()):
                sides = []
                for s, c_ in (("away", pair[0]), ("home", pair[1])):
                    nm, d = c_[0].get("player_name"), c_[0].get("date")
                    if game.opener_record(nm, d) is not None:
                        team = (c_[0].get("team") or "").upper()
                        sides.append((s, real.get((d, team))))
                if sides:
                    hits.append((gid, pair, sides))
            for gi, (gid, pair, sides) in enumerate(hits):
                for _, ro in sides:
                    if ro is not None:
                        real_outs.append(ro)
                for i in range(N):
                    rng = random.Random(yr * 1000003 + gi * 1009 + i)
                    cal.replay(pair, lg, pens, rng)
                    for s, _ in sides:
                        side = seen["A"] if s == "away" else seen["H"]
                        a = arms_of(side)
                        if len(a) > 1:
                            sim_outs.append(a[1])
            print(f"fold {yr}: {len(hits)} opener games", flush=True)
    finally:
        _restore(orig_next, orig_sim)

    def shape(v, lbl):
        n = len(v)
        m = sum(v) / n
        print(f"  {lbl:<18} n={n:>6}   mean {m:5.2f}   "
              f"<=6 {sum(1 for x in v if x <= 6)/n:5.1%}   "
              f"7-14 {sum(1 for x in v if 7 <= x <= 14)/n:5.1%}   "
              f">=15 {sum(1 for x in v if x >= 15)/n:5.1%}")

    print("\nTHE ARM BEHIND THE OPENER — outs")
    shape(real_outs, "real")
    shape(sim_outs, "sim")
    print("\n  Read the SHARES, not the mean. A single hazard cannot be"
          " bimodal.")


if __name__ == "__main__":
    main()
