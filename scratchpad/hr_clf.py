"""A DIRECT HOME RUN CLASSIFIER — data in, did-he-homer out.

    venv/bin/python -m scratchpad.hr_clf --build     # the batter-game table
    venv/bin/python -m scratchpad.hr_clf --fit       # train and score
    venv/bin/python -m scratchpad.hr_clf --vs-sim    # head to head

WHY THIS EXISTS ALONGSIDE THE SIMULATION, and it is not heresy. CLAUDE.md's
own rule is FIT THE QUANTITY THAT SETTLES, NOT THE UPSTREAM PROXY: the
engine is tuned on hazard curves and run distributions and the home run
probability falls out the far end, while this fits P(home run) directly.
The engine's number is the incumbent and it is a real one — bottom decile
6.7% against 6.8% real, top decile 21.5% against 20.9%, threefold spread,
62,681 batter-games (`hrbat`, four folds). So this has a BENCHMARK TO BEAT
rather than a vacuum to fill, and `--vs-sim` scores both on identical rows.

WHAT THE ENGINE GETS FOR FREE THAT THIS MUST LEARN, stated up front
because it is the honest handicap: how many plate appearances the man
actually gets, who relieves and when, times through the order, and the
base-out state each trip arrives in. A classifier sees a lineup slot and
has to infer the rest.

ONE ROW IS ONE BATTER-GAME. The label is whether he homered, which needs
no rate: a home run requires a ball in play, so a batter in the lineup with
no `mlb_traj` row hit none. Every feature is frozen STRICTLY BEFORE the
row's month — the same monthly-cut discipline `AIR_HR_PIT` was counted
under, and for the same reason.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
import pathlib
from pathlib import Path

from src.context import store
from src.context.sources import battedball
from scratchpad import hr_savant

OUT = Path("scratchpad/hr_clf_rows.json")
SEASONS = (2023, 2024, 2025, 2026)

#: Shrinkage in balls in play, measured by `hr_traj.py --stabilise`.
K = {"bat_hr": 140.7, "bat_air": 179.0, "pit_hr": 943.7, "pit_air": 175.7}


#: How many completed seasons back to look for a batter's contact-quality
#: tiers. Measured: one season back covers 88.2% of batter-games, two covers
#: 90.4%, three covers 90.6%. The knee is at two and the residual ~10% is
#: not a matching failure — Savant's leaderboard lists only players who
#: HOMERED, so a rookie with no prior major league home run is a genuine
#: absence and gets `t_seen = 0`.
TIER_BACK = 2

#: The tier columns, each divided by the batter's BALLS IN PLAY that
#: season. THE DENOMINATOR IS THE WHOLE CARE HERE (rule 10). The obvious
#: base — `hr_total`, which Savant itself uses for its `no_doubter_per`
#: field — is WRONG for the other three: the tiers count batted balls and
#: not just home runs, so Cooper Hummel reads 3 home runs and 4
#: mostly-gone. Dividing by `hr_total` made a ratio above 1 for 8 rows in
#: 10 and above 7 in the tail, purely because the denominator collapses on
#: a light hitter. Balls in play is a base all four share and is the one
#: the +2.84 measurement used.
TIER_COLS = (("t_nd", "no_doubters"), ("t_mg", "mostly_gone"),
             ("t_db", "doubters"), ("t_wl", "non_hr_would_have_left"))


def _tiers_for(year: int) -> dict:
    """Prior-season contact-quality tiers, {normalised batter: features}.

    STRICTLY PRIOR, and structurally rather than by a date filter: only
    seasons that had ENDED before `year` opened are read, nearest first, so
    no row can be described by its own season. A finished season's
    leaderboard never changes again, which is the one thing that lets a
    Savant table into this project at all — the park index died on being
    season-to-date and unaskable about June.

    THE 2023 FOLD CARRIES NO TIERS AND THAT IS NOT A BUG. The denominator
    comes from `mlb_traj`, which starts in 2023, so a 2023 row would need a
    2022 balls-in-play count that this project does not have and cannot
    cheaply get — the pipeline database itself opens in 2023. Those rows
    get `t_seen = 0`, the same encoding as a rookie, and the 2023 column of
    the head-to-head is therefore a tier-free control rather than a
    measurement of them.
    """
    from scratchpad import hr_savant as hs
    out: dict = {}
    for y in range(year - 1, year - 1 - TIER_BACK, -1):
        sv = hs.savant_map("bat", y)
        bip = {nm: v[1] for nm, v in hs.traj_counts("bat", y).items()
               if v[1] > 0 and nm in sv}
        if not bip:
            continue
        # SHRUNK, NOT FLOORED. An eighth of matched batters have under 50
        # balls in play the season before, and a raw ratio on 40 balls is
        # noise dressed as a quality read. A hard cutoff would throw the
        # part-time slugger in with the rookies; shrinking toward the
        # league tier rate pulls him most of the way there and leaves the
        # regular untouched. `k` is the measured HR shrinkage in balls in
        # play, not a new constant — the tiers are home run events on the
        # same denominator, so they stabilise at the same speed.
        tot = sum(bip.values())
        lg = {k: sum(hs._f(sv[nm][c]) for nm in bip) / tot
              for k, c in TIER_COLS}
        for nm, n in bip.items():
            if nm in out:
                continue        # a nearer season already describes him
            out[nm] = {"t_seen": 1.0, **{
                k: ((hs._f(sv[nm][c]) + K["bat_hr"] * lg[k])
                    / (n + K["bat_hr"])) for k, c in TIER_COLS}}
    return out


#: Savant's park columns are TEAM abbreviations; the pipeline's
#: `home_team_abbr` disagrees on two. Everything else joins directly, and
#: the leftovers are minor league neutral sites (Memphis, Sugar Land) which
#: get no fit at all — the same rule park factors already follow.
#: CAVEAT ON `ath`: the Athletics play in Sacramento now, and this assumes
#: Savant's `oak` column tracks the TEAM's current park rather than the
#: Coliseum. 150 games, and the geometry is the whole point, so it is worth
#: re-checking if this feature ever ships.
_ABBR = {"az": "ari", "ath": "oak"}
_PARK_IX = {p: i for i, p in enumerate(hr_savant.PARKS)}


HANDS = Path("scratchpad/hands.json")


def _hands(rebuild: bool = False) -> dict:
    """{'pit': {name: 'R'|'L'}, 'bat': ...}, counted off the play-by-play.

    NOT `roster.throws`, AND THE REASON IS A BUG THIS FOUND. The roster
    index is a snapshot of the CURRENT season, so labelling a 2023 game
    with it returns None for anyone off a 2026 roster — Berríos, Morton,
    Burnes, Heaney, López all came back empty, 226 pitchers and 17.5% of
    rows, on what `sim.PLATOON_MULT` says is the single largest matchup
    term on this channel. Nothing in `context.db` carries handedness at
    all.

    `matchup.pitchHand` is on EVERY cached play for all four seasons, which
    is ground truth rather than a lookup. 10,167 games, 2,325 pitchers,
    and exactly one arm recorded with two hands — a real switch pitcher or
    a single bad row, and the modal value is taken either way.
    """
    import collections
    import glob
    import gzip
    if HANDS.exists() and not rebuild:
        return json.loads(HANDS.read_text())
    pit: dict = collections.defaultdict(collections.Counter)
    bat: dict = collections.defaultdict(collections.Counter)
    for f in sorted(glob.glob(".cache/pbp/*.json.gz")):
        try:
            d = json.load(gzip.open(f))
        except Exception:
            continue
        for p in d.get("allPlays") or []:
            m = p.get("matchup") or {}
            if m.get("pitcher") and m.get("pitchHand"):
                pit[m["pitcher"]["fullName"]][m["pitchHand"]["code"]] += 1
            if m.get("batter") and m.get("batSide"):
                bat[m["batter"]["fullName"]][m["batSide"]["code"]] += 1
    out = {k: {n: c.most_common(1)[0][0] for n, c in v.items()}
           for k, v in (("pit", pit), ("bat", bat))}
    HANDS.write_text(json.dumps(out))
    return out


def _venue_park() -> dict:
    """{venue_id: savant park column}, by whoever plays there most."""
    from collections import Counter, defaultdict
    by: dict = defaultdict(Counter)
    with store.connect() as c:
        for r in c.execute(
                f"select venue_id, home_team_abbr, count(*) n from "
                f"{store.BETS}.games where sport = 'mlb' and venue_id "
                "is not null group by 1, 2"):
            by[r["venue_id"]][(r["home_team_abbr"] or "").lower()] += r["n"]
    out = {}
    for v, cc in by.items():
        ab = _ABBR.get(cc.most_common(1)[0][0], cc.most_common(1)[0][0])
        if ab in _PARK_IX:
            out[v] = ab
    return out


def _fit_for(year: int) -> dict:
    """DOES THIS HITTER'S CONTACT FIT THIS YARD — the thirty park columns
    kept as a VECTOR instead of averaged away.

    Park shapes are arbitrary and DIRECTIONAL: a scalar park factor cannot
    say that this yard is short to the pull side for a left-handed bat and
    deep to centre. Savant computes, for every ball a hitter put in play,
    which of the thirty parks it would have left, so the vector encodes
    exactly that interaction. `xhr` — item 28, dead — is the MEAN of these
    columns, which is precisely the part `park_hr` already carries.

    DOUBLE-CENTRED, and both centrings matter:

      * dividing by his own mean removes HIS POWER, which `b_hr` has;
      * subtracting the league's profile removes THE PARK, which
        `park_hr` has.

    What is left is the interaction and nothing else. Measured year over
    year on 2018-2025 the raw vector repeats at r +0.51, but almost all of
    that is the shared park profile — everyone is high at Coors. The
    residual, which is the actual claim, repeats at **r +0.19**, positive
    in all five season pairs.

    Shrunk on the residual ONLY, at `K["bat_hr"]` balls in play. The
    league profile is measured on every hitter at once and needs no
    shrinking; a single man's deviation from it, on 80 balls, badly does.
    """
    import numpy as np
    from scratchpad import hr_savant as hs
    out: dict = {}
    for y in range(year - 1, year - 1 - TIER_BACK, -1):
        sv = hs.savant_map("bat", y)
        bip = {nm: v[1] for nm, v in hs.traj_counts("bat", y).items()
               if nm in sv and v[1] > 0
               and sum(hs._f(sv[nm][p]) for p in hs.PARKS) > 0}
        if len(bip) < 50:
            continue
        nms = sorted(bip)
        M = np.array([[hs._f(sv[nm][p]) for p in hs.PARKS] for nm in nms])
        # PER BALL IN PLAY, not per his own average park. The relative
        # form — v / v.mean() - 1 — is the natural way to write a
        # multiplier and it EXPLODES on light hitters: a man with one
        # counterfactual home run across thirty parks has a mean of 1/30,
        # so his one park reads +29. It put |6.13| in the built column.
        # Dividing by balls in play instead cannot blow up, and the units
        # are what the model actually wants: extra home runs per ball in
        # play from the fit of his contact to this yard.
        D = ((M - M.mean(1, keepdims=True))
             / np.array([bip[nm] for nm in nms])[:, None])
        lg = D.mean(0)
        R = D - lg
        for i, nm in enumerate(nms):
            if nm in out:
                continue        # a nearer season already describes him
            w = bip[nm] / (bip[nm] + K["bat_hr"])
            out[nm] = {"res": R[i] * w, "d": lg + R[i] * w}
    return out


def _fit_cols(fit, park) -> dict:
    """His park-fit at TONIGHT'S park, or nothing.

    Both halves must be present — a hitter with no prior vector and a
    neutral site with no park column are different absences with the same
    consequence, and `f_seen` marks both rather than letting a zero
    masquerade as an average fit.
    """
    if not fit or park is None:
        return {}
    i = _PARK_IX[park]
    return {"f_seen": 1.0, "f_fit": float(fit["res"][i]),
            "f_raw": float(fit["d"][i])}


def _act_cols(arms, mp_) -> dict:
    """THE PITCHING HE ACTUALLY FACED — every arm, weighted by batters.

    No starter/reliever split, because there is no reason for one. A
    hitter faces a blend of arms over a game and the honest summary is
    the blend. The shipped `p_hr` is this same quantity truncated after
    whoever started, which is why it covers only about half his chances.

    A CEILING, NOT A DEPLOYABLE FEATURE. Which arms appear, and for how
    many batters, is known only afterwards. That is exactly what makes it
    worth computing: if the true blend — the right arms in the right
    proportions — still moves nothing, the channel is empty and no
    amount of predicting the bullpen would rescue it. If it moves a lot,
    that is the case for building the hard version.

    THE LINE THAT STILL HOLDS: each arm enters at his rate as of BEFORE
    this month, never at what he gave up in this game. The first is
    hindsight about the lineup card; the second is reading the answer.
    """
    if not arms:
        return {}
    num_hr = num_air = den = 0.0
    for nm, bf in arms:
        if bf <= 0 or nm not in mp_["pit_hr"]:
            continue
        num_hr += mp_["pit_hr"][nm] * bf
        num_air += mp_["pit_air"][nm] * bf
        den += bf
    if den <= 0:
        return {}
    return {"act_seen": 1.0, "act_n": float(len(arms)),
            "act_hr": num_hr / den, "act_air": num_air / den}


def _pen_before(cut: str) -> dict:
    """{team abbr: shrunk relief HR and air rates}, strictly before `cut`.

    THE MODEL HAS NO RELIEVER TERM AT ALL. `p_hr` is the STARTER's rate
    and roughly half a hitter's plate appearances come against arms the
    model has never heard of, priced at nothing. And the two populations
    genuinely differ: relief 0.0420 home runs per ball in play against
    starters' 0.0477, a 12% gap, so borrowing the starter's number for
    the whole game is wrong in a known direction.

    THE CLUB, NOT THE ARM, AND THAT IS THE POINT RATHER THAN A
    SIMPLIFICATION. Who actually relieves is not known before first
    pitch — using the arms that did appear would be reading the game's
    own outcome back into its prediction. A club's relief corps as of
    yesterday is knowable, and `deploy.py` already measured that role is
    stable and projects (split-half r +0.55 to +0.78 over 319 relievers).

    Per-arm usage weighting is the better version and this is not it.
    This is the cheap one that says whether the channel carries anything
    before anybody builds that.
    """
    from collections import defaultdict
    c: dict = defaultdict(lambda: {"hr": 0, "air": 0, "bip": 0})
    with store.connect() as conn:
        conn.execute(battedball._TRAJ_SCHEMA)
        for r in conn.execute(
                f"select case when s.side = 'home' then g.home_team_abbr "
                f"else g.away_team_abbr end ab, sum(t.hr) hr, "
                f"sum(t.fb) + sum(t.ld) air, sum(t.bip) bip "
                f"from mlb_traj t join mlb_stints s on s.game_id = t.game_id "
                f"and s.player_name = t.name join {store.BETS}.games g "
                f"on g.game_id = t.game_id where t.role = 'pit' "
                f"and s.appearance_order > 0 and t.date < ? group by ab",
                (cut,)):
            if r["ab"]:
                c[r["ab"]] = {"hr": r["hr"] or 0, "air": r["air"] or 0,
                              "bip": r["bip"] or 0}
    tot = sum(v["bip"] for v in c.values()) or 1
    lg_hr = sum(v["hr"] for v in c.values()) / tot
    lg_air = sum(v["air"] for v in c.values()) / tot
    k = K["pit_hr"]
    return {ab: {"pen_seen": 1.0,
                 "pen_hr": (v["hr"] + k * lg_hr) / (v["bip"] + k),
                 "pen_air": (v["air"] + k * lg_air) / (v["bip"] + k)}
            for ab, v in c.items() if v["bip"] > 0}


def _shrunk(counts, num, den, k, lg):
    return {nm: (num(v) + k * lg) / (den(v) + k)
            for nm, v in counts.items() if den(v) > 0}


def _maps_before(cut: str) -> dict:
    """Both sides' shrunk HR and air rates as of `cut`, strictly prior."""
    out = {}
    for role in ("bat", "pit"):
        c: dict = defaultdict(lambda: {"hr": 0, "air": 0, "bip": 0})
        with store.connect(attach=False) as conn:
            conn.execute(battedball._TRAJ_SCHEMA)
            for r in conn.execute(
                    "select name, sum(hr) hr, sum(fb) + sum(ld) air, "
                    "sum(bip) bip from mlb_traj where role = ? "
                    "and date < ? group by name", (role, cut)):
                c[r["name"]] = {"hr": r["hr"] or 0, "air": r["air"] or 0,
                                "bip": r["bip"] or 0}
        tot_b = sum(v["bip"] for v in c.values()) or 1
        lg_hr = sum(v["hr"] for v in c.values()) / tot_b
        lg_air = sum(v["air"] for v in c.values()) / tot_b
        out[f"{role}_hr"] = _shrunk(c, lambda v: v["hr"],
                                    lambda v: v["bip"], K[f"{role}_hr"],
                                    lg_hr)
        out[f"{role}_air"] = _shrunk(c, lambda v: v["air"],
                                     lambda v: v["bip"], K[f"{role}_air"],
                                     lg_air)
        out[f"{role}_lg_hr"], out[f"{role}_lg_air"] = lg_hr, lg_air
    return out


