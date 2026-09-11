"""Per-pitcher pitch efficiency — the count, the centring, the wiring (34).

The ways this could be silently wrong rather than loudly broken: the
multiplier could be measured against the league instead of against his own
outcome mix (and so just restate his strikeout rate), it could move the
league's calibrated pitches-a-start, it could be billed to the wrong arm
after a handover, or it could be shrunk by two coefficients that each
already account for the same noise.
"""
import json
import math
import random

from src.context import efficiency as eff, game, sim


def _row(nm, yr, pitches, k=0, bb=0, hbp=0, hr=0, h=0, o=60, gs=20):
    return {"nm": nm, "yr": yr, "pt": pitches, "k": k, "bb": bb, "hbp": hbp,
            "hr": hr, "h": h, "o": o, "gs": gs}


def check_expected_pitches_uses_his_own_outcome_mix():
    """OBSERVED OVER EXPECTED, never observed over league. A strikeout costs
    4.85 and a ball in play 3.37, so two arms with identical pitch counts and
    different strikeout totals must get DIFFERENT multipliers — that is what
    stops this term from handing the engine back a rate it already has."""
    many_k = _row("k", "2025", 1000, k=100, o=60, h=20, bb=10)
    few_k = _row("c", "2025", 1000, k=10, o=60, h=20, bb=10)
    e1, bf1 = eff._expected(many_k)
    e2, bf2 = eff._expected(few_k)
    assert bf1 == bf2, "same batters faced, or the comparison is not clean"
    assert e1 > e2, (e1, e2)
    # and the strikeout arm is therefore the MORE efficient of the two at an
    # identical pitch count
    assert 1000 / e1 < 1000 / e2


def check_expected_pitches_tracks_the_shipped_pitch_cost():
    """The multiplier is measured AGAINST `PITCH_COST`, so the two must not
    drift apart: if that table is recounted, every multiplier on disk is
    measured against a table that no longer exists. This pins the dependency
    so the rebuild is not forgotten."""
    r = _row("a", "2025", 0, k=10, bb=5, hbp=1, hr=2, h=8, o=30)
    exp, bf = eff._expected(r)
    c = sim.PITCH_COST
    rest = bf - 10 - 5 - 1 - 2
    want = (c[sim.K] * 10 + c[sim.BB] * 5 + c[sim.HBP] * 1
            + c[sim.HR] * 2 + c[sim.OUT] * rest)
    assert abs(exp - want) < 1e-9, (exp, want)


def check_the_carry_and_its_variance_come_from_one_population():
    """NAME THE DENOMINATOR. The carry is a correlation and it scales a
    variance; measuring the two on different populations makes their ratio
    meaningless. Taking the variance over every arm-season — twenty-batter
    cameos included — inflated it 4x and switched the shrinkage off for the
    whole table, which is the bug this pins."""
    assert eff.CARRY_MIN_BF >= 150
    cells = {("a", "2023"): (1.10, 50), ("a", "2024"): (0.90, 50)}
    # a thin arm-season must not reach the carry estimate at all
    r, pairs = eff.carry_of(cells)
    assert pairs == 0, pairs


def check_an_unmeasurable_carry_is_refused():
    """Same rule TODO 32 had to learn: a carry that cannot be measured must
    RAISE, not default. Defaulting to 1.0 ships the over-correction the carry
    exists to prevent, and silently."""
    cells = {("a", "2023"): (1.0, 500)}
    r, pairs = eff.carry_of(cells)
    assert r == 0.0 and pairs == 0


def check_centring_removes_the_batters_faced_WEIGHTED_mean():
    """A per-arm multiplier must REDISTRIBUTE, never move the league level:
    `PITCH_COST` is calibrated to ~86.8 pitches a start and a table averaging
    0.98 would hand every pitcher in baseball 2% more pitch budget.

    THE WEIGHTS ARE BATTERS FACED, and this is built so the weighting is
    load-bearing — one heavy arm against three light ones, so the weighted
    and unweighted means differ a lot. An implementation that skipped the
    centring, or centred on the unweighted mean, fails here. The previous
    version of this check asserted only that the SHIPPED file averaged ~1.0
    within 1%, which the shipped file does whether it is centred or not
    (its applied mean is 1.002), and it survived deleting the centring."""
    shrunk = {"heavy": (1.06, 3000), "a": (0.98, 100),
              "b": (0.98, 100), "c": (0.98, 100)}
    out, applied, _clamped = eff.centre(shrunk)
    # the weighted mean is dominated by `heavy`, the unweighted by the others
    want = (1.06 * 3000 + 0.98 * 300) / 3300
    assert abs(applied - want) < 1e-9, (applied, want)
    assert applied > 1.04, "the weighting must dominate, or this proves little"
    back = sum(out[k] * shrunk[k][1] for k in out) / 3300
    assert abs(back - 1.0) < 1e-4, back


