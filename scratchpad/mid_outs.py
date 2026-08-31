"""DOES THE OUT COUNT IN THE INNING CHANGE A MID-INNING PULL? Counted.

    venv/bin/python -m scratchpad.mid_outs

QUESTION. `boundary.MID_FEATURES` lists `outs_before` as a mid-inning
feature and `sim.mid_removal_p` does not take it. `Frame` carries `outs`
separately from `damage`, `runs` and `br`, so with two down and nobody on
every value the hook receives is identical to nobody out and nobody on. Does
a real manager treat those the same?

HYPOTHESIS. He does not: with two outs he lets the starter get the last one
and walk off, so the mid-inning hazard FALLS as outs rise. If so the model's
mid curve fires with equal force exactly where reality hesitates, which is a
mechanism for the mid curve beating the boundary curve to the punch and for
the boundary share sitting at 0.616 against a real 0.674.

TEST. Per-plate-appearance mid-inning removal hazard by `outs_before`,
counted on `boundary.decisions` rows. Mid-inning rows only — `ends_inning`
excludes the plate appearance that ends the frame, which is a BOUNDARY
decision and a different curve.

CONFOUND, AND IT IS THE WHOLE REASON FOR THE SECOND TABLE. Outs correlate
with everything else in the inning: two outs means more batters have come
up, so more pitches and more chances for damage. A raw hazard by out count
therefore measures workload as much as it measures the manager. So the same
count is repeated INSIDE pitch and inning-damage cells; if the effect
survives there it is not the confound.

TRAIN ROWS ONLY (`date < HOLDOUT_CUT`). This feeds a coefficient.
"""
from __future__ import annotations

import json
from collections import defaultdict

ROWS = "/tmp/hook_rows.json"
HOLDOUT_CUT = "2026-07-01"
PITCH_BANDS = ((0, 60), (60, 78), (78, 90), (90, 200))


def load():
    with open(ROWS) as f:
        rows = json.load(f)
    train = [r for r in rows if (r.get("date") or "9") < HOLDOUT_CUT]
    mid = [r for r in train if not r.get("ends_inning")]
    return rows, train, mid


def rate(rows):
    n = len(rows)
    return (sum(1 for r in rows if r.get("removed")) / n if n else 0.0), n


def se(p, n):
    return (p * (1 - p) / n) ** 0.5 if n else 0.0


def table(rows, label):
    by = defaultdict(list)
    for r in rows:
        o = r.get("outs_before")
        if o in (0, 1, 2):
            by[o].append(r)
    print(f"  {label}")
    print(f"    {'outs':<6}{'n':>10}{'pull rate':>12}{'se':>9}")
    got = {}
    for o in (0, 1, 2):
        p, n = rate(by[o])
        got[o] = (p, n)
        print(f"    {o:<6}{n:>10,}{p:>12.4f}{se(p, n):>9.4f}")
    if got[0][1] and got[2][1]:
        d = got[2][0] - got[0][0]
        s = (se(*got[0]) ** 2 + se(*got[2]) ** 2) ** 0.5
        print(f"    2 minus 0: {d:+.4f}  ({d / s:+.1f} sigma)"
              if s else "")
    return got


def main():
    rows, train, mid = load()
    print(f"  {len(rows):,} decisions, {len(train):,} train "
          f"(date < {HOLDOUT_CUT}), {len(mid):,} mid-inning\n")
    table(mid, "POOLED — every mid-inning decision")
    print("\n  INSIDE PITCH BANDS — the confound control. Outs rise with")
    print("  workload, so a pooled effect could be pitch count wearing a")
    print("  disguise. It is not one if it survives here.\n")
    for lo, hi in PITCH_BANDS:
        band = [r for r in mid if lo <= (r.get("pitches") or 0) < hi]
        table(band, f"{lo}-{hi} pitches")
        print()
    print("  INSIDE INNING DAMAGE — a rally brings both outs and hooks.\n")
    for lo, hi in ((0.0, 0.01), (0.01, 2.0), (2.0, 99.0)):
        band = [r for r in mid if lo <= (r.get("inn_dmg") or 0.0) < hi]
        table(band, f"inning damage {lo}-{hi}")
        print()


if __name__ == "__main__":
    main()
