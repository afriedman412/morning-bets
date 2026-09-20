"""WHERE DOES THE AGGREGATE HOOK MISS? — a decision-level residual screen.

    venv/bin/python -m scratchpad.hook_resid [--control 0.4] [--holdout-only]

QUESTION    Both hook curves are league aggregates with a per-pitcher and
            per-club offset bolted on. Evaluated on REAL game states, is the
            residual (actual removal - predicted p) flat, or does it have
            structure the curve cannot express?

WHY THIS SHAPE. This is a CALIBRATION screen on the decision, not a score on
the outs distribution. The two are different and the difference matters: the
simulator's outs error mixes the curve's error with the error in the STATES
it reaches, and a screen on real states holds the second one fixed. A miss
here is the curve's own.

THE CONDITIONING MATCHES THE CODE PATH (rule 10). Every argument is the one
`game._half_inning` passes at the two call sites, including the leash and
patience offsets through `sim.for_start`, and the `hard_pitch_cap` OR. TWO
EXCEPTIONS, both stated rather than hidden:

  * `pen` (arms unavailable, club rest) is NOT reconstructed — it needs a
    club's rolling bullpen state, which these rows do not carry. It is a
    CENTRED term, so it contributes zero on average and adds noise to any
    slice; a club-level slice is where that noise would bite, so club rows
    are read with that caveat attached.
  * `forced_exit_outs` is the opener path. It does not apply to these rows.

STANDARD ERRORS ARE CLUSTERED ON (game, side). Six boundary decisions from
one start are one manager on one night, not six independent draws. The
binomial se is printed next to it so the inflation is visible.

POSITIVE CONTROL (rule 7). `--control X` adds X log-odds to the predicted p
of every decision in a named subgroup and re-runs the screen. The subgroup's
row must come back at the injected size and the others must stay flat, or
the screen cannot see what it claims to be looking for.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics as st
import sys
from collections import defaultdict

from src.context import sim
from src.context.holdout import HOLDOUT

ROWS = "/tmp/hook_rows.json"
MIN_N = 200


# ── inputs ─────────────────────────────────────────────────────────────

def load_rows() -> list[dict]:
    if not os.path.exists(ROWS):
        sys.exit(f"  {ROWS} missing — build it with scratchpad.fit_hooks")
    return json.load(open(ROWS))


def attach_context(rows: list[dict]) -> None:
    """Pitching club, pitcher NAME (the leash key) and days since his last
    start. All three are joins the row set does not carry."""
    from src import db
    from src.context import store

    games = {}
    with db.connect() as c:
        for r in c.execute("select game_id, date, away_team_abbr, "
                           "home_team_abbr, day_night from games "
                           "where sport='mlb'"):
            games[r["game_id"]] = dict(r)

    names: dict[int, str] = {}
    with store.connect() as c:
        for r in c.execute("select pitcher_id, player_name from mlb_stints "
                           "where player_name is not null"):
            names.setdefault(int(r["pitcher_id"]), r["player_name"])

    for r in rows:
        g = games.get(r["game_id"]) or {}
        # The PITCHING side. `side` on a decision row is already the
        # fielding club — 'home' on a top-inning play — so this is a
        # straight lookup, not a flip.
        r["team"] = (g["home_team_abbr"] if r["side"] == "home"
                     else g["away_team_abbr"]) if g else None
        r["day_night"] = (g or {}).get("day_night")
        r["name"] = names.get(int(r["pitcher"]), "")

    # Days since his previous START, from the rows themselves: the first
    # decision row of a game is a start. None across a season break.
    starts: dict[int, set] = defaultdict(set)
    for r in rows:
        starts[r["pitcher"]].add(r["date"])
    prev: dict[tuple[int, str], int | None] = {}
    for pid, dates in starts.items():
        ds = sorted(dates)
        for i, d in enumerate(ds):
            if i == 0 or d[:4] != ds[i - 1][:4]:
                prev[(pid, d)] = None
            else:
                prev[(pid, d)] = _daygap(ds[i - 1], d)
    for r in rows:
        r["gap"] = prev.get((r["pitcher"], r["date"]))


def _daygap(a: str, b: str) -> int:
    from datetime import date
    pa = date(*map(int, a.split("-")))
    pb = date(*map(int, b.split("-")))
    return (pb - pa).days


# ── the model's own number ─────────────────────────────────────────────

def predict(rows: list[dict]) -> None:
    """`p` on every row, from the SHIPPED hook, with the same offsets and
    the same hard cap `game._half_inning` applies."""
    base = sim.Hook()
    hooks: dict[tuple, sim.Hook] = {}
    for r in rows:
        key = (r["team"], r["name"])
        h = hooks.get(key)
        if h is None:
            h = hooks[key] = sim.for_start(base, r["team"], r["name"])
        gap = r["gap"]
        if r["ends_inning"]:
            p = h.removal_p(
                r["pitches"], r["runs"], r["inning"], r["br"], r["margin"],
                inning_runs=r["inn_runs"], pen=None, layoff_gap=gap,
                month_offset=(sim.bnd_month_offset(r["date"])
                              if sim.USE_HOOK_MONTH else 0.0))
        else:
            p = h.mid_removal_p(
                r["pitches"], r["runs"], r["onbase"], r["inn_dmg"],
                r["margin"], inning_runs=r["inn_runs"], inning=r["inning"],
                inning_br=r["inn_br"], k_rate=r["k_rate"], pen=None,
                layoff_gap=gap)
        if r["pitches"] >= h.hard_pitch_cap:
            p = 1.0
        r["p"] = p
        r["e"] = (1.0 if r["removed"] else 0.0) - p


# ── the screen ─────────────────────────────────────────────────────────

def cell(rows: list[dict]) -> dict:
    """Observed vs predicted with BOTH standard errors.

    `se_bin` treats every decision as independent. `se_cl` clusters on
    (game, side) — one manager, one night — and is the one to read.
    """
    n = len(rows)
    obs = sum(1 for r in rows if r["removed"]) / n
    pred = sum(r["p"] for r in rows) / n
    se_bin = math.sqrt(sum(r["p"] * (1 - r["p"]) for r in rows)) / n
    byc: dict = defaultdict(float)
    for r in rows:
        byc[(r["game_id"], r["side"])] += r["e"]
    se_cl = math.sqrt(sum(v * v for v in byc.values())) / n
    diff = obs - pred
    return {"n": n, "obs": obs, "pred": pred, "diff": diff,
            "se_bin": se_bin, "se_cl": se_cl,
            "z": diff / se_cl if se_cl else 0.0}


def _by(rows: list[dict], keyfn) -> dict:
    out: dict = defaultdict(list)
    for r in rows:
        out[keyfn(r)].append(r)
    return out


def table(title: str, rows: list[dict], keyfn, order=None,
          min_n: int = MIN_N) -> list[tuple]:
    groups: dict = defaultdict(list)
    for r in rows:
        k = keyfn(r)
        if k is not None:
            groups[k].append(r)
    keys = [k for k in (order or sorted(groups))
            if len(groups.get(k, ())) >= min_n]
    print(f"\n  {title}")
    print(f"    {'cell':<16}{'n':>8}{'real':>9}{'model':>9}"
          f"{'diff':>9}{'se':>8}{'z':>7}")
    out = []
    for k in keys:
        c = cell(groups[k])
        flag = "  <<<" if abs(c["z"]) >= 3 else ("  <" if abs(c["z"]) >= 2
                                                 else "")
        print(f"    {str(k):<16}{c['n']:>8,}{c['obs']:>9.4f}{c['pred']:>9.4f}"
              f"{c['diff']:>+9.4f}{c['se_cl']:>8.4f}{c['z']:>+7.1f}{flag}")
        out.append((k, c))
    return out


# ── slicers ────────────────────────────────────────────────────────────

def _bucket(v, edges):
    for e in edges:
        if v < e:
            return f"<{e}"
    return f"{edges[-1]}+"


def margin_cell(r):
    m = r["margin"]
    if m <= -5:
        return "trail 5+"
    if m <= -2:
        return "trail 2-4"
    if m <= -1:
        return "trail 1"
    if m == 0:
        return "tied"
    if m == 1:
        return "lead 1"
    if m <= 4:
        return "lead 2-4"
    return "lead 5+"


MARGIN_ORDER = ["trail 5+", "trail 2-4", "trail 1", "tied", "lead 1",
                "lead 2-4", "lead 5+"]
MONTHS = ["03", "04", "05", "06", "07", "08", "09", "10"]
SEASONS = ["2023", "2024", "2025", "2026"]


def slices(rows: list[dict], kind: str) -> None:
    table("BY SEASON", rows, lambda r: r["date"][:4])
    table("BY MONTH", rows, lambda r: r["date"][5:7], order=MONTHS)
    table("BY INNING", rows, lambda r: min(r["inning"], 9),
          order=list(range(1, 10)))
    table("BY PITCH COUNT", rows,
          lambda r: _bucket(r["pitches"], [30, 45, 60, 70, 80, 90, 100]),
          order=["<30", "<45", "<60", "<70", "<80", "<90", "<100", "100+"])
    table("BY TIMES THROUGH", rows, lambda r: r["tto"], order=[1, 2, 3])
    table("BY SCORE MARGIN", rows, margin_cell, order=MARGIN_ORDER)
    table("BY RUNS ALLOWED", rows, lambda r: min(r["runs"], 6),
          order=list(range(0, 7)))
    table("BY K RATE (dominance)", rows,
          lambda r: _bucket(r["k_rate"], [0.10, 0.18, 0.25, 0.33]),
          order=["<0.1", "<0.18", "<0.25", "<0.33", "0.33+"])
    table("BY DAYS REST", rows,
          lambda r: (None if r["gap"] is None
                     else _bucket(r["gap"], [4, 5, 6, 7])),
          order=["<4", "<5", "<6", "<7", "7+"])
    table("BY SIDE", rows, lambda r: r["side"], order=["home", "away"])
    table("BY DAY/NIGHT", rows, lambda r: r["day_night"])
    table("BY LEASH OFFSET", rows,
          lambda r: ("none" if not sim.leash(r["name"])
                     else _bucket(sim.leash(r["name"]),
                                  [-0.5, -0.15, 0.15, 0.5])),
          order=["none", "<-0.5", "<-0.15", "<0.15", "<0.5", "0.5+"])
    # TWO-WAY, and it is the one that decides between two readings of the
    # tables above. Inning and pitch count are collinear, so "under-pulls
    # in the sixth" and "under-pulls at 85 pitches" are the SAME rows seen
    # twice unless the residual is read inside a pitch band.
    for lo, hi in ((60, 80), (80, 95)):
        band = [r for r in rows if lo <= r["pitches"] < hi]
        table(f"INNING, HOLDING PITCHES {lo}-{hi}", band,
              lambda r: min(r["inning"], 8), order=list(range(3, 9)),
              min_n=150)
    # Same question for the blowout rows: is 'trailing by five' a margin
    # effect or is it just 'he has allowed six', which has its own term?
    shelled = [r for r in rows if r["runs"] >= 5]
    table("MARGIN, HOLDING RUNS ALLOWED >= 5", shelled, margin_cell,
          order=MARGIN_ORDER, min_n=150)
    clean = [r for r in rows if r["runs"] <= 2]
    table("MARGIN, HOLDING RUNS ALLOWED <= 2", clean, margin_cell,
          order=MARGIN_ORDER, min_n=150)
    if kind == "mid":
        table("BY OUTS IN THE INNING", rows, lambda r: r["outs_before"],
              order=[0, 1, 2])
        table("BY RUNNERS ON", rows, lambda r: min(r["onbase"], 3),
              order=[0, 1, 2, 3])
        table("BY RUNS IN THIS INNING", rows, lambda r: min(r["inn_runs"], 4),
              order=[0, 1, 2, 3, 4])


# ── does the miss REPEAT? ──────────────────────────────────────────────

def repeats(rows: list[dict], keyfn, label: str, min_units: int = 25,
            min_n: int = 60) -> None:
    """Split-half reliability of the residual within a unit.

    THE POINT OF THE WHOLE SCREEN. A slice being off says the aggregate is
    wrong THERE; a residual that repeats within a pitcher or a club says the
    aggregate is the wrong OBJECT, and that a per-unit term is available.
    Halves are odd/even GAMES so a single night cannot land in both.
    """
    halves: dict = defaultdict(lambda: [[], []])
    for r in rows:
        u = keyfn(r)
        if u is None or u == "":
            continue
        # A STABLE split, not `hash()` — Python randomises string hashing
        # per process, so the halves would differ between two runs of the
        # same screen and the reliability would not reproduce.
        h = int(r["game_id"].split("-")[-1]) % 2
        halves[u][h].append(r["e"])
    pairs = [(st.fmean(a), st.fmean(b), len(a) + len(b))
             for a, b in halves.values()
             if len(a) >= min_n and len(b) >= min_n]
    if len(pairs) < min_units:
        print(f"\n  {label}: only {len(pairs)} units clear the floor "
              f"— NOT POWERED, no number reported")
        return
    xa = [p[0] for p in pairs]
    xb = [p[1] for p in pairs]
    r = _corr(xa, xb)
    # Spearman-Brown, to the full sample the offsets would be built on.
    sb = 2 * r / (1 + r) if r > -1 else float("nan")
    se = 1.0 / math.sqrt(len(pairs) - 3)
    print(f"\n  {label}: {len(pairs)} units   split-half r {r:+.3f} "
          f"(se ~{se:.3f})   full-sample {sb:+.3f}")
    print(f"    spread of the half-means: sd {st.pstdev(xa + xb):.4f}")


def year_over_year(rows: list[dict], min_n: int = 120) -> None:
    """IS THE PER-ARM RESIDUAL PROJECTABLE, OR IS IT ERA DRIFT WEARING A
    PITCHER'S NAME? (TODO 32, and the number the item rests on.)

    `repeats` splits odd/even GAMES, which POOLS SEASONS — so an arm whose
    career sits mostly in one season looks stable for a reason that has
    nothing to do with him, because the table is era-stale (TODO 33) and
    every row from that season carries the same sign. The honest number is
    year-over-year: estimate on season N, score on N+1, which is also the
    only form a live hook could ever use.

    Reported twice so the confound is visible rather than argued: RAW, and
    with each SEASON'S OWN MEAN removed first, which is what a per-arm term
    has to beat.
    """
    for label, want in (("BOUNDARY", True), ("MID", False)):
        cells: dict = defaultdict(list)
        for r in rows:
            if r["ends_inning"] is want and r["name"]:
                cells[(r["name"], r["date"][:4])].append(r["e"])
        per_season: dict = defaultdict(list)
        for (_, s), v in cells.items():
            per_season[s].extend(v)
        sm = {s: st.fmean(v) for s, v in per_season.items()}
        big = {k: v for k, v in cells.items() if len(v) >= min_n}
        print(f"\n  {label} year-over-year, {len(big)} arm-seasons with "
              f">= {min_n} decisions")
        for name, tbl in (("RAW", {k: st.fmean(v) for k, v in big.items()}),
                          ("DE-ERA'D", {k: st.fmean(v) - sm[k[1]]
                                        for k, v in big.items()})):
            pairs = [(tbl[(nm, s)], tbl[(nm, str(int(s) + 1))])
                     for (nm, s) in tbl if (nm, str(int(s) + 1)) in tbl]
            if len(pairs) < 25:
                print(f"    {name:<10} only {len(pairs)} arm-pairs "
                      f"— NOT POWERED, no number reported")
                continue
            r = _corr([p[0] for p in pairs], [p[1] for p in pairs])
            sd = st.pstdev([p[0] for p in pairs])
            print(f"    {name:<10} {len(pairs):>4} arm-pairs   r {r:+.3f} "
                  f"(se ~{1/math.sqrt(len(pairs)-3):.3f})   spread sd "
                  f"{sd:.4f}   projectable sd "
                  f"{sd * math.sqrt(r) if r > 0 else 0.0:.4f}")


def deep(rows: list[dict]) -> None:
    """THE FOUR FOLLOW-UPS THAT DECIDE WHAT THE TABLES ABOVE MEAN.

    Kept in this module rather than four scratchpads, which is the failure
    CLAUDE.md's battery rule records: the fourth-inning defect and the
    60-85 pitch defect were one defect seen through two instruments.
    """
    for kind, want in (("BOUNDARY", True), ("MID", False)):
        rs = [r for r in rows if r["ends_inning"] is want]
        print(f"\n{'=' * 72}\n  {kind}: residual by INNING x SEASON")
        print("  IS THE LATE GAP STRUCTURAL, OR HAS THE LEAGUE MOVED UNDER"
              " A POOLED TABLE?")
        print(f"    {'inning':<9}" + "".join(f"{s:>18}" for s in SEASONS))
        for i in range(3, 9):
            line = f"    {i:<9}"
            for s in SEASONS:
                v = [r for r in rs
                     if r["inning"] == i and r["date"][:4] == s]
                if len(v) < 150:
                    line += f"{'-':>18}"
                    continue
                c = cell(v)
                line += f"{c['diff']:>+11.4f} z{c['z']:>+5.1f}"
            print(line)

        # INNING or TIMES-THROUGH? They are collinear and only one of them
        # is a missing term.
        band = [r for r in rs if 75 <= r["pitches"] < 95 and r["tto"] == 3]
        table("inning, holding pitches 75-95 AND tto==3", band,
              lambda r: min(r["inning"], 8), order=list(range(4, 9)),
              min_n=150)
        for i in (5, 6):
            b2 = [r for r in rs if 75 <= r["pitches"] < 95
                  and r["inning"] == i]
            table(f"tto, holding pitches 75-95 AND inning=={i}", b2,
                  lambda r: r["tto"], order=[2, 3], min_n=150)

        # Is DAY/NIGHT a real pattern or is it calendar composition?
        print("\n  day/night, HOLDING MONTH")
        for m in ("04", "05", "06", "07", "08", "09"):
            line = f"    {m}  "
            for dn in ("day", "night"):
                v = [r for r in rs if r["date"][5:7] == m
                     and r["day_night"] == dn]
                if len(v) < 200:
                    continue
                c = cell(v)
                line += (f"{dn:>7} n{c['n']:>6,} diff{c['diff']:+.4f}"
                         f" z{c['z']:+5.1f}   ")
            print(line)

    year_over_year(rows)

    # Does the per-pitcher residual just re-state the shipped leash?
    bnd = [r for r in rows if r["ends_inning"]]
    g = defaultdict(list)
    for r in bnd:
        if r["name"]:
            g[r["name"]].append(r)
    pairs = [(sim.leash(k), st.fmean(x["e"] for x in v))
             for k, v in g.items() if len(v) >= 250]
    print(f"\n  corr(shipped leash offset, boundary residual) over "
          f"{len(pairs)} arms: "
          f"{_corr([p[0] for p in pairs], [p[1] for p in pairs]):+.3f}")
    print("    0 would mean the residual is entirely NEW information; "
          "negative means the offsets OVERSHOOT.")


def _corr(a, b):
    ma, mb = st.fmean(a), st.fmean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    dbv = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * dbv) if da and dbv else 0.0


# ── driver ─────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", type=float, default=0.0,
                    help="log-odds injected into the control subgroup")
    ap.add_argument("--control-cell", default="lead 5+",
                    help="SCORE MARGIN cell to inject into")
    ap.add_argument("--holdout-only", action="store_true")
    ap.add_argument("--train-only", action="store_true")
    ap.add_argument("--deep", action="store_true",
                    help="the follow-ups that decide what the tables mean")
    a = ap.parse_args()

    rows = load_rows()
    attach_context(rows)
    predict(rows)

    if a.control:
        # POSITIVE CONTROL. Shifting the PREDICTION down by X is the same
        # screen as reality being X log-odds higher, and it needs no
        # resampling — the recovered diff must match `expect` below.
        hit = [r for r in rows if margin_cell(r) == a.control_cell]
        before = {k: [st.fmean(r["p"] for r in v), cell(v)["diff"]]
                  for k, v in _by(hit, lambda r: r["ends_inning"]).items()}
        for r in hit:
            lo = math.log(r["p"] / (1 - r["p"])) if 0 < r["p"] < 1 else None
            if lo is None:
                continue
            r["p"] = 1 / (1 + math.exp(-(lo - a.control)))
            r["e"] = (1.0 if r["removed"] else 0.0) - r["p"]
        print(f"\n  POSITIVE CONTROL: {a.control:+.2f} log-odds injected "
              f"into '{a.control_cell}' ({len(hit):,} rows)")
        for k, v in _by(hit, lambda r: r["ends_inning"]).items():
            p0, d0 = before[k]
            p1 = st.fmean(r["p"] for r in v)
            print(f"    {'boundary' if k else 'mid':<10}"
                  f"expect that cell's diff to move "
                  f"{d0:+.4f} -> {d0 + (p0 - p1):+.4f}")

    if a.holdout_only:
        rows = [r for r in rows if r["date"] >= HOLDOUT]
    if a.train_only:
        rows = [r for r in rows if r["date"] < HOLDOUT]

    bnd = [r for r in rows if r["ends_inning"]]
    mid = [r for r in rows if not r["ends_inning"]]

    for kind, rs in (("boundary", bnd), ("mid", mid)):
        print("\n" + "=" * 72)
        c = cell(rs)
        print(f"  {kind.upper()}   {c['n']:,} decisions   "
              f"real {c['obs']:.4f}   model {c['pred']:.4f}   "
              f"diff {c['diff']:+.4f}   se {c['se_cl']:.4f} "
              f"(binomial {c['se_bin']:.4f}, clustering inflates it "
              f"{c['se_cl']/c['se_bin']:.1f}x)")
        print("=" * 72)
        slices(rs, kind)
        repeats(rs, lambda r: r["name"], "REPEATS WITHIN A PITCHER")
        repeats(rs, lambda r: r["team"], "REPEATS WITHIN A CLUB",
                min_units=20, min_n=300)

    if a.deep:
        deep(rows)


if __name__ == "__main__":
    main()
