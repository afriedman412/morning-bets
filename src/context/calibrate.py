"""Does the simulator reproduce real baseball? Run before trusting a number.

The first validation is against the league's own distribution, not against
any bet. A simulator that gets the average right and the SHAPE wrong will
price a 15.5 line correctly and a 20.5 line badly, and comparing means would
never show it — which is the same mistake the point-estimate estimator made
and the reason it measured AUC 0.537.

Four things are checked, in the order they would break:

  1. Rates. Simulated K, BB, HR and hit rates against the league's.
  2. Runs. Nothing in the base-running model was tuned to hit 4.63 runs per
     nine, so matching it is evidence the crude advancement rules are
     adequate; missing it says they are not.
  3. Outs distribution. Mean, spread, and specifically the share ending on
     an inning boundary — 66% in the real data, and a simulator that ends
     starts mid-inning half the time has the wrong hook no matter how good
     its mean looks.
  4. Hook hazard by inning, against the observed 8/20/46/70/84% curve.

LEAKAGE, DELIBERATE. Player rates here are full-season, including the games
being replayed. That is correct for asking "does the machinery produce the
right shape" and wrong for asking "does it predict", so no claim about
forecasting should be read off this. Pass `--before` for a clean split.
"""
from __future__ import annotations

import random
import sys
from collections import Counter

from src import db, roster
from src.context import game, sim
from src.context.sources import mixture
from src.context.sources import rates as rate_src

# Real starters where the boxscore has been consulted, the most-outs
# heuristic only where it has not. The heuristic agrees 91.7% of the time
# and its 8.3% of misses are all short starts — a starter knocked out in the
# second passed by the long reliever behind him — so leaning on it truncates
# the left tail and teaches the hook that blowups do not happen.
#
# `o >= 1` rather than `>= 3`: with ground truth, a start that lasted two
# outs is a real observation and belongs in the distribution. The old floor
# existed only because the heuristic could never return one.
_STARTS_Q = """
with pr as (
  select p.game_id, p.team, p.player_name, p.outs_recorded o,
         p.k, p.bb, p.h, p.hr, p.r, p.er, g.date, p.is_starter,
         g.venue_id, g.day_night,
         case when p.team = g.home_team_abbr then 1 else 0 end is_home,
         row_number() over (partition by p.game_id, p.team
                            order by p.outs_recorded desc) rn,
         max(case when p.is_starter is not null then 1 else 0 end)
           over (partition by p.game_id) has_truth
  from mlb_pitching p join games g on g.game_id = p.game_id
  where g.sport = 'mlb' and g.status = 'Final' {where}
)
select pr.* from pr
{rotation_join}
where o >= 1
  and ((has_truth = 1 and is_starter = 1)
       or (has_truth = 0 and rn = 1 and o >= 3))
  {rotation_filter}
"""

#: A pitcher needs this many starts on the season to count as a rotation
#: arm. Openers are genuine starters by the boxscore's definition and are
#: correctly flagged as such, but no book offers an outs line on one, and
#: their 4.5-out outings would drag the hook toward a leash nobody in the
#: modelled population is actually on. 101 of the 172 starts the old
#: heuristic missed were openers; the other 71 were rotation starters
#: knocked out early, and those DO belong.
ROTATION_MIN_GS = 5

_ROTATION_JOIN = """
join (select player_name
      from mlb_pitching
      where is_starter is not null
      group by player_name
      having sum(case when is_starter = 1 then 1 else 0 end) >= {gs}
     ) rot on rot.player_name = pr.player_name
"""


def actual_starts(season=None, before=None, limit=None,
                  since=None, rotation_only=True) -> list[dict]:
    where = ""
    if season:
        where += f" and g.date like '{season}%'"
    if before:
        where += f" and g.date < '{before}'"
    if since:
        where += f" and g.date >= '{since}'"
    q = _STARTS_Q.format(
        where=where,
        rotation_join=(_ROTATION_JOIN.format(gs=ROTATION_MIN_GS)
                       if rotation_only else ""),
        rotation_filter="")
    if limit:
        q += f" limit {limit}"
    with db.connect() as c:
        return [dict(r) for r in c.execute(q)]


#: Use the REAL batting order from play-by-play instead of the at-bat
#: proxy. ON, and it is a correction rather than a feature.
#:
#: The proxy sorted each club's hitters by at-bats descending and took the
#: top nine. Against play-by-play over 574 lineups it matched exactly 0.0%
#: of the time, missed at least one batter in 23.5%, and put the average
#: hitter 2.30 slots from where he really batted. At-bats exclude walks, so
#: a high-OBP leadoff man sorted below a free swinger; a club that batted
#: around handed its leadoff man five at-bats, so the "input" was partly a
#: function of the result.
#:
#: The order is not cosmetic: the simulator wraps the lineup and derives
#: times through the order from batters faced, and TTO is a measured 19%
#: swing in strikeout rate between the first pass and the third.
USE_REAL_ORDER = True


def opposing_lineups(conn=None) -> dict[tuple, list[str]]:
    """{(game_id, pitcher_team): [the nine he FACES, in batting order]}.

    Prefers `order.lineups()`, which counts the true order off play-by-play
    and covers 97% of final games. The at-bat proxy below remains only as
    the fallback for the 3% with no cached play-by-play — it is kept rather
    than deleted so a missing game degrades to a worse lineup instead of
    dropping the start entirely.
    """
    if USE_REAL_ORDER:
        try:
            from src.context import order
            real = order.lineups()
        except Exception:
            real = {}
        if real:
            return {**_ab_proxy_lineups(conn), **real}
    return _ab_proxy_lineups(conn)


