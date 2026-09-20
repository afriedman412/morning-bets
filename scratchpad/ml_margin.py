"""TODO 19, step 1 — settle the margin contradiction, and step 2 — is the
win probability under- or over-confident.

QUESTION. Two instruments read the one-run-game share in opposite
directions. The moneyline pass (2026-09-09, `scratchpad/moneyline.py`)
reads 0.294 model against 0.273 real — HIGH. Item 1's retired survivor
reads 0.247 against 0.266 — LOW. Rule 11: check they measure the same
thing before touching a mechanism.

TEST. One instrument, one engine, one set of draws. Everything here is
recomputed off the CACHED `scratchpad/sims/ml_<fold>.json.gz` draws
(3,548 paired games x 200 draws, HEAD engine with USE_OPENER_* on) using
the BATTERY's definition of the row verbatim: per game the model share is
the mean over draws of `abs(away - home) == 1`, the actual is the 0/1
indicator, and the se is the paired sd of (model - actual) over games —
`battery._paired`. No new simulation, so the engine cannot drift between
the two numbers being compared.

Also reported, because rule 2 says the shape is the product and a mean is
not a result: the whole |margin| distribution, model against real, cell by
cell; and the same rows off the first 20 draws of each game, which is what
the moneyline pass pooled — if the draw count moves the answer the
instrument is the problem.

STEP 2, the pre-registered calibration cell. A margin distribution that is
too NARROW makes win probabilities too UNDER-confident (forecasts squeezed
toward 0.5), the opposite of what the item predicted from item 1's LOW
reading. The test is the standard one: fit `outcome ~ a + b logit(p)`. b>1
is under-confident (the forecasts should be pushed out), b<1 over-confident.
Reported with its se, plus the extreme cells the deciles are too thin to
resolve.

POWER. Pooled 3,548 games: a one-run share se of ~0.0075, so the two
instruments' 0.047 disagreement is 6 se apart and cannot be noise. The
calibration slope has se ~0.15 at this n against a null of b=1, so only a
gross confidence error is resolvable — state that before reading it.

    venv/bin/python -m scratchpad.ml_margin
"""
import gzip
import json
import math
import os
import statistics as st

from src import db

FOLDS = [2023, 2024, 2025, 2026]
SIM_DIR = os.path.join("scratchpad", "sims")
BATTERY = os.path.join("scratchpad", "battery_640abdb42799.json")


def paired(pairs):
    """(model mean, actual mean, gap, se, n) — battery._paired verbatim."""
    d = [m - a for m, a in pairs]
    n = len(d)
    se = st.pstdev(d) / n ** 0.5 if n > 1 else 0.0
    return (st.mean(m for m, _ in pairs), st.mean(a for _, a in pairs),
            st.mean(d), se, n)


def row(label, r):
    m, a, gap, se, n = r
    z = gap / se if se else float("nan")
    print(f"    {label:24s} model {m:.4f}  real {a:.4f}  "
          f"gap {gap:+.4f}  se {se:.4f}  z {z:+5.2f}  n {n}")


def load():
    """{fold: [(draws, actual_row)]} for every game with a final score."""
    with db.connect() as c:
        act = {r["game_id"]: dict(r) for r in c.execute(
            "select game_id, away_score, home_score, away_score_f5,"
            " home_score_f5 from games where sport='mlb'")}
    out = {}
    for yr in FOLDS:
        path = os.path.join(SIM_DIR, f"ml_{yr}.json.gz")
        with gzip.open(path, "rt") as f:
            blob = json.load(f)
        games = []
        for gid, draws in blob["games"].items():
            a = act.get(gid) or {}
            if a.get("away_score") is None:
                continue
            games.append((draws, a))
        out[yr] = games
        print(f"  fold {yr}: {len(games)} games x {blob['n_sims']} draws")
    return out


