"""Is the boundary curve the SAME CURVE in every season, or an average?

    venv/bin/python -m scratchpad.split_boundary [--rebuild]

THE QUESTION, and it is the user's. The season gate compared BUCKET HAZARDS
across 2025 and 2026 and they matched almost exactly — pull rates 0.0645
against 0.0656 on ~40,000 decisions each. That agreement was flagged as
"almost concerning", and it should be: a hazard is one step removed from the
thing that ships. Two seasons can produce the same marginal pull rate out of
different curves — a steeper pitch term and a weaker traffic term trade off
against each other and cancel in the margin.

So fit the curve INDEPENDENTLY on each season and compare the COEFFICIENTS,
which is what `sim.Hook` actually reads.

THREE OUTCOMES AND THEY MEAN DIFFERENT THINGS:

  * Coefficients agree within their standard errors -> the pooled fit is
    legitimate and 89,983 decisions is one population.
  * They disagree -> the pooled fit is averaging two managers' eras together
    and the shipped curve is nobody's. Then the hook is season-scoped.
  * They agree FAR CLOSER than their standard errors -> that is not
    stability, it is the same rows fitted twice. `AN IDENTICAL-TO-FOUR-
    DECIMALS A/B IS PLUMBING, NEVER A NULL.` The `agree/se` column below is
    there to make that case loud instead of reassuring.

The standard errors are the point. Eyeballing "0.0645 against 0.0656" cannot
distinguish any of the three, and each pairwise gap is reported as a z so
the comparison is against sampling noise rather than against a feeling.

OUT-OF-SAMPLE IS THE TIEBREAK. Coefficients can differ and still predict
each other's seasons fine, which would mean the differences are in
directions the data does not care about. So every season's fitted curve is
also scored on every OTHER season's rows. If the 2025 curve prices 2026
decisions as well as the 2026 curve does, the stability is real whatever the
coefficients say.

FITTING TO REMOVAL DECISIONS IS PERMITTED. The target is what the manager
did, not what the game settled at — same footing as `fit_boundary.py`.
"""
from __future__ import annotations

import concurrent.futures as cf
import glob
import json
import multiprocessing as mp
import os
import statistics as st
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression

from src import db
from src.context import boundary, removal, sim

#: The features the shipped boundary curve reads, in its order.
FEATS = ("pitches", "runs", "br", "inning", "margin")

CACHE = "/tmp/boundary_rows_by_season.json"


def _seasons() -> dict[str, str]:
    """{pbp game id: season}. The pbp cache keys are bare gamePks and the
    pipeline DB prefixes them with the sport, hence the strip."""
    with db.connect() as c:
        return {r["game_id"].split("-")[-1]: r["date"][:4]
                for r in c.execute(
                    "select game_id, date from games where sport = 'mlb'")}


def _dates() -> dict[str, str]:
    with db.connect() as c:
        return {r["game_id"].split("-")[-1]: r["date"]
                for r in c.execute(
                    "select game_id, date from games where sport = 'mlb'")}


def drop_october(rows: list[dict]) -> list[dict]:
    """October and later — the postseason, plus the last days of the regular
    season, which is close enough for a sensitivity check.

    WHY IT IS WORTH ASKING. A postseason manager has a different hook and
    the three complete seasons carry one while 2026, in progress, does not:
    2023 has 56 such games, 2024 and 2025 have 43, 2026 has none. That is an
    asymmetry between exactly the seasons being compared, so it is a
    candidate explanation for the era shift and has to be ruled out rather
    than reasoned away. Note the direction runs the wrong way for it — the
    season with the MOST postseason is the one pulling LEAST — which is a
    reason to expect the check to pass, not a substitute for running it.
    """
    d = _dates()
    return [r for r in rows if (d.get(r["game_id"], "")[5:7] or "01") < "10"]


def _one(gid: str) -> list[dict]:
    try:
        return [r for r in boundary.decisions(gid) if r["ends_inning"]]
    except Exception:
        return []


