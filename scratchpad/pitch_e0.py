"""E0 — THE LEAGUE EXPECTATION SURFACE, counted per pitch.

    venv/bin/python -m scratchpad.pitch_e0 --build     one pass over the cache
    venv/bin/python -m scratchpad.pitch_e0             read the table back

P(outcome | pitch type, count, location region), counted on our own four
seasons. The floor rung of PLAN-pitch-expectation's ladder: before asking
whether a pitcher over- or under-performed, there has to be a counted
answer to "what does this pitch, in this count, in this spot, usually
do?"

OUTCOME ALPHABET: ball / called / whiff / foul / inplay (hbp folded into
ball — it is a take that ended the PA, and there are too few to model).
The three quantities the engine cares about fall out of it: swing rate
(whiff+foul+inplay), whiff-per-swing, and called-strike-per-take.

LOCATION IS MEASURED AGAINST THE BATTER'S OWN ZONE, not the fixed one.
The feed carries `strikeZoneTop`/`strikeZoneBottom` per pitch, so a
pitch at 3.4 ft is a different pitch to a 5-foot-6 leadoff man than to
Aaron Judge. (The SHIPPED zone% term in `velo.py` uses the fixed zone on
purpose — there it is a command measurement of the pitcher and folding
in the lineup's heights would contaminate it. Here the question is what
the pitch deserved, so the real zone is right. Both are correct for
their own question; the difference is deliberate and is why this file
does not import that constant.)

    dx = |pX| / (half-width 0.83)      dz = |pZ - mid| / (half-height)
    d  = max(dx, dz)          heart d<=0.5, shadow <=1.0, chase <=1.5,
                              waste beyond

TRAIN/TEST SPLIT IS BUILT IN, at the project's one cutoff 2026-07-01.
Counts are accumulated separately either side so no rung can ever be
fitted on rows it will be scored on — the split happens in the extractor
rather than being remembered later, which is exactly the discipline the
scratchpad fitters failed on 2026-08-29.

AGGREGATES, NOT ROWS: each worker returns cell counts, so the whole
four-season pass comes back as a few hundred kilobytes instead of three
million rows.
"""
from __future__ import annotations

import glob
import gzip
import json
import multiprocessing as mp
import os
import sys
from collections import Counter, defaultdict

from src import db

OUT = "scratchpad/pitch_e0.json"
HOLDOUT = "2026-07-01"
ZONE_HALF_X = 0.83

BALL = {"B", "*B", "H"}          # hbp folded in: a take that ended the PA
CALLED = {"C"}
WHIFF = {"S", "W"}
FOUL = {"F", "T", "L"}
INPLAY = {"X", "D", "E"}
OUTCOMES = ("ball", "called", "whiff", "foul", "inplay")

#: Pitch types grouped to the families that behave alike. Anything
#: unlisted lands in "OTH" and is reported so a growing bucket is visible
#: rather than silently absorbed.
FAMILY = {
    "FF": "FF", "FA": "FF",
    "SI": "SI", "FT": "SI",
    "FC": "FC",
    "SL": "SL", "ST": "ST", "SV": "SL",
    "CU": "CU", "KC": "CU", "CS": "CU",
    "CH": "CH", "FS": "CH", "FO": "CH",
    "KN": "OTH", "EP": "OTH", "SC": "OTH",
}

_DATES: dict[str, str] = {}


def outcome_of(code):
    if code in BALL:
        return "ball"
    if code in CALLED:
        return "called"
    if code in WHIFF:
        return "whiff"
    if code in FOUL:
        return "foul"
    if code in INPLAY:
        return "inplay"
    return None


def region_of(px, pz, top, bot):
    """heart / shadow / chase / waste against the BATTER's zone."""
    if px is None or pz is None:
        return None
    if not top or not bot or top <= bot:
        top, bot = 3.5, 1.5
    mid = (top + bot) / 2.0
    half_z = (top - bot) / 2.0
    d = max(abs(px) / ZONE_HALF_X, abs(pz - mid) / (half_z or 1.0))
    if d <= 0.5:
        return "heart"
    if d <= 1.0:
        return "shadow"
    if d <= 1.5:
        return "chase"
    return "waste"


def _one(path: str):
    """{(split, family, balls, strikes, region, outcome): n} for one game."""
    pk = os.path.basename(path).split(".")[0]
    date = _DATES.get(f"mlb-{pk}")
    if not date:
        return None
    split = "train" if date < HOLDOUT else "test"
    try:
        d = json.load(gzip.open(path))
    except Exception:
        return None
    acc = Counter()
    for pl in d.get("allPlays") or []:
        b = s = 0
        for ev in pl.get("playEvents") or []:
            if not ev.get("isPitch"):
                continue
            det = ev.get("details") or {}
            oc = outcome_of(det.get("code"))
            if oc is None:
                continue
            pd = ev.get("pitchData") or {}
            co = pd.get("coordinates") or {}
            reg = region_of(co.get("pX"), co.get("pZ"),
                            pd.get("strikeZoneTop"),
                            pd.get("strikeZoneBottom"))
            code = (det.get("type") or {}).get("code")
            fam = FAMILY.get(code, "OTH" if code else None)
            if reg and fam and s <= 2 and b <= 3:
                acc[(split, fam, b, s, reg, oc)] += 1
            if oc == "ball":
                b += 1
            elif oc in ("called", "whiff"):
                s += 1
            elif oc == "foul" and s < 2:
                s += 1
            if b > 3 or s > 2:          # feed oddity; abandon this PA
                break
    return acc


