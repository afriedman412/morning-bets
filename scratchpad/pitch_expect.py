"""STEP TWO — did his stuff get the outcome it deserved, and does either
half of that question repeat?

    venv/bin/python -m scratchpad.pitch_expect --pitcher "Dylan Cease"

For every pitch a starter threw, E0 (`scratchpad/pitch_e0.py`) gives the
league's counted P(ball/called/whiff/foul/inplay) for that pitch type, in
that count, in that region of the batter's own zone. Summed over a start
that is what his pitch selection and location DESERVED; beside it sits
what he actually got.

THE MEASUREMENT THAT DECIDES WHETHER ANY OF THIS IS USABLE, and it is
pre-registered in PLAN-pitch-expectation before being run — split each
start's pitches odd/even and correlate the halves across his starts, for
both:

    (b) THE EXPECTATION — is "what tonight's pitches deserved" a stable
        per-start read? Predicted RELIABLE: it is built from pitch type
        and location, and the physicals underneath measured 0.8-0.99.
    (a) THE RESIDUAL, actual minus expected — is out-performing your
        stuff a repeatable trait? Predicted NOISE: it is whiff% with the
        good part subtracted, and raw per-start whiff% already measured
        r ~ 0 (`pitch_one.py`).

If (a) comes back reliable it is a deception/sequencing channel nothing
in the engine carries and it jumps the queue. If (b) is reliable and (a)
is not, the usable object is the EXPECTATION, and the screen that
follows asks whether its drift predicts the next start.

SPLIT BY PLATE APPEARANCE, NOT BY PITCH, and this was bought with a
wrong answer on 2026-09-07. Splitting a start's pitches odd/even biases
the two halves' COUNT composition against each other — every PA's first
pitch is 0-0, so when one half catches more first pitches the other
catches fewer, and any count-dependent quantity see-saws. Expected
called-strike per pitch read r = -0.65 that way. A negative split-half
correlation is not a weak result, it is a broken denominator, and the
fix is to split on PA index so each half is a random sample of whole
at-bats with their count structure intact.

THE POSITIVE CONTROL RUNS THROUGH THE SPLIT, which is the other half of
the same lesson. The first version planted a signal directly on
start-level values and confirmed r ~ 1 — it passed happily while the
splitting scheme underneath was corrupting every real number, because it
never touched the split. A control that skips the step being tested
cannot fail. This one plants a per-start effect on the PITCH rows and
lets the real splitter, the real aggregator and the real correlator see
it, exactly as CLAUDE.md's "a mis-specified mechanism and an absent
effect look identical" rule demands.

SELF-REFERENCE, stated rather than hidden: E0's train half counted every
pitcher including this one, so a starter's own ~2,500 pitches are ~0.1%
of the table he is scored against. That is far too small to manufacture
agreement, and it cannot affect a split-half correlation at all — but a
future per-pitcher rung must leave-one-out, and this note is where that
requirement is recorded.
"""
from __future__ import annotations

import argparse
import statistics as st

import numpy as np

from scratchpad import pitch_e0, pitch_walk

MIN_HALF = 15                    # pitches per half for a start to count


def halves(rows, by="pa"):
    """Split one start in two. `by='pa'` keeps whole plate appearances
    together (correct); `by='pitch'` is the biased alternate, kept so the
    artifact can be reproduced on demand rather than described."""
    if by == "pitch":
        return rows[0::2], rows[1::2]
    return ([r for r in rows if r["pa"] % 2 == 0],
            [r for r in rows if r["pa"] % 2 == 1])


def expectation(rows, p):
    """Attach E0's per-pitch probabilities. Returns (kept, n_missing)."""
    kept, miss = [], 0
    for r in rows:
        fam = pitch_e0.FAMILY.get(r["type"], "OTH" if r["type"] else None)
        reg = pitch_e0.region_of(r["px"], r["pz"], r.get("sz_top"),
                                 r.get("sz_bot"))
        key = (fam, r["balls"], r["strikes"], reg)
        cell = p.get(key)
        if cell is None or r["outcome"] == "other":
            miss += 1
            continue
        kept.append({**r, "p": cell})
    return kept, miss


