"""HOW FAR DID THE NO-BULLPEN FOLD BUG REACH? (TODO 20)

    venv/bin/python -m scratchpad.pen_exposure [broken_fp] [fixed_fp]

QUESTION    `bullpens(lg, before=cut)` without `season=` returned zero clubs
            for 2023-2025, and an empty pen hands every relief inning to the
            STARTER'S rates. Every recorded cross-fold conclusion was read
            off a harness that made that call. WHICH rows does it actually
            move, and by how much against their own standard error?

TEST        The two battery runs that bracket the fix, identical flags and
            identical seeds: broken `538f29ee3751` against fixed
            `55b73d1d3ed5`. Same games, same draws, so the difference IS the
            bug. Report per row group, per fold, in units of the row's own
            se — a row that moves under 1 se is a row whose recorded number
            survives, and 2026 is the built-in negative control because it
            always had a live pen.

WHY IN SE UNITS. The recorded conclusions are all "this improved by X, and
X is Y se". A bug that moves the LEVEL of a row by 4 se voids any recorded
reading of that level; one that moves it by 0.1 se does not, however real
the mechanism is.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict

BROKEN = "538f29ee3751"
FIXED = "55b73d1d3ed5"


def load(fp):
    with open(f"scratchpad/battery_{fp}.json") as fh:
        d = json.load(fh)
    return d, {(r["fold"], r["group"], r["key"]): r for r in d["rows"]}


def main(argv):
    broken_fp = argv[0] if argv else BROKEN
    fixed_fp = argv[1] if len(argv) > 1 else FIXED
    bd, b = load(broken_fp)
    fd, f = load(fixed_fp)

    diff = {k: v["flags"] for k, v in (("b", bd["meta"]), ("f", fd["meta"]))}
    off = [k for k in diff["b"] if diff["b"][k] != diff["f"].get(k)]
    print(f"  broken {broken_fp}  vs  fixed {fixed_fp}"
          f"   n_sims {bd['meta']['n_sims']}/{fd['meta']['n_sims']}")
    print(f"  flag differences: {off or 'none'}\n")

    # Per (group, fold): the mean and max |move| in se units.
    per = defaultdict(list)
    worst = []
    for key, rb in b.items():
        rf = f.get(key)
        if rf is None or rb["se"] in (None, 0) or rb["model"] is None:
            continue
        fold, group, name = key
        z = (rf["model"] - rb["model"]) / rb["se"]
        per[(group, fold)].append(abs(z))
        worst.append((abs(z), group, fold, name, rb["model"], rf["model"],
                      rb["se"]))

    groups = sorted({g for g, _ in per})
    folds = sorted({fo for _, fo in per})
    print("  MEAN |move| IN SE UNITS, per group per fold "
          "(2026 is the negative control)\n")
    print(f"    {'group':<14}" + "".join(f"{fo:>9}" for fo in folds)
          + f"{'n rows':>9}")
    for g in groups:
        cells = []
        for fo in folds:
            v = per.get((g, fo))
            cells.append(f"{st.mean(v):>9.2f}" if v else f"{'-':>9}")
        n = len(per.get((g, folds[0]), []))
        print(f"    {g:<14}" + "".join(cells) + f"{n:>9}")

    print("\n  THE TWENTY WORST INDIVIDUAL MOVES\n")
    print(f"    {'|z|':>6}  {'fold':>4}  {'group':<12} {'key':<26}"
          f"{'broken':>10}{'fixed':>10}{'se':>9}")
    for z, g, fo, name, mb, mf, se in sorted(worst, reverse=True)[:20]:
        print(f"    {z:>6.2f}  {fo:>4}  {g:<12} {name:<26}"
              f"{mb:>10.4f}{mf:>10.4f}{se:>9.4f}")

    # The outs ladder specifically: it is what `hz_cv.py`, `hz_cv_bnd.py`
    # and `pxi_cv.py` score, so its exposure decides whether those recorded
    # numbers have to be re-run or only re-read.
    print("\n  THE OUTS LADDER, which every hook CV scores on\n")
    lines = [k for (_, g, k) in b if g == "shape" and k.startswith("outs_over")]
    print(f"    {'line':<18}" + "".join(f"{fo:>16}" for fo in folds))
    for name in sorted(set(lines)):
        cells = []
        for fo in folds:
            rb, rf = b.get((fo, "shape", name)), f.get((fo, "shape", name))
            if not rb or not rf:
                cells.append(f"{'-':>16}")
                continue
            d = rf["model"] - rb["model"]
            cells.append(f"{d:>+10.4f}{d / rb['se']:>+6.1f}")
        print(f"    {name:<18}" + "".join(cells))
    for name in ("outs_mean", "outs_sd", "k_mean"):
        cells = []
        for fo in folds:
            rb, rf = b.get((fo, "shape", name)), f.get((fo, "shape", name))
            d = rf["model"] - rb["model"]
            cells.append(f"{d:>+10.4f}{d / rb['se']:>+6.1f}")
        print(f"    {name:<18}" + "".join(cells))

    # Rule 12b's bar: the between-fold spread of the baseline cell error.
    print("\n  RULE 12b, THE BETWEEN-SEASON SPREAD OF THE BASELINE ERROR")
    print("  (all-line mean |model - actual| over the seven outs lines)\n")
    ladder = (12.5, 14.5, 15.5, 16.5, 17.5, 18.5, 20.5)
    for tag, tab in (("broken", b), ("fixed", f)):
        errs = []
        for fo in folds:
            e = [abs(tab[(fo, "shape", f"outs_over_{x}")]["gap"])
                 for x in ladder if (fo, "shape", f"outs_over_{x}") in tab]
            errs.append((fo, st.mean(e)))
        body = "  ".join(f"{fo} {v:.4f}" for fo, v in errs)
        lo, hi = min(v for _, v in errs), max(v for _, v in errs)
        print(f"    {tag:<7} {body}    spread {lo:.4f} to {hi:.4f}")


if __name__ == "__main__":
    main(sys.argv[1:])
