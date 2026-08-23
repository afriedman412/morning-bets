"""First five innings: the game bet the starter model can actually price.

WHY F5 AND NOT THE FULL GAME. A full nine is roughly 40% bullpen, and the
bullpen is the component every signal this project tested came back dead on
— usage, core-reliever availability, four separate proxies, none clearing
z=1.4. The first five is the starters' half, and 75% of starts cover all of
it, so three-quarters of the time the removal decision never enters at all.

WHY THIS IS NOT THE OUTS TRAP. Outs measured no CLV edge (z=1.3 against K's
43.5) because outs ARE the hook — a manager decision the model reproduces
only in aggregate. F5 runs are the RATE model plus sequencing, which is the
regime where the measured edge lives. Different quantity, different half of
the model.

THE RELIEF INNINGS ARE NOT FREE. When a starter leaves before the fifth,
someone covers the rest, and a generic reliever is not a league-average
starter: relievers strike out more (0.2238 vs 0.2176 per batter faced) and
walk considerably more (0.0936 vs 0.0784). Modelling those innings with
starter rates would understate walks in exactly the games that already went
badly.

WHAT SETTLES THE BET. A team's F5 score is the runs it scored in five
innings, which is the runs ALLOWED by the other side's pitching. So the
away team's F5 total comes from the home starter, and vice versa — getting
that crossed is the obvious way to build this wrong.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from src import db
from src.context import sim

_RELIEF_Q = """
select sum(p.outs_recorded) o, sum(p.h) h, sum(p.bb) bb, sum(p.k) k,
       sum(p.hr) hr
from mlb_pitching p join games g on g.game_id = p.game_id
where g.sport = 'mlb' and g.status = 'Final' and p.is_starter = 0
"""

_RELIEF: sim.PitcherRates | None = None


def relief_rates(conn=None) -> sim.PitcherRates:
    """One generic reliever, from the whole relief population."""
    global _RELIEF
    if _RELIEF is not None:
        return _RELIEF

    def _run(c):
        return c.execute(_RELIEF_Q).fetchone()
    r = _run(conn) if conn is not None else _with(_run)
    bf = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
    bip = bf - (r["k"] or 0) - (r["bb"] or 0) - (r["hr"] or 0)
    _RELIEF = sim.PitcherRates(
        name="generic relief", pa=bf,
        k_pct=(r["k"] or 0) / bf,
        bb_pct=(r["bb"] or 0) / bf,
        hr_pct=(r["hr"] or 0) / bf,
        babip=(((r["h"] or 0) - (r["hr"] or 0)) / bip) if bip > 0 else 0.28,
    )
    return _RELIEF


def _with(fn):
    with db.connect() as c:
        return fn(c)


@dataclass
class F5Result:
    """One simulated first five. `away`/`home` are runs SCORED."""
    away: int = 0
    home: int = 0

    @property
    def total(self) -> int:
        return self.away + self.home

    @property
    def winner(self) -> str:
        return ("away" if self.away > self.home
                else "home" if self.home > self.away else "tie")


def _side_runs(starter, lineup, lg, hook, rng, park, relief):
    """Runs a pitching side allows through five, and the starter's line.

    Returns `(runs, StartResult)`. The result comes back so a caller can
    report how far the starter got WITHOUT re-simulating him — the F5 fit
    reports that share as a diagnostic and must not pay for it twice.
    """
    r = sim.simulate_start(starter, lineup, lg, hook, rng, park=park,
                           max_innings=5)
    # `runs_f5` already contains the men he stranded — sim.simulate_start
    # credits them to him, which is how earned runs actually work. Adding
    # them again here would double-count.
    runs = r.runs_f5
    left = 15 - r.outs_f5
    if left > 0:
        # Whoever finishes the fifth. Simulated as its own short outing with
        # a hook that will not pull him, because the question is only what
        # happens in the innings remaining, not who pitches them.
        rel = sim.simulate_start(
            relief, lineup, lg,
            sim.Hook(intercept=-99.0, mid_intercept=-99.0), rng,
            park=park, max_innings=(left + 2) // 3)
        # Scale to the outs actually needed — the relief sim rounds up to
        # whole innings and would otherwise credit runs from outs nobody
        # pitched.
        if rel.outs:
            runs += int(round(rel.runs * left / rel.outs))
    return runs, r


def simulate_f5(away_sp, away_lineup, home_sp, home_lineup, lg,
                away_hook=None, home_hook=None, n=10000, seed=0,
                away_park=None, home_park=None) -> list[F5Result]:
    """`n` simulated first-fives for one matchup.

    The AWAY starter's runs allowed become the HOME team's score. Crossing
    those is the obvious way to get this exactly backwards.
    """
    rng = random.Random(seed)
    relief = relief_rates()
    park = away_park or home_park or sim.NEUTRAL_PARK
    out = []
    for _ in range(n):
        home_scored, _ = _side_runs(away_sp, home_lineup, lg,
                                    away_hook or sim.Hook(), rng, park, relief)
        away_scored, _ = _side_runs(home_sp, away_lineup, lg,
                                    home_hook or sim.Hook(), rng, park, relief)
        out.append(F5Result(away=away_scored, home=home_scored))
    return out


def prob_total_over(res: list[F5Result], line: float) -> float:
    return sum(1 for r in res if r.total > line) / len(res) if res else 0.0


def prob_winner(res: list[F5Result]) -> dict:
    n = len(res) or 1
    c = {"away": 0, "home": 0, "tie": 0}
    for r in res:
        c[r.winner] += 1
    return {k: v / n for k, v in c.items()}


if __name__ == "__main__":
    from src.context import calibrate as cal
    lg = sim.league()
    print("generic reliever:", relief_rates())
    cases = cal.build_cases()[:2]
    (s1, p1, l1), (s2, p2, l2) = cases[0], cases[1]
    res = simulate_f5(p1, l1, p2, l2, lg, n=4000)
    tot = [r.total for r in res]
    print(f"\n{p1.name} vs {p2.name} (illustrative, lineups not matched)")
    print(f"  F5 total mean {sum(tot)/len(tot):.2f}")
    for ln in (3.5, 4.5, 5.5):
        print(f"    over {ln}: {prob_total_over(res, ln):.3f}")
    print(f"  winner {prob_winner(res)}")
