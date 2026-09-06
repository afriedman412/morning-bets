# PLAN — baseball-logic improvements, written to be worked cold

Source: an external read of `sim.py`, `game.py`, `calibrate.py`, `rates.py`
and the docs on 2026-09-05. Every item below is a place where the state
machine is sound but never receives an input baseball has. All are COUNTS,
not fits. None is a betting-layer change.

`CLAUDE.md` binds. In particular: rules 3 (small and measured ships), 4
(count it, do not import it), 7 (a null is a claim), 12b (four folds), 13
(verify checks by mutation). Nothing here is admissible on a flat CRPS and
nothing here is rejected on one.

## HOW TO WORK THIS FILE

ONE ITEM PER SESSION. Item 0 is the battery and comes first; the rest are
ordered by runs per day of work and by dependency. Do not skip ahead. Before starting any item:

  1. `git status` clean. `venv/bin/python -m tests.run` green. Record the
     count.
  2. `venv/bin/python -m scratchpad.fingerprint 400 6`. Record the hash.
  3. Write QUESTION / HYPOTHESIS / TEST / EVALUATE / CONCLUSION / NEXT STEPS
     as literal headers in the session log BEFORE running anything, with
     the POWER and the STANDARD ERROR of the headline number stated in
     TEST, and the falsifier from the item copied in verbatim.

Every item after 0 starts with a battery run and ends the same way:

  * `battery.py --diff <pre-fingerprint>` reported in full — every row
    that moved, not just the target row.
  * A wiring check that fails if the mechanism is switched off, and a
    mutation that proves it (flip the constant, confirm THAT check fails).
  * The fingerprint moved, and the log says why. If it did not move, the
    mechanism is not live somewhere — find it before reporting anything.
  * If the hook was touched in any way: re-run `scratchpad/outs_adjust.py`
    in the same sitting. Twelve seconds.
  * No number reported from a dev-count run. `price.N_SIMS` and
    `tonight.py`'s 400 are not measurement settings. Ladders and fitf5
    use their own paired instruments; state which one and how many games.
  * Result written into `NOTES-context-layer.md` under a dated header, the
    item deleted here, the RESUME state block updated in the same commit.

The standing scoring instruments, and which one each item names:

    ladder.py / where_runs.py    prefix ladder F1/F3/F5/F7 against real runs
    fitf5.evaluate               F5 runs allowed, discrete CRPS, full support
    scratchpad/shape.py          per-start outs / K distribution on holdout
    scratchpad/hz_cells.py       hook cell rates against real holdout rates
    calibrate.paired_cases       the pairing; PASS season= for prior years

Holdout is 2026-07-01 for 2026 and the same calendar cut for prior seasons.
Fit on `date < cut`, score on `date >= cut`, per season, four folds.

---

## 0. THE BATTERY — one command, every table, before and after every item

DO THIS FIRST. Nothing below ships until this exists, because every item
below is scored on a row of it.

WHY: twenty days of one-defect-one-scratchpad means each session scores
the thing it built and nothing else. The fourth-inning defect and the
60-85 pitch defect were one defect with two instruments and it took days
to see. A fix in `apply_pa` moves the hook cells; a park change moves
traffic and therefore the hook; nothing today shows the side effect until
someone happens to run the other script. The battery makes every change
score against everything, the same afternoon.

STATUS: `scratchpad/battery.sh` and `scratchpad/scope_baseline.py` exist
and are most of the way there. This item consolidates, does not rebuild.

BUILD `scratchpad/battery.py`:

  * ONE simulation pass per fold, samples kept in memory, every table read
    off the same games — the `board.py` rule: one payload, many views, so
    the views cannot disagree. 40 sims a game, paired seeds, holdout
    2026-07-01+ and the matched cut in 2023-2025, four folds. State n, se
    and the noise floor on every row.
  * The rows, all model vs real with a gap and a z:
      - prefix ladder F1/F3/F5/F7, per inning 1-9+, one-run-game share,
        extras share (`ladder`, `where_runs`, `ninth`)
      - F5 and full team-total residual PER VENUE, sorted by |gap|
      - runs per baserunner, brought-home share, shutout and blowup
        shares, run-distribution mass at 0-3 and 8+ (`f5_decomp`,
        `dispersion`)
      - HR and K per batter split by platoon-advantage side; the
        stacked-lineup top decile residual
      - DP rate, sacrifice rate, XBH share: league level AND by pitcher /
        batter GB% quintile (quintile rows empty until item 4a plumbs
        `gb_pct`; print them empty, do not omit them)
      - HR per ball in play by temperature bucket (empty until item 5)
      - innings 7-9 runs allowed by |margin| at the start of the inning
      - hook cells, both curves (`hz_cells`); outs and K shape on the
        starter (`shape`); mean outs, boundary share, mid-share of each
        round-number spike (`outs_split`)
      - outs_adjust band corrections, current
  * Output: `scratchpad/battery_<fingerprint>.json` and a terminal dump.
    A `--diff <fingerprint>` mode prints every row that moved by more
    than one se against a previous run, and nothing else.
  * Runtime target under fifteen minutes on the machine it runs on; fork
    over games as `score_boundary` does. If it cannot fit, cut sims per
    game before cutting rows.

