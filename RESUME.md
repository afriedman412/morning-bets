# Resume here — state as of 2026-08-24

Written at the end of day three, for the next session. `NOTES-context-layer.md`
has the full record; this is what you need to act.

---

## The one-paragraph version

The simulator is calibrated and the market work is done. **F5 totals and K
props carry a real edge; team totals, game totals, outs and NRFI carry
none.** The edge tracks how little BULLPEN is in the settlement, not whether
a starter drives it. Nine feature ideas have been measured and all nine were
null. The model is no longer the constraint — execution near the open is.

---

## Where the edge is

| target | contracts | bullpen share | direction | blend | cents |
|---|---|---|---|---|---|
| K props | 12,181 | ~0% | **73.2%** | +32.9% | +3.7c |
| **F5 totals** | **2,676** | **~10%** | **59.6%** | **+23.4%** | **+3.4c** |
| team totals | 4,943 | ~40% | 50.7% | +9.4% | +1.4c |
| game totals | 4,222 | ~40% | 52.0% | +4.1% | +1.2c |
| outs / NRFI | — | ~0% | — | ~0% | — |

Nothing has ever beaten a settled CLOSING price. The edge is being EARLY —
beat the open, lose to the close — so realising it means betting near the
open where books are thinnest. **Execution is the binding constraint.**

A prediction of mine that was WRONG, and the useful part: team totals should
have carried the F5 edge, since one team's runs are what the opposing starter
allows. They do not. It is not "starter-driven" that matters, it is bullpen
share — but outs and NRFI have no bullpen and no edge either, so the rule is
not monotone. It needs a starter-dominated settlement AND enough plate
appearances for skill to beat variance. F5 is the only measured quantity with
both.

---

## DO THIS FIRST (highest value, roughly in order)

1. **`quote.py` may have a live line-matching bug.** DraftKings' 7.0 can
   PUSH — over-7.0 needs a total of 8 — while Kalshi's threshold-7 contract
   is over-6.5 and wins at exactly 7. Different bets. I hit this in analysis
   code and have NOT checked whether `quote.py` shares it. This is the only
   open item that could mis-price a real bet.

2. **Re-run the CLV tests at higher `n_sims`.** They ran at 250, giving ~3.2
   cents of Monte Carlo error per contract against a 3.7-cent median
   disagreement. That does not invalidate anything — it ATTENUATES, so
   59.6% direction is a FLOOR. Trade histories now cache to disk (154x warm),
   so a re-run is ~3 minutes of simulation.

3. **Decide what to do about `hook_patience.json` / `hook_leash.json`.**
   206 offsets fitted 2026-08-23 as residuals against a model that no longer
   exists. `sim.USE_OFFSETS` is False so nothing applies them, but they are
   still on disk and eight modules would use them if switched on. Refit on
   the training window or delete.

4. **`price.py` and `quote.py` are start-only** — they cannot price an F5 or
   a game total, which is the stated product. `game.py` exists and does; they
   were never wired to it.

---

## DO NOT DO THESE (measured, recorded, do not re-run)

* **Reliever deployment modelling.** Back-half mechanism, no back-half edge.
  The defect is real — only 52.6% of relief outings are one clean inning,
  mean 3.51 outs not 3.00 — and fixing it improves a number nobody pays for.
* **Home run props**, despite being the largest market at 29,128 contracts.
  A BATTER outcome where the model holds one `hr_pct` with no batted-ball
  data. A ~12% base rate needs far more contracts to resolve an edge than a
  ~55% one.
* **NRFI.** P(NRFI) calibrates at 0.522 against 0.510 and carries Brier
  skill of **-2.9%**. Three batters is signal-free variance.
* **Nine dead features:** handedness, park on raw rates, day/night, bullpen
  availability, arsenal (scalar multiplier), input-uncertainty propagation,
  recency weighting (3-5 sigma WRONG way), arsenal mixture on strikeouts,
  arsenal mixture on contact. Both arsenal mixtures were PRE-REGISTERED.
* **Pitcher archetypes by pitch mix.** Real for relievers (permutation null
  p=0.003) and absent for starters, but too small to wire in.
* **Cross-book arbitrage on game totals.** Kalshi agrees with DraftKings
  within ~1 cent on matched half-point lines. They are the same consensus.

---

## The two rules that actually earned their place

**A fitted parameter sitting at the EDGE of its grid is a MISSING
MECHANISM, not a tuning problem.** Four for four: the absent hit-by-pitch,
absent fielding errors, and out-dependent runner advancement (twice). Every
time the fit was right and I was slow to read it. Treat a grid-edge result as
a mechanism hypothesis on FIRST sight.

**Prefer a high-n ratio to a low-n aggregate.** Runs per baserenner (~17,500
simulated starts) tracked every real fix monotonically, -4.2% -> -0.2%. The
mean F5 total over a few hundred games gave four consecutive "improvements"
that were all inside one standard error, and I put one in a commit message
before catching it. Compare PAIRED and on every game.

---

## Model state (believed settled)

* runs per baserunner **-0.2%**, F5 totals **-0.130 +/- 0.095** (1.4 sigma
  light), game totals 8.69 vs 8.94 (2.8% light)
* inning-prefix ladder: F1, F5, F7 all within a third of a standard error,
  so each mechanism is individually right rather than two errors cancelling
* advancement is keyed BY OUT COUNT from published references, NOT fitted —
  do not hand those back to a search
* `PITCH_COST` fitted on 3,880 real starts; `WP_PB_RATE` was 1.8x too high;
  `ROE_PER_OUT` anchored to the measured unearned share
* the F5 stub is retired — `fitf5` scores on `game.py` like everything else
* bottom-of-9th and extra innings are modelled

## Data state

2,006 final games (2026-03-20 to 08-24), F5 scores on 2,009, per-inning
lines on all of them, real pitch counts on 16,624 pitching rows. numpy and
scikit-learn are dependencies now.

## Test state

**201 checks, `make test`, ~60s, no network.** Every new check this session
was verified by mutation. Two turned out to guard nothing and only the
mutation run revealed it — keep doing that.
