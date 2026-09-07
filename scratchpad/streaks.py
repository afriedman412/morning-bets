"""IS THIS STREAK REAL? — does anything observable separate fades that
persist from fades that evaporate?

    venv/bin/python -m scratchpad.streaks

The pooled fact (day-22): a recent-window K% drift carries ~0.18 of its
face value into the next starts. That is an AVERAGE over real declines and
small-sample noise. This screen asks whether the exchange rate VARIES with
what we can see at price time:

    evidence   BF in the recent window (more sample -> trust more)
    velo       recent fastball velocity vs his own season mean (the
               classic "the fade is real" marker, from our own pbp cache)
    walks      bb% drifting bad alongside the K drift (corroboration)

DESIGN — rolling, one row per start: features from starts strictly BEFORE
start t (season-to-date baseline, last-5 recent window), target is start
t's own K% vs the baseline. Nothing from t leaks into its features.

    y = k%(t) - k%(before t)
    y ~ x + x*z_velo + x*z_bf + x*z_bb  (+ the z mains, so an interaction
        cannot masquerade as a level effect)   where x = recent drift

POWER, stated before the result: ~10k rows, per-row target noise se ~0.08
(25 BF), sd(x) ~0.03 -> se(lambda) ~0.03. The pooled 0.18 resolves at ~6
sigma; an interaction worth half the main effect resolves at ~3. The
per-season sign split is the stability gate.

POSITIVE CONTROL: a synthetic target where the drift persists ONLY when
velocity is down must light the velo interaction and nothing else.
"""
from __future__ import annotations

import json

import numpy as np

from src import db

MIN_PRIOR_STARTS = 10
RECENT = 5
MIN_T_BF = 15


def starts():
    q = """select p.player_name name, g.date d, g.game_id gid,
           p.k, p.outs_recorded o, p.h, p.bb
           from mlb_pitching p join games g on g.game_id=p.game_id
           where g.sport='mlb' and g.status='Final' and p.is_starter=1
           order by p.player_name, g.date"""
    with db.connect() as c:
        return [dict(r) for r in c.execute(q)]


def build():
    velo = {}
    for r in json.load(open("scratchpad/velo_starts.json")):
        velo[(f"mlb-{r['pk']}", r["name"])] = r["velo"]
    rows, n_velo = [], 0
    byp: dict[str, list] = {}
    for r in starts():
        r["bf"] = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
        if r["bf"] < 1:
            continue
        byp.setdefault(r["name"], []).append(r)
    for name, rs in byp.items():
        for season in {r["d"][:4] for r in rs}:
            ss = [r for r in rs if r["d"][:4] == season]
            for t in range(MIN_PRIOR_STARTS, len(ss)):
                prior, rec, tgt = ss[:t], ss[t - RECENT:t], ss[t]
                if tgt["bf"] < MIN_T_BF:
                    continue
                bf_p = sum(r["bf"] for r in prior)
                bf_r = sum(r["bf"] for r in rec)
                k_p = sum(r["k"] for r in prior) / bf_p
                k_r = sum(r["k"] for r in rec) / bf_r
                bb_p = sum(r["bb"] for r in prior) / bf_p
                bb_r = sum(r["bb"] for r in rec) / bf_r
                vs = [velo.get((r["gid"], name)) for r in prior]
                vr = [velo.get((r["gid"], name)) for r in rec]
                vs = [v for v in vs if v]
                vr = [v for v in vr if v]
                dv = (sum(vr) / len(vr) - sum(vs) / len(vs)) \
                    if len(vr) >= 3 and len(vs) >= 5 else None
                if dv is not None:
                    n_velo += 1
                rows.append({
                    "season": int(season), "date": tgt["d"],
                    "x": k_r - k_p, "y": tgt["k"] / tgt["bf"] - k_p,
                    "bf_r": bf_r, "d_bb": bb_r - bb_p, "d_velo": dv})
    print(f"  {len(rows)} start-rows; velo coverage "
          f"{n_velo / len(rows):.1%}  <- read nothing before this is high")
    return rows


def z(a):
    a = np.array(a, dtype=float)
    return (a - a.mean()) / (a.std() or 1)


def fit(rows, ykey="y", label="", quiet=False):
    x = np.array([r["x"] for r in rows])
    y = np.array([r[ykey] for r in rows])
    zv = z([r["d_velo"] for r in rows])
    zb = z([r["bf_r"] for r in rows])
    zw = z([r["d_bb"] for r in rows])
    X = np.column_stack([np.ones_like(x), x, x * zv, x * zb, x * zw,
                         zv, zb, zw])
    names = ["const", "drift", "drift*velo", "drift*bf", "drift*bb",
             "velo", "bf", "bb"]
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    sig2 = float(res @ res) / (len(y) - X.shape[1])
    se = np.sqrt(np.diag(sig2 * np.linalg.inv(X.T @ X)))
    if not quiet:
        print(f"\n  {label}  n={len(y)}")
        for n_, b, s in zip(names, beta, se):
            mark = "  <-" if abs(b) > 2 * s and n_ != "const" else ""
            print(f"    {n_:<12}{b:+.4f} ± {s:.4f}{mark}")
    return dict(zip(names, zip(beta, se)))


def main():
    rows = [r for r in build() if r["d_velo"] is not None]
    print(f"  {len(rows)} rows with velocity")

    # positive control FIRST: drift persists fully iff velo is down 1 sd
    rng = np.random.default_rng(7)
    zv = z([r["d_velo"] for r in rows])
    fake = [dict(r, fake=r["x"] * (zv[i] < -1)
                 + rng.normal(0, 0.08)) for i, r in enumerate(rows)]
    got = fit(fake, "fake", "POSITIVE CONTROL (planted velo-gated fade)")
    b, s = got["drift*velo"]
    print(f"    control {'SEEN' if abs(b) > 2 * s else '** NOT SEEN **'}"
          f" at {abs(b / s):.1f} sigma")

    fit(rows, "y", "REAL — all seasons pooled")
    print("\n  drift*velo per season (the stability gate):")
    for season in (2023, 2024, 2025, 2026):
        sub = [r for r in rows if r["season"] == season]
        got = fit(sub, "y", "", quiet=True)
        b, s = got["drift*velo"]
        print(f"    {season}  {b:+.4f} ± {s:.4f}  ({b / s:+.1f} sigma)")


if __name__ == "__main__":
    main()