def _ab_proxy_lineups(conn=None) -> dict[tuple, list[str]]:
    """The old at-bat-sorted approximation. FALLBACK ONLY — see above."""
    q = """
    select mb.game_id, mb.team, mb.player_name, mb.ab
    from mlb_batting mb join games g on g.game_id = mb.game_id
    where g.sport = 'mlb' and g.status = 'Final'
    order by mb.game_id, mb.team, mb.ab desc
    """

    def _run(c):
        return c.execute(q).fetchall()

    rows = _run(conn) if conn is not None else _with(_run)

    by_side: dict[tuple, list[str]] = {}
    for r in rows:
        by_side.setdefault((r["game_id"], r["team"]), []).append(
            r["player_name"])
    # A pitcher on team T faces the OTHER team's hitters in the same game.
    teams_in: dict[str, list[str]] = {}
    for gid, team in by_side:
        teams_in.setdefault(gid, []).append(team)
    out = {}
    for gid, teams in teams_in.items():
        if len(teams) != 2:
            continue
        a, b = teams
        out[(gid, a)] = by_side[(gid, b)][:9]
        out[(gid, b)] = by_side[(gid, a)][:9]
    return out


def _with(fn):
    with db.connect() as c:
        return fn(c)


_CASES: dict[tuple, list] = {}

#: Loaded once — the Savant exports are ~4MB and the fit reads them per
#: candidate otherwise.
_MIX: list = [None, None, None]


#: Use derived vs-LHP/vs-RHP batter rates instead of overall rates.
#:
#: OFF, because it was measured and it does nothing. The hypothesis was that
#: handedness would supply the between-start variance the model is missing,
#: and it does add 20.3% more between-BATTER spread in K% — but A/B'd over
#: 1,776 starts the Brier skill deltas alternate sign between -0.23% and
#: +0.49% on K, and -0.20% to +0.40% on outs, with AUC unchanged to three
#: decimals on all twelve lines.
#:
#: Two explanations, and they point at different follow-ups. Platoon effects
#: largely AVERAGE OUT across nine hitters, so between-batter variance is
#: not the same thing as between-start variance. And the derivation is
#: attenuated: crediting a batter's whole game line to the opposing
#: starter's hand includes his plate appearances against relievers, then
#: SPLIT_STABILISE pulls each split roughly halfway back to his overall
#: rate. Testing statsapi's exact splits would separate the two — if those
#: also fail, the averaging argument wins and the idea is dead.
#:
#: Kept rather than deleted so the next person with this instinct can flip
#: one flag instead of rebuilding it.
USE_HANDEDNESS = False

#: Apply Savant park multipliers, keyed by the game's venue_id. An unrated
#: venue resolves to neutral, never to the home club's park — the Athletics
#: played 38 home games this season at sites Savant does not rate.
USE_PARK = False

#: Apply per-matchup arsenal multipliers.
#:
#: OFF. Measured 9.79% mean Brier skill with and 9.79% without — dead even
#: across 20 stat/line combinations.
#:
#: The structural argument for it was sound and is worth keeping on record,
#: because it correctly predicted why handedness failed and it did NOT save
#: this. Handedness varies by batter and nine of them average it away; an
#: arsenal varies by PITCHER and the whole lineup faces the same one, so it
#: survives to the start level — measured per-start mean k-multiplier sd
#: 0.0642, range 0.864-1.180, where handedness scored about zero. The
#: variance is genuinely there and it still bought nothing.
#:
#: One hint, below the noise floor and recorded so it is not mistaken for a
#: new idea later: every HIGH K line improved on both Brier and AUC
#: (k 7.5 +0.67pp, AUC 0.813 -> 0.822; k 6.5 +0.62pp) while the low lines
#: and outs got slightly worse. Consistent with a whiff signal helping
#: discriminate big strikeout games. Each delta is under the 0.5pp
#: detection floor, and selecting the four lines that rose is how findings
#: get manufactured — so if this is revisited, re-run at n_sims >= 400 and
#: decide on the high-K lines BEFORE looking.
USE_ARSENAL = False

#: Resolve the strikeout matchup PER PITCH TYPE and average by usage, rather
#: than multiplying the aggregate rate by a scalar. See
#: `sources/mixture.py` for why the scalar version was structurally weak,
#: and `PREREG-arsenal.md` for the decision rule fixed before this was run.
#:
#: OFF until the pre-registered test says otherwise.
USE_MIXTURE = False

#: The CONTACT channel of the same mixture — wOBA per pitch type, applied
#: through `BatterRates.arsenal_mult`, which scales home runs AND BABIP by
#: the same factor.
#:
#: A DIFFERENT MECHANISM, not a subset of the strikeout null. That channel
#: was tested and is dead — +0.6 sigma the wrong way, and flat in every
#: quartile of mixture deviation including lineups it moved 7.5-16%. Whiffs
#: move OUTS, the half measured to carry no edge; runs come from balls in
#: play. See PREREG-arsenal-contact.md. OFF until measured.
USE_CONTACT_MIXTURE = False

