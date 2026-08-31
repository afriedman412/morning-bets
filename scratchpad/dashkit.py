"""THE DASHBOARD KIT — the shared visual system for every HTML page here.

Extracted 2026-08-30 from `dash.py`, which built the blind re-simulation
page. `board.py --html` renders the same league in the same idiom, and two
copies of a 120-line stylesheet drift within a week.

WHAT IS SHARED. The colour tokens (away ochre, home teal, the dashed-red
actual marker), the type pairing, and four primitives: `hist` bins a sample,
`bars` draws it, `statline` writes the moments underneath, `thresholds`
writes the over-ladder. Everything a page does with those is its own.

WHY A FRAGMENT AND NOT A DOCUMENT. `document()` emits `<title>`, `<style>`
and body markup with no `<!doctype>`, `<html>` or `<head>`. That is what the
Artifact publisher wants, and a browser opening the file directly hoists the
tags itself, so ONE string serves both. The cost is that there is no
`<meta charset>` to lean on, so **everything rendered through here must be
ASCII** — use `&mdash;`, `&times;`, `&middot;` rather than the characters.
`check_dashkit_output_is_ascii` pins it.
"""
from __future__ import annotations

import statistics as st

#: en/em dashes and friends, as entities. See the docstring.
MDASH = "&mdash;"
NDASH = "&ndash;"
MIDDOT = "&middot;"
GEQ = "&ge;"

_DARK = """--ink:#e6e9ed; --paper:#0e1116; --card:#161a20;
  --line:#262c34; --line2:#1d222a; --dim:#98a2ad; --dimmer:#5d6672;
  --away:#e08b4e; --home:#4fa8a4;
  --awaySoft:#2a1f16; --homeSoft:#14262a; --hit:#ff6b5e;"""

_LIGHT = """--ink:#12161b; --paper:#fbfbfc; --card:#ffffff;
  --line:#dfe3e8; --line2:#eef1f4; --dim:#68727e; --dimmer:#98a2ad;
  --away:#b6642f; --home:#2c6f73;
  --awaySoft:#f0e2d6; --homeSoft:#dceceb; --hit:#c0392b;"""

