"""Fit the two hooks separately and score them against the shipped one.

    venv/bin/python -m scratchpad.fit_hooks [n_games]
    venv/bin/python -m scratchpad.fit_hooks --rebuild [--rows-only]

The comparison is like for like: the shipped single model is refit here on
the same rows with the same holdout, so any difference is the SPLIT and the
current-inning features, not a different training window.
"""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict

import numpy as np
from sklearn.linear_model import LogisticRegression

from src import db
from src.context import boundary, removal
from src.context.sources import pbp

CUTOFF = "2026-07-15"


def leashes() -> dict:
    """{(pitcher_name, date): {...}} from PRIOR starts only.

    Expanding and trailing versions both, so the recency question is
    measured rather than asserted.
    """
    q = """select p.player_name n, g.date d, p.outs_recorded o, p.k, p.bb,
                  p.outs_recorded + p.h + p.bb bf
           from mlb_pitching p join games g on g.game_id = p.game_id
           where p.is_starter = 1 and g.status = 'Final'
             and p.outs_recorded is not null
           order by g.date"""
    with db.connect() as c:
        rows = [dict(r) for r in c.execute(q)]
    hist: dict = defaultdict(list)
    out: dict = {}
    for r in rows:
        h = hist[r["n"]]
        if len(h) >= boundary.LEASH_MIN_STARTS:
            recent = h[-boundary.RECENT_WINDOW:]
            bf = sum(x["bf"] for x in h) or 1
            out[(r["n"], r["d"])] = {
                "leash": st.mean(x["o"] for x in h),
                "leash_recent": st.mean(x["o"] for x in recent),
                "kbb": (sum(x["k"] for x in h) - sum(x["bb"] for x in h)) / bf,
            }
        h.append(r)
    return out


#: Set in the PARENT and read by the pool's children through fork. The
#: three maps cost a few seconds to build and tens of megabytes to hold;
#: a spawn child would rebuild all three, which is most of what the
#: parallelism just bought.
_CTX: dict = {}


def _rows_for(gid):
    """One game's decision rows, or None if it has no play-by-play.

    `boundary.decisions` reads the gzip cache and touches no database, so
    this is pure CPU per game and the only reason `build` was ever slow.
    """
    if not pbp.have(gid):
        return None
    try:
        rs = boundary.decisions(gid)
    except Exception:
        return None
    lz, names = _CTX["lz"], _CTX["names"]
    d = _CTX["dates"].get(gid)
    out = []
    for r in rs:
        lz_ = lz.get((names.get(r["pitcher"], ""), d))
        if not lz_:
            continue
        r.update(lz_, date=d)
        out.append(r)
    return out


def build(limit=None, workers=None):
    """Every hook decision in the cache.

    PARALLEL SINCE 2026-09-24, and that is the whole change — the rows
    are the same rows in the same order. This walked ~10,000 gzipped
    games on one core and was 2m54s of a 4m06s daily backfill while
    eleven cores sat idle; `velo.build` had used a pool over the same
    cache for weeks. Order is preserved because `imap` yields in the
    order of `ids`, which is what the caller's train/test split by date
    and every saved cache already assume.
    """
    import multiprocessing as mp
    ids = pbp.final_games()
    if limit:
        ids = ids[:limit]
    from src.context import store
    with db.connect() as c:
        dates = {r["game_id"]: r["date"] for r in
                 c.execute("select game_id, date from games where sport='mlb'")}
    with store.connect() as c:
        names = {r["pitcher_id"]: r["player_name"] for r in
                 c.execute("select distinct pitcher_id, player_name "
                           "from mlb_stints")}
    _CTX.update(lz=leashes(), dates=dates, names=names)

    rows, n = [], 0
    w = workers or max(1, round((mp.cpu_count() or 2) * 2 / 3))
    with mp.get_context("fork").Pool(w) as pool:
        for got in pool.imap(_rows_for, ids, chunksize=16):
            if got is None:
                continue
            n += 1
            rows.extend(got)
            if n % 400 == 0:
                print(f"  {n} games, {len(rows):,} decisions", flush=True)
    return rows


def _xy(rows, feats):
    X = np.array([[float(r[f]) for f in feats] for r in rows])
    y = np.array([1 if r["removed"] else 0 for r in rows])
    return X, y


def fit_one(rows, feats, label, cutoff=CUTOFF):
    tr = [r for r in rows if r["date"] < cutoff]
    te = [r for r in rows if r["date"] >= cutoff]
    if len(te) < 200 or len(set(r["removed"] for r in tr)) < 2:
        print(f"  {label}: too few rows ({len(tr)} train, {len(te)} test)")
        return None
    Xtr, ytr = _xy(tr, feats)
    Xte, yte = _xy(te, feats)
    mu, sd = Xtr.mean(0), Xtr.std(0)
    sd[sd == 0] = 1.0
    m = LogisticRegression(max_iter=2000, C=1.0)
    m.fit((Xtr - mu) / sd, ytr)
    p = m.predict_proba((Xte - mu) / sd)[:, 1]
    a = removal.auc(yte, p)
    ll = removal.log_loss(yte, p)
    print(f"\n  {label}")
    print(f"    {len(tr):,} train / {len(te):,} test   base rate "
          f"{yte.mean():.3f}   AUC {a:.4f}   log loss {ll:.4f}")
    order = sorted(zip(feats, m.coef_[0]), key=lambda x: -abs(x[1]))
    print("    " + "  ".join(f"{f} {c:+.3f}" for f, c in order[:8]))
    return {"auc": a, "ll": ll, "n": len(te), "y": yte, "p": p}


