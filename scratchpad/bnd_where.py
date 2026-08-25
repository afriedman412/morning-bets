"""Is the boundary-share error UNIFORM or CONCENTRATED?

Uniform means a shared intercept is off and shifting it is honest.
Concentrated means something structural is wrong in those cells and an
intercept shift would paper over it — which is what `pitch_scale` did when
it pinned at its grid edge to cover pitch-count dispersion.
"""
import random
import statistics as st
from collections import defaultdict

from src.context import boundary, calibrate as cal, game, sim
from src.context.sources import pbp, rates as rate_src

EARLY = 3


def actual():
    """Real removals, split by kind, binned by inning and pitch count."""
    cells = defaultdict(lambda: [0, 0])          # key -> [boundary, mid]
    for gid in pbp.final_games():
        if not pbp.have(gid):
            continue
        try:
            rows = boundary.exits(gid)
        except Exception:
            continue
        for r in rows:
            if r["kind"] not in ("boundary", "mid"):
                continue
            i = min(max(r["inning"], 1), 8)
            p = min(r["pitches"] // 15 * 15, 105)
            cells[("inning", i)][r["kind"] == "mid"] += 1
            cells[("pitches", p)][r["kind"] == "mid"] += 1
    return cells


def simulated():
    lg = sim.league()
    pens = rate_src.bullpens(lg)
    by = {}
    for s, p, l in cal.build_cases():
        by.setdefault(s["game_id"], []).append((s, p, l))
    by = {g: v for g, v in by.items()
          if len(v) == 2 and sum(bool(x[0]["is_home"]) for x in v) == 1}
    cells = defaultdict(lambda: [0, 0])
    hook = sim.Hook(early_innings=EARLY)
    orig = game._half_inning
    state = {}

    def spy(side, lg_, rng, inning, margin, park, walk_off=False):
        was_out = side.starter_out
        before = side.line.pitches
        r = orig(side, lg_, rng, inning, margin, park, walk_off)
        if not was_out and side.starter_out:
            state["inning"] = inning
            state["pitches"] = side.line.pitches
            state["mid"] = bool(side.line.pulled_mid_inning)
        return r

    game._half_inning = spy
    try:
        for i, (gid, v) in enumerate(by.items()):
            home = next(x for x in v if x[0]["is_home"])
            away = next(x for x in v if not x[0]["is_home"])
            an = cal.adjust_lineup(away[2], False)
            hn = cal.adjust_lineup(home[2], True)
            for draw in range(6):
                rng = random.Random(7 + i * 100003 + draw)
                for sd, pen, nine in ((away[1], (away[0]["team"] or "").upper(), hn),
                                      (home[1], (home[0]["team"] or "").upper(), an)):
                    pass
                A = game.build_side(away[1], pens.get((away[0]["team"] or "").upper(), []), hn, hook, rng)
                H = game.build_side(home[1], pens.get((home[0]["team"] or "").upper(), []), an, hook, rng)
                game.simulate_game(A, H, lg, rng)
                for side in (A, H):
                    if not side.starter_out:
                        continue
                    ln = side.line
                    inn = min(max(ln.innings_completed or 1, 1), 8)
                    p = min(ln.pitches // 15 * 15, 105)
                    m = bool(ln.pulled_mid_inning)
                    cells[("inning", inn)][m] += 1
                    cells[("pitches", p)][m] += 1
    finally:
        game._half_inning = orig
    return cells


def show(a, s, kind, labels):
    print(f"\n  BOUNDARY SHARE by {kind}")
    print(f"    {'':<8}{'actual':>10}{'n':>8}{'sim':>10}{'n':>9}{'gap':>9}")
    for k in labels:
        av = a.get((kind, k))
        sv = s.get((kind, k))
        if not av or sum(av) < 60 or not sv or sum(sv) < 200:
            continue
        ap = av[0] / sum(av)
        sp = sv[0] / sum(sv)
        print(f"    {k:<8}{ap:>10.1%}{sum(av):>8,}{sp:>10.1%}{sum(sv):>9,}"
              f"{sp - ap:>+9.1%}")


def main():
    import sys
    global EARLY
    if len(sys.argv) > 1:
        EARLY = int(sys.argv[1])
    print(f"early_innings={EARLY}", flush=True)
    print("counting real removals ...", flush=True)
    a = actual()
    print("simulating ...", flush=True)
    s = simulated()
    show(a, s, "inning", range(1, 9))
    show(a, s, "pitches", range(0, 120, 15))
    print("\n  A roughly CONSTANT gap down both tables means one shared")
    print("  intercept is off. A gap that changes sign or size means the")
    print("  structure is wrong in those cells.")


if __name__ == "__main__":
    main()
