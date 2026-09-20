"""Classify openers by RELIEF USAGE, and score exit estimators by counting.

Operator's framing (2026-09-09): nothing says "bullpen" like almost never
pitching in the 3rd. A true opener is a late-inning reliever handed the
first inning on purpose — identifiable from his relief entry innings
BEFORE any start record exists, which the shipped gate (>= 2 prior
starts) structurally cannot do.

No simulation anywhere. Every start is scored against evidence strictly
before its own date; the pooled curves are built chronologically so
nothing later leaks in. Discrete CRPS of an empirical predictive
distribution against the observed outs, paired per start.

    venv/bin/python -m scratchpad.opener_class [--table]

`--table` prints the counted exit distribution for the population the
engine's no-record fallback fires in — opener-class starts where the arm
had fewer than `OPENER_MIN_STARTS` prior starts (rule 9: fit the curve on
the population it fires in). Paste into `game.OPENER_POOL_DIST`.
"""
import sys
from collections import Counter, defaultdict

from src.context import store

HOLDOUT = "2026-07-01"
#: Relief entries on record before usage is trusted to classify.
MIN_RELIEF = 10
#: Share of relief entries beginning in innings 1-3 above which the arm is
#: a LONG MAN (he is routinely asked for early/middle bulk), not a
#: late-inning reliever.
EARLY_SHARE = 0.15
#: The role is read off the arm's LAST N appearances, not his career —
#: the first cut classified on career history and put a 12.99-out mean on
#: the "opener" class, because a rotation regular who entered late as a
#: rookie reliever stayed an opener forever. Current role is the signal.
ROLE_WINDOW = 30
#: Relief share of the window at or above which the arm's CURRENT role is
#: the bullpen. An opener is a reliever handed the first inning; an arm
#: starting half his recent games is a swingman and classifies as neither.
RELIEF_SHARE = 0.8
#: The shipped short-yardage gate, for the population comparison.
SHORT_AVG, MIN_STARTS = 11.0, 2


def crps_emp(sample, actual):
    """CRPS of the empirical distribution given by `sample` against one
    observation. Kernel form, E|X-a| - E|X-X'|/2 — the first run of this
    file omitted the /2 (a bug inherited from `opener_score.py`, fixed
    there too) and the spread bonus alone produced a fake 15-sigma win
    for the wide pooled curve."""
    n = len(sample)
    t1 = sum(abs(d - actual) for d in sample) / n
    s = sorted(sample)
    t2 = 2 * sum((2 * i - n + 1) * v for i, v in enumerate(s)) / (n * n)
    return t1 - t2 / 2


