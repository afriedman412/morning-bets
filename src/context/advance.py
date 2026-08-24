"""What runners actually do, measured on THIS league instead of imported.

WHY. `sim._advance` keys its advancement rates by out count, which is the
mechanism that moved runs per baserunner from -4.2% to -0.2% — the single
largest correction the run model has had. But the NUMBERS in those tables
are published league references, deliberately not fitted, because fitting
them against runs is exactly how they would absorb every other defect in
the model. The docstring says so.

Measuring is not fitting. These are countable events on 2,006 games of
play-by-play now sitting on disk: how often a runner on first reaches third
on a single, how often a runner on second scores, how often anybody moves on
a ball in play. Replacing a published constant with the same quantity
counted on this season's data is not tuning against the settlement value —
it is the same mechanism with a better-sourced number, and it is checkable
against the reference rather than against runs.

WHAT THIS IS NOT. It is not a search. There is no loss function here and no
grid. If a measured rate lands far from the published one, that is a fact to
look at — usually a definition mismatch — and not a licence to move the
constant until the run total improves.

TWO ASSUMPTIONS ARE CHECKED, NOT MEASURED. The model asserts that a runner
on third always scores on a single and that runners on second and third both
always score on a double. Those are stated as certainties in code, so the
measurement's job is to report how far from 1.000 they really are.

    venv/bin/python -m src.context.advance
"""
from __future__ import annotations

import sys
from collections import Counter

from src.context import sim
from src.context.sources import pbp

#: How statsapi's `result.eventType` maps onto the simulator's outcomes.
#: The simulator has a separate SAC outcome that advances runners for free,
#: so a sacrifice must NOT be pooled with an ordinary ball-in-play out — the
#: whole point of laying one down is that it moves people.
HIT = {"single": sim.B1, "double": sim.B2, "triple": sim.B3,
       "home_run": sim.HR}
SAC = {"sac_fly", "sac_bunt", "sac_fly_double_play", "sac_bunt_double_play"}
DP = {"grounded_into_double_play", "double_play", "triple_play"}
OUT = {"field_out", "force_out", "fielders_choice_out", "fielders_choice",
       "other_out"}
K = {"strikeout", "strikeout_double_play"}


def _ends(play) -> dict:
    """{starting base: where he ended} for this play. 'out' for an out."""
    final, order = pbp.resolve(play.get("runners") or [])
    out = {}
    for rid in order:
        start, end, is_out = final[rid]
        if start in pbp._BASES:
            out[start] = "out" if is_out else end
    return out


def _adv(end, base: str) -> bool:
    """Did a runner who started on `base` move up at all?"""
    if end in (None, "out"):
        return False
    if end == "score":
        return True
    return pbp._BASES.index(end) > pbp._BASES.index(base)


#: Plays that are not a plate appearance — a steal, a pickoff, a wild
#: pitch. They belong in the base-state reconstruction and in NO rate's
#: denominator.
#: `field_error` is NOT in here — the batter reached, so it is a plate
#: appearance and belongs in the opportunity count.
NOT_A_PA = ("caught_", "pickoff", "stolen", "wild_pitch", "passed_ball",
            "balk", "other_advance", "defensive_indiff")


