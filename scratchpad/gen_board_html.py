"""Render `scratchpad.board` text output as an operator's HTML page.

    venv/bin/python -m scratchpad.board_json      2026-09-09
    venv/bin/python -m scratchpad.gen_board_html  2026-09-09

NOT A BET LIST — same footer rules as the text board. What this adds over
the .txt is the FILTER and the K DIVERGENCE table; everything else is the
same numbers laid out to be read rather than dumped.

FOUR PRICES PER RUNG, and no interpretation layered on top: our over, our
under, Kalshi's over, Kalshi's under, each with the probability behind it.
An earlier version showed one side and inferred a "play" from the sign of
the gap; the operator wanted the raw four, so the four is what prints. The
edge column is the only derived number left and it is just our P(over)
minus the mid's.

WHY THE TWO KALSHI CELLS MIRROR AND A BOOK'S DO NOT: Kalshi's `N+` binary
is ONE contract, so its NO side is exactly 1 minus its YES side. A
sportsbook quotes two prices with its hold baked into both, which is why a
book's under can read +106 against Kalshi's +117 on the same event and
neither is wrong. De-vig the book before calling anything backwards.

THE FILTER, and each clause is a rule from BETTING.md rather than taste:
  * `off-band` goes — the +/-170 band is a shopping filter, a rung outside
    it is not a number a book hangs.
  * a starter rung with NO Kalshi mid goes — nothing to disagree with.
  * a rung inside 3 points of the mid goes — that is not an edge.
  * totals, team totals and F5 always STAY. No name-shaped ticker exists
    for them, so fair-only is the product, not a missing comparison.

The K ladder ignores the filter entirely: a pitcher's divergence is a
property of his whole curve, so it is fitted across every rung carrying a
mid, off-band ones included.
"""
from __future__ import annotations

import html
import json
import sys

MIN_GAP = 3.0
K_LADDER = (2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5)

#: Below this many dollars traded, a Kalshi mid is a market maker's
#: resting quote rather than a price anyone has taken. Chosen off the
#: 2026-09-15 slate, where the split was not close: untraded books sat
#: at $14-$122 while real ones started around $500 and ran to $12k.
UNTRADED = 500.0

CLS_LABEL = {"f5": "F5", "total": "game", "team": "team",
             "k": "K", "outs": "outs"}


# ── numbers ────────────────────────────────────────────────────────────

def am(p):
    """Fair American odds for probability p."""
    if p is None or p <= 0 or p >= 1:
        return "&mdash;"
    return (f"{-100 * p / (1 - p):+.0f}" if p > 0.5
            else f"{100 * (1 - p) / p:+.0f}")


def cross(pairs):
    """Interpolate the line where P(over) crosses 0.5.

    For a total this is the number a book hangs; for a strikeout ladder it
    is the pitcher's implied K line. NOT the mean — run totals are right
    skewed, so on 10,136 real games the league mean is 8.99 against a 50/50
    line near 8.5. Comparing a simulated mean to a posted total reads as a
    run of bias that is not there.
    """
    v = sorted(p for p in pairs if p[1] is not None)
    for (l1, p1), (l2, p2) in zip(v, v[1:]):
        if p1 >= 0.5 >= p2:
            return l1 + (p1 - 0.5) / (p1 - p2) * (l2 - l1)
    return None


def fmt_cross(x):
    """Display a crossing that may not exist.

    `cross` returns None whenever every rung on the board sits on ONE side
    of even money, and the ±170 band makes that ordinary rather than rare:
    the rung that would have bracketed the crossing is exactly the one the
    band drops. COL @ NYY on 2026-09-10 printed F5 4.5 and 5.5 only — both
    under 50% — because F5 3.5 priced outside the band, and the page died
    formatting the None.
    """
    return f"{x:.2f}" if x is not None else "&mdash;"


def line_of(r):
    return float(r["bet"].split()[-1])


def keep(r):
    if r["cls"] in ("f5", "total", "team"):
        return True
    return (not r["offband"]) and r["kalshi"] and abs(r["gap"]) >= MIN_GAP


def weight(r):
    """Coin-flip weight: a gap at even money outranks one on a longshot."""
    if r["gap"] is None:
        return 0.0
    p = (r["p_over"] + r["p_kalshi"]) / 2
    return abs(r["gap"]) * 4 * p * (1 - p)


# ── cells ──────────────────────────────────────────────────────────────

def chips(r):
    out = []
    if r["thin"]:
        out.append(("thin", "THIN",
                    "Under 60% of this arm&rsquo;s priced rate is his own "
                    "record &mdash; a gap here can be our shrinkage rather "
                    "than his talent."))
    if r["bump"]:
        out.append(("bump", "tail +2",
                    "K 8.5 and up: the model prices a high-K over at ~78% "
                    "of its true probability. Two points already added."))
    if r.get("gate"):
        short = ("opener" if "opener" in r["gate"]
                 else "swingman" if "swingman" in r["gate"]
                 else "thin record")
        out.append(("gate", short,
                    "Fails the starter gate &mdash; " + r["gate"] +
                    ". The model still gives him a full starter&rsquo;s "
                    "leash, so a large gap on his rows is more likely our "
                    "error than the market&rsquo;s."))
    if r["cls"] == "outs":
        out.append(("raw", f'raw {r["raw"]}',
                    "The displayed price carries the 2026-09-05 outs "
                    "correction; this is the uncorrected number."))
    return out


def vol_cell(r):
    v = r.get("vol")
    if v is None:
        return '<td class="c-vol c-none">&mdash;</td>'
    lbl = (f"${v / 1000:.0f}k" if v >= 10000
           else f"${v / 1000:.1f}k" if v >= 1000 else f"${v:.0f}")
    if v < UNTRADED:
        return (f'<td class="c-vol novol" title="Dollars traded on the '
                f'Kalshi contract. Under ${UNTRADED:.0f} the mid is a '
                'market maker&rsquo;s resting quote, not a price anyone '
                'has taken &mdash; a gap here is model-vs-model, and '
                'there is no informed flow for it to be wrong against.">'
                f'{lbl}</td>')
    return ('<td class="c-vol" title="Dollars traded on the Kalshi '
            'contract. Real flow &mdash; a gap here is a disagreement '
            'with actual traders, which is when &lsquo;the market knows '
            'something&rsquo; is worth a news check.">'
            f'{lbl}</td>')


