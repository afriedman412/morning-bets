"""Score the half-life sweep against the registered falsifier.

    venv/bin/python -m scratchpad.hl_score

Reads each `hl_sweep_<hl>.log` for the battery JSON it saved, then compares
every candidate to the flag-off run (hl=0) on the pre-registered rows:

  * K shape   — k_mean, k_sd, k_9_plus_share
  * outs shape — outs_mean, outs_sd, outs_over_*, spike_*_share
  * run level — the ladder (F1/F3/F5/F7), which must sit within 1 se
  * everything else — count of rows that moved PAST 1 se, either way

The falsifier, registered before the sweep ran: a half-life ships only if
K and outs shape improve on the CLEAN 2026 fold and in >= 3 of 4 folds,
the ladder holds within 1 se everywhere, no unrelated group worsens past
1 se unexplained, and the winner is not at the grid edge (rule 8).
"""
from __future__ import annotations

import json
import re

CANDIDATES = (0, 30, 60, 90, 150)
K_ROWS = ("k_mean", "k_sd", "k_9_plus_share")


def fp_of(hl: int) -> str:
    txt = open(f"scratchpad/hl_sweep_{hl}.log").read()
    m = re.findall(r"battery_([0-9a-f]{12})\.json", txt)
    if not m:
        raise SystemExit(f"no battery JSON recorded in hl_sweep_{hl}.log")
    return m[-1]


def rows_of(hl: int):
    d = json.load(open(f"scratchpad/battery_{fp_of(hl)}.json"))
    assert d["meta"]["flags"].get("rates.HALF_LIFE_DAYS") == (hl or None), \
        (hl, d["meta"]["flags"].get("rates.HALF_LIFE_DAYS"))
    return d["rows"]


def classify(r) -> str:
    if r["group"] == "ladder":
        return "ladder"
    if r["group"] != "shape":
        return "other"
    k = r["key"]
    if k in K_ROWS:
        return "k"
    if k.startswith(("outs_", "spike_")):
        return "outs"
    return "other"


def main():
    base = {(r["fold"], r["group"], r["key"]): r for r in rows_of(0)}
    folds = sorted({f for f, _g, _k in base})
    print(f"  folds {folds}; every number is sum|gap| vs actual, "
          f"and (delta) vs flag-off\n")
    for fam in ("k", "outs", "ladder"):
        print(f"  {fam.upper()}")
        hdr = "  " + f"{'hl':>6}" + "".join(f"{f:>16}" for f in folds)
        print(hdr)
        for hl in CANDIDATES:
            rows = {(r["fold"], r["group"], r["key"]): r for r in rows_of(hl)}
            line = f"  {hl:>6}"
            for f in folds:
                tot = sum(abs(r["gap"]) for (fo, _g, _k), r in rows.items()
                          if fo == f and classify(r) == fam)
                b = sum(abs(r["gap"]) for (fo, _g, _k), r in base.items()
                        if fo == f and classify(r) == fam)
                line += f"{tot:>8.3f} ({tot - b:+.3f})"
            print(line)
        print()
    # the guard rows: ladder must hold within 1 se, and nothing unrelated
    # may move past 1 se without a name
    print("  ROWS PAST 1 SE vs flag-off (any group), per candidate:")
    for hl in CANDIDATES[1:]:
        rows = {(r["fold"], r["group"], r["key"]): r for r in rows_of(hl)}
        moved = []
        for key, r in rows.items():
            b = base.get(key)
            if not b or not r["se"]:
                continue
            d = abs(r["gap"]) - abs(b["gap"])
            if abs(r["model"] - b["model"]) > r["se"]:
                moved.append((key, d))
        worse = [m for m in moved if m[1] > 0]
        better = [m for m in moved if m[1] <= 0]
        print(f"    hl={hl}: {len(moved)} moved past 1 se "
              f"({len(better)} toward real, {len(worse)} away)")
        for (f, g, k), d in sorted(worse, key=lambda x: -x[1])[:8]:
            print(f"      AWAY  {f} {g}.{k}  |gap| {d:+.4f}")


if __name__ == "__main__":
    main()
