"""A deterministic estimator. No model, no personas, no API calls.

The point of this is to be the BASELINE. Any LLM added later has to beat a
few lines of arithmetic over the same evidence, and until that comparison
exists there is no way to tell whether a persona is contributing judgement
or just variance. It also runs free and instantly, so it can be backtested
against every graded bet in the database rather than argued about.

WHY DISTRIBUTIONS, NOT POINT ESTIMATES. Comparing a projected mean to the
line was measured at exactly 50% on 80 graded outs props — a coin flip —
and that is not a failure of the projection, it is a failure of the
question. The book sets the line near the true mean, so shaving 0.2 outs
off an estimate almost never changes which side of it you land on. What
does change is knowing the SPREAD: a starter going 15, 16, 16, 16, 17 and
one going 5, 25, 10, 22, 18 both average 16, and their chances of clearing
15.5 are nothing alike.

So this asks "in what share of his recent starts would this bet have won?"
and shrinks that toward a coin flip according to how little evidence there
is behind it.
"""
from __future__ import annotations

import math

#: Pseudo-counts pulling an empirical rate toward 0.5. With six starts,
#: 6-for-6 becomes 0.70 rather than 1.00 — which is the honest reading of
#: six observations, and stops a thin sample from producing a huge edge.
SHRINK_K = 4.0
#: Below this many starts, decline to estimate at all.
MIN_STARTS = 4
#: An edge under this is inside the noise of everything above and is not
#: worth acting on. Expressed in probability points.
MIN_EDGE = 0.04


def implied_prob(american: int | float | None) -> float | None:
    """Break-even win rate at an American price, vig included."""
    if american is None:
        return None
    a = float(american)
    return abs(a) / (abs(a) + 100) if a < 0 else 100 / (a + 100)