def price(p, cls):
    if p is None:
        return f'<td class="c-num {cls} c-none">&mdash;</td>'
    return (f'<td class="c-num {cls}">{am(p)}'
            f'<span class="pc">{p * 100:.1f}%</span></td>')


def row_html(r, game=None):
    po, pk = r["p_over"], r["p_kalshi"]
    cs = "".join(f'<span class="chip chip-{k}" title="{t}">{v}</span>'
                 for k, v, t in chips(r))
    g = f'<td class="c-game">{html.escape(game)}</td>' if game else ""
    k = "1" if (game or keep(r)) else "0"
    ag = "" if r["gap"] is None else (
        f' data-agap="{abs(r["gap"]):.1f}"'
        f' data-po="{po:.4f}" data-pk="{pk:.4f}"')
    d = "" if r["gap"] is None else ("over" if r["gap"] > 0 else "under")
    edge = ('<td class="c-gap c-none">no book</td>' if r["gap"] is None
            else f'<td class="c-gap {d}">{r["gap"]:+.1f}</td>')
    return f"""<tr class="r-{r['cls']}" data-keep="{k}"{ag}>
  {g}<td class="c-bet"><span class="mk mk-{r['cls']}">\
{CLS_LABEL[r['cls']]}</span> {html.escape(r['bet'])}{cs}</td>
  {price(po, 'c-ours')}{price(1 - po, 'c-ours')}\
{price(pk, 'c-mkt')}{price(None if pk is None else 1 - pk, 'c-mkt')}
  {vol_cell(r)}{edge}
</tr>"""


HEAD = ('<thead><tr>{g}<th>market</th>'
        '<th class="c-num">our over</th><th class="c-num">our under</th>'
        '<th class="c-num">kalshi over</th>'
        '<th class="c-num">kalshi under</th>'
        '<th class="c-vol">vol</th>'
        '<th class="c-gap">edge</th></tr></thead>')


# ── page ───────────────────────────────────────────────────────────────

def k_table(games):
    """Per-pitcher: our implied K line against the market's, plus the
    rung-by-rung point gap. Fitted on the FULL ladder, band ignored."""
    rows = []
    for g in games:
        for who in (g["ap"], g["hp"]):
            rr = [r for r in g["rows"]
                  if r["cls"] == "k" and r["bet"].startswith(who + " k ")
                  and r["kalshi"]]
            if any(r.get("gate") for r in rr):
                continue
            if len(rr) < 3:
                continue
            ours = cross([(line_of(r), r["p_over"]) for r in rr])
            mkt = cross([(line_of(r), r["p_kalshi"]) for r in rr])
            if ours is None or mkt is None:
                continue
            by = {line_of(r): r["gap"] for r in rr}
            rows.append((ours - mkt, who, f'{g["away"]} @ {g["home"]}',
                         ours, mkt, by, g))
    rows.sort(key=lambda x: -abs(x[0]))

    out = []
    for diff, who, tag, ours, mkt, by, g in rows:
        cells = ""
        for ln in K_LADDER:
            v = by.get(ln)
            if v is None:
                cells += '<td class="hx hx-na"></td>'
            else:
                d = "over" if v > 0 else "under"
                o = min(abs(v) / 18.0, 1.0)
                cells += (f'<td class="hx hx-{d}" style="--o:{o:.2f}" '
                          f'title="K {ln}: ours {abs(v):.1f} points '
                          f'{"above" if v > 0 else "below"} the mid">'
                          f'{v:+.0f}</td>')
        big = "big" if abs(diff) >= 0.40 else ""
        out.append(f"""<tr class="{big}" data-adiff="{abs(diff):.2f}">
  <td class="c-who">{html.escape(who)}</td>
  <td class="c-game"><a href="#g-{g['away']}-{g['home']}">{tag}</a></td>
  <td class="c-num">{ours:.2f}</td>
  <td class="c-num c-mkt">{mkt:.2f}</td>
  <td class="c-gap {'over' if diff > 0 else 'under'}">{diff:+.2f}</td>
  {cells}
</tr>""")
    hx = "".join(f'<th class="hx">{x}</th>' for x in K_LADDER)
    return f"""<div class="scroll"><table class="t-k" id="t-k">
  <thead><tr><th>pitcher</th><th>game</th>
    <th class="c-num">our K line</th><th class="c-num">market</th>
    <th class="c-gap">diff</th>{hx}</tr></thead>
  <tbody>{''.join(out)}</tbody></table></div>""", rows


def date_label(iso):
    from datetime import date as _d
    y, m, dd = (int(x) for x in iso.split("-"))
    t = _d(y, m, dd)
    return t.strftime("%A %-d %B %Y")


