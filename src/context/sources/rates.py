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

The constants WERE approximations from the public literature. They have now
been MEASURED on this league by `src.context.stabilise` — split-half over
odd/even games, Spearman-Brown corrected — and the imported values were
wrong in both directions at once:

                 measured   imported
    batter  k        32         70
    batter  bb       80        170
    batter  hr      160        350
    batter  babip   184        500
    pitcher k        57         70
    pitcher bb      138        170
    pitcher hr      934        350

Two findings. Batter rates were over-shrunk by roughly 2.2x across the
board, which matters because a leverage screen puts LINEUP QUALITY as the
largest single source of separation between clubs (~0.47 runs) — the model
was averaging away half of the only thing generating separation. And a
pitcher's home-run rate was UNDER-shrunk by 2.7x, manufacturing separation
that is not there.

ONE TABLE FOR TWO POPULATIONS WAS THE BIGGEST ERROR. `_shrink` keyed only on
the stat name, so a batter's HR rate and a pitcher's HR rate shared 350.
Measured, they are 160 and 934 — a factor of six apart.

CAVEAT ON THE MEASUREMENT. Odd and even games share park, role and
teammates, so the split-half correlation carries persistent CONTEXT as well
as talent. These are therefore lower bounds on true-talent stabilisation
(batter BABIP measures 184 against ~800 in the literature). For this use
that is defensible — the model predicts a player in his context, not his
context-free talent — but it is the reason `USE_MEASURED_STABILISE` exists
rather than the constants simply being replaced.
"""
from __future__ import annotations

from src import db
from src.context import scope

#: Plate appearances at which each rate is worth half its own weight
#: against the league. Higher means slower to trust.
#:
#: IMPORTED, and kept as the legacy path. See the module docstring.
STABILISE = {
    "k_pct": 70,
    "bb_pct": 170,
    "hr_pct": 350,
    "babip": 500,
}

#: MEASURED on this league by `src.context.stabilise`, split by population
#: because batters and pitchers are not the same problem.
#:
#: A PITCHER'S STRIKEOUT RATE STABILISES AT 132, NOT 57 (2026-08-28). The 57
#: was measured on half a season and never re-measured after the four-season
#: load; `stabilise` reads 132 on the data now on disk. Three independent
#: lines agree, which is why this is a replacement and not a tuning:
#:
#:     stabilise, split-half over 406 starters      132
#:     method of moments on the 2026 spread          98
#:     holdout discrimination, k = 57 x 2.3         131
#:
#: THE THIRD IS A CONFIRMATION, NOT THE FIT. `scratchpad/unshrink --only
#: pit:k_pct` sweeps the constant on starts AFTER a cutoff with rates trained
#: only before it, and strikeout discrimination peaks at x2.3 (+0.0135,
#: +9.5 sigma) — the same place the split-half puts it. Replicated on a
#: second cutoff, 2026-06-01, at +2.6. Past x3.5 the K gain flattens and
#: OUTS starts to break (-2.5 at x5.0), so the peak is not an artifact of
#: scoring one channel.
#:
#: THE BATTER ROW IS THE CURRENTLY MEASURED ONE (2026-08-28), replacing
#: 32/80/160/184, which `stabilise` produced on less data. babip moved most
#: and for a second reason: its numerator was H against a denominator that
#: excludes home runs, where BABIP is (H - HR)/(AB - K - HR). Corrected, the
#: batter figure is 447 rather than the 250 the contaminated version gave,
#: and it is well determined — r_half 0.277 over 662 hitters puts k between
#: 371 and 550 across one standard error, with the shipped 184 far outside.
#:
#: IT EARNS NOTHING MEASURABLE AND IT SHIPS ANYWAY, which is the same
#: standard pitcher k_pct was held to. Paired F5 CRPS -0.0026 +/- 0.0075
#: (neutral) and the differentiation slopes come out MIXED — two of four
#: toward 1, two away. An earlier run of this A/B reported the row COSTING
#: F5 at +1.8 sigma and a clean four-of-four differentiation win; both were
#: the broken babip numerator and both are withdrawn.
#:
#: A PITCHER'S BABIP WAS NEVER MEASURED AT ALL (2026-08-28). `stabilise`
#: printed a babip row for BATTERS and omitted it for pitchers with no
#: reason given, so the 500 here is the legacy all-players import — the same
#: class of unmeasured number that left k_pct at 57. Counted now over 365
#: starters: split-half 0.057, implied k 3068. A pitcher's balls-in-play
#: rate barely repeats, which is the standing DIPS result and is already
#: encoded next door in `PRIOR_DECAY["babip"] = 0.0`.
#:
#: THE POINT ESTIMATE IS SOFT AND THE DIRECTION IS NOT. At r_half 0.057 with
#: a standard error of 0.052 over 365 arms, k runs from about 1,500 to
#: 36,000 across one standard error — but EVERY value consistent with the
#: data is at least 3x the shipped 500. The split half also shares park,
#: defence and teammates between its halves, which INFLATES the correlation,
#: so the true-talent constant is higher still. Do not re-tune this to a
#: third decimal; it is a direction, not a knife edge.
#:
#: SCORED: F5 CRPS +0.0011 +/- 0.0034 (neutral, the bar for a measurement
#: replacing a guess), hits discrimination flat, home-run discrimination
#: +0.0254 (+3.2 sigma) and monotone across the sweep.
#:
#: HOME RUNS ARE DELIBERATELY LEFT ALONE AT 934, and the reason is the rule
#: about contradictory numbers. `stabilise` now reads 2130 for pitcher
#: hr_pct — but method of moments on the same arms says 946, and the holdout
#: sweep says raising it is WORSE (-2.6 sigma at x2.0). Three answers that
#: do not agree, on a channel where a starter's season is ~15 events. Until
#: they are reconciled the shipped value stands. See
#: `scratchpad/hr_spread.py`.
STABILISE_MEASURED = {
    "bat": {"k_pct": 51, "bb_pct": 122, "hr_pct": 193, "babip": 447},
    "pit": {"k_pct": 132, "bb_pct": 138, "hr_pct": 934, "babip": 3068},
}

#: Off restores the imported constants exactly, for both populations. Every
#: mechanism in this project stays separately scoreable.
USE_MEASURED_STABILISE = True


#: Balls in play, from a boxscore, are OVERCOUNTED by this much.
#:
#: `bip = outs_recorded + hits - strikeouts - home runs` counts OUTS, and
#: outs are not balls in play. A double play is one ball in play and TWO
#: outs; a caught stealing or pickoff is an out and NO ball in play. Both
#: inflate the denominator, which deflates BABIP.
#:
#: COUNTED PER PLAY off play-by-play, matched on the same games
#: (`scratchpad/babip_def.py`):
#:
#:     2026 starters   boxscore 57,079   counted 55,225   ratio 1.0336
#:     2025 starters   boxscore 77,378   counted 74,898   ratio 1.0331
#:     2025 relievers  boxscore 55,842   counted 54,125   ratio 1.0317
#:
#: The NUMERATOR is exact — 15,920 non-homer hits from both sources on the
#: matched games — so this is purely a denominator error. Note the matched
#: game set matters: the boxscore is missing starter rows for 67 games of
#: 2026, and comparing unmatched makes the 3.4% inflation cancel against a
#: 3.3% shortfall and read as 1.001.
#:
#: WHY IT SHOWS UP IN BABIP AND NOWHERE ELSE. The same inflation understates
#: k_pct, bb_pct and hr_pct by ~2% too, but those resolve through log5
#: AGAINST A LEAGUE MEASURED THE SAME WAY, so the error very largely cancels
#: in the ratio. BABIP's LEVEL survives into the simulation as an absolute
#: rate. That is why the channel decomposition showed strikeouts, walks and
#: home runs all within 1% and singles 4.9% short.
#:
#: 1,763 second-outs-of-a-double-play plus 211 outs on the bases account for
#: the 1,854 phantom balls in play in 2026.
BIP_PER_OUT_UNIT = 1.0333

#: Off restores the boxscore denominator exactly.
USE_COUNTED_BIP = True


def balls_in_play(bf: float, k, bb, hr) -> float:
    """Balls in play behind a pitcher's line, corrected for the out count."""
    raw = bf - (k or 0) - (bb or 0) - (hr or 0)
    if raw <= 0:
        return 0.0
    return raw / BIP_PER_OUT_UNIT if USE_COUNTED_BIP else raw