CACHE = "/tmp/hook_rows.json"


def limit_arg(argv) -> int | None:
    """The positional row limit, ignoring flags. None means "all rows".

    ITS OWN FUNCTION so it can be tested without rebuilding 10,000 games.
    The bug it replaces: `main` did `int(sys.argv[1])` unconditionally and
    checked for `--rebuild` on the NEXT line, so the one documented way to
    refresh `/tmp/hook_rows.json` crashed on its own flag. Found 2026-09-09
    wiring `/backfill-data`, and it is the same class as the `make
    calibrate` finding in CLAUDE.md — a command in the docs that could not
    work.
    """
    pos = [a for a in argv if not a.startswith("-")]
    return int(pos[0]) if pos else None


def rows_only(argv) -> bool:
    """Is this the backfill asking for the cache and nothing else?

    ITS OWN FUNCTION for the same reason `limit_arg` is one — so the flag
    can be tested without rebuilding 10,000 games. An `in sys.argv` check
    buried in `main` is only assertable by reading the source back, and a
    source-reading test passes on the COMMENT that explains the flag.
    """
    return "--rows-only" in argv


def main():
    import json
    import os
    lim = limit_arg(sys.argv[1:])
    if lim is None and os.path.exists(CACHE) and "--rebuild" not in sys.argv:
        rows = json.load(open(CACHE))
        print(f"{len(rows):,} decisions from cache")
    else:
        rows = build(lim)
        if lim is None:
            json.dump(rows, open(CACHE, "w"))
    # THE DAILY BACKFILL WANTS THE ROWS, NOT THE RESEARCH. Everything
    # below refits six logistic models and prints a pooled-vs-split
    # comparison — 21s a morning into a log nobody reads, and not one
    # consumer of the cache looks at the output. `--rows-only` writes the
    # file and stops; the comparison is still one command away when the
    # hook is actually being worked on.
    if rows_only(sys.argv[1:]):
        print(f"\n{len(rows):,} decisions cached -> {CACHE}")
        return

    mid = [r for r in rows if not r["ends_inning"]]
    bnd = [r for r in rows if r["ends_inning"]]
    print(f"\n{len(rows):,} decisions: {len(mid):,} mid-inning, "
          f"{len(bnd):,} at an inning boundary")
    print(f"  removal rate: mid {st.mean(r['removed'] for r in mid):.4f}, "
          f"boundary {st.mean(r['removed'] for r in bnd):.4f}")

    print("\n=== POOLED, the shipped shape (one model, no current-inning "
          "features) ===")
    pooled_feats = ("pitches", "bf", "tto", "br", "damage", "inning",
                    "outs_before", "margin", "abs_margin", "runs")
    a = fit_one(rows, pooled_feats, "pooled / shipped features")
    b = fit_one(rows, pooled_feats + ("leash", "kbb"),
                "pooled + leash and quality")
    c = fit_one(rows, pooled_feats + ("leash", "kbb", "inn_runs", "inn_br",
                                      "inn_dmg"),
                "pooled + current-inning features")

    print("\n=== SPLIT ===")
    m = fit_one(mid, boundary.MID_FEATURES, "MID-INNING hazard")
    n_ = fit_one(bnd, boundary.BOUNDARY_FEATURES, "BOUNDARY hazard")

    if m and n_ and a:
        # Combined score over the same test rows the pooled model saw.
        y = np.concatenate([m["y"], n_["y"]])
        p = np.concatenate([m["p"], n_["p"]])
        ll = removal.log_loss(y, p)
        au = removal.auc(y, p)
        print(f"\n  SPLIT combined over {len(y):,} test decisions   "
              f"AUC {au:.4f}   log loss {ll:.4f}")
        print(f"  pooled/shipped                                   "
              f"AUC {a['auc']:.4f}   log loss {a['ll']:.4f}")
        print(f"  pooled + current-inning                          "
              f"AUC {c['auc']:.4f}   log loss {c['ll']:.4f}")

    print("\n=== does a TRAILING leash beat a season one? ===")
    fit_one(mid, tuple(f for f in boundary.MID_FEATURES if f != "leash")
            + ("leash_recent",), "MID, trailing-5 leash")
    fit_one(bnd, tuple(f for f in boundary.BOUNDARY_FEATURES if f != "leash")
            + ("leash_recent",), "BOUNDARY, trailing-5 leash")


if __name__ == "__main__":
    main()
