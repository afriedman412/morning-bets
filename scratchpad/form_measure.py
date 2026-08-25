"""Measure the WITHIN-START form state, with out rate as the instrument.

`form.py` measured this with a bespoke DAMAGE score — hand-chosen weights,
BB=1.0, 2B=1.7, HR=3.0 — and got pass-1 damage predicting pass-2 runs at
r = +0.081 with runs partialled out. The weights were invented, so the slope
inherits whatever the weights got wrong.

Out rate per batter faced is the better instrument and it is not invented:
it is the exact quantity whose BETWEEN-start persistence measured +0.190 at
8.5 sigma this morning, and it decomposed cleanly — BB% and BABIP move,
K% barely does.

WHAT IS BEING ASKED. Within one start, does how he has thrown SO FAR predict
how he throws NEXT? If yes, plate appearances are not independent draws from
a fixed rate, and the simulator — which treats them as exactly that — cannot
produce the clustered traffic that makes crooked innings, early hooks and
short starts.

THE BASELINE EXCLUDES THIS START. Residualising against a season mean that
CONTAINS the start being predicted manufactures a negative correlation out
of pure noise:

    r = (-1/n) / sqrt((1/w - 1/n)(1 - 1/n))

That artifact reversed the sign of the between-start result this morning —
measured -0.112 against an artifact of -0.158, concealing a true +0.21. Same
trap, same fix: leave-one-start-out.

    venv/bin/python -m scratchpad.form_measure [n_games]
"""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict

from src.context.sources import pbp

_K = {"strikeout", "strikeout_double_play"}
_BB = {"walk", "intent_walk", "hit_by_pitch"}
_HIT = {"single", "double", "triple", "home_run"}
_OUT = {"field_out", "force_out", "fielders_choice_out", "fielders_choice",
        "grounded_into_double_play", "double_play", "triple_play", "sac_fly",
        "sac_bunt", "sac_fly_double_play", "sac_bunt_double_play"}
_ROE = {"field_error"}


def _bucket(ev: str) -> str | None:
    if ev in _K:
        return "k"
    if ev in _BB:
        return "bb"
    if ev in _HIT:
        return "hit"
    if ev in _OUT:
        return "out"
    if ev in _ROE:
        return "roe"
    return None


def start_pas(game_id: str) -> list[dict]:
    """[{pitcher, side, seq, bucket, outs_made}] for each STARTER's PAs."""
    data = pbp.fetch(game_id)
    if not data:
        return []
    starter: dict = {}
    seq: dict = defaultdict(int)
    out = []
    for play in (data.get("allPlays") or []):
        mu = play.get("matchup") or {}
        ab = play.get("about") or {}
        pid = (mu.get("pitcher") or {}).get("id")
        if not pid:
            continue
        side = "home" if ab.get("isTopInning") else "away"
        starter.setdefault(side, pid)
        if starter[side] != pid:
            continue
        b = _bucket((play.get("result") or {}).get("eventType") or "")
        if b is None:
            continue
        seq[side] += 1
        out.append({"game_id": game_id, "pitcher": pid, "side": side,
                    "seq": seq[side], "bucket": b})
    return out


def collect(limit=None, verbose=True):
    ids = pbp.final_games()
    if limit:
        ids = ids[:limit]
    starts: dict = defaultdict(list)
    n = 0
    for gid in ids:
        if not pbp.have(gid):
            continue
        try:
            rows = start_pas(gid)
        except Exception:
            continue
        n += 1
        for r in rows:
            starts[(gid, r["side"], r["pitcher"])].append(r)
        if verbose and n % 500 == 0:
            print(f"  {n} games, {len(starts):,} starts", flush=True)
    return starts


def rates(pas) -> dict:
    n = len(pas)
    if not n:
        return {}
    c = defaultdict(int)
    for p in pas:
        c[p["bucket"]] += 1
    bip = n - c["k"] - c["bb"]
    return {"n": n,
            "out": (c["out"] + c["k"]) / n,
            "k": c["k"] / n,
            "bb": c["bb"] / n,
            "babip": (c["hit"] / bip) if bip > 0 else None}


def corr(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0, 0.0
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if not sx or not sy:
        return 0.0, 0.0
    r = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n * sx * sy)
    se = ((1 - r * r) / max(n - 2, 1)) ** 0.5
    return r, (r / se if se else 0.0)


def main():
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    starts = collect(lim)
    by_p: dict = defaultdict(list)
    for key, pas in starts.items():
        by_p[key[2]].append((key, pas))
    print(f"\n{len(starts):,} starts, {len(by_p):,} starters")

    rows = []
    for pid, group in by_p.items():
        if len(group) < 8:
            continue
        for key, pas in group:
            if len(pas) < 18:
                continue                 # needs a first and second pass
            first, later = pas[:9], pas[9:]
            # BASELINE FROM HIS OTHER STARTS ONLY.
            other = [p for k, ps in group if k != key for p in ps]
            if len(other) < 60:
                continue
            b = rates(other)
            f, l = rates(first), rates(later)
            if not b or not f or not l or b["babip"] is None:
                continue
            rows.append({
                "d_out": f["out"] - b["out"],
                "d_k": f["k"] - b["k"],
                "d_bb": f["bb"] - b["bb"],
                "n_out": l["out"] - b["out"],
                "n_k": l["k"] - b["k"],
                "n_bb": l["bb"] - b["bb"],
                "n_babip": (l["babip"] - b["babip"]) if l["babip"] is not None
                else None,
            })
    print(f"{len(rows):,} (first pass -> rest of start) pairs\n")
    print("  DOES THE FIRST PASS PREDICT THE REST OF THE SAME START?")
    print(f"    {'predictor -> target':<40}{'r':>9}{'sigma':>8}")
    for px, lx in (("d_out", "1st-pass OUT RATE"),
                   ("d_bb", "1st-pass BB%"),
                   ("d_k", "1st-pass K%")):
        for py, ly in (("n_out", "rest OUT RATE"), ("n_bb", "rest BB%"),
                       ("n_k", "rest K%"), ("n_babip", "rest BABIP")):
            ok = [r for r in rows if r[py] is not None]
            r_, t = corr([x[px] for x in ok], [x[py] for x in ok])
            print(f"    {lx + ' -> ' + ly:<40}{r_:>+9.4f}{t:>+8.1f}")
        print()
    xs = [r["d_out"] for r in rows]
    ys = [r["n_out"] for r in rows]
    r_, _ = corr(xs, ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    print(f"  slope: one sd of 1st-pass out-rate residual ({sx:.4f}/BF) "
          f"implies {r_ * sy:.4f}/BF")
    print(f"  for the rest of the start — about "
          f"{abs(r_ * sy) * 18:.2f} outs over the next 18 batters.")


if __name__ == "__main__":
    main()
