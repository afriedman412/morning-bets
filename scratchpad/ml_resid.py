"""TODO 19.2 — is the missing coupling DYNAMIC or is it the MATCHUPS?

QUESTION. Reality's across-games correlation between the two clubs' runs is
-0.053 through eight innings against the model's ~+0.012. That number
CANNOT tell why. Two stories fit it and they are different items:

  * BETWEEN GAMES — the matchups are composed that way. A strong club
    facing a weak one scores a lot while the weak one scores little, which
    is a negative correlation across games with no in-game coupling at all.
    Shared park, weather and umpire push the other way. If this is the
    story, the defect is in how the model spreads the two clubs'
    EXPECTATIONS apart, and it is a rates/shrinkage item.
  * WITHIN A GAME — games pull apart as they are played, over and above
    what the two clubs' abilities predict. That is the bullpen-leverage
    story: the club with a lead goes to its best arms and the club behind
    empties the mop-up end. If this is the story it belongs with item 22.

`ml_extras.py` split the MODEL both ways (within-game ~0, between ~+0.008)
because it has 200 draws per game. Reality has ONE realisation, so it
cannot be split the same way, and the earlier write-up asserted the within
story on evidence that only covered the total. This is the missing test.

TEST. RESIDUALS AGAINST THE MODEL'S OWN EXPECTATION. For every game take
    ra = real away runs - model mean away runs
    rh = real home runs - model mean home runs
and correlate ra with rh. The model's expectation already contains
everything it knows about the matchup — the two starters, both lineups, the
park, the pen — so the between-game structure the model HAS is subtracted
out. What survives is the coupling that is there conditional on the model's
own view of the game, which is the quantity the within story predicts and
the between story does not.

  * corr(ra, rh) clearly NEGATIVE -> a real coupling the model lacks
    conditional on its own expectations. Dynamic. Screen with item 22.
  * corr(ra, rh) ~ ZERO -> the model's per-game expectations are simply not
    spread apart the way real matchups are. Between-game. A different item,
    and item 22 is not implicated.

CONTROL. The same correlation computed on the MODEL against itself — one
draw standing in for the real outcome, residual against the mean of the
other 199. That is the same statistic on a world with a known answer
(the model's within-game coupling, measured at ~+0.0035 through nine), so
it says what this estimator reads when the coupling is absent.

NOISE IN A PREDICTOR: the model mean carries Monte Carlo error, but at 200
draws that is ~0.22 runs against a club sd of ~3.1, under 0.5% of variance,
and CLAUDE.md's rule 10 notes residual screens are unaffected in any case.

POWER. 3,548 games, se of a correlation 0.0168. The quantity in dispute is
~0.05-0.065, so this resolves it at 3-4 se. It cannot resolve 0.02.

    venv/bin/python -m scratchpad.ml_resid
"""
import gzip
import json
import os
import statistics as st

from src import db
from scratchpad.ml_extras import REAL9, corr

FOLDS = [2023, 2024, 2025, 2026]
SIM_DIR = os.path.join("scratchpad", "sims")


def main():
    with db.connect() as c:
        act = {r["game_id"]: dict(r) for r in c.execute(
            "select game_id, away_score, home_score, away_score_f5,"
            " home_score_f5 from games where sport='mlb'")}
    with open(REAL9) as f:
        real = json.load(f)

    rows = []
    for yr in FOLDS:
        with gzip.open(os.path.join(SIM_DIR, f"ml_{yr}.json.gz"), "rt") as f:
            blob = json.load(f)
        for gid, draws in blob["games"].items():
            a = act.get(gid)
            v = real.get(gid, "missing")
            if not a or a.get("away_score_f5") is None or v == "missing":
                continue
            nine = v[1]
            rows.append((draws,
                         (a["away_score_f5"], a["home_score_f5"]),
                         tuple(nine) if nine else (a["away_score"],
                                                   a["home_score"])))
    n = len(rows)
    print(f"{n} games, se of a correlation {1 / n ** 0.5:.4f}\n")

    for label, ri, (ai, hi) in (("F5", 1, (2, 3)),
                                ("through 9", 2, (4, 5))):
        ma = [st.mean(d[ai] for d in draws) for draws, _, _ in rows]
        mh = [st.mean(d[hi] for d in draws) for draws, _, _ in rows]
        real_a = [x[ri][0] for x in rows]
        real_h = [x[ri][1] for x in rows]
        ra = [r - m for r, m in zip(real_a, ma)]
        rh = [r - m for r, m in zip(real_h, mh)]

        # The control: one draw plays the part of the outcome, and its
        # residual is taken against the mean of the OTHER draws so the
        # point is not inside its own baseline.
        cvals = []
        for k in range(10):
            ca, ch = [], []
            for draws, _, _ in rows:
                others = [d for j, d in enumerate(draws) if j != k]
                ca.append(draws[k][ai] - st.mean(d[ai] for d in others))
                ch.append(draws[k][hi] - st.mean(d[hi] for d in others))
            cvals.append(corr(ca, ch))

        print(f"  {label}")
        print(f"    raw across-games   model {corr(ma, mh):+.4f} (expectations)"
              f"   real {corr(real_a, real_h):+.4f} (outcomes)")
        print(f"    RESIDUAL corr(real - model mean)      {corr(ra, rh):+.4f}")
        print(f"    control: same statistic on the model  "
              f"{st.mean(cvals):+.4f}  (sd over 10 draws"
              f" {st.pstdev(cvals):.4f})")
        gap = corr(ra, rh) - st.mean(cvals)
        print(f"    real residual minus model control     {gap:+.4f}"
              f"   z {gap * n ** 0.5:+.1f}\n")


if __name__ == "__main__":
    main()
