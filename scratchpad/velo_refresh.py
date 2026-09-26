"""HOW FAR DID A VELO REBUILD MOVE THE SHIPPED KICKS?

    venv/bin/python -m scratchpad.velo_refresh OLD.json [NEW.json]

THE QUESTION THIS ANSWERS, and it is the one rule 15 forces after any
data refresh: the battery said "no row moved by more than one se". Is the
scorecard BLIND to the change, or did the change do nothing? Those are
different and the difference has to be quantified, never asserted.

There are exactly two reasons a row can be blind and they need different
evidence. DILUTION — the mechanism fires on a small population — is read
off the "starts whose kick changed" line. SIZE — it fires everywhere but
under the resolution of the row that would see it — is read off the mean
shift against that row's se. This prints both so the right one gets named.

WORKED, 2026-09-22, rebuilding `velo_starts.json` after it had sat eight
days stale and still counted spring training (19,497 -> 19,048 rows):

    starts whose kick changed   3,843 / 9,426  (40.8%)   <- NOT dilution
    mean k_pct shift            -0.00013  =  0.08 se of k_pa_all
    median |delta| 0.00053   p90 0.00160   max 0.01987

So: it touched 41% of scored starts, and was still twelve times below what
the battery can resolve. Flat was the only possible outcome. AND THE LAST
COLUMN IS WHY THE REFRESH STILL MATTERED — the worst-affected arm's kick
moved two full points of K%, which is a live-board effect that a pooled
four-fold row averages away by construction.

THE POPULATION IS THE BATTERY'S, not the whole table: every starter-start
from July 1 onward in each season, which is what the four folds score.
Comparing over all starts would flatter the numbers with rows nothing is
graded on.
"""
from __future__ import annotations

import statistics as st
import sys

from src.context import store, velo

#: se of the battery's `k_pa_all` row (~70,000 PA a fold). The denominator
#: for "could the scorecard have seen this", not a tuning constant.
K_PA_ALL_SE = 0.0016


def fold_starts() -> list[tuple[str, str]]:
    """(pitcher, date) for every starter-start the four folds score."""
    with store.connect() as c:
        return [(r[0], r[1]) for r in c.execute(
            "select s.player_name, s.date from mlb_stints s"
            " join bets.games g on g.game_id = s.game_id"
            " where s.appearance_order = 0 and g.sport = 'mlb'"
            "   and substr(s.date, 6) >= '07-01'"
            " order by s.date").fetchall()]


def kicks(path: str, starts) -> tuple[list[float], list[float]]:
    """Both shipped kicks for every start, read through `velo`'s OWN
    lookup with the table swapped underneath — never a reimplementation
    of the gates, which is how a comparison quietly measures the wrong
    thing."""
    velo.PATH = path
    velo._reset()
    return ([velo.kick_for(n, d) for n, d in starts],
            [velo.bb_kick_for(n, d) for n, d in starts])


def report(label: str, old: list[float], new: list[float],
           row_se: float | None = None) -> None:
    d = [n - o for o, n in zip(old, new)]
    moved = [x for x in d if abs(x) > 1e-12]
    print(f"\n  {label}")
    print(f"    mean old {st.mean(old):+.5f}   mean new {st.mean(new):+.5f}"
          f"   mean delta {st.mean(d):+.5f}")
    print(f"    starts whose kick changed: {len(moved):,} / {len(d):,}"
          f"  ({100 * len(moved) / len(d):.1f}%)"
          f"   <- {'NOT dilution' if len(moved) > len(d) // 10 else 'DILUTION'}")
    if moved:
        a = sorted(abs(x) for x in moved)
        print(f"    |delta|  median {a[len(a) // 2]:.5f}"
              f"   p90 {a[int(.9 * len(a))]:.5f}   max {a[-1]:.5f}")
    if row_se:
        print(f"    mean shift is {abs(st.mean(d)) / row_se:.2f} se of the "
              f"row that would see it (se {row_se})")


def main(argv: list[str]) -> None:
    if not argv:
        print(__doc__.strip().splitlines()[2])
        raise SystemExit(1)
    old_path = argv[0]
    new_path = argv[1] if len(argv) > 1 else velo.PATH
    starts = fold_starts()
    print(f"\n  {len(starts):,} starter-starts in the four fold windows")
    print(f"  OLD {old_path}\n  NEW {new_path}")
    k_old, b_old = kicks(old_path, starts)
    k_new, b_new = kicks(new_path, starts)
    report("k_pct kick", k_old, k_new, K_PA_ALL_SE)
    report("bb_pct kick", b_old, b_new)


if __name__ == "__main__":
    main(sys.argv[1:])
