"""HIS OWN split, against TONIGHT'S lineup. The interaction, not the average.

    venv/bin/python -m scratchpad.platoon_split

WHY THIS AND NOT `platoon.py`. That one correlated the LINEUP's platoon
balance against the residual and found nothing, which is under-powered by
construction: it assumes every pitcher has the same size split. Pitchers'
splits vary in magnitude and some are REVERSED, so averaging across them
cancels the effect whether or not it is there. The shipped `USE_HANDEDNESS`
attempt had the mirror-image hole — it varied the BATTER's rates by the
pitcher's hand and never asked how big that pitcher's own split is.

THE QUANTITY. For each starter, his own rate vs left-handed and vs
right-handed batters, counted per plate appearance off play-by-play. Then
for each start, what his rate SHOULD be given the nine he actually faced:

    expected = share_L * rate_vs_L + share_R * rate_vs_R

and the handedness ADJUSTMENT is that minus his overall rate — the amount a
handedness-aware model would move this start. Correlated against the
residual the model already leaves.

IT IS A DIFFERENCE OF DIFFERENCES and that is deliberate. A pitcher who
always faces the same mix gets an adjustment near zero however severe his
split, because his overall rate already contains it — the same absorption
that killed park and team defence. What is left is the start-to-start
DEVIATION in who he faced, which is the only part a model could exploit.

LEAVE-ONE-OUT, AND WITHOUT IT THIS MEASURES ITSELF. A pitcher's split is
counted on the same season as the starts being scored, so the start under
test is INSIDE its own predictor — nine strikeouts against lefties raises his
vs-L rate, which then "predicts" the nine. That is the leak that had
`headroom.py` reporting 112% of a perfect forecaster's ceiling. Each start's
own plate appearances are subtracted from the split before it is used.

SPLITS ARE SHRUNK. A pitcher with 40 plate appearances against lefties has a
rate that is mostly noise, and an unshrunk split would manufacture a
correlation out of small samples. Each side is pulled toward his own overall
rate by the same measured constant the model uses.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict

from src import db
from src.context.sources import pbp, rates as rate_src

STATS = {"k": "k_pct", "h": "babip"}
MIN_VS = 30


def corr(xs, ys):
    n = len(xs)
    if n < 30:
        return 0.0, 0.0
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if not sx or not sy:
        return 0.0, 0.0
    r = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (n * sx * sy)
    return r, r * (n - 2) ** 0.5 / max((1 - r * r) ** 0.5, 1e-9)


def collect():
    """Per starter: splits; per start: the mix he actually faced."""
    with db.connect() as c:
        games = {r["game_id"]: (r["home_team_abbr"], r["away_team_abbr"],
                                r["date"])
                 for r in c.execute("select game_id, home_team_abbr,"
                                    " away_team_abbr, date from games"
                                    " where sport = 'mlb'")}
        starters = defaultdict(list)
        for r in c.execute("select game_id, player_name, team from"
                           " mlb_pitching where is_starter = 1"):
            starters[r["game_id"]].append((r["player_name"], r["team"]))

    # name -> hand -> [pa, k, hits, bip]
    split = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))
    starts = {}
    for full, arms in starters.items():
        short = full.split("-")[-1]
        if full not in games or not pbp.have(short):
            continue
        home_ab, away_ab, date = games[full]
        if not date.startswith("2026"):
            continue
        try:
            d = pbp.fetch(short)
        except Exception:
            continue
        if not d:
            continue
        seen = {}
        per = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))
        for p in (d.get("allPlays") or []):
            ab, mu = p.get("about") or {}, p.get("matchup") or {}
            res = p.get("result") or {}
            pid = (mu.get("pitcher") or {}).get("id")
            bh = ((mu.get("batSide") or {}).get("code") or "")
            if not pid or bh not in ("L", "R"):
                continue
            side = "home" if ab.get("isTopInning") else "away"
            seen.setdefault(side, pid)
            if seen[side] != pid:
                continue
            ev = res.get("eventType") or ""
            cell = per[side][bh]
            cell[0] += 1
            if ev in ("strikeout", "strikeout_double_play"):
                cell[1] += 1
            if ev in ("single", "double", "triple"):
                cell[2] += 1
                cell[3] += 1
            elif ev in ("field_out", "force_out", "fielders_choice_out",
                        "grounded_into_double_play", "double_play",
                        "triple_play", "field_error"):
                cell[3] += 1
        for name, team in arms:
            t = (team or "").upper()
            side = ("home" if t == (home_ab or "").upper()
                    else "away" if t == (away_ab or "").upper() else None)
            if side is None or not per[side]:
                continue
            starts[(full, name)] = {h: list(v) for h, v in per[side].items()}
            for h, v in per[side].items():
                for i in range(4):
                    split[name][h][i] += v[i]
    return split, starts


def main(argv):
    split, starts = collect()
    rows = [r for r in json.load(open("scratchpad/ceiling_rows.json"))
            if not r.get("_team_row")]
    K = rate_src.STABILISE_MEASURED["pit"]
    print(f"  {len(split):,} starters with splits, {len(starts):,} starts\n")

    # How big are the splits, before anything is correlated?
    ks = []
    for name, byh in split.items():
        L, R = byh.get("L"), byh.get("R")
        if not L or not R or min(L[0], R[0]) < 150:
            continue
        ks.append(L[1] / L[0] - R[1] / R[0])
    if ks:
        print(f"  K% split (vs L minus vs R) over {len(ks)} starters:"
              f" mean {st.mean(ks):+.4f}, sd {st.pstdev(ks):.4f},"
              f" range {min(ks):+.3f} to {max(ks):+.3f}")
        print(f"  reversed splits: {sum(1 for x in ks if x > 0)} of {len(ks)}")

    print(f"\n  {'stat':<8}{'n':>7}{'r':>9}{'z':>8}{'removable spread':>20}")
    for stat, _rate in STATS.items():
        xs, ys = [], []
        for r in rows:
            key = (r["game_id"], r["player"])
            byh, here = split.get(r["player"]), starts.get(key)
            if not byh or not here or r.get(f"m_{stat}") is None:
                continue
            hl0 = here.get("L", [0, 0, 0, 0])
            hr0 = here.get("R", [0, 0, 0, 0])
            # LEAVE ONE OUT: this start comes out of its own predictor.
            L = [byh.get("L", [0, 0, 0, 0])[i] - hl0[i] for i in range(4)]
            R = [byh.get("R", [0, 0, 0, 0])[i] - hr0[i] for i in range(4)]
            if min(L[0], R[0]) < MIN_VS:
                continue
            num = 1 if stat == "k" else 2
            den = 0 if stat == "k" else 3
            tot_n = L[den] + R[den]
            if not tot_n:
                continue
            overall = (L[num] + R[num]) / tot_n
            k = K["k_pct"] if stat == "k" else K["babip"]

            def rate(cell):
                if not cell[den]:
                    return overall
                w = cell[den] / (cell[den] + k)
                return w * (cell[num] / cell[den]) + (1 - w) * overall

            hl = here.get("L", [0, 0, 0, 0])
            hr_ = here.get("R", [0, 0, 0, 0])
            n_here = hl[den] + hr_[den]
            if n_here < 8:
                continue
            exp = (hl[den] * rate(L) + hr_[den] * rate(R)) / n_here
            xs.append(exp - overall)
            ys.append(r[f"a_{stat}"] - r[f"m_{stat}"])
        r_, z = corr(xs, ys)
        sd = st.pstdev(ys) if ys else 0.0
        print(f"  {stat:<8}{len(xs):>7,}{r_:>+9.3f}{z:>+8.1f}"
              f"{abs(r_) * sd:>20.3f}")
    print("\n  x is the amount a handedness-aware model would MOVE this start")
    print("  relative to his overall rate. If that carries no information")
    print("  about the residual, handedness has nothing left to give.")


if __name__ == "__main__":
    main(sys.argv[1:])
