"""How fast does each rate become trustworthy? Counted on THIS league.

`rates.STABILISE` sets the plate appearances at which a player's own rate is
worth half its weight against the league:

    k_pct 70, bb_pct 170, hr_pct 350, babip 500

Those are IMPORTED. `rates.py` says so outright — "Refitting them against
this database is a real piece of work and is deliberately not pretended
at." Every other imported constant in this project has been wrong when
finally counted, and unlike the rest these four touch EVERY pitcher and
batter input in the model.

WHY THEY MATTER MORE THAN THE STATE MACHINE. A leverage screen over the
whole parameter set puts lineup quality at ~0.47 runs of separation between
clubs, bullpen quality ~0.25, starter quality ~0.19 — and every advancement
constant under 0.04. Separation lives almost entirely in the RATES. These
four numbers decide how much of each player's real spread survives
shrinkage into the prediction, so they scale the only thing generating
separation at all. Set too high, the model shrinks real differences away
and predicts the league average for everybody.

THE METHOD IS A MEASUREMENT, NOT A FIT. Split each player's season into odd
and even GAMES, correlate the two halves, and Spearman-Brown the result up
to full-season reliability. For the shrinkage form actually used,

    w = n / (n + k)

reliability at n plate appearances IS w, so

    k = n * (1 - r) / r

with `n` the harmonic-mean sample per half. No loss function is involved and
none may be: handing these to a search against the settlement value is
exactly how a measured quantity goes back to absorbing other defects.

ODD/EVEN GAMES, not first-half/second-half. A chronological split confounds
true talent with in-season change — a pitcher who adds a pitch in June
looks unreliable when he is merely different. Odd/even interleaves the two
halves in time, so anything seasonal affects both equally.

    venv/bin/python -m src.context.stabilise
"""
from __future__ import annotations

import statistics as st
from collections import defaultdict

from src.context import store

#: Minimum plate appearances IN EACH HALF for a player to be counted. Too
#: low and the correlation is dominated by players whose halves are both
#: noise; too high and only regulars survive, which biases toward the
#: stable end of the population.
MIN_PER_HALF = 60

_BAT = """
select b.player_name name, b.game_id gid, g.date date,
       b.ab, b.bb, b.h, b.so, b.hr
from bets.mlb_batting b join bets.games g on g.game_id = b.game_id
where g.sport = 'mlb' and g.status = 'Final'
order by g.date, b.game_id
"""

_PIT = """
select p.player_name name, p.game_id gid, g.date date,
       p.outs_recorded o, p.bb, p.h, p.k, p.hr
from bets.mlb_pitching p join bets.games g on g.game_id = p.game_id
where g.sport = 'mlb' and g.status = 'Final' and p.is_starter = 1
order by g.date, p.game_id
"""


def _rows(q):
    with store.connect() as c:
        return [dict(r) for r in c.execute(q)]


def _halves(rows, key_fn):
    """{name: [half0, half1]} where each half accumulates counting stats.

    Games are assigned by their ORDER within the player's own season, so
    each player contributes alternate appearances to the two halves.
    """
    by = defaultdict(list)
    for r in rows:
        by[r["name"]].append(r)
    out = {}
    for name, games in by.items():
        halves = [defaultdict(float), defaultdict(float)]
        for i, g in enumerate(games):
            acc = halves[i % 2]
            for k, v in key_fn(g).items():
                acc[k] += v
        out[name] = halves
    return out


def _corr(pairs):
    if len(pairs) < 10:
        return None
    xs = [a for a, _ in pairs]
    ys = [b for _, b in pairs]
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / \
        (len(xs) * sx * sy)


def measure(rows, stats, denom_key) -> dict:
    """Split-half reliability and the implied stabilisation point."""
    def counts(g):
        # A source may be a COLUMN NAME or a callable. BABIP's numerator is
        # (H - HR) and no column holds it, which is how the batter path came
        # to be measured with home runs in the numerator and out of the
        # denominator — a rate that is not BABIP by any definition.
        d = {k: (src(g) if callable(src) else (g.get(src) or 0))
             for k, src in stats.items()}
        d["_den"] = denom_key(g)
        return d

    halves = _halves(rows, counts)
    out = {}
    for stat in stats:
        pairs, ns = [], []
        for name, (a, b) in halves.items():
            if a["_den"] < MIN_PER_HALF or b["_den"] < MIN_PER_HALF:
                continue
            pairs.append((a[stat] / a["_den"], b[stat] / b["_den"]))
            ns.append(2.0 / (1.0 / a["_den"] + 1.0 / b["_den"]))
        r = _corr(pairs)
        if r is None or r <= 0:
            out[stat] = {"n_players": len(pairs), "r_half": r, "k": None}
            continue
        full = 2 * r / (1 + r)          # Spearman-Brown to a full half-pair
        n = st.mean(ns)
        out[stat] = {
            "n_players": len(pairs), "r_half": r, "r_full": full,
            "n_per_half": n,
            # reliability at n IS the shrinkage weight n/(n+k)
            "k": n * (1 - full) / full if 0 < full < 1 else None,
        }
    return out


