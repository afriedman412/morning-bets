# Resume here — state as of 2026-08-24 (end of day four)

`NOTES-context-layer.md` has the long record; this is what you need to act.
Read it before touching anything, then read `CLAUDE.md`.

---

## The one-paragraph version

Play-by-play is scraped and it changed what we know. The advancement
constants the run model rests on were **published guesses that were wrong in
both directions and cancelled**, and they are now measured on this league.
The bullpen work has passed its gate — role is real and projects from prior
games — and per-club baserunning has FAILED its gate, so the league number
stays. The model is calibrated; the binding constraint is execution near the
open, and the biggest remaining mechanism is the bullpen.

---

## What is new since day three

**205 MB of whole-game play-by-play, all 2,006 games** (`sources/pbp.py`,
`.cache/pbp/`, ~2 min over 8 workers). Fetched whole and stored whole —
extracting a subset to save disk is a false economy, the API call is
identical either way and re-scraping for a discarded field is the expensive
mistake. `pbp.plays()` reconstructs base-out-score state BEFORE every play;
`pbp.stints()` turns that into one row per pitcher per game.

**`context.db` is new and `morning_bets.db` is now READ-ONLY to this
layer.** Derived tables (`mlb_stints`, 17,260 rows) live in the new file;
the pipeline DB attaches through a `mode=ro` URI as the `bets` schema, so
joins read `bets.games` exactly as before and a stray INSERT raises. The
pipeline DB is not version controlled and holds a season of boxscores that
cannot be regenerated — that is the whole reason.

**Independent validation of the extraction:** PBP-derived outs agree exactly
with the boxscore on **99.68%** of 16,653 pitcher-games, and reconstructed
base state agrees with statsapi's own `menOnBase` on 62/62 non-inning-ending
plays of the first game checked.

---

## Where the edge is (n_sims CORRECTED — the old table understated it)

Every recorded CLV number was measured at `n_sims=250`, which carries ~3.2
cents of Monte Carlo error against a 3.7-cent median disagreement. That
ATTENUATES. Re-run at 1500 on the same 2,676 F5 contracts:

| | 250 sims | 1500 sims |
|---|---|---|
| CLV corr | +0.456 | **+0.496** |
| z | +36.2 | **+39.5** |
| blend vs open | +20.7% | **+24.9%** |
| 5c+ direction | 56.3% | **63.2%** |
| cents our way | +2.9c | **+3.7c** |
| n disagreements | 932 | **787** |

145 of the "five-cent disagreements" at 250 sims were simulation noise
rather than opinions, and +3.7c now matches the K prop exactly. **K props,
team totals and game totals have NOT been re-run and are all understated by
an unknown amount.** That is cheap and it is high on the list, because it
may change which markets look worth pursuing.

Nothing has ever beaten a settled CLOSING price. The edge is being EARLY.

---

## The advancement tables are measured now, and they were cancelling

152,153 plays (`src/context/advance.py`). The published references were
wrong in BOTH directions at once, which is why nothing showed up in the
aggregate:

    first -> third on a single   .307 .295 .408   was .240 .280 .340
    second scores on a single    .411 .542 .796   was .420 .620 .840
    first scores on a double     .274 .346 .565   was .330 .450 .630
    anyone advances on an out    .326 .354        was .300 .450

Too many runners stranded at second, then too many of the ones who got
there scored. Runs per baserunner sat at **-0.2%** while every component was
off by 3-6 sigma. **The aggregate was right for cancelling reasons**, which
is the exact failure the notes warn about, and it means the model breaks
wherever the compensation does.

Two mechanisms were wrong in SHAPE, not level, and both are now fixed:

* **Advance-on-out is per base.** One pooled constant moved every runner
  together on one coin flip. Measured, the man on second goes ~twice as
  often as the man on first (.49 vs .22 with nobody out), so no single value
  is right for both. Now three tables, rolled LEAD RUNNER FIRST, and
  conditioned on the base ahead being free — which is a different quantity
  from the marginal, and using the marginal would double-count the blocking.
* **Scoring from first on a single did not exist.** Measured .022 / .043 /
  .068 by out count. Added as its own table with a cumulative threshold
  against first-to-third, so the two stay disjoint.

