"""The per-arm hook offset — the fit's arithmetic and its wiring (TODO 32).

Every check here guards a way this mechanism could be silently wrong rather
than loudly broken, which is the only kind that survives: an offset fitted
on the wrong scale, a variance that forgets it is clustered, a shrinkage
that ignores the measured carry, a table that moves the league LEVEL instead
of redistributing, two curves quietly sharing one number, and a per-arm slot
leaking into the hash that protects every offset file on disk.

The fit is exercised on HAND-MADE rows with no database and no play-by-play
behind it — `fit` takes the intent-gated population as an argument for
exactly this reason.
"""
import math

from src.context import armhook as ah, sim


def _rows(name, curve_is_bnd, p, n, removed, date="2025-05-01", cluster=None):
    """`n` decisions at probability `p`, `removed` of them pulled.

    THE REMOVALS ARE SPREAD EVENLY ACROSS CLUSTERS, not dealt to the first
    rows. Piling them into the opening clusters makes every start either
    all-pulled or all-left, which is perfectly correlated within a cluster
    and inflates the cluster-robust variance past the planted between-arm
    spread — the shrinkage then zeroes the whole table and the test reads as
    a wiring failure. Real starts do not look like that, and a synthetic
    fixture that does tests the wrong thing.
    """
    def pulled(i):
        return ((i + 1) * removed) // n - (i * removed) // n == 1
    return [{"name": name, "date": date, "ends_inning": curve_is_bnd,
             "p": p, "removed": pulled(i),
             "cluster": cluster or (f"{name}|{date}|{i // 6}", "home")}
            for i in range(n)]


def _planted(p, delta):
    """The observed rate a planted log-odds shift produces at base `p`."""
    lo = math.log(p / (1 - p)) + delta
    return 1 / (1 + math.exp(-lo))


# ── the solve ──────────────────────────────────────────────────────────

def check_the_solve_recovers_a_planted_offset():
    """THE POSITIVE CONTROL ON THE ESTIMATOR ITSELF. Outcomes generated at a
    known log-odds shift must come back at that shift — if this drifts, every
    number the module prints is on the wrong scale."""
    for delta in (-0.8, -0.25, 0.4, 1.1):
        n = 4000
        rate = _planted(0.2, delta)
        got, _var, _n = ah._solve(_rows("a", True, 0.2, n, round(n * rate)))
        assert abs(got - delta) < 0.02, (delta, got)


def check_the_solve_is_right_when_the_states_differ():
    """A real arm's decisions span very different p, and an offset is NOT the
    difference of averages there — it is the shift that reproduces the
    observed COUNT through the nonlinearity. Averaging the probabilities
    first would pass the flat-p check above and fail this one."""
    delta = 0.6
    rows = []
    for p in (0.03, 0.12, 0.45, 0.8):
        n = 3000
        rows += _rows(f"a{p}", True, p, n, round(n * _planted(p, delta)))
    got, _var, _n = ah._solve(rows)
    assert abs(got - delta) < 0.02, got


def check_a_base_offset_is_fitted_against_not_reabsorbed():
    """`base` is what a wider group (the season) already explains. An arm who
    is exactly average FOR HIS SEASON must come back at zero, not at the
    season's own offset — that is what keeps this item orthogonal to the era
    drift of TODO 33 instead of double-counting it."""
    n = 5000
    season = 0.5
    rate = _planted(0.2, season)
    got, _var, _n = ah._solve(_rows("a", True, 0.2, n, round(n * rate)),
                              base=season)
    assert abs(got) < 0.02, got


def check_the_variance_is_cluster_robust():
    """MUTATION IN THE DATA. Decisions from one start are one manager on one
    night. Rows whose misses are perfectly correlated INSIDE a cluster must
    carry a larger variance than the same rows spread across clusters;
    treating them as independent would under-shrink every arm and hand the
    clamp real work to do."""
    # 20 starts of 6 decisions. Correlated: a start is all-pulled or
    # all-left. Independent: the same 60 removals dealt evenly, 3 per start.
    corr, indep = [], []
    for g in range(20):
        allpulled = g < 10
        for i in range(6):
            corr.append({"name": "a", "date": "2025-05-01",
                         "ends_inning": True, "p": 0.5,
                         "removed": allpulled, "cluster": (f"g{g}", "home")})
            indep.append({"name": "a", "date": "2025-05-01",
                          "ends_inning": True, "p": 0.5,
                          "removed": i < 3, "cluster": (f"g{g}", "home")})
    v_corr = ah._solve(corr)[1]
    v_indep = ah._solve(indep)[1]
    assert v_corr > 4 * v_indep, (v_corr, v_indep)


