"""The pre-registered falsifier for TODO 15 / PLAN-opener-bullpen.md.

QUESTION. Does `USE_RELIEF_INTENT` improve the RUN DISTRIBUTION in the
games it was built for — games listing a short-yardage starter — measured
against what actually happened?

TEST. Per fold, `paired_cases` games where EITHER listed starter averaged
under 11 outs a start as of the cut (the same cell `slate.priceable`
gates on, so this is the morning-of population, not hindsight on the
day's outcome). Each game replays N times with the flag ON and OFF on
common per-draw seeds. Score: discrete CRPS of each side's full-game and
F5 runs against the actual score, paired per game; the relief outs the
model hands the pen, against the real pen's outs in those games, as the
shape check the CRPS may be too blunt for.

POWER, stated before the result. The population is 5-6% of starts, so
expect tens of games per fold. The paired design with common seeds
cancels most draw noise; the se that matters is across GAMES and is
printed with every number. If the CRPS diff se comes out larger than any
plausible effect, the honest conclusion is "underpowered", not "null".

    venv/bin/python -m scratchpad.opener_score [n_sims_per_state] [flag]

`flag` is the `game` attribute the A/B flips — default `USE_RELIEF_INTENT`
(the original falsifier). Pass `USE_OPENER_EXIT` to score the opener exit
distribution itself (TODO 15's sharp remaining job); everything else about
the harness — population, seeds, scoring — is identical, so the two runs
are directly comparable.
"""
import random
import sys
from collections import defaultdict

from src import db
from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src

FOLDS = [(2023, "2023-07-01"), (2024, "2024-07-01"),
         (2025, "2025-07-01"), (2026, "2026-07-01")]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
FLAG = sys.argv[2] if len(sys.argv) > 2 else "USE_RELIEF_INTENT"
SHORT_AVG = 11.0


def short_starters(cut):
    q = """
      select p.player_name nm, avg(p.outs_recorded) ao, count(*) n
      from mlb_pitching p join games g on g.game_id = p.game_id
      where g.sport = 'mlb' and g.status = 'Final' and p.is_starter = 1
        and g.date < ?
      group by p.player_name having n >= 2
    """
    with db.connect() as c:
        return {r["nm"] for r in c.execute(q, (cut,)) if r["ao"] < SHORT_AVG}


def crps(draws, actual):
    """Kernel form: E|X-actual| - HALF of E|X-X'|.

    THE HALF WAS MISSING UNTIL 2026-09-09 (later session) and every number
    this file ever printed before that is on a broken scale — true CRPS
    minus half the predictive spread, so a state that widens its run
    distribution collected a phantom bonus. Found when the same identity,
    copied into `opener_class.py`, produced NEGATIVE values, which a
    proper CRPS cannot. Every other scorer in the repo uses the CDF form
    and never had the bug; verified equal to `score_outs.crps` on shared
    inputs to 1e-12.
    """
    n = len(draws)
    t1 = sum(abs(d - actual) for d in draws) / n
    s = sorted(draws)
    # E|X-X'| via the sorted identity, O(n log n).
    t2 = 2 * sum((2 * i - n + 1) * v for i, v in enumerate(s)) / (n * n)
    return t1 - t2 / 2


def main():
    rows = []
    for yr, cut in FOLDS:
        pairs = cal.paired_cases(season=yr, rates_before=cut, since=cut)
        lg = sim.league(season=yr, before=cut)
        pens = rate_src.bullpens(lg, season=yr, before=cut)
        short = short_starters(cut)
        with db.connect() as c:
            act = {r["game_id"]: dict(r) for r in c.execute(
                "select game_id, away_score, home_score, away_score_f5,"
                " home_score_f5 from games where sport='mlb'")}
        hit = [(g, p) for g, p in sorted(pairs.items())
               if p[0][0].get("player_name") in short
               or p[1][0].get("player_name") in short]
        print(f"fold {yr}: {len(hit)} of {len(pairs)} paired games list a "
              f"short-yardage starter", flush=True)
        for gi, (gid, pair) in enumerate(hit):
            a = act.get(gid) or {}
            if a.get("away_score") is None:
                continue
            draws = {}
            for state in (True, False):
                setattr(game, FLAG, state)
                d = {"ar": [], "hr": [], "af5": [], "hf5": []}
                for i in range(N):
                    rng = random.Random(yr * 1000003 + gi * 1009 + i)
                    r = cal.replay(pair, lg, pens, rng, track=(5,))
                    d["ar"].append(r.away)
                    d["hr"].append(r.home)
                    d["af5"].append(r.away_f5)
                    d["hf5"].append(r.home_f5)
                draws[state] = d
            setattr(game, FLAG, True)
            row = {"gid": gid, "yr": yr}
            for state, tag in ((True, "on"), (False, "off")):
                d = draws[state]
                row[f"crps_{tag}"] = (
                    crps(d["ar"], a["away_score"])
                    + crps(d["hr"], a["home_score"])) / 2
                f5 = None
                if a.get("away_score_f5") is not None:
                    f5 = (crps(d["af5"], a["away_score_f5"])
                          + crps(d["hf5"], a["home_score_f5"])) / 2
                row[f"crps_f5_{tag}"] = f5
                row[f"mean_{tag}"] = (sum(d["ar"]) + sum(d["hr"])) / (2 * N)
            rows.append(row)
        print(f"  scored {len([r for r in rows if r['yr'] == yr])}",
              flush=True)

    def paired(key):
        ds = [r[f"{key}_on"] - r[f"{key}_off"] for r in rows
              if r.get(f"{key}_on") is not None
              and r.get(f"{key}_off") is not None]
        n = len(ds)
        m = sum(ds) / n
        sd = (sum((x - m) ** 2 for x in ds) / (n - 1)) ** 0.5
        return m, sd / n ** 0.5, n

    print(f"\n{len(rows)} affected games, {N} sims a state, common seeds,"
          f" A/B on {FLAG}")
    for key, label in (("crps", "full-game team-run CRPS"),
                       ("crps_f5", "F5 team-run CRPS"),
                       ("mean", "mean team runs")):
        m, se, n = paired(key)
        print(f"  {label:26s} on-minus-off {m:+.4f} (se {se:.4f}, n {n}, "
              f"{abs(m) / se if se else 0:.1f} sigma)")
    by = defaultdict(list)
    for r in rows:
        by[r["yr"]].append(r["crps_on"] - r["crps_off"])
    for yr in sorted(by):
        d = by[yr]
        m = sum(d) / len(d)
        print(f"    fold {yr}: {m:+.4f} over {len(d)}")


if __name__ == "__main__":
    main()