#: The base sheet. A page appends its own rules to this rather than
#: redefining these, so the two pages stay recognisably the same product.
CSS = """
:root{
  --ink:#12161b; --paper:#fbfbfc; --card:#ffffff;
  --line:#dfe3e8; --line2:#eef1f4;
  --dim:#68727e; --dimmer:#98a2ad;
  --away:#b6642f; --home:#2c6f73;
  --awaySoft:#f0e2d6; --homeSoft:#dceceb;
  --hit:#c0392b;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,sans-serif;
}
@media (prefers-color-scheme:dark){:root{__DARK__}}
:root[data-theme="dark"]{__DARK__}
:root[data-theme="light"]{__LIGHT__}

*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:var(--sans);line-height:1.5;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:40px 24px 96px}
h1{font-size:26px;letter-spacing:-.02em;margin:0 0 4px;font-weight:650;
  text-wrap:balance}
.lede{color:var(--dim);font-size:14px;margin:0 0 6px;max-width:64ch}
.meta{font-family:var(--mono);font-size:11.5px;color:var(--dimmer);
  margin:14px 0 0;padding-top:14px;border-top:1px solid var(--line);
  display:flex;flex-wrap:wrap;gap:6px 22px}
.meta b{color:var(--dim);font-weight:500}
.warn{margin:20px 0 0;padding:11px 14px;border-left:2px solid var(--away);
  background:var(--awaySoft);font-size:13px;color:var(--ink);
  border-radius:0 4px 4px 0}
.game{margin-top:52px}
.gh{display:flex;align-items:baseline;gap:18px;flex-wrap:wrap;
  padding-bottom:12px;border-bottom:1px solid var(--line)}
.gt{display:flex;align-items:baseline;gap:9px}
.club{font-family:var(--mono);font-size:23px;font-weight:600;
  letter-spacing:-.01em}
.club.a{color:var(--away)} .club.h{color:var(--home)}
.at{color:var(--dimmer);font-size:13px}
.gsp{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--dim)}
.gsp span{display:flex;align-items:center;gap:6px}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block;flex:none}
.dot.a{background:var(--away)} .dot.h{background:var(--home)}
.gn{margin-left:auto;font-family:var(--mono);font-size:11px;
  color:var(--dimmer)}
.rh{font-size:11px;text-transform:uppercase;letter-spacing:.11em;
  color:var(--dimmer);font-weight:600;margin:26px 0 10px}
.grid{display:grid;gap:14px}
.g4{grid-template-columns:repeat(4,1fr)}
.g3{grid-template-columns:repeat(3,1fr)}
.g2{grid-template-columns:repeat(2,1fr)}
@media (max-width:940px){.g4{grid-template-columns:repeat(2,1fr)}
  .g3{grid-template-columns:1fr} .g2{grid-template-columns:1fr}}
@media (max-width:560px){.g4{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;
  padding:14px 14px 12px;min-width:0}
.card header{margin-bottom:10px}
.card h4{margin:0;font-size:13.5px;font-weight:600;letter-spacing:-.01em}
.card header p{margin:1px 0 0;font-size:11px;color:var(--dimmer);
  text-transform:uppercase;letter-spacing:.07em}
.series+.series{margin-top:12px}
.sn{display:flex;justify-content:space-between;align-items:baseline;
  font-family:var(--mono);font-size:11px;color:var(--dim);margin-bottom:3px}
.sn b{color:var(--ink);font-size:12.5px;font-variant-numeric:tabular-nums}
.hist{display:flex;align-items:flex-end;gap:1px;height:54px;
  padding-top:12px;position:relative}
.bar{flex:1 1 0;min-width:0;display:flex;flex-direction:column;
  justify-content:flex-end;align-items:center;height:100%;position:relative}
.bar i{display:block;width:100%;height:var(--h);background:var(--c);
  border-radius:1px 1px 0 0;min-height:1px;opacity:.88}
.bar:hover i{opacity:1}
.bv{position:absolute;top:-11px;font-family:var(--mono);font-size:8.5px;
  color:var(--dimmer);opacity:0;transition:opacity .12s}
.bar:hover .bv{opacity:1}
.bl{font-family:var(--mono);font-size:8.5px;color:var(--dimmer);
  margin-top:3px;white-space:nowrap}
.sl{display:flex;flex-wrap:wrap;gap:3px 12px;font-size:10.5px;
  color:var(--dimmer);font-family:var(--mono);margin-top:9px}
.sl b{color:var(--ink);font-variant-numeric:tabular-nums;font-weight:600}
.ths{display:grid;grid-template-columns:repeat(2,1fr);gap:2px 10px;
  margin-top:9px;padding-top:8px;border-top:1px solid var(--line2)}
.th{display:flex;justify-content:space-between;font-family:var(--mono);
  font-size:11px}
.thl{color:var(--dimmer)}
.thv{color:var(--ink);font-variant-numeric:tabular-nums;font-weight:600}
.sp{min-width:0}
.spn{display:flex;align-items:center;gap:7px;font-size:14.5px;
  font-weight:600;letter-spacing:-.01em;margin-bottom:2px}
.spc{font-family:var(--mono);font-size:10.5px;color:var(--dimmer);
  font-weight:500}
.spm{display:flex;gap:14px;flex-wrap:wrap;font-family:var(--mono);
  font-size:11px;color:var(--dim);margin-bottom:14px}
.spm b{color:var(--ink);font-variant-numeric:tabular-nums}
.sub{font-size:10.5px;text-transform:uppercase;letter-spacing:.09em;
  color:var(--dimmer);font-weight:600;margin:16px 0 0}
.sub:first-of-type{margin-top:4px}
.act{position:absolute;top:0;bottom:14px;width:0;
  border-left:2px dashed var(--hit);transform:translateX(-1px);
  pointer-events:none;z-index:2}
.act span{position:absolute;top:-13px;left:50%;transform:translateX(-50%);
  font-family:var(--mono);font-size:9.5px;font-weight:700;color:var(--hit);
  background:var(--card);padding:0 3px;white-space:nowrap;border-radius:2px}
.bar.hit i{opacity:1;outline:1px solid var(--hit);outline-offset:-1px}
.actout{position:absolute;top:-2px;right:0;font-family:var(--mono);
  font-size:9px;color:var(--hit)}
.ac{color:var(--hit) !important}
.ac b{color:var(--hit) !important}
.pc{font-family:var(--mono);font-size:10px;color:var(--hit);margin-left:7px}
.fin{margin:10px 0 0;font-family:var(--mono);font-size:13px;color:var(--dim)}
.fin b{color:var(--ink);font-size:15px}
a:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--home);
  outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{transition:none !important;
  animation:none !important}}
""".replace("__DARK__", _DARK).replace("__LIGHT__", _LIGHT)


def esc(s):
    """Payload text -> ASCII-safe HTML. Use it on EVERY value from the data.

    Two things get through otherwise and both did, on the first live run:
    a pitcher named `Jose Ramirez` is spelled with two accents in the roster,
    and `gamestate` writes its decline reason with an em dash. Neither is a
    bug in the data &mdash; a fragment simply has no `<meta charset>`, so the
    escaping has to happen here. Angle brackets go too, since a name is
    interpolated straight into markup.
    """
    s = (str(s).replace("&", "&amp;").replace("<", "&lt;")
         .replace(">", "&gt;").replace('"', "&quot;"))
    return s.encode("ascii", "xmlcharrefreplace").decode("ascii")


