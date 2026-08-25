"""WHERE is the missing between-start variation in starter outs?

`scratchpad/ceiling.py` says there are ~2.7 outs of real start-to-start
variation and we produce ~0.5 of it. This asks which grouping or which
observable carries the rest, WITHOUT building anything into the simulator:
every test is run on the RESIDUAL `actual - predicted`, so a feature that
already feeds the model (the opposing nine) must score ~0 and acts as the
control.

Two kinds of test:

  * LEAVE-ONE-OUT GROUP SIGNAL. For each start, the mean residual of the
    same pitcher's (or club's, or park's) OTHER starts, correlated against
    this start's residual. Leave-one-out because a group mean containing
    the target manufactures a correlation — see the note in RESUME about
    the (-1/n)/sqrt(...) artifact, which is the same failure with the sign
    flipped. This is directly actionable: the correlation IS the resolution
    a per-group offset would add.

  * PER-START OBSERVABLES. Plain correlation of the residual against
    home/away, day/night, park run index, days of rest, and the opposing
    lineup's quality.

    venv/bin/python -m scratchpad.between [stat]
"""
import json
import math
import statistics as st
import sys
from collections import defaultdict


def load(path="scratchpad/ceiling_rows.json"):
    with open(path) as f:
        return json.load(f)


def _corr(x, y):
    n = len(x)
    if n < 3:
        return 0.0, 0.0
    mx, my = st.mean(x), st.mean(y)
    sx, sy = st.pstdev(x), st.pstdev(y)
    if not sx or not sy:
        return 0.0, 0.0
    r = sum((a - mx) * (b - my) for a, b in zip(x, y)) / (n * sx * sy)
    r = max(-0.999, min(0.999, r))
    z = 0.5 * math.log((1 + r) / (1 - r)) * math.sqrt(n - 3)
    return r, z


def loo_group(rows, key, resid, min_n=6):
    """Correlation between a group's OTHER starts' mean residual and this one.

    The group mean is recomputed excluding the target start, so a group with
    no real effect scores zero rather than the negative artifact that
    leave-nothing-out produces.
    """
    tot, cnt = defaultdict(float), defaultdict(int)
    for r, v in zip(rows, resid):
        tot[key(r)] += v
        cnt[key(r)] += 1
    x, y = [], []
    for r, v in zip(rows, resid):
        k = key(r)
        if cnt[k] - 1 < min_n:
            continue
        x.append((tot[k] - v) / (cnt[k] - 1))
        y.append(v)
    return x, y


def split_half(rows, key, resid, min_n=8):
    """Chronological split-half of each group's mean residual.

    The bullpen-role gate this project already trusts is a split-half at
    r +0.55 to +0.78; per-club advancement FAILED the same gate at +0.11 to
    +0.38. Same test, same yardstick.
    """
    by = defaultdict(list)
    for r, v in zip(rows, resid):
        by[key(r)].append((r["date"], v))
    a, b = [], []
    for k, vals in by.items():
        if len(vals) < min_n * 2:
            continue
        vals.sort()
        h = len(vals) // 2
        a.append(st.mean(v for _, v in vals[:h]))
        b.append(st.mean(v for _, v in vals[h:]))
    return a, b


def park_index():
    try:
        from src.context.sources import park
        pf = park.park_factors() or {}
    except Exception:
        return {}
    out = {}
    for k, v in pf.items():
        if not str(k).startswith("id:"):
            continue
        try:
            out[int(str(k)[3:])] = float(v.get("runs"))
        except (TypeError, ValueError):
            continue
    return out


def rest_days(rows):
    """{index: days since that pitcher's previous start}, None for the first."""
    from datetime import date
    by = defaultdict(list)
    for i, r in enumerate(rows):
        by[r["player"]].append((r["date"], i))
    out = {}
    for _, seq in by.items():
        seq.sort()
        prev = None
        for d, i in seq:
            if prev is not None:
                y, m, dd = (int(x) for x in d.split("-"))
                py, pm, pdd = (int(x) for x in prev.split("-"))
                out[i] = (date(y, m, dd) - date(py, pm, pdd)).days
            prev = d
    return out


