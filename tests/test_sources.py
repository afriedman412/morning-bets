"""Checks for the source adapters that had no coverage.

`mixture` matters most: the pre-registered arsenal test depends on it, and a
mixture that silently degrades to the aggregate model would produce a clean
null that means nothing. The rest guard bugs that already shipped once.
"""
from __future__ import annotations

from src.context import sim
from src.context.sources import archetype, mixture, season


# ── name matching ──────────────────────────────────────────────────────
def check_flip_name_converts_savant_to_boxscore_order():
    """Savant writes "Abel, Mick"; the boxscore cache writes "Mick Abel".

    This shipped broken: every pooled archetype rate came out 0.0 because
    nothing joined, and the table still rendered. A silent join failure that
    reads as a modelling result is the worst kind.
    """
    assert archetype.flip_name("Abel, Mick") == "Mick Abel"
    assert archetype.flip_name("Ashcraft, Braxton") == "Braxton Ashcraft"
    assert archetype.flip_name("Mick Abel") == "Mick Abel"    # idempotent
    assert archetype.flip_name("  Cease, Dylan ") == "Dylan Cease"


# ── the arsenal mixture ────────────────────────────────────────────────
def _ars(**usage):
    """A pitcher arsenal: {pitch_type: row} with usage in percent."""
    return {pt: {"pitch_usage": str(u), "k_percent": str(k), "pa": "300"}
            for pt, (u, k) in usage.items()}


def _lg(**k):
    return {pt: {"k_pct": v, "woba": 0.31, "pitches": 10000}
            for pt, v in k.items()}


def check_mixture_degrades_to_the_aggregate_model():
    """A batter with no per-pitch tendencies must return the pitcher's own
    aggregate rate, whatever his mix.

    THE PROPERTY THAT MAKES THIS SAFE TO SWITCH ON. If it did not hold, the
    mixture would move every matchup by some constant and the arsenal test
    would be measuring a level shift rather than a matchup effect.
    """
    data = {"pitchers": {"P": _ars(FF=(60, 20.0), SL=(40, 30.0))},
            "batters": {}}
    lgp = _lg(FF=0.20, SL=0.30)
    got = mixture.matchup_k("B", "P", data, lgp, b_overall=0.22,
                            p_overall=0.24, lg_overall=0.22, log5=sim.log5)
    assert got is not None
    assert abs(got - 0.24) < 1e-6, got


def check_mixture_respects_usage_weighting():
    """Throwing the strikeout pitch more often must raise the matchup rate.

    The whole reason a mixture beats a scalar multiplier: 45% sliders to a
    hitter who cannot touch sliders is not the same matchup as 15%, and a
    single multiplier cannot tell them apart once it is formed.
    """
    lgp = _lg(FF=0.20, SL=0.30)
    bat = {"B": {"SL": {"k_percent": "45.0", "pa": "300"},
                 "FF": {"k_percent": "18.0", "pa": "300"}}}
    out = {}
    for label, sl in (("slider-heavy", 70), ("fastball-heavy", 20)):
        data = {"pitchers": {"P": _ars(FF=(100 - sl, 20.0), SL=(sl, 30.0))},
                "batters": bat}
        out[label] = mixture.matchup_k(
            "B", "P", data, lgp, b_overall=0.22, p_overall=0.24,
            lg_overall=0.22, log5=sim.log5)
    assert out["slider-heavy"] > out["fastball-heavy"], out


def check_mixture_declines_on_thin_coverage():
    """Returns None rather than a guess when the arsenal is incomplete.

    The same rule the rest of the codebase follows: a guessed value that
    moves the estimate in a definite wrong direction is worse than no value,
    because the missing families would silently renormalise onto whatever
    is left.
    """
    data = {"pitchers": {"P": _ars(FF=(30, 20.0))},   # 30% of the arsenal
            "batters": {}}
    got = mixture.matchup_k("B", "P", data, _lg(FF=0.20), b_overall=0.22,
                            p_overall=0.24, lg_overall=0.22, log5=sim.log5)
    assert got is None, got


def check_mixture_shrinks_a_thin_cell_toward_the_batter_himself():
    """A batter's rate against one pitch is a few dozen plate appearances.

    Shrinking toward HIS OWN overall rate rather than the league's means an
    empty cell falls back to what we already believe about him, not to a
    stranger. A one-PA slider line must barely move the answer.
    """
    lgp = _lg(FF=0.20, SL=0.30)
    data = {"pitchers": {"P": _ars(FF=(50, 20.0), SL=(50, 30.0))},
            "batters": {"B": {"SL": {"k_percent": "90.0", "pa": "1"}}}}
    thin = mixture.matchup_k("B", "P", data, lgp, b_overall=0.22,
                             p_overall=0.24, lg_overall=0.22, log5=sim.log5)
    data["batters"]["B"]["SL"]["pa"] = "900"
    thick = mixture.matchup_k("B", "P", data, lgp, b_overall=0.22,
                              p_overall=0.24, lg_overall=0.22, log5=sim.log5)
    assert abs(thin - 0.24) < abs(thick - 0.24), (thin, thick)
    assert thick > thin, (thin, thick)


