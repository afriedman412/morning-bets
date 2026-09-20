"""TODO item 11 — count the first-inning rate residual, batter-controlled.

    venv/bin/python -m scratchpad.inn1 [--limit N] [--control] [--null]

QUESTION    Within a starter's FIRST lineup pass, are real per-PA rates
            different in inning 1 than in innings 2+, once the batter is
            controlled? The model applies one flat TTO pass-1 multiplier to
            every pass-1 plate appearance regardless of inning, so any real
            within-pass-1 split is a mechanism the simulator does not have
            — and item 11 says the model's first inning is short ~12%.

HYPOTHESIS  Real starters allow more offence in inning 1 than the same
            pass against the same hitters later would predict (the classic
            "not settled in yet" first-inning effect). If true, the counted
            ratio is exactly the multiplier `pa_from` is missing.

TEST        Difference-in-differences on the play-by-play cache, pre-holdout
            games only (date < 2026-07-01). For each start, split batters by
            where their PASS-1 plate appearance fell: inning 1 (group T) or
            inning >= 2 (group B). Keep only batters also faced at pass 2,
            so each batter is his own control. For channel c:

                mult_c = (rate_T_pass1 / rate_T_pass2)
                       / (rate_B_pass1 / rate_B_pass2)

            Batter quality cancels inside each ratio; the TTO pass-1 ->
            pass-2 decay cancels across the two ratios; survival-to-pass-2
            selection hits both groups of the same start equally and
            cancels in the DiD. What is left is the inning-1 effect.

            Field-state confound: STATE_MULT already handles base-out state
            per PA, so the count must not absorb it. The bases-EMPTY-only
            variant is printed alongside; if the two agree, state mix is
            not driving the number.

            POWER: ~9,000 pre-holdout games, ~2 pass-1/pass-2 pairs per
            batter, expect ~150k+ PAs a cell for T, more for B. A 5%
            k-rate effect at these counts is several sigma.

            --control injects +10% strikeouts and +10% BABIP into the
            inning-1 rows only and re-runs the estimator: it must read
            ~1.10 on those channels and ~1.00 elsewhere or the harness is
            not seeing what it claims to measure.
            --null permutes the T/B labels within each start: must read
            ~1.00 everywhere.
"""
from __future__ import annotations

import math
import pathlib
import pickle
import random
import sys
from collections import defaultdict
from multiprocessing import Pool

from src import db
from src.context.sources import pbp
from src.context.tto import _bucket

HOLDOUT = "2026-07-01"


def _extract(gid: str) -> list[tuple]:
    """(season, side, batter, pass, inning, bucket, empty) per starter PA."""
    try:
        data = pbp.fetch(gid)
    except Exception:
        return []
    if not data:
        return []
    starter: dict = {}
    seen: dict = defaultdict(list)      # (side, batter) -> [(inn, b, empty)]
    for play, bases, _o, _a, _h in pbp.plays(gid, data):
        ab = play.get("about") or {}
        mu = play.get("matchup") or {}
        pid = (mu.get("pitcher") or {}).get("id")
        bid = (mu.get("batter") or {}).get("id")
        if not pid or not bid:
            continue
        side = "home" if ab.get("isTopInning") else "away"
        starter.setdefault(side, pid)
        if starter[side] != pid:
            continue
        b = _bucket(((play.get("result") or {}).get("eventType") or ""))
        if b is None:
            continue
        seen[(side, bid)].append((ab.get("inning") or 0, b,
                                  not any(bases)))
    # LINEUP SLOT, taken as the order a batter first appears against this
    # starter. It is the EXOGENOUS version of the T/B split: slot is set
    # before a pitch is thrown, where "did his first PA fall in inning 1"
    # is decided by how the inning went. See `--slots`.
    slot: dict = {}
    for (side, bid) in seen:
        n = sum(1 for (s, _b) in slot if s == side)
        slot[(side, bid)] = n + 1
    out = []
    for (side, bid), evs in seen.items():
        if len(evs) < 2:
            continue                        # no pass-2 control
        for i, (inn, b, empty) in enumerate(evs[:2], start=1):
            group = "T" if evs[0][0] == 1 else "B"
            out.append((gid, side, bid, i, group, b, empty,
                        slot[(side, bid)]))
    return out


