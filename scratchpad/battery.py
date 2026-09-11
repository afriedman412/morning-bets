"""ONE COMMAND, EVERY TABLE — the standing scorecard for the whole engine.

    venv/bin/python -m scratchpad.battery [n_sims] [--folds 2026,2025]
        [--limit N] [--diff FINGERPRINT] [--maim]

WHY (PLAN-baseball-logic item 0). Twenty days of one-defect-one-scratchpad
meant each session scored the thing it built and nothing else. The
fourth-inning defect and the 60-85 pitch defect were ONE defect seen
through two instruments and it took days to notice. A fix in `apply_pa`
moves the hook cells; a park change moves traffic and therefore the hook;
nothing showed the side effect until someone happened to run the other
script. The battery makes every change score against everything, the same
afternoon.

ONE SIMULATION PASS PER FOLD — the `board.py` rule: one payload, many
views, so the views cannot disagree. Every row below is read off the SAME
games and the SAME draws. 40 sims a game, seeds paired per (game, draw) on
a crc32 of the game id so adding or removing a game cannot shift any other
game's stream. Fold = one season scored July 1 onward with rates frozen
before that cut — the same four folds as `pxi_cv.py` / `hz_cv.py`.

THE ROWS, all model vs real with gap, se, z and the Monte-Carlo floor:

    ladder      prefix F1/F3/F5/F7, combined runs (paired per game)
    inning      runs per inning 1-8 and 9+ (the `where_runs` convention:
                runs on a play are the score CHANGE across it)
    game        one-run-game share, extras share
    venue       F5 and full team-total residual per venue, sorted |gap|
    traffic     runs per baserunner (whole game, every arm), full-game
                team-run mass at 0, 0-3, 8+, F5 team shutout share
    platoon     K and HR per PA against the STARTER, split by whether the
                batter had the platoon advantage; stacked-lineup top-decile
                team-total residual with the all-games residual as control
    contact     DP per opportunity, sacrifice per PA, XBH share of non-HR
                hits, HR per ball in play; GB%-quintile rows EMPTY until
                item 4a plumbs `gb_pct` (printed empty, not omitted)
    weather     HR/BIP by temperature bucket — EMPTY until item 5
    late        innings 7-9: runs per inning by |margin| when it started
    save        a lead of 1-3 after eight: how often it is HELD, and what
                the protecting side allows from the ninth on (0, 2+). The
                OUTCOME the bullpen items aim at — every other bullpen row
                here is a proxy, and `late` is all means
    pen         relief outing length: mean outs, the <=2 and >=7 shares, the
                mid-inning ENTRY share and ARMS PER SIDE. Added 2026-09-09
                because four bullpen mechanisms shipped that day and none
                moved a row here — and no row here COULD have moved, which
                is the obligation the "nothing moved" rule imposes. Arms per
                side is the one a total feels: every handover is a fresh
                pitcher facing the top of the order
    hook        both curves, model hazard vs real rate on the
                `pitch_hazard` bucket edges (holdout rows of the fold)
    shape       starter outs/K mean+sd, K 9+ share, outs over-lines,
                boundary share BY DECISION, round-number spike heights and
                the mid-inning share of each spike
    outs_adjust the current betting-layer band corrections, informational

DEFINITIONS THE REAL SIDE COUNTS WITH (must match the model side):
  * baserunner: BB/IBB/HBP/1B/2B/3B/HR/ROE. Steals move nobody onto base.
  * ball in play: 1B/2B/3B/HR + in-play outs + ROE + sacrifices.
  * DP opportunity: man on first, <2 out, ball-in-play out (sacs excluded,
    strikeouts excluded) — the model's `o == OUT` branch, exactly.
  * platoon advantage: batter's side != pitcher's hand. Model batter sides
    come from the game's own play-by-play (`mlb_lineups` covers only a
    fifth of the cache); PAs whose batter has no known side are dropped
    from the platoon rows and counted as coverage.
  * top half of an inning: the AWAY club bats, so the HOME side pitches.
    (`f5_decomp` labels this backwards and gets away with it by pooling.)

THE HEADER PRINTS EVERY `USE_*` FLAG in `sim`, `game` and `calibrate`, so
a run can never be mis-attributed to the wrong configuration.
`tests/test_battery.py` proves a flipped flag changes the header.

OUTPUT: `scratchpad/battery_<engine-fingerprint>.json` plus the terminal
dump. `--diff <fingerprint>` runs the battery and then prints every row
that moved by more than one se against that saved run — and nothing else.
If the engine fingerprint has NOT moved, the mechanism under test is not
live; the file is saved with a `_dup` suffix so the baseline survives.

`--maim` is the POSITIVE CONTROL: it halves `sim.ADVANCE_3B_ON_OUT` before
simulating. Traffic and run rows must move, pure event-rate rows (sac per
PA, XBH share, HR per BIP) must not. A battery that cannot see a planted
defect is not a measurement.

DEV RUNS: `--limit` or sims != 40 stamps DEV on the header and the JSON.
No number from a dev run is reportable — `price.N_SIMS` and `tonight.py`'s
400 are not measurement settings, and neither is `--limit 60`.
"""
from __future__ import annotations

import hashlib
import json
import os
import multiprocessing as mp
import random
import statistics as st
import sys
import zlib
from collections import Counter, defaultdict

from src import db, roster
from src.context import boundary, calibrate as cal, game, sim
from src.context.sources import pbp, rates as rate_src
from scratchpad.pitch_hazard import EDGES, ROWS

FOLDS = ((2023, "2023-07-01"), (2024, "2024-07-01"),
         (2025, "2025-07-01"), (2026, "2026-07-01"))

#: Innings tracked in the one pass. 18 is the ceiling (`max_extra=9`).
TRACK = tuple(range(1, 19))
LADDER = (1, 3, 5, 7)
SPIKES = (9, 12, 15, 18, 21)
OUTS_LINES = (12.5, 14.5, 15.5, 16.5, 17.5, 18.5, 20.5)
MARGIN_CAP = 4          # |margin| buckets 0,1,2,3,4+
MIN_REAL_HOOK = 120     # same floor as hz_cells
MIN_VENUE = 20          # team-games before a venue row prints

_CASES: dict = {}
_LG: dict = {}
_PENS: dict = {}
_SIMS = 40
_HANDS: dict = {}       # starter name -> throwing hand
_PIDS: dict = {}        # starter name -> mlb player id

#: Per-draw logs the wrappers write into. Cleared by the worker per draw.
_PA_LOG: list = []
_HOOK_LOG: list = []
#: (side id, entry_outs, outs, batters) for each arm as he LEAVES. `Side`
#: keeps only the STARTER's line and folds every relief line away at
#: handover, so the outgoing arm has to be recorded at the handover or he is
#: gone. The last arm on each side never hands over and is appended by the
#: worker from `cur_line`.
_ARM_LOG: list = []
#: The two `Side` objects of the draw in flight, so the worker can reach the
#: arm still on the mound when the game ended.
_SIDES: list = [None, None]
_WRAPPED = [False]

#: Real-side event sets, mirroring the model's outcome alphabet.
EV_K = ("strikeout", "strikeout_double_play", "strikeout_triple_play")
EV_BB = ("walk", "intent_walk")
EV_HIT = {"single": "1B", "double": "2B", "triple": "3B", "home_run": "HR"}
EV_SAC = ("sac_fly", "sac_bunt", "sac_fly_double_play",
          "sac_bunt_double_play")
EV_INPLAY_OUT = ("field_out", "force_out", "grounded_into_double_play",
                 "double_play", "triple_play", "fielders_choice",
                 "fielders_choice_out")
EV_DP = ("grounded_into_double_play", "double_play")
EV_REACH = EV_BB + ("hit_by_pitch", "field_error") + tuple(EV_HIT)


def flags() -> dict:
    """Every USE_* switch in the three modules, live values, plus the two
    non-USE_ knobs that change what a run means. THE WIRING CONTRACT: a
    battery run is attributable to a configuration only if this is total,
    and `tests/test_battery.py` holds it to that."""
    out = {}
    for m in (sim, game, cal):
        for k in sorted(vars(m)):
            if k.startswith("USE_"):
                out[f"{m.__name__.rsplit('.', 1)[-1]}.{k}"] = getattr(m, k)
    out["calibrate.NEUTRALISE_PARK"] = getattr(cal, "NEUTRALISE_PARK", None)
    out["calibrate.HOME_HOOK"] = getattr(cal, "HOME_HOOK", None)
    # The recency half-life changes every pitcher rate a fold is built on.
    # It earned this line the hard way: a five-candidate sweep set it
    # in-process, `main`'s macOS re-exec silently reset it, and all five
    # runs printed the same fingerprint — with the knob in the header the
    # vacuous run would have been visible on sight.
    out["rates.HALF_LIFE_DAYS"] = getattr(rate_src, "HALF_LIFE_DAYS", None)
    return out


#: THE HOME RUN PROBABILITY OF THE PLATE APPEARANCE `pa_from` IS ABOUT TO
#: DRAW, stashed by the `pa_from` wrapper and read by the `apply_pa`
#: wrapper one line later — `game._half_inning` calls them back to back
#: for the same batter, and a forked child plays one game at a time, so
#: the pairing cannot slip.
#:
#: WHY AN ANALYTIC PROBABILITY AND NOT THE SHARE OF DRAWS HE WENT DEEP IN,
#: which is what the first version of the `hrbat` rows used. Rule 10's
#: second half: a Monte Carlo mean carries its own noise. At 40 draws the
#: standard error of that share is ~0.05 at a base rate of 0.12, which is
#: the SAME SIZE as the real spread between hitters — so ranking batters
#: by it ranks them mostly by simulation noise, the top decile is selected
#: on that noise and reports an inflated model probability, and the real
#: rate in it is attenuated toward the mean. The 8-draw smoke run showed
#: exactly that: a claimed spread of 0.356 against a real 0.006, and BOTH
#: numbers were artefacts. This estimator's only remaining variance is
#: which arms he actually faced, which is a real feature of the night.
_PHR = [0.0]