def main():
    with store.connect() as c:
        rows = [dict(r) for r in c.execute(
            "select date, player_name nm, appearance_order ao,"
            " entry_inning ei, outs_recorded o from mlb_stints"
            " order by date")]

    # Chronological pass: per-arm history and per-class pooled curves.
    starts = defaultdict(list)      # arm -> prior start outs
    recent = defaultdict(list)      # arm -> last ROLE_WINDOW (is_start, ei)
    pool = defaultdict(list)        # class -> prior start outs (same class)
    events = []                     # one row per scoreable short start

    def classify(nm):
        w = recent[nm][-ROLE_WINDOW:]
        rel = [ei for st, ei in w if not st]
        if len(rel) < MIN_RELIEF or len(rel) / len(w) < RELIEF_SHARE:
            return None
        early = sum(1 for e in rel if e <= 3) / len(rel)
        return "opener" if early <= EARLY_SHARE else "long_man"

    for r in rows:
        nm, o = r["nm"], r["o"] or 0
        if r["ao"] != 0:
            recent[nm].append((False, r["ei"] or 9))
            continue
        cls = classify(nm)
        prior = starts[nm]
        gate = (len(prior) >= MIN_STARTS
                and sum(prior) / len(prior) < SHORT_AVG)
        if cls is not None or gate:
            events.append({
                "date": r["date"], "nm": nm, "actual": o, "cls": cls,
                "gate": gate, "n_prior": len(prior),
                "own": list(prior), "pool": list(pool[cls]) if cls else [],
            })
        if cls is not None:
            pool[cls].append(o)
        starts[nm].append(o)
        recent[nm].append((True, r["ei"] or 1))

    if "--table" in sys.argv:
        v = [e["actual"] for e in events
             if e["cls"] == "opener" and e["n_prior"] < MIN_STARTS]
        m = sum(v) / len(v)
        print(f"# {len(v)} no-record opener-class starts, mean {m:.2f}"
              f" outs, counted on all cached seasons")
        print(dict(sorted(Counter(v).items())))
        return

    # ── the classification itself ─────────────────────────────────────
    print("STARTS BY USAGE CLASS (population outs, all four seasons)")
    by = defaultdict(list)
    for e in events:
        if e["cls"]:
            by[e["cls"]].append(e["actual"])
    for cls, v in sorted(by.items()):
        m = sum(v) / len(v)
        sd = (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5
        sh9 = sum(1 for x in v if x <= 9) / len(v)
        print(f"  {cls:9s} {len(v):5d} starts  mean {m:5.2f}  sd {sd:.2f}"
              f"  share<=9 {sh9:.3f}")

    # The coverage hole: usage says opener, the shipped gate cannot fire.
    hole = [e for e in events if e["cls"] == "opener" and not e["gate"]]
    hole_thin = [e for e in hole if e["n_prior"] < MIN_STARTS]
    print(f"\nCOVERAGE HOLE: {len(hole)} opener-class starts the shipped"
          f" gate misses ({len(hole_thin)} for want of a start record);"
          f" mean actual outs {sum(e['actual'] for e in hole)/len(hole):.2f}"
          if hole else "\nCOVERAGE HOLE: none")
    # THE DECIDING SPLIT for the 311: an arm whose CURRENT role is the pen
    # but whose start record predates the demotion — does his own stale
    # record or the pooled opener curve predict tonight better?
    sub = [e for e in hole
           if len(e["own"]) >= MIN_STARTS and len(e["pool"]) >= 30]
    if sub:
        d = [crps_emp(e["own"], e["actual"])
             - crps_emp(e["pool"], e["actual"]) for e in sub]
        n = len(d)
        m = sum(d) / n
        sd = (sum((x - m) ** 2 for x in d) / (n - 1)) ** 0.5
        ao = sum(e["actual"] for e in sub) / n
        ro = sum(sum(e["own"]) / len(e["own"]) for e in sub) / n
        print(f"  of which {n} carry a record the gate trusts and the role"
              f" contradicts:")
        print(f"    record says {ro:.1f} outs, reality {ao:.1f};"
              f" own-minus-pool CRPS {m:+.3f}"
              f" (se {sd/n**0.5:.3f}, {abs(m)/(sd/n**0.5):.1f} sigma)")

    gate_only = [e for e in events if e["gate"] and e["cls"] is None]
    print(f"GATE-ONLY (no usable relief usage): {len(gate_only)} starts,"
          f" mean actual outs "
          f"{sum(e['actual'] for e in gate_only)/len(gate_only):.2f}"
          if gate_only else "GATE-ONLY: none")

    # ── scoring the estimators, own record vs pooled class curve ─────
    # Only starts where BOTH exist, so the comparison is paired.
    both = [e for e in events
            if len(e["own"]) >= MIN_STARTS and len(e["pool"]) >= 30]
    train = [e for e in both if e["date"] < HOLDOUT]
    hold = [e for e in both if e["date"] >= HOLDOUT]
    print(f"\nPAIRED SCORING: {len(both)} starts with both estimators"
          f" ({len(train)} train / {len(hold)} holdout)")

    def score(events, blend_k=None):
        out = defaultdict(list)
        for e in events:
            own, pl, a = e["own"], e["pool"], e["actual"]
            out["own"].append(crps_emp(own, a))
            out["pool"].append(crps_emp(pl, a))
            if blend_k is not None:
                w = len(own) / (len(own) + blend_k)
                reps = max(1, round(w * 100 / max(1 - w, 1e-9) / len(own)))
                mix = own * reps + pl
                out["blend"].append(crps_emp(mix, a))
        return out

    for label, ev in (("train", train), ("holdout", hold)):
        s = score(ev)
        n = len(ev)
        d = [a - b for a, b in zip(s["own"], s["pool"])]
        m = sum(d) / n
        sd = (sum((x - m) ** 2 for x in d) / (n - 1)) ** 0.5
        print(f"  {label:8s} own {sum(s['own'])/n:.3f}  pool"
              f" {sum(s['pool'])/n:.3f}  own-minus-pool {m:+.3f}"
              f" (se {sd/n**0.5:.3f}, {abs(m)/(sd/n**0.5):.1f} sigma)")

    # Blend sweep ON TRAIN ONLY, then the chosen k scored once on holdout.
    print("\n  blend sweep (train):")
    best_k, best = None, None
    for k in (1, 2, 4, 8, 16):
        s = score(train, blend_k=k)
        v = sum(s["blend"]) / len(train)
        print(f"    k={k:2d}  blend {v:.3f}")
        if best is None or v < best:
            best_k, best = k, v
    s = score(hold, blend_k=best_k)
    n = len(hold)
    d = [a - b for a, b in zip(s["blend"], s["pool"])]
    m = sum(d) / n
    sd = (sum((x - m) ** 2 for x in d) / (n - 1)) ** 0.5
    print(f"  holdout, k={best_k}: blend {sum(s['blend'])/n:.3f} against"
          f" pool {sum(s['pool'])/n:.3f}, blend-minus-pool {m:+.3f}"
          f" (se {sd/n**0.5:.3f})")


if __name__ == "__main__":
    main()