CHECKS: a wiring check that every `USE_*` flag in `sim`, `game` and
`calibrate` is printed in the battery header (so a run is never mis-
attributed to the wrong configuration), and a mutation that a flipped
flag changes the header.

THE RULE, added to CLAUDE.md in the same commit: every item in this plan
runs the battery at its start, commits the JSON with the pre-fingerprint,
runs it again at the end, and reports the DIFF — not just the row it was
aiming at. A change that moves an unrelated row by more than one se is
not done until the log says why. And the battery is what the session
reads when deciding what to work on next: "make this row go green" is
the item, not "build an instrument to see if it moved".

FALSIFIER for the battery itself: positive-control it. Inject a known
effect (halve `ADVANCE_3B_ON_OUT`, or double a park index) and confirm
the rows that should move do and the rows that should not do not. A
battery that cannot see a planted defect is not a measurement.

---

## 1. PARK — switch on with neutralised rates, score PER VENUE

STATUS: `calibrate.USE_PARK = False`, `calibrate.NEUTRALISE_PARK = False`.

ESTABLISHED (NOTES "Park factors — the double-count, and the fix"): raw park
on raw rates double-counts because a player's line is half earned at home;
`rates.park_exposure` / `rates.neutralise` divide each rate by the
usage-weighted park it was accumulated in; neutralise-then-apply was the
best of three configs at n_sims=110 and was parked at +0.34pp because that
was under the detection floor on POOLED prop Brier.

WHY THE OLD TEST CANNOT SEE IT: a park effect is signed per venue and nets
to zero across thirty of them. A pooled ladder at F5 -0.047 over 1,645
games says nothing about Coors. The quantity to score is the per-venue
residual on team totals.

BLOCKER TO CLEAR FIRST: `fitf5.evaluate` cannot take a park (TODO item 9
records this). `price.simulate_slate_game` already passes
`calibrate.park_for(g["venue_id"])`. Thread `park` through
`calibrate.replay` / `paired_cases` / `fitf5.evaluate` / `ladder` the same
way `team` and `date` were threaded on 2026-08-25, and add the call-site
check (`check_every_replay_passes_a_park`, same shape as
`check_every_build_side_call_passes_team_and_date`). An omitted park must
resolve to NEUTRAL and be counted as a coverage miss, never to the home
club's park — Mexico City, Athletics' unrated sites.

TEST:
  * Coverage first: print the share of holdout games with a rated
    `venue_id` before reading any score. Rule 3 from RESUME.
  * Per-venue mean residual (model - real) on FULL team total and on F5
    team total, holdout 2026-07-01+, 40 sims a game paired, three
    configs: off / raw / neutralised. Report all thirty venues with n and
    se, sorted by |residual|.
  * Four folds (2023-2026, same cut), per rule 12b.
  * League-wide ladder as the control: it should NOT move outside noise.
    If it does, something else is on.

FALSIFIER, pre-registered: neutralised park does not reduce the
sample-size-weighted mean |per-venue residual| in at least three of four
folds, or it moves the league ladder by more than one se. Either kills it.
PREDICTION: Coors is the largest residual off and the largest correction
on; Oracle/Petco/T-Mobile move the other way.

DO NOT: solve for a multiplier that makes any venue land. Savant's index,
neutralised, is the count. If a venue still sits out, record it as a
missing mechanism (altitude on breaking balls is not a HR index) and move
on.

SHIP: both flags on, checks in, fingerprint moved, `outs_adjust`
re-measured (park changes traffic, traffic reaches the hook).

---

## 2. GIDP ADVANCEMENT and STATE-BLIND SACRIFICES — one function, two fixes

Both live in `sim.apply_pa`. Both are signed toward "men reach base and do
not come home", which `f5_decomp.py` measures at -1.7%.

### 2a. On a double play nothing else moves

`apply_pa`, `o == OUT` branch: `bases[0] = False; fr.outs += 2`. The runner
on third with nobody out scores on most 6-4-3s; the runner on second
usually takes third. The model freezes both. Also `False` is written into a
list that otherwise carries runner tokens or `None`.