def _hr_prob(mu, tto, state) -> float:
    """P(home run) for one plate appearance, unconditional, from `mu`.

    The same three lines `pa_from` uses, with the `/ cond` left off —
    `cond` is exactly the probability that neither the sacrifice nor the
    hit-by-pitch fired off the top, and dividing by it is what makes the
    drawn value CONDITIONAL on that. The unconditional probability is the
    raw one, and that is what "does he homer tonight" is asking for.
    """
    p_hr = mu.p_hr
    m = sim.tto_mult(tto)
    if m is not None:
        p_hr *= m["hr_pct"]
    s_hr = 1.0
    st_ = sim.state_mult(state)
    if st_ is not None:
        s_hr = st_.get("hr_pct", 1.0)
    return sim.odds_mult(sim.log5(mu.b_hr, p_hr, mu.lg_hr),
                         mu.m_hr * s_hr, mu.lg_hr)


def _install():
    """Wrap `sim.apply_pa` and both hook curves to log, changing nothing.

    Installed ONCE in the parent before any pool forks, so every child
    inherits exactly one layer — `hz_cells` re-wraps per game and stacks
    wrappers, which happens to cancel in its means and would not cancel in
    these counts. The wrappers consume no randomness and return the
    original values, so the engine fingerprint is identical wrapped or not.
    """
    if _WRAPPED[0]:
        return
    _WRAPPED[0] = True
    orig = sim.apply_pa

    def apply_pa(o, r, fr, rng, batter=None, mu=None):
        # `batter` is the NAME STRING — `_half_inning` passes
        # `side.lineup[slot].name`, not the BatterRates object. `mu` must
        # travel through or the DP roll loses its GB odds inside battery
        # runs only — a wrapper that swallows a kwarg is a silent flag-off.
        pre_first = bool(fr.bases[0])
        pre_outs = fr.outs
        orig(o, r, fr, rng, batter, mu)
        _PA_LOG.append((id(r), o, batter, pre_first, pre_outs,
                        fr.outs - pre_outs, _PHR[0]))

    sim.apply_pa = apply_pa

    orig_pa_from = sim.pa_from

    def pa_from(mu, rng, tto=None, state=None):
        _PHR[0] = _hr_prob(mu, tto, state)
        return orig_pa_from(mu, rng, tto, state)

    sim.pa_from = pa_from
    game.sim.pa_from = pa_from

    bnd, mid = sim.Hook.removal_p, sim.Hook.mid_removal_p

    def removal_p(self, pitches, *a, **k):
        p = bnd(self, pitches, *a, **k)
        _HOOK_LOG.append(("bnd", _bucket(pitches), p))
        return p

    def mid_removal_p(self, pitches, *a, **k):
        p = mid(self, pitches, *a, **k)
        _HOOK_LOG.append(("mid", _bucket(pitches), p))
        return p

    sim.Hook.removal_p, sim.Hook.mid_removal_p = removal_p, mid_removal_p

    # RELIEF OUTING LENGTH — the row the bullpen items had no scorecard for.
    # Four mechanisms shipped on 2026-09-09 aimed at how long an arm stays
    # out there and not one of them could be scored here, because every
    # other row in this file reads runs, outs or a hook cell. `pen_shape.py`
    # measured it off to one side, which is exactly the one-defect-one-
    # scratchpad habit the battery exists to end.
    orig_next = game.Side.next_arm

    def next_arm(self, entry_outs=0, rng=None, inning=0, margin=None):
        _ARM_LOG.append((id(self), self.cur_entry_outs,
                         self.cur_line.outs, self.cur_line.batters))
        return orig_next(self, entry_outs, rng, inning, margin)

    game.Side.next_arm = next_arm

    orig_game = game.simulate_game

    def simulate_game(A, H, *a, **k):
        _SIDES[0], _SIDES[1] = A, H
        return orig_game(A, H, *a, **k)

    game.simulate_game = simulate_game
    cal.game.simulate_game = simulate_game


def _bucket(p):
    for lo, hi in zip(EDGES, EDGES[1:]):
        if lo <= p < hi:
            return lo
    return EDGES[-2]


def engine_fingerprint(pairs, lg, pens, n_games=200, n_sims=2) -> str:
    """The same recipe as `scratchpad/fingerprint.py`, inlined so the
    battery stamps its own JSON. Cheap: 200 games x 2 sims."""
    h = hashlib.md5()
    for i, gid in enumerate(sorted(pairs)[:n_games]):
        for draw in range(n_sims):
            rng = random.Random(7 + i * 100003 + draw)
            r = cal.replay(pairs[gid], lg, pens, rng, track=(5,))
            h.update(f"{r.away},{r.home},{r.away_sp.outs},{r.away_sp.k},"
                     f"{r.home_sp.outs},{r.home_sp.k},"
                     f"{r.prefix_side.get(5)}|".encode())
    return h.hexdigest()


def save_cell(a8: int, h8: int, away: int, home: int) -> dict:
    """The save situation, defined ONCE for both sides of the battery.

    A lead of 1-3 after EIGHT innings. `held` is whether the club that led
    went on to WIN; `r0`/`r2` are what the club PROTECTING the lead gave up
    from the ninth on.

    Both sides call this. They used to carry their own copy of the
    arithmetic, which is how a row ends up comparing two populations that
    are not the same thing and reading as a permanent defect — and a test
    written against a third copy would have passed through all of it.
    """
    sv = {"n": 0, "held": 0, "r0": 0, "r2": 0}
    if 1 <= abs(a8 - h8) <= 3:
        lead_away = a8 > h8
        gave = (home - h8) if lead_away else (away - a8)
        sv["n"] = 1
        sv["held"] = int((away > home) if lead_away else (home > away))
        sv["r0"] = int(gave == 0)
        sv["r2"] = int(gave >= 2)
    return sv


# ── the one pass: model side ────────────────────────────────────────────

def _collect_pen(acc: dict) -> None:
    """Fold the draw's relief outings into `acc`, one entry per arm.

    THE PHANTOM ARM, and it is 80% of sides. `game._end_of_inning` fires
    after the LAST inning too, so a failed continuation roll warms up a
    reliever who never faces a batter. He is not a relief outing and
    `mlb_stints` has no row for him — counting him reads 4.23 arms a side
    against a real 3.38 and puts 41% of outings at two outs or fewer, a
    wrong instrument rather than a wrong engine. Filter on `batters > 0`.

    THE STARTER IS DROPPED per side, not globally: the first entry a side
    logs is its starter handing over, and a side whose starter went the
    distance logs exactly one entry, which is that same starter.
    """
    by_side: dict = defaultdict(list)
    for sid, entry_outs, outs, batters in _ARM_LOG:
        by_side[sid].append((entry_outs, outs, batters))
    for side in _SIDES:
        if side is None:
            continue
        by_side[id(side)].append((side.cur_entry_outs, side.cur_line.outs,
                                  side.cur_line.batters))
    for sid, arms in by_side.items():
        acc["sides"] += 1
        used = 0
        for entry_outs, outs, batters in arms[1:]:
            if batters <= 0:
                continue
            used += 1
            acc["n"] += 1
            acc["outs"] += outs
            acc["outs2"] += outs * outs
            acc["le2"] += outs <= 2
            acc["ge7"] += outs >= 7
            acc["mid"] += entry_outs > 0
        acc["arms2"] += used * used


