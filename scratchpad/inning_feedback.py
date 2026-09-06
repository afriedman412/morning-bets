"""Plan item 8a: within-inning feedback, COUNTED. Does traffic breed traffic?

    venv/bin/python -m scratchpad.inning_feedback --control    # harness first
    venv/bin/python -m scratchpad.inning_feedback --backfill   # scan, ~5 min
    venv/bin/python -m scratchpad.inning_feedback              # from cache

QUESTION: is the league worse at preventing the NEXT event once traffic is
on in the SAME inning, beyond what the (men on, outs) state multipliers
already carry? Physics candidates: pitching from the stretch, defence
holding runners, a pitcher losing his release point mid-rally.

THE DENOMINATOR, NAMED (rule 10), because three selection effects would
each manufacture this result from independent plate appearances:

  * STATE. Traffic so far correlates with occupancy, and `STATE_MULT`
    already pays for occupancy. Counted WITHIN (men on, outs) cells and
    standardised per cell before pooling, so the state effect divides out.
  * PITCHER QUALITY. Bad pitchers spend more plate appearances behind
    traffic, so tbin 1+ over-samples them — the hot-hand fallacy in
    reverse. Every plate appearance carries an EXPECTED rate built from
    the pitcher's and batter's own season rates (log5-lite, shrunk toward
    the league by 300 PA of prior), and the count is observed over
    expected, not observed over league.
  * POPULATION. A reliever entering mid-rally puts LOW traffic-by-him next
    to HIGH occupancy, and relievers are a different population. Excluded:
    a pitcher who enters with men aboard is dropped for the REST of that
    inning, so every runner on base was allowed by the current pitcher and
    "traffic so far by the SAME pitcher" equals runner provenance exactly.

TRAFFIC, DEFINED (rule 10 again — the definition, not just the
denominator): batters who REACHED against this pitcher this inning —
hits (home runs included: the batter reached, and the post-homer
bases-empty cell is the purest feedback probe there is), walks, hit
batsmen, and reached-on-error. Fielder's choice is an out recorded and
does not count. The covariate is frozen STRICTLY BEFORE the current
plate appearance — the 4b/4c leakage class is conditioning on a window
that contains the outcome, and the null control below is the proof it
does not happen here.

CONTROLS (`--control`), run before the count and the reason to trust it:
  * NULL: a base-out machine with HETEROGENEOUS pitchers and batters and
    independent plate appearances. Selection alone must read FLAT through
    this pipeline; a naive observed-over-league count reads it hot.
  * POSITIVE: the same machine with a GRADED injection, x1.05 on the hit
    channel per baserunner already allowed. The pipeline must hand back
    ~1.05 at surplus 1 and ~1.10+ at surplus 2+.
  * TTO CONFOUND: k x 0.99 per batter faced, NO feedback. Surplus rows
    sit deeper in the inning, so a pure batters-faced gradient reads as
    fake feedback unless the expectation carries the league's own
    rate-vs-batters-faced curve — which it does, and the model already
    ships `TTO_MULT`, so anything explainable by batters faced must be
    SURRENDERED to that curve or the wire double-counts a shipped
    mechanism. This control must read flat.

**THE REGISTERED BINNING FAILED ITS OWN POSITIVE CONTROL AND WAS REPLACED,
2026-09-06.** The plan registered traffic bins 0/1/2+ within (men on,
outs). But excluding inherited runners makes occupancy a FLOOR on traffic
— a (2, 1) cell is ALL traffic 2+ — so the bins are near-degenerate within
the very cells that were meant to hold state fixed. Degenerate cells pool
in at exactly 1.0 and an injected step of x1.100 read back as 1.008. The
within-cell coordinate that exists in EVERY cell is

    surplus = traffic so far - men currently on
            = his runners who have since scored or been erased,

so surplus 0/1/2+ is the primary binning and raw-traffic bins are printed
for the record only. Two consequences, stated so nobody re-fights them: a
STEP effect at traffic >= 1 is structurally inside `STATE_MULT` already
(it is collinear with occupancy, which the state table pays for); what
this count can see — and what a wire would add — is the traffic GRADIENT
at fixed occupancy.

WHAT THE CONTROLS MEASURED ABOUT THE HARNESS ITSELF, needed to read the
real count: the graded injection comes back at ~80% of its true size
(surplus 1 ratio 1.041 against a true 1.05, surplus 2+ 1.083 against
~1.12 — the boosted rows contaminate the player baselines), so a
survivor here UNDERSTATES the true gradient and must not be scaled up to
compensate without a decision. And the positive control leaked a
spurious -4% (1.9 se, sign-consistent) into the UNTOUCHED hr channel at
surplus 2+, so a lone sub-2-se hr reading is harness noise, not physics.

ROWS: pre-July of 2023-2026 — the same cut in every season, so no fold of
the battery (July-onward, all four years) ever scores a row this table was
fitted on. Era gate: multipliers computed within season, four seasons
reported side by side before anything pools.

REGISTERED BEFORE THE RUN (rule 12): surplus needs a runner scored or
erased, so expected shares are roughly 82/13/5 — surplus 1 pools ~45k PA
and surplus 2+ ~18k over four seasons, se ~1-1.5% on k/bb/babip and ~4%
on hr/hbp at the thin bin. The count SURVIVES if a channel clears 2 se
pooled AND keeps its sign in at least 3 of 4 seasons; anything smaller is
a null at this power and nothing gets wired.

THE RESULT, 2026-09-06: **NULL AT THE REGISTERED BAR. NOTHING WIRES.**
398,605 eligible PAs (shares 85/10/5, close to registered). With the TTO
standardiser in place the best channel is k_pct at 0.9790 +- 0.011
(surplus 1, 4/4 seasons) and 0.9711 +- 0.015 (surplus 2+, 3/4) — 1.9 se
per bin, UNDER the 2-se gate; bb 0.9665 +- 0.024 (1.4 se), babip
1.0241 +- 0.016 (1.5 se), hr/hbp nothing. Three things the run settled:

  * HALF THE APPARENT FEEDBACK WAS TIMES-THROUGH-THE-ORDER. Without the
    bf standardiser k read 0.955 +- 0.014 (3.2 se) at surplus 2+ and
    would have shipped a double-count of `TTO_MULT`. The confound
    control is what made that subtraction trustworthy.
  * THE NULL IS A MEASUREMENT, NOT A FAILURE TO LOOK (rule 7): the
    positive control shows a true x1.05-per-runner hit feedback would
    have read ~1.052 at surplus 2+ against the measured 1.024, so the
    within-inning hit gradient is bounded below ~x1.03/runner. Smaller
    is invisible at this power.
  * THE NEAR-MISS, stated so nobody has to rediscover it: k sits at
    1.9 se in BOTH bins, same direction, monotone over four bins
    (0.979 / 0.981 / 0.954), with bb collapsing alongside — a contact
    pattern, fewer K and fewer BB behind a partially-cleared rally. A
    combined trend test would clear 2 se, but it was not registered and
    inventing it after seeing the data is rule 13. Re-open ONLY with
    new rows (a 2022 pbp backfill) or a pre-registered trend test, and
    note the leverage is small regardless: ~0.98 on k over ~15% of PAs
    is well under the 0.05-run floor, priority-wise.
"""
from __future__ import annotations

