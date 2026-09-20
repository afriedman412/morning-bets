"""HOME RUNS OFF CONTACT TYPE — the counting stage.

    venv/bin/python -m scratchpad.hr_traj --build      # count mlb_traj
    venv/bin/python -m scratchpad.hr_traj --agree      # gb/bip vs mlb_batted
    venv/bin/python -m scratchpad.hr_traj --stabilise  # split-half r, k
    venv/bin/python -m scratchpad.hr_traj --predict    # out-of-sample test

WHY. `battedball.py`'s own note says contact TYPE is a stable per-player
trait in a way contact OUTCOME is not — pitcher GB% shrinks with k = 77
against BABIP's 3,068 — and that is the whole reason the DP and hit-mix
tables read it. The home run is the largest contact OUTCOME the engine
still reads only as an outcome: `hr_pct` is a per-PA rate shrunk with
k = 350 and nothing about the fly ball it has to leave on reaches the
channel.

WHAT ONE ROW IS. (game_id, date, name, role, gb, fb, ld, pu, hr, bip):
one player's batted balls in one game from one side of the ball, split by
`hitData.trajectory` — the same scan, the same coverage rule and the same
`role` convention as `mlb_batted`, so `--agree` can check gb and bip
row-for-row against it. `hr` counts home runs among those balls; probed at
100% trajectory coverage (`hr_traj_probe`, 2026-09-10), 91.3% fly_ball and
8.7% line_drive, none on the ground.
"""
from __future__ import annotations

import math
import multiprocessing as mp
import statistics as st
import sys
from collections import defaultdict

from src.context import sim, store
from src.context.holdout import HOLDOUT
from src.context.sources import pbp
from src.context.sources.battedball import BIP_EV

#: trajectory -> column. Bunts travel with the shape they are, not with a
#: category of their own: `battedball` already folds bunt_grounder into
#: ground balls and the same rule keeps the two tables comparable.
#: `bunt_line_drive` is 75 balls in four seasons and was the entire
#: disagreement against `mlb_batted` on the first build — a trajectory
#: this map did not carry is dropped from `bip` here and counted there.
TRAJ = {"ground_ball": "gb", "bunt_grounder": "gb", "fly_ball": "fb",
        "line_drive": "ld", "bunt_line_drive": "ld",
        "popup": "pu", "bunt_popup": "pu"}

_SCHEMA = """
create table if not exists mlb_traj (
    game_id text, date text, name text, role text,
    gb integer, fb integer, ld integer, pu integer, hr integer,
    bip integer,
    primary key (game_id, name, role)
)
"""
_COLS = ("gb", "fb", "ld", "pu", "hr", "bip")


def game_rows(game_id: str, data: dict | None = None) -> dict:
    """{(name, role): {col: n}} for one game."""
    out: dict = defaultdict(lambda: dict.fromkeys(_COLS, 0))
    for play, *_ in pbp.plays(game_id, data):
        ev = ((play.get("result") or {}).get("eventType") or "")
        if ev not in BIP_EV:
            continue
        hd = None
        for e in (play.get("playEvents") or []):
            if e.get("hitData"):
                hd = e["hitData"]
        traj = (hd or {}).get("trajectory")
        col = TRAJ.get(traj)
        if not col:
            continue                      # coverage miss, not a fly ball
        mu = play.get("matchup") or {}
        for who, role in (((mu.get("batter") or {}).get("fullName"), "bat"),
                          ((mu.get("pitcher") or {}).get("fullName"), "pit")):
            if not who:
                continue
            r = out[(who, role)]
            r[col] += 1
            r["bip"] += 1
            r["hr"] += ev == "home_run"
    return out


def _one(args):
    gid, date = args
    try:
        return gid, date, {f"{n}|{r}": v
                           for (n, r), v in game_rows(gid).items()}
    except Exception:
        return None


_PAIR_SCHEMA = """
create table if not exists mlb_hr_pairs (
    game_id text, date text, batter text, pitcher text,
    bip integer, air integer, hr integer,
    primary key (game_id, batter, pitcher)
)
"""