def build(d, nav=None, chat=False):
    games = d["games"]
    DATE_LABEL = date_label(d["date"])
    # Derived from the blocks themselves, not a JSON key, so an older file
    # without the counters still renders an honest header.
    posted = sum(1 for g in games if "posted" in g.get("lineups", ""))
    sched = len(games) + len(d.get("declined", []))
    lu_class = "warn" if posted < sched else ""
    allrows = [(g, r) for g in games for r in g["rows"]]
    # EVERY row with a mid renders, ranked by weight; the threshold input
    # decides what shows. Was top 12 — a fixed N hid exactly the middle of
    # the list a reader asks about next. A flagged arm's gap is mostly our
    # own leash error, so it still never leads the board; it prints in its
    # game block, chip attached.
    ranked = sorted((x for x in allrows
                     if x[1]["gap"] is not None and not x[1].get("gate")),
                    key=lambda x: weight(x[1]), reverse=True)
    fls = [x for x in (cross([(line_of(r), r["p_over"])
                              for r in g["rows"] if r["cls"] == "total"])
                       for g in games) if x]
    # Same None as `fmt_cross` guards, one aggregation up: a slate on which
    # no game brackets even money would divide by zero here.
    slate_line = sum(fls) / len(fls) if fls else 0.0

    if posted < sched:
        standfirst = (
            "Every nine on this board is <em>projected</em>. Re-run once the "
            "real cards post, two to three hours before first pitch &mdash; on "
            "the 27 August board two wrong names in a projected lineup cut the "
            "largest edge in half.")
    else:
        standfirst = ("Lineups are <em>posted</em> &mdash; these are the "
                      "numbers to act on rather than orient by.")

    ktab, krows = k_table(games)
    big = [r for r in krows if abs(r[0]) >= 0.40]
    tight = [r for r in krows if abs(r[0]) < 0.10]

    lead = "\n".join(row_html(r, f'{g["away"]} @ {g["home"]}')
                     for g, r in ranked)

    cards = []
    for g in games:
        f5 = [r for r in g["rows"] if r["cls"] == "f5"]
        fl = cross([(line_of(r), r["p_over"]) for r in f5])
        lines = "".join(
            f'<div class="f5-line"><span class="f5-n">'
            f'{r["bet"].replace("F5 total ", "")}</span>'
            f'<span class="f5-o">o {am(r["p_over"])}</span>'
            f'<span class="f5-o">u {am(1 - r["p_over"])}</span>'
            f'<span class="f5-u">{r["p_over"] * 100:.0f}%</span></div>'
            for r in f5)
        cards.append(
            f'<a class="f5-card" href="#g-{g["away"]}-{g["home"]}">'
            f'<div class="f5-top"><span class="f5-mt">'
            f'{g["away"]} @ {g["home"]}</span>'
            f'<span class="f5-mean">{fmt_cross(fl)}</span></div>'
            f'<div class="f5-arms">{html.escape(g["ap"])} '
            f'<span class="v">v</span> {html.escape(g["hp"])}</div>'
            f'<div class="f5-lines">{lines}</div></a>')

    blocks = []
    for g in games:
        rows = "\n".join(row_html(r) for r in g["rows"])
        n_keep = sum(1 for r in g["rows"] if keep(r))
        fl = cross([(line_of(r), r["p_over"])
                    for r in g["rows"] if r["cls"] == "total"])
        blocks.append(f"""<section class="game" id="g-{g['away']}-{g['home']}">
  <header class="g-head">
    <h3>{g['away']} <span class="at">@</span> {g['home']}</h3>
    <p class="g-arms">{html.escape(g['ap'])} <span class="v">v</span> \
{html.escape(g['hp'])}</p>
    <p class="g-meta"><span class="g-line" title="Where our over/under \
crosses even money — the number comparable to a posted total.">fair total \
{fmt_cross(fl)}</span><span class="g-mean" title="The simulated average. Right \
skew puts it about half a run above the line; the league's own gap is \
+0.50.">mean {g['mean']:.1f}</span><span class="g-proj">projected \
lineups</span><span class="g-count"><b class="n-keep">{n_keep}</b>\
<b class="n-all">{len(g['rows'])}</b> rungs</span></p>
  </header>
  <div class="scroll"><table>{HEAD.format(g='')}
    <tbody>
{rows}
    </tbody>
  </table></div>
</section>""")

    declines = "".join(f"<li>{html.escape(x)}</li>" for x in d["declined"]) \
        or "<li>none &mdash; both starters posted in every game priced</li>"
    notquoted = "".join(
        f'<li><b>{html.escape(x["pitcher"])}</b> '
        f'<span class="nq-g">{html.escape(x["game"])}</span> '
        f'{html.escape(x["why"])}</li>' for x in d.get("not_quoted", [])) \
        or "<li>none &mdash; every quoted arm cleared the gate</li>"

    side = f'\n<nav class="side">{nav}</nav>' if nav else ""
    # STATIC PAGES GET NO PANEL. `-m scratchpad.gen_board_html` writes a
    # file that is read off disk, often days later and often nowhere near
    # a running server, and a box that posts to a /ask nobody is serving
    # is worse than no box. The Flask path passes chat=True.
    chatbox = CHAT_HTML.replace("__DATE__", d["date"]) if chat else ""
    return f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Board &mdash; {DATE_LABEL}</title>
<style>{CSS}</style>
<div class="layout{' has-side' if nav else ''}">{side}
<div class="wrap">

<header class="masthead">
  <p class="eyebrow">Simulated board &middot; fair odds, no vig</p>
  <h1>{DATE_LABEL}</h1>
  <dl class="facts">
    <div><dt>games priced</dt><dd>{len(games)}</dd></div>
    <div><dt>simulations</dt><dd>20,000</dd></div>
    <div><dt>avg fair total</dt><dd>{slate_line:.2f}</dd></div>
    <div><dt>lineups posted</dt><dd class="{lu_class}">{posted} of {sched}</dd></div>
  </dl>
  <p class="standfirst">{standfirst}</p>
</header>
{chatbox}

<section class="kdiv" id="k-model">
  <h2>Strikeout model &mdash; where we diverge</h2>
  <p class="sub">Our implied K line against the market&rsquo;s, fitted across
  each pitcher&rsquo;s whole ladder rather than read off a single rung.
  <b>{len(big)} of {len(krows)} arms sit 0.4 strikeouts or more from the mid;
  {len(tight)} are inside 0.1.</b> The grid is the point gap at each rung
  &mdash; green where we price the over higher than the market does, red where
  lower. A row leaning one way throughout is a disagreement about the pitcher;
  the two ends disagreeing is a disagreement about the shape of his
  distribution.</p>
  <p class="filterline">line diff of at least
    <input type="number" id="kdiff-min" value="0.2" min="0" max="3"
      step="0.05" aria-label="minimum K line difference"> strikeouts
    &mdash; showing <b id="kdiff-n">&mdash;</b> of {len(krows)} arms.</p>
  {ktab}
</section>

<section class="lead" id="disagreements">
  <h2>Disagreements, all markets</h2>
  <p class="sub">Ranked by gap weighted toward even money &mdash; a 12-point gap
  on a longshot is worth less than a 9-point gap at a coin flip. <b>Edge is our
  P(over) minus the mid&rsquo;s</b>, so a positive number means we price the over
  higher than Kalshi and a negative one means we price it lower.</p>
  <p class="filterline">gap of at least
    <input type="number" id="gap-min" value="10" min="0" max="40"
      step="0.5" aria-label="minimum gap in points"> points, both prices
    inside &plusmn;<input type="number" id="odds-max" value="200"
      min="100" max="2000" step="10" aria-label="odds band, both sides">
    (blank for any odds) &mdash; showing
    <b id="gap-n">&mdash;</b> of {len(ranked)} rungs carrying a Kalshi mid.
    Off-band and thin rungs are in the count too; their chips travel with
    them.</p>
  <div class="scroll"><table class="t-lead" id="t-lead">\
{HEAD.format(g='<th>game</th>')}
    <tbody>
{lead}
    </tbody>
  </table></div>
