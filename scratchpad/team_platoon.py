"""Is a club's platoon split ITS OWN, or is it the league's split?

    venv/bin/python -m scratchpad.team_platoon CIN 2026 2026-09-05

Every club hits right-handed pitching better than left-handed pitching,
because most hitters do and most lineups are built that way. So "this team
is better against righties" is TRUE OF EVERY TEAM and carries no information
on its own. The quantity that could carry information is the DIFFERENCE IN
DIFFERENCES: this club's (vs-RHP minus vs-LHP) gap, minus the league's.

Counted off the cached play-by-play, one row per completed plate appearance,
with the pitcher's hand read from `matchup.pitchHand` rather than a roster
lookup. wOBA weights are the standard published ones — they are a fixed
linear scoring rule applied identically to both splits, not a fit.

STATE THE POWER BEFORE THE RESULT. Per-PA wOBA has a standard deviation near
0.7, so a club's vs-LHP sample of ~1,200 PA gives a standard error of about
0.020 and the difference-in-differences roughly the same. A platoon claim
worth less than ~0.040 wOBA is not resolvable on one season and should be
reported as unresolved, not as a null.
"""
from __future__ import annotations

import random
import statistics as st
import sys
from collections import defaultdict

from src import db
from src.context.sources import pbp

#: Standard wOBA weights. A fixed scoring rule, applied to both splits.
W = {"walk": 0.690, "hit_by_pitch": 0.722, "single": 0.888,
     "double": 1.271, "triple": 1.616, "home_run": 2.101}
#: Not plate appearances for wOBA purposes.
SKIP = {"sac_bunt", "intent_walk", "catcher_interf"}


def games(season: int, before: str | None) -> list[tuple[str, str, str]]:
    """[(game_id, away_abbr, home_abbr)] for cached final games in season."""
    with db.connect() as c:
        rows = c.execute(
            "select game_id, away_team_abbr a, home_team_abbr h from games "
            "where sport='mlb' and status='Final' and date like ? "
            "and (? is null or date < ?) order by date",
            (f"{season}-%", before, before)).fetchall()
    return [(r["game_id"], r["a"], r["h"]) for r in rows
            if pbp.have(r["game_id"])]


def collect(season: int, before: str | None, verbose=True):
    """{(team, pitcher hand, half): [wOBA value per PA]}.

    `half` is the game's index parity, which is what makes the split-half
    reliability gate possible off the same single pass. Alternating games
    rather than splitting the season in two keeps both halves over the same
    weather, the same opponents and the same roster.
    """
    out: dict[tuple, list] = defaultdict(list)
    gs = games(season, before)
    if verbose:
        print(f"  {len(gs)} cached games in {season}"
              f"{' before ' + before if before else ''}", flush=True)
    for i, (gid, away, home) in enumerate(gs):
        for play, _b, _o, _a, _h in pbp.plays(gid):
            res = play.get("result") or {}
            if res.get("type") != "atBat":
                continue
            ev = res.get("eventType")
            if not ev or ev in SKIP:
                continue
            mu = play.get("matchup") or {}
            hand = (mu.get("pitchHand") or {}).get("code")
            if hand not in ("L", "R"):
                continue
            top = (play.get("about") or {}).get("isTopInning")
            bat = away if top else home
            out[(bat, hand, i % 2)].append(W.get(ev, 0.0))
        if verbose and (i + 1) % 250 == 0:
            print(f"    {i + 1}/{len(gs)}", flush=True)
    return out


def _woba(v):
    if not v:
        return (0.0, 0.0, 0)
    return (st.mean(v), st.pstdev(v) / len(v) ** 0.5, len(v))


def _gaps(d, halves=(0, 1)) -> tuple[dict, float]:
    """({team: gap against the league's gap}, the league's own gap)."""
    def pool(t, h):
        return [x for k, v in d.items() if k[1] == h and k[2] in halves
                and (t is None or k[0] == t) for x in v]
    lgap = _woba(pool(None, "R"))[0] - _woba(pool(None, "L"))[0]
    out = {}
    for t in {k[0] for k in d if k[0]}:
        l_m, _se, l_n = _woba(pool(t, "L"))
        r_m, _se, r_n = _woba(pool(t, "R"))
        if l_n < 100 or r_n < 100:
            continue
        out[t] = r_m - l_m - lgap
    return out, lgap