import gzip
import json
import multiprocessing as mp
import random
import sys
from collections import defaultdict

from src import db
from src.context.sources import pbp
from scratchpad.state_table import PA_EV, K_EV, HIT_EV

CACHE = "scratchpad/inning_feedback_pas.json.gz"
REACH_EV = HIT_EV | {"walk", "hit_by_pitch", "field_error"}

#: Event classes, compact. h = hit in play (not hr); e = reached on error;
#: o = every other ball in play (outs, fielder's choice, sacrifices).
#: babip's denominator is exactly {h, e, o}; its numerator is {h}.
CLS = {"k": 0, "bb": 1, "hp": 2, "hr": 3, "h": 4, "e": 5, "o": 6}


def _cls(ev: str) -> int:
    if ev in K_EV:
        return CLS["k"]
    if ev == "walk":
        return CLS["bb"]
    if ev == "hit_by_pitch":
        return CLS["hp"]
    if ev == "home_run":
        return CLS["hr"]
    if ev in HIT_EV:
        return CLS["h"]
    if ev == "field_error":
        return CLS["e"]
    return CLS["o"]


def _one(args):
    """One game -> per-PA rows [pid, bid, men_on, outs, traffic, bf, cls].

    Traffic is the count of reaches allowed by the CURRENT pitcher in the
    CURRENT half-inning, frozen before this plate appearance. bf is the
    batters this pitcher has faced in the GAME before this one - the
    times-through-the-order coordinate the expectation standardises on.
    A pitcher who enters with men on base is ineligible for the rest of
    the inning (see the module docstring - runner provenance).
    """
    gid, season = args
    rows = []
    try:
        half = None
        cur = elig = None
        traffic = 0
        faced: dict = defaultdict(int)
        for play, bases, outs, _a, _h in pbp.plays(gid):
            ab = play.get("about") or {}
            key = (ab.get("inning"), ab.get("halfInning"))
            if key != half:
                half, cur, traffic, elig = key, None, 0, False
            p = ((play.get("matchup") or {}).get("pitcher") or {}).get("id")
            b = ((play.get("matchup") or {}).get("batter") or {}).get("id")
            if p and p != cur:
                cur, traffic = p, 0
                elig = not any(bases)
            ev = (play.get("result") or {}).get("eventType") or ""
            if ev not in PA_EV:
                continue
            c = _cls(ev)
            if elig and p and b:
                rows.append([p, b, sum(1 for x in bases if x), outs,
                             min(traffic, 9), min(faced[p], 35), c])
            if p:
                faced[p] += 1
            traffic += ev in REACH_EV
    except Exception:
        return None
    return season, rows


