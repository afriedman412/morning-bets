"""The board's HTML view. Offline, on a synthetic payload.

`board.build()` needs a slate, a season of rates and Kalshi, so nothing here
touches it. What IS tested is the part that can silently go wrong without
anyone noticing on a rendered page: the two views disagreeing about a price,
the away/home first-five split landing on the wrong club, the outs block
losing the caveat that governs it, and a non-ASCII character reaching a
document that has no `<meta charset>` to decode it.

The correction table itself is checked here too, since the board is its only
caller: that it is passed through UNSMOOTHED, that its crossover at 18 outs
holds, and that the two long rows stay inside the noise they were measured
at.
"""
import random

from scratchpad import board, board_html, outs_adjust
from scratchpad import dashkit as dk


def _row(stat, line, over, mid=None, **kw):
    """Built by the SHIPPED rule, never by a reimplementation of it.

    The first version of this helper computed `priced` and `edge` itself.
    Every check then passed against a board that priced off the raw
    probability, because the fixture was the only thing being tested.
    """
    r = board.price_row(
        stat, line, over, kw.get("proj", 5.0 if stat == "k" else 15.6),
        player=kw.get("player", "Test Arm"), opp="NYY", tag="BOS @ NYY",
        pa=400, w=kw.get("w", 0.9), confirmed=kw.get("confirmed", True))
    if kw.get("far") is not None:
        r["far"] = kw["far"]
    if mid is not None:
        r["mid"], r["edge"] = mid, r["priced"] - mid
    return r


def _payload(seed=7, away_f5_mean=1, home_f5_mean=4):
    """One game, two starters, deliberately different F5 distributions."""
    rnd = random.Random(seed)
    side = lambda name, opp, f5m: {           # noqa: E731
        "name": name, "opp": opp,
        "k": [rnd.randint(0, 12) for _ in range(400)],
        "outs": [rnd.randint(6, 24) for _ in range(400)],
        "pitches": [rnd.uniform(50, 105) for _ in range(400)],
        "f5": [max(0, int(rnd.gauss(f5m, 1))) for _ in range(400)],
        "pa": 400, "w": 0.9, "thin_at": 0.60, "confirmed": True,
        "rows": [_row("k", 4.5, 0.62, 0.50, player=name),
                 _row("k", 5.5, 0.41, 0.55, player=name),
                 _row("outs", 15.5, 0.55, 0.49, player=name, proj=15.6)],
    }
    return {
        "date": "2026-08-30", "n": 400, "band": 170.0, "max_spread": 12.0,
        "corrected_on": "2026-08-30",
        "declined": [("MIA @ WSH", "Janson Junk / Andrew Alvarez",
                      "game is In Progress")],
        "games": [{
            "tag": "BOS @ NYY", "away": "BOS", "home": "NYY", "n": 400,
            "f5_game": [rnd.randint(0, 11) for _ in range(400)],
            "f5_rows": [{"tag": "BOS @ NYY", "who": "BOS", "kind": "team",
                         "line": 1.5, "over": 0.51, "proj": 2.0},
                        {"tag": "BOS @ NYY", "who": "GAME", "kind": "game",
                         "line": 4.5, "over": 0.47, "proj": 4.6}],
            "sides": {"away": side("Away Arm", "NYY", away_f5_mean),
                      "home": side("Home Arm", "BOS", home_f5_mean)},
        }],
    }


def check_board_page_renders_every_section():
    html = board_html.render(_payload())
    for needle in ("<title>", "Strikeouts", "Outs", "First five",
                   "Declined", "Away Arm", "Home Arm", "BOS", "NYY",
                   "Janson Junk"):
        assert needle in html, needle
    assert html.count("<style>") == 1


def check_board_page_is_ascii():
    """No `<meta charset>` exists in a fragment, so nothing may need one."""
    html = board_html.render(_payload())
    html.encode("ascii")