def tally(rows, empty_only=False):
    cells: dict = defaultdict(lambda: defaultdict(int))
    for _gid, _side, _bid, p, group, b, empty, _slot in rows:
        if empty_only and not empty:
            continue
        c = cells[(group, p)]
        c["pa"] += 1
        c[b] += 1
    return cells


def by_slot(rows, top=3, bot=7):
    """THE COLLIDER CONTROL. Relabel by LINEUP SLOT, not by which inning the
    plate appearance fell in.

    Whether a batter's first PA lands in inning 1 is decided by how inning 1
    went — three up three down and only three men are 'inning 1' batters, a
    four-run rally and eight are. That makes the shipped T/B split endogenous
    to the very offence being measured. Slots 1-3 bat in the first inning
    almost always and slots 7-9 almost never, and neither fact depends on the
    outcome, so this split is exogenous by construction. It answers a
    slightly different question — top of the order versus bottom — which is
    why it is a CONTROL on the sign rather than the headline number.
    """
    out = []
    for r in rows:
        s = r[7]
        if s <= top:
            out.append(r[:4] + ("T",) + r[5:])
        elif s >= bot:
            out.append(r[:4] + ("B",) + r[5:])
    return out


def rates(cell):
    pa = cell["pa"]
    bip = pa - cell["k"] - cell["bb"] - cell["hbp"] - cell["hr"]
    return {"pa": pa, "k_pct": (cell["k"], pa), "bb_pct": (cell["bb"], pa),
            "hr_pct": (cell["hr"], pa), "babip": (cell["hit"], bip)}


def did(cells):
    """Per-channel DiD multiplier with a delta-method se on the log."""
    out = {}
    for ch in ("k_pct", "bb_pct", "hr_pct", "babip"):
        try:
            r = {gp: rates(cells[gp])[ch] for gp in
                 (("T", 1), ("T", 2), ("B", 1), ("B", 2))}
        except KeyError:
            continue
        if any(x == 0 or n == 0 for x, n in r.values()):
            continue
        logm = (math.log(r[("T", 1)][0] / r[("T", 1)][1])
                - math.log(r[("T", 2)][0] / r[("T", 2)][1])
                - math.log(r[("B", 1)][0] / r[("B", 1)][1])
                + math.log(r[("B", 2)][0] / r[("B", 2)][1]))
        var = sum((1.0 - x / n) / x for x, n in r.values())
        out[ch] = (math.exp(logm), math.exp(logm) * math.sqrt(var),
                   logm / math.sqrt(var))
    return out


def inject(rows, rng):
    """Positive control: +10% k and +10% babip in inning-1 rows only."""
    base = tally([r for r in rows if r[4] == "T" and r[3] == 1])
    c = base[("T", 1)]
    pk = c["k"] / c["pa"]
    p_flip_k = 0.1 * pk / (1.0 - pk)
    p_flip_h = 0.1 * c["hit"] / c["out"] if c["out"] else 0.0
    out = []
    for r in rows:
        gid, side, bid, p, group, b, empty, slot = r
        if group == "T" and p == 1:
            if b != "k" and rng.random() < p_flip_k:
                b = "k"
            elif b == "out" and rng.random() < p_flip_h:
                b = "hit"
        out.append((gid, side, bid, p, group, b, empty, slot))
    return out


def permute(rows, rng):
    """Null control: shuffle the T/B labels GLOBALLY across batter-starts.

    THE WITHIN-GAME-SIDE SHUFFLE IS NOT A VALID NULL AND THIS IS THE WHOLE
    POINT OF THE INSTRUMENT. Shuffling inside a game-side preserves how many
    batters that game-side labelled T — and that count IS AN OUTCOME OF THE
    FIRST INNING. A starter retired in order puts three batters in T; one
    hit hard puts eight. So preserving it re-weights the T cell toward
    high-offence game-sides and the null reads z +14 on BABIP with nothing
    injected. Measured 2026-09-09 (`scratchpad/inn1_dbg3.py`): permuted
    pass-1 BABIP came out T 0.3161 / B 0.2524 against source groups of
    0.2869 and 0.2795 — ABOVE BOTH, which is arithmetically impossible for a
    random subset and is the signature of selection on the outcome.

    A global shuffle does not preserve that count, and reads flat (T 0.2849
    / B 0.2812 on pass 1) as a null must. A per-batter coin flip agrees.
    """
    batters = sorted({(r[0], r[1], r[2]) for r in rows})
    seen: dict = {}
    for r in rows:
        seen.setdefault((r[0], r[1], r[2]), r[4])
    labs = [seen[k] for k in batters]
    rng.shuffle(labs)
    labels = dict(zip(batters, labs))
    return [r[:4] + (labels[(r[0], r[1], r[2])],) + r[5:] for r in rows]


