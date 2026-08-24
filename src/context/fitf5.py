"""Fit the simulator to the quantity that settles: first-five runs.

WHY THIS REPLACES `calibrate.tune`. That objective targets the hazard curve,
the boundary share and the outs distribution — quantities chosen because
they were measurable, not because anyone bets them. It works: outs calibrate
to within 0.01 of a start. It also earns nothing, CLV z 1.3 against
strikeouts' 43.5, because outs ARE the hook and the hook is a manager
decision the model only reproduces in aggregate.

221 parameters were fitted to reach that — 11 hook, 30 club patience, 176
pitcher leash, 4 advancement — and 206 of them exist to make OUTS come out
right per pitcher and per club. They were accumulated across a long sequence
of fits, each conditioned on the last, and never validated jointly out of
sample.

WHAT THIS FITS INSTEAD. Runs allowed through five by ONE pitching side, which
is what a first-five market settles on. A parameter that does not move that
number does not need identifying — that is what "does not matter" means. So
the club and pitcher offsets are simply not applied here, and whether that
costs anything is measured rather than assumed (`--offsets`).

WHY SIDES AND NOT GAME TOTALS. `games` carries `away_score_f5` and
`home_score_f5` separately: 512 games but 909 side observations with a
modelled rotation starter. A side ties to ONE starter; a total confounds
two. That is double the sample against half the parameters — roughly 80
observations each at 11, against 2.3 before.

THE SCORING RULE IS RPS, not squared error on the mean. A simulator can land
the average and get every threshold wrong, which is the exact failure the
point-estimate estimator died of. Ranked probability score is the same
proper rule the market is graded by, summed over the lines a book offers, so
minimising it IS minimising Brier on the bet.

TOTAL RUNS, NOT EARNED. Everywhere else in this project the sim is scored
against EARNED runs, because it models no errors and charging it for defence
it never simulated read as a 12% deficit that was not there. That reasoning
is correct for a diagnostic and WRONG here: an F5 market settles on runs
that crossed the plate, unearned ones included. Fitting to earned runs would
build a model that is right about a number nobody pays out on. Expect the
fitted constants to sit a little hot against their published references —
that is the ~8% unearned share being absorbed, and it belongs in there.
"""
from __future__ import annotations

import random
import sys
import zlib
from collections import defaultdict

from src import db
from src.context import calibrate as cal
from src.context import f5, game, sim
from src.context.sources import rates as rate_src

#: Thresholds the side distribution is scored across. This is the FULL
#: SUPPORT of runs allowed through five, not a menu of book lines — a side
#: allows 2.38 on average and essentially never more than eight.
#:
#: The distinction is the point. Summed across the whole support, ranked
#: probability score IS the discrete CRPS: a measure of how far the
#: simulated DISTRIBUTION sits from what happened, which is the definition
#: of simulating the game correctly. Scored across a book's liquid lines
#: instead, the same arithmetic quietly becomes "how well do we hit props",
#: which would tune the model to the shape of somebody's board.
SIDE_LINES = tuple(x + 0.5 for x in range(9))
#: The same, for a full game's F5 total.
TOTAL_LINES = tuple(x + 0.5 for x in range(13))

#: Weight on the game-total term. Small on purpose: the total is the sum of
#: two sides already in the objective, so it adds little beyond them — what
#: it does add is the pairing, which is the only place the fit can see both
#: halves of one game at once.
W_TOTAL = 0.25

#: Hook fields a fit MAY move, and by default does not. Measured on the F5
#: objective, every one of these is flat inside its own error bar: across
#: its entire grid `intercept` moved the loss 0.0034 against a paired
#: standard error of 0.0017, `per_run` 0.0050 against 0.0036, `pitch_center`
#: 0.0059 against 0.0055. That is the expected result rather than a
#: disappointment — the starter is still in through the fifth about
#: three-quarters of the time, so the removal rule usually never fires
#: inside the window being scored.
#:
#: The hook is a manager decision this model only ever reproduced in
#: aggregate, and it is not what makes a simulated game right. Left where
#: the outs work put it. `--with-hook` puts them back in the search.
HOOK_KEYS = ("intercept", "per_inning", "per_run", "pitch_center",
             "mid_intercept", "mid_per_runner")

