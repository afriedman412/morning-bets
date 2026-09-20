"""Item 36 stage 1 — usage-trend detection, pure data, no simulation.

    venv/bin/python -m scratchpad.usage_trend --control   control (run FIRST)
    venv/bin/python -m scratchpad.usage_trend             the registered read

QUESTION: is a managed-down arm (Leahy, Burns) visible in the usage
record — the within-season SLOPE of pitch count and fastball velocity —
beyond the trailing LEVEL, which item 35 already showed regresses?

One row per start with >= 7 prior same-season starts. Outcome is
tonight's pitches (outs secondary, in its own units). Regressors:
season-to-date mean, last-4 mean, LAST-4 OLS SLOPE (the term on trial),
rest days capped at 30; the velo channel adds the wired recent5-vs-season
level and the LAST-5 VELO SLOPE on the subset where velo exists.
Arm-clustered (CR0) se. Registered bar (TODO 36, set before any run):
slope >= 3 sigma pooled pre-holdout AND same sign all four seasons, with
both levels and rest in the fit. Control gate: an injected -8/start ramp
on the final five starts of a 10% md5 subset must read >= 5 sigma or the
real read does not run.

Leak-free by construction: every regressor reads starts STRICTLY BEFORE
the outcome start, same season (velo.py's lookup shape).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict

import numpy as np

from src.context import store
from src.context.holdout import HOLDOUT

VELO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "src", "context", "velo_starts.json")

MIN_PRIOR = 7          # prior same-season starts required for a row
WINDOW = 4             # pitch-count window, start units (item 35's J)
VELO_WINDOW = 5        # velo window, matching velo.py's recent5
REST_CAP = 30
CONTROL_SHARE = 10     # md5 % 10 == 0 -> ~10% of arm-seasons
CONTROL_RAMP = -8.0    # pitches per start, the injected Leahy
CONTROL_FLOOR = 45.0
CONTROL_STARTS = 5     # final N starts of the arm-season get the ramp


def load_starts():
    """(pitcher_id, name, season) -> [(date, pitches, outs)], date-ordered."""
    with store.connect() as con:
        rows = con.execute("""
            SELECT s.pitcher_id, s.player_name, s.date, s.game_id,
                   p.pitches, s.outs_recorded
            FROM mlb_stints s
            JOIN bets.mlb_pitching p
              ON p.game_id = s.game_id AND p.player_name = s.player_name
            WHERE s.appearance_order = 0
              AND p.is_starter = 1
              AND p.pitches IS NOT NULL AND p.pitches > 0
            ORDER BY s.date, s.game_id
        """).fetchall()
    seq = defaultdict(list)
    for r in rows:
        season = int(r["date"][:4])
        seq[(r["pitcher_id"], r["player_name"], season)].append(
            (r["date"], float(r["pitches"]), float(r["outs_recorded"])))
    return seq


def load_velo():
    with open(VELO_PATH) as f:
        table = json.load(f)
    return {(r["name"], r["date"]): r["velo"] for r in table}


def slope(ys):
    xs = np.arange(len(ys), dtype=float)
    xs -= xs.mean()
    ys = np.asarray(ys, float)
    return float(np.dot(xs, ys - ys.mean()) / np.dot(xs, xs))


def shuffle_null(seq):
    """Destroy any real within-season ordering: permute each arm-season's
    (pitches, outs) pairs across its dates, fixed seed. What survives in
    the slope term afterwards is harness artifact, not baseball."""
    rng = np.random.default_rng(0)
    for starts in seq.values():
        vals = [(p, o) for _, p, o in starts]
        rng.shuffle(vals)
        for i, (d, _, _) in enumerate(starts):
            starts[i] = (d, vals[i][0], vals[i][1])


def inject(seq):
    """The positive control: a -8/start ramp on the final CONTROL_STARTS
    starts of a 10% md5 subset of arm-seasons."""
    hit = 0
    for (pid, name, season), starts in seq.items():
        h = int(hashlib.md5(f"{pid}-{season}".encode()).hexdigest(), 16)
        if h % CONTROL_SHARE != 0 or len(starts) < MIN_PRIOR + CONTROL_STARTS:
            continue
        hit += 1
        base = np.mean([p for _, p, _ in starts[:-CONTROL_STARTS]])
        for k in range(CONTROL_STARTS):
            i = len(starts) - CONTROL_STARTS + k
            d, _, o = starts[i]
            ramped = max(CONTROL_FLOOR, base + CONTROL_RAMP * (k + 1))
            starts[i] = (d, ramped, o)
    return hit


def build_rows(seq, velo):
    rows = []
    for (pid, name, season), starts in seq.items():
        for i in range(MIN_PRIOR, len(starts)):
            prior = starts[:i]
            pitches = [p for _, p, _ in prior]
            outs = [o for _, _, o in prior]
            d0 = np.datetime64(prior[-1][0])
            d1 = np.datetime64(starts[i][0])
            rest = min(int((d1 - d0).astype(int)), REST_CAP)
            row = dict(
                pid=pid, season=season, date=starts[i][0],
                y_pitch=starts[i][1], y_outs=starts[i][2],
                s_pitch=np.mean(pitches), w_pitch=np.mean(pitches[-WINDOW:]),
                t_pitch=slope(pitches[-WINDOW:]),
                s_outs=np.mean(outs), w_outs=np.mean(outs[-WINDOW:]),
                t_outs=slope(outs[-WINDOW:]),
                rest=float(rest), idx=float(i),
            )
            row["t_neg"] = min(row["t_pitch"], 0.0)
            row["t_pos"] = max(row["t_pitch"], 0.0)
            vs = [velo.get((name, d)) for d, _, _ in prior]
            vs = [v for v in vs if v is not None]
            if len(vs) >= VELO_WINDOW:
                recent = float(np.mean(vs[-VELO_WINDOW:]))
                row["v_level"] = recent - float(np.mean(vs))
                row["v_slope"] = slope(vs[-VELO_WINDOW:])
            rows.append(row)
    return rows


FLAG_SLOPE = -8.0      # last-4 slope, pitches per start
FLAG_LEVEL = -8.0      # last-4 mean minus season-to-date mean, pitches


def flagged(r):
    """The Leahy signature: low AND still falling."""
    return (r["t_pitch"] <= FLAG_SLOPE
            and (r["w_pitch"] - r["s_pitch"]) <= FLAG_LEVEL)


def detector(rows, label):
    """Instrument v2. Level-only model fitted on unflagged rows, mean
    residual of the flagged, arm-clustered se. Negative = the decline
    continues below what the level alone says. The level model's own
    estimation error is ignored (unflagged n is ~50x flagged n)."""
    print(f"\n  DETECTOR — {label}")
    print(f"    flag: slope <= {FLAG_SLOPE:+.0f}/start AND last4-season "
          f"<= {FLAG_LEVEL:+.0f}")
    print(f"    {'cell':<16}{'n_flag':>7}{'arms':>6}{'mean_resid':>12}"
          f"{'se':>8}{'z':>7}")
    out = {}
    cells = [(str(s), [r for r in rows if r["season"] == s])
             for s in (2023, 2024, 2025, 2026)]
    cells.append(("pooled<HOLDOUT", [r for r in rows if r["date"] < HOLDOUT]))
    for name, rs in cells:
        fl = [r for r in rs if flagged(r)]
        un = [r for r in rs if not flagged(r)]
        if len(fl) < 10:
            print(f"    {name:<16}{len(fl):>7}   too thin")
            continue
        Xu = np.column_stack([np.ones(len(un))] +
                             [np.array([r[k] for r in un])
                              for k in ("s_pitch", "w_pitch", "rest")])
        yu = np.array([r["y_pitch"] for r in un])
        beta = np.linalg.lstsq(Xu, yu, rcond=None)[0]
        Xf = np.column_stack([np.ones(len(fl))] +
                             [np.array([r[k] for r in fl])
                              for k in ("s_pitch", "w_pitch", "rest")])
        resid = np.array([r["y_pitch"] for r in fl]) - Xf @ beta
        arms = np.array([r["pid"] for r in fl])
        m = resid.mean()
        var = sum((resid[arms == g].sum() - (arms == g).sum() * m) ** 2
                  for g in np.unique(arms)) / len(resid) ** 2
        se = np.sqrt(var)
        print(f"    {name:<16}{len(fl):>7}{len(np.unique(arms)):>6}"
              f"{m:>+12.2f}{se:>8.2f}{m / se:>+7.1f}")
        out[name] = (m, se, len(fl))
    return out


def det_read(rows):
    """The detector's scalar: mean flagged residual, pre-holdout rows,
    level model fitted on the same rows' unflagged part."""
    rs = [r for r in rows if r["date"] < HOLDOUT]
    fl = [r for r in rs if flagged(r)]
    un = [r for r in rs if not flagged(r)]
    if len(fl) < 10:
        return None

    def mat(sub):
        return np.column_stack([np.ones(len(sub))] +
                               [np.array([r[k] for r in sub])
                                for k in ("s_pitch", "w_pitch", "rest")])
    beta = np.linalg.lstsq(mat(un), np.array([r["y_pitch"] for r in un]),
                           rcond=None)[0]
    resid = np.array([r["y_pitch"] for r in fl]) - mat(fl) @ beta
    return float(resid.mean())