#: Divide each player's rates by the park they were accumulated in before
#: applying tonight's. Without this a park multiplier double-counts the
#: home side and mis-bases the road side — see rates.park_neutralise.
NEUTRALISE_PARK = False

#: Home/road adjustment, centred on each player's season mean.
USE_HOME_ROAD = True

# ── home / road ────────────────────────────────────────────────────────
#
# MEASURED, NOT TUNED. Set from the observed league split rather than fitted
# against Brier, because two free parameters searched against the same
# metric they are then scored on will find something whether or not anything
# is there.
#
#   K rate    home 0.2253 vs away 0.2110   +6.8%   z +3.49
#   hit rate  home 0.2164 vs away 0.2253   -3.9%   z -2.15
#   outs      home 16.12  vs away 15.79    +0.33   z +1.80  (not sig alone)
#
# Applied to the OPPOSING LINEUP, not to the pitcher: the visiting nine hit
# worse, which is the same statement viewed from the other side and keeps
# the pitcher's own rates meaning one thing everywhere.
#
# Two multipliers rather than one because a single knob cannot fit both — K
# moves +6.8% while contact moves -3.9%, and forcing them to share a
# parameter would split the difference and get both wrong.
#
# NOT CONFOUNDED WITH PARK at this level, contrary to the obvious worry:
# every park hosts 81 home starts and 81 away starts, so park balances out
# in the league-wide split. The confounding is real only PER PITCHER, whose
# home starts all happen at one venue — which is why any per-pitcher home
# term must still be fitted after park.
# CENTRED ON THE SEASON MEAN, not applied one-sided. A player's season rate
# already contains ~half home starts and ~half away, so giving the home
# start the full +6.8% and the away start nothing would inflate every
# pitcher's K rate by ~3.4% overall. Half the contrast each way leaves the
# average untouched and only redistributes it.
#
# This is the same double-counting that makes PARK FACTORS useless here: a
# Rockies pitcher's season rates already include his starts at Coors, so
# multiplying by the park index again counts it one and a half times. Park
# cannot help until the underlying rates are park-neutralised.
HOME_OPP_K = 1.034
HOME_OPP_CONTACT = 0.981
AWAY_OPP_K = 1.0 / HOME_OPP_K
AWAY_OPP_CONTACT = 1.0 / HOME_OPP_CONTACT
#: Extra log-odds on the hook at home. Left at zero: the outs difference
#: does not clear 2 sigma on its own, and whatever is there should fall out
#: of the rate effects above rather than being double-counted here.
HOME_HOOK = 0.0


def adjust_lineup(lineup: list, is_home: bool) -> list:
    """The opposing nine, shifted for who is batting at home.

    Applied to the LINEUP rather than to the pitcher so his own rates keep
    meaning one thing everywhere, and centred on the season mean so the
    league average is untouched — see the HOME_OPP_* block above.

    Factored out of `per_start_probs_all` when the F5 fit needed the same
    nine. Two copies of a centring rule is exactly how one of them ends up
    one-sided.
    """
    if not USE_HOME_ROAD or HOME_OPP_K == 1.0:
        return lineup
    mk = HOME_OPP_K if is_home else AWAY_OPP_K
    mc = HOME_OPP_CONTACT if is_home else AWAY_OPP_CONTACT
    return [sim.BatterRates(
        name=b.name, pa=b.pa, arsenal_mult=b.arsenal_mult,
        arsenal_k_mult=b.arsenal_k_mult,
        k_pct=min(0.95, b.k_pct * mk),
        bb_pct=b.bb_pct * mc, hr_pct=b.hr_pct * mc,
        babip=b.babip * mc) for b in lineup]


_PARK_CACHE: dict = {}


def park_for(venue_id) -> dict:
    """Rate multipliers for a venue. Neutral when unrated or unknown."""
    if not venue_id:
        return sim.NEUTRAL_PARK
    if venue_id not in _PARK_CACHE:
        try:
            from src.context.sources import park as park_src
            rec = park_src.park_factors().get(f"id:{venue_id}")
        except Exception:
            rec = None
        _PARK_CACHE[venue_id] = sim.park_mults(rec)
    return _PARK_CACHE[venue_id]


#: One simulated game per draw is ~2x the work of one simulated start, and
#: `replay` is the only way anything in this project simulates now. That is
#: deliberate. The deleted `sim.simulate_start` modelled ONE PITCHING SIDE,
#: which cannot see its own team's runs — so `Hook.per_margin` and
#: `mid_per_margin` were structurally unreachable and sat at 0.0 forever,
#: and a "start" was a different model from a game rather than a part of
#: one. Every measured null in the dead list (park, handedness, day/night,
#: home field) was produced on that engine, against games that were not
#: games.
def paired_cases(season=None, before=None, since=None, rates_before=None,
                 max_starts=None, handed=None) -> dict:
    """{game_id: (away_case, home_case)} for games with BOTH starters modelled.

    A case is the `(start_row, PitcherRates, opposing_lineup)` triple that
    `build_cases` yields. Games where only one side is replayable are
    DROPPED rather than given a league-average opponent: inventing the other
    club would invent the score, and the score is the input this whole
    migration exists to make reachable.

    Retention is about 90% of starts — the same filter `ladder` has always
    applied, which is why the ladder's game count (1,615) has always been
    lower than the start count (3,600).
    """
    by: dict = {}
    for case in build_cases(season=season, before=before, since=since,
                            rates_before=rates_before,
                            max_starts=max_starts, handed=handed):
        by.setdefault(case[0]["game_id"], []).append(case)
    out = {}
    for gid, v in by.items():
        if len(v) != 2:
            continue
        home = [c for c in v if c[0]["is_home"]]
        away = [c for c in v if not c[0]["is_home"]]
        if len(home) != 1 or len(away) != 1:
            continue
        out[gid] = (away[0], home[0])
    return out


