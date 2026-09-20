"""DOES THE BULK ARM NOW PITCH LIKE A STARTER? — TODO 15, `USE_BULK_STARTER`.

    venv/bin/python -m scratchpad.bulk_score [n_sims]

SCORED ON HIS OWN LINE, NOT ON THE GAME. The item's pre-registered falsifier
says so and the arithmetic backs it: the mechanism fires on 23 of 7,096
sides across four folds, and `opener_score`'s run-level CRPS se is 0.0164 at
124 games. A run total over 23 sides cannot resolve this in either
direction — it would read as a null whatever the truth, which is the failure
mode rule 7 exists for.

So this counts the FOLLOWER'S OUTS, simulated against what he actually
recorded, on exactly the sides where a bulk arm is named. Run it with the
flag on and off; the gap that matters is against the real column.

POWER, before the result: 23 real outings, sd of relief/start outs about 4,
so the standard error on the real mean is roughly 0.8 outs. The effect being
looked for is the difference between running a rotation starter as a
one-inning reliever and running him as a starter — several outs, not
tenths — so the test resolves it. Nothing subtler than that is readable here
and should not be claimed.
"""
from __future__ import annotations

import random
import sys

from src.context import calibrate as cal
from src.context import game, sim, store

FOLDS = [(2023, "2023-07-01"), (2024, "2024-07-01"),
         (2025, "2025-07-01"), (2026, "2026-07-01")]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 40


def real_followers() -> dict:
    """{(date, TEAM): outs} for the arm who actually followed the starter."""
    with store.connect() as c:
        return {(r["date"], (r["team"] or "").upper()): r["o"]
                for r in c.execute(
                    "select date, team, outs_recorded o from mlb_stints"
                    " where appearance_order = 1")}


def main() -> None:
    if "--off" in sys.argv:
        game.USE_BULK_STARTER = False
        print("*** USE_BULK_STARTER OFF — the pre-item engine")
    real = real_followers()

    orig = game.Side.to_bulk
    orig_sim = game.simulate_game

    # His line is folded away when his own hook pulls him, so it is captured
    # at handover. Two patches, both restored in the finally.
    def spy(self):
        ok = orig(self)
        if ok:
            self.__dict__["_bulk_line"] = self.cur_line
        return ok

    keep = {}

    def simulate_game(A, H, *a, **k):
        keep["A"], keep["H"] = A, H
        return orig_sim(A, H, *a, **k)

    # OFF, `to_bulk` never fires and the follower is just the first man out
    # of the pen, whose line is folded away at HIS handover. Same patch
    # `bulk_shape` uses, so the two arms of the A/B measure the same man.
    orig_next = game.Side.next_arm

    def next_arm(self, entry_outs=0, rng=None, inning=0, margin=None):
        self.__dict__.setdefault("_arm_outs", []).append(self.cur_line.outs)
        return orig_next(self, entry_outs, rng, inning, margin)

    game.Side.next_arm = next_arm
    game.Side.to_bulk = spy
    game.simulate_game = simulate_game
    cal.game.simulate_game = simulate_game
    s_outs: list[int] = []
    r_outs: list[int] = []
    try:
        from src.context.sources import rates as rate_src
        for yr, cut in FOLDS:
            pairs = cal.paired_cases(season=yr, rates_before=cut, since=cut)
            lg = sim.league(season=yr, before=cut)
            pens = rate_src.bullpens(lg, season=yr, before=cut)
            hits = []
            for gi, (gid, pair) in enumerate(sorted(pairs.items())):
                which = [s for s, c_ in (("A", pair[0]), ("H", pair[1]))
                         if c_[0].get("bulk") is not None]
                if which:
                    hits.append((gi, pair, which))
            for gi, pair, which in hits:
                for s in which:
                    c_ = pair[0] if s == "A" else pair[1]
                    ro = real.get((c_[0].get("date"),
                                   (c_[0].get("team") or "").upper()))
                    if ro is not None:
                        r_outs.append(ro)
                for i in range(N):
                    rng = random.Random(yr * 1000003 + gi * 1009 + i)
                    cal.replay(pair, lg, pens, rng)
                    for s in which:
                        side = keep[s]
                        # OFF, `to_bulk` never fires and the follower is the
                        # first man out of the pen — read HIS line instead,
                        # or the two arms of the A/B measure different men.
                        ln = side.__dict__.pop("_bulk_line", None)
                        arms = (list(side.__dict__.pop("_arm_outs", []))
                                + [side.cur_line.outs])
                        if ln is not None:
                            s_outs.append(ln.outs)
                        elif len(arms) > 1:
                            s_outs.append(arms[1])
            print(f"fold {yr}: {len(hits)} games with a named bulk arm",
                  flush=True)
    finally:
        game.Side.to_bulk = orig
        game.simulate_game = orig_sim
        cal.game.simulate_game = orig_sim

    def shape(v, lbl):
        n = len(v)
        if not n:
            print(f"  {lbl}: nothing recorded")
            return
        m = sum(v) / n
        sd = (sum((x - m) ** 2 for x in v) / max(n - 1, 1)) ** 0.5
        print(f"  {lbl:<6} n={n:>6}   mean {m:5.2f} +-{sd / n ** 0.5:4.2f}   "
              f"<=6 {sum(1 for x in v if x <= 6)/n:5.1%}   "
              f">=12 {sum(1 for x in v if x >= 12)/n:5.1%}")

    print("\nTHE NAMED BULK ARM — outs recorded")
    shape(r_outs, "real")
    shape(s_outs, "sim")


if __name__ == "__main__":
    main()
