"""E1 — THE BATTER RUNG, and the test that decides what the residual is.

    venv/bin/python -m scratchpad.pitch_e1 --build
    venv/bin/python -m scratchpad.pitch_e1              inspect the table

THE FINDING THIS EXISTS TO EXPLAIN (expect_league, 2026-09-07): the
RESIDUAL — actual whiffs minus what E0 says his pitches deserved —
repeats within a start at r +0.143 against a negative-control baseline of
-0.003, on 17,762 starts. The plan predicted noise. It is not noise.

BUT A REPEATABLE RESIDUAL IS NOT YET A PITCHER TRAIT, and the leading
alternative is mundane: E0 CARRIES NO BATTER. Both halves of a start face
the same nine men, so if tonight's lineup swings and misses more than the
league does, both halves inherit it and the residual correlates — with no
latent pitcher state involved at all. That channel is ALREADY in the
engine (log5 against the specific nine), so it would be worth nothing new.

THE DECISIVE TEST, pre-registered here before the run: add the batter to
the expectation and re-measure. If the residual's reliability collapses
toward the negative-control baseline, it was the opponent, the finding is
explained, and the item closes. If it survives largely intact, there is a
per-start pitcher channel that neither E0 nor the engine's rates carry,
and it earns a screen against the next start.

THE BATTER TERM, counted not imported: for every batter, over TRAIN
pitches only (date < 2026-07-01), his swings and whiffs against what E0
expected of them, as a log-odds offset on whiff-given-swing

    delta_b = logit(W_b / S_b) - logit(E[W]_b / S_b)

shrunk by S_b / (S_b + K). K IS MEASURED, not chosen: split each batter's
swings odd/even, correlate the two halves' offsets, and solve the
reliability for the swings-to-half-reliable count. Guessing K is how a
measured quantity gets handed back to a search — `stabilise.py` counted
the four shipped shrinkage constants for exactly this reason and found
every guessed one wrong.
"""
from __future__ import annotations

import glob
import gzip
import json
import math
import multiprocessing as mp
import os
import sys
from collections import defaultdict

import numpy as np

from src import db
from scratchpad import pitch_e0

OUT = "scratchpad/pitch_e1.json"
HOLDOUT = "2026-07-01"
SWING = ("whiff", "foul", "inplay")
_P: dict = {}
_DATES: dict[str, str] = {}


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


def _one(path: str):
    """{batter_id: [S, W, E_W, S_odd, W_odd, E_odd, S_ev, W_ev, E_ev]}
    over TRAIN pitches of one game. Odd/even is by swing index, for the
    shrinkage measurement."""
    pk = os.path.basename(path).split(".")[0]
    date = _DATES.get(f"mlb-{pk}")
    if not date or date >= HOLDOUT:
        return None
    try:
        d = json.load(gzip.open(path))
    except Exception:
        return None
    acc: dict = defaultdict(lambda: [0, 0, 0.0, 0, 0, 0.0, 0, 0, 0.0])
    for pl in d.get("allPlays") or []:
        mu = pl.get("matchup") or {}
        bid = (mu.get("batter") or {}).get("id")
        if not bid:
            continue
        b = s = 0
        for ev in pl.get("playEvents") or []:
            if not ev.get("isPitch"):
                continue
            det = ev.get("details") or {}
            oc = pitch_e0.outcome_of(det.get("code"))
            if oc is None:
                continue
            pd = ev.get("pitchData") or {}
            co = pd.get("coordinates") or {}
            reg = pitch_e0.region_of(co.get("pX"), co.get("pZ"),
                                     pd.get("strikeZoneTop"),
                                     pd.get("strikeZoneBottom"))
            code = (det.get("type") or {}).get("code")
            fam = pitch_e0.FAMILY.get(code, "OTH" if code else None)
            cell = _P.get((fam, b, s, reg)) if (reg and fam) else None
            if cell is not None and oc in SWING:
                a = acc[bid]
                p = cell["whiff"] / sum(cell[o] for o in SWING)
                w = 1 if oc == "whiff" else 0
                half = 3 * (1 + a[0] % 2)      # alternate odd/even swings
                a[0] += 1
                a[1] += w
                a[2] += p
                a[half] += 1
                a[half + 1] += w
                a[half + 2] += p
            if oc == "ball":
                b += 1
            elif oc in ("called", "whiff"):
                s += 1
            elif oc == "foul" and s < 2:
                s += 1
            if b > 3 or s > 2:
                break
    return dict(acc)