def fair_odds(p: float) -> int | None:
    """American odds for a probability, before any margin."""
    if not 0 < p < 1:
        return None
    return -round(100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def _shrink(hits: int, n: int) -> float:
    """Empirical rate pulled toward 0.5 by SHRINK_K pseudo-observations."""
    return (SHRINK_K * 0.5 + hits) / (SHRINK_K + n)


def over_under(
    values: list[float], line: float, side: str,
) -> dict | None:
    """P(this side wins) from an empirical sample of past results.

    Pushes — a result landing exactly on the line — are excluded from both
    numerator and denominator rather than counted as losses, because that
    is how the bet settles.
    """
    vals = [v for v in values if v is not None]
    live = [v for v in vals if v != line]
    n = len(live)
    if n < MIN_STARTS:
        return None
    want_over = (side or "").lower() != "under"
    hits = sum(1 for v in live if (v > line) == want_over)
    p = _shrink(hits, n)
    return {
        "p": round(p, 3),
        "raw_rate": round(hits / n, 3),
        "hits": hits,
        "n": n,
        "pushes": len(vals) - n,
        "fair_odds": fair_odds(p),
        # Standard error on the unshrunk rate — a 4-start sample carries an
        # error bar wide enough to swallow most edges, and saying so beside
        # the number is cheaper than someone discovering it later.
        "se": round(math.sqrt(max(p * (1 - p), 1e-9) / n), 3),
    }


def edge(p: float, american: int | float | None) -> dict | None:
    """Our probability against what the price needs to break even."""
    need = implied_prob(american)
    if need is None:
        return None
    e = p - need
    return {
        "price": american,
        "breakeven": round(need, 3),
        "edge": round(e, 3),
        "actionable": abs(e) >= MIN_EDGE and e > 0,
    }


# ── bootstrap: not a better error bar, a different selection rule ──────
#
# The point estimate above is the standard construction, which is precisely
# why it has no edge: the market price IS that construction, aggregated
# over everyone running it. Measured AUC 0.537 on 79 graded outs props,
# permutation p = 0.289. Nothing there, and nothing there was predictable.
#
# Resampling asks a question the consensus does not. Two bets both reading
# p = 0.60 are not the same bet — one may come from [15,16,16,16,17] and
# the other from [5,25,10,22,18], and only the first survives being
# resampled. Selecting for edges that hold up under resampling is a filter
# on WHICH bets to take rather than a better guess at the number, and it is
# unglamorous enough that most people skip it.
#
# JITTER goes further, and is the part actually worth testing. A plain
# bootstrap treats the observed starts as the whole truth and only
# resamples which ones you saw. Adding noise to each resampled value admits
# that a start's result was itself a draw — that a 16-out start could as
# easily have been 13 or 19. Pushing jitter up and watching where the edge
# dies gives a resilience score: an edge that survives two outs of noise is
# a different animal from one that evaporates at half an out.

#: Share of resampled worlds that must still show an edge for that noise
#: level to count as survived. Set at 0.80, not 0.60: shrinkage pulls every
#: p toward 0.5, so a lenient bar is cleared by samples with no structure at
#: all. At 0.60 a tight [15,16,16,16,17] and a scattered [5,25,10,22,18]
#: both "survived" to 3 outs of noise, which is exactly the distinction the
#: metric exists to make.
SURVIVE_AT = 0.80
N_BOOT = 4000
#: Noise levels to stress at, in outs. 0 is the plain bootstrap.
JITTER_LEVELS = (0.0, 1.0, 2.0, 3.0)


def bootstrap_p(
    values: list[float], line: float, side: str,
    n_boot: int = N_BOOT, jitter: float = 0.0, seed: int = 0,
) -> dict | None:
    """Distribution of P(win) under resampling, optionally with added noise.

    Deterministic for a given seed, because a bet's assessment should not
    change between two runs of the same question.
    """
    import random as _r

    vals = [v for v in values if v is not None]
    n = len(vals)
    if n < MIN_STARTS:
        return None
    want_over = (side or "").lower() != "under"
    rng = _r.Random(seed)
    ps = []
    for _ in range(n_boot):
        hits = live = 0
        for _ in range(n):
            v = vals[rng.randrange(n)]
            if jitter:
                v += rng.gauss(0.0, jitter)
            if v == line:
                continue
            live += 1
            hits += (v > line) == want_over
        if live:
            ps.append(_shrink(hits, live))
    if not ps:
        return None
    ps.sort()
    def q(f): return ps[min(len(ps) - 1, int(f * len(ps)))]
    return {
        "mean": round(sum(ps) / len(ps), 3),
        "p10": round(q(0.10), 3),
        "p50": round(q(0.50), 3),
        "p90": round(q(0.90), 3),
        "jitter": jitter,
        "_ps": ps,
    }


def resilience(
    values: list[float], line: float, side: str, american: int | float | None,
    seed: int = 0,
) -> dict | None:
    """How much noise the edge on this bet can absorb before it dies.

    For each jitter level, the share of resampled worlds in which the bet
    still beats its break-even price. `survives_to` is the largest noise
    level where that share stays above SURVIVE_AT — the headline number,
    and the one worth ranking bets on.
    """
    need = implied_prob(american)
    if need is None:
        return None
    out, survives = {}, None
    for j in JITTER_LEVELS:
        bs = bootstrap_p(values, line, side, jitter=j, seed=seed)
        if not bs:
            return None
        share = sum(1 for p in bs["_ps"] if p > need) / len(bs["_ps"])
        out[j] = {"p_mean": bs["mean"], "p10": bs["p10"], "p90": bs["p90"],
                  "share_with_edge": round(share, 3)}
        if share >= SURVIVE_AT:
            survives = j
    return {
        "breakeven": round(need, 3),
        "by_jitter": out,
        # None means the edge does not hold even with zero added noise.
        "survives_to": survives,
        "fragile": survives is None or survives < 1.0,
    }


# ── the one bet type with clean inputs and a graded history ────────────
def estimate_outs(side: dict, line: float, bet_side: str) -> dict | None:
    """P(win) for a pitcher-outs bet, from that starter's own recent starts.

    `side` is a snapshot side record. Uses the six-week window when it has
    enough starts and the fuller log otherwise — the same preference
    game_log_summary already encodes, reused rather than re-derived.
    """
    gl = ((side or {}).get("starter") or {}).get("starter_game_log") or {}
    starts = gl.get("starts") or []
    summary = gl.get("summary") or {}
    if not starts:
        return None

    recent_days = summary.get("recent_days")
    pool = starts
    basis = "all starts on record"
    if recent_days and summary.get("recent"):
        want = summary["recent"].get("starts") or 0
        if want >= MIN_STARTS:
            pool = starts[-want:]
            basis = f"last {want} starts ({recent_days}d)"

    dist = over_under([s.get("outs") for s in pool], line, bet_side)
    if not dist:
        return None
    return {
        "stat": "outs",
        "line": line,
        "side": bet_side,
        "basis": basis,
        "sample": [s.get("outs") for s in pool],
        **dist,
    }


def assess(bet: dict, side: dict) -> dict | None:
    """Estimate a bet and price it against the market. None if unsupported.

    Deliberately narrow. Only pitcher-outs is wired, because it is the one
    stat with a clean per-start history AND a graded backlog to test
    against. Adding a stat here should mean adding a backtest for it, not
    just a branch.
    """
    if (bet.get("stat") or "").lower() != "outs":
        return None
    if bet.get("line") is None:
        return None
    est = estimate_outs(side, float(bet["line"]), bet.get("side") or "over")
    if not est:
        return None
    ed = edge(est["p"], bet.get("american_odds"))
    return {**est, **(ed or {})}