def boot_gate(rows_clean, rows_inj, reps=400):
    """Paired arm-clustered bootstrap of det_read(inj) - det_read(clean).
    The two reads share their innocent rows, so an unpaired se
    overstates the difference's error (the item-32 lesson). Both reads
    are computed inside each resample of ARMS."""
    by_arm_c = defaultdict(list)
    by_arm_i = defaultdict(list)
    for r in rows_clean:
        by_arm_c[r["pid"]].append(r)
    for r in rows_inj:
        by_arm_i[r["pid"]].append(r)
    arms = sorted(set(by_arm_c) | set(by_arm_i))
    d_hat = det_read(rows_inj) - det_read(rows_clean)
    rng = np.random.default_rng(1)
    ds = []
    for _ in range(reps):
        pick = rng.choice(len(arms), size=len(arms), replace=True)
        rc, ri = [], []
        for j in pick:
            rc.extend(by_arm_c[arms[j]])
            ri.extend(by_arm_i[arms[j]])
        mc, mi = det_read(rc), det_read(ri)
        if mc is None or mi is None:
            continue
        ds.append(mi - mc)
    return d_hat, float(np.std(ds)), len(ds)


def cr0(X, y, clusters):
    """OLS with CR0 arm-clustered se. Returns beta, se."""
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    u = y - X @ beta
    meat = np.zeros((X.shape[1], X.shape[1]))
    for g in np.unique(clusters):
        m = clusters == g
        s = X[m].T @ u[m]
        meat += np.outer(s, s)
    V = XtX_inv @ meat @ XtX_inv
    return beta, np.sqrt(np.diag(V))


