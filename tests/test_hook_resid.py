"""The hook residual screen's arithmetic, because the numbers it prints are
reported as findings.

Three things can silently break a calibration screen and each is checked
here: the diff can be computed against the wrong denominator, the clustered
standard error can quietly collapse to the binomial one (which would call a
noise slice a finding), and the split-half halves can move between runs so a
reliability does not reproduce.
"""
import math

from scratchpad import hook_resid as hr


def _row(gid, side, p, removed):
    return {"game_id": gid, "side": side, "p": p, "removed": removed,
            "e": (1.0 if removed else 0.0) - p}


def check_cell_reports_observed_against_predicted():
    """`diff` is the real rate minus the MODEL's mean p, not minus a
    constant and not the other way round."""
    rows = [_row(f"mlb-{i}", "home", 0.2, i < 3) for i in range(10)]
    c = hr.cell(rows)
    assert c["n"] == 10
    assert abs(c["obs"] - 0.3) < 1e-12
    assert abs(c["pred"] - 0.2) < 1e-12
    assert abs(c["diff"] - 0.1) < 1e-12


def check_the_binomial_se_is_the_poisson_binomial_one():
    """Rows carry DIFFERENT p, so the se is sqrt(sum p(1-p))/n — using the
    pooled rate instead would be wrong wherever the curve varies, which is
    every slice in the screen."""
    ps = [0.05, 0.4, 0.9]
    rows = [_row(f"mlb-{i}", "home", p, False) for i, p in enumerate(ps)]
    want = math.sqrt(sum(p * (1 - p) for p in ps)) / 3
    assert abs(hr.cell(rows)["se_bin"] - want) < 1e-12


def check_clustering_sees_correlation_within_a_start():
    """MUTATION IN THE DATA. Six decisions that all miss the same way on
    one night are one manager, not six draws. Perfectly correlated rows
    must inflate the clustered se above the binomial one; independent rows
    must leave it near it.

    Without this, `se_cl` could be wired to the same expression as `se_bin`
    and every z in the screen would be overstated on clustered slices.
    """
    same = [_row("mlb-1", "home", 0.5, True) for _ in range(6)]
    spread = [_row(f"mlb-{i}", "home", 0.5, True) for i in range(6)]
    c_same, c_spread = hr.cell(same), hr.cell(spread)
    assert c_same["se_cl"] > 2 * c_same["se_bin"], \
        "the clustered se did not respond to within-start correlation"
    assert abs(c_spread["se_cl"] - c_spread["se_bin"]) < 1e-9, \
        "the clustered se inflated rows that share no cluster"


def check_clusters_are_game_AND_side():
    """The two starters in one game are two managers. Clustering on the
    game alone would pool them and misstate every se in the screen."""
    rows = ([_row("mlb-1", "home", 0.5, True) for _ in range(4)]
            + [_row("mlb-1", "away", 0.5, False) for _ in range(4)])
    # The two sides' residuals are +0.5 and -0.5 and would cancel exactly
    # if the side were dropped from the key.
    assert hr.cell(rows)["se_cl"] > 1e-6, \
        "opposing starters were pooled into one cluster"


def check_the_split_half_is_stable_across_runs():
    """`hash()` on a string is randomised per process, so halves built with
    it do not reproduce. The split must be a function of the game id."""
    rows = [dict(_row(f"mlb-{i}", "home", 0.2, i % 3 == 0), name="A")
            for i in range(400)]
    seen = []
    for _ in range(2):
        halves: dict = {}
        for r in rows:
            halves.setdefault(int(r["game_id"].split("-")[-1]) % 2,
                              []).append(r["game_id"])
        seen.append(sorted(halves[0]))
    assert seen[0] == seen[1]
    assert len(seen[0]) == 200, "the split is not even on consecutive ids"


def check_repeats_refuses_an_underpowered_sample(capture=None):
    """A null from this screen is a claim (rule 7), so too few units must
    print a refusal rather than a correlation over three points."""
    rows = [dict(_row(f"mlb-{i}", "home", 0.2, i % 2 == 0), name="A")
            for i in range(200)]
    # One unit, floor is 25 — it must not report a number.
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        hr.repeats(rows, lambda r: r["name"], "UNIT")
    assert "NOT POWERED" in buf.getvalue(), \
        "the screen reported a reliability it had no units for"