def variance_components(rows, key, stat, min_n=6):
    """MODEL-FREE lower bound on the real between-start variation.

    `ceiling.py` gets its 'implied true' by subtracting OUR simulated
    within-start variance from the actual variance, which is only as good as
    our spread being right — and a too-narrow within-start distribution
    would manufacture between-start signal that is not there. This does not
    touch the model at all: a one-way ANOVA on the ACTUAL values grouped by
    pitcher. Whatever variance sits BETWEEN pitchers is real start-to-start
    variation by construction, and it is a lower bound because opponent,
    park and rest all vary within a pitcher's own season too.

    The (MSB - MSW) / n0 estimator, not the raw spread of group means: with
    ~11 starts a pitcher's observed mean carries a full out of sampling
    noise and the raw spread would report most of it as talent.
    """
    by = defaultdict(list)
    for r in rows:
        by[key(r)].append(r[f"a_{stat}"])
    by = {k: v for k, v in by.items() if len(v) >= min_n}
    if len(by) < 3:
        return None
    n = sum(len(v) for v in by.values())
    k = len(by)
    grand = sum(sum(v) for v in by.values()) / n
    ssb = sum(len(v) * (st.mean(v) - grand) ** 2 for v in by.values())
    ssw = sum(sum((x - st.mean(v)) ** 2 for x in v) for v in by.values())
    msb, msw = ssb / (k - 1), ssw / (n - k)
    n0 = (n - sum(len(v) ** 2 for v in by.values()) / n) / (k - 1)
    return {"between": max((msb - msw) / n0, 0) ** 0.5,
            "within": msw ** 0.5, "groups": k, "n": n}


GROUPS = {
    "pitcher": lambda r: r["player"],
    "club (manager)": lambda r: r["team"],
    "venue": lambda r: r["venue_id"],
}
ALL_STATS = ("outs", "k", "h", "bb", "er")


def pen_workload():
    """{(date, team): relief outs thrown that day} — a taxed bullpen is the
    most-cited reason a manager leaves a starter in, and nothing in the
    simulator knows about yesterday."""
    from src import db
    q = """
    select g.date, p.team, sum(p.outs_recorded) o
    from mlb_pitching p join games g on g.game_id = p.game_id
    where g.sport = 'mlb' and g.status = 'Final'
      and coalesce(p.is_starter, 0) = 0
    group by g.date, p.team
    """
    with db.connect() as c:
        return {(r["date"], r["team"]): r["o"] for r in c.execute(q)}


def _prev(d, n):
    from datetime import date, timedelta
    y, m, dd = (int(x) for x in d.split("-"))
    return (date(y, m, dd) - timedelta(days=n)).isoformat()


