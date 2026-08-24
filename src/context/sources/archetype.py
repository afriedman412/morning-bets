"""Typify pitchers by what they throw. Unsupervised, so it cannot cheat.

WHY THIS IS A DIFFERENT KIND OF BET FROM THE SIX THAT FAILED. Handedness,
park, day/night, bullpen availability, arsenal multipliers and input
uncertainty were all the same move: take a known baseball effect and apply
it as an adjustment to a rate. Each was measured and each returned zero, and
the founding observation explains why — the market prices the consensus
construction, and those features ARE the consensus construction.

Clustering is not that. It never sees an outcome, so it cannot be fitted to
one and cannot manufacture a finding. It only reorganises the INPUT space.
What it buys is a better PRIOR, which is the one thing this codebase has
repeatedly found does work.

MEASURED 2026-08-24. REAL FOR RELIEVERS, ABSENT FOR STARTERS.

  * Arsenals DO NOT CLUSTER. Silhouette peaks at 0.121 at k=3 and decays
    toward zero as k rises; under ~0.25 means no real structure. Pitch mixes
    are a continuum on the simplex, not a set of types.
  * Type barely predicts rates, and WHICH POPULATION YOU TEST MATTERS —
    the first pass got this wrong by looking only at pitchers with 200+
    batters faced, which is mostly starters:

        population        n    K% R2   BB% R2
        starters        174     0.9%     2.6%
        RELIEVERS       160     5.2%     3.6%

    Relievers are ~6x starters on K%, exactly as one would predict: a
    rotation arm needs four pitches to face a lineup three times, so
    starters' mixes converge, while bullpens carry one-pitch specialists.
    Testing starters alone hides the whole effect.
  * AND A FIRST READING CALLED IT NOISE WHEN IT IS NOT. R2 with four free
    parameters is upward-biased, so the question is not "is 5% small" but
    "is it bigger than what this procedure invents from nothing". A
    permutation null — shuffle which pitcher has which arsenal, refit,
    repeat 400 times — settles it on the full season:

        pop  minBF    n     R2   null mean   p
        SP     200  186   2.7%        1.7%   0.168
        RP     100  252   4.0%        1.2%   0.015
        RP     150  171   7.6%        1.7%   0.003
        RP     200   96  13.4%        3.0%   0.003

    Relievers clear the null at every sample bar; starters never do. Net of
    the null the effect is roughly 3-10% of K% variance. Modest, real, and
    concentrated exactly where one-pitch specialists live.

  * SO THE STARTER PRIOR IS DEAD AND THE RELIEVER PRIOR IS NOT. Relievers
    throw ~40% of a full game and `game.build_side` currently shrinks thin
    arms toward the league mean, which is the case this improves.

Kept rather than deleted, on the same principle as the USE_HANDEDNESS and
USE_ARSENAL flags in `calibrate.py` — the next person with this instinct
should find the measurement, not rebuild it. The instinct is good and the
construction is sound; the data does not support discrete types, and what
signal exists lives in bullpens rather than rotations.

The two uses it was built for, both unsupported at this magnitude:

  1. A shrinkage target. A pitcher with 80 batters faced currently regresses
     toward the league, which is wrong — a knuckleballer is not a
     league-average pitcher with noise. Regressing him toward his ARCHETYPE
     keeps the underlying value, which is the rule the rest of this codebase
     already follows for catcher framing and workload.

  2. A denominator for batter-vs-arsenal. Per-pitch batter data is thin —
     3,290 rows across ~1,000 hitters, so "how does this man hit sliders" is
     mostly noise. "How does he hit power fastball/slider righties" pools
     every pitcher of the type and is thick enough to mean something.
     Sparsity is the main thing standing between the arsenal idea and a real
     signal.

CLUSTERED ON USAGE ONLY, NOT EFFECTIVENESS. We want to know what KIND of
pitcher this is, not how good he is — his quality already lives in his
rates, and folding results into the clustering would produce clusters that
mean "good" and "bad" and double-count what the simulator already has.

SOFT MEMBERSHIP, not hard labels. Pitchers do not fall into discrete bins;
plenty sit between a fastball/slider and a fastball/change profile. A
Gaussian mixture gives a weight per archetype, which is what a shrinkage
prior wants anyway — the prior becomes a weighted blend rather than a
lookup, and nobody sitting on a boundary gets snapped to the wrong side.
"""
from __future__ import annotations

import csv
import glob
import sys

import numpy as np
from sklearn.metrics import silhouette_score
from sklearn.mixture import GaussianMixture

