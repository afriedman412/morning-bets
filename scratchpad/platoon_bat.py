"""THE BATTER side of handedness — the channel that was never screened.

    venv/bin/python -m scratchpad.platoon_bat [workers]

WHY THIS EXISTS. `platoon_split.py` asked whether THIS PITCHER has a split
and found +1.2 sigma, because 42 of 91 starters have REVERSED splits and the
population very largely cancels. That is a real result and it stands. It is
also only one of the two channels, and the smaller one.

The other channel is the LINEUP's: does the nine he faces tonight strike out
more against a left-hander than their season line says. Toronto's card
against Noah Cameron read 21.69% vs LHP against the 18.69% overall rate the
model fed the simulator — three points, sixteen percent relative, and enough
to move his expected strikeouts from 4.19 to about 4.8. That is the whole
remaining disagreement on the biggest gap of the day.

THE OLD NULL DOES NOT SETTLE IT. `USE_HANDEDNESS` shipped and was killed,
but it used DERIVED splits attenuated halfway back to the overall rate, on
the two-engine setup, relievers included. Its own docstring names exact
splits as the discriminating test. We now have per-plate-appearance
handedness over 9,962 games.

THE QUANTITY. Per start, the opposing lineup's K rate recomputed from each
batter's rate against THIS STARTER'S HAND, minus the same lineup's rate from
their overall numbers — the amount a handedness-aware model would move the
start. Correlated against the residual the model already leaves.

SWITCH HITTERS FALL OUT FOR FREE because the split is keyed on the
PITCHER'S hand, not the batter's side. A switch hitter's "vs LHP" cell is
his right-handed record, which is what he will actually do.

TWO ARMS, and the second is the deployable one:

  in-season   splits counted on 2026, each start's own plate appearances
              SUBTRACTED before it is scored. Leave-one-out from the start:
              the pitcher-side screen read +4.8 sigma before the start was
              removed from its own predictor and +1.2 after.
  prior       splits counted on 2023-2025 only. No leak by construction,
              and it is what a model would actually hold in March.

WEIGHTED TWO WAYS. `pa` weights by the plate appearances he actually took,
which is what happened; `flat` weights the nine equally, which is closer to
what the simulator does when it walks a lineup. They disagree when a start
runs long, and the Cameron case turned on exactly that distinction.
"""
from __future__ import annotations

import json
import pathlib
import statistics as st
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

from src import db
from src.context import sim
from src.context.sources import pbp, rates as rate_src

#: A strikeout for these purposes. `strikeout_double_play` is a strikeout
#: with a runner thrown out and the boxscore counts it as one.
_K = ("strikeout", "strikeout_double_play")
_HIT = ("single", "double", "triple")
_BIP_OUT = ("field_out", "force_out", "fielders_choice_out",
            "grounded_into_double_play", "double_play", "triple_play",
            "field_error")

#: (numerator, denominator) into a counts cell [pa, k, hits, bip, hr], the
#: shrink constant to use, and the residual column it is scored against.
#: THREE CHANNELS, because testing handedness on strikeouts alone would be
#: the upstream-proxy mistake this project keeps making: what settles is
#: runs, and the textbook platoon effect is a POWER effect. A left-hander
#: facing a right-handed card gives up home runs, not just fewer whiffs.
CHANNELS = {
    "k":     (1, 0, "k_pct", "k"),
    "babip": (2, 3, "babip", "h"),
    "hr":    (4, 0, "hr_pct", "hr"),
}


def corr(xs, ys):
    n = len(xs)
    if n < 30:
        return 0.0, 0.0
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if not sx or not sy:
        return 0.0, 0.0
    r = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (n * sx * sy)
    return r, r * (n - 2) ** 0.5 / max((1 - r * r) ** 0.5, 1e-9)