def replay(pair, lg, pens, rng, innings=9, track=(), apply_leash=True,
           use_park=None):
    """One simulated game from a paired case. THE simulation entry point.

    Park is applied to the GAME, not to a side — both clubs play in the same
    building, which is the natural shape and was impossible to express while
    each side was simulated on its own. `simulate_game` has always accepted
    a park argument and every caller passed None, so until this existed park
    had never once been evaluated inside a real game.
    """
    away, home = pair
    # `build_cases` attaches to each start the nine that pitcher FACES, so
    # `away[2]` is already the HOME club's batters. The away PITCHING side
    # therefore takes `an`, not `hn`. Getting this backwards has every
    # pitcher facing his own teammates — see
    # `check_each_side_faces_the_opposing_lineup`.
    an = adjust_lineup(away[2], False)
    hn = adjust_lineup(home[2], True)
    park = None
    if USE_PARK if use_park is None else use_park:
        park = park_for(home[0].get("venue_id"))
    A = game.build_side(away[1], pens.get((away[0]["team"] or "").upper(), []),
                        an, None, rng, team=away[0]["team"],
                        apply_leash=apply_leash)
    H = game.build_side(home[1], pens.get((home[0]["team"] or "").upper(), []),
                        hn, None, rng, team=home[0]["team"],
                        apply_leash=apply_leash)
    if HOME_HOOK:
        H.hook = sim.Hook(**{
            **H.hook.__dict__,
            "team_offset": H.hook.team_offset + HOME_HOOK})
    return game.simulate_game(A, H, lg, rng, innings=innings, park=park,
                              track=track)


def build_cases(season=None, before=None, max_starts=None, since=None,
                rates_before=None, handed=None) -> list[tuple]:
    """[(actual_row, PitcherRates, [BatterRates])] for every replayable start.

    Split out from the simulation and memoised because the tuner evaluates
    a hundred candidate hooks against the same cases, and rebuilding rates
    and lineups each time made a two-minute search a twenty-minute one.
    """
    handed = USE_HANDEDNESS if handed is None else handed
    key = (season, before, max_starts, since, rates_before, handed,
           NEUTRALISE_PARK, USE_ARSENAL, USE_MIXTURE,
           USE_CONTACT_MIXTURE)
    if key in _CASES:
        return _CASES[key]

    # Rates and starts are filtered SEPARATELY so a holdout can train rates
    # on one window and score starts in another. Tying them together is what
    # makes an "out-of-sample" test quietly in-sample.
    rb = rates_before if rates_before is not None else before
    # The LEAGUE BASELINE is training data too. log5 returns the league value
    # when both sides are average, so it anchors every simulated rate — and
    # computing it over every cached game let the test window into a
    # "train-only" fit. Same cutoff as the player rates.
    lg = sim.league(season, before=rb)
    pr = rate_src.pitcher_rates(lg, season, rb)
    br = rate_src.batter_rates(lg, season, rb)
    split = rate_src.batter_rates_by_hand(lg, season, rb) if handed else {}
    if NEUTRALISE_PARK:
        pr = rate_src.neutralise(
            pr, rate_src.park_exposure("pitcher", season, rb))
        br = rate_src.neutralise(
            br, rate_src.park_exposure("batter", season, rb))
    lineups = opposing_lineups()
    league_bats = sim.BatterRates(name="league", k_pct=lg["k_pct"],
                                  bb_pct=lg["bb_pct"], hr_pct=lg["hr_pct"],
                                  babip=lg["babip"])

    if (USE_MIXTURE or USE_CONTACT_MIXTURE) and _MIX[0] is None:
        d = mixture.load()
        _MIX[0] = d
        _MIX[1] = mixture.league_by_pitch(d) if d else {}
        _MIX[2] = mixture.league_usage(_MIX[1]) if _MIX[1] else {}

    arsenals = {}
    if USE_ARSENAL:
        try:
            from datetime import date as _d
            from src import panel
            stamp = rb or _d.today().isoformat()
            arsenals = panel._pitcher_arsenal_blob(
                panel.savant_pitcher_arsenal(season or 2026, stamp)) or {}
        except Exception:
            arsenals = {}

    cases = []
    for s in actual_starts(season, before, max_starts, since):
        p = pr.get(s["player_name"])
        names = lineups.get((s["game_id"], s["team"]))
        if not p or not names or len(names) < 9:
            continue
        # The starter's throwing hand picks each hitter's split. Unknown
        # hand falls back to overall rates rather than guessing a side —
        # a wrong split moves the estimate in a definite wrong direction,
        # which is worse than no split at all.
        hand = roster.throws(s["player_name"]) if handed else None
        lineup = []
        for nm in names:
            b = br.get(nm)
            if b is None:
                lineup.append(league_bats)
                continue
            use = (split.get(nm, {}).get(hand) or b) if hand else b
            lineup.append(
                sim.BatterRates(name=nm, k_pct=use["k_pct"],
                                bb_pct=use["bb_pct"], hr_pct=use["hr_pct"],
                                babip=use["babip"], pa=b["pa"]))
        if (USE_MIXTURE or USE_CONTACT_MIXTURE) and _MIX[0]:
            data, lgp, lgu = _MIX
            if USE_CONTACT_MIXTURE:
                for x in lineup:
                    cm = mixture.matchup_contact(
                        x.name, p["name"], data, lgp,
                        b_overall=mixture.batter_woba(x.name, data, lgu),
                        lg_usage=lgu)
                    if cm is not None:
                        x.arsenal_mult = cm
        if USE_MIXTURE and _MIX[0]:
            data, lgp, lgu = _MIX
            for x in lineup:
                m = mixture.matchup_k(
                    x.name, p["name"], data, lgp,
                    b_overall=x.k_pct, p_overall=p["k_pct"],
                    lg_overall=lg["k_pct"], log5=sim.log5)
                if m is None:
                    continue
                agg = sim.log5(x.k_pct, p["k_pct"], lg["k_pct"])
                # Enters through the multiplier slot that already feeds
                # `pa_outcome`, so nothing downstream changes shape. A
                # neutral arsenal against a batter with no per-pitch
                # tendencies gives m == agg and a multiplier of exactly 1.
                if agg > 0:
                    x.arsenal_k_mult = m / agg
        if arsenals:
            mix = arsenals.get((s["player_name"] or "").lower().strip())
            mm = rate_src.arsenal_mults(
                mix, [x.name for x in lineup], arsenals, season, rb) \
                if mix else {}
            for x in lineup:
                v = mm.get(x.name)
                if v:
                    x.arsenal_mult = v["contact"]
                    x.arsenal_k_mult = v["k"]
        cases.append((s, sim.PitcherRates(
            name=p["name"], k_pct=p["k_pct"], bb_pct=p["bb_pct"],
            hr_pct=p["hr_pct"], babip=p["babip"], pa=p["pa"]), lineup))
    _CASES[key] = cases
    return cases


