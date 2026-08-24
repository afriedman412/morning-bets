"""How bullpens are ACTUALLY used. Measurement, before any modelling.

WHY THIS COMES FIRST. `game.build_side` samples eight arms weighted by
season appearances and then uses them in sample order, one inning each,
regardless of the score. So the closer can pitch the sixth of a blowout and
the mop-up man the ninth of a one-run game. That is obviously not how a
bullpen works, but "obviously wrong" is not a number, and the notes are
explicit that every imported baseball effect this project has tried
measured zero. Before replacing random deployment with role-based
deployment, the thing to establish is that ROLE IS REAL AND PREDICTABLE
FROM PRIOR GAMES — otherwise the replacement is a more expensive way to
draw from the same distribution.

THREE QUESTIONS, IN ORDER.

  1. IS ROLE STABLE? Split each reliever's season in half chronologically
     and correlate the halves. A role that does not survive its own season
     cannot be projected into tomorrow's game.
  2. DOES THE SCORE SELECT THE ARM? If close games get better pitchers, the
     current model destroys a real correlation, and that correlation is
     what shapes the tails of the run distribution.
  3. HOW BIG IS IT? In runs, not in adjectives. This decides whether the
     bullpen model is worth building at all.

The split-half in (1) is deliberately not a within-game measure. What the
simulator needs is a rate it can compute the MORNING OF, from games already
played, so the test has to be first-half-predicts-second-half rather than
anything that reads the game being simulated.

    venv/bin/python -m src.context.deploy
"""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict

from src.context import sim, store
from src.context.sources import rates as rate_src

#: A reliever needs this many outings before a split-half correlation says
#: anything. Six a half is already thin; below it the halves are mostly
#: sampling noise and the correlation measures the threshold, not the role.
MIN_OUTINGS = 12

#: Innings where a manager has a choice worth measuring. Earlier than this
#: and he is covering for a starter who did not last, which is a different
#: decision.
LATE = 7

_Q = """
select s.date, s.team, s.player_name name, s.appearance_order ord,
       s.entry_inning inning, s.entry_outs outs, s.entry_margin margin,
       s.on_1b, s.on_2b, s.on_3b,
       s.batters, s.outs_recorded, s.runs, s.last_inning
from mlb_stints s
where s.appearance_order > 0
order by s.date, s.game_id, s.appearance_order
"""


def outings(conn=None) -> list[dict]:
    def _run(c):
        return [dict(r) for r in c.execute(_Q)]
    if conn is not None:
        return _run(conn)
    with store.connect(attach=False) as c:
        return _run(c)


def leverage(o: dict) -> bool:
    """A late inning with the game in the balance — the closer's job."""
    return o["inning"] >= LATE and abs(o["margin"]) <= 3


def split_half(rows: list[dict], key) -> tuple:
    """(r, n) between each pitcher's first and second half on `key`.

    `rows` must arrive in CHRONOLOGICAL order — the query supplies it — or
    this answers an easier question than the one being asked. Note that
    swapping the two halves changes nothing: Pearson correlation is
    symmetric, so "the first half predicts the second" and its reverse are
    the same number. The direction lives in the ordering, not the formula.
    """
    by = defaultdict(list)
    for o in rows:
        by[(o["team"], o["name"])].append(o)
    xs, ys = [], []
    for outs in by.values():
        if len(outs) < MIN_OUTINGS:
            continue
        h = len(outs) // 2
        xs.append(st.mean(key(o) for o in outs[:h]))
        ys.append(st.mean(key(o) for o in outs[h:]))
    if len(xs) < 3:
        return None, len(xs)
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if sx == 0 or sy == 0:
        return None, len(xs)
    r = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) * sx * sy)
    return r, len(xs)


def quality(conn=None) -> dict:
    """{(team, name): k_minus_bb} from the same rates the simulator uses."""
    lg = sim.league()
    out = {}
    for team, arms in rate_src.bullpens(lg, conn=conn).items():
        for a in arms:
            out[(team, a["name"])] = a["k_pct"] - a["bb_pct"]
    return out


def report(rows: list[dict], q: dict) -> None:
    rel = rows
    print(f"\n{len(rel):,} relief outings\n")

    print("  LENGTH — the model gives every arm exactly one inning")
    n3 = sum(1 for o in rel if o["outs_recorded"] == 3)
    mid = sum(1 for o in rel if o["outs"] > 0 or o["on_1b"] or o["on_2b"]
              or o["on_3b"])
    multi = sum(1 for o in rel if o["outs_recorded"] > 3)
    print(f"    mean outs            "
          f"{st.mean(o['outs_recorded'] for o in rel):.2f}   (model: 3.00)")
    print(f"    exactly three        {n3 / len(rel):.1%}")
    print(f"    more than three      {multi / len(rel):.1%}")
    print(f"    entered mid-inning   {mid / len(rel):.1%}   (model: never)\n")

    print("  IS ROLE STABLE? first half of a season vs second, per pitcher")
    for lbl, key in (("entry inning", lambda o: o["inning"]),
                     ("entry margin", lambda o: o["margin"]),
                     ("|margin|", lambda o: abs(o["margin"])),
                     ("high-leverage share", lambda o: float(leverage(o))),
                     ("outs recorded", lambda o: o["outs_recorded"])):
        r, n = split_half(rel, key)
        got = "too few" if r is None else f"r {r:+.3f}"
        print(f"    {lbl:<22}{got:>10}   n={n} pitchers")
    print()

    late = [o for o in rel if o["inning"] >= LATE and (o["team"], o["name"])
            in q]
    print(f"  DOES THE SCORE SELECT THE ARM? innings {LATE}+, n={len(late)}")
    print(f"    {'entry margin':<16}{'n':>6}{'K-BB% of the arm used':>24}"
          f"{'runs/BF':>10}")
    for lo, hi, lbl in ((-99, -4, "trailing 4+"), (-3, -1, "trailing 1-3"),
                        (0, 0, "tied"), (1, 3, "leading 1-3"),
                        (4, 99, "leading 4+")):
        g = [o for o in late if lo <= o["margin"] <= hi]
        if not g:
            continue
        kbb = st.mean(q[(o["team"], o["name"])] for o in g)
        bf = sum(o["batters"] for o in g)
        print(f"    {lbl:<16}{len(g):>6}{kbb:>24.3f}"
              f"{sum(o['runs'] for o in g) / max(bf, 1):>10.3f}")

    close = [o for o in late if abs(o["margin"]) <= 2]
    blow = [o for o in late if abs(o["margin"]) >= 5]
    if close and blow:
        a = st.mean(q[(o["team"], o["name"])] for o in close)
        b = st.mean(q[(o["team"], o["name"])] for o in blow)
        sd = st.pstdev([q[k] for k in q]) or 1e-9
        print(f"\n    close (<=2) {a:.3f} vs blowout (>=5) {b:.3f}"
              f"   gap {a - b:+.3f} K-BB%, {(a - b) / sd:.2f} SD of the"
              f" reliever pool")
        print("    The model draws from that pool at random, so it prices"
              " every\n    late inning as the AVERAGE arm — too good in a"
              " blowout, too bad\n    in a one-run game, and wrong in both"
              " tails at once.")


if __name__ == "__main__":
    rows = outings()
    if not rows:
        print("no stints — run `... sources.pbp --backfill --sync` first")
        sys.exit(0)
    report(rows, quality())
