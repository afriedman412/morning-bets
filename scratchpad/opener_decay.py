"""HOW FAST DOES A PITCHER'S OUTS RECORD GO STALE? — TODO 15.

QUESTION. `game.opener_record` averages EVERY prior start a man has ever
made, with equal weight, and calls him an opener under `OPENER_AVG_OUTS`.
A flat mean over four seasons cannot notice a role change in either
direction, and both directions cost:

  * a converted starter-to-opener carries three seasons of sixteen-out
    starts and never trips the gate;
  * a converted opener-to-starter carries the opposite and trips it for
    months. Counted 2026-09-09: the gate fires on 627 starts in 2024-2026
    and 18.2% (own-record) / 11.1% (pooled) of them went fifteen outs or
    more.

HYPOTHESIS. The record's predictive power decays, and the decay is
MEASURABLE against the thing the gate exists to anticipate — how long he
actually goes tonight. Weighting by that decay fixes both directions with
one number.

TEST. For every start with a prior record, predict tonight's outs from his
own previous starts under four estimators — the shipped flat mean, a
trailing window, and an exponential decay in DAYS or in STARTS — and score
RMSE. The half-life is chosen on rows BEFORE `HOLDOUT` only and confirmed
on the holdout rows, the same posture `stabilise.py` takes: this fits a
MEASUREMENT of staleness to the quantity it predicts, not a constant to a
loss.

WHAT WOULD FALSIFY IT. If the flat mean is inside one se of the best decay
on holdout rows, the record does not go stale, the false positives are
something else, and the recency weight closes with a null.

POWER, before the result. ~20,000 starts with a prior record, sd of start
outs ~6.5, so an RMSE difference of 0.05 outs is ~3 sigma. The gate cares
about the SHORT-RECORD population specifically, so the tables below split
it out — the estimator is evaluated on every start (it must not fire on a
normal starter), which is why it is FITTED on every start too. That is the
boundary-curve rule from CLAUDE.md, not an oversight.

    venv/bin/python -m scratchpad.opener_decay [--holdout]
"""
from __future__ import annotations

import math
import sys
from collections import defaultdict
from datetime import date as _date

from src import db
from src.context.holdout import HOLDOUT

#: Start records live in `mlb_pitching`, the same table `game._opener_starts`
#: reads, so the instrument and the shipped gate see identical rows.
_Q = """
  select p.player_name nm, g.date d, p.outs_recorded o
  from mlb_pitching p join games g on g.game_id = p.game_id
  where g.sport = 'mlb' and g.status = 'Final' and p.is_starter = 1
    and p.outs_recorded is not null
  order by g.date
"""

#: Minimum prior starts before an estimator is asked anything. Matches
#: `game.OPENER_MIN_STARTS` so the comparison is on the gate's own rows.
MIN_PRIOR = 2


def _days(a: str, b: str) -> int:
    ya, ma, da = (int(x) for x in a.split("-"))
    yb, mb, dbb = (int(x) for x in b.split("-"))
    return (_date(ya, ma, da) - _date(yb, mb, dbb)).days


def load(conn=None) -> dict[str, list[tuple[str, int]]]:
    def _run(c):
        out: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for r in c.execute(_Q):
            out[r["nm"]].append((r["d"], r["o"] or 0))
        return {k: sorted(v) for k, v in out.items()}
    if conn is not None:
        return _run(conn)
    with db.connect() as c:
        return _run(c)


def rows(starts: dict) -> list[dict]:
    """One row per start that has `MIN_PRIOR` prior starts behind it."""
    out = []
    for nm, rec in starts.items():
        for i in range(MIN_PRIOR, len(rec)):
            d, o = rec[i]
            out.append({"nm": nm, "date": d, "outs": o, "prior": rec[:i]})
    out.sort(key=lambda r: r["date"])
    return out


# ----------------------------------------------------------- the estimators
def flat(prior, _date_):
    return sum(o for _, o in prior) / len(prior)


def window(k):
    def f(prior, _date_):
        w = prior[-k:]
        return sum(o for _, o in w) / len(w)
    f.__name__ = f"last {k} starts"
    return f


def decay_starts(half):
    def f(prior, _date_):
        num = den = 0.0
        for j, (_, o) in enumerate(reversed(prior)):
            w = 0.5 ** (j / half)
            num += w * o
            den += w
        return num / den
    f.__name__ = f"decay {half:g} starts"
    return f


def decay_days(half):
    def f(prior, at):
        num = den = 0.0
        for d, o in prior:
            w = 0.5 ** (_days(at, d) / half)
            num += w * o
            den += w
        return num / den
    f.__name__ = f"decay {half:g} days"
    return f


def rmse(rs, est):
    s = 0.0
    for r in rs:
        s += (est(r["prior"], r["date"]) - r["outs"]) ** 2
    return math.sqrt(s / len(rs))


