"""Resolve a matchup per PITCH TYPE, then average. The arsenal idea, redone.

WHAT THE OLD VERSION DID WRONG. `rates.arsenal_mults` collapsed a pitcher's
whole arsenal into one scalar — this hitter's projection against that mix
over his projection against a league-average mix — and multiplied his
aggregate rate by it. That measured 9.79% against 9.79%, a dead-even zero.
Three things were wrong with the construction, independent of whether the
effect is real:

  * It DISCARDS THE STRUCTURE. A pitcher who throws 45% sliders to a hitter
    who cannot touch sliders is a different matchup from one who throws 15%,
    and a single multiplier cannot tell them apart once it has been formed.
  * It DOUBLE-SHRINKS. The aggregate rate is already regressed toward the
    league, and the multiplier is built from components that were regressed
    separately, so the matchup signal is attenuated twice.
  * It was CLAMPED to [0.80, 1.25], which is defensible as a guard and also
    caps the exact cases that would carry the most information.

WHAT THIS DOES INSTEAD. The same log5 the rest of the model uses, evaluated
once per pitch type and averaged by how often he actually throws it:

    P(K) = sum over t of  usage_p(t) * log5( k_b(t), k_p(t), lg_k(t) )

No multiplier, no clamp, no second shrinkage. A pitcher whose mix is
league-average against a hitter with no per-pitch tendencies returns exactly
the aggregate answer, so this DEGRADES GRACEFULLY to the current model —
which is the property that makes it safe to switch on.

THE BINDING CONSTRAINT IS SAMPLE SIZE, NOT CONSTRUCTION. Savant gives ~3,290
batter rows over ~1,000 hitters, so a single hitter's slider line is a few
dozen plate appearances. Each per-pitch rate is therefore shrunk toward that
batter's OWN aggregate rate — not toward the league — so a thin cell falls
back to what we already believed about him rather than to a stranger.
Clustering pitchers was tried as a way to pool those cells and measured too
small to help (see `archetype.py`).

PRE-REGISTERED. `PREREG-arsenal.md` fixes the decision rule, written before
any of this was run. The endpoint is F5 and game-total CRPS, not prop lines,
and the bar is two standard errors on the paired difference.
"""
from __future__ import annotations

import csv
import glob
import sys

from src.context.sources.archetype import flip_name

#: Per-pitch cells are thin. A batter's rate against one pitch type is
#: shrunk toward HIS OWN overall rate with this many plate appearances of
#: prior weight — toward himself, not toward the league, because his overall
#: rate is the best thing we know about him when the cell is empty.
CELL_SHRINK_PA = 60

#: A pitcher's usage must cover at least this much of his arsenal before the
#: mixture is trusted; below it the missing families would silently
#: renormalise onto whatever is left.
MIN_COVERAGE = 0.80


def _latest(pattern: str) -> str | None:
    f = sorted(glob.glob(f".cache/{pattern}"))
    return f[-1] if f else None


def _load(path: str, key_name: str) -> dict:
    """{player: {pitch_type: row}} from a Savant arsenal export."""
    out: dict[str, dict] = {}
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            nm = flip_name(r[key_name])
            out.setdefault(nm, {})[r["pitch_type"]] = r
    return out


def _f(row, key):
    try:
        v = row.get(key)
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def load(pitcher_path=None, batter_path=None) -> dict:
    """Both sides of the arsenal data, keyed by name."""
    pp = pitcher_path or _latest("savant_pitch_arsenal_*.csv")
    bp = batter_path or _latest("savant_batter_arsenal_*.csv")
    if not pp or not bp:
        return {}
    return {"pitchers": _load(pp, "last_name, first_name"),
            "batters": _load(bp, "last_name, first_name")}


