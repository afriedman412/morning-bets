# RESUME — per-channel recency in pitcher rates

**RESOLVED 2026-09-17, the same day — item 35, CLOSED, nothing ships.**
The registered sweep never ran: the positive control (rule 7) came first
and proved the battery blind at claimed size, the seeing rows
(`shape.outs_bias_*`) were built per the build-the-row obligation, and
they read noise, not decay — BB incoherent across folds, BABIP symmetric
(a volatility lead, moved to item 34 candidate 5), and the corrected
divergence z distribution consistent with pure sampling noise. The
per-channel wiring is in and off (`rates.CHANNEL_HALF_LIFE_DAYS = {}`).
Full write-up: `NOTES-context-layer.md` 2026-09-17; closed record: TODO.md
item 35. Kept for the framing below — the ESTABLISHED list is still
accurate and still binding.

Written 2026-09-17 to hand this question to a fresh session. The question:

**Should recent starts count more than April — per channel?** Decay the
command/contact channels (BB%, BABIP) with a half-life, leave K% flat, and
score it on OUTCOMES (prefix ladder, outs CRPS), never on the market.

The motivating shape, seen twice now: a starter whose strikeout stuff is
intact but whose command/contact has decayed, priced by season rates that
hide it. deGrom (NOTES ~line 1865) and, on the 2026-09-17 board, Kyle
Harrison — outs 14.5 priced -149 over against Kalshi +120; his season over
rate is 57% (12/21, matching our raw -131) but his last four starts went
14/15/11/11 outs with the 11s costing 98 and 93 pitches. The market is fast
on exactly the thing we hold flat.

## ESTABLISHED (measured; do not re-run)

* **A single half-life over all four rates is CLOSED.** RESUME.md item D,
  2026-09-07. Sweep 30/60/90/150 days, four folds, `scratchpad/hl_score.py`.
  K got WORSE in 16/16 fold×candidate cells including the clean fold — K
  stuff is stable and season-long is its right window. Outs improved on the
  clean 2026 fold only (-0.048 at hl=60), worse on 2023/24. Named mechanism
  for the fold split: the shipped constants were co-fitted with FLAT rates
  on 2023-25 rows. `rates.HALF_LIFE_DAYS` stays None. **This item is NOT a
  rescue of that one — new item, new falsifier** (item D's own closing
  words).
* **Market-scored recency is dead at 3-5 sigma** (`src/context/recency.py`,
  NOTES ~line 195): 14- and 21-day half-lives moved FURTHER from the close
  AND worse against outcomes. Wrong yardstick by THE OBJECTIVE anyway; do
  not resurrect the market comparison.
* **Recency in the LEASH is a wash** (trailing-5 outs mean in the removal
  hazard: MID AUC 0.9422 v 0.9418, BOUNDARY 0.9449 v 0.9440). That is
  outing LENGTH, a different mechanism from the RATES, and it has its own
  open TODO item ("per-channel leash half-life", the compression
  hypothesis). Do not conflate the two; both can matter for an outs line.
* **The deGrom decomposition — the hypothesis in one table.** Last 7 v
  first 17: K% .298 v .301 (IDENTICAL), BB% .085 v .052 (+63%), BABIP .407
  v .255, pitches/out 6.38 v 5.31, outs/BF .660 v .751. Re-simulated on
  last-7 rates his under 16.5 went 0.412 -> 0.501 against his own 7/14 and
  a market at 0.490. The stuff holds; the command decays.
* **Within-start agrees on direction of K, inverts on contact:** first-pass
  out rate -> rest of start +0.1 sigma (does not persist), first-pass K% ->
  rest +6.4 sigma. Between starts the signs flip: K is the stable one.
  Different windows, not a contradiction.
* **The K-side of recency already shipped** as the velo term
  (`sim.USE_VELO_K`, +0.0157 K% pts/mph, 5.3 sigma) — a second reason K
  stays FLAT in this item.
* **`stabilise.py` measured how fast each channel becomes trustworthy and
  BABIP is the slowest** — a recent .407 over ~90 BIP regresses hard.
  Whatever half-life BB gets, BABIP's evidence is thinner; the shrink must
  see the EFFECTIVE sample (it does — see wiring).

## THE WIRING THAT ALREADY EXISTS

`src/context/sources/rates.py` — `HALF_LIFE_DAYS` (None), `_weighted_rows`,
and `pitcher_rates(half_life=)`. Since 2026-09-07 the weighting runs INSIDE
`pitcher_rates`: same shrink targets (own prior season, defence, counted
pool constants), same park neutralisation, and the shrink denominator uses
the SUM OF WEIGHTS, not raw BF — weighting without shrinking the
denominator is how a recency filter becomes an overreaction to one bad
outing. (The first version shrank weighted rates to league alone and would
have measured two changes at once; that bug is fixed — keep it fixed.)

**The build is the per-channel extension:** `_weighted_rows` currently
multiplies ALL of o/h/bb/k/hr by one scalar weight per appearance. Per
channel means each rate aggregates under its own half-life (K flat = hl
None/inf; BB and the BABIP inputs decayed), each with its own effective
sample feeding its own shrink. Watch the coupling: BABIP's numerator (h)
and denominator (BIP = BF - k - bb - hr) draw on channels with different
windows — decide and document whose weight the denominator uses.

## PRE-REGISTER BEFORE RUNNING (the falsifier)

* Candidate grid stated in advance (item D used 30/60/90/150 days; per
  channel now, K excluded from the sweep entirely).
* Scored on the four folds (`hl_score.py` is the harness — READ IT, do not
  rebuild), on outs CRPS and the prefix ladder. **Set the bar first**, rule
  12b: item D died at 2/4 folds, so state what ships (e.g. outs better in
  >=3/4 with the K rows flat) before looking.
* **Re-measure the flat baseline on current data first** — the 2026-09-09
  fold numbers (0.0577/0.0524/0.0399/0.0451) predate several backfills and
  a fingerprint is only valid across constant data.
* **Positive control** (rule 7): inject a synthetic BB decay of the claimed
  size into recent rows and confirm the harness sees it. A mis-specified
  mechanism and an absent effect look identical.
* **The known confound, named in item D:** every shipped constant was
  co-fitted with flat rates, which is the offered mechanism for 2023/24
  reading worse. If the per-channel sweep shows the same clean-fold-only
  split, that mechanism predicts it — decide in advance what result
  distinguishes "constants confound" from "doesn't generalise", or the
  sweep cannot conclude anything.

## PROTOCOL

`data_status` before anything; battery before and after with the diff
reported (rule 15); no backfill between paired measurements; HOLDOUT =
2026-07-01 from `src/context/holdout.py` for anything fitted; stages
labelled QUESTION/HYPOTHESIS/TEST/EVALUATE/CONCLUSION. Open it as a NEW
TODO item (check TODO-SHORT.md for the next free number, update both files
in the same edit) — do not reopen item D.
