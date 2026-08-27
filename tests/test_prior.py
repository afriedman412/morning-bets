"""Checks for the multi-season prior — the shrink target `set_prior` builds.

Offline: every check hands `_blend_priors` its own seasons, so the DB is
never opened.

WHAT IS BEING GUARDED. `rates.USE_PRIOR_SEASON` aims a thin current line at
the pitcher's OWN past instead of at the league, and `PRIOR_DECAY` says how
fast a past season fades. The arithmetic has two failure modes that no
downstream number would flag: the decay can be applied against the calendar
instead of against the pitcher's own most recent season, which silently
DELETES every pitcher who missed a year, and the effective sample can be
left at a full season's worth, which lets a stale prior shout down the
current evidence it is supposed to be supporting.
"""
from __future__ import annotations

from src.context.sources import rates


def _season(name, k_pct=0.25, pa=500.0, **over):
    r = {"name": name, "pa": pa, "k_pct": k_pct, "bb_pct": 0.08,
         "hr_pct": 0.03, "babip": 0.29}
    r.update(over)
    return {name: r}


def check_one_season_passes_through_untouched():
    """`seasons=1` has to be the behaviour that was measured on day ten.

    The single-season prior is the arm that produced the K correlation gain,
    so the blend must not perturb it when there is nothing to blend.
    """
    only = _season("A", k_pct=0.31)
    out = rates._blend_priors([(1, only)])
    assert out is only or out["A"]["k_pct"] == 0.31, out


def check_an_older_season_is_discounted_against_a_newer_one():
    """The whole purpose of the decay: 500 batters faced last year must
    outweigh 500 from the year before."""
    parts = [(1, _season("A", k_pct=0.30, pa=500.0)),
             (2, _season("A", k_pct=0.20, pa=500.0))]
    got = rates._blend_priors(parts)["A"]["k_pct"]
    w = rates.PRIOR_DECAY["k_pct"]
    assert abs(got - (0.30 + w * 0.20) / (1 + w)) < 1e-9, got
    # and it must land on the recent side of a flat average
    assert got > 0.25, got


def check_batters_faced_weight_the_blend_alongside_the_decay():
    """A 20-batter cameo last year must not outweigh a full season before
    it. Decay alone would let it."""
    parts = [(1, _season("A", k_pct=0.10, pa=20.0)),
             (2, _season("A", k_pct=0.30, pa=600.0))]
    got = rates._blend_priors(parts)["A"]["k_pct"]
    assert got > 0.25, got


def check_a_pitcher_who_missed_last_season_keeps_a_prior():
    """THE REGRESSION THAT CAUSED THIS FILE.

    Lag counted against the CALENDAR rather than against the pitcher's own
    most recent season drops him entirely wherever a decay is 0.0 — BABIP's
    is — because every weight for that stat comes out zero. He is 7.6% of
    pitcher-seasons and he is the population the prior was built to reach.
    """
    parts = [(2, _season("A", k_pct=0.28)), (3, _season("A", k_pct=0.28))]
    out = rates._blend_priors(parts)
    assert "A" in out, out
    assert out["A"]["babip"] == 0.29, out["A"]


def check_his_freshest_season_carries_full_weight_however_old_it_is():
    """A man back from an elbow is represented by his last real season, not
    by a fraction of it. Two years old at full weight, one year behind that
    discounted — the same shape everybody else gets."""
    parts = [(2, _season("A", k_pct=0.30, pa=500.0)),
             (3, _season("A", k_pct=0.20, pa=500.0))]
    got = rates._blend_priors(parts)["A"]["k_pct"]
    w = rates.PRIOR_DECAY["k_pct"]
    assert abs(got - (0.30 + w * 0.20) / (1 + w)) < 1e-9, got


def check_the_effective_sample_is_discounted_not_summed():
    """`pa` feeds the second shrink stage, which is what stops a thin prior
    speaking louder than the current evidence behind it. Summing raw batters
    faced across three seasons would treat a stale prior as three times the
    evidence it is."""
    parts = [(1, _season("A", pa=500.0)), (2, _season("A", pa=500.0)),
             (3, _season("A", pa=500.0))]
    pa = rates._blend_priors(parts)["A"]["pa"]
    w = rates.PRIOR_DECAY["k_pct"]
    assert abs(pa - 500.0 * (1 + w + w * w)) < 1e-6, pa
    assert pa < 1500.0, pa


def check_babip_does_not_pool_across_seasons():
    """Measured at 0.0: a pitcher's BABIP barely persists one year and is
    indistinguishable from noise at two. Blending it in anyway would import
    the noise as if it were evidence."""
    assert rates.PRIOR_DECAY["babip"] == 0.0, rates.PRIOR_DECAY
    parts = [(1, _season("A", babip=0.310)), (2, _season("A", babip=0.250))]
    got = rates._blend_priors(parts)["A"]["babip"]
    assert abs(got - 0.310) < 1e-9, got