def collect(rebuild: bool = False) -> list[dict]:
    if not rebuild and os.path.exists(CACHE):
        return json.load(open(CACHE))
    season = _seasons()
    gids = [os.path.basename(f).split(".")[0]
            for f in sorted(glob.glob(".cache/pbp/*.json.gz"))]
    gids = [g for g in gids if g in season]
    print(f"  collecting {len(gids):,} games", flush=True)
    rows: list[dict] = []
    workers = max(1, (os.cpu_count() or 4) - 1)
    with cf.ProcessPoolExecutor(max_workers=workers,
                                mp_context=mp.get_context("fork")) as pool:
        for i, got in enumerate(pool.map(_one, gids, chunksize=32)):
            for r in got:
                r["season"] = season[r["game_id"]]
            rows += got
            if (i + 1) % 2000 == 0:
                print(f"    {i+1:,}/{len(gids):,} games, {len(rows):,} rows",
                      flush=True)
    json.dump(rows, open(CACHE, "w"))
    return rows


def fit(rows: list[dict]) -> dict:
    """Unregularised logistic in the Hook's own form, plus standard errors.

    UNREGULARISED for the reason `fit_boundary.py` gives: the coefficients
    ARE the shipped parameters, so shrinking them toward zero ships a hook
    that is deliberately too flat. The standard errors come from the Fisher
    information at the solution, sqrt(diag(inv(X'WX))) with W = p(1-p) —
    the textbook logistic covariance, computed here because sklearn does not
    report one.
    """
    X = np.array([[float(r[f]) for f in FEATS] for r in rows])
    y = np.array([1 if r["removed"] else 0 for r in rows])
    m = LogisticRegression(max_iter=5000, C=1e6)
    m.fit(X, y)
    p = m.predict_proba(X)[:, 1]

    Xc = np.hstack([np.ones((len(X), 1)), X])
    W = p * (1 - p)
    cov = np.linalg.inv(Xc.T @ (Xc * W[:, None]))
    se = np.sqrt(np.diag(cov))

    names = ("const",) + FEATS
    beta = np.concatenate([m.intercept_, m.coef_[0]])
    return {
        "n": len(rows),
        "pull": float(y.mean()),
        "beta": dict(zip(names, beta)),
        "se": dict(zip(names, se)),
        "auc": removal.auc(y, p),
        "model": m,
        "pitch_center": st.mean(r["pitches"] for r in rows),
    }


def hook_of(f: dict) -> sim.Hook:
    """The fit, expressed as the object the simulator actually runs.

    `pitch_center` and `intercept` are not separately identified — only
    `intercept - pitch_center/pitch_scale` is — so the centre is PINNED at
    the mean pitch count of a real boundary decision and the intercept
    solved from it, exactly as `fit_boundary.py` does.
    """
    b = f["beta"]
    scale = 1.0 / b["pitches"]
    return sim.Hook(intercept=b["const"] + f["pitch_center"] * b["pitches"],
                    pitch_center=f["pitch_center"], pitch_scale=scale,
                    per_run=b["runs"], per_baserunner=b["br"],
                    per_inning=b["inning"], per_margin=b["margin"])


def score_on(f: dict, rows: list[dict]) -> tuple[float, float]:
    X = np.array([[float(r[c]) for c in FEATS] for r in rows])
    y = np.array([1 if r["removed"] else 0 for r in rows])
    p = f["model"].predict_proba(X)[:, 1]
    return removal.auc(y, p), removal.log_loss(y, p)


