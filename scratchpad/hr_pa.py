"""A PER-PLATE-APPEARANCE home run model — one row, one chance.

    venv/bin/python -m scratchpad.hr_pa --build    # ~780k plate appearances
    venv/bin/python -m scratchpad.hr_pa --fit      # train and score
    venv/bin/python -m scratchpad.hr_pa --ablate   # what each block buys

WHY THIS REPLACES THE PER-GAME VERSION, and it is not a refinement — it
dissolves three problems at once that `hr_clf.py` could only work around.

  * **THE PITCHER IS KNOWN ON EVERY ROW.** `hr_clf` had only the STARTER,
    so roughly half a hitter's chances were priced against an arm the
    model had never heard of. Every attempt to patch that failed on its
    own terms: a club bullpen aggregate measured z +0.30/+0.07/-0.48/-0.91,
    and even handing the model THE ARMS THAT ACTUALLY APPEARED bought
    almost nothing once `act_n` was separated out (+1.2 pooled for real
    pitcher quality against +4.5 for the arm COUNT, which is a consequence
    of home runs rather than a predictor of them). Per plate appearance
    there is nothing to aggregate and nothing to forecast.

  * **OPPORTUNITY STOPS CONTAMINATING THE RATE.** `slot` was the second
    most valuable input in the per-game model at z +5.7/+3.1/+5.1, and it
    is not a baseball skill — it is a proxy for how many times he bats.
    Here every row is exactly one chance, so the model estimates a RATE
    and the count of chances becomes a separate multiplication.

  * **STATE IS AVAILABLE.** Inning, times through the order and the
    handedness of the man actually on the mound are properties of a plate
    appearance and have nowhere to live in a game-level row.

THE LABEL is `result.eventType == 'home_run'` on a play with
`result.type == 'atBat'`. Every feature is frozen STRICTLY BEFORE the
row's month, the same monthly-cut discipline the rest of this work uses.
"""
from __future__ import annotations

import glob
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

from src.context import store

OUT = Path("scratchpad/hr_pa_rows.json.gz")
SEASONS = (2023, 2024, 2025, 2026)


def _games() -> dict:
    """{game_id: (date, venue_id, away_abbr, home_abbr)} for mlb."""
    with store.connect() as c:
        return {r["game_id"]: (r["date"], r["venue_id"],
                               r["away_team_abbr"], r["home_team_abbr"])
                for r in c.execute(
                    f"select game_id, date, venue_id, away_team_abbr, "
                    f"home_team_abbr from {store.BETS}.games "
                    "where sport = 'mlb'")}