def pair_rows(game_id: str, data: dict | None = None) -> dict:
    """{(batter, pitcher): [bip, air, hr]} for one game.

    THE UNIT THE TABLE HAS TO BE COUNTED ON. A home run needs both sides'
    rates and the league's on the same population (the log5 rule the
    `resolve` docstring states), so an observed-over-expected count cannot
    be run at pitcher-game level against a club aggregate — the batters a
    starter actually faced are not the nine in the other dugout once a
    lineup turns over and a pinch hitter arrives.
    """
    out: dict = defaultdict(lambda: [0, 0, 0])
    for play, *_ in pbp.plays(game_id, data):
        ev = ((play.get("result") or {}).get("eventType") or "")
        if ev not in BIP_EV:
            continue
        hd = None
        for e in (play.get("playEvents") or []):
            if e.get("hitData"):
                hd = e["hitData"]
        col = TRAJ.get((hd or {}).get("trajectory"))
        if not col:
            continue
        mu = play.get("matchup") or {}
        b = (mu.get("batter") or {}).get("fullName")
        p = (mu.get("pitcher") or {}).get("fullName")
        if not (b and p):
            continue
        r = out[(b, p)]
        r[0] += 1
        r[1] += col in ("fb", "ld")
        r[2] += ev == "home_run"
    return out


def _one_pair(args):
    gid, date = args
    try:
        return gid, date, {f"{b}|{p}": v
                           for (b, p), v in pair_rows(gid).items()}
    except Exception:
        return None


def build_pairs(verbose: bool = True) -> int:
    store.init()
    with store.connect() as c:
        c.execute(_PAIR_SCHEMA)
        dates = {r["game_id"]: r["date"] for r in c.execute(
            f"select game_id, date from {store.BETS}.games "
            "where sport = 'mlb'")}
        have = {r[0] for r in c.execute(
            "select distinct game_id from mlb_hr_pairs")}
    todo = [(g, dates[g]) for g in
            (f"mlb-{f.name.split('.')[0]}" for f in pbp.CACHE.glob(
                "*.json.gz"))
            if g not in have and g in dates]
    if verbose:
        print(f"  {len(todo):,} games to scan", flush=True)
    with mp.get_context("fork").Pool(8) as p:
        got = [g for g in p.map(_one_pair, todo, chunksize=16) if g]
    n = 0
    with store.connect(attach=False) as c:
        c.execute(_PAIR_SCHEMA)
        for gid, date, rows in got:
            for key, v in rows.items():
                b, pit = key.rsplit("|", 1)
                c.execute("insert or replace into mlb_hr_pairs values "
                          "(?,?,?,?,?,?,?)", (gid, date, b, pit, *v))
                n += 1
    if verbose:
        print(f"  wrote {n:,} pair-game rows from {len(got):,} games")
    return n


def build(verbose: bool = True) -> int:
    """Fill the table from every cached game it does not yet cover."""
    store.init()
    with store.connect() as c:
        c.execute(_SCHEMA)
        dates = {r["game_id"]: r["date"] for r in c.execute(
            f"select game_id, date from {store.BETS}.games "
            "where sport = 'mlb'")}
        have = {r[0] for r in c.execute(
            "select distinct game_id from mlb_traj")}
    todo = [(g, dates[g]) for g in
            (f"mlb-{f.name.split('.')[0]}" for f in pbp.CACHE.glob(
                "*.json.gz"))
            if g not in have and g in dates]
    if verbose:
        print(f"  {len(todo):,} games to scan", flush=True)
    with mp.get_context("fork").Pool(8) as p:
        got = [g for g in p.map(_one, todo, chunksize=16) if g]
    n = 0
    with store.connect(attach=False) as c:
        c.execute(_SCHEMA)
        for gid, date, rows in got:
            for key, v in rows.items():
                nm, role = key.rsplit("|", 1)
                c.execute(
                    "insert or replace into mlb_traj values (?,?,?,?," +
                    ",".join("?" * len(_COLS)) + ")",
                    (gid, date, nm, role, *(v[k] for k in _COLS)))
                n += 1
    if verbose:
        print(f"  wrote {n:,} player-game rows from {len(got):,} games")
    return n