def check_an_arm_with_too_few_starts_gets_no_believable_variance():
    """A sandwich needs clusters to count. At one cluster the score residuals
    sum to zero BY CONSTRUCTION, so the variance is exactly 0 and that arm
    would sail through the shrinkage with weight 1.0 — the least trustworthy
    arm in the table treated as the most. Below `MIN_CLUSTERS` the variance
    must come back non-finite so `_eb` drops him."""
    one = _rows("a", True, 0.2, 120, 60, cluster=("one", "home"))
    assert ah._solve(one)[1] == float("inf")
    spread = [dict(r, cluster=(f"g{i % ah.MIN_CLUSTERS}", "home"))
              for i, r in enumerate(_rows("a", True, 0.2, 120, 60))]
    assert math.isfinite(ah._solve(spread)[1])


# ── shrinkage ──────────────────────────────────────────────────────────

def check_a_thin_sample_is_pulled_further_than_a_thick_one():
    """Two arms with the SAME raw estimate and different precision must not
    get the same offset. This is the part a single shrinkage constant cannot
    express, and the reason `_eb` weights each arm by his own variance."""
    est = {"thick": (0.6, 0.01, 400), "thin": (0.6, 0.25, 40),
           "a": (0.2, 0.02, 300), "b": (-0.5, 0.02, 300),
           "c": (0.1, 0.02, 300), "d": (-0.3, 0.02, 300)}
    offs, _b, _w = ah._eb(est)
    assert abs(offs["thick"]) > abs(offs["thin"]), offs
    assert abs(offs["thin"]) < 0.6


def check_shrinkage_scales_with_the_measured_carry():
    """The year-over-year reliability multiplies every offset. A `carry` that
    silently defaulted to 1.0 is the bug that made the clamp bind on forty
    arms — the term then describes an arm's past and over-corrects his
    future, which is the established defect in the shipped leash."""
    est = {k: (v, 0.02, 300) for k, v in
           (("a", 0.6), ("b", -0.4), ("c", 0.2), ("d", -0.1))}
    full, _b, _w = ah._eb(est, carry=1.0)
    half, _b2, _w2 = ah._eb(est, carry=0.5)
    for k in full:
        assert abs(half[k] - full[k] / 2) < 1e-12, (k, full[k], half[k])


def check_an_arm_under_the_floor_is_not_written():
    """Below `MIN_DECISIONS` an arm has nothing to say and his MLE can be at
    the bracket edge. He must be absent from the table, not present at zero:
    absent takes the league curve, which is the missing-group rule."""
    est = {"tiny": (2.0, 0.5, ah.MIN_DECISIONS - 1),
           "a": (0.2, 0.02, 300), "b": (-0.5, 0.02, 300),
           "c": (0.1, 0.02, 300), "d": (-0.3, 0.02, 300)}
    offs, _b, _w = ah._eb(est)
    assert "tiny" not in offs
    assert "a" in offs


def check_the_clamp_is_applied_to_the_shrunk_value():
    """A degenerate solve must not escape through the shrinkage. The clamp is
    a guard, and `build` prints how many arms it binds on so a clamp that
    starts doing real work cannot do it silently."""
    est = {"wild": (40.0, 1e-9, 500), "a": (0.2, 0.02, 300),
           "b": (-0.5, 0.02, 300), "c": (0.1, 0.02, 300)}
    offs, _b, _w = ah._eb(est)
    assert abs(offs["wild"]) <= ah.ARM_CLAMP + 1e-9


# ── the level ──────────────────────────────────────────────────────────

def check_offsets_are_centred_on_the_decision_weighted_mean():
    """A per-arm term must REDISTRIBUTE and never move the league level —
    the level belongs to the hook's intercept and the counted tables. The
    weights are decision counts, so an arm with ten times the starts carries
    ten times the weight; centring on the unweighted mean would leave a
    level shift behind whenever the two differ, which is exactly how
    `AIR_HR_PIT`'s falsifier fired."""
    offs = {"big": 0.5, "small": -0.5}
    n_by = {"big": 900, "small": 100}
    out, removed = ah._centre(offs, n_by)
    assert abs(removed - 0.4) < 1e-12, removed
    applied = sum(out[k] * n_by[k] for k in out) / sum(n_by.values())
    assert abs(applied) < 1e-12, applied