</section>

<section class="f5" id="f5">
  <h2>First five &mdash; the product</h2>
  <p class="sub">The settled quantity the model fits directly. It does not
  beat Kalshi&rsquo;s close on outcomes &mdash; 0.1947 Brier against
  0.1927 over 2,149 contracts; an early 455-contract sample showed us ahead
  and did not survive. The large figure is the fair F5 line; no ticker
  exists for totals, so bring your own number.</p>
  <div class="f5-grid">{"".join(cards)}</div>
</section>

<section class="detail" id="games">
  <h2>Every game</h2>
  <p class="filterline">Showing
    <button type="button" class="ctl is-on" id="btn-keep"
      aria-pressed="true">actionable rungs</button>
    <button type="button" class="ctl" id="btn-all"
      aria-pressed="false">everything priced</button>
    <span class="n-keep-note">&mdash; hiding rungs outside the &plusmn;170
    band, rungs with no Kalshi mid, and anything inside {MIN_GAP:.0f} points of
    the mid. Totals and F5 always stay.</span><span class="n-all-note">&mdash;
    every rung priced, off-band longshots included.</span></p>
  {"".join(blocks)}
</section>

<section class="declined">
  <h2>Arms not quoted</h2>
  <p class="sub">The game is priced; these pitchers are not. An opener or a
  swingman given a starter&rsquo;s leash produces a confident number with nothing
  behind it &mdash; <b>this gate was dead from 5 to 9 September</b>, having lived in
  the deleted betting layer, and it is why the 8 September board carried rows on
  four arms it should not have.</p>
  <ul class="nq">{notquoted}</ul>
</section>

<section class="declined">
  <h2>Declined</h2>
  <p class="sub">Both starters or neither. A missing arm is never filled with a
  league-average stand-in &mdash; inventing the other club invents the score, and
  the score is what the hook, the bullpen and the margin are conditioned on.</p>
  <ul>{declines}</ul>
</section>

<footer class="rules">
  <h2>What the numbers carry</h2>
  <div class="rulegrid">
    <div><h4>Comparing to a sportsbook</h4><p>Kalshi&rsquo;s two sides are one
    contract, so they mirror exactly. A book&rsquo;s two sides carry its hold, so
    de-vig before comparing: an under at &minus;124 alone implies 55.4%, but with
    the over near +103 on the same book its true under is about 53%.</p></div>
    <div><h4>Strikeouts</h4><p>Usable as printed from 4.5 to 7.5. At 8.5 and up
    the tail is light and two points are already added to those overs. Against a
    closing price the K model adds nothing &mdash; its whole measured value is
    being early.</p></div>
    <div><h4>Totals</h4><p>July and August ran roughly 0.15 to 0.20 runs light a
    side; September is unmeasured. The engine over-weights three-to-six run
    games, so a low-total under lean is bias, not a read.</p></div>
    <div><h4>Not here at all</h4><p>Moneyline and run line have never been scored
    against outcomes in this repo. Batter props print elsewhere and are
    audit-only until something grades them.</p></div>
  </div>
  <p class="colophon">Read off one shared set of draws per matchup, so a
  strikeout rung and the total its start sits inside cannot contradict each
  other. <b>This is not a bet list.</b></p>
</footer>

</div>
</div>
<script>{JS}</script>
"""


#: Rendered only on the served page (`chat=True`). The log, the trace
#: under each answer and the example questions are built by CHAT_JS;
#: this is the empty frame it fills.
CHAT_HTML = """
<section class="chat" id="chat" data-date="__DATE__">
  <h2>Ask the board</h2>
  <p class="sub">Every figure in an answer comes back from a lookup &mdash;
  the board JSONs, the graded record, or read-only SQL over the two
  databases &mdash; and the calls are listed under each answer. It is told
  to say it cannot find something rather than recall it, and it knows we
  sit behind Kalshi on Brier. <b>It reads; it places nothing.</b></p>
  <div class="chat-log" id="chat-log"></div>
  <form class="chat-form" id="chat-form">
    <textarea id="chat-q" rows="1" spellcheck="false"
      placeholder="how did the strikeout rungs grade last week?"></textarea>
    <button type="submit" id="chat-send">ask</button>
  </form>
  <p class="chat-eg" id="chat-eg"></p>
</section>
"""


CSS = """
:root{
  --bg:#E7EAED; --surface:#FAFBFC; --sunk:#EFF2F4;
  --ink:#12171B; --ink2:#4E5A64; --ink3:#78848E;
  --rule:#CFD6DC; --rule2:#DFE4E9;
  --accent:#9C5F16; --accent-soft:#F0E2CE;
  --over:#0F6154; --over-soft:#D3E5E1;
  --under:#8A3049; --under-soft:#F0DAE0;
  --warn:#8A5A12;
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
  --sans:ui-sans-serif,-apple-system,"Segoe UI","Helvetica Neue",Arial,sans-serif;
  --serif:ui-serif,Georgia,"Iowan Old Style","Times New Roman",serif;
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#0E1216; --surface:#161B20; --sunk:#12171B;
    --ink:#E4E9ED; --ink2:#96A3AD; --ink3:#6B7982;
    --rule:#283037; --rule2:#1F262C;
    --accent:#D69A44; --accent-soft:#3A2E19;
    --over:#4FBAA4; --over-soft:#12312D;
    --under:#DB7B95; --under-soft:#33161F;
    --warn:#D69A44;
  }
}
:root[data-theme="dark"]{
  --bg:#0E1216; --surface:#161B20; --sunk:#12171B;
  --ink:#E4E9ED; --ink2:#96A3AD; --ink3:#6B7982;
  --rule:#283037; --rule2:#1F262C;
  --accent:#D69A44; --accent-soft:#3A2E19;
  --over:#4FBAA4; --over-soft:#12312D;
  --under:#DB7B95; --under-soft:#33161F;
  --warn:#D69A44;
}
:root[data-theme="light"]{
  --bg:#E7EAED; --surface:#FAFBFC; --sunk:#EFF2F4;
  --ink:#12171B; --ink2:#4E5A64; --ink3:#78848E;
  --rule:#CFD6DC; --rule2:#DFE4E9;
  --accent:#9C5F16; --accent-soft:#F0E2CE;
  --over:#0F6154; --over-soft:#D3E5E1;
  --under:#8A3049; --under-soft:#F0DAE0;
  --warn:#8A5A12;
}