def check_mixture_returns_a_probability():
    """No input combination may escape [0, 1] — it feeds `pa_outcome`
    directly and a rate above one would silently strike out every batter."""
    lgp = _lg(FF=0.20, SL=0.30)
    for kb in ("1.0", "99.0", "0.1"):
        data = {"pitchers": {"P": _ars(FF=(50, 99.0), SL=(50, 1.0))},
                "batters": {"B": {"FF": {"k_percent": kb, "pa": "400"},
                                  "SL": {"k_percent": kb, "pa": "400"}}}}
        got = mixture.matchup_k("B", "P", data, lgp, b_overall=0.22,
                                p_overall=0.24, lg_overall=0.22,
                                log5=sim.log5)
        if got is not None:
            assert 0.0 < got <= 0.95, (kb, got)


# ── season backfill ────────────────────────────────────────────────────
def check_missing_dates_skips_what_is_already_cached():
    """A date with any cached game counts as done. Re-pulling every date on
    every run would be a thousand needless requests to somebody's free API."""
    import datetime as dt
    have = {"2026-04-02", "2026-04-04"}

    class _C:
        def execute(self, *_):
            return [{"date": d} for d in have]
    got = season.missing_dates(start=dt.date(2026, 4, 1),
                               end=dt.date(2026, 4, 5), conn=_C())
    assert got == ["2026-04-01", "2026-04-03"], got


def check_missing_dates_excludes_the_end():
    """The window is half-open, so the earliest cached date is not re-pulled
    and the two ranges cannot overlap by one."""
    import datetime as dt

    class _C:
        def execute(self, *_):
            return []
    got = season.missing_dates(start=dt.date(2026, 4, 1),
                               end=dt.date(2026, 4, 3), conn=_C())
    assert got == ["2026-04-01", "2026-04-02"], got


def check_gb_share_is_counted_scoped_and_shrunk():
    """Item 4a's plumbing contract: ground-ball share is COUNTED from the
    pbp cache (never fetched season-to-date, which would hand prior folds
    an index that knows the future), obeys the same date cuts rates do,
    and shrinks a thin sample toward the league."""
    from src.context.sources import battedball as bb
    full = bb.gb_pct_map("pit")
    assert len(full) > 800, len(full)
    vals = list(full.values())
    lg = sum(vals) / len(vals)
    assert 0.38 < lg < 0.47, lg
    assert all(0.10 < v < 0.75 for v in vals)
    # The cutoff reaches the count: an early-season cut must not return
    # the same table as the full scan.
    cut = bb.gb_pct_map("pit", 2026, "2026-05-01")
    assert cut and cut != full
    # Thin samples sit near the league — the measured k, not a guess.
    counts = bb.gb_counts("pit")
    thin = [nm for nm, (_g, n) in counts.items() if 0 < n <= 5]
    for nm in thin[:20]:
        assert abs(full[nm] - lg) < 0.08, (nm, full[nm])


def check_the_cases_carry_gb_for_both_sides_of_the_ball():
    """The plumbing is only plumbing if the engine's inputs actually carry
    it: starters and lineups out of `build_cases`, arms out of `bullpens`.
    None on a name nobody counted is correct; None everywhere is a dead
    wire."""
    from src.context import calibrate as cal, sim
    from src.context.sources import rates as rate_src
    pairs = cal.paired_cases(rates_before="2026-07-01", since="2026-07-01")
    gids = sorted(pairs)[:40]
    sp = [pairs[g][i][1].gb_pct for g in gids for i in (0, 1)]
    assert sum(v is not None for v in sp) / len(sp) > 0.9, \
        "starters missing gb_pct — the build_cases wire is dead"
    bats = [b.gb_pct for g in gids for c in pairs[g] for b in c[2]]
    assert sum(v is not None for v in bats) / len(bats) > 0.8, \
        "batters missing gb_pct"
    lg = sim.league(before="2026-07-01")
    pens = rate_src.bullpens(lg, before="2026-07-01")
    arms = [a["gb_pct"] for team in list(pens.values())[:10] for a in team]
    assert sum(v is not None for v in arms) / len(arms) > 0.8, \
        "pen arms missing gb_pct"


