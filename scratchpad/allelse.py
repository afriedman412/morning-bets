"""Are the between-game nulls actually ALL-ELSE-EQUAL? Joint, within-pitcher.

`between.py` correlated each candidate with the residual ONE AT A TIME. The
residual is a real control — it has already removed everything the model
knows about the matchup — but it is not the only one that matters, and two
gaps are left:

  * THE CANDIDATES ARE CORRELATED WITH EACH OTHER. A club's home park, the
    share of its games played at night, and the quality of its own roster
    all travel together. A univariate test hands the shared variance to
    whichever feature is asked first.

  * THE PITCHER IS NOT HELD FIXED. Coors hosts Colorado's staff far more
    than anyone else's, so "starts in a hitter park" is partly "starts by
    Colorado pitchers". Demeaning the residual WITHIN PITCHER compares the
    same man across parks, days and travel, which is the actual
    counterfactual — a pitcher throws roughly half his starts at home, so
    the contrast survives demeaning.

Both are reported so the difference is visible rather than asserted.

    venv/bin/python -m scratchpad.allelse [stat] [rows.json]
"""
import statistics as st
import sys
from collections import defaultdict

import numpy as np

from scratchpad.between import load, park_index, pen_workload, rest_days
from scratchpad.between import _prev


def design(rows, stat, weather=False):
    pk, rest, pen = park_index(), rest_days(rows), pen_workload()
    wx = {}
    if weather:
        from src.context.sources import weather as wx_src
        wx = wx_src.by_game()
    feats, keep = {}, []
    for i, r in enumerate(rows):
        v = pk.get(r["venue_id"])
        dn = r["day_night"]
        rs = rest.get(i)
        p1 = pen.get((_prev(r["date"], 1), r["team"]))
        if v is None or dn not in ("day", "night") or rs is None \
                or p1 is None or not (3 <= rs <= 7):
            continue
        w = wx.get(r["game_id"]) if wx else None
        if wx:
            # A CLOSED ROOF IS NOT CALM WEATHER. It is no weather by
            # construction, and pooling it with real still days dilutes
            # whatever effect exists outdoors.
            if not w or w["roof_closed"] or w["temp_f"] is None:
                continue
        keep.append(i)
        if wx:
            feats.setdefault("temp F", []).append(float(w["temp_f"]))
            # speed alone is useless: 15 out and 15 in are opposite effects
            # with the same number, and they average to zero
            feats.setdefault("wind carry", []).append(
                float(w["wind_mph"] * w["carry"]))
            feats.setdefault("wind speed", []).append(float(w["wind_mph"]))
        feats.setdefault("park runs idx", []).append(v)
        feats.setdefault("is_home", []).append(float(r["is_home"]))
        feats.setdefault("night game", []).append(1.0 if dn == "night" else 0.0)
        feats.setdefault("days rest", []).append(float(rs))
        feats.setdefault("pen outs y'day", []).append(float(p1))
        feats.setdefault("month", []).append(float(r["date"][5:7]))
    y = np.array([rows[i][f"a_{stat}"] - rows[i][f"m_{stat}"] for i in keep])
    names = list(feats)
    X = np.column_stack([np.array(feats[n], dtype=float) for n in names])
    who = [rows[i]["player"] for i in keep]
    return names, X, y, who


def demean(X, y, who):
    """Within-pitcher demeaning: the fixed effect, done by centring."""
    idx = defaultdict(list)
    for i, p in enumerate(who):
        idx[p].append(i)
    Xd, yd = X.copy().astype(float), y.copy().astype(float)
    for _p, ii in idx.items():
        if len(ii) < 2:
            Xd[ii] = 0.0
            yd[ii] = 0.0
            continue
        Xd[ii] -= Xd[ii].mean(axis=0)
        yd[ii] -= yd[ii].mean()
    return Xd, yd, len(idx)


def ols(X, y):
    X1 = np.column_stack([np.ones(len(y)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    resid = y - X1 @ beta
    dof = max(len(y) - X1.shape[1], 1)
    s2 = float(resid @ resid) / dof
    xtx_inv = np.linalg.pinv(X1.T @ X1)
    se = np.sqrt(np.maximum(np.diag(xtx_inv) * s2, 0))
    return beta[1:], se[1:]


def main():
    stat = sys.argv[1] if len(sys.argv) > 1 else "outs"
    src = (sys.argv[2] if len(sys.argv) > 2
           else "scratchpad/ceiling_rows_noleash.json")
    rows = load(src)
    weather = "--weather" in sys.argv
    names, X, y, who = design(rows, stat, weather=weather)
    print(f"  {src}\n  {len(y)} starts with every feature present, "
          f"residual on {stat} (sd {st.pstdev(list(y)):.2f})\n")

    b_uni = []
    for j, n in enumerate(names):
        bb, ss = ols(X[:, [j]], y)
        b_uni.append((bb[0], ss[0]))
    b_joint, se_joint = ols(X, y)
    Xd, yd, npit = demean(X, y, who)
    b_fe, se_fe = ols(Xd, yd)

    print(f"  {'feature':<18}{'univariate':>20}{'joint':>20}"
          f"{'+ pitcher fixed':>20}")
    for j, n in enumerate(names):
        u = f"{b_uni[j][0]:+.4f} ({b_uni[j][0]/b_uni[j][1] if b_uni[j][1] else 0:+.1f})"
        jo = f"{b_joint[j]:+.4f} ({b_joint[j]/se_joint[j] if se_joint[j] else 0:+.1f})"
        fe = f"{b_fe[j]:+.4f} ({b_fe[j]/se_fe[j] if se_fe[j] else 0:+.1f})"
        print(f"  {n:<18}{u:>20}{jo:>20}{fe:>20}")
    print(f"\n  coefficient (t-statistic). {npit} pitchers absorbed by the"
          "\n  fixed effect, which compares the SAME man across parks, days"
          "\n  and travel. |t| > 3 is the bar this project uses.")
    print("\n  READ THE COLUMNS AGAINST EACH OTHER. A feature that survives"
          "\n  univariate and dies jointly was borrowing another's variance;"
          "\n  one that dies under the fixed effect was a property of WHICH"
          "\n  PITCHERS pitch there, not of the ballpark.")


if __name__ == "__main__":
    main()