body{background:var(--bg);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased;}
.wrap{max-width:1160px;margin:0 auto;padding:0 20px 96px;
  display:flex;flex-direction:column;gap:52px;}
h1,h2,h3,h4{text-wrap:balance;margin:0;}
p{margin:0;}
.scroll{overflow-x:auto;}
a{color:inherit;}

.masthead{padding-top:56px;display:flex;flex-direction:column;gap:18px;}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--accent);}
.masthead h1{font-size:clamp(30px,5.5vw,52px);line-height:1.02;
  letter-spacing:-.032em;font-weight:760;}
.facts{display:flex;flex-wrap:wrap;gap:0;margin:2px 0 0;
  border-top:1px solid var(--ink);border-bottom:1px solid var(--rule);}
.facts>div{padding:11px 26px 11px 0;margin-right:26px;
  border-right:1px solid var(--rule2);}
.facts>div:last-child{border-right:0;}
.facts dt{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink3);}
.facts dd{margin:2px 0 0;font-family:var(--mono);font-size:19px;
  font-variant-numeric:tabular-nums;letter-spacing:-.01em;}
.facts dd.warn{color:var(--warn);}
.standfirst{font-family:var(--serif);font-size:17px;line-height:1.62;
  max-width:63ch;color:var(--ink2);}
.standfirst em{color:var(--ink);font-style:italic;}

section>h2{font-size:13px;font-family:var(--mono);letter-spacing:.12em;
  text-transform:uppercase;color:var(--accent);
  padding-bottom:8px;border-bottom:2px solid var(--accent);
  display:inline-block;margin-bottom:14px;}
.sub{font-family:var(--serif);font-size:15px;line-height:1.6;
  color:var(--ink2);max-width:76ch;margin-bottom:20px;}
.sub em{font-style:italic;color:var(--ink);}
.sub b{color:var(--ink);font-family:var(--sans);font-size:14px;
  font-weight:660;}

table{width:100%;border-collapse:collapse;font-size:13.5px;}
thead th{font-family:var(--mono);font-size:10px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink3);font-weight:500;
  text-align:left;padding:0 10px 7px 0;border-bottom:1px solid var(--rule);
  white-space:nowrap;}
thead th.c-num,thead th.c-gap,thead th.c-vol{text-align:right;}
tbody tr{border-bottom:1px solid var(--rule2);}
tbody tr:hover{background:var(--sunk);}
td{padding:7px 10px 7px 0;vertical-align:middle;}
.c-num,.c-gap{font-family:var(--mono);font-variant-numeric:tabular-nums;
  text-align:right;white-space:nowrap;width:1%;}
.c-ours{color:var(--ink);}
.c-mkt{color:var(--ink2);}
.c-none{color:var(--ink3);font-size:11px;font-style:italic;
  font-family:var(--serif);}
.pc{display:block;font-size:10.5px;color:var(--ink3);font-weight:400;
  margin-top:1px;}
.c-gap{font-weight:640;padding-right:14px;}
.c-gap.over{color:var(--over);} .c-gap.under{color:var(--under);}
.c-vol{font-family:var(--mono);font-variant-numeric:tabular-nums;
  text-align:right;white-space:nowrap;width:1%;font-size:11.5px;
  color:var(--ink3);cursor:help;}
.c-vol.novol{color:var(--warn);font-style:italic;}
.c-game{font-family:var(--mono);font-size:11.5px;color:var(--ink3);
  white-space:nowrap;width:1%;padding-right:16px;}
.c-who{font-size:13.5px;white-space:nowrap;padding-right:14px;}
.c-bet{min-width:210px;}
.mk{display:inline-block;min-width:38px;margin-right:9px;
  font-family:var(--mono);font-size:9.5px;letter-spacing:.08em;
  text-transform:uppercase;color:var(--ink3);
  border:1px solid var(--rule);padding:1px 5px;text-align:center;}
.mk-f5{color:var(--accent);border-color:var(--accent);}
.chip{display:inline-block;margin-left:7px;font-family:var(--mono);
  font-size:9.5px;letter-spacing:.05em;padding:1px 5px;
  color:var(--ink3);background:var(--sunk);border:1px solid var(--rule2);
  cursor:help;}
.chip-thin{color:var(--warn);border-color:var(--accent-soft);
  background:var(--accent-soft);}
.chip-bump{color:var(--accent);border-color:var(--accent-soft);}
.chip-gate{color:var(--under);background:var(--under-soft);
  border-color:var(--under);letter-spacing:.07em;font-weight:600;}
.chip-novol{color:var(--warn);border-style:dashed;background:none;}

/* ── K divergence grid ────────────────────────────────────── */
.t-k tbody tr.big .c-who{font-weight:680;}
.t-k thead th.hx{text-align:center;padding-right:0;}
.hx{width:34px;text-align:center;font-family:var(--mono);font-size:11px;
  font-variant-numeric:tabular-nums;padding:7px 0;
  border-left:1px solid var(--bg);cursor:help;}
.hx-over{background:color-mix(in srgb,var(--over) calc(var(--o)*46%),
  transparent);}
.hx-under{background:color-mix(in srgb,var(--under) calc(var(--o)*46%),
  transparent);}
.hx-na{background:var(--rule2);}

/* ── F5 rail ──────────────────────────────────────────────── */
.f5-grid{display:grid;gap:1px;background:var(--rule);
  grid-template-columns:repeat(auto-fill,minmax(252px,1fr));
  border:1px solid var(--rule);}
.f5-card{display:flex;flex-direction:column;gap:7px;padding:13px 15px 15px;
  background:var(--surface);text-decoration:none;color:inherit;
  transition:background .12s;}
.f5-card:hover{background:var(--sunk);}
.f5-card:focus-visible{outline:2px solid var(--accent);outline-offset:-2px;}
.f5-top{display:flex;align-items:baseline;justify-content:space-between;
  gap:8px;}
