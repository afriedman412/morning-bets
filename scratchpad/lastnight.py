"""Blind re-simulation of three games from 2026-08-24.

RATES ARE CUT OFF STRICTLY BEFORE THE GAME DATE, so a game cannot inform its
own prediction. Nothing in this script reads a result — not the score, not
the boxscore lines, not the starters' actual outs. Lineups only.

    venv/bin/python -m scratchpad.lastnight [n_sims]
"""
import json
import random
import sys
from collections import Counter

from src.context import game, sim
from src.context import price as pm
from src.context.sources import rates as rate_src

DATE = "2026-08-24"
BEFORE = "2026-08-24"

#: Batting orders as they were posted. PHI and SEA come from the pregame
#: projection — the boxscore carries no batting order, only outcomes.
LINEUPS = {
    "PIT": ["Nick Gonzales", "Enmanuel Valdez", "Bryan Reynolds", "Oneil Cruz",
            "Rafael Flores", "Brandon Lowe", "Nick Yorke", "Spencer Horwitz",
            "Jared Triolo"],
    "SD": ["Fernando Tatis Jr.", "Jake Cronenworth", "Manny Machado",
           "Ty France", "Jackson Merrill", "Xander Bogaerts", "Gavin Sheets",
           "Freddy Fermin", "Dustin Harris"],
    "CIN": ["Elly De La Cruz", "Sal Stewart", "Dane Myers", "Tyler Stephenson",
            "Eugenio Suarez", "Matt McLain", "JJ Bleday", "Jose Trevino",
            "Ivan Johnson"],
    "SF": ["Drew Gilbert", "Rafael Devers", "Jung Hoo Lee", "Derek Hill",
           "Dario Cavanaugh", "Nick Furman", "Sam Whitcomb", "Grant McCray",
           "Casey Koss"],
}

GAMES = [
    ("PHI", "SEA", "Zack Wheeler", "Logan Gilbert"),
    ("PIT", "SD", "Braxton Ashcraft", "Robbie Ray"),
    ("CIN", "SF", "Chase Burns", "Carson Whisenhunt"),
]

PREFIXES = (3, 5, 7)


def _fold(name):
    """Accent-folded, suffix-stripped, lowercase tokens.

    Rafael Flores Jr. and Eugenio Suarez both fell through to league-average
    on the first pass — one for a suffix, one for an accent. Same class as
    the Kalshi wrong-player bug earlier the same day: a name matcher that
    silently returns the wrong thing is worse than one that raises, because
    a league-average bat looks exactly like a real one downstream.
    """
    import unicodedata
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    toks = [t.lower().strip(".") for t in n.replace("'", "").split()]
    return [t for t in toks if t and t not in
            ("jr", "sr", "ii", "iii", "iv")]


def resolve(names, br, lg):
    """Match posted names to the rate table, warn on anything missing."""
    league = sim.BatterRates(name="league", k_pct=lg["k_pct"],
                             bb_pct=lg["bb_pct"], hr_pct=lg["hr_pct"],
                             babip=lg["babip"])
    out, missing = [], []
    folded = {}
    for k in br:
        folded.setdefault(tuple(_fold(k)), k)
    for n in names:
        f = tuple(_fold(n))
        k = folded.get(f)
        if k is None:
            cand = [v for kk, v in folded.items()
                    if kk and f and kk[-1] == f[-1] and kk[0][0] == f[0][0]]
            k = cand[0] if len(cand) == 1 else None
        if k is None:
            missing.append(n)
            out.append(league)
        else:
            b = br[k]
            out.append(sim.BatterRates(name=k, k_pct=b["k_pct"],
                                       bb_pct=b["bb_pct"], hr_pct=b["hr_pct"],
                                       babip=b["babip"], pa=b["pa"]))
    return out, missing


def main():
    n_sims = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    lg = sim.league(before=BEFORE)
    pr = rate_src.pitcher_rates(lg, before=BEFORE)
    br = rate_src.batter_rates(lg, before=BEFORE)
    pens = rate_src.bullpens(lg, before=BEFORE)

    out = []
    for away, home, a_sp_name, h_sp_name in GAMES:
        rec = {"away": away, "home": home,
               "away_sp": a_sp_name, "home_sp": h_sp_name, "n": n_sims}
        sps = {}
        for side, nm in ((away, a_sp_name), (home, h_sp_name)):
            p = pr.get(nm)
            if not p:
                print(f"  !! no rates for {nm}")
                return
            sps[side] = sim.PitcherRates(
                name=nm, k_pct=p["k_pct"], bb_pct=p["bb_pct"],
                hr_pct=p["hr_pct"], babip=p["babip"], pa=p["pa"])
            rec[f"{'away' if side == away else 'home'}_sp_rates"] = {
                "k_pct": p["k_pct"], "bb_pct": p["bb_pct"],
                "hr_pct": p["hr_pct"], "babip": p["babip"], "pa": p["pa"]}
        nines = {}
        for club in (away, home):
            names = LINEUPS.get(club) or pm.projected_lineup(club, DATE)
            nine, miss = resolve(names, br, lg)
            if miss:
                print(f"  {club}: league-average for {miss}")
            nines[club] = nine
            rec[f"{'away' if club == away else 'home'}_lineup"] = \
                [b.name for b in nine]

        acc = {"away_runs": [], "home_runs": [], "total": [],
               "away_sp_outs": [], "home_sp_outs": [],
               "away_sp_k": [], "home_sp_k": [],
               "away_sp_pitches": [], "home_sp_pitches": []}
        for n in PREFIXES:
            acc[f"away_f{n}"], acc[f"home_f{n}"] = [], []
        for i in range(n_sims):
            rng = random.Random(20260824 + i)
            A = game.build_side(sps[away], pens.get(away, []),
                                nines[home], None, rng)
            H = game.build_side(sps[home], pens.get(home, []),
                                nines[away], None, rng)
            r = game.simulate_game(A, H, lg, rng, track=PREFIXES)
            acc["away_runs"].append(r.away)
            acc["home_runs"].append(r.home)
            acc["total"].append(r.total)
            acc["away_sp_outs"].append(r.away_sp.outs)
            acc["home_sp_outs"].append(r.home_sp.outs)
            acc["away_sp_k"].append(r.away_sp.k)
            acc["home_sp_k"].append(r.home_sp.k)
            acc["away_sp_pitches"].append(r.away_sp.pitches)
            acc["home_sp_pitches"].append(r.home_sp.pitches)
            for n2 in PREFIXES:
                a_, h_ = r.prefix_side.get(n2, (None, None))
                if a_ is not None:
                    acc[f"away_f{n2}"].append(a_)
                    acc[f"home_f{n2}"].append(h_)
        rec["dist"] = {k: dict(Counter(v)) for k, v in acc.items()}
        out.append(rec)
        print(f"  {away}@{home} done", flush=True)
    json.dump(out, open("scratchpad/lastnight.json", "w"))
    print("wrote scratchpad/lastnight.json")


if __name__ == "__main__":
    main()
