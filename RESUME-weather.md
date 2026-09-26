# RESUME — WEATHER

Everything the engine knows about the air, what was counted on
2026-09-20, and the one constraint that decides whether any of it is
worth more work. Read `CLAUDE.md` first; this assumes its rules,
especially 4 (count it, do not import it), 6 (the holdout), 7 (a null is
a claim) and 15 (the battery).

**STATE (2026-09-26): THE BINDING CONSTRAINT IS FIXED, AND THE TWO
REMAINING COUNT ITEMS ARE BOTH DEAD.** Section 4 said coverage, not
counting, was the bottleneck. It was right, and it is closed: the board
now reads statsapi first and falls back to an Open-Meteo hourly forecast
per game. Board-time coverage went from 6 of 15 games to 16 of 16.

* **Coverage, the actual fix.** Two bugs, not one. statsapi fills a
  slate in START-TIME ORDER, and `fetch_date` froze a date's cache as
  soon as ANY game carried a temperature — so the 1:05 game locked the
  file and every night game stayed blank. 2026-09-19 to -23 ran
  4/15, 6/15, 1/15, 1/16. `backfill`'s skip-list had the identical
  half-fix (`sum(temp_f is not null) > 0`), so a partial date could
  never heal. Both now key on COMPLETENESS. Since the fix every date is
  full, and 09-19 through 09-23 were healed retroactively.
* **`fetch_live` is the board's entry point and `backfill` must never
  use it.** Every shipped table was counted on statsapi OBSERVATIONS,
  so a forecast belongs in tonight's price and not in `mlb_weather`.
  A forecast also only ever fills a game that has NOT STARTED — once
  the first pitch is thrown the conditions are being observed, and
  unknown state counts as started.
* **The orientation table exists and was DERIVED, not typed.** 27 parks,
  off ~7,000 nights where we hold statsapi's field-relative label and
  Open-Meteo's compass bearing for the same hour. Eight independent
  routes pin each park and their agreement is the validation; wind is
  gated on it, so six parks including Coors (R 0.39) get temperature
  only rather than a guessed direction.
* **Source mismatch measured, and it is not a problem for temperature.**
  Open-air, n=2,151: temperature corr 0.942 at +0.56F bias — nothing
  against the bin widths, so `TEMP_*` takes Open-Meteo with NO recount,
  which was supposed to be the expensive half of the source item. Wind
  is weaker (corr 0.563, statsapi 6% high) and is rescaled.
* **PRECIPITATION IS DEAD** — section 5, rewritten. 1,501 wet games on
  continuous millimetres against the old 96 categorical, flat on every
  channel, every era gate negative. The old 0.805 was a COLD CONFOUND.
* **WIND BEYOND HR IS DEAD** — old item 4. K spans 0.015 (era 0.29),
  BB spans 0.013 (era -0.02), against `hbp`'s 0.103 that was rejected
  on the era gate alone.
* **Both nulls carry the prescribed positive control.** Temperature run
  back through the precip pipeline reproduces the HR row at 0.7650
  against section 3's independently counted 0.7651, era 0.89.

Still open, and now the only weather item: the shipped `TEMP_BB_MULT`
<55F cell reads about half too big (below). It is a change to a shipped
constant, so it owes the battery a diff across all eight folds.

**STATE (2026-09-20, second sitting): RULE 15 IS CLOSED ON THE K AND BB
TABLES, AND THEY STAY ON.** Full entry in `NOTES-context-layer.md`
under this date. What it found, in order:

* **The replay path was a stub.** `calibrate.temp_kbb_for` returned
  neutral on both branches and never read the weather row, so the
  live board applied the tables while the battery, ladder and fitf5
  were blind to them — the exact failure the section below warns
  about. Two checks in `tests/test_game.py` were red against it and
  had never been run. Fixed; the engine fingerprint is `56c56687b554`
  flags-on and `432ed646d830` flags-off.
* **The battery had no walk row and could not see the BB table.** Built
  `battery.temp_cells` and the rows `weather/k_pa_all`, `bb_pa_all`,
  `k_pa_temp_<bin>`, `bb_pa_temp_<bin>`. Baseline re-run reproduces all
  884 prior rows exactly.