.f5-mt{font-family:var(--mono);font-size:14px;font-weight:600;}
.f5-mean{font-family:var(--mono);font-size:20px;color:var(--accent);
  font-variant-numeric:tabular-nums;letter-spacing:-.02em;}
.f5-arms{font-size:12px;color:var(--ink3);line-height:1.35;}
.f5-arms .v,.g-arms .v{color:var(--rule);font-style:italic;}
.f5-lines{display:flex;flex-direction:column;gap:3px;margin-top:2px;
  padding-top:8px;border-top:1px solid var(--rule2);}
.f5-line{display:flex;gap:10px;font-family:var(--mono);font-size:12px;
  font-variant-numeric:tabular-nums;}
.f5-n{width:24px;color:var(--ink3);}
.f5-o{width:62px;}
.f5-u{color:var(--ink3);font-size:11px;margin-left:auto;}

/* ── per-game ─────────────────────────────────────────────── */
.detail{display:flex;flex-direction:column;gap:0;}
.filterline{font-size:12.5px;color:var(--ink3);margin-bottom:6px;
  line-height:2;}
.ctl{font:inherit;font-size:12px;padding:3px 10px;cursor:pointer;
  background:transparent;color:var(--ink2);
  border:1px solid var(--rule);border-radius:2px;margin:0 2px;
  transition:background .12s,color .12s,border-color .12s;}
.ctl:hover{border-color:var(--ink3);color:var(--ink);}
.ctl:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
.ctl.is-on{background:var(--ink);color:var(--bg);border-color:var(--ink);}
.game{padding:22px 0 6px;border-top:1px solid var(--rule);}
.game:first-of-type{border-top:2px solid var(--ink);}
.g-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 18px;
  margin-bottom:12px;}
.g-head h3{font-family:var(--mono);font-size:19px;font-weight:640;}
.g-head .at{color:var(--ink3);font-weight:400;}
.g-arms{font-size:13.5px;color:var(--ink2);}
.g-meta{margin-left:auto;display:flex;gap:14px;font-family:var(--mono);
  font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink3);}
.g-line{color:var(--accent);font-weight:600;cursor:help;}
.g-mean{color:var(--ink3);cursor:help;}
.g-proj{color:var(--warn);}
.g-count b{font-weight:600;color:var(--ink2);}

/* ── declined + rules ─────────────────────────────────────── */
.declined ul{margin:0;padding:0;list-style:none;display:flex;
  flex-direction:column;gap:8px;}
.declined li{font-family:var(--mono);font-size:12.5px;color:var(--ink2);
  padding:11px 14px;background:var(--surface);
  border-left:3px solid var(--under);}
.declined ul.nq li{border-left-color:var(--warn);}
.nq b{color:var(--ink);} .nq-g{color:var(--ink3);margin-right:10px;}
.rules{padding-top:34px;border-top:2px solid var(--ink);}
.rulegrid{display:grid;gap:26px 34px;
  grid-template-columns:repeat(auto-fit,minmax(250px,1fr));
  margin-bottom:28px;}
.rulegrid h4{font-family:var(--mono);font-size:11px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink);margin-bottom:6px;}
.rulegrid p{font-family:var(--serif);font-size:14px;line-height:1.6;
  color:var(--ink2);}
.colophon{font-family:var(--serif);font-size:14px;line-height:1.6;
  color:var(--ink3);max-width:72ch;padding-top:20px;
  border-top:1px solid var(--rule2);}
.colophon b{color:var(--ink);font-family:var(--sans);font-size:13px;
  font-weight:680;}

/* ── sidebar (server pages only; static files render without) ── */
.layout.has-side{display:flex;align-items:flex-start;}
.side{position:sticky;top:0;max-height:100vh;overflow-y:auto;
  flex:0 0 212px;padding:56px 16px 48px 20px;
  border-right:1px solid var(--rule);}
.side .side-title{font-family:var(--mono);font-size:11px;
  letter-spacing:.14em;text-transform:uppercase;color:var(--accent);
  margin-bottom:12px;}
.side details{border-bottom:1px solid var(--rule2);}
.side summary{list-style:none;cursor:pointer;padding:7px 2px;
  font-family:var(--mono);font-size:12.5px;color:var(--ink2);
  display:flex;align-items:baseline;gap:6px;}
.side summary::before{content:"+";color:var(--ink3);font-size:11px;
  width:10px;}
.side details[open] summary::before{content:"\\2212";}
.side details[open] summary{color:var(--ink);font-weight:640;}
.side summary a{text-decoration:none;color:inherit;}
.side summary a:hover{color:var(--accent);}
.side ul{list-style:none;margin:0 0 10px;padding:0 0 0 16px;
  display:flex;flex-direction:column;gap:1px;}
.side li a{display:block;padding:3px 6px;font-size:12px;
  color:var(--ink2);text-decoration:none;border-radius:2px;}
.side li a:hover{background:var(--sunk);color:var(--ink);}
.side li.side-sub{font-family:var(--mono);font-size:9.5px;
  letter-spacing:.1em;text-transform:uppercase;color:var(--ink3);
  padding:7px 6px 2px;}
@media (max-width:900px){
  .layout.has-side{display:block;}
  .side{position:static;max-height:none;border-right:0;
    border-bottom:1px solid var(--rule);padding:24px 20px 12px;}
}

#gap-min{font:inherit;font-family:var(--mono);font-size:12.5px;
  width:60px;padding:2px 5px;margin:0 3px;
  background:var(--surface);color:var(--ink);
  border:1px solid var(--rule);border-radius:2px;}
#gap-min:focus-visible{outline:2px solid var(--accent);outline-offset:1px;}
#gap-n{color:var(--ink);font-family:var(--mono);}

.n-all-note{display:none;}
body.show-all .n-keep-note{display:none;}
body.show-all .n-all-note{display:inline;}
.n-all{display:none;}
body.show-all .n-keep{display:none;}
body.show-all .n-all{display:inline;}
tbody tr.hidden{display:none;}

@media (prefers-reduced-motion:reduce){
  *{transition:none!important;animation:none!important;}
}
@media (max-width:640px){
  .wrap{padding:0 14px 64px;gap:40px;}
  .facts>div{padding-right:18px;margin-right:18px;}
  .g-meta{margin-left:0;flex-basis:100%;}
}