def one_run_rows(folds, ndraws=None):
    """The battery's `one_run_share` row, per fold and pooled."""
    pooled = []
    for yr in FOLDS:
        pairs = []
        for draws, a in folds[yr]:
            d = draws[:ndraws] if ndraws else draws
            m = sum(abs(aw - hm) == 1 for aw, hm, *_ in d) / len(d)
            pairs.append((m, float(abs(a["away_score"] - a["home_score"])
                                   == 1)))
        pooled.extend(pairs)
        row(str(yr), paired(pairs))
    row("POOLED", paired(pooled))
    return paired(pooled)


def margin_rows(folds, ndraws=None):
    pooled = []
    for yr in FOLDS:
        pairs = []
        for draws, a in folds[yr]:
            d = draws[:ndraws] if ndraws else draws
            m = sum(abs(aw - hm) for aw, hm, *_ in d) / len(d)
            pairs.append((m, float(abs(a["away_score"] - a["home_score"]))))
        pooled.extend(pairs)
        row(str(yr), paired(pairs))
    row("POOLED", paired(pooled))
    return paired(pooled)


def margin_shape(folds):
    """The whole |margin| distribution, cell by cell, paired per game."""
    cells = list(range(1, 8)) + ["8+"]
    print("\n  |MARGIN| DISTRIBUTION, pooled, paired per game")
    for cell in cells:
        pairs = []
        for yr in FOLDS:
            for draws, a in folds[yr]:
                hit = (lambda x: x >= 8) if cell == "8+" else \
                      (lambda x, c=cell: x == c)
                m = sum(hit(abs(aw - hm)) for aw, hm, *_ in draws) \
                    / len(draws)
                pairs.append((m, float(hit(abs(a["away_score"]
                                              - a["home_score"])))))
        row(f"|margin| {cell}", paired(pairs))


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def calib_slope(rows_):
    """Newton fit of outcome ~ a + b*logit(p). Returns (a, b, se_b)."""
    x = [logit(p) for p, _ in rows_]
    y = [o for _, o in rows_]
    a, b = 0.0, 1.0
    for _ in range(60):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for xi, yi in zip(x, y):
            p = 1 / (1 + math.exp(-(a + b * xi)))
            w = p * (1 - p)
            g0 += yi - p
            g1 += (yi - p) * xi
            h00 += w
            h01 += w * xi
            h11 += w * xi * xi
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-12:
            break
        da = (h11 * g0 - h01 * g1) / det
        dbb = (h00 * g1 - h01 * g0) / det
        a, b = a + da, b + dbb
        if abs(da) < 1e-10 and abs(dbb) < 1e-10:
            break
    return a, b, math.sqrt(h00 / det)


def confidence(rows_, label):
    a, b, se_b = calib_slope(rows_)
    verdict = ("UNDER-confident (spread the forecasts out)" if b > 1
               else "OVER-confident (shrink the forecasts in)")
    print(f"\n  {label}: n {len(rows_)}")
    print(f"    calibration slope b {b:.3f}  se {se_b:.3f}  "
          f"z vs 1.0 {(b - 1) / se_b:+.2f}  intercept {a:+.3f}")
    print(f"    -> {verdict if abs(b - 1) > 2 * se_b else 'flat at this n'}")
    print(f"    forecast sd {st.pstdev([p for p, _ in rows_]):.4f}")
    edges = [0.0, 0.35, 0.45, 0.55, 0.65, 1.0]
    print("    the extreme cells (deciles are too thin out here):")
    for lo, hi in zip(edges, edges[1:]):
        v = [(p, o) for p, o in rows_ if lo <= p < hi]
        if not v:
            continue
        k = len(v)
        pk = sum(p for p, _ in v) / k
        ok = sum(o for _, o in v) / k
        se = (ok * (1 - ok) / k) ** 0.5 if 0 < ok < 1 else 1 / k
        star = "*" if abs(pk - ok) > 2 * se else " "
        print(f"      {lo:.2f}-{hi:.2f}  n {k:4d}  forecast {pk:.3f}  "
              f"actual {ok:.3f}  (se {se:.3f}){star}")