def report(rows, title):
    print(f"\n== {title} ==")
    for name, empty_only in (("all plate appearances", False),
                             ("bases-empty only", True)):
        cells = tally(rows, empty_only=empty_only)
        d = did(cells)
        if not d:
            print(f"  {name}: empty cell, no estimate")
            continue
        npa = {gp: cells[gp]["pa"] for gp in cells}
        print(f"  {name}  (PA: T1 {npa.get(('T', 1), 0):,} "
              f"T2 {npa.get(('T', 2), 0):,} B1 {npa.get(('B', 1), 0):,} "
              f"B2 {npa.get(('B', 2), 0):,})")
        for ch, (m, se, z) in d.items():
            print(f"    {ch:<8} mult {m:6.4f}  se {se:6.4f}  z {z:+5.1f}")


CACHE = pathlib.Path("scratchpad/inn1_rows.pkl")


def null_spread(rows, n=25):
    """CALIBRATE THE STANDARD ERROR against the permutation distribution.

    The analytic se treats the four cells as independent binomials. They are
    not: a batter contributes to two of them, so the real spread is wider by
    however much batter-level clustering matters. Running the null n times
    measures that spread directly, and the ratio empirical/analytic is the
    factor every z in this module has to be divided by.
    """
    got: dict = defaultdict(list)
    for seed in range(n):
        d = did(tally(permute(rows, random.Random(seed))))
        for ch, (m, _se, _z) in d.items():
            got[ch].append(m)
    base = did(tally(rows))
    print(f"\n== NULL SPREAD over {n} permutations ==")
    print(f"  {'channel':<9}{'null mean':>11}{'null sd':>10}"
          f"{'analytic se':>13}{'inflation':>11}{'honest z':>10}")
    for ch, vals in got.items():
        mean = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1))
        m, se, _z = base[ch]
        infl = sd / se if se else float("nan")
        print(f"  {ch:<9}{mean:>11.4f}{sd:>10.4f}{se:>13.4f}"
              f"{infl:>11.2f}{math.log(m) / sd:>10.1f}")


def main(argv):
    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    with db.connect() as c:
        season = {r["game_id"]: r["date"][:4] for r in c.execute(
            "select game_id, date from games where sport = 'mlb'")}
    if CACHE.exists() and limit is None and "--refresh" not in argv:
        rows = [tuple(r) for r in pickle.loads(CACHE.read_bytes())]
        print(f"{len(rows):,} starter PAs from {CACHE}")
    else:
        ids = pbp.final_games(before=HOLDOUT)
        if limit:
            ids = ids[:limit]
        ids = [g for g in ids if pbp.have(g)]
        print(f"{len(ids):,} pre-holdout games (date < {HOLDOUT})")
        with Pool(8) as pool:
            got = pool.map(_extract, ids, chunksize=32)
        rows = [r for rr in got for r in rr]
        n_games = sum(1 for rr in got if rr)
        print(f"{n_games:,} games extracted, {len(rows):,} starter PAs "
              f"(pass 1 and 2, batters faced at both)")
        if limit is None:
            CACHE.write_bytes(pickle.dumps(rows))

    report(rows, "MEASURED")

    # Per-season stability — the gate. Same sign all four or it is noise.
    for yr in sorted({season.get(r[0], "?") for r in rows}):
        report([r for r in rows if season.get(r[0], "?") == yr],
               f"season {yr}")

    if "--slots" in argv:
        report(by_slot(rows),
               "COLLIDER CONTROL (slots 1-3 vs 7-9, exogenous split)")
    if "--control" in argv:
        rng = random.Random(11)
        report(inject(rows, rng),
               "POSITIVE CONTROL (+10% k, +10% babip injected in inning 1)")
    if "--null" in argv:
        rng = random.Random(11)
        report(permute(rows, rng),
               "NULL (T/B labels shuffled globally across batter-starts)")
        null_spread(rows)


if __name__ == "__main__":
    main(sys.argv[1:])