COUNT IT: from play-by-play (`pbp.plays()` gives base-out state before
every play), for every GIDP with outs_before in {0, 1}: P(runner on 3B
scores), P(runner on 2B reaches 3B). Key on outs_before, same as
`ADVANCE_*_ON_OUT`. Stability gate across four seasons as `state_seasons.py`
does it; if the gate fails, the pooled number stays.

WIRE: on the DP branch, apply the counted movements lead-runner-first
through `_credit`, tokens not booleans, and use `None` for the vacated bag.
Third-out rule still holds: a DP that makes the third out scores nobody.

### 2b. Sacrifice drawn regardless of state

`pa_from` rolls `mu.sac` first, unconditionally. Bases empty or two out the
draw becomes a pure out with no BABIP roll; in real sac states the rate is
correspondingly light. It just gained a per-arm rate through
`USE_ROLE_HBP`, so the mis-specification is now per arm.

COUNT IT: sacrifice (SH + SF) share of PA by (men on, outs) cell on the
same 748,905-PA scan behind `STATE_MULT`. Expect ~0 with bases empty and
with two out.

WIRE: a `sac_pct` column on `STATE_MULT`, applied as the plain multiplier
`hbp_pct` uses, with `cond` renormalised alongside it exactly as the HBP
branch does. `SAC_RATE_SP` / `SAC_RATE_RP` stay as the level; the cell
table redistributes it. PA-weighted mean of the multipliers must be 1.000
— same rule as `TTO_MULT`.

TEST for both: `f5_decomp.py` runs-per-baserunner and the "brought home"
share; the shutout share and the distribution shape per rule 2; overall
sacrifice rate and DP rate unchanged at the league level (they are
redistributed, not re-levelled). Positive control: double the 3B-scores
rate and confirm the harness sees it.

FALSIFIER: runs per baserunner does not move toward real, or the league
sacrifice / DP rates move by more than one se.

---

## 3. PLATOON — the LEAGUE cell, as an odds multiplier

STATUS: `calibrate.USE_HANDEDNESS = False`. `BatterRates.side`,
`BatterRates.lg_cell`, `PitcherRates.vs_side` exist and are inert.

ESTABLISHED (NOTES day thirteen, `scratchpad/platoon_league.py`): four
cells counted on ~754k PA —

    bat/pit        K%      BB%      HR%    BABIP
    R vs R      0.2296   0.0878   0.0298   0.2954
    R vs L      0.2205   0.0954   0.0312   0.3027
    L vs R      0.2187   0.1067   0.0325   0.2955
    L vs L      0.2387   0.0939   0.0240   0.2973

— and the full matchup construction (individual splits shrunk toward the
cell, pitcher vs side) scored FLAT on start-level K/BB/HR/H marginals.

WHY THAT NULL DOES NOT SETTLE IT: nine mixed hands average the effect away
in a start-level marginal by construction. The `USE_HANDEDNESS` docstring's
argument — the manager stacked his lineup so the effect is "expressed in who
is batting" — is a selection argument about WHO bats, not a rate argument
about what happens when he does. The left-handed bat who stays in against
the lefty still loses 26% of his home run rate.

BUILD THE SIMPLE VERSION ONLY: the league cell ratio, applied through
`odds_mult` the way `STATE_MULT` is, keyed on (batter side, pitcher hand).
No individual splits — their reliability is the noisy half and was the
defect in every earlier attempt. Switch hitters resolve to the side they
bat from against this hand. Ratios centred so the PA-weighted mean over
the real hand mix is 1.000 per channel.

TEST — score where the effect lives, not where it cancels:
  * Per-batter attribution: HR and K by batter, split by whether he had
    the platoon advantage, model against real, holdout.
  * Stacked starts: the top-decile of starts by lineup platoon-advantage
    share (mostly RHB vs LHP), team-total residual off vs on.
  * Start-level marginals as the CONTROL: they should stay flat. That is
    the prediction, not a failure.
  * Four folds.

FALSIFIER: per-batter HR / K residual by advantage side does not shrink,
or the stacked-decile residual does not move toward zero, in three of four
folds.

DO NOT re-run the individual-split construction. Do not fit the cells.

---

## 4. BATTED-BALL PROFILE — GB% into double plays and hit mix

STATUS: nothing in the model reads GB%/FB% for hitter or pitcher.
`gidp_rate` keys on outs only; `hit_mix` is `lg["hit_mix"]` for every
pairing; pitcher BABIP is shrunk to 3,068 PA (league), so a pitcher's
contact suppression enters through HR% alone.

This is two or three sessions. Split it and ship each half on its own
count.