from src import db

#: Pitch families, collapsed. Savant separates sweepers, slurves and sliders
#: — the same idea with different sweep — and splitting them three ways
#: spreads thin samples thinner for no gain in TYPE.
FAMILY = {
    "4-Seam Fastball": "FF",
    "Sinker": "SI",
    "Cutter": "FC",
    "Slider": "SL", "Sweeper": "SL", "Slurve": "SL",
    "Curveball": "CU", "Knuckle Curve": "CU",
    "Changeup": "CH", "Split-Finger": "CH",
    "Knuckleball": "KN",
}
AXES = ["FF", "SI", "FC", "SL", "CU", "CH", "KN"]

#: Minimum pitches on record before a pitcher is typed at all. Below this the
#: usage vector is itself noise and would drag a centroid toward it.
MIN_PITCHES = 200


def flip_name(n: str) -> str:
    """Savant writes "Abel, Mick"; the boxscore cache writes "Mick Abel".

    Silently unmatched names are the worst kind of bug here — every pooled
    rate came out 0.0 and the table still rendered, so it read as a modelling
    result rather than a join failure.
    """
    if "," in n:
        last, first = n.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return n.strip()


def _latest(pattern: str) -> str | None:
    f = sorted(glob.glob(f".cache/{pattern}"))
    return f[-1] if f else None


def mixes(path: str | None = None) -> dict[str, dict]:
    """{pitcher_name: {'mix': [usage per axis], 'pitches': int, 'id': str}}.

    Usage is renormalised over the families kept, so the vector sums to one
    and a pitcher with an unclassified pitch is not quietly shrunk toward
    the origin.
    """
    path = path or _latest("savant_pitch_arsenal_*.csv")
    if not path:
        return {}
    by_id: dict[str, dict] = {}
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            fam = FAMILY.get(r["pitch_name"])
            if not fam:
                continue
            rec = by_id.setdefault(r["player_id"],
                                   {"name": r["last_name, first_name"],
                                    "mix": [0.0] * len(AXES), "pitches": 0,
                                    "id": r["player_id"]})
            try:
                rec["mix"][AXES.index(fam)] += float(r["pitch_usage"] or 0)
                rec["pitches"] += int(r["pitches"] or 0)
            except (ValueError, TypeError):
                continue
    out = {}
    for rec in by_id.values():
        tot = sum(rec["mix"])
        if tot:
            rec["mix"] = [x / tot for x in rec["mix"]]
        rec["name"] = flip_name(rec["name"])
        out[rec["name"]] = rec
    return out


def choose_k(X: np.ndarray, lo: int = 3, hi: int = 10,
             seed: int = 0) -> tuple[int, list]:
    """Pick the number of archetypes by silhouette rather than by taste.

    Silhouette rewards clusters that are tight and well separated, and it
    does NOT reward more of them — unlike inertia, which falls monotonically
    and would let anyone read whatever k they had already decided on.
    """
    scores = []
    for k in range(lo, hi + 1):
        gm = GaussianMixture(n_components=k, covariance_type="full",
                             random_state=seed, n_init=5).fit(X)
        lab = gm.predict(X)
        if len(set(lab)) < 2:
            continue
        scores.append((k, float(silhouette_score(X, lab)), gm.bic(X)))
    if not scores:
        return lo, []
    best = max(scores, key=lambda s: s[1])
    return best[0], scores


def label(mix) -> str:
    """A readable name for a centroid: its dominant families."""
    order = np.argsort(mix)[::-1]
    a, b = AXES[order[0]], AXES[order[1]]
    if mix[order[0]] > 0.55:
        return f"{a}-heavy"
    return f"{a}/{b}"


def fit(k: int | None = None, seed: int = 0, min_pitches: int = MIN_PITCHES):
    """Fit archetypes. -> dict with soft memberships per pitcher.

    {'names': [...], 'X': array, 'weights': array (n x k),
     'centroids': [{'label', 'mix'}], 'k': k, 'scores': [...]}
    """
    m = {n: r for n, r in mixes().items() if r["pitches"] >= min_pitches}
    if not m:
        return {}
    names = sorted(m)
    X = np.array([m[n]["mix"] for n in names], dtype=float)
    scores = []
    if k is None:
        k, scores = choose_k(X, seed=seed)
    gm = GaussianMixture(n_components=k, covariance_type="full",
                         random_state=seed, n_init=10).fit(X)
    W = gm.predict_proba(X)
    cents = [{"label": label(c), "mix": c} for c in gm.means_]
    return {"names": names, "X": X, "weights": W, "centroids": cents,
            "k": k, "scores": scores, "model": gm,
            "index": {n: i for i, n in enumerate(names)}}