def build() -> int:
    """One row per batter-game, every feature strictly prior to it."""
    from src.context import calibrate as cal
    with store.connect() as c:
        lineups = [dict(r) for r in c.execute(
            "select game_id, date, team, side, slot, player_name, bat_side "
            "from mlb_lineups order by date")]
        starters = {(r["game_id"], r["side"]): r["player_name"]
                    for r in c.execute(
                        "select game_id, side, player_name from mlb_stints "
                        "where appearance_order = 0")}
        # EVERY ARM THAT ACTUALLY APPEARED — starter included, no split.
        # A pitcher is a pitcher: what a hitter faces over a game is one
        # weighted blend of arms, and `p_hr` is just that blend truncated
        # after the first two or three trips. Weighted by batters faced.
        actual: dict = defaultdict(list)
        for r in c.execute(
                "select game_id, side, player_name, batters from "
                "mlb_stints"):
            actual[(r["game_id"], r["side"])].append(
                (r["player_name"], r["batters"] or 0))
        wx = {r["game_id"]: dict(r) for r in c.execute(
            "select game_id, temp_f, wind_mph, carry from mlb_weather")}
        venue = {r["game_id"]: r["venue_id"] for r in c.execute(
            f"select game_id, venue_id from {store.BETS}.games "
            "where sport = 'mlb'")}
        abbr = {r["game_id"]: (r["away_team_abbr"], r["home_team_abbr"])
                for r in c.execute(
                    f"select game_id, away_team_abbr, home_team_abbr from "
                    f"{store.BETS}.games where sport = 'mlb'")}
        hr_by = {(r["game_id"], r["name"]): r["hr"] for r in c.execute(
            "select game_id, name, hr from mlb_traj where role = 'bat'")}
    # THROWING HAND, from `roster` — the same source the battery uses. It
    # is the single biggest matchup term on this channel: a left-handed
    # bat loses 22% of his home run rate against a left-handed arm
    # (`sim.PLATOON_MULT`), so a model without it is missing the largest
    # thing it could know about a pairing. `mlb_starters` carries no hand
    # column, which is why the first build came back 0% covered.
    from src import roster
    hmap = _hands()["pit"]
    hands: dict = {}
    from scratchpad.hr_savant import _norm
    tiers = {s: _tiers_for(s) for s in SEASONS}
    fits = {s: _fit_for(s) for s in SEASONS}
    vpark = _venue_park()
    rows, cur, mp_ = [], None, None
    for ln in lineups:
        yr = int(ln["date"][:4])
        if yr not in SEASONS:
            continue
        cut = ln["date"][:7] + "-01"
        if cut != cur:
            cur, mp_ = cut, _maps_before(cut)
            pen_ = _pen_before(cut)
        opp = "home" if ln["side"] == "away" else "away"
        sp = starters.get((ln["game_id"], opp))
        b, p = ln["player_name"], sp
        if not sp or b not in mp_["bat_hr"] or p not in mp_["pit_hr"]:
            continue
        w = wx.get(ln["game_id"]) or {}
        park = cal.park_for(venue.get(ln["game_id"]))
        rows.append({
            # OPPORTUNITY, and the model had no idea. A home club skips
            # the bottom of the ninth when it is ahead, so home hitters
            # get 3.4% fewer balls in play than away hitters — measured
            # 2025, negative at every one of the nine slots. `slot` is
            # already the second most valuable input in the model and it
            # is a proxy for exactly this; this is the other half of it.
            "is_home": float(ln["side"] == "home"),
            "game_id": ln["game_id"], "date": ln["date"],
            "batter": b, "pitcher": p, "slot": ln["slot"],
            "b_hr": mp_["bat_hr"][b], "b_air": mp_["bat_air"][b],
            "p_hr": mp_["pit_hr"][p], "p_air": mp_["pit_air"][p],
            "lg_hr": mp_["bat_lg_hr"],
            "b_side": ln["bat_side"] or "",
            # Play-by-play first, roster only as a fallback for an arm
            # with no cached game — never the other way round.
            "p_hand": hands.setdefault(
                p, hmap.get(p) or roster.throws(p) or ""),
            "park_hr": (park or {}).get("hr", 1.0),
            # A STORED ZERO IS NOT A TEMPERATURE. Two games carry 0F, one
            # of them in late June, and it arrived as a real value rather
            # than a null — so the imputation never fired and the model
            # was handed a 72-degree swing on a fabricated reading.
            "temp": (w.get("temp_f")
                     if (w.get("temp_f") or 0) > 20 else None),
            "wind": (w.get("carry") or 0) * (w.get("wind_mph") or 0),
            "y": int((hr_by.get((ln["game_id"], b)) or 0) > 0),
            **tiers[yr].get(_norm(b), {}),
            **_fit_cols(fits[yr].get(_norm(b)),
                        vpark.get(venue.get(ln["game_id"]))),
            # The OPPOSING club's bullpen — index 1 is home, 0 is away,
            # and `opp` is the side doing the pitching.
            **(pen_.get((abbr.get(ln["game_id"]) or ("", ""))[
                opp == "home"]) or {}),
            **_act_cols(actual.get((ln["game_id"], opp)), mp_),
        })
    OUT.write_text(json.dumps(rows))
    n1 = sum(r["y"] for r in rows)
    print(f"  {len(rows):,} batter-games, {n1:,} with a home run "
          f"({n1 / max(len(rows), 1):.2%})")
    print(f"  seasons: " + ", ".join(
        f"{s}:{sum(r['date'][:4] == str(s) for r in rows):,}"
        for s in SEASONS))
    return len(rows)


