"""Render the blind re-simulation into a static dashboard.

Six games played 2026-08-24, priced as if they had not been. The visual
system moved to `dashkit.py` on 2026-08-30 so `board.py --html` could render
tonight's slate in the same idiom; this file is now the page and nothing
else.

    venv/bin/python -m scratchpad.dash [OUT.html]
"""
import json
import sys

from scratchpad.dashkit import (MDASH, NDASH, bars, card, document, esc,
                                expand, hist, over, pctile, statline, stats,
                                thresholds)

DATA_PATH = "scratchpad/lastnight0.json"
ACTUALS_PATH = "scratchpad/actuals.json"
DEFAULT_OUT = "scratchpad/lastnight.html"


def game_block(g, actuals):
    d = {k: expand(v) for k, v in g["dist"].items()}
    A, H = g["away"], g["home"]
    a = actuals.get(f"{A}@{H}", {})
    ac, hc = "var(--away)", "var(--home)"
    out = ['<article class="game">']
    out.append(
        f'<div class="gh">'
        f'<div class="gt"><span class="club a">{esc(A)}</span>'
        f'<span class="at">at</span>'
        f'<span class="club h">{esc(H)}</span></div>'
        f'<div class="gsp">'
        f'<span><i class="dot a"></i>{esc(g["away_sp"])}</span>'
        f'<span><i class="dot h"></i>{esc(g["home_sp"])}</span></div>'
        f'<div class="gn">{g["n"]:,} simulations</div></div>')
    if a.get("away_runs") is not None:
        out.append(f'<div class="fin">Final <b>{esc(A)} {a["away_runs"]}'
                   f'</b> {MDASH} <b>{a["home_runs"]} {esc(H)}</b></div>')

    # Team totals through 3 / 5 / 7 / final -- a real sequence, so ordered.
    out.append('<h3 class="rh">Team runs through</h3>')
    out.append('<div class="grid g4">')
    for lab, key in (("3 innings", "f3"), ("5 innings", "f5"),
                     ("7 innings", "f7"), ("Final", "runs")):
        inner = []
        for club, side, col in ((A, "away", ac), (H, "home", hc)):
            v = d[f"{side}_{key}"]
            s = stats(v)
            hi = 8 if key != "runs" else 12
            av = a.get(f"{side}_{key}")
            pc = ("" if av is None else
                  f'<span class="pc">{pctile(v, av):.0%}</span>')
            inner.append(
                f'<div class="series"><div class="sn">{esc(club)}'
                f'<span><b>{s["mean"]:.2f}</b>{pc}</span></div>'
                f'{bars(hist(v, 0, hi), col, actual=av)}</div>')
        lines = ([("o2.5", 2.5), ("o3.5", 3.5)] if key != "runs"
                 else [("o3.5", 3.5), ("o4.5", 4.5)])
        th = "".join(
            f'<div class="th"><span class="thl">{esc(club)} {lab2}</span>'
            f'<span class="thv">{over(d[f"{side}_{key}"], ln):.0%}</span>'
            f'</div>'
            for club, side in ((A, "away"), (H, "home"))
            for lab2, ln in lines)
        out.append(card(lab, "runs scored",
                        "".join(inner) + f'<div class="ths">{th}</div>'))
    out.append('</div>')

    out.append('<h3 class="rh">Starters</h3>')
    out.append('<div class="grid g2">')
    for name, side, col, club in ((g["away_sp"], "away", ac, A),
                                  (g["home_sp"], "home", hc, H)):
        o, k, pt = (d[f"{side}_sp_outs"], d[f"{side}_sp_k"],
                    d[f"{side}_sp_pitches"])
        so, sk, sp = stats(o), stats(k), stats(pt)
        ip = f'{so["med"] // 3}.{so["med"] % 3}'
        block = (
            f'<div class="sp"><div class="spn"><i class="dot '
            f'{"a" if side == "away" else "h"}"></i>{esc(name)}'
            f'<span class="spc">{esc(club)}</span></div>'
            f'<div class="spm"><span>median <b>{ip}</b> IP</span>'
            f'<span><b>{sk["mean"]:.1f}</b> K</span>'
            f'<span><b>{sp["mean"]:.0f}</b> pitches</span></div>'
            f'<div class="sub">Outs recorded</div>'
            f'{bars(hist(o, 0, 27), col, 3, actual=a.get(f"{side}_sp_outs"))}'
            f'{statline(so, a.get(f"{side}_sp_outs"), o)}'
            + thresholds(o, [("o14.5", 14.5), ("o15.5", 15.5),
                             ("o17.5", 17.5), ("o18.5", 18.5)])
            + '<div class="sub">Strikeouts</div>'
            f'{bars(hist(k, 0, 14), col, actual=a.get(f"{side}_sp_k"))}'
            f'{statline(sk, a.get(f"{side}_sp_k"), k)}'
            + thresholds(k, [("o4.5", 4.5), ("o5.5", 5.5),
                             ("o6.5", 6.5), ("o7.5", 7.5)])
            + '<div class="sub">Pitch count</div>'
            + bars(hist(pt, 20, 115, 5), col, 2, binw=5,
                   actual=a.get(f"{side}_sp_pitches"))
            + statline(sp, a.get(f"{side}_sp_pitches"), pt)
            + thresholds(pt, [("80+", 79.5), ("90+", 89.5),
                              ("100+", 99.5), ("110+", 109.5)])
            + '</div>')
        out.append(f'<section class="card">{block}</section>')
    out.append('</div></article>')
    return "".join(out)


def render(data, actuals):
    body = ['<div class="wrap">',
            '<h1>Six games, re-simulated blind</h1>',
            '<p class="lede">Games played 24 August 2026, priced as if they '
            'had not been. Every rate is computed from data strictly before '
            'the game date, so no game can inform its own prediction, and '
            'nothing here reads a result ' + MDASH + ' not the score, not a '
            'boxscore line, not the starters&rsquo; actual outs. Batting '
            'orders only.</p>',
            '<div class="meta">'
            '<span><b>Simulations</b> 20,000 per game</span>'
            f'<span><b>Games</b> {len(data)}</span>'
            '<span><b>Rates cutoff</b> before 2026-08-24</span>'
            '<span><b>Engine</b> game.simulate_game</span>'
            '<span><b>Hook</b> two branches, refit per population</span>'
            '<span><b>Bullpen</b> sampled per draw from real arms</span>'
            '</div>',
            '<div class="warn">The <b>dashed red line</b> is what actually '
            'happened. It was added after the fact ' + MDASH + ' the '
            'simulation never saw it. &ldquo;Pctile&rdquo; is where the real '
            'result landed inside the predicted distribution; 50% means dead '
            f'centre.</div>']
    body.extend(game_block(g, actuals) for g in data)
    body.append('</div>')
    return document("Six games, re-simulated blind", "".join(body))


def main(argv=()):
    out = argv[0] if argv else DEFAULT_OUT
    with open(DATA_PATH) as f:
        data = json.load(f)
    with open(ACTUALS_PATH) as f:
        actuals = json.load(f)
    html = render(data, actuals)
    with open(out, "w") as f:
        f.write(html)
    print(f"wrote {out}  ({len(html):,} bytes)")


if __name__ == "__main__":
    main(sys.argv[1:])