def expand(d):
    """{"4": 12, ...} -> a sorted sample. Counts are how draws are stored."""
    out = []
    for k, v in d.items():
        out.extend([int(k)] * v)
    return sorted(out)


def stats(vals):
    v = sorted(vals)
    n = len(v)
    return {"mean": st.mean(v), "med": v[n // 2],
            "p10": v[n // 10], "p90": v[9 * n // 10], "sd": st.pstdev(v)}


def hist(vals, lo=None, hi=None, binw=1):
    lo = lo if lo is not None else int(min(vals))
    hi = hi if hi is not None else int(max(vals))
    bins = {}
    for v in vals:
        b = lo + int((v - lo) // binw) * binw
        b = max(lo, min(b, hi))
        bins[b] = bins.get(b, 0) + 1
    n = len(vals)
    return [(k, bins.get(k, 0) / n) for k in range(lo, hi + 1, binw)]


def over(vals, line):
    return sum(1 for v in vals if v > line) / len(vals)


def pctile(vals, x):
    n = len(vals)
    below = sum(1 for v in vals if v < x)
    at = sum(1 for v in vals if v == x)
    return (below + at / 2) / n


def bars(h, colour, label_every=1, fmt=lambda k: str(k), actual=None,
         binw=1, mark=None, mark_label=None):
    """Histogram.

    `actual` draws the dashed marker in the bin it falls in &mdash; the blind
    re-simulation page uses it for what happened. `mark` draws the same
    marker at an arbitrary VALUE on the axis, which is how the board shows a
    betting line sitting between two bins.
    """
    peak = max(p for _, p in h) or 1
    cells, hit = [], None
    for i, (k, p) in enumerate(h):
        lab = fmt(k) if i % label_every == 0 else ""
        on = actual is not None and k <= actual < k + binw
        if on:
            hit = i
        cells.append(
            f'<div class="bar{" hit" if on else ""}" '
            f'style="--h:{p / peak * 100:.1f}%;--c:{colour}" '
            f'title="{fmt(k)} {MDASH} {p * 100:.1f}%">'
            f'<span class="bv">{p * 100:.0f}</span>'
            f'<i></i><span class="bl">{lab}</span></div>')
    tail = ""
    if hit is not None:
        left = (hit + 0.5) / len(h) * 100
        tail = (f'<div class="act" style="left:{left:.2f}%">'
                f'<span>{actual:g}</span></div>')
    elif actual is not None:
        tail = f'<div class="actout">actual {actual:g}</div>'
    if mark is not None and h:
        lo, step = h[0][0], binw
        pos = (mark - lo) / step + 0.5
        if 0 <= pos <= len(h):
            left = min(max(pos / len(h) * 100, 0), 100)
            lab = mark_label if mark_label is not None else f"{mark:g}"
            tail += (f'<div class="act" style="left:{left:.2f}%">'
                     f'<span>{lab}</span></div>')
    return f'<div class="hist">{"".join(cells)}{tail}</div>'


def thresholds(vals, lines, fmt="{:.0%}"):
    out = [f'<div class="th"><span class="thl">{lab}</span>'
           f'<span class="thv">{fmt.format(over(vals, ln))}</span></div>'
           for lab, ln in lines]
    return f'<div class="ths">{"".join(out)}</div>'


def statline(s, actual=None, vals=None):
    act = ""
    if actual is not None and vals is not None:
        act = (f'<span class="ac"><b>{actual:g}</b> actual {MIDDOT} '
               f'{pctile(vals, actual):.0%} pctile</span>')
    return (f'<div class="sl">'
            f'<span><b>{s["mean"]:.2f}</b> mean</span>'
            f'<span><b>{s["med"]}</b> median</span>'
            f'<span><b>{s["p10"]}{NDASH}{s["p90"]}</b> 10{NDASH}90</span>'
            f'<span><b>{s["sd"]:.2f}</b> sd</span>{act}</div>')


def card(title, sub, body):
    return (f'<section class="card"><header><h4>{title}</h4>'
            f'<p>{sub}</p></header>{body}</section>')


def document(title, body, extra_css=""):
    """One string that is BOTH a publishable fragment and an openable file.

    No doctype and no head: the Artifact publisher supplies them, and a
    browser given the bare fragment hoists `<title>` and `<style>` itself.
    """
    return (f"<title>{title}</title><style>{CSS}{extra_css}</style>"
            f"{body}")
