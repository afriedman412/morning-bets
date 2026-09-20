"""Per-start pitch-physics columns, extracted from the pbp cache.

    venv/bin/python -m scratchpad.velo_build

One row per (game, starter). Original columns unchanged (`velo`, `n_fb`:
mean startSpeed over FF/SI — streaks.py reads these). Extended 2026-09-07
for PLAN-pitch-history step two with the columns the single-pitcher
reliability table (pitch_one.py) admitted: per-type n / mean velo / mean
spin / mean induced vertical break under `types`, and a fixed-zone
location count (`n_loc`, `n_zone`; |pX| <= 0.83, 1.5 <= pZ <= 3.5).
Whiff is deliberately NOT extracted — split-half r ~ 0 at n = 1 start.

Starters identified positionally — the first pitcher in the top of the
1st is the HOME starter, bottom of the 1st the AWAY starter. Output
`scratchpad/velo_starts.json`; coverage printed BEFORE anyone reads a
result off it (rule: print the coverage of any lookup).
"""
from __future__ import annotations

import glob
import gzip
import json
import multiprocessing as mp

FB = {"FF", "SI"}
OUT = "scratchpad/velo_starts.json"
MIN_TYPE = 5                    # pitches for a start-type cell to be kept
ZONE_X, ZONE_LO, ZONE_HI = 0.83, 1.5, 3.5


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
    acc = {}                        # name -> {type: [n, sum_v, sum_s, sum_b,
    loc = {}                        # name -> [n_loc, n_zone]   n_s, n_b]}
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
            pd = ev.get("pitchData") or {}
            sp = pd.get("startSpeed")
            if not (code and sp):
                continue
            br = pd.get("breaks") or {}
            co = pd.get("coordinates") or {}
            a = acc.setdefault(name, {}).setdefault(code,
                                                    [0, 0.0, 0.0, 0.0, 0, 0])
            a[0] += 1
            a[1] += sp
            if br.get("spinRate"):
                a[2] += br["spinRate"]
                a[4] += 1
            if br.get("breakVerticalInduced") is not None:
                a[3] += br["breakVerticalInduced"]
                a[5] += 1
            px, pz = co.get("pX"), co.get("pZ")
            if px is not None and pz is not None:
                z = loc.setdefault(name, [0, 0])
                z[0] += 1
                z[1] += abs(px) <= ZONE_X and ZONE_LO <= pz <= ZONE_HI
    rows = []
    for name, types in acc.items():
        fb_n = sum(t[0] for c, t in types.items() if c in FB)
        if fb_n < 10:
            continue
        fb_v = sum(t[1] for c, t in types.items() if c in FB) / fb_n
        n_loc, n_zone = loc.get(name, [0, 0])
        rows.append({
            "pk": pk, "name": name, "velo": fb_v, "n_fb": fb_n,
            "n_loc": n_loc, "n_zone": n_zone,
            "types": {c: {"n": t[0], "velo": t[1] / t[0],
                          "spin": t[2] / t[4] if t[4] else None,
                          "ivb": t[3] / t[5] if t[5] else None}
                      for c, t in types.items() if t[0] >= MIN_TYPE}})
    return rows


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