def count_play(c: Counter, play: dict, bases: tuple, outs: int,
               p: str = "") -> None:
    """Tally one play into `c`, given the state it started from.

    `p` prefixes every key, so the same counting code can fill a league
    table and a per-club one in the same pass. The alternative — a second
    function that drifts from this one — is how two measurements end up
    disagreeing about what they measured.
    """
    ev = ((play.get("result") or {}).get("eventType") or "")
    on1, on2, on3 = bases
    ends = _ends(play)
    c[f"{p}ev:{ev}"] += 1
    c[f"{p}plays"] += 1

    if ev == "single":
        if on3:
            c[f"{p}third_on_1b/{outs}"] += 1
            c[f"{p}third_on_1b_scored/{outs}"] += ends.get("3B") == "score"
        if on2:
            c[f"{p}second_on_1b/{outs}"] += 1
            c[f"{p}second_on_1b_scored/{outs}"] += ends.get("2B") == "score"
        # The model consults FIRST_TO_THIRD_ON_1B only when third is free
        # once the lead runners have resolved — a runner held at third
        # blocks it — so the measurement is conditioned the same way or it
        # is answering a different question. A runner already ON third does
        # NOT block, because the model scores him unconditionally first.
        if on1 and ends.get("2B") in (None, "score", "out"):
            c[f"{p}first_on_1b/{outs}"] += 1
            c[f"{p}first_to_third/{outs}"] += ends.get("1B") == "3B"
            c[f"{p}first_scores_on_1b/{outs}"] += ends.get("1B") == "score"
    elif ev == "double":
        if on1:
            c[f"{p}first_on_2b/{outs}"] += 1
            c[f"{p}first_scores_on_2b/{outs}"] += ends.get("1B") == "score"
        for b in ("2B", "3B"):
            if bases[pbp._BASES.index(b)]:
                c[f"{p}lead_on_2b/{b}"] += 1
                c[f"{p}lead_scores_on_2b/{b}"] += ends.get(b) == "score"
    elif ev in OUT and outs < 2 and any(bases):
        c[f"{p}out_with_runners/{outs}"] += 1
        c[f"{p}any_advance_on_out/{outs}"] += any(
            _adv(ends.get(b), b)
            for b in pbp._BASES if bases[pbp._BASES.index(b)])
        for b in pbp._BASES:
            if bases[pbp._BASES.index(b)]:
                c[f"{p}on_{b}_out/{outs}"] += 1
                c[f"{p}on_{b}_advanced/{outs}"] += _adv(ends.get(b), b)
        # WITH THE BASE AHEAD ALREADY EMPTY — the rate a lead-runner-first
        # model actually needs. The marginal above pools in the trailing
        # runners who could not move because someone was standing there,
        # which makes it the wrong number to hand to a simulator that
        # checks occupancy itself. Nobody can pass anybody, so a rate
        # measured without that condition and applied with it double-counts
        # the blocking.
        if on1 and not on2:
            c[f"{p}free_1B_out/{outs}"] += 1
            c[f"{p}free_1B_advanced/{outs}"] += _adv(ends.get("1B"), "1B")
        if on2 and not on3:
            c[f"{p}free_2B_out/{outs}"] += 1
            c[f"{p}free_2B_advanced/{outs}"] += _adv(ends.get("2B"), "2B")
        if on3:
            c[f"{p}free_3B_out/{outs}"] += 1
            c[f"{p}free_3B_advanced/{outs}"] += ends.get("3B") == "score"

    # TWO DENOMINATORS, because the published number and the model do not
    # share one. `GIDP%` as normally quoted is double plays per
    # OPPORTUNITY — every plate appearance with a man on first and fewer
    # than two out. The simulator rolls its constant only once a ball in
    # play has already become an out, which is about half as many chances.
    if on1 and outs < 2:
        if ev in DP:
            c[f"{p}dp_chance/{outs}"] += 1
        if ev in OUT | DP:
            c[f"{p}dp_denom/{outs}"] += 1
        if ev and not ev.startswith(NOT_A_PA):
            c[f"{p}dp_pa/{outs}"] += 1


def batting_team(pair: tuple, is_top: bool) -> str | None:
    """Whose runners are on the bases, given (away, home) and the half.

    Top of the inning means the AWAY club is batting, so the runners
    advancing are the away club's. Backwards, this measures every club's
    OPPONENTS' baserunning and still produces a table that looks entirely
    reasonable — which is why it is a named function with a check rather
    than a ternary buried in a loop.
    """
    if not pair:
        return None
    return pair[0] if is_top else pair[1]


def tally(limit: int | None = None, verbose: bool = True,
          by_team: bool = False) -> dict:
    """League counters, and optionally per-club ones in the same pass.

    Per-club keys are prefixed `TEAM|` and `TEAM.H|` where H is 0 for the
    first half of that club's season and 1 for the second — the split-half
    stability gate needs the halves counted, not recomputed.

    THE RUNNING TEAM IS THE BATTING TEAM. Top of the inning means the away
    club is up, so the runners advancing belong to the away club. Getting
    this backwards would measure each club's OPPONENTS' baserunning and
    still produce a plausible-looking table.
    """
    c: Counter = Counter()
    files = sorted(pbp.CACHE.glob("*.json.gz"))
    if limit:
        files = files[-limit:]
    teams, order = _game_teams() if by_team else ({}, {})
    for i, f in enumerate(files):
        gid = f"mlb-{f.name.split('.')[0]}"
        pair = teams.get(gid)
        for play, bases, outs, _a, _h in pbp.plays(gid):
            count_play(c, play, bases, outs)
            if pair:
                ab = play.get("about") or {}
                club = batting_team(pair, bool(ab.get("isTopInning")))
                if club:
                    count_play(c, play, bases, outs, p=f"{club}|")
                    half = order.get((club, gid), 0)
                    count_play(c, play, bases, outs, p=f"{club}.{half}|")
        if verbose and (i + 1) % 400 == 0:
            print(f"  {i + 1}/{len(files)}", flush=True)
    return dict(c)