def _model_one(gid: str) -> dict:
    """Simulate one game `_SIMS` times, every view read off the same draws."""
    pair = _CASES[gid]
    away, home = pair
    sp_hand = {"away": _HANDS.get(away[0]["player_name"]),
               "home": _HANDS.get(home[0]["player_name"])}
    bside = _BSIDE.get(gid, {})
    m = {"lad": {p: 0.0 for p in LADDER},
         "inn": {i: 0.0 for i in list(range(1, 9)) + [9]},
         "one": 0.0, "ext": 0.0, "a": 0.0, "h": 0.0, "af": 0.0, "hf": 0.0,
         "late": {b: [0.0, 0] for b in range(MARGIN_CAP + 1)},
         # THE SAVE SITUATION — a lead of 1-3 after eight. `n` is how many
         # draws reached one, `held` how many the leading club went on to
         # win, and the two mass cells are what the protecting side allowed
         # from the ninth on. A RATE and a SHAPE, because the mean of
         # ninth-inning runs is exactly what a better closer does not move.
         "save": {"n": 0, "held": 0, "r0": 0, "r2": 0},
         # RELIEF OUTING LENGTH. `n` outings, `outs` their total, and the
         # two tail shares — a one-inning arm and a two-inning arm are the
         # same mean and a different bullpen, so the mean alone is not the
         # row. `sides` counts club-games so `arms` can be a per-side rate.
         "pen": {"n": 0, "outs": 0, "outs2": 0, "le2": 0, "ge7": 0,
                 "mid": 0, "sides": 0, "arms2": 0},
         "hook": {"bnd": defaultdict(lambda: [0.0, 0]),
                  "mid": defaultdict(lambda: [0.0, 0])},
         "sp": {s: {"outs": Counter(), "k": Counter(), "spike_mid": Counter(),
                    "mid": 0, "dp_opp": 0, "dp": 0}
                for s in ("away", "home")},
         # Per-batter singles and extra-base hits, for the GB-quintile
         # rows — {name: [1b, xbh]} summed over draws.
         "bathits": defaultdict(lambda: [0, 0]),
         # PER-BATTER HOME RUNS — {name: [draws he went deep in, home
         # runs, plate appearances]}. The first entry over `_SIMS` IS the
         # model's answer to "does this man homer tonight", which is the
         # only form of the question anyone actually asks and the one no
         # row in this file could see: every other home run row here is a
         # CLUB total.
         "bathr": defaultdict(lambda: [0, 0, 0]),
         # Balls in play and home runs off each STARTER, for the
         # air-share cells — [bip, hr] per side.
         "sp_hr": {s_: [0, 0] for s_ in ("away", "home")},
         "pa": Counter(), "plat": Counter(),
         # Draw-level distributions per CLUB, so mass rows are read off the
         # actual draws rather than a normal approximation to their mean.
         "dist_full": Counter(), "dist_f5": Counter(),
         # HOME RUNS PER CLUB-GAME, as a DISTRIBUTION and not a mean. The
         # `contact.hr_per_bip` row above is the mean and it has read
         # healthy throughout; the mean is exactly what a clustering
         # defect does not move (rule 2, and the strikeout tail is the
         # standing example — an exact mean at 4.86 against 4.84 hiding a
         # 3.9 sigma miss at nine or more). Two entries per draw, one per
         # batting club.
         "hrdist": Counter()}
    # WHICH CLUB A BATTER HITS FOR, by name. `away[2]` is the nine the
    # away PITCHER faces — the HOME club's batters — per the standing
    # crossing this file already relies on for `advshare`. The lineup is a
    # fixed nine in the engine, so every logged batter resolves; built
    # once per game, because a module global would carry one game's names
    # into the next one in the same pool worker.
    club_of = {b.name: club
               for club, nine in (("home", away[2]), ("away", home[2]))
               for b in nine}
    for draw in range(_SIMS):
        rng = random.Random((zlib.crc32(gid.encode()) & 0xFFFFFF) * 100003
                            + draw)
        _PA_LOG.clear()
        _HOOK_LOG.clear()
        _ARM_LOG.clear()
        r = cal.replay(pair, _LG, _PENS, rng, track=TRACK)
        _collect_pen(m["pen"])
        ps = r.prefix_side
        for p in LADDER:
            m["lad"][p] += r.prefix.get(p, r.away + r.home)
        prev = (0, 0)
        for i in range(1, 9):
            cur = ps.get(i, prev)
            m["inn"][i] += (cur[0] - prev[0]) + (cur[1] - prev[1])
            prev = cur
        m["inn"][9] += (r.away + r.home) - (prev[0] + prev[1])
        m["one"] += abs(r.away - r.home) == 1
        m["ext"] += 10 in ps
        m["a"] += r.away
        m["h"] += r.home
        m["af"] += r.away_f5
        m["hf"] += r.home_f5
        m["dist_full"][r.away] += 1
        m["dist_full"][r.home] += 1
        m["dist_f5"][r.away_f5] += 1
        m["dist_f5"][r.home_f5] += 1
        for i in (7, 8, 9):
            if i not in ps:
                continue
            a0, h0 = ps.get(i - 1, (0, 0))
            a1, h1 = ps[i]
            b = min(abs(a0 - h0), MARGIN_CAP)
            m["late"][b][0] += (a1 - a0) + (h1 - h0)
            m["late"][b][1] += 1
        a8, h8 = ps.get(8, (0, 0))
        for k, v in save_cell(a8, h8, r.away, r.home).items():
            m["save"][k] += v
        for curve, b, p in _HOOK_LOG:
            m["hook"][curve][b][0] += p
            m["hook"][curve][b][1] += 1
        sp_ids = {id(r.away_sp): "away", id(r.home_sp): "home"}
        for side, sp in (("away", r.away_sp), ("home", r.home_sp)):
            d = m["sp"][side]
            d["outs"][sp.outs] += 1
            d["k"][sp.k] += 1
            if sp.pulled_mid_inning:
                d["mid"] += 1
                if sp.outs in SPIKES:
                    d["spike_mid"][sp.outs] += 1
        pa = m["pa"]
        hr_club: Counter = Counter()
        hr_bat: Counter = Counter()
        pa_bat: Counter = Counter()
        # P(no home run all night) for each batter, as a running product
        # over the plate appearances he actually got in this draw.
        miss_bat: dict = defaultdict(lambda: 1.0)
        for rid, o, batter, pre_first, pre_outs, douts, p_hr in _PA_LOG:
            pa["pa"] += 1
            if o == sim.HR:
                hr_club[club_of.get(batter, "?")] += 1
                hr_bat[batter] += 1
            pa_bat[batter] += 1
            miss_bat[batter] *= 1.0 - p_hr
            if o == sim.K:
                pa["k"] += 1
            elif o in (sim.B1, sim.B2, sim.B3):
                pa["h1" if o == sim.B1 else "xbh"] += 1
            elif o == sim.HR:
                pa["hr"] += 1
            elif o == sim.SAC:
                pa["sac"] += 1
            if o in (sim.BB, sim.HBP, sim.B1, sim.B2, sim.B3, sim.HR,
                     sim.ROE):
                pa["br"] += 1
            if o in (sim.B1, sim.B2, sim.B3, sim.HR, sim.OUT, sim.ROE,
                     sim.SAC):
                pa["bip"] += 1
            if o == sim.B1:
                m["bathits"][batter][0] += 1
            elif o in (sim.B2, sim.B3):
                m["bathits"][batter][1] += 1
            if o == sim.OUT and pre_first and pre_outs < 2:
                pa["dp_opp"] += 1
                if douts == 2:
                    pa["dp"] += 1
                sp_side = sp_ids.get(rid)
                if sp_side:
                    m["sp"][sp_side]["dp_opp"] += 1
                    m["sp"][sp_side]["dp"] += douts == 2
            side = sp_ids.get(rid)
            if side and o in (sim.B1, sim.B2, sim.B3, sim.HR, sim.OUT,
                              sim.ROE, sim.SAC):
                m["sp_hr"][side][0] += 1
                m["sp_hr"][side][1] += o == sim.HR
            if side:
                hand = sp_hand[side]
                bs = bside.get(batter)
                pa["sp_pa"] += 1
                if not (hand and bs):
                    pa["plat_miss"] += 1
                    continue
                adv = "adv" if bs != hand else "nad"
                pl = m["plat"]
                pl[f"{adv}_pa"] += 1
                if o == sim.K:
                    pl[f"{adv}_k"] += 1
                elif o == sim.HR:
                    pl[f"{adv}_hr"] += 1
        for nm_ in pa_bat:
            d = m["bathr"][nm_]
            # THE MODEL'S PREDICTION IS THE ANALYTIC ONE — 1 minus the
            # product of missing every trip — not the 0/1 of whether this
            # particular draw happened to produce one. See `_PHR`.
            d[0] += 1.0 - miss_bat[nm_]
            d[1] += hr_bat[nm_]
            d[2] += pa_bat[nm_]
        for club in ("away", "home"):
            m["hrdist"][hr_club[club]] += 1
        # A batter the lineup map missed would silently land in the "?"
        # club rather than in a real one, so it is carried as its own
        # count and scored as a coverage row rather than assumed to be
        # zero.
        pa["hr_orphan"] += hr_club["?"]
    m["pa"]["runs"] = m["a"] + m["h"]        # numerator for runs/baserunner
    for key in ("lad", "inn"):
        m[key] = {k: v / _SIMS for k, v in m[key].items()}
    for key in ("one", "ext", "a", "h", "af", "hf"):
        m[key] /= _SIMS
    m["sp_hr"] = {k: [v[0] / _SIMS, v[1] / _SIMS]
                  for k, v in m["sp_hr"].items()}
    m["hook"] = {c: dict(v) for c, v in m["hook"].items()}
    m["bathits"] = dict(m["bathits"])
    m["bathr"] = dict(m["bathr"])
    # Lineup platoon-advantage share per CLUB vs the opposing starter, for
    # the stacked-lineup decile. away[2] is the nine the away PITCHER
    # faces — the HOME club's batters — per the standing crossing.
    adv = {}
    for club, nine, opp in (("home", away[2], "away"), ("away", home[2],
                                                        "home")):
        hand = sp_hand[opp]
        sides = [bside.get(b.name) for b in nine]
        known = [s for s in sides if s and hand]
        adv[club] = (sum(s != hand for s in known) / len(known)
                     if known else None)
    m["advshare"] = adv
    return m


# ── the one pass: actual side, counted off play-by-play ─────────────────