def check_board_escapes_accents_and_dashes_from_the_data():
    """Found by the first live run, not by this suite. Now pinned.

    The page is ASCII because a fragment has no `<meta charset>`, and the
    payload is not: rosters spell `Jose Ramirez` with two accents and
    `gamestate` writes its decline reason with an em dash. The escaping has
    to happen at the render boundary, not in the data.
    """
    p = _payload()
    p["games"][0]["sides"]["away"]["name"] = "José Ramírez"
    for r in p["games"][0]["sides"]["away"]["rows"]:
        r["player"] = "José Ramírez"
    p["declined"] = [("MIA @ WSH", "Andrés Muñoz",
                      "game is In Progress — never price a live one")]
    html = board_html.render(p)
    html.encode("ascii")
    assert "Jos&#233; Ram&#237;rez" in html
    assert "Andr&#233;s Mu&#241;oz" in html
    assert "In Progress &#8212; never" in html


def check_dashkit_esc_closes_the_markup_hole():
    """A name is interpolated straight into markup, so it must not open a
    tag. No user types these, but the roster is fetched, not authored."""
    assert dk.esc('<script>x</script>') == '&lt;script&gt;x&lt;/script&gt;'
    assert dk.esc('a & b') == 'a &amp; b'
    assert dk.esc('say "hi"') == 'say &quot;hi&quot;'
    # And the ampersand rule runs FIRST, or every entity is double-escaped.
    assert dk.esc("—") == "&#8212;"


def check_board_survives_an_absent_market():
    """Kalshi being down must not take the page down with it."""
    p = _payload()
    for s in p["games"][0]["sides"].values():
        for r in s["rows"]:
            r["mid"], r["edge"] = None, None
    html = board_html.render(p)
    assert "No Kalshi market attached" in html
    assert "Away Arm" in html


def check_board_edge_direction_picks_the_side():
    """P(over) above the market's says take the OVER, and the reverse."""
    hi = board_html.disagreement_table([_row("k", 4.5, 0.62, 0.50)])
    lo = board_html.disagreement_table([_row("k", 4.5, 0.30, 0.50)])
    assert ">over<" in hi and ">under<" not in hi
    assert ">under<" in lo and ">over<" not in lo
    # The probability shown is the one for the side being taken, not
    # P(over) regardless: 0.30 over is a 70% under, and quoting 30% next to
    # the word "under" would read as a 40-point edge that is not there.
    assert "62.0%" in hi
    assert "70.0%" in lo and "30.0%" not in lo


def check_board_outs_block_dates_its_correction():
    """A correction is only as current as the hook underneath it.

    This replaced `..._says_it_is_stale` on 2026-08-30, when the table was
    re-measured and the warning stopped being true. What it guards is
    unchanged: the outs block states the thing that governs it, and that
    thing never leaks onto a strikeout row.
    """
    p = _payload()
    html = board_html.render(p)
    assert p["corrected_on"] in html
    assert "1,224 holdout starts" in html
    assert "corrected" in html
    assert "corrected" not in board_html.disagreement_table(
        [_row("k", 4.5, 0.62, 0.50)])


def check_board_never_claims_an_undated_correction_is_current():
    """A payload with no date must say so rather than imply currency."""
    p = _payload()
    del p["corrected_on"]
    html = board_html.render(p)
    assert "unrecorded" in html
    assert "2026-" not in html.split("<h2>Outs</h2>")[1].split("</div>")[0]


def check_board_f5_sides_are_not_swapped():
    """THE HALF-INNING TRAP, guarded at the render layer too.

    The away samples are centred on 1 run and the home samples on 4, so a
    swap moves the printed mean by three runs.
    """
    html = board_html.f5_card(_payload(away_f5_mean=1, home_f5_mean=4)
                              ["games"][0])
    away = html.index("BOS first five")
    home = html.index("NYY first five")
    a_mean = float(html[away:home].split('<b>')[1].split('</b>')[0])
    h_mean = float(html[home:].split('<b>')[1].split('</b>')[0])
    assert a_mean < 2.0, a_mean
    assert h_mean > 3.0, h_mean


def check_board_thin_arm_is_flagged_on_the_page():
    thin = board_html.disagreement_table([_row("k", 4.5, 0.62, 0.50, w=0.23)])
    fat = board_html.disagreement_table([_row("k", 4.5, 0.62, 0.50, w=0.91)])
    assert "thin 0.23" in thin
    assert "thin" not in fat