def pen_check(folds):
    """DID THE CACHE HAVE BULLPENS (TODO 20)? An empty pen hands every
    relief inning to the STARTER'S rates, which is a large, fold-specific
    run-level effect — so the cache is checked AGAINST the battery that
    was run with the fix in, fold by fold. If 2023-2025 agree as closely
    as 2026 does, the cache is on live pens; if they are off and 2026 is
    not, it was built broken and every number here is void.

    `moneyline.py` passed `season=yr` explicitly, which was correct even
    before the root fix, and the draws were written 13:08-13:28 against a
    tree that already had it (12:18, e1ebfda) — this is the evidence, not
    the argument."""
    with open(BATTERY) as f:
        bat = json.load(f)
    print("\n  CACHE vs THE FIXED-PEN BATTERY, per fold (the TODO 20 check)")
    print("    fold   F5 total (cache/battery)   club shutout share"
          "   club 8+ share")
    for yr in FOLDS:
        f5 = [d[2] + d[3] for draws, _ in folds[yr] for d in draws]
        clubs = [v for draws, _ in folds[yr] for d in draws
                 for v in (d[0], d[1])]
        sho = sum(v == 0 for v in clubs) / len(clubs)
        big = sum(v >= 8 for v in clubs) / len(clubs)
        b = {r["key"]: r for r in bat["rows"] if r["fold"] == yr}
        print(f"    {yr}   {st.mean(f5):.4f} / {b['F5']['model']:.4f}"
              f"  ({st.mean(f5) - b['F5']['model']:+.4f})"
              f"     {sho:.4f} / {b['shutout_share']['model']:.4f}"
              f"  ({sho - b['shutout_share']['model']:+.4f})"
              f"     {big:.4f} / {b['mass_8_plus']['model']:.4f}"
              f"  ({big - b['mass_8_plus']['model']:+.4f})")


def main():
    print("LOADING CACHED DRAWS (no simulation)")
    folds = load()
    pen_check(folds)

    print("\nSTEP 1 — ONE-RUN SHARE, battery definition, all 200 draws")
    one_run_rows(folds)
    print("\n  the same rows off the first 20 draws (what the moneyline"
          " pass pooled)")
    one_run_rows(folds, ndraws=20)

    with open(BATTERY) as f:
        bat = json.load(f)
    br = [r for r in bat["rows"] if r["key"] == "one_run_share"]
    tm = sum(r["model"] * r["n"] for r in br) / sum(r["n"] for r in br)
    ta = sum(r["actual"] * r["n"] for r in br) / sum(r["n"] for r in br)
    print(f"\n  THE BATTERY, same engine, 40 draws, its own game set:"
          f" model {tm:.4f}  real {ta:.4f}")

    print("\n  MEAN |MARGIN|, paired per game, all 200 draws")
    margin_rows(folds)
    margin_shape(folds)

    print("\nSTEP 2 — IS THE WIN PROBABILITY UNDER- OR OVER-CONFIDENT")
    ml, f5 = [], []
    for yr in FOLDS:
        for draws, a in folds[yr]:
            n = len(draws)
            ml.append((sum(1 for aw, hm, *_ in draws if hm > aw) / n,
                       1 if a["home_score"] > a["away_score"] else 0))
            if a.get("away_score_f5") is None \
                    or a["home_score_f5"] == a["away_score_f5"]:
                continue
            hw = sum(1 for _, _, af, hf, *_ in draws if hf > af)
            aw_ = sum(1 for _, _, af, hf, *_ in draws if af > hf)
            if hw + aw_ == 0:
                continue
            f5.append((hw / (hw + aw_),
                       1 if a["home_score_f5"] > a["away_score_f5"] else 0))
    confidence(f5, "F5 WINNER (no-tie conditional)")
    confidence(ml, "FULL-GAME MONEYLINE")


if __name__ == "__main__":
    main()