def scan(short: str):
    """One game. Module level so the pool can pickle it.

    Returns (splits, starts). `splits` counts EVERY pitcher's plate
    appearances — a batter's record against left-handers is built from all
    of them, not only from starters. `starts` carries just the opening
    pitcher on each side, which is the row that gets scored.
    """
    try:
        d = pbp.fetch(short)
    except Exception:
        return None
    if not d:
        return None
    splits = defaultdict(lambda: [0, 0, 0, 0, 0])    # (bid, phand) -> counts
    who = {}                                          # bid -> full name
    game = {}                                         # bid -> hand -> counts
    first = {}                                        # side -> pitcher id
    starts = {}                                       # side -> {...}
    for p in (d.get("allPlays") or []):
        ab, mu = p.get("about") or {}, p.get("matchup") or {}
        res = p.get("result") or {}
        pit = mu.get("pitcher") or {}
        bat = mu.get("batter") or {}
        pid, bid = pit.get("id"), bat.get("id")
        ph = ((mu.get("pitchHand") or {}).get("code") or "")
        if not pid or not bid or ph not in ("L", "R"):
            continue
        ev = res.get("eventType") or ""
        who[bid] = bat.get("fullName")
        side = "home" if ab.get("isTopInning") else "away"
        first.setdefault(side, pid)
        cells = [splits[(bid, ph)]]
        if first[side] == pid:
            s = starts.setdefault(side, {"pid": pid, "hand": ph,
                                         "name": pit.get("fullName"),
                                         "faced": {}})
            cells.append(s["faced"].setdefault(bid, [0, 0, 0, 0, 0]))
        # THE WHOLE GAME, per batter per hand. Subtracting only the
        # starter's plate appearances leaves the batter's innings against
        # the RELIEVERS inside his own split, and a night when everything
        # fell in raises both the starter's hits and the lineup's counted
        # rate against that hand. That is a leak with the sign of the
        # result, so the strict arm has to remove the game entire.
        g = game.setdefault(bid, {})
        cells.append(g.setdefault(ph, [0, 0, 0, 0, 0]))
        for cell in cells:
            cell[0] += 1
            if ev in _K:
                cell[1] += 1
            if ev in _HIT:
                cell[2] += 1
                cell[3] += 1
            elif ev in _BIP_OUT:
                cell[3] += 1
            elif ev == "home_run":
                cell[4] += 1
    # Attach only the batters this starter actually faced — the rest of the
    # card is dead weight in the cache.
    for s in starts.values():
        s["game"] = {b: game[b] for b in s["faced"] if b in game}
    return ({k: v for k, v in splits.items()}, starts, who)


def collect(workers: int = 8):
    with db.connect() as c:
        games = {r["game_id"]: (r["home_team_abbr"], r["away_team_abbr"],
                                r["date"])
                 for r in c.execute("select game_id, home_team_abbr,"
                                    " away_team_abbr, date from games"
                                    " where sport = 'mlb'")}
    todo = [(g, games[g][2]) for g in games if pbp.have(g.split("-")[-1])]
    todo.sort()
    print(f"  scanning {len(todo):,} games on {workers} workers ...",
          flush=True)
    #: season -> (bid, hand) -> counts, kept apart so the prior arm can be
    #: built from years the scored starts are not in.
    by_year = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0, 0]))
    starts = {}
    names = {}                                        # batter id -> name
    with ProcessPoolExecutor(max_workers=workers) as ex:
        out = ex.map(scan, [g.split("-")[-1] for g, _ in todo], chunksize=32)
        for (full, date), got in zip(todo, out):
            if not got:
                continue
            splits, sides, who = got
            names.update(who)
            yr = int(date[:4])
            tgt = by_year[yr]
            for k, v in splits.items():
                cell = tgt[k]
                for i in range(len(v)):
                    cell[i] += v[i]
            home_ab, away_ab, _ = games[full]
            for side, s in sides.items():
                s["date"] = date
                s["team"] = (home_ab if side == "away" else away_ab)
                starts[(full, s["name"])] = s
    return by_year, starts, names


CACHE = pathlib.Path("scratchpad/bat_splits.json")


