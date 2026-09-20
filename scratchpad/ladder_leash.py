"""Does the leash move the RUN level? Paired, same games, same draws.

The prefix ladder cannot see a hook change in principle — starters and
relievers are equal in aggregate here (K-BB 0.1358 against 0.1333), so
moving WHEN a pitcher leaves does not move how many score. That makes this
a NO-REGRESSION test, not a hunt for a gain: the leash is expected to read
flat, and a real move at F1 — an inning no reliever reaches — would mean
the mechanism is leaking somewhere it should not.

    venv/bin/python -m scratchpad.ladder_leash [limit] [n_sims]
"""
import statistics as st
import sys

from src.context import calibrate as cal
from src.context import ladder, sim
from src.context.sources import innings as inn_src
from src.context.sources import rates as rate_src


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    n_sims = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    lg = sim.league()
    pens = rate_src.bullpens(lg)
    by = {}
    for s, p, l in cal.build_cases():
        by.setdefault(s["game_id"], []).append((s, p, l))
    by = {g: v for g, v in by.items()
          if len(v) == 2 and sum(bool(x[0]["is_home"]) for x in v) == 1}
    actual = {p: inn_src.prefix_totals(p) for p in ladder.PREFIXES}
    usable = [g for g in by if all(g in actual[p] for p in ladder.PREFIXES)]
    if limit:
        usable = usable[:limit]
    by = {g: by[g] for g in usable}
    print(f"  {len(by)} games x {n_sims} draws, paired")

    states = {}
    for flag in (False, True):
        sim.USE_LEASH = flag
        sim.reload_offsets()
        states[flag] = ladder.simulate_prefixes(by, pens, lg, n_sims=n_sims)
        print(f"  USE_LEASH={flag} done", flush=True)
    sim.USE_LEASH = True
    sim.reload_offsets()

    print(f"\n  {'':<6}{'actual':>9}{'OFF':>8}{'ON':>8}{'errOFF':>9}"
          f"{'errON':>9}{'d|err|':>10}{'sigma':>8}")
    for p in ladder.PREFIXES:
        gs = [g for g in by if g in states[False] and g in states[True]]
        a = [actual[p][g]["total"] for g in gs]
        o = [states[False][g][p] for g in gs]
        n = [states[True][g][p] for g in gs]
        d = [abs(x - t) - abs(y - t) for x, y, t in zip(o, n, a)]
        md = st.mean(d)
        se = st.pstdev(d) / len(d) ** 0.5 if len(d) > 1 else 0.0
        print(f"  F{p:<5}{st.mean(a):>9.2f}{st.mean(o):>8.2f}"
              f"{st.mean(n):>8.2f}{st.mean(o) - st.mean(a):>+9.3f}"
              f"{st.mean(n) - st.mean(a):>+9.3f}{md:>+10.4f}"
              f"{(md / se if se else 0):>+8.1f}")
    print("\n  d|err| > 0 means the leash REDUCED absolute error.")


if __name__ == "__main__":
    main()
