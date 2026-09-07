"""THE POWERED VERSION of pitch_expect's reliability question.

    venv/bin/python -m scratchpad.expect_league [min_starts]

One pitcher's season is 27 starts and se(r) ~ 0.20, so every column in
`pitch_expect` came back inside two standard errors of zero — that run
settled nothing and said so. This runs the identical measurement over
every starter in the cache.

THE DESIGN POINT THAT DECIDES WHAT THE NUMBER MEANS: the halves are
CENTRED ON EACH PITCHER'S OWN SEASON MEAN before pooling. Without that,
a high correlation would only say "Cease differs from a soft-tosser",
which is between-PITCHER variance we already model. The question here is
BETWEEN-START WITHIN-PITCHER: does tonight's reading deviate from his own
norm in a way that repeats within the same night?

Centring on an n-start mean induces a known small negative bias (~ -1/(n-1)).
It is not argued away — the NEGATIVE CONTROL runs through the same
centring, so the baseline it reports already contains it.

THREE CONTROLS, all through the real pipeline:
  * POSITIVE — a planted per-start effect on the pitch rows must be seen.
  * NEGATIVE — pitches reshuffled across starts within a pitcher, which
    destroys between-start signal and leaves the harness's own baseline.
  * A KNOWN-GOOD COLUMN — per-start fastball velocity, which measured
    0.89-0.99 in `pitch_one.py`. If velo does not come back high here
    the pipeline is broken, whatever the other columns say.

Split is by PLATE APPEARANCE (see pitch_expect's docstring: splitting by
pitch biases the halves' count composition against each other).
"""
from __future__ import annotations

import glob
import gzip
import json
import multiprocessing as mp
import os
import sys
from collections import defaultdict

import numpy as np

from src import db
from scratchpad import pitch_e0, pitch_e1

MIN_HALF = 20
MIN_STARTS = 10
_P: dict = {}
_DATES: dict[str, str] = {}
_E1: dict = {}                   # batter_id -> log-odds whiff|swing offset
_SINCE: str = ""                 # optional date floor (out-of-sample runs)


def _agg(rows):
    """Half-aggregate: counts of actual and expected outcomes + velo."""
    out = {"n": len(rows)}
    for o in pitch_e0.OUTCOMES:
        out["a_" + o] = sum(1 for r in rows if r[0] == o)
        out["e_" + o] = sum(r[1][o] for r in rows)
    v = [r[2] for r in rows if r[2] is not None]
    out["velo"] = sum(v) / len(v) if v else None
    return out


def _one(path: str):
    """[(name, date, halfA, halfB)] for the two STARTERS of one game."""
    pk = os.path.basename(path).split(".")[0]
    date = _DATES.get(f"mlb-{pk}")
    if not date or (_SINCE and date < _SINCE):
        return None
    try:
        d = json.load(gzip.open(path))
    except Exception:
        return None
    first: dict = {}
    bypa: dict = defaultdict(lambda: defaultdict(list))
    pa_i = -1
    for pl in d.get("allPlays") or []:
        mu = pl.get("matchup") or {}
        name = (mu.get("pitcher") or {}).get("fullName")
        if not name:
            continue
        bid = (mu.get("batter") or {}).get("id")
        delta = _E1.get(bid, 0.0) if _E1 else 0.0
        side = "home" if (pl.get("about") or {}).get("isTopInning") else "away"
        first.setdefault(side, name)
        if first[side] != name:
            continue
        pa_i += 1
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
            if cell is not None:
                if delta:
                    cell = pitch_e1.apply_batter(cell, delta)
                bypa[name][pa_i % 2].append((oc, cell, pd.get("startSpeed")))
            if oc == "ball":
                b += 1
            elif oc in ("called", "whiff"):
                s += 1
            elif oc == "foul" and s < 2:
                s += 1
            if b > 3 or s > 2:
                break
    out = []
    for name, halves in bypa.items():
        a, b_ = halves.get(0, []), halves.get(1, [])
        if len(a) >= MIN_HALF and len(b_) >= MIN_HALF:
            out.append((name, date, _agg(a), _agg(b_),
                        [(r[0], r[1], r[2]) for r in a + b_]))
    return out


