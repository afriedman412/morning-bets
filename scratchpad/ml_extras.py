"""TODO 19.1 — NAME THE COUPLING. Extras, or shared state inside nine?

QUESTION. The model puts a +0.059 correlation between the two clubs' runs
where reality has -0.022 (`scratchpad/ml_split.py`, 2026-09-09), and the
decomposition put most of it WITHIN a game (+0.048) rather than between
games. Within a game the two clubs' expectations are fixed, so a positive
within-game correlation is a SHARED STATE the engine invents. Which one?

HYPOTHESIS. Extra innings. Both clubs bat in every extra half, both start
one on second, and about one game in twelve goes there — a game-length
term is shared by construction and is the only candidate that is obviously
shared. The alternative is something inside nine innings, where the margin
feeds both hook curves and the pen usage.

TEST. `moneyline.py` now persists the REGULATION-NINE split beside the
final, so the same draws answer it with no new simulation:

  * the within-game covariance is split algebraically. Writing the final
    as `a = a9 + ax`, `h = h9 + hx`,
        cov(a, h) = cov(a9, h9) + [cov(a9, hx) + cov(ax, h9)] + cov(ax, hx)
    and the last two terms are BY DEFINITION extras. `cov(a9, h9)` is the
    nine-inning coupling with no selection applied to it at all.
  * the item's literal ask — "extras excluded" — is also reported, and it
    is the WEAKER of the two: dropping the extras draws is conditioning on
    `a9 != h9`, a selection on the very quantity being correlated, so it
    is read only against the unselected row above it.
  * REALITY GETS THE SAME TWO NUMBERS. Real regulation-nine scores come
    from the play-by-play cache (the score before the first play of the
    tenth), so "model final vs real final" and "model through nine vs real
    through nine" are like for like. Nothing here compares the model to a
    price.

CONTROLS, because a null and a broken estimator look identical (rule 7).
  * NEGATIVE — the home club's draws are shuffled within each game, which
    destroys the pairing and nothing else. The within-game correlation must
    read zero.
  * POSITIVE — a synthetic league with INDEPENDENT clubs and an
    extras rule bolted on. The instrument must report ~0 through nine, a
    clearly positive final correlation, and attribute all of it to the two
    extras terms. This is what proves the decomposition can tell "extras"
    from "nine innings", which is the entire question.

POWER. 3,548 games x 200 draws. A single game's within-draw correlation
carries se ~1/sqrt(200) = 0.071, so the mean over games resolves ~0.0012 —
the +0.048 is ~40 se and any residual above ~0.004 is real. The
one-draw-a-game correlations carry se ~1/sqrt(3548) = 0.0168, which is the
se the -0.022 real figure was quoted with, and it is the binding one on
every model-against-real row here.

    venv/bin/python -m scratchpad.ml_extras
"""
import gzip
import json
import os
import random
import statistics as st

from src import db
from src.context.sources import pbp

FOLDS = [2023, 2024, 2025, 2026]
SIM_DIR = os.path.join("scratchpad", "sims")
REAL9 = os.path.join("scratchpad", "real_prefix.json")
SCHEMA = 2


# ---------------------------------------------------------------- helpers