def run(season=None, before=None, n_sims=100, max_starts=None,
        hook: sim.Hook | None = None, seed=0, flat=True) -> dict:
    """Replay every start. `flat=True` uses the league hook for everyone.

    The tuner needs flat: fitting the global hook while per-club and
    per-pitcher offsets are already absorbing the error would drive the
    global parameters somewhere meaningless.
    """
    lg = sim.league(season)
    pairs = paired_cases(season=season, before=before, max_starts=max_starts)
    pens = rate_src.bullpens(lg, before=before)
    rng = random.Random(seed)
    act, simd = [], []
    for pair in pairs.values():
        act.append(pair[0][0])
        act.append(pair[1][0])
        for _ in range(n_sims):
            # `flat` keeps everyone on the league hook. The tuner needs it:
            # fitting global parameters while per-pitcher leash offsets are
            # already absorbing the error drives them somewhere meaningless.
            r = replay(pair, lg, pens, rng, apply_leash=not flat)
            simd.append(r.away_sp)
            simd.append(r.home_sp)
    return {"lg": lg, "actual": act, "sim": simd, "starts_used": len(act)}


def _boundary(vals) -> float:
    return sum(1 for v in vals if v % 3 == 0) / len(vals) if vals else 0.0


def _hazard(outs_list) -> dict[int, float]:
    out = {}
    for inn in range(3, 9):
        o = inn * 3
        reached = sum(1 for v in outs_list if v >= o)
        ended = sum(1 for v in outs_list if o <= v < o + 3)
        if reached >= 20:
            out[inn] = ended / reached
    return out