def _has(c, table) -> bool:
    return bool(c.execute(
        "select 1 from sqlite_master where type='table' and name=?",
        (table,)).fetchone())


#: Feature order is fixed and printed with the coefficients — a silently
#: reordered matrix trains fine and means something else entirely.
FEATS = ("b_hr", "b_air", "p_hr", "p_air", "log5", "slot", "park_hr",
         "temp", "wind", "pl_RR", "pl_RL", "pl_LR", "pl_LL", "pl_unk",
         "t_seen", "t_nd", "t_mg", "t_db", "t_wl",
         "f_seen", "f_fit", "f_raw",
         "pen_seen", "pen_hr", "pen_air", "is_home",
         "act_seen", "act_n", "act_hr", "act_air")

PEN_FEATS = ("pen_seen", "pen_hr", "pen_air")
ACT_FEATS = ("act_seen", "act_n", "act_hr", "act_air")

TIER_FEATS = ("t_seen",) + tuple(k for k, _ in TIER_COLS)
FIT_FEATS = ("f_seen", "f_fit", "f_raw")

#: OFF, AND THE NULL IS MEASURED RATHER THAN ASSUMED. Savant's
#: contact-quality tiers add nothing on top of `b_hr` — four folds,
#: paired, tier columns zeroed against tier columns present, on identical
#: rows with an identical seed: z +0.46 / +0.73 / -0.48 on the three folds
#: that carry tiers. The harness was positive-controlled by ablating
#: `b_hr` and `log5` instead, which it saw at z +3.8 in the same two folds
#: where the tiers read nothing, so this is an absence and not a blind
#: screen. The likely reason is redundancy and not irrelevance: the
#: earlier +2.84 put the tiers against ONE prior season's home run rate,
#: while `b_hr` here is a shrunk season-to-date rate that already knows
#: everything a completed season could say. `--ablate --early` is the one
#: loose end, at pooled z ~+2.0 on March-May rows.
USE_TIERS = False

