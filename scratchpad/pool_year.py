"""Pool every season and model the DRIFT, instead of discarding old seasons.

    venv/bin/python -m scratchpad.pool_year

THE ARGUMENT, and it is the user's. The era gate as applied today is
"do the seasons differ? if so, use only the recent ones." That spends data
to avoid a bias. The alternative is to keep all four seasons and give the
model a YEAR term, so the shared structure is estimated on 4x the rows while
the part that actually moved stays free.

A YEAR DUMMY IS NOT ENOUGH AND THAT IS THE WHOLE DESIGN QUESTION. The
boundary curve's drift is in the SLOPE — `pitch_scale` runs 22.4 / 16.2 /
11.8 / 12.6 across 2023-2026 — so a dummy that shifts the level up or down
leaves the real difference untouched. Year is therefore INTERACTED with
every term, centred on 2026, so that evaluating at year = 2026 makes the
interaction vanish and the main effects ARE the 2026 curve.

HELD OUT PROPERLY, because this is a claim about prediction and not about
fit. Train on 2023-2025 plus the first 70% of 2026 by date; test on the last
30% of 2026. Three arms on identical rows:

    pooled+year   every season, year interacted   <- the proposal
    era           2025 + 2026 only                <- what ships
    recent        2026 only                       <- the strictest cut

If the proposal is right it wins on the 2026 test rows, because it has four
seasons of evidence about the terms that did not move.
"""
from __future__ import annotations

import sys

import numpy as np
from sklearn.linear_model import LogisticRegression

from src import db
from src.context import removal
from scratchpad import split_boundary as sb

FEATS = ("pitches", "runs", "br", "inning", "margin")


def dated_rows():
    with db.connect() as c:
        date = {r["game_id"].split("-")[-1]: r["date"]
                for r in c.execute(
                    "select game_id, date from games where sport = 'mlb'")}
    rows = sb.collect(rebuild=False)
    for r in rows:
        r["date"] = date.get(r["game_id"], "")
    return [r for r in rows if r["date"]]


def design(rows, with_year):
    """X, y. `with_year` adds year-centred main and interaction terms."""
    X, y = [], []
    for r in rows:
        base = [float(r[f]) for f in FEATS]
        if with_year:
            yc = float(int(r["season"]) - 2026)      # 0 in 2026
            base = base + [yc] + [yc * v for v in base]
        X.append(base)
        y.append(1 if r["removed"] else 0)
    return np.array(X), np.array(y)


def fit_score(train, test, with_year, label):
    Xtr, ytr = design(train, with_year)
    Xte, yte = design(test, with_year)
    m = LogisticRegression(max_iter=8000, C=1e6)
    m.fit(Xtr, ytr)
    p = m.predict_proba(Xte)[:, 1]
    ll, auc = removal.log_loss(yte, p), removal.auc(yte, p)
    print(f"  {label:<16}{len(train):>9,}{ll:>11.5f}{auc:>9.4f}")
    return ll, auc, m


def main(argv):
    rows = dated_rows()
    y26 = sorted(r["date"] for r in rows if r["season"] == "2026")
    cut = y26[int(len(y26) * 0.70)]
    test = [r for r in rows if r["season"] == "2026" and r["date"] >= cut]
    tr_all = [r for r in rows if r["date"] < cut]
    print(f"  train < {cut}, test = the last 30% of 2026 "
          f"({len(test):,} rows)\n")
    print(f"  {'arm':<16}{'train n':>9}{'log loss':>11}{'AUC':>9}")
    res = {}
    res["pooled+year"] = fit_score(tr_all, test, True, "pooled+year")
    res["era"] = fit_score([r for r in tr_all if r["season"] in ("2025",
                                                                "2026")],
                           test, False, "era (25+26)")
    res["recent"] = fit_score([r for r in tr_all if r["season"] == "2026"],
                              test, False, "recent (26)")
    res["pooled flat"] = fit_score(tr_all, test, False, "pooled, NO year")

    best = min(res.items(), key=lambda kv: kv[1][0])
    print(f"\n  best log loss: {best[0]}")
    print("\n  'pooled, NO year' is the control: it is what naive pooling")
    print("  does, and the gap between it and 'pooled+year' is what the")
    print("  year term is worth.")


if __name__ == "__main__":
    main(sys.argv[1:])