def report(res: dict) -> None:
    act, sm = res["actual"], res["sim"]
    a_outs = [a["o"] for a in act]
    s_outs = [r.outs for r in sm]
    n_a, n_s = len(a_outs), len(s_outs)
    print(f"{res['starts_used']} real starts, {n_s} simulated\n")

    def line(label, a, s, fmt="{:.2f}"):
        d = s - a
        flag = "  <-- off" if a and abs(d) / max(abs(a), 1e-9) > 0.10 else ""
        print(f"  {label:<22}{fmt.format(a):>9}{fmt.format(s):>9}"
              f"{fmt.format(d):>9}{flag}")

    print(f"  {'':<22}{'actual':>9}{'sim':>9}{'diff':>9}")
    print("  -- per start --")
    for lbl, key, f in (("outs", "o", "{:.2f}"), ("strikeouts", "k", "{:.2f}"),
                        ("walks", "bb", "{:.2f}"), ("hits", "h", "{:.2f}"),
                        ("home runs", "hr", "{:.2f}"),
                        # EARNED runs, not total: the simulation models no
                        # errors, so every run it produces is earned by
                        # construction. Scoring it against total runs
                        # charges it for defence it never simulated, which
                        # read as a 12% run deficit that was not there.
                        ("earned runs", "er", "{:.2f}")):
        attr = {"o": "outs", "k": "k", "bb": "bb", "h": "h", "hr": "hr",
                "er": "earned"}[key]
        line(lbl, sum(a[key] for a in act) / n_a,
             sum(getattr(r, attr) for r in sm) / n_s, f)

    line("earned runs/9", sum(a["er"] for a in act) * 27 / max(sum(a_outs), 1),
         sum(r.earned for r in sm) * 27 / max(sum(s_outs), 1))
    line("TOTAL runs/9", sum(a["r"] for a in act) * 27 / max(sum(a_outs), 1),
         sum(r.runs for r in sm) * 27 / max(sum(s_outs), 1))
    line("K per 9", sum(a["k"] for a in act) * 27 / max(sum(a_outs), 1),
         sum(r.k for r in sm) * 27 / max(sum(s_outs), 1))

    print("  -- shape --")
    line("ends on boundary", _boundary(a_outs) * 100, _boundary(s_outs) * 100,
         "{:.1f}")
    line("P(outs >= 18)", sum(1 for v in a_outs if v >= 18) / n_a * 100,
         sum(1 for v in s_outs if v >= 18) / n_s * 100, "{:.1f}")
    line("P(outs < 15)", sum(1 for v in a_outs if v < 15) / n_a * 100,
         sum(1 for v in s_outs if v < 15) / n_s * 100, "{:.1f}")
    sd_a = (sum((v - sum(a_outs) / n_a) ** 2 for v in a_outs) / n_a) ** 0.5
    sd_s = (sum((v - sum(s_outs) / n_s) ** 2 for v in s_outs) / n_s) ** 0.5
    line("outs SD", sd_a, sd_s)

    print("  -- hook hazard by inning --")
    ha, hs = _hazard(a_outs), _hazard(s_outs)
    for inn in sorted(set(ha) | set(hs)):
        line(f"after inning {inn}", ha.get(inn, 0) * 100,
             hs.get(inn, 0) * 100, "{:.1f}")

    print("  -- outs histogram (% of starts) --")
    ca, cs = Counter(a_outs), Counter(s_outs)
    for o in range(6, 25):
        pa, ps = ca.get(o, 0) / n_a * 100, cs.get(o, 0) / n_s * 100
        if pa < 0.5 and ps < 0.5:
            continue
        bar_a = "#" * int(pa)
        bar_s = "-" * int(ps)
        print(f"  {o:>4}  act {pa:>5.1f} {bar_a:<24} sim {ps:>5.1f} {bar_s}")


#: Lines a book actually offers, by stat. Calibration is only interesting
#: where someone will take the other side.
LINES = {
    "outs": (11.5, 14.5, 15.5, 17.5, 18.5, 20.5),
    "k": (3.5, 4.5, 5.5, 6.5, 7.5, 8.5),
    # Every counting stat the boxscore cache carries and the simulation
    # already emits. These are not all liquid markets — the point is
    # DIAGNOSTIC COVERAGE. Each one isolates a different part of the model,
    # so a defect that hides in the outs total shows up plainly somewhere
    # else: walks test the BB path alone, hits test BABIP and the hit mix,
    # earned runs test the base-running rules that nothing else checks.
    "h": (3.5, 4.5, 5.5, 6.5, 7.5),
    "bb": (0.5, 1.5, 2.5, 3.5),
    "hr": (0.5, 1.5, 2.5),
    "er": (1.5, 2.5, 3.5, 4.5),
}

#: Boxscore column and StartResult attribute for each stat. Earned runs, not
#: runs: the simulation models no errors, so every run it produces is earned
#: by construction and comparing against total runs would charge it for
#: defence it never simulated.
_STAT_COL = {"outs": "o", "k": "k", "h": "h", "bb": "bb", "hr": "hr",
             "er": "er"}
_STAT_ATTR = {"outs": "outs", "k": "k", "h": "h", "bb": "bb", "hr": "hr",
              "er": "earned"}


def per_start_probs_all(stat: str, lines, season=None, before=None,
                        since=None, n_sims=300, seed=0, adjusted=True):
    """{line: [(actual, p_over)]} — every line off ONE set of draws.

    Simulating separately per line is the obvious version and it is six
    times the work for an identical answer: the draws do not depend on the
    threshold. It also makes the lines inconsistent with each other, since
    independent draws can put P(over 15.5) below P(over 17.5) by noise
    alone. Sharing the draws makes the curve monotone by construction.

    This is the shape a reliability check needs, and `run()` cannot provide
    it: that flattens every simulation into one pool, which measures whether
    the LEAGUE distribution is right. A pool can match perfectly while every
    individual start is priced wrong and the errors cancel.
    """
    lg = sim.league(season)
    pairs = paired_cases(season=season, before=before, since=since,
                         rates_before=before)
    pens = rate_src.bullpens(lg, before=before)
    key, attr = _STAT_COL[stat], _STAT_ATTR[stat]
    out = {ln: [] for ln in lines}
    # BOTH starters off the SAME simulated games. Previously each start was
    # its own one-sided simulation, which could not see its team's runs, so
    # `Hook.per_margin` was unreachable and every reliability table in the
    # notes was measured against games that were not games.
    for pair in pairs.values():
        rng = random.Random(seed)
        draws = [replay(pair, lg, pens, rng, apply_leash=adjusted)
                 for _ in range(n_sims)]
        for idx, side in ((0, "away_sp"), (1, "home_sp")):
            s = pair[idx][0]
            vals = [getattr(getattr(d, side), attr) for d in draws]
            for ln in lines:
                out[ln].append(
                    (s[key], sum(1 for v in vals if v > ln) / len(vals)))
    return out