# ── the two curves ─────────────────────────────────────────────────────

def check_each_curve_gets_ITS_OWN_offset():
    """Rule 9. The boundary and mid-inning pulls are different decisions, and
    an arm left in at the boundary while being yanked mid-inning must come
    out with offsets of OPPOSITE sign. One shared field cannot carry two
    numbers, which is why `Hook` grew two."""
    rows = []
    for nm in ("x", "y", "z", "w"):
        rows += _rows(nm, True, 0.2, 600, round(600 * 0.2))
        rows += _rows(nm, False, 0.05, 600, round(600 * 0.05))
    # One arm: pulled MORE at the boundary, LESS mid-inning.
    rows += _rows("split", True, 0.2, 600, round(600 * _planted(0.2, 1.0)))
    rows += _rows("split", False, 0.05, 600, round(600 * _planted(0.05, -1.0)))
    keep = {"x", "y", "z", "w", "split"}
    # `carry` is handed in because these rows are one season, so the
    # year-over-year reliability is not estimable from them — and `fit`
    # RAISES rather than defaulting it, which is the behaviour
    # `check_an_unmeasurable_carry_is_refused` pins.
    out = ah.fit(rows, before="2026-07-01", verbose=False, keep=keep,
                 carry=1.0)
    assert out["bnd"]["split"] > 0, out["bnd"]
    assert out["mid"]["split"] < 0, out["mid"]


def check_a_pure_season_effect_does_not_become_a_per_arm_offset():
    """THE ERA GUARD. Every arm behaves identically but the league pulls
    harder in 2026. The season offsets must absorb it and the per-arm
    offsets must stay at zero — otherwise an arm whose career sits in one
    season is handed that season's drift as if it were his own leash, and
    TODO 32 and 33 would double-count each other."""
    rows = []
    for nm in ("a", "b", "c", "d"):
        for date, delta in (("2024-05-01", 0.0), ("2026-05-01", 0.8)):
            n = 900
            rate = _planted(0.2, delta)
            rows += _rows(nm, True, 0.2, n, round(n * rate), date=date)
    out = ah.fit(rows, before="2026-07-01", verbose=False,
                 keep={"a", "b", "c", "d"}, carry=1.0)
    seasons = out["_meta"]["bnd"]["season_offsets"]
    assert seasons["2026"] - seasons["2024"] > 0.6, seasons
    for nm, v in (out["bnd"] or {}).items():
        assert abs(v) < 0.05, (nm, v)


def check_the_holdout_bound_filters_rows_before_fitting():
    """Rule 6, and it is one line that is easy to lose: anything fitted on
    decision rows filters to `date < HOLDOUT` BEFORE fitting. A row from the
    scoring window must not reach the solve."""
    rows = _rows("a", True, 0.2, 400, 200, date="2026-09-01")
    rows += _rows("b", True, 0.2, 400, 80, date="2025-05-01")
    rows += _rows("c", True, 0.2, 400, 80, date="2025-05-01")
    rows += _rows("d", True, 0.2, 400, 80, date="2025-05-01")
    out = ah.fit(rows, before="2026-07-01", verbose=False,
                 keep={"a", "b", "c", "d"}, carry=1.0)
    assert "a" not in (out["bnd"] or {}), out["bnd"]
    assert out["_meta"]["bnd"]["decisions"] == 1200


def check_the_intent_gate_drops_arms_not_sent_out_for_length():
    """An opener's short outings are a ROLE, not a leash, and `USE_OPENER_
    EXIT` already models him. He must not reach the fit — where he would
    also inflate the between-arm variance and loosen the shrinkage applied
    to every genuine starter."""
    rows = []
    for nm in ("a", "b", "c", "opener"):
        rows += _rows(nm, True, 0.2, 400, 80)
    out = ah.fit(rows, before="2026-07-01", verbose=False,
                 keep={"a", "b", "c"}, carry=1.0)
    assert "opener" not in (out["bnd"] or {})
    assert out["_meta"]["bnd"]["decisions"] == 1200


# ── the wiring ─────────────────────────────────────────────────────────

