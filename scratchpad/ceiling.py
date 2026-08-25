"""How much between-START variation is there to predict, and how much do we
produce?

The same decomposition `scratchpad/resolution.py` ran on game totals, moved
to the target that should have the most between-game signal in it: the
STARTER's own line. A team total is mostly two bullpens and eighteen half
innings of noise; a starter's outs and strikeouts are one man against nine
known hitters, so if between-game features pay anywhere they pay here.

    var(actual) = var(true per-start mean) + E[within-start var]

`within` comes from our own simulation, so this assumes our per-start SPREAD
is about right. It is checked: outs SD 3.95 against a real 3.99 pooled. If
our within is too WIDE the implied true between-start sd is understated and
our share is flattered, so the number to distrust is a share near 100%.

THE BET-LEVEL VIEW, and the one that decides whether any of this pays: a
bet settles on a THRESHOLD, so what matters is not the spread of our
predicted means but how far our P(over the line) moves off the base rate.
A model whose mean wanders half an out while its median never leaves 18 is
differentiating nothing a book would price. `--lines` reports, per line, the
sd of our per-start probability against the sd a PERFECT forecaster would
have — which is the Brier resolution term, and the achievable half of it is
estimated by pushing the implied between-start spread back through our own
within-start shape.

    venv/bin/python -m scratchpad.ceiling [n_starts|-] [n_sims]
"""
import json
import multiprocessing as mp
import os
import random
import statistics as st
import sys

from src.context import calibrate as cal
from src.context import sim

STATS = ("outs", "k", "er", "h", "bb")
_COL = {"outs": "o", "k": "k", "er": "er", "h": "h", "bb": "bb"}
_ATTR = {"outs": "outs", "k": "k", "er": "earned", "h": "h", "bb": "bb"}

#: Where books actually hang these. Outs sit on thirds because a line of
#: 17.5 is "does he finish the sixth".
LINES = {"outs": (14.5, 15.5, 17.5, 18.5, 20.5),
         "k": (3.5, 4.5, 5.5, 6.5, 7.5),
         "er": (1.5, 2.5, 3.5, 4.5),
         "h": (4.5, 5.5, 6.5),
         "bb": (1.5, 2.5)}

_CASES = None


def _one(args):
    i, n_sims, seed = args
    s, pitcher, lineup = _CASES[i]
    lg = sim.league()
    rng = random.Random(seed)
    hook = sim.for_start(sim.Hook(), s["team"], pitcher.name)
    pk = cal.park_for(s.get("venue_id")) if cal.USE_PARK else sim.NEUTRAL_PARK
    home = bool(s.get("is_home"))
    nine = cal.adjust_lineup(lineup, home)
    if cal.HOME_HOOK and home:
        hook = sim.Hook(**{**hook.__dict__,
                           "team_offset": hook.team_offset + cal.HOME_HOOK})
    draws = [sim.simulate_start(pitcher, nine, lg, hook, rng, park=pk)
             for _ in range(n_sims)]
    rec = {"game_id": s["game_id"], "team": s["team"], "date": s["date"],
           "player": s["player_name"], "venue_id": s["venue_id"],
           "day_night": s["day_night"], "is_home": s["is_home"]}
    for stat in STATS:
        v = [getattr(d, _ATTR[stat]) for d in draws]
        rec[f"a_{stat}"] = s[_COL[stat]]
        rec[f"m_{stat}"] = st.mean(v)
        rec[f"w_{stat}"] = st.pvariance(v)
        rec[f"med_{stat}"] = st.median(v)
        rec[f"p_{stat}"] = [sum(1 for x in v if x > ln) / len(v)
                            for ln in LINES[stat]]
    return rec


def _init(cases):
    global _CASES
    _CASES = cases


def collect(limit=None, n_sims=300, seed=0, holdout=None):
    global _CASES
    # A holdout is the only way to answer the leakage question this whole
    # analysis turns on: with rates estimated over the SAME starts being
    # scored, a pitcher's season mean is already absorbed into his rates,
    # which SUPPRESSES a per-pitcher residual rather than inventing one —
    # but "the artifact has the conservative sign" is an argument, and a
    # cutoff is a measurement.
    _CASES = cal.build_cases(max_starts=limit, since=holdout,
                             rates_before=holdout)
    n = len(_CASES)
    print(f"  {n} starts x {n_sims} draws", flush=True)
    # FORK, not spawn: a spawned child re-imports every module at DEFAULT
    # global state, so `USE_PARK`, `USE_TTO` and the rest silently revert
    # and the whole run measures a model nobody ships. Pinned elsewhere by
    # `check_worker_state_crosses_the_fork`.
    ctx = mp.get_context("fork")
    workers = max(1, (os.cpu_count() or 4) - 2)
    with ctx.Pool(workers) as pool:
        out = []
        for j, rec in enumerate(pool.imap(
                _one, [(i, n_sims, seed) for i in range(n)], chunksize=16)):
            out.append(rec)
            if (j + 1) % 500 == 0:
                print(f"  {j + 1}/{n}", flush=True)
    return out