def per_start_probs(stat: str, line: float, **kw):
    """Single-line convenience wrapper over `per_start_probs_all`."""
    return per_start_probs_all(stat, [line], **kw)[line]


def reliability(stat: str, season=None, before=None, since=None,
                n_sims=300, bins=5, seed=0, adjusted=True) -> None:
    """Does a simulated 60% actually win 60% of the time?

    The only calibration test that matters for pricing. A model can nail the
    league distribution and still be useless per bet, and the reverse is the
    thing being checked here: bucket every start by what the simulation said
    and compare to how often it actually happened.

    Brier score is reported alongside. 0.25 is what a coin flip scores;
    lower is better, and a model that beats the base rate is doing real work
    even when its calibration is imperfect.
    """
    all_rows = per_start_probs_all(stat, LINES[stat], season=season,
                                   before=before, since=since,
                                   n_sims=n_sims, seed=seed,
                                   adjusted=adjusted)
    for line in LINES[stat]:
        rows = all_rows[line]
        if not rows:
            print(f"  {stat} {line}: no cases")
            continue
        n = len(rows)
        base = sum(1 for a, _ in rows if a > line) / n
        brier = sum((p - (1 if a > line else 0)) ** 2 for a, p in rows) / n
        brier_base = base * (1 - base)
        mean_p = sum(p for _, p in rows) / n
        print(f"\n  {stat} over {line}   n={n}  actual {base:.1%}  "
              f"model {mean_p:.1%}  bias {mean_p - base:+.1%}")
        print(f"    Brier {brier:.4f} vs {brier_base:.4f} "
              f"base-rate  ({(brier_base - brier) / brier_base:+.1%})")
        rows_sorted = sorted(rows, key=lambda r: r[1])
        per = max(1, n // bins)
        print(f"    {'bucket':<14}{'n':>5}{'said':>8}{'happened':>10}"
              f"{'gap':>8}")
        for i in range(0, n, per):
            chunk = rows_sorted[i:i + per]
            if len(chunk) < max(10, per // 2):
                continue
            said = sum(p for _, p in chunk) / len(chunk)
            hap = sum(1 for a, _ in chunk if a > line) / len(chunk)
            lo, hi = chunk[0][1], chunk[-1][1]
            print(f"    {f'{lo:.2f}-{hi:.2f}':<14}{len(chunk):>5}"
                  f"{said:>8.1%}{hap:>10.1%}{hap - said:>+8.1%}")


def _auc(rows) -> float:
    """Rank-based AUC. rows = [(won: bool, p: float)]."""
    pos = [p for w, p in rows if w]
    neg = [p for w, p in rows if not w]
    if not pos or not neg:
        return 0.5
    ordered = sorted(((p, w) for w, p in rows), key=lambda x: x[0])
    ranks, i = {}, 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][0] == ordered[i][0]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    rsum = sum(ranks[k] for k, (_, w) in enumerate(ordered) if w)
    n1, n0 = len(pos), len(neg)
    return (rsum - n1 * (n1 + 1) / 2) / (n1 * n0)


def _prior_starts(conn, name: str, before: str, last: int = 10,
                  stat: str = "outs") -> list[int]:
    """A pitcher's own last `last` STARTS strictly before a date.

    `is_starter = 1` matters here as much as anywhere: feeding the estimator
    relief appearances is the Drew Anderson bug, where five starts hidden in
    43 outings made his "last ten" read 6.5 outs.
    """
    col = "p.outs_recorded" if stat == "outs" else "p.k"
    rows = conn.execute(f"""
        select {col} v
        from mlb_pitching p join games g on g.game_id = p.game_id
        where p.player_name = ? and g.date < ? and g.sport = 'mlb'
          and g.status = 'Final' and p.is_starter = 1
        order by g.date desc limit ?""", (name, before, last)).fetchall()
    return [r["v"] for r in rows][::-1]


def versus_estimator(cutoff: str, stat="outs", n_sims=200, seed=0,
                     min_prior=4, refit=True) -> None:
    """The decisive comparison: simulation against the six-start estimator.

    Both are asked the same question — P(this start goes over this line) —
    on starts neither has seen, with everything trained strictly before
    `cutoff`. The estimator gets exactly what it gets in production: that
    pitcher's own recent starts, shrunk toward a prior.

    Brier and AUC are reported because they answer different questions.
    Brier asks whether the numbers are RIGHT; AUC asks only whether they
    ORDER the starts correctly. A model can rank well and be miscalibrated,
    which is still useful — you can recalibrate a ranking, you cannot
    rescue a model that has no signal at all.
    """
    from src.context import estimate

    # The leash is part of the model and must be built on the training
    # window too. Without this the rates are clean and the offsets are not,
    # which is the quiet kind of leakage: everything LOOKS like a holdout
    # because the obvious knob was set correctly.
    if refit:
        from src.context import leash as leash_mod
        leash_mod.build(before=cutoff)
        sim.reload_offsets()

    lg = sim.league()
    pairs = paired_cases(since=cutoff, rates_before=cutoff)
    pens = rate_src.bullpens(lg, before=cutoff)
    cases = [c for pair in pairs.values() for c in pair]
    key = _STAT_COL[stat]
    print(f"holdout from {cutoff}: {len(cases)} starts\n")

    with db.connect() as conn:
        priors = {nm: _prior_starts(conn, nm, cutoff, stat=stat)
                  for nm in {p.name for _, p, _ in cases}}

    for line in LINES[stat]:
        sim_rows, est_rows = [], []
        for pair in pairs.values():
            for idx, side in ((0, "away_sp"), (1, "home_sp")):
                s, pitcher, _lineup = pair[idx]
                hist = priors.get(pitcher.name) or []
                if len(hist) < min_prior:
                    continue
                won = s[key] > line
                rng = random.Random(seed)
                hits = 0
                for _ in range(n_sims):
                    r = getattr(replay(pair, lg, pens, rng), side)
                    hits += (r.outs if stat == "outs" else r.k) > line
                sim_rows.append((won, hits / n_sims))
            d = estimate.over_under(hist, line, "over")
            if d:
                est_rows.append((won, d["p"]))

        if len(sim_rows) < 30:
            continue
        base = sum(1 for w, _ in sim_rows if w) / len(sim_rows)

        def brier(rows):
            return sum((p - (1 if w else 0)) ** 2 for w, p in rows) / len(rows)

        bb = base * (1 - base)
        print(f"  {stat} over {line}  n={len(sim_rows)}  base {base:.1%}")
        print(f"    {'':<12}{'Brier':>9}{'vs base':>10}{'AUC':>8}")
        print(f"    {'sim':<12}{brier(sim_rows):>9.4f}"
              f"{(bb - brier(sim_rows)) / bb:>+10.1%}"
              f"{_auc(sim_rows):>8.3f}")
        if len(est_rows) >= 30:
            print(f"    {'estimator':<12}{brier(est_rows):>9.4f}"
                  f"{(bb - brier(est_rows)) / bb:>+10.1%}"
                  f"{_auc(est_rows):>8.3f}")


def loss(res: dict) -> float:
    """How far the simulated hook is from the observed one.

    Weighted on the hazard curve rather than on mean outs, because a
    simulator can land the mean while getting every threshold wrong — which
    is the failure mode that matters for pricing a 20.5 line. Boundary share
    is included so a hook that reaches the right length by pulling everyone
    mid-inning scores badly.
    """
    a_outs = [a["o"] for a in res["actual"]]
    s_outs = [r.outs for r in res["sim"]]
    if not a_outs or not s_outs:
        return 1e9
    ha, hs = _hazard(a_outs), _hazard(s_outs)
    tot = sum((ha[i] - hs.get(i, 0.0)) ** 2 for i in ha if i <= 7) * 4.0

    def share(vals, fn):
        return sum(1 for v in vals if fn(v)) / len(vals)

    for fn in (lambda v: v >= 18, lambda v: v < 15, lambda v: v >= 21):
        tot += (share(a_outs, fn) - share(s_outs, fn)) ** 2
    tot += (_boundary(a_outs) - _boundary(s_outs)) ** 2
    n_a, n_s = len(a_outs), len(s_outs)
    tot += ((sum(a_outs) / n_a - sum(s_outs) / n_s) / 10.0) ** 2
    return tot


def tune(season=None, starts=500, sims=30, seed=0) -> sim.Hook:
    """Coordinate descent over the hook parameters.

    Not elegant and not global, but the surface is smooth in each parameter
    and the whole search costs a couple of minutes. The point is that these
    numbers end up FITTED to the league's own hook behaviour instead of
    asserted, which is the difference between this module and the constants
    table in NOTES that keeps producing bugs.
    """
    grid = {
        "intercept": [-7.0, -6.0, -5.2, -4.6, -4.0, -3.2, -2.4],
        "per_inning": [0.3, 0.45, 0.6, 0.8, 1.0, 1.3],
        "per_run": [0.1, 0.2, 0.3, 0.45, 0.6],
        "pitch_center": [80.0, 86.0, 92.0, 98.0],
        "pitch_scale": [8.0, 11.0, 15.0],
        "mid_intercept": [-6.5, -5.5, -5.0, -4.4, -3.8],
        "mid_per_run": [0.15, 0.3, 0.45],
        "mid_per_runner": [0.25, 0.55, 0.9, 1.3],
        "mid_per_damage": [0.0, 0.15, 0.25, 0.4],
        "per_baserunner": [0.0, 0.1, 0.2, 0.35],
    }
    best = sim.Hook()
    best_loss = loss(run(season=season, n_sims=sims, max_starts=starts,
                         hook=best, seed=seed))
    print(f"start loss {best_loss:.5f}  {best}")
    for sweep in range(2):
        for param, values in grid.items():
            for v in values:
                cand = sim.Hook(**{**best.__dict__, param: v})
                if cand.__dict__ == best.__dict__:
                    continue
                lo = loss(run(season=season, n_sims=sims, max_starts=starts,
                              hook=cand, seed=seed))
                if lo < best_loss:
                    best, best_loss = cand, lo
                    print(f"  sweep{sweep} {param}={v} -> {lo:.5f}")
    print(f"\nbest loss {best_loss:.5f}")
    for k, v in best.__dict__.items():
        print(f"  {k:<18}{v}")
    return best