#: What the fit actually moves: the mechanisms that PRODUCE RUNS. Every one
#: is a rule about how a runner gets from where he is to home plate, which
#: is the part of the simulation that has to be right for the innings to
#: come out like real innings.
#:
#: INHERITED_SCORE_RATE IS GONE. It only ever existed because the f5.py stub
#: could not simulate the reliever finishing the inning, so a departing
#: starter's stranded runners were settled by a flat 0.33. `game.py` hands
#: over the base-out state and they score for real reasons. The fit drove it
#: to its grid ceiling on the stub and the holdout rejected the move at 2.6
#: sigma — a constant straining on a path the product does not use.
RULE_KEYS = ("WP_PB_RATE", "GIDP_RATE")

PARAMS = RULE_KEYS


def defaults() -> dict:
    """Current shipped values for everything the fit can move."""
    h = sim.Hook()
    out = {k: getattr(h, k) for k in HOOK_KEYS}
    out.update({k: getattr(sim, k) for k in RULE_KEYS})
    return out


def _dist(vals: list[int]) -> dict:
    """Mean, spread and the two tails of a run distribution.

    The headline check on whether a simulated inning behaves like a real
    one. A model can carry a good score while producing the right average
    out of the wrong shape — too few shutouts and too few crooked numbers —
    and only the tails show it.
    """
    n = len(vals) or 1
    m = sum(vals) / n
    return {
        "mean": m,
        "sd": (sum((v - m) ** 2 for v in vals) / n) ** 0.5,
        "p0": sum(1 for v in vals if v == 0) / n,
        "p5": sum(1 for v in vals if v >= 5) / n,
    }


_F5_Q = """
select game_id, date, home_team_abbr h, away_score_f5 af5,
       home_score_f5 hf5, venue_id
from games
where sport = 'mlb' and away_score_f5 is not null
  and home_score_f5 is not null
"""

_SIDES: dict[tuple, list] = {}


def side_cases(before=None, since=None, rates_before=None,
               offsets=False) -> list[dict]:
    """One row per pitching side of a settled game with a modelled starter.

    `runs` is what that side ACTUALLY allowed through five, which is the
    other team's F5 score — crossing those is the obvious way to build this
    exactly backwards, so it is read off the `is_home` flag rather than by
    matching abbreviations.

    `offsets=False` is the point of the rebuild: no club patience, no
    pitcher leash. Pass True to measure what dropping them costs.
    """
    key = (before, since, rates_before, offsets)
    if key in _SIDES:
        return _SIDES[key]

    with db.connect() as c:
        games = {r["game_id"]: dict(r) for r in c.execute(_F5_Q)}

    out = []
    for s, pitcher, lineup in cal.build_cases(before=before, since=since,
                                              rates_before=rates_before):
        g = games.get(s["game_id"])
        if not g:
            continue
        home = bool(s["is_home"])
        off = (sim.patience(s["team"]) + sim.leash(pitcher.name)
               if offsets else 0.0)
        out.append({
            "game_id": s["game_id"], "date": g["date"], "team": s["team"],
            "is_home": home, "pitcher": pitcher,
            "lineup": cal.adjust_lineup(lineup, home),
            # Runs this side ALLOWED through five = the opponent's F5 score.
            "runs": (g["af5"] if home else g["hf5"]) or 0,
            # Whether the starter himself covered all five. The only channel
            # through which the hook reaches an F5 number at all.
            "covered": s["o"] >= 15,
            "offset": off,
            # Seeded per side, not per run, so every candidate parameter set
            # is scored against the same draws. Without common random
            # numbers a coordinate descent on a noisy objective walks
            # wherever the seeds sent it.
            "seed": zlib.crc32(f'{s["game_id"]}|{s["team"]}'.encode()),
        })
    _SIDES[key] = out
    return out


def _rps(vals: list[int], actual: int, lines) -> float:
    """Ranked probability score of a simulated distribution against truth.

    Proper — a model cannot improve it by shading its numbers — and it is
    literally the sum of the Brier scores a book would grade at each line.

    DEBIASED for Monte Carlo. A probability read off `n` draws carries
    variance p(1-p)/n, and squaring it adds exactly that to the expected
    score: measured 1.434 at 20 sims, 1.411 at 40, 1.380 at 80 on the same
    parameters, which is not a model getting better. Subtracting the
    plug-in estimate makes the number mean the same thing at every sim count
    and, more usefully, makes it comparable to a Brier score somebody else
    computed.

    It cannot drive a term negative, which is worth knowing rather than
    assuming: at p = k/n the squared error is (n-k)^2/n^2 and the correction
    is k(n-k)/(n^2(n-1)), and those cross exactly at k = n-1, where both are
    1/n^2. So no clamp is needed and none should be added — a clamp would
    only ever fire on a bug.
    """
    n = len(vals) or 1
    tot = 0.0
    for ln in lines:
        p = sum(1 for v in vals if v > ln) / n
        tot += (p - (1.0 if actual > ln else 0.0)) ** 2
        if n > 1:
            tot -= p * (1.0 - p) / (n - 1)
    return tot


