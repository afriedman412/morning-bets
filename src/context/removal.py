"""When does the starter come out? A decision model, fitted to real hooks.

FOUR PREVIOUS ATTEMPTS AND WHY THIS IS NOT A FIFTH. `calibrate.tune`, the 206
club-patience and pitcher-leash offsets, `fitf5 --with-hook`, and the relief
hazard in `relief.py` all fitted a hand-specified logistic to AGGREGATE
targets — a hazard curve, a boundary share, an F5 loss. `sim.Hook`'s own
docstring names the limit: it can reproduce how often starters are pulled
after the fifth "without knowing that this one was pulled because he had
thrown 28 pitches that inning."

The play-by-play removes that excuse. Every pitching change now has the
base-out-score state that preceded it, so the target is the DECISION itself
— was this man removed before the next batter — scored per plate appearance
rather than in aggregate.

That also makes it a BEHAVIOURAL MEASUREMENT rather than a fit against the
settlement value: the loss is on what managers actually did, not on the
quantity we price. Same footing as `advance.py` and `relief.py`.

WHAT IT KEYS ON, AND WHY NOT RUNS. Runs allowed are a lagging indicator and
measured on this league they are nearly useless as a signal: a starter's
runs in his first pass predict his next pass's runs at r = +0.008. A rule
keyed on runs is keyed on noise. Baserunners lead, runs follow — a pitcher
who has put five men on and been charged nothing is about to be removed, and
`sim.DAMAGE`'s docstring already says so without the model acting on it.

So the features are traffic and workload, not runs:

    on base NOW              the immediate situation
    baserunners allowed      cumulative H + BB, the leading indicator
    cumulative damage        weighted, and NOT reset each inning the way
                             `Frame.damage` is
    pitches, batters faced   workload
    times through the order  familiarity, worth 19% of his strikeout rate
    inning, outs, margin     game state
    the pitcher's own rates  an ace is left in situations a swingman is not
    the club                 manager tendency, shrunk

SHRINKAGE IS THE POINT, NOT AN AFTERTHOUGHT. Club effects enter as one-hot
columns under an L2 penalty, which IS partial pooling: a club with little
evidence is pulled to zero and contributes nothing, a club with a real and
consistent tendency survives. That is the protocol the per-club advancement
work failed and the bullpen-role work passed, applied here rather than
bolted on as 30 separate offsets the way `hook_patience.json` was.

REQUIRES numpy and scikit-learn, now declared in `requirements.txt`.
`sources/archetype.py` had been importing both without declaring them, so a
fresh install would have crashed there; that is fixed by the same change.
"""
from __future__ import annotations

import json
import math
import os
import pathlib

from src.context.sources import pbp
from src.context import atomic

CACHE = pathlib.Path(".cache/removal_decisions.json")

#: Weighted trouble per outcome. Same shape as `sim.DAMAGE` but accumulated
#: over the WHOLE START rather than reset each inning, which is the defect
#: that makes a starter squared up for three innings look clean whenever he
#: happens to be between rallies.
DAMAGE = {"walk": 1.0, "intent_walk": 1.0, "hit_by_pitch": 1.0,
          "single": 1.0, "double": 1.7, "triple": 2.3, "home_run": 3.0,
          "field_error": 0.5}

#: Not plate appearances. They belong in the base state and in no
#: denominator.
SKIP = {"stolen_base", "caught_stealing", "wild_pitch", "passed_ball",
        "pickoff", "stolen_base_2b", "stolen_base_3b", "caught_stealing_2b",
        "caught_stealing_3b", "pickoff_1b", "pickoff_2b", "pickoff_3b",
        "other_advance", "defensive_indiff", "balk"}