def stabilise_k(stat: str, who: str = "bat") -> float:
    """The shrinkage constant `_shrink` would use. One place, not three."""
    if USE_MEASURED_STABILISE:
        return (STABILISE_MEASURED.get(who, {}).get(stat)
                or STABILISE.get(stat, 200))
    return STABILISE.get(stat, 200)


def _shrink(observed: float | None, lg: float, n: float, stat: str,
            who: str = "bat", k_override: float | None = None) -> float:
    """Weighted average of the player's rate and the league's.

    `who` selects the population — "bat" or "pit". It has a default because
    the batter path is the larger caller, but passing the wrong one is a
    silent six-fold error on home runs, so every call site names it.

    `k_override` exists for ONE caller and it is exact algebra, not a knob.
    Pooling three sources at once,

        (n*own + m*prior + k*lg) / (n + m + k)

    is identical to shrinking `own` toward the two-source target
    `T = (m*prior + k*lg)/(m+k)` with the constant `m + k` in place of `k`.
    So `shrink_target` builds T and the call site passes `m + k` here. See
    `PRIOR_EFFECTIVE_PA`. Nothing else may pass it.
    """
    if observed is None or n <= 0:
        return lg
    k = stabilise_k(stat, who) if k_override is None else k_override
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


#: Drop postseason games from every rate aggregate. OFF until measured.
#:
#: THE ASYMMETRY IS THE REASON THIS EXISTS. The current season has no
#: postseason yet and every prior season has a complete one, so October
#: innings enter the PRIOR and never the current line it is shrunk against.
#: They are also not like the rest: a playoff pitcher faces playoff lineups,
#: which drags his rates the same way every time. Measured 2026-08-26,
#: excluding October moves K% by more than half a point for about 8% of
#: arms, up to 3.1 points, and always in the same direction:
#:
#:     Aroldis Chapman 2023   0.3833 -> 0.4143
#:     Kris Bubic 2024        0.2917 -> 0.3197
#:     Daniel Palencia 2025   0.2667 -> 0.2913
#:
#: `_prior_adjusted` scales by the league, which absorbs SOME of this — but
#: only some, because the league's postseason share is ~2% while a
#: contender's ace runs 10%+. It lands hardest on exactly the arms worth
#: pricing.
EXCLUDE_POSTSEASON = False

#: First and last postseason date per season, inclusive. TRANSCRIBED rather
#: than inferred, because a rule that looked right was wrong at the edges.
#:
#: The rule tried first — "October onward, a day with fewer than eight
#: games" — fails in both directions and the failures are invisible:
#:
#:   * 2025's Wild Card round opened on SEPTEMBER 30. A month test misses
#:     four postseason days entirely.
#:   * 2024-09-30 carries two games and they are REGULAR SEASON, a rained-out
#:     doubleheader that decided a playoff place. A game-count test applied
#:     in September throws them away.
#:   * 2023-10-01 carries fifteen games and is the last regular-season day,
#:     so a bare month test throws away a full slate.
#:
#: DERIVED FROM THE SCHEDULE AND CHECKED AGAINST IT: the last regular-season
#: day is the final full slate (14-16 games) and the postseason opens at the
#: next date, which is 2 to 4 games. Verified per season against the day
#: counts around the boundary. 2026 has no postseason on record — the season
#: is in progress, which is the entire reason this filter matters.
POSTSEASON_RANGE = {
    2023: ("2023-10-03", "2023-11-01"),
    2024: ("2024-10-01", "2024-10-30"),
    2025: ("2025-09-30", "2025-11-01"),
}


def postseason_clause(alias: str = "g") -> str:
    """SQL excluding every postseason date, as inclusive ranges."""
    return " ".join(
        f"and not ({alias}.date >= '{a}' and {alias}.date <= '{b}')"
        for a, b in POSTSEASON_RANGE.values())


def _where(season: int | None, before: str | None) -> str:
    bits = []
    # None means THIS SEASON, not every season — see `context.scope`. Pass
    # `scope.ALL_SEASONS` to pool history on purpose.
    season = scope.resolve(season)
    if season:
        bits.append(f"and g.date like '{season}%'")
    if before:
        # Strictly before, so a brief never sees the game being bet on.
        bits.append(f"and g.date < '{before}'")
    if EXCLUDE_POSTSEASON:
        bits.append(postseason_clause("g"))
    return " ".join(bits)


#: Shrink a thin current-season line toward the pitcher's OWN PAST SEASONS
#: instead of toward the league. ON since 2026-08-26, over `PRIOR_SEASONS`
#: seasons at `PRIOR_DECAY`.
#:
#: This is the same arithmetic `_shrink` already does, aimed at a better
#: target. A man with 180 innings last year is a far better guess for what
#: he is than "average major league starter", and the code used to throw
#: that away in favour of the worse guess. It decays on the calendar for
#: free: in April his prior dominates because he has nothing else, by
#: August his own numbers swamp it — which is why the mechanism is
#: believable and not just the number.
#:
#: SCORED ON OUTCOMES, `scratchpad.memory`, paired on identical games and
#: seeds, against simulating from this season alone:
#:
#:     cut 2026-05-01       none    prior(1)   prior(3)
#:       K correlation    0.3342     0.3843     0.3854
#:       K CRPS           1.3467     1.3195     1.3117
#:       outs CRPS        2.1667     2.1799     2.1620
#:       K bias          +0.0867    +0.1360    +0.1348
#:
#: The May cut is where it is worth having and July is nearly a wash, which
#: is the mechanism arguing for itself: a prior can only matter while the
#: current line is thin.
#:
#: THE COST IS K BIAS, +0.087 to +0.135, and it is accepted rather than
#: unnoticed. A flat POOL of the same seasons buys slightly more correlation
#: for +0.308 of bias — over twice the error for a fraction more discrimination
#: — and gets WORSE as seasons are added, because it weights an April 2023
#: inning exactly like an August 2026 one. The prior does not.
USE_PRIOR_SEASON = True


#: How many prior seasons the shrink target may draw on, and how fast one
#: fades. Season S-k enters at weight `PRIOR_DECAY[stat] ** (k-1)` times its
#: own batters faced, so 1 season back is always full weight and the decay
#: only governs what the ones behind it are worth.
PRIOR_SEASONS = 3

#: MEASURED by `scratchpad.decay` on 2023-2026, and per stat because the
#: stats differ enormously in how long a pitcher stays himself. Each is the
#: weight at which the blended prior best predicts the season it is aimed
#: at — a property of the PREDICTOR, scored against the pitcher's next-season
#: rate. Nothing that settles is anywhere near it.
#:
#:     stat      w=0     best   at w    n
#:     k_pct    0.645   0.651   0.3   1,077
#:     bb_pct   0.523   0.542   0.5   1,077
#:     hr_pct   0.236   0.247   0.7   1,077
#:     babip    0.142   0.142   0.0     868
#:
#: The maxima are BROAD and the gains are small — this is not a knife edge
#: and it should not be re-tuned to a third decimal. BABIP is 0.0 because it
#: falls monotonically: a pitcher's balls-in-play rate barely persists one
#: year (true correlation 0.43 after correcting for sampling noise) and is
#: indistinguishable from noise at two.
#:
#: THE OTHER GAIN, AND IT IS NOT COVERAGE OF GAMES. 7.6% of pitcher-seasons
#: have NO last season at all — an elbow, a year in the minors — and today
#: they shrink to league average. For them a two-year-old K rate predicts at
#: 0.587 against the 0.645 a one-year-old one manages for everybody else:
#: nearly the full signal, for a population currently getting none of it.
#: On the 2026 board that is 22 of the 467 arms with 100+ batters faced and
#: 77 of the thin ones. It does NOT make a single extra game priceable —
#: whether a game can be priced turns on both starters having a
#: current-season line, which the prior does not touch — so it shows up as
#: a better number on those arms and nowhere in the case counts.
PRIOR_DECAY = {"k_pct": 0.3, "bb_pct": 0.5, "hr_pct": 0.7, "babip": 0.0}