def league_by_pitch(data: dict) -> dict:
    """League K rate and wOBA per pitch type — the log5 baseline per type.

    Computed from the PITCHER side, weighted by pitches thrown, because that
    is the population the simulator draws from. Using the batter side would
    weight by who happened to face what.
    """
    agg: dict[str, dict] = {}
    for arsenal in data["pitchers"].values():
        for pt, row in arsenal.items():
            n = _f(row, "pitches") or 0
            k = _f(row, "k_percent")
            w = _f(row, "woba")
            if not n or k is None:
                continue
            a = agg.setdefault(pt, {"n": 0.0, "k": 0.0, "w": 0.0, "wn": 0.0})
            a["n"] += n
            a["k"] += n * k
            if w is not None:
                a["w"] += n * w
                a["wn"] += n
    return {pt: {"k_pct": a["k"] / a["n"] / 100.0,
                 "woba": (a["w"] / a["wn"]) if a["wn"] else None,
                 "pitches": a["n"]}
            for pt, a in agg.items() if a["n"] > 0}


def _shrunk_cell(row, overall: float | None, key: str) -> float | None:
    """A per-pitch rate pulled toward the player's own overall rate."""
    v = _f(row, key)
    if v is None:
        return overall
    v /= 100.0 if key.endswith("percent") else 1.0
    pa = _f(row, "pa") or 0.0
    if overall is None:
        return v
    w = pa / (pa + CELL_SHRINK_PA)
    return w * v + (1.0 - w) * overall


def matchup_k(batter: str, pitcher: str, data: dict, lg_by_pitch: dict,
              b_overall: float, p_overall: float, lg_overall: float,
              log5) -> float | None:
    """Mixture K rate for one matchup, or None if the arsenal is unusable.

    Returns None rather than a guess whenever coverage is thin — the same
    rule the rest of this codebase follows, because a guessed value that
    moves the estimate in a definite wrong direction is worse than no value.
    """
    ars = data["pitchers"].get(pitcher)
    if not ars:
        return None
    bat = data["batters"].get(batter) or {}
    num = cov = 0.0
    for pt, row in ars.items():
        usage = (_f(row, "pitch_usage") or 0.0) / 100.0
        lgp = lg_by_pitch.get(pt)
        kp = _f(row, "k_percent")
        if not usage or not lgp or kp is None:
            continue
        # Pitcher's K rate WITH this pitch, batter's K rate AGAINST it, and
        # the league baseline FOR it. Each cell shrunk toward that player's
        # own overall rate so a thin cell falls back to what we already knew.
        kp = kp / 100.0
        kb = _shrunk_cell(bat.get(pt, {}), b_overall, "k_percent")
        num += usage * log5(kb, kp, lgp["k_pct"])
        cov += usage
    if cov < MIN_COVERAGE:
        return None
    # Renormalise over the families actually covered, then rescale so a
    # league-average arsenal against a batter with no tendencies reproduces
    # the aggregate answer exactly. Without that rescale the mixture carries
    # any level difference between the per-pitch league rates and the
    # simulator's own baseline.
    mixed = num / cov
    ref = _reference(ars, lg_by_pitch, lg_overall, log5)
    if not ref:
        return None
    return max(1e-6, min(0.95, mixed * (p_overall / ref)))


def league_usage(lg_by_pitch: dict) -> dict:
    """League-wide share of pitches by type — the neutral arsenal."""
    tot = sum(v["pitches"] for v in lg_by_pitch.values()) or 1.0
    return {pt: v["pitches"] / tot for pt, v in lg_by_pitch.items()}


def batter_woba(name: str, data: dict, lg_usage: dict) -> float | None:
    """This batter's overall wOBA, weighted by the LEAGUE arsenal.

    The shrinkage base for his per-pitch cells. Using the league's wOBA
    instead would pull a thin cell toward a stranger; this pulls it toward
    what we already believe about him, which is the rule the rest of the
    codebase follows for a missing group value.
    """
    bat = data["batters"].get(name)
    if not bat:
        return None
    num = den = 0.0
    for pt, u in lg_usage.items():
        w = _f(bat.get(pt, {}), "woba")
        if w is None:
            continue
        num += u * w
        den += u
    return (num / den) if den >= 0.5 else None