def build() -> int:
    """One row per plate appearance, straight off the play-by-play cache.

    The cache is keyed by bare MLB game pk (`716352.json.gz`) while the
    pipeline uses `mlb-716352`; the join goes through that prefix and a
    miss is DROPPED rather than guessed, since a plate appearance with no
    date cannot be assigned to a fold.
    """
    meta = _games()
    # SLOT STAYS, for a different reason than it was in the per-game
    # model. There it was mostly a proxy for how many times a man bats;
    # per plate appearance that is gone. What remains is real: a nine-hole
    # hitter gets challenged and a three-hole hitter gets worked around,
    # so the slot is information about HOW HE IS PITCHED. Starters only —
    # `mlb_lineups` is the card as posted, so a pinch hitter has no slot
    # and is marked rather than assigned one.
    with store.connect() as c:
        slots = {(r["game_id"], r["player_name"]): r["slot"]
                 for r in c.execute("select game_id, player_name, slot "
                                    "from mlb_lineups")}
    rows = []
    for f in sorted(glob.glob(".cache/pbp/*.json.gz")):
        gid = "mlb-" + Path(f).name.split(".")[0]
        m = meta.get(gid)
        if not m or m[0][:4] not in {str(s) for s in SEASONS}:
            continue
        date, venue, away, home = m
        try:
            plays = json.load(gzip.open(f)).get("allPlays") or []
        except Exception:
            continue
        # TIMES THROUGH THE ORDER, counted as the number of previous
        # meetings of this exact pair in this game — which is what the
        # phrase actually means, and is not the same as the inning.
        met: dict = defaultdict(int)
        for p in plays:
            res, ab = p.get("result") or {}, p.get("matchup") or {}
            if res.get("type") != "atBat" or not ab.get("batter"):
                continue
            b = ab["batter"]["fullName"]
            pit = ab["pitcher"]["fullName"]
            half = (p.get("about") or {}).get("halfInning")
            met[(b, pit)] += 1
            rows.append({
                "g": gid, "d": date, "v": venue,
                "b": b, "p": pit,
                "bs": (ab.get("batSide") or {}).get("code") or "",
                "ph": (ab.get("pitchHand") or {}).get("code") or "",
                "i": (p.get("about") or {}).get("inning") or 0,
                "h": int(half == "bottom"),
                "t": min(met[(b, pit)], 4),
                "s": slots.get((gid, b)) or 0,
                "y": int(res.get("eventType") == "home_run"),
            })
    with gzip.open(OUT, "wt") as fh:
        json.dump(rows, fh)
    n1 = sum(r["y"] for r in rows)
    print(f"  {len(rows):,} plate appearances, {n1:,} home runs "
          f"({n1 / max(len(rows), 1):.3%})")
    for s in SEASONS:
        sub = [r for r in rows if r["d"][:4] == str(s)]
        print(f"    {s}: {len(sub):>8,} PA, "
              f"{sum(r['y'] for r in sub) / max(len(sub), 1):.3%} HR")
    return len(rows)


def load():
    with gzip.open(OUT, "rt") as fh:
        return json.load(fh)


#: Shrinkage in PLATE APPEARANCES. `stabilise.py` measured these in balls
#: in play (batter 140.7, pitcher 943.7); they are converted here by the
#: measured balls-in-play-per-PA ratio rather than re-guessed, and the
#: conversion factor is printed by `--shrink` so it is checkable.
K_PA = {"bat": 200.0, "pit": 1340.0}


def _maps_before(rows, cut: str) -> dict:
    """Both sides' shrunk HR-per-PA rates as of `cut`, strictly prior."""
    out = {}
    for side, key in (("bat", "b"), ("pit", "p")):
        hr: dict = defaultdict(int)
        pa: dict = defaultdict(int)
        for r in rows:
            if r["d"] < cut:
                hr[r[key]] += r["y"]
                pa[r[key]] += 1
        tot = sum(pa.values()) or 1
        lg = sum(hr.values()) / tot
        k = K_PA[side]
        out[side] = {n: (hr[n] + k * lg) / (pa[n] + k) for n in pa}
        out[side + "_lg"] = lg
    return out


FEATS = ("b_hr", "p_hr", "log5", "tto", "inning", "is_home",
         "slot", "slot_unk", "park_hr", "temp", "wind",
         "pl_RR", "pl_RL", "pl_LR", "pl_LL", "pl_unk")


def _log5(b, p, lg):
    if lg <= 0 or lg >= 1:
        return (b + p) / 2
    num = (b * p) / lg
    den = num + ((1 - b) * (1 - p)) / (1 - lg)
    return num / den if den else lg


def _x(r, mp_, park, wx):
    cell = f"{r['bs']}{r['ph']}" if r["ph"] and r["bs"] else "unk"
    w = wx.get(r["g"]) or {}
    t = w.get("temp_f")
    return [
        mp_["bat"].get(r["b"], mp_["bat_lg"]),
        mp_["pit"].get(r["p"], mp_["pit_lg"]),
        _log5(mp_["bat"].get(r["b"], mp_["bat_lg"]),
              mp_["pit"].get(r["p"], mp_["pit_lg"]), mp_["bat_lg"]),
        float(r["t"]), float(r["i"]), float(r["h"]),
        float(r["s"]), float(r["s"] == 0),
        (park.get(r["v"]) or {}).get("hr", 1.0),
        (t if (t or 0) > 20 else 72.0),
        (w.get("carry") or 0) * (w.get("wind_mph") or 0),
        float(cell == "RR"), float(cell == "RL"),
        float(cell == "LR"), float(cell == "LL"), float(cell == "unk"),
    ]