#: OFF FOR THE CLASSIFIER, AND THE REASON IS NOT THAT THE EFFECT IS ABSENT.
#: Hitter-park fit is REAL — within hitter and within park, z +2.97,
#: monotone across five quintiles, and with a calibrated slope of 0.863 +/-
#: 0.291 against a nominal 1.0, so it needs no fitting. The tails are worth
#: +23.6% / -21.9% on a home run rate, the size of the platoon term.
#: It still does not improve a PER-GAME prediction in any of three model
#: forms, because a game is a 12% coin flip, the effect lives in the tails,
#: and the Brier gain there is smaller than the noise of three added
#: columns. It belongs in `sim.py`, where a multiplier runs over every
#: plate appearance. See the 2026-09-10 park-fit entry and TODO 31.
USE_FIT = False

#: The "pitching he actually faced" block. OFF by default and it must
#: STAY off in anything that reports a deployable number — the arms and
#: their batter counts are known only after the game. It exists to bound
#: how much the pitcher channel could be worth if the blend were known.
USE_ACT = False

#: Both measured NULL and both left live, because that is the state the
#: reported per-game numbers were produced in and the comparison against
#: the per-plate-appearance model has to be against the real incumbent,
#: not a quietly improved one. Bullpen aggregate: z +0.30/+0.07/-0.48/
#: -0.91. Home/away: -3.60/-0.26/+2.26, mixed.
USE_PEN = True
USE_HOME = True