def load(workers: int = 8, with_names: bool = False):
    """`collect`, cached. Batter ids are normalised to STRINGS on both
    paths — a JSON round trip stringifies dict keys, and a cached run that
    silently matched nothing would look exactly like a null result."""
    if CACHE.exists():
        raw = json.loads(CACHE.read_text())
        by_year = {int(y): {tuple(k.split("|")): v for k, v in d.items()}
                   for y, d in raw["by_year"].items()}
        starts = {tuple(k.split("|")): s for k, s in raw["starts"].items()}
        names = raw.get("names") or {}
        return (by_year, starts, names) if with_names else (by_year, starts)
    by_year, starts, names = collect(workers)
    by_year = {y: {(str(b), h): v for (b, h), v in d.items()}
               for y, d in by_year.items()}
    names = {str(b): n for b, n in names.items() if n}
    for s in starts.values():
        # BOTH maps, or the strict arm looks up string ids in an int-keyed
        # dict, silently subtracts nothing, and reports the leak it exists
        # to remove as a +6 sigma discovery.
        s["faced"] = {str(b): v for b, v in s["faced"].items()}
        s["game"] = {str(b): v for b, v in (s.get("game") or {}).items()}
    CACHE.write_text(json.dumps({
        "by_year": {str(y): {f"{b}|{h}": v for (b, h), v in d.items()}
                    for y, d in by_year.items()},
        "starts": {f"{g}|{n}": s for (g, n), s in starts.items()},
        "names": names,
    }))
    return (by_year, starts, names) if with_names else (by_year, starts)


def _rate(cell, overall, num, den, k):
    """His rate against this hand, pulled toward his own overall rate.

    Toward HIS OVERALL, not toward the league: the question is only how much
    the hand moves him, so the league level is already in the base.
    """
    if not cell or cell[den] <= 0:
        return overall
    w = cell[den] / (cell[den] + k)
    return w * (cell[num] / cell[den]) + (1 - w) * overall


def arm(rows, starts, split, loo: bool, channel: str, kconst: float,
        min_pa: int, against: str | None = None):
    """Returns (xs_pa, xs_flat, ys, mags) for one construction of the split.

    `against` scores the channel's adjustment against a DIFFERENT residual
    column than its own — the strikeout shift against earned runs, say. The
    x side is untouched; only the y column moves.
    """
    num, den, _stat, col = CHANNELS[channel]
    ycol = against or col
    xs_pa, xs_flat, ys, mags, keys = [], [], [], [], []
    #: [subtractions that landed, lookups that missed]. A leave-one-out that
    #: silently removes nothing is indistinguishable from a discovery.
    hit = [0, 0]
    for r in rows:
        s = starts.get((r["game_id"], r["player"]))
        if not s or r.get(f"m_{col}") is None or r.get(f"m_{ycol}") is None:
            continue
        hand, faced = s["hand"], s["faced"]
        gm = s.get("game") or {}
        num_pa = den_pa = 0.0
        flat_x, flat_n = 0.0, 0
        for bid, here in faced.items():
            cells = {}
            tot_d = tot_n = 0
            for h in ("L", "R"):
                c = list(split.get((bid, h), (0, 0, 0, 0, 0)))
                if loo == "game":
                    # Every plate appearance he took tonight, either hand.
                    out = (gm.get(bid) or {}).get(h)
                    if out:
                        hit[0] += 1
                        for i in range(5):
                            c[i] -= out[i]
                    else:
                        hit[1] += 1
                elif loo and h == hand:
                    for i in range(5):
                        c[i] -= here[i]
                if min(c) < 0:
                    c = [0, 0, 0, 0, 0]
                cells[h] = c
                tot_d += c[den]
                tot_n += c[num]
            if cells["L"][0] + cells["R"][0] < min_pa or not tot_d:
                continue
            overall = tot_n / tot_d
            vs = _rate(cells[hand], overall, num, den, kconst)
            # Weight by the DENOMINATOR he actually took here — plate
            # appearances for k and hr, balls in play for babip. Weighting
            # a babip shift by plate appearances would credit a hitter who
            # struck out three times with three balls in play.
            w = here[den]
            num_pa += w * (vs - overall)
            den_pa += w
            flat_x += vs - overall
            flat_n += 1
        if den_pa < 8 or flat_n < 6:
            continue
        xs_pa.append(num_pa / den_pa)
        xs_flat.append(flat_x / flat_n)
        ys.append(r[f"a_{ycol}"] - r[f"m_{ycol}"])
        mags.append(den_pa)
        keys.append((r["game_id"], r["player"]))
    if loo == "game" and hit[0] < hit[1]:
        raise SystemExit(f"strict leave-one-out matched {hit[0]:,} and MISSED"
                         f" {hit[1]:,} — the id keys do not line up, and the"
                         f" arm is measuring its own outcome")
    return xs_pa, xs_flat, ys, mags, keys


