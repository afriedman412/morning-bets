"""WHO are we wrong about — and is being wrong about them REPEATABLE?

    venv/bin/python -m scratchpad.whos_wrong

TWO DIFFERENT QUESTIONS, and this project has only ever asked the first.

  BIAS       is the model consistently high or low on this pitcher? That is
             the per-pitcher leash / patience territory, already fitted.
  DISPERSION is the model consistently MORE WRONG about him, in either
             direction? Nobody has asked. It is also exactly the open lead:
             measured 2026-08-27, the model is under-dispersed, and a FLAT
             dispersion term closed the shape and the level but was neutral
             on CRPS because it added the same spread to everyone. A
             dispersion that VARIES by something real moves discrimination
             too, and "which pitcher" is the first candidate.

THE ONLY THING THAT MATTERS IS WHETHER IT REPEATS. Any split of any data
produces pitchers with big residuals; the question is whether the SAME ones
are big next time. So everything here is split-half — odd-numbered starts
against even-numbered ones, Spearman-Brown corrected to full length — and a
raw spread with no reliability behind it is noise wearing a name.

SCORED ON EARNED RUNS, not strikeouts. Strikeouts are the channel this
project is already at the market's level on, and outs are the hook. Runs are
what settles.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict


def corr(xs, ys):
    n = len(xs)
    if n < 10:
        return 0.0, 0
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if not sx or not sy:
        return 0.0, n
    r = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (n * sx * sy)
    return r, n


def sb(r):
    """Spearman-Brown: a half-length correlation to full length."""
    return 2 * r / (1 + r) if r > -1 else 0.0


def split_half(groups, fn, min_n=8):
    """Correlate `fn` over odd starts against even starts, per group."""
    a, b = [], []
    for _key, rows in groups.items():
        odd = [r for i, r in enumerate(rows) if i % 2]
        even = [r for i, r in enumerate(rows) if not i % 2]
        if len(odd) < min_n or len(even) < min_n:
            continue
        a.append(fn(odd))
        b.append(fn(even))
    r, n = corr(a, b)
    return r, sb(r), n


def main(argv):
    rows = [r for r in json.load(open("scratchpad/ceiling_rows.json"))
            if not r.get("_team_row") and r.get("m_er") is not None]
    for r in rows:
        r["_res"] = r["a_er"] - r["m_er"]
    rows.sort(key=lambda r: (r["player"], r["date"]))

    by_pit = defaultdict(list)
    for r in rows:
        by_pit[r["player"]].append(r)
    by_team = defaultdict(list)
    for r in rows:
        by_team[r["team"]].append(r)

    print(f"  {len(rows):,} starts, {len(by_pit):,} pitchers,"
          f" {len(by_team):,} clubs\n")

    metrics = (
        ("BIAS  mean residual", lambda rs: st.mean(x["_res"] for x in rs)),
        ("DISP  mean |resid|", lambda rs: st.mean(abs(x["_res"]) for x in rs)),
        ("DISP  sd of resid", lambda rs: st.pstdev([x["_res"] for x in rs])),
    )
    print(f"  {'population':<10}{'metric':<22}{'n':>5}{'half r':>9}"
          f"{'full r':>9}")
    for label, groups, min_n in (("pitcher", by_pit, 8),
                                 ("club", by_team, 25)):
        for name, fn in metrics:
            r, full, n = split_half(groups, fn, min_n)
            print(f"  {label:<10}{name:<22}{n:>5}{r:>+9.3f}{full:>+9.3f}")

    # SIZE IT. A reliable spread still has to be big enough to matter: the
    # leverage floor is ~0.05 runs and half of today's candidates died there.
    print()
    for label, groups, min_n in (("pitcher", by_pit, 8),
                                 ("club", by_team, 25)):
        vals = [st.mean(abs(x["_res"]) for x in rs)
                for rs in groups.values() if len(rs) >= min_n * 2]
        bias = [st.mean(x["_res"] for x in rs)
                for rs in groups.values() if len(rs) >= min_n * 2]
        if len(vals) < 5:
            continue
        vs = sorted(vals)
        print(f"  {label}: mean |resid| spread over {len(vals)} — "
              f"sd {st.pstdev(vals):.3f}, p10 {vs[len(vs) // 10]:.3f}, "
              f"p90 {vs[-len(vs) // 10]:.3f}")
        print(f"  {label}: bias spread — sd {st.pstdev(bias):.3f}")

    print("\n  `full r` is the reliability of the per-pitcher number. Only a")
    print("  RELIABLE dispersion is worth wiring: an unreliable one shrinks")
    print("  to the league mean, which is the flat term already measured")
    print("  neutral. Bias is the leash's territory and is already fitted.")


if __name__ == "__main__":
    main(sys.argv[1:])
