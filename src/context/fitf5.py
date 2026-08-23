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
from src.context import f5, sim

#: Lines to score a SIDE at. A side allows 2.38 runs through five on
#: average, so these bracket it; the outer two are thin but a fit that gets
#: the tail wrong prices the shutout and the blowup wrong.
SIDE_LINES = (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)
#: And a full game total. Kalshi's F5 board clusters on 4.5.
TOTAL_LINES = (2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5)

#: Weight on the game-total term. Small on purpose: the total is the sum of
#: two sides already in the objective, so it adds little beyond them — what
#: it does add is the pairing, which is the only place the fit can see that
#: an early hook puts a reliever into BOTH halves of a settled number.
W_TOTAL = 0.25

#: Hook fields the fit may move. Six of eleven — the mid-inning damage and
#: baserunner terms and the hard cap are left where the outs fit put them,
#: because F5 runs barely see them and a parameter a fit cannot resolve
#: should not be handed to a search that will move it anyway.
HOOK_KEYS = ("intercept", "per_inning", "per_run", "pitch_center",
             "mid_intercept", "mid_per_runner")
#: Base-running constants, via `sim.rules`. These move F5 runs directly.
RULE_KEYS = ("FIRST_TO_THIRD_ON_1B", "SECOND_SCORES_ON_1B",
             "FIRST_SCORES_ON_2B", "RUNNER_ADVANCES_ON_OUT",
             "INHERITED_SCORE_RATE")

PARAMS = HOOK_KEYS + RULE_KEYS


def defaults() -> dict:
    """Current shipped values for everything the fit can move."""
    h = sim.Hook()
    out = {k: getattr(h, k) for k in HOOK_KEYS}
    out.update({k: getattr(sim, k) for k in RULE_KEYS})
    return out


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
    sim_runs = act_runs = 0.0
    sim_cov = act_cov = 0
    draws: dict[str, list[list[int]]] = defaultdict(list)
    actual_total: dict[str, int] = {}

    with sim.rules(**rules):
        for c in cases:
            hook = (base if not c["offset"] else
                    sim.Hook(**{**base.__dict__, "team_offset": c["offset"]}))
            rng = random.Random(c["seed"] + salt)
            vals = []
            for _ in range(n_sims):
                runs, r = f5._side_runs(c["pitcher"], c["lineup"], lg, hook,
                                        rng, sim.NEUTRAL_PARK, relief)
                vals.append(runs)
                sim_cov += r.outs >= 15
            side_tot += _rps(vals, c["runs"], SIDE_LINES)
            sim_runs += sum(vals) / n_sims
            act_runs += c["runs"]
            act_cov += c["covered"]
            draws[c["game_id"]].append(vals)
            actual_total[c["game_id"]] = \
                actual_total.get(c["game_id"], 0) + c["runs"]

    n = len(cases) or 1
    # A game total only exists where BOTH starters are modelled. Pairing
    # draw j of one side with draw j of the other is an independent sum,
    # which is what two starters facing different lineups are.
    pairs = [(g, v) for g, v in draws.items() if len(v) == 2]
    total_tot = 0.0
    for g, (a, b) in pairs:
        total_tot += _rps([x + y for x, y in zip(a, b)],
                          actual_total[g], TOTAL_LINES)
    total_rps = total_tot / len(pairs) if pairs else 0.0

    return {
        "n_sides": n, "n_games": len(pairs),
        "side_rps": side_tot / n,
        "total_rps": total_rps,
        "loss": side_tot / n + W_TOTAL * total_rps,
        "sim_runs": sim_runs / n, "act_runs": act_runs / n,
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
    "FIRST_TO_THIRD_ON_1B": [0.22, 0.28, 0.34, 0.40],
    "SECOND_SCORES_ON_1B": [0.52, 0.60, 0.68, 0.76],
    "FIRST_SCORES_ON_2B": [0.35, 0.45, 0.55, 0.65],
    "RUNNER_ADVANCES_ON_OUT": [0.15, 0.25, 0.35],
    "INHERITED_SCORE_RATE": [0.25, 0.33, 0.42],
}


#: Salts used to average a candidate's score. Each is a different set of
#: simulation draws over the SAME sides, so the spread across them is pure
#: Monte Carlo noise and their mean has a standard error the search can be
#: held to.
SALTS = (0, 7919, 15013)


def score(cases, params, n_sims, lg, salts=SALTS) -> tuple[float, float]:
    """Mean loss over `salts`, and the standard error of that mean."""
    ls = [evaluate(cases, params, n_sims=n_sims, lg=lg, salt=s)["loss"]
          for s in salts]
    m = sum(ls) / len(ls)
    if len(ls) < 2:
        return m, 0.0
    var = sum((x - m) ** 2 for x in ls) / (len(ls) - 1)
    return m, (var / len(ls)) ** 0.5