**`sim.USE_MEASURED_ADVANCEMENT` and `sim.USE_MEASURED_GIDP` switch each
change independently** (`LEGACY_ADVANCEMENT` holds the old values). Every
mechanism here is discrete and must stay separately scoreable — the winning
combination is not necessarily the newest state.

**A test changed meaning and you should know.**
`check_advancement_rises_with_the_out_count` asserted a strict 0<1<2 ladder.
That is a property of the published references, not the league: first-to-
third goes .307 .295 .408, so the middle entry is 0.8 sigma BELOW the first.
The invariant was weakened to what the data supports (two-out >> nobody-out)
rather than making the data fit the test.

**THE PAIRED F5 SCORING RUN WAS IN FLIGHT WHEN THIS WAS WRITTEN.** Four
states — advancement published/measured x GIDP published/measured — on the
same sides, outcomes and salts, train before 2026-07-01 and test after.
Re-run it: `scratchpad/score_adv.py`. Whatever it says, the measured values
STAY: a guess that happens to score well is still a guess, and if measured
values score worse that locates the compensation rather than refuting them.
Do NOT reverse-engineer which constant to un-measure to win the score back.

### The GIDP constant is on the wrong denominator

`GIDP%` as published is double plays per OPPORTUNITY — every PA with a man
on first and under two out — and measures .089/.095 here, right next to the
shipped 0.11. But the simulator rolls it only once a ball in play has
ALREADY become an out, about half as many chances, where the real rate is
**.209/.224**. So it turns roughly half the double plays it should.

Not simply corrected, because the F5 fit chose 0.11 in the model's own
denominator over a grid reaching 0.19. Something compensates. Behind
`USE_MEASURED_GIDP`; the scoring run adjudicates.

---

## Per-club baserunning: MEASURED, and it does not pass the gate

The hypothesis was that league-wide generalisation costs accuracy. Mostly
no. Split-half per club, first half of each club's own season against its
second (`advance.py --by-team`):

    grounds into a double play      r +0.384   n=30
    first -> third on a single      r +0.289   n=30
    advances on a ball-in-play out  r +0.119   n=30
    second scores on a single       r +0.111   n=12

Compare the bullpen role gate at r +0.55 to +0.78. The observed club spread
looks large — first-to-third runs .265 (TEX) to .493 (DET), sd .051 — but
with a split-half r of .289 most of that is a season of sampling noise, not
a persistent club property. **Do not wire per-club advancement tables.**

GIDP is the one with any case (r +0.384, and it makes sense as a batter
trait — ground-ball rate and speed), and even that needs heavy shrinkage.

---

## BUILD THE BULLPEN MODEL — the gate has passed

The question was never "is random deployment wrong". It is whether ROLE IS
PREDICTABLE FROM PRIOR GAMES, because otherwise role-based deployment is a
more expensive way to draw from the same distribution. Split-half over 319
relievers, chronological (`src/context/deploy.py`):

    outs recorded        r +0.780
    entry inning         r +0.627
    high-leverage share  r +0.551
    entry margin         r +0.393

**Role is real and it projects.** Build it.

The score does select the arm, but modestly: K-BB% .154 leading 1-3 against
.127 down 4+, and close (<=2) .147 against blowout (>=5) .134 — a gap of
0.36 SD of the reliever pool. The model draws at random, so it prices every
late inning as the AVERAGE arm: too good in a blowout, too bad in a one-run
game, wrong in both tails at once.

**The bigger errors are structural, not selection.** 13,248 relief outings
average **3.47 outs** against the model's flat 3.00, only 52.2% are one
clean inning, 25.4% are longer, and **30.4% are mid-inning entries the model
cannot produce at all.** That changes how many arms a game uses, which is a
variance question, and variance is what a total settles on.

Supporting: team-total direction accuracy by how deep the opposing starter
went — 49.9% (<=15 outs), 52.7% (16-18), 57.1% (19+). Monotone. The relief
innings are what destroy the edge, so the ~40%-bullpen markets are
recoverable rather than hopeless.

Do NOT fit team-specific bullpen offsets. That is the patience/leash mistake
waiting to happen.

