"""SPLIT THE SELECTION PROFILE BY INNING — TODO 21, the closer's slot.

    venv/bin/python -m scratchpad.pen_pick_inning

`PEN_PICK` routes by margin bucket alone and its weights were COUNTED POOLED
over innings 7-9. The real structure is setup in the 7th and 8th, closer in
the 9th, so the pooled profile smears into "44% best-fifth whenever leading
late" and the engine can spend the club's best arm two innings early. Same
pooling defect as the hook curves and the relief hazard, same fix: one more
key.

WHAT WOULD REFUTE THE ITEM, pre-registered: if the five weights are flat
across innings 7/8/9 inside a margin bucket, there is no slot structure to
recover and `PEN_PICK` should stay as it is. The item survives only if the
best-fifth weight RISES with the inning while protecting a lead.

CHECK THE CELL SIZES FIRST — that is the operator's instruction and it is
the whole risk here. Three innings x five buckets x five bins is 75 cells
off 24,181 entries, and a rate counted on forty rows is a rumour. Cells and
standard errors print alongside every weight.

The quality percentile is computed exactly as `pen_pick.py` does it — rank
among the arms STILL UNUSED that night, in fifths, 0 = best remaining — so
the two counts are comparable line for line. Train rows only, per rule 6.
"""
from collections import defaultdict

from src.context import game, sim, store
from src.context.sources import rates as rate_src

CUTS = {s: f"{s}-07-01" for s in (2023, 2024, 2025, 2026)}
LATE = 7

_Q = """
select game_id, date, team, player_name name, appearance_order ord,
       entry_inning inning, entry_margin margin
from mlb_stints
where date >= '{a}' and date < '{b}'
order by game_id, team, appearance_order
"""


def inning_key(inning: int) -> str:
    """7, 8, 9+ — extras go with the ninth, where the same arms work."""
    return "7" if inning == 7 else ("8" if inning == 8 else "9+")


def count() -> tuple[dict, dict]:
    lg = sim.league()
    pctl: dict = defaultdict(lambda: defaultdict(int))
    pooled: dict = defaultdict(lambda: defaultdict(int))
    for s in sorted(CUTS):
        pens = rate_src.bullpens(lg, season=s, before=CUTS[s])
        qual = {(t, a["name"]): a["k_pct"] - a["bb_pct"]
                for t, arms in pens.items() for a in arms}
        with store.connect(attach=False) as c:
            rows = [dict(r) for r in
                    c.execute(_Q.format(a=f"{s}-01-01", b=CUTS[s]))]
        used: dict = {}
        for r in rows:
            key = (r["game_id"], r["team"])
            seen = used.setdefault(key, set())
            if r["ord"] > 0 and r["inning"] >= LATE:
                remaining = [n for (t, n), v in qual.items()
                             if t == r["team"] and n not in seen]
                if len(remaining) > 1 and r["name"] in remaining:
                    ranked = sorted(remaining,
                                    key=lambda n: -qual[(r["team"], n)])
                    pct = ranked.index(r["name"]) / (len(ranked) - 1)
                    bin5 = min(int(pct * 5), 4)
                    b = game._pick_bucket(r["margin"])
                    i = inning_key(r["inning"])
                    pctl[(b, i)][bin5] += 1
                    pctl[(b, i)]["n"] += 1
                    pooled[b][bin5] += 1
                    pooled[b]["n"] += 1
            seen.add(r["name"])
    return pctl, pooled


def main() -> None:
    pctl, pooled = count()
    print("\nQUALITY PERCENTILE OF THE ARM CHOSEN, in fifths (bin1 = best "
          "remaining)")
    print("  weights, then n, then the se on bin1\n")
    print(f"  {'bucket':<9}{'inn':>5}{'n':>7}" +
          "".join(f"{f'bin{i+1}':>8}" for i in range(5)) + f"{'se1':>8}")
    for b in ("lead", "tied", "trail", "mid", "blowout"):
        n0 = pooled[b]["n"]
        if n0:
            w = [pooled[b][i] / n0 for i in range(5)]
            se = (w[0] * (1 - w[0]) / n0) ** 0.5
            print(f"  {b:<9}{'pool':>5}{n0:>7}" +
                  "".join(f"{x:>8.4f}" for x in w) + f"{se:>8.4f}")
        for i_ in ("7", "8", "9+"):
            n = pctl[(b, i_)]["n"]
            if not n:
                continue
            w = [pctl[(b, i_)][k] / n for k in range(5)]
            se = (w[0] * (1 - w[0]) / n) ** 0.5
            print(f"  {'':<9}{i_:>5}{n:>7}" +
                  "".join(f"{x:>8.4f}" for x in w) + f"{se:>8.4f}")
        print()

    print("  THE PRE-REGISTERED TEST: bin1 must RISE with the inning while")
    print("  protecting a lead, or there is no slot structure to recover.")
    for b in ("lead", "tied"):
        v = []
        for i_ in ("7", "8", "9+"):
            n = pctl[(b, i_)]["n"]
            if n:
                p = pctl[(b, i_)][0] / n
                v.append((i_, p, (p * (1 - p) / n) ** 0.5, n))
        if len(v) == 3:
            d = v[2][1] - v[0][1]
            sd = (v[2][2] ** 2 + v[0][2] ** 2) ** 0.5
            print(f"    {b:<6} 7th {v[0][1]:.4f}  8th {v[1][1]:.4f}  "
                  f"9th {v[2][1]:.4f}   9th-7th {d:+.4f} +-{sd:.4f}"
                  f"  {d / sd:+.1f} sd")


if __name__ == "__main__":
    main()
