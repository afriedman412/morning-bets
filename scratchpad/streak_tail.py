"""IS A COLD STREAK LINEAR? NO — THE BOTTOM DECILE IS ITS OWN ANIMAL.

    venv/bin/python -m scratchpad.streak_tail [--drift -0.123]

WHY THIS EXISTS. `scratchpad/streaks.py` fits a LINE through the recent-5
K drift and reports its carryover (+0.0443 +/- 0.0305 with velocity in the
fit — 1.5 sigma, which reads as "a streak carries nothing"). That is a
correct reading of the average and a WRONG reading of any particular arm,
because the drift sd is 0.036 and the rows that prompt the question are
three and four sd out. Asking a line about the tail is extrapolation, not
measurement.

Found 2026-09-22 from a live question about an arm whose last five starts
ran 10.9% K against a season 23.2% — a drift of -0.123, the 0.03rd
percentile, with three rows in 8,900 as cold. The pooled slope said
"noise"; the tail says otherwise:

    x <= -0.06   n=414   mean y -0.0230 +/- 0.0051   carryover +0.30
    x <= -0.08   n=142   mean y -0.0304 +/- 0.0086   carryover +0.32
    x <= -0.10   n= 41   mean y -0.0349 +/- 0.0165   carryover +0.31

against -0.0034 / -0.0042 / -0.0050 from the line — 3.9 / 3.0 / 1.8 se off.
Stable across three independent cuts, and the decile table shows why the
pooled fit missed it: the middle eight deciles bounce around zero and the
bottom decile alone carries 0.22. ONE TAIL AVERAGED INTO NINE FLAT BINS.

NON-PARAMETRIC BY CONSTRUCTION. No line is fitted here and none should be
— fitting a curve to the tail is how a counted quantity gets handed back
to a search (rule 5). This reports conditional means and their standard
errors, nothing else.

HOLDOUT, AND WHY BOTH ARE PRINTED. The first cut of this ran over all four
seasons with no cutoff, which is fine for reading a live board and NOT
fine for anything that would be wired. The train-only column (rule 6) is
what a mechanism would have to be built on; the all-seasons column is
there so the difference between them is visible rather than assumed.

NOT SHIPPED, PARKED 2026-09-22 (end of season). The engine's velo term is
linear and structurally blind to this. The item is TODO 39; the falsifier
and the dilution problem — it fires on ~4% of starts, so `k_pa_all` cannot
see it and a battery row would have to be built — are recorded there.
"""
from __future__ import annotations

import statistics as st
import sys

from scratchpad import streaks
from src.context.holdout import HOLDOUT

#: The drift this screen was built to answer a question about, kept as the
#: default so the percentile line means something on a bare run.
EXAMPLE_DRIFT = 0.109 - 0.232

#: The cuts, deliberately overlapping: three nested tails agreeing is the
#: stability gate here, since no single one of them has the n to stand up.
CUTS = (-0.06, -0.08, -0.10, -0.12)

#: `streaks.py`'s pooled slope, for the "what the line predicted" column.
#: Not a parameter — it is the claim being tested.
POOLED_SLOPE = 0.0443


def _cell(sel: list[dict]) -> tuple[float, float, float]:
    """(mean x, mean y, se of mean y) for one bin."""
    mx = st.mean(r["x"] for r in sel)
    my = st.mean(r["y"] for r in sel)
    se = st.pstdev([r["y"] for r in sel]) / len(sel) ** 0.5
    return mx, my, se


def deciles(rows: list[dict]) -> None:
    """Carryover in each drift decile. THE POINT OF THE WHOLE SCREEN: the
    middle is flat and the bottom is not, which is invisible to a line."""
    n = len(rows)
    xs = sorted(r["x"] for r in rows)
    edges = [xs[int(i * n / 10)] for i in range(1, 10)]
    bins = [(-9.0, edges[0])] + list(zip(edges, edges[1:])) + [(edges[-1], 9.0)]
    print(f"\n  CARRYOVER BY DRIFT DECILE  (n={n:,})")
    print(f"    {'drift bin':>19}{'n':>7}{'mean x':>9}{'mean y':>9}"
          f"{'se':>8}{'y/x':>8}")
    for lo, hi in bins:
        sel = [r for r in rows if lo <= r["x"] < hi]
        if len(sel) < 30:
            continue
        mx, my, se = _cell(sel)
        print(f"    {lo:>8.3f}..{hi:<9.3f}{len(sel):>7,}{mx:>9.4f}"
              f"{my:>9.4f}{se:>8.4f}{my / mx:>8.2f}")


def tail(rows: list[dict], label: str) -> None:
    """The nested cold cuts, against what the pooled line predicts."""
    print(f"\n  THE COLD TAIL — {label}  (n={len(rows):,})")
    for cut in CUTS:
        sel = [r for r in rows if r["x"] <= cut]
        if len(sel) < 20:
            print(f"    x <= {cut:+.2f}   n={len(sel):>4}   too thin to read")
            continue
        mx, my, se = _cell(sel)
        pred = POOLED_SLOPE * mx
        print(f"    x <= {cut:+.2f}   n={len(sel):>4}   mean x {mx:+.4f}   "
              f"mean y {my:+.4f} +/- {se:.4f}   carryover {my / mx:+.2f}   "
              f"line {pred:+.4f} ({(my - pred) / se:+.1f} se)")


def velo_split(rows: list[dict]) -> None:
    """Does the tail care whether the RADAR fell with the box score?

    Directional only and said so: the cells run n=30-60, and the two are
    about 1.2 se apart. It is here because the sign is the same at both
    cuts and because the shipped velo term is the reason anyone would
    expect the split to exist at all.
    """
    print("\n  THE SAME TAIL, SPLIT ON VELOCITY  (directional — cells are thin)")
    for cut in (-0.06, -0.08):
        sel = [r for r in rows if r["x"] <= cut and r["d_velo"] is not None]
        for lab, sub in (("velo down >0.5mph",
                          [r for r in sel if r["d_velo"] <= -0.5]),
                         ("velo flat or up",
                          [r for r in sel if r["d_velo"] > -0.5])):
            if len(sub) < 20:
                print(f"    x<={cut:+.2f}  {lab:<18} n={len(sub):>4}  thin")
                continue
            mx, my, se = _cell(sub)
            print(f"    x<={cut:+.2f}  {lab:<18} n={len(sub):>4}  "
                  f"mean y {my:+.4f} +/- {se:.4f}   carryover {my / mx:+.2f}")


def main(argv: list[str]) -> None:
    drift = EXAMPLE_DRIFT
    for i, a in enumerate(argv):
        if a.startswith("--drift"):
            drift = float(a.split("=", 1)[1] if "=" in a else argv[i + 1])

    rows = [r for r in streaks.build() if r["d_velo"] is not None]
    xs = sorted(r["x"] for r in rows)
    colder = sum(1 for v in xs if v <= drift)
    print(f"\n  drift sd {st.pstdev([r['x'] for r in rows]):.4f}")
    print(f"  a drift of {drift:+.3f} sits at the "
          f"{100 * colder / len(rows):.2f}th percentile — {colder} of "
          f"{len(rows):,} rows are that cold")

    deciles(rows)
    # BOTH POPULATIONS, never one. See the module docstring: the all-seasons
    # number is for reading a board tonight, the train-only number is the
    # only one a mechanism could ever be built on.
    tail(rows, "all seasons (board reading)")
    train = [r for r in rows if r["date"] < HOLDOUT]
    tail(train, f"TRAIN ONLY, date < {HOLDOUT} (rule 6)")
    velo_split(rows)


if __name__ == "__main__":
    main(sys.argv[1:])