def main(argv):
    workers = int(argv[0]) if argv else 8
    by_year, starts = load(workers)
    rows = [r for r in json.load(open("scratchpad/ceiling_rows.json"))
            if not r.get("_team_row")]
    kconst = rate_src.STABILISE_MEASURED["bat"]["k_pct"]
    lg_babip = sim.league()["babip"]
    print(f"  {len(starts):,} starts with a faced-nine, {len(rows):,} scored,"
          f" shrink k={kconst}, league babip {lg_babip:.4f}\n")

    def merge(years):
        out = defaultdict(lambda: [0, 0, 0, 0, 0])
        for y in years:
            for k, v in by_year.get(y, {}).items():
                c = out[k]
                for i in range(5):
                    c[i] += v[i]
        return out

    in_season = merge([2026])
    prior = merge([2023, 2024, 2025])

    # How big is the effect BEFORE anything is correlated? If the lineups
    # barely move, nothing downstream can matter however real the split is.
    spread = []
    for (bid, h), c in in_season.items():
        if h != "L":
            continue
        rr = in_season.get((bid, "R"))
        if not rr or min(c[0], rr[0]) < 120:
            continue
        spread.append(c[1] / c[0] - rr[1] / rr[0])
    if spread:
        print(f"  batter K% split (vs L minus vs R), {len(spread)} hitters"
              f" with 120+ each:")
        print(f"    mean {st.mean(spread):+.4f}  sd {st.pstdev(spread):.4f}"
              f"  range {min(spread):+.3f} to {max(spread):+.3f}")
        print(f"    reversed (higher vs R): "
              f"{sum(1 for x in spread if x < 0)} of {len(spread)}")

    # The `raw` arm shrinks nothing. It cannot be deployed — a 40-plate-
    # appearance split is mostly noise — but it bounds how much of the
    # movement the shrink is absorbing, which is the first thing to rule out
    # if the screen's spread looks too small against a known case.
    ARMS = (("in-season", in_season, True, True),
            ("strict-loo", in_season, "game", True),
            ("raw", in_season, True, False),
            ("prior", prior, False, True))
    for ch, (num, den, stat, col) in CHANNELS.items():
        k0 = rate_src.STABILISE_MEASURED["bat"][stat]
        print(f"\n  === {ch.upper()} (vs the {col} residual), shrink k={k0}")
        print(f"  {'arm':<12}{'weight':<8}{'n':>7}{'r':>9}{'z':>8}"
              f"{'mean|x|':>10}{'sd x':>9}{'per start':>11}{'ceiling':>9}")
        for name, split, loo, shrunk in ARMS:
            xs_pa, xs_flat, ys, mags, _k = arm(
                rows, starts, split, loo, ch, k0 if shrunk else 0.0, 60)
            if not ys:
                print(f"  {name:<12}no rows")
                continue
            n_den = st.mean(mags)
            sy = st.pstdev(ys)
            # WHAT COULD THIS EVER HAVE SCORED. If the adjustment were
            # exactly right, the correlation it produces is its own spread
            # over the residual's. A null against an unreachable ceiling
            # says nothing, and every arm here prints its own.
            #
            # READ IT ONLY ON THE `raw` ARM. Shrinking x attenuates its
            # spread, so a shrunk arm's ceiling is BELOW the true one and a
            # measured r can legitimately exceed it — which babip does, and
            # it is arithmetic, not leakage.
            ceil = st.pstdev(xs_pa) * n_den / sy if sy else 0.0
            for wname, xs in (("pa", xs_pa), ("flat", xs_flat)):
                r_, z = corr(xs, ys)
                print(f"  {name:<12}{wname:<8}{len(xs):>7,}{r_:>+9.3f}"
                      f"{z:>+8.1f}{st.mean(abs(x) for x in xs):>10.4f}"
                      f"{st.pstdev(xs):>9.4f}"
                      f"{st.pstdev(xs) * n_den:>11.3f}{ceil:>+9.3f}")
            # The TAIL is the case that started this: a 0.6-point standard
            # deviation reads as nothing, but a single lineup measured +3.6.
            # If the mechanism works anywhere it works where lineups move.
            order = sorted(range(len(xs_pa)), key=lambda i: -abs(xs_pa[i]))
            top = order[:len(order) // 5]
            tr, tz = corr([xs_pa[i] for i in top], [ys[i] for i in top])
            q = sorted(xs_flat)
            print(f"  {'':<12}{'tail':<8}1% {q[len(q) // 100]:+.4f}"
                  f"  99% {q[-len(q) // 100]:+.4f}  max {max(q):+.4f}"
                  f"   top-20%-by-|x| r {tr:+.3f} z {tz:+.1f}")
            # Bucketed, because a slope near zero can hide a real step.
            print(f"  {'':<12}{'quints':<8}", end="")
            d = sorted(range(len(xs_pa)), key=lambda i: xs_pa[i])
            for j in range(5):
                g = d[j * len(d) // 5:(j + 1) * len(d) // 5]
                print(f"{st.mean(xs_pa[i] for i in g):+.4f}->"
                      f"{st.mean(ys[i] for i in g):+.2f}  ", end="")
            print()

    # AND THE ONE THAT SETTLES. Each channel's adjustment against EARNED
    # RUNS, because a handedness effect that never reaches the scoreboard
    # is not worth wiring in however real it is upstream.
    # THE COMBINED TEST, and it is the one the objective cares about. Each
    # channel alone is small; handedness is only worth wiring in if the
    # three of them POINT THE SAME WAY on a lineup and add up to runs.
    #
    # Linear weights, on the standard scale: a home run is worth about 1.40
    # runs over an average plate appearance and a single about 0.47. The
    # strikeout channel reaches the scoreboard only by DELETING a ball in
    # play, so its coefficient is the ball in play's expected value —
    # league BABIP times the single's weight — not the whole strikeout.
    print("\n  === COMBINED, the three channels as one run adjustment")
    print(f"  {'arm':<12}{'n':>7}{'r':>9}{'z':>8}{'sd runs':>10}"
          f"{'ceiling':>9}")
    for name, split, loo, shrunk in ARMS:
        per = {}
        for ch, (_n, _d, stat, _c) in CHANNELS.items():
            k0 = rate_src.STABILISE_MEASURED["bat"][stat]
            xs, _f, ys, mags, ks = arm(rows, starts, split, loo, ch,
                                       k0 if shrunk else 0.0, 60,
                                       against="er")
            per[ch] = {k: (x, y, m) for k, x, y, m in zip(ks, xs, ys, mags)}
        # The three channels drop different rows — babip needs balls in
        # play where k and hr need plate appearances — so they are joined
        # on the START, never zipped and hoped for.
        shared = set(per["k"]) & set(per["babip"]) & set(per["hr"])
        bip_val = lg_babip * 0.47
        xr, yr = [], []
        for key in sorted(shared):
            kx, y, pa = per["k"][key]
            bx, _, bip = per["babip"][key]
            hx, _, _ = per["hr"][key]
            xr.append(hx * pa * 1.40 + bx * bip * 0.47 - kx * pa * bip_val)
            yr.append(y)
        r_, z = corr(xr, yr)
        sy = st.pstdev(yr)
        print(f"  {name:<12}{len(xr):>7,}{r_:>+9.3f}{z:>+8.1f}"
              f"{st.pstdev(xr):>10.3f}"
              f"{(st.pstdev(xr) / sy if sy else 0):>+9.3f}")

    print("\n  === EARNED RUNS, each channel's adjustment against a_er - m_er")
    print(f"  {'channel':<12}{'arm':<12}{'n':>7}{'r':>9}{'z':>8}")
    for ch, (_num, _den, stat, _col) in CHANNELS.items():
        k0 = rate_src.STABILISE_MEASURED["bat"][stat]
        for name, split, loo, shrunk in ARMS:
            xs, _flat, ys, _m, _k = arm(rows, starts, split, loo, ch,
                                        k0 if shrunk else 0.0, 60,
                                        against="er")
            if not ys:
                continue
            r_, z = corr(xs, ys)
            print(f"  {ch:<12}{name:<12}{len(xs):>7,}{r_:>+9.3f}{z:>+8.1f}")

    print("\n  x is how far handedness moves the LINEUP's rate off the")
    print("  overall rate the model actually fed the simulator. `per start`")
    print("  is one standard deviation of that in events, over the")
    print("  denominator the start really took — the size of the correction")
    print("  on the table, before asking whether it points the right way.")


if __name__ == "__main__":
    main(sys.argv[1:])