def check_every_decay_stays_inside_the_measured_range():
    """A weight above 1 would make an older season count for MORE than a
    newer one, which no reading of the measurement supports. Below zero
    alternates the sign of the blend."""
    for stat, w in rates.PRIOR_DECAY.items():
        assert 0.0 <= w <= 1.0, (stat, w)


def check_a_pitcher_missing_from_a_season_is_not_counted_as_a_zero():
    """Absence is absence. Reading a missing season as a 0.0 rate would drag
    every pitcher who changed leagues, got hurt or came up midway toward
    zero — silently, and hardest for the thin lines the prior exists for."""
    parts = [(1, _season("A", k_pct=0.30)), (2, _season("B", k_pct=0.10))]
    out = rates._blend_priors(parts)
    assert abs(out["A"]["k_pct"] - 0.30) < 1e-9, out["A"]
    assert abs(out["B"]["k_pct"] - 0.10) < 1e-9, out["B"]


def check_the_prior_is_cleared_before_it_is_rebuilt():
    """`pitcher_rates` reads `prior or _PRIOR`, so handing it an empty prior
    is NOT enough to stop `set_prior` recursing into its own output — a
    second call would build a prior out of the previous prior and compound
    three seasons into nine. `set_prior` clears the module global first.

    Asserted on what `pitcher_rates` actually SEES rather than on the order
    of two lines of source. The source-order version of this check passed
    with the clearing moved back inside the `season is None` branch, which
    is the bug it exists to catch.
    """
    from src.context import sim
    seen = []
    real_rates, real_league = rates.pitcher_rates, sim.league

    def fake_rates(lg, season=None, **kw):
        seen.append(dict(rates._PRIOR))
        return _season(f"P{season}")

    try:
        sim.league = lambda *a, **k: {"k_pct": 0.22, "bb_pct": 0.08,
                                      "hr_pct": 0.03, "babip": 0.29}
        rates.pitcher_rates = fake_rates
        rates._PRIOR = _season("STALE")
        rates.set_prior(2025, seasons=2)
    finally:
        rates.pitcher_rates, sim.league = real_rates, real_league
        rates._PRIOR = {}
    assert len(seen) == 2, seen
    assert all(not s for s in seen), seen


def check_the_postseason_filter_stays_off():
    """MEASURED DEAD on 2026-08-26, and pinned so the reasoning survives.

    The hypothesis was sound and the raw numbers support it: a playoff
    pitcher faces playoff lineups, so excluding October moves his K% by up
    to 5.3 points and always the same way. The current season has no
    postseason, so that bias enters the PRIOR and never the line it is
    shrunk against — a genuine asymmetry.

    It still makes prediction WORSE, six for six. Correlation of a prior
    season's rate with the next season's, pitchers with 150+ batters faced
    in both:

        lag  stat      n    with post   without     delta
        1    k_pct   275       0.7536    0.7491    -0.0045
        1    bb_pct  275       0.7048    0.6960    -0.0088
        1    babip   275       0.4805    0.4761    -0.0044
        2    k_pct   209       0.6494    0.6490    -0.0004
        2    bb_pct  209       0.6108    0.6066    -0.0042
        2    babip   209       0.1784    0.1603    -0.0181

    Removing a real bias costs more than it saves when the bias is small and
    the sample it lives in is 10% of the record. Playoff innings are still
    innings against major-league hitters.
    """
    assert rates.EXCLUDE_POSTSEASON is False


def check_the_postseason_ranges_cover_the_wild_card_round():
    """The dates are TRANSCRIBED because the obvious rule was wrong at both
    edges, and those edges are the whole content of the filter.

    2025's Wild Card opened on SEPTEMBER 30, so anything keyed on the month
    misses four postseason days. 2024-09-30 carries two REGULAR-season
    makeup games that decided a playoff place, so anything keyed on a low
    game count throws them away. 2023-10-01 is a fifteen-game regular-season
    slate sitting in October.
    """
    r = rates.POSTSEASON_RANGE
    assert r[2025][0] == "2025-09-30", "the Wild Card round starts in September"
    assert r[2024][0] == "2024-10-01", r[2024]
    assert r[2023][0] == "2023-10-03", r[2023]
    for yr, (a, b) in r.items():
        assert a < b and a.startswith(str(yr)) and b[:4] in (str(yr),), (yr, a, b)
    # 2026 must NOT be present: the season is in progress and has none.
    assert 2026 not in r, r
    clause = rates.postseason_clause("g")
    assert "2025-09-30" in clause and "not (" in clause, clause
