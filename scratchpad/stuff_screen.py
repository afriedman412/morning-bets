"""STEP TWO of PLAN-pitch-history.md — candidate drift columns, screened.

    venv/bin/python -m scratchpad.stuff_screen

QUESTION: beyond recent FASTBALL velo (shipped as sim.USE_VELO_K), does
any other per-pitch physical drift predict the NEXT start's K% (or BB%)?
Candidates, in the order pitch_one.py's reliability table justifies:
secondary-pitch velo, FB spin, FB induced vertical break, zone%. Whiff
was gated OUT by the table (split-half r ~ 0 at one start).

DESIGN — identical to streaks.py, the harness that found the velo term:
rolling, one row per start; features strictly before start t (last-5
recent window minus season-to-date mean, both from prior starts only;
the secondary type itself is chosen from prior starts, so nothing from
t or later leaks). Target y = k%(t) - k%(before t), bf-weighted.

    y ~ 1 + d_velo + d_candidate      (one candidate at a time; the
                                       question is "beyond velo")

POWER, stated before the run: ~9k rows, per-row target noise se ~0.08
(25 BF) -> se(beta per sd of candidate) ~ 0.001. The velo term is
~+0.010 K% per sd; anything half that size resolves at ~5 sigma.

POSITIVE CONTROL, per candidate: a synthetic target 0.010 * z(d_cand) +
noise(0.08) must light that candidate at > 5 sigma.

THE BAR, pre-registered before the first real number: a candidate is
ALIVE only if the pooled beta with velo controlled is |t| >= 3 AND the
per-season betas carry the same sign in all four seasons (the gate the
velo term passed). 2-3 sigma with consistent signs = WEAK, log it, do
not wire. Anything else is dead. The zone candidate is screened against
BB% as well (the plan expects command to lead walks); same bar. A
coefficient that ships is refit on date < 2026-07-01 only.
"""
from __future__ import annotations

import json

import numpy as np

from src import db

MIN_PRIOR_STARTS = 10
RECENT = 5
MIN_T_BF = 15
MIN_SEASON, MIN_RECENT = 5, 3
FB = {"FF", "SI"}
HOLDOUT = "2026-07-01"


def starts():
    q = """select p.player_name name, g.date d, g.game_id gid,
           p.k, p.outs_recorded o, p.h, p.bb
           from mlb_pitching p join games g on g.game_id=p.game_id
           where g.sport='mlb' and g.status='Final' and p.is_starter=1
           order by p.player_name, g.date"""
    with db.connect() as c:
        return [dict(r) for r in c.execute(q)]


def drift(series):
    """last-RECENT mean minus all-prior mean over available values."""
    vals = [v for v in series if v is not None]
    rec = [v for v in series[-RECENT:] if v is not None]
    if len(vals) < MIN_SEASON or len(rec) < MIN_RECENT:
        return None
    return sum(rec) / len(rec) - sum(vals) / len(vals)


def build():
    pitch = {}
    for r in json.load(open("scratchpad/velo_starts.json")):
        pitch[(f"mlb-{r['pk']}", r["name"])] = r
    rows = []
    byp: dict[str, list] = {}
    for r in starts():
        r["bf"] = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
        if r["bf"] >= 1:
            byp.setdefault(r["name"], []).append(r)
    for name, rs in byp.items():
        for season in {r["d"][:4] for r in rs}:
            ss = [r for r in rs if r["d"][:4] == season]
            ps = [pitch.get((r["gid"], name)) for r in ss]
            for t in range(MIN_PRIOR_STARTS, len(ss)):
                prior, tgt = ss[:t], ss[t]
                if tgt["bf"] < MIN_T_BF:
                    continue
                bf_p = sum(r["bf"] for r in prior)
                k_p = sum(r["k"] for r in prior) / bf_p
                bb_p = sum(r["bb"] for r in prior) / bf_p
                rec = prior[-RECENT:]
                bf_r = sum(r["bf"] for r in rec)
                d_bb = sum(r["bb"] for r in rec) / bf_r - bb_p
                pp = ps[:t]
                d_velo = drift([p["velo"] if p else None for p in pp])
                if d_velo is None:
                    continue
                # secondary type: top non-FB by count over PRIOR starts
                cnt: dict[str, int] = {}
                for p in pp:
                    for c, cell in (p or {}).get("types", {}).items():
                        if c not in FB:
                            cnt[c] = cnt.get(c, 0) + cell["n"]
                sec = max(cnt, key=cnt.get) if cnt else None

                def col(fn):
                    return drift([fn(p) if p else None for p in pp])

                rows.append({
                    "season": int(season), "date": tgt["d"],
                    "y": tgt["k"] / tgt["bf"] - k_p,
                    "y_bb": tgt["bb"] / tgt["bf"] - bb_p,
                    "d_bb": d_bb,
                    "d_velo": d_velo,
                    "d_sec": col(lambda p: (p["types"].get(sec) or {})
                                 .get("velo")) if sec else None,
                    "d_spin": col(lambda p: _fb(p, "spin")),
                    "d_ivb": col(lambda p: _fb(p, "ivb")),
                    "d_zone": col(lambda p: p["n_zone"] / p["n_loc"]
                                  if p.get("n_loc") else None)})
    print(f"  {len(rows)} start-rows with d_velo; candidate coverage "
          f"<- read nothing before these are high:")
    for c in ("d_sec", "d_spin", "d_ivb", "d_zone"):
        n = sum(1 for r in rows if r[c] is not None)
        print(f"    {c:<8}{n}  ({n / len(rows):.1%})")
    return rows