def _game_teams() -> tuple[dict, dict]:
    """({game_id: (away, home)}, {(team, game_id): 0 or 1}).

    The second map is which half of that club's OWN season the game falls
    in — clubs do not all play the same number of games, so a calendar
    midpoint would put lopsided samples in the two halves.
    """
    from src.context import store
    with store.connect() as c:
        rows = [dict(r) for r in c.execute(
            f"select game_id, date, away_team_abbr a, home_team_abbr h "
            f"from {store.BETS}.games where sport = 'mlb' "
            f"and status = 'Final' order by date")]
    teams = {r["game_id"]: (r["a"], r["h"]) for r in rows}
    seen: dict = {}
    for r in rows:
        for club in (r["a"], r["h"]):
            seen.setdefault(club, []).append(r["game_id"])
    order = {}
    for club, gids in seen.items():
        mid = len(gids) // 2
        for i, g in enumerate(gids):
            order[(club, g)] = 0 if i < mid else 1
    return teams, order


def team_stability(c: dict, num: str, den: str, keys=(0, 1, 2),
                   min_n: int = 60) -> tuple:
    """(r, n_clubs) between each club's first and second half on a rate.

    THE GATE, and the same one the bullpen role had to pass. Clubs
    obviously differ in speed; the question is whether a club's rate in
    games already played predicts its rate in games not yet played. If it
    does not, per-club tables are fitting a season's noise and the league
    number is the honest one.
    """
    import statistics as st
    clubs = sorted({k.split("|")[0].split(".")[0] for k in c
                    if "|" in k and "." in k.split("|")[0]})
    xs, ys = [], []
    for club in clubs:
        halves = []
        for h in (0, 1):
            n = sum(c.get(f"{club}.{h}|{den}/{k}", 0) for k in keys)
            v = sum(c.get(f"{club}.{h}|{num}/{k}", 0) for k in keys)
            halves.append((v / n, n) if n >= min_n else None)
        if all(halves):
            xs.append(halves[0][0])
            ys.append(halves[1][0])
    if len(xs) < 5:
        return None, len(xs)
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if sx == 0 or sy == 0:
        return None, len(xs)
    r = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) * sx * sy)
    return r, len(xs)


def _rate(c, num, den):
    n, d = c.get(num, 0), c.get(den, 0)
    return (n / d, d) if d else (None, 0)


