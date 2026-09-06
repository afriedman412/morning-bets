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

## 7. WIND INTO THE HR CHANNEL — written for a cold session

Temperature's mirror; the counted numbers already exist (in 5+ mph
x0.896, out 5+ x1.063, `scratchpad/temp_hr.py` wind section). Follow
item 5's shipped shape EXACTLY — every trap below cost a battery run:

  COUNT: extend `temp_hr.py`'s WITHIN-VENUE section to wind bins
  (in 5+/calm-cross/out 5+, open air only; roof_closed games are
  carry=0 by definition and must sit in calm). The pooled ratios above
  are NOT shippable — hot/windy games concentrate in particular parks
  and park is already applied separately (the item-5 lesson).
  CENTRE ON CLIMATE, not the training window: reference = mean raw
  multiplier over prior seasons' full-year wind distribution (the
  1.0191 analogue). Era gate per season; if the three bins do not hold
  ordering in all four seasons, PARK the item and write why.

  WIRE: multiply into the SAME game-level `hr_temp` value (rename it
  `hr_air` everywhere in one commit, or leave the name — decide once).
  It rides `simulate_game(hr_temp=...)` -> both Sides -> the `hr_park`
  slot. There are FIVE callers: `calibrate.replay` (via
  `temp_mult_for`), `fitf5`, `ladder`, `slate`, and
  `scratchpad/fingerprint.py` — the AST check covers src/ only, so
  CHECK THE FINGERPRINT MOVED or the fifth caller is sitting still
  again. Silent-neutral: no reading contributes exactly 1.0.

  TEST: battery weather rows (add wind-bin rows next to the temp
  ones, model vs actual HR/BIP); level control `contact/hr_per_bip`
  must stay within one se per fold — if it lifts, the centring
  reference is wrong (the item-5 signature).
  FALSIFIER: the per-bin gap does not close across folds, or the
  hr_per_bip level moves past one se in the clean folds (2023/24 —
  2025/26 carry the dead-ball anomaly, see the notes).

  PREDICT BEFORE RUNNING: expected effect is ~half of temperature's;
  the wired slope may read steeper than holdout reality in 2026-H2 for
  the dead-ball reason, NOT a table defect. Do not rescale the table
  to fix 2026 — that is solving for a level on scored rows.

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

### 8a. COUNT within-inning feedback (a session-sized, safe first step)
QUESTION: is the league worse at preventing the NEXT event once
traffic is on in the SAME inning, beyond what (men on, outs) state
multipliers already carry? Physics candidates: pitching from the
stretch, defence holding runners.
COUNT: from pbp, per-PA rates (k/bb/h1/xbh/hr) conditioned on
baserunners allowed SO FAR THIS INNING by the SAME pitcher (0/1/2+),
WITHIN (men on, outs) cells — the state table already conditions on
occupancy, so the count must hold state fixed or it re-counts
STATE_MULT (rule 10: name the denominator). Pre-July rows, four
seasons, era gate. TRAP: the covariate (traffic so far) contains the
outcome's own PA sequence — this is the 4b/4c leakage class. Condition
on events STRICTLY BEFORE the current PA (they are), and positive-
control the harness by injecting a known feedback into simulated
innings and confirming the count recovers it.
WIRE (only if the count survives): a multiplier keyed on
(inning-traffic-so-far) applied in `pa_from` next to the state mult,
centred over REAL cell weights — NEVER model occupancy (that absorbs
the defect; it is why item 2 parked).
TEST: battery traffic/mass rows, sac occupancy (re-open item 2's table
if occupancy moves), late-by-margin, shutout/blowup shares. F5 CRPS
expected FLAT (rule 2 — a flat CRPS is not a rejection here).
FALSIFIER: the extreme-traffic occupancy cells do not move toward
real across four folds, or the run LEVEL moves past one se.

### 8b. Shared-night conditions (only after 8a resolves either way)
Temperature was the first (shipped). Candidates in order: umpire zone
(one man, both clubs, whole game — count K/BB by plate umpire from
pbp officials data if cached), wind (item 7). Each adds BETWEEN-GAME
variance, which fattens both tails without touching within-game
independence.

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
