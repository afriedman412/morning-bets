"""STEP THREE — does pitch-level expectation predict the NEXT start?

    venv/bin/python -m scratchpad.expect_screen

The reliability work (expect_league) established two real per-start
quantities, both measured within-pitcher against a negative control on
17,762 starts:

    the EXPECTATION   what his pitch selection and locations deserved,
                      split-half SB 0.54 with the batter rung in
    the RESIDUAL      what he got beyond that, SB 0.22, and it SURVIVED
                      the batter rung (+0.143 -> +0.124), so it is not
                      merely "who he faced"

Reliable is not useful. This asks the only question that ships: does a
DRIFT in either — recent five starts against his own season-to-date mean
— predict the NEXT start's strikeout or walk rate, BEYOND the two terms
already wired (velo->K, zone->BB)?

THE BAR, pre-registered in PLAN-pitch-expectation before this ran and
restated here: |t| >= 3 pooled with velo AND zone controlled, AND the
same sign in all four seasons. 2-3 sigma with consistent signs is logged,
not wired. Anything else is dead. A survivor is refit on date <
2026-07-01 before any constant is quoted.

POSITIVE CONTROL per candidate, planted at the size of the shipped velo
term (~0.010 K% per sd) — a screen that cannot see a known effect cannot
report a null.

ONE CONSERVATIVE BIAS, stated not hidden: the E1 batter offsets were
counted on train pitches, so for pre-holdout starts the residual has a
sliver of its own noise subtracted out. That ATTENUATES the residual
candidate rather than inflating it, which is the safe direction for a
screen; a survivor would be understated, not manufactured.
"""
from __future__ import annotations

import json

import numpy as np

from src import db

MIN_PRIOR_STARTS = 10
RECENT = 5
MIN_T_BF = 15
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
    vals = [v for v in series if v is not None]
    rec = [v for v in series[-RECENT:] if v is not None]
    if len(vals) < 5 or len(rec) < 3:
        return None
    return sum(rec) / len(rec) - sum(vals) / len(vals)


def build():
    exp = {(r["name"], r["date"]): r
           for r in json.load(open("scratchpad/expect_starts.json"))}
    phys = {(r["name"], r["date"]): r
            for r in json.load(open("src/context/velo_starts.json"))}
    rows, byp = [], {}
    for r in starts():
        r["bf"] = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
        if r["bf"] >= 1:
            byp.setdefault(r["name"], []).append(r)
    for name, rs in byp.items():
        for season in {r["d"][:4] for r in rs}:
            ss = [r for r in rs if r["d"][:4] == season]
            es = [exp.get((name, r["d"])) for r in ss]
            ps = [phys.get((name, r["d"])) for r in ss]
            for t in range(MIN_PRIOR_STARTS, len(ss)):
                prior, tgt = ss[:t], ss[t]
                if tgt["bf"] < MIN_T_BF:
                    continue
                bf_p = sum(r["bf"] for r in prior)
                k_p = sum(r["k"] for r in prior) / bf_p
                bb_p = sum(r["bb"] for r in prior) / bf_p
                ep, pp = es[:t], ps[:t]

                def col(src, fn):
                    return drift([fn(x) if x else None for x in src])

                d_velo = col(pp, lambda x: x["velo"])
                d_zone = col(pp, lambda x: x.get("zone"))
                if d_velo is None or d_zone is None:
                    continue
                rows.append({
                    "season": int(season), "date": tgt["d"],
                    "y": tgt["k"] / tgt["bf"] - k_p,
                    "y_bb": tgt["bb"] / tgt["bf"] - bb_p,
                    "d_velo": d_velo, "d_zone": d_zone,
                    # the two candidates
                    "d_exp": col(ep, lambda x: x["e_whiff"] / x["n"]),
                    "d_res": col(ep, lambda x: (x["a_whiff"] - x["e_whiff"])
                                 / x["n"]),
                    # and the command-channel pair, for the BB target
                    "d_expb": col(ep, lambda x: x["e_ball"] / x["n"]),
                    "d_resb": col(ep, lambda x: (x["a_ball"] - x["e_ball"])
                                  / x["n"]),
                })
    print(f"  {len(rows):,} start-rows with velo+zone; candidate coverage:")
    for c in ("d_exp", "d_res", "d_expb", "d_resb"):
        n = sum(1 for r in rows if r[c] is not None)
        print(f"    {c:<8}{n:,}  ({n / len(rows):.1%})")
    return rows


def fit(rows, cand, ykey):
    """y ~ 1 + d_velo + d_zone + z(candidate). Both shipped terms are
    controls so the candidate must earn what it adds, not re-sell them."""
    sub = [r for r in rows if r[cand] is not None]
    xc = np.array([r[cand] for r in sub], dtype=float)
    sd = xc.std() or 1
    X = np.column_stack([np.ones(len(sub)),
                         [r["d_velo"] for r in sub],
                         [r["d_zone"] for r in sub],
                         xc / sd])
    y = np.array([r[ykey] for r in sub])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    se = np.sqrt(np.diag(float(res @ res) / (len(y) - 4)
                         * np.linalg.inv(X.T @ X)))
    return beta, se, sd, sub


def screen(rows, cand, ykey):
    rng = np.random.default_rng(11)
    sub = [r for r in rows if r[cand] is not None]
    xc = np.array([r[cand] for r in sub], dtype=float)
    zc = (xc - xc.mean()) / (xc.std() or 1)
    fake = [dict(r, fk=0.010 * zc[i] + rng.normal(0, 0.08))
            for i, r in enumerate(sub)]
    b, s, *_ = fit(fake, cand, "fk")
    ctl = abs(b[3] / s[3])

    b, s, sd, sub = fit(rows, cand, ykey)
    t = b[3] / s[3]
    per = []
    for season in (2023, 2024, 2025, 2026):
        ss = [r for r in sub if r["season"] == season]
        bb_, ss_, *_ = fit(ss, cand, ykey)
        per.append(bb_[3] / ss_[3])
    pre = [r for r in sub if r["date"] < HOLDOUT]
    bp, sp, *_ = fit(pre, cand, ykey)
    same = all(np.sign(x) == np.sign(t) for x in per)
    verdict = ("ALIVE" if abs(t) >= 3 and same else
               "WEAK" if abs(t) >= 2 and same else "dead")
    print(f"\n  {cand} -> {ykey}   n={len(sub):,}  sd={sd:.4g}  "
          f"control {ctl:.0f} sigma "
          f"{'SEEN' if ctl > 5 else '** NOT SEEN **'}")
    print(f"    pooled  {b[3]:+.5f} ± {s[3]:.5f}  ({t:+.1f} sigma)"
          f"   pre-holdout {bp[3]:+.5f} ± {sp[3]:.5f}")
    print("    seasons " + "  ".join(f"{x:+.1f}" for x in per)
          + f"   -> {verdict}")
    # what the controls themselves are doing, so a candidate that merely
    # re-expresses velocity is visible rather than credited
    print(f"    (controls in the same fit: velo {b[1]:+.4f}±{s[1]:.4f}, "
          f"zone {b[2]:+.4f}±{s[2]:.4f})")


def main():
    rows = build()
    for cand in ("d_exp", "d_res"):
        screen(rows, cand, "y")
    for cand in ("d_expb", "d_resb"):
        screen(rows, cand, "y_bb")


if __name__ == "__main__":
    main()