def game_pairs(cases: list[dict]) -> list[tuple]:
    """Sides regrouped into (away, home) pairs — one entry per game.

    `game.py` simulates BOTH sides at once, so the objective moves from
    sides to games. Two consequences, both wanted: one simulation per game
    instead of two, and sides whose opposing starter is not modelled drop
    out. About 10% are lost that way, which is the price of scoring on the
    engine the product actually uses.
    """
    by: dict[str, list] = {}
    for c in cases:
        by.setdefault(c["game_id"], []).append(c)
    out = []
    for v in by.values():
        if len(v) != 2 or sum(bool(x["is_home"]) for x in v) != 1:
            continue
        home = next(x for x in v if x["is_home"])
        away = next(x for x in v if not x["is_home"])
        out.append((away, home))
    return out


def evaluate(cases: list[dict], params: dict | None = None, n_sims=60,
             lg=None, salt=0) -> dict:
    """Score one parameter set. Lower `loss` is better.

    `salt` shifts every per-side seed. Its only purpose is measuring the
    objective's own noise floor: re-score identical parameters at several
    salts and the spread is the smallest difference this search can honestly
    resolve. A coordinate descent that accepts moves below that floor is
    fitting seeds, and it will report an improvement that a holdout then
    fails to reproduce.
    """
    lg = lg or sim.league()
    relief = f5.relief_rates()
    p = defaults()
    p.update(params or {})
    base = sim.Hook(**{k: p[k] for k in HOOK_KEYS})
    rules = {k: p[k] for k in RULE_KEYS}

    side_tot = 0.0
    sim_cov = act_cov = 0
    pooled: list[int] = []          # every simulated side, for the shape
    actual: list[int] = []
    pairs = game_pairs(cases)
    pens = rate_src.bullpens(lg)
    draws: dict[str, list[list[int]]] = defaultdict(list)
    actual_total: dict[str, int] = {}

    with sim.rules(**rules):
        for away, home in pairs:
            rng = random.Random(away["seed"] + salt)
            vals = {"away": [], "home": []}
            for _ in range(n_sims):
                A = game.build_side(
                    away["pitcher"],
                    pens.get((away["team"] or "").upper(), []),
                    home["lineup"], base, rng)
                H = game.build_side(
                    home["pitcher"],
                    pens.get((home["team"] or "").upper(), []),
                    away["lineup"], base, rng)
                game.simulate_game(A, H, lg, rng)
                # `Side.runs_f5` is runs ALLOWED through five by that
                # pitching side, which is exactly what the side observation
                # records. `GameResult.away_f5` is the opposite convention —
                # runs SCORED — and mixing them is the obvious way to build
                # this backwards.
                vals["away"].append(A.runs_f5)
                vals["home"].append(H.runs_f5)
                sim_cov += (A.line.outs >= 15) + (H.line.outs >= 15)
            for who, c in (("away", away), ("home", home)):
                side_tot += _rps(vals[who], c["runs"], SIDE_LINES)
                pooled.extend(vals[who])
                actual.append(c["runs"])
                act_cov += c["covered"]
            gid = away["game_id"]
            draws[gid] = [vals["away"], vals["home"]]
            actual_total[gid] = away["runs"] + home["runs"]

    # The game total, from the SAME simulated game rather than two
    # independent side draws added together. Under the stub the two sides
    # were simulated separately and pairing draw j with draw j assumed
    # independence; `game.py` plays them in one game, so this is now the
    # actual joint distribution — which is the only place the objective can
    # see both halves of a total at once.
    total_tot = 0.0
    for gid, (av, hv) in draws.items():
        total_tot += _rps([x + y for x, y in zip(av, hv)],
                          actual_total[gid], TOTAL_LINES)
    total_rps = total_tot / len(draws) if draws else 0.0

    n = len(pairs) * 2 or 1
    s, a = _dist(pooled), _dist(actual)
    return {
        "n_sides": n, "n_games": len(pairs),
        "side_rps": side_tot / n,
        "total_rps": total_rps,
        "loss": side_tot / n + W_TOTAL * total_rps,
        # Does a simulated inning look like a real one? The score above says
        # how well the model ranks sides; this says whether the runs it
        # invents have the right shape, which is the actual goal.
        "sim": s, "act": a,
        "sim_runs": s["mean"], "act_runs": a["mean"],
        "sim_covered": sim_cov / (n * n_sims), "act_covered": act_cov / n,
    }