def _decisions_for(game_id: str, data: dict | None = None) -> list[dict]:
    """One row per plate appearance faced by a starter.

    `removed` is whether a different pitcher faced the next batter of the
    same half-inning OR the starter did not return for the next half-inning
    his side pitched — a hook at the end of an inning is still a hook.
    """
    data = data if data is not None else pbp.fetch(game_id)
    if not data:
        return []
    plays = [p for p in (data.get("allPlays") or [])
             if ((p.get("result") or {}).get("eventType") or "") not in SKIP]
    starter: dict = {}
    state: dict = {}
    # Every play index at which each side's pitcher is identified, so
    # "who faced the next batter" is a lookup rather than a guess.
    out: list[dict] = []
    prev_score = 0
    for i, play in enumerate(plays):
        ab = play.get("about") or {}
        mu = play.get("matchup") or {}
        pid = (mu.get("pitcher") or {}).get("id")
        if not pid:
            continue
        top = bool(ab.get("isTopInning"))
        side = "home" if top else "away"
        starter.setdefault(side, pid)
        s = state.setdefault(side, {"pitches": 0, "bf": 0, "runs": 0,
                                    "dmg": 0.0, "onbase": 0, "br": 0})
        if starter[side] != pid:
            continue

        res = play.get("result") or {}
        score = (res.get("awayScore", 0) or 0) + (res.get("homeScore", 0) or 0)
        runs_now = max(score - prev_score, 0)
        prev_score = score

        # The next plate appearance this side pitches to, whenever it comes.
        nxt = next((p for p in plays[i + 1:]
                    if bool((p.get("about") or {}).get("isTopInning")) == top),
                   None)
        if nxt is None:
            break
        nxt_pid = ((nxt.get("matchup") or {}).get("pitcher") or {}).get("id")
        removed = bool(nxt_pid and nxt_pid != pid)

        cnt = play.get("count") or {}
        margin = ((res.get("homeScore", 0) or 0) - (res.get("awayScore", 0) or 0))
        out.append({
            "game_id": game_id, "pitcher": pid, "side": side,
            "inning": ab.get("inning") or 1,
            "outs": cnt.get("outs", 0) or 0,
            # STATE BEFORE THE DECISION, which is what the manager saw.
            "pitches": s["pitches"], "bf": s["bf"],
            "tto": min(s["bf"] // 9 + 1, 3),
            "runs": s["runs"], "onbase": s["onbase"],
            # Cumulative baserunners allowed. THE leading indicator: a
            # starter's runs predict his next pass at r = +0.008, so a rule
            # keyed on runs is keyed on noise. Traffic comes first.
            "br": s["br"], "damage": s["dmg"],
            # Margin from the pitching side's point of view: positive means
            # his team is ahead, which is when a manager protects a lead.
            "margin": margin if side == "home" else -margin,
            "removed": removed,
        })

        ev = (res.get("eventType") or "")
        s["bf"] += 1
        s["runs"] += runs_now
        s["dmg"] += DAMAGE.get(ev, 0.0)
        s["pitches"] += sum(1 for e in (play.get("playEvents") or [])
                            if e.get("isPitch"))
        if ev in ("single", "double", "triple", "home_run", "walk",
                  "intent_walk", "hit_by_pitch", "field_error"):
            s["br"] += 1
        s["onbase"] = _on_base(play)
    return out


def _on_base(play: dict) -> int:
    """Runners left on after this play, from the runner records."""
    ends = {}
    for r in (play.get("runners") or []):
        mv = r.get("movement") or {}
        rid = ((r.get("details") or {}).get("runner") or {}).get("id")
        if rid is None:
            continue
        if mv.get("end") is not None or mv.get("isOut"):
            ends[rid] = (mv.get("end"), bool(mv.get("isOut")))
    return sum(1 for end, is_out in ends.values()
               if not is_out and end in ("1B", "2B", "3B"))


def build(limit: int | None = None, verbose: bool = True) -> list[dict]:
    """Extract every starter decision, cached — the scrape is the slow part."""
    if CACHE.exists() and limit is None:
        return json.loads(CACHE.read_text())
    ids = pbp.final_games()
    if limit:
        ids = ids[:limit]
    rows: list[dict] = []
    n = 0
    for gid in ids:
        if not pbp.have(gid):
            continue
        try:
            rows.extend(_decisions_for(gid))
        except Exception:
            continue
        n += 1
        if verbose and n % 400 == 0:
            print(f"  {n} games, {len(rows):,} decisions", flush=True)
    if limit is None:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_text(CACHE, json.dumps(rows))
    return rows


def summary(rows: list[dict]) -> None:
    n = len(rows)
    rem = sum(1 for r in rows if r["removed"])
    print(f"\n{n:,} starter decisions, {rem:,} removals "
          f"(base rate {rem / n:.2%})")
    print("\n  removal rate by cumulative baserunners allowed")
    for lo, hi in ((0, 2), (3, 4), (5, 6), (7, 8), (9, 99)):
        g = [r for r in rows if lo <= r["br"] <= hi]
        if len(g) > 200:
            print(f"    {lo}-{hi if hi < 99 else '+':<3} "
                  f"{sum(1 for r in g if r['removed']) / len(g):>7.2%}"
                  f"   n={len(g):,}")
    print("\n  removal rate by pitches thrown")
    for lo, hi in ((0, 39), (40, 59), (60, 79), (80, 94), (95, 999)):
        g = [r for r in rows if lo <= r["pitches"] <= hi]
        if len(g) > 200:
            print(f"    {lo}-{hi if hi < 999 else '+':<4} "
                  f"{sum(1 for r in g if r['removed']) / len(g):>7.2%}"
                  f"   n={len(g):,}")


if __name__ == "__main__":
    import sys
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    rows = build(limit=lim)
    summary(rows)
    print(f"\n  cached to {CACHE}" if lim is None else "\n  (not cached)")


# ---------------------------------------------------------------------------
# The model.
# ---------------------------------------------------------------------------

#: Everything the manager can see, in the order the coefficients print. Runs
#: is included ONLY so the fit can tell us what it is worth next to traffic —
#: the expectation, from r = +0.008 for runs predicting runs, is that it adds
#: little once baserunners are in.
FEATURES = ("pitches", "bf", "tto", "br", "damage", "onbase", "inning",
            "outs", "margin", "abs_margin", "runs",
            "k_pct", "bb_pct", "quality")


def _rows_with_rates(rows, before=None):
    """Attach each starter's own season rates. An ace is left in situations
    a swingman is not, so the model has to know who is pitching."""
    from src.context import sim
    from src.context.sources import rates as rate_src
    from src.context import store

    lg = sim.league(before=before)
    pr = rate_src.pitcher_rates(lg, before=before)
    with store.connect() as c:
        name = {r["pitcher_id"]: r["player_name"] for r in c.execute(
            "select distinct pitcher_id, player_name from mlb_stints")}
    out = []
    for r in rows:
        p = pr.get(name.get(r["pitcher"], ""))
        r = dict(r)
        r["k_pct"] = p["k_pct"] if p else lg["k_pct"]
        r["bb_pct"] = p["bb_pct"] if p else lg["bb_pct"]
        r["quality"] = r["k_pct"] - r["bb_pct"]
        r["abs_margin"] = abs(r["margin"])
        out.append(r)
    return out


def fit(rows, cutoff="2026-07-15", clubs=True, C=1.0, verbose=True):
    """Fit on decisions before `cutoff`, score on the ones after.

    A DATE holdout, not a random split: rows from the same game are not
    independent — a starter's twenty plate appearances share his afternoon —
    so a random split leaks the answer across the boundary and every model
    looks good.
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from src.context import store

    with store.connect() as c:
        gdate = {str(r["game_id"]): r["date"] for r in c.execute(
            "select game_id, date from bets.games")}
        gteam = {str(r["game_id"]): (r["away_team_abbr"], r["home_team_abbr"])
                 for r in c.execute(
                     "select game_id, away_team_abbr, home_team_abbr "
                     "from bets.games")}

    rows = [r for r in rows if gdate.get(str(r["game_id"]))]
    for r in rows:
        a, h = gteam.get(str(r["game_id"]), (None, None))
        r["club"] = h if r["side"] == "home" else a

    clubs_seen = sorted({r["club"] for r in rows if r["club"]})
    idx = {c_: i for i, c_ in enumerate(clubs_seen)}

    def design(rs):
        X = np.zeros((len(rs), len(FEATURES) + (len(idx) if clubs else 0)))
        for i, r in enumerate(rs):
            for j, f in enumerate(FEATURES):
                X[i, j] = r[f]
            if clubs and r.get("club") in idx:
                X[i, len(FEATURES) + idx[r["club"]]] = 1.0
        return X

    tr = [r for r in rows if gdate[str(r["game_id"])] < cutoff]
    te = [r for r in rows if gdate[str(r["game_id"])] >= cutoff]
    Xtr, ytr = design(tr), np.array([r["removed"] for r in tr], dtype=float)
    Xte, yte = design(te), np.array([r["removed"] for r in te], dtype=float)
    mu, sd = Xtr.mean(0), Xtr.std(0)
    sd[sd == 0] = 1.0
    m = LogisticRegression(C=C, max_iter=2000)
    m.fit((Xtr - mu) / sd, ytr)
    p = m.predict_proba((Xte - mu) / sd)[:, 1]

    if verbose:
        print(f"\n  train {len(tr):,} decisions before {cutoff}, "
              f"test {len(te):,} after")
        print(f"  test base rate {yte.mean():.2%}")
    return {"model": m, "mu": mu, "sd": sd, "idx": idx, "clubs": clubs,
            "p": p, "y": yte, "test": te, "features": list(FEATURES)}


def auc(y, p) -> float:
    """Rank-based, no ties assumption. Hand-rolled like the rest."""
    pairs = sorted(zip(p, y))
    n_pos = sum(y)
    n_neg = len(y) - n_pos
    if not n_pos or not n_neg:
        return 0.5
    rank_sum = 0.0
    for i, (_, yy) in enumerate(pairs, start=1):
        if yy:
            rank_sum += i
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def log_loss(y, p) -> float:
    import numpy as np
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


MODEL_PATH = pathlib.Path("src/context/removal_model.json")


def train_and_save(cutoff="2026-07-15", path=MODEL_PATH) -> dict:
    """Fit on the training window and persist plain coefficients.

    CLUB EFFECTS ARE DROPPED. Measured, all 30 of them together are worth
    +0.002 AUC (0.9143 with, 0.9123 without) and their whole spread is 0.21
    in standardised log-odds. Carrying them would mean threading club
    identity through the simulator for nothing, and it is the fifth
    independent finding that team-specific hook effects do not pay.

    Saved as coefficients rather than a pickled estimator so the simulator
    needs no sklearn at run time — the prediction is a dot product.
    """
    rows = _rows_with_rates(build(), before=cutoff)
    res = fit(rows, cutoff=cutoff, clubs=False, verbose=False)
    m = res["model"]
    blob = {
        "features": list(FEATURES),
        "coef": [float(x) for x in m.coef_[0][:len(FEATURES)]],
        "intercept": float(m.intercept_[0]),
        "mu": [float(x) for x in res["mu"][:len(FEATURES)]],
        "sd": [float(x) for x in res["sd"][:len(FEATURES)]],
        "cutoff": cutoff,
        "auc": auc(res["y"], res["p"]),
        "log_loss": log_loss(res["y"], res["p"]),
        "n_train": len(rows) - len(res["test"]),
        "n_test": len(res["test"]),
    }
    atomic.write_text(path, json.dumps(blob, indent=1))
    return blob


_MODEL: dict | None = None


def model() -> dict | None:
    global _MODEL
    if _MODEL is None and MODEL_PATH.exists():
        _MODEL = json.loads(MODEL_PATH.read_text())
    return _MODEL


def predict(state: dict) -> float:
    """P(this starter is replaced before the next batter he would face).

    Pure Python on purpose: this runs once per simulated plate appearance,
    millions of times in a pricing run, and must not import a solver.
    """
    m = model()
    if not m:
        return 0.0
    z = m["intercept"]
    for f, c, mu, sd in zip(m["features"], m["coef"], m["mu"], m["sd"]):
        z += c * ((state.get(f, 0.0) - mu) / (sd or 1.0))
    if z < -30:
        return 0.0
    if z > 30:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))