### 4a. Plumbing
Savant is already fetched (`sources/savant.py`). Carry `gb_pct` on
`BatterRates` and `PitcherRates`, shrunk with a constant MEASURED by
`stabilise.py`'s method (expect it to stabilise fast — it is among the most
reliable per-player rates). Inert until a table reads it; fingerprint must
not move. Check it as plumbing.

### 4b. Double plays by GB%
COUNT: DP rate per opportunity (man on first, <2 out, ball in play that is
an out) by pitcher GB% quintile and by batter GB% quintile, from
play-by-play. Combine as a log5-style odds construction against the league
DP rate — the same shape `resolve` uses for every other channel — not as a
product of two multipliers.
WIRE: `gidp_rate(outs)` becomes `gidp_rate(outs, mu)`.
TEST: DP count per game unchanged at league level; DP rate by pitcher
quintile model vs real on holdout; positive control by injection.

### 4c. Hit mix by GB%
COUNT: 1B/2B/3B share of hits by batter GB% quintile and by pitcher GB%
quintile. `hit_mix` is already a field on `Matchup`; TODO's parked note on
per-hitter hit mix says impute it from power — GB% is the other half of
that.
TEST: XBH share per game unchanged at league level; per-quintile share on
holdout; F5 CRPS as the control, expected flat.

FALSIFIER for 4b/4c: the per-quintile model-vs-real gap does not shrink
across four folds, or the league-level DP / XBH rates move.

---

## 5. WEATHER — temperature and wind carry into the HR channel

STATUS: `sources/weather.py` fetches temperature and parses wind into a
carry term. Nothing in `sim`, `game`, `calibrate` or `price` reads it.
The month-keyed seasonal HR term (TODO item 9, `month_league.py`) is a
proxy for this and is not portable across seasons or venues.

COUNT: HR per ball in play by game temperature bucket (10°F bins) and by
wind carry bucket, on the four cached seasons joined to the weather cache.
Coverage first — print the share of games with a temperature. Gate for
stability across seasons.

WIRE: a temperature multiplier through `odds_mult` on `m_hr`, applied at
`resolve` time next to `hr_park`, centred so the season-wide mean is 1.000.
This SUPERSEDES the month term; do not ship both. If the month term still
explains residual after temperature is on, that residual is humidity or
the ball and gets its own note.

TEST: HR per BIP by temperature bucket, model vs real, holdout; the
July/August F5 residual as the number this was originally hunting.
FALSIFIER: the per-bucket gap does not close, or the April/May side gets
worse.

---

## 6. BULLPEN EXPOSURE — best available arms in a close game

STATUS: `build_side` draws eight arms weighted by appearances;
`next_arm` walks them in draw order. Reliever quality is independent of
score. TODO item 8 has the measurement: oracle ceiling 0.618 runs, ~0.6 of
it is WHICH arms are exposed.

THE RULE IS DECIDED, do not build a leverage index: from the seventh
inning, when |margin| <= 2, the next arm is the best available by a
measured quality rank (K% - BB%, or whatever `deploy.py` found projects);
otherwise draw order as now. "Available" is the existing `pen_state`.

COUNT FIRST: from `deploy.py` / `mlb_stints`, P(top-3 arm appears | inning
>= 7, |margin| <= 2) against P(top-3 arm appears | blowout). That is the
number the rule has to reproduce.

TEST: innings 7-9 runs allowed split by |margin| at the start of the
inning, model vs real, holdout; one-run-game share (real 0.266, model
0.247 as of 2026-08-30); F7 and full-game ladder; F5 as the control (must
not move — nothing before the sixth is touched).
FALSIFIER: close-game late-inning runs do not move toward real, or F5
moves.

---

## OUT OF SCOPE HERE, RECORDED SO THEY ARE NOT LOST

Found on the same read; they are measurement hygiene, not baseball, and
each is its own session:

  * The base boundary curve (`Hook.intercept`, `pitch_scale`, `per_run`,
    `per_inning`, `per_baserunner`) and the `late_mid_*` coefficients were
    fitted 2026-08-26 on 2026 through that date — inside the holdout — and
    `fit_boundary.py` / `fit_midinning.py` have no `train_only`. A joint
    refit on four-season training rows, compared coefficient by coefficient
    to what ships, closes this and item 7 in TODO at once.
  * `HOLDOUT` is a string literal in ~25 scratchpads and `train_only` is
    defined six times. One `src/context/holdout.py`, imported everywhere,
    and a check that greps for the literal.
  * `sim.leash` loads `hook_leash.json` without reading `_meta.before`;
    it is a residual against a model the hook has changed under five times
    since. Rebuild it after every hook ship, and have the loader refuse a
    file built on a stale fingerprint.
