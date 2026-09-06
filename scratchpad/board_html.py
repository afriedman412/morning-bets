"""THE BOARD, AS A PAGE. `scratchpad/board.py --html` renders through here.

Same slate, same numbers, same caveats as the terminal board. It is a
second VIEW of one payload, never a second computation. `board.build()`
produces the payload; nothing in this file simulates, fetches or prices.

WHAT THE LAYOUT ENCODES, and it is the whole point of building it rather
than printing a flat table: **the three markets are not equally
trustworthy**, and a flat list says they are. So strikeouts lead at full
strength, outs is demoted into its own block behind a warning and its stale
correction is never given a recommendation, and first-five gets the room its
record earns. That ordering is the finding, not a style choice.

The visual system is `dashkit.py`, shared with the blind re-simulation page.
Everything rendered here must be ASCII: see that module's docstring for
why there is no `<meta charset>` to lean on.
"""
from __future__ import annotations

import statistics as st

from scratchpad import dashkit as dk
from scratchpad.dashkit import MDASH, esc

#: An edge at or above this is drawn in the alert colour. Not a bet
#: threshold &mdash; `BETTING.md` governs that, and this page does not fire.
LOUD = 0.08
#: Below this a disagreement is inside the noise a 20,000-draw simulation
#: carries plus the width of a Kalshi book, so it is greyed rather than
#: dropped: the reader should see that we agree.
QUIET = 0.03

CSS = """
.tbl{width:100%;border-collapse:collapse;font-family:var(--mono);
  font-size:12px;font-variant-numeric:tabular-nums}
.tbl th{text-align:right;font-weight:600;font-size:10px;
  text-transform:uppercase;letter-spacing:.08em;color:var(--dimmer);
  padding:0 0 7px;border-bottom:1px solid var(--line);white-space:nowrap}
.tbl th:first-child,.tbl td:first-child{text-align:left}
.tbl td{text-align:right;padding:6px 0;border-bottom:1px solid var(--line2);
  white-space:nowrap}
.tbl td:first-child{white-space:normal}
.tbl tr:last-child td{border-bottom:0}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.scroll .tbl{min-width:560px}
.tbl td+td{padding-left:14px}
.who{font-family:var(--sans);font-size:13px;font-weight:600;
  letter-spacing:-.01em}
.vs{color:var(--dimmer);font-weight:400;font-size:11px;
  font-family:var(--mono);margin-left:6px}
.bet{color:var(--dim)}
.big{color:var(--ink);font-weight:600}
.loud{color:var(--hit);font-weight:700}
.quiet{color:var(--dimmer)}
.take{font-size:10px;letter-spacing:.09em;text-transform:uppercase;
  font-weight:700}
.chips{display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end}
.chip{font-family:var(--mono);font-size:9.5px;letter-spacing:.04em;
  text-transform:uppercase;color:var(--dim);border:1px solid var(--line);
  border-radius:3px;padding:1px 5px;white-space:nowrap}
.chip.hot{color:var(--away);border-color:var(--away);
  background:var(--awaySoft)}
.block{margin-top:34px}
.block>h2{font-size:15px;font-weight:650;letter-spacing:-.01em;margin:0}
.block>p{margin:3px 0 14px;font-size:12.5px;color:var(--dim);max-width:70ch}
.weak{opacity:.72}
.weak:hover{opacity:1}
.ladder{width:100%;border-collapse:collapse;font-family:var(--mono);
  font-size:11px;font-variant-numeric:tabular-nums;margin-top:9px}
.ladder th{font-size:9px;text-transform:uppercase;letter-spacing:.07em;
  color:var(--dimmer);font-weight:600;text-align:right;
  padding:0 0 4px;border-bottom:1px solid var(--line2)}
.ladder th:first-child,.ladder td:first-child{text-align:left}
.ladder td{text-align:right;padding:3px 0;color:var(--dim)}
.ladder td+td{padding-left:8px}
.dead{font-family:var(--mono);font-size:12px;color:var(--dim);
  display:flex;flex-wrap:wrap;gap:2px 16px;padding:9px 0;
  border-bottom:1px solid var(--line2)}
.dead b{color:var(--ink);font-weight:600}
.rules{margin:0;padding:0;list-style:none;display:grid;gap:10px;
  font-size:13px;color:var(--dim);max-width:76ch}
.rules b{color:var(--ink);font-weight:600}
.foot{margin-top:44px;padding-top:16px;border-top:1px solid var(--line);
  font-size:12px;color:var(--dimmer);max-width:70ch}
"""