_RATE_Q = """
select p.player_name name,
       sum(p.outs_recorded) o, sum(p.h) h, sum(p.bb) bb,
       sum(p.k) k, sum(p.hr) hr
from mlb_pitching p join games g on g.game_id = p.game_id
where g.sport = 'mlb' and g.status = 'Final' {where}
group by p.player_name
"""


def archetype_rates(res: dict, before: str | None = None,
                    conn=None) -> list[dict]:
    """Pooled rates per archetype — the shrinkage prior this exists for.

    Each pitcher's counting stats are credited to every archetype in
    proportion to his MEMBERSHIP, so a man sitting between two types
    contributes to both instead of being forced into one.
    """
    where = f"and g.date < '{before}'" if before else ""

    def _run(c):
        return c.execute(_RATE_Q.format(where=where)).fetchall()
    rows = _run(conn) if conn is not None else _with(_run)
    idx, W, k = res["index"], res["weights"], res["k"]

    acc = [{"bf": 0.0, "k": 0.0, "bb": 0.0, "hr": 0.0, "h": 0.0}
           for _ in range(k)]
    for r in rows:
        i = idx.get(r["name"])
        if i is None:
            continue
        bf = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
        if bf < 1:
            continue
        for c in range(k):
            w = float(W[i][c])
            if w < 1e-4:
                continue
            acc[c]["bf"] += w * bf
            for f in ("k", "bb", "hr", "h"):
                acc[c][f] += w * (r[f] or 0)

    out = []
    for c in range(k):
        a = acc[c]
        bf = a["bf"]
        if bf < 1:
            out.append(None)
            continue
        bip = bf - a["k"] - a["bb"] - a["hr"]
        out.append({
            "label": res["centroids"][c]["label"], "bf": bf,
            "k_pct": a["k"] / bf, "bb_pct": a["bb"] / bf,
            "hr_pct": a["hr"] / bf,
            "babip": ((a["h"] - a["hr"]) / bip) if bip > 0 else None,
        })
    return out


def prior_for(name: str, res: dict, rates: list[dict]) -> dict | None:
    """This pitcher's personalised prior: his archetypes, weighted.

    The point of soft membership. A man who is 70% fastball/slider and 30%
    fastball/change regresses toward a blend of the two, not to whichever
    label won by a nose.
    """
    i = res["index"].get(name)
    if i is None:
        return None
    W = res["weights"][i]
    out = {}
    for stat in ("k_pct", "bb_pct", "hr_pct", "babip"):
        num = den = 0.0
        for c, r in enumerate(rates):
            if r and r.get(stat) is not None:
                num += float(W[c]) * r[stat]
                den += float(W[c])
        out[stat] = num / den if den else None
    return out


def _with(fn):
    with db.connect() as c:
        return fn(c)


if __name__ == "__main__":
    k = None
    for a in sys.argv[1:]:
        if a.startswith("--k="):
            k = int(a.split("=")[1])
    res = fit(k=k)
    if not res:
        print("no arsenal cache found")
        sys.exit(1)
    if res["scores"]:
        print("  k  silhouette        BIC")
        for kk, s, b in res["scores"]:
            mark = "  <- chosen" if kk == res["k"] else ""
            print(f"  {kk:<3}{s:>11.3f}{b:>11.0f}{mark}")
    W = res["weights"]
    hard = W.argmax(axis=1)
    rates = archetype_rates(res)
    print(f"\n{len(res['names'])} pitchers, k={res['k']}\n")
    print("  " + "".join(f"{ax:>6}" for ax in AXES)
          + f"{'n':>5}{'K%':>7}{'BB%':>7}{'BABIP':>7}   archetype")
    for c in sorted(range(res["k"]), key=lambda c: -(hard == c).sum()):
        mix = res["centroids"][c]["mix"]
        r = rates[c] or {}
        print("  " + "".join(f"{x * 100:>6.0f}" for x in mix)
              + f"{int((hard == c).sum()):>5}"
              + f"{(r.get('k_pct') or 0) * 100:>7.1f}"
              + f"{(r.get('bb_pct') or 0) * 100:>7.1f}"
              + f"{(r.get('babip') or 0):>7.3f}"
              + f"   {res['centroids'][c]['label']}")
        ex = [n for n, h in zip(res["names"], hard) if h == c][:3]
        print(f"        e.g. {', '.join(ex)}")
