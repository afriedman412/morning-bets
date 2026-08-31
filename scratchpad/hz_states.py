"""WHY DOES THE COUNTED HAZARD LEAVE STARTERS IN TOO LONG?

    venv/bin/python -m scratchpad.hz_states [n_sims] [max_games]

QUESTION. With `USE_PITCH_HAZARD` on, the model produces 22.1% of starts at
18+ outs against a real 17.1% (4.5 sigma). The table was COUNTED on 294,884
real decisions, so either the count is wrong or the model is not arriving at
those buckets the way reality does.

TWO HYPOTHESES, and they are separable.

  H1  PITCH ACCUMULATION. If the model's starter throws fewer pitches per
      out, he reaches any given out count at a LOWER pitch count, sits in a
      lower hazard bucket and lasts longer. The table would be innocent.
  H2  CONDITIONING. Each bucket was solved CONDITIONAL on the other shipped
      terms (runs, traffic, inning, margin). If the model's game STATE at a
      given pitch count differs from reality's, a correct conditional table
      still yields the wrong marginal.

TEST. Simulate the holdout with the hazard on and compare against the real
boxscore line for the same starts: pitches at exit, pitches per out, and
the share of starts reaching each pitch bucket. H1 predicts the model is
short on pitches per out. H2 predicts pitches per out matches and the model
still survives its buckets.
"""
from __future__ import annotations

import multiprocessing as mp
import random
import statistics as st
import sys
from collections import Counter

from src.context import sim

sim.USE_PITCH_HAZARD = True

from src.context import calibrate as cal   # noqa: E402
from src.context import game, store        # noqa: E402
from src.context.sources import rates as rate_src  # noqa: E402
from scratchpad.dispersion import perturb  # noqa: E402

HOLDOUT = "2026-07-01"
BUCKETS = (0, 25, 40, 50, 60, 70, 78, 85, 90, 95, 100, 200)

_CASES: dict = {}
_PENS: dict = {}
_LG: dict = {}
_SIMS = 20


def real_pitches() -> dict:
    """{(game_id, player_name): (pitches, outs)} for real STARTERS."""
    with store.connect() as c:
        rows = c.execute(
            "SELECT game_id, player_name, pitches, outs_recorded "
            "FROM bets.mlb_pitching WHERE is_starter = 1 "
            "AND pitches IS NOT NULL AND pitches > 0").fetchall()
    return {(str(r[0]), r[1]): (r[2], r[3]) for r in rows}


def _one(args):
    i, gid = args
    v = _CASES[gid]
    home = next(x for x in v if x[0]["is_home"])
    away = next(x for x in v if not x[0]["is_home"])
    an = cal.adjust_lineup(away[2], False)
    hn = cal.adjust_lineup(home[2], True)
    out = []
    for act in (away[0], home[0]):
        out.append([act["game_id"], act["player_name"], [], []])
    for draw in range(_SIMS):
        rng = random.Random(7 + i * 100003 + draw)
        za, zh = rng.gauss(0, 1), rng.gauss(0, 1)
        A = game.build_side(perturb(away[1], za, 0.0),
                            _PENS.get((away[0]["team"] or "").upper(), []),
                            hn, sim.Hook(), rng, team=away[0]["team"],
                            date=away[0].get("date"))
        H = game.build_side(perturb(home[1], zh, 0.0),
                            _PENS.get((home[0]["team"] or "").upper(), []),
                            an, sim.Hook(), rng, team=home[0]["team"],
                            date=home[0].get("date"))
        r = game.simulate_game(A, H, _LG, rng)
        for slot, sp in ((0, r.away_sp), (1, r.home_sp)):
            out[slot][2].append(sp.pitches)
            out[slot][3].append(sp.outs)
    return out


def bucket(p):
    for lo, hi in zip(BUCKETS, BUCKETS[1:]):
        if lo <= p < hi:
            return lo
    return BUCKETS[-2]


def main(argv):
    global _CASES, _PENS, _LG, _SIMS
    pos = [a for a in argv if not a.startswith("-")]
    _SIMS = int(pos[0]) if pos else 20
    cap = int(pos[1]) if len(pos) > 1 else None

    pairs = cal.paired_cases(rates_before=HOLDOUT, since=HOLDOUT)
    gids = sorted(pairs)[:cap] if cap else sorted(pairs)
    _CASES = {g: pairs[g] for g in gids}
    _LG = sim.league(before=HOLDOUT)
    _PENS = rate_src.bullpens(_LG, before=HOLDOUT)
    real = real_pitches()

    ctx = mp.get_context("fork")
    with ctx.Pool(max(1, (mp.cpu_count() or 2) - 1)) as pool:
        got = pool.map(_one, list(enumerate(gids)))

    m_p, m_o, r_p, r_o = [], [], [], []
    m_bucket, r_bucket = Counter(), Counter()
    for g in got:
        for gid, name, pitches, outs in g:
            key = (str(gid), name)
            if key not in real:
                continue
            rp, ro = real[key]
            if not ro:
                continue
            r_p.append(rp); r_o.append(ro)
            r_bucket[bucket(rp)] += 1
            m_p.append(st.mean(pitches)); m_o.append(st.mean(outs))
            for p in pitches:
                m_bucket[bucket(p)] += 1

    n = len(r_p)
    print(f"  holdout {HOLDOUT}+, {n} starts matched to a real pitch count, "
          f"{_SIMS} sims each\n")
    mp_, rp_ = st.mean(m_p), st.mean(r_p)
    mo_, ro_ = st.mean(m_o), st.mean(r_o)
    se_p = st.pstdev(r_p) / n ** 0.5
    print(f"  {'':<22}{'model':>9}{'real':>9}{'gap':>9}{'se':>8}")
    print(f"  {'pitches at exit':<22}{mp_:>9.2f}{rp_:>9.2f}"
          f"{mp_ - rp_:>+9.2f}{se_p:>8.2f}")
    print(f"  {'outs at exit':<22}{mo_:>9.2f}{ro_:>9.2f}{mo_ - ro_:>+9.2f}"
          f"{st.pstdev(r_o) / n ** 0.5:>8.2f}")
    print(f"  {'PITCHES PER OUT':<22}{mp_ / mo_:>9.3f}{rp_ / ro_:>9.3f}"
          f"{mp_ / mo_ - rp_ / ro_:>+9.3f}")
    print(f"\n  H1 says the model is SHORT on pitches per out. "
          f"H2 says it matches.\n")
    print(f"  share of starts by exit pitch bucket")
    print(f"  {'bucket':<12}{'model':>9}{'real':>9}{'gap':>9}")
    mt, rt = sum(m_bucket.values()), sum(r_bucket.values())
    for lo in BUCKETS[:-1]:
        mm, rr = m_bucket[lo] / mt, r_bucket[lo] / rt
        print(f"  {lo:<12}{mm:>9.3f}{rr:>9.3f}{mm - rr:>+9.3f}")


if __name__ == "__main__":
    main(sys.argv[1:])