def american(p):
    """Fair price, no vig. Shared definition with the terminal board."""
    if p <= 0 or p >= 1:
        return "-"
    if p > 0.5:
        return f"{-100 * p / (1 - p):+.0f}"
    return f"{100 * (1 - p) / p:+.0f}"


def _chips(row, stale=False):
    out = []
    if row.get("w") is not None and row["w"] < row.get("thin_at", 0.60):
        out.append(f'<span class="chip hot">thin {row["w"]:.2f}</span>')
    if not row.get("confirmed", True):
        out.append('<span class="chip">proj lineup</span>')
    if stale:
        out.append('<span class="chip">corrected</span>')
    if row.get("far"):
        out.append('<span class="chip">extrapolated</span>')
    return f'<div class="chips">{"".join(out)}</div>' if out else ""


def _edge_cell(edge):
    cls = "loud" if abs(edge) >= LOUD else (
        "quiet" if abs(edge) < QUIET else "big")
    return f'<td class="{cls}">{edge:+.3f}</td>'


def disagreement_table(rows, stale=False):
    """Every row Kalshi priced, widest disagreement first."""
    body = []
    for r in sorted(rows, key=lambda x: -abs(x["edge"])):
        take = "over" if r["edge"] > 0 else "under"
        pv = r.get("priced", r["over"])
        p = pv if take == "over" else 1 - pv
        cls = "quiet" if abs(r["edge"]) < QUIET else "take"
        body.append(
            f'<tr><td><span class="who">{esc(r["player"])}</span>'
            f'<span class="vs">vs {esc(r["opp"])}</span></td>'
            f'<td class="bet">{esc(r["stat"])} {r["line"]:g}</td>'
            f'<td class="{cls}">{take}</td>'
            f'<td>{p:.1%}</td>'
            f'<td>{american(p)}</td>'
            f'<td class="quiet">{r["mid"]:.3f}</td>'
            + _edge_cell(r["edge"]) +
            f'<td>{_chips(r, stale)}</td></tr>')
    if not body:
        return '<p class="lede">No Kalshi market attached on this slate.</p>'
    return ('<div class="scroll"><table class="tbl"><thead><tr>'
            '<th>pitcher</th><th>line</th><th>take</th><th>ours</th>'
            '<th>fair</th><th>kalshi</th><th>edge</th><th></th>'
            '</tr></thead><tbody>' + "".join(body) + '</tbody></table></div>')


