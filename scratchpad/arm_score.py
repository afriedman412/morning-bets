"""DOES THE PER-ARM HOOK OFFSET TELL STARTS APART? — TODO 32's falsifier.

    venv/bin/python -m scratchpad.arm_score [n_sims] [--season 2026]
                                            [--limit N] [--leash-off]

WHY THIS EXISTS BESIDE THE BATTERY. The battery scores everything and takes
a full pass per fold; this scores the ONE quantity the mechanism targets, on
one fold, so a dead mechanism is found in minutes rather than after four
folds of everything else. The battery still runs afterwards — this does not
replace it, it decides whether it is worth running.

THE PRE-REGISTERED ROW, quoted from the item so it cannot drift: "NAME THE
ROW BEFORE RUNNING: the per-start outs CORRELATION (the number `leash.py`
moved +0.105 -> +0.226 out of sample) and `boundary_share_by_decision`."
And the caveat the item attaches: `leash.py` already records that a per-arm
term is FLAT on outs CRPS and the run ladder BY DESIGN — it buys
discrimination BETWEEN starts, not a better-shaped average start — so the
ladder and `outs_mean` are NOT the rows and a flat ladder is not evidence
either way.

THE CEILING IS REPORTED WITH THE CORRELATION, because a correlation with no
ceiling is unreadable. If actual outs = this arm's own central tendency plus
a night's noise, the best any per-arm predictor can do is the arm mean, and
its correlation with the actual is sd_between / sd_total. That is computed
model-free from the ACTUAL outs by a one-way ANOVA with sampling noise
removed, exactly as `battery._corr_ceiling` does it.

PAIRED SEEDS. The same (game, draw) seed in both states, so a start's two
outs distributions differ only by the flag. Unpaired, the se on a 1,300-
start correlation swamps the effect this is looking for.

THE POPULATION SPLIT IS THE POINT, and it is the dilution rule from
CLAUDE.md made concrete: the offsets cover about 350 arms, and a start by an
arm with NO entry cannot move however right the mechanism is. So the
correlation is reported three ways — every start, starts whose arm HAS an
entry, and starts whose arm does not. The third is the control: it must not
move, and if it does the wiring is leaking.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import random
import statistics as st
import sys
import zlib
from collections import defaultdict

from src.context import armhook, calibrate as cal, sim
from src.context.holdout import HOLDOUT
from src.context.sources import rates as rate_src

_CASES: dict = {}
_PENS: dict = {}
_SIMS = 24
_ARM_ON = False
_LEASH = True
_CONTROL_LEASH = False
_MECH = "arm"


def _corr(pairs):
    n = len(pairs)
    if n < 3:
        return 0.0
    mx = sum(x for x, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    num = sum((x - mx) * (y - my) for x, y in pairs)
    dx = sum((x - mx) ** 2 for x, _ in pairs) ** 0.5
    dy = sum((y - my) ** 2 for _, y in pairs) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def _ceiling(by_arm):
    by = {u: v for u, v in by_arm.items() if u and len(v) >= 2}
    if len(by) < 3:
        return None
    n = sum(len(v) for v in by.values())
    k = len(by)
    if n == k:
        return None
    grand = sum(sum(v) for v in by.values()) / n
    ssb = sum(len(v) * (st.mean(v) - grand) ** 2 for v in by.values())
    ssw = sum(sum((x - st.mean(v)) ** 2 for x in v) for v in by.values())
    msb, msw = ssb / (k - 1), ssw / (n - k)
    n0 = (n - sum(len(v) ** 2 for v in by.values()) / n) / (k - 1)
    between = max((msb - msw) / n0, 0.0)
    total = between + max(msw, 1e-9)
    return (between / total) ** 0.5


def _one(gid):
    """(name, actual outs, model mean outs, boundary share) per side."""
    # WHICH mechanism is being switched. `eff` is TODO 34's per-pitcher pitch
    # efficiency, which enters upstream of the hook rather than in it.
    if _MECH == "eff":
        sim.USE_PITCH_EFF = _ARM_ON
    else:
        sim.USE_ARM_HOOK = _ARM_ON
    sim.USE_LEASH = _LEASH
    sim.reload_offsets()
    pair = _CASES[gid]
    lg = sim.league()
    out = []
    draws = []
    for d in range(_SIMS):
        # Seed on a crc32 of (game, draw) so adding or dropping a game
        # cannot shift any other game's stream — the battery's rule.
        rng = random.Random(zlib.crc32(f"{gid}|{d}".encode()))
        draws.append(cal.replay(pair, lg, _PENS, rng))
    for idx, side in ((0, "away_sp"), (1, "home_sp")):
        s = pair[idx][0]
        outs = [getattr(g, side).outs for g in draws]
        out.append((s["player_name"], s.get("o"), st.mean(outs)))
    return out


def _init(cases, pens, sims, arm_on, leash_on, mech="arm"):
    global _CASES, _PENS, _SIMS, _ARM_ON, _LEASH, _MECH
    _CASES, _PENS, _SIMS, _ARM_ON, _LEASH = cases, pens, sims, arm_on, leash_on
    _MECH = mech


def run(season: int, sims: int, limit: int | None, leash_on: bool) -> None:
    cases = cal.paired_cases(season=season, since=HOLDOUT,
                             rates_before=HOLDOUT)
    gids = sorted(cases)
    if limit:
        gids = gids[:limit]
    cases = {g: cases[g] for g in gids}
    pens = rate_src.bullpens(sim.league(), before=HOLDOUT)
    tbl = armhook._load(armhook.PATH) if hasattr(armhook, "_load") else None
    if tbl is None:
        with open(armhook.PATH) as f:
            tbl = json.load(f)
    has = set(tbl.get("bnd") or {}) | set(tbl.get("mid") or {})
    if _MECH == "eff":
        from src.context import efficiency
        with open(efficiency.PATH) as f:
            has = set((json.load(f).get("mult") or {}))
    if _CONTROL_LEASH:
        # In control mode the mechanism being switched is the LEASH, so the
        # population that can move is the one IT covers. Reusing the arm
        # table's names here would label the rows with the wrong cohort and
        # make a real control effect look diluted.
        with open(sim._LEASH_PATH) as f:
            has = {k for k in json.load(f) if k != "_meta"}
    print(f"  {len(gids)} games x {sims} draws x 2 states   "
          f"{len(has)} arms carry an offset   leash "
          f"{'ON' if leash_on else 'OFF'}")

    # THE POSITIVE CONTROL (rule 7), and it is the whole reason this
    # instrument can report a null. `--control-leash` swaps the thing being
    # switched: state A is the engine with NO per-arm term at all, state B
    # is the engine with the SHIPPED LEASH. `leash.py` records that change
    # as +0.105 -> +0.226 out of sample, so a harness that cannot see it
    # cannot see anything of that kind and no null from it is reportable.
    # A mis-specified screen and an absent effect look identical.
    if _CONTROL_LEASH:
        plan = (("leash OFF", False, False), ("leash ON", False, True))
    else:
        plan = (("flag OFF", False, leash_on), ("flag ON", True, leash_on))

    states = {}
    for label, arm_on, l_on in plan:
        ctx = mp.get_context("fork")
        with ctx.Pool(max(1, (os.cpu_count() or 4) - 2), initializer=_init,
                      initargs=(cases, pens, sims, arm_on, l_on,
                                _MECH)) as pool:
            rows = pool.map(_one, gids, chunksize=8)
        flat = [x for r in rows for x in r if x[1] is not None]
        states[label] = flat
        print(f"  {label}: {len(flat)} starts simulated")

    (la, _, _), (lb, _, _) = plan
    base = {(nm, i): (a, m) for i, (nm, a, m) in enumerate(states[la])}
    on = {(nm, i): (a, m) for i, (nm, a, m) in enumerate(states[lb])}
    keys = [k for k in base if k in on]

    lab_a, lab_b = la, lb
    print(f"\n  {'population':<22}{'n':>7}{'corr ' + lab_a.split()[-1]:>10}{'corr ' + lab_b.split()[-1]:>10}"
          f"{'delta':>9}{'ceiling':>9}{'se':>8}{'z':>7}")
    print("  (se and z are on the DELTA, paired bootstrap over starts)")
    for label, pick in (
            ("every start", lambda nm: True),
            ("arm HAS an offset", lambda nm: nm in has),
            ("no offset (control)", lambda nm: nm not in has)):
        ks = [k for k in keys if pick(k[0])]
        if len(ks) < 30:
            print(f"  {label:<22}{len(ks):>7}   too few — not reported")
            continue
        p_off = [(base[k][1], base[k][0]) for k in ks]
        p_on = [(on[k][1], on[k][0]) for k in ks]
        by_arm = defaultdict(list)
        for k in ks:
            by_arm[k[0]].append(base[k][0])
        c_off, c_on = _corr(p_off), _corr(p_on)
        ceil = _ceiling(by_arm)
        # THE SE OF THE DELTA, BY PAIRED BOOTSTRAP, and it is not the se of
        # either correlation. Both are computed on the SAME starts against
        # the SAME actuals from predictions that differ only by the flag, so
        # they are correlated to about 0.99 and the marginal se — 1/sqrt(n-3)
        # — overstates the noise on their difference by an order of
        # magnitude. Resampling STARTS (not draws) keeps the pairing: each
        # resample recomputes both correlations on the same index set.
        rng = random.Random(11)
        n = len(ks)
        ds = []
        for _ in range(2000):
            idx = [rng.randrange(n) for _ in range(n)]
            ds.append(_corr([p_on[i] for i in idx])
                      - _corr([p_off[i] for i in idx]))
        se = st.pstdev(ds)
        print(f"  {label:<22}{len(ks):>7}{c_off:>+10.4f}{c_on:>+10.4f}"
              f"{c_on - c_off:>+9.4f}"
              f"{(ceil if ceil is not None else float('nan')):>9.4f}{se:>8.4f}"
              f"{(c_on - c_off) / se if se else 0:>+7.1f}")

    # The level rows, which the item says are NOT the falsifier but must be
    # reported anyway: a per-arm term is centred and a level move means the
    # centring is wrong.
    for label, d in (("OFF", base), ("ON", on)):
        ms = [d[k][1] for k in keys]
        print(f"  mean model outs {label:<4}{st.mean(ms):>8.3f}   "
              f"sd {st.pstdev(ms):.3f}")
    print(f"  mean ACTUAL outs     {st.mean([base[k][0] for k in keys]):>8.3f}"
          f"   sd {st.pstdev([base[k][0] for k in keys]):.3f}")


def main() -> None:
    args = sys.argv[1:]
    pos = [a for a in args if not a.startswith("-")]
    sims = int(pos[0]) if pos else 24
    season = int(args[args.index("--season") + 1]) \
        if "--season" in args else 2026
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    global _CONTROL_LEASH, _MECH
    _CONTROL_LEASH = "--control-leash" in args
    _MECH = args[args.index("--mech") + 1] if "--mech" in args else "arm"
    run(season, sims, limit, leash_on="--leash-off" not in args)


if __name__ == "__main__":
    main()