---

## The order of work from here

1. **Re-read the paired F5 scoring result** (`scratchpad/score_adv.py`),
   record it, move on either way.
2. **Re-run every CLV test at n_sims >= 1500** — K props, team totals, game
   totals. Cheap, and it may reorder the priorities.
3. **Bullpen: role score from prior games**, deploy by role and live margin
   instead of sample order. `game.py` already tracks the margin.
4. **Bullpen: multi-inning and mid-inning outings.**
5. **Bullpen: inherited-runner rates from PBP by base-out state**, replacing
   `f5`'s flat `INHERITED_SCORE_RATE = 0.33`. `game.py` already plays them
   out; this closes the f5 path.
6. **Re-run team totals and game totals** — the targets this unlocks.
7. **Times through the order** — the biggest absent mechanism. The sim wraps
   the lineup and charges nothing for it. PBP has real TTO per PA. Fit as a
   RESIDUAL.
8. **Handedness, re-run as a residual and PRE-REGISTERED.** Dead as an
   imported scalar; PBP carries `batSide`/`pitchHand` per plate appearance.
9. **Rest/availability, re-opened** — same reasoning.
10. `price.py` / `quote.py` are start-only and cannot price an F5 or a team
    total, which is the stated product. `game.py` exists and does.
11. Stale `hook_patience.json` / `hook_leash.json` — 206 offsets fitted
    against a model that no longer exists. `USE_OFFSETS` is False. Refit on
    the training window or delete.

---

## Rules that have earned their place

**A fitted parameter at the EDGE of its grid is a MISSING MECHANISM.** Four
for four: absent hit-by-pitch, absent fielding errors, out-dependent
advancement twice.

**Prefer a high-n ratio to a low-n aggregate.** Runs per baserunner over
~17,500 simulated starts tracked every real fix; the mean F5 total over a
few hundred games gave four consecutive "improvements" inside one standard
error.

**MEASURING IS NOT FITTING.** Replacing a published constant with the same
quantity counted on this league is not tuning against the settlement value,
provided the conditioning matches the code path exactly. There is no loss
function behind the advancement tables and there must not be one.

**THE DEAD LIST RECORDS HOW A THING WAS TRIED, NOT THAT IT IS UNKNOWABLE.**
Six of the nine dead features were imported scalar multipliers, scored
against a model that has since changed, on half the data. Re-opening one is
legitimate when the APPROACH changes (residual fit rather than import) or
the DATA does (play-by-play). Pre-register it, so it is a test and not a
fishing trip.

**Verify every new check by mutation.** THREE tests in this project have
turned out to guard nothing, and only the mutation run revealed it. The most
recent: a split-half check that passed just as happily when the outings were
sorted, because sorting turns every pitcher into a promotion and made the
correlation MORE negative, not less. It was the assertion that could not
tell them apart, not the mutation that was subtle.

---

## Do not re-run these (measured, recorded)

* **Home run props** despite being the largest market (29,128 contracts) — a
  BATTER outcome, and we hold one `hr_pct` with no batted-ball data.
* **NRFI** — Brier skill -2.9%. Three batters is signal-free variance.
* **Cross-book arbitrage on game totals** — Kalshi agrees with DraftKings
  within ~1 cent on matched half-point lines. Same consensus.
* **Nine features** measured null: handedness, park on raw rates, day/night,
  bullpen availability, arsenal scalar, input-uncertainty propagation,
  recency weighting (3-5 sigma the WRONG way), arsenal mixture on
  strikeouts, arsenal mixture on contact. The last two were pre-registered.
  See the dead-list rule above before assuming any of these is closed.
* **Pitcher archetypes by pitch mix** — real for relievers (permutation null
  p=0.003), absent for starters, too small to wire in.

## State

* 257 checks, `make test`, ~60s, no network, no pytest.
* 2,006 final games, F5 scores on 2,009, real pitch counts on 16,624
  pitching rows, 17,260 stints, 205 MB of play-by-play.
* `.claude/settings.json` sets bypass permissions for this repo, denying
  `git push`, `make publish`, `rm -rf` and reading `.env`.