def check_each_offset_reaches_its_own_curve_and_only_its_own():
    """The term is useless if it does not arrive, and WRONG if it arrives in
    both places. A boundary offset must move `removal_p` and leave
    `mid_removal_p` untouched, and the reverse."""
    base = sim.Hook()
    args_b = (85, 3, 6, 2, 1)
    args_m = (85, 3, 1, 1.0, 1)
    b_on = sim.Hook(**{**base.__dict__, "arm_bnd_offset": 0.5})
    m_on = sim.Hook(**{**base.__dict__, "arm_mid_offset": 0.5})
    assert b_on.removal_p(*args_b) > base.removal_p(*args_b)
    assert b_on.mid_removal_p(*args_m) == base.mid_removal_p(*args_m)
    assert m_on.mid_removal_p(*args_m) > base.mid_removal_p(*args_m)
    assert m_on.removal_p(*args_b) == base.removal_p(*args_b)


def check_the_offset_reaches_the_early_branches_too():
    """Both curves have an `early_innings` branch that ships inert. A term
    left out of it is a silent hole the day that branch is switched on —
    the trap `per_layoff` documents and which this mechanism would have
    repeated for free."""
    for field, kw, call in (
            ("arm_bnd_offset", {"early_innings": 3},
             lambda h: h.removal_p(40, 1, 2, 1, 0)),
            ("arm_mid_offset", {"early_innings": 3},
             lambda h: h.mid_removal_p(40, 1, 1, 0.0, 0, inning=2))):
        off = sim.Hook(**kw)
        on = sim.Hook(**{**off.__dict__, field: 0.7})
        assert call(on) > call(off), field


def check_for_start_composes_the_arm_offsets():
    """`for_start` ADDS, so a caller that has already applied something
    composes instead of silently losing it — the rule `team_offset` follows
    and the bug its docstring records."""
    pre = sim.Hook(arm_bnd_offset=0.3, arm_mid_offset=-0.2)
    got = sim.for_start(pre, "PHI", "Nobody In Any Table")
    assert got.arm_bnd_offset == 0.3
    assert got.arm_mid_offset == -0.2


def check_an_unknown_arm_contributes_exactly_zero():
    """The missing-group rule. An arm with no entry gets the league curve,
    never a guess and never another arm's number."""
    was = sim.USE_ARM_HOOK
    try:
        sim.USE_ARM_HOOK = True
        sim.reload_offsets()
        assert sim.arm_offsets("Nobody In Any Table") == (0.0, 0.0)
        assert sim.arm_offsets(None) == (0.0, 0.0)
    finally:
        sim.USE_ARM_HOOK = was
        sim.reload_offsets()


def check_the_flag_off_means_off():
    """A shipped-off mechanism must contribute nothing even with a table on
    disk, or every measurement taken while it is parked is contaminated."""
    was = sim.USE_ARM_HOOK
    try:
        sim.USE_ARM_HOOK = False
        sim.reload_offsets()
        assert sim.arm_offsets("Aaron Nola") == (0.0, 0.0)
    finally:
        sim.USE_ARM_HOOK = was
        sim.reload_offsets()


# ── the hash that protects every offset file ───────────────────────────

def check_hook_hash_ignores_the_per_start_slots():
    """Adding a per-start slot that defaults to zero changes no curve, so it
    must not change the digest — otherwise every offset table on disk is
    refused and has to be rebuilt to measure the very same hook."""
    for name in sim._HASH_EXCLUDE:
        assert name in {f for f in sim.Hook().__dict__}
    assert sim.hook_hash() == sim.hook_hash()
    h = sim.Hook()
    assert h.arm_bnd_offset == 0.0 and h.arm_mid_offset == 0.0


def _with_defaults(**kw):
    """A Hook subclass carrying different DEFAULTS.

    Mutating `dataclasses.fields(Hook)[x].default` does NOT work and the
    first version of these two checks did exactly that: the generated
    `__init__` captured the defaults at class-creation time, so `Hook()`
    kept returning the old values and both checks passed vacuously. A
    subclass is the only mutation vector that reaches `hook_hash`, which
    reads `Hook()` through the module global.
    """
    import dataclasses
    ns = {"__annotations__": {k: float for k in kw}}
    ns.update(kw)
    return dataclasses.dataclass(type("_MutantHook", (sim.Hook,), ns))


def check_the_shipped_offset_tables_still_load():
    """THE INVARIANT THE EXCLUSION EXISTS FOR, and the only one that is
    checkable against the real world: `hook_leash.json` was stamped before
    the two arm slots were added, so if they had entered the digest the
    shipped leash would be REFUSED at import and `USE_LEASH` would silently
    become a no-op. A mechanism that disables another one by being added is
    the failure this pins."""
    import json
    with open(sim._LEASH_PATH) as f:
        meta = json.load(f).get("_meta") or {}
    assert meta.get("hook_hash") == sim.hook_hash(), (
        meta.get("hook_hash"), sim.hook_hash())
    # and the loader really does hand the offset over
    was = sim.USE_LEASH
    try:
        sim.USE_LEASH = True
        sim.reload_offsets()
        assert sim.leash("Cristopher Sánchez") != 0.0
    finally:
        sim.USE_LEASH = was
        sim.reload_offsets()