def backfill():
    with db.connect() as c:
        games = [(r["game_id"], r["date"][:4]) for r in c.execute(
            "select game_id, date from games where sport='mlb'"
            " and status='Final' and cast(substr(date,6,2) as int) < 7"
            " order by date")]
    games = [(g, s) for g, s in games if pbp.have(g)]
    print(f"  {len(games):,} cached pre-July games over "
          f"{len(set(s for _g, s in games))} seasons", flush=True)
    with mp.get_context("fork").Pool(8) as p:
        got = [g for g in p.map(_one, games, chunksize=16) if g]
    out: dict = defaultdict(list)
    for season, rows in got:
        out[season].extend(rows)
    with gzip.open(CACHE, "wt") as f:
        json.dump(out, f)
    n = sum(len(v) for v in out.values())
    print(f"  {n:,} eligible plate appearances -> {CACHE}")
    return out


# ── THE PIPELINE, shared verbatim by the real count and both controls ──────

STATS = ("k_pct", "bb_pct", "hr_pct", "babip", "hbp_pct")
#: Which class is each channel's numerator, and is its denominator the
#: plate appearance (None) or the ball in play ({h,e,o})?
CHAN = {"k_pct": (CLS["k"], None), "bb_pct": (CLS["bb"], None),
        "hr_pct": (CLS["hr"], None), "babip": (CLS["h"], "bip"),
        "hbp_pct": (CLS["hp"], None)}
BIP = {CLS["h"], CLS["e"], CLS["o"]}
PRIOR = 300  # PA of league-average prior on each player-season rate