def se_of_diff(rs, a, b):
    """se of the PAIRED difference in squared error — the rows are the same
    starts under both estimators, so pairing is what gives this any power."""
    ds = [(a(r["prior"], r["date"]) - r["outs"]) ** 2
          - (b(r["prior"], r["date"]) - r["outs"]) ** 2 for r in rs]
    m = sum(ds) / len(ds)
    var = sum((x - m) ** 2 for x in ds) / (len(ds) - 1)
    return m, (var / len(ds)) ** 0.5


def report(rs, label):
    short = [r for r in rs if flat(r["prior"], r["date"]) < 11.0]
    print(f"\n{label}: {len(rs):,} starts   "
          f"({len(short):,} whose flat record is already under 11 outs)")
    base = flat
    cands = [flat, window(5), window(10),
             decay_starts(3), decay_starts(5), decay_starts(8),
             decay_starts(12),
             # DAYS, and the grid runs well past the optimum in BOTH
             # directions on purpose: a parameter sitting on a grid edge
             # is a missing mechanism, four for four in this project.
             decay_days(20), decay_days(30), decay_days(45),
             decay_days(60), decay_days(90), decay_days(120),
             decay_days(180), decay_days(240), decay_days(365),
             decay_days(540)]
    print(f"    {'estimator':<20}{'RMSE':>8}{'short-record':>14}"
          f"{'vs flat':>12}")
    for f in cands:
        nm = getattr(f, "__name__", str(f))
        nm = "flat (shipped)" if f is flat else nm
        d = ""
        if f is not base:
            m, se = se_of_diff(rs, f, base)
            d = f"{m / se:+6.1f} sd"
        print(f"    {nm:<20}{rmse(rs, f):>8.4f}{rmse(short, f):>14.4f}"
              f"{d:>12}")


#: A PLANNED opener, for scoring the gate as a classifier: the starter goes
#: six outs or fewer WITHOUT being chased (two runs or fewer), and the arm
#: behind him goes nine or more. Conservative on purpose — a blown-up
#: starter is short for a different reason and does not belong in the
#: population the gate exists to catch.
def opener_truth(conn=None) -> set[tuple[str, str]]:
    """{(pitcher, date)} of starts that were really an opener's."""
    from src.context import store
    q = """
      select s.player_name nm, s.date d, s.outs_recorded o, s.runs r,
             f.outs_recorded fo
      from mlb_stints s
      join mlb_stints f on f.game_id = s.game_id and f.team = s.team
                        and f.appearance_order = 1
      where s.appearance_order = 0
    """

    def _run(c):
        return {(r["nm"], r["d"]) for r in c.execute(q)
                if (r["o"] or 0) <= 6 and (r["r"] or 0) <= 2
                and (r["fo"] or 0) >= 9}
    if conn is not None:
        return _run(conn)
    with store.connect() as c:
        return _run(c)


def classify(rs, truth, threshold=11.0):
    """The gate's REAL job, scored as a classifier rather than by RMSE.

    RECALL is the share of true opener starts the gate fires on. The
    FALSE-ALARM column is the share of gate-fired starts that went fifteen
    outs or more — a genuine rotation start handed an opener's exit draw,
    which is the failure the flat mean produces in the other direction.
    """
    print(f"\n    {'estimator':<20}{'recall':>9}{'false alarm':>13}"
          f"{'fires on':>10}")
    for f in (flat, decay_days(20), decay_days(30), decay_days(45),
              decay_days(60), decay_days(90), decay_days(120),
              decay_days(240)):
        hit = miss = fired = alarm = 0
        for r in rs:
            est = f(r["prior"], r["date"]) < threshold
            true = (r["nm"], r["date"]) in truth
            if est:
                fired += 1
                alarm += r["outs"] >= 15
            if true:
                hit += est
                miss += not est
        nm = "flat (shipped)" if f is flat else f.__name__
        print(f"    {nm:<20}{hit / max(hit + miss, 1):>8.1%}"
              f"{alarm / max(fired, 1):>13.1%}{fired:>10}")
    print(f"      ({hit + miss} true opener starts in this population)")


def main() -> None:
    starts = load()
    rs = rows(starts)
    train = [r for r in rs if r["date"] < HOLDOUT]
    held = [r for r in rs if r["date"] >= HOLDOUT]
    print(f"{len(starts):,} pitchers, {len(rs):,} starts with {MIN_PRIOR}+"
          f" priors, cutoff {HOLDOUT}")
    report(train, "TRAIN (before the cutoff)")
    truth = opener_truth()
    print(f"\nTHE GATE AS A CLASSIFIER — {len(truth):,} planned opener starts"
          f" on file")
    classify(train, truth)
    if "--holdout" in sys.argv:
        report(held, "HOLDOUT — read only after the choice is made")
        classify(held, truth)


if __name__ == "__main__":
    main()
