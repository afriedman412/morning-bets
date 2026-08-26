"""What season a query means when nobody says.

WHY THIS EXISTS. Every season-sensitive query in the context layer took
`season: int | None = None`, and None meant NO FILTER — every row in the
database. That was harmless while the database held exactly one season, and
48 of the 52 call sites relied on it.

The moment 2025 is loaded it stops being harmless and starts being SILENT.
A pitcher's K% would pool two seasons, the league baselines would pool two
different balls, and the leash would measure a manager across a winter of
roster turnover. Nothing would raise; every number would just move, and
there would be no way afterwards to tell a pooling bug from a real
year-over-year effect.

So the default changes from "everything" to "this season" BEFORE the load,
while the two are provably identical. `scratchpad/scope_baseline.py`
captures the digests that prove it.

WHAT IS SEASON-SCOPED AND WHAT IS NOT, which is the distinction that
matters and is not "seasons are independent" flatly:

  SCOPED — anything indexed by a PLAYER. Rates, the leash, lineups, park
  exposure, league baselines. A pitcher is not the same pitcher across a
  winter (deGrom's command is the case on record here), and the ball itself
  changes between seasons.

  POOLED — anything indexed by LEAGUE BEHAVIOUR. The removal curves,
  advancement, inherited runners, relief-outing length, times through the
  order. These are regularities of how the game is managed rather than
  properties of a man, and they are where a second season actually pays:
  38,485 boundary decisions becomes about 85,000.

Pooling is not automatic even there. `advance.py`'s per-club stability gate
is the precedent — check that the two seasons agree before combining them,
and treat disagreement as a finding rather than a nuisance. If managers pull
starters faster in 2026 than they did in 2025, that is worth knowing.

CROSSING SEASONS FOR A PLAYER IS A DECISION, NOT A DEFAULT. Pass
`season=None` explicitly to mean "every season on record" — career workload
is the legitimate case. It now says so at the call site.
"""
from __future__ import annotations

#: The season every unqualified query means. A plain int, not derived from
#: today's date: a March run and an October run of the same backtest must
#: agree, and `date.today().year` would quietly disagree across a new year.
CURRENT_SEASON = 2026

#: Sentinel for "every season on record", so a caller can ask for pooled
#: history without it being indistinguishable from forgetting to pass one.
ALL_SEASONS = "all"


def resolve(season) -> int | None:
    """Turn a caller's `season` argument into a filter value.

    None  -> CURRENT_SEASON   (the default, and the behaviour change)
    'all' -> None             (no filter; pool every season, deliberately)
    int   -> itself
    """
    if season is None:
        return CURRENT_SEASON
    if season == ALL_SEASONS:
        return None
    return season