* **Diff:** no pre-existing row moved beyond one se. The K shape across
  the hot bins (85+ minus 65-74, relative to the fold's own level)
  went +14.5 / +6.3 / +4.7 / +5.3 -> +9.0 / +0.6 / −1.0 / +0.1 ×1000
  K/PA. The 85+ walk surplus went from combined z +2.0 to −0.3.
* **The cold half is now scored, in sample** (third sitting, same day).
  `--spring` adds four folds cut April 8, scored to June 30. Under 55F
  the K cell reproduces the count end to end (model −8.6 ×1000 K/PA
  flags off, −1.4 on); the BB cell OVERSHOOTS by about half its size
  (−5.3 off, +4.5 on, combined z −2.5 -> +2.1) — noted, not re-scaled,
  the cell to watch on any recount. `TEMP_HR_MULT` holds in the cold.
  Every spring game was in the training window, so this is
  reproduction, not validation.
* **Precipitation rows exist now** (`weather/*_wet`, `*_dry`): 46 wet
  games across eight folds. Model makes ~12% too many HR in the rain
  (z 1.4, same sign as the hand count's 3.1 se); K, BB and runs a game
  unresolvable. Still needs the continuous source.
* **The spring folds found two non-weather defects**, both > 3 se and
  absent in summer: starters pulled too early in spring 2023-24, and
  spring 2026 under-scoring every ladder rung off a stale prior-season
  anchor. `TODO.md` item 38.
* **A level error outranks all of this:** the model is ~2.5% light on
  strikeouts fold-wide in 2024-25 (`k_pa_all` −3.7 / −3.2 se), every
  arm. Not a weather item; it belongs in `TODO.md`.

The change is still uncommitted, alongside the unrelated board work.

---

## 1. WHAT IS SHIPPED

All of it lives in `src/context/sim.py` and is silent-neutral: a missing
reading, or the flag off, contributes exactly 1.0.

| table | channel | flag | status |
|---|---|---|---|
| `TEMP_HR_MULT` | home runs | `USE_TEMP_HR` | shipped, scored |
| `WIND_HR_MULT` | home runs | `USE_WIND_HR` | shipped, scored |
| `AIR_HR_PIT` | home runs | `USE_AIR_HR` | shipped, scored |
| `TEMP_K_MULT` | strikeouts | `USE_TEMP_K` | shipped, scored 2026-09-20 (hot half only) |
| `TEMP_BB_MULT` | walks | `USE_TEMP_BB` | shipped, scored 2026-09-20 (hot half only) |

Values, on the shared `TEMP_HR_EDGES = (55, 65, 75, 85)`:

```
              <55    55-64   65-74   75-84    85+     era gate
TEMP_HR_MULT  0.7983 0.9464  0.9639  1.0531  1.1153   0.92
TEMP_K_MULT   1.0350 1.0063  1.0072  0.9931  0.9802   0.73
TEMP_BB_MULT  1.1119 1.0243  1.0069  0.9804  0.9647   0.95
```

Cold adds strikeouts and walks and removes home runs. Heat does the
reverse. The channels disagree in direction on purpose — that is the
physics, not a sign error.

### Where they enter

Two paths, and BOTH must be wired or the change is invisible:

* **live** — `slate.py`, just after `hr_air`. Multiplies into the
  `ump` tuple.
* **replay** — `calibrate.temp_kbb_for`, multiplied into `ump` inside
  `replay`. Every scored thing (battery, ladder, fitf5) comes through
  here.

**THE FAILURE THIS ALMOST SHIPPED:** wired to `slate.py` only, the
mechanism reaches the live board and nothing else, so the entire
scorecard reads flat and the change gets reported as inert while
genuinely working in production. `check_replay_actually_applies_the_
temperature` in `tests/test_game.py` is the guard, and it is
behavioural (it intercepts `simulate_game`) because the first version
tested `temp_kbb_for` in isolation and a mutation that deleted the
multiply inside `replay` left it green.

K and BB ride `Side.ump_kbb`, the shared night rail that already
carried the plate umpire. The field name predates the second passenger.

---

## 2. THE METHOD — copy it, do not invent one

`scratchpad/temp_k.py` and `scratchpad/temp_hr.py` both do this. Any
new weather table must:

1. **Count WITHIN VENUE** (indirect standardisation — observed over
   that venue's own baseline). Pooled counts confound air with park,
   and the engine applies park separately. The pooled version of the K
   table read 0.864 at Coors, which is mostly altitude. Within-venue
   dropped the whole effect from ~8% to 5.5%.
2. **Climate-centre**, on the PRIOR seasons' full-year temperature
   distribution — not the training window. Baseline rates already carry
   an average season's air; centring on spring re-adds the summer
   premium as a level shift. (K reference came out 0.9996.)
3. **Train on `date < HOLDOUT`** (2026-07-01), imported from
   `src/context/holdout.py`.
4. **Pass an era gate** — season-to-season shape correlation. This is
   what rejected two channels below.
5. **Keep the dome as a control.** Conditioned air is league air, so
   closed-roof cells should show no gradient. K's dome row came back
   1.041 / 0.974 / 1.001 / 1.000 / 1.053 — noisy but with none of the
   monotone decline the open-air row has, which is the control passing.
6. **Reuse `TEMP_HR_EDGES`, do not search for bins.** Choosing edges
   after seeing the outcome is fitting a shape to noise.

Run it: `venv/bin/python -m scratchpad.temp_k [--all] [--vs-month]`

---

## 3. WHAT WAS COUNTED ON 2026-09-20

7,907 open-air games, 598,773 plate appearances, before the holdout.
Every channel `resolve` multiplies, not just the one that prompted it:

```
channel     den      <55    55-64    65-74    75-84      85+    range    era
k            pa   1.0350   1.0063   1.0072   0.9931   0.9802    0.055   0.73
bb           pa   1.1119   1.0243   1.0069   0.9804   0.9647    0.147   0.95
hr           pa   0.7651   0.9233   0.9639   1.0517   1.1253    0.360   0.93
hbp          pa   0.9590   0.9781   0.9669   1.0214   1.0624    0.103  -0.03
h_on_bip    bip   0.9942   0.9908   0.9968   1.0033   1.0111    0.020   0.11
```

**The HR row is the control and it validates the pipeline.** Counted
blind it lands at 0.765 → 1.125 against the independently counted
shipped table's 0.798 → 1.115. A pipeline that reproduces a known
answer is measuring air rather than manufacturing tables. If you change
the method, re-run this row first and check it still does.

**Two channels were REJECTED on the era gate alone.** `hbp` spans
0.103 — larger than the strikeout effect that started all this — and
would have shipped on size. Its shape does not survive to the next
season (−0.03), so that span is one season's noise. `h_on_bip` is both
tiny and non-repeating. **Size is not evidence; repeating is.**

**Temperature is NOT redundant with month.** Checked before shipping,
not after. Counted within venue AND month the K column reads
1.031 / 1.006 / 1.004 / 0.993 / 0.987 against 1.035 / 1.006 / 1.007 /
0.993 / 0.980 — roughly four fifths survives. It is the air, not a
worse-measured proxy for the calendar.

---

## 4. THE BINDING CONSTRAINT — coverage, not counting (CLOSED 2026-09-26)

**This section was right and is now HISTORY. Read it for why coverage
outranks counting, not for the current state — the board reads statsapi
first and Open-Meteo second, and every game on the card gets a reading.**

**This is the most important section. Counting more tables is not the
bottleneck.**

`sources/weather.py` reads statsapi, which reports OBSERVED conditions
near first pitch and has **no forecast at all**. So:

* **Apr–Aug coverage: 100%.** September: 90% — the gap is the last two
  days.
* **At board time on 2026-09-20: 6 of 15 games had a temperature.**
  Coors, where it mattered most, had none — `temp_f`, `condition` and
  `carry` all null.

The consequence, and it is a rule-10 trap in waiting: **a backtest of
any weather mechanism is fully powered while the live board can use it
on a minority of games.** Never read a holdout score for one of these
tables as what the board will actually get. Silent-neutral makes the
gap safe rather than wrong, but it makes the mechanism absent.

`weather.py` already documents a related bug it fixed: a temperature-
less pregame answer was once cached as final and cost 2026-09-07/08/09
their weather entirely — 41 games — with nothing complaining, because
silent-neutral mechanisms fail quietly. Re-fetching is handled now, but
re-fetching cannot conjure a forecast statsapi does not serve.

### The alternate source — BUILT 2026-09-26

**All three catches below were resolved, and the second was the only real
one.** Catch 1 (source mismatch) measured away for temperature at corr
0.942. Catch 2 (wind direction) is the `PARK_CF` table in `weather.py`,
derived from our own data rather than typed. Catch 3 (precip gets
better) came true and killed the mechanism — see section 5.

The investigation as it stood:

Both halves work, free, no API key:

* **Venue coordinates from statsapi.**
  `GET /api/v1/venues/{id}?hydrate=location` →
  `location.defaultCoordinates`. Coors returns
  `{latitude: 39.756042, longitude: -104.994136}`. One-time fetch of 30.
* **Open-Meteo forecast.** `api.open-meteo.com/v1/forecast` with
  `hourly=temperature_2m,precipitation,precipitation_probability,
  wind_speed_10m,wind_direction_10m`. Coors on 2026-09-20 at 19:00 came
  back **69.0F, 0.0mm precip (4%), wind 8.0mph, direction 54°** — a
  reading where statsapi had a hole.
* **Open-Meteo historical archive.**
  `archive-api.open-meteo.com/v1/archive`, same fields. Verified on
  2024-06-15 at Coors: 84.3F.

**THREE CATCHES, and the second is a real loss:**

1. **Source mismatch is the trap.** Every shipped table was counted on
   statsapi OBSERVATIONS. Serving Open-Meteo FORECASTS trains on one
   population and applies to another. The archive API is the fix —
   recount the tables on Open-Meteo history so training and serving are
   the same source. That is why the archive was checked.
2. **Wind direction would break.** statsapi reports wind FIELD-RELATIVE
   ("12 mph, Out To RF"), which is why `carry * wind_mph` needs no
   stadium-orientation table — `weather.py` calls this the pleasant
   surprise. Open-Meteo gives COMPASS degrees. Converting needs a
   per-stadium orientation table that does not exist, so a naive switch
   silently breaks `WIND_HR_MULT`. Mixing sources (wind from statsapi,
   temp/precip from Open-Meteo) means two feeds can disagree about the
   same night.
3. **Precip gets much better.** statsapi gives a category; Open-Meteo
   gives millimetres and probability, continuous, on every game.

---

## 5. PRECIPITATION — DEAD, counted properly 2026-09-26

**The doc below predicted that continuous millimetres would "turn this
from an underpowered categorical count into a real one". They turned it
into a null, and explained the old result.**

Open-Meteo archive precipitation, summed over first pitch to +3h, bins
PRE-REGISTERED on the physics before any outcome was read
(0 / 0.2 / 1.0 / 3.0 mm). Within venue, before HOLDOUT, era-gated —
`scratchpad/temp_k.py`'s method, copied.

```
channel     den      dry    trace    light moderate    heavy   range    era
k            pa   1.0015   1.0029   0.9879   1.0039   0.9791   0.025  -0.15
bb           pa   0.9986   0.9921   1.0059   0.9973   1.0402   0.048  -0.12
hr           pa   0.9994   1.0082   0.9970   0.9902   1.0169   0.027  -0.25
hbp          pa   0.9939   0.9955   1.0438   1.0025   1.0604   0.066  -0.12
h_on_bip    bip   1.0008   0.9884   0.9987   1.0173   0.9864   0.031   0.12
games              5801      476      525      271      229
```

**1,501 wet games against 96 by statsapi's category.** Every era gate
negative. Heavy-rain HR is +0.4 se, in a sample powered to see 8.6%.

**WHY THE OLD NUMBER WAS WRONG, and it is a rule-10 definition failure:
statsapi's "wet" label is a COLD label.** Mean temperature by subset —

```
all open-air games          72.8F
statsapi label wet          62.1F
labelled wet BUT dry by mm  59.6F
open-meteo > 3mm            73.0F
```

Real rain falls at ordinary summer temperature. The label lands on raw
drizzly days 10-13F below average, inside the cells where
`TEMP_HR_MULT` already removes 5-20% of the home runs. Net of venue AND
temperature bin the label's HR effect shrinks 0.749 (-3.6 se) to 0.858
(-2.0 se) on 83 games, while millimetres stay flat at 1.026 (+0.6 se)
on 229. The categorical count was measuring the thermometer.

**The honest caveat:** Open-Meteo reanalysis is gridded at ~9-25km, so a
localised shower can be misplaced, and that dilutes toward null. Bounded,
though — for the >3mm cell to read +0.6 se when the truth is -19.5%, it
would have to be ~90% contaminated, and 17% of it is label-confirmed wet.

**POSITIVE CONTROL (rule 7, and section 3's own instruction).** The same
pipeline with only the binning variable swapped back to degrees:

```
channel         <55    55-64    65-74    75-84      85+   range    era
hr           0.7650   0.9211   0.9753   1.0601   1.1065   0.341   0.89
k            1.0325   1.0037   1.0060   0.9933   0.9832   0.049   0.66
bb           1.1137   1.0240   1.0036   0.9806   0.9599   0.154   0.95
```

against section 3's blind recount of 0.7651 / 0.9233 / 0.9639 / 1.0517 /
1.1253. The harness measures air.

---

## 5b. WIND BEYOND HOME RUNS — DEAD, counted 2026-09-26

Old item 4. Within venue AND temperature bin, cells matching the shipped
HR table's own split, HR carried as the positive control:

```
channel         in 5+  calm/cross      out 5+   range    era
hr             0.9535      0.9894      1.0420   0.088    0.67
                -2.6se       -1.0se       +3.2se
k              1.0106      0.9988      0.9960   0.015    0.29
bb             0.9924      1.0056      0.9954   0.013   -0.02
```

HR reproduces, so the pipeline sees wind. K's best cell is +1.8 se,
under the 2 se bar set before the run, on a weak era gate. BB is the
`hbp` signature exactly — except `hbp` spanned 0.103 and these span a
seventh of that. Neither ships.

---

## 5c. THE OLD CATEGORICAL COUNT, kept for the record

Counted 2026-09-20 off statsapi's `condition` field. Four seasons of
open-air games:

```
Partly Cloudy 3,252   Clear 1,985   Cloudy 1,426   Sunny 1,274
Overcast 498   Dome 266   Drizzle 50   Rain 45   Snow 1
```

**96 wet games in four seasons, ~1% of the slate.** Power stated before
the result: ~7,000 PA gives ~2.2% relative se on a K rate, so only
effects above ~4–5% are resolvable.

Within-venue, observed over expected, 91 games with full rows:

```
precip   k 1.027 +/- 0.026   bb 1.053 +/- 0.042   hr 0.740 +/- 0.058
dry      k 1.000 +/- 0.003   bb 0.999 +/- 0.004   hr 1.003 +/- 0.007
```

K and BB lean the way cold does but sit at ~1 se — underpowered exactly
as predicted, so **not a null, just unresolved**. HR is 4.5 se.

Net of the shipped `TEMP_HR_MULT` (rainy games are cold games, and that
is already modelled), precip HR is **0.805 +/- 0.063, still 3.1 se** —
an independent ~20% home-run suppression.

**Why it did not ship:** 91 games cannot be era-gated the way every
other table was, and there is a selection effect — heavy rain means no
game, so the observed rain is rain they chose to play through. It is a
pre-registered item, not a change. **Open-Meteo's continuous
millimetres would turn this from an underpowered categorical count into
a real one**, which is the strongest argument for doing the source work.

---

## 6. NEXT, IN ORDER

1. ~~Close rule 15 on the K/BB tables~~ — DONE 2026-09-20. ~~The cold
   half needs a spring fold~~ — BUILT the same day (`--spring`, April 8
   to June 30) and run; see the state block. Open from it: the <55F walk
   cell reads ~half too big end to end, in sample.
1b. **Not a weather item, but found by the weather rows and larger than
   any of them:** the model is ~2.5% light on strikeouts fold-wide in
   2024 and 2025, across every arm. Goes to `TODO.md` (rule 14).
2. ~~**The source item.**~~ DONE 2026-09-26. Coordinates, the derived
   `PARK_CF` orientation table, and `fetch_live` serving forecasts for
   games that have not started. The recount turned out to be
   unnecessary: temperature agrees across the two sources at corr 0.942.
3. ~~**Precip, once there is a continuous measure.**~~ DONE and DEAD,
   2026-09-26 — section 5. The continuous measure arrived and the
   effect did not survive it.
4. ~~**Wind beyond HR.**~~ DONE and DEAD, 2026-09-26 — section 5b.

5. **THE ONLY WEATHER ITEM LEFT: the `TEMP_BB_MULT` <55F cell reads
   about half too big** (state block, 2026-09-20 third sitting: model
   −5.3 off, +4.5 on, combined z −2.5 → +2.1, in sample on the spring
   folds). It is a shipped constant, not a new mechanism, so it owes
   the battery a diff across all eight folds and the bar set first.

## 7. FILES

```
src/context/sim.py         the tables, the flags, temp_*_mult()
src/context/slate.py       live wiring, just after hr_air
src/context/calibrate.py   _weather_row, temp_kbb_for, replay wiring
src/context/game.py        Side.ump_kbb — the shared night rail
src/context/sources/weather.py   the statsapi feed and its cache rules
scratchpad/temp_k.py       counts K, BB, HR, HBP, h_on_bip  [--all]
scratchpad/temp_hr.py      the original, and the wind count
scratchpad/air_centre.py   re-checks the AIR_HR centring invariant
tests/test_game.py         check_temp_kbb_*, check_replay_actually_*
```