def split_half(d) -> None:
    """DOES A CLUB'S PLATOON GAP REPEAT? The same gate `advance.py` applies
    to clubs and `stabilise.py` applies to players — a spread that does not
    survive a split of the same season is sampling noise wearing a team
    name, and no amount of it can be known by anyone.
    """
    a, _ = _gaps(d, (0,))
    b, _ = _gaps(d, (1,))
    both = sorted(set(a) & set(b))
    if len(both) < 10:
        print("\n  split-half: too few clubs")
        return
    xs, ys = [a[t] for t in both], [b[t] for t in both]
    r = st.correlation(xs, ys)
    # se of a correlation near zero is 1/sqrt(n-3).
    se = 1 / (len(both) - 3) ** 0.5
    print(f"\n  SPLIT-HALF over {len(both)} clubs (odd games vs even): "
          f"r = {r:+.3f} ± {se:.3f}")
    print(f"  powered to see r >= {2 * se:.2f} at 2 sigma. Each half's gap "
          f"sd: {st.pstdev(xs):.3f} / {st.pstdev(ys):.3f}")


def positive_control(d, size: float = 0.030) -> None:
    """A NULL IS A CLAIM. Inject a club platoon spread of a stated size and
    confirm the split-half gate above can see it — a mis-specified harness
    and an absent effect print the same r.

    The injected tendency is FIXED PER CLUB across both halves, which is
    exactly what "a real club platoon skill" means, and is added to the
    club's vs-RHP plate appearances only.
    """
    rng = random.Random(7)
    tend = {t: rng.gauss(0, size) for t in sorted({k[0] for k in d if k[0]})}
    spiked = {k: ([x + tend[k[0]] for x in v] if k[1] == "R" and k[0] in tend
                  else list(v)) for k, v in d.items()}
    print(f"\n  POSITIVE CONTROL — club tendencies injected at sd {size:.3f}"
          f" wOBA")
    split_half(spiked)


def report(team: str, season: int = 2026, before: str | None = None,
           control: bool = False) -> None:
    d = collect(season, before)
    lg = {h: [x for (t, hh, _i), v in d.items() if hh == h for x in v]
          for h in ("L", "R")}
    d2 = {(t, h): [x for (tt, hh, _i), v in d.items()
                   if tt == t and hh == h for x in v]
          for (t, h, _i) in d}
    print(f"\n  {'':<10}{'vs LHP':>18}{'vs RHP':>18}{'gap R-L':>12}")
    rows = []
    for label, get in ((team, lambda h: d2.get((team, h), [])),
                       ("league", lambda h: lg[h])):
        l_m, l_se, l_n = _woba(get("L"))
        r_m, r_se, r_n = _woba(get("R"))
        gap = r_m - l_m
        gse = (l_se ** 2 + r_se ** 2) ** 0.5
        rows.append((gap, gse))
        print(f"  {label:<10}{l_m:>8.3f} ±{l_se:.3f} n{l_n:<6}"
              f"{r_m:>8.3f} ±{r_se:.3f} n{r_n:<6}{gap:>+8.3f}")
    (tg, tse), (lgap, lse) = rows
    dd = tg - lgap
    dse = (tse ** 2 + lse ** 2) ** 0.5
    print(f"\n  {team} gap {tg:+.3f}, league gap {lgap:+.3f}")
    print(f"  difference in differences {dd:+.3f} ± {dse:.3f}"
          f"  ({dd / dse if dse else 0:+.1f} sigma)")
    print(f"  resolvable at 2 sigma: {2 * dse:.3f} wOBA. A claim smaller "
          f"than that is UNRESOLVED,\n  not refuted.")

    # Every club's difference-in-differences, so one team's number can be
    # read against the spread rather than against zero.
    ranked = []
    # A cached game with no abbreviation on one club yields a None team.
    # Dropping it is right: it is one row per game, not a systematic side.
    for t in sorted({t for (t, _h) in d2 if t}):
        l_m, l_se, l_n = _woba(d2.get((t, "L"), []))
        r_m, r_se, r_n = _woba(d2.get((t, "R"), []))
        if l_n < 200 or r_n < 200:
            continue
        ranked.append((r_m - l_m - lgap, t, l_n, r_n))
    ranked.sort(reverse=True)
    print(f"\n  every club's platoon gap against the league's "
          f"({len(ranked)} clubs)")
    spread = st.pstdev([x[0] for x in ranked])
    print(f"  sd of the club gaps: {spread:.3f}, against a per-club "
          f"standard error of {dse:.3f}")
    print("  THE SPREAD IS THE ERROR PLUS THE TRUTH. Subtract in quadrature "
          "to see\n  how much of it is real: "
          f"{max(spread ** 2 - dse ** 2, 0) ** 0.5:.3f} wOBA.")
    for v, t, ln, rn in ranked:
        mark = "  <--" if t == team else ""
        print(f"    {t:<5}{v:>+8.3f}   n {ln:>5}L {rn:>5}R{mark}")
    split_half(d)
    if control:
        positive_control(d)


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("-")]
    team = a[0] if a else "CIN"
    season = int(a[1]) if len(a) > 1 else 2026
    before = a[2] if len(a) > 2 else None
    report(team, season, before, control="--control" in sys.argv)