#: Searched values per parameter. Deliberately coarse — the surface is smooth
#: in each one and a fine grid on a Monte Carlo objective mostly fits seeds.
GRID = {
    "intercept": [-5.4, -5.0, -4.6, -4.2, -3.8],
    "per_inning": [0.25, 0.35, 0.45, 0.60, 0.80],
    "per_run": [0.30, 0.45, 0.60, 0.75],
    "pitch_center": [86.0, 92.0, 98.0],
    "mid_intercept": [-5.6, -5.0, -4.4],
    "mid_per_runner": [0.35, 0.55, 0.80],
    # The three advancement constants are now TABLES keyed by out count and
    # are set from published references per out state, deliberately not
    # fitted — see sim.py. They are scanned as a single multiplier on the
    # whole table instead, so the SHAPE stays published and only the level
    # can move.
    "WP_PB_RATE": [0.010, 0.0155, 0.022, 0.030],
    # A double play ends a rally outright, so this is a run-production
    # mechanism and not the outs term it looks like.
    "GIDP_RATE": [0.07, 0.11, 0.15, 0.19],
}


#: Salts used to average a candidate's score. Each is a different set of
#: simulation draws over the SAME sides, so the spread across them is pure
#: Monte Carlo noise and their mean has a standard error the search can be
#: held to.
SALTS = (0, 7919, 15013, 22381, 31337, 40009)


def losses(cases, params, n_sims, lg, salts=SALTS) -> list[float]:
    """One loss per salt. Kept as a vector, not collapsed to a mean.

    Two candidates scored at the SAME salts are correlated — they share the
    sides, the actual outcomes and the seeds — so the spread of one
    candidate's losses badly overstates the uncertainty in the DIFFERENCE
    between two. Measured on this objective: the unpaired sd is 0.0165 while
    the sd of the paired difference is 0.0078, so throwing the pairing away
    inflates the error bar 2.6x and the search then rejects every real move.
    Returning the vector is what lets `_paired_se` use it.
    """
    return [evaluate(cases, params, n_sims=n_sims, lg=lg, salt=s)["loss"]
            for s in salts]


def _mean_se(ls: list[float]) -> tuple[float, float]:
    m = sum(ls) / len(ls)
    if len(ls) < 2:
        return m, 0.0
    var = sum((x - m) ** 2 for x in ls) / (len(ls) - 1)
    return m, (var / len(ls)) ** 0.5


def _paired_se(a: list[float], b: list[float]) -> tuple[float, float]:
    """Mean and standard error of the salt-by-salt difference b - a."""
    d = [y - x for x, y in zip(a, b)]
    return _mean_se(d)


def accept(cur: list[float], win: list[float]) -> tuple[bool, float, float]:
    """Should the search move from `cur` to `win`? -> (take, delta, se)

    Both are loss vectors over the same salts. The bar is ONE standard error
    of the paired difference, which is permissive on purpose: at four salts
    the standard error is itself a noisy estimate, so a stricter bar mostly
    means the fit never leaves its starting point while a looser one lets
    obvious noise through. It is a guard against wild moves, NOT a
    significance test — the out-of-sample window is what adjudicates, and
    nothing here should be reported as fitted until it does.
    """
    delta, se = _paired_se(cur, win)
    return delta < -se, delta, se


def score(cases, params, n_sims, lg, salts=SALTS) -> tuple[float, float]:
    """Mean loss over `salts` and its standard error. For reporting only —
    a comparison between two parameter sets must go through `_paired_se`."""
    return _mean_se(losses(cases, params, n_sims, lg, salts))


