"""Does a lineup's HANDEDNESS BALANCE predict what the model gets wrong?

    venv/bin/python -m scratchpad.platoon

THE SCREEN BEFORE THE BUILD, which is the project's own rule and is what the
last handedness attempt skipped. That one derived vs-LHP/vs-RHP batter rates,
wired them in and A/B'd — days of work for deltas that alternated sign.

Its docstring names two explanations and says which test separates them:

  * platoon effects AVERAGE OUT across nine hitters, in which case handedness
    is dead however well it is measured; or
  * the DERIVATION was attenuated — a batter's whole game line credited to
    the opposing starter's hand, relievers included, then shrunk halfway
    back to his overall rate.

This tests the first one directly and costs no simulation. If the platoon
BALANCE of the nine a starter faces carries no information about his
residual, then no amount of better-measured splits can help, because the
lineup-level quantity is what reaches a start.

REAL HANDEDNESS, per plate appearance, off play-by-play — `batSide` and
`pitchHand` as they actually were, switch-hitters included, rather than a
season split derived and shrunk.

SUPERSEDED IN PART — READ THIS. The first version measured only the LINEUP
side: the share of batters with the platoon advantage, correlated against the
residual. That is under-powered by construction, because it assumes every
pitcher has the same size split. The real mechanism is an INTERACTION — a
pitcher with a severe split facing a stacked lineup is a different case from
one with no split facing the same lineup, and averaging over pitchers whose
splits differ in size AND SIGN washes it out. The old `USE_HANDEDNESS`
attempt had the mirror-image hole: it varied the BATTER's rates by the
pitcher's hand and never modelled how big that pitcher's own split is.

`scratchpad/platoon_split.py` runs the interaction version. This file is kept
because the lineup-only null is still worth having on record.

THE MEASURE is the share of batters faced who had the platoon ADVANTAGE
(opposite hand to the pitcher). A league-average lineup runs near 0.55; a
stacked one is well above. Correlated against the residual the model already
leaves — actual minus predicted — so a feature the model already uses would
score ~0.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict

from src import db
from src.context.sources import pbp


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


def platoon_by_start() -> dict:
    """{(game_id, starter_name): advantage share} off real play-by-play.

    THE JOIN IS THE HARD PART AND THE FIRST VERSION GOT IT WRONG. It attached
    both starters' names to both sides and then dropped everything ambiguous,
    which threw away 95% of the rows and left whichever survived possibly
    matched to the wrong lineup. A screen that quietly discards its sample is
    worse than one that fails.

    Each starter is tied to his side through the TEAM ABBREVIATION: the home
    club's starter pitches while `isTopInning` is true, because that is when
    the away side bats.
    """
    with db.connect() as c:
        games = {r["game_id"]: (r["home_team_abbr"], r["away_team_abbr"])
                 for r in c.execute(
                     "select game_id, home_team_abbr, away_team_abbr"
                     " from games where sport = 'mlb'")}
        starters = defaultdict(list)
        for r in c.execute(
                "select game_id, player_name, team from mlb_pitching"
                " where is_starter = 1"):
            starters[r["game_id"]].append((r["player_name"], r["team"]))

    out = {}
    for full, arms in starters.items():
        short = full.split("-")[-1]
        if full not in games or not pbp.have(short):
            continue
        home_ab, away_ab = games[full]
        try:
            d = pbp.fetch(short)
        except Exception:
            continue
        if not d:
            continue
        seen, tally = {}, defaultdict(lambda: [0, 0])
        for p in (d.get("allPlays") or []):
            mu = p.get("matchup") or {}
            ab = p.get("about") or {}
            pid = (mu.get("pitcher") or {}).get("id")
            ph = ((mu.get("pitchHand") or {}).get("code") or "")
            bh = ((mu.get("batSide") or {}).get("code") or "")
            if not pid or not ph or not bh:
                continue
            # Top of the inning: the away side bats, so the HOME club is
            # pitching. That is the side this plate appearance belongs to.
            side = "home" if ab.get("isTopInning") else "away"
            seen.setdefault(side, pid)
            if seen[side] != pid:
                continue
            tally[side][0] += 1
            if bh != ph:
                tally[side][1] += 1
        for name, team in arms:
            if not team:
                continue
            t = (team or "").upper()
            side = ("home" if t == (home_ab or "").upper()
                    else "away" if t == (away_ab or "").upper() else None)
            if side is None:
                continue
            n, adv = tally.get(side, [0, 0])
            if n >= 10:
                out[(full, name)] = adv / n
    return out


def main(argv):
    rows = [r for r in json.load(open("scratchpad/ceiling_rows.json"))
            if not r.get("_team_row")]
    share = platoon_by_start()

    print(f"  {len(rows):,} residual rows, {len(share):,} starts with real"
          f" handedness\n")
    print(f"  {'stat':<8}{'n':>7}{'r':>9}{'z':>8}{'spread it could remove':>26}")
    for stat in ("k", "outs", "h", "er"):
        xs, ys = [], []
        for r in rows:
            key = (r["game_id"], r["player"])
            if key not in share or r.get(f"m_{stat}") is None:
                continue
            xs.append(share[key])
            ys.append(r[f"a_{stat}"] - r[f"m_{stat}"])
        r_, z = corr(xs, ys)
        sd = st.pstdev(ys) if ys else 0.0
        print(f"  {stat:<8}{len(xs):>7,}{r_:>+9.3f}{z:>+8.1f}"
              f"{abs(r_) * sd:>26.3f}")

    vals = list(share.values())
    if vals:
        print(f"\n  platoon advantage share across starts: mean"
              f" {st.mean(vals):.3f}, sd {st.pstdev(vals):.3f},"
              f" range {min(vals):.2f}-{max(vals):.2f}")
    print("\n  A feature the model already uses scores ~0. The last attempt")
    print("  died on 'platoon effects average out across nine hitters' —")
    print("  if that is right, this correlation is noise and no better")
    print("  measurement of the splits can rescue it.")


if __name__ == "__main__":
    main(sys.argv[1:])