def main():
    stat = sys.argv[1] if len(sys.argv) > 1 else "outs"
    rows = load()
    resid = [r[f"a_{stat}"] - r[f"m_{stat}"] for r in rows]
    print(f"  {len(rows)} starts, residual on {stat}: "
          f"mean {st.mean(resid):+.2f}, sd {st.pstdev(resid):.2f}\n")

    print("  MODEL-FREE VARIANCE COMPONENTS on the ACTUAL values"
          "  (ANOVA by pitcher)")
    print(f"  {'stat':<7}{'actual sd':>11}{'between sp':>12}"
          f"{'within sp':>11}{'our within':>12}{'our spread':>12}"
          f"{'floor ceil':>12}")
    for s in ALL_STATS:
        vc = variance_components(rows, lambda r: r["player"], s)
        if not vc:
            continue
        sa = st.pstdev([r[f"a_{s}"] for r in rows])
        ow = st.mean([r[f"w_{s}"] for r in rows]) ** 0.5
        osp = st.pstdev([r[f"m_{s}"] for r in rows])
        print(f"  {s:<7}{sa:>11.2f}{vc['between']:>12.2f}"
              f"{vc['within']:>11.2f}{ow:>12.2f}{osp:>12.2f}"
              f"{vc['between'] / sa:>12.3f}")
    print("  'between sp' is the sd of TRUE per-pitcher means, sampling"
          "\n  noise removed. It is a LOWER bound on real between-start"
          "\n  variation (opponent, park and rest vary inside a pitcher's"
          "\n  own season too). Compare 'within sp' to 'our within': if"
          "\n  ours is the larger, the simulator is over-dispersed per"
          "\n  start and every 'implied true' in ceiling.py is understated.")

    # Every stat at once, because that is what separates the two stories.
    # The pitcher's RATES are estimated over his whole season INCLUDING
    # these starts, so his per-PA outcomes are already right on average. A
    # per-pitcher residual that survives on OUTS but not on k/h/bb is
    # therefore a LEASH — how long he is left in — and not a rate error.
    print("  LEAVE-ONE-OUT GROUP SIGNAL, r (and sd of the residual it"
          " removes)")
    print(f"  {'group':<16}" + "".join(f"{s:>16}" for s in ALL_STATS))
    for name, fn in GROUPS.items():
        cells = []
        for s in ALL_STATS:
            res = [r[f"a_{s}"] - r[f"m_{s}"] for r in rows]
            x, y = loo_group(rows, fn, res)
            r, z = _corr(x, y)
            cells.append(f"{r:>+7.3f} {r * st.pstdev(y) if y else 0:>5.2f}"
                         f"{'*' if abs(z) > 3 else ' '}")
        print(f"  {name:<16}" + "".join(f"{c:>16}" for c in cells))
    print("  * = |z| > 3")

    print(f"\n  CHRONOLOGICAL SPLIT-HALF on {stat}"
          f"  (bullpen-role gate: +0.55..+0.78;"
          f" per-club advancement FAILED at +0.11..+0.38)")
    print(f"  {'group':<18}{'n':>7}{'r':>8}{'z':>8}")
    for name, fn in GROUPS.items():
        a, b = split_half(rows, fn, resid)
        r, z = _corr(a, b)
        print(f"  {name:<18}{len(a):>7}{r:>8.3f}{z:>8.1f}")

    print(f"\n  PER-START OBSERVABLES (correlation with the {stat} residual)")
    pk = park_index()
    rest = rest_days(rows)
    pen = pen_workload()
    feats = {
        "is_home": [(i, float(r["is_home"])) for i, r in enumerate(rows)],
        "night game": [(i, 1.0 if (r["day_night"] or "") == "night" else 0.0)
                       for i, r in enumerate(rows)
                       if r["day_night"] in ("day", "night")],
        "park runs idx": [(i, pk[r["venue_id"]]) for i, r in enumerate(rows)
                          if r["venue_id"] in pk],
        "days rest": [(i, float(rest[i])) for i in range(len(rows))
                      if rest.get(i) is not None and 3 <= rest[i] <= 7],
        "pen outs y'day": [(i, float(pen[(_prev(r["date"], 1), r["team"])]))
                           for i, r in enumerate(rows)
                           if (_prev(r["date"], 1), r["team"]) in pen],
        "pen outs last 2": [
            (i, float(pen[(_prev(r["date"], 1), r["team"])]
                      + pen[(_prev(r["date"], 2), r["team"])]))
            for i, r in enumerate(rows)
            if (_prev(r["date"], 1), r["team"]) in pen
            and (_prev(r["date"], 2), r["team"]) in pen],
        "opp K% (model)": [(i, r["m_k"]) for i, r in enumerate(rows)],
        "predicted outs": [(i, r["m_outs"]) for i, r in enumerate(rows)],
        "month": [(i, float(r["date"][5:7])) for i, r in enumerate(rows)],
    }
    print(f"  {'feature':<18}{'n':>7}{'r':>8}{'z':>8}{'outs gained':>13}")
    for name, pairs in feats.items():
        if len(pairs) < 30:
            print(f"  {name:<18}{len(pairs):>7}{'--':>8}")
            continue
        idx = [i for i, _ in pairs]
        x = [v for _, v in pairs]
        y = [resid[i] for i in idx]
        r, z = _corr(x, y)
        print(f"  {name:<18}{len(pairs):>7}{r:>8.3f}{z:>8.1f}"
              f"{abs(r) * st.pstdev(y):>13.2f}")

    print("\n  'outs gained' is |r| x residual sd: the sd of the part of the"
          "\n  residual this feature could remove. Against ~2.7 outs of real"
          "\n  between-start variation, anything under ~0.2 is not worth"
          "\n  building. 'opp K% (model)' and 'predicted outs' are CONTROLS:"
          "\n  they already feed the simulation, so a large value there means"
          "\n  the model is mis-USING what it already has.")


if __name__ == "__main__":
    main()