def scan(cases, param, values=None, n_sims=50, lg=None, base=None,
         salts=SALTS) -> list[tuple]:
    """Loss across one parameter's grid, everything else held. -> [(v, m, se)]

    A curve rather than a winner, because on this objective the shape is the
    finding. A parameter whose curve is flat within its error bars does not
    need identifying — which is the entire argument for dropping 206 of
    them, and it should be shown rather than asserted.
    """
    lg = lg or sim.league()
    base = dict(base or defaults())
    return [(v,) + score(cases, {**base, param: v}, n_sims, lg, salts)
            for v in (values or GRID[param])]


def tune(cases, n_sims=50, sweeps=2, start=None, verbose=True,
         salts=SALTS) -> dict:
    """Coordinate descent on the F5 objective, with a noise floor.

    NOT a plain descent. Measured on this objective, two nearby candidates
    differ by about 0.005 while the paired standard deviation of that
    difference is 0.008 at 40 sims — so a search that accepts any
    improvement accepts mostly noise, converges, and reports a gain the
    holdout then fails to reproduce. Every parameter's whole grid is scored
    at the same salts and a move is taken only when it beats the incumbent
    by more than the standard error of the difference.

    Common random numbers help less here than they usually do: the seed is
    shared per side, but the draw streams diverge as soon as two parameter
    sets produce different outcomes, so the pairing survives only a few
    plate appearances. Averaging over salts is doing most of the work.
    """
    lg = sim.league()
    best = dict(start or defaults())
    for sweep in range(sweeps):
        for param in PARAMS:
            rows = scan(cases, param, n_sims=n_sims, lg=lg, base=best,
                        salts=salts)
            cur = next((r for r in rows if r[0] == best[param]), None)
            win = min(rows, key=lambda r: r[1])
            # se of a DIFFERENCE of two means, each with its own se.
            se = ((cur[2] ** 2 + win[2] ** 2) ** 0.5) if cur else win[2]
            take = cur is not None and win[0] != cur[0] and \
                win[1] < cur[1] - se
            if verbose:
                cells = "  ".join(
                    f"{v:g}:{m:.4f}{'*' if (v == win[0]) else ' '}"
                    for v, m, _ in rows)
                print(f"  s{sweep} {param:<24}{cells}   se{se:.4f}"
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


def report(label: str, res: dict) -> None:
    print(f"  {label:<16}{res['loss']:>9.5f}{res['side_rps']:>10.5f}"
          f"{res['total_rps']:>10.5f}{res['sim_runs']:>9.2f}"
          f"{res['sim_covered']:>10.1%}")


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
    print(f"\n{'':<16}{'loss':>9}{'side RPS':>10}{'total':>10}"
          f"{'runs':>9}{'covered':>10}")
    print("  -- train --")
    report("shipped", evaluate(train, None, n_sims=n_sims, lg=lg))
    report("fitted", evaluate(train, fitted, n_sims=n_sims, lg=lg))
    print("  -- test (unseen) --")
    a = evaluate(test, None, n_sims=n_sims, lg=lg)
    b = evaluate(test, fitted, n_sims=n_sims, lg=lg)
    report("shipped", a)
    report("fitted", b)
    # Scored at more salts than the fit used, because the whole question on
    # the test window is whether a difference this small is real.
    ma, sa = score(test, None, n_sims, lg)
    mb, sb = score(test, fitted, n_sims, lg)
    print(f"\n  actual runs/side {a['act_runs']:.2f}, "
          f"starter covered five {a['act_covered']:.1%}")
    print(f"  test loss  shipped {ma:.5f} +/- {sa:.5f}   "
          f"fitted {mb:.5f} +/- {sb:.5f}")
    print(f"  difference {mb - ma:+.5f} "
          f"+/- {(sa ** 2 + sb ** 2) ** 0.5:.5f} (negative = fitted better)")
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
    print(f"  {'':<16}{'loss':>9}{'side RPS':>10}{'total':>10}"
          f"{'runs':>9}{'covered':>10}")
    report("flat", evaluate(flat, None, n_sims=n_sims, lg=lg))
    report("patience+leash", evaluate(adj, None, n_sims=n_sims, lg=lg))


if __name__ == "__main__":
    args = sys.argv[1:]

    def opt(flag, default):
        return (args[args.index(flag) + 1]
                if flag in args and len(args) > args.index(flag) + 1
                else default)

    cut = opt("--cutoff", "2026-08-09")
    sims = int(opt("--sims", "60"))
    if "--offsets" in args:
        offsets_cost(cut, n_sims=sims)
    elif "--score" in args:
        lg = sim.league()
        cases = side_cases(since=cut, rates_before=cut)
        print(f"{len(cases)} sides on/after {cut}\n")
        print(f"  {'':<16}{'loss':>9}{'side RPS':>10}{'total':>10}"
              f"{'runs':>9}{'covered':>10}")
        report("shipped", evaluate(cases, None, n_sims=sims, lg=lg))
    else:
        holdout(cut, n_sims=sims, sweeps=int(opt("--sweeps", "2")),
                fit_sims=int(opt("--fit-sims", "40")))
