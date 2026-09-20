"""WHY ARE 29% OF SIMULATED RELIEF OUTINGS TWO OUTS OR FEWER? — TODO 23.

    venv/bin/python -m scratchpad.pen_short [n_sims]

`pen_shape.py` says the level and the long tail of relief-outing length are
now right and the short end is not: 29.1% of simulated outings are <= 2 outs
against a real 22.3%. That is a SHAPE row and it has two candidate causes
that the pooled share cannot tell apart.

    THE ENTRY MIX. An arm who enters with two out and does not come back for
    the next inning records exactly ONE out, and no hook was involved. So a
    model that hands the ball over mid-inning too often produces short
    outings for a reason that has nothing to do with how long it leaves
    anyone out there.

    THE HOOK. Conditional on the state he walked into, the arm is pulled
    before he has recorded three outs.

The decomposition is the entry-outs mix and the length distribution WITHIN
each entry state, real against sim on the same games. If the mix is wrong
and the conditionals are right, the defect is the mid-inning ENTRY rate —
which is the starter's hook and the reliever's hook producing handovers, not
the continuation table. If the conditionals are wrong the hook is charging
too much, and the cell that is wrong says which arm it is charging.

MEASUREMENT NOTES, both inherited from `pen_shape` and both load-bearing:

  * `Side` keeps only the STARTER's line and folds every relief line away at
    handover, so `next_arm` is patched to record the outgoing arm first.
  * THE PHANTOM ARM: `_end_of_inning` fires after the last inning too, so a
    failed continuation roll warms up a reliever who never faces a batter.
    He is not a relief outing. Filter on `batters > 0`.
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
    """{(date, TEAM): [(entry_outs, entry_inning, outs), ...]}, after the starter."""
    out = defaultdict(list)
    with store.connect() as c:
        for r in c.execute(
                "select date, team, entry_outs eo, entry_inning ei,"
                " outs_recorded o from mlb_stints"
                " where appearance_order > 0 order by appearance_order"):
            out[(r["date"], (r["team"] or "").upper())].append(
                (min(max(r["eo"] or 0, 0), 2), r["ei"] or 0, r["o"] or 0))
    return out


def _install():
    """Record every arm as he LEAVES, with the state he walked into."""
    orig_next = game.Side.next_arm
    orig_sim = game.simulate_game
    seen = {}

    def next_arm(self, entry_outs=0, rng=None, inning=0, margin=None):
        self.__dict__.setdefault("_arms", []).append(
            (self.cur_entry_outs, self.cur_entry_inning,
             self.cur_line.outs, self.cur_line.batters))
        return orig_next(self, entry_outs, rng, inning, margin)

    def simulate_game(A, H, *a, **k):
        seen["A"], seen["H"] = A, H
        return orig_sim(A, H, *a, **k)

    game.Side.next_arm = next_arm
    game.simulate_game = simulate_game
    cal.game.simulate_game = simulate_game
    return orig_next, orig_sim, seen


def shape(v: list[int]) -> str:
    n = len(v)
    if not n:
        return "        -"
    m = sum(v) / n
    return (f"n={n:>7}  mean {m:5.2f}   "
            f"0 {sum(1 for x in v if x == 0)/n:5.1%}  "
            f"1 {sum(1 for x in v if x == 1)/n:5.1%}  "
            f"2 {sum(1 for x in v if x == 2)/n:5.1%}  "
            f"<=2 {sum(1 for x in v if x <= 2)/n:5.1%}  "
            f"3 {sum(1 for x in v if x == 3)/n:5.1%}  "
            f">=4 {sum(1 for x in v if x >= 4)/n:5.1%}")


def main() -> None:
    real = real_relief()
    s: dict = defaultdict(list)      # entry_outs -> [outs]
    r: dict = defaultdict(list)
    s_bucket: dict = defaultdict(list)   # (entry bucket) -> [outs]
    r_bucket: dict = defaultdict(list)
    orig_next, orig_sim, seen = _install()
    try:
        for yr, cut in FOLDS:
            pairs = cal.paired_cases(season=yr, rates_before=cut, since=cut)
            lg = sim.league(season=yr, before=cut)
            pens = rate_src.bullpens(lg, season=yr, before=cut)
            for gi, (gid, pair) in enumerate(sorted(pairs.items())):
                for c_ in pair:
                    key = (c_[0].get("date"), (c_[0].get("team") or "").upper())
                    for eo, ei, o in real.get(key) or ():
                        r[eo].append(o)
                        r_bucket[_bucket(ei)].append(o)
                for i in range(N):
                    rng = random.Random(yr * 1000003 + gi * 1009 + i)
                    cal.replay(pair, lg, pens, rng)
                    for side_key in ("A", "H"):
                        side = seen[side_key]
                        arms = (list(side.__dict__.get("_arms", []))
                                + [(side.cur_entry_outs,
                                    side.cur_entry_inning,
                                    side.cur_line.outs,
                                    side.cur_line.batters)])
                        side.__dict__["_arms"] = []
                        for eo, ei, o, bf in arms[1:]:
                            if bf <= 0:
                                continue          # the phantom arm
                            s[min(max(eo, 0), 2)].append(o)
                            s_bucket[_bucket(ei)].append(o)
            print(f"fold {yr}: {len(pairs)} games", flush=True)
    finally:
        game.Side.next_arm = orig_next
        game.simulate_game = orig_sim
        cal.game.simulate_game = orig_sim

    all_r = [x for v in r.values() for x in v]
    all_s = [x for v in s.values() for x in v]
    print(f"\nRELIEF OUTING LENGTH, outs ({N} sims a game)")
    print(f"  real  {shape(all_r)}")
    print(f"  sim   {shape(all_s)}")

    print("\nTHE ENTRY MIX — how often the arm walks into an inning already"
          " in progress")
    for k in (0, 1, 2):
        rp = len(r[k]) / len(all_r) if all_r else 0
        sp = len(s[k]) / len(all_s) if all_s else 0
        print(f"  entry_outs {k}   real {rp:6.2%}   sim {sp:6.2%}"
              f"   {sp - rp:+6.2%}")
    rm = sum(len(r[k]) for k in (1, 2)) / len(all_r)
    sm = sum(len(s[k]) for k in (1, 2)) / len(all_s)
    print(f"  mid-inning     real {rm:6.2%}   sim {sm:6.2%}   {sm - rm:+6.2%}")

    print("\nLENGTH WITHIN THE ENTRY STATE — the hook, with the mix divided"
          " out")
    for k in (0, 1, 2):
        print(f"  entry_outs {k}")
        print(f"    real  {shape(r[k])}")
        print(f"    sim   {shape(s[k])}")

    print("\nAND BY ENTRY INNING (intent bucket), all entry states pooled")
    for b, lbl in ((0, "innings 1-3"), (1, "innings 4-6"), (2, "innings 7+")):
        print(f"  {lbl}")
        print(f"    real  {shape(r_bucket[b])}")
        print(f"    sim   {shape(s_bucket[b])}")

    # THE COUNTERFACTUAL: hold the engine's own conditional lengths and give
    # it the league's entry mix. Whatever is left over is the hook.
    if all_r and all_s:
        mixed = sum(
            (len(r[k]) / len(all_r)) * (sum(1 for x in s[k] if x <= 2)
                                        / max(len(s[k]), 1))
            for k in (0, 1, 2))
        print(f"\n  <=2 share, sim as it stands          "
              f"{sum(1 for x in all_s if x <= 2)/len(all_s):6.2%}")
        print(f"  <=2 share, sim on the REAL entry mix "
              f"{mixed:6.2%}")
        print(f"  <=2 share, real                      "
              f"{sum(1 for x in all_r if x <= 2)/len(all_r):6.2%}")


def _bucket(entry_inning: int) -> int:
    from src.context import relief
    return relief.intent_bucket(max(entry_inning or 1, 1))


if __name__ == "__main__":
    main()
