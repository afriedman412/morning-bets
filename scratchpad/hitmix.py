"""Should the 1B/2B/3B split be PER HITTER instead of one league number?

    venv/bin/python -m scratchpad.hitmix

`sim.resolve` sets `hit_mix=lg["hit_mix"]`, and the comment above it in
`rates.py` says extra-base rates "move much less between hitters than the
overall hit rate does, so this is applied league-wide and the individual
variation is carried by BABIP." That is an ASSERTION. The house rule here
is count it, do not import it — so this counts it.

THE GATE IS TWO-PART and both halves have to pass:
  1. SPREAD — do hitters actually differ, after removing the binomial
     noise that a 100-hit sample carries on its own?
  2. RELIABILITY — does the difference REPEAT? Split-half on odd against
     even games, Spearman-Brown corrected, which is the same gate
     `stabilise.py` and `whos_wrong.py` use.
A real spread that does not repeat is exactly the per-pitcher dispersion
result: visible, and useless to price with.
"""
from __future__ import annotations

import statistics as st
from collections import defaultdict

from src import db

MIN_HITS = 40


def main():
    with db.connect() as c:
        rows = [dict(r) for r in c.execute(
            "select b.player_name nm, b.game_id gid, b.h, b.hr, b.\"2b\" d,"
            " b.\"3b\" t from mlb_batting b join games g"
            " on g.game_id = b.game_id where g.sport='mlb'"
            " and g.status='Final' and g.date like '2026%'")]
    half = defaultdict(lambda: [[0, 0], [0, 0]])   # [xbh, hits] per half
    tot = defaultdict(lambda: [0, 0])
    for i, r in enumerate(sorted(rows, key=lambda x: (x["nm"], x["gid"]))):
        nh = (r["h"] or 0) - (r["hr"] or 0)          # non-homer hits
        xb = (r["d"] or 0) + (r["t"] or 0)
        if nh < 0:
            continue
        k = i % 2
        half[r["nm"]][k][0] += xb
        half[r["nm"]][k][1] += nh
        tot[r["nm"]][0] += xb
        tot[r["nm"]][1] += nh

    pop = [(n, x / h) for n, (x, h) in tot.items() if h >= MIN_HITS]
    shares = [s for _, s in pop]
    lg_share = sum(tot[n][0] for n, _ in pop) / sum(tot[n][1] for n, _ in pop)
    print(f"  {len(pop)} hitters with >= {MIN_HITS} non-homer hits, 2026")
    print(f"  league extra-base share of a non-homer hit: {lg_share:.4f}\n")
    q = sorted(shares)
    print(f"  observed spread   p10 {q[len(q)//10]:.4f}   "
          f"p50 {q[len(q)//2]:.4f}   p90 {q[-len(q)//10]:.4f}   "
          f"sd {st.pstdev(shares):.4f}")
    # BINOMIAL NOISE FLOOR. A hitter with n hits carries sd
    # sqrt(p(1-p)/n) on his share by chance alone, so an observed spread
    # has to clear it before any of it is real.
    mean_n = st.mean(tot[n][1] for n, _ in pop)
    noise = (lg_share * (1 - lg_share) / mean_n) ** 0.5
    obs = st.pstdev(shares)
    true = (max(obs ** 2 - noise ** 2, 0)) ** 0.5
    print(f"  binomial noise at mean n={mean_n:.0f}: {noise:.4f}")
    print(f"  -> TRUE spread after removing it: {true:.4f}"
          f"   ({100 * true / lg_share:.1f}% of the league share)\n")

    pairs = [(half[n][0][0] / half[n][0][1], half[n][1][0] / half[n][1][1])
             for n, _ in pop
             if half[n][0][1] >= MIN_HITS // 2 and half[n][1][1] >= MIN_HITS // 2]
    if len(pairs) > 10:
        a = [x for x, _ in pairs]
        b = [y for _, y in pairs]
        ma, mb = st.mean(a), st.mean(b)
        cov = sum((x - ma) * (y - mb) for x, y in pairs) / len(pairs)
        r = cov / (st.pstdev(a) * st.pstdev(b))
        sb = 2 * r / (1 + r) if r > -1 else 0.0
        print(f"  SPLIT-HALF over {len(pairs)} hitters: r {r:+.3f}"
              f"   Spearman-Brown {sb:+.3f}")
        print("  (for scale: pitcher HBP reliability is +0.711 and IS worth")
        print("   wiring; per-pitcher dispersion is +0.072 and is closed.)")

    print("\n  WHAT IT WOULD BE WORTH. A double instead of a single is worth")
    print("  roughly 0.30 runs of base-out state. A hitter's non-homer hits")
    print("  are about 1.05 a game, so a full standard deviation of true")
    print(f"  extra-base share moves {1.05 * true * 0.30:.4f} runs a game per")
    print(f"  hitter, or {9 * 1.05 * true * 0.30:.3f} across a lineup if every")
    print("  slot deviated the same way — which they do not, so the club")
    print("  level is far smaller. The leverage floor in this project is")
    print("  0.05 runs.")


if __name__ == "__main__":
    main()