def _actual_one(gid: str, data: dict) -> dict:
    a = {"inn": defaultdict(int), "one": 0.0, "ext": 0.0,
         "late": {b: [0.0, 0] for b in range(MARGIN_CAP + 1)},
         "save": {"n": 0, "held": 0, "r0": 0, "r2": 0},
         # The real relief outings, off `pbp.stints` rather than re-derived
         # here: it is the same extractor `mlb_stints` is built from, so the
         # model and real sides of this row cannot drift apart through two
         # different definitions of "an outing" (rule 10).
         "pen": {"n": 0, "outs": 0, "outs2": 0, "le2": 0, "ge7": 0,
                 "mid": 0, "sides": 2, "arms2": 0},
         "pa": Counter(), "plat": Counter(), "kind": {},
         # Starter-restricted DP counts per pitching half, and per-batter
         # singles/XBH — the real side of the GB-quintile rows.
         "sp_dp": {"away": [0, 0], "home": [0, 0]},
         "sp_hr": {"away": [0, 0], "home": [0, 0]},
         "bathits": defaultdict(lambda: [0, 0]),
         # HOME RUNS PER CLUB-GAME — the real side of `hrshape`. The
         # batting club is the half-inning, which needs no lineup map at
         # all on this side.
         "hrdist": Counter(), "hrby": Counter(),
         # {name: [home runs, plate appearances]} — the real side of the
         # per-batter rows. Counting PA here as well as home runs is what
         # separates "we had his rate wrong" from "we gave him four trips
         # and the manager gave him two".
         "bathr": defaultdict(lambda: [0, 0])}
    first = {}
    cum = defaultdict(lambda: [0, 0])   # inning -> [away runs, home runs]
    max_inn = 0
    for play, bases, outs, aw, ho in pbp.plays(gid, data):
        ab = play.get("about") or {}
        inn, top = ab.get("inning"), ab.get("isTopInning")
        res = play.get("result") or {}
        ev = res.get("eventType") or ""
        mu = play.get("matchup") or {}
        if not inn:
            continue
        max_inn = max(max_inn, inn)
        pit_side = "home" if top else "away"     # the side PITCHING
        pid = (mu.get("pitcher") or {}).get("id")
        if pid:
            first.setdefault(pit_side, pid)
        pa = a["pa"]
        pa["pa"] += 1
        if ev in EV_K:
            pa["k"] += 1
        elif ev == "single":
            pa["h1"] += 1
        elif ev in ("double", "triple"):
            pa["xbh"] += 1
        elif ev == "home_run":
            pa["hr"] += 1
            a["hrby"]["away" if top else "home"] += 1
        elif ev in EV_SAC:
            pa["sac"] += 1
        if ev in EV_REACH:
            pa["br"] += 1
        if ev in EV_HIT or ev in EV_INPLAY_OUT or ev in EV_SAC \
                or ev == "field_error":
            pa["bip"] += 1
        nm = (mu.get("batter") or {}).get("fullName")
        if nm:
            a["bathr"][nm][0] += ev == "home_run"
            a["bathr"][nm][1] += 1
            if ev == "single":
                a["bathits"][nm][0] += 1
            elif ev in ("double", "triple"):
                a["bathits"][nm][1] += 1
        if ev in EV_INPLAY_OUT and bases[0] and outs < 2:
            pa["dp_opp"] += 1
            if ev in EV_DP:
                pa["dp"] += 1
            if pid and pid == first.get(pit_side):
                a["sp_dp"][pit_side][0] += 1
                a["sp_dp"][pit_side][1] += ev in EV_DP
        if pid and pid == first.get(pit_side):
            if ev in EV_HIT or ev in EV_INPLAY_OUT or ev in EV_SAC \
                    or ev == "field_error":
                a["sp_hr"][pit_side][0] += 1
                a["sp_hr"][pit_side][1] += ev == "home_run"
            pa["sp_pa"] += 1
            bs = ((mu.get("batSide") or {}).get("code"))
            hand = ((mu.get("pitchHand") or {}).get("code"))
            if not (bs and hand):
                pa["plat_miss"] += 1
            else:
                adv = "adv" if bs != hand else "nad"
                pl = a["plat"]
                pl[f"{adv}_pa"] += 1
                if ev in EV_K:
                    pl[f"{adv}_k"] += 1
                elif ev == "home_run":
                    pl[f"{adv}_hr"] += 1
        if res.get("awayScore") is not None:
            got = res["awayScore"] + res["homeScore"] - (aw + ho)
            if got > 0:
                cum[inn][0 if top else 1] += got
    a["ext"] = float(max_inn > 9)
    ca = ch = 0
    at_start = {}
    for i in range(1, max_inn + 1):
        at_start[i] = (ca, ch)
        ca += cum[i][0]
        ch += cum[i][1]
        runs = cum[i][0] + cum[i][1]
        a["inn"][min(i, 9)] += runs
        if 7 <= i <= 9:
            b = min(abs(at_start[i][0] - at_start[i][1]), MARGIN_CAP)
            a["late"][b][0] += runs
            a["late"][b][1] += 1
    if 9 in at_start:
        a["save"] = save_cell(*at_start[9], ca, ch)
    per_side: dict = defaultdict(int)
    for s in pbp.stints(gid, data):
        if s.order <= 0:                       # the starter is not relief
            continue
        per_side[s.side] += 1
        a["pen"]["n"] += 1
        a["pen"]["outs"] += s.outs_recorded
        a["pen"]["outs2"] += s.outs_recorded ** 2
        a["pen"]["le2"] += s.outs_recorded <= 2
        a["pen"]["ge7"] += s.outs_recorded >= 7
        a["pen"]["mid"] += s.outs > 0          # `outs` is the ENTRY state
    # Both sides always count, so a club whose starter finished contributes
    # a real ZERO rather than dropping out of the denominator.
    a["pen"]["arms2"] = sum(per_side.get(s, 0) ** 2 for s in ("away", "home"))
    a["lad"] = {}
    run = 0
    for i in range(1, 8):
        run += a["inn"].get(i, 0)
        if i in LADDER:
            a["lad"][i] = run
    for club in ("away", "home"):
        a["hrdist"][a["hrby"][club]] += 1
    a["pa"]["runs"] = ca + ch
    a["inn"] = dict(a["inn"])
    a["bathits"] = dict(a["bathits"])
    # A defaultdict over a lambda cannot cross the pool — `bathits` learned
    # this first and the traceback is an unpicklable-local, not anything
    # about the counts.
    a["bathr"] = dict(a["bathr"])
    try:
        for e in boundary.exits(gid, data):
            a["kind"][e.get("pitcher")] = e.get("kind")
    except Exception:
        pass
    return a


def _one(gid: str):
    short = gid.split("-")[-1]
    try:
        data = pbp.fetch(short)
    except Exception:
        data = None
    if not data:
        return gid, None, None
    # The model side reads batter handedness off the same game's feed.
    bmap = {}
    for play, *_ in pbp.plays(short, data):
        mu = play.get("matchup") or {}
        nm = (mu.get("batter") or {}).get("fullName")
        bs = ((mu.get("batSide") or {}).get("code"))
        if nm and bs:
            bmap[nm] = bs
    _BSIDE[gid] = bmap
    act = _actual_one(short, data)
    model = _model_one(gid)
    return gid, model, act


_BSIDE: dict = {}


# ── aggregation ─────────────────────────────────────────────────────────

def _paired(pairs_):
    """(model mean, actual mean, gap, se, n) from per-game (m, a)."""
    d = [m_ - a_ for m_, a_ in pairs_]
    n = len(d)
    if not n:
        return None
    se = st.pstdev(d) / n ** 0.5 if n > 1 else 0.0
    return (st.mean(m_ for m_, _ in pairs_), st.mean(a_ for _, a_ in pairs_),
            st.mean(d), se, n)


def _rate_se(p, n):
    """Binomial se of an observed rate. An observed 0 or 1 returns se 0,
    which the row constructor turns into z=None rather than infinity."""
    return (p * (1 - p) / n) ** 0.5 if n else 0.0


def _corr(pairs_):
    """Pearson r over (x, y) pairs. 0.0 when either side is constant."""
    n = len(pairs_)
    if n < 3:
        return 0.0
    mx = st.mean(x for x, _ in pairs_)
    my = st.mean(y for _, y in pairs_)
    num = sum((x - mx) * (y - my) for x, y in pairs_)
    dx = sum((x - mx) ** 2 for x, _ in pairs_) ** 0.5
    dy = sum((y - my) ** 2 for _, y in pairs_) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def _corr_ceiling(by_unit):
    """The highest correlation ANY per-pitcher predictor could reach here.

    WHY THIS IS THE RIGHT TARGET for `shape.outs_corr` rather than 1.0. A
    start's outs are a pitcher's own central tendency plus a night's noise,
    and no predictor that knows only the pitcher can reach the noise. If
    actual = arm mean + noise, the best such predictor IS the arm mean and
    its correlation with the actual is sd_between / sd_total — so that is
    what the model is scored against.

    Sampling noise is removed by the (MSB - MSW) / n0 estimator, the same
    one `leash.shrink_k` uses and for the same reason: with a dozen starts
    an arm's observed mean carries a full out of noise, and the raw spread
    of arm means would report most of it as real between-arm spread and
    hand back a ceiling that is too high to ever be reached.

    Returns None when it is not estimable (too few arms with repeats), so
    the row reports the model's own number with no target rather than a
    fabricated one.
    """
    by = {u: v for u, v in by_unit.items() if u and len(v) >= 2}
    if len(by) < 3:
        return None
    n = sum(len(v) for v in by.values())
    k = len(by)
    grand = sum(sum(v) for v in by.values()) / n
    ssb = sum(len(v) * (st.mean(v) - grand) ** 2 for v in by.values())
    ssw = sum(sum((x - st.mean(v)) ** 2 for x in v) for v in by.values())
    if n == k or k < 2:
        return None
    msb, msw = ssb / (k - 1), ssw / (n - k)
    n0 = (n - sum(len(v) ** 2 for v in by.values()) / n) / (k - 1)
    between = max((msb - msw) / n0, 0.0)
    total = between + max(msw, 1e-9)
    return (between / total) ** 0.5 if total > 0 else None


class Fold:
    def __init__(self, year, cut):
        self.year, self.cut = year, cut
        self.rows = []

    def add(self, group, key, model, actual, se, n, note=""):
        gap = (model - actual) if (model is not None and actual is not None) \
            else None
        self.rows.append({
            "fold": self.year, "group": group, "key": str(key),
            "model": model, "actual": actual, "gap": gap, "se": se,
            "z": (gap / se if gap is not None and se else None),
            "floor": (se / _SIMS ** 0.5 if se else None),
            "n": n, "note": note})


