"""How much separation could each parameter possibly buy?

THE SCREEN THAT GOES BEFORE THE WORK. Every mechanism so far has been
measured first and scored afterwards, at four hours a run, and most have
come back a wash. This asks the cheaper question first: if this parameter
were perfectly modelled per club, how far apart would two clubs' predicted
team totals actually be?

A parameter can be real, pass every stability gate, and still move nothing.
This finds those before they cost a day.

    separation = output sensitivity  x  usable club spread
    usable spread = observed club spread x reliability

Reliability, not raw spread, because a club value gets shrunk toward league
by exactly the fraction that is not real — so the deployed spread is
already smaller than the observed one. The gate number and the shrinkage
weight are the same number.

THE REFERENCE IS A MEDIAN MLB CLUB, not a replacement-level one. A bad club
produces unusual game states — early hooks, blowouts, more relief innings —
which would misreport the sensitivity of precisely the mechanisms in
question. The point is how things move around the middle of the
distribution.

COMMON RANDOM NUMBERS across every parameter state, seeded per draw, for
the same reason the prefix ladder needs it: without it the comparison
measures dice. Today that mistake produced a fake 74% improvement.

    venv/bin/python -m scratchpad.leverage [n_sims]
"""
import random
import statistics as st
import sys

from src.context import game, sim

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3000


#: Real relievers span K% 0.165 to 0.304 with sd 0.037 (game.py). The pen
#: MUST carry that spread or the screen is broken in a way that is easy to
#: miss: with a uniform staff, replacing the starter with a reliever changes
#: nothing, so every "who pitches" parameter — the hook, role, relief length
#: — reads as exactly zero leverage BY CONSTRUCTION. The first version of
#: this file did that and reported the hook at 0.000 +/- 0.000.
PEN_K_SD = 0.037


def reference(lg):
    """A median MLB matchup: league-average nine, and a REAL-SHAPED staff."""
    bat = [sim.BatterRates(name=f"b{i}", k_pct=lg["k_pct"],
                           bb_pct=lg["bb_pct"], hr_pct=lg["hr_pct"],
                           babip=lg["babip"], pa=600) for i in range(9)]
    sp = sim.PitcherRates(name="sp", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
                          hr_pct=lg["hr_pct"], babip=lg["babip"], pa=600)
    # Eight arms laid across the observed spread, best first — which is also
    # roughly how a manager reaches for them.
    offsets = [1.5, 1.0, 0.6, 0.2, -0.2, -0.6, -1.0, -1.5]
    pen = [{"name": f"r{i}",
            "k_pct": max(0.05, lg["k_pct"] + o * PEN_K_SD),
            "bb_pct": max(0.01, lg["bb_pct"] - o * PEN_K_SD * 0.25),
            "hr_pct": lg["hr_pct"], "babip": lg["babip"], "apps": 40}
           for i, o in enumerate(offsets)]
    return bat, sp, pen


def run(lg, bat, sp, pen, n_sims, seed=101, hook=None):
    """Per-DRAW runs allowed by one side at each prefix, on fixed seeds.

    Returns the vectors rather than the means so the comparison can be
    PAIRED. The effects being screened are ~0.01-0.05 runs against a
    per-draw spread near 3.0, so an unpaired mean at any affordable n_sims
    is pure noise — the same trap that produced a fake 74% improvement
    earlier today.
    """
    out = {5: [], 7: [], 9: []}
    for d in range(n_sims):
        rng = random.Random(seed + d)
        A = game.build_side(sp, pen, bat, hook, rng)
        H = game.build_side(sp, pen, bat, hook, rng)
        r = game.simulate_game(A, H, lg, rng, track=(5, 7))
        # One SIDE's runs allowed is the other team's team total.
        out[5].append(A.runs_f5)
        out[7].append(r.prefix.get(7, 0) / 2.0)
        out[9].append(A.runs)
    return out


def paired(hi, lo):
    """(half the mean swing, its standard error) per prefix."""
    res = {}
    for p in (5, 7, 9):
        d = [(a - b) / 2.0 for a, b in zip(hi[p], lo[p])]
        m = st.mean(d)
        se = st.pstdev(d) / len(d) ** 0.5 if len(d) > 1 else 0.0
        res[p] = (m, se)
    return res


def scale(table, factor):
    """Multiply every rate in a nested dict of rates."""
    if isinstance(table, dict):
        return {k: scale(v, factor) for k, v in table.items()}
    return min(0.999, max(0.0, table * factor))


#: (label, apply(delta) -> undo, observed club sd as a FRACTION of the
#: parameter, reliability). Reliability from the split-half work in
#: RESUME.md, Spearman-Brown corrected to full-season.
#:
#: `None` for spread means IT HAS NOT BEEN MEASURED — the sensitivity is
#: still reported, but the separation column cannot be, and inventing a
#: spread to fill it in would be the whole mistake this screen exists to
#: avoid.
CONSTANTS = [
    ("advancement: first->third on 1B", "FIRST_TO_THIRD_ON_1B", 0.17, 0.448),
    ("advancement: second scores on 1B", "SECOND_SCORES_ON_1B", 0.10, 0.200),
    ("advancement: first scores on 2B", "FIRST_SCORES_ON_2B", 0.12, None),
    ("double play rate", "GIDP_RATE", 0.20, 0.555),
    ("advance on an out (1B)", "ADVANCE_1B_ON_OUT", 0.15, 0.213),
    ("wild pitch / passed ball", "WP_PB_RATE", 0.20, None),
    ("reached on error", "ROE_PER_OUT", 0.20, None),
]