def totals(rows):
    """Actual and expected counts of each outcome over a bag of pitches."""
    out = {"n": len(rows)}
    for o in pitch_e0.OUTCOMES:
        out[f"a_{o}"] = sum(1 for r in rows if r["outcome"] == o)
        out[f"e_{o}"] = sum(r["p"][o] for r in rows)
    # per-swing views: the denominator a whiff rate actually has
    a_sw = out["a_whiff"] + out["a_foul"] + out["a_inplay"]
    e_sw = out["e_whiff"] + out["e_foul"] + out["e_inplay"]
    out["a_swing"], out["e_swing"] = a_sw, e_sw
    out["a_wps"] = out["a_whiff"] / a_sw if a_sw else None
    out["e_wps"] = out["e_whiff"] / e_sw if e_sw else None
    return out


def r_of(a, b):
    if len(a) < 8 or np.std(a) == 0 or np.std(b) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def sb(r):
    return 2 * r / (1 + r) if r is not None and r > -1 else None


def negative_control(starts, split_by, rng, reps=40):
    """WHAT DOES THIS HARNESS RETURN WHEN THERE IS NO SIGNAL? Pool every
    pitch of the season and deal it back out into starts of the same
    sizes, so between-start variation is destroyed by construction and
    only within-start sampling remains. Any quantity's r here is the
    harness's own baseline; a real reading must be judged against IT, not
    against zero.

    This exists because expected-called/pitch read -0.41 after the PA fix
    and 'negative means broken' is an assumption, not a measurement. A
    null is a claim (CLAUDE.md) and this is the claim's test."""
    pool = [r for s in starts for r in s["rows"]]
    sizes = [len(s["rows"]) for s in starts]
    keys = {
        "e_whiff/p": lambda t: t["e_whiff"] / t["n"],
        "e_called/p": lambda t: t["e_called"] / t["n"],
        "e_ball/p": lambda t: t["e_ball"] / t["n"],
        "a_wps": lambda t: t["a_wps"],
        "resid_whiff/p": lambda t: (t["a_whiff"] - t["e_whiff"]) / t["n"],
    }
    acc: dict = {k: [] for k in keys}
    for _ in range(reps):
        idx = rng.permutation(len(pool))
        at, fakes = 0, []
        for n in sizes:
            take = [pool[i] for i in idx[at:at + n]]
            at += n
            # re-index PAs so the PA splitter has something to split on;
            # the shuffle destroyed real PA structure, which is the point
            for j, r in enumerate(take):
                r = dict(r)
                r["pa"] = j // 4
                take[j] = r
            fakes.append(take)
        for k, fn in keys.items():
            a, b = [], []
            for rows in fakes:
                x, y = halves(rows, split_by)
                if len(x) < MIN_HALF or len(y) < MIN_HALF:
                    continue
                vx, vy = fn(totals(x)), fn(totals(y))
                if vx is not None and vy is not None:
                    a.append(vx)
                    b.append(vy)
            r = r_of(a, b)
            if r is not None:
                acc[k].append(r)
    return {k: (float(np.mean(v)), float(np.std(v))) for k, v in acc.items()
            if v}


