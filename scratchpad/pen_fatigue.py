"""DOES A TIRED RELIEVER PITCH WORSE? Within-pitcher, paired.

    venv/bin/python -m scratchpad.pen_fatigue [--control]

WHAT WAS ALREADY TRIED, so this is not a re-run. "Bullpen availability" sat
on the dead list as a rejected import (z <= 1.4 under four proxies), then
came back legitimately as a HOOK feature and shipped: `sim.USE_PEN_STATE`
puts two CLUB-level columns on both removal curves, so a depleted pen makes
the manager leave his STARTER in longer. That is a decision model. It says
nothing about whether the ARM that finally comes in is worse for the work,
and the engine currently says he is not — `build_side` redraws the pen every
game AND every draw, so no simulated reliever has ever thrown a pitch
before (`NOTES-context-layer.md`, "THE BULLPEN IS DRAWN, NOT DEPLOYED").

QUESTION. Is per-arm workload a RATE effect, a SELECTION effect, or
neither?

DESIGN. Paired within pitcher, the same posture as the starter/reliever
role difference: split each arm's own outings by days since his last
appearance and compare him to himself, so talent, club and season all
cancel. Batter-weighted inside each side so a one-batter outing does not
count as much as a full inning. Training rows only.

POSITIVE CONTROL, because a mis-specified harness and an absent effect look
identical and this project has accepted five nulls in a row that were a
specification error. `--control` removes a known `INJECT` of K% from the
back-to-back rows and re-runs. It comes back at -4.9 sigma but ATTENUATED
to about two thirds, because a short outing with no strikeout clips at
zero — so read the power as "this sees about one point of K%", not two.

RESULT 2026-09-09: null on every channel. Fatigue as a RATE effect is dead;
fatigue as AVAILABILITY is alive and lives in `closer_slot.py`, where the
same closer takes the save slot 65.0% rested against 58.7% having pitched
the day before.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date as _date

from src import db
from src.context import store
from src.context.holdout import HOLDOUT

#: The injected effect for `--control`, in K% per batter faced, at the size
#: a mechanism would need to be worth wiring.
INJECT = 0.020

#: A gap longer than this is a different animal — a return from the IL, not
#: a rested arm — and it would be measuring roster moves.
MAX_GAP = 30


def _days(a: str, b: str) -> int:
    return (_date(*(int(x) for x in a.split("-")))
            - _date(*(int(x) for x in b.split("-")))).days


def load(conn=None):
    with store.connect() as c:
        st = [dict(r) for r in c.execute(
            "select game_id, date, player_name nm, batters, outs_recorded o"
            " from mlb_stints where appearance_order > 0 order by date")]
    with db.connect() as c:
        line = {(r["game_id"], r["player_name"]): dict(r) for r in c.execute(
            "select game_id, player_name, k, bb, hr, h from mlb_pitching"
            " where is_starter = 0")}
    return st, line


def build(st, line, control: bool) -> list[dict]:
    seen = defaultdict(list)
    for r in st:
        seen[r["nm"]].append(r["date"])
    seen = {k: sorted(set(v)) for k, v in seen.items()}

    rows = []
    for r in st:
        ln = line.get((r["game_id"], r["nm"]))
        if not ln or not r["batters"]:
            continue
        ds = seen[r["nm"]]
        i = ds.index(r["date"])
        if i == 0:
            continue
        gap = _days(r["date"], ds[i - 1])
        if gap > MAX_GAP:
            continue
        bf = r["batters"]
        k = (ln["k"] or 0) / bf
        if control and gap <= 1:
            k = max(k - INJECT, 0.0)
        rows.append({
            "nm": r["nm"], "date": r["date"], "gap": gap, "bf": bf, "k": k,
            "heavy": i >= 2 and _days(r["date"], ds[i - 2]) <= 3,
            "bb": (ln["bb"] or 0) / bf, "hr": (ln["hr"] or 0) / bf,
            "h": (ln["h"] or 0) / bf, "o": (r["o"] or 0) / bf,
        })
    return rows


def paired(rows, split, lo_lbl, hi_lbl, minn=10) -> None:
    by = defaultdict(lambda: ([], []))
    for r in rows:
        by[r["nm"]][1 if split(r) else 0].append(r)
    out = defaultdict(list)
    n = 0
    for a, b in by.values():
        if len(a) < minn or len(b) < minn:
            continue
        n += 1
        for stat in ("k", "bb", "hr", "h", "o"):
            wa = sum(r["bf"] for r in a)
            wb = sum(r["bf"] for r in b)
            out[stat].append(sum(r[stat] * r["bf"] for r in b) / wb
                             - sum(r[stat] * r["bf"] for r in a) / wa)
    print(f"\n  {hi_lbl} MINUS {lo_lbl} — {n} arms with {minn}+ of each")
    for stat in ("k", "bb", "hr", "h", "o"):
        v = out[stat]
        if not v:
            continue
        m = sum(v) / len(v)
        var = sum((x - m) ** 2 for x in v) / (len(v) - 1)
        se = (var / len(v)) ** 0.5
        flag = "  <-" if abs(m) > 2 * se else ""
        print(f"    {stat:<4} {m:+.5f}   se {se:.5f}   "
              f"{m / se:+5.1f} sigma{flag}")


def main() -> None:
    control = "--control" in sys.argv
    st, line = load()
    if not st:
        print("no stints — run `... sources.pbp --backfill --sync` first")
        return
    rows = build(st, line, control)
    train = [r for r in rows if r["date"] < HOLDOUT]
    print(f"{len(rows):,} relief outings with a line and a prior appearance;"
          f" {len(train):,} before the {HOLDOUT} cutoff")
    if control:
        print(f"*** POSITIVE CONTROL: {INJECT:.3f} K% removed from the"
              f" back-to-back rows")
    paired(train, lambda r: r["gap"] <= 1, "2+ days rest", "pitched yesterday")
    paired(train, lambda r: r["heavy"], "not", "3 apps in 4 days", minn=5)


if __name__ == "__main__":
    main()