#: Shrink a thin pitcher's BABIP toward HIS CLUB'S defence rather than
#: toward a neutral league. OFF until measured.
#:
#: THE GAP IT FILLS. There is no team defence anywhere in this simulator.
#: Balls in play become outs at one league rate, double plays turn at one
#: league rate, and a club with the best infield in baseball is
#: indistinguishable from the worst. Savant's team Outs Above Average has
#: been fetched and cached by `sources/defense.py` for months and nothing
#: has ever read it into the model.
#:
#: IT PROJECTS, which is the gate that matters — a club number that does not
#: persist cannot be used to price tomorrow. Team OAA correlates +0.632
#: between 2025 and 2026 across all thirty clubs, comparable to the bullpen
#: role split-half (+0.55..+0.78) that passed, and far above per-club
#: advancement (+0.11..+0.38) which failed.
#:
#: AND IT IS BIG ENOUGH TO MATTER. OAA runs -54 to +64 with an sd of 23
#: across clubs, against roughly 4,100 balls in play a club fields in a
#: season. One sd is therefore ~0.0056 of BABIP against a league 0.2778,
#: and best-to-worst is ~0.029 — about 0.07 runs a game per side for one sd,
#: which clears the ~0.05 leverage bar.
#:
#: WHY IT IS A SHRINK TARGET AND NOT A MULTIPLIER, which is the whole design
#: and the reason this is not the park mistake again. A pitcher's OWN
#: measured BABIP already contains his own defence — he has been throwing in
#: front of those gloves all season — so layering OAA on top would count it
#: twice, exactly as `NEUTRALISE_PARK` being off counted park 1.5x. What is
#: actually lost is in the SHRINKAGE: a thin line pulled toward the league
#: is handed a NEUTRAL defence it does not have. So the defence moves the
#: target, never the observation, and a pitcher with a full season of his
#: own is untouched.
USE_TEAM_DEFENCE = False

#: Balls in play a club fields in a full season, the denominator that turns
#: an OAA count into a rate. Counted from the pitching table rather than
#: assumed; see `_defence_targets`.
_DEFENCE_CACHE: dict = {}


def _defence_targets(season) -> dict[str, float]:
    """{team abbr: BABIP this club's gloves SAVE against a neutral defence}.

    Positive means a good defence: balls that would have been hits become
    outs, so the BABIP allowed in front of it is LOWER by this much.

    OAA is a COUNT of outs above average, so it becomes a rate by dividing
    by the balls in play that club actually fielded. A positive OAA means
    more balls became outs, which is a LOWER BABIP allowed — hence the sign.

    Returns {} on any failure, and an unmapped club falls through to the
    league. That is deliberate and follows the standing rule: a guessed
    value must not move the estimate in the wrong direction, so a club with
    no OAA row gets league-neutral rather than a neighbour's number. The 17
    unmapped clubs in the pitching table are exhibition, international-series
    and rehab affiliates, not major-league defences.
    """
    from src.context import scope
    yr = scope.resolve(season) or scope.CURRENT_SEASON
    if yr in _DEFENCE_CACHE:
        return _DEFENCE_CACHE[yr]
    try:
        from src.context import sim
        from src.context.sources import defense, statsapi
        oaa = defense.team_defense(year=yr)
        abbr = statsapi.team_abbrs(yr)
        sim.league(yr)          # fail fast if the season has no rows
    except Exception:
        _DEFENCE_CACHE[yr] = {}
        return {}

    def _bip(c):
        return {r["team"]: r["bip"] for r in c.execute(
            "select p.team team,"
            " sum(p.outs_recorded + p.h + p.bb - p.k - p.bb - p.hr) bip"
            " from mlb_pitching p join games g on g.game_id = p.game_id"
            " where g.sport = 'mlb' and g.status = 'Final'"
            f" and g.date like '{yr}%' group by p.team") if r["team"]}

    bip = _with(_bip)
    out = {}
    for tid, row in oaa.items():
        team = abbr.get(tid)
        n = bip.get(team) or 0
        if not team or n < 500:
            continue
        out[team] = (row.get("oaa") or 0) / n
    _DEFENCE_CACHE[yr] = out
    return out


def _pitcher_teams(season, before, conn=None) -> dict[str, str]:
    """{player_name: the club he threw the most innings for}.

    By outs rather than appearances so a rehab stint or a September cameo
    does not outvote the season, and it is the club whose gloves were behind
    him for most of the line being shrunk.
    """
    q = ("select p.player_name name, p.team team,"
         " sum(p.outs_recorded) o"
         " from mlb_pitching p join games g on g.game_id = p.game_id"
         f" where g.sport = 'mlb' and g.status = 'Final' {_where(season, before)}"
         " group by p.player_name, p.team")

    def _run(c):
        return c.execute(q).fetchall()

    best: dict[str, tuple[int, str]] = {}
    for r in (_run(conn) if conn is not None else _with(_run)):
        o = r["o"] or 0
        if r["team"] and o > best.get(r["name"], (-1, ""))[0]:
            best[r["name"]] = (o, r["team"])
    return {n: t for n, (_o, t) in best.items()}


#: Set by `set_prior`. Held at module level rather than threaded through
#: every call site because `build_cases` reaches `pitcher_rates` through
#: four layers, and a flag that has to be passed by hand at each one is a
#: flag that will be forgotten at one of them.
_PRIOR: dict = {}

#: Which season `_PRIOR` was built to serve, so a prior aimed at 2026 is not
#: silently reused while building 2025's rates. Both happen in one process
#: — `set_prior` itself walks back through the seasons.
_PRIOR_FOR: int | None = None

#: Re-entrancy guard. `set_prior` builds the prior by calling
#: `pitcher_rates`, which is the function that asks for the prior.
_LOADING = False


def _ensure_prior(season) -> dict:
    """The prior for `season`, loaded on first use.

    WITHOUT THIS THE FLAG REACHES NOTHING. Only the experiment ever called
    `set_prior`, so `USE_PRIOR_SEASON = True` on its own would leave `_PRIOR`
    empty and every rate would shrink to the league exactly as before — a
    shipped mechanism that is switched on and not wired, which is a failure
    mode this project has hit twice and can only detect by asserting on it.
    See `tests/test_wiring.py`.

    Returns {} rather than loading when the caller asked for pooled history:
    a pooled query already contains the prior seasons, and shrinking pooled
    rates toward a prior built from the same rows would count them twice.
    """
    global _PRIOR, _PRIOR_FOR
    if _LOADING:
        return {}
    resolved = scope.resolve(season)
    if resolved is None:
        return {}
    if _PRIOR and _PRIOR_FOR == resolved:
        return _PRIOR
    set_prior(resolved - 1)
    _PRIOR_FOR = resolved
    return _PRIOR


def defence_delta(team: str | None, season=None) -> float:
    """BABIP this club's gloves save against a neutral defence.

    ONE ENTRY POINT, used in two OPPOSITE directions and that is the whole
    design:

      * `rates` NEUTRALISES — a pitcher's observed BABIP was earned in front
        of his own club, so the delta is added back to recover what he would
        have allowed behind an average defence. That is his talent.
      * `game.build_side` APPLIES — whoever takes the mound tonight has
        TONIGHT'S defence behind him, so the delta comes back off.

    Splitting it this way is what makes relievers free: the defence belongs
    to the SIDE, not to the pitcher, so every arm that enters gets it without
    a second code path. It also fixes the traded pitcher, who carries his old
    club's gloves in his rates and pitches in front of new ones.

    This is the `NEUTRALISE_PARK` lesson applied before it cost anything: a
    factor that is already inside the observed rate must be removed before it
    is applied, or it is counted twice.
    """
    if not USE_TEAM_DEFENCE or not team:
        return 0.0
    return _defence_targets(season).get(team.upper(), 0.0)


def shrink_target(name: str, team: str | None, stat: str, lg: dict,
                  prior: dict, dfn: dict) -> float:
    """What a PITCHER's rate is pulled toward. One function, both callers.

    THIS EXISTS BECAUSE THERE WERE TWO. `pitcher_rates` had a `_t` closure
    that consulted the prior and the club's defence; `bullpens` carried a
    copy of the same shrink block with `lg[stat]` hardcoded. So every
    improvement to the target reached STARTERS ONLY — including the
    multi-season prior shipped the same day — and reached them in the
    population where it matters least. A reliever's median line is 106
    batters faced against a starter's 480, so 38% of a reliever's strikeout
    rate IS this target against 11% of a starter's.

    Two stages, in this order:

      1. His CLUB'S defence replaces the league for BABIP, because a thin
         line pulled toward the league is handed a NEUTRAL defence it does
         not have. Never applied to his own observed rate — that already
         contains his own gloves, and layering it on is the park mistake.
      2. His OWN past seasons replace whatever that came to, shrunk by their
         own effective sample so a thin prior cannot shout down the evidence
         behind it.
    """
    base = lg[stat]
    p = prior.get(name)
    if not p:
        return base
    m = prior_effective_pa(name, stat, prior)
    n = p.get("pa", 0) if m is None else m
    return _shrink(p[stat], base, n, stat, who="pit")


