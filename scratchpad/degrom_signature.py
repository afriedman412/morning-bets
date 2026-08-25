"""Is deGrom a phenomenon or a coincidence? Count how many share his shape.

He is the case that motivated looking, NOT evidence. n=7 makes compelling
stories cheap, and six of seven going under is exactly the kind of run that
turns up somewhere in a league of 300 starters every month.

Two questions, both high-n, in the order that matters:

  1. HOW COMMON IS THE SIGNATURE? A window where K% holds but outs per
     batter faced falls. If it is one pitcher it is noise; if it is a
     recurring shape there is a mechanism.

  2. DOES IT PREDICT? This is the whole question and it is the one the
     deGrom story cannot answer about itself. Regress the NEXT start's
     outs on the trailing window's outs residual, with the pitcher's own
     season mean partialled out so it cannot be measuring who is good.
     Predictive power here is what licenses recency in the rates; its
     absence means the last seven starts describe the past only.

Every window is strictly prior to the start being predicted, and the
baseline each is measured against EXCLUDES both — see the note in `main`.
Residualising against the season mean instead put a -0.158 artifact into a
measurement whose true value is +0.21, i.e. it reversed the sign.

    venv/bin/python -m scratchpad.degrom_signature [window]
"""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict

from src import db

MIN_STARTS = 14
WINDOW = 7


def starts() -> dict:
    q = """select p.player_name n, g.date d, p.outs_recorded o, p.k, p.bb,
                  p.h, p.hr, p.pitches,
                  p.outs_recorded + p.h + p.bb bf
           from mlb_pitching p join games g on g.game_id = p.game_id
           where p.is_starter = 1 and g.status = 'Final'
             and p.outs_recorded is not null and p.outs_recorded > 0
           order by g.date"""
    by: dict = defaultdict(list)
    with db.connect() as c:
        for r in c.execute(q):
            by[r["n"]].append(dict(r))
    return {k: v for k, v in by.items() if len(v) >= MIN_STARTS}


def corr(xs, ys) -> tuple:
    n = len(xs)
    if n < 3:
        return 0.0, 0.0
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if not sx or not sy:
        return 0.0, 0.0
    r = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n * sx * sy)
    se = ((1 - r * r) / max(n - 2, 1)) ** 0.5
    return r, (r / se if se else 0.0)


def main():
    w = int(sys.argv[1]) if len(sys.argv) > 1 else WINDOW
    by = starts()
    print(f"{len(by)} pitchers with >= {MIN_STARTS} starts, "
          f"{sum(len(v) for v in by.values()):,} starts, window {w}\n")

    sig = 0
    rows = []
    # THE BASELINE MUST SHARE NO STARTS WITH EITHER SIDE.
    #
    # A first pass residualised against the pitcher's SEASON mean, which
    # contains both the window and the start being predicted. That forces a
    # negative correlation out of pure noise: for n starts and a window of
    # w, the artifact is
    #
    #     r = (-1/n) / sqrt((1/w - 1/n)(1 - 1/n))
    #
    # which is -0.158 at n=21, w=7. The measured value was -0.112, i.e. LESS
    # negative than noise — so the naive reading ("recent form mean-reverts")
    # had the sign of the real effect backwards. Baseline here excludes the
    # window and the next start both, so zero is zero.
    for name, ss in by.items():
        # Season baselines, for residualising. Computed over the WHOLE
        # season deliberately: the question is whether a window departs
        # from the man himself, and using a prior-only baseline would
        # make the early season all noise.
        tot_bf = sum(s["bf"] for s in ss)
        base_k = sum(s["k"] for s in ss) / tot_bf
        base_ob = sum(s["o"] for s in ss) / tot_bf
        base_o = st.mean(s["o"] for s in ss)
        for i in range(w, len(ss)):
            win = ss[i - w:i]
            nxt = ss[i]
            rest = ss[:i - w] + ss[i + 1:]       # neither window nor next
            if len(rest) < 4:
                continue
            rbf = sum(s["bf"] for s in rest) or 1
            b_k = sum(s["k"] for s in rest) / rbf
            b_ob = sum(s["o"] for s in rest) / rbf
            b_o = st.mean(s["o"] for s in rest)
            bf = sum(s["bf"] for s in win) or 1
            rows.append({
                "name": name, "date": nxt["d"],
                "d_k": sum(s["k"] for s in win) / bf - b_k,
                "d_ob": sum(s["o"] for s in win) / bf - b_ob,
                "d_outs": st.mean(s["o"] for s in win) - b_o,
                "next": nxt["o"] - b_o,
            })
        # The signature: last window, K% intact, out rate down.
        last = ss[-w:]
        bf = sum(s["bf"] for s in last) or 1
        if (abs(sum(s["k"] for s in last) / bf - base_k) < 0.02
                and sum(s["o"] for s in last) / bf - base_ob < -0.04):
            sig += 1

    print(f"  pitchers whose FINAL {w} starts show the signature "
          f"(K% within 2pts of season, out rate down 4+ pts): "
          f"{sig} of {len(by)}")

    print(f"\n  {len(rows):,} (window -> next start) pairs, residualised "
          f"against a baseline holding neither\n")
    print(f"    {'predictor':<34}{'r':>9}{'sigma':>8}")
    for key, lbl in (("d_outs", "window mean OUTS residual"),
                     ("d_ob", "window OUTS PER BF residual"),
                     ("d_k", "window K% residual")):
        r, t = corr([x[key] for x in rows], [x["next"] for x in rows])
        print(f"    {lbl:<34}{r:>+9.4f}{t:>+8.1f}")

    # In outs, which is what decides whether it is worth carrying.
    xs = [x["d_ob"] for x in rows]
    ys = [x["next"] for x in rows]
    sx = st.pstdev(xs)
    r, _ = corr(xs, ys)
    slope = r * st.pstdev(ys) / sx if sx else 0.0
    lo, hi = sorted(xs)[len(xs) // 10], sorted(xs)[9 * len(xs) // 10]
    print(f"\n  one sd of window out-rate ({sx:.4f} per BF) is worth "
          f"{abs(slope * sx):.3f} outs")
    print(f"  in the next start; 10th-to-90th window spread is worth "
          f"{abs(slope * (hi - lo)):.3f} outs")

    # And the case that started it, scored the same way as everyone else.
    dg = [x for x in rows if x["name"] == "Jacob deGrom"]
    if dg:
        print(f"\n  Jacob deGrom, his {len(dg)} windows, same residual scale")
        print(f"    {'next start':<14}{'window d_ob':>13}{'window d_outs':>15}"
              f"{'next resid':>12}")
        for x in dg[-8:]:
            print(f"    {x['date']:<14}{x['d_ob']:>+13.4f}"
                  f"{x['d_outs']:>+15.2f}{x['next']:>+12.2f}")


if __name__ == "__main__":
    main()
