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

    Batters faced is approximated as outs + hits + walks — the cache carries
    no HBP and no reached-on-error. That is the same footing
    `sim._starter_league` uses for its baselines, so pitcher and league agree
    and the BATTER rates are the ones converted onto it.
    """
    def _run(c):
        return c.execute(
            _PITCHER_Q.format(where=_where(season, before))).fetchall()

    rows = _run(conn) if conn is not None else _with(_run)
    # These are already per BATTER FACED, which is the footing the league
    # baselines now use (see sim._starter_league). It is the BATTER rates
    # that get scaled onto it, not these. Scaling the pitchers was tried
    # first and made walks worse — their denominator was never the problem.
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
        # Batters are measured per batting plate appearance; the baselines
        # are per batter faced by a rotation starter. Put them on that
        # footing before they meet a pitcher in log5.
        bs = lg.get("batter_scale") or {}
        out[r["name"]] = {
            "name": r["name"],
            "pa": pa,
            "games": r["games"],
            "k_pct": _shrink((r["so"] or 0) / pa * bs.get("k_pct", 1.0),
                             lg["k_pct"], pa, "k_pct"),
            "bb_pct": _shrink((r["bb"] or 0) / pa * bs.get("bb_pct", 1.0),
                              lg["bb_pct"], pa, "bb_pct"),
            "hr_pct": _shrink((r["hr"] or 0) / pa * bs.get("hr_pct", 1.0),
                              lg["hr_pct"], pa, "hr_pct"),
            "babip": _shrink(
                ((((r["h"] or 0) - (r["hr"] or 0)) / bip)
                 * bs.get("babip", 1.0)) if bip > 0 else None,
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
# `f5.relief_rates()` collapses the entire relief population into a single
# set of rates and uses it for every leftover out. That is a defensible stub
# for first-five, where relief appears in maybe a quarter of sides and
# usually for under an inning. It is badly wrong for a full game, where the
# bullpen throws roughly 40% of the innings EVERY time.
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
    out: dict[str, list[dict]] = {}
    for r in rows:
        bf = (r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0)
        if bf < 1 or (r["apps"] or 0) < MIN_PEN_APPS:
            continue
        bip = bf - (r["k"] or 0) - (r["bb"] or 0) - (r["hr"] or 0)
        out.setdefault((r["team"] or "").upper(), []).append({
            "name": r["name"],
            "pa": bf,
            "apps": r["apps"],
            "k_pct": _shrink((r["k"] or 0) / bf, lg["k_pct"], bf, "k_pct"),
            "bb_pct": _shrink((r["bb"] or 0) / bf, lg["bb_pct"], bf,
                              "bb_pct"),
            "hr_pct": _shrink((r["hr"] or 0) / bf, lg["hr_pct"], bf,
                              "hr_pct"),
            "babip": _shrink((((r["h"] or 0) - (r["hr"] or 0)) / bip)
                             if bip > 0 else None, lg["babip"], bip, "babip"),
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
            "k_pct": _shrink(a["k"] / bf, lg["k_pct"], bf, "k_pct"),
            "bb_pct": _shrink(a["bb"] / bf, lg["bb_pct"], bf, "bb_pct"),
            "hr_pct": _shrink(a["hr"] / bf, lg["hr_pct"], bf, "hr_pct"),
            "babip": _shrink(((a["h"] - a["hr"]) / bip) if bip > 0 else None,
                             lg["babip"], bip, "babip"),
        }
    return out
