"""TODO 19 — moneylines, the easy version: persist the draws, count, score.

QUESTION. The engine already produces a joint (away, home) run distribution
per game; nothing has ever counted P(home wins) out of it or scored that
number against who actually won. Is the win probability any good?

F5 WINNER FIRST, per the item: F5 is the only window that has ever beaten
a settled price, and it ends before the bullpen and the late-innings lean
are involved. If any win probability works it is that one; the full-game
number is scored in the same pass because it is the same loop.

TEST. Per fold, `paired_cases` games replayed N times; the per-draw
`(away, home)` and `(away_f5, home_f5)` pairs are PERSISTED to
`scratchpad/sims/ml_<fold>.json.gz` so any later margin question (run
line, spreads) reads the same draws without re-simulating. P(home wins)
counts draws with home > away, extras already resolved by the engine
(nine innings never tie). F5 leads CAN tie — the three-way split is
reported and the binary is scored conditional on no tie, with the tie
share checked against reality separately.

SCORE. Brier decomposition (uncertainty - resolution + reliability) on
outcomes, and a calibration table by forecast decile. THE ADOPTED
ONE-RUN-GAME FINDING: the model makes 0.247 one-run games against a real
0.266 (1.9 sigma light), so the margin may be too wide and the win
probability too confident — the extreme deciles of the table are where
that shows. POWER: ~900 games a fold, so a decile holds ~90 games and a
calibration gap under ~5 points is unresolvable in one fold; the pooled
table over ~3,500 games resolves ~2.5 points.

DO NOT start repairing anything on a bad score — the item says stop and
write the null.

    venv/bin/python -m scratchpad.moneyline [n_sims]
"""
import gzip
import json
import os
import random
import sys
from collections import defaultdict

from src import db
from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src

FOLDS = [(2023, "2023-07-01"), (2024, "2024-07-01"),
         (2025, "2025-07-01"), (2026, "2026-07-01")]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
OUT_DIR = os.path.join("scratchpad", "sims")
#: Bumped whenever the persisted per-draw tuple changes shape. 1 was
#: (away, home, away_f5, home_f5); 2 appends the regulation-nine split.
SCHEMA = 2


def simulate_fold(yr, cut):
    """Replay the fold and persist every draw's six numbers per game.

    THE LAST TWO ARE THE REGULATION-NINE SPLIT (item 19.1), and they are
    what makes the extras question answerable without re-simulating again.
    `track=(9,)` fills `prefix_side[9]`, which is each club's score THROUGH
    THE NINTH; the first two numbers are the FINAL score. A game reaches
    extras exactly when it is tied after nine, so `away_9 == home_9` is the
    extras flag and `(away - away_9, home - home_9)` is what extras added.
    Recording the split rather than a last-inning integer is deliberate:
    conditioning on "no extras" is conditioning on `away_9 != home_9`,
    which is a SELECTION on the very quantity whose correlation is being
    read, so the unselected regulation-nine correlation has to be available
    beside it.
    """
    pairs = cal.paired_cases(season=yr, rates_before=cut, since=cut)
    lg = sim.league(season=yr, before=cut)
    pens = rate_src.bullpens(lg, season=yr, before=cut)
    rows = {}
    for gi, (gid, pair) in enumerate(sorted(pairs.items())):
        d = []
        for i in range(N):
            rng = random.Random(yr * 7000003 + gi * 1013 + i)
            r = cal.replay(pair, lg, pens, rng, track=(5, 9))
            a9, h9 = r.prefix_side.get(9, (r.away, r.home))
            d.append((r.away, r.home, r.away_f5, r.home_f5, a9, h9))
        rows[gid] = d
        if (gi + 1) % 200 == 0:
            print(f"  fold {yr}: {gi + 1}/{len(pairs)}", flush=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"ml_{yr}.json.gz")
    with gzip.open(path, "wt") as f:
        json.dump({"n_sims": N, "cut": cut, "schema": SCHEMA, "games": rows},
                  f)
    print(f"  saved {path} ({len(rows)} games x {N} draws)", flush=True)
    return rows


def load_or_simulate(yr, cut):
    """A cache written under an OLDER SCHEMA is re-simulated, not read.

    The four-number files written on 2026-09-09 unpack fine into the first
    four slots and would silently answer every question here with no
    regulation-nine columns at all, which is the failure mode the schema
    key exists to prevent.
    """
    path = os.path.join(OUT_DIR, f"ml_{yr}.json.gz")
    if os.path.exists(path):
        with gzip.open(path, "rt") as f:
            blob = json.load(f)
        if blob.get("n_sims") == N and blob.get("schema") == SCHEMA:
            print(f"  fold {yr}: loaded {path}", flush=True)
            return blob["games"]
    return simulate_fold(yr, cut)