def agree() -> None:
    """gb and bip must match `mlb_batted` row-for-row.

    Two scans of the same cache written by two functions is the one free
    correctness check available here: the columns this table adds are
    unverifiable against anything, but the two it shares are not.
    """
    with store.connect(attach=False) as c:
        rows = list(c.execute(
            "select t.game_id, t.name, t.role, t.gb tg, t.bip tn, "
            "b.gb bg, b.bip bn from mlb_traj t join mlb_batted b "
            "using (game_id, name, role)"))
    bad = [r for r in rows if r["tg"] != r["bg"] or r["tn"] != r["bn"]]
    print(f"  {len(rows):,} rows joined, {len(bad):,} disagree")
    for r in bad[:5]:
        print(f"    {r['game_id']} {r['name']} {r['role']}: "
              f"gb {r['tg']} vs {r['bg']}, bip {r['tn']} vs {r['bn']}")


def counts(role: str, before=None, parity=None) -> dict:
    """{name: {col: n}} under the usual date scoping.

    `parity` selects odd or even GAMES for the split-half — by the game's
    rank within that player's own season, which is `stabilise.py`'s
    convention and not a date filter.
    """
    where = f" and date < '{before}'" if before else ""
    out: dict = defaultdict(lambda: dict.fromkeys(_COLS, 0))
    with store.connect(attach=False) as c:
        c.execute(_SCHEMA)
        seen: dict = defaultdict(int)
        for r in c.execute(
                "select name, date, " + ",".join(_COLS) +
                f" from mlb_traj where role = ? {where} "
                "order by name, date", (role,)):
            i = seen[r["name"]]
            seen[r["name"]] += 1
            if parity is not None and i % 2 != parity:
                continue
            for k in _COLS:
                out[r["name"]][k] += r[k] or 0
    return out


#: The three quantities in the decomposition. HR/PA is what the engine
#: carries today; the other two are what it is made of. `air` is fly balls
#: plus line drives — the two trajectories home runs actually leave on,
#: 91.3% and 8.7% of them, against 0.0% on the ground.
def _air(v):
    return v["fb"] + v["ld"]


RATES = {
    "hr_per_bip": (lambda v: v["hr"], lambda v: v["bip"]),
    "air_share": (_air, lambda v: v["bip"]),
    "hr_per_air": (lambda v: v["hr"], _air),
    "fb_share": (lambda v: v["fb"], lambda v: v["bip"]),
    "hr_per_fb": (lambda v: v["hr"], lambda v: v["fb"]),
}


def stabilise(min_bip: int = 100) -> None:
    """Split-half reliability of each rate, `stabilise.py`'s method.

    Odd/even games, Pearson r on the two halves, Spearman-Brown up to the
    full sample, k = n(1 - r) / r on the mean half denominator. The
    comparison that matters is `hr_per_bip` against the product of
    `air_share` and `hr_per_air`: a rate the engine can hold more firmly
    than the one it holds now is the whole claim.
    """
    print(f"\n  SPLIT-HALF RELIABILITY  (players with >= {min_bip} bip "
          "in each half)\n")
    print(f"    {'role':<5}{'rate':<14}{'n':>6}{'r_half':>9}{'r_full':>9}"
          f"{'k (den)':>10}{'mean den':>10}")
    for role in ("bat", "pit"):
        odd, even = counts(role, parity=1), counts(role, parity=0)
        for name, (num, den) in RATES.items():
            xs, ys, dens = [], [], []
            for nm in odd.keys() & even.keys():
                a, b = odd[nm], even[nm]
                if min(a["bip"], b["bip"]) < min_bip:
                    continue
                da, db = den(a), den(b)
                if da < 10 or db < 10:
                    continue
                xs.append(num(a) / da)
                ys.append(num(b) / db)
                dens.append((da + db) / 2)
            if len(xs) < 30:
                continue
            r = st.correlation(xs, ys)
            rf = 2 * r / (1 + r) if r > -1 else 0.0
            d = st.mean(dens)
            k = d * (1 - r) / r if r > 0 else float("inf")
            print(f"    {role:<5}{name:<14}{len(xs):>6,}{r:>9.3f}"
                  f"{rf:>9.3f}{k:>10.1f}{d:>10.1f}")