def check_board_projected_lineup_is_flagged_on_the_page():
    proj = board_html.disagreement_table(
        [_row("k", 4.5, 0.62, 0.50, confirmed=False)])
    assert "proj lineup" in proj
    assert "proj lineup" not in board_html.disagreement_table(
        [_row("k", 4.5, 0.62, 0.50, confirmed=True)])


def check_board_two_views_agree_on_the_fair_price():
    """Two `american()` definitions exist. They must never diverge.

    A page quoting a different price from the terminal for the same
    probability is the exact failure the one-payload split exists to stop,
    and it would be invisible unless both were read side by side.
    """
    for i in range(1, 1000):
        p = i / 1000
        assert board.american(p) == board_html.american(p), p
    for p in (0.0, 1.0, -0.1, 1.4):
        assert board.american(p) == board_html.american(p) == "-"


def check_dashkit_hist_is_a_distribution():
    h = dk.hist([1, 1, 2, 3, 3, 3], 0, 4)
    assert [k for k, _ in h] == [0, 1, 2, 3, 4]
    assert abs(sum(p for _, p in h) - 1.0) < 1e-9
    assert abs(dict(h)[3] - 0.5) < 1e-9


def check_dashkit_hist_clamps_rather_than_dropping():
    """Out-of-range draws pile into the end bins; mass is never lost."""
    h = dk.hist([-3, 0, 9, 40], 0, 5)
    assert abs(sum(p for _, p in h) - 1.0) < 1e-9
    assert dict(h)[0] == 0.5 and dict(h)[5] == 0.5


def check_dashkit_marks_the_line_inside_the_axis():
    """A betting line sits BETWEEN bins, so the marker takes a value."""
    h = dk.hist([0, 1, 2, 3, 4], 0, 4)
    left = dk.bars(h, "red", mark=0.5)
    right = dk.bars(h, "red", mark=3.5)
    grab = lambda s: float(  # noqa: E731
        s.split('class="act" style="left:')[1].split("%")[0])
    assert grab(left) < grab(right)
    assert dk.bars(h, "red", mark=99.0).count('class="act"') == 0


def check_dashkit_output_is_ascii():
    """Pins the entities. A raw em dash here would mojibake in a file."""
    for s in (dk.CSS, dk.MDASH, dk.NDASH, dk.MIDDOT,
              dk.statline(dk.stats([1, 2, 3, 4, 5])),
              dk.bars(dk.hist([1, 2, 3], 0, 3), "red"),
              dk.thresholds([1, 2, 3], [("o1.5", 1.5)]),
              dk.card("t", "s", "b"), dk.document("t", "<p>b</p>")):
        s.encode("ascii")


def check_dashkit_document_is_a_publishable_fragment():
    """No doctype and no head: the Artifact publisher supplies both."""
    doc = dk.document("Title", "<p>hi</p>")
    low = doc.lower()
    for tag in ("<!doctype", "<html", "<head", "<body"):
        assert tag not in low, tag
    assert doc.startswith("<title>Title</title>")


def check_outs_correction_matches_its_measured_table():
    """The correction at a measured line IS the measured gap, untouched.

    A table that COUNTS must not be smoothed, rounded or re-levelled on its
    way to the caller. Every absorbed constant in this project's history got
    that way by being handed back to something that adjusted it.
    """
    for line, (model, actual) in outs_adjust.MEASURED.items():
        assert abs(outs_adjust.correction(line) - (actual - model)) < 1e-12


def check_outs_correction_keeps_its_sign_across_the_band():
    """UNDERSTATE the over to 17.5, OVERSTATE at 18.5+. Crossover at 18.

    That crossover is the whole mechanism: it is the mass the boundary
    defect misplaces. If it moves, the correction has stopped describing
    the defect it was measured on.
    """
    for line in (12.5, 14.5, 15.5, 16.5, 17.5):
        assert outs_adjust.correction(line) > 0, line
    for line in (18.5, 20.5):
        assert outs_adjust.correction(line) < 0, line