def _bfbin(bf):
    return min(bf // 3, 9)


def _baselines(rows):
    """League, per-pitcher/batter season rates (shrunk), and the league's
    rate-vs-batters-faced curve per channel.

    babip is kept on its own denominator (balls in play) all the way
    through - getting that wrong is the single likeliest error in any
    count touching these channels (state_table's docstring, rule 10).

    The batters-faced curve F is the TTO standardiser: expectation picks
    up the league's own drift with batters faced, so anything the surplus
    bins could have claimed that is really times-through-the-order is
    surrendered to it. Conservative on purpose - `TTO_MULT` already ships.
    """
    lg = defaultdict(int)
    per = {"p": defaultdict(lambda: defaultdict(int)),
           "b": defaultdict(lambda: defaultdict(int))}
    bfc = defaultdict(lambda: defaultdict(int))
    for pid, bid, _on, _o, _t, bf, c in rows:
        for who, key in (("p", pid), ("b", bid)):
            d = per[who][key]
            d["pa"] += 1
            d[c] = d.get(c, 0) + 1
        lg["pa"] += 1
        lg[c] += 1
        e = bfc[_bfbin(bf)]
        e["pa"] += 1
        e[c] = e.get(c, 0) + 1

    def rates(d):
        out = {}
        for stat, (num, den) in CHAN.items():
            n = sum(d.get(c, 0) for c in BIP) if den else d["pa"]
            out[stat] = (d.get(num, 0) / n) if n else 0.0
        return out

    L = rates(lg)
    F = {}
    for bfb, d in bfc.items():
        r = rates(d)
        F[bfb] = {stat: (r[stat] / L[stat]) if L[stat] else 1.0
                  for stat in CHAN}

    def shrunk(d):
        out = {}
        for stat, (num, den) in CHAN.items():
            n = sum(d.get(c, 0) for c in BIP) if den else d["pa"]
            out[stat] = (d.get(num, 0) + PRIOR * L[stat]) / (n + PRIOR)
        return out

    return L, {w: {k: shrunk(d) for k, d in per[w].items()} for w in per}, F


def season_table(rows, binner):
    """One season's (cell, bin) -> observed and expected counts.

    Expected per plate appearance is log5-lite: pitcher rate x batter rate
    over the league rate, from rates shrunk toward the league. The state
    effect is NOT in the expectation - it divides out per cell via
    statehat below, which is what "within (men on, outs)" means here.
    `binner(traffic, men_on)` maps a row to its bin - surplus for the
    primary analysis, raw traffic for the record.
    """
    L, per, F = _baselines(rows)
    obs = defaultdict(lambda: defaultdict(float))
    exp = defaultdict(lambda: defaultdict(float))
    for pid, bid, on, outs, t, bf, c in rows:
        cell, tb = (on, outs), binner(t, on)
        rp, rb, f = per["p"][pid], per["b"][bid], F[_bfbin(bf)]
        for stat, (num, den) in CHAN.items():
            if den and c not in BIP:
                continue
            e = (min(0.95, rp[stat] * rb[stat] * f[stat] / L[stat])
                 if L[stat] else 0.0)
            exp[(cell, tb)][stat] += e
            obs[(cell, tb)][stat] += c == num
    return obs, exp


def feedback(obs, exp):
    """(tbin, stat) -> (multiplier, se, observed n) for ONE season.

    statehat(cell) = obs/exp over the whole cell, so dividing each
    (cell, tbin) expectation by it removes the cell's own state effect;
    what is left to explain is the within-cell traffic split. Weighted
    over cells by the corrected expectation, the tbin multipliers average
    to exactly 1.0 by construction - checked by the caller.
    """
    cells = sorted({c for c, _t in obs})
    tbins = sorted({t for _c, t in obs})
    hat = {}
    for cell in cells:
        for stat in STATS:
            o = sum(obs[(cell, t)][stat] for t in tbins if (cell, t) in obs)
            e = sum(exp[(cell, t)][stat] for t in tbins if (cell, t) in obs)
            hat[(cell, stat)] = o / e if e else 1.0
    out = {}
    for tb in tbins:
        for stat in STATS:
            num = sum(obs[(c, tb)][stat] for c in cells if (c, tb) in obs)
            den = sum(exp[(c, tb)][stat] * hat[(c, stat)]
                      for c in cells if (c, tb) in obs)
            m = num / den if den else 1.0
            out[(tb, stat)] = (m, m / num ** 0.5 if num else 9.9, num)
    return out


def report(by_season, binner, labels):
    per = {}
    for s in sorted(by_season):
        obs, exp = season_table(by_season[s], binner)
        per[s] = feedback(obs, exp)
    seasons = sorted(per)
    tbins = sorted({t for t, _s in per[seasons[0]]})
    print(f"\n  {'':>10}" + "".join(f"{labels[t]:>16}" for t in tbins))
    pooled = {}
    for stat in STATS:
        line = f"  {stat:<10}"
        for tb in tbins:
            n = sum(per[s][(tb, stat)][0] * per[s][(tb, stat)][2]
                    for s in seasons)
            d = sum(per[s][(tb, stat)][2] for s in seasons)
            m = n / d if d else 1.0
            se = m / d ** 0.5 if d else 9.9
            pooled[(tb, stat)] = (m, se, d)
            line += f"{m:>9.4f}+-{se:<5.3f}"
        print(line)
    print("\n  per season (sign consistency is the era gate):")
    for stat in STATS:
        for tb in tbins:
            if tb == 0:
                continue
            vals = [per[s][(tb, stat)][0] for s in seasons]
            print(f"    {stat:<9} {labels[tb]:<5} "
                  + " ".join(f"{v:>7.4f}" for v in vals))
    return per, pooled


# ── CONTROLS ───────────────────────────────────────────────────────────────

def _machine(n_innings, feedback_mult, rng, tto_mult=1.0):
    """A crude base-out inning machine with heterogeneous players.

    Advancement is deliberately naive (station-to-station singles, walks
    force) - the pipeline only needs realistic CELL COMPOSITION and true
    per-PA independence, not a good baseball simulator. Pitcher and batter
    quality multiply the hit and walk channels lognormally, which is the
    selection effect the pipeline must NOT read as feedback. `tto_mult`
    scales the strikeout channel per batter faced - a pure
    times-through-the-order gradient with NO feedback, which the
    standardiser must absorb.
    """
    P = [{"h": rng.lognormvariate(0, 0.15), "bb": rng.lognormvariate(0, 0.15)}
         for _ in range(240)]
    B = [{"h": rng.lognormvariate(0, 0.10), "bb": rng.lognormvariate(0, 0.10)}
         for _ in range(540)]
    rows = []
    bi = 0
    for inning in range(n_innings):
        pi = rng.randrange(len(P))
        bases, outs, traffic, bf = [False] * 3, 0, 0, 3 * (inning % 7)
        while outs < 3:
            bid = bi % len(B)
            bi += 1
            p, b = P[pi], B[bid]
            k = 0.222 * tto_mult ** bf
            bb = min(0.30, 0.082 * p["bb"] * b["bb"])
            hp, hr = 0.011, 0.032
            fb = feedback_mult ** min(traffic, 4)
            babip = min(0.85, 0.29 * p["h"] * b["h"] * fb)
            r = rng.random()
            if r < k:
                c = CLS["k"]
            elif r < k + bb:
                c = CLS["bb"]
            elif r < k + bb + hp:
                c = CLS["hp"]
            elif r < k + bb + hp + hr:
                c = CLS["hr"]
            else:
                c = CLS["h"] if rng.random() < babip else CLS["o"]
            rows.append([pi, 10000 + bid, sum(bases), outs, min(traffic, 9),
                         min(bf, 35), c])
            bf += 1
            if c == CLS["hr"]:
                bases = [False] * 3
            elif c in (CLS["bb"], CLS["hp"]):
                if all(bases):
                    pass
                else:
                    for i in (0, 1, 2):
                        if not bases[i]:
                            bases[i] = True
                            break
            elif c == CLS["h"]:
                bases = [True] + bases[:2]
            else:
                outs += 1
            traffic += c in (CLS["bb"], CLS["hp"], CLS["hr"], CLS["h"])
    return rows


def sbin(t, on):
    """Surplus 0/1/2+ - the primary binning; see the module docstring."""
    s = max(0, t - on)
    return 0 if s == 0 else (1 if s == 1 else 2)


def sbin4(t, on):
    return min(max(0, t - on), 3)


def tbin3(t, _on):
    """Raw traffic 0/1/2+ - the binning the plan registered, printed for
    the record. Its positive control failed (x1.100 in, 1.008 out)."""
    return 0 if t == 0 else (1 if t == 1 else 2)


S_LABELS = {0: "surplus 0", 1: "surplus 1", 2: "surplus 2+"}
S_LABELS4 = {0: "surplus 0", 1: "surplus 1", 2: "surplus 2",
             3: "surplus 3+"}
T_LABELS = {0: "traffic 0", 1: "traffic 1", 2: "traffic 2+"}


def control():
    cases = (("NULL (heterogeneous, independent)", 1.0, 1.0),
             ("POSITIVE (x1.05 on hits per runner allowed)", 1.05, 1.0),
             ("TTO CONFOUND (k x0.99 per batter faced, NO feedback)",
              1.0, 0.99))
    for name, mult, tto in cases:
        rng = random.Random(8)
        by_season = {str(2023 + i): _machine(60000, mult, rng, tto)
                     for i in range(4)}
        print(f"\n== CONTROL: {name} — surplus bins (primary) ==")
        report(by_season, sbin, S_LABELS)
        if tto == 1.0:
            print(f"\n== CONTROL: {name} — raw traffic bins (the record) ==")
            report(by_season, tbin3, T_LABELS)


def main(argv):
    if "--control" in argv:
        control()
        return
    if "--backfill" in argv:
        by_season = backfill()
    else:
        with gzip.open(CACHE, "rt") as f:
            by_season = json.load(f)
    n = sum(len(v) for v in by_season.values())
    print(f"\n  {n:,} eligible plate appearances, pre-July, "
          f"{len(by_season)} seasons")
    for s in sorted(by_season):
        sh = defaultdict(int)
        for r in by_season[s]:
            sh[sbin(r[4], r[2])] += 1
        tot = len(by_season[s])
        print(f"    {s}: {tot:>8,} PA   surplus shares "
              + " / ".join(f"{sh[t] / tot:.3f}" for t in (0, 1, 2)))

    print("\n== THE COUNT — surplus bins (primary) ==")
    report(by_season, sbin, S_LABELS)

    print("\n== FOUR SURPLUS BINS, for the record only ==")
    report(by_season, sbin4, S_LABELS4)

    print("\n== RAW TRAFFIC BINS (registered shape; failed its positive"
          " control) ==")
    report(by_season, tbin3, T_LABELS)


if __name__ == "__main__":
    main(sys.argv[1:])