def _shrunk(c: dict, num, den, k: float, lg: float) -> dict:
    return {nm: (num(v) + k * lg) / (den(v) + k)
            for nm, v in c.items() if den(v) > 0}


def _league(c: dict, num, den) -> float:
    n = sum(den(v) for v in c.values())
    return sum(num(v) for v in c.values()) / n if n else 0.0


#: Shrinkage constants MEASURED by `--stabilise` above, in balls-in-play
#: (or air-ball) units — k = n(1 - r) / r on the mean half denominator:
#:
#:     bat  hr_per_bip 140.7   air_share 179.0   hr_per_air  88.1
#:     pit  hr_per_bip 943.7   air_share 175.7   hr_per_air 973.1
#:
#: THE WHOLE FINDING IS IN THE PITCHER ROW. His home run OUTCOME barely
#: repeats (r_full 0.416, and 0.257 once the fly ball is granted) while
#: his contact TYPE does (0.793) — the same split `battedball.py` found
#: for ground balls, on the channel it matters most for. The batter is
#: the opposite: HR/BIP is his most reliable rate of the five.
K = {"bat_hr": 140.7, "bat_air": 179.0, "bat_hpa": 88.1,
     "pit_hr": 943.7, "pit_air": 175.7, "pit_hpa": 973.1}


def predict(min_bip: int = 50, ks: dict | None = None) -> None:
    """Out of sample: does the decomposition beat the direct rate?

    Everything before HOLDOUT estimates; everything on or after it scores.
    Each player-side of each held-out game is one row, the target is his
    home runs on the balls he put in play there, and the two candidate
    predictions are (a) his shrunk HR/BIP and (b) his shrunk air share
    times his shrunk HR per air ball. Scored as Brier and log loss per
    ball in play, plus the correlation against the held-out rate.

    THE POWER: stated by the row count printed below, and the paired
    difference carries its own standard error — the two predictions share
    the same games, so the comparison is paired and does not have to clear
    the between-player spread.
    """
    ks = {**K, **(ks or {})}
    print(f"\n  OUT OF SAMPLE, from {HOLDOUT}  (estimated on games "
          f"before it, >= {min_bip} bip)\n")
    for role in ("bat", "pit"):
        tr = counts(role, before=HOLDOUT)
        with store.connect(attach=False) as c:
            rows = [dict(r) for r in c.execute(
                "select name, " + ",".join(_COLS) + " from mlb_traj "
                "where role = ? and date >= ? order by date",
                (role, HOLDOUT))]
        lg_hr = _league(tr, RATES["hr_per_bip"][0], RATES["hr_per_bip"][1])
        lg_air = _league(tr, _air, lambda v: v["bip"])
        lg_hpa = _league(tr, lambda v: v["hr"], _air)
        direct = _shrunk(tr, lambda v: v["hr"], lambda v: v["bip"],
                         ks[f"{role}_hr"], lg_hr)
        air = _shrunk(tr, _air, lambda v: v["bip"], ks[f"{role}_air"],
                      lg_air)
        hpa = _shrunk(tr, lambda v: v["hr"], _air, ks[f"{role}_hpa"],
                      lg_hpa)
        pa, pb, pc, ys, ns = [], [], [], [], []
        for r in rows:
            nm = r["name"]
            if nm not in direct or tr[nm]["bip"] < min_bip or not r["bip"]:
                continue
            pa.append(direct[nm])
            pb.append(air[nm] * hpa[nm])
            # CONTACT TYPE ONLY — his air-ball share against the LEAGUE's
            # home run rate per air ball, granting him no personal skill
            # at keeping a fly ball in the yard. The strong form of the
            # pitcher finding, and the row that says whether `hr_per_air`
            # is worth carrying at all.
            pc.append(air[nm] * lg_hpa)
            ys.append(r["hr"])
            ns.append(r["bip"])
        n = sum(ns)
        if not n:
            continue
        print(f"    {role}: {len(ys):,} player-games, {n:,} balls in "
              f"play, {sum(ys):,} home runs")
        print(f"      {'model':<14}{'brier x1e3':>12}{'logloss':>10}"
              f"{'mean p':>9}{'actual':>9}")
        for lab, ps in (("direct", pa), ("decomposed", pb),
                        ("contact-only", pc),
                        ("half-half", [(x + y) / 2
                                       for x, y in zip(pa, pb)])):
            br = sum(nn * (p - y / nn) ** 2 for p, y, nn in zip(ps, ys, ns))
            ll = -sum(y * math.log(max(p, 1e-9)) +
                      (nn - y) * math.log(max(1 - p, 1e-9))
                      for p, y, nn in zip(ps, ys, ns))
            print(f"      {lab:<14}{1e3 * br / n:>12.4f}{ll / n:>10.5f}"
                  f"{sum(p * nn for p, nn in zip(ps, ns)) / n:>9.4f}"
                  f"{sum(ys) / n:>9.4f}")
        # PAIRED, and that is what makes this readable at all: the two
        # predictions score the same player-games, so the difference does
        # not have to clear the between-player spread the levels sit in.
        for lab, alt in (("decomposed", pb), ("contact-only", pc)):
            d = [nn * ((a - y / nn) ** 2 - (b - y / nn) ** 2)
                 for a, b, y, nn in zip(pa, alt, ys, ns)]
            se = st.pstdev(d) / len(d) ** 0.5
            print(f"      paired brier, direct - {lab:<13}"
                  f"{1e3 * sum(d) / n:>+9.4f} x1e-3   se "
                  f"{1e3 * se * len(d) / n:.4f}")