/* ── the ask panel ─────────────────────────────────────────────── */
.chat{background:var(--surface);border:1px solid var(--rule);
  border-radius:3px;padding:22px 24px 18px;}
.chat h2{margin:0 0 6px;}
.chat .sub{margin:0 0 16px;}
.chat-log:empty{display:none;}
.chat-log{margin:0 0 14px;display:flex;flex-direction:column;gap:16px;}
.turn-q{font-family:var(--sans);font-size:14px;font-weight:600;
  color:var(--ink);border-left:2px solid var(--accent);padding:1px 0 1px 12px;}
.turn-a{font-family:var(--serif);font-size:15px;line-height:1.62;
  color:var(--ink);}
.turn-a p{margin:0 0 10px;}
.turn-a ul{margin:0 0 10px;padding-left:20px;}
.turn-a li{margin:0 0 3px;}
.turn-a code{font-family:var(--mono);font-size:12.5px;background:var(--sunk);
  border:1px solid var(--rule2);border-radius:2px;padding:0 4px;}
.turn-a .scroll{margin:0 0 12px;}
.turn-a table{border-collapse:collapse;font-family:var(--mono);
  font-size:12.5px;}
.turn-a th,.turn-a td{border-bottom:1px solid var(--rule2);
  padding:4px 16px 4px 0;text-align:left;white-space:nowrap;}
.turn-a th{font-family:var(--sans);font-size:10.5px;letter-spacing:.06em;
  text-transform:uppercase;color:var(--ink3);}
.turn-err{font-family:var(--sans);font-size:13px;color:var(--under);
  background:var(--under-soft);border-radius:2px;padding:9px 11px;}
.trace{margin:9px 0 0;font-family:var(--mono);font-size:11.5px;
  color:var(--ink3);}
.trace summary{cursor:pointer;}
.trace summary:hover{color:var(--ink2);}
.trace ol{margin:6px 0 0;padding-left:24px;}
.trace li{margin:0 0 2px;word-break:break-word;}
.trace .bad{color:var(--under);}
.chat-form{display:flex;gap:8px;align-items:flex-end;}
.chat-form textarea{flex:1;font-family:var(--sans);font-size:14px;
  color:var(--ink);background:var(--sunk);border:1px solid var(--rule);
  border-radius:2px;padding:9px 11px;resize:none;line-height:1.45;
  max-height:170px;}
.chat-form textarea:focus{outline:none;border-color:var(--accent);}
.chat-form button{font-family:var(--sans);font-size:12px;font-weight:600;
  letter-spacing:.04em;color:var(--surface);background:var(--ink2);
  border:0;border-radius:2px;padding:10px 18px;cursor:pointer;}
.chat-form button:hover{background:var(--ink);}
.chat-form button[disabled]{background:var(--ink3);cursor:default;}
.chat-eg{margin:11px 0 0;font-family:var(--sans);font-size:12px;
  color:var(--ink3);}
.chat-eg button{font:inherit;color:var(--accent);background:none;border:0;
  border-bottom:1px dotted var(--rule);padding:0;cursor:pointer;
  margin:0 12px 0 0;}
.chat-eg button:hover{border-bottom-style:solid;}
.waiting{font-family:var(--mono);font-size:12px;color:var(--ink3);}
@media (max-width:640px){
  .chat{padding:18px 15px 15px;}
  .chat-form{flex-wrap:wrap;}
  .chat-form button{width:100%;}
}
"""

JS = r"""
(function(){
  var body=document.body,
      keep=document.getElementById('btn-keep'),
      all=document.getElementById('btn-all'),
      drop=[].slice.call(document.querySelectorAll('tbody tr'))
              .filter(function(r){return r.dataset.keep==='0';});
  function set(showAll){
    body.classList.toggle('show-all',showAll);
    keep.classList.toggle('is-on',!showAll);
    all.classList.toggle('is-on',showAll);
    keep.setAttribute('aria-pressed',String(!showAll));
    all.setAttribute('aria-pressed',String(showAll));
    drop.forEach(function(r){r.classList.toggle('hidden',!showAll);});
  }
  keep.addEventListener('click',function(){set(false);});
  all.addEventListener('click',function(){set(true);});
  set(false);
})();
(function(){
  var inp=document.getElementById('gap-min'),
      band=document.getElementById('odds-max'),
      n=document.getElementById('gap-n'),
      tbl=document.getElementById('t-lead');
  if(!inp||!tbl)return;
  var rows=[].slice.call(tbl.querySelectorAll('tbody tr'));
  function apply(){
    var min=parseFloat(inp.value),shown=0;
    if(isNaN(min))min=0;
    /* odds band: fair American +/-b <=> p in [100/(b+100), b/(b+100)],
       and BOTH prices must sit inside it. Blank means any odds. */
    var b=parseFloat(band.value),lo=0,hi=1;
    if(!isNaN(b)&&b>=100){hi=b/(b+100);lo=1-hi;}
    rows.forEach(function(r){
      var po=parseFloat(r.dataset.po),pk=parseFloat(r.dataset.pk),
          hide=(parseFloat(r.dataset.agap)||0)<min
            ||po<lo||po>hi||pk<lo||pk>hi;
      r.classList.toggle('hidden',hide);
      if(!hide)shown++;
    });
    n.textContent=shown;
  }
  inp.addEventListener('input',apply);
  band.addEventListener('input',apply);
  apply();
})();
(function(){
  var inp=document.getElementById('kdiff-min'),
      n=document.getElementById('kdiff-n'),
      tbl=document.getElementById('t-k');
  if(!inp||!tbl)return;
  var rows=[].slice.call(tbl.querySelectorAll('tbody tr'));
  function apply(){
    var min=parseFloat(inp.value),shown=0;
    if(isNaN(min))min=0;
    rows.forEach(function(r){
      var hide=(parseFloat(r.dataset.adiff)||0)<min;
      r.classList.toggle('hidden',hide);
      if(!hide)shown++;
    });
    n.textContent=shown;
  }
  inp.addEventListener('input',apply);
  apply();
})();

