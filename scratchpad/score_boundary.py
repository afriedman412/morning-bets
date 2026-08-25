"""Score the boundary hook on ACTUAL RUNS via the prefix ladder, paired.

Common random numbers on both sides — `ladder.simulate_prefixes` seeds per
(game, draw), so the two states see bit-identical innings until the hook
itself diverges them. The comparison is the PAIRED change in absolute error
per game, which is what the low-n aggregate mean cannot resolve.
"""
import statistics as st

from src.context import calibrate as cal
from src.context import game, ladder, sim
from src.context.sources import innings as inn_src
from src.context.sources import rates as rate_src


def main():
    lg = sim.league()
    pens = rate_src.bullpens(lg)
    by = {}
    for s, p, l in cal.build_cases():
        by.setdefault(s["game_id"], []).append((s, p, l))
    by = {g: v for g, v in by.items()
          if len(v) == 2 and sum(bool(x[0]["is_home"]) for x in v) == 1}
    actual = {p: inn_src.prefix_totals(p) for p in ladder.PREFIXES}
    usable = [g for g in by if all(g in actual[p] for p in ladder.PREFIXES)]
    by = {g: by[g] for g in usable}
    print(f"{len(by)} games, paired with common random numbers", flush=True)
    res = {}
    for flag in (False, True):
        game.USE_BOUNDARY_HOOK = flag
        print(f"  simulating USE_BOUNDARY_HOOK={flag} ...", flush=True)
        res[flag] = ladder.simulate_prefixes(by, pens, lg, n_sims=40, seed=7)
    game.USE_BOUNDARY_HOOK = True
    print(f"\n  {'':<6}{'actual':>9}{'OFF':>9}{'ON':>9}{'errOFF':>9}"
          f"{'errON':>9}{'d(|err|)':>10}{'sigma':>8}")
    for p in ladder.PREFIXES:
        a = [actual[p][g]["total"] for g in by]
        o = [res[False][g][p] for g in by]
        n = [res[True][g][p] for g in by]
        eo = st.mean(x - y for x, y in zip(o, a))
        en = st.mean(x - y for x, y in zip(n, a))
        d = [abs(x - y) - abs(z - y) for x, z, y in zip(o, n, a)]
        m = st.mean(d)
        se = st.pstdev(d) / len(d) ** 0.5
        print(f"  F{p:<5}{st.mean(a):>9.2f}{st.mean(o):>9.2f}{st.mean(n):>9.2f}"
              f"{eo:>+9.3f}{en:>+9.3f}{m:>+10.4f}{m / se if se else 0:>+8.1f}")
    print("\n  d(|err|) > 0 means the boundary hook REDUCED absolute error.")


if __name__ == "__main__":
    main()
