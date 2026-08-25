"""Is the missing disaster tail the HOOK or the RUN SCORING?

Starts under 2 innings happen 1.6% of the time and the simulator produces
0.1%. Conditional on a short start, real ones average 7.6 outs and the
simulator's 9.4 — it bottoms out around the third inning and stops.

Two candidates, and steepening the hook before separating them would be
another compensating error, exactly like `pitch_scale` pinning at its grid
edge to paper over pitch-count dispersion.

  HOOK: the disaster inning happens and the manager does not react hard
  enough. `mid_per_damage` is 0.25 in the refit, so a five-run inning barely
  moves the pull probability.

  SCORING: the disaster inning never happens. The notes already record the
  simulator short of crooked innings, 15.2% against 17.7%.

Separated by counting BIG INNINGS AGAINST THE STARTER independent of
whether he was pulled — a quantity the hook cannot touch, because it is
measured over innings he actually pitched.

    venv/bin/python -m scratchpad.tail
"""
import random
import statistics as st
import sys
from collections import Counter, defaultdict

from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import pbp, rates as rate_src


def actual_innings(limit=None, verbose=True):
    """Runs allowed by the STARTER in each inning he pitched, from PBP."""
    ids = pbp.final_games()
    if limit:
        ids = ids[:limit]
    per = []
    n = 0
    for gid in ids:
        if not pbp.have(gid):
            continue
        data = pbp.fetch(gid)
        if not data:
            continue
        n += 1
        starter, runs = {}, defaultdict(int)
        prev = 0
        for play in (data.get("allPlays") or []):
            ab = play.get("about") or {}
            mu = play.get("matchup") or {}
            res = play.get("result") or {}
            pid = (mu.get("pitcher") or {}).get("id")
            if not pid:
                continue
            side = "home" if ab.get("isTopInning") else "away"
            starter.setdefault(side, pid)
            sc = (res.get("awayScore", 0) or 0) + (res.get("homeScore", 0) or 0)
            d = max(sc - prev, 0)
            prev = sc
            if starter[side] != pid:
                continue
            runs[(side, ab.get("inning") or 1)] += d
        per.extend(runs.values())
        if verbose and n % 500 == 0:
            print(f"  {n} games", flush=True)
    return per


def main():
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    print("counting REAL innings pitched by starters ...", flush=True)
    act = actual_innings(lim)

    lg = sim.league()
    pens = rate_src.bullpens(lg)
    by = {}
    for s, p, l in cal.build_cases():
        by.setdefault(s["game_id"], []).append((s, p, l))
    by = {g: v for g, v in by.items()
          if len(v) == 2 and sum(bool(x[0]["is_home"]) for x in v) == 1}
    by = dict(list(by.items())[:800])

    fitted = sim.Hook(pitch_center=80.0, pitch_scale=8.0, per_run=0.3,
                      per_inning=0.45, intercept=-4.0, mid_intercept=-4.4,
                      mid_per_run=0.45, mid_per_runner=0.55,
                      mid_per_damage=0.25, per_baserunner=0.2)
    # Per-inning runs are not recorded by the engine. Wrapping
    # `_half_inning` keeps this a diagnostic rather than a schema change:
    # the quantity is only needed here, and adding a field to StartResult to
    # answer one question is how fields accumulate.
    _orig = game._half_inning
    bucket = []

    def spy(side, lg_, rng, inning, margin, park, walk_off=False):
        before = side.line.runs
        was_out = side.starter_out
        r = _orig(side, lg_, rng, inning, margin, park, walk_off)
        if not was_out:
            bucket.append(side.line.runs - before)
        return r

    out = {}
    for hook, lbl in ((sim.Hook(), "shipped"), (fitted, "refit")):
        innings = bucket
        bucket.clear()
        game._half_inning = spy
        for i, (gid, v) in enumerate(by.items()):
            home = next(x for x in v if x[0]["is_home"])
            away = next(x for x in v if not x[0]["is_home"])
            an = cal.adjust_lineup(away[2], False)
            hn = cal.adjust_lineup(home[2], True)
            for draw in range(6):
                rng = random.Random(7 + i * 100003 + draw)
                A = game.build_side(
                    away[1], pens.get((away[0]["team"] or "").upper(), []),
                    hn, hook, rng)
                H = game.build_side(
                    home[1], pens.get((home[0]["team"] or "").upper(), []),
                    an, hook, rng)
                game.simulate_game(A, H, lg, rng, track=())
        out[lbl] = list(bucket)
        game._half_inning = _orig

    print(f"\nRUNS ALLOWED BY THE STARTER, PER INNING HE PITCHED")
    print(f"  {'runs':>6}{'ACTUAL':>10}" +
          "".join(f"{k:>10}" for k in out))
    rows = [act] + [out[k] for k in out]
    for r in range(0, 7):
        cells = "".join(
            f"{sum(1 for x in v if (x == r if r < 6 else x >= 6)) / len(v):>9.2%}"
            for v in rows)
        print(f"  {r if r < 6 else '6+':>6}" + cells)
    print(f"\n  {'':>6}" + "".join(
        f"{'':>0}mean {st.mean(v):.3f}   " for v in rows))
    print(f"\n  n: actual {len(act):,}" +
          "".join(f", {k} {len(out[k]):,}" for k in out))
    print("\n  If the simulator matches on 4+ run innings, the disaster")
    print("  innings ARE happening and the hook is not reacting. If it is")
    print("  short, the scoring model is the problem and steepening the")
    print("  hook would be a compensating error.")


if __name__ == "__main__":
    main()
