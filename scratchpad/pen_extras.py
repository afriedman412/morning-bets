"""Two structural checks the model has never had: extras, and the bullpen.

    venv/bin/python -m scratchpad.pen_extras

EXTRAS. `sim.Frame.__post_init__` sets `bases = [None, None, None]` on
every half-inning with no exception for the tenth, so the simulator plays
extra innings under the PRE-2020 rules. MLB has started each half-inning
from the tenth with an automatic runner on second since 2020 and
permanently since 2023. This prints what that is worth.

BULLPEN. `game.build_side` draws `PEN_DEPTH` arms without replacement,
weighted by season appearances, and `next_arm` walks that list IN DRAW
ORDER. So the club's best reliever is as likely to appear in the sixth as
the ninth, and nothing carries across games — there is no fatigue state of
any kind. This compares the model's implied usage concentration against
the real one.
"""
from __future__ import annotations

import random
import statistics as st
from collections import Counter, defaultdict

from src import db
from src.context import game, sim
from src.context.sources import rates as rate_src


def extras():
    print("  === EXTRA INNINGS ===\n")
    # `away_innings`/`home_innings` are the LINE SCORE, comma separated,
    # so the number of cells is the number of innings played and the cells
    # past the ninth are the runs the automatic runner helped produce.
    with db.connect() as c:
        rows = [dict(r) for r in c.execute(
            "select away_innings, home_innings from games where sport='mlb'"
            " and status='Final' and date like '2026%'")]
    games = ex_runs = ex_halves = 0
    ex_games = []
    reg_half_runs = reg_halves = 0
    for r in rows:
        a = [x for x in (r["away_innings"] or "").split(",")]
        h = [x for x in (r["home_innings"] or "").split(",")]
        if len(a) < 9:
            continue
        games += 1
        n_inn = max(len(a), len(h))
        for cells in (a, h):
            for i, v in enumerate(cells):
                if v == "":
                    continue
                if i < 9:
                    reg_half_runs += int(v)
                    reg_halves += 1
                else:
                    ex_runs += int(v)
                    ex_halves += 1
        if n_inn > 9:
            ex_games.append(n_inn)
    print(f"    ACTUAL 2026: {len(ex_games):,} of {games:,} games went past"
          f" nine ({100 * len(ex_games) / games:.1f}%)")
    if ex_games:
        print(f"    mean innings in those games: {st.mean(ex_games):.2f}")
        print(f"    runs per EXTRA half-inning:      {ex_runs / ex_halves:.3f}"
              f"   ({ex_halves:,} halves)")
        print(f"    runs per REGULATION half-inning: "
              f"{reg_half_runs / reg_halves:.3f}   ({reg_halves:,} halves)")
        print(f"    -> a real extra half-inning scores "
              f"{ex_runs / ex_halves / (reg_half_runs / reg_halves):.2f}x a"
              f" regulation one.")
        print(f"    The model plays it with the bases EMPTY, so it produces")
        print(f"    a regulation half-inning there.")

    # Run expectancy is the whole argument, so state it rather than imply it.
    print("\n    The automatic runner starts every half-inning from the")
    print("    tenth with a man on second and nobody out. League run")
    print("    expectancy for that state is ~1.1 runs against ~0.48 for")
    print("    bases empty, so the model under-scores EVERY extra half-")
    print("    inning by roughly 0.6 runs — while also playing more of")
    print("    them, because scoreless extras are far likelier when the")
    print("    inning starts empty.")
    print("\n    IT CANNOT TOUCH F5 OR A STARTER'S LINE. It is a FULL-GAME")
    print("    TOTAL and MONEYLINE defect only, which is exactly the pair")
    print("    that has never been scored against a settled price.")


def bullpen():
    print("\n\n  === BULLPEN USAGE ===\n")
    lg = sim.league()
    pens = rate_src.bullpens(lg)
    # REAL usage: appearances per reliever, by club.
    real_share, model_share = [], []
    rng = random.Random(0)
    for team, arms in pens.items():
        if len(arms) < 8:
            continue
        apps = sorted((a.get("apps") or 0) for a in arms)[::-1]
        tot = sum(apps)
        if tot < 50:
            continue
        real_share.append(apps[0] / tot)
        # MODEL: how often does the club's most-used arm even get drawn,
        # and where in the order does he land? Draw many bullpens the way
        # `build_side` does and count.
        top = max(arms, key=lambda a: a.get("apps") or 0)["name"]
        drawn = slots = 0
        for _ in range(400):
            pool = list(arms)
            w = [max(a.get("apps") or 1, 1) for a in pool]
            picked = []
            while pool and len(picked) < game.PEN_DEPTH:
                i = rng.choices(range(len(pool)), weights=w, k=1)[0]
                picked.append(pool.pop(i)["name"])
                w.pop(i)
            if top in picked:
                drawn += 1
                slots += picked.index(top)
        model_share.append((drawn / 400, slots / max(drawn, 1)))

    print(f"    {len(real_share)} clubs with a usable pen\n")
    print(f"    real share of relief APPEARANCES taken by the club's most-")
    print(f"    used arm: {st.mean(real_share):.1%} "
          f"(p10 {sorted(real_share)[len(real_share)//10]:.1%}, "
          f"p90 {sorted(real_share)[-len(real_share)//10]:.1%})")
    d = st.mean(x[0] for x in model_share)
    s = st.mean(x[1] for x in model_share)
    print(f"\n    model: that arm is drawn into the {game.PEN_DEPTH}-man pen "
          f"{d:.1%} of games,")
    print(f"    and when drawn he sits at average slot {s:.2f} of "
          f"{game.PEN_DEPTH} — i.e. he is")
    print(f"    as likely to pitch the sixth as the ninth.")
    print("\n    NO FATIGUE OF ANY KIND. The pen is redrawn independently")
    print("    every game and every draw; nothing records that an arm threw")
    print("    30 pitches yesterday or worked three days running. Real")
    print("    availability is the single largest game-to-game difference")
    print("    between two outings by the same club.")
    print("\n    AND `deploy.py` ALREADY MEASURED THAT ROLE IS REAL AND")
    print("    PROJECTS: split-half r +0.55 to +0.78 over 319 relievers.")
    print("    Its own conclusion was that role-based deployment is worth")
    print("    building. It was never built.")


if __name__ == "__main__":
    extras()
    bullpen()
