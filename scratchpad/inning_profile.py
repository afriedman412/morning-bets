"""Exit-inning profile from a persisted dump. Model against real.

    venv/bin/python -m scratchpad.inning_profile [DUMP.json ...]

QUESTION    Is the fourth-inning over-pull the SAME defect as the pitch
            backbone's over-pull between 60 and 85 pitches? 60-85 pitches is
            the fourth and fifth innings and the fourth-inning excess sits
            at 45-75, so the ranges overlap. If they are one defect, the
            counted pitch hazard should close the fourth inning.

TEST        The exit-inning profile from each dump, side by side. Real side
            is the boxscore out count mapped to an exit inning — the same
            rule for every dump, so the comparison BETWEEN dumps is clean
            even though the rule mislabels a starter chased in a new inning
            (7.8% of real starts; `bnd_rulers.py`). Absolute gaps here are
            therefore not the four-season figures and are not comparable to
            them; the DIFFERENCE between dumps is what this is for.
"""
from __future__ import annotations

import json
import sys
from collections import Counter

MAXI = 9


def profile(path):
    d = json.load(open(path))
    c = {k: i for i, k in enumerate(d["cols"])}
    rows = d["rows"]
    mc, n = Counter(), 0
    for r in rows:
        n += 1
        mc[min(r[c["exit_inning"]], MAXI)] += 1
    real = {}
    for r in rows:
        if r[c["real_outs"]] is not None:
            real[(r[c["pitcher"]], r[c["game_id"]])] = r[c["real_outs"]]
    rc, rn = Counter(), 0
    for o in real.values():
        rn += 1
        rc[min(o // 3 + (0 if o % 3 == 0 else 1), MAXI)] += 1
    return mc, n, rc, rn, d


def main(argv):
    paths = argv or ["scratchpad/starts_holdout.json",
                     "scratchpad/starts_holdout_hz.json"]
    got = [(p, profile(p)) for p in paths]
    names = [p.split("/")[-1].replace("starts_holdout", "").replace(
        ".json", "").strip("_") or "shipped" for p, _ in got]
    print(f"  exit-inning profile, share of ALL starts\n")
    print(f"  {'inning':<8}{'real':>9}" + "".join(f"{n:>12}" for n in names)
          + "".join(f"{'gap ' + n:>12}" for n in names))
    tot = {n: 0.0 for n in names}
    _, (_, (_, _, rc0, rn0, _)) = 0, got[0]
    for i in range(2, MAXI + 1):
        r = rc0[i] / rn0
        cells = []
        gaps = []
        for (p, (mc, n, _rc, _rn, _d)), nm in zip(got, names):
            m = mc[i] / n
            cells.append(f"{m:>12.3f}")
            gaps.append(f"{m - r:>+12.3f}")
            tot[nm] += abs(m - r)
        print(f"  {i:<8}{r:>9.3f}" + "".join(cells) + "".join(gaps))
    print()
    for nm in names:
        print(f"  mean |gap| {nm:<12} {tot[nm]/(MAXI-1):.4f}")


if __name__ == "__main__":
    main(sys.argv[1:])