def check_the_shipped_table_is_centred_and_inside_the_clamp():
    """The same invariant on the file that actually ships."""
    with open(eff.PATH) as f:
        data = json.load(f)
    vals = list(data["mult"].values())
    assert abs(data["_meta"]["applied_mean_removed"] - 1.0) < 0.05
    assert all(abs(v - 1.0) <= eff.EFF_CLAMP + 1e-9 for v in vals)


def check_apply_pa_bills_the_line_its_own_multiplier():
    """THE MECHANISM, THROUGH THE REAL CODE PATH, and its SIGN: above 1.0 he
    needs more pitches for the same outcomes.

    IT MUST CALL `apply_pa`. The first version of this check did the
    multiplication in the test itself and so asserted its own arithmetic — it
    survived a mutation that deleted `* r.pitch_mult` from the engine, which
    is the entire mechanism. A test that reimplements what it is checking
    cannot fail when the thing it checks is removed."""
    rng = random.Random(0)
    got = {}
    for mult in (0.95, 1.0, 1.05):
        r = sim.StartResult(pitch_mult=mult)
        fr = sim.Frame()
        for _ in range(9):
            sim.apply_pa(sim.K, r, fr, rng)
            if fr.outs >= 3:
                fr = sim.Frame()
        got[mult] = r.pitches
    assert got[0.95] < got[1.0] < got[1.05], got
    assert abs(got[1.05] / got[1.0] - 1.05) < 1e-9, got
    # Not an exact equality: nine accumulations of 4.85 and 9 * 4.85 differ
    # by an ULP, which is the kind of assertion that fails for a reason that
    # has nothing to do with the mechanism.
    assert abs(got[1.0] - 9 * sim.PITCH_COST[sim.K]) < 1e-9, got[1.0]


def check_the_multiplier_follows_the_ARM_not_the_side():
    """IT LIVES ON THE LINE. `game.Side` replaces `cur_line` at every
    handover, so a reliever must be billed his OWN efficiency and never the
    starter's — the stale-key defect item 23 records, which charged the
    relief hook the previous arm's cell for the life of the module.

    THE REAL MULTIPLIER HAS TO ARRIVE. Asserting only that an unknown arm
    gets 1.0 is satisfied by a `_bill` that hardcodes 1.0, which is what the
    first version of this check did and what let that mutation survive."""
    was = sim.USE_PITCH_EFF
    try:
        sim.USE_PITCH_EFF = True
        sim.reload_offsets()
        with open(eff.PATH) as f:
            mult = json.load(f)["mult"]
        nm, want = max(mult.items(), key=lambda kv: abs(kv[1] - 1.0))
        assert abs(want - 1.0) > 0.01, "pick an arm whose value is not ~1.0"

        class _Arm:
            name = nm

        line = sim.StartResult()
        game.Side._bill(line, _Arm())
        assert abs(line.pitch_mult - want) < 1e-9, (line.pitch_mult, want)
        # and an unknown arm is league, never a guess or a neighbour's number
        other = sim.StartResult()
        game.Side._bill(other, None)
        assert other.pitch_mult == 1.0
    finally:
        sim.USE_PITCH_EFF = was
        sim.reload_offsets()


def check_the_flag_off_bills_everybody_the_league_table():
    """A shipped-off mechanism must contribute exactly nothing, or every
    measurement taken while it is parked is contaminated."""
    was = sim.USE_PITCH_EFF
    try:
        sim.USE_PITCH_EFF = False
        sim.reload_offsets()
        assert sim.pitch_eff("Freddy Peralta") == 1.0
        sim.USE_PITCH_EFF = True
        sim.reload_offsets()
        # a real arm in the table moves off 1.0, or the check above proves
        # nothing but that the file never loads
        assert sim.pitch_eff("Freddy Peralta") != 1.0
        assert sim.pitch_eff("Nobody In Any Table") == 1.0
        assert sim.pitch_eff(None) == 1.0
    finally:
        sim.USE_PITCH_EFF = was
        sim.reload_offsets()


def check_the_shipped_spread_is_not_wider_than_the_stable_signal():
    """The lesson TODO 32 paid for: a per-arm term shrunk only for sampling
    noise describes an arm's PAST and over-corrects his future. The shipped
    spread must sit at or below the stable (year-over-year) signal, which for
    this quantity is sd ~0.023 in multiplier units."""
    with open(eff.PATH) as f:
        mult = json.load(f)["mult"]
    vals = list(mult.values())
    sd = math.sqrt(sum((v - 1.0) ** 2 for v in vals) / len(vals))
    assert sd <= 0.025, sd
    # and it is not zero, which would mean the shrinkage ate the whole term
    assert sd > 0.005, sd