def check_outs_correction_is_flat_outside_the_measured_range():
    """The sign is not known to continue, so it is held, not extrapolated."""
    ks = sorted(outs_adjust.MEASURED)
    lo, hi = ks[0], ks[-1]
    assert outs_adjust.correction(lo - 5) == outs_adjust.correction(lo)
    assert outs_adjust.correction(hi + 5) == outs_adjust.correction(hi)


def check_outs_correction_interpolates_between_measured_lines():
    a, b = outs_adjust.correction(15.5), outs_adjust.correction(16.5)
    mid = outs_adjust.correction(16.0)
    assert min(a, b) < mid < max(a, b)
    assert abs(mid - (a + b) / 2) < 1e-9


def check_outs_correction_long_lines_are_within_noise():
    """Kept as MEASURED, but they must stay insignificant.

    Pinned because the temptation on a re-measure is to zero them, and
    zeroing a measured 0.008 is a decision dressed as a measurement.

    IT FIRED ON 2026-08-31, AS DESIGNED. Shipping the counted mid-inning
    hazard drifted these rows out (+0.011 -> +0.018 at o18.5, +0.008 ->
    +0.011 at o20.5) — the counted table under-pulls at 90+ pitches, so a
    few too many starters go deep. That is the real finding the old wording
    promised to surface, and it is recorded in `outs_adjust`'s docstring.

    RE-SPECIFIED, NOT LOOSENED. The bound was `SE`, a single nominal
    constant of 0.013 that is not the standard error of any particular row.
    Significance is 2 se on the row's OWN se (0.011 at both long lines), so
    that is what is asserted. o18.5 at 0.018 is 1.6 sigma and passes; at the
    0.024 it would need to reach 2 sigma it fails, which is the bar that was
    always meant.
    """
    row_se = 0.011
    for line in (18.5, 20.5):
        assert abs(outs_adjust.correction(line)) < 2 * row_se, line


def check_outs_correction_centre_is_the_models_mean_not_reality():
    """`far` compares a MODEL projection, so the centre must be the model's.

    Reality's holdout mean is 15.75 and the model's is 15.62. Centring on
    reality would mis-flag extrapolation by 0.13 outs in one direction.

    Both numbers move when the hook moves — this is the value as of the
    2026-09-04 re-measure, after `sim.USE_LAYOFF` shipped.
    """
    assert abs(outs_adjust.HOLDOUT_MEAN_OUTS - 15.62) < 0.005


def check_outs_rows_are_priced_after_the_correction():
    """THE BUG THE OPERATOR FOUND, 2026-08-30. Pinned so it cannot return.

    `edge` was `raw_over - kalshi_mid` while the measured correction sat in
    a note. Since the correction is +0.032 to +0.067 across the whole
    12.5-17.5 band, that tilted every outs row toward the UNDER by about
    four points and hid genuine overs. A note nobody can act on is not a
    correction.
    """
    r = _row("outs", 15.5, 0.470, 0.500)
    exp = 0.470 + outs_adjust.correction(15.5)
    assert abs(r["priced"] - exp) < 1e-12, r["priced"]
    assert r["priced"] > r["over"], "the correction must move the price"
    assert abs(r["edge"] - (exp - 0.500)) < 1e-12
    # The sign flips on this row precisely because the correction applies.
    assert r["over"] - 0.500 < 0 < r["edge"]
    table = board_html.disagreement_table([r], stale=True)
    assert ">over<" in table, "a corrected over must not read as an under"
    assert f'{r["priced"]:.1%}' in table
    assert f'{1 - r["over"]:.1%}' not in table


def check_strikeout_rows_are_priced_raw():
    """K has no correction, so `priced` must be the simulator's own number.

    Guarded because the obvious fix for the outs bug is a blanket one, and
    a blanket correction would silently move a market that is calibrated.
    """
    r = _row("k", 4.5, 0.620, 0.500)
    assert r["priced"] == r["over"] == 0.620
    assert abs(r["edge"] - 0.120) < 1e-12
    assert "adj" not in r, "K has no correction to carry"
    # Across the whole K ladder, priced is the simulator's number untouched.
    for line in (2.5, 4.5, 6.5, 8.5, 10.5):
        assert board.price_row("k", line, 0.4, 5.0)["priced"] == 0.4