#: The candidates that are NOT plain sim constants — a hook parameter, the
#: quality of the arms, the shape of the contact. These are where the
#: hierarchy in AF_PLAN puts the value, so a screen that skipped them would
#: rank only the cheap half of the model.
#:
#: Spreads: the bullpen K-BB gap is MEASURED (deploy.py: .154 leading 1-3
#: against .127 down 4+, ~0.36 sd of the reliever pool). The hook and hit
#: mix spreads are NOT measured, which is itself a finding — they are the
#: two highest-leverage rows and nobody has counted how much clubs differ.
def _hook(delta):
    """Manager patience: shift the removal intercept."""
    return {"hook": sim.Hook(intercept=sim.Hook().intercept + delta)}


def _pen_quality(delta):
    """Bullpen strikeout-minus-walk quality."""
    def build(lg, bat, sp, pen):
        p = [{**a, "k_pct": a["k_pct"] * (1 + delta),
              "bb_pct": a["bb_pct"] * (1 - delta)} for a in pen]
        return {"pen": p}
    return build


def _starter_quality(delta):
    def build(lg, bat, sp, pen):
        return {"sp": sim.PitcherRates(
            name="sp", k_pct=sp.k_pct * (1 + delta),
            bb_pct=sp.bb_pct * (1 - delta), hr_pct=sp.hr_pct,
            babip=sp.babip, pa=600)}
    return build


def _hit_mix(delta):
    """Shift contact from singles toward extra bases."""
    def build(lg, bat, sp, pen):
        m = dict(lg["hit_mix"])
        shift = m["1b"] * delta
        m["1b"] -= shift
        m["2b"] += shift
        return {"lg": {**lg, "hit_mix": m}}
    return build


def _lineup_quality(delta):
    def build(lg, bat, sp, pen):
        b = [sim.BatterRates(name=x.name, k_pct=x.k_pct * (1 - delta),
                             bb_pct=x.bb_pct * (1 + delta),
                             hr_pct=x.hr_pct * (1 + delta),
                             babip=x.babip * (1 + delta * 0.3), pa=600)
             for x in bat]
        return {"bat": b}
    return build


STRUCTURAL = [
    ("HOOK: manager patience", _hook, 0.40, None),
    ("BULLPEN: arm quality (K-BB)", _pen_quality, 0.12, 0.876),
    ("STARTER: arm quality (K-BB)", _starter_quality, 0.12, None),
    ("HIT MIX: singles -> extra bases", _hit_mix, 0.10, None),
    ("LINEUP: offensive quality", _lineup_quality, 0.08, None),
]


def main():
    lg = sim.league()
    bat, sp, pen = reference(lg)
    base = run(lg, bat, sp, pen, N)
    print(f"median MLB reference, n_sims={N}")
    print(f"  baseline runs allowed per side: "
          f"F5 {st.mean(base[5]):.3f}   F7 {st.mean(base[7]):.3f}   "
          f"F9 {st.mean(base[9]):.3f}\n")
    hdr = (f"  {'parameter':<34}{'F5':>8}{'F7':>8}{'F9':>8}"
           f"{'usable':>9}{'separation':>13}{'sigma':>8}")
    print(hdr)
    rows = []

    def emit(label, hi, lo, usable):
        d = paired(hi, lo)
        m9, se9 = d[9]
        sig = abs(m9) / se9 if se9 else 0.0
        sep = f"{abs(m9) * 2:.3f}" if usable else "spread?"
        if usable and sig < 2.0:
            sep += " ?"
        u = f"{usable:.3f}" if usable else "--"
        print(f"  {label:<34}"
              + "".join(f"{d[p][0]:>+8.3f}" for p in (5, 7, 9))
              + f"{u:>9}{sep:>13}{sig:>+8.1f}")
        rows.append((label, abs(m9) * 2 if usable else None, sig))

    for label, name, sd, rel in CONSTANTS:
        orig = getattr(sim, name)
        usable = (sd * rel) if (sd is not None and rel is not None) else None
        bump = usable if usable else (sd or 0.10)
        setattr(sim, name, scale(orig, 1.0 + bump))
        hi = run(lg, bat, sp, pen, N)
        setattr(sim, name, scale(orig, 1.0 - bump))
        lo = run(lg, bat, sp, pen, N)
        setattr(sim, name, orig)
        emit(label, hi, lo, usable)

    print()
    for label, fn, sd, rel in STRUCTURAL:
        usable = (sd * rel) if (sd is not None and rel is not None) else None
        bump = usable if usable else (sd or 0.10)
        out = {}
        for sign, key in ((+1, "hi"), (-1, "lo")):
            spec = fn(sign * bump)
            over = spec(lg, bat, sp, pen) if callable(spec) else spec
            out[key] = run(over.get("lg", lg), over.get("bat", bat),
                           over.get("sp", sp), over.get("pen", pen), N,
                           hook=over.get("hook"))
        emit(label, out["hi"], out["lo"], usable)

    print("\n  'separation' is the 10th-to-90th-percentile gap in predicted")
    print("  team total this parameter could produce if modelled perfectly")
    print("  per club. Under ~0.05 runs it cannot matter however real it is.")
    print("  A trailing '?' means the swing is not resolved above the noise.")
    print("\n  RANKED by separation, resolved rows only:")
    for label, sep, sig in sorted(
            [r for r in rows if r[1] and r[2] >= 2.0],
            key=lambda r: -r[1]):
        print(f"    {sep:>6.3f}  {label}")
    unmeasured = [r[0] for r in rows if r[1] is None and r[2] >= 2.0]
    if unmeasured:
        print("\n  HAS LEVERAGE, CLUB SPREAD NEVER MEASURED — measure these:")
        for label in unmeasured:
            print(f"    {label}")

    print("\n  CAVEATS. Screens LEVERAGE, not correctness. Parameters")
    print("  interact, so this is a ranking and not an additive budget.")


if __name__ == "__main__":
    main()