def _log5(b, p, lg):
    if lg <= 0 or lg >= 1:
        return (b + p) / 2
    num = (b * p) / lg
    den = num + ((1 - b) * (1 - p)) / (1 - lg)
    return num / den if den else lg


def _x(r):
    cell = f"{r['b_side']}{r['p_hand']}" if r["p_hand"] else "unk"
    return [
        r["b_hr"], r["b_air"], r["p_hr"], r["p_air"],
        _log5(r["b_hr"], r["p_hr"], r["lg_hr"]),
        r["slot"], r["park_hr"],
        # Missing temperature is imputed at the league mean rather than
        # dropped; the row is still a real batter-game.
        (r["temp"] if r["temp"] is not None else 72.0),
        r["wind"],
        float(cell == "RR"), float(cell == "RL"),
        float(cell == "LR"), float(cell == "LL"), float(cell == "unk"),
        # EXPLICIT MISSING, not a silent neutral. A batter with no prior
        # major league home run has no tier row, and imputing him to the
        # league's average power shape would say something false about the
        # exact population — rookies and September call-ups — where it is
        # most wrong. `t_seen` lets the model learn that group separately;
        # every tier column is then read only in company with it.
        r.get("t_seen", 0.0),
        *(r.get(k, 0.0) for k, _ in TIER_COLS),
        *(r.get(k, 0.0) for k in FIT_FEATS),
        *(r.get(k, 0.0) for k in PEN_FEATS),
        r.get("is_home", 0.0),
        *(r.get(k, 0.0) for k in ACT_FEATS),
    ]


