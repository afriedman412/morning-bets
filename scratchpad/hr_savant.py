"""Savant's park-adjusted home runs — TODO item 28, the measuring stage.

    venv/bin/python -m scratchpad.hr_savant --fetch    # cache 2023-2026
    venv/bin/python -m scratchpad.hr_savant --match    # name coverage
    venv/bin/python -m scratchpad.hr_savant --predict  # the pre-registered test

WHAT THE NUMBER IS. Savant overlays each home run's observed TRAJECTORY on
all 30 parks' real fence geometry and reports how many would have left each
one. `xhr` is the mean of those thirty (verified: Springs 25.4 against a
computed 25.3, Nola 26.3/26.3). DETERMINISTIC GEOMETRY, not an
expected-value model — it is not a barrel or an xwOBA.

THE PRE-REGISTERED TEST, written into TODO item 28 BEFORE any of this ran.
`NEUTRALISE_PARK` already removes park BIAS from a player's rate using
HR-specific, handedness-split factors, so bias is not what is on offer
here. The only thing left to win is NOISE: a pitcher's HR/BIP shrinks with
k = 944 because the outcome barely repeats (r_full 0.416, item 24), and the
engine therefore discards most of his personal home run signal. If `xhr`
measures the same quantity with the park randomness taken out, it should
repeat harder. IF IT DOES NOT, THE ITEM CLOSES.

WHY YEAR-OVER-YEAR AND NOT ODD/EVEN. `--stabilise` splits a player's games
in half, and `xhr` is published as ONE NUMBER PER PLAYER-SEASON — there are
no halves to take. So the reliability question is asked in the form that a
season aggregate can actually answer, and it happens to be the form the
engine cares about anyway: predicting the NEXT season's real home run rate.
Out of sample by construction, and no holdout arithmetic is needed because
the target season is a different season.
"""
from __future__ import annotations

import json
import re
import statistics as st
import sys
import unicodedata
import urllib.request
from pathlib import Path

from src.context import store
from src.context.sources import battedball

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = PROJECT_ROOT / ".cache" / "savant_hr"
UA = "Mozilla/5.0 (compatible; morning-bets/1.0)"
TIMEOUT = 60

#: CAPITAL P, AND THIS IS NOT A STYLE POINT: `type=pitcher` and
#: `player_type=pitcher` both return BATTER rows silently. An hour was
#: nearly spent reading a batter table as a pitcher one.
_URL = ("https://baseballsavant.mlb.com/leaderboard/home-runs"
        "?player_type={side}&year={year}")
SIDES = {"bat": "Batter", "pit": "Pitcher"}
YEARS = (2023, 2024, 2025, 2026)

#: The thirty park columns, so `xhr` can be checked against their mean
#: rather than trusted.
PARKS = ("ari", "atl", "bal", "bos", "chc", "cin", "cle", "col", "cws",
         "det", "hou", "kc", "laa", "lad", "mia", "mil", "min", "nym",
         "nyy", "oak", "phi", "pit", "sd", "sea", "sf", "stl", "tb",
         "tex", "tor", "wsh")


def _path(side: str, year: int) -> Path:
    return CACHE_DIR / f"{side}_{year}.json"


def fetch(side: str, year: int, force: bool = False) -> list[dict]:
    """One (side, season) leaderboard, cached forever.

    A COMPLETED season's rows never change, so there is no TTL — and that
    is the whole reason this source escapes the "Savant is season-to-date
    and cannot be asked what it said in June" problem the park index has.
    The CURRENT season is the exception and the caller must respect it;
    see `--predict`, which only ever uses a completed season as an input.
    """
    p = _path(side, year)
    if p.exists() and not force:
        return json.loads(p.read_text())
    url = _URL.format(side=SIDES[side], year=year)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        html = r.read().decode("utf-8", "replace")
    m = re.search(r"var data = (\[.*?\]);", html, re.S)
    if not m:
        raise RuntimeError(f"no `var data` in {url} — the page changed")
    rows = json.loads(m.group(1))
    bad = [r for r in rows if r.get("player_type") != SIDES[side]]
    if bad:
        raise RuntimeError(
            f"{url} returned {len(bad)}/{len(rows)} rows of the wrong "
            f"player_type — the capital-P trap, see _URL")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows))
    return rows