def prior_effective_pa(name: str, stat: str, prior: dict) -> float | None:
    """The COUNTED effective sample of this pitcher's prior, or None.

    None means "not counted for this stat" and the shipped construction is
    left alone — it is not a zero and it is not a guess.
    """
    if not USE_MEASURED_PRIOR_PA or name not in prior:
        return None
    return PRIOR_EFFECTIVE_PA.get(stat)


def pool_k(name: str, stat: str, prior: dict) -> float | None:
    """`m + k` for the second shrink, or None to leave `_shrink` alone.

    See `_shrink`'s `k_override`: this is the denominator that makes the
    two-stage shrink equal to pooling own, prior and league at once.
    """
    m = prior_effective_pa(name, stat, prior)
    return None if m is None else stabilise_k(stat, "pit") + m


def set_prior(season: int | None, lg_now: dict | None = None,
              seasons: int | None = None) -> int:
    """Load and league-adjust the seasons BEFORE `season` as the shrink target.

    `season` is the most recent prior season — pass 2025 while pricing 2026.
    `seasons` is how many to walk back from it, defaulting to
    `PRIOR_SEASONS`; 1 restores the single-season behaviour exactly.

    Returns how many pitchers are in it. Passing None clears it, which is
    what every caller that is not testing this should do.
    """
    global _PRIOR, _PRIOR_FOR, _LOADING
    _PRIOR = {}
    _PRIOR_FOR = None
    if season is None:
        return 0
    from src.context import sim
    lg_now = lg_now or sim.league()
    back = PRIOR_SEASONS if seasons is None else seasons
    parts = []
    _LOADING = True
    try:
        parts = _load_seasons(season, back, lg_now)
    finally:
        _LOADING = False
    _PRIOR = _blend_priors(parts)
    _PRIOR_FOR = season + 1
    return len(_PRIOR)


def _load_seasons(season: int, back: int, lg_now: dict) -> list:
    from src.context import sim
    parts = []
    for k in range(back):
        yr = season - k
        # `sim.league` RAISES for a season with no rows rather than
        # returning empty, so walking back past the history on disk is an
        # exception and not a short list. Found by asking for 2023's rates
        # with the prior on, which reached for 2022.
        try:
            lg_prior = sim.league(yr)
        except Exception:
            continue
        if not lg_prior:
            continue
        # No `before` on purpose: a prior season is COMPLETE by the time any
        # of this one is being priced, so there is no cutoff to respect and
        # using a partial one would throw away the reason to have it.
        #
        # `prior={}` is not enough to stop this recursing — `pitcher_rates`
        # reads `prior or _ensure_prior(...)` — so `_PRIOR` is cleared by the
        # caller and `_LOADING` blocks the lazy path for the duration.
        # Otherwise a season's prior would be built out of the previous
        # prior, compounding three seasons into nine.
        # RAW when `USE_RAW_PRIOR`: these rates become the shrink TARGET
        # and `shrink_target` shrinks them once against their own effective
        # sample. Shrinking them here too is the double count.
        raw = pitcher_rates(lg_prior, yr,
                            shrink=not (USE_RAW_PRIOR
                                        or USE_MEASURED_PRIOR_PA))
        if raw and USE_MEASURED_PRIOR_PA and not USE_RAW_PRIOR:
            _reshrink_uncounted(raw, lg_prior)
        if raw:
            parts.append((k + 1, _prior_adjusted(raw, lg_prior, lg_now)))
    return parts


def _reshrink_uncounted(raw: dict, lg_prior: dict) -> None:
    """Put the shipped first shrink back on the stats with no counted `m`.

    `USE_MEASURED_PRIOR_PA` needs the prior RAW, because the counted `m`
    replaces both shrink stages at once. But it is counted for `k_pct` and
    `bb_pct` only, and handing the other two a raw prior would silently
    turn `USE_RAW_PRIOR` on for them — the arm that was scored and LOST.
    So those two are shrunk here exactly as `pitcher_rates(shrink=True)`
    would have, in place.

    THE TARGET IS THE LEAGUE AND THAT IS NOT AN APPROXIMATION: `_LOADING`
    blocks the lazy prior path while a prior is being built, so
    `shrink_target` sees an empty prior and returns `lg[stat]`. Stage one
    is a plain league shrink at that season's own sample.

    Balls in play are RECONSTRUCTED rather than re-queried. With
    `shrink=False` the rates are the observed ones, so `k = k_pct * pa`
    exactly, and `balls_in_play` is the same function `pitcher_rates` used
    to build the denominator it shrank babip against.
    """
    for r in raw.values():
        pa = r.get("pa") or 0
        if pa <= 0:
            continue
        bip = balls_in_play(pa, r["k_pct"] * pa, r["bb_pct"] * pa,
                            r["hr_pct"] * pa)
        for stat in ("k_pct", "bb_pct", "hr_pct", "babip"):
            if stat in PRIOR_EFFECTIVE_PA:
                continue
            n = bip if stat == "babip" else pa
            r[stat] = _shrink(r[stat], lg_prior[stat], n, stat, who="pit")


def _blend_priors(parts: list[tuple[int, dict]]) -> dict:
    """Combine prior seasons into one target, older ones discounted.

    Weight is `PRIOR_DECAY[stat] ** (lag - 1)` times that season's batters
    faced, so a pitcher who threw 180 innings two years ago and 20 last year
    is not represented mainly by the 20. `pa` comes out as the EFFECTIVE
    sample — the sum of the discounted weights — which is what the second
    shrink stage in `pitcher_rates` then reads, so an older prior is treated
    as the thinner evidence it is rather than as a full season.

    THE LAG IS RELATIVE TO THE PITCHER'S OWN MOST RECENT SEASON, not to the
    calendar, and that is the whole point rather than a detail. A man back
    from an elbow has no last season; his 2024 is the freshest thing that
    exists about him and it enters at full weight. Discounting it by the
    calendar instead drops him out of the prior altogether whenever a decay
    is 0.0 — which is what BABIP's is — and it is exactly this population,
    7.6% of pitcher-seasons, that the prior was built to reach. Measured,
    their two-year-old K rate predicts at 0.587 where a one-year-old one
    manages 0.645 for everybody else.
    """
    if not parts:
        return {}
    if len(parts) == 1:
        return parts[0][1]
    stats = ("k_pct", "bb_pct", "hr_pct", "babip")
    names = {n for _, p in parts for n in p}
    out = {}
    for name in names:
        acc = {s: [0.0, 0.0] for s in stats}
        # Per stat, because availability differs: a pitcher can have a
        # strikeout rate in a season and no balls in play worth a BABIP.
        base = {}
        for lag, pop in sorted(parts):
            r = pop.get(name)
            if not r:
                continue
            for s in stats:
                if r.get(s) is not None:
                    base.setdefault(s, lag)
        for lag, pop in parts:
            r = pop.get(name)
            if not r:
                continue
            for s in stats:
                if r.get(s) is None:
                    continue
                w = PRIOR_DECAY.get(s, 0.0) ** (lag - base[s])
                wt = w * (r.get("pa") or 0)
                acc[s][0] += wt * r[s]
                acc[s][1] += wt
        blended = {s: (v[0] / v[1]) for s, v in acc.items() if v[1] > 0}
        if len(blended) < len(stats):
            continue
        # `pa` is per stat in principle — the decay differs — but the second
        # shrink stage takes one number, so the K weighting leads. It is the
        # stat the prior exists for and the one with the most at stake.
        blended["pa"] = acc["k_pct"][1]
        blended["name"] = name
        out[name] = blended
    return out