def _ladder(rows, stale=False):
    """Fair price against the market for one pitcher and one stat."""
    head = ('<tr><th>line</th><th>P(ov)</th><th>fair ov</th><th>fair un</th>'
            '<th>kalshi</th><th>edge</th></tr>')
    body = []
    for r in sorted(rows, key=lambda x: x["line"]):
        if r.get("mid") is None:
            mid, edge = '<td class="quiet">-</td>', '<td class="quiet">-</td>'
        else:
            mid = f'<td>{r["mid"]:.3f}</td>'
            edge = _edge_cell(r["edge"])
        pv = r.get("priced", r["over"])
        raw = ""
        if stale and abs(pv - r["over"]) > 1e-9:
            raw = f' <span class="quiet">(raw {r["over"]:.2f})</span>'
        body.append(
            f'<tr><td class="big">o{r["line"]:g}</td>'
            f'<td class="big">{pv:.3f}{raw}</td>'
            f'<td>{american(pv)}</td>'
            f'<td>{american(1 - pv)}</td>{mid}{edge}</tr>')
    return (f'<table class="ladder"><thead>{head}</thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


def starter_card(s, colour, dot, club):
    k, o = s["k"], s["outs"]
    sk, so = dk.stats(k), dk.stats(o)
    ip = f'{so["med"] // 3}.{so["med"] % 3}'
    pitch = (f'<span><b>{st.mean(s["pitches"]):.0f}</b> pitches</span>'
             if s.get("pitches") else "")
    krows = [r for r in s["rows"] if r["stat"] == "k"]
    orows = [r for r in s["rows"] if r["stat"] == "outs"]
    kmark = min((r["line"] for r in krows), key=lambda ln: abs(
        dk.over(k, ln) - 0.5), default=None)
    omark = min((r["line"] for r in orows), key=lambda ln: abs(
        dk.over(o, ln) - 0.5), default=None)
    parts = [
        f'<div class="sp"><div class="spn"><i class="dot {dot}"></i>'
        f'{esc(s["name"])}<span class="spc">{esc(club)} vs '
        f'{esc(s["opp"])}</span></div>'
        f'<div class="spm"><span>median <b>{ip}</b> IP</span>'
        f'<span><b>{sk["mean"]:.1f}</b> K</span>{pitch}</div>',
        _chips({**s, "confirmed": s.get("confirmed", True)}),
        '<div class="sub">Strikeouts</div>',
        dk.bars(dk.hist(k, 0, 14), colour, mark=kmark,
                mark_label=None if kmark is None else f"{kmark:g}"),
        dk.statline(sk),
    ]
    parts.append(_ladder(krows) if krows else
                 '<p class="sl">No line inside the band.</p>')
    parts += [
        '<div class="sub">Outs <span class="quiet">weakest market</span>'
        '</div>',
        dk.bars(dk.hist(o, 0, 27), colour, 3, mark=omark,
                mark_label=None if omark is None else f"{omark:g}"),
        dk.statline(so),
    ]
    parts.append(_ladder(orows, stale=True) if orows else
                 '<p class="sl">No line inside the band.</p>')
    parts.append('</div>')
    return f'<section class="card">{"".join(parts)}</section>'


def f5_card(g):
    """Away, home and the game total through five, side by side."""
    inner = []
    for side, colour in (("away", "var(--away)"), ("home", "var(--home)")):
        s = g["sides"][side]
        if not s.get("f5"):
            continue
        v = s["f5"]
        inner.append(
            f'<div class="series"><div class="sn">{esc(g[side])} first '
            f'five'
            f'<span><b>{st.mean(v):.2f}</b></span></div>'
            f'{dk.bars(dk.hist(v, 0, 8), colour)}</div>')
    if g.get("f5_game"):
        v = g["f5_game"]
        inner.append(
            f'<div class="series"><div class="sn">Game total'
            f'<span><b>{st.mean(v):.2f}</b></span></div>'
            f'{dk.bars(dk.hist(v, 0, 14), "var(--ink)")}</div>')
    rows = g.get("f5_rows") or []
    if rows:
        body = "".join(
            f'<tr><td class="big">{esc(r["who"])} o{r["line"]:g}</td>'
            f'<td class="big">{r["over"]:.3f}</td>'
            f'<td>{american(r["over"])}</td>'
            f'<td>{american(1 - r["over"])}</td></tr>'
            for r in rows)
        inner.append(
            '<table class="ladder"><thead><tr><th>bet</th><th>P(ov)</th>'
            '<th>fair ov</th><th>fair un</th></tr></thead>'
            f'<tbody>{body}</tbody></table>')
    return dk.card("First five", "the stated product", "".join(inner))


def game_block(g):
    out = ['<article class="game">',
           f'<div class="gh"><div class="gt">'
           f'<span class="club a">{esc(g["away"])}</span>'
           f'<span class="at">at</span>'
           f'<span class="club h">{esc(g["home"])}</span></div>'
           f'<div class="gsp">'
           f'<span><i class="dot a"></i>'
           f'{esc(g["sides"]["away"]["name"])}</span>'
           f'<span><i class="dot h"></i>'
           f'{esc(g["sides"]["home"]["name"])}</span>'
           f'</div>'
           f'<div class="gn">{g["n"]:,} simulations</div></div>',
           '<div class="grid g3">',
           starter_card(g["sides"]["away"], "var(--away)", "a", g["away"]),
           starter_card(g["sides"]["home"], "var(--home)", "h", g["home"]),
           f5_card(g), '</div></article>']
    return "".join(out)


def render(payload):
    p = payload
    corr_on = p.get("corrected_on", "an unrecorded date")
    priced = [r for g in p["games"] for s in g["sides"].values()
              for r in s["rows"] if r.get("mid") is not None]
    ks = [r for r in priced if r["stat"] == "k"]
    outs = [r for r in priced if r["stat"] == "outs"]
    band = ("all lines" if p["band"] is None
            else f'fair price inside +/-{p["band"]:.0f}')
    body = [
        '<div class="wrap">',
        f'<h1>The board {MDASH} {esc(p["date"])}</h1>',
        '<p class="lede">Every startable line on tonight\'s slate, priced '
        'off <b>one</b> set of simulated games, so a starter\'s strikeout '
        'line, his outs line and the first-five total his own start sits '
        'inside cannot contradict each other. Fair prices carry <b>no '
        'vig</b>: an offered number beats us only if it is longer than the '
        'fair one on that side.</p>',
        '<div class="meta">'
        f'<span><b>Games</b> {len(p["games"])} priced'
        f'{"" if not p["declined"] else f", {len(p['declined'])} declined"}'
        '</span>'
        f'<span><b>Simulations</b> {p["n"]:,} per game</span>'
        f'<span><b>Band</b> {band}</span>'
        '<span><b>Engine</b> game.simulate_game</span>'
        f'<span><b>Market</b> Kalshi mid, book under '
        f'{p["max_spread"]:.0f}c</span>'
        '</div>',
        '<div class="warn">This page prices; it does not pick. '
        f'<b>BETTING.md</b> governs whether anything here is a bet {MDASH} '
        'and the three markets below are <b>not</b> equally trustworthy, which '
        'is why they are not one list.</div>',
    ]

    body += [
        '<div class="block">',
        '<h2>Strikeouts</h2>',
        '<p>The strongest market here, and only against the <b>open</b>: '
        '32.9% better than Kalshi\'s opening price at predicting the close '
        'over 1,220 settled contracts, and nothing at all against the '
        'close (blend weight 0.00). An edge found late is mostly gone. '
        'Sorted by disagreement.</p>',
        disagreement_table(ks), '</div>',
        '<div class="block weak">',
        '<h2>Outs</h2>',
        f'<p>The weakest market. Outs <i>are</i> the hook {MDASH} a '
        'manager\'s decision the model reproduces only in aggregate, CLV z '
        'of 1.3 against strikeouts\' 43.5. Every number below is <b>after</b> '
        'the measured boundary-share correction, re-measured '
        f'<b>{esc(corr_on)}</b> on the shipped hook over 1,224 holdout '
        'starts; the raw simulator figure is in brackets on the ladders. '
        'The correction prices the line rather than annotating it &mdash; '
        'reading the raw number against a market tilts this whole block '
        'toward unders by about four points. The market is still the '
        'weakest one here; that is about outs, not about the correction.'
        '</p>',
        disagreement_table(outs, stale=True), '</div>',
    ]

    body.append('<h3 class="rh">Every game, both starters, first five</h3>')
    body += [game_block(g) for g in p["games"]]

    if p["declined"]:
        body.append('<div class="block"><h2>Declined</h2>'
                    '<p>Both starters or neither. A game with one unmodelled '
                    'arm is never filled with a league-average stand-in '
                    + MDASH + ' inventing the other club invents the score, '
                    'and the score is what the hook, the bullpen and the '
                    'margin are conditioned on.</p>')
        for tag, who, why in p["declined"]:
            body.append(
                f'<div class="dead"><b>{esc(tag)}</b>'
                f'<span>{esc(who)}</span><span>{esc(why)}</span></div>')
        body.append('</div>')

    body += [
        '<div class="block"><h2>What governs a number here</h2>',
        '<ul class="rules">',
        '<li><b>Thin</b> means under 60% of the rate being priced is the '
        'pitcher\'s own season record and the rest is the shrink target. A '
        'gap on a thin arm is often <i>our shrinkage</i>, not his talent, '
        'and it is largest on the thinnest.</li>',
        '<li><b>Projected lineup</b> means no card is posted and the '
        'opposing nine is a projection. It is the weakest link in the whole '
        'path.</li>',
        '<li><b>Never a live game.</b> A started game is declined before it '
        'is priced, and unknown state resolves to <i>not</i> pregame.</li>',
        '<li><b>Do not stack discounts.</b> State the number, state the one '
        'caveat that governs it, stop. Piling every caveat onto one bet '
        'until a real edge reads as unbettable is the standing failure mode '
        'on this page.</li>',
        '<li><b>Nothing here judges a mechanism.</b> This is the betting '
        'layer. Model changes are scored on the prefix ladder, CRPS and '
        'coverage against what actually happened ' + MDASH + ' never on how '
        'the board looks tonight.</li>',
        '</ul></div>',
        '<p class="foot">First-five <i>game</i> totals are listed by Kalshi '
        'as KXMLBF5TOTAL and are not attached: the ticker packs both club '
        'abbreviations into one segment. <code>f5_market._match</code> is '
        'the parser if that is worth wiring. Team-total fair prices above '
        'are ours alone.</p>',
        '</div>']
    return dk.document(f'The board {MDASH} {esc(p["date"])}',
                       "".join(body), CSS)