def brier_decomp(rows):
    """[(p, outcome)] -> (brier, uncertainty, resolution, reliability),
    binned by forecast decile — the same construction the notes'
    resolution comparisons used."""
    n = len(rows)
    base = sum(o for _, o in rows) / n
    unc = base * (1 - base)
    bins = defaultdict(list)
    for p, o in rows:
        bins[min(int(p * 10), 9)].append((p, o))
    rel = res = 0.0
    for v in bins.values():
        k = len(v)
        pk = sum(p for p, _ in v) / k
        ok = sum(o for _, o in v) / k
        rel += k / n * (pk - ok) ** 2
        res += k / n * (ok - base) ** 2
    brier = sum((p - o) ** 2 for p, o in rows) / n
    return brier, unc, res, rel


def table(rows, label):
    print(f"\n  {label}: calibration by forecast decile")
    bins = defaultdict(list)
    for p, o in rows:
        bins[min(int(p * 10), 9)].append((p, o))
    for b in sorted(bins):
        v = bins[b]
        k = len(v)
        pk = sum(p for p, _ in v) / k
        ok = sum(o for _, o in v) / k
        se = (ok * (1 - ok) / k) ** 0.5 if 0 < ok < 1 else 1 / k
        star = "*" if abs(pk - ok) > 2 * max(se, 1e-9) else " "
        print(f"    {b/10:.1f}-{(b+1)/10:.1f}  n {k:4d}  "
              f"forecast {pk:.3f}  actual {ok:.3f}  (se {se:.3f}){star}")


def main():
    with db.connect() as c:
        act = {r["game_id"]: dict(r) for r in c.execute(
            "select game_id, away_score, home_score, away_score_f5,"
            " home_score_f5 from games where sport='mlb'")}
    ml, f5, f5_tie = [], [], []       # (forecast, outcome) pairs
    margins_sim, margins_real = [], []
    for yr, cut in FOLDS:
        games = load_or_simulate(yr, cut)
        for gid, draws in games.items():
            a = act.get(gid) or {}
            if a.get("away_score") is None:
                continue
            n = len(draws)
            ph = sum(1 for aw, hm, *_ in draws if hm > aw) / n
            ml.append((ph, 1 if a["home_score"] > a["away_score"] else 0))
            margins_sim.extend(abs(hm - aw) for aw, hm, *_ in draws[:20])
            margins_real.append(abs(a["home_score"] - a["away_score"]))
            if a.get("away_score_f5") is None:
                continue
            hw = sum(1 for _, _, af, hf, *_ in draws if hf > af)
            aw_ = sum(1 for _, _, af, hf, *_ in draws if af > hf)
            tie = n - hw - aw_
            f5_tie.append((tie / n,
                           1 if a["home_score_f5"] == a["away_score_f5"]
                           else 0))
            if hw + aw_ == 0 or a["home_score_f5"] == a["away_score_f5"]:
                continue
            f5.append((hw / (hw + aw_),
                       1 if a["home_score_f5"] > a["away_score_f5"] else 0))

    for rows, label in ((f5, "F5 WINNER (no-tie conditional)"),
                        (ml, "FULL-GAME MONEYLINE")):
        b, unc, res, rel = brier_decomp(rows)
        print(f"\n{label}: {len(rows)} games")
        print(f"  brier {b:.4f} = uncertainty {unc:.4f}"
              f" - resolution {res:.4f} + reliability {rel:.4f}")
        table(rows, label)

    pt = sum(p for p, _ in f5_tie) / len(f5_tie)
    ot = sum(o for _, o in f5_tie) / len(f5_tie)
    se = (ot * (1 - ot) / len(f5_tie)) ** 0.5
    print(f"\nF5 TIE SHARE: model {pt:.3f}  real {ot:.3f}  (se {se:.3f},"
          f" {len(f5_tie)} games)")

    ms = sum(margins_sim) / len(margins_sim)
    mr = sum(margins_real) / len(margins_real)
    sdr = (sum((x - mr) ** 2 for x in margins_real)
           / (len(margins_real) - 1)) ** 0.5
    one_sim = sum(1 for m in margins_sim if m == 1) / len(margins_sim)
    one_real = sum(1 for m in margins_real if m == 1) / len(margins_real)
    print(f"\nFULL-GAME MARGIN (the adopted one-run finding):")
    print(f"  mean |margin|  model {ms:.3f}  real {mr:.3f}"
          f"  (se {sdr/len(margins_real)**0.5:.3f})")
    print(f"  one-run share  model {one_sim:.3f}  real {one_real:.3f}")


if __name__ == "__main__":
    main()
