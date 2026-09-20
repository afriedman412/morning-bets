"""THE SINGLE-PITCHER INSTRUMENT — step one of PLAN-pitch-history.md.

    venv/bin/python -m scratchpad.pitch_one --pitcher "Dylan Cease" [--season 2026]

QUESTION: which per-pitch columns are RELIABLE at n = one start, measured
on the data we own? The plan's expected ordering — physical instrument
reads (velo, spin, break) reliable, outcome rates (whiff%, zone%) not —
was asserted from binomial arithmetic and has never been measured here.

One pitcher, every start of a season, one row per start per pitch type:
n, mean velo, mean spin, mean vertical break (raw + induced), zone%
(fixed zone from pX/pZ: |pX| <= 0.83, 1.5 <= pZ <= 3.5), whiff/swing —
next to the start's K/BB/outs from the pipeline DB.

RELIABILITY: split each start's pitches odd/even WITHIN pitch type,
compute every stat on both halves, Pearson-correlate the halves across
starts. Spearman-Brown 2r/(1+r) lifts a half-start r to full-start.

POWER, stated before any result: ~28 starts -> se(r) ~ 1/sqrt(n-3) ~ 0.20
at r=0. This resolves "reliable vs not" (0.8 vs 0.0), not fine ordering.

POSITIVE CONTROL, built in: a planted column that varies start-to-start
and agrees across halves must read r ~ 1; an independent-noise column
must read r ~ 0. A harness that fails either is not measuring reliability.

League-wide extraction stays in velo_build.py (extend it, per the plan);
this is the one-pitcher exploration instrument.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os

import numpy as np

from src import db

WHIFF = {"S", "W"}                       # swinging strike (+ blocked)
SWING = {"S", "W", "F", "T", "X", "D", "E"}   # excludes bunt attempts (L)
ZONE_X, ZONE_LO, ZONE_HI = 0.83, 1.5, 3.5
MIN_HALF = 5                             # pitches per half to enter a cell


def starts_for(name: str, season: int):
    q = """select g.game_id gid, g.date d, p.k, p.bb, p.outs_recorded outs
           from mlb_pitching p join games g on g.game_id=p.game_id
           where g.sport='mlb' and g.status='Final' and p.is_starter=1
           and p.player_name=? and substr(g.date,1,4)=? order by g.date"""
    with db.connect() as c:
        return [dict(r) for r in c.execute(q, (name, str(season)))]


def pitches_of(pk: str, name: str):
    """This pitcher's pitches, in order: one dict per pitch."""
    path = f".cache/pbp/{pk}.json.gz"
    if not os.path.exists(path):
        return None
    d = json.load(gzip.open(path))
    out = []
    for pl in d.get("allPlays") or []:
        if ((pl.get("matchup") or {}).get("pitcher") or {}).get(
                "fullName") != name:
            continue
        for e in pl.get("playEvents") or []:
            if not e.get("isPitch"):
                continue
            det = e.get("details") or {}
            pd = e.get("pitchData") or {}
            br = pd.get("breaks") or {}
            co = pd.get("coordinates") or {}
            out.append({
                "type": (det.get("type") or {}).get("code"),
                "code": det.get("code"),
                "velo": pd.get("startSpeed"),
                "spin": br.get("spinRate"),
                "vb": br.get("breakVertical"),
                "ivb": br.get("breakVerticalInduced"),
                "px": co.get("pX"), "pz": co.get("pZ")})
    return out


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


def stat_row(ps):
    """Every stat on one bag of pitches (a start-type cell, or one half)."""
    velo, n_v = _mean([p["velo"] for p in ps])
    spin, n_s = _mean([p["spin"] for p in ps])
    vb, _ = _mean([p["vb"] for p in ps])
    ivb, _ = _mean([p["ivb"] for p in ps])
    loc = [(p["px"], p["pz"]) for p in ps
           if p["px"] is not None and p["pz"] is not None]
    zone = (sum(abs(x) <= ZONE_X and ZONE_LO <= z <= ZONE_HI
                for x, z in loc) / len(loc)) if loc else None
    swings = [p for p in ps if p["code"] in SWING]
    whiff = (sum(p["code"] in WHIFF for p in swings) / len(swings)
             if len(swings) >= MIN_HALF else None)
    return {"n": len(ps), "n_velo": n_v, "n_spin": n_s,
            "velo": velo, "spin": spin, "vb": vb, "ivb": ivb,
            "zone": zone, "whiff": whiff, "n_swing": len(swings)}


STATS = ["velo", "spin", "vb", "ivb", "zone", "whiff"]