#: Fitting rows are PRE-JULY of every season, not just pre-2026-07-01:
#: July-onward of all four seasons is battery scoring territory, which is
#: the convention `DP_GB_*` and `TEMP_HR_*` were counted under.
FIT_MONTHS = ("03", "04", "05", "06")


def _maps_before(cut: str) -> dict:
    """The four shrunk player maps as of `cut`, all strictly prior to it.

    THE LEAKAGE CLASS THAT COST `DP_GB_*` AND `XBH_GB_*` A RE-COUNT: a
    covariate window that CONTAINS the row it bins is self-correlated —
    every home run is a fly ball, so a counted HR raises its own
    pitcher's air share and the slope comes back inflated. Rows in month
    m are binned by the map frozen before month m, and the expected value
    they are scored against is frozen there too.
    """
    out = {}
    for role in ("bat", "pit"):
        c = counts(role, before=cut)
        lg_hr = _league(c, lambda v: v["hr"], lambda v: v["bip"])
        lg_air = _league(c, _air, lambda v: v["bip"])
        out[f"{role}_hr"] = _shrunk(c, lambda v: v["hr"],
                                    lambda v: v["bip"],
                                    K[f"{role}_hr"], lg_hr)
        out[f"{role}_air"] = _shrunk(c, _air, lambda v: v["bip"],
                                     K[f"{role}_air"], lg_air)
        out[f"{role}_lg_hr"] = lg_hr
        out[f"{role}_lg_air"] = lg_air
    return out


