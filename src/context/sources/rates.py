"""Per-player rates for the simulator, from the local boxscore cache.

Zero network. Every number here comes from `mlb_batting` / `mlb_pitching`,
which the grading pass already populates, so a slate can be simulated with
no connection and no API key.

WHY SHRINKAGE IS NOT OPTIONAL HERE. A reliever with 40 batters faced and
zero home runs allowed has an observed HR rate of 0.000, and handing that to
the simulator produces a pitcher who cannot give up a homer. The same
problem in miniature is what made the old estimator useless — a raw rate off
a small sample is not an estimate, it is an anecdote. Each rate is pulled
toward the league by a stabilisation constant: the approximate sample size
at which that statistic starts to describe the player rather than the
season.

The constants are approximations from the public literature, not fitted
here. They are in the right order of magnitude and the right ORDER —
strikeout rate stabilises fastest, home-run rate slowest, which is why a
half-season HR rate should be trusted far less than a half-season K rate.
Refitting them against this database is a real piece of work and is
deliberately not pretended at.
"""
from __future__ import annotations

from src import db

#: Plate appearances at which each rate is worth half its own weight
#: against the league. Higher means slower to trust.
STABILISE = {
    "k_pct": 70,
    "bb_pct": 170,
    "hr_pct": 350,
    "babip": 500,
}


def _shrink(observed: float | None, lg: float, n: float, stat: str) -> float:
    """Weighted average of the player's rate and the league's."""
    if observed is None or n <= 0:
        return lg
    k = STABILISE.get(stat, 200)
    w = n / (n + k)
    return w * observed + (1 - w) * lg


_PITCHER_Q = """
select p.player_name name,
       sum(p.outs_recorded) o, sum(p.h) h, sum(p.bb) bb,
       sum(p.k) k, sum(p.hr) hr, count(*) apps
from mlb_pitching p join games g on g.game_id = p.game_id
where g.sport = 'mlb' and g.status = 'Final' {where}
group by p.player_name
"""

_BATTER_Q = """
select mb.player_name name,
       sum(mb.ab) ab, sum(mb.bb) bb, sum(mb.h) h, sum(mb.so) so,
       sum(mb.hr) hr, count(*) games
from mlb_batting mb join games g on g.game_id = mb.game_id
where g.sport = 'mlb' and g.status = 'Final' {where}
group by mb.player_name
"""


def _where(season: int | None, before: str | None) -> str:
    bits = []
    if season:
        bits.append(f"and g.date like '{season}%'")
    if before:
        # Strictly before, so a brief never sees the game being bet on.
        bits.append(f"and g.date < '{before}'")
    return " ".join(bits)


def pitcher_rates(
    lg: dict, season: int | None = None, before: str | None = None,
    conn=None,
) -> dict[str, dict]:
    """{player_name: rates} for every pitcher with a line on record.

    Batters faced is approximated as outs + hits + walks. The cache carries
    no HBP and no reached-on-error, so this runs a couple of percent light —
    the same direction and roughly the same magnitude as the league
    denominator in `sim.league`, so the ratio the model actually consumes is
    close to unaffected.
    """
    def _run(c):
        return c.execute(
            _PITCHER_Q.format(where=_where(season, before))).fetchall()

    rows = _run(conn) if conn is not None else _with(_run)
    out = {}
    for r in rows:
        bf = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
        if bf < 1:
            continue
        bip = bf - (r["k"] or 0) - (r["bb"] or 0) - (r["hr"] or 0)
        out[r["name"]] = {
            "name": r["name"],
            "pa": bf,
            "apps": r["apps"],
            "k_pct": _shrink((r["k"] or 0) / bf, lg["k_pct"], bf, "k_pct"),
            "bb_pct": _shrink((r["bb"] or 0) / bf, lg["bb_pct"], bf,
                              "bb_pct"),
            "hr_pct": _shrink((r["hr"] or 0) / bf, lg["hr_pct"], bf,
                              "hr_pct"),
            "babip": _shrink(
                (((r["h"] or 0) - (r["hr"] or 0)) / bip) if bip > 0 else None,
                lg["babip"], max(bip, 0), "babip"),
            "raw_k_pct": (r["k"] or 0) / bf,
        }
    return out


def batter_rates(
    lg: dict, season: int | None = None, before: str | None = None,
    conn=None,
) -> dict[str, dict]:
    """{player_name: rates} for every hitter with a line on record."""
    def _run(c):
        return c.execute(
            _BATTER_Q.format(where=_where(season, before))).fetchall()

    rows = _run(conn) if conn is not None else _with(_run)
    out = {}
    for r in rows:
        pa = (r["ab"] or 0) + (r["bb"] or 0)
        if pa < 1:
            continue
        bip = (r["ab"] or 0) - (r["so"] or 0) - (r["hr"] or 0)
        out[r["name"]] = {
            "name": r["name"],
            "pa": pa,
            "games": r["games"],
            "k_pct": _shrink((r["so"] or 0) / pa, lg["k_pct"], pa, "k_pct"),
            "bb_pct": _shrink((r["bb"] or 0) / pa, lg["bb_pct"], pa,
                              "bb_pct"),
            "hr_pct": _shrink((r["hr"] or 0) / pa, lg["hr_pct"], pa,
                              "hr_pct"),
            "babip": _shrink(
                (((r["h"] or 0) - (r["hr"] or 0)) / bip) if bip > 0 else None,
                lg["babip"], max(bip, 0), "babip"),
        }
    return out


def _with(fn):
    with db.connect() as c:
        return fn(c)


if __name__ == "__main__":
    from src.context import sim
    lg = sim.league()
    pr = pitcher_rates(lg)
    br = batter_rates(lg)
    print(f"league  K% {lg['k_pct']:.1%}  BB% {lg['bb_pct']:.1%}  "
          f"HR% {lg['hr_pct']:.1%}  BABIP {lg['babip']:.3f}")
    print(f"{len(pr)} pitchers, {len(br)} batters\n")
    print("highest K% pitchers (min 200 BF), shrunk vs raw:")
    top = sorted((v for v in pr.values() if v["pa"] >= 200),
                 key=lambda v: -v["k_pct"])[:8]
    for v in top:
        print(f"  {v['name'][:22]:<24}{v['k_pct']:>7.1%}  raw "
              f"{v['raw_k_pct']:>6.1%}  BF {v['pa']:>4}")
    print("\nshrinkage working on thin samples:")
    thin = sorted((v for v in pr.values() if v["pa"] < 30),
                  key=lambda v: -v["pa"])[:5]
    for v in thin:
        print(f"  {v['name'][:22]:<24}{v['k_pct']:>7.1%}  raw "
              f"{v['raw_k_pct']:>6.1%}  BF {v['pa']:>4}")