COLS = {
    "velo (known-good)": lambda t: t["velo"],
    "(b) e_whiff / pitch": lambda t: t["e_whiff"] / t["n"],
    "(b) e_whiff / swing": lambda t: t["e_whiff"] / (
        t["e_whiff"] + t["e_foul"] + t["e_inplay"]),
    "(b) e_called / pitch": lambda t: t["e_called"] / t["n"],
    "(b) e_ball / pitch": lambda t: t["e_ball"] / t["n"],
    "    ACTUAL whf/swing": lambda t: (
        t["a_whiff"] / (t["a_whiff"] + t["a_foul"] + t["a_inplay"])
        if (t["a_whiff"] + t["a_foul"] + t["a_inplay"]) else None),
    "    ACTUAL ball/pitch": lambda t: t["a_ball"] / t["n"],
    "(a) resid whiff/pitch": lambda t: (t["a_whiff"] - t["e_whiff"]) / t["n"],
    "(a) resid called/pitch": lambda t: (t["a_called"] - t["e_called"])
    / t["n"],
    "(a) resid ball/pitch": lambda t: (t["a_ball"] - t["e_ball"]) / t["n"],
    "(a) resid swing/pitch": lambda t: (
        (t["a_whiff"] + t["a_foul"] + t["a_inplay"])
        - (t["e_whiff"] + t["e_foul"] + t["e_inplay"])) / t["n"],
}


def centred_r(rows, fn):
    """Pool half-A vs half-B across pitchers, each centred on his own mean."""
    by: dict = defaultdict(list)
    for name, _date, a, b, _ in rows:
        x, y = fn(a), fn(b)
        if x is not None and y is not None:
            by[name].append((x, y))
    A, B = [], []
    for name, pairs in by.items():
        if len(pairs) < MIN_STARTS:
            continue
        mx = sum(p[0] for p in pairs) / len(pairs)
        my = sum(p[1] for p in pairs) / len(pairs)
        for x, y in pairs:
            A.append(x - mx)
            B.append(y - my)
    if len(A) < 50 or np.std(A) == 0 or np.std(B) == 0:
        return None, len(A), 0
    return float(np.corrcoef(A, B)[0, 1]), len(A), len(by)