def _norm(name: str) -> str:
    """'Judge, Aaron' -> a key that matches pbp's 'Aaron Judge'.

    Accents are folded on BOTH sides rather than trusted to agree —
    `mlb_traj` carries 'Luis García Jr.' from the play-by-play feed and
    the leaderboard is not guaranteed to encode it the same way.
    """
    if "," in name:
        last, first = name.split(",", 1)
        name = f"{first.strip()} {last.strip()}"
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    return re.sub(r"[^a-z ]", "", name.lower()).strip()


def savant_map(side: str, year: int) -> dict:
    """{normalised name: row} for one side and season."""
    return {_norm(r["player"]): r for r in fetch(side, year)}


def traj_counts(role: str, year: int) -> dict:
    """{normalised name: (hr, bip)} for one season, from `mlb_traj`."""
    out = {}
    with store.connect(attach=False) as c:
        c.execute(battedball._TRAJ_SCHEMA)
        for r in c.execute(
                "select name, sum(hr) hr, sum(bip) bip from mlb_traj "
                "where role = ? and date like ? group by name",
                (role, f"{year}%")):
            out[_norm(r["name"])] = (r["hr"] or 0, r["bip"] or 0)
    return out


def match(min_bip: int = 200) -> None:
    """Coverage, and the `xhr`-is-the-park-mean claim, both checked.

    RULE 10'S HABIT: print the actual names and numbers before believing
    any table built on them. Two independent sources joined on a
    reformatted string is exactly where a silent 10% miss lives.
    """
    for role, side in (("bat", "bat"), ("pit", "pit")):
        print(f"\n  {SIDES[side].upper()}S")
        for year in YEARS:
            sv, tj = savant_map(side, year), traj_counts(role, year)
            big = {n: v for n, v in tj.items() if v[1] >= min_bip}
            hit = [n for n in big if n in sv]
            miss = sorted(set(big) - set(sv))
            # The leaderboard lists players WITH home runs, so a genuine
            # zero is a legitimate absence and not a match failure.
            miss_hr = [n for n in miss if big[n][0] > 0]
            print(f"    {year}: {len(sv):>4} savant rows, "
                  f"{len(big):>4} players >= {min_bip} bip, "
                  f"matched {len(hit):>4} ({len(hit) / max(len(big), 1):.1%}), "
                  f"unmatched-with-a-home-run {len(miss_hr)}")
            for n in miss_hr[:4]:
                print(f"        MISS {n!r} hr={big[n][0]}")
    # `xhr` against the thirty park columns.
    rows = fetch("pit", 2026)[:200]
    d = [abs(float(r["xhr"]) - st.mean(float(r[p]) for p in PARKS))
         for r in rows]
    print(f"\n  xhr against the mean of the 30 park columns, 200 arms: "
          f"max |diff| {max(d):.3f}, mean {st.mean(d):.3f}")


def predict(min_bip: int = 250) -> None:
    """THE PRE-REGISTERED TEST. Which season-Y number predicts season
    Y+1's real home run rate better — the actual rate, or `xhr`?

    Both estimators are put on the SAME denominator (balls in play from
    `mlb_traj`) and scored on the SAME players, so the comparison is
    PAIRED and does not have to clear the between-player spread. The
    target is next season's real HR/BIP; a season pair contributes a
    player only if he clears the threshold in BOTH seasons.
    """
    print(f"\n  YEAR-OVER-YEAR, players with >= {min_bip} balls in play "
          "in both seasons\n")
    print(f"    {'role':<5}{'pair':<12}{'n':>5}{'r actual':>10}"
          f"{'r xhr':>9}{'better':>9}{'rmse act':>10}{'rmse xhr':>10}")
    tot = {"bat": [0, 0], "pit": [0, 0]}
    for role in ("bat", "pit"):
        for y0, y1 in zip(YEARS, YEARS[1:]):
            sv = savant_map(role, y0)
            t0, t1 = traj_counts(role, y0), traj_counts(role, y1)
            a, x, tgt = [], [], []
            for n, (hr0, bip0) in t0.items():
                if bip0 < min_bip or n not in sv or n not in t1:
                    continue
                hr1, bip1 = t1[n]
                if bip1 < min_bip:
                    continue
                a.append(hr0 / bip0)
                x.append(float(sv[n]["xhr"]) / bip0)
                tgt.append(hr1 / bip1)
            if len(a) < 30:
                print(f"    {role:<5}{y0}->{y1:<7}{len(a):>5}   too few")
                continue
            ra, rx = st.correlation(a, tgt), st.correlation(x, tgt)
            # RMSE of a plain rescale of each predictor onto the target,
            # so neither is penalised for sitting on a different level —
            # the question is ORDERING and spread, not calibration.
            def _rmse(p):
                b = st.correlation(p, tgt) * st.stdev(tgt) / st.stdev(p)
                c = st.mean(tgt) - b * st.mean(p)
                return (sum((b * v + c - t) ** 2
                            for v, t in zip(p, tgt)) / len(p)) ** 0.5
            tot[role][0] += ra
            tot[role][1] += rx
            print(f"    {role:<5}{y0}->{y1:<7}{len(a):>5}{ra:>10.3f}"
                  f"{rx:>9.3f}{'xhr' if rx > ra else 'actual':>9}"
                  f"{_rmse(a):>10.5f}{_rmse(x):>10.5f}")
    for role in ("bat", "pit"):
        n = len(YEARS) - 1
        print(f"    {role} mean r: actual {tot[role][0] / n:.3f}   "
              f"xhr {tot[role][1] / n:.3f}")


