"""TODO 19.1, the follow-up — is the coupling the UNPLAYED BOTTOM OF THE NINTH?

QUESTION. `ml_extras.py` put the whole of the model's invented between-club
correlation inside nine innings and, within that, entirely in innings 6-9:
F5 x F5 is +0.0028 (z +0.4) and 6-9 x 6-9 is +0.1770 (z +38). Stratifying
on the F5 margin removes 3% of it, so the score-feedback story — both
managers reading the same margin — is refuted. Something else about the
late innings couples the two clubs.

HYPOTHESIS. The bottom of the ninth is not always played. The away club
bats every one of innings 6-9; the home club bats the ninth only when it is
NOT ahead. That truncation deletes exactly the (home high, away low) draws
— the anti-correlated corner — and deleting that corner pushes a
correlation POSITIVE. It fires in the ninth and nowhere else, which is
precisely the shape observed: nothing at five innings, everything at nine.

TEST. Replay with `track=(5, 8, 9)` and take the same within-game
covariance through EIGHT innings, where both clubs always bat, beside the
through-nine number off the same draws. If the eight-inning coupling is
~0 the ninth is the whole mechanism; if it survives, the ninth is not it
and the suspect list has to be rebuilt.

WHY THIS IS NOT A NULL-BY-CONSTRUCTION: real baseball has the same rule, so
a coupling that is purely the unplayed ninth is a feature the model shares
with the league, and the defect would be in its SIZE rather than its
existence. The real through-nine correlation is -0.0087 against the model's
+0.0553, so if the ninth explains the model's number it has to explain why
reality does not show it too — the run environment of the ninth, not the
skip rule itself. State that before reading the result.

POWER. One fold, 600 games x 200 draws. The through-nine covariance is
+0.417 with se 0.011 on 1,000 games, so at 600 the se is ~0.014 and the
eight-inning row resolves anything above ~0.03 — a twelfth of the signal.
Deliberately one fold: `ml_extras` showed the four folds agree to within
0.004 in correlation, so a second fold buys nothing here.

    venv/bin/python -m scratchpad.ml_eight [n_games] [n_sims]
"""
import random
import statistics as st
import sys

from src.context import calibrate as cal
from src.context import sim
from src.context.sources import rates as rate_src
from scratchpad.ml_extras import cov, mean_se

YEAR, CUT = 2023, "2023-07-01"
NG = int(sys.argv[1]) if len(sys.argv) > 1 else 600
N = int(sys.argv[2]) if len(sys.argv) > 2 else 200


def simulate():
    pairs = cal.paired_cases(season=YEAR, rates_before=CUT, since=CUT)
    lg = sim.league(season=YEAR, before=CUT)
    pens = rate_src.bullpens(lg, season=YEAR, before=CUT)
    out = []
    items = sorted(pairs.items())[:NG]
    for gi, (gid, pair) in enumerate(items):
        d = []
        for i in range(N):
            rng = random.Random(YEAR * 7000003 + gi * 1013 + i)
            r = cal.replay(pair, lg, pens, rng, track=(5, 8, 9))
            a5, h5 = r.prefix_side[5]
            a8, h8 = r.prefix_side[8]
            a9, h9 = r.prefix_side.get(9, (r.away, r.home))
            d.append((a5, h5, a8, h8, a9, h9))
        out.append(d)
        if (gi + 1) % 100 == 0:
            print(f"  {gi + 1}/{len(items)}", flush=True)
    return out


def row(label, games, ai, hi, base=None):
    """Within-game covariance of two per-draw columns, and the correlation
    it implies. `base` subtracts an earlier prefix to make an INCREMENT."""
    cs, sa, sh = [], [], []
    for draws in games:
        a = [d[ai] - (d[base[0]] if base else 0) for d in draws]
        h = [d[hi] - (d[base[1]] if base else 0) for d in draws]
        cs.append(cov(a, h))
        sa.append(st.pstdev(a))
        sh.append(st.pstdev(h))
    m, se = mean_se(cs)
    denom = st.mean(sa) * st.mean(sh)
    print(f"    {label:26s} cov {m:+.4f}  se {se:.4f}  z {m/se:+6.1f}"
          f"   -> corr {m / denom:+.4f}")
    return m


def main():
    print(f"REPLAYING {NG} games x {N} draws, fold {YEAR} (track 5/8/9)")
    games = simulate()
    print(f"\n  WITHIN-GAME COVARIANCE, {len(games)} games")
    print("  cumulative through each prefix:")
    row("through 5 (both bat)", games, 0, 1)
    c8 = row("through 8 (both bat)", games, 2, 3)
    c9 = row("through 9 (home may skip)", games, 4, 5)
    print("  the increments, so the windows do not nest:")
    row("innings 6-8", games, 2, 3, base=(0, 1))
    row("innings 6-9", games, 4, 5, base=(0, 1))
    row("the ninth alone", games, 4, 5, base=(2, 3))
    print(f"\n  THE READING: the ninth adds {c9 - c8:+.4f} of covariance to"
          f" a through-eight base of {c8:+.4f}")
    print("    through eight ~0  -> the unplayed bottom of the ninth is the"
          " mechanism")
    print("    through eight big -> the ninth is NOT it; rebuild the suspects")

    # How often does the home club actually lose its ninth? A mechanism
    # that fires on 5% of draws cannot carry a 40-se covariance, and this
    # is the share that decides whether the story is even arithmetically
    # available (rule: state the population before believing the effect).
    skip = st.mean(1.0 if d[5] == e else 0.0
                   for draws in games for d, e in ((x, x[3]) for x in draws))
    print(f"\n  HOME SCORES NOTHING FROM THE NINTH ON: {skip:.1%} of draws"
          f" (skipped ninths are a subset of this)")


if __name__ == "__main__":
    main()