def measure_k(rows):
    """The shrinkage constant, COUNTED. Split-half over batters: correlate
    the odd-swing offset against the even-swing offset, then K is the
    swing count at which the offset is half signal, half noise:
    reliability r = S / (S + K)  =>  K = S_median * (1 - r) / r."""
    a, b, ns = [], [], []
    for r in rows:
        S1, W1, E1_, S2, W2, E2 = r[3], r[4], r[5], r[6], r[7], r[8]
        if S1 < 25 or S2 < 25:
            continue
        a.append(logit(W1 / S1) - logit(E1_ / S1))
        b.append(logit(W2 / S2) - logit(E2 / S2))
        ns.append(min(S1, S2))
    if len(a) < 50:
        return None, 0, 0
    r_half = float(np.corrcoef(a, b)[0, 1])
    med = float(np.median(ns))
    if r_half <= 0:
        return None, len(a), r_half
    k = med * (1 - r_half) / r_half
    return k, len(a), r_half


def build(path: str = OUT):
    with db.connect() as c:
        _DATES.update({r["game_id"]: r["date"] for r in c.execute(
            "select game_id, date from games where sport='mlb'")})
    p, _ = pitch_e0.probs(pitch_e0.load(split="train"))
    _P.update(p)
    files = sorted(glob.glob(".cache/pbp/*.json.gz"))
    print(f"  {len(files)} cached games (train pitches only)")
    tot: dict = defaultdict(lambda: [0, 0, 0.0, 0, 0, 0.0, 0, 0, 0.0])
    with mp.get_context("fork").Pool(max(mp.cpu_count() - 1, 1)) as pool:
        for got in pool.imap_unordered(_one, files, chunksize=64):
            if not got:
                continue
            for bid, v in got.items():
                t = tot[bid]
                for i in range(9):
                    t[i] += v[i]
    rows = list(tot.values())
    ids = list(tot.keys())
    k, n_k, r_half = measure_k(rows)
    print(f"  {len(ids):,} batters, {sum(r[0] for r in rows):,} swings")
    print(f"  SHRINKAGE MEASURED: split-half r={r_half:+.3f} over {n_k:,} "
          f"batters -> K = {k:.0f} swings")
    out = {"K": k, "r_half": r_half, "n_batters": len(ids), "off": {}}
    for bid, r in zip(ids, rows):
        S, W, E = r[0], r[1], r[2]
        if S < 20:
            continue
        raw = logit(W / S) - logit(E / S)
        out["off"][str(bid)] = round(raw * S / (S + k), 5)
    json.dump(out, open(path, "w"))
    d = list(out["off"].values())
    print(f"  {len(d):,} batters with an offset; sd {np.std(d):.4f}, "
          f"range {min(d):+.3f} .. {max(d):+.3f} (log-odds on whiff|swing)")
    print(f"  -> {path}")


def load(path: str = OUT):
    d = json.load(open(path))
    return {int(k): v for k, v in d["off"].items()}, d


def apply_batter(cell, delta):
    """E0 cell -> E1 cell: shift whiff-given-swing by the batter's offset
    and redistribute inside the SWING outcomes only. Take outcomes (ball,
    called) are untouched — this term is about what he does when he
    swings, and moving take probability here would silently re-price the
    command channel that `velo.py` already ships."""
    if not delta:
        return cell
    sw = sum(cell[o] for o in SWING)
    if sw <= 0:
        return cell
    p = cell["whiff"] / sw
    q = sigmoid(logit(p) + delta)
    rest = sw - cell["whiff"]
    out = dict(cell)
    out["whiff"] = sw * q
    scale = (sw * (1 - q)) / rest if rest > 0 else 0.0
    out["foul"] = cell["foul"] * scale
    out["inplay"] = cell["inplay"] * scale
    return out


def main():
    if "--build" in sys.argv:
        build()
        return
    off, meta = load()
    d = np.array(list(off.values()))
    print(f"  {meta['n_batters']:,} batters counted, {len(off):,} with an "
          f"offset (>= 20 swings)")
    print(f"  measured K = {meta['K']:.0f} swings "
          f"(split-half r {meta['r_half']:+.3f})")
    print(f"  offsets: sd {d.std():.4f}  "
          f"p05 {np.percentile(d, 5):+.3f}  p95 {np.percentile(d, 95):+.3f}")
    print(f"  a +0.10 offset turns a 25% whiff/swing into "
          f"{sigmoid(logit(.25) + .10):.3f}")


if __name__ == "__main__":
    main()