def check_air_share_is_counted_scoped_and_shrunk():
    """The `AIR_HR_PIT` covariate's contract, and it is the same one
    `gb_pct` has for the reason `battedball`'s header gives: counted from
    the pbp cache, never fetched season-to-date, so a 2023 fold is not
    handed a share that knows the future.

    The date cut is load-bearing here in a way it is not for `gb_pct` —
    the table this feeds was counted on a covariate frozen STRICTLY
    before the rows it bins, and scoring it against a share built on the
    whole scan would be the leakage `DP_GB_*` had to be re-counted for.
    """
    from src.context.sources import battedball as bb
    full = bb.air_pct_map("pit")
    assert len(full) > 800, len(full)
    vals = list(full.values())
    lg = sum(vals) / len(vals)
    # Air is fly balls plus line drives, so the league sits just above a
    # half — the complement of the ground-ball share plus popups.
    assert 0.45 < lg < 0.58, lg
    assert all(0.20 < v < 0.85 for v in vals)
    cut = bb.air_pct_map("pit", 2026, "2026-05-01")
    assert cut and cut != full
    # Thin samples sit near the league — the measured k, not a guess.
    counts = bb.air_counts("pit")
    thin = [nm for nm, (_a, n) in counts.items() if 0 < n <= 5]
    for nm in thin[:20]:
        assert abs(full[nm] - lg) < 0.08, (nm, full[nm])
    # AND THE QUINTILE EDGES MUST CUT THIS POPULATION, not some other
    # one. A table whose edges sit outside the covariate's range would
    # put every arm in one cell and read as a null rather than an error.
    from src.context import sim
    cells = [sum(v >= e for e in sim.AIR_HR_PIT[0]) for v in vals]
    assert len(set(cells)) == 5, \
        f"AIR_HR_PIT edges do not span the shrunk air shares: {set(cells)}"


def check_the_cases_carry_air_for_every_arm():
    """Starters out of `build_cases`, relievers out of `bullpens`.

    RELIEVERS ARE CHECKED AND NOT ASSUMED: they throw about a third of
    the innings, and a level or shape measured on every arm but wired to
    starters only is the wild-pitch mistake this project has already
    made once (rule 14).
    """
    from src.context import calibrate as cal, sim
    from src.context.sources import rates as rate_src
    pairs = cal.paired_cases(rates_before="2026-07-01", since="2026-07-01")
    gids = sorted(pairs)[:40]
    sp = [pairs[g][i][1].air_pct for g in gids for i in (0, 1)]
    assert sum(v is not None for v in sp) / len(sp) > 0.9, \
        "starters missing air_pct — the build_cases wire is dead"
    lg = sim.league(before="2026-07-01")
    pens = rate_src.bullpens(lg, before="2026-07-01")
    arms = [a["air_pct"] for team in list(pens.values())[:10] for a in team]
    assert sum(v is not None for v in arms) / len(arms) > 0.8, \
        "pen arms missing air_pct"
    # The batter carries none, by measurement — see the null recorded on
    # `sim.AIR_HR_PIT`.
    bats = [b for g in gids for c in pairs[g] for b in c[2]]
    assert bats and not any(hasattr(b, "air_pct") for b in bats)


def check_the_two_batted_ball_tables_count_the_same_balls():
    """`mlb_traj` and `mlb_batted` are two independent walks of the same
    cache, so their shared columns must agree exactly.

    THIS IS THE ONLY CORRECTNESS CHECK AVAILABLE for either extractor —
    nothing else in the project counts a trajectory, so `fb`, `ld` and
    `pu` can only be checked against each other's totals. It has already
    earned its place once: the first build of `mlb_traj` dropped
    `bunt_line_drive` on the floor, 75 balls in four seasons, and this
    comparison is what found it. A silent one-in-4,000 undercount of
    `bip` is exactly the kind of thing that never surfaces anywhere else.
    """
    from src.context import store
    with store.connect(attach=False) as c:
        row = c.execute(
            "select count(*) n, "
            "sum(t.gb != b.gb) dg, sum(t.bip != b.bip) dn "
            "from mlb_traj t join mlb_batted b "
            "using (game_id, name, role)").fetchone()
    assert row["n"] > 200000, f"only {row['n']} rows joined"
    assert (row["dg"], row["dn"]) == (0, 0), \
        f"{row['dg']} gb and {row['dn']} bip disagreements over " \
        f"{row['n']:,} rows"
    # And the split must exhaust the total, per player-game — a
    # trajectory landing in no column would leave `bip` short of its
    # own parts and read as a thinner sample rather than a lost ball.
    with store.connect(attach=False) as c:
        bad = c.execute(
            "select count(*) n from mlb_traj "
            "where gb + fb + ld + pu != bip").fetchone()["n"]
    assert bad == 0, f"{bad} rows where the trajectory split misses bip"
    # Home runs are a subset of the air balls they leave on — with one
    # genuine exception per four seasons, and it is not a bug. The
    # INSIDE-THE-PARK home run is a ground ball: mlb-825099, 2026-04-21,
    # Sam Antonacci off Ryan Thompson, launch angle 1 degree and 57 feet
    # of total distance, down the left-field line. This assertion
    # originally read `== 0` and that row is what corrected it. Pinned
    # loosely rather than exactly, because the right bound is "a handful
    # in the modern game", not the one that happens to be cached today.
    with store.connect(attach=False) as c:
        n_hr = c.execute("select sum(hr) n from mlb_traj "
                         "where role = 'pit'").fetchone()["n"]
        bad = c.execute(
            "select count(*) n from mlb_traj where hr > fb + ld"
            " and role = 'pit'").fetchone()["n"]
    assert bad <= 5, f"{bad} rows with more home runs than air balls"
    assert bad / n_hr < 1e-3, "inside-the-park home runs are supposed " \
        "to be a rounding error; this is a trajectory bug"