def check_grids() -> None:
    """Every searched parameter's grid must contain its own shipped value.

    A grid that omits its incumbent is not merely wasteful — `scan` looks the
    incumbent up by exact value, finds nothing, and `take` can never fire. The
    parameter is then scanned at full cost on every sweep and silently frozen,
    which reads in the output as a genuine "no move" rather than as a bug.
    That happened to WP_PB_RATE for two full runs after its shipped value was
    corrected to 0.0155 and the grid was left alone.
    """
    d = defaults()
    bad = [k for k in PARAMS
           if not any(abs(v - d[k]) < 1e-12 for v in GRID[k])]
    if bad:
        raise ValueError(
            f"grid does not contain the shipped value for {bad} — "
            f"these would be scanned at full cost and never move")


def scan(cases, param, values=None, n_sims=50, lg=None, base=None,
         salts=SALTS) -> list[tuple]:
    """Loss across one parameter's grid, everything else held.

    -> [(value, mean_loss, [loss per salt])]

    A curve rather than a winner, because on this objective the shape is the
    finding. A parameter whose curve is flat within its error bars does not
    need identifying — which is the entire argument for dropping 206 of
    them, and it should be shown rather than asserted.
    """
    lg = lg or sim.league()
    base = dict(base or defaults())
    out = []
    for v in (values or GRID[param]):
        ls = losses(cases, {**base, param: v}, n_sims, lg, salts)
        out.append((v, sum(ls) / len(ls), ls))
    return out


def tune(cases, n_sims=50, sweeps=2, start=None, verbose=True,
         salts=SALTS) -> dict:
    """Coordinate descent on the F5 objective, with a noise floor.

    NOT a plain descent. Measured on this objective, two nearby candidates
    differ by about 0.005 while the paired standard deviation of that
    difference is 0.008 at 40 sims — so a search that accepts any
    improvement accepts mostly noise, converges, and reports a gain the
    holdout then fails to reproduce. Every parameter's whole grid is scored
    at the same salts and a move is taken only when it beats the incumbent
    by more than the standard error of the PAIRED difference.

    Paired, not independent. The first version of this compared two means by
    combining their separate standard errors, which ignores that both were
    computed over the same sides, the same outcomes and the same seeds. That
    inflates the bar 2.6x and would have rejected every move on the board —
    a search that reports "nothing matters" because its own error bar was
    drawn wrong.

    The bar is ONE standard error, which is deliberately permissive: two
    sweeps and an out-of-sample window are what adjudicate the result, and a
    stricter bar here mostly means the fit never leaves its starting point.
    """
    check_grids()
    lg = sim.league()
    best = dict(start or defaults())
    for sweep in range(sweeps):
        for param in PARAMS:
            rows = scan(cases, param, n_sims=n_sims, lg=lg, base=best,
                        salts=salts)
            cur = next((r for r in rows if r[0] == best[param]), None)
            win = min(rows, key=lambda r: r[1])
            take, delta, se = (False, 0.0, 0.0)
            if cur is not None and win[0] != cur[0]:
                take, delta, se = accept(cur[2], win[2])
            if verbose:
                cells = "  ".join(
                    f"{v:g}:{m:.4f}{'*' if v == win[0] else ' '}"
                    for v, m, _ in rows)
                print(f"  s{sweep} {param:<24}{cells}   d{delta:+.4f}"
                      f" se{se:.4f}"
                      f"{'   TAKE ' + format(win[0], 'g') if take else ''}")
            if take:
                best[param] = win[0]
    if verbose:
        base = defaults()
        moved = [k for k in PARAMS if best[k] != base[k]]
        print(f"\n  {len(moved)} of {len(PARAMS)} parameters moved")
        for k in PARAMS:
            mark = "   <-- moved" if best[k] != base[k] else ""
            print(f"    {k:<24}{base[k]:>8}  ->{best[k]:>8}{mark}")
    return best


#: Column header matching `report`.
HEAD = (f"  {'':<16}{'CRPS':>9}{'runs':>8}{'sd':>7}{'shutout':>9}"
        f"{'5+ runs':>9}{'covered5':>10}")


def report(label: str, res: dict) -> None:
    """One line: the score, then whether the runs have the right shape."""
    s = res["sim"]
    print(f"  {label:<16}{res['loss']:>9.5f}{s['mean']:>8.2f}{s['sd']:>7.2f}"
          f"{s['p0']:>9.1%}{s['p5']:>9.1%}{res['sim_covered']:>10.1%}")


