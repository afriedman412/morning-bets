"""Per-start whiff/swing + K/BF for every starter, from the pbp cache.

Whiff was excluded from velo_build because split-half r ~ 0 at n = ONE
start. That is a different question from the one here: over a FIVE-start
sample, does whiff carry signal about the NEXT starts that the observed
strikeout rate does not already carry? Extract first, screen in
whiff_test.py.

    venv/bin/python -m scratchpad.whiff_build
"""
from __future__ import annotations

import glob
import gzip
import json
import multiprocessing as mp

OUT = "scratchpad/whiff_starts.json"
WHIFF = {"S", "W"}
SWING = {"S", "W", "F", "T", "X", "D", "E"}
K_EVENTS = {"strikeout", "strikeout_double_play"}


def one(path: str):
    try:
        d = json.load(gzip.open(path))
    except Exception:
        return None
    plays = (d.get("allPlays")
             or (d.get("liveData") or {}).get("plays", {}).get("allPlays")
             or [])
    if not plays:
        return None
    pk = path.split("/")[-1].split(".")[0]
    first, acc = {}, {}
    for p in plays:
        m = (p.get("matchup") or {}).get("pitcher") or {}
        name = m.get("fullName")
        if not name:
            continue
        top = (p.get("about") or {}).get("isTopInning")
        side = "home" if top else "away"
        first.setdefault(side, name)
        if first[side] != name:
            continue
        a = acc.setdefault(name, {"bf": 0, "k": 0, "sw": 0, "wh": 0, "np": 0})
        ev_type = (p.get("result") or {}).get("eventType") or ""
        a["bf"] += 1
        a["k"] += ev_type in K_EVENTS
        for ev in p.get("playEvents") or []:
            if not ev.get("isPitch"):
                continue
            code = ((ev.get("details") or {}).get("call") or {}).get("code")
            a["np"] += 1
            if code in SWING:
                a["sw"] += 1
            if code in WHIFF:
                a["wh"] += 1
    return [dict(pk=pk, name=n, **v) for n, v in acc.items() if v["bf"] >= 5]


def main():
    files = sorted(glob.glob(".cache/pbp/*.json.gz"))
    print(f"  {len(files)} cached games")
    with mp.get_context("fork").Pool(max(mp.cpu_count() - 1, 1)) as pool:
        got = pool.map(one, files, chunksize=64)
    rows = [r for g in got if g for r in g]
    json.dump(rows, open(OUT, "w"))
    sw = sum(r["sw"] for r in rows)
    wh = sum(r["wh"] for r in rows)
    print(f"  {len(rows)} starter-start rows -> {OUT}")
    print(f"  league whiff/swing {wh / sw:.4f}  (sanity: MLB ~0.24-0.25)")
    print(f"  league K/BF {sum(r['k'] for r in rows) / sum(r['bf'] for r in rows):.4f}")


if __name__ == "__main__":
    main()