def adversarial(role: str = "pit") -> None:
    """TWO CHECKS BEFORE THE NULL IS ACCEPTED (rule 7).

    ONE — THE POPULATION IT FIRES IN (rule 9). The claim is that `xhr`
    DE-NOISES, and noise matters most in a THIN sample. Requiring 250
    balls in play in both seasons selects for exactly the established
    players whose actual rate is already stable, which is where the
    mechanism has least to offer. If the effect is real its advantage
    must GROW as the threshold falls.

    TWO — INDEPENDENT INFORMATION. `xhr` losing head to head does not
    mean it carries nothing: a weaker predictor can still hold signal the
    stronger one lacks. A half-and-half blend beating BOTH would say so,
    and would be a different (and still shippable) finding.
    """
    print(f"\n  ADVERSARIAL, role={role}\n")
    print(f"    {'min bip':<9}{'pair':<12}{'n':>5}{'r actual':>10}"
          f"{'r xhr':>9}{'r blend':>10}{'xhr - act':>11}")
    for thr in (75, 125, 200, 350):
        agg = [0.0, 0.0, 0.0, 0]
        for y0, y1 in zip(YEARS, YEARS[1:]):
            sv = savant_map(role, y0)
            t0, t1 = traj_counts(role, y0), traj_counts(role, y1)
            a, x, tgt = [], [], []
            for n, (hr0, bip0) in t0.items():
                if bip0 < thr or n not in sv or n not in t1:
                    continue
                hr1, bip1 = t1[n]
                if bip1 < thr:
                    continue
                a.append(hr0 / bip0)
                x.append(float(sv[n]["xhr"]) / bip0)
                tgt.append(hr1 / bip1)
            if len(a) < 30:
                continue
            bl = [(u + v) / 2 for u, v in zip(a, x)]
            ra, rx, rb = (st.correlation(a, tgt), st.correlation(x, tgt),
                          st.correlation(bl, tgt))
            agg[0] += ra
            agg[1] += rx
            agg[2] += rb
            agg[3] += 1
            print(f"    {thr:<9}{y0}->{y1:<7}{len(a):>5}{ra:>10.3f}"
                  f"{rx:>9.3f}{rb:>10.3f}{rx - ra:>+11.3f}")
        if agg[3]:
            print(f"    {thr:<9}{'MEAN':<12}{'':>5}{agg[0] / agg[3]:>10.3f}"
                  f"{agg[1] / agg[3]:>9.3f}{agg[2] / agg[3]:>10.3f}"
                  f"{(agg[1] - agg[0]) / agg[3]:>+11.3f}\n")