def fit(rows, names, outcome, label):
    """One regression per season + pooled pre-holdout; prints the slope
    terms' beta/se/z and returns them keyed by term."""
    def matrix(rs):
        X = np.column_stack([np.ones(len(rs))] + [np.array([r[n] for r in rs])
                                                  for n in names])
        y = np.array([r[outcome] for r in rs])
        c = np.array([r["pid"] for r in rs])
        return X, y, c

    print(f"\n  {label}   n={len(rows)}  arms={len({r['pid'] for r in rows})}")
    print(f"    {'term':<10} " + " ".join(f"{s:>22}" for s in
          ["2023", "2024", "2025", "2026", "pooled<HOLDOUT"]))
    out = {}
    cells = []
    for season in (2023, 2024, 2025, 2026):
        cells.append([r for r in rows if r["season"] == season])
    cells.append([r for r in rows if r["date"] < HOLDOUT])
    results = []
    for rs in cells:
        X, y, c = matrix(rs)
        b, se = cr0(X, y, c)
        results.append((b, se, len(rs)))
    for j, n in enumerate(names, start=1):
        if not n.startswith(("t_", "v_")):
            continue
        line = f"    {n:<10} "
        for b, se, _ in results:
            z = b[j] / se[j]
            line += f" {b[j]:+7.3f} ({se[j]:.3f}) z{z:+5.1f}"
        print(line)
        out[n] = [(r[0][j], r[1][j]) for r in results]
    print(f"    {'rows':<10} " + " ".join(f"{r[2]:>22}" for r in results))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", action="store_true")
    args = ap.parse_args()

    seq = load_starts()
    velo = load_velo()

    if args.control:
        print("CONTROLS, both on WITHIN-ARM-SEASON SHUFFLED data so the "
              "gate is blind to any real signal.")
        shuffle_null(seq)
        rows = build_rows(seq, velo)
        res = fit(rows, ["s_pitch", "w_pitch", "t_pitch", "rest"],
                  "y_pitch",
                  "PITCHES ~ season + last4 + SLOPE + rest  [SHUFFLED]")
        b0, se0 = res["t_pitch"][4]
        print(f"\n  SPECIFICITY: shuffled-clean slope z = {b0 / se0:+.1f} "
              "(anything past ~2 is a harness artifact)")
        detector(rows, "shuffled clean")
        rows_clean = rows
        hit = inject(seq)
        print(f"\n  SENSITIVITY — ramp {CONTROL_RAMP:+.0f}/start, final "
              f"{CONTROL_STARTS} starts, {hit} of {len(seq)} arm-seasons")
        rows = build_rows(seq, velo)
        res = fit(rows, ["s_pitch", "w_pitch", "t_pitch", "rest"],
                  "y_pitch",
                  "PITCHES ~ season + last4 + SLOPE + rest  [SHUF+INJECT]")
        b, se = res["t_pitch"][4]
        z = (b - b0) / se
        print(f"\n  v1 GATE (global slope, FAILED 2026-09-19): "
              f"injected-minus-clean z = {z:+.1f} against 5")
        detector(rows, "shuffled + injected")
        d, se_d, reps = boot_gate(rows_clean, rows)
        zd = d / se_d
        verdict = ("PASS — the real read may run" if zd <= -5
                   else "FAIL — harness blind, do not run the read")
        print(f"\n  v2 GATE (detector, registered): injected-minus-clean "
              f"<= -5 sigma pooled pre-holdout, PAIRED arm-clustered "
              f"bootstrap ({reps} reps).\n  READ: d = {d:+.2f} pitches, "
              f"se {se_d:.2f}, z = {zd:+.1f}  -> {verdict}")
        return

    print("ITEM 36 STAGE 1 — the registered read"
          " (control must have passed first)")
    rows = build_rows(seq, velo)
    fit(rows, ["s_pitch", "w_pitch", "t_pitch", "rest"],
        "y_pitch", "PITCHES ~ season + last4 + SLOPE + rest")
    fit(rows, ["s_outs", "w_outs", "t_outs", "rest"],
        "y_outs", "OUTS    ~ season + last4 + SLOPE + rest  [secondary]")
    vrows = [r for r in rows if "v_slope" in r]
    fit(vrows, ["s_pitch", "w_pitch", "t_pitch", "rest", "v_level", "v_slope"],
        "y_pitch", "PITCHES ~ ... + velo level + VELO SLOPE  [velo subset]")
    detector(rows, "REAL DATA — the v2 instrument on trial")
    print("\n  POST-HOC ROBUSTNESS on the passed positive (not registered):")
    fit(rows, ["s_pitch", "w_pitch", "t_pitch", "rest", "idx"],
        "y_pitch", "PITCHES ~ ... + START INDEX (calendar proxy control)")
    fit(rows, ["s_pitch", "w_pitch", "t_neg", "t_pos", "rest"],
        "y_pitch", "PITCHES ~ ... slope split by SIGN (t_neg / t_pos)")
    print("\nBARS (TODO 36): v2 detector mean residual <= -3 sigma pooled "
          "pre-holdout AND negative in >= 3/4 seasons. Global slope is "
          "reported but its NULL is uninformative (v1 gate failed).")


if __name__ == "__main__":
    main()
