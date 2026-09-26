"""TEMPERATURE INTO THE STRIKEOUT CHANNEL — counted, not imported.

Temperature's mirror on the other side of the ball. Warm air is less
dense and the ball carries, which is the home run channel `temp_hr.py`
already counted; the same air also appears to move STRIKEOUTS, in the
opposite direction, and nothing in the engine reads it.

METHOD IS `temp_hr.py`'S, LINE FOR LINE, AND DELIBERATELY SO:

  * WITHIN-VENUE (indirect standardisation). A pooled count confounds
    temperature with park — hot games concentrate in particular
    buildings and the engine applies park separately — and the pooled
    version of this exact table was the first thing that looked real:
    it read 0.864 at Coors, which is mostly altitude, not air. Each
    game's K is compared against ITS OWN venue's baseline, so the
    identification is the same park being hot in June and cold in April.

  * CLIMATE-CENTRED, not training-centred. The baseline K rates already
    contain an average season's air, so a table centred on the SPRING
    distribution would re-add the summer difference as a level shift.
    The reference is the mean raw multiplier over the PRIOR seasons'
    full-year temperature distribution — exogenous, no scored outcome.

  * PRE-JULY TRAINING ROWS (rule 6). `HOLDOUT` is imported, never
    retyped. The summer folds score the relation out of sample.

  * OPEN AIR ONLY, with closed roofs kept back as the control: a dome
    is conditioned air, so its cell should read ~1.0 whatever the
    outdoor reading says. If it does not, the feed's temperature does
    not mean what it claims and nothing here is trustworthy.

  * THE BINNING IS `TEMP_HR_EDGES`, REUSED, NOT SEARCHED. Picking edges
    that maximise a K effect is fitting a shape to noise; borrowing the
    pre-registered home-run split costs a little power and buys the one
    thing that matters, which is that nobody chose these boundaries
    after seeing this outcome.

WHAT IT IS NOT. This does not settle whether temperature adds anything
beyond MONTH, which is already known to the model through the seasonal
rate baselines. That is a real question, it is deliberately left open
here, and `--vs-month` prints the within-month version so the answer is
one command away rather than an argument.

    venv/bin/python -m scratchpad.temp_k
    venv/bin/python -m scratchpad.temp_k --vs-month
"""
from __future__ import annotations

import math
import statistics as st
import sys
from collections import defaultdict
from itertools import combinations

from src.context import sim, store
from src.context.holdout import HOLDOUT

#: BORROWED FROM THE HOME RUN TABLE ON PURPOSE — see the docstring.
EDGES = sim.TEMP_HR_EDGES
LABELS = ("<55", "55-64", "65-74", "75-84", "85+")

#: The climate reference window: prior FULL seasons, so an average
#: season's air is what the baseline rates already carry.
CLIMATE_BEFORE = "2026-01-01"


def tbin(t: float) -> int:
    return sum(t >= e for e in EDGES)


#: EVERY CHANNEL THE ENGINE HAS, not just the one that prompted this.
#: `resolve` builds exactly four multipliers — m_k, m_bb, m_hr, m_bip —
#: and air that moves one has no reason to leave the others alone. HR is
#: already shipped (`TEMP_HR_MULT`) and is recounted here as a CONTROL:
#: this pipeline should reproduce its known direction, and if it does not,
#: the pipeline is wrong rather than the finding new.
#:
#: Denominators differ and it matters (rule 10). K, BB and HBP are
#: per PLATE APPEARANCE. Hits-on-balls-in-play is per BALL IN PLAY,
#: because a hot day that removes strikeouts mechanically adds balls in
#: play, and scoring hits per PA would count that twice.
CHANNELS = (
    ("k", lambda r: r["k"], "pa"),
    ("bb", lambda r: r["bb"], "pa"),
    ("hr", lambda r: r["hr"], "pa"),
    ("hbp", lambda r: r["hbp"], "pa"),
    ("h_on_bip", lambda r: r["h"] - r["hr"], "bip"),
)