def control(starts, split_by, rng):
    """Plant a per-start effect on the PITCH rows and push it through the
    real splitter/aggregator/correlator. Returns (r_planted, r_noise)."""
    lvl = rng.normal(0, 1, len(starts))
    planted, noise = [], []
    for i, s in enumerate(starts):
        # a start where the stuff really was better: every pitch's whiff
        # probability lifted by the same per-start amount
        rows = [{**r, "p": {**r["p"], "whiff": min(max(
            r["p"]["whiff"] + 0.06 * lvl[i], 0.001), 0.99)}}
            for r in s["rows"]]
        a, b = halves(rows, split_by)
        if len(a) < MIN_HALF or len(b) < MIN_HALF:
            continue
        planted.append((totals(a)["e_whiff"] / len(a),
                        totals(b)["e_whiff"] / len(b)))
        noise.append((rng.normal(), rng.normal()))
    r_p = r_of([x for x, _ in planted], [y for _, y in planted])
    r_n = r_of([x for x, _ in noise], [y for _, y in noise])
    return r_p, r_n, len(planted)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pitcher", default="Dylan Cease")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--split", default="pa", choices=("pa", "pitch"),
                    help="'pitch' reproduces the count-composition bias")
    args = ap.parse_args()

    p, _ = pitch_e0.probs(pitch_e0.load(split="train"))
    gs = pitch_walk.games_for(args.pitcher, args.season)
    print(f"  {args.pitcher} {args.season}: {len(gs)} starts; "
          f"E0 train table has {len(p)} cells")

    starts, miss_tot, n_tot = [], 0, 0
    for g in gs:
        raw = pitch_walk.pitches(g["gid"], args.pitcher)
        if not raw:
            continue
        rows, miss = expectation(raw, p)
        miss_tot += miss
        n_tot += len(raw)
        if len(rows) < 2 * MIN_HALF:
            continue
        a, b = halves(rows, args.split)
        if len(a) < MIN_HALF or len(b) < MIN_HALF:
            continue
        starts.append({"date": g["d"], "k": g["k"], "bb": g["bb"],
                       "outs": g["outs"], "rows": rows,
                       "all": totals(rows),
                       "odd": totals(a), "even": totals(b)})
    print(f"  {len(starts)} starts scored; {n_tot - miss_tot:,}/{n_tot:,} "
          f"pitches matched a cell ({1 - miss_tot / n_tot:.1%}) "
          f"<- read nothing before this is high\n")

    print(f"  {'date':<12}{'n':>4}{'sw a':>6}{'sw e':>6}{'whf a':>7}"
          f"{'whf e':>7}{'diff':>7}{'cs a':>6}{'cs e':>6}{'bb a':>6}"
          f"{'bb e':>6}  {'K':>2}{'BB':>3}")
    for s in starts:
        t = s["all"]
        print(f"  {s['date']:<12}{t['n']:>4}{t['a_swing']:>6.0f}"
              f"{t['e_swing']:>6.1f}{t['a_whiff']:>7.0f}{t['e_whiff']:>7.1f}"
              f"{t['a_whiff'] - t['e_whiff']:>+7.1f}"
              f"{t['a_called']:>6.0f}{t['e_called']:>6.1f}"
              f"{t['a_ball']:>6.0f}{t['e_ball']:>6.1f}  "
              f"{s['k']:>2}{s['bb']:>3}")

    # CALIBRATION FIRST: if E0 is biased on this pitcher the residual is
    # not a residual, it is an offset, and every reliability number below
    # would be measuring the same constant twice.
    print("\n  === E0 CALIBRATION over the season (actual vs expected) ===")
    for o in pitch_e0.OUTCOMES:
        a = sum(s["all"][f"a_{o}"] for s in starts)
        e = sum(s["all"][f"e_{o}"] for s in starts)
        n = sum(s["all"]["n"] for s in starts)
        se = (e * (1 - e / n)) ** 0.5      # binomial on the expectation
        print(f"    {o:<8}actual {a:>6}  expected {e:>8.1f}  "
              f"diff {a - e:>+7.1f} ({(a - e) / se:>+5.1f} se)")

    # POSITIVE CONTROL, THROUGH THE REAL SPLIT — see the module docstring.
    rng = np.random.default_rng(7)
    hi, nz, n_c = control(starts, args.split, rng)
    ok = hi is not None and hi > 0.7 and abs(nz) < 2 / max(n_c, 1) ** 0.5
    print(f"\n  CONTROL through the '{args.split}' split (n={n_c}): "
          f"planted r={hi:+.2f}, noise r={nz:+.2f}  "
          f"{'SEEN' if ok else '** HARNESS BROKEN **'}")

    neg = negative_control(starts, args.split, rng)
    print(f"  NEGATIVE CONTROL (pitches reshuffled across starts, 40 reps"
          f" — the harness's no-signal baseline):")
    for k, (m, sd) in neg.items():
        print(f"    {k:<16}{m:+.2f} ± {sd:.2f}")

    print(f"\n  === SPLIT-HALF RELIABILITY (split by {args.split.upper()},"
          f" se(r)~{1 / max(len(starts) - 3, 1) ** 0.5:.2f} at r=0) ===")
    print(f"  {'quantity':<34}{'r':>7}{'SB':>7}{'n':>5}")

    def show(label, fn):
        a = [fn(s["odd"]) for s in starts]
        b = [fn(s["even"]) for s in starts]
        pairs = [(x, y) for x, y in zip(a, b)
                 if x is not None and y is not None]
        if len(pairs) < 8:
            print(f"  {label:<34}{'--':>7}{'':>7}{len(pairs):>5}")
            return
        r = r_of([x for x, _ in pairs], [y for _, y in pairs])
        s_ = sb(r)
        print(f"  {label:<34}{r:>+7.2f}"
              f"{(f'{s_:+.2f}' if s_ is not None else '--'):>7}"
              f"{len(pairs):>5}")

    # (b) THE EXPECTATION — what tonight's pitches deserved
    show("(b) expected whiff / pitch", lambda t: t["e_whiff"] / t["n"])
    show("(b) expected swing / pitch", lambda t: t["e_swing"] / t["n"])
    show("(b) expected whiff / swing", lambda t: t["e_wps"])
    show("(b) expected called / pitch", lambda t: t["e_called"] / t["n"])
    show("(b) expected ball / pitch", lambda t: t["e_ball"] / t["n"])
    # the raw outcome, for the comparison that makes (b) mean something
    show("    ACTUAL whiff / swing (raw)", lambda t: t["a_wps"])
    show("    ACTUAL ball / pitch (raw)", lambda t: t["a_ball"] / t["n"])
    # (a) THE RESIDUAL — did he beat what he deserved
    show("(a) whiff resid / pitch",
         lambda t: (t["a_whiff"] - t["e_whiff"]) / t["n"])
    show("(a) swing resid / pitch",
         lambda t: (t["a_swing"] - t["e_swing"]) / t["n"])
    show("(a) called resid / pitch",
         lambda t: (t["a_called"] - t["e_called"]) / t["n"])
    show("(a) ball resid / pitch",
         lambda t: (t["a_ball"] - t["e_ball"]) / t["n"])

    # WHAT THE EXPECTATION IS MADE OF, so a reliable (b) can be read: is
    # it his pitch MIX repeating, or where he located within a type?
    print("\n  === WHAT DRIVES THE EXPECTATION (season shares) ===")
    mix = {}
    for s in starts:
        for r in s["rows"]:
            fam = pitch_e0.FAMILY.get(r["type"], "OTH")
            m = mix.setdefault(fam, [0, 0])
            m[0] += 1
            m[1] += r["p"]["whiff"]
    tot = sum(m[0] for m in mix.values())
    print(f"  {'fam':<6}{'usage':>8}{'exp whf/pitch':>15}")
    for f, m in sorted(mix.items(), key=lambda kv: -kv[1][0]):
        print(f"  {f:<6}{m[0] / tot:>8.1%}{m[1] / m[0]:>15.3f}")
    reg = {}
    for s in starts:
        for r in s["rows"]:
            g = pitch_e0.region_of(r["px"], r["pz"], None, None)
            reg[g] = reg.get(g, 0) + 1
    print("  regions: " + "  ".join(
        f"{k}:{v / tot:.1%}" for k, v in sorted(reg.items(),
                                                key=lambda kv: -kv[1])))
    print(f"\n  season expected whiff/swing "
          f"{st.mean(s['all']['e_wps'] for s in starts):.3f}  actual "
          f"{st.mean(s['all']['a_wps'] for s in starts):.3f}")


if __name__ == "__main__":
    main()