def _fit_rows():
    """Every pre-July ball-in-play pair row, carrying its own prior maps.

    Yields (bip, hr, p_air, b_air, expected_rate, season, venue) — the
    covariate for each side and the log5 expectation, both built from the
    cut before the row's month.
    """
    with store.connect() as c:
        c.execute(_PAIR_SCHEMA)
        rows = [dict(r) for r in c.execute(
            "select p.date, p.batter, p.pitcher, p.bip, p.air, p.hr, "
            f"g.venue_id from mlb_hr_pairs p join {store.BETS}.games g "
            "using (game_id) "
            "where substr(p.date, 6, 2) in ('03','04','05','06') "
            "order by p.date")]
    cur, mp_ = None, None
    for r in rows:
        cut = r["date"][:7] + "-01"
        if cut != cur:
            cur, mp_ = cut, _maps_before(cut)
        b_hr = mp_["bat_hr"].get(r["batter"])
        p_hr = mp_["pit_hr"].get(r["pitcher"])
        b_air = mp_["bat_air"].get(r["batter"])
        p_air = mp_["pit_air"].get(r["pitcher"])
        if None in (b_hr, p_hr, b_air, p_air):
            continue
        # THE LEAGUE TERM ON THE SAME POPULATION as the two player terms —
        # the batter map's league rate and the pitcher map's are the same
        # balls in play counted from the two sides, so either serves and
        # they agree to floating point.
        yield (r["bip"], r["hr"], p_air, b_air,
               sim.log5(b_hr, p_hr, mp_["bat_lg_hr"]),
               r["date"][:4], r["venue_id"])


def _odds(p: float) -> float:
    return p / (1 - p) if 0 < p < 1 else 0.0


def airtable(nq: int = 5) -> None:
    """HR observed over expected, by each side's shrunk air-ball share.

    THE CLAIM BEING TESTED, and it is not the one `DP_GB_*` tested. The
    double-play and hit-mix tables read contact type because the engine
    had NO per-player rate on those channels at all. Home runs it does
    have — so the only thing worth counting here is what air share adds
    ON TOP of the log5 the engine already computes, which is why every
    cell below is observed over EXPECTED and never observed over league.

    WHY THERE SHOULD BE ANYTHING LEFT. The pitcher's home run outcome
    shrinks with k = 944 balls in play (`--stabilise`), so a starter's
    season is pulled most of the way to the league and nearly all of his
    personal home run signal is discarded — correctly, because it is
    mostly noise. His air-ball share shrinks with k = 176 and survives.
    The part of his home run rate that contact type explains is therefore
    real, reliable, and currently unreachable by the channel.
    """
    rows = list(_fit_rows())
    n_bip = sum(r[0] for r in rows)
    n_hr = sum(r[1] for r in rows)
    print(f"\n  {len(rows):,} pair-game rows, {n_bip:,} balls in play, "
          f"{n_hr:,} home runs  (pre-July, four seasons)")
    out = {}
    for who, idx in (("pitcher", 2), ("batter", 3)):
        edges = _quintiles(rows, idx, nq)
        mults, cells = _table(rows, idx, edges, nq)
        print(f"\n  BY {who.upper()} AIR SHARE   edges "
              f"{', '.join(f'{e:.4f}' for e in edges)}")
        print(f"    {'q':<3}{'bip':>10}{'obs':>10}{'exp':>10}"
              f"{'obs/exp':>10}{'odds mult':>11}{'se':>8}")
        for q, ((o, e, n), m) in enumerate(zip(cells, mults), 1):
            print(f"    {q:<3}{n:>10,}{o:>10,.0f}{e:>10,.1f}"
                  f"{o / e:>10.4f}{m:>11.4f}{o ** 0.5 / e:>8.4f}")
        ctr = _centre(mults, cells)
        print(f"    centre {ctr:.4f}  ->  "
              f"({', '.join(f'{m / ctr:.4f}' for m in mults)})")
        out[who] = (edges, [m / ctr for m in mults])
        # WITHIN VENUE, which is the correction item 5 had to be given
        # after its first battery run: a fly-ball staff that happens to
        # pitch half its games in a home run park would put the park's
        # index into this table, and the engine applies park SEPARATELY.
        # Identified off the same pitcher in different buildings.
        vm, vc = _table(rows, idx, edges, nq, within_venue=True)
        vctr = _centre(vm, vc)
        print(f"    within venue          "
              f"({', '.join(f'{m / vctr:.4f}' for m in vm)})")
    return out