def main(argv):
    rows = collect(rebuild="--rebuild" in argv)
    if "--regular" in argv:
        before = len(rows)
        rows = drop_october(rows)
        print(f"  regular season only: {len(rows):,} rows, "
              f"{before - len(rows):,} dropped from October on")
    seasons = sorted({r["season"] for r in rows})
    by = {s: [r for r in rows if r["season"] == s] for s in seasons}
    print(f"\n  {len(rows):,} BOUNDARY decisions across {len(seasons)} seasons")

    fits = {s: fit(by[s]) for s in seasons}
    fits["pooled"] = fit(rows)

    print(f"\n  {'season':<10}{'n':>9}{'pull':>9}{'AUC':>9}")
    for s in seasons + ["pooled"]:
        f = fits[s]
        print(f"  {s:<10}{f['n']:>9,}{f['pull']:>9.4f}{f['auc']:>9.4f}")

    print(f"\n  COEFFICIENTS, each season fitted alone (se in brackets)")
    head = f"  {'term':<10}"
    for s in seasons + ["pooled"]:
        head += f"{s:>20}"
    print(head)
    for term in ("const",) + FEATS:
        line = f"  {term:<10}"
        for s in seasons + ["pooled"]:
            f = fits[s]
            line += f"{f['beta'][term]:>+13.4f} ({f['se'][term]:.4f})"
        print(line)

    # The comparison that answers the question. A z of 0 to 2 is agreement,
    # above 3 is a real difference, and BELOW about 0.2 across every term at
    # once is the plumbing signature — independent fits on ~40,000 rows each
    # do not land on top of each other.
    print(f"\n  2025 vs 2026, in standard errors of the difference")
    if "2025" in fits and "2026" in fits:
        a, b = fits["2025"], fits["2026"]
        print(f"  {'term':<16}{'2025':>12}{'2026':>12}{'diff':>12}{'z':>8}")
        zs = []
        for term in ("const",) + FEATS:
            d = b["beta"][term] - a["beta"][term]
            s = (a["se"][term] ** 2 + b["se"][term] ** 2) ** 0.5
            z = d / s if s else 0.0
            zs.append(abs(z))
            print(f"  {term:<16}{a['beta'][term]:>+12.4f}"
                  f"{b['beta'][term]:>+12.4f}{d:>+12.4f}{z:>+8.2f}")
        print(f"  max |z| {max(zs):.2f}, mean |z| {st.mean(zs):.2f}")

    print(f"\n  AS THE SIMULATOR READS THEM")
    print(f"  {'parameter':<18}" + "".join(f"{s:>10}"
                                           for s in seasons + ["pooled"])
          + f"{'shipped':>10}")
    cur = sim.Hook()
    hooks = {s: hook_of(fits[s]) for s in seasons + ["pooled"]}
    for name in ("intercept", "pitch_center", "pitch_scale", "per_run",
                 "per_baserunner", "per_inning", "per_margin"):
        line = f"  {name:<18}"
        for s in seasons + ["pooled"]:
            line += f"{getattr(hooks[s], name):>10.4f}"
        print(line + f"{getattr(cur, name):>10.4f}")

    # OUT OF SAMPLE. The diagonal is in-sample and will flatter itself; what
    # matters is how far each off-diagonal cell falls below the diagonal of
    # the column it sits in.
    print(f"\n  OUT OF SAMPLE — AUC of each season's curve on each season's"
          f" rows")
    print(f"  {'fitted on':<12}" + "".join(f"{s:>10}" for s in seasons)
          + "   (columns are the rows scored)")
    for s in seasons + ["pooled"]:
        line = f"  {s:<12}"
        for t in seasons:
            line += f"{score_on(fits[s], by[t])[0]:>10.4f}"
        print(line)

    print(f"\n  and the same cells as log loss, which is sensitive to the"
          f" LEVEL")
    print(f"  {'fitted on':<12}" + "".join(f"{s:>10}" for s in seasons))
    for s in seasons + ["pooled"]:
        line = f"  {s:<12}"
        for t in seasons:
            line += f"{score_on(fits[s], by[t])[1]:>10.4f}"
        print(line)

    # THE MODEL-FREE CHECK, and it is not optional. `pitches` and `inning`
    # are close to collinear in these rows, so a steeper pitch term with a
    # more negative inning term can be the SAME curve re-partitioned between
    # two features rather than a different one. A counted hazard by pitch
    # bucket cannot be re-partitioned — it is what the managers did.
    print("\n  OBSERVED HAZARD BY PITCH COUNT, counted per season")
    cc = np.corrcoef([float(r["pitches"]) for r in rows],
                     [float(r["inning"]) for r in rows])[0, 1]
    print(f"  corr(pitches, inning) in the pooled rows: {cc:.3f}")
    edges = [(0, 60), (60, 70), (70, 80), (80, 90), (90, 100), (100, 110),
             (110, 999)]
    print(f"  {'bucket':<12}" + "".join(f"{s:>16}" for s in seasons))
    for lo, hi in edges:
        line = f"  {f'{lo}-{hi}':<12}"
        for s in seasons:
            g = [r for r in by[s] if lo <= r["pitches"] < hi]
            if len(g) < 30:
                line += f"{'-':>16}"
                continue
            act = sum(1 for r in g if r["removed"]) / len(g)
            line += f"{act:>10.3f}{len(g):>6,}"
        print(line)


if __name__ == "__main__":
    main(sys.argv[1:])