#: Every predictor the leaderboard can supply, plus the two the engine
#: already has. All on the SAME denominator — season balls in play — so a
#: coefficient is comparable across them and none of them is secretly a
#: playing-time proxy.
#:
#: WHAT THE TIER COLUMNS ARE, and they are the reason this stage exists:
#: `xhr` collapses thirty park counterfactuals into one mean and throws
#: away their SHAPE. A no-doubter leaves all thirty parks; a wall-scraper
#: leaves one. Ten of each are the same `hr_total` and the same `xhr`,
#: and they are not the same contact allowed. `non_hr_would_have_left`
#: is the other half of it — balls that were NOT home runs here and
#: would have left elsewhere, which the home run total cannot see at all.
#: A NULL COLUMN IS A ZERO, NOT A MISSING PLAYER. Savant leaves
#: `non_hr_would_have_left` null rather than 0 for a player who had none,
#: and dropping those rows would silently select for players who DID have
#: one — the sample would then answer a different question than the one
#: asked. `_f` is the only place that decision is made.
def _f(v):
    return 0.0 if v in (None, "", "null") else float(v)


FEATURES = {
    "actual":  lambda r, c: c["hr"] / c["bip"],
    "xhr":     lambda r, c: _f(r["xhr"]) / c["bip"],
    "nodoubt": lambda r, c: _f(r["no_doubters"]) / c["bip"],
    "mostly":  lambda r, c: _f(r["mostly_gone"]) / c["bip"],
    "doubt":   lambda r, c: _f(r["doubters"]) / c["bip"],
    "wouldve": lambda r, c: _f(r["non_hr_would_have_left"]) / c["bip"],
    "air":     lambda r, c: c["air"] / c["bip"],
}

SETS = {
    "actual (baseline)":        ("actual",),
    "xhr alone":                ("xhr",),
    "actual + xhr":             ("actual", "xhr"),
    "actual + air (shipped)":   ("actual", "air"),
    "actual + air + xhr":       ("actual", "air", "xhr"),
    "actual + wouldve":         ("actual", "wouldve"),
    "actual + tiers":           ("actual", "nodoubt", "mostly", "doubt"),
    "actual + air + tiers":     ("actual", "air", "nodoubt", "mostly",
                                 "doubt"),
    "everything":               ("actual", "air", "xhr", "nodoubt",
                                 "mostly", "doubt", "wouldve"),
}


def _season(role: str, year: int) -> dict:
    """{name: {hr, bip, air}} for one season, straight off `mlb_traj`."""
    out = {}
    with store.connect(attach=False) as c:
        c.execute(battedball._TRAJ_SCHEMA)
        for r in c.execute(
                "select name, sum(hr) hr, sum(bip) bip, "
                "sum(fb) + sum(ld) air from mlb_traj "
                "where role = ? and date like ? group by name",
                (role, f"{year}%")):
            out[_norm(r["name"])] = {"hr": r["hr"] or 0, "bip": r["bip"] or 0,
                                     "air": r["air"] or 0}
    return out


def _rows(role: str, y0: int, y1: int, thr: int):
    sv = savant_map(role, y0)
    c0, c1 = _season(role, y0), _season(role, y1)
    out = []
    for n, c in c0.items():
        if c["bip"] < thr or n not in sv or n not in c1:
            continue
        if c1[n]["bip"] < thr:
            continue
        r = sv[n]
        out.append(([FEATURES[f](r, c) for f in FEATURES],
                    c1[n]["hr"] / c1[n]["bip"]))
    return out