/* ── the ask panel ──────────────────────────────────────────────
   Answers arrive as markdown. Rather than ship a parser, this
   renders the four things the panel is told to produce — pipe
   tables, bullets, `code` and **bold** — and shows anything else as
   the paragraph it already is. EVERYTHING IS ESCAPED FIRST and the
   inline rules run on escaped text, so a stray < in a tool result
   cannot become a tag on its way through. */
(function(){
  var sec=document.getElementById('chat'),
      log=document.getElementById('chat-log'),
      form=document.getElementById('chat-form'),
      box=document.getElementById('chat-q'),
      send=document.getElementById('chat-send'),
      egs=document.getElementById('chat-eg');
  if(!sec||!form)return;
  var date=sec.dataset.date,history=[],busy=false;

  function esc(t){
    return t.replace(/&/g,'&amp;').replace(/</g,'&lt;')
            .replace(/>/g,'&gt;');
  }
  function inline(t){
    return esc(t).replace(/`([^`]+)`/g,'<code>$1</code>')
                 .replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>');
  }
  function cells(line){
    var p=line.trim().replace(/^\||\|$/g,'').split('|');
    return p.map(function(c){return c.trim();});
  }
  function md(text){
    var out=[],lines=text.split('\n'),i=0;
    while(i<lines.length){
      var ln=lines[i];
      /* a pipe table: header, a |---|---| rule, then rows */
      if(/^\s*\|.*\|\s*$/.test(ln)&&i+1<lines.length
         &&/^\s*\|[\s:|-]+\|\s*$/.test(lines[i+1])){
        var head=cells(ln),body=[];
        i+=2;
        while(i<lines.length&&/^\s*\|.*\|\s*$/.test(lines[i])){
          body.push(cells(lines[i]));i++;
        }
        out.push('<div class="scroll"><table><thead><tr>'
          +head.map(function(c){return '<th>'+inline(c)+'</th>';}).join('')
          +'</tr></thead><tbody>'
          +body.map(function(r){
              return '<tr>'+r.map(function(c){
                return '<td>'+inline(c)+'</td>';}).join('')+'</tr>';
            }).join('')
          +'</tbody></table></div>');
        continue;
      }
      if(/^\s*[-*]\s+/.test(ln)){
        var items=[];
        while(i<lines.length&&/^\s*[-*]\s+/.test(lines[i])){
          items.push('<li>'+inline(lines[i].replace(/^\s*[-*]\s+/,''))+'</li>');
          i++;
        }
        out.push('<ul>'+items.join('')+'</ul>');
        continue;
      }
      if(!ln.trim()){i++;continue;}
      var para=[];
      while(i<lines.length&&lines[i].trim()
            &&!/^\s*[-*]\s+/.test(lines[i])
            &&!/^\s*\|.*\|\s*$/.test(lines[i])){
        para.push(lines[i]);i++;
      }
      out.push('<p>'+inline(para.join(' '))+'</p>');
    }
    return out.join('');
  }
  function trace(calls){
    if(!calls||!calls.length)return '';
    var n=calls.length;
    return '<details class="trace"><summary>'+n+' lookup'
      +(n>1?'s':'')+'</summary><ol>'
      +calls.map(function(c){
          var a=JSON.stringify(c.input);
          if(a.length>180)a=a.slice(0,180)+'…';
          return '<li'+(c.error?' class="bad"':'')+'>'+esc(c.tool)+' '
                 +esc(a)+(c.error?' — failed':'')+'</li>';
        }).join('')
      +'</ol></details>';
  }
  function turn(q){
    var d=document.createElement('div');
    d.innerHTML='<div class="turn-q">'+esc(q)+'</div>'
               +'<div class="turn-a"><p class="waiting">looking…</p></div>';
    log.appendChild(d);
    return d.querySelector('.turn-a');
  }
  function grow(){
    box.style.height='auto';
    box.style.height=Math.min(box.scrollHeight,170)+'px';
  }

  function ask(q){
    if(busy||!q.trim())return;
    busy=true;send.disabled=true;
    var slot=turn(q);
    box.value='';grow();
    fetch('/ask',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({question:q,date:date,history:history})})
      .then(function(r){return r.json().then(function(j){
        return {ok:r.ok,body:j};});})
      .then(function(res){
        if(!res.ok||res.body.error){
          slot.innerHTML='<div class="turn-err">'
            +esc(res.body.error||('HTTP '+res.status))+'</div>';
          return;
        }
        slot.innerHTML=md(res.body.answer||'(no answer)')
                       +trace(res.body.trace,res.body.usage);
        /* History carries TEXT ONLY — the tool calls and their results
           stay server-side, so a long session does not resend a
           fortnight of rungs it already read. */
        history.push({role:'user',content:q});
        history.push({role:'assistant',content:res.body.answer||''});
      })
      .catch(function(e){
        slot.innerHTML='<div class="turn-err">'+esc(String(e))+'</div>';
      })
      .then(function(){
        busy=false;send.disabled=false;
        slot.scrollIntoView({block:'nearest'});
      });
  }

  form.addEventListener('submit',function(e){e.preventDefault();ask(box.value);});
  box.addEventListener('input',grow);
  box.addEventListener('keydown',function(e){
    if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask(box.value);}
  });
  [['biggest disagreement tonight',
    'What is the largest disagreement on the '+date+' board, and is the '
    +'Kalshi side of it actually traded?'],
   ['how the K model has graded',
    'How have the strikeout rungs scored against Kalshi over the last two '
    +'weeks, and is the difference bigger than its standard error?'],
   ['where we are worst',
    'Which market class has the worst head-to-head Brier against Kalshi, '
    +'and how many rungs is that judgement resting on?']]
  .forEach(function(pair){
    var b=document.createElement('button');
    b.type='button';b.textContent=pair[0];
    b.addEventListener('click',function(){box.value=pair[1];grow();ask(pair[1]);});
    egs.appendChild(b);
  });
})();
"""


def main(argv):
    date = argv[0] if argv else "2026-09-09"
    stem = date.replace("-", "_")
    src = argv[1] if len(argv) > 1 else f"bets/{stem}_board.json"
    out = argv[2] if len(argv) > 2 else f"bets/{stem}_board.html"
    page = build(json.load(open(src)))
    open(out, "w").write(page)
    print(f"wrote {out}  ({len(page):,} bytes)")


if __name__ == "__main__":
    main(sys.argv[1:])