def report_actual(res: dict) -> None:
    a = res["act"]
    print(f"  {'ACTUAL':<16}{'':>9}{a['mean']:>8.2f}{a['sd']:>7.2f}"
          f"{a['p0']:>9.1%}{a['p5']:>9.1%}{res['act_covered']:>10.1%}")


def holdout(cutoff: str, n_sims=200, sweeps=2, fit_sims=50) -> dict:
    """Fit strictly before `cutoff`, score strictly on or after it.

    Rates for the TEST window are frozen before the cutoff too. Tying rates
    to the same window as the starts is what makes an out-of-sample test
    quietly in-sample, and it is a mistake this project has already made
    once.
    """
    train = side_cases(before=cutoff)
    test = side_cases(since=cutoff, rates_before=cutoff)
    print(f"train {len(train)} sides before {cutoff}, "
          f"test {len(test)} on/after\n")

    fitted = tune(train, n_sims=fit_sims, sweeps=sweeps)

    lg = sim.league()
    print(f"\n{HEAD}")
    print("  -- train --")
    tr = evaluate(train, None, n_sims=n_sims, lg=lg)
    report("shipped", tr)
    report("fitted", evaluate(train, fitted, n_sims=n_sims, lg=lg))
    report_actual(tr)
    print("  -- test (unseen) --")
    a = evaluate(test, None, n_sims=n_sims, lg=lg)
    b = evaluate(test, fitted, n_sims=n_sims, lg=lg)
    report("shipped", a)
    report("fitted", b)
    report_actual(a)
    # The whole question on the test window is whether a difference this
    # small is real, so it is measured salt by salt and paired — the same
    # correction the search itself needed.
    la = losses(test, None, n_sims, lg)
    lb = losses(test, fitted, n_sims, lg)
    ma, sa = _mean_se(la)
    mb, sb = _mean_se(lb)
    delta, dse = _paired_se(la, lb)
    print(f"\n  actual runs/side {a['act_runs']:.2f}, "
          f"starter covered five {a['act_covered']:.1%}")
    print(f"  test loss  shipped {ma:.5f} +/- {sa:.5f}   "
          f"fitted {mb:.5f} +/- {sb:.5f}")
    print(f"  paired difference {delta:+.5f} +/- {dse:.5f}"
          f"  ({delta / dse if dse else 0:+.1f} sigma, negative = fitted "
          f"better)")
    return fitted


def offsets_cost(cutoff: str, n_sims=60) -> None:
    """What does dropping club patience and pitcher leash cost on F5?

    The rebuild drops 206 parameters on the argument that they reach an F5
    number through one channel — whether the starter is still in through the
    fifth — and he is roughly three-quarters of the time. That is an
    argument, not a measurement. This is the measurement.
    """
    lg = sim.league()
    flat = side_cases(since=cutoff, rates_before=cutoff, offsets=False)
    adj = side_cases(since=cutoff, rates_before=cutoff, offsets=True)
    moved = sum(1 for c in adj if c["offset"])
    print(f"{len(flat)} sides on/after {cutoff}, "
          f"{moved} carry a non-zero offset\n")
    print(HEAD)
    fa = evaluate(flat, None, n_sims=n_sims, lg=lg)
    report("flat", fa)
    report("patience+leash", evaluate(adj, None, n_sims=n_sims, lg=lg))
    report_actual(fa)


if __name__ == "__main__":
    args = sys.argv[1:]

    def opt(flag, default):
        return (args[args.index(flag) + 1]
                if flag in args and len(args) > args.index(flag) + 1
                else default)

    cut = opt("--cutoff", "2026-08-09")
    sims = int(opt("--sims", "60"))
    if "--with-hook" in args:
        # Off by default: measured, every hook term is flat inside its own
        # error bar on this objective. See HOOK_KEYS.
        PARAMS = HOOK_KEYS + RULE_KEYS                       # noqa: F811
        globals()["PARAMS"] = PARAMS
    if "--offsets" in args:
        offsets_cost(cut, n_sims=sims)
    elif "--score" in args:
        lg = sim.league()
        cases = side_cases(since=cut, rates_before=cut)
        print(f"{len(cases)} sides on/after {cut}\n")
        print(HEAD)
        res = evaluate(cases, None, n_sims=sims, lg=lg)
        report("shipped", res)
        report_actual(res)
    else:
        holdout(cut, n_sims=sims, sweeps=int(opt("--sweeps", "2")),
                fit_sims=int(opt("--fit-sims", "40")))