def _quintiles(rows, idx, nq):
    vals = sorted(r[idx] for r in rows for _ in range(r[0]))
    return [vals[int(len(vals) * q / nq)] for q in range(1, nq)]


def _table(rows, idx, edges, nq, within_venue=False, season=None):
    """(odds multipliers, cells) for one covariate.

    `within_venue` renormalises each venue's expected total to its own
    observed total before the quintiles are cut, so a park's own index
    cannot travel into the table — it is the same observed-over-venue-
    expected identification `TEMP_HR_MULT` carries.
    """
    use = [r for r in rows if season is None or r[5] == season]
    scale: dict = {}
    if within_venue:
        agg: dict = defaultdict(lambda: [0.0, 0.0])
        for bip, hr, _p, _b, exp, _s, ven in use:
            agg[ven][0] += hr
            agg[ven][1] += exp * bip
        scale = {v: (o / e if e else 1.0) for v, (o, e) in agg.items()}
    acc = [[0.0, 0.0, 0] for _ in range(nq)]
    for bip, hr, p_air, b_air, exp, _s, ven in use:
        q = sum((p_air if idx == 2 else b_air) >= e for e in edges)
        acc[q][0] += hr
        acc[q][1] += exp * bip * scale.get(ven, 1.0)
        acc[q][2] += bip
    mults = [_odds(o / n) / _odds(e / n) if e and n else 0.0
             for o, e, n in acc]
    return mults, acc


def _centre(mults, cells):
    """CENTRED over real ball-in-play weights, the same rule TTO_MULT,
    STATE_MULT and both GB tables follow: the table carries SHAPE, and the
    LEVEL stays with the rates it multiplies."""
    tot = sum(n for _, _, n in cells)
    return sum(m * n for m, (_, _, n) in zip(mults, cells)) / tot if tot \
        else 1.0


def gate(nq: int = 5) -> None:
    """THE ERA GATE: does the shape repeat season to season?

    `DP_GB_*` and `XBH_GB_*` both ship with a between-season correlation
    of their odds ratios and a note on what per-cell noise caps that
    correlation at. Same test here, plus per-season ordering — the check
    that killed the five-bin wind table.
    """
    rows = list(_fit_rows())
    seasons = sorted({r[5] for r in rows})
    for who, idx in (("pitcher", 2), ("batter", 3)):
        edges = _quintiles(rows, idx, nq)
        print(f"\n  {who.upper()} AIR SHARE, BY SEASON  "
              f"(pooled edges, each season centred on itself)")
        per = {}
        for s in seasons:
            m, c = _table(rows, idx, edges, nq, season=s)
            ctr = _centre(m, c)
            per[s] = [v / ctr for v in m]
            mono = all(x < y for x, y in zip(per[s], per[s][1:]))
            print(f"    {s}  {'  '.join(f'{v:.4f}' for v in per[s])}"
                  f"   n {sum(x[2] for x in c):>7,}"
                  f"   {'ordered' if mono else ''}")
        pairs = [(a, b) for i, a in enumerate(seasons) for b in seasons[i+1:]]
        rs = [st.correlation(per[a], per[b]) for a, b in pairs]
        print(f"    between-season correlation of the odds ratios: "
              f"mean {st.mean(rs):+.3f} over {len(pairs)} pairs "
              f"({', '.join(f'{r:+.2f}' for r in rs)})")


def main(argv):
    if "--rebuild" in argv:
        with store.connect(attach=False) as c:
            c.execute("drop table if exists mlb_traj")
        print("  dropped mlb_traj")
    if "--build" in argv or "--rebuild" in argv:
        build()
    if "--pairs" in argv:
        build_pairs()
    if "--agree" in argv:
        agree()
    if "--stabilise" in argv:
        stabilise()
    if "--gate" in argv:
        gate()
    if "--airtable" in argv:
        airtable()
    if "--predict" in argv:
        predict()


if __name__ == "__main__":
    main(sys.argv[1:])
