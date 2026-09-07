"""Per-start fastball velocity, extracted from the pbp cache.

    venv/bin/python -m scratchpad.velo_build

One row per (game, starter): mean startSpeed over four-seamers and sinkers
(FF/SI), n pitches. Starters identified positionally — the first pitcher in
the top of the 1st is the HOME starter, bottom of the 1st the AWAY starter.
Output `scratchpad/velo_starts.json`; coverage printed BEFORE anyone reads
a result off it (rule: print the coverage of any lookup).
"""
from __future__ import annotations

import glob
import gzip
import json
import multiprocessing as mp

FB = {"FF", "SI"}
OUT = "scratchpad/velo_starts.json"


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
    first = {}                      # side -> starter name
    acc = {}                        # (name) -> [sum, n]  (starters only)
    for p in plays:
        m = (p.get("matchup") or {}).get("pitcher") or {}
        name = m.get("fullName")
        if not name:
            continue
        top = (p.get("about") or {}).get("isTopInning")
        side = "home" if top else "away"       # top: home club pitches
        first.setdefault(side, name)
        if first[side] != name:
            continue
        for ev in p.get("playEvents") or []:
            if not ev.get("isPitch"):
                continue
            code = ((ev.get("details") or {}).get("type") or {}).get("code")
            sp = (ev.get("pitchData") or {}).get("startSpeed")
            if code in FB and sp:
                a = acc.setdefault(name, [0.0, 0])
                a[0] += sp
                a[1] += 1
    return [{"pk": pk, "name": n, "velo": s / c, "n_fb": c}
            for n, (s, c) in acc.items() if c >= 10]


def main():
    files = sorted(glob.glob(".cache/pbp/*.json.gz"))
    print(f"  {len(files)} cached games")
    with mp.get_context("fork").Pool(max(mp.cpu_count() - 1, 1)) as pool:
        got = pool.map(one, files, chunksize=64)
    rows = [r for g in got if g for r in g]
    empty = sum(1 for g in got if not g)
    json.dump(rows, open(OUT, "w"))
    print(f"  {len(rows)} starter-start velo rows "
          f"({empty} games yielded none)  -> {OUT}")


if __name__ == "__main__":
    main()