def _load(tiers: bool | None = None):
    """The design matrix. With `tiers` false the tier block is ZEROED
    rather than dropped, so the column indices in `FEATS` stay valid and
    `--ablate` can turn them back on without a second code path. A
    constant column is inert to both models."""
    import numpy as np
    rows = json.loads(OUT.read_text())
    X = np.array([_x(r) for r in rows], dtype=float)
    if not (USE_TIERS if tiers is None else tiers):
        X[:, [FEATS.index(f) for f in TIER_FEATS]] = 0.0
    if not USE_FIT:
        X[:, [FEATS.index(f) for f in FIT_FEATS]] = 0.0
    # The ceiling block is OFF unless something asks for it — it is not
    # deployable and must never sit in a baseline by accident.
    if not USE_ACT:
        X[:, [FEATS.index(f) for f in ACT_FEATS]] = 0.0
    if not USE_PEN:
        X[:, [FEATS.index(f) for f in PEN_FEATS]] = 0.0
    if not USE_HOME:
        X[:, FEATS.index("is_home")] = 0.0
    y = np.array([r["y"] for r in rows], dtype=int)
    yr = np.array([int(r["date"][:4]) for r in rows])
    return rows, X, y, yr


def _score(name, p, y):
    import numpy as np
    from sklearn.metrics import roc_auc_score, log_loss, brier_score_loss
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return (f"    {name:<26}{roc_auc_score(y, p):>8.4f}"
            f"{log_loss(y, p):>10.5f}{brier_score_loss(y, p):>10.5f}"
            f"{p.mean():>9.4f}{y.mean():>9.4f}")


def deciles(p, y, label):
    """The `hrbat` table, on the classifier — same construction, so the
    two are directly comparable rather than merely both about home runs."""
    import numpy as np
    o = np.argsort(p)
    cut = [len(p) * i // 10 for i in range(11)]
    print(f"\n    {label}: predicted vs actual by decile of its own "
          "prediction")
    out = []
    for i in range(10):
        idx = o[cut[i]:cut[i + 1]]
        out.append((p[idx].mean(), y[idx].mean(), len(idx)))
        print(f"      d{i + 1:<3}{p[idx].mean():>9.4f}{y[idx].mean():>9.4f}"
              f"{len(idx):>9,}")
    print(f"      spread top-bottom: predicted "
          f"{out[-1][0] - out[0][0]:.4f}   actual "
          f"{out[-1][1] - out[0][1]:.4f}")
    return out


def fit(test_year: int = 2026) -> None:
    """Train on every other season, score on `test_year`.

    BY SEASON AND NOT AT RANDOM. A random split puts the same
    batter-month on both sides — his rate features are a monthly
    aggregate, so a random hold-out leaks him to himself and every model
    below would score better than it deserves.
    """
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    rows, X, y, yr = _load()
    tr, te = yr != test_year, yr == test_year
    print(f"\n  train {tr.sum():,} batter-games "
          f"({sorted(set(yr[tr]))}), test {te.sum():,} ({test_year})")
    print(f"    {'model':<26}{'AUC':>8}{'logloss':>10}{'brier':>10}"
          f"{'mean p':>9}{'actual':>9}")
    preds = {}
    base = np.full(te.sum(), y[tr].mean())
    print(_score("league rate (baseline)", base, y[te]))
    # HIS OWN RATE ALONE, scaled onto the training level — the "he is a
    # power hitter" model, and the thing any of this has to beat.
    own = X[:, FEATS.index("b_hr")]
    lr0 = LogisticRegression(max_iter=1000).fit(
        own[tr].reshape(-1, 1), y[tr])
    p0 = lr0.predict_proba(own[te].reshape(-1, 1))[:, 1]
    preds["batter rate only"] = p0
    print(_score("batter rate only", p0, y[te]))
    sc = StandardScaler().fit(X[tr])
    lr = LogisticRegression(max_iter=2000).fit(sc.transform(X[tr]), y[tr])
    p1 = lr.predict_proba(sc.transform(X[te]))[:, 1]
    preds["logistic (all features)"] = p1
    print(_score("logistic (all features)", p1, y[te]))
    gb = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.06, max_leaf_nodes=15,
        l2_regularization=1.0, random_state=0).fit(X[tr], y[tr])
    p2 = gb.predict_proba(X[te])[:, 1]
    preds["gradient boosting"] = p2
    print(_score("gradient boosting", p2, y[te]))
    print("\n    logistic coefficients (standardised):")
    for f, c_ in sorted(zip(FEATS, lr.coef_[0]), key=lambda t: -abs(t[1])):
        print(f"      {f:<10}{c_:>+8.4f}")
    for lab in ("logistic (all features)", "gradient boosting"):
        deciles(preds[lab], y[te], lab)
    np.save("scratchpad/hr_clf_pred.npy", np.vstack([p1, p2]))
    json.dump([{"game_id": r["game_id"], "batter": r["batter"],
                "y": r["y"]} for r, m in zip(rows, te) if m],
              open("scratchpad/hr_clf_test_keys.json", "w"))