def _prior_adjusted(prior: dict, lg_prior: dict, lg_now: dict) -> dict:
    """Last season's rates, moved onto THIS season's run environment.

    Home runs are up 7% between 2025 and 2026, so a 2025 home-run rate was
    earned against a different ball. Using it raw imports the old run
    environment along with the pitcher. Scaled by the league ratio, which
    keeps his position relative to his peers and re-bases the level.
    """
    out = {}
    for name, r in prior.items():
        adj = dict(r)
        for stat in ("k_pct", "bb_pct", "hr_pct", "babip"):
            base = lg_prior.get(stat)
            if base:
                adj[stat] = r[stat] * (lg_now[stat] / base)
        out[name] = adj
    return out


#: Build the PRIOR from raw season rates instead of already-shrunk ones.
#:
#: THE DEFECT. `_load_seasons` calls `pitcher_rates(lg_prior, yr)`, which
#: returns rates ALREADY SHRUNK toward the league. `shrink_target` then
#: shrinks that result toward the league AGAIN with the same constant.
#: Shrinking an estimate twice toward the same mean discards evidence, and
#: it bites in proportion to `k`, so it is nearly invisible on strikeouts
#: and severe on home runs. Measured over 181 arms, the share of a shipped
#: rate that traces to the pitcher rather than to the league:
#:
#:     stat        k    as shipped   pooled once    gain
#:     k_pct      57       0.969        0.943      -0.026
#:     bb_pct    138       0.894        0.883      -0.011
#:     babip    3068       0.497        0.537      +0.040
#:     hr_pct    934       0.418        0.568      +0.151
#:
#: A pitcher's four-year home-run record arrives flattened to a sixth of its
#: real spread — target sd 0.0012 against a raw 0.0073.
#:
#: IT IS WORTH ABOUT 0.044 RUNS, under the 0.05 leverage floor, so this is a
#: correctness change and not an edge.
#:
#: **SCORED AND IT LOSES. OFF, AND NOT BECAUSE THE DEFECT IS IMAGINARY.**
#: Paired F5 CRPS over four salts, `scratchpad/rawprior_ab.py`:
#:
#:     per salt, shipped      1.64694  1.62432  1.63189  1.65550
#:     per salt, shrunk once  1.64780  1.63044  1.64751  1.67064
#:     paired difference      +0.00944 +/- 0.00359   z +2.6, 4/4 positive
#:
#: The double shrink is wrong as a Bayesian construction and is
#: EMPIRICALLY BETTER than shrinking once, which means it is compensating
#: for something. The candidate is `_blend_priors` setting the prior's `pa`
#: to the raw sum of decayed plate appearances: that OVERSTATES its
#: predictive weight, because a season-old rate is worth less than its
#: sample implies once talent has had a year to move. `PRIOR_DECAY` already
#: discounts the RATE for that and nothing discounts the SAMPLE.
#:
#: So the fix is not this one. It is to shrink ONCE against a DISCOUNTED
#: effective sample, and the size of that discount is a measurement nobody
#: has made. Kept switchable with the negative recorded rather than
#: deleted, because the defect it names is real.
USE_RAW_PRIOR = False


#: WHAT A PRIOR SEASON'S SAMPLE IS ACTUALLY WORTH, in batters faced.
#: COUNTED by `scratchpad/priorsample.py` on 2026-08-29, and it is the
#: measurement `USE_RAW_PRIOR`'s docstring above says has never been made.
#:
#: The form is ONE shrink pooling three sources:
#:
#:     rate = (n_own*own + m*prior + k_lg*league) / (n_own + m + k_lg)
#:
#: scored on OUT-OF-SAMPLE PREDICTION OF THE REST OF A PITCHER'S OWN SEASON
#: — a fact about pitchers, not about anything that settles. Positive
#: control recovers a planted `m` exactly at 50/100/200/400/800.
#:
#:     stat      raw prior pa   counted m   shipped m_eff   by season
#:     k_pct          403           250          173        250 250 250
#:     bb_pct         444           250          192        250 250 300
#:     hr_pct         495           400          127        400 400 800
#:     babip          291           800           41       1000 800 600
#:
#: `shipped m_eff` is what the DOUBLE shrink amounts to: applying the same
#: constant twice leaves the prior at weight w^2, which is the pooled form
#: at `k*w^2/(1-w^2)`. So the shipped path UNDER-weights the prior and
#: `USE_RAW_PRIOR` (which would use the raw `pa`) OVER-weights it. The
#: counted value sits between the two, which is exactly why removing one
#: error while leaving the other scored worse than doing nothing.
#:
#: ONLY TWO STATS ARE COUNTED AND THE OTHER TWO ARE DELIBERATELY ABSENT.
#: A prior cannot be worth MORE batters faced than it contains, so `m` over
#: the raw sample is a failed measurement rather than a large one: babip
#: asks for 800 against a raw 291 and its argmin walks 1000/800/600 by
#: season, because k_lg is 3068 and the loss curve is nearly flat. Home
#: runs pass the sample test but the argmin moves 400/400/800 and the whole
#: gain is 1%. Both are UNRESOLVED, keep the shipped construction, and are
#: not zeros.
#:
#: k_pct and bb_pct are interior minima, identical in every target season,
#: and stable across four current-sample cuts. Those ship.
PRIOR_EFFECTIVE_PA = {"k_pct": 250, "bb_pct": 250}

#: OFF until scored on F5 CRPS. The measurement above is a fact about
#: predicting rates; whether it reaches what settles is a separate question
#: and `scratchpad/priorsample_ab.py` is where it gets asked.
USE_MEASURED_PRIOR_PA = False