def matchup_contact(batter: str, pitcher: str, data: dict, lg_by_pitch: dict,
                    b_overall: float | None = None,
                    lg_usage: dict | None = None) -> float | None:
    """Contact-quality multiplier for one matchup, or None if unusable.

    THE CHANNEL THE STRIKEOUT VERSION DID NOT TEST. Whiffs move outs, and
    outs are the half of this model measured to carry no edge. Runs come
    from what happens when the ball is put in play, so if an arsenal matters
    for a TEAM TOTAL it should matter here.

    THE DENOMINATOR IS THIS SAME BATTER AGAINST A LEAGUE-AVERAGE ARSENAL,
    not his overall rate. That distinction is the whole construction: with
    his own rate as the reference the multiplier came out at mean 1.0354
    rather than 1.0, which is a 3.5% level shift on every matchup — the test
    would then measure "more runs" rather than "this mix against this
    hitter". Against a neutral mix the numerator and denominator are the
    same sum, so it returns exactly 1.0 and only the DIFFERENCE in mix
    survives.
    """
    ars = data["pitchers"].get(pitcher)
    if not ars:
        return None
    lg_usage = lg_usage or league_usage(lg_by_pitch)
    bat = data["batters"].get(batter) or {}

    def cell(pt):
        """This batter's wOBA on pitch type `pt`, shrunk toward his own."""
        lgp = lg_by_pitch.get(pt)
        if not lgp or not lgp.get("woba"):
            return None
        base = b_overall if b_overall else lgp["woba"]
        w = _f(bat.get(pt, {}), "woba")
        if w is None:
            return base
        pa = _f(bat.get(pt, {}), "pa") or 0.0
        k = pa / (pa + CELL_SHRINK_PA)
        return k * w + (1.0 - k) * base

    here = ref = cov = 0.0
    for pt, row in ars.items():
        usage = (_f(row, "pitch_usage") or 0.0) / 100.0
        c = cell(pt)
        if not usage or c is None:
            continue
        here += usage * c
        cov += usage
    if cov < MIN_COVERAGE:
        return None
    # Same batter, league-average mix. Restricted to the families the
    # pitcher actually throws would bias it; this is the true neutral.
    rcov = 0.0
    for pt, u in lg_usage.items():
        c = cell(pt)
        if c is None:
            continue
        ref += u * c
        rcov += u
    if rcov <= 0 or ref <= 0:
        return None
    return max(0.70, min(1.35, (here / cov) / (ref / rcov)))


def _reference(ars: dict, lg_by_pitch: dict, lg_overall: float,
               log5) -> float | None:
    """What the mixture says for a LEAGUE-AVERAGE batter against this mix.

    The denominator that makes the result a matchup effect rather than a
    restatement of the pitcher's quality — his own level already lives in
    his aggregate rate, and multiplying it back in would count him twice.
    """
    num = cov = 0.0
    for pt, row in ars.items():
        usage = (_f(row, "pitch_usage") or 0.0) / 100.0
        lgp = lg_by_pitch.get(pt)
        kp = _f(row, "k_percent")
        if not usage or not lgp or kp is None:
            continue
        num += usage * log5(lg_overall, kp / 100.0, lgp["k_pct"])
        cov += usage
    return (num / cov) if cov >= MIN_COVERAGE else None


if __name__ == "__main__":
    from src.context import sim
    data = load()
    if not data:
        print("no arsenal cache")
        sys.exit(1)
    lgp = league_by_pitch(data)
    print(f"{len(data['pitchers'])} pitchers, {len(data['batters'])} batters")
    print(f"\n  {'pitch':<6}{'league K%':>11}{'wOBA':>8}{'pitches':>10}")
    for pt, r in sorted(lgp.items(), key=lambda x: -x[1]["pitches"]):
        print(f"  {pt:<6}{r['k_pct'] * 100:>11.1f}"
              f"{(r['woba'] or 0):>8.3f}{r['pitches']:>10.0f}")
    lg = sim.league()
    # A worked example against the aggregate model, to show the spread.
    print(f"\n  league aggregate K% (rotation starters): {lg['k_pct']:.4f}")
