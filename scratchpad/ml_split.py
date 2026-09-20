"""TODO 19, step 4 — score the SUM against the SPLIT off the cached draws.

QUESTION. Team totals have never been scored separately from the game
total. The item's motivation was a market disagreement (3.03 points on the
sum against 3.65 on the split, 2026-09-09), but the market is not the
yardstick here — actual outcomes are. So: given the same draws, is the
model worse at the SPLIT (who scores them) than at the SUM (how many are
scored)?

TEST. One game's 200 draws give three distributions with no new
simulation: the SUM (away + home), each CLUB's total, and the signed
MARGIN (home - away). Each is scored against what happened with discrete
CRPS over the full support — the same construction `fitf5` uses — plus the
paired bias and the shape cell by cell. Full game and F5 both, since F5 is
the item's lead.

THE COMPARISON THAT MAKES IT READABLE: CRPS is on the units of the
quantity, so a club total (mean ~4.4) and a game total (mean ~8.8) cannot
be compared raw. Each is therefore also scored against a CLIMATOLOGY
benchmark — the pooled empirical distribution of that same quantity over
the fold, which knows the league and nothing about the game. The SKILL
RATIO (1 - model/climatology) is unitless and comparable across the three.

POWER. 3,548 games / 7,096 club-games. The paired CRPS se is printed on
every row; skill differences under ~0.5% of climatology are not resolvable.

    venv/bin/python -m scratchpad.ml_split
"""
import gzip
import json
import os
import statistics as st
from collections import Counter

from src import db

FOLDS = [2023, 2024, 2025, 2026]
SIM_DIR = os.path.join("scratchpad", "sims")


def crps(counts, actual):
    """Discrete CRPS of a draw histogram against an integer outcome."""
    n = sum(counts.values())
    lo = min(min(counts), actual)
    hi = max(max(counts), actual)
    cum = 0.0
    total = 0.0
    for k in range(lo, hi + 1):
        cum += counts.get(k, 0) / n
        total += (cum - (1.0 if actual <= k else 0.0)) ** 2
    return total


def load():
    with db.connect() as c:
        act = {r["game_id"]: dict(r) for r in c.execute(
            "select game_id, away_score, home_score, away_score_f5,"
            " home_score_f5 from games where sport='mlb'")}
    out = {}
    for yr in FOLDS:
        with gzip.open(os.path.join(SIM_DIR, f"ml_{yr}.json.gz"), "rt") as f:
            blob = json.load(f)
        games = []
        for gid, draws in blob["games"].items():
            a = act.get(gid) or {}
            if a.get("away_score") is None or a.get("away_score_f5") is None:
                continue
            games.append((draws, a))
        out[yr] = games
    return out


def score(items, label):
    """items = [(Counter over draws, actual)]. Model CRPS vs climatology."""
    clim = Counter()
    for _, a in items:
        clim[a] += 1
    m = [crps(c, a) for c, a in items]
    cl = [crps(clim, a) for _, a in items]
    d = [x - y for x, y in zip(m, cl)]
    n = len(m)
    se = st.pstdev(d) / n ** 0.5
    skill = 1 - st.mean(m) / st.mean(cl)
    bias = [sum(k * v for k, v in c.items()) / sum(c.values()) - a
            for c, a in items]
    bse = st.pstdev(bias) / n ** 0.5
    print(f"    {label:22s} crps {st.mean(m):.4f}  clim {st.mean(cl):.4f}  "
          f"skill {skill:+.4f}  (gap se {se:.4f}, z {st.mean(d)/se:+.1f})  "
          f"bias {st.mean(bias):+.3f} (se {bse:.3f})  n {n}")
    return skill


def dist(items, label, cells):
    """Model mass against real mass, paired per case, cell by cell."""
    print(f"\n  {label}: mass by cell, paired")
    for cell in cells:
        hit = cell[1]
        pairs = []
        for c, a in items:
            n = sum(c.values())
            m = sum(v for k, v in c.items() if hit(k)) / n
            pairs.append((m, 1.0 if hit(a) else 0.0))
        d = [x - y for x, y in pairs]
        se = st.pstdev(d) / len(d) ** 0.5
        gap = st.mean(d)
        print(f"    {cell[0]:>8s}  model {st.mean(x for x, _ in pairs):.4f}"
              f"  real {st.mean(y for _, y in pairs):.4f}"
              f"  gap {gap:+.4f}  se {se:.4f}  z {gap/se:+5.2f}")


