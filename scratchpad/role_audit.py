"""Every run-producing constant, re-counted SPLIT BY ROLE.

    venv/bin/python -m scratchpad.role_audit [workers]

THE PATTERN THIS CHASES. Three constants were found on 2026-08-27 that had
been measured on STARTERS from boxscores and then applied to every arm in
the game — `HBP_RATE` (relievers +21-34%), `SAC_RATE` (+43%) and
`WP_PB_RATE` (+32% pooled). Three for three, all wrong the same way, and the
last one closed a fifth of the F5 run gap on its own.

The rest of the constants were never checked for it. This checks them.

WHY IT SHOULD BITE HERE TOO. Relief innings are not starter innings: they
are later, the score is tighter, the defence is positioned differently, and
the runners on base are being held by a different kind of pitcher. Anything
counted over "innings" without asking WHOSE innings inherits that mix.

MEASURED, with the same denominators the simulator actually uses — getting
that wrong is how the wild-pitch rate was first mis-stated today:

  SB / CS        per plate appearance with a runner on FIRST and SECOND
                 EMPTY, which is the only state `sim.baserunning` rolls in.
  first->third   of singles with a runner on first, by OUTS BEFORE.
  second scores  of singles with a runner on second, by outs before.
  advance on out of ball-in-play OUTS with a runner on, by outs before.

Base state is reconstructed by `pbp.plays`, which yields the state BEFORE
each play. The `matchup.postOn*` fields are the state AFTER and reading them
as "before" is the same misreading that mislabelled 27,401 inning endings
earlier in this project.
"""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

from src import db
from src.context import sim
from src.context.sources import pbp

_BIP_OUT = ("field_out", "force_out", "fielders_choice_out",
            "grounded_into_double_play", "double_play", "triple_play")


_YEAR = ["?"]


def scan(short: str):
    """Counters keyed (role, metric, outs) -> [numerator, denominator]."""
    try:
        d = pbp.fetch(short)
    except Exception:
        return None
    if not d:
        return None
    out = defaultdict(lambda: [0, 0])
    first = {}
    for play, bases, outs, _a, _h in pbp.plays(short, d):
        ab = play.get("about") or {}
        mu = play.get("matchup") or {}
        res = play.get("result") or {}
        pid = (mu.get("pitcher") or {}).get("id")
        if not pid:
            continue
        side = "home" if ab.get("isTopInning") else "away"
        first.setdefault(side, pid)
        role = "SP" if first[side] == pid else "RP"
        # Pooled and per-season. Steal rates moved sharply with the 2023
        # rule changes (bigger bases, pickoff limits), so a four-season
        # pool would average across two different games. Standing rule
        # here: gate on the era before pooling.
        yr = _YEAR[0]
        ev = res.get("eventType") or ""
        runners = play.get("runners") or []

        # `pbp.resolve` collapses a runner's MULTIPLE records into where he
        # actually ended up. Taking the first record and breaking — the
        # obvious hand-rolled version — reports a runner going first to
        # third as having stopped at second, because that advance is written
        # as 1B->2B followed by 2B->3B. Measured: it found 2 first-to-thirds
        # in 557 singles against a real rate near 0.30.
        final, _order = pbp.resolve(runners)

        # 1. STEAL OPPORTUNITY — the exact state `sim.baserunning` rolls in.
        if bases[0] and not bases[1]:
            out[("ALL", f"steal_{yr}", 0)][1] += 1
            out[("ALL", f"cs_{yr}", 0)][1] += 1
            for r in runners:
                e = ((r.get("details") or {}).get("event") or "")
                if e.startswith("Stolen Base"):
                    out[("ALL", f"steal_{yr}", 0)][0] += 1
                elif e.startswith("Caught Stealing"):
                    out[("ALL", f"cs_{yr}", 0)][0] += 1
            out[(role, "steal", 0)][1] += 1
            for r in runners:
                e = ((r.get("details") or {}).get("event") or "")
                if e.startswith("Stolen Base"):
                    out[(role, "steal", 0)][0] += 1
                elif e.startswith("Caught Stealing") or "Caught Stealing" in e:
                    out[(role, "cs", 0)][0] += 1
                    out[(role, "cs", 0)][1] += 0
        if bases[0] and not bases[1]:
            out[(role, "cs", 0)][1] += 1

        # 1b. WHERE STEALS ACTUALLY HAPPEN. `sim.baserunning` rolls only
        #     when first is occupied and second is EMPTY, so any steal from
        #     another state is unreachable by the model at ANY rate. When a
        #     parameter cannot reach the target the mechanism is missing
        #     rather than mistuned — the standing diagnostic here.
        for r in runners:
            e = ((r.get("details") or {}).get("event") or "")
            if not (e.startswith("Stolen Base")
                    or e.startswith("Caught Stealing")):
                continue
            key = ("MODELLED" if (bases[0] and not bases[1])
                   else "unreachable")
            out[("ALL", "steal_state_" + key, 0)][0] += 1
            out[("ALL", "steal_state_" + key, 0)][1] += 1

        # 2. ADVANCEMENT ON A SINGLE, by outs before the play.
        if ev == "single":
            if bases[0]:
                out[(role, "first_to_third", outs)][1] += 1
                for _rid, (st_, en_, is_out_) in final.items():
                    if st_ == "1B" and not is_out_:
                        if en_ in ("3B", "score"):
                            out[(role, "first_to_third", outs)][0] += 1
                        break
            if bases[1]:
                out[(role, "second_scores", outs)][1] += 1
                for _rid, (st_, en_, is_out_) in final.items():
                    if st_ == "2B" and not is_out_:
                        if en_ == "score":
                            out[(role, "second_scores", outs)][0] += 1
                        break

        # 3. RUNNER ADVANCES ON A BALL-IN-PLAY OUT.
        if ev in _BIP_OUT and any(bases) and outs < 2:
            out[(role, "adv_on_out", outs)][1] += 1
            for _rid, (st_, en_, is_out_) in final.items():
                if st_ in ("1B", "2B") and not is_out_ and en_ not in (st_,):
                    if en_ in ("2B", "3B", "score"):
                        out[(role, "adv_on_out", outs)][0] += 1
                        break
    return {f"{a}|{b}|{c}": v for (a, b, c), v in out.items()}