def pitcher_rates(
    lg: dict, season: int | None = None, before: str | None = None,
    conn=None, prior: dict | None = None, shrink: bool = True,
) -> dict[str, dict]:
    """{player_name: rates} for every pitcher with a line on record.

    Batters faced is approximated as outs + hits + walks — the cache carries
    no HBP and no reached-on-error. That is the same footing
    `sim._starter_league` uses for its baselines, so pitcher and league agree
    and the BATTER rates are the ones converted onto it.

    `prior` is {name: rates} from a previous season, already league-adjusted
    by `_prior_adjusted`. When a pitcher appears in it his thin current line
    shrinks toward HIS OWN last year rather than toward the league; when he
    does not — a genuine rookie — nothing changes and he shrinks to league
    as before. See `USE_PRIOR_SEASON`.
    """
    def _run(c):
        return c.execute(
            _PITCHER_Q.format(where=_where(season, before))).fetchall()

    rows = _run(conn) if conn is not None else _with(_run)
    prior = (prior or _ensure_prior(season)) if USE_PRIOR_SEASON else {}
    # These are already per BATTER FACED, which is the footing the league
    # baselines now use (see sim._starter_league). It is the BATTER rates
    # that get scaled onto it, not these. Scaling the pitchers was tried
    # first and made walks worse — their denominator was never the problem.
    dfn = _defence_targets(season) if USE_TEAM_DEFENCE else {}
    _team_of = (_pitcher_teams(season, before, conn)
                if USE_TEAM_DEFENCE else {})

    def _t(row, stat):
        """Delegates to `shrink_target` — see there for why this is shared."""
        return shrink_target(row["name"], _team_of.get(row["name"]), stat,
                             lg, prior, dfn)

    def _s(observed, target, n, stat, name=None):
        """`_shrink`, or the raw rate when this call is building a PRIOR.

        A prior season is shrunk ONCE, by `shrink_target`, against its own
        effective sample. Shrinking it here as well is the double count.

        `pool_k` is None unless `USE_MEASURED_PRIOR_PA` is on AND this
        pitcher has a prior for this stat, so the default path is bit-for-
        bit what it was.
        """
        if shrink:
            return _shrink(observed, target, n, stat, who="pit",
                           k_override=pool_k(name, stat, prior))
        return target if (observed is None or n <= 0) else observed

    out = {}
    for r in rows:
        bf = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
        if bf < 1:
            continue
        bip = balls_in_play(bf, r["k"], r["bb"], r["hr"])
        out[r["name"]] = {
            "name": r["name"],
            "pa": bf,
            "apps": r["apps"],
            "k_pct": _s((r["k"] or 0) / bf, _t(r, "k_pct"), bf, "k_pct",
                        r["name"]),
            "bb_pct": _s((r["bb"] or 0) / bf, _t(r, "bb_pct"), bf, "bb_pct",
                         r["name"]),
            "hr_pct": _s((r["hr"] or 0) / bf, _t(r, "hr_pct"), bf, "hr_pct",
                         r["name"]),
            # NEUTRALISED: what he would have allowed behind an average
            # defence. `game.build_side` puts tonight's defence back on.
            "babip": _s(
                ((((r["h"] or 0) - (r["hr"] or 0)) / bip)
                 + defence_delta(_team_of.get(r["name"]), season))
                if bip > 0 else None,
                _t(r, "babip"), max(bip, 0), "babip", r["name"]),
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
        # Batters are measured per batting plate appearance; the baselines
        # are per batter faced by a rotation starter. Put them on that
        # footing before they meet a pitcher in log5.
        bs = lg.get("batter_scale") or {}
        out[r["name"]] = {
            "name": r["name"],
            "pa": pa,
            "games": r["games"],
            "k_pct": _shrink((r["so"] or 0) / pa * bs.get("k_pct", 1.0),
                             lg["k_pct"], pa, "k_pct", who="bat"),
            "bb_pct": _shrink((r["bb"] or 0) / pa * bs.get("bb_pct", 1.0),
                              lg["bb_pct"], pa, "bb_pct", who="bat"),
            "hr_pct": _shrink((r["hr"] or 0) / pa * bs.get("hr_pct", 1.0),
                              lg["hr_pct"], pa, "hr_pct", who="bat"),
            "babip": _shrink(
                ((((r["h"] or 0) - (r["hr"] or 0)) / bip)
                 * bs.get("babip", 1.0)) if bip > 0 else None,
                lg["babip"], max(bip, 0), "babip", who="bat"),
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


# ── handedness splits, derived locally ─────────────────────────────────
#
# WHY DERIVE RATHER THAN FETCH. statsapi serves exact vs-LHP/vs-RHP splits,
# but only season-to-date at the moment of the call — so a backtest over
# June would apply September's splits to it. That is the same trap the
# snapshot layer exists to avoid with Savant. Deriving from the local
# boxscore cache is approximate and AS-OF CORRECT, which is worth more.
#
# THE APPROXIMATION, STATED PLAINLY. A batter's line for a game is credited
# entirely to the opposing STARTER's throwing hand, but perhaps 35-40% of his
# plate appearances that night came against relievers of assorted hands. That
# contamination pulls each measured split toward the batter's overall rate,
# so the splits below UNDERSTATE the true platoon effect. The direction is
# knowable and safe: the model gets less spread than reality has, never more.
#
# Switch hitters need no special handling. Their "vs L" rows already are
# their right-handed batting, because that is what they did in those games.

#: Split-sample plate appearances at which a batter's own split outweighs
#: his overall rate. Lower than the STABILISE constants because the prior
#: here is the batter himself rather than the league — a much better guess,
#: so it takes less evidence to move off it.
SPLIT_STABILISE = 120

_SPLIT_Q = """
with st as (
  select game_id, team, player_name
  from mlb_pitching where is_starter = 1
)
select mb.player_name name, st.player_name opp_starter,
       sum(mb.ab) ab, sum(mb.bb) bb, sum(mb.h) h, sum(mb.so) so,
       sum(mb.hr) hr
from mlb_batting mb
join games g on g.game_id = mb.game_id
join st on st.game_id = mb.game_id and st.team <> mb.team
where g.sport = 'mlb' and g.status = 'Final' {where}
group by mb.player_name, st.player_name
"""


def batter_rates_by_hand(lg: dict, season: int | None = None,
                         before: str | None = None, conn=None) -> dict:
    """{name: {'L': rates, 'R': rates}}, shrunk toward the batter's own line.

    Two-level shrinkage, which is the rule the rest of this codebase
    follows: a split with little behind it falls back to the hitter's
    overall rate, and only a hitter with nothing at all falls back to the
    league. Shrinking a thin split straight to league average would erase
    the very platoon signal this exists to add.
    """
    from src import roster

    overall = batter_rates(lg, season, before, conn)

    def _run(c):
        return c.execute(_SPLIT_Q.format(
            where=_where(season, before))).fetchall()

    rows = _run(conn) if conn is not None else _with(_run)

    hand_of: dict[str, str | None] = {}
    acc: dict[str, dict[str, dict]] = {}
    for r in rows:
        sp = r["opp_starter"]
        if sp not in hand_of:
            hand_of[sp] = roster.throws(sp)
        hand = hand_of[sp]
        if hand not in ("L", "R"):
            continue
        d = acc.setdefault(r["name"], {}).setdefault(
            hand, {"ab": 0, "bb": 0, "h": 0, "so": 0, "hr": 0})
        for k in d:
            d[k] += r[k] or 0

    out: dict[str, dict] = {}
    for name, byhand in acc.items():
        base = overall.get(name)
        if not base:
            continue
        out[name] = {}
        for hand, d in byhand.items():
            pa = d["ab"] + d["bb"]
            bip = d["ab"] - d["so"] - d["hr"]
            w = pa / (pa + SPLIT_STABILISE) if pa else 0.0

            def mix(obs, prior):
                return w * obs + (1 - w) * prior if pa else prior

            out[name][hand] = {
                "name": name, "hand": hand, "pa": pa,
                "k_pct": mix(d["so"] / pa if pa else 0, base["k_pct"]),
                "bb_pct": mix(d["bb"] / pa if pa else 0, base["bb_pct"]),
                "hr_pct": mix(d["hr"] / pa if pa else 0, base["hr_pct"]),
                "babip": mix((d["h"] - d["hr"]) / bip if bip > 0 else
                             base["babip"], base["babip"]),
            }
    return out


# ── park neutralisation ────────────────────────────────────────────────
#
# WHY RATES MUST BE NEUTRALISED BEFORE A PARK MULTIPLIER MEANS ANYTHING.
# A player's season line is not park-neutral: he takes roughly half his
# plate appearances in one stadium. Logan Gilbert's strikeout rate is
# inflated 10.6% by half a season at T-Mobile; Tanner Gordon's is suppressed
# 7.9% by Coors. Applying tonight's park index to those raw rates counts the
# home park one and a half times and the road park not at all.
#
# Measured: the usage-weighted SO park a starter pitched in ranges 0.921 to
# 1.106 (sd 0.032), and for batters 0.940 to 1.091 (sd 0.030) — the two are
# the same size, because hitters play half at home too.
#
# This is why the first park A/B came out a wash (mean Brier skill 7.25%
# without park, 7.15% with): the home side was over-adjusted and the road
# side correctly adjusted, and the two roughly cancelled. The machinery was
# right; the inputs were not ready for it.
#
# Requires `games.venue_id`, which is why this could not be built before the
# venue backfill.

#: Which Savant index neutralises which rate.
_PARK_KEY = {"k_pct": "so", "bb_pct": "bb", "hr_pct": "hr", "babip": "bacon"}

_EXPOSURE_Q = {
    "pitcher": """
        select p.player_name nm, g.venue_id v, p.outs_recorded w
        from mlb_pitching p join games g on g.game_id = p.game_id
        where g.sport = 'mlb' and g.status = 'Final'
          and p.is_starter = 1 and g.venue_id is not null {where}
    """,
    "batter": """
        select mb.player_name nm, g.venue_id v, mb.ab + mb.bb w
        from mlb_batting mb join games g on g.game_id = mb.game_id
        where g.sport = 'mlb' and g.status = 'Final'
          and g.venue_id is not null {where}
    """,
}


def park_exposure(side: str, season=None, before=None, conn=None) -> dict:
    """{name: {rate_key: weighted park multiplier}} for the games he played.

    Divide a raw rate by this to get the park-neutral version. A venue
    Savant does not rate contributes 1.0 rather than being dropped — the
    player really did accumulate those plate appearances, and treating them
    as neutral is the honest reading when the park is unknown.
    """
    from src.context.sources import park as park_src
    try:
        pf = park_src.park_factors()
    except Exception:
        return {}

    def _run(c):
        return c.execute(
            _EXPOSURE_Q[side].format(where=_where(season, before))).fetchall()

    rows = _run(conn) if conn is not None else _with(_run)
    acc: dict[str, dict] = {}
    for r in rows:
        w = r["w"] or 0
        if w <= 0:
            continue
        rec = pf.get(f"id:{r['v']}")
        d = acc.setdefault(r["nm"], {"_w": 0.0})
        d["_w"] += w
        for key, col in _PARK_KEY.items():
            v = (rec or {}).get(col)
            d[key] = d.get(key, 0.0) + w * ((v / 100.0) if v else 1.0)
    out = {}
    for nm, d in acc.items():
        w = d.pop("_w")
        out[nm] = {k: (v / w if w else 1.0) for k, v in d.items()}
    return out


def neutralise(rates: dict, exposure: dict) -> dict:
    """Divide each rate by the park it was accumulated in.

    Clamped, because dividing a rate by a multiplier below 1 can push it
    past a probability. Names absent from `exposure` are returned untouched
    rather than guessed at.
    """
    out = {}
    for nm, r in rates.items():
        exp = exposure.get(nm)
        if not exp:
            out[nm] = r
            continue
        adj = dict(r)
        for key in _PARK_KEY:
            m = exp.get(key) or 1.0
            if m > 0 and key in adj and adj[key] is not None:
                adj[key] = min(max(adj[key] / m, 1e-6), 0.95)
        out[nm] = adj
    return out


# ── arsenal matchup multipliers ────────────────────────────────────────
#
# The one input the simulator has a slot for and has never been given.
# `BatterRates.arsenal_mult` has defaulted to 1.0 since the module was
# written, so `vs_arsenal` — the per-pitch whiff and usage work — has been
# feeding nothing.
#
# WHY THIS MIGHT SUCCEED WHERE HANDEDNESS FAILED. Handedness varies by
# BATTER, and nine batters average it away, which is why it moved
# between-batter variance 20% and changed nothing. An arsenal varies by
# PITCHER and every hitter in the lineup faces the same one, so it does not
# cancel — it shifts the whole start. That is the axis the model is short on.
#
# RELATIVE TO A LEAGUE-AVERAGE ARSENAL, not to the batter's own season line.
# His overall quality is already in his k_pct and babip; dividing by his own
# wOBA would put it in twice. What is wanted here is only "is this
# particular mix good or bad for him", which is the ratio of his projection
# against this arsenal to his projection against a league-typical one.

_LEAGUE_ARSENAL: list | None = None


def league_arsenal(arsenals: dict) -> list[dict]:
    """Usage-weighted average pitch mix across every pitcher on record."""
    global _LEAGUE_ARSENAL
    if _LEAGUE_ARSENAL is not None:
        return _LEAGUE_ARSENAL
    tot: dict[str, float] = {}
    for mix in arsenals.values():
        for p in mix or []:
            try:
                tot[p.get("pitch")] = tot.get(p.get("pitch"), 0.0) + float(
                    p.get("usage_pct") or 0)
            except (TypeError, ValueError):
                continue
    n = len(arsenals) or 1
    _LEAGUE_ARSENAL = [{"pitch": k, "usage_pct": v / n}
                       for k, v in tot.items() if k]
    return _LEAGUE_ARSENAL


def arsenal_mults(starter_arsenal, batter_names, arsenals, season=None,
                  as_of=None) -> dict[str, dict]:
    """{batter: {'contact': m, 'k': m}} for one starter's mix.

    `contact` scales home runs and balls in play; `k` scales the strikeout
    rate off projected whiff. Both are ratios against the same batter
    projected onto a league-average arsenal, so a hitter who is simply good
    gets 1.0 — his quality already lives in his rates.

    A batter Savant has no per-pitch rows for returns neutral rather than a
    guess. So does a projection built on thin arsenal coverage.
    """
    from src.context.sources import batter as bat
    if not starter_arsenal:
        return {}
    ref_mix = league_arsenal(arsenals)
    out: dict[str, dict] = {}
    for nm in batter_names:
        here = bat.vs_arsenal(nm, starter_arsenal, season, as_of)
        ref = bat.vs_arsenal(nm, ref_mix, season, as_of)
        if not here or not ref or not ref.get("proj_woba"):
            continue
        if (here.get("coverage") or 0) < 0.6:
            continue
        c = here["proj_woba"] / ref["proj_woba"]
        k = 1.0
        if here.get("proj_whiff_pct") and ref.get("proj_whiff_pct"):
            k = here["proj_whiff_pct"] / ref["proj_whiff_pct"]
        # Clamped: a 40% swing off a per-pitch sample is noise, not a
        # matchup, and the simulator has no other guard against it.
        out[nm] = {"contact": min(max(c, 0.80), 1.25),
                   "k": min(max(k, 0.80), 1.25)}
    return out


# ── bullpens ───────────────────────────────────────────────────────────
#
# WHY PER-CLUB AND PER-ARM, rather than one league-average reliever.
#
# The deleted `f5.relief_rates()` collapsed the entire relief population
# into a single set of rates and used it for every leftover out. That was a
# defensible stub for first-five, where relief appears in maybe a quarter of
# sides and usually for under an inning. It is badly wrong for a full game,
# where the bullpen throws roughly 40% of the innings EVERY time.
#
# The reason is variance, not level. A league-average arm every night makes
# the run distribution smooth, and the model's measured defect is already
# that its run distribution is COMPRESSED — too many shutouts and too few
# crooked numbers at the same time. Bullpens are the largest single source
# of game-to-game variance in run scoring: a club's best reliever and its
# mop-up man are not the same pitcher, and which one appears depends on the
# score. Averaging them away destroys exactly the spread that is missing.
#
# The per-arm rates were already being computed and then thrown away.

_PEN_Q = """
select p.player_name name, p.team team,
       sum(p.outs_recorded) o, sum(p.h) h, sum(p.bb) bb,
       sum(p.k) k, sum(p.hr) hr, count(*) apps
from mlb_pitching p join games g on g.game_id = p.game_id
where g.sport = 'mlb' and g.status = 'Final' and p.is_starter = 0 {where}
group by p.player_name, p.team
"""

#: An arm needs this many appearances before it is a bullpen member rather
#: than a position player mopping up a blowout or a starter's one relief
#: outing. Low, because carrying the fringe arms is the point — they are
#: where the bad innings come from.
MIN_PEN_APPS = 5


#: Shrink a reliever toward the RELIEVER league rather than the rotation's.
#:
#: `sim._starter_league` is measured on rotation starters — deliberately,
#: because it is the log5 anchor and starters are what the model was built
#: to price. But it is also the SHRINK TARGET, and relievers are not doing
#: the same job. Counted on 2026:
#:
#:                    BF        K%       BB%       HR%
#:     RELIEVERS  64,752    0.2227    0.0972    0.0280
#:     STARTERS   85,207    0.2160    0.0823    0.0319
#:
#: They allow 12% FEWER home runs and walk 18% MORE. And the target
#: dominates: the pitcher home-run shrink constant is 934 against a
#: reliever's median 106 batters faced, so 90% of a reliever's home-run rate
#: IS this number. Applying the rotation's inflates every reliever's home
#: runs by ~13% and suppresses his walks by ~18%, across the 40% of innings
#: the bullpen throws.
#:
#: That is the shape of the measured defect in `scratchpad/traffic.py`: 11%
#: too many home runs and too few walks and singles, at almost exactly the
#: right total number of baserunners. Homers end rallies and walks start
#: them, which is also why the model is short of crooked innings.
#:
#: THE LOG5 ANCHOR IS DELIBERATELY LEFT ALONE. Changing what every rate is
#: resolved against is a different and much larger change; this moves only
#: what a THIN LINE IS PULLED TOWARD, which is where the 90% sits.
#: ON. Scored neutral and shipped on CORRECTNESS, not on the score: the
#: composition it fixes is demonstrably wrong without it (walks -1.9% ->
#: +0.7%, home runs +10.7% -> +4.5% against reality), while F5 CRPS moves
#: 1.63959 -> 1.63754, inside noise. The extra walks and the missing home
#: runs very nearly cancel on runs.
#:
#: The prediction that walks would buy CLUSTERING did NOT pay — sides
#: scoring 5+ went 15.1% to 15.0% against a real 17.6%. Recorded because it
#: was stated before looking.
USE_RELIEVER_LEAGUE = True

_PEN_LG: dict = {}


def reliever_league(season=None) -> dict:
    """League rates over RELIEF appearances only, on the pitcher footing."""
    key = scope.resolve(season)
    if key in _PEN_LG:
        return _PEN_LG[key]
    q = ("select sum(p.outs_recorded) o, sum(p.h) h, sum(p.bb) bb,"
         " sum(p.k) k, sum(p.hr) hr"
         " from mlb_pitching p join games g on g.game_id = p.game_id"
         " where g.sport = 'mlb' and g.status = 'Final'"
         " and p.is_starter = 0 " + _where(season, None))

    def _run(c):
        return c.execute(q).fetchone()

    try:
        r = _with(_run)
    except Exception:
        r = None
    if not r or not r["o"]:
        _PEN_LG[key] = {}
        return {}
    bf = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
    bip = balls_in_play(bf, r["k"], r["bb"], r["hr"])
    out = {
        "k_pct": (r["k"] or 0) / bf,
        "bb_pct": (r["bb"] or 0) / bf,
        "hr_pct": (r["hr"] or 0) / bf,
        "babip": (((r["h"] or 0) - (r["hr"] or 0)) / bip) if bip > 0 else None,
    }
    out = {k: v for k, v in out.items() if v is not None}
    _PEN_LG[key] = out
    return out


def bullpens(lg: dict, season: int | None = None, before: str | None = None,
             conn=None) -> dict[str, list[dict]]:
    """{team: [reliever rates, most-used first]}.

    Each arm carries `apps`, which is the sampling weight — a leverage
    reliever appears far more often than the twelfth man, and drawing
    uniformly would hand every club a bullpen made mostly of its worst
    pitchers.
    """
    def _run(c):
        return c.execute(_PEN_Q.format(where=_where(season, before))).fetchall()

    rows = _run(conn) if conn is not None else _with(_run)
    # THE SAME TARGET STARTERS GET. Until 2026-08-26 this block hardcoded
    # `lg[stat]`, so no reliever ever saw the multi-season prior or his
    # club's defence — in the population where the target carries 38% of the
    # rate rather than 11%.
    prior = _ensure_prior(season) if USE_PRIOR_SEASON else {}
    dfn = _defence_targets(season) if USE_TEAM_DEFENCE else {}
    # The target only. `lg` still anchors the log5 resolution.
    pen_lg = dict(lg)
    if USE_RELIEVER_LEAGUE:
        pen_lg.update(reliever_league(season))
    out: dict[str, list[dict]] = {}
    for r in rows:
        bf = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
        if bf < 1 or (r["apps"] or 0) < MIN_PEN_APPS:
            continue
        bip = balls_in_play(bf, r["k"], r["bb"], r["hr"])

        def _t(stat, _r=r):
            return shrink_target(_r["name"], _r["team"], stat,
                                 pen_lg, prior, dfn)

        out.setdefault((r["team"] or "").upper(), []).append({
            "name": r["name"],
            "pa": bf,
            "apps": r["apps"],
            # `pool_k` reaches relievers too, for the reason `_t` does: a
            # reliever's median line is 106 batters faced against a
            # starter's 480, so the target carries 38% of his rate and 11%
            # of a starter's. A prior correction that stopped at the
            # rotation would miss the population it matters most in.
            "k_pct": _shrink((r["k"] or 0) / bf, _t("k_pct"), bf,
                             "k_pct", who="pit",
                             k_override=pool_k(r["name"], "k_pct", prior)),
            "bb_pct": _shrink((r["bb"] or 0) / bf, _t("bb_pct"), bf,
                              "bb_pct", who="pit",
                              k_override=pool_k(r["name"], "bb_pct", prior)),
            "hr_pct": _shrink((r["hr"] or 0) / bf, _t("hr_pct"), bf,
                              "hr_pct", who="pit",
                              k_override=pool_k(r["name"], "hr_pct", prior)),
            "babip": _shrink(((((r["h"] or 0) - (r["hr"] or 0)) / bip)
                              + defence_delta(r["team"], season))
                             if bip > 0 else None,
                             _t("babip"), bip, "babip", who="pit",
                             k_override=pool_k(r["name"], "babip", prior)),
        })
    for arms in out.values():
        arms.sort(key=lambda a: -a["apps"])
    return out


# ── recency ────────────────────────────────────────────────────────────
#
# A season aggregate treats April and August as the same evidence, and a
# pitcher is not the same pitcher across them: stuff comes and goes, arms
# tire, a change of grip or a new pitch shows up mid-year. Pooling flat
# means the model is always describing a player who no longer exists.
#
# This is a WEIGHTED version of the same shrinkage. Each appearance is
# discounted by age with a half-life, so a start six weeks ago counts half
# what last night's does, and the shrinkage denominator uses the EFFECTIVE
# sample — the sum of weights — rather than the raw batters faced. That
# second part matters: weighting without shrinking the denominator would
# keep the model's confidence at full-season levels while the evidence
# behind it shrank, which is how a recency filter turns into an overreaction
# to one bad outing.
#
# OFF BY DEFAULT (`HALF_LIFE_DAYS = None`). Every imported baseball effect
# this project has tried measured zero, and the ones that worked were fitted
# as residuals against the model's own error. Recency is plausible enough to
# build and has NOT yet been measured, so it ships switched off until it is.

_PITCHER_GAMES_Q = """
select p.player_name name, g.date date,
       p.outs_recorded o, p.h h, p.bb bb, p.k k, p.hr hr
from mlb_pitching p join games g on g.game_id = p.game_id
where g.sport = 'mlb' and g.status = 'Final' {where}
"""

#: Days after which an appearance counts half. None disables weighting and
#: reproduces the flat season aggregate exactly.
HALF_LIFE_DAYS: float | None = None


def _days(a: str, b: str) -> int:
    from datetime import date as _d
    ya, ma, da = (int(x) for x in a[:10].split("-"))
    yb, mb, db = (int(x) for x in b[:10].split("-"))
    return (_d(ya, ma, da) - _d(yb, mb, db)).days


def pitcher_rates_recent(lg: dict, season=None, before=None,
                         half_life: float | None = None,
                         conn=None) -> dict[str, dict]:
    """`pitcher_rates`, with appearances discounted by age.

    `half_life=None` falls straight through to the unweighted version, so
    this is safe to call unconditionally.
    """
    hl = HALF_LIFE_DAYS if half_life is None else half_life
    if not hl:
        return pitcher_rates(lg, season, before, conn)

    def _run(c):
        return c.execute(
            _PITCHER_GAMES_Q.format(where=_where(season, before))).fetchall()

    rows = _run(conn) if conn is not None else _with(_run)
    if not rows:
        return {}
    # Age is measured from the most recent game in the WINDOW, not from
    # today. Scoring a July date must not discount July as if it were old
    # news — that would make a backtest quietly weaker than production.
    latest = max(r["date"] for r in rows)

    agg: dict[str, dict] = {}
    for r in rows:
        w = 0.5 ** (_days(latest, r["date"]) / hl)
        bf = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
        if bf < 1:
            continue
        a = agg.setdefault(r["name"], {"bf": 0.0, "k": 0.0, "bb": 0.0,
                                       "hr": 0.0, "h": 0.0, "raw": 0,
                                       "apps": 0})
        a["bf"] += w * bf
        a["k"] += w * (r["k"] or 0)
        a["bb"] += w * (r["bb"] or 0)
        a["hr"] += w * (r["hr"] or 0)
        a["h"] += w * (r["h"] or 0)
        a["raw"] += bf
        a["apps"] += 1

    out = {}
    for name, a in agg.items():
        bf = a["bf"]
        if bf < 1:
            continue
        bip = bf - a["k"] - a["bb"] - a["hr"]
        # Shrink on the EFFECTIVE sample, not the raw one. Discounting the
        # evidence but not the confidence is how this becomes an
        # overreaction to a recent bad start.
        out[name] = {
            "name": name, "pa": a["raw"], "apps": a["apps"],
            "eff_pa": bf,
            "k_pct": _shrink(a["k"] / bf, lg["k_pct"], bf, "k_pct", who="pit"),
            "bb_pct": _shrink(a["bb"] / bf, lg["bb_pct"], bf, "bb_pct", who="pit"),
            "hr_pct": _shrink(a["hr"] / bf, lg["hr_pct"], bf, "hr_pct", who="pit"),
            "babip": _shrink(((a["h"] - a["hr"]) / bip) if bip > 0 else None,
                             lg["babip"], bip, "babip", who="pit"),
        }
    return out