def main():
    global MIN_STARTS, _SINCE
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        MIN_STARTS = int(sys.argv[1])
    use_e1 = "--e1" in sys.argv
    for a in sys.argv:
        if a.startswith("--since="):
            _SINCE = a.split("=", 1)[1]
    with db.connect() as c:
        _DATES.update({r["game_id"]: r["date"] for r in c.execute(
            "select game_id, date from games where sport='mlb'")})
    p, _ = pitch_e0.probs(pitch_e0.load(split="train"))
    _P.update(p)
    if use_e1:
        off, meta = pitch_e1.load()
        _E1.update(off)
        print(f"  E1 ON: {len(off):,} batter offsets, measured K="
              f"{meta['K']:.0f} swings")
    if _SINCE:
        print(f"  restricted to starts on/after {_SINCE}")
    files = sorted(glob.glob(".cache/pbp/*.json.gz"))
    print(f"  {len(files)} cached games; E0 has {len(p)} cells")
    rows = []
    with mp.get_context("fork").Pool(max(mp.cpu_count() - 1, 1)) as pool:
        for got in pool.imap_unordered(_one, files, chunksize=64):
            if got:
                rows.extend(got)
    for a in sys.argv:
        if a.startswith("--dump="):
            # PER-START ROWS for the step-three screen. Whole-start
            # totals (both halves summed) — the split only existed for
            # the reliability question.
            out = [{"name": r[0], "date": r[1],
                    "n": r[2]["n"] + r[3]["n"],
                    "a_whiff": r[2]["a_whiff"] + r[3]["a_whiff"],
                    "e_whiff": round(r[2]["e_whiff"] + r[3]["e_whiff"], 4),
                    "a_swing": sum(r[h]["a_" + o] for h in (2, 3)
                                   for o in ("whiff", "foul", "inplay")),
                    "e_swing": round(sum(r[h]["e_" + o] for h in (2, 3)
                                         for o in ("whiff", "foul",
                                                   "inplay")), 4),
                    "a_ball": r[2]["a_ball"] + r[3]["a_ball"],
                    "e_ball": round(r[2]["e_ball"] + r[3]["e_ball"], 4)}
                   for r in rows]
            json.dump(out, open(a.split("=", 1)[1], "w"))
            print(f"  dumped {len(out):,} start rows -> {a.split('=', 1)[1]}")

    npitch = sum(r[2]["n"] + r[3]["n"] for r in rows)
    print(f"  {len(rows):,} starter-starts, {npitch:,} matched pitches, "
          f"{len({r[0] for r in rows})} distinct starters")
    print(f"  pitchers need >= {MIN_STARTS} starts to enter\n")

    rng = np.random.default_rng(7)

    # NEGATIVE CONTROL: reshuffle a pitcher's pitches across his own
    # starts, so between-start signal is gone but everything else — the
    # centring, the pooling, the start sizes — is identical.
    bypit: dict = defaultdict(list)
    for r in rows:
        bypit[r[0]].append(r)
    fake = []
    for name, rs in bypit.items():
        pool_ = [p_ for r in rs for p_ in r[4]]
        idx = rng.permutation(len(pool_))
        at = 0
        for r in rs:
            n = r[2]["n"] + r[3]["n"]
            take = [pool_[i] for i in idx[at:at + n]]
            at += n
            half = len(take) // 2
            fake.append((name, r[1], _agg(take[:half]), _agg(take[half:]),
                         take))

    # POSITIVE CONTROL: a real per-start lift on every pitch's whiff prob.
    plant = []
    for name, rs in bypit.items():
        for r in rs:
            z = rng.normal()

            def bump(cell, z=z):
                return {**cell, "whiff": min(max(
                    cell["whiff"] + 0.06 * z, 0.001), 0.99)}

            a = [(o, bump(c), v) for o, c, v in r[4][:r[2]["n"]]]
            b = [(o, bump(c), v) for o, c, v in r[4][r[2]["n"]:]]
            plant.append((name, r[1], _agg(a), _agg(b), a + b))

    fn = COLS["(b) e_whiff / pitch"]
    rp, np_, _ = centred_r(plant, fn)
    rn, nn, _ = centred_r(fake, fn)
    print(f"  POSITIVE control (planted per-start whiff lift): "
          f"r={rp:+.3f} on {np_:,} starts")
    print(f"  NEGATIVE control (pitches reshuffled within pitcher): "
          f"r={rn:+.3f} on {nn:,} starts   <- the baseline to beat")
    ok = rp > 0.5 and abs(rn) < 0.05
    print(f"  {'CONTROLS SEEN' if ok else '** HARNESS SUSPECT **'}")

    print("\n  === WITHIN-PITCHER SPLIT-HALF RELIABILITY (split by PA,"
          " centred on each pitcher's own mean) ===")
    print(f"  {'quantity':<24}{'r':>8}{'SB':>8}{'starts':>9}{'pit':>6}"
          f"{'neg ctl':>9}")
    for label, f in COLS.items():
        r, n, npit = centred_r(rows, f)
        rn_, _, _ = centred_r(fake, f)
        if r is None:
            print(f"  {label:<24}{'--':>8}")
            continue
        s = 2 * r / (1 + r) if r > -1 else float("nan")
        print(f"  {label:<24}{r:>+8.3f}{s:>+8.3f}{n:>9,}{npit:>6}"
              f"{(rn_ if rn_ is not None else 0):>+9.3f}")


if __name__ == "__main__":
    main()