def vs_sim(dump: str = "scratchpad/simpred.2026.json") -> None:
    """HEAD TO HEAD ON IDENTICAL ROWS, which is the only honest version.

    The `hrbat` deciles in the notes are on PAIRED July-onward games —
    both starters modelled, ~676 of the season — and the classifier's
    test set is all of 2026. Comparing those two tables directly would
    be comparing populations, not models, and would have handed the
    classifier a win it might not have earned. This joins on
    (game_id, batter) and scores both on the intersection.

    THE CLASSIFIER IS STILL THE ONE WITH THE ADVANTAGE HERE, and it is
    worth naming rather than burying: it TRAINED on 2023-2025 with the
    outcome in front of it, while the engine was never fitted to a home
    run at all. A narrow classifier win is not evidence the approach is
    better; a classifier LOSS would be strong evidence it is not.
    """
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    sim = {(r["game_id"], r["batter"]): r for r in
           json.loads(pathlib.Path(dump).read_text())}
    rows, X, y, yr = _load()
    tr = yr != 2026
    keys = [(r["game_id"], r["batter"]) for r in rows]
    te = np.array([k in sim and yr[i] == 2026 for i, k in enumerate(keys)])
    print(f"\n  HEAD TO HEAD on {te.sum():,} batter-games both models "
          f"scored (2026 paired games)")
    sc = StandardScaler().fit(X[tr])
    lr = LogisticRegression(max_iter=2000).fit(sc.transform(X[tr]), y[tr])
    gb = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.06, max_leaf_nodes=15,
        l2_regularization=1.0, random_state=0).fit(X[tr], y[tr])
    p_lr = lr.predict_proba(sc.transform(X[te]))[:, 1]
    p_gb = gb.predict_proba(X[te])[:, 1]
    p_sim = np.array([sim[k]["p"] for k, m in zip(keys, te) if m])
    yt = y[te]
    y_sim = np.array([sim[k]["y"] for k, m in zip(keys, te) if m])
    agree = (y_sim == yt).mean()
    print(f"    label agreement between the two pipelines: {agree:.4%}"
          "   (a join this size with a different label is a bug, not a "
          "result)")
    print(f"    {'model':<26}{'AUC':>8}{'logloss':>10}{'brier':>10}"
          f"{'mean p':>9}{'actual':>9}")
    for lab, p in (("simulation", p_sim), ("logistic", p_lr),
                   ("gradient boosting", p_gb)):
        print(_score(lab, p, yt))
    for lab, p in (("simulation", p_sim), ("gradient boosting", p_gb)):
        deciles(p, yt, lab)
    # PAIRED, per held-out batter-game — the se of the difference, not of
    # either score.
    for lab, p in (("logistic", p_lr), ("gradient boosting", p_gb)):
        d = (p_sim - yt) ** 2 - (p - yt) ** 2
        se = d.std(ddof=1) / len(d) ** 0.5
        print(f"\n    paired brier, simulation - {lab}: "
              f"{d.mean():+.3e}  se {se:.3e}  z {d.mean() / se:+.2f}")


def vs_sim_all() -> None:
    """FOUR FOLDS, and the sim RECALIBRATED — the two checks the single
    2026 comparison cannot make.

    RULE 12b: one holdout is not a measurement of generalisation, and
    2026 is precisely the fold where the engine is known to run hot
    (`hrbat.p_hr_level` +3.9). So a 2026-only win could be nothing but
    the classifier having a better LEVEL, which is the cheapest possible
    edge and not a reason to change approach.

    THE DECOMPOSITION: the engine's predictions are re-levelled onto the
    test season's own base rate — an advantage the engine could never
    have in real time, granted deliberately — and scored again. What
    survives that is DISCRIMINATION, which is the thing worth having.
    """
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    rows, X, y, yr = _load()
    keys = [(r["game_id"], r["batter"]) for r in rows]
    print(f"\n  {'fold':<6}{'n':>8}{'AUC sim':>9}{'AUC gb':>8}"
          f"{'brier sim':>11}{'+recal':>9}{'brier gb':>10}"
          f"{'z raw':>8}{'z recal':>9}")
    for year in SEASONS:
        f = pathlib.Path(f"scratchpad/simpred.{year}.json")
        if not f.exists():
            continue
        sim = {(r["game_id"], r["batter"]): r
               for r in json.loads(f.read_text())}
        te = np.array([k in sim and yr[i] == year
                       for i, k in enumerate(keys)])
        tr = yr != year
        if te.sum() < 500:
            continue
        gb = HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.06, max_leaf_nodes=15,
            l2_regularization=1.0, random_state=0).fit(X[tr], y[tr])
        p_gb = gb.predict_proba(X[te])[:, 1]
        p_sim = np.array([sim[k]["p"] for k, m in zip(keys, te) if m])
        yt = y[te]
        # RE-LEVEL the engine onto the test season's base rate, in odds,
        # so only its ordering is being judged.
        o = p_sim / np.clip(1 - p_sim, 1e-9, None)
        scale = (yt.mean() / (1 - yt.mean())) / (o.mean())
        p_rec = (o * scale) / (1 + o * scale)
        from sklearn.metrics import roc_auc_score, brier_score_loss
        b_sim = brier_score_loss(yt, np.clip(p_sim, 1e-6, 1 - 1e-6))
        b_rec = brier_score_loss(yt, np.clip(p_rec, 1e-6, 1 - 1e-6))
        b_gb = brier_score_loss(yt, np.clip(p_gb, 1e-6, 1 - 1e-6))

        def _z(a, b):
            d = (a - yt) ** 2 - (b - yt) ** 2
            return d.mean() / (d.std(ddof=1) / len(d) ** 0.5)

        print(f"  {year:<6}{te.sum():>8,}"
              f"{roc_auc_score(yt, p_sim):>9.4f}"
              f"{roc_auc_score(yt, p_gb):>8.4f}"
              f"{b_sim:>11.5f}{b_rec:>9.5f}{b_gb:>10.5f}"
              f"{_z(p_sim, p_gb):>+8.2f}{_z(p_rec, p_gb):>+9.2f}")
    print("\n  z is PAIRED brier, positive = the classifier wins. "
          "`+recal` grants the\n  engine the test season's own base "
          "rate, which it could never have live —\n  what survives that "
          "column is ordering, not level.")