def report() -> None:
    from src.context.sources.rates import STABILISE as SHIPPED

    print("\nBATTERS (denominator: plate appearances)")
    bat = measure(
        _rows(_BAT),
        {"k_pct": "so", "bb_pct": "bb", "hr_pct": "hr"},
        lambda g: (g.get("ab") or 0) + (g.get("bb") or 0))
    # BABIP needs its own denominator: balls in play. And its own
    # NUMERATOR — hits on balls in play, which excludes the home run.
    bip = measure(
        _rows(_BAT),
        {"babip": lambda g: max((g.get("h") or 0) - (g.get("hr") or 0), 0)},
        lambda g: max((g.get("ab") or 0) - (g.get("so") or 0)
                      - (g.get("hr") or 0), 0))
    bat.update(bip)
    _table(bat, SHIPPED, who="bat")

    print("\nSTARTING PITCHERS (denominator: batters faced, approximated)")
    pit_rows = _rows(_PIT)
    pit = measure(
        pit_rows,
        {"k_pct": "k", "bb_pct": "bb", "hr_pct": "hr"},
        lambda g: (g.get("o") or 0) + (g.get("h") or 0) + (g.get("bb") or 0))
    # PITCHER BABIP WAS SIMPLY MISSING. Nothing said why, and the shipped
    # 500 is therefore the legacy all-players import — the same class of
    # unmeasured number that left pitcher k_pct at 57 when it should have
    # been 132. The denominator goes through `balls_in_play` because a
    # boxscore's `bf - k - bb - hr` counts OUTS and outs are not balls in
    # play; using the raw figure would understate k by the same 3.3%.
    from src.context.sources.rates import balls_in_play
    pit.update(measure(
        pit_rows,
        {"babip": lambda g: max((g.get("h") or 0) - (g.get("hr") or 0), 0)},
        lambda g: balls_in_play(
            (g.get("o") or 0) + (g.get("h") or 0) + (g.get("bb") or 0),
            g.get("k"), g.get("bb"), g.get("hr"))))
    _table(pit, SHIPPED, who="pit")

    print("\n  k is the plate appearances at which a player's own rate is")
    print("  worth half its weight against the league. LOWER means the")
    print("  signal separates faster, so more of a real difference survives")
    print("  into the prediction.")
    print("\n  A shipped value ABOVE the measured one is over-shrinking:")
    print("  real spread is being averaged away, and separation is the only")
    print("  thing the model has.")


def _table(res, shipped, who="bat"):
    """`who` selects the row of `STABILISE_MEASURED` that actually ships.

    The comparison column used to read the IMPORTED `STABILISE` dict for
    both populations, which is not what runs — `USE_MEASURED_STABILISE` is
    True. Every pitcher row therefore compared against a number nothing
    uses, and all three read as UNDER-shrunk when two of them are over-.
    """
    from src.context.sources.rates import STABILISE_MEASURED, \
        USE_MEASURED_STABILISE
    live = (STABILISE_MEASURED.get(who, {}) if USE_MEASURED_STABILISE
            else shipped)
    print(f"  {'stat':<9}{'players':>9}{'PA/half':>9}{'r half':>9}"
          f"{'r full':>9}{'k measured':>12}{'IN USE':>9}{'imported':>10}")
    for stat, d in res.items():
        if d.get("k") is None:
            print(f"  {stat:<9}{d['n_players']:>9}"
                  f"{'':>9}{str(d.get('r_half')):>9}   (unresolved)")
            continue
        print(f"  {stat:<9}{d['n_players']:>9}{d['n_per_half']:>9.0f}"
              f"{d['r_half']:>9.3f}{d['r_full']:>9.3f}"
              f"{d['k']:>12.0f}{live.get(stat, 0):>9}"
              f"{shipped.get(stat, 0):>10}")


if __name__ == "__main__":
    report()