def report(c: dict) -> None:
    print(f"\n{c.get('plays', 0):,} plays\n")

    def block(title, model, num, den, keys=(0, 1, 2)):
        print(f"  {title}")
        for k in keys:
            r, n = _rate(c, f"{num}/{k}", f"{den}/{k}")
            if r is None:
                print(f"    {k} out   (never happens)")
                continue
            want = model.get(k) if isinstance(model, dict) else model
            se = (r * (1 - r) / n) ** 0.5
            gap = "" if want is None else f"   model {want:.3f}"
            if want is not None:
                z = (r - want) / se if se else 0.0
                gap += f"   {r - want:+.3f}  ({z:+.1f} sigma)"
            print(f"    {k} out   {r:.3f} +/- {se:.3f}  n={n:<6}{gap}")
        print()

    block("runner on FIRST reaches THIRD on a single",
          sim.FIRST_TO_THIRD_ON_1B, "first_to_third", "first_on_1b")
    block("runner on FIRST SCORES on a single  (the model cannot)",
          None, "first_scores_on_1b", "first_on_1b")
    block("runner on SECOND scores on a single",
          sim.SECOND_SCORES_ON_1B, "second_on_1b_scored", "second_on_1b")
    block("runner on FIRST scores on a double",
          sim.FIRST_SCORES_ON_2B, "first_scores_on_2b", "first_on_2b")
    block("ANY runner advances on a ball-in-play out",
          sim.RUNNER_ADVANCES_ON_OUT, "any_advance_on_out",
          "out_with_runners", keys=(0, 1))
    for b in pbp._BASES:
        block(f"  ... the runner on {b}, marginal",
              None, f"on_{b}_advanced", f"on_{b}_out", keys=(0, 1))
    print("  WHAT A LEAD-RUNNER-FIRST MODEL NEEDS — base ahead already free")
    for b in pbp._BASES:
        block(f"  ... the runner on {b}, next base empty",
              None, f"free_{b}_advanced", f"free_{b}_out", keys=(0, 1))
    block("double play per BALL-IN-PLAY OUT  (what the model rolls)",
          sim.GIDP_RATE, "dp_chance", "dp_denom", keys=(0, 1))
    block("double play per OPPORTUNITY  (what 'GIDP%' usually means)",
          sim.GIDP_RATE, "dp_chance", "dp_pa", keys=(0, 1))

    print("  ASSERTED AS CERTAIN by the model — how true is it?")
    r, n = _rate(c, "third_on_1b_scored/0", "third_on_1b/0")
    for k in (0, 1, 2):
        r, n = _rate(c, f"third_on_1b_scored/{k}", f"third_on_1b/{k}")
        if r is not None:
            print(f"    third scores on a single, {k} out   {r:.3f}  n={n}")
    for b in ("2B", "3B"):
        r, n = _rate(c, f"lead_scores_on_2b/{b}", f"lead_on_2b/{b}")
        if r is not None:
            print(f"    {b} scores on a double              {r:.3f}  n={n}")


if __name__ == "__main__":
    n = None
    for a in sys.argv[1:]:
        if a.startswith("--limit="):
            n = int(a.split("=")[1])
    if "--by-team" in sys.argv:
        c = tally(limit=n, by_team=True)
        print("\n  DOES BASERUNNING BELONG TO THE CLUB? split-half per club")
        print("  (r near zero means the league number is the honest one)")
        for lbl, num, den, keys in (
                ("first -> third on a single", "first_to_third",
                 "first_on_1b", (0, 1, 2)),
                ("second scores on a single", "second_on_1b_scored",
                 "second_on_1b", (0, 1, 2)),
                ("first scores on a double", "first_scores_on_2b",
                 "first_on_2b", (0, 1, 2)),
                ("advances on a ball-in-play out", "any_advance_on_out",
                 "out_with_runners", (0, 1)),
                ("grounds into a double play", "dp_chance", "dp_denom",
                 (0, 1))):
            r, k = team_stability(c, num, den, keys)
            got = "too few" if r is None else f"r {r:+.3f}"
            print(f"    {lbl:<34}{got:>10}   n={k} clubs")
        print("\n  spread across clubs, full season:")
        for lbl, num, den, keys in (
                ("first -> third on a single", "first_to_third",
                 "first_on_1b", (0, 1, 2)),
                ("advances on a ball-in-play out", "any_advance_on_out",
                 "out_with_runners", (0, 1))):
            vals = []
            clubs = sorted({k.split("|")[0] for k in c
                            if "|" in k and "." not in k.split("|")[0]})
            for club in clubs:
                d = sum(c.get(f"{club}|{den}/{k}", 0) for k in keys)
                v = sum(c.get(f"{club}|{num}/{k}", 0) for k in keys)
                if d > 200:
                    vals.append((v / d, club))
            if vals:
                vals.sort()
                import statistics as _st
                print(f"    {lbl}: {vals[0][0]:.3f} ({vals[0][1]}) to "
                      f"{vals[-1][0]:.3f} ({vals[-1][1]}), "
                      f"sd {_st.pstdev(v for v, _ in vals):.3f}")
        sys.exit(0)
    if "--events" in sys.argv:
        c = tally(limit=n or 200)
        for k, v in sorted(((k, v) for k, v in c.items()
                            if k.startswith("ev:")), key=lambda x: -x[1]):
            print(f"  {v:>7}  {k[3:]}")
        sys.exit(0)
    report(tally(limit=n))