def ablate() -> None:
    """DID THE TIERS ADD ANYTHING — four folds, paired, same rows.

    The logistic coefficients cannot answer this and it is worth saying
    why rather than reading them anyway: `log5` is built out of `b_hr` and
    `p_hr`, and a slugger's tier shares move with his home run rate, so
    the tier columns are collinear with three features that are already
    there. Collinearity parks the coefficient near zero whether the
    information is redundant or merely double-counted.

    So the model is refitted with the tier columns ZEROED — identical
    rows, identical hyperparameters, identical seed, one block of the
    matrix blanked — and the two are scored PAIRED on the same held-out
    batter-games.

    READ THE 2023 ROW AS A DIAGNOSTIC AND NOT AS EVIDENCE EITHER WAY. It
    carries no tier data, so it trains on three seasons where 89% of rows
    have `t_seen = 1` and then scores rows where every tier is zero — a
    value the model has only ever seen on rookies. It duly routes the
    whole fold down the rookie branch and reads about -10. That is
    distribution shift between train and test, which is a fact about the
    fold structure; the tier question is settled by 2024-2026, where both
    sides of the split carry tiers.

    AND THE HARNESS IS POSITIVE-CONTROLLED, `--control`, because a screen
    too blunt to see anything and a real absence print the same table.
    """
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    # Load the tier block only when it is what is under test — otherwise
    # a known-null block would sit in the baseline of every other run.
    rows, X, y, yr = _load(tiers=any(c in TIER_FEATS for c in ablate.cols))
    tcols = [FEATS.index(f) for f in ablate.cols]
    X0 = X.copy()
    X0[:, tcols] = 0.0
    print(f"\n  ABLATING {', '.join(ablate.cols)}")
    # Report the coverage of the block ACTUALLY under test, not a fixed
    # column — the first version printed `t_seen` while ablating the park
    # fit, which reads as 0% coverage for a block that has plenty.
    cov = next((c for c in ablate.cols if c.endswith("_seen")), "t_seen")
    print(f"\n  {'fold':<6}{'n':>8}{'AUC off':>9}{'AUC on':>8}"
          f"{'brier off':>11}{'brier on':>10}{'z':>8}{cov:>9}")
    for year in SEASONS:
        tr, te = yr != year, yr == year

        def _p(m):
            gb = HistGradientBoostingClassifier(
                max_iter=300, learning_rate=0.06, max_leaf_nodes=15,
                l2_regularization=1.0, random_state=0).fit(m[tr], y[tr])
            return gb.predict_proba(m[te])[:, 1]

        p_off, p_on, yt = _p(X0), _p(X), y[te]
        if ablate.early:
            # COLD START ONLY. `b_hr` is a season-to-date rate, so in
            # April it is almost all prior — the population where a
            # completed season's quality read has the most left to add.
            # Training is untouched; only the scored rows narrow.
            m = np.array([r["date"][5:7] in ("03", "04", "05")
                          for r, k in zip(rows, te) if k])
            p_off, p_on, yt = p_off[m], p_on[m], yt[m]
        d = (p_off - yt) ** 2 - (p_on - yt) ** 2
        se = d.std(ddof=1) / len(d) ** 0.5
        print(f"  {year:<6}{len(yt):>8,}"
              f"{roc_auc_score(yt, p_off):>9.4f}"
              f"{roc_auc_score(yt, p_on):>8.4f}"
              f"{((p_off - yt) ** 2).mean():>11.5f}"
              f"{((p_on - yt) ** 2).mean():>10.5f}"
              f"{d.mean() / se:>+8.2f}"
              f"{X[te][:, FEATS.index(cov)].mean():>9.1%}")
    print("\n  z is PAIRED brier, positive = the ablated block helps. "
          "2023 has NO tier\n  data and is train/test distribution shift, "
          "not a reading — see the\n  docstring. Run --control for the "
          "harness's positive control.")


#: What `--ablate` blanks. Overridden by `--control`, which blanks the
#: batter's own home run rate instead — a feature known to carry signal, so
#: the harness MUST light up on it. A screen that cannot see a real effect
#: and a screen reporting a real absence produce the same table.
ablate.cols = TIER_FEATS
ablate.early = False


def main(argv):
    ablate.early = "--early" in argv
    if "--control" in argv:
        ablate.cols = ("b_hr", "log5")
    if "--ablate" in argv or "--control" in argv:
        ablate()
    if "--vs-sim-all" in argv:
        vs_sim_all()
    if "--vs-sim" in argv:
        vs_sim()
    if "--build" in argv:
        build()
    if "--fit" in argv:
        fit()


if __name__ == "__main__":
    main(sys.argv[1:])