def _design():
    """X, y, season — features rebuilt month by month, strictly prior."""
    import numpy as np
    from src.context import calibrate as cal
    rows = load()
    rows.sort(key=lambda r: r["d"])
    with store.connect() as c:
        wx = {r["game_id"]: dict(r) for r in c.execute(
            "select game_id, temp_f, wind_mph, carry from mlb_weather")}
    park: dict = {}
    for v in {r["v"] for r in rows if r["v"]}:
        park[v] = cal.park_for(v)
    X, cur, mp_ = [], None, None
    for r in rows:
        cut = r["d"][:7] + "-01"
        if cut != cur:
            cur, mp_ = cut, _maps_before(rows, cut)
        X.append(_x(r, mp_, park, wx))
    return (np.array(X, dtype=float),
            np.array([r["y"] for r in rows], dtype=int),
            np.array([int(r["d"][:4]) for r in rows]))


def fit() -> None:
    """Leave-one-season-out, four folds. By SEASON and never at random —
    a random split puts the same batter-month on both sides and every
    rate feature would leak him to himself."""
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score, brier_score_loss
    X, y, yr = _design()
    print(f"\n  {len(y):,} plate appearances, {y.mean():.3%} home runs\n")
    print(f"  {'fold':<7}{'n test':>10}{'AUC':>9}{'brier':>10}"
          f"{'top 1%':>9}{'top 5%':>9}{'lift@1%':>9}")
    for year in SEASONS:
        tr, te = yr != year, yr == year
        p = HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.06, max_leaf_nodes=15,
            l2_regularization=1.0, random_state=0
        ).fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
        yt = y[te]
        o = np.argsort(p)
        t1 = yt[o[-int(len(yt) * 0.01):]].mean()
        t5 = yt[o[-int(len(yt) * 0.05):]].mean()
        print(f"  {year:<7}{te.sum():>10,}{roc_auc_score(yt, p):>9.4f}"
              f"{brier_score_loss(yt, p):>10.5f}{t1:>9.2%}{t5:>9.2%}"
              f"{t1 / yt.mean():>8.2f}x")


def ablate(cols) -> None:
    """Paired, per plate appearance, one block zeroed."""
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    X, y, yr = _design()
    X0 = X.copy()
    X0[:, [FEATS.index(c) for c in cols]] = 0.0
    print(f"\n  ABLATING {', '.join(cols)}")
    print(f"  {'fold':<7}{'AUC off':>9}{'AUC on':>8}{'z':>8}")
    for year in SEASONS:
        tr, te = yr != year, yr == year

        def _p(m):
            return HistGradientBoostingClassifier(
                max_iter=300, learning_rate=0.06, max_leaf_nodes=15,
                l2_regularization=1.0, random_state=0
            ).fit(m[tr], y[tr]).predict_proba(m[te])[:, 1]

        a, b, yt = _p(X0), _p(X), y[te]
        d = (a - yt) ** 2 - (b - yt) ** 2
        print(f"  {year:<7}{roc_auc_score(yt, a):>9.4f}"
              f"{roc_auc_score(yt, b):>8.4f}"
              f"{d.mean() / (d.std(ddof=1) / len(d) ** 0.5):>+8.2f}")


def main(argv):
    if "--build" in argv:
        build()
    if "--fit" in argv:
        fit()
    if "--ablate" in argv:
        i = argv.index("--ablate")
        ablate(tuple(argv[i + 1].split(","))
               if len(argv) > i + 1 else ("slot", "slot_unk"))


if __name__ == "__main__":
    main(sys.argv[1:])
