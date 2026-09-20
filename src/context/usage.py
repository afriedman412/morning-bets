"""Recent workload -> tonight's hook. Item 36.

    venv/bin/python -m src.context.usage            coverage + today's gaps

THE FINDING (2026-09-19, four sittings, NOTES same date): the engine
prices outs off season-long inputs and never looks at recent pitch
counts, and the miss is linear in the gap between the two — confirmed
by the registered `outs_bias_usage_*` battery rows at z +4.7 pooled
(hi-lo separation +1.29 outs, 4/4 folds, homogeneous). The coefficient
was COUNTED pre-holdout (folds 2023-25 only, CR0 by arm, 5,568 starts):

    +0.0571 (0.0103) outs per pitch of gap, z +5.5, chi-sq 0.62 on 2 df

and every registered form check came back simple: linear to both tails
(no clamp), symmetric (one coefficient, sides 1.3 se apart), and it
survives within-arm demeaning (+0.0357 z +3.2) — start-to-start state,
not a per-arm trait, so it stacks on the leash rather than repeating
it. This is the graded Leahy defect: the 120-day gate priced him at
14.1 outs while his last three starts said 9; `plans.py` was the
manual patch, this is the automatic one.

WHAT SHIPS: `gap_for(name, date)` — the starter's last-4 mean pitch
count minus his season-to-date mean, STRICTLY PRIOR same-season starts
only (velo's leak-free lookup shape: a replay of July is priced off
June, a backtest cannot see its own game). Fewer than 4 prior starts,
an unknown name, a missing date, or an AMBIGUOUS name (two pitcher ids
sharing one name — the Sandlin trap) return exactly 0.0: silent-
neutral, never a guess. `game.build_side` converts through
`leash.offset_for` (the measured outs -> log-odds table) onto the
per-start hook, STARTER ONLY — measured on starters, and "measured on
starters, applied to every arm" is the recorded error pattern.
"""
from __future__ import annotations

import statistics as st
from collections import defaultdict

from src.context import store

#: Counted 2026-09-19 on folds 2023-25 (pre-HOLDOUT by construction:
#: every date in those folds precedes 2026-07-01), z +5.5. Outs of
#: engine under-call per pitch of last-4-vs-season gap.
USAGE_OUTS_PER_PITCH = 0.0571
#: The window and the floor, matching the battery's `_usage_gap` and
#: the counted regressor exactly. NOTE the floor is documentation more
#: than behaviour: with WINDOW == MIN_PRIOR, any arm at or under the
#: floor has a window equal to his season and a gap of exactly zero by
#: arithmetic. The guard states the contract and protects it if either
#: constant ever moves independently; it is not separately mutation-
#: killable and the tests do not claim it is.
WINDOW = 4
MIN_PRIOR = 4

_INDEX: dict | None = None      # {name: [(date, pitches), ...] sorted}
_AMBIG: set | None = None       # names carried by more than one id


def _reset() -> None:
    """Drop the cache so a backfill is picked up in-process."""
    global _INDEX, _AMBIG
    _INDEX = None
    _AMBIG = None


def _load() -> None:
    global _INDEX, _AMBIG
    by_id: dict = defaultdict(list)
    with store.connect() as con:
        rows = con.execute("""
            SELECT s.pitcher_id, s.player_name, s.date, p.pitches
            FROM mlb_stints s
            JOIN bets.mlb_pitching p
              ON p.game_id = s.game_id AND p.player_name = s.player_name
            WHERE s.appearance_order = 0
              AND p.is_starter = 1
              AND p.pitches IS NOT NULL AND p.pitches > 0
            ORDER BY s.date, s.game_id
        """).fetchall()
    ids_of: dict = defaultdict(set)
    for r in rows:
        ids_of[r["player_name"]].add(r["pitcher_id"])
        by_id[r["player_name"]].append((r["date"], float(r["pitches"])))
    _AMBIG = {nm for nm, ids in ids_of.items() if len(ids) > 1}
    _INDEX = dict(by_id)


def gap_for(name: str | None, date: str | None) -> float:
    """Last-4 mean minus season-to-date mean pitches, strictly prior.

    0.0 when unknown — thin history, unknown name, missing date, or an
    ambiguous name — which is the missing-group rule everywhere here.
    """
    if not name or not date:
        return 0.0
    if _INDEX is None:
        _load()
    if name in _AMBIG:
        return 0.0
    season = date[:4]
    prior = [p for d, p in _INDEX.get(name, ())
             if d < date and d[:4] == season]
    if len(prior) < MIN_PRIOR:
        return 0.0
    return st.mean(prior[-WINDOW:]) - st.mean(prior)


def main() -> None:
    if _INDEX is None:
        _load()
    import datetime
    today = datetime.date.today().isoformat()
    n_starts = sum(len(v) for v in _INDEX.values())
    print(f"  {len(_INDEX)} starters, {n_starts:,} starts with pitch "
          f"counts, {len(_AMBIG)} ambiguous names excluded: "
          f"{sorted(_AMBIG) or 'none'}")
    gaps = [(gap_for(nm, today), nm) for nm in _INDEX]
    gaps = [(g, nm) for g, nm in gaps if g]
    gaps.sort()
    print(f"  {len(gaps)} arms with a live gap today; extremes:")
    for g, nm in gaps[:5] + gaps[-5:]:
        print(f"    {nm:<28} {g:+7.1f} pitches "
              f"({USAGE_OUTS_PER_PITCH * g:+.2f} outs)")


if __name__ == "__main__":
    main()