def _fb(p, key):
    """bf-weighted FB (FF/SI) mean of one per-start cell."""
    cells = [(c["n"], c[key]) for t, c in p.get("types", {}).items()
             if t in FB and c.get(key) is not None]
    tot = sum(n for n, _ in cells)
    return sum(n * v for n, v in cells) / tot if tot else None


def fit(rows, cand, ykey="y", quiet=False):
    sub = [r for r in rows if r[cand] is not None]
    x1 = np.array([r["d_velo"] for r in sub])
    xc = np.array([r[cand] for r in sub], dtype=float)
    sd = xc.std()
    y = np.array([r[ykey] for r in sub])
    X = np.column_stack([np.ones_like(x1), x1, xc / (sd or 1)])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    sig2 = float(res @ res) / (len(y) - 3)
    se = np.sqrt(np.diag(sig2 * np.linalg.inv(X.T @ X)))
    return beta, se, sd, len(sub), sub


def screen(rows, cand, ykey="y"):
    # positive control first
    rng = np.random.default_rng(11)
    sub = [r for r in rows if r[cand] is not None]
    xc = np.array([r[cand] for r in sub], dtype=float)
    zc = (xc - xc.mean()) / (xc.std() or 1)
    fake = [dict(r, fk=0.010 * zc[i] + rng.normal(0, 0.08))
            for i, r in enumerate(sub)]
    b, s, *_ = fit(fake, cand, "fk")
    ctl = abs(b[2] / s[2])
    ctl_ok = ctl > 5

    b, s, sd, n, sub = fit(rows, cand, ykey)
    t_pool = b[2] / s[2]
    per = []
    for season in (2023, 2024, 2025, 2026):
        ss = [r for r in sub if r["season"] == season]
        bb_, ss_, *_ = fit(ss, cand, ykey)
        per.append(bb_[2] / ss_[2])
    pre = [r for r in sub if r["date"] < HOLDOUT]
    bp, sp, *_ = fit(pre, cand, ykey)
    same = all(np.sign(t) == np.sign(t_pool) for t in per)
    alive = abs(t_pool) >= 3 and same
    verdict = ("ALIVE" if alive else
               "WEAK" if abs(t_pool) >= 2 and same else "dead")
    print(f"\n  {cand} -> {ykey}   n={n}  sd={sd:.3g}  "
          f"control {ctl:.0f} sigma {'SEEN' if ctl_ok else '** NOT SEEN **'}")
    print(f"    pooled  {b[2]:+.5f} ± {s[2]:.5f}  ({t_pool:+.1f} sigma)"
          f"   pre-holdout {bp[2]:+.5f} ± {sp[2]:.5f}")
    print("    seasons " + "  ".join(f"{t:+.1f}" for t in per)
          + f"   -> {verdict}")


def main():
    rows = build()
    for cand in ("d_sec", "d_spin", "d_ivb", "d_zone"):
        screen(rows, cand, "y")
    screen(rows, "d_zone", "y_bb")
    sd = float(np.std([r["d_velo"] for r in rows]))
    print(f"\n  scale: d_velo sd on these rows is {sd:.3f} mph "
          f"(the shipped term is ~+0.016 K% per mph ~ +0.010 per sd)")

    # ADVERSARIAL CHECK on the survivor: does zone% add anything beyond
    # the BOX-SCORE walk drift? The velo term earned its place by beating
    # the box-score K streak; the same bar applies here, same sign gate.
    sub = [r for r in rows if r["d_zone"] is not None]
    zc = np.array([r["d_zone"] for r in sub])
    zc = (zc - zc.mean()) / zc.std()
    xb = np.array([r["d_bb"] for r in sub])
    y = np.array([r["y_bb"] for r in sub])
    X = np.column_stack([np.ones(len(y)), xb, zc])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    se = np.sqrt(np.diag(float(res @ res) / (len(y) - 3)
                         * np.linalg.inv(X.T @ X)))
    print(f"\n  ADVERSARIAL: y_bb ~ d_bb(box-score) + z(d_zone), n={len(y)}")
    print(f"    d_bb    {beta[1]:+.4f} ± {se[1]:.4f}  "
          f"({beta[1] / se[1]:+.1f} sigma)  <- walk-drift persistence")
    print(f"    d_zone  {beta[2]:+.5f} ± {se[2]:.5f}  "
          f"({beta[2] / se[2]:+.1f} sigma)  <- what the radar adds")
    for season in (2023, 2024, 2025, 2026):
        ss = [i for i, r in enumerate(sub) if r["season"] == season]
        Xs, ys = X[ss], y[ss]
        b2, *_ = np.linalg.lstsq(Xs, ys, rcond=None)
        r2 = ys - Xs @ b2
        s2 = np.sqrt(np.diag(float(r2 @ r2) / (len(ys) - 3)
                             * np.linalg.inv(Xs.T @ Xs)))
        print(f"    {season}  d_zone {b2[2]:+.5f} ± {s2[2]:.5f}  "
              f"({b2[2] / s2[2]:+.1f} sigma)")


if __name__ == "__main__":
    main()
