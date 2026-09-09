"""STEP TWO of PLAN-opener-bullpen.md: the same pitcher in two roles.

QUESTION. When a pitcher relieves instead of starts, what happens to his
rates? The published answer (a reliever gains a couple points of K%) is an
imported constant, which is 0-for-everything here. Count it on this league.

HYPOTHESIS. Relief K% is higher than the same pitcher's starter K% in the
same season; direction of the others unknown.

TEST. Within pitcher-season, both roles with >= 30 batters faced in each.
Paired difference (relief minus start) per stat, pooled with a standard
error. Split-half reliability of the PER-PITCHER difference (odd/even
games within each role) decides whether anything beyond the pooled number
repeats. BF is reconstructed as outs + h + bb + hbp — identical formula in
both roles, so the reconstruction cancels in the pair.

HOLDOUT. The pooled diff is a shipping candidate, so it is counted on
date < 2026-07-01 only (the project's one cutoff). Full-sample shown
beside it for stability, marked as not-for-shipping.

POSITIVE CONTROL. The reliability estimator is the part that can silently
fail (a mis-specified split reads as "does not repeat"), so it runs on
synthetic pitchers with a known persistent per-pitcher diff (sd 0.03)
plus binomial noise at each pitcher's real BF.

POWER, stated before the result. Binomial noise on a rate at ~100 BF is
~0.04; a paired diff of two such is ~0.06. At ~400 pitcher-seasons the
pooled se is ~0.003, so a two-point K% shift is a >6 sigma detection. The
split-half correlation at ~half those BFs per half is attenuated hard —
the control tells us what a true sd-0.03 trait looks like through it.
"""
import random
from collections import defaultdict

from src.context import store

HOLDOUT = "2026-07-01"
MIN_BF = 30


def lines(con, before=None):
    q = """
      select p.player_name nm, substr(g.date, 1, 4) season, p.is_starter s,
             p.outs_recorded outs, p.h, p.k, p.bb, p.hr, p.hbp, g.date
      from bets.mlb_pitching p
      join bets.games g on g.game_id = p.game_id
      where g.sport = 'mlb' and g.status = 'Final'
    """
    if before:
        q += " and g.date < ?"
        return [dict(r) for r in con.execute(q, (before,))]
    return [dict(r) for r in con.execute(q)]


def tally(rows):
    t = {"bf": 0, "k": 0, "bb": 0, "hr": 0, "h": 0, "hbp": 0, "n": 0}
    for r in rows:
        t["bf"] += r["outs"] + r["h"] + r["bb"] + (r["hbp"] or 0)
        for f in ("k", "bb", "hr", "h"):
            t[f] += r[f]
        t["hbp"] += r["hbp"] or 0
        t["n"] += 1
    return t


def rates(t):
    bf = t["bf"]
    bip = bf - t["k"] - t["bb"] - t["hr"] - t["hbp"]
    return {"k_pct": t["k"] / bf, "bb_pct": t["bb"] / bf,
            "hr_pct": t["hr"] / bf,
            "babip": (t["h"] - t["hr"]) / bip if bip > 0 else None}


def pairs(rows):
    g = defaultdict(lambda: {0: [], 1: []})
    for r in rows:
        g[(r["nm"], r["season"])][r["s"]].append(r)
    out = []
    for key, roles in g.items():
        ts, tr = tally(roles[1]), tally(roles[0])
        if ts["bf"] >= MIN_BF and tr["bf"] >= MIN_BF:
            out.append((key, roles, ts, tr))
    return out


def pooled(pp):
    stats = ("k_pct", "bb_pct", "hr_pct", "babip")
    diffs = defaultdict(list)
    for _, _, ts, tr in pp:
        rs, rr = rates(ts), rates(tr)
        for s in stats:
            if rs[s] is not None and rr[s] is not None:
                diffs[s].append(rr[s] - rs[s])
    out = {}
    for s in stats:
        d = diffs[s]
        n = len(d)
        m = sum(d) / n
        sd = (sum((x - m) ** 2 for x in d) / (n - 1)) ** 0.5
        out[s] = (m, sd / n ** 0.5, n)
    return out


def split_half_diff(pp, stat="k_pct"):
    xs, ys = [], []
    for _, roles, _, _ in pp:
        halves = []
        for part in (0, 1):
            ts = tally(roles[1][part::2])
            tr = tally(roles[0][part::2])
            if ts["bf"] < MIN_BF // 2 or tr["bf"] < MIN_BF // 2:
                halves = None
                break
            halves.append(rates(tr)[stat] - rates(ts)[stat])
        if halves:
            xs.append(halves[0])
            ys.append(halves[1])
    return pearson(xs, ys), len(xs)


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if not sx or not sy:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def control(pp, trait_sd=0.03, seed=11):
    """Synthetic pitchers with a KNOWN persistent per-pitcher K% diff.

    Keeps each real pitcher's game structure and per-game BF; replaces k
    with binomial draws at base 0.20 as starter and 0.20 + his trait as
    reliever. What the estimator returns here is what a real sd-0.03
    trait looks like through the split-half harness.
    """
    rng = random.Random(seed)
    fake = []
    for key, roles, ts, tr in pp:
        trait = rng.gauss(0, trait_sd)
        froles = {0: [], 1: []}
        for s in (0, 1):
            base = 0.20 if s == 1 else 0.20 + trait
            for r in roles[s]:
                bf = r["outs"] + r["h"] + r["bb"] + (r["hbp"] or 0)
                k = sum(rng.random() < base for _ in range(bf))
                froles[s].append({**r, "k": k})
        fake.append((key, froles, tally(froles[1]), tally(froles[0])))
    return fake


def main():
    with store.connect() as con:
        train = lines(con, before=HOLDOUT)
        full = lines(con)
    for tag, rows in (("TRAIN (< %s) — the shipping candidate" % HOLDOUT,
                       train),
                      ("FULL sample — stability check only", full)):
        pp = pairs(rows)
        print(f"== {tag} ==")
        print(f"{len(pp)} pitcher-seasons with both roles >= {MIN_BF} BF")
        for s, (m, se, n) in pooled(pp).items():
            print(f"  {s:7s} relief-minus-start {m:+.4f} (se {se:.4f}, "
                  f"n {n}, {abs(m) / se:.1f} sigma)")
        r, n = split_half_diff(pp)
        print(f"  split-half r of per-pitcher K% diff: {r:+.3f} over {n}")
        cr, cn = split_half_diff(control(pp))
        print(f"  POSITIVE control (true sd-0.03 trait): {cr:+.3f} over "
              f"{cn}")
        print()


if __name__ == "__main__":
    main()