def kitchen_sink(thr: int = 150) -> None:
    """EVERY COLUMN THE LEADERBOARD HAS, scored out of sample.

    LEAVE-ONE-SEASON-PAIR-OUT, which is what keeps this from being the
    overfit it would otherwise obviously be: with seven candidate
    predictors and ~250 players, an in-sample R2 would rise for any set
    at all and mean nothing. Each model is FITTED on two season pairs and
    SCORED on the third it never saw, and the reported number is the mean
    over the three held-out pairs.

    The baseline is `actual` alone, and the row that decides whether any
    of this reaches the engine is `actual + air (shipped)` — that is what
    the model ALREADY knows after item 24, so a Savant column has to beat
    THAT, not the bare rate.
    """
    import numpy as np
    names = list(FEATURES)
    pairs = list(zip(YEARS, YEARS[1:]))
    for role in ("pit", "bat"):
        data = {p_: _rows(role, *p_, thr) for p_ in pairs}
        n_tot = sum(len(v) for v in data.values())
        print(f"\n  {role.upper()}  leave-one-pair-out, >= {thr} bip both "
              f"seasons, {n_tot:,} player-seasons over {len(pairs)} pairs")
        print(f"    {'predictor set':<26}{'oos r':>9}{'oos rmse':>11}"
              f"{'vs baseline':>13}")
        base = None
        for label, feats in SETS.items():
            idx = [names.index(f) for f in feats]
            rs, ses, ns = [], 0.0, 0
            for held in pairs:
                tr = [r for p_ in pairs if p_ != held for r in data[p_]]
                te = data[held]
                if len(tr) < 40 or len(te) < 20:
                    continue
                X = np.array([[1.0] + [x[i] for i in idx] for x, _ in tr])
                y = np.array([t for _, t in tr])
                beta, *_ = np.linalg.lstsq(X, y, rcond=None)
                Xt = np.array([[1.0] + [x[i] for i in idx] for x, _ in te])
                yt = np.array([t for _, t in te])
                pred = Xt @ beta
                if pred.std() > 0:
                    rs.append(float(np.corrcoef(pred, yt)[0, 1]))
                ses += float(((pred - yt) ** 2).sum())
                ns += len(yt)
            if not rs:
                continue
            r_, rmse = st.mean(rs), (ses / ns) ** 0.5
            if base is None:
                base = (r_, rmse)
                mark = "  (baseline)"
            else:
                mark = f"{r_ - base[0]:+.4f} r"
            print(f"    {label:<26}{r_:>9.4f}{rmse:>11.5f}{mark:>13}")


def paired(thr: int = 150) -> None:
    """PAIRED, per held-out player — the se the summary table cannot give.

    Two models scored on the SAME player-seasons have most of their error
    in common, so the se of the DIFFERENCE is far smaller than the se of
    either correlation. Comparing two 0.66s by eye against the se of a
    correlation is how a real 1-se effect gets called noise and a noise
    one gets called real.

    AND THE SELECTION IS STATED RATHER THAN HIDDEN: nine predictor sets
    were tried, so the best one is optimistic by construction even under
    leave-one-pair-out. A margin near its own se is a LEAD, not a
    finding.
    """
    import numpy as np
    names = list(FEATURES)
    pairs = list(zip(YEARS, YEARS[1:]))
    tests = {"pit": [("actual (baseline)", "actual + air (shipped)"),
                     ("actual + air (shipped)", "actual + air + xhr")],
             "bat": [("actual (baseline)", "actual + tiers"),
                     ("actual (baseline)", "xhr alone"),
                     ("actual + tiers", "actual + air + tiers")]}
    for role in ("pit", "bat"):
        data = {p_: _rows(role, *p_, thr) for p_ in pairs}
        print(f"\n  {role.upper()}  paired squared-error difference per "
              f"held-out player-season")
        for lo, hi in tests[role]:
            d_all = []
            for held in pairs:
                tr = [r for p_ in pairs if p_ != held for r in data[p_]]
                te = data[held]
                preds = {}
                for lab in (lo, hi):
                    idx = [names.index(f) for f in SETS[lab]]
                    X = np.array([[1.0] + [x[i] for i in idx]
                                  for x, _ in tr])
                    y = np.array([t for _, t in tr])
                    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
                    Xt = np.array([[1.0] + [x[i] for i in idx]
                                   for x, _ in te])
                    preds[lab] = Xt @ beta
                yt = np.array([t for _, t in te])
                d_all += list((preds[lo] - yt) ** 2 - (preds[hi] - yt) ** 2)
            d = np.array(d_all)
            se = d.std(ddof=1) / len(d) ** 0.5
            z = d.mean() / se if se else 0.0
            print(f"    {hi} over {lo}")
            print(f"      n {len(d):,}   mean sq-error reduction "
                  f"{d.mean():+.3e}   se {se:.3e}   z {z:+.2f}")


def main(argv):
    if "--fetch" in argv:
        for side in SIDES:
            for year in YEARS:
                rows = fetch(side, year, force="--force" in argv)
                print(f"  {side} {year}: {len(rows):,} rows")
    if "--match" in argv:
        match()
    if "--predict" in argv:
        predict()
    if "--paired" in argv:
        paired()
    if "--sink" in argv:
        kitchen_sink()
    if "--adversarial" in argv:
        for role in ("pit", "bat"):
            adversarial(role)


if __name__ == "__main__":
    main(sys.argv[1:])
