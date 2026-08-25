"""Is there a per-PITCHER and per-CLUB leash, and would knowing it PAY?

`scratchpad/between.py` found the pattern that motivates this: a pitcher's
residual on strikeouts, hits, walks and earned runs is noise (r +0.01 to
-0.09), but his residual on OUTS is stable at +0.295. His rates are already
estimated over his own season, so his per-batter performance is right by
construction — what is wrong is HOW LONG HE IS LEFT IN. That is a leash, not
a rate error, and it is the only reading consistent with all five columns.

This asks the deployable version of the question. Every offset is computed
from STRICTLY PRIOR starts on an expanding window, so a start is never
predicted with knowledge of itself or of anything later. Shrinkage is not
searched: the constant is `within_var / between_var` read off the
model-free ANOVA, which is the posterior mean of a normal-normal and is a
MEASURED quantity, not a tuned one. Handing it to a grid would let it
absorb whatever else is wrong.

Order is club first, then pitcher against the remainder. Fitting both
independently and adding them counts the manager twice — the same rule
`calibrate --patience` follows, and the reason it exists.

    venv/bin/python -m scratchpad.leash [min_prior]
"""
import statistics as st
import sys
from collections import defaultdict

from scratchpad.between import _corr, load, variance_components


def expanding(rows, stat="outs", min_prior=3):
    """[(row, base_pred, club_off, pitcher_off)] using prior starts only."""
    rows = sorted(rows, key=lambda r: (r["date"], r["game_id"]))
    vc_p = variance_components(rows, lambda r: r["player"], stat)
    # Shrinkage constant K: a group needs K starts before its own mean
    # outweighs the league prior. K = within_var / between_var falls out of
    # the normal-normal posterior; both numbers are measured above.
    k_p = (vc_p["within"] ** 2) / (vc_p["between"] ** 2)
    vc_c = variance_components(rows, lambda r: r["team"], stat, min_n=30)
    k_c = (vc_c["within"] ** 2) / (vc_c["between"] ** 2)
    print(f"  pitcher: between {vc_p['between']:.2f} within "
          f"{vc_p['within']:.2f}  ->  K = {k_p:.1f} starts")
    print(f"  club:    between {vc_c['between']:.2f} within "
          f"{vc_c['within']:.2f}  ->  K = {k_c:.1f} starts")

    club_sum, club_n = defaultdict(float), defaultdict(int)
    p_sum, p_n = defaultdict(float), defaultdict(int)
    out = []
    for r in rows:
        base = r[f"m_{stat}"]
        t, p = r["team"], r["player"]
        c_off = (club_sum[t] / (club_n[t] + k_c)) if club_n[t] else 0.0
        # the pitcher is fitted against what the club offset has NOT already
        # explained, so the manager is not counted twice
        p_off = (p_sum[p] / (p_n[p] + k_p)) if p_n[p] >= min_prior else 0.0
        out.append((r, base, c_off, p_off))
        resid = r[f"a_{stat}"] - base
        club_sum[t] += resid
        club_n[t] += 1
        p_sum[p] += resid - c_off
        p_n[p] += 1
    return out


def score(rows, stat, fitted, label):
    a = [r[f"a_{stat}"] for r, *_ in fitted]
    print(f"\n  {label}")
    print(f"  {'prediction':<26}{'spread':>9}{'corr':>8}{'MAE':>8}"
          f"{'RMSE':>8}{'bias':>8}")
    variants = {
        "base (shipped)": lambda b, c, p: b,
        "+ club offset": lambda b, c, p: b + c,
        "+ pitcher offset": lambda b, c, p: b + p,
        "+ both": lambda b, c, p: b + c + p,
    }
    for name, fn in variants.items():
        m = [fn(b, c, p) for _, b, c, p in fitted]
        sm, sa = st.pstdev(m), st.pstdev(a)
        mm, ma = st.mean(m), st.mean(a)
        r = (sum((x - mm) * (y - ma) for x, y in zip(m, a))
             / (len(a) * sm * sa)) if sm and sa else 0.0
        mae = st.mean(abs(x - y) for x, y in zip(m, a))
        rmse = st.mean((x - y) ** 2 for x, y in zip(m, a)) ** 0.5
        print(f"  {name:<26}{sm:>9.2f}{r:>8.3f}{mae:>8.3f}"
              f"{rmse:>8.3f}{mm - ma:>+8.2f}")


