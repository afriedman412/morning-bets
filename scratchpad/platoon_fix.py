"""Handedness, specified correctly: shrink toward the LEAGUE platoon
effect for the hitter's side, not toward his own overall rate.

    venv/bin/python -m scratchpad.platoon_fix [workers]

THE ERROR THIS REPLACES. `rates.batter_rates_by_hand` shrinks each split
toward the HITTER'S OWN OVERALL RATE, so a hitter with a thin split
regresses to having NO platoon effect. That is the one answer known to be
false: a left-handed bat loses about a quarter of its home run rate against
a left-handed arm, measured over 62,000 plate appearances. The shipped
construction keeps each hitter's PERSONAL DEVIATION — the noisy half that
does not persist across seasons — and discards the STRUCTURAL half, which
is the reliable one. That is the best explanation for a mechanism scoring
+3.5 sigma in sample and -2.3 out of it.

THE CONSTRUCTION, two levels, in the order the rest of this codebase uses:

    structural   his overall rate, scaled by how the league's (his side vs
                 this hand) cell compares to the blend HE would produce
                 given the mix he actually faces.
    individual   his own measured deviation from that, shrunk by n/(n+k).

SWITCH HITTERS ARE WHY THE BLEND IS PER-BATTER. A switch hitter bats left
against right-handers and right against left-handers, so he takes the
platoon ADVANTAGE both ways and has no disadvantage to model. Dividing by a
league blend for "left-handed batters" would invent one. Dividing by the
blend HIS OWN sides and mix produce gives him a ratio of ~1.0 both ways,
which is correct and falls out rather than being special-cased.

LEAK-FREE BY SEASON. Both the league table and the individual splits can be
counted on seasons the scored starts are not in. The in-sample version is
kept only as the upper bound it is.
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

from src import db
from src.context.sources import pbp

CACHE = pathlib.Path("scratchpad/platoon_fix2.json")

_K = ("strikeout", "strikeout_double_play")
_HIT = ("single", "double", "triple")
_BIP_OUT = ("field_out", "force_out", "fielders_choice_out",
            "grounded_into_double_play", "double_play", "triple_play",
            "field_error")
_BB = ("walk", "intent_walk", "hit_by_pitch")

#: [pa, k, hits, bip, hr, bb]
_N = 6

#: Plate appearances against one hand at which a hitter's OWN deviation
#: from the league platoon effect outweighs the league effect itself.
#: Deliberately higher than `SPLIT_STABILISE`: the prior here is a far
#: better guess than "no split at all", so it should take more evidence to
#: move off it, not less.
DEV_STABILISE = 300


def scan(short: str):
    try:
        d = pbp.fetch(short)
    except Exception:
        return None
    if not d:
        return None
    league = defaultdict(lambda: [0] * _N)      # (batSide, pitchHand)
    bat = defaultdict(lambda: [0] * _N)         # (bid, pitchHand)
    pit = defaultdict(lambda: [0] * _N)         # (pid, batSide)
    phand = {}                                  # pid -> throwing hand
    side = defaultdict(lambda: defaultdict(int))  # (bid, pitchHand) -> side
    names = {}
    for p in (d.get("allPlays") or []):
        mu = p.get("matchup") or {}
        res = p.get("result") or {}
        b = mu.get("batter") or {}
        bid = b.get("id")
        bs = ((mu.get("batSide") or {}).get("code") or "")
        ph = ((mu.get("pitchHand") or {}).get("code") or "")
        if not bid or bs not in ("L", "R") or ph not in ("L", "R"):
            continue
        names[bid] = b.get("fullName")
        pit_ = mu.get("pitcher") or {}
        pid = pit_.get("id")
        if pid:
            names[pid] = pit_.get("fullName")
            phand[pid] = ph
        ev = res.get("eventType") or ""
        side[(bid, ph)][bs] += 1
        cells = [league[(bs, ph)], bat[(bid, ph)]]
        if pid:
            cells.append(pit[(pid, bs)])
        for c in cells:
            c[0] += 1
            if ev in _K:
                c[1] += 1
            if ev in _HIT:
                c[2] += 1
                c[3] += 1
            elif ev in _BIP_OUT:
                c[3] += 1
            elif ev == "home_run":
                c[4] += 1
            elif ev in _BB:
                c[5] += 1
    return ({f"{a}{b}": v for (a, b), v in league.items()},
            {f"{a}|{b}": v for (a, b), v in bat.items()},
            {f"{a}|{b}": dict(v) for (a, b), v in side.items()},
            {str(k): v for k, v in names.items() if v},
            {f"{a}|{b}": v for (a, b), v in pit.items()},
            {str(k): v for k, v in phand.items()})


def build(workers: int = 8):
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    with db.connect() as c:
        games = {r["game_id"]: r["date"] for r in
                 c.execute("select game_id, date from games"
                           " where sport = 'mlb'")}
    todo = sorted((g, d) for g, d in games.items()
                  if pbp.have(g.split("-")[-1]))
    print(f"  scanning {len(todo):,} games on {workers} workers ...",
          flush=True)
    out = {"league": defaultdict(lambda: defaultdict(lambda: [0] * _N)),
           "bat": defaultdict(lambda: defaultdict(lambda: [0] * _N)),
           "pit": defaultdict(lambda: defaultdict(lambda: [0] * _N)),
           "side": defaultdict(lambda: defaultdict(lambda: defaultdict(int))),
           "names": {}, "phand": {}}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        res = ex.map(scan, [g.split("-")[-1] for g, _ in todo], chunksize=32)
        for (g, date), got in zip(todo, res):
            if not got:
                continue
            lg_, bat_, side_, names_, pit_, phand_ = got
            y = str(int(date[:4]))
            for k, v in lg_.items():
                c = out["league"][y][k]
                for i in range(_N):
                    c[i] += v[i]
            for k, v in bat_.items():
                c = out["bat"][y][k]
                for i in range(_N):
                    c[i] += v[i]
            for k, v in pit_.items():
                c = out["pit"][y][k]
                for i in range(_N):
                    c[i] += v[i]
            out["phand"].update(phand_)
            for k, v in side_.items():
                for s, n in v.items():
                    out["side"][y][k][s] += n
            out["names"].update(names_)
    packed = {
        "league": {y: dict(d) for y, d in out["league"].items()},
        "bat": {y: dict(d) for y, d in out["bat"].items()},
        "side": {y: {k: dict(v) for k, v in d.items()}
                 for y, d in out["side"].items()},
        "pit": {y: dict(d) for y, d in out["pit"].items()},
        "names": out["names"],
        "phand": out["phand"],
    }
    CACHE.write_text(json.dumps(packed))
    return packed


def _merge(per_year: dict, seasons) -> dict:
    out = defaultdict(lambda: [0] * _N)
    for y in seasons:
        for k, v in (per_year.get(str(y)) or {}).items():
            c = out[k]
            for i in range(len(v)):
                c[i] += v[i]
    return out


def _rates(c):
    pa, k, h, bip, hr, bb = c
    if not pa:
        return None
    return {"pa": pa, "k_pct": k / pa, "bb_pct": bb / pa, "hr_pct": hr / pa,
            "babip": (h / bip) if bip else None}


_STATS = ("k_pct", "bb_pct", "hr_pct", "babip")


def splits(overall: dict, data: dict, seasons, dev_seasons=None,
           dev_k: float = DEV_STABILISE, structural: bool = True,
           amplify: float = 1.0) -> dict:
    """{name: {'L': rates, 'R': rates}} with the league platoon as prior.

    `structural=False` reproduces the SHIPPED behaviour — shrink toward the
    hitter's own overall rate — so the two specifications can be A/B'd
    against each other with everything else held fixed.

    `amplify` scales the structural ratio away from 1.0 and exists ONLY as a
    POSITIVE CONTROL. A mis-specified mechanism and an absent effect produce
    identical output, so a null is worthless until the harness has been shown
    to detect a known effect of known size. Run the same screen at 3x and 6x:
    if those are seen and 1x is not, the real effect is genuinely too small;
    if even 6x is invisible, the screen is broken and its null means nothing.
    """
    dev_seasons = dev_seasons or seasons
    lg_cells = _merge(data["league"], seasons)
    bat_cells = _merge(data["bat"], dev_seasons)
    names = data["names"]

    # Which side does he bat from against each hand? Counted, so switch
    # hitters resolve themselves and nobody needs a roster lookup.
    sides = defaultdict(lambda: defaultdict(int))
    for y in dev_seasons:
        for key, d in (data["side"].get(str(y)) or {}).items():
            bid, ph = key.split("|")
            for s, n in d.items():
                sides[(bid, ph)][s] += n

    lg = {k: _rates(v) for k, v in lg_cells.items()}
    by_bat = defaultdict(dict)
    for key, v in bat_cells.items():
        bid, ph = key.split("|")
        by_bat[bid][ph] = v

    out: dict = {}
    for bid, byh in by_bat.items():
        nm = names.get(bid)
        base = overall.get(nm) if nm else None
        if not base:
            continue
        # HIS blend: the league rate he would post given the sides he bats
        # from and the mix of hands he faces. For a switch hitter both cells
        # are platoon-advantaged, so his ratios come out ~1.0 and he
        # correctly receives no adjustment.
        mine = {}
        for ph in ("L", "R"):
            s = sides.get((bid, ph)) or {}
            bs = max(s, key=s.get) if s else None
            cell = lg.get(f"{bs}{ph}") if bs else None
            mine[ph] = (bs, cell, (byh.get(ph) or [0] * _N)[0])
        tot_pa = sum(m[2] for m in mine.values())
        if not tot_pa:
            continue
        blend = {}
        for stat in _STATS:
            num = den = 0.0
            for ph, (bs, cell, pa) in mine.items():
                if cell and cell.get(stat) is not None and pa:
                    num += pa * cell[stat]
                    den += pa
            blend[stat] = (num / den) if den else None

        out[nm] = {}
        for ph in ("L", "R"):
            bs, cell, _pa = mine[ph]
            obs = _rates(byh.get(ph) or [0] * _N)
            row = {"name": nm, "hand": ph, "pa": (obs or {}).get("pa", 0),
                   "side": bs}
            for stat in _STATS:
                b = base[stat]
                if structural and cell and cell.get(stat) is not None \
                        and blend.get(stat):
                    ratio = cell[stat] / blend[stat]
                    prior = b * (1.0 + amplify * (ratio - 1.0))
                else:
                    prior = b
                o = (obs or {}).get(stat)
                n = (obs or {}).get("pa", 0) or 0
                if o is None or not n:
                    row[stat] = prior
                else:
                    w = n / (n + dev_k)
                    row[stat] = w * o + (1 - w) * prior
            out[nm][ph] = row
    return out


def main(argv):
    data = build(int(argv[0]) if argv else 8)
    lg = {k: _rates(v) for k, v in _merge(data["league"],
                                          (2023, 2024, 2025, 2026)).items()}
    print(f"\n  {'cell':<9}{'PA':>11}{'K%':>9}{'BB%':>8}{'HR%':>8}"
          f"{'BABIP':>9}")
    for k in ("RR", "RL", "LR", "LL"):
        r = lg.get(k)
        if r:
            print(f"  {k[0]} vs {k[1]:<5}{r['pa']:>11,}{r['k_pct']:>9.4f}"
                  f"{r['bb_pct']:>8.4f}{r['hr_pct']:>8.4f}"
                  f"{r['babip']:>9.4f}")
    print(f"\n  {len(data['names']):,} batters, "
          f"{sum(len(v) for v in data['bat'].values()):,} batter-season-hand"
          f" cells")


if __name__ == "__main__":
    main(sys.argv[1:])


def pitcher_splits(overall: dict, data: dict, seasons,
                   dev_seasons=None, dev_k: float = 1e9) -> dict:
    """{name: {'L': rates, 'R': rates}} — HIS rates against each batter side.

    THE HALF THAT NEVER EXISTED. Every handedness attempt in this project
    conditioned the batter and left the pitcher on his blended line, so a
    two-sided matchup was only ever half specified.

    Same two-level construction as the batter side and for the same reason:
    the prior is the LEAGUE cell for a pitcher of his hand against this
    batter side, scaled against the blend HIS OWN mix of opposing sides
    produces. Shrinking toward his own overall rate would regress a
    thin-sample pitcher to having no platoon split, which is the error this
    whole rebuild exists to remove.

    `dev_k` defaults to switching the individual deviation OFF, because on
    the batter side the personal split measured as noise — it cost 5.7 sd on
    walks against the pure structural arm.
    """
    dev_seasons = dev_seasons or seasons
    lg_cells = _merge(data["league"], seasons)
    lg = {k: _rates(v) for k, v in lg_cells.items()}
    pit_cells = _merge(data["pit"], dev_seasons)
    names, phand = data["names"], data.get("phand") or {}

    by_pit: dict = defaultdict(dict)
    for key, v in pit_cells.items():
        pid, bs = key.split("|")
        by_pit[pid][bs] = v

    out: dict = {}
    for pid, bysd in by_pit.items():
        nm = names.get(pid)
        base = overall.get(nm) if nm else None
        ph = phand.get(pid)
        if not base or ph not in ("L", "R"):
            continue
        blend = {}
        for stat in _STATS:
            num = den = 0.0
            for bs in ("L", "R"):
                cell = lg.get(f"{bs}{ph}")
                pa = (bysd.get(bs) or [0] * _N)[0]
                if cell and cell.get(stat) is not None and pa:
                    num += pa * cell[stat]
                    den += pa
            blend[stat] = (num / den) if den else None
        out[nm] = {}
        for bs in ("L", "R"):
            cell = lg.get(f"{bs}{ph}")
            obs = _rates(bysd.get(bs) or [0] * _N)
            row = {"name": nm, "bat_side": bs, "hand": ph,
                   "pa": (obs or {}).get("pa", 0)}
            for stat in _STATS:
                b = base[stat]
                if cell and cell.get(stat) is not None and blend.get(stat):
                    prior = b * (cell[stat] / blend[stat])
                else:
                    prior = b
                o = (obs or {}).get(stat)
                n = (obs or {}).get("pa", 0) or 0
                if o is None or not n:
                    row[stat] = prior
                else:
                    w = n / (n + dev_k)
                    row[stat] = w * o + (1 - w) * prior
            out[nm][bs] = row
    return out


def league_cells(data: dict, seasons, lg: dict) -> dict:
    """{'RL': rates, ...} — the log5 baseline for each matchup cell, RATIOED
    onto the model's own league level rather than substituted wholesale.

    THIS IS NOT A DETAIL. These cells are counted off play-by-play and the
    model's league rates come from boxscore aggregates, so the two sit on
    different footings: walks here include hit-by-pitch, which the simulator
    draws separately, and the counted balls-in-play denominator differs from
    the boxscore one. Measured, my counts against `sim.league()`:

        k_pct 1.042    bb_pct 1.172    hr_pct 0.966    babip 1.037

    Substituting the absolute cell therefore moved the WALK LEVEL by 17%
    and called it handedness — it cost +6.9 sd on walks, swamping an effect
    worth a fraction of that. Only the RATIO between a cell and the counted
    overall carries platoon information; the level must stay the model's.
    The batter and pitcher priors were never exposed to this because they
    already use `cell / blend`, where the footing cancels.
    """
    cells = {k: _rates(v) for k, v in _merge(data["league"], seasons).items()
             if _rates(v)}
    raw = _merge(data["league"], seasons)
    tot = {}
    for stat in _STATS:
        if stat == "babip":
            num = sum(raw[k][2] for k in cells)
            den = sum(raw[k][3] for k in cells)
            tot[stat] = (num / den) if den else None
        else:
            num = sum(cells[k]["pa"] * cells[k][stat] for k in cells)
            den = sum(cells[k]["pa"] for k in cells)
            tot[stat] = (num / den) if den else None
    out = {}
    for key, c in cells.items():
        out[key] = {stat: (lg[stat] * c[stat] / tot[stat])
                    if (tot.get(stat) and c.get(stat) is not None)
                    else lg[stat] for stat in _STATS}
    return out