def main():
    folds = load()
    total = sum(len(v) for v in folds.values())
    print(f"CACHED DRAWS: {total} games, {total * 2} club-games, no"
          f" simulation\n")

    for window, idx, keys in (("FULL GAME", (0, 1),
                               ("away_score", "home_score")),
                              ("F5", (2, 3),
                               ("away_score_f5", "home_score_f5"))):
        sums, clubs, margins = [], [], []
        for yr in FOLDS:
            for draws, a in folds[yr]:
                aw = [d[idx[0]] for d in draws]
                hm = [d[idx[1]] for d in draws]
                ra, rh = a[keys[0]], a[keys[1]]
                sums.append((Counter(x + y for x, y in zip(aw, hm)), ra + rh))
                clubs.append((Counter(aw), ra))
                clubs.append((Counter(hm), rh))
                margins.append((Counter(y - x for x, y in zip(aw, hm)),
                                rh - ra))
        print(f"  {window}")
        score(sums, "game total (SUM)")
        score(clubs, "team total (SPLIT)")
        score(margins, "margin (SPLIT)")
        print()

    # Shape, full game only — where the split is actually wrong.
    clubs, margins = [], []
    for yr in FOLDS:
        for draws, a in folds[yr]:
            clubs.append((Counter(d[0] for d in draws), a["away_score"]))
            clubs.append((Counter(d[1] for d in draws), a["home_score"]))
            margins.append((Counter(d[1] - d[0] for d in draws),
                            a["home_score"] - a["away_score"]))
    dist(clubs, "CLUB RUNS, full game",
         [("0", lambda k: k == 0), ("1", lambda k: k == 1),
          ("2", lambda k: k == 2), ("3", lambda k: k == 3),
          ("4", lambda k: k == 4), ("5", lambda k: k == 5),
          ("6", lambda k: k == 6), ("7", lambda k: k == 7),
          ("8+", lambda k: k >= 8), ("10+", lambda k: k >= 10)])
    # Is the margin its own defect, or the club defect counted twice?
    # var(margin) = var(a) + var(h) - 2cov(a, h), so a narrow margin is
    # either narrow clubs or a correlation the model invents.
    ra = [a["away_score"] for yr in FOLDS for _, a in folds[yr]]
    rh = [a["home_score"] for yr in FOLDS for _, a in folds[yr]]
    ma = [d[0] for yr in FOLDS for draws, _ in folds[yr] for d in draws]
    mh = [d[1] for yr in FOLDS for draws, _ in folds[yr] for d in draws]
    print("\n  VARIANCE DECOMPOSITION (unconditional, pooled over games)")
    for lab, aa, hh in (("real ", ra, rh), ("model", ma, mh)):
        sd_a, sd_h = st.pstdev(aa), st.pstdev(hh)
        sd_m = st.pstdev([h - a for a, h in zip(aa, hh)])
        sd_s = st.pstdev([h + a for a, h in zip(aa, hh)])
        cov = (st.pstdev([h + a for a, h in zip(aa, hh)]) ** 2
               - sd_a ** 2 - sd_h ** 2) / 2
        print(f"    {lab}  sd(away) {sd_a:.3f}  sd(home) {sd_h:.3f}  "
              f"sd(margin) {sd_m:.3f}  sd(sum) {sd_s:.3f}  "
              f"corr {cov / (sd_a * sd_h):+.4f}  n {len(aa)}")

    # LIKE FOR LIKE, because the row above compares 200 draws a game
    # against ONE outcome a game and a correlation is exactly the kind of
    # quantity that changes when the mixture weights change. Take draw i
    # only — one realisation per game, the same shape as reality — and
    # report the spread over i. Then split the model's correlation into
    # its BETWEEN-game part (do the two clubs' expectations move together,
    # which is the environment) and its WITHIN-game part (a shared game
    # state: extras, a long game).
    singles = []
    for i in range(20):
        aa = [draws[i][0] for yr in FOLDS for draws, _ in folds[yr]]
        hh = [draws[i][1] for yr in FOLDS for draws, _ in folds[yr]]
        sd_a, sd_h = st.pstdev(aa), st.pstdev(hh)
        cov = (st.pstdev([h + a for a, h in zip(aa, hh)]) ** 2
               - sd_a ** 2 - sd_h ** 2) / 2
        singles.append((cov / (sd_a * sd_h),
                        st.pstdev([h - a for a, h in zip(aa, hh)])))
    cs = [c for c, _ in singles]
    ms = [m for _, m in singles]
    print(f"    ONE DRAW A GAME, 20 repeats: corr {st.mean(cs):+.4f} "
          f"(sd over repeats {st.pstdev(cs):.4f}), sd(margin) "
          f"{st.mean(ms):.3f} (sd {st.pstdev(ms):.3f});  a correlation on"
          f" {len(ra)} games carries se {1 / len(ra) ** 0.5:.4f}")
    means = [(st.mean(d[0] for d in draws), st.mean(d[1] for d in draws))
             for yr in FOLDS for draws, _ in folds[yr]]
    sa, sh = st.pstdev([m for m, _ in means]), st.pstdev([h for _, h in means])
    cov_b = (st.pstdev([m + h for m, h in means]) ** 2 - sa ** 2 - sh ** 2) / 2
    within = []
    for yr in FOLDS:
        for draws, _ in folds[yr]:
            aa = [d[0] for d in draws]
            hh = [d[1] for d in draws]
            va, vh = st.pvariance(aa), st.pvariance(hh)
            cv = (st.pvariance([a + h for a, h in zip(aa, hh)]) - va - vh) / 2
            within.append(cv / (va * vh) ** 0.5 if va and vh else 0.0)
    print(f"    BETWEEN games: corr of the two clubs' model means "
          f"{cov_b / (sa * sh):+.4f} (sd of means {sa:.3f} / {sh:.3f});  "
          f"WITHIN a game: mean corr over draws {st.mean(within):+.4f}")

    dist(margins, "SIGNED MARGIN (home - away)",
         [("<=-6", lambda k: k <= -6), ("-5..-3", lambda k: -5 <= k <= -3),
          ("-2..-1", lambda k: -2 <= k <= -1),
          ("+1..+2", lambda k: 1 <= k <= 2),
          ("+3..+5", lambda k: 3 <= k <= 5), (">=+6", lambda k: k >= 6)])


if __name__ == "__main__":
    main()