def blowups(rows, stat="outs", min_prior=3):
    """Is the pitcher effect just the left tail?

    RESUME records, from day six, that per-pitcher leash variation is
    "mostly blowups, not real". That is a testable claim and this is the
    test: rebuild the offset from a TRIMMED mean of prior residuals, and
    from the prior MEDIAN. Both are nearly immune to a start where he was
    knocked out in the second. If the gain survives them it is a leash the
    manager sets, not a handful of disasters.
    """
    rows = sorted(rows, key=lambda r: (r["date"], r["game_id"]))
    vc = variance_components(rows, lambda r: r["player"], stat)
    k = (vc["within"] ** 2) / (vc["between"] ** 2)
    hist = defaultdict(list)
    ests = {"mean": [], "median": [], "trimmed": [], "long only": []}
    a, base = [], []
    for r in rows:
        h = hist[r["player"]]
        a.append(r[f"a_{stat}"])
        base.append(r[f"m_{stat}"])
        n = len(h)
        if n >= min_prior:
            s = sorted(h)
            cut = max(1, n // 5)
            mid = s[cut:n - cut] or s
            # 'long only' drops every prior start under 9 outs entirely, so
            # the disasters cannot contribute at all
            lo = [v for v, o in zip(h, hist[r["player"] + "|o"]) if o >= 9]
            ests["mean"].append(st.mean(h) * n / (n + k))
            ests["median"].append(st.median(h) * n / (n + k))
            ests["trimmed"].append(st.mean(mid) * n / (n + k))
            ests["long only"].append(
                st.mean(lo) * len(lo) / (len(lo) + k) if lo else 0.0)
        else:
            for v in ests.values():
                v.append(0.0)
        hist[r["player"]].append(r[f"a_{stat}"] - r[f"m_{stat}"])
        hist[r["player"] + "|o"].append(r[f"a_{stat}"])

    live = [i for i, v in enumerate(ests["mean"]) if v != 0.0]
    print(f"\n{'=' * 68}\n  IS IT JUST BLOWUPS? ({len(live)} live starts)"
          f"\n{'=' * 68}")
    print(f"  {'offset from prior':<22}{'spread':>9}{'corr':>8}{'MAE':>8}"
          f"{'RMSE':>8}")
    for name in ("__base__", "mean", "median", "trimmed", "long only"):
        m = [base[i] + (0.0 if name == "__base__" else ests[name][i])
             for i in live]
        aa = [a[i] for i in live]
        sm, sa = st.pstdev(m), st.pstdev(aa)
        mm, ma = st.mean(m), st.mean(aa)
        r = (sum((x - mm) * (y - ma) for x, y in zip(m, aa))
             / (len(aa) * sm * sa)) if sm and sa else 0.0
        mae = st.mean(abs(x - y) for x, y in zip(m, aa))
        rmse = st.mean((x - y) ** 2 for x, y in zip(m, aa)) ** 0.5
        label = "base (shipped)" if name == "__base__" else name
        print(f"  {label:<22}{sm:>9.2f}{r:>8.3f}{mae:>8.3f}{rmse:>8.3f}")


def main():
    min_prior = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    src = sys.argv[2] if len(sys.argv) > 2 else "scratchpad/ceiling_rows.json"
    print(f"  source: {src}")
    rows = load(src)
    for stat in ("outs", "k"):
        print(f"\n{'=' * 68}\n  {stat.upper()}\n{'=' * 68}")
        fitted = expanding(rows, stat, min_prior)
        used = [f for f in fitted if f[3] != 0.0]
        print(f"  {len(used)} of {len(fitted)} starts have >= {min_prior} "
              f"prior starts for the pitcher")
        score(rows, stat, fitted, "ALL STARTS (offset 0 where no history)")
        if used:
            score(rows, stat, used,
                  f"ONLY starts with >= {min_prior} prior "
                  f"(where the offset is live)")

    # Does the pitcher effect live in the regulars or in the marginal arms?
    # The chronological split-half in `between.py` restricted to pitchers
    # with 16+ starts and read +0.088; the leave-one-out over everyone read
    # +0.295. If those disagree it is because the population differs, and
    # that is a fact about WHERE the leash varies, not a contradiction.
    blowups(rows)
    print(f"\n{'=' * 68}\n  WHERE THE PITCHER EFFECT LIVES (outs)"
          f"\n{'=' * 68}")
    cnt = defaultdict(int)
    for r in rows:
        cnt[r["player"]] += 1
    resid = [r["a_outs"] - r["m_outs"] for r in rows]
    print(f"  {'season starts':<16}{'pitchers':>10}{'starts':>9}{'LOO r':>9}"
          f"{'z':>8}{'sd of means':>13}")
    for lo, hi in ((6, 11), (12, 17), (18, 24), (25, 99)):
        sub = [(r, v) for r, v in zip(rows, resid)
               if lo <= cnt[r["player"]] <= hi]
        if len(sub) < 100:
            continue
        tot, n = defaultdict(float), defaultdict(int)
        for r, v in sub:
            tot[r["player"]] += v
            n[r["player"]] += 1
        x = [(tot[r["player"]] - v) / (n[r["player"]] - 1)
             for r, v in sub if n[r["player"]] > 1]
        y = [v for r, v in sub if n[r["player"]] > 1]
        rr, z = _corr(x, y)
        means = [tot[q] / n[q] for q in tot]
        print(f"  {f'{lo}-{hi}':<16}{len(tot):>10}{len(sub):>9}{rr:>9.3f}"
              f"{z:>8.1f}{st.pstdev(means):>13.2f}")


if __name__ == "__main__":
    main()