def _scan_year(arg):
    short, yr = arg
    _YEAR[0] = yr
    return scan(short)


def main(argv):
    """`--season 2026` for ITERATION, no argument for the era gate.

    One season is ~2,000 games against 9,962 and runs in a quarter the time.
    Three full four-season scans were spent debugging extraction on
    2026-08-27; every one of those would have been a one-season run. Use the
    full set only when the question is whether something moved between eras.
    """
    season = None
    if argv and argv[0] == "--season":
        season, argv = argv[1], argv[2:]
    workers = int(argv[0]) if argv else 8
    with db.connect() as c:
        dates = {r["game_id"]: r["date"] for r in
                 c.execute("select game_id, date from games"
                           " where sport = 'mlb'")}
    todo = sorted(g for g in dates if pbp.have(g.split("-")[-1])
                  and (season is None or dates[g].startswith(season)))
    print(f"  scanning {len(todo):,} games on {workers} workers ...",
          flush=True)
    acc = defaultdict(lambda: [0, 0])
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for got in ex.map(_scan_year,
                          [(g.split("-")[-1], dates[g][:4]) for g in todo],
                          chunksize=32):
            if not got:
                continue
            for k, v in got.items():
                c = acc[k]
                c[0] += v[0]
                c[1] += v[1]

    def rate(role, metric, outs=0):
        n, d = acc.get(f"{role}|{metric}|{outs}", [0, 0])
        return (n / d if d else None), d

    print(f"\n  {'constant':<22}{'outs':>5}{'shipped':>10}{'SP':>10}"
          f"{'RP':>10}{'RP/SP':>8}{'n(RP)':>9}")

    rows = [
        ("SB_RATE", "steal", [0], sim.SB_RATE),
        ("CS_RATE", "cs", [0], sim.CS_RATE),
        ("FIRST_TO_THIRD_ON_1B", "first_to_third", [0, 1, 2], None),
        ("SECOND_SCORES_ON_1B", "second_scores", [0, 1, 2], None),
        ("RUNNER_ADVANCES_ON_OUT", "adv_on_out", [0, 1], None),
    ]
    tables = {"FIRST_TO_THIRD_ON_1B": sim.FIRST_TO_THIRD_ON_1B,
              "SECOND_SCORES_ON_1B": sim.SECOND_SCORES_ON_1B,
              "RUNNER_ADVANCES_ON_OUT": sim.RUNNER_ADVANCES_ON_OUT}
    for name, metric, outs_list, flat in rows:
        for o in outs_list:
            sp, _ = rate("SP", metric, o)
            rp, nrp = rate("RP", metric, o)
            ship = flat if flat is not None else tables[name].get(o)
            if sp is None or rp is None or not nrp:
                continue
            print(f"  {name:<22}{o:>5}{ship:>10.4f}{sp:>10.4f}{rp:>10.4f}"
                  f"{rp / sp if sp else 0:>8.3f}{nrp:>9,}")

    mod = acc.get("ALL|steal_state_MODELLED|0", [0, 0])[0]
    unr = acc.get("ALL|steal_state_unreachable|0", [0, 0])[0]
    tot = mod + unr
    if tot:
        print(f"\n  STEAL EVENTS BY STATE, over {tot:,}:")
        print(f"    reachable by the model (1B occupied, 2B empty):"
              f" {mod:,}  {100*mod/tot:.1f}%")
        print(f"    UNREACHABLE at any rate:"
              f" {unr:,}  {100*unr/tot:.1f}%")

    print(f"\n  ERA GATE — steal rates per opportunity, by season:")
    print(f"    {'season':<8}{'SB':>9}{'CS':>9}{'n':>10}")
    for y in ("2023", "2024", "2025", "2026"):
        sb = acc.get(f"ALL|steal_{y}|0", [0, 0])
        cs = acc.get(f"ALL|cs_{y}|0", [0, 0])
        if sb[1]:
            print(f"    {y:<8}{sb[0]/sb[1]:>9.4f}{cs[0]/cs[1]:>9.4f}"
                  f"{sb[1]:>10,}")

    print("\n  RP/SP is the whole point. Anything far from 1.00 is a")
    print("  constant measured on one population and used on another —")
    print("  the pattern that has now hit three for three.")


if __name__ == "__main__":
    main(sys.argv[1:])