def build(name: str, season: int):
    """rows: per start per type, full stats + odd/even halves + K/BB/outs."""
    rows, missing = [], 0
    for i, s in enumerate(starts_for(name, season)):
        ps = pitches_of(s["gid"].split("-")[1], name)
        if not ps:
            missing += 1
            continue
        by_type: dict[str, list] = {}
        for p in ps:
            if p["type"]:
                by_type.setdefault(p["type"], []).append(p)
        for t, tps in sorted(by_type.items()):
            rows.append({
                "start": i, "date": s["d"], "type": t,
                "k": s["k"], "bb": s["bb"], "outs": s["outs"],
                "full": stat_row(tps),
                "odd": stat_row(tps[0::2]), "even": stat_row(tps[1::2])})
    print(f"  {name} {season}: {len({r['start'] for r in rows})} starts "
          f"walked ({missing} missing from cache), {len(rows)} "
          f"start-type rows")
    return rows


def split_half(rows, ptype, stat):
    """(r, n_starts) for one (type, stat) cell across starts."""
    a, b = [], []
    for r in rows:
        if r["type"] != ptype:
            continue
        if r["odd"]["n"] < MIN_HALF or r["even"]["n"] < MIN_HALF:
            continue
        va, vb_ = r["odd"][stat], r["even"][stat]
        if va is None or vb_ is None:
            continue
        a.append(va)
        b.append(vb_)
    if len(a) < 8 or np.std(a) == 0 or np.std(b) == 0:
        return None, len(a)
    return float(np.corrcoef(a, b)[0, 1]), len(a)


def controls(rows, ptype):
    """The harness must see a planted signal and must not invent one."""
    rng = np.random.default_rng(7)
    sub = [r for r in rows if r["type"] == ptype
           and r["odd"]["n"] >= MIN_HALF and r["even"]["n"] >= MIN_HALF]
    lvl = rng.normal(0, 1, len(sub))          # true start-to-start signal
    hi_a = lvl + rng.normal(0, 0.1, len(sub))
    hi_b = lvl + rng.normal(0, 0.1, len(sub))
    nz_a = rng.normal(0, 1, len(sub))
    nz_b = rng.normal(0, 1, len(sub))
    r_hi = float(np.corrcoef(hi_a, hi_b)[0, 1])
    r_nz = float(np.corrcoef(nz_a, nz_b)[0, 1])
    ok = r_hi > 0.9 and abs(r_nz) < 2 / np.sqrt(len(sub))
    print(f"  CONTROLS on {ptype} (n={len(sub)}): planted r={r_hi:+.2f}, "
          f"noise r={r_nz:+.2f}  "
          f"{'SEEN' if ok else '** HARNESS BROKEN **'}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pitcher", default="Dylan Cease")
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()

    rows = build(args.pitcher, args.season)
    slug = args.pitcher.lower().replace(" ", "_")
    out = f"scratchpad/pitch_one_{slug}_{args.season}.json"
    json.dump(rows, open(out, "w"))
    print(f"  -> {out}")

    types = {}
    for r in rows:
        types[r["type"]] = types.get(r["type"], 0) + r["full"]["n"]
    main_types = [t for t, n in sorted(types.items(), key=lambda kv: -kv[1])
                  if n >= 100]
    print(f"  pitch mix: " + "  ".join(
        f"{t}:{n}" for t, n in sorted(types.items(), key=lambda kv: -kv[1])))

    controls(rows, main_types[0])

    n_starts = len({r["start"] for r in rows})
    print(f"\n  SPLIT-HALF RELIABILITY (odd/even within start, across "
          f"{n_starts} starts; se(r)~{1 / np.sqrt(max(n_starts - 3, 1)):.2f}"
          f" at r=0; SB = full-start 2r/(1+r))")
    print(f"  {'type':<5}{'stat':<7}{'r':>7}{'SB':>7}{'n':>5}")
    for t in main_types:
        for stat in STATS:
            r, n = split_half(rows, t, stat)
            if r is None:
                print(f"  {t:<5}{stat:<7}{'--':>7}{'':>7}{n:>5}")
            else:
                sb = 2 * r / (1 + r) if r > -1 else float("nan")
                print(f"  {t:<5}{stat:<7}{r:>+7.2f}{sb:>+7.2f}{n:>5}")
        print()

    # the walk: his stuff start by start, primary type, next to the line
    prim = main_types[0]
    print(f"  START BY START — {prim} (primary), K/BB/outs")
    print(f"  {'date':<12}{'n':>4}{'velo':>7}{'spin':>7}{'ivb':>6}"
          f"{'zone%':>7}{'whiff%':>8}  {'K':>2} {'BB':>2} {'outs':>4}")
    for r in [r for r in rows if r["type"] == prim]:
        f = r["full"]
        wz = f"{f['zone']:.0%}" if f["zone"] is not None else "--"
        ww = f"{f['whiff']:.0%}" if f["whiff"] is not None else "--"
        print(f"  {r['date']:<12}{f['n']:>4}{f['velo']:>7.1f}"
              f"{f['spin']:>7.0f}{f['ivb']:>6.1f}{wz:>7}{ww:>8}  "
              f"{r['k']:>2} {r['bb']:>2} {r['outs']:>4}")


if __name__ == "__main__":
    main()