def game_rows(before: str = HOLDOUT, roof: int = 0, channel: str = "k"):
    """(game_id, season, numerator, denominator, temp_f, venue_id) per game.

    Both clubs' pitching pooled: the air is the game's, not a side's,
    exactly as `hr_air` is set on both sides in `simulate_game`.

    BALLS IN PLAY are derived, not fetched — PA less the three true
    outcomes and the hit batsmen. It is the same identity the engine
    works in, so a channel counted here lands on the rate the engine
    would multiply.
    """
    q = """
        select g.game_id, substr(g.date,1,4) season, w.temp_f, w.venue_id,
               sum(p.k) k, sum(p.bb) bb, sum(p.hr) hr, sum(p.h) h,
               sum(coalesce(p.hbp,0)) hbp, sum(s.batters) pa
        from mlb_weather w
        join bets.games g on g.game_id = w.game_id
        join mlb_stints s on s.game_id = w.game_id
        join bets.mlb_pitching p
          on p.game_id = s.game_id and p.player_name = s.player_name
        where w.temp_f is not null and w.venue_id is not null
          and w.roof_closed = ? and g.date < ?
        group by g.game_id
        having pa > 0
    """
    num = dict((c[0], c[1]) for c in CHANNELS)[channel]
    den = dict((c[0], c[2]) for c in CHANNELS)[channel]
    out = []
    with store.connect() as c:
        for r in c.execute(q, (roof, before)):
            d = (r["pa"] if den == "pa"
                 else r["pa"] - r["k"] - r["bb"] - r["hr"] - r["hbp"])
            if d > 0:
                out.append((r["game_id"], r["season"], num(r), d,
                            r["temp_f"], r["venue_id"]))
    return out


def within_venue(rows) -> tuple[list[float], list[int], dict]:
    """(ratio per bin, n per bin, per-season ratios) — observed over
    venue-expected. The venue baseline is built on the SAME rows, which
    is what makes it a within-venue contrast rather than a park count."""
    vrate = defaultdict(lambda: [0, 0])
    for _, _, k, pa, _, v in rows:
        vrate[v][0] += k
        vrate[v][1] += pa
    seasons = sorted({r[1] for r in rows})
    mult, ns, per_season = [], [], {s: [] for s in seasons}
    for b in range(len(LABELS)):
        sub = [r for r in rows if tbin(r[4]) == b]
        obs = sum(r[2] for r in sub)
        exp = sum(vrate[r[5]][0] / vrate[r[5]][1] * r[3] for r in sub)
        mult.append(obs / exp if exp else 1.0)
        ns.append(len(sub))
        for s in seasons:
            ss = [r for r in sub if r[1] == s]
            o = sum(r[2] for r in ss)
            e = sum(vrate[r[5]][0] / vrate[r[5]][1] * r[3] for r in ss)
            per_season[s].append(o / e if e else None)
    return mult, ns, per_season


def climate_reference(mult: list[float]) -> tuple[float, int]:
    """Mean raw multiplier over the prior seasons' full-year temperatures."""
    with store.connect() as c:
        temps = [r["temp_f"] for r in c.execute(
            "select temp_f from mlb_weather where temp_f is not null "
            "and roof_closed = 0 and date < ?", (CLIMATE_BEFORE,))]
    return sum(mult[tbin(t)] for t in temps) / len(temps), len(temps)


def report() -> tuple:
    rows = game_rows()
    pa = sum(r[3] for r in rows)
    print(f"TEMPERATURE -> STRIKEOUTS, counted within venue")
    print(f"  {len(rows):,} open-air games before {HOLDOUT}, "
          f"{pa:,} plate appearances")

    mult, ns, per_season = within_venue(rows)
    seasons = sorted(per_season)
    print(f"\n  {'bin':<8}{'games':>8}{'ratio':>9}{'se':>8}   "
          + "".join(f"{s:>8}" for s in seasons))
    for b, lab in enumerate(LABELS):
        sub = [r for r in rows if tbin(r[4]) == b]
        obs = sum(r[2] for r in sub)
        se = mult[b] / math.sqrt(obs) if obs else float("nan")
        cols = "".join(f"{c:>8.3f}" if c is not None else f"{'-':>8}"
                       for c in (per_season[s][b] for s in seasons))
        print(f"  {lab:<8}{ns[b]:>8,}{mult[b]:>9.3f}{se:>8.3f}   {cols}")

    # DOES IT REPEAT? Same gate the HR table passes — a shape that does
    # not hold season to season is a shape fitted to one of them.
    cors = []
    for a, b in combinations(seasons, 2):
        xs = [(x, y) for x, y in zip(per_season[a], per_season[b])
              if x is not None and y is not None]
        if len(xs) > 2:
            cors.append(st.correlation([x for x, _ in xs],
                                       [y for _, y in xs]))
    gate = st.mean(cors) if cors else float("nan")
    print(f"\n  era gate (within-venue): {gate:.3f} over {len(cors)} pairs")

    # THE DOME CONTROL. Conditioned air is league air whatever the
    # outdoor thermometer says, so these cells should read ~1.0. A
    # gradient here would mean the reading is a proxy for something
    # else and the open-air table is not measuring air.
    dome = game_rows(roof=1)
    if dome:
        dmult, dns, _ = within_venue(dome)
        print(f"\n  DOME CONTROL ({len(dome):,} closed-roof games) — "
              f"should be flat at ~1.0")
        print("  " + "".join(f"{lab:>9}" for lab in LABELS))
        print("  " + "".join(f"{m:>9.3f}" for m in dmult))

    ref, n_clim = climate_reference(mult)
    out = tuple(round(m / ref, 4) for m in mult)
    print(f"\n  climate reference (prior full seasons, {n_clim:,} games): "
          f"mean raw mult {ref:.4f}")
    print("\n  CONSTANTS TO SHIP (within-venue, climate-centred):")
    print(f"  TEMP_K_EDGES = {EDGES}")
    print(f"  TEMP_K_MULT = {out}")
    return out, gate