def _score_fold(fold: Fold, got: dict, act_db: dict, real_hook: dict):
    """Turn the per-game payloads into rows. `got` = {gid: (model, actual)}."""
    gids = sorted(got)
    A = lambda k: [got[g][1][k] for g in gids]        # noqa: E731
    M = lambda k: [got[g][0][k] for g in gids]        # noqa: E731

    for p in LADDER:
        r = _paired([(got[g][0]["lad"][p], got[g][1]["lad"].get(p, 0))
                     for g in gids])
        fold.add("ladder", f"F{p}", r[0], r[1], r[3], r[4])
    for i in list(range(1, 9)) + [9]:
        r = _paired([(got[g][0]["inn"][i], got[g][1]["inn"].get(i, 0))
                     for g in gids])
        fold.add("inning", "9+" if i == 9 else i, r[0], r[1], r[3], r[4])

    one_real = [(abs(act_db[g]["away_score"] - act_db[g]["home_score"]) == 1)
                for g in gids]
    r = _paired(list(zip(M("one"), map(float, one_real))))
    fold.add("game", "one_run_share", r[0], r[1], r[3], r[4])
    r = _paired(list(zip(M("ext"), A("ext"))))
    fold.add("game", "extras_share", r[0], r[1], r[3], r[4])

    # Team-level rows: two club-games per game, model mean vs the score.
    club = []      # (venue, model_full, real_full, model_f5, real_f5)
    for g in gids:
        m, db_ = got[g][0], act_db[g]
        club.append((db_["venue_id"], m["a"], db_["away_score"], m["af"],
                     db_["away_score_f5"], m["advshare"]["away"]))
        club.append((db_["venue_id"], m["h"], db_["home_score"], m["hf"],
                     db_["home_score_f5"], m["advshare"]["home"]))
    club = [c for c in club if c[2] is not None and c[4] is not None]

    for label, mi, ai in (("full", 1, 2), ("f5", 3, 4)):
        by_venue = defaultdict(list)
        for c in club:
            if c[0]:
                by_venue[c[0]].append(c[mi] - c[ai])
        wsum = wn = 0.0
        for v, d in sorted(by_venue.items(), key=lambda kv: -len(kv[1])):
            n = len(d)
            mean = st.mean(d)
            se = st.pstdev(d) / n ** 0.5 if n > 1 else 0.0
            wsum += abs(mean) * n
            wn += n
            if n >= MIN_VENUE:
                fold.add(f"venue_{label}", v, mean, 0.0, se, n)
        fold.add(f"venue_{label}", "wmean_abs_resid",
                 wsum / wn if wn else None, 0.0, 0.0, int(wn),
                 "sample-weighted mean |per-venue residual|")

    # Traffic and the run-distribution shape.
    pa_m = sum((got[g][0]["pa"] for g in gids), Counter())
    pa_a = sum((got[g][1]["pa"] for g in gids), Counter())
    rm = pa_m["runs"] / _SIMS / max(pa_m["br"] / _SIMS, 1)
    ra = pa_a["runs"] / max(pa_a["br"], 1)
    fold.add("traffic", "runs_per_baserunner", rm, ra,
             _rate_se(ra, pa_a["br"]), pa_a["br"])
    full_a = [c[2] for c in club]
    f5_a = [c[4] for c in club]
    n = len(club)
    for key, lo, hi in (("shutout_share", 0, 0), ("mass_0_3", 0, 3),
                        ("mass_8_plus", 8, 99)):
        # Model side is a mean over draws already; use the per-club share
        # of draws only where we kept it — here full totals are means, so
        # shares come from the pooled draw distribution kept below.
        am = st.mean(float(lo <= v <= hi) for v in full_a)
        fold.add("traffic", key, _mass(got, gids, "full", lo, hi), am,
                 _rate_se(am, n), n)
    a0 = st.mean(float(v == 0) for v in f5_a)
    fold.add("traffic", "f5_shutout_share", _mass(got, gids, "f5", 0, 0),
             a0, _rate_se(a0, n), n)

    # Platoon.
    pl_m = sum((got[g][0]["plat"] for g in gids), Counter())
    pl_a = sum((got[g][1]["plat"] for g in gids), Counter())
    for ch in ("k", "hr"):
        for adv in ("adv", "nad"):
            mrate = pl_m[f"{adv}_{ch}"] / max(pl_m[f"{adv}_pa"], 1)
            arate = pl_a[f"{adv}_{ch}"] / max(pl_a[f"{adv}_pa"], 1)
            fold.add("platoon", f"{ch}_per_pa_{adv}", mrate, arate,
                     _rate_se(arate, pl_a[f"{adv}_pa"]), pl_a[f"{adv}_pa"])
    cover = 1 - pa_m["plat_miss"] / max(pa_m["sp_pa"], 1)
    fold.add("platoon", "model_side_coverage", cover, None, 0.0,
             pa_m["sp_pa"], "share of starter PAs with a known batter side")
    ranked = sorted((c for c in club if c[5] is not None),
                    key=lambda c: -c[5])
    top = ranked[:max(1, len(ranked) // 10)]
    for key, rows_ in (("stacked_decile_resid", top),
                       ("all_clubs_resid_control", ranked)):
        d = [c[1] - c[2] for c in rows_]
        if d:
            fold.add("platoon", key, st.mean(c[1] for c in rows_),
                     st.mean(c[2] for c in rows_),
                     st.pstdev(d) / len(d) ** 0.5, len(d))

    # Contact.
    for key, num, den in (("dp_per_opportunity", "dp", "dp_opp"),
                          ("sac_per_pa", "sac", "pa"),
                          ("hr_per_bip", "hr", "bip")):
        mrate = pa_m[num] / max(pa_m[den], 1)
        arate = pa_a[num] / max(pa_a[den], 1)
        fold.add("contact", key, mrate, arate, _rate_se(arate, pa_a[den]),
                 pa_a[den])
    # HOME RUN SHAPE — the distribution of home runs by one club in one
    # game, model against real. `contact.hr_per_bip` is the LEVEL and has
    # read healthy since it was added; this is the row that can see a
    # clustering miss, which is the defect the level cannot show (rule 2).
    # The model side is a share of DRAWS, the real side a share of
    # club-games, and the standard error is the real side's.
    hd_m = sum((got[g][0]["hrdist"] for g in gids), Counter())
    hd_a = sum((got[g][1]["hrdist"] for g in gids), Counter())
    nm_, na_ = sum(hd_m.values()), sum(hd_a.values())
    if nm_ and na_:
        for lab, lo, hi in (("hr_0", 0, 0), ("hr_1", 1, 1), ("hr_2", 2, 2),
                            ("hr_3plus", 3, 99)):
            mm = sum(v for k_, v in hd_m.items() if lo <= k_ <= hi) / nm_
            aa = sum(v for k_, v in hd_a.items() if lo <= k_ <= hi) / na_
            fold.add("hrshape", lab, mm, aa, _rate_se(aa, na_), na_)
        def _mv(src, n_):
            mean = sum(k_ * v for k_, v in src.items()) / n_
            var = sum(k_ * k_ * v for k_, v in src.items()) / n_ - mean ** 2
            return mean, var

        mmean, mvar = _mv(hd_m, nm_)
        amean, avar = _mv(hd_a, na_)
        fold.add("hrshape", "hr_per_club_game", mmean, amean,
                 (avar / na_) ** 0.5, na_)
        # VARIANCE OVER MEAN: 1.0 is the Poisson that a run of independent
        # plate appearances produces, and anything above it is clustering.
        # se is the Poisson-null sqrt(2/n) — an approximation, and named
        # as one so the row is not read tighter than it is.
        fold.add("hrshape", "hr_var_over_mean",
                 mvar / mmean if mmean else None,
                 avar / amean if amean else None,
                 (2.0 / na_) ** 0.5, na_,
                 "1.0 is Poisson; above it is clustering (se is the "
                 "Poisson-null approximation)")
    # ── PER-BATTER: DOES THIS MAN GO DEEP TONIGHT ────────────────────
    #
    # Every other home run row in this file is a CLUB total, and a club
    # total cannot say whether the model can pick the HITTER. One row is
    # one batter in one game: the model's predicted P(at least one home
    # run) is the share of its own draws he went deep in, and the real
    # side is the 0/1 of whether he did.
    #
    # BUCKETED BY THE MODEL'S OWN PREDICTION, in deciles of it, which
    # makes this a reliability curve — the same construction
    # `calibrate.py` uses, applied to the question anyone actually asks
    # about a home run. Two things it can catch and no existing row can:
    # the level being off inside a bucket (calibration), and the real
    # rate failing to RISE across the buckets (discrimination), which is
    # the one that says whether the prediction is worth anything.
    #
    # THE POPULATION IS THE MODEL'S NINE, scored on what those same nine
    # did in the real game. That deliberately keeps the pinch hitter in
    # the comparison rather than defining him away: the engine never
    # lifts anybody, so a lifted batter really did get fewer trips than
    # he was given, and `hrbat_pa_top`/`_bot` are the rows that separate
    # that from a wrong rate (rule 10 — name the denominator).
    rel = []
    for g in gids:
        mb, ab = got[g][0].get("bathr") or {}, got[g][1].get("bathr") or {}
        for nm_, d in mb.items():
            real = ab.get(nm_)
            if real is None or not d[2]:
                continue
            rel.append((d[0] / _SIMS, float(real[0] > 0),
                        d[1] / _SIMS, real[0], d[2] / _SIMS, real[1],
                        g, nm_))
    # THE PER-ROW DUMP, for scoring anything else on IDENTICAL rows.
    # `HRBAT_DUMP` names a file; without it this is inert. The deciles
    # below are an aggregate and cannot be joined against another model's
    # predictions, which is the only way a head-to-head is honest.
    dump = os.environ.get("HRBAT_DUMP")
    if dump:
        with open(f"{dump}.{fold.year}.json", "w") as fh:
            json.dump([{"game_id": r[6], "batter": r[7], "p": r[0],
                        "y": r[1]} for r in rel], fh)
    if len(rel) >= 500:
        rel.sort(key=lambda r: r[0])
        nb = 10
        cut = [len(rel) * i // nb for i in range(nb + 1)]
        bins = [rel[cut[i]:cut[i + 1]] for i in range(nb)]
        for i, b in enumerate(bins, 1):
            if not b:
                continue
            mp = sum(r[0] for r in b) / len(b)
            ap = sum(r[1] for r in b) / len(b)
            fold.add("hrbat", f"p_hr_decile_{i:02d}", mp, ap,
                     _rate_se(ap, len(b)), len(b))
        lo, hi = bins[0], bins[-1]
        m_lo = sum(r[0] for r in lo) / len(lo)
        m_hi = sum(r[0] for r in hi) / len(hi)
        a_lo = sum(r[1] for r in lo) / len(lo)
        a_hi = sum(r[1] for r in hi) / len(hi)
        # THE ROW THAT ANSWERS THE QUESTION. If the model can pick the
        # hitter at all, the real rate in its top decile must beat the
        # real rate in its bottom one, and by about as much as it claims.
        # A model with the level exactly right and no discrimination has
        # every decile row healthy and this row at zero.
        fold.add("hrbat", "spread_top_minus_bottom", m_hi - m_lo,
                 a_hi - a_lo,
                 (_rate_se(a_hi, len(hi)) ** 2
                  + _rate_se(a_lo, len(lo)) ** 2) ** 0.5, len(hi) + len(lo),
                 "real rate in the model's top decile minus its bottom")
        n_all = len(rel)
        am = sum(r[1] for r in rel) / n_all
        fold.add("hrbat", "p_hr_level", sum(r[0] for r in rel) / n_all,
                 am, _rate_se(am, n_all), n_all,
                 "share of batter-games with at least one home run")
        # PER PLATE APPEARANCE, top and bottom decile — the rate itself,
        # with the number of trips divided out. A gap here that the
        # `p_hr` rows do not show is a PA-count problem, not a rate one.
        for lab, b in (("top", hi), ("bot", lo)):
            mh, mp_ = sum(r[2] for r in b), sum(r[4] for r in b)
            ah, ap_ = sum(r[3] for r in b), sum(r[5] for r in b)
            if mp_ and ap_:
                fold.add("hrbat", f"hr_per_pa_{lab}", mh / mp_, ah / ap_,
                         _rate_se(ah / ap_, ap_), int(ap_))
            fold.add("hrbat", f"pa_{lab}", mp_ / len(b), ap_ / len(b),
                     0.0, len(b), "plate appearances per batter-game")
    else:
        fold.add("hrbat", "spread_top_minus_bottom", None, None, 0.0, 0,
                 "EMPTY — fewer than 500 batter-games matched")

    # HOME RUNS BY THE STARTER'S AIR-BALL SHARE, in the SHIPPED cells of
    # `sim.AIR_HR_PIT` — the row that scores the wire and not just the
    # table, the way the weather rows do. Both sides bucket on the same
    # covariate, the model's own shrunk cutoff-scoped share, so a cell is
    # the same population on both sides (rule 10). Starter-restricted
    # because that is the arm the battery can name on the real side.
    sp_air = {}
    for g in gids:
        for side, idx in (("away", 0), ("home", 1)):
            v = _CASES[g][idx][1].air_pct
            if v is not None:
                sp_air[(g, side)] = v
    if sp_air:
        am = {q: [0, 0] for q in range(1, 6)}
        aa = {q: [0, 0] for q in range(1, 6)}
        for (g, side), v in sp_air.items():
            q = sum(v >= e for e in sim.AIR_HR_PIT[0]) + 1
            bip_m, hr_m = got[g][0]["sp_hr"][side]
            am[q][0] += hr_m
            am[q][1] += bip_m
            bip_a, hr_a = got[g][1]["sp_hr"][side]
            aa[q][0] += hr_a
            aa[q][1] += bip_a
        for q in range(1, 6):
            if not (aa[q][1] and am[q][1]):
                continue
            ar = aa[q][0] / aa[q][1]
            fold.add("hrshape", f"hr_per_bip_by_sp_air_q{q}",
                     am[q][0] / am[q][1], ar, _rate_se(ar, aa[q][1]),
                     aa[q][1])
    else:
        for q in range(1, 6):
            fold.add("hrshape", f"hr_per_bip_by_sp_air_q{q}", None, None,
                     0.0, 0, "EMPTY until air_pct is plumbed")
    fold.add("hrshape", "orphan_hr_per_draw",
             pa_m["hr_orphan"] / max(_SIMS * len(gids), 1), 0.0, 0.0,
             len(gids), "model home runs by a batter off the lineup map")
    xm = pa_m["xbh"] / max(pa_m["xbh"] + pa_m["h1"], 1)
    xa = pa_a["xbh"] / max(pa_a["xbh"] + pa_a["h1"], 1)
    fold.add("contact", "xbh_share_nonhr_hits", xm, xa,
             _rate_se(xa, pa_a["xbh"] + pa_a["h1"]),
             pa_a["xbh"] + pa_a["h1"])
    # GB-QUINTILE ROWS, live since item 4a plumbed `gb_pct`. Quintiles are
    # a CONDITIONING variable, so both sides bucket on the same value —
    # the model's shrunk, cutoff-scoped share — and the rows measure how
    # the model's flat tables miss by contact type, which is the gap 4b
    # and 4c exist to close. Names with no counted share are dropped from
    # these rows only.
    sp_gb = {}
    bat_gb = {}
    for g in gids:
        for side, idx in (("away", 0), ("home", 1)):
            v = _CASES[g][idx][1].gb_pct
            if v is not None:
                sp_gb[(g, side)] = v
        for case in _CASES[g]:
            for b in case[2]:
                if b.gb_pct is not None and b.name not in bat_gb:
                    bat_gb[b.name] = b.gb_pct

    def _edges(vals):
        s = sorted(vals)
        return [s[int(len(s) * q / 5)] for q in range(1, 5)]

    def _q(v, edges):
        return sum(v >= e for e in edges) + 1

    if sp_gb:
        edges = _edges(list(sp_gb.values()))
        mo = {q: [0, 0] for q in range(1, 6)}
        ra = {q: [0, 0] for q in range(1, 6)}
        for (g, side), v in sp_gb.items():
            q = _q(v, edges)
            d = got[g][0]["sp"][side]
            mo[q][0] += d["dp_opp"]
            mo[q][1] += d["dp"]
            opp, k_ = got[g][1]["sp_dp"][side]
            ra[q][0] += opp
            ra[q][1] += k_
        for q in range(1, 6):
            if not (ra[q][0] and mo[q][0]):
                continue
            ar = ra[q][1] / ra[q][0]
            fold.add("contact", f"dp_by_pitcher_gb_q{q}",
                     mo[q][1] / mo[q][0], ar, _rate_se(ar, ra[q][0]),
                     ra[q][0])
    else:
        for q in range(1, 6):
            fold.add("contact", f"dp_by_pitcher_gb_q{q}", None, None, 0.0,
                     0, "EMPTY until item 4a plumbs gb_pct")
    if bat_gb:
        edges = _edges(list(bat_gb.values()))
        mo = {q: [0, 0] for q in range(1, 6)}
        ra = {q: [0, 0] for q in range(1, 6)}
        for g in gids:
            for acc, src in ((mo, got[g][0]["bathits"]),
                             (ra, got[g][1]["bathits"])):
                for nm, (h1, xbh) in src.items():
                    v = bat_gb.get(nm)
                    if v is None:
                        continue
                    q = _q(v, edges)
                    acc[q][0] += h1
                    acc[q][1] += xbh
        for q in range(1, 6):
            mn, rn = sum(mo[q]), sum(ra[q])
            if not (mn and rn):
                continue
            ar = ra[q][1] / rn
            fold.add("contact", f"xbh_by_batter_gb_q{q}",
                     mo[q][1] / mn, ar, _rate_se(ar, rn), rn)
    else:
        for q in range(1, 6):
            fold.add("contact", f"xbh_by_batter_gb_q{q}", None, None, 0.0,
                     0, "EMPTY until item 4a plumbs gb_pct")
    # WEATHER ROWS, live since item 5. Bucketed by the SHIPPED bins so
    # each row names the cell the mechanism fires in; the model side
    # carries the multiplier through `cal.replay`'s hr_air, so these
    # rows score the wire, not just the table.
    wx = cal._WEATHER or {}
    wb_m: dict = defaultdict(lambda: [0.0, 0.0])
    wb_a: dict = defaultdict(lambda: [0.0, 0.0])
    n_temp = 0
    for g in gids:
        t = (wx.get(g) or {}).get("temp_f")
        if t is None:
            continue
        n_temp += 1
        b = sum(t >= e for e in sim.TEMP_HR_EDGES)
        for acc, pay in ((wb_m, got[g][0]["pa"]), (wb_a, got[g][1]["pa"])):
            acc[b][0] += pay["hr"]
            acc[b][1] += pay["bip"]
    fold.add("weather", "temp_coverage", n_temp / max(len(gids), 1), 1.0,
             0.0, len(gids), "share of fold games with a temperature")
    for b, lab in enumerate(("lt55", "55_64", "65_74", "75_84", "85plus")):
        if not (wb_a[b][1] and wb_m[b][1]):
            fold.add("weather", f"hr_bip_temp_{lab}", None, None, 0.0, 0,
                     "no games in this bin")
            continue
        ar = wb_a[b][0] / wb_a[b][1]
        fold.add("weather", f"hr_bip_temp_{lab}", wb_m[b][0] / wb_m[b][1],
                 ar, _rate_se(ar, int(wb_a[b][1])), int(wb_a[b][1]))
    # WIND ROWS, live since item 7, in the SHIPPED three bins. Open-air
    # only, matching the population the table was counted on — a closed
    # roof reports no push toward the fence and belongs in neither the
    # in nor the out cell.
    nb_m: dict = defaultdict(lambda: [0.0, 0.0])
    nb_a: dict = defaultdict(lambda: [0.0, 0.0])
    n_wind = 0
    for g in gids:
        w = wx.get(g) or {}
        if w.get("carry") is None or w.get("wind_mph") is None \
                or w.get("roof_closed"):
            continue
        n_wind += 1
        s = w["carry"] * w["wind_mph"]
        b = 0 if s <= -5 else (1 if s < 5 else 2)
        for acc, pay in ((nb_m, got[g][0]["pa"]), (nb_a, got[g][1]["pa"])):
            acc[b][0] += pay["hr"]
            acc[b][1] += pay["bip"]
    fold.add("weather", "wind_coverage", n_wind / max(len(gids), 1), None,
             0.0, len(gids), "open-air share of fold games with a wind")
    for b, lab in enumerate(("in5plus", "calm", "out5plus")):
        if not (nb_a[b][1] and nb_m[b][1]):
            fold.add("weather", f"hr_bip_wind_{lab}", None, None, 0.0, 0,
                     "no games in this bin")
            continue
        ar = nb_a[b][0] / nb_a[b][1]
        fold.add("weather", f"hr_bip_wind_{lab}", nb_m[b][0] / nb_m[b][1],
                 ar, _rate_se(ar, int(nb_a[b][1])), int(nb_a[b][1]))

    # Late innings by margin.
    for b in range(MARGIN_CAP + 1):
        ms = mn = as_ = an = 0.0
        for g in gids:
            s, c = got[g][0]["late"][b]
            ms += s
            mn += c
            s, c = got[g][1]["late"][b]
            as_ += s
            an += c
        if not an or not mn:
            continue
        aa = as_ / an
        # se of a mean of per-inning run counts; sd~1.1 run per inning.
        fold.add("late", f"inn7_9_margin_{'4+' if b == MARGIN_CAP else b}",
                 ms / mn, aa, 1.1 / an ** 0.5, int(an))

    # THE SAVE SITUATION. The rate a late lead is HELD is the outcome the
    # bullpen work of 2026-09-09 was aiming at and could not be scored on —
    # every instrument that day was a proxy (outing length, selection
    # percentile, closer usage rate). The two mass rows are there because a
    # better closer removes the crooked number without moving the mean, and
    # the `late` group above is all means.
    msv = {k: 0 for k in ("n", "held", "r0", "r2")}
    asv = {k: 0 for k in ("n", "held", "r0", "r2")}
    for g in gids:
        for src, dst in ((got[g][0]["save"], msv), (got[g][1]["save"], asv)):
            for k in dst:
                dst[k] += src[k]
    if asv["n"] and msv["n"]:
        for key, num in (("lead_held", "held"), ("allowed_0", "r0"),
                         ("allowed_2plus", "r2")):
            ar = asv[num] / asv["n"]
            fold.add("save", key, msv[num] / msv["n"], ar,
                     _rate_se(ar, asv["n"]), asv["n"])

    # HOW LONG THE PEN'S ARMS STAY OUT THERE. Built 2026-09-09 (TODO 23)
    # because the four bullpen mechanisms that shipped that day moved no row
    # in this file and there was no row here that COULD have moved — the
    # obligation the "nothing moved" rule imposes. `arms_per_side` is the
    # one a total feels: each handover is a fresh pitcher facing the top of
    # the order, so burning an arm too many per game puts a worse pitcher on
    # the mound in the eighth of every game the model prices.
    keys = ("n", "outs", "outs2", "le2", "ge7", "mid", "sides", "arms2")
    mpn = {k: 0 for k in keys}
    apn = {k: 0 for k in keys}
    for g in gids:
        for src, dst in ((got[g][0]["pen"], mpn), (got[g][1]["pen"], apn)):
            for k in dst:
                dst[k] += src[k]
    if apn["n"] and mpn["n"]:
        for key, num, den, sq in (
                ("relief_outs_mean", "outs", "n", "outs2"),
                ("relief_le2_share", "le2", "n", None),
                ("relief_ge7_share", "ge7", "n", None),
                ("relief_mid_entry_share", "mid", "n", None),
                ("arms_per_side", "n", "sides", "arms2")):
            ar = apn[num] / apn[den]
            if sq is None:
                se = _rate_se(ar, apn[den])
            else:
                # NOT A RATE — a mean outing is 3.3 outs and a side uses 3.4
                # arms, so the binomial formula would take the root of a
                # negative. The se comes off the real spread.
                var = max(apn[sq] / apn[den] - ar * ar, 0.0)
                se = (var / apn[den]) ** 0.5
            fold.add("pen", key, mpn[num] / mpn[den], ar, se, apn[den])

    # Hook cells.
    for curve in ("bnd", "mid"):
        agg = defaultdict(lambda: [0.0, 0])
        for g in gids:
            for b, (s, c) in got[g][0]["hook"][curve].items():
                agg[b][0] += s
                agg[b][1] += c
        gaps = []
        for b in EDGES[:-1]:
            rk, rn = real_hook[curve].get(b, (0, 0))
            if rn < MIN_REAL_HOOK or not agg[b][1]:
                continue
            mrate, arate = agg[b][0] / agg[b][1], rk / rn
            fold.add(f"hook_{curve}", b, mrate, arate, _rate_se(arate, rn),
                     rn)
            gaps.append(abs(mrate - arate))
        if gaps:
            fold.add(f"hook_{curve}", "mean_abs_gap", st.mean(gaps), 0.0,
                     0.0, len(gaps))

    # Starter shape. Real side: the paired-case act rows.
    real_o, real_k, kinds = [], [], []
    mo, mk = Counter(), Counter()
    mid_draws = tot_draws = 0
    spike_mid = Counter()
    # PER-START pairs for `outs_corr`, and the actual outs grouped by arm
    # for its ceiling. Read off the same draws as every row above — no
    # extra simulation, which is the whole point of one pass per fold.
    o_pairs, o_by_arm = [], defaultdict(list)
    for g in gids:
        for side, case in (("away", 0), ("home", 1)):
            act = _CASES[g][case][0]
            if act.get("o") is not None:
                real_o.append(act["o"])
            if act.get("k") is not None:
                real_k.append(act["k"])
            kind = got[g][1]["kind"].get(_PIDS.get(act.get("player_name")))
            if kind:
                kinds.append((act.get("o"), kind))
            d = got[g][0]["sp"][side]
            mo.update(d["outs"])
            mk.update(d["k"])
            mid_draws += d["mid"]
            tot_draws += _SIMS
            spike_mid.update(d["spike_mid"])
            dn = sum(d["outs"].values())
            if act.get("o") is not None and dn:
                o_pairs.append(
                    (sum(v * c for v, c in d["outs"].items()) / dn, act["o"]))
                o_by_arm[act.get("player_name") or ""].append(act["o"])
    mo_n, mk_n = sum(mo.values()), sum(mk.values())
    mo_mean = sum(v * c for v, c in mo.items()) / mo_n
    mk_mean = sum(v * c for v, c in mk.items()) / mk_n
    mo_sd = (sum(c * (v - mo_mean) ** 2 for v, c in mo.items()) / mo_n) ** .5
    mk_sd = (sum(c * (v - mk_mean) ** 2 for v, c in mk.items()) / mk_n) ** .5
    n = len(real_o)
    fold.add("shape", "outs_mean", mo_mean, st.mean(real_o),
             st.pstdev(real_o) / n ** 0.5, n)
    fold.add("shape", "outs_sd", mo_sd, st.pstdev(real_o),
             st.pstdev(real_o) / (2 * n) ** 0.5, n)
    # DOES THE MODEL TELL STARTS APART? Added 2026-09-11 for TODO 32, whose
    # pre-registered falsifier names this number and `boundary_share_by_
    # decision` — and says to BUILD the row if nothing here can see a
    # per-arm term. Nothing could: every other `shape` row is a POOLED
    # distribution over draws, and a term that moves one arm up and another
    # down by construction leaves all of them unmoved. This row is the only
    # one in the battery that scores DISCRIMINATION BETWEEN starts rather
    # than the shape of an average one, which is what `leash.py` records a
    # per-arm term as buying ("FLAT on outs CRPS and the run ladder BY
    # DESIGN").
    # READ THE CEILING AS LOOSE, AND DO NOT PRICE THE GAP (added 2026-09-11,
    # with the number that bounds it). The ceiling is computed WITHIN the
    # fold, so every scrap of in-season between-arm variation counts as
    # signal — including the part that no prior-season evidence can know. The
    # per-arm outs residual carries year over year at only r +0.225
    # (`scratchpad/leash_carry.py`, 451 arm-pairs), so the STABLE between-arm
    # signal is sd 0.551 outs, and a PERFECT per-arm term is worth about
    # +0.023 of this correlation — roughly a sixth of the ~0.135 gap the row
    # prints. The shipped `sim.leash` already measures +0.0130 of that
    # (`scratchpad/arm_score.py --control-leash`). So a 4-sigma gap here is a
    # real defect and MOSTLY NOT a per-arm one; treating the whole gap as
    # reachable by a better leash is the mistake TODO 32 made.
    if len(o_pairs) > 10:
        fold.add("shape", "outs_corr", _corr(o_pairs),
                 _corr_ceiling(o_by_arm), 1 / (len(o_pairs) - 3) ** 0.5,
                 len(o_pairs),
                 "actual vs model mean outs per start; real = the "
                 "model-free per-arm ceiling (LOOSE — see the comment)")
    nk = len(real_k)
    fold.add("shape", "k_mean", mk_mean, st.mean(real_k),
             st.pstdev(real_k) / nk ** 0.5, nk)
    fold.add("shape", "k_sd", mk_sd, st.pstdev(real_k),
             st.pstdev(real_k) / (2 * nk) ** 0.5, nk)
    k9a = sum(1 for v in real_k if v >= 9) / nk
    fold.add("shape", "k_9_plus_share",
             sum(c for v, c in mk.items() if v >= 9) / mk_n, k9a,
             _rate_se(k9a, nk), nk)
    for ln in OUTS_LINES:
        aa = sum(1 for v in real_o if v > ln) / n
        fold.add("shape", f"outs_over_{ln}",
                 sum(c for v, c in mo.items() if v > ln) / mo_n, aa,
                 _rate_se(aa, n), n)
    if kinds:
        rb = sum(1 for _o, k_ in kinds if k_ == "boundary") / len(kinds)
        fold.add("shape", "boundary_share_by_decision",
                 1 - mid_draws / tot_draws, rb, _rate_se(rb, len(kinds)),
                 len(kinds))
        for o in SPIKES:
            rt = [k_ for oo, k_ in kinds if oo == o]
            mt = mo.get(o, 0)
            if not rt or not mt:
                continue
            ra_ = len(rt) / len(kinds)
            fold.add("shape", f"spike_{o}_share", mt / mo_n, ra_,
                     _rate_se(ra_, len(kinds)), len(kinds))
            rmid = sum(1 for k_ in rt if k_ == "mid") / len(rt)
            fold.add("shape", f"spike_{o}_mid_share",
                     spike_mid.get(o, 0) / mt, rmid,
                     _rate_se(rmid, len(rt)), len(rt))

    # The current betting-layer correction, informational.
    from scratchpad import outs_adjust
    for ln, (m_, a_) in sorted(outs_adjust.MEASURED.items()):
        fold.add("outs_adjust", f"corr_o{ln}", a_ - m_, None, 0.0, 0,
                 f"measured {outs_adjust.MEASURED_ON}")


def _mass(got, gids, which, lo, hi):
    """Pooled draw-level share, read off the `dist_*` counters the model
    payload keeps per game — the actual draws, not an approximation."""
    tot = hit = 0
    for g in gids:
        for v, k in got[g][0][f"dist_{which}"].items():
            tot += k
            if lo <= v <= hi:
                hit += k
    return hit / tot if tot else None


# ── driver ──────────────────────────────────────────────────────────────

def _print_fold(fold: Fold):
    print(f"\n  ── FOLD {fold.year} "
          f"(cut {fold.cut}) ──────────────────────────────────")
    groups: dict = {}
    for r in fold.rows:
        groups.setdefault(r["group"], []).append(r)
    for grp, rows_ in groups.items():
        print(f"\n  {grp}")
        print(f"    {'key':<26}{'model':>9}{'actual':>9}{'gap':>9}"
              f"{'se':>8}{'z':>7}{'floor':>8}{'n':>9}")
        if grp.startswith("venue"):
            rows_ = sorted(
                rows_, key=lambda r: -(abs(r["gap"] or 0)
                                       if r["key"] != "wmean_abs_resid"
                                       else 9e9))
        for r in rows_:
            f = lambda v, fm: (fm.format(v) if v is not None else "-")  # noqa
            print(f"    {r['key']:<26}{f(r['model'], '{:>9.4f}')}"
                  f"{f(r['actual'], '{:>9.4f}')}"
                  f"{f(r['gap'], '{:>+9.4f}')}{f(r['se'], '{:>8.4f}')}"
                  f"{f(r['z'], '{:>+7.1f}')}{f(r['floor'], '{:>8.4f}')}"
                  f"{r['n']:>9,}"
                  f"{('  ' + r['note']) if r['note'] else ''}")


def _diff(rows_now, path_prev, se_key="se"):
    prev = json.load(open(path_prev))
    old = {(r["fold"], r["group"], r["key"]): r for r in prev["rows"]}
    print(f"\n  DIFF against {path_prev}")
    if prev.get("meta", {}).get("flags") != flags_jsonable():
        print("  FLAGS DIFFER between the two runs:")
        for k, v in flags_jsonable().items():
            pv = prev.get("meta", {}).get("flags", {}).get(k, "<absent>")
            if pv != v:
                print(f"    {k}: {pv} -> {v}")
    moved = 0
    for r in rows_now:
        o = old.get((r["fold"], r["group"], r["key"]))
        if not o or r["gap"] is None or o.get("gap") is None:
            continue
        thresh = r[se_key] or o.get(se_key) or 0
        if thresh and abs(r["gap"] - o["gap"]) > thresh:
            moved += 1
            print(f"    {r['fold']} {r['group']}/{r['key']:<24} gap "
                  f"{o['gap']:+.4f} -> {r['gap']:+.4f}  (se {thresh:.4f})")
    if not moved:
        print("    no row moved by more than one se")


def flags_jsonable():
    return {k: (v if isinstance(v, (bool, int, float, str, type(None)))
                else str(v)) for k, v in flags().items()}


def main(argv):
    global _CASES, _LG, _PENS, _SIMS
    # macOS KILLS FORKED CHILDREN once Objective-C state has been touched
    # in the parent — and a single stale-cache `roster.load()` network call
    # touches it. The 2026 fold's whole pool died at fork and `pool.map`
    # hung forever at 0% CPU, ten minutes into a run. The documented
    # escape hatch is this env var, which must be set BEFORE the
    # interpreter starts, hence the re-exec.
    import os
    if sys.platform == "darwin" and \
            os.environ.get("OBJC_DISABLE_INITIALIZE_FORK_SAFETY") != "YES":
        os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        os.execv(sys.executable,
                 [sys.executable, "-m", "scratchpad.battery"] + argv)
    limit = None
    fold_years = [y for y, _ in FOLDS]
    diff_fp = None
    mods = {"sim": sim, "game": game, "calibrate": cal}
    # An option's space-separated value is CONSUMED — without this, the
    # value of `--on calibrate.USE_PARK` fell through into the positional
    # list and was parsed as the sim count.
    consumed: set = set()
    takes_value = ("--limit", "--folds", "--diff", "--on", "--off")
    for i, a in enumerate(argv):
        if not any(a.startswith(t) for t in takes_value):
            continue
        v = a.split("=", 1)[1] if "=" in a else argv[i + 1]
        if "=" not in a:
            consumed.add(i + 1)
        if a.startswith("--limit"):
            limit = int(v)
        elif a.startswith("--folds"):
            fold_years = [int(y) for y in v.split(",")]
        elif a.startswith("--diff"):
            diff_fp = v
        # `--on calibrate.USE_PARK,...` / `--off ...`: flip switches for
        # THIS RUN. The header and the JSON record live values, so a run
        # under a candidate config is attributable by construction — this
        # is how an A/B goes through the battery without editing source.
        else:
            for dotted in v.split(","):
                mod, attr = dotted.split(".")
                assert hasattr(mods[mod], attr), f"unknown flag {dotted}"
                setattr(mods[mod], attr, a.startswith("--on"))
    pos = [a for i, a in enumerate(argv)
           if not a.startswith("-") and i not in consumed]
    _SIMS = int(pos[0]) if pos else 40
    maim = "--maim" in argv
    dev = bool(limit) or _SIMS != 40 or maim or \
        set(fold_years) != {y for y, _ in FOLDS}

    print("  THE BATTERY — every table, one pass per fold")
    if dev:
        print("  *** DEV RUN — NOT REPORTABLE (limit/sims/folds/maim "
              "non-standard) ***")
    if maim:
        print("  *** POSITIVE CONTROL: ADVANCE_3B_ON_OUT HALVED ***")
        sim.ADVANCE_3B_ON_OUT = {k: v / 2
                                 for k, v in sim.ADVANCE_3B_ON_OUT.items()}
    print(f"  {_SIMS} sims a game, folds {fold_years}, "
          f"limit {limit or 'none'}")
    print("  flags:")
    for k, v in flags().items():
        print(f"    {k} = {v}")

    # Engine fingerprint off the LAST fold's cases (2026 when standard).
    yr, cut = [f for f in FOLDS if f[0] == max(fold_years)][0]
    pairs = cal.paired_cases(season=yr, rates_before=cut, since=cut)
    lg = sim.league(season=yr, before=cut)
    pens = rate_src.bullpens(lg, season=yr, before=cut)
    fp = engine_fingerprint(pairs, lg, pens)
    print(f"\n  engine fingerprint {fp}")

    _install()
    hook_rows = json.load(open(ROWS))
    with db.connect() as c:
        act_db_all = {r["game_id"]: dict(r) for r in c.execute(
            "select game_id, away_score, home_score, away_score_f5,"
            " home_score_f5, venue_id from games where sport='mlb'")}

    all_rows = []
    folds_meta = []
    for year, cut in FOLDS:
        if year not in fold_years:
            continue
        pairs = cal.paired_cases(season=year, rates_before=cut, since=cut)
        gids = sorted(pairs)[:limit] if limit else sorted(pairs)
        _CASES = {g: pairs[g] for g in gids}
        _LG = sim.league(season=year, before=cut)
        # `season=` IS LOAD-BEARING: without it the resolver defaulted to
        # the current season, the 2023-2025 folds got ZERO pen clubs, and
        # `Side.current` quietly handed every relief inning to the
        # STARTER'S rates. Three of four folds measured a bullpen-free
        # engine until 2026-09-09. `_where` now heals this class of call,
        # but the fold loop says what it means.
        _PENS = rate_src.bullpens(_LG, season=year, before=cut)
        # Warm the weather table IN THE PARENT so forked workers inherit
        # it instead of each opening the database at first replay.
        cal.air_mult_for({"game_id": ""})
        _HANDS.clear()
        _PIDS.clear()
        for g in gids:
            for case in pairs[g]:
                nm = case[0].get("player_name")
                if nm and nm not in _HANDS:
                    _HANDS[nm] = roster.throws(nm)
                    _PIDS[nm] = roster.player_id(nm)
        real_hook = {}
        for curve, sel in (("bnd", True), ("mid", False)):
            agg = defaultdict(lambda: [0, 0])
            for r in hook_rows:
                d = r.get("date") or ""
                if d[:4] != str(year) or d < cut:
                    continue
                if bool(r.get("ends_inning")) != sel:
                    continue
                agg[_bucket(r["pitches"])][0] += bool(r.get("removed"))
                agg[_bucket(r["pitches"])][1] += 1
            real_hook[curve] = {b: (v[0], v[1]) for b, v in agg.items()}

        venue_cover = st.mean(
            bool(act_db_all.get(g, {}).get("venue_id")) for g in gids)
        print(f"\n  fold {year}: {len(gids)} paired games, venue coverage "
              f"{venue_cover:.1%}", flush=True)
        if cal.USE_PARK:
            # COVERAGE BEFORE ANY SCORE, and a parent-side pre-warm in one
            # move: `park_for` caches per (venue, year), the workers
            # inherit the cache through the fork, and no child ever races
            # seven siblings to fetch the same Savant page.
            rated = 0
            for g in gids:
                d = (pairs[g][1][0].get("date") or "")
                pk = cal.park_for(pairs[g][1][0].get("venue_id"),
                                  int(d[:4]) if d[:4].isdigit() else None)
                rated += pk != sim.NEUTRAL_PARK
            print(f"  fold {year}: park RATED for {rated}/{len(gids)} "
                  f"games ({rated / len(gids):.1%}); the rest simulate "
                  f"NEUTRAL and are coverage misses, not home-park guesses",
                  flush=True)
        ctx = mp.get_context("fork")
        with ctx.Pool(max(1, (mp.cpu_count() or 4) - 2)) as pool:
            got_l = pool.map(_one, gids, chunksize=4)
        got = {g: (m, a) for g, m, a in got_l if m and a
               and g in act_db_all
               and act_db_all[g]["away_score"] is not None
               and act_db_all[g]["away_score_f5"] is not None}
        print(f"  fold {year}: {len(got)} games scored "
              f"({len(gids) - len(got)} dropped: no pbp or no score)")
        fold = Fold(year, cut)
        _score_fold(fold, got, act_db_all, real_hook)
        _print_fold(fold)
        all_rows.extend(fold.rows)
        folds_meta.append({"year": year, "cut": cut, "games": len(got)})

    out = {"meta": {"engine_fp": fp, "n_sims": _SIMS, "dev": dev,
                    "maim": maim, "flags": flags_jsonable(),
                    "folds": folds_meta},
           "rows": all_rows}
    # DEV RUNS GET THEIR OWN NAMESPACE: a dev run under an unchanged engine
    # has the same fingerprint as the standard baseline and would silently
    # overwrite it otherwise.
    path = f"scratchpad/battery_{'dev_' if dev else ''}{fp[:12]}.json"
    if diff_fp:
        prev_path = (diff_fp if diff_fp.endswith(".json")
                     else f"scratchpad/battery_{diff_fp[:12]}.json")
        if not maim and fp.startswith(diff_fp[:12]):
            print("\n  *** THE ENGINE FINGERPRINT DID NOT MOVE — the "
                  "mechanism under test is not live. ***")
            path = path.replace(".json", "_dup.json")
        json.dump(out, open(path, "w"))
        print(f"\n  saved {path}")
        _diff(all_rows, prev_path)
    else:
        json.dump(out, open(path, "w"))
        print(f"\n  saved {path}")


if __name__ == "__main__":
    main(sys.argv[1:])