def check_an_unmeasurable_carry_is_refused():
    """A window with no consecutive seasons in it cannot estimate the carry,
    and the honest response is to REFUSE. Defaulting it to 0.0 writes a table
    of zeros that loads and validates and does nothing; defaulting it to 1.0
    ships the over-correction this term exists to avoid. Both are silent, so
    `fit` raises."""
    rows = []
    for nm in ("a", "b", "c", "d"):
        rows += _rows(nm, True, 0.2, 400, 80)
    raised = False
    try:
        ah.fit(rows, before="2026-07-01", verbose=False,
               keep={"a", "b", "c", "d"})
    except ValueError:
        raised = True
    assert raised, "an unmeasurable year-over-year carry must raise"


def check_hook_hash_still_moves_on_a_real_coefficient():
    """MUTATION. The exclusion must be narrow: a change to a LEAGUE
    coefficient has to keep invalidating the offset files, which is the
    whole job of the guard and the thing it went stale five times without."""
    before = sim.hook_hash()
    was = sim.Hook
    try:
        sim.Hook = _with_defaults(per_run=was().per_run + 0.01)
        assert sim.hook_hash() != before
    finally:
        sim.Hook = was
    assert sim.hook_hash() == before


def check_a_non_zero_default_in_an_excluded_slot_raises():
    """The exclusion is legitimate only while the default is zero. A
    non-zero default is a league-level change wearing a per-start slot's
    clothes and must fail loudly rather than hide inside the digest."""
    was = sim.Hook
    try:
        sim.Hook = _with_defaults(arm_bnd_offset=0.25)
        raised = False
        try:
            sim.hook_hash()
        except ValueError:
            raised = True
        assert raised, "a non-zero excluded default must raise"
    finally:
        sim.Hook = was
    sim.hook_hash()


def check_a_table_built_against_another_hook_is_refused(tmp=None):
    """A residual correcting errors the curve no longer makes pushes the
    WRONG way. The loader refuses a stamp mismatch rather than distrusting
    it quietly — `sim.leash` needed this after going stale five times."""
    import json
    import os
    was, path = sim.USE_ARM_HOOK, sim._ARM_PATH
    tmp_path = "/tmp/hook_arm_test_refuse.json"
    try:
        with open(tmp_path, "w") as f:
            json.dump({"_meta": {"hook_hash": "deadbeef1234"},
                       "bnd": {"Aaron Nola": -0.5}, "mid": {}}, f)
        sim.USE_ARM_HOOK = True
        sim._ARM_PATH = tmp_path
        sim.reload_offsets()
        assert sim.arm_offsets("Aaron Nola") == (0.0, 0.0)
        # And it is accepted once the stamp matches, or the check above
        # would pass for a table that simply never loads.
        with open(tmp_path, "w") as f:
            json.dump({"_meta": {"hook_hash": sim.hook_hash()},
                       "bnd": {"Aaron Nola": -0.5}, "mid": {}}, f)
        sim.reload_offsets()
        assert sim.arm_offsets("Aaron Nola") == (-0.5, 0.0)
    finally:
        sim.USE_ARM_HOOK, sim._ARM_PATH = was, path
        sim.reload_offsets()
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def check_the_fit_never_runs_with_its_own_table_applied():
    """THE DOUBLE-COUNT GUARD, and it is the same one `leash._sim_one` needs:
    the offsets are a residual against the hook WITHOUT them, so a rebuild
    with the table already in effect folds its own correction back into
    itself and drifts a little further every time."""
    seen = []
    real_predict, real_rows = ah.predict, ah.decision_rows
    was = sim.USE_ARM_HOOK
    try:
        sim.USE_ARM_HOOK = True
        ah.decision_rows = lambda **kw: []
        ah.predict = lambda rows: seen.append(sim.USE_ARM_HOOK)
        ah.build(before="2026-07-01", path="/tmp/hook_arm_test_build.json")
    finally:
        ah.predict, ah.decision_rows = real_predict, real_rows
        sim.USE_ARM_HOOK = was
    assert seen == [False], seen
    # and it is RESTORED afterwards, not left off for the whole process
    assert sim.USE_ARM_HOOK == was
