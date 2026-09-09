"""The DIRECT check on `USE_OPENER_EXIT` — the quantity it targets.

QUESTION. In games listing a flagged short-yardage starter, what outs does
the sim hand that arm with the flag on and off, against what he actually
recorded? And do the affected games' team runs sit above or below reality
in each state — i.e. is run 1's -0.032 mean move toward the truth or away?

WHY THIS EXISTS BESIDE `opener_score.py`. The run-level CRPS there came
back with se 0.0164 — larger than the recorded intent failure it was built
to detect — so it cannot resolve this mechanism either way. The starter's
OUTS are what the mechanism actually changes (a ~12-out error per flagged
start), settle real markets (outs and K lines), and are directly observed.
High-n ratio over low-n aggregate, per CLAUDE.md.

    venv/bin/python -m scratchpad.opener_outs [n_sims_per_state]
"""
import random
import sys

from src import db
from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src

FOLDS = [(2023, "2023-07-01"), (2024, "2024-07-01"),
         (2025, "2025-07-01"), (2026, "2026-07-01")]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
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


def main():
    outs = {True: [], False: []}          # sim outs for the FLAGGED arm
    real_outs = []                        # what he actually recorded
    runs = {True: [], False: []}          # game total in affected games
    real_runs = []
    for yr, cut in FOLDS:
        pairs = cal.paired_cases(season=yr, rates_before=cut, since=cut)
        lg = sim.league(season=yr, before=cut)
        pens = rate_src.bullpens(lg, season=yr, before=cut)
        short = short_starters(cut)
        with db.connect() as c:
            act = {r["game_id"]: dict(r) for r in c.execute(
                "select game_id, away_score, home_score from games"
                " where sport='mlb'")}
        hit = [(g, p) for g, p in sorted(pairs.items())
               if p[0][0].get("player_name") in short
               or p[1][0].get("player_name") in short]
        for gi, (gid, pair) in enumerate(hit):
            a = act.get(gid) or {}
            if a.get("away_score") is None:
                continue
            flagged = [s for s, c_ in (("away", pair[0]), ("home", pair[1]))
                       if c_[0].get("player_name") in short]
            for s, c_ in (("away", pair[0]), ("home", pair[1])):
                if s in flagged:
                    real_outs.append(c_[0]["o"])
            real_runs.append(a["away_score"] + a["home_score"])
            for state in (True, False):
                game.USE_OPENER_EXIT = state
                for i in range(N):
                    rng = random.Random(yr * 1000003 + gi * 1009 + i)
                    r = cal.replay(pair, lg, pens, rng)
                    for s in flagged:
                        sp = r.away_sp if s == "away" else r.home_sp
                        outs[state].append(sp.outs)
                    runs[state].append(r.away + r.home)
            game.USE_OPENER_EXIT = True
        print(f"fold {yr}: {len(hit)} affected games", flush=True)

    def stats(v):
        n = len(v)
        m = sum(v) / n
        sd = (sum((x - m) ** 2 for x in v) / (n - 1)) ** 0.5
        return m, sd, n

    mr, sdr, nr = stats(real_outs)
    print(f"\nFLAGGED STARTER OUTS ({nr} real starts, se {sdr/nr**0.5:.2f})")
    print(f"  real            {mr:6.2f}  (sd {sdr:.2f})")
    for state, tag in ((True, "on "), (False, "off")):
        m, sd, n = stats(outs[state])
        print(f"  sim flag {tag}    {m:6.2f}  (sd {sd:.2f}, {n} draws)")
    for state, tag in ((True, "on "), (False, "off")):
        v = outs[state]
        share = sum(1 for o in v if o <= 9) / len(v)
        print(f"  sim flag {tag}    share <=9 outs {share:.3f}  "
              f"(real {sum(1 for o in real_outs if o <= 9)/nr:.3f})")

    mr, sdr, nr = stats(real_runs)
    print(f"\nGAME TOTAL IN AFFECTED GAMES ({nr} games, "
          f"se {sdr/nr**0.5:.2f})")
    print(f"  real            {mr:6.2f}")
    for state, tag in ((True, "on "), (False, "off")):
        m, sd, n = stats(runs[state])
        print(f"  sim flag {tag}    {m:6.2f}")


if __name__ == "__main__":
    main()
