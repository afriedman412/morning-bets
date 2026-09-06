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

ONE ITEM PER SESSION. Shipped so far: the battery (item 0, 2026-09-05),
PARK (item 1, 2026-09-05), GIDP advancement (2a, 2026-09-06), PLATOON
(item 3, 2026-09-06 — `sim.USE_PLATOON`, per-batter falsifier 3/4 folds,
2026 on all rows). Item 2's sac table is PARKED below. Every remaining
item is scored on battery rows, ordered by runs per day of work and by
dependency. Do not skip ahead. Before starting any item:

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

## 2. SACRIFICES BY STATE — PARKED 2026-09-06, blocked on occupancy

(2a, GIDP advancement, SHIPPED the same day — `sim.USE_GIDP_ADVANCE`.)

ESTABLISHED: the counted table is done and maximally stable (sac share
by (men on, outs), between-season correlation 0.994, exactly 0.0000 at
two out everywhere, 14-15x bases loaded; `scratchpad/gidp_sac_count.py`).
The `pa_from` wire is live and bit-inert behind the `sac_pct` key.

WHY IT IS PARKED: the pre-registered falsifier fired on the LEVEL
control — realized league sac rate fell x0.9639 because the model
under-occupies the extreme-traffic cells the multipliers are largest in
(bases loaded 0.32% of model PAs vs 0.42% real). That is the CLUSTERING
defect, measured at new resolution, not a defect of this table.

RE-OPEN when clustering/occupancy moves, or with an explicit decision
that the level-through-occupancy is the honest projection. DO NOT
re-centre the table on model occupancy — that absorbs the defect.

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
