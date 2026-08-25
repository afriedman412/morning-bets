"""Render the blind re-simulation into a static dashboard."""
import json
import statistics as st

DATA = json.load(open("scratchpad/lastnight0.json"))
ACT = json.load(open("scratchpad/actuals.json"))
OUT = ("/private/tmp/claude-501/-Users-user-Documents-code-morning-bets/"
       "24fbc992-224a-46bb-9f62-f739fbeec48b/scratchpad/lastnight.html")


def expand(d):
    out = []
    for k, v in d.items():
        out.extend([int(k)] * v)
    return sorted(out)


def stats(vals):
    n = len(vals)
    return {"mean": st.mean(vals), "med": vals[n // 2],
            "p10": vals[n // 10], "p90": vals[9 * n // 10],
            "sd": st.pstdev(vals)}


def hist(vals, lo=None, hi=None, binw=1):
    lo = lo if lo is not None else min(vals)
    hi = hi if hi is not None else max(vals)
    bins = {}
    for v in vals:
        b = lo + ((v - lo) // binw) * binw
        b = max(lo, min(b, hi))
        bins[b] = bins.get(b, 0) + 1
    n = len(vals)
    keys = list(range(lo, hi + 1, binw))
    return [(k, bins.get(k, 0) / n) for k in keys]


def over(vals, line):
    return sum(1 for v in vals if v > line) / len(vals)


def bars(h, colour, label_every=1, fmt=lambda k: str(k), actual=None,
         binw=1):
    """Histogram. `actual` draws a dashed marker in the bin it falls in."""
    peak = max(p for _, p in h) or 1
    cells = []
    hit = None
    for i, (k, p) in enumerate(h):
        pct = p / peak * 100
        lab = fmt(k) if i % label_every == 0 else ""
        on = actual is not None and k <= actual < k + binw
        if on:
            hit = i
        cells.append(
            f'<div class="bar{" hit" if on else ""}" '
            f'style="--h:{pct:.1f}%;--c:{colour}" '
            f'title="{fmt(k)} — {p * 100:.1f}%">'
            f'<span class="bv">{p * 100:.0f}</span>'
            f'<i></i><span class="bl">{lab}</span></div>')
    mark = ""
    if hit is not None:
        left = (hit + 0.5) / len(h) * 100
        mark = (f'<div class="act" style="left:{left:.2f}%">'
                f'<span>{actual:g}</span></div>')
    elif actual is not None:
        mark = f'<div class="actout">actual {actual:g}</div>'
    return f'<div class="hist">{"".join(cells)}{mark}</div>'


def thresholds(vals, lines, fmt="{:.0%}"):
    out = []
    for lab, ln in lines:
        out.append(f'<div class="th"><span class="thl">{lab}</span>'
                   f'<span class="thv">{fmt.format(over(vals, ln))}</span></div>')
    return f'<div class="ths">{"".join(out)}</div>'


def pctile(vals, x):
    n = len(vals)
    below = sum(1 for v in vals if v < x)
    at = sum(1 for v in vals if v == x)
    return (below + at / 2) / n


def statline(s, actual=None, vals=None):
    act = ""
    if actual is not None and vals is not None:
        act = (f'<span class="ac"><b>{actual:g}</b> actual · '
               f'{pctile(vals, actual):.0%} pctile</span>')
    return (f'<div class="sl">'
            f'<span><b>{s["mean"]:.2f}</b> mean</span>'
            f'<span><b>{s["med"]}</b> median</span>'
            f'<span><b>{s["p10"]}–{s["p90"]}</b> 10–90</span>'
            f'<span><b>{s["sd"]:.2f}</b> sd</span>{act}</div>')


def card(title, sub, body):
    return (f'<section class="card"><header><h4>{title}</h4>'
            f'<p>{sub}</p></header>{body}</section>')


def game_block(g):
    d = {k: expand(v) for k, v in g["dist"].items()}
    A, H = g["away"], g["home"]
    a = ACT.get(f"{A}@{H}", {})
    ac, hc = "var(--away)", "var(--home)"
    out = [f'<article class="game">']
    out.append(
        f'<div class="gh">'
        f'<div class="gt"><span class="club a">{A}</span>'
        f'<span class="at">at</span>'
        f'<span class="club h">{H}</span></div>'
        f'<div class="gsp">'
        f'<span><i class="dot a"></i>{g["away_sp"]}</span>'
        f'<span><i class="dot h"></i>{g["home_sp"]}</span></div>'
        f'<div class="gn">{g["n"]:,} simulations</div></div>')
    if a.get("away_runs") is not None:
        out.append(f'<div class="fin">Final <b>{A} {a["away_runs"]}</b>'
                   f' — <b>{a["home_runs"]} {H}</b></div>')

    # Team totals through 3 / 5 / 7 / final — a real sequence, so ordered.
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
                f'<div class="series"><div class="sn">{club}'
                f'<span><b>{s["mean"]:.2f}</b>{pc}</span></div>'
                f'{bars(hist(v, 0, hi), col, actual=av)}</div>')
        lines = [("o2.5", 2.5), ("o3.5", 3.5)] if key != "runs" else \
                [("o3.5", 3.5), ("o4.5", 4.5)]
        th = "".join(
            f'<div class="th"><span class="thl">{club} {lab2}</span>'
            f'<span class="thv">{over(d[f"{side}_{key}"], ln):.0%}</span></div>'
            for club, side in ((A, "away"), (H, "home"))
            for lab2, ln in lines)
        out.append(card(lab, "runs scored", "".join(inner)
                        + f'<div class="ths">{th}</div>'))
    out.append('</div>')

    # Starters
    out.append('<h3 class="rh">Starters</h3>')
    out.append('<div class="grid g2">')
    for name, side, col, club in ((g["away_sp"], "away", ac, A),
                                  (g["home_sp"], "home", hc, H)):
        o = d[f"{side}_sp_outs"]
        k = d[f"{side}_sp_k"]
        pt = d[f"{side}_sp_pitches"]
        so, sk, sp = stats(o), stats(k), stats(pt)
        ip = f'{so["med"] // 3}.{so["med"] % 3}'
        block = (
            f'<div class="sp"><div class="spn"><i class="dot '
            f'{"a" if side == "away" else "h"}"></i>{name}'
            f'<span class="spc">{club}</span></div>'
            f'<div class="spm"><span>median <b>{ip}</b> IP</span>'
            f'<span><b>{sk["mean"]:.1f}</b> K</span>'
            f'<span><b>{sp["mean"]:.0f}</b> pitches</span></div>'
            f'<div class="sub">Outs recorded</div>'
            f'{bars(hist(o, 0, 27), col, 3, actual=a.get(f"{side}_sp_outs"))}'
            f'{statline(so, a.get(f"{side}_sp_outs"), o)}'
            + thresholds(o, [("o14.5", 14.5), ("o15.5", 15.5),
                             ("o17.5", 17.5), ("o18.5", 18.5)])
            + f'<div class="sub">Strikeouts</div>'
            f'{bars(hist(k, 0, 14), col, actual=a.get(f"{side}_sp_k"))}'
            f'{statline(sk, a.get(f"{side}_sp_k"), k)}'
            + thresholds(k, [("o4.5", 4.5), ("o5.5", 5.5),
                             ("o6.5", 6.5), ("o7.5", 7.5)])
            + f'<div class="sub">Pitch count</div>'
            + bars(hist(pt, 20, 115, 5), col, 2, binw=5,
                   actual=a.get(f"{side}_sp_pitches"))
            + statline(sp, a.get(f"{side}_sp_pitches"), pt)
            + thresholds(pt, [("≥80", 79.5), ("≥90", 89.5),
                              ("≥100", 99.5), ("≥110", 109.5)])
            + '</div>')
        out.append(f'<section class="card">{block}</section>')
    out.append('</div></article>')
    return "".join(out)


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
@media (prefers-color-scheme:dark){
  :root{--ink:#e6e9ed; --paper:#0e1116; --card:#161a20;
    --line:#262c34; --line2:#1d222a; --dim:#98a2ad; --dimmer:#5d6672;
    --away:#e08b4e; --home:#4fa8a4;
    --awaySoft:#2a1f16; --homeSoft:#14262a;}
}
:root[data-theme="dark"]{--ink:#e6e9ed; --paper:#0e1116; --card:#161a20;
  --line:#262c34; --line2:#1d222a; --dim:#98a2ad; --dimmer:#5d6672;
  --away:#e08b4e; --home:#4fa8a4;
  --awaySoft:#2a1f16; --homeSoft:#14262a; --hit:#ff6b5e;}
:root[data-theme="light"]{--ink:#12161b; --paper:#fbfbfc; --card:#ffffff;
  --line:#dfe3e8; --line2:#eef1f4; --dim:#68727e; --dimmer:#98a2ad;
  --away:#b6642f; --home:#2c6f73;
  --awaySoft:#f0e2d6; --homeSoft:#dceceb; --hit:#c0392b;}

*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:var(--sans);line-height:1.5;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:40px 24px 96px}
h1{font-size:26px;letter-spacing:-.02em;margin:0 0 4px;font-weight:650}
.lede{color:var(--dim);font-size:14px;margin:0 0 6px;max-width:64ch}
.meta{font-family:var(--mono);font-size:11.5px;color:var(--dimmer);
  margin:14px 0 0;padding-top:14px;border-top:1px solid var(--line);
  display:flex;flex-wrap:wrap;gap:6px 22px}
.meta b{color:var(--dim);font-weight:500}
.warn{margin:20px 0 0;padding:11px 14px;border-left:2px solid var(--away);
  background:var(--awaySoft);font-size:13px;color:var(--ink);border-radius:0 4px 4px 0}
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
.g2{grid-template-columns:repeat(2,1fr)}
@media (max-width:940px){.g4{grid-template-columns:repeat(2,1fr)}
  .g2{grid-template-columns:1fr}}
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
.hist{position:relative}
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
.pc{font-family:var(--mono);font-size:10px;color:var(--hit);
  margin-left:7px}
.fin{margin:10px 0 0;font-family:var(--mono);font-size:13px;color:var(--dim)}
.fin b{color:var(--ink);font-size:15px}
"""


def main():
    body = [f'<div class="wrap">',
            '<h1>Six games, re-simulated blind</h1>',
            '<p class="lede">Games played 24 August 2026, priced as if they '
            'had not been. Every rate is computed from data strictly before '
            'the game date, so no game can inform its own prediction, and '
            'nothing here reads a result — not the score, not a boxscore '
            'line, not the starters’ actual outs. Batting orders only.</p>',
            '<div class="meta">'
            '<span><b>Simulations</b> 20,000 per game</span>'
            '<span><b>Games</b> 6</span>'
            '<span><b>Rates cutoff</b> before 2026-08-24</span>'
            '<span><b>Engine</b> game.simulate_game</span>'
            '<span><b>Hook</b> two branches, refit per population</span>'
            '<span><b>Bullpen</b> sampled per draw from real arms</span>'
            '</div>',
            '<div class="warn">The <b>dashed red line</b> is what actually happened. '
            'It was added after the fact — the simulation never saw it. '
            '“Pctile” is where the real result landed inside the predicted '
            'distribution; 50% means dead centre.</div>']
    for g in DATA:
        body.append(game_block(g))
    body.append('</div>')
    html = (f'<title>Six games, re-simulated blind</title>'
            f'<style>{CSS}</style>' + "".join(body))
    open(OUT, "w").write(html)
    print(f"wrote {OUT}  ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