def report(rows) -> None:
    print(f"\n  {len(rows)} starts")
    print(f"\n  {'':<7}{'actual sd':>11}{'our within':>12}{'implied':>9}"
          f"{'our spread':>12}{'share':>8}{'ceiling':>9}{'corr':>8}"
          f"{'of ceil':>9}")
    for stat in STATS:
        a = [r[f"a_{stat}"] for r in rows]
        m = [r[f"m_{stat}"] for r in rows]
        w = [r[f"w_{stat}"] for r in rows]
        sa, sm = st.pstdev(a), st.pstdev(m)
        within = st.mean(w) ** 0.5
        between = max(st.pvariance(a) - st.mean(w), 0) ** 0.5
        ceil = between / sa if sa else 0.0
        ma, mm = st.mean(a), st.mean(m)
        r = (sum((x - mm) * (y - ma) for x, y in zip(m, a))
             / (len(a) * sm * sa)) if sm and sa else 0.0
        print(f"  {stat:<7}{sa:>11.2f}{within:>12.2f}{between:>9.2f}"
              f"{sm:>12.2f}{(sm / between if between else 0):>8.0%}"
              f"{ceil:>9.3f}{r:>8.3f}{(r / ceil if ceil else 0):>9.0%}")
    print("\n  'implied' is sqrt(var(actual) - mean within-start var): how"
          "\n  much start-to-start variation really exists. 'our spread' is"
          "\n  the sd of our per-start predicted means, 'share' the ratio."
          "\n  'ceiling' is the correlation a PERFECT forecaster would get"
          "\n  (implied/actual sd); 'of ceil' is how much of it we capture.")
    print()
    for stat in STATS:
        a = st.mean([r[f"a_{stat}"] for r in rows])
        m = st.mean([r[f"m_{stat}"] for r in rows])
        print(f"  {stat:<7} actual mean {a:>6.2f}   model {m:>6.2f}"
              f"   {m - a:+.2f}")


def lines_report(rows) -> None:
    """The bet-level view: does our number MOVE at the threshold?

    The Brier resolution term is var(p) across starts. A perfect forecaster
    whose true means are spread by `between` and whose within-start shape
    matches ours achieves a resolution we can estimate directly: shift each
    start's own simulated distribution by a draw from that spread and see
    how far the resulting probability moves. That keeps the discreteness —
    outs land on whole innings, and a normal approximation would quietly
    promise resolution the shape cannot deliver.
    """
    print("\n  BET LEVEL — how far the number moves off the base rate\n")
    for stat in STATS:
        a = [r[f"a_{stat}"] for r in rows]
        w = [r[f"w_{stat}"] for r in rows]
        between = max(st.pvariance(a) - st.mean(w), 0) ** 0.5
        sm = st.pstdev([r[f"m_{stat}"] for r in rows])
        # how much MORE spread a perfect forecaster's means would have
        extra = max(between ** 2 - sm ** 2, 0) ** 0.5
        med = [r[f"med_{stat}"] for r in rows]
        print(f"  {stat}   median of our per-start medians "
              f"{st.median(med):.1f}, sd {st.pstdev(med):.2f}, "
              f"{len(set(med))} distinct values")
        print(f"  {'line':>7}{'base':>8}{'our mean p':>12}{'our sd(p)':>11}"
              f"{'achievable':>12}{'share':>8}")
        for j, ln in enumerate(LINES[stat]):
            p = [r[f"p_{stat}"][j] for r in rows]
            base = sum(1 for x in a if x > ln) / len(a)
            # nudge each start's mean by the missing between-start spread and
            # re-read the probability off a normal with that start's own sd
            ach = _achievable(rows, stat, ln, extra)
            sp = st.pstdev(p)
            print(f"  {ln:>7}{base:>8.1%}{st.mean(p):>12.1%}{sp:>11.3f}"
                  f"{ach:>12.3f}{(sp / ach if ach else 0):>8.0%}")
        print()
    print("  'our sd(p)' IS the Brier resolution term (its square).")
    print("  'achievable' adds the missing between-start spread to each")
    print("  start's own mean and re-reads the probability, so it is what")
    print("  this same simulator would produce if it differentiated starts")
    print("  as much as reality does. share < 100% is unpriced signal.")


def _achievable(rows, stat, ln, extra, draws=41):
    """sd of p if each start's mean were spread by `extra` more."""
    import math
    if extra <= 0:
        return st.pstdev([r[f"p_{stat}"][LINES[stat].index(ln)] for r in rows])
    ps = []
    for r in rows:
        sd = max(r[f"w_{stat}"] ** 0.5, 1e-6)
        mu = r[f"m_{stat}"]
        for t in range(draws):
            # deterministic quantiles of N(0, extra) so this does not add
            # Monte Carlo noise on top of the quantity being measured
            q = (t + 0.5) / draws
            z = _probit(q) * extra
            ps.append(0.5 * (1 - math.erf(((ln - (mu + z)) / sd)
                                          / math.sqrt(2))))
    return st.pstdev(ps)


def _probit(p):
    import math
    # Acklam-style rational approximation, plenty for a spread estimate
    a = [-39.69683028665376, 220.9460984245205, -275.9285104469687,
         138.3577518672690, -30.66479806614716, 2.506628277459239]
    b = [-54.47609879822406, 161.5858368580409, -155.6989798598866,
         66.80131188771972, -13.28068155288572]
    c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838,
         -2.549732539343734, 4.374664141464968, 2.938163982698783]
    d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996,
         3.754408661907416]
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q
                + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > 1 - pl:
        return -_probit(1 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r
            + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r
                            + b[4]) * r + 1)


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] != "-" \
        else None
    n_sims = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    holdout = sys.argv[3] if len(sys.argv) > 3 else None
    rows = collect(limit, n_sims, holdout=holdout)
    report(rows)
    lines_report(rows)
    path = ("scratchpad/ceiling_rows.json" if not holdout
            else "scratchpad/ceiling_holdout.json")
    with open(path, "w") as f:
        json.dump(rows, f)
    print(f"\n  wrote {path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