def cov(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n


def corr(xs, ys):
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    return cov(xs, ys) / (sx * sy) if sx and sy else 0.0


def mean_se(v):
    return st.mean(v), st.pstdev(v) / len(v) ** 0.5


# ------------------------------------------------------------------ input

def load():
    """{fold: [(gid, draws, actual)]} — schema-2 draws only."""
    with db.connect() as c:
        act = {r["game_id"]: dict(r) for r in c.execute(
            "select game_id, away_score, home_score, away_score_f5,"
            " home_score_f5 from games where sport='mlb'")}
    out = {}
    for yr in FOLDS:
        path = os.path.join(SIM_DIR, f"ml_{yr}.json.gz")
        with gzip.open(path, "rt") as f:
            blob = json.load(f)
        if blob.get("schema") != SCHEMA:
            raise SystemExit(
                f"{path} is schema {blob.get('schema')}, not {SCHEMA} — it "
                "has no regulation-nine columns. Re-run "
                "`venv/bin/python -m scratchpad.moneyline 200`.")
        games = []
        for gid, draws in blob["games"].items():
            a = act.get(gid)
            if not a or a.get("away_score") is None:
                continue
            games.append((gid, [tuple(d) for d in draws], a))
        out[yr] = games
        print(f"  fold {yr}: {len(games)} games x {blob['n_sims']} draws")
    return out


def real_prefix(gids):
    """{gid: [through-eight, through-nine]} for the real games.

    THROUGH EIGHT IS THE ONE THAT MATTERS, and it is here because of what
    the nine-inning reading turned up: the model's coupling appears
    entirely in the ninth, and the ninth is the one half-inning the home
    club sometimes does not bat. Reality has that rule too, so the two
    prefixes have to be read as a pair — an eight-inning number where both
    clubs always bat, and a nine-inning one where one of them may not.

    Each is the score BEFORE the first play of the following inning; a
    game that never gets there ends at its final, which the caller
    supplies. `pbp.have` guards the network, so this is offline.
    """
    cache = {}
    if os.path.exists(REAL9):
        with open(REAL9) as f:
            cache = json.load(f)
    todo = [g for g in gids if g not in cache]
    if todo:
        print(f"  reading play-by-play for {len(todo)} games "
              f"({len(cache)} cached)")
        for i, gid in enumerate(todo):
            if not pbp.have(gid):
                # DISTINCT from `None`. Both mean "that inning was never
                # reached", and conflating them counts an unread game as a
                # regulation one, which biases the real extras rate DOWN —
                # the row the whole item turns on.
                cache[gid] = "missing"
                continue
            got8 = got9 = None
            for play, _, _, aw, hm in pbp.plays(gid):
                inn = ((play.get("about") or {}).get("inning")) or 0
                if inn >= 9 and got8 is None:
                    got8 = [aw, hm]
                if inn >= 10:
                    got9 = [aw, hm]
                    break
            cache[gid] = [got8, got9]
            if (i + 1) % 500 == 0:
                print(f"    {i + 1}/{len(todo)}", flush=True)
        with open(REAL9, "w") as f:
            json.dump(cache, f)
    return cache


def real_ladder(games, real):
    """THE ROW THE ITEM TURNS ON: model against real at three prefixes.

    F5 and through-eight are windows where BOTH clubs always bat; through
    nine is the one where the home club may not. Real numbers are one
    realisation a game, so the model side is the one-draw-a-game
    correlation, not the within-game one — they are different quantities
    and pairing them wrongly is how this reads backwards.
    """
    rows = []
    for gid, draws, a in games:
        v = real.get(gid, "missing")
        if v == "missing" or a.get("away_score_f5") is None:
            continue
        got8, got9 = v
        rows.append((draws,
                     (a["away_score_f5"], a["home_score_f5"]),
                     tuple(got8) if got8 else (a["away_score"],
                                               a["home_score"]),
                     tuple(got9) if got9 else (a["away_score"],
                                               a["home_score"])))
    n = len(rows)
    print(f"\n  MODEL AGAINST REAL BY PREFIX, {n} games, se of a"
          f" correlation {1 / n ** 0.5:.4f}")
    print("    window                    model     real      gap      z")
    for label, ri, (ai, hi) in (("F5 (both bat)", 1, (2, 3)),
                                ("through 8 (both bat)", 2, (4, 4)),
                                ("through 9 (home may skip)", 3, (4, 5))):
        if label.startswith("through 8"):
            continue                     # filled in by ml_eight.py
        reps = [corr([d[i][ai] for d, _, _, _ in rows],
                     [d[i][hi] for d, _, _, _ in rows]) for i in range(20)]
        m = st.mean(reps)
        r = corr([x[ri][0] for x in rows], [x[ri][1] for x in rows])
        print(f"    {label:24s} {m:+.4f}  {r:+.4f}  {m - r:+.4f}"
              f"  {(m - r) * n ** 0.5:+5.1f}")
    r8 = corr([x[2][0] for x in rows], [x[2][1] for x in rows])
    r9 = corr([x[3][0] for x in rows], [x[3][1] for x in rows])
    print(f"    real through 8 {r8:+.4f} -> through 9 {r9:+.4f}: the"
          f" unplayed ninth moves REALITY by {r9 - r8:+.4f}")
    print("    (the model's own through-8 number needs a 5/8/9 track —"
          " `scratchpad/ml_eight.py`, which reads +0.0035 within-game)")


# ------------------------------------------------------------- the reading

def within_rows(games, label):
    """Mean within-game covariance, split into its nine-inning and extras
    parts, plus the correlation those covariances imply."""
    c_fin, c_99, c_cross, c_xx = [], [], [], []
    sd_a, sd_h, sd_a9, sd_h9 = [], [], [], []
    for _, draws, _ in games:
        a = [d[0] for d in draws]
        h = [d[1] for d in draws]
        a9 = [d[4] for d in draws]
        h9 = [d[5] for d in draws]
        ax = [x - y for x, y in zip(a, a9)]
        hx = [x - y for x, y in zip(h, h9)]
        c_fin.append(cov(a, h))
        c_99.append(cov(a9, h9))
        c_cross.append(cov(a9, hx) + cov(ax, h9))
        c_xx.append(cov(ax, hx))
        sd_a.append(st.pstdev(a))
        sd_h.append(st.pstdev(h))
        sd_a9.append(st.pstdev(a9))
        sd_h9.append(st.pstdev(h9))
    # The identity has to hold exactly, or the columns are mislabelled.
    resid = max(abs(f - (n + x + xx))
                for f, n, x, xx in zip(c_fin, c_99, c_cross, c_xx))
    assert resid < 1e-9, resid
    sa, sh = st.mean(sd_a), st.mean(sd_h)
    sa9, sh9 = st.mean(sd_a9), st.mean(sd_h9)
    print(f"\n  {label}: WITHIN-GAME covariance, {len(games)} games")
    ses = {}
    for name, key, v, denom in (
            ("cov(a, h)   final", "fin", c_fin, sa * sh),
            ("cov(a9, h9) nine  ", "99", c_99, sa9 * sh9),
            ("cross a9/hx + ax/h9", "cross", c_cross, sa * sh),
            ("cov(ax, hx) extras ", "xx", c_xx, sa * sh)):
        m, se = mean_se(v)
        ses["se_" + key] = se
        print(f"    {name:22s} {m:+.4f}  se {se:.4f}  z {m/se:+6.1f}"
              f"   -> corr {m / denom:+.4f}")
    share = st.mean(c_cross) + st.mean(c_xx)
    ses["extras_share"] = share / st.mean(c_fin)
    print(f"    extras are {ses['extras_share']:.1%} of the within-game"
          f" covariance")
    return st.mean(c_fin) / (sa * sh), st.mean(c_99) / (sa9 * sh9), ses


def margin_rows(games, real9):
    """IS IT THE SCORE? Inside a game the two PITCHING sides share exactly
    one quantity — the margin. Bullpens are drawn per club and per draw
    with no common term, so a within-game coupling cannot come from the
    pens on their own; it has to run through the score both managers are
    reading. Two readings, both off the same draws:

      * CONDITIONAL COUPLING. Stratify a game's draws by the F5 margin and
        re-take cov(a69, h69) inside each stratum. If the coupling is the
        margin, holding it fixed removes it. Strata are noisier but the
        estimator is the same one, and the unconditional number is printed
        beside it.
      * THE RESPONSE ITSELF, against reality. Mean runs scored in innings
        6-9 by both clubs, by the F5 margin. Real 6-9 runs are the
        play-by-play through-nine score minus the recorded F5, so this is
        a like-for-like level check on how hard the engine leans on the
        score late.
    """
    def bucket(m):
        return min(abs(m), 4)

    strat, uncond, wt = [], [], []
    for _, draws, _ in games:
        by = {}
        for d in draws:
            by.setdefault(bucket(d[2] - d[3]), []).append(d)
        a6 = [d[4] - d[2] for d in draws]
        h6 = [d[5] - d[3] for d in draws]
        uncond.append(cov(a6, h6))
        for v in by.values():
            if len(v) < 20:
                continue
            strat.append(cov([d[4] - d[2] for d in v],
                             [d[5] - d[3] for d in v]))
            wt.append(len(v))
    cw = sum(c * w for c, w in zip(strat, wt)) / sum(wt)
    um, use = mean_se(uncond)
    print(f"\n  CONDITIONAL ON THE F5 MARGIN: cov(a69, h69)"
          f"  unconditional {um:+.4f} (se {use:.4f})"
          f"  ->  within-stratum {cw:+.4f}"
          f"  ({1 - cw / um:.0%} of it is the margin)")

    print("\n  RUNS IN INNINGS 6-9, BOTH CLUBS, by the F5 margin")
    print("    |F5 margin|      model            real            gap")
    for b in range(5):
        mv = [(d[4] - d[2]) + (d[5] - d[3])
              for _, draws, _ in games for d in draws
              if bucket(d[2] - d[3]) == b]
        rv = []
        for gid, _, a in games:
            got = real9.get(gid, "missing")
            if got == "missing" or a.get("away_score_f5") is None:
                continue
            a9, h9 = (got[1] if got[1]
                      else (a["away_score"], a["home_score"]))
            if bucket(a["away_score_f5"] - a["home_score_f5"]) != b:
                continue
            rv.append((a9 - a["away_score_f5"])
                      + (h9 - a["home_score_f5"]))
        mm, mse = mean_se(mv)
        rm, rse = mean_se(rv)
        gap = mm - rm
        se = (mse ** 2 + rse ** 2) ** 0.5
        tag = str(b) if b < 4 else "4+"
        print(f"    {tag:>3s}   {mm:8.3f} (n {len(mv):6d})"
              f"   {rm:7.3f} (n {len(rv):4d})   {gap:+.3f}  se {se:.3f}"
              f"  z {gap/se:+5.1f}")


def selected_row(games):
    """The item's literal ask: drop the extras DRAWS and re-read. Read
    against the unselected `cov(a9, h9)` row, never on its own."""
    vals = []
    for _, draws, _ in games:
        keep = [d for d in draws if d[4] != d[5]]
        if len(keep) < 20:
            continue
        a = [d[0] for d in keep]
        h = [d[1] for d in keep]
        if st.pstdev(a) and st.pstdev(h):
            vals.append(corr(a, h))
    m, se = mean_se(vals)
    print(f"\n  EXTRAS DRAWS DROPPED (selection on a9 != h9): mean"
          f" within-game corr {m:+.4f}  se {se:.4f}  n {len(vals)} games")


def one_draw(games, real9, label):
    """One realisation per game — the shape reality has — for both the
    final and the through-nine score, model and real side by side."""
    real_fin_a = [a["away_score"] for _, _, a in games]
    real_fin_h = [a["home_score"] for _, _, a in games]
    ra9, rh9, rn = [], [], 0
    for gid, _, a in games:
        got = real9.get(gid, "missing")
        if got == "missing":
            continue                     # no play-by-play: no reg-9 truth
        rn += 1
        nine = got[1]                    # [through-eight, through-nine]
        if nine:
            ra9.append(nine[0])
            rh9.append(nine[1])
        else:                            # never reached a tenth
            ra9.append(a["away_score"])
            rh9.append(a["home_score"])
    fin, nine = [], []
    for i in range(20):
        fin.append(corr([d[i][0] for _, d, _ in games],
                        [d[i][1] for _, d, _ in games]))
        nine.append(corr([d[i][4] for _, d, _ in games],
                         [d[i][5] for _, d, _ in games]))
    n = len(games)
    print(f"\n  {label}: ONE DRAW A GAME (20 repeats), n {n},"
          f" se of a correlation {1 / n ** 0.5:.4f}")
    print(f"    model  final    corr {st.mean(fin):+.4f}"
          f"  (sd over repeats {st.pstdev(fin):.4f})")
    print(f"    real   final    corr {corr(real_fin_a, real_fin_h):+.4f}")
    print(f"    model  thru 9   corr {st.mean(nine):+.4f}"
          f"  (sd over repeats {st.pstdev(nine):.4f})")
    print(f"    real   thru 9   corr {corr(ra9, rh9):+.4f}   ({rn} games"
          f" with play-by-play)")


def extras_rows(games, real9):
    """Does the engine play the right NUMBER of extra innings, and score
    the right amount in them? A coupling that is real but the wrong size
    is a different repair from one that should not be there."""
    tied = [st.mean(1.0 if d[4] == d[5] else 0.0 for d in draws)
            for _, draws, _ in games]
    added = [st.mean((d[0] - d[4]) + (d[1] - d[5]) for d in draws
                     if d[4] == d[5]) or 0.0
             for _, draws, _ in games
             if any(d[4] == d[5] for d in draws)]
    seen = [(gid, a) for gid, _, a in games
            if real9.get(gid, "missing") != "missing"]
    r_tied = st.mean(1.0 if real9[gid][1] else 0.0 for gid, _ in seen)
    r_added = [a["away_score"] + a["home_score"]
               - real9[gid][1][0] - real9[gid][1][1]
               for gid, a in seen if real9[gid][1]]
    m, se = mean_se(tied)
    rse = (r_tied * (1 - r_tied) / len(seen)) ** 0.5
    print(f"\n  EXTRAS RATE   model {m:.4f} (se {se:.4f})   real {r_tied:.4f}"
          f" (se {rse:.4f})   z {(m - r_tied) / (se**2 + rse**2)**0.5:+.1f}")
    am, ase = mean_se(added)
    rm, rase = mean_se(r_added)
    print(f"  RUNS SCORED IN EXTRAS (both clubs, games that got there)"
          f"   model {am:.3f} (se {ase:.3f})   real {rm:.3f} (se {rase:.3f})"
          f"   z {(am - rm) / (ase**2 + rase**2)**0.5:+.1f}")


# ---------------------------------------------------------------- controls

def negative_control(games, seeds=(11, 12, 13, 14, 15)):
    """Shuffle the home club's draws within each game. Nothing else about
    the marginals changes, and the within-game correlation must vanish.

    RUN ON SEVERAL SEEDS. One seed read -0.0028 at -2.4 se, which is either
    a floor under the instrument or an ordinary 1-in-60; the spread over
    seeds is what tells them apart, and a single-seed control that lands
    two se out is exactly the kind of number that gets waved through.
    """
    got = []
    for seed in seeds:
        rng = random.Random(seed)
        vals = []
        for _, draws, _ in games:
            a = [d[0] for d in draws]
            h = [d[1] for d in draws]
            rng.shuffle(h)
            if st.pstdev(a) and st.pstdev(h):
                vals.append(corr(a, h))
        got.append(mean_se(vals))
    print("\n  NEGATIVE CONTROL (home draws shuffled within game),"
          f" {len(seeds)} seeds")
    for seed, (m, se) in zip(seeds, got):
        print(f"    seed {seed}  corr {m:+.4f}  se {se:.4f}  z {m/se:+.1f}")
    print(f"    mean {st.mean(m for m, _ in got):+.4f}  against a signal of"
          f" +0.048")


def prefix_rows(games):
    """WHERE inside nine innings? The cache already carries F5, so the
    nine-inning covariance splits again for nothing:
        cov(a9, h9) = cov(a5, h5) + [cov(a5, h69) + cov(a69, h5)]
                      + cov(a69, h69)
    F5 is the stated modelling target, so a coupling that is already there
    at five innings is a different item from one that only appears once the
    bullpens are in. Innings 6-9 are the increment, not a re-simulation —
    same draw, so the prefixes nest.
    """
    parts = {"5x5": [], "cross": [], "69x69": [], "total": []}
    sd5a, sd5h, sd6a, sd6h = [], [], [], []
    for _, draws, _ in games:
        a5 = [d[2] for d in draws]
        h5 = [d[3] for d in draws]
        a6 = [d[4] - d[2] for d in draws]
        h6 = [d[5] - d[3] for d in draws]
        parts["5x5"].append(cov(a5, h5))
        parts["cross"].append(cov(a5, h6) + cov(a6, h5))
        parts["69x69"].append(cov(a6, h6))
        parts["total"].append(cov([d[4] for d in draws],
                                  [d[5] for d in draws]))
        sd5a.append(st.pstdev(a5))
        sd5h.append(st.pstdev(h5))
        sd6a.append(st.pstdev(a6))
        sd6h.append(st.pstdev(h6))
    resid = max(abs(t - (x + c + y)) for t, x, c, y in
                zip(parts["total"], parts["5x5"], parts["cross"],
                    parts["69x69"]))
    assert resid < 1e-9, resid
    d5 = st.mean(sd5a) * st.mean(sd5h)
    d6 = st.mean(sd6a) * st.mean(sd6h)
    print(f"\n  WHERE INSIDE NINE: covariance by prefix, {len(games)} games")
    for name, key, denom in (("cov(a9, h9)  all nine", "total", None),
                             ("  F5 x F5", "5x5", d5),
                             ("  cross F5 / 6-9", "cross", None),
                             ("  6-9 x 6-9", "69x69", d6)):
        m, se = mean_se(parts[key])
        tail = f"   -> corr {m / denom:+.4f}" if denom else ""
        print(f"    {name:22s} {m:+.4f}  se {se:.4f}  z {m/se:+6.1f}"
              f"   {m / st.mean(parts['total']):6.1%} of nine{tail}")


def positive_control():
    """A synthetic league with INDEPENDENT clubs and an extras rule.

    Each club draws its nine innings from its own Poisson, independent by
    construction; a tie after nine then plays extra half-innings in which
    BOTH clubs score, exactly the coupling the hypothesis names. The
    instrument passes only if it reads ~0 through nine, clearly positive on
    the final, and books essentially all of the difference to the two
    extras terms.
    """
    # SEPARATE STREAMS PER CLUB, and the extras rule draws from a third.
    # Sharing one stream makes the number of draws consumed by the extras
    # loop depend on the game, which phase-shifts the next draw's innings —
    # a dependence the synthetic is not supposed to contain, and the first
    # run of this control read cov(a9, h9) at -3.2 se because of it.
    ra, rh, rx = random.Random(41), random.Random(42), random.Random(43)
    rs = random.Random(44)
    games = []
    for g in range(600):
        la, lh = rs.uniform(3.2, 5.6), rs.uniform(3.2, 5.6)
        draws = []
        for _ in range(200):
            a9 = sum(ra.random() < la / 18 for _ in range(18))
            h9 = sum(rh.random() < lh / 18 for _ in range(18))
            a, h = a9, h9
            while a == h:                    # the extras rule, both bat
                a += rx.random() < 0.55
                h += rx.random() < 0.55
                if a == h and rx.random() < 0.3:
                    break                    # cap, like `max_extra`
            draws.append((a, h, 0, 0, a9, h9))
        games.append((f"syn-{g}", draws, {"away_score": 0, "home_score": 0}))
    print("\n  POSITIVE CONTROL — independent clubs, extras bolted on")
    fin, nine, parts = within_rows(games, "synthetic")
    # The criterion is the ATTRIBUTION, not a threshold on the final: the
    # instrument must find nothing through nine and book the whole of the
    # final coupling to the two extras terms.
    ok = abs(nine) < 2 * parts["se_99"] and parts["extras_share"] > 0.9
    print(f"    through nine {nine:+.4f} (must be within 2 se of 0),"
          f" extras share of the final covariance"
          f" {parts['extras_share']:.1%} (must be >90%)"
          f"  ->  {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    print("LOADING CACHED DRAWS (no simulation)")
    folds = load()
    games = [g for yr in FOLDS for g in folds[yr]]
    real9 = real_prefix([gid for gid, _, _ in games])

    if not positive_control():
        raise SystemExit("the decomposition failed its positive control")

    print("\n" + "=" * 70)
    print("THE ENGINE")
    negative_control(games)
    within_rows(games, "ALL FOLDS")
    prefix_rows(games)
    margin_rows(games, real9)
    selected_row(games)
    one_draw(games, real9, "ALL FOLDS")
    real_ladder(games, real9)
    extras_rows(games, real9)

    print("\n" + "=" * 70)
    print("PER FOLD (the between-season spread is the bar — rule 12b)")
    for yr in FOLDS:
        within_rows(folds[yr], str(yr))
        prefix_rows(folds[yr])


if __name__ == "__main__":
    main()
