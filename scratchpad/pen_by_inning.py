"""DOES A MANAGER'S FOURTH-INNING HOOK DEPEND ON HIS BULLPEN MORE THAN HIS
SIXTH-INNING ONE DOES? Counted on real decisions.

    venv/bin/python -m scratchpad.pen_by_inning

QUESTION    Pulling in the fourth commits the bullpen to six innings;
            pulling in the sixth commits it to three. Does a real manager's
            sensitivity to his pen scale with what he is asking of it?

WHY IT IS NOT ALREADY ANSWERED. `per_pen_back2` / `per_pen_rest` ship on
both curves — measured, controlled at x5, and they did NOT close the
boundary share (day seventeen part seven). But they are MAIN EFFECTS: one
coefficient applied identically in the second inning and the eighth. The
INTERACTION with inning has never been counted.

HYPOTHESIS  If real managers weigh the pen more heavily early, the spread
            in pull rate between a rested and a burned bullpen is WIDER in
            the fourth than in the sixth. If the spread is the same, the
            main effect already says everything and a fourth-inning
            mechanism built on the pen would be fitting the cell.

TEST        Mid-inning decisions only, real rows, split by inning and by
            `pen_state` rest. Raw AND solved conditional on the other
            shipped terms, because rested pens correlate with everything
            else about a club's week.

TRAIN ROWS ONLY.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict

import numpy as np

from src.context import sim, store
from scratchpad.pitch_hazard import HOLDOUT_CUT, ROWS, other_terms, train_only


def team_map():
    """{(game_id, side): TEAM} so a decision row can be given a bullpen."""
    out = {}
    with store.connect() as c:
        for gid, a, h in c.execute(
                "SELECT game_id, away_team, home_team FROM bets.games"):
            out[(str(gid), "away")] = (a or "").upper()
            out[(str(gid), "home")] = (h or "").upper()
    return out


def main():
    sim.USE_PEN_STATE = True
    tm = team_map()
    rows = train_only(json.load(open(ROWS)))
    mid = [r for r in rows if not r.get("ends_inning")]
    kept = []
    for r in mid:
        t = tm.get((str(r.get("game_id")), r.get("side")))
        if not t:
            continue
        back2, rest = sim.pen_state(t, r.get("date"))
        if rest is None:
            continue
        r["_rest"] = rest
        r["_back2"] = back2
        kept.append(r)
    print(f"  {len(kept):,} of {len(mid):,} training mid-inning decisions "
          f"given a bullpen state\n")

    # ARMS UNAVAILABLE, NOT DAYS OF CLUB REST. `rest` is 1 in 84.3% of
    # games -- it is a schedule fact (did the club have an off day), not a
    # measure of bullpen depletion, and splitting on it collapses to a
    # near-constant. `back2` counts relievers who threw on back-to-back
    # days and so are down tonight: 57/26/12/4% at 0/1/2/3.
    from collections import Counter
    dist = Counter(int(r["_back2"]) for r in kept)
    tot = sum(dist.values())
    print("  arms unavailable (`back2`) in the decision rows:")
    for k in sorted(dist):
        print(f"    {k}  {dist[k]:>9,}  {dist[k]/tot:>6.1%}")
    print("  split: RESTED = 0 arms down, BURNED = 2 or more\n")

    def tier(r):
        b = int(r["_back2"])
        return "rested" if b == 0 else "burned" if b >= 2 else "mid"

    print(f"  RAW pull rate by inning and bullpen rest\n")
    print(f"  {'inning':<9}{'burned':>11}{'middle':>11}{'rested':>11}"
          f"{'rested-burned':>16}{'se':>8}")
    for inn in (3, 4, 5, 6, 7):
        cells = defaultdict(lambda: [0, 0])
        for r in kept:
            if r["inning"] != inn:
                continue
            c = cells[tier(r)]
            c[0] += bool(r.get("removed"))
            c[1] += 1
        vals = {}
        for k in ("burned", "mid", "rested"):
            a, n = cells[k]
            vals[k] = (a / n if n else 0.0, n)
        d = vals["rested"][0] - vals["burned"][0]
        se = math.sqrt(
            sum(max(vals[k][0], 1e-6) * (1 - vals[k][0]) / max(vals[k][1], 1)
                for k in ("burned", "rested")))
        star = "*" if abs(d) > 2 * se else " "
        print(f"  {inn:<9}{vals['burned'][0]:>11.4f}{vals['mid'][0]:>11.4f}"
              f"{vals['rested'][0]:>11.4f}{d:>+15.4f}{star}{se:>8.4f}")

    print(f"\n  SOLVED conditional on the other shipped terms\n")
    print(f"  {'inning':<9}{'burned':>11}{'rested':>11}"
          f"{'diff':>13}{'se':>8}{'sigma':>8}{'n':>10}")
    h = sim.Hook()
    for inn in (3, 4, 5, 6, 7):
        sub = [r for r in kept if r["inning"] == inn]
        got = {}
        for k in ("burned", "rested"):
            cell = [r for r in sub if tier(r) == k]
            if len(cell) < 300:
                got[k] = None
                continue
            base = np.array([
                h.mid_intercept + h.late_mid_offset
                + h.late_mid_per_pitch * r["pitches"]
                + (h.high_pitch_mid
                   if r["pitches"] >= h.high_pitch_threshold else 0.0)
                + other_terms(r, boundary=False) for r in cell])
            y = np.array([1.0 if r["removed"] else 0.0 for r in cell])
            tgt = y.mean()
            lo, hi = -9.0, 9.0
            for _ in range(140):
                m = (lo + hi) / 2
                if (1 / (1 + np.exp(-np.clip(base + m, -30, 30)))).mean() < tgt:
                    lo = m
                else:
                    hi = m
            se = math.sqrt(max(tgt * (1 - tgt), 1e-12) / len(cell))
            got[k] = ((lo + hi) / 2, se / max(tgt * (1 - tgt), 1e-9),
                      len(cell))
        if got["burned"] is None or got["rested"] is None:
            print(f"  {inn:<9}{'thin cell':>11}")
            continue
        d = got["rested"][0] - got["burned"][0]
        s = (got["burned"][1] ** 2 + got["rested"][1] ** 2) ** 0.5
        print(f"  {inn:<9}{got['burned'][0]:>+11.3f}{got['rested'][0]:>+11.3f}"
              f"{d:>+13.3f}{s:>8.3f}{d / s:>+8.1f}"
              f"{got['burned'][2] + got['rested'][2]:>10,}")


if __name__ == "__main__":
    main()