def build(path: str = OUT):
    with db.connect() as c:
        _DATES.update({r["game_id"]: r["date"] for r in c.execute(
            "select game_id, date from games where sport='mlb'")})
    files = sorted(glob.glob(".cache/pbp/*.json.gz"))
    print(f"  {len(files)} cached games")
    total = Counter()
    with mp.get_context("fork").Pool(max(mp.cpu_count() - 1, 1)) as pool:
        for got in pool.imap_unordered(_one, files, chunksize=64):
            if got:
                total.update(got)
    rows = [{"split": k[0], "fam": k[1], "b": k[2], "s": k[3],
             "reg": k[4], "oc": k[5], "n": v} for k, v in total.items()]
    json.dump(rows, open(path, "w"))
    n_tr = sum(r["n"] for r in rows if r["split"] == "train")
    n_te = sum(r["n"] for r in rows if r["split"] == "test")
    print(f"  {n_tr:,} train pitches + {n_te:,} test = {n_tr + n_te:,}")
    print(f"  {len(rows)} cell-outcome rows -> {path}")


# ── reading the table ───────────────────────────────────────────────────

def load(path: str = OUT, split: str = "train"):
    """{(fam, b, s, reg): {outcome: n}} for one split."""
    cells: dict = defaultdict(Counter)
    for r in json.load(open(path)):
        if r["split"] == split:
            cells[(r["fam"], r["b"], r["s"], r["reg"])][r["oc"]] = r["n"]
    return cells


def probs(cells, prior_n: float = 50.0):
    """Cell probabilities, shrunk toward the cell's own (fam, reg)
    marginal. A thin cell (0-0 knuckleballs in the waste zone) must not
    speak with the confidence of a full one; `prior_n` is the pseudo-count
    weight and is set, not fitted — the shrinkage RATE gets counted at E1
    where it changes an answer."""
    marg: dict = defaultdict(Counter)
    for (fam, b, s, reg), c in cells.items():
        marg[(fam, reg)].update(c)
    out = {}
    for key, c in cells.items():
        fam, b, s, reg = key
        m = marg[(fam, reg)]
        mt = sum(m.values()) or 1
        n = sum(c.values())
        out[key] = {o: (c.get(o, 0) + prior_n * m.get(o, 0) / mt)
                    / (n + prior_n) for o in OUTCOMES}
    return out, marg


def main():
    if "--build" in sys.argv:
        build()
        return
    cells = load()
    p, marg = probs(cells)
    tot = sum(sum(c.values()) for c in cells.values())
    print(f"  E0 train: {tot:,} pitches in {len(cells)} cells")

    fams = sorted({k[0] for k in cells},
                  key=lambda f: -sum(sum(c.values())
                                     for k, c in cells.items() if k[0] == f))
    print(f"\n  BY FAMILY (train, all counts/regions pooled)")
    print(f"  {'fam':<5}{'n':>10}{'ball':>8}{'called':>8}{'whiff':>8}"
          f"{'foul':>8}{'inplay':>8}{'swing%':>8}{'whf/sw':>8}")
    for f in fams:
        c = Counter()
        for k, v in cells.items():
            if k[0] == f:
                c.update(v)
        n = sum(c.values())
        sw = c["whiff"] + c["foul"] + c["inplay"]
        print(f"  {f:<5}{n:>10,}" + "".join(
            f"{c[o] / n:>8.3f}" for o in OUTCOMES)
            + f"{sw / n:>8.3f}{c['whiff'] / (sw or 1):>8.3f}")

    print(f"\n  THE COUNT MATTERS — four-seam, shadow region, by count")
    print(f"  {'count':<7}{'n':>9}{'swing%':>9}{'whf/sw':>9}{'called%':>9}")
    for b in range(4):
        for s in range(3):
            c = cells.get(("FF", b, s, "shadow"))
            if not c:
                continue
            n = sum(c.values())
            sw = c["whiff"] + c["foul"] + c["inplay"]
            tk = c["ball"] + c["called"]
            print(f"  {b}-{s:<5}{n:>9,}{sw / n:>9.3f}"
                  f"{c['whiff'] / (sw or 1):>9.3f}"
                  f"{c['called'] / (tk or 1):>9.3f}")

    print(f"\n  THE LOCATION MATTERS — slider, 0-2 and 2-0, by region")
    print(f"  {'cnt':<5}{'region':<8}{'n':>9}{'swing%':>9}{'whf/sw':>9}")
    for (b, s) in ((0, 2), (2, 0)):
        for reg in ("heart", "shadow", "chase", "waste"):
            c = cells.get(("SL", b, s, reg))
            if not c:
                continue
            n = sum(c.values())
            sw = c["whiff"] + c["foul"] + c["inplay"]
            print(f"  {b}-{s:<3}{reg:<8}{n:>9,}{sw / n:>9.3f}"
                  f"{c['whiff'] / (sw or 1):>9.3f}")


if __name__ == "__main__":
    main()
