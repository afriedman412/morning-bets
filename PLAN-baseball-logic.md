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
2026 on all rows), GB plumbing (4a, 2026-09-06), DP-by-GB (4b,
2026-09-06 — `sim.USE_GB_DP`; tables corrected same day for covariate
leakage, see 4c), hit mix by GB (4c, 2026-09-06 — `sim.USE_GB_HITMIX`,
XBH quintile gap shrank in all four folds, both levels held). Item 2's
sac table is PARKED below. Every remaining
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

### 4a. Plumbing — SHIPPED 2026-09-06

Counted from the pbp cache (`sources/battedball.py`), NOT fetched:
Savant is season-to-date and would hand prior folds the future. Shrunk
by measured constants (bat k=111.9, pit k=76.8 — `gb_stabilise.py`).
Inert, fingerprint unchanged, quintile rows live in the battery: model
DP flat vs real 0.224->0.286 by pitcher quintile (q5 -3.9 sigma); model
XBH flat vs real 0.273->0.228 by batter quintile (q5 +4.4 sigma).

### 4b + 4c. DP and hit mix by GB% — SHIPPED 2026-09-06

`sim.USE_GB_DP` and `sim.USE_GB_HITMIX`, both log5 odds constructions
validated on their 25-cell crosses, both counted with the covariate
STRICTLY PRIOR to the outcome rows — 4c's scoring run caught the first
count binning rows inside their own covariate window, which inflated
both slopes (~2x on XBH) and is the portable lesson: an overlapping
window smuggles the outcome into its own conditioning and the era gate
cannot catch it. Falsifier clean on the corrected tables: XBH quintile
gap shrank in all four folds, DP pooled best of the three states, both
levels and everything else in the battery held. Full result in the
notes.

---

## 5. WEATHER — SHIPPED 2026-09-06 (`sim.USE_TEMP_HR`)

Counted within venue and centred on climate — the first battery run
rejected the first table twice, both specification fixes (the pooled
count confounded park, which the engine applies separately; spring
centring double-counted the seasonal air already in the baseline
rates). Level rows returned to zero in the clean folds as predicted;
2026-H2's hot side stays high, co-located with the pre-existing
dead-ball anomaly — one cause, two instruments now. Wind counted
(x0.90 in / x1.06 out), recorded, waits for its own item. Full result
in the notes.

---

## 6. BULLPEN EXPOSURE — SHIPPED 2026-09-06 (`game.USE_PEN_ROLES`)

The count REFUTED the decided rule before it was built: real
P(best remaining | close) is 0.18-0.23 vs the draw order's natural
0.157 — deterministic best-arm would overshoot 5x — and the real
defect was the blowout side (0.084; good arms are SAVED). Shipped the
whole counted selection profile instead, signed by margin (lead 44%
top-fifth, trailing near-flat, blowout leans to the bottom), drawn per
entry from inning seven. Battery flat everywhere, which is the
predicted result at the counted effect size (~0.01 runs/late inning vs
pooled se 0.025); ships on rule 3. THE SURVIVING FACT: the late-inning
margin gaps are NOT deployment — the oracle ceiling in TODO item 8 is
not reachable through selection; what remains is clustering's
late-inning face. Full result in the notes.

---

## 7. WIND INTO THE HR CHANNEL — SHIPPED 2026-09-06 (`sim.USE_WIND_HR`)

Counted within venue AND net of the shipped temperature table (0.924 /
1.000 / 1.043), climate-centred, three bins — five is worse and the
notes say why. The prediction registered before the run was right:
about half temperature's size. The confound was decomposed rather than
asserted (park 16% of the raw spread, temperature 6%).

THE PRE-REGISTERED ORDERING GATE FAILED AND THE ITEM SHIPPED ANYWAY,
on the user's call and not the session's: 2026 inverts by 0.007
against a difference se of 0.043, so the clause cannot resolve what it
is testing. The A/B (flag off, identical stream) closed the wind gap
in 3 of 4 folds and moved FIVE rows out of 687 — all five its own.
What makes that admissible and not rationalisation: nothing was
rescaled after seeing a score. Full result, and the precedent, in the
notes.

---

## 8. CLUSTERING — rallies; the biggest known defect, now with
## instruments. DO NOT SHIP ANYTHING FROM THIS ITEM ON A FLAT DIFF
## WITHOUT READING THE TRAPS.

THE DEFECT (measured, CLAUDE.md carries it): reality has more shutouts
AND more blowups; the model bunches in the middle. Real PAs arrive
together; the model's resolve independently. Runs are convex in
clustering so the thin tail also drags the mean. THREE INSTRUMENTS NOW
STAND: traffic/mass rows (battery), sac-table occupancy (bases loaded
0.32% model vs 0.42% real — plan item 2's parking note), late-inning
runs by margin (+2.5 sigma pooled at margin 1, survives pen roles).

DEAD ENDS, do not re-run: per-pitcher/per-club dispersion (split-half
0.07, powered to 0.32); a flat dispersion term (closed 44% of shape /
86% of level but is calibration-not-discrimination — PARKED, and
re-opening it is a DECISION for a human, not a session).

### 8a. COUNT within-inning feedback — RESOLVED 2026-09-06: NULL AT THE
### REGISTERED BAR. Nothing wired. Full result in the notes.
The count ran as written (`scratchpad/inning_feedback.py`, 398,605
pre-July PAs, four seasons) and twice caught its own specification:
the registered traffic binning failed its positive control (occupancy
floors traffic once inherited runners are excluded — an injected
x1.100 read back as 1.008; SURPLUS = traffic - men on is the
identifiable coordinate, and a step at traffic >= 1 is already inside
STATE_MULT), and half the apparent k effect was times-through-the-
order, removed by a batters-faced standardiser verified with its own
confound control. What is left: k 0.979/0.971 at 1.9 se per bin
(under the 2-se gate), bb 1.4 se, babip 1.5 se. The positive control
bounds a true hit-side gradient below ~x1.03 per runner. Re-open only
with a 2022 pbp backfill or a pre-registered trend test; the k/bb
contact near-miss is recorded in the notes and is under the leverage
floor regardless.

### 8b. Shared-night conditions — UMPIRE COUNTED 2026-09-06, SURVIVES
Temperature and wind shipped. The plate umpire is COUNTED and passes
both registered gates (`scratchpad/ump_kbb.py`, full result in the
notes): k tau 0.0176 / split-half +0.352, bb tau 0.0438 / +0.454,
season-pair r +0.204/+0.323 over 211 pairs. Walks are the channel —
2.5x the k spread. THE WIRE IS THE OPEN STEP, falsifier registered in
the notes before building: shrink per-umpire mults toward 1.0 against
tau (stabilise arithmetic), thread a per-game (k, bb) pair through
`simulate_game` like `hr_air`, join `game_officials` in replay; A/B
must move only K/BB rows, move the K shape and walk traffic TOWARD
real in >= 3 of 4 folds, hold the run level inside one se. Slate-time
crew availability is its own check before the live path reads it.

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
