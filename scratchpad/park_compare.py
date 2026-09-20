"""ITEM 1'S VERDICT TABLE: off / raw / neutralised park, per fold.

    venv/bin/python -m scratchpad.park_compare

Reads every `scratchpad/battery_*.json`, classifies each run by the flags
its meta recorded (off / raw / neutralised), and prints the three numbers
the pre-registered falsifier is decided on:

  * the sample-weighted mean |per-venue residual|, full and F5, per fold —
    "neutralised does not reduce it in at least three of four folds" kills
  * the league ladder per fold — "moves by more than one se" kills
  * the named venues from the PREDICTION: Coors (19) largest correction
    on; Oracle (2395), Petco (2680), T-Mobile (680) move the other way

No simulation here — this only reads what the battery already measured.
"""
from __future__ import annotations

import glob
import json

NAMED = {"19": "Coors", "2395": "Oracle", "2680": "Petco",
         "680": "T-Mobile"}


def config_of(meta) -> str | None:
    f = meta.get("flags", {})
    if meta.get("dev") or meta.get("maim"):
        return None
    park, neut = f.get("calibrate.USE_PARK"), f.get("calibrate.NEUTRALISE_PARK")
    if not park:
        return "off"
    return "neut" if neut else "raw"


def main():
    runs: dict[str, dict] = {}
    for p in sorted(glob.glob("scratchpad/battery_*.json")):
        d = json.load(open(p))
        cfg = config_of(d.get("meta", {}))
        if cfg:
            runs[cfg] = d          # newest of each config wins
    missing = {"off", "raw", "neut"} - set(runs)
    if missing:
        print(f"  missing configs: {missing}")
        return
    rows = {cfg: {(r["fold"], r["group"], r["key"]): r for r in d["rows"]}
            for cfg, d in runs.items()}
    folds = sorted({r["fold"] for r in runs["off"]["rows"]})

    for view in ("venue_full", "venue_f5"):
        print(f"\n  WEIGHTED MEAN |PER-VENUE RESIDUAL| — {view}")
        print(f"    {'fold':<7}{'off':>9}{'raw':>9}{'neut':>9}"
              f"{'neut-off':>10}  verdict")
        wins = 0
        for f in folds:
            k = (f, view, "wmean_abs_resid")
            o, r, n = (rows[c][k]["model"] for c in ("off", "raw", "neut"))
            better = n < o
            wins += better
            print(f"    {f:<7}{o:>9.4f}{r:>9.4f}{n:>9.4f}{n - o:>+10.4f}"
                  f"  {'improved' if better else 'WORSE'}")
        print(f"    -> neutralised improves {wins}/{len(folds)} folds "
              f"(falsifier needs >= 3)")

    print("\n  LADDER CONTROL — gap off vs neut, flagged past one se")
    print(f"    {'fold':<7}{'prefix':<8}{'off':>9}{'neut':>9}"
          f"{'moved':>9}{'se':>8}")
    for f in folds:
        for p in ("F1", "F3", "F5", "F7"):
            k = (f, "ladder", p)
            o, n = rows["off"][k], rows["neut"][k]
            moved = n["gap"] - o["gap"]
            flag = "  <<" if abs(moved) > (o["se"] or 9e9) else ""
            print(f"    {f:<7}{p:<8}{o['gap']:>+9.4f}{n['gap']:>+9.4f}"
                  f"{moved:>+9.4f}{o['se']:>8.4f}{flag}")

    print("\n  NAMED VENUES (prediction) — full-game residual, model-real")
    print(f"    {'venue':<10}{'fold':<7}{'off':>9}{'raw':>9}{'neut':>9}"
          f"{'se':>8}")
    for vid, nm in NAMED.items():
        for f in folds:
            k = (f, "venue_full", vid)
            if any(k not in rows[c] for c in ("off", "raw", "neut")):
                continue
            o, r, n = (rows[c][k] for c in ("off", "raw", "neut"))
            print(f"    {nm:<10}{f:<7}{o['model']:>+9.4f}{r['model']:>+9.4f}"
                  f"{n['model']:>+9.4f}{o['se']:>8.4f}")


if __name__ == "__main__":
    main()