def vs_month():
    """IS TEMPERATURE REDUNDANT WITH MONTH? The open question, printed.

    The engine already knows the month implicitly, through rate
    baselines built to the cut date. If the within-VENUE-and-MONTH
    contrast collapses to flat, temperature is a worse-measured proxy
    for the calendar and should not ship.
    """
    rows = game_rows()
    key = defaultdict(lambda: [0, 0])
    with store.connect() as c:
        mon = {r["game_id"]: r["date"][5:7] for r in c.execute(
            "select game_id, date from bets.games")}
    rows = [r + (mon.get(r[0], "??"),) for r in rows]
    for _, _, k, pa, _, v, m in rows:
        key[(v, m)][0] += k
        key[(v, m)][1] += pa
    print("\nWITHIN VENUE *AND* MONTH — temperature net of the calendar")
    print(f"  {'bin':<8}{'games':>8}{'ratio':>9}{'se':>8}")
    for b, lab in enumerate(LABELS):
        sub = [r for r in rows if tbin(r[4]) == b]
        obs = sum(r[2] for r in sub)
        exp = sum(key[(r[5], r[6])][0] / key[(r[5], r[6])][1] * r[3]
                  for r in sub if key[(r[5], r[6])][1])
        if not exp or not obs:
            continue
        ratio = obs / exp
        print(f"  {lab:<8}{len(sub):>8,}{ratio:>9.3f}"
              f"{ratio / math.sqrt(obs):>8.3f}")
    print("\n  A flat column here means the open table is measuring the\n"
          "  calendar, not the air, and TEMP_K_MULT should not ship.")


def all_channels():
    """Every channel the engine multiplies, counted the same way.

    THE POINT IS THE WHOLE ROW, not the cell anyone went looking for.
    A temperature effect that appears only on strikeouts and nowhere
    else is more likely a quirk of one denominator than a property of
    air; one that shows up coherently across channels is the physics.
    HR is the control — its shipped table was counted independently, so
    this pipeline reproducing its direction is what says the pipeline
    works.
    """
    print("\nEVERY CHANNEL, within venue, climate-centred, pre-July rows")
    print(f"  {'channel':<10}{'den':>5}" + "".join(f"{l:>9}" for l in LABELS)
          + f"{'range':>9}{'era':>7}")
    out = {}
    for name, _, den in CHANNELS:
        rows = game_rows(channel=name)
        mult, ns, per_season = within_venue(rows)
        ref, _ = climate_reference(mult)
        cent = [m / ref for m in mult]
        cors = []
        seasons = sorted(per_season)
        for a, b in combinations(seasons, 2):
            xs = [(x, y) for x, y in zip(per_season[a], per_season[b])
                  if x is not None and y is not None]
            if len(xs) > 2:
                cors.append(st.correlation([x for x, _ in xs],
                                           [y for _, y in xs]))
        era = st.mean(cors) if cors else float("nan")
        rng = max(cent) - min(cent)
        print(f"  {name:<10}{den:>5}"
              + "".join(f"{c:>9.4f}" for c in cent)
              + f"{rng:>9.3f}{era:>7.2f}")
        out[name] = tuple(round(c, 4) for c in cent)
    print("\n  `range` is the span from the coldest cell to the hottest —"
          "\n  the size of the whole effect, not a typical game's."
          "\n  `era` is the season-to-season shape correlation; a channel"
          "\n  that does not repeat is a shape fitted to one season.")
    return out


if __name__ == "__main__":
    if "--all" in sys.argv:
        all_channels()
    else:
        report()
    if "--vs-month" in sys.argv:
        vs_month()
