# BEFORE YOU START — read this or you will redo work

## DAY FOURTEEN (2026-08-28) — READ THIS FIRST, IT RETRACTS A DAY-THIRTEEN LEAD

**THE OPEN HOME-RUN QUESTION IS CLOSED AND THE ANSWER IS "NO DEFECT".** The
+10 sigma pitcher-level home-run compression is an artifact of measuring in
sample. A pitcher's shipped rate is built from the same starts it is graded
against, so his own sampling noise is inside the predictor and inside the
outcome, and the slope tends to `1/w` — the shrinkage weight — however good
the model is. **A model that is right by construction scores 2.57 on that
harness; the observed value was 2.36.** `scratchpad/hr_spread.py --synth`.

`STABILISE_MEASURED["pit"]["hr_pct"] = 934` is RIGHT: the constant the data
asks for is 946. Do not change it. PARK is bounded too small to matter here.

**THE REAL FINDING, SHIPPED: pitcher `k_pct` was 57 and is now 132.** Stale —
measured on half a season, never re-measured after the four-season load.
Three independent lines agree (split-half 132, method of moments 98, holdout
discrimination peak 131 at +9.5 sigma, replicated on a second cutoff at
+2.6). F5 CRPS neutral (-0.008 +/- 0.008). The tell that should have caught
it: 57 was BELOW the imported all-players 70.

**DO NOT ALSO RAISE bb_pct OR hr_pct.** `stabilise` reads 165 and 2130, and
the outcome sweep says both are worse (-2.7, -2.6). That specificity is the
control: the harness is not simply preferring more shrinkage.

**RECORDED, NOT FIXED — THE PRIOR IS SHRUNK TWICE.** `_load_seasons` loads
prior seasons through `pitcher_rates`, which already shrank them, and
`shrink_target` shrinks the result again with the same constant. Bites in
proportion to `k`, so it is home-runs-only in size: a pitcher keeps 0.418 of
his own homer record where pooling the evidence once gives 0.568. Worth
~0.044 runs, just under the 0.05 leverage floor. One line to fix, will not
score.

## DAY FOURTEEN, PART TWO — THE OFFENCE IS READABLE

`GameResult.away_bats`/`home_bats` carry per-batter runs and RBI across every
arm. Three answers, in `scratchpad/offense.py`:

* **The batting-order machine is RIGHT** — slot curve and the RBI peak at
  cleanup both match. The slot 6-9 residual is SUBSTITUTION: the model never
  pinch-hits and its nine absorb the 0.207 runs a game real substitutes take.
* **We OVER-separate hitters** (slope 0.73 on runs, 0.82 on rbi, out of
  sample, with a quantitative positive control at x1.69 spread -> x0.56
  slope). The stale batter constants FIX it and COST F5 (+0.0126 +/- 0.0069).
  **NOT SHIPPED.** Re-measuring is necessary and not sufficient.
* **We put runs on TOO FEW hitters** — matched on the team total, top RBI
  +0.072 (z +2.7). Predicted sign was the opposite, so this is NOT clustering
  at the batter level.

**THE SEED IS SHARED ACROSS GAMES IN `ceiling` AND `offense`** (`seed=0` for
every game), which correlates the per-draw errors and inflates the standard
error of any ABSOLUTE level or share by **3.4x**. It cancels in a paired A/B
and does not cancel in a level. Vary the seed by game — crc32 of the game id.
It turned a z +3.5 home-run-share result into z +1.4.

**PITCHER BABIP 500 -> 3068, SHIPPED.** It had NEVER been measured —
`stabilise` omitted the pitcher babip row — so 500 was the legacy import.
Split-half 0.057 over 365 arms. F5 neutral (+0.0011 +/- 0.0034), home-run
discrimination +3.2 sigma, hits flat. The point estimate is soft (k spans
1,500-36,000 over one standard error) and the DIRECTION is not; do not
re-tune it.

**THE BATTER ROW IS NOW 51/122/193/447, SHIPPED.** The numerator was wrong —
H instead of (H - HR) — so the first A/B used 250 and BOTH its conclusions
are void: F5 goes from "costs +1.8 sigma" to NEUTRAL (-0.0026 +/- 0.0075),
and the four-of-four differentiation win becomes two better, two worse. It
ships as a measured value replacing a stale one and buys nothing measurable.

**BEWARE THE STALE .pyc WHEN VERIFYING A TEST BY MUTATION.** CPython
validates bytecode on (mtime, size). Editing a constant, running the suite,
and restoring it WITHIN THE SAME SECOND at the SAME BYTE COUNT — 184 against
447 — leaves the MUTATED bytecode in place for every later run. It cost a
confusing half hour today and it points the wrong way: the mutation fails
correctly and everything after the restore is silently wrong. Clear
`__pycache__` after restoring.

**THE CONCENTRATION FINDING IS WITHDRAWN.** On RUNS SCORED it is +0.025
(z +1.1), signs mixed. It only appears on rbi, and `_credit` over-awards rbi
by rule (MLB gives none on a double play or an error). The batting order and
the hitter over-separation both survive the reseeding.

**HOW RUNS ARRIVE — the home-run share of runs is NOT RESOLVED.** +1.53% on a
July cut, -1.33% on a May cut, neither over 1.6 sigma. So the rbi
concentration finding has NO mechanism identified: sequencing is not
established and the batter rates are ruled out by F5.

**`mlb_batting` UNDERCOUNTS RUNS BY 1.0%** against the final scores on the
same games. Every "actual" figure in `offense.py` is light by that much.

**ADVANCEMENT RE-MEASURED ON 754,886 PLAYS AND CONFIRMED.** Every live
constant within ~0.01 runs of shipped. Do not re-run it. And beware
`advance.report`: its "ANY runner advances" row compares against
`RUNNER_ADVANCES_ON_OUT`, which is LEGACY and does not ship — it reads -41
sigma and means nothing.

**THE PROCESS LESSON, THREE DAYS RUNNING.** The F5 A/B read +0.0079 (worse)
off ONE salt and was about to be reported as a failure; across four salts it
is -0.008 and the noise floor is 0.0165. `fitf5.evaluate` has a `salt`
argument whose docstring says precisely this. Use it.


## WHAT IS RUNNING RIGHT NOW

NOTHING. The history load finished at the end of day ten:
(day eleven added no long jobs; everything below completed.)

    scratchpad/load_rest.out ends "=== HISTORY LOAD COMPLETE ==="

It ran 2023 -> play-by-play -> real pitch counts as one chained job. Both
of those passes take their work list from the `games` table, so they cover
every season present with no argument.

## DATA STATE — FOUR COMPLETE SEASONS

    season   games   final
    2023     2,677   2,664
    2024     2,652   2,635
    2025     2,639   2,632   (+ postseason)
    2026     2,079   2,031   (in progress)

    play-by-play   9,962 games cached, 981 MB in `.cache/pbp`
    pitch counts   46,185 rows backfilled, 0 failed

Backups of the pipeline DB taken before each load:
`/tmp/morning_bets_backup_pre2025.db`, `..._pre2024.db`.

NOTE (CORRECTED day thirteen) the four seasons ARE used now:
`USE_PRIOR_SEASON` is True and `PRIOR_SEASONS` is 3. The paragraph below was
written on day ten and its flag states are stale. The decay
weight across three prior seasons is unmeasured — that is next.

## START HERE — DAY THIRTEEN STATE, AND WHERE THE WORK IS

**EVERYTHING BELOW THIS BLOCK UNTIL "ARSENAL IS HARMFUL" IS DAY 8-12 AND
PARTLY STALE.** The current picture, in order of what should be read:

  1. `## THE INVESTIGATION PROTOCOL` — run investigations as labelled
     stages, and the rule that when a new number contradicts an earlier one
     you check whether they measure the same thing before acting.
  2. `## THE OPEN HOME-RUN QUESTION` — the one live lead, stated in the
     protocol's terms with its hypothesis marked NOT ESTABLISHED.
  3. `## THE RUN GAP IS ADVANCEMENT AND IT IS UNDER-DISPERSION` — the
     measured diagnosis that should drive the work.
  4. `## WHAT IS CLOSED AS OF THE END OF DAY THIRTEEN` — do not re-run.
  5. `## ARSENAL IS HARMFUL, NOT NULL` and `## HANDEDNESS — CLOSED`.

**FLAG STATE, verified at the end of day thirteen:**

    USE_PRIOR_SEASON   True   (3 seasons)
    USE_STEAL_TABLE    True   steals in every base state, measured
    USE_ROLE_HBP       True   per-arm hit-by-pitch and sacrifice rates
    USE_HANDEDNESS     False  HARMFUL, not inert — see its docstring
    USE_ARSENAL        False  HARMFUL, +5.0 sigma worse leak-free
    USE_PARK           False  and park is a large HOME RUN effect the model
                              does not represent at all — a live candidate
                              for the open home-run question

**THE ONE-LINE STATE OF THE MODEL:** it puts exactly the right men on base
(+0.0%) with every event channel inside 1.4%, and brings 1.7% fewer of them
home. The remaining gap is advancement, and it is SHAPE — reality has more
shutouts AND more blowups. No further measurement of a RATE can close it.

**THE SIMULATOR NOW CARRIES RUNNER IDENTITY.** `Frame.bases` holds a runner
token, `StartResult.scored_by` / `.rbi_by` attribute runs, and per-hitter
questions are answerable for the first time. Reliever lines are still
discarded on each arm change, so a whole-side tally needs them merged first.

## PARALLELISATION — WHAT IS AND IS NOT, AND WHY

**The season load is SEQUENTIAL ON PURPOSE. Do not "optimise" it.**
`season.py` says so in its own docstring — it is somebody's free public API.
More importantly a second writer against SQLite would collide, and
`backfill` COUNTS A LOCK COLLISION AS A FAILED DATE AND SKIPS IT. That
leaves silent gaps that look exactly like a completed load. ~14s per date,
~50 min per season.

**Everything else already forks and does not need work:**

    pbp / pitches backfill    8 workers (network-bound)
    tests/run.py              one process per check, 95s -> 35s
    score_boundary, memory    fork over games, cpu_count-1
    fit_boundary              one pass, ~5 min over 4,663 games

Fork, never spawn. A spawned child re-imports at DEFAULT globals and every
`USE_*` flag silently reverts.

## TOOLS BUILT TODAY — CHECK HERE BEFORE WRITING ONE

    memory.py           3 arms (none/pool/prior) x 2 cuts, on outs, K,
                        game totals and F5. THE main experiment.
    season_hook.py      do managers pull the same way across seasons
    preseason_test.py   preseason rank vs the leash residual, any season
    preseason_ranks.py  2025 + 2026 lists, transcribed with provenance
    reputation.py       career/awards vs the residual
    qualitative.py      prior-season IP, budget, rookie, age
    rank_starters.py    stat-line rank vs prior outs
    yesterday.py        one slate vs actuals AND vs Kalshi close
    score_boundary.py   legacy/linear/knee/shipped, paired seeds
    fit_boundary_nl.py  linear vs quad vs hinge forms
    scope_baseline.py   digests every season-sensitive number
    battery.sh          the whole re-measurement, unattended

## QUESTIONS ALREADY ANSWERED — DO NOT RE-RUN

* Does more data fix outs? NO. Memory, and 89,983 hook decisions.
* Does it reach game totals? NO. Inside noise on RMSE 4.5.
* Do managers pull the same in 2025 and 2026? YES, on matched calendar.
* Stat-line rank, career record, awards, workload, rookie status vs the
  leash? ALL absorbed by the pitcher's own recent innings.
* Preseason rank gradient? DEAD on 2025. Headline correlation replicates.
* Boundary knee? Better per decision, worse on what settles. Ships inert.
* K% shrinkage constants? Tested, no change needed.

---

# Resume here — state as of 2026-08-27 (day twelve)

## WHAT CHANGED TODAY, IN ONE LINE

**THE BASERUNNER SHORTFALL IS REAL, IT IS -2.4%, AND IT IS ALMOST ENTIRELY
SINGLES.** Decomposing the five ways to reach base localised it for the first
time.

## THE SINGLES GAP WAS A DENOMINATOR. FIXED, AND IT REACHED THE RUNS.

`bip = outs_recorded + hits - K - HR` counts OUTS, and outs are not balls in
play. A DOUBLE PLAY is one ball in play and TWO outs; a CAUGHT STEALING or
pickoff is an out and no ball in play at all. Counted per play off
play-by-play, matched on the same games (`scratchpad/babip_def.py`):

    2026 starters   boxscore 57,079   counted 55,225   ratio 1.0336
    2025 starters   boxscore 77,378   counted 74,898   ratio 1.0331
    2025 relievers  boxscore 55,842   counted 54,125   ratio 1.0317

**THE NUMERATOR IS EXACT** — 15,920 non-homer hits from both sources on the
matched games — so it is purely the denominator. League BABIP 0.2778 against
a counted 0.2883.

**WHY IT SURFACED IN BABIP AND NOWHERE ELSE, and this is the transferable
part.** The same inflation understates k_pct, bb_pct and hr_pct by ~2% too —
but those are resolved through log5 AGAINST A LEAGUE MEASURED THE SAME WAY,
so the error cancels in the ratio. **BABIP's LEVEL reaches the simulation as
an absolute rate and does not cancel.** One error, visible in exactly one
channel, which is why a decomposition found it and seven days of aggregates
did not.

    channel      before    after
    1B            -4.9%    -1.7%
    REACHED       -2.4%    -0.6%

AND ON THE PRODUCT, paired, 1,152 sides (`scratchpad/bip_ab.py`):

                       CRPS    runs     sd  shutout  5+ runs
    boxscore bip    1.63754    2.30   2.19    22.9%    15.0%
    counted bip     1.62634    2.37   2.23    22.1%    15.8%
    ACTUAL                     2.44   2.32    21.9%    17.6%

**CRPS -0.0112, and every column moves the right way at once** — which
almost nothing here ever does. The run deficit HALVES (0.14 -> 0.07 per
side), the under-dispersion narrows, shutouts land within 0.2 points, and
the crooked-innings gap closes by a third after resisting everything all
week.

STILL OPEN in that table: hit-by-pitch 11% light, and sides scoring 5+ still
1.8 points short — so some CLUSTERING is missing even with the traffic
roughly right.

**MATCH THE GAME SET WHEN COMPARING TWO SOURCES.** The boxscore is missing
starter rows for 67 games of 2026. Compared unmatched, the 3.4% denominator
inflation cancels against a 3.3% game shortfall and the ratio reads 1.001 —
a real defect hidden by an unrelated one.

## READ THIS BEFORE THE TABLE BELOW — A CORRECTION TO IT

The decomposition was first run at 300 games and reported as "the right
NUMBER of baserunners and the wrong KIND", with home runs 11% high. **Re-run
at the full 520 games with 12 sims, the home-run excess DISAPPEARS** — the
ACTUAL home-run rate was 29.3 per 1,000 in the 300-game sample and 31.1 in
the 520-game one, a 6% swing on the target itself:

    channel     300g     520g   actual (520)
    HR        +11.2%    -0.4%          31.1
    1B         -6.6%    -4.9%         144.4
    ROE       +68.2%    +6.1%           5.5
    HBP        -5.3%   -11.3%          11.2
    REACHED    -1.2%    -2.4%         322.6

**THE ACTUAL SIDE IS THE BINDING SAMPLE, NOT THE SIMULATED ONE.** 300 games
is ~23,000 real plate appearances, which puts +/- 1.1 per 1,000 on the home
run rate. Simulating each game six times sharpens the MODEL's number and does
nothing for the target it is compared against — and it is easy to read the
combined 1,800 simulated games as the sample size. It is not.

So: home runs are FINE, errors are fine after today's fix, walks are fine
after the reliever-league fix. **What is left is singles at -4.9% and a real
-2.4% shortfall in men reaching base.** That is a BABIP problem — too few
balls in play become hits — and the hit MIX is already exonerated below.

The "wrong kind, not too few" framing was overstated and the reliever-league
fix was over-credited on home runs; its WALK fix (-1.9% -> +0.7%) survives.

## THE DECOMPOSITION THAT SHOULD HAVE BEEN RUN ON DAY SIX

`scratchpad/traffic.py`. There are only five ways to reach base, and nobody
had ever split them. Per 1,000 plate appearances, 300 games, sim against the
same games' play-by-play:

    channel     sim   actual    diff     rel
    K         224.4    228.3    -3.9   -1.7%
    BB         84.4     85.9    -1.5   -1.7%
    HBP        10.2     10.8    -0.6   -5.3%
    HR         32.6     29.3    +3.3  +11.2%
    1B        137.0    146.7    -9.7   -6.6%
    2B         39.4     38.5    +0.8   +2.2%
    3B          3.4      3.1    +0.4  +11.3%
    ROE         8.7      5.2    +3.5  +68.2%
    OUT       459.8    452.1    +7.7   +1.7%

    REACHED   315.8    319.6    -3.8   -1.2%

**REACHED IS 1.2% OFF. The composition is 68% off in one channel and 11% in
another, and they nearly cancel** — which is exactly why every aggregate ever
run here missed it. "Too few men reach base" was the wrong diagnosis for
days: it is TOO MANY HOME RUNS, TOO FEW SINGLES, AND A MADE-UP ERROR RATE.

And it explains the crooked-innings shortfall directly. **Singles cluster and
home runs do not** — a homer clears the bases and ends the rally, a single
puts a man on AND moves the men already there. Same traffic, arranged into
fewer big innings.

## FIXED TODAY

**`ROE_PER_OUT` 0.018 -> 0.0123, COUNTED.** Its own comment showed the
working — "8.09 / (1 - 0.0764) = 8.76 against an actual 8.67" — which is an
error rate set to lift the RUN LEVEL. It ran 46% high and put 3.5 fake
baserunners per 1,000 PA into the model. **Correcting it WIDENED the run
deficit from 0.10 to 0.14 per side, and that is the point**: part of the run
total was fake traffic, and the 3%-light figure was masked.

**`USE_RELIEVER_LEAGUE`, ON.** `_starter_league` is the log5 anchor AND was
the shrink target for relievers. Counted on 2026:

                       BF        K%       BB%       HR%
    RELIEVERS      64,752    0.2227    0.0972    0.0280
    STARTERS       85,207    0.2160    0.0823    0.0319
    MODEL LEAGUE             0.2170    0.0812    0.0317

Relievers allow 12% fewer home runs and walk 18% more. The target DOMINATES
them: the home-run shrink constant is 934 against a reliever's median 106
batters faced, so ~90% of his home-run rate IS the target. Fixed:

    channel    before    after   actual
    BB          -1.9%    +0.7%   fixed
    HR         +10.7%    +4.5%   halved
    K           -2.1%    -2.3%   unmoved

**AND THE SIZE OF EACH MOVE TRACKS THE SHRINK WEIGHT**, which is the internal
check that it is the real mechanism: 90% league on HR moved a lot, 57% on BB
moved some, 35% on K moved nothing.

SCORED NEUTRAL — F5 CRPS 1.63959 -> 1.63754, inside noise, because the extra
walks and the missing home runs cancel on runs. Shipped on CORRECTNESS.
The prediction that walks would buy CLUSTERING did NOT pay (5+ runs 15.1% ->
15.0% against a real 17.6%), and it was stated before looking.

## THE PRINCIPLE THAT KILLED TWO MECHANISMS AND SHOULD BE ASKED FIRST

**HOW MUCH OF THIS IS ALREADY INSIDE THE PITCHER'S OWN RATES?**

Team defence died on it: a pitcher's BABIP was earned in front of his own
gloves, so neutralise-then-apply is a ROUND TRIP for anyone who was not
traded. Park died on it once already. The raw club spread — 0.034 of BABIP
between the best defence and the worst — is real and is NOT headroom.

**AN OBSERVED SPREAD ACROSS CLUBS IS NOT AN OPPORTUNITY. Ask what is LEFT
after the player's own line has absorbed it, and size the prize from THAT.**

## FOUR CANDIDATES SCREENED ON RESIDUALS — ALL DEAD, ALL CHEAP

The pattern to copy: a residual correlation over all 3,278 starts, no
simulation, minutes each. Every one of these would have been days of
build-and-A/B under the old approach.

    candidate                       n       r       z   removable   bar
    handedness (own split, LOO)  3,153  +0.022    +1.2      0.046   0.2
    catcher identity (LOO)       3,207  -0.055    -3.1      0.115   0.2
    arsenal, contact mult        3,278  +0.040    +2.3      0.088   0.2
    arsenal, k mult              3,278  +0.005    +0.3      0.011   0.2
    lineup slot due up          45,097       -       -    AUC -0.0004

**HANDEDNESS took three answers to get right and only the third is real.**
First screen: lineup platoon BALANCE against the residual, flat — but that
assumes every pitcher has the same size split, and 42 of 91 starters have
REVERSED splits, so the population cancels. Second: his OWN split against
tonight's mix, +4.8 sigma — leaked, because his split was counted on a
season INCLUDING the start being predicted. Third, leave-one-out: +1.2
sigma. The mechanism is right and the effect is ~0.06 K per start.

**CATCHER** is dead on the stat that matters: walks score -0.001, and walks
are what framing should move most. Its strikeout number is significant and
NEGATIVE, which is the wrong sign for a mechanism and matches the known
leash artifact.

**ARSENAL is a null for the seventh time**, but the shape is new and worth
recording: the signal is entirely on the CONTACT multiplier, not strikeouts,
where every previous attempt looked. It is still below the bar and
leak-inflated. If ever revisited, aim it at contact.

**LINEUP SLOT DUE UP** (does a manager leave him in for 7-8-9?) is dead.
Counted, pull rates are flat across the order — slots 1-3 at 0.1087 against
4-9 at 0.1093 — and fitted alongside the existing features the top-of-order
coefficient comes out NEGATIVE (-0.243) with AUC slightly WORSE. The
intuition is not in the data.

ALL FOUR were re-run against residuals regenerated after the BABIP fix and
none of the conclusions moved.

## THREE RE-OPENED, RANKED BY THAT QUESTION

1. **PARK, FOR THE VISITING SIDE ONLY.** The strongest of the three and the
   reason park keeps measuring null: every previous test applied it
   SYMMETRICALLY. A home pitcher has half his innings in this park and it is
   already in his rates; a VISITING pitcher has a series here all year and it
   is not. So the correct specification is asymmetric — apply to the visitors,
   apply nothing to the home side — and that has never been tested.
2. **HANDEDNESS.** The dead result used DERIVED SEASON SPLITS on the
   two-engine setup. Play-by-play carries real `batSide`/`pitchHand` on every
   plate appearance now. Different data, different engine.
3. **CATCHER FRAMING.** `sources/catcher.py` fetches it and the simulator has
   never touched it — the only mention of a catcher in `sim.py` is a comment
   about passed balls. Same absorption problem as park, WITH ONE ESCAPE: the
   catcher changes WITHIN a team. The backup catches ~30% of games, so the
   usable signal is the starter/backup swing and not the club level. Needs
   posted lineups, so it is not an 8am mechanism.

## EXONERATED — DO NOT SPEND A DAY ON THESE

**THE HIT MIX IS CORRECT.** Suspected all week ("one league constant splits
every hit"). Measured:

                  1b       2b       3b
    model     0.7597   0.2207   0.0196
    actual    0.7594   0.2210   0.0196     (28,631 non-HR hits, 2026)

Measured right and wired right. **The singles gap is a BABIP problem — total
balls-in-play hits are 4.2% low — not an apportionment problem.** That is now
the largest single unexplained channel and the best lead in the table.

**ARSENAL HAS NEVER PRODUCED ANYTHING.** Stated plainly because it keeps
being half-remembered as promising. The headline was 9.79% against 9.79%, a
dead-even zero. What survives is a SUB-THRESHOLD hint on high-K prop lines
(+0.67pp, under a 0.5pp detection floor) and `PREREG-arsenal.md` exists
specifically to stop that hint becoming a finding. Its protocol is also now
stale: it demands n_sims >= 400 across 6 salts to resolve 2 sigma, and
today's real mechanisms were visible at 25 sims in one run. **A thing needing
that much machinery to detect is below the threshold that changes a price.**

## PRICING A LIVE SLATE — WHAT THE TOOLING CANNOT YET SAY

Ran 2026-08-27 end to end (`price.py` for props, `scratchpad/tonight.py` for
game totals, which `total_market` still cannot do). It works, and two gaps
showed up that are about the OUTPUT rather than the model.

**A DISAGREEMENT ARRIVES WITH NO ATTRIBUTION.** The board's two biggest
edges were Cameron unders and Arrighetti overs — six of the top ten rows.
Both pitchers are league-average strikeout arms with nearly identical rates
(0.2115 and 0.2118), so NONE of it was about the pitchers: Toronto's
projected lineup sits at 17.1% against a 21.7% league. That took a manual
investigation to find. Nothing in the output says "this is a lineup effect",
and nothing flags that six rows are ONE bet. Worth building: attribute each
gap to pitcher / lineup / park, and group correlated markets.

**SORTING BY GAP OVERWEIGHTS THE TAILS.** The list is ranked by |ours -
market|, which puts an 8.8-point gap on a longshot above a 8.3-point gap at
a coin flip. The probability estimate is least reliable exactly where the
gap is largest. Rank by gap over simulation error, which `price.py` already
computes per market.

**SIM COUNT: 400 IS NOT ENOUGH FOR A TOTAL.** LAD/ATL came out at 7.34 with
400 sims and 7.05 with 20,000 — 1.5 standard errors apart, and it moved the
under from 51.6% to 54.8%. Same for props: two 1,500-sim runs of the same
Cole line differed by 1.2 points on seed alone. Use >= 20,000 before
comparing to a price.

**THE ODD/EVEN SAWTOOTH IN GAME TOTALS IS REAL**, checked rather than
assumed: one-run margins are 27.3% of games and always produce an odd total,
and the actual 2026 odd share is 58.1%. The model reproduces it. But the
same comparison shows the model still carries too much mass at 3-6 runs
(0.099 against an actual 0.067 at three), so **it leans UNDER on low totals
as a matter of bias, not information** — worth remembering before trusting
an under lean.

**THE LINEUP PROJECTION IS THE WEAKEST LINK IN THE PRICING PATH, and it is
not modelled as a source of error anywhere.** Demonstrated on a live board.

The biggest edge on 2026-08-27 was Noah Cameron unders against Toronto,
built on a projected nine at 17.03% K against a 21.67% league. The user
supplied the ACTUAL card: 18.69%. Two names of nine were wrong — we had
Gimenez (19.2%) and Lukes (15.7%), the real card had Charles McAdoo (37.1%
vs LHP) and Daz Cameron (28.6%), the two highest-strikeout bats on the sheet.

    line    projected card    actual card    market
    o3.5         0.543          0.622        0.710
    o4.5         0.331          0.413        0.545
    o5.5         0.174          0.239        0.345

Cameron's expected strikeouts go 3.7 -> 4.19 and **HALF THE EDGE
DISAPPEARS** — the gap at 4.5 falls from 21.4 points to 13.2. And that
UNDERSTATES it: only the personnel could be corrected. The 18.69% is the
vs-LHP split and the model uses overall rates with no handedness, while
Cameron is a lefty facing eight right-handed bats holding the platoon edge.

**Everything the modelling work touched today — the hook, BABIP, reliever
rates — is worth less on a live board than getting the card right.** Two
roster spots moved a headline edge by half. Worth building: treat the
projected lineup as an uncertainty to be propagated rather than an input to
be trusted, and flag any edge whose size depends on unconfirmed names.

## THE INVESTIGATION PROTOCOL — USE IT, AND LABEL THE STAGES

Adopted 2026-08-27. Full version with the failure behind each rule is at the
END of `NOTES-context-layer.md`. Write the labels out explicitly — the point
is that a missing stage becomes visible.

    QUESTION    the quantity, the population, and the UNIT OF OBSERVATION.
                "differentiates pitchers" was answered with a regression over
                STARTS, which is a different question with a different answer.

    HYPOTHESIS  stated BEFORE running, naming the CHANNEL it should appear in
                and what would falsify it. Handedness was screened on
                strikeouts when the effect was on contact; arsenal was aimed
                at strikeouts six times out of eight.

    TEST        - STATE THE POWER FIRST. A run chosen for speed is a plumbing
                  check and its NUMBER IS NOT REPORTABLE.
                - NAME THE DENOMINATOR.
                - POSITIVE CONTROL: amplify 3-6x, confirm the harness sees it.
                - LEAVE-ONE-OUT MECHANICALLY, not by argument.

    EVALUATE    read the control first. A uniform % error across independent
                channels is a DENOMINATOR. Ask whether the result LOCALISES
                to what the hypothesis named. Remember a Monte Carlo mean
                carries its own noise.

    CONCLUSION  separate ESTABLISHED from INFERRED in the same breath, and
                give the size in RUNS or CENTS, not only in sigma.

    NEXT STEPS  the ONE test that resolves the largest remaining ambiguity.

**WHEN A NEW NUMBER CONTRADICTS AN EARLIER ONE, DO NOT ACT — CHECK WHETHER
THEY MEASURE THE SAME THING.** Three positions were taken in two minutes on
the home-run question and two of them were never in conflict: a split-half
reliability of a RATE and a regression slope on a SIMULATION OUTPUT are
different quantities.

## THE OPEN HOME-RUN QUESTION, STATED IN THE PROTOCOL'S TERMS

**CLOSED ON 2026-08-28 — THE COMPRESSION IS NOT REAL. Kept because the
question was well posed and the answer came out of it, but do NOT run the
"NEXT TEST" below: it was run, both arms, and the premise is void. See the
day-fourteen block at the top of this file.**

QUESTION    Where is the model's home-run compression? Its HR predictions are
            2.36x too bunched across pitchers (+10 sigma, pitcher-level,
            minimal noise correction).
HYPOTHESIS  It is `STABILISE_MEASURED["pit"]["hr_pct"] = 934`, which leaves a
            600-batter pitcher holding 39% of his own rate.
STATUS      **NOT ESTABLISHED — this is inference, not measurement.** The
            predictor is a simulation output combining the pitcher's rate,
            the NINE BATTERS' rates and the workload, so a compressed output
            does not localise to the pitcher. Batters carry only 0.73 of
            observed HR spread. And `stabilise` measures pitcher HR as the
            LEAST reliable stat on the board (split-half 0.108, implied k
            2130), which argues for MORE shrinkage, not less.
NEXT TEST   Sweep BATTER HR shrinkage and PITCHER HR shrinkage SEPARATELY on
            the holdout. Pitcher-only helps -> k=934 is the culprit.
            Batter-only helps -> it is k=160 on the hitters. Neither ->
            the compression is elsewhere, and PARK is the obvious candidate
            since `USE_PARK` is False and park is a large home-run effect the
            model does not represent at all.

NOTE a reporting bug found alongside: `stabilise.report()` prints its
"k shipped" column against the OLD imported `STABILISE` dict, not against
`STABILISE_MEASURED`, which is what actually ships. Its comparison column is
therefore stale for pitchers — measured 132/165/2130 against IN USE 57/138/934,
so all three read as under-shrunk rather than over-.

## ARSENAL IS HARMFUL, NOT NULL — AND THE INSTRUMENT IS NOW VALIDATED

Nine attempts. The first eight had no positive control, were scored on runs,
and reasoned their leave-one-out away in a docstring.
`scratchpad/arsenal_direct.py` fixes all three. Positive is WORSE:

    arm                    k               bb              hr              h
    arsenal 2026    +0.0088(+5.5)   -0.0014(-1.1)   -0.0002(-0.2)  +0.0043(+2.3)
    arsenal x4     +0.1720(+113.0)  -0.0017(-1.9)   +0.0005(+0.7)  +0.0900(+58.7)
    arsenal 2025    +0.0082(+5.0)   -0.0007(-0.6)   -0.0008(-0.8)  +0.0040(+2.8)

**THE CONTROL FIRES AT +113 SIGMA**, so an arsenal null here finally MEANS
something. And the answer is not null: leak-free 2025 arsenal is +5.0 sigma
WORSE on strikeouts and +2.8 on hits. `USE_ARSENAL` stays False, and the
docstring should say harmful rather than inert.

**CARRY THE CAVEAT:** the control barely moves walks (-1.9) or home runs
(+0.7), so those two rows are UNINFORMATIVE rather than null. A power or
walk hypothesis needs a different instrument.

## WHAT IS CLOSED AS OF THE END OF DAY THIRTEEN — DO NOT RE-RUN

Every one of these was measured on 2026-08-27 with stated power. They are
not "we could not find it"; they are answers.

**PER-PITCHER AND PER-CLUB DISPERSION — CLOSED.** Are some arms harder to
predict? Split-half, odd against even starts, Spearman-Brown corrected, on
earned runs: pitcher dispersion reliability 0.072 over 107 arms, pitcher bias
-0.011, club dispersion NEGATIVE. There is spread (mean |residual| 1.19 at
p10 against 1.91 at p90) and it does not repeat. Powered to see a full
reliability of 0.32. `scratchpad/whos_wrong.py`.

This was the top lead out of the under-dispersion diagnosis and it is gone.
Whatever makes a start blow up is not a persistent property of the pitcher.

**SCHEDULE BURDEN — CLOSED, on the level AND on the variance.** Travel
distance, time zones, getaway days, long stretches, days since home. Real
great-circle miles and signed eastbound time-zone shift, which
`sources/rest.py` has carried all along and which had never once been scored
against outcomes. Everything with power is flat: miles +1.5 signed / +0.3
dispersion, far-travel +1.2/+0.9, eastbound +0.6/-0.9, getaway -0.5/-0.9.
`scratchpad/schedule.py`.

TWICE the only row over 2 sigma was the interaction, with THIRTEEN and then
SEVEN starts in it. Recorded as not a lead both times.

**SPREAD CALIBRATION — real but NOT EXPLOITABLE.** Regressing actual on
predicted, every channel is above 1.0 once Monte Carlo noise in the predictor
is corrected (k 1.15, bb 1.23, er 1.32, h 1.37, outs 1.58, hr 2.59), so the
model's underlying predictions are too bunched. But fit the correction on
early starts and apply it to later ones and MSE moves -1.4% to +0.7% with
mixed signs — the DELIVERED predictions carry the Monte Carlo noise, and
noise widens what shrinkage narrowed. `scratchpad/spread_cal.py`.

**PER-BATTER RUN SHARE — NOT ANSWERABLE, and worth knowing why.** Whether
Judge takes the run share he should cannot be measured: `sim.apply_pa` does
not know which batter is up and `fr.bases` holds booleans, not runner
identity. Giving the bases identity is a real state-machine change. The
INPUT spread is measurable and matches the shipped shrinkage constants almost
exactly, so the flattening is configured rather than broken.

## THE RUN GAP IS ADVANCEMENT AND IT IS UNDER-DISPERSION. START HERE.

**MEASURED AND SETTLED** (`scratchpad/f5_decomp.py`, 1,659 games). Simulated
events through five against what ACTUALLY happened through five, starter
innings on both halves:

    channel    sim/side    actual    gap %
    k            4.2771    4.2981    +0.5%
    bb           1.6041    1.6257    +1.3%
    hbp          0.2034    0.1962    -3.7%
    h            3.6555    3.6519    -0.1%
    hr           0.6301    0.6212    -1.4%
    on           6.0931    6.0949    +0.0%      <-- EXACT
    runs         2.1533    2.1905    +1.7%

**THE MODEL PUTS THE RIGHT MEN ON AND BRINGS 1.7% FEWER HOME.** No further
measurement of strikeout, walk, hit or home run rates can close this — they
are already right to within a percent. Runs per baserunner 0.3534 against
0.3594.

**AND IT IS SHAPE, NOT RATES.** Runs allowed by the starter through five:

    runs     sim %  actual %     diff
       0     22.72     23.24    +0.51
       1     21.80     21.43    -0.37
       2     18.93     18.38    -0.55
       3     14.31     13.74    -0.56
       4      9.75      9.37    -0.38
       5      6.12      6.51    +0.39
      6+      6.37      7.32    +0.95

Reality has MORE shutouts AND MORE blowups; the model is bunched in the
middle. Both tails thin at once is CLUSTERING — plate appearances resolve
independently and real ones arrive in bunches. Runs are convex in
clustering, so the missing tail also drags the mean. One defect, both
symptoms.

**CONFIRMED BY A FLAT DISPERSION TERM** (`scratchpad/dispersion.py`): one
latent draw per start at sigma 0.10 cuts the shape error 44% AND closes 86%
of the run gap. Two separate defects would need the shape overshot to fix
the level; one sigma doing both says they are one thing.

**IT IS NOT SHIPPED, AND WHY MATTERS FOR WHAT TO BUILD NEXT.** It is neutral
on F5 CRPS (+0.00313 +/- 0.00315 held out) because a FLAT term adds the same
dispersion everywhere — the marginal distribution gets righter and no
individual game's prediction improves. Calibration moves, discrimination
does not.

**SO BUILD A DISPERSION THAT VARIES.** By pitcher, by workload, by anything
with a measurable spread and a stability gate. That moves discrimination as
well as calibration and is the one thing left that can reach this gap.

NOTE `form.py` IS PARKED ON A DIFFERENT QUESTION. It asked whether nightly
form is PREDICTABLE IN ADVANCE and answered no three ways. Generating enough
bad nights needs no prediction at all. Form was tried as a predictor; it has
never been tried as a dispersion. Also note `early_exit_p`, already built and
shipped inert, aims at the same tail from the hook side.

## THREE CONSTANTS WERE MEASURED ON STARTERS AND USED ON EVERYONE (2026-08-27)

**THAT IS A PATTERN, NOT THREE COINCIDENCES, AND THE REST OF THE CONSTANTS
HAVE NOT BEEN CHECKED FOR IT.** All three were counted off play-by-play,
all three were wrong in the same direction, and all three were derived from
boxscore aggregates over starters and then applied to every arm in the game.

    HBP_RATE   0.0098  -> per role: SP 0.01044, RP 0.01262  (relievers +21-34%)
    SAC_RATE   0.010   -> per role: SP 0.00888, RP 0.01272  (relievers +43%)
    WP_PB_RATE 0.0155  -> 0.02046                            (pooled, +32%)

`PitcherRates` now carries `hbp_rate`/`sac_rate` (None = old flat fallback),
`game.build_side` sets them per arm behind `USE_ROLE_HBP`, and an explicitly
set rate WINS over the role default — overwriting unconditionally made the
field unusable by any caller and let a regression test's mutation survive.

**WP_PB_RATE CLOSED A FIFTH OF THE F5 RUN GAP** (+0.0655 -> +0.0521 runs)
while CRPS moved 0.0004 against error bars of 0.0015-0.0024. That is the
expected shape for measurement replacing a guess, and why such a change does
not have to prove itself on the loss.

**IT IS ALSO NO LONGER SEARCHED.** It was the ONLY parameter `fitf5` moved,
and the fit had settled it BELOW a number anyone can count — a fitted
constant drifting away from measurable truth is a fitted constant absorbing
somebody else's error. The direction was diagnostic and predicted the
result: the search bought accuracy by handing out FEWER free bases, which is
what you do when the model turns the ones it has into too many runs.
`fitf5.MEASURED` is the new home for constants the search may not touch, so
`PARAMS` is now EMPTY — the honest state, not a bug.

**PASSED BALLS ARE CLOSED.** 12.8% of free-base advances; the pitcher owns
87% through wild pitches. A per-catcher BLOCKING model works on an eighth of
an already-small quantity, ~0.002 runs. Framing was separately dead on
strikeouts and walks. Both halves of the catcher question are now answered.

**STILL MEASURED BUT NOT WIRED:** per-pitcher HBP is real and unusually
stable — sd 0.00675, p10 0.0043 against p90 0.0200, reliability +0.711,
which is bullpen-role territory. Leverage 0.035 runs pitcher-only, near 0.05
with the batter side. Right at the floor, so it is a judgement call rather
than a free win. Per-pitcher wild pitch is +0.657 reliable and 0.020 runs —
under the floor, not worth wiring.

## log5 MULTIPLIERS NOW ENTER THE ODDS, AND THE CLAMPS ARE GONE (2026-08-27)

Park and arsenal MULTIPLIED log5's probability output. log5 is an odds-ratio
construction, so scaling its output is not a consistent change to the
underlying rates — the same park factor meant different things in different
matchups, worst in the TAILS where prop lines sit. `sim.odds_mult` applies a
rate multiplier as the odds ratio taking the league rate to `m * lg`, so a
league-average matchup in an `m` park lands on exactly `m * lg` and the
result CANNOT leave (0, 1).

That deletes the clamps rather than tidying them: they existed only because
output multipliers overflow, and clamped three different ways across four
adjacent branches. **BIT-IDENTICAL, verified by fingerprint over 400 games x
6 sims: 5bdcf78e9e70c3579220e55431c18aeb before and after.**

**AND `pa_outcome` NOW RAISES on rates that sum past one** instead of
clamping them. Clamping manufactures a plausible answer out of impossible
inputs, which is the failure mode this whole session was spent unwinding —
the clamp was an instance of the thing it was meant to guard against. Zero
occurrences in 529,581 plate appearances, so being strict is free.

## THE NEXT BUILD: ONE RESOLVED MATCHUP OBJECT — NOT STARTED

A plate appearance's inputs come from FIVE places: fields on the batter,
fields on the pitcher, a league dict threaded down through several layers,
module globals, and function arguments. Nothing owns the question "what does
this at-bat depend on?", so every new value finds its own route down and
picks whichever object is already going there.

That is not cosmetic — it caused two bugs today. `lg_cell` is a LEAGUE value
riding on a `BatterRates` because the batter was the object that happened to
flow to the right place, and `adjust_lineup` rebuilt every `BatterRates`
listing fields by hand, so it silently dropped `side` and `lg_cell` and the
matchup arm came out identical to four decimals.

WHAT TO BUILD: one object per batter-pitcher pairing holding the resolved
numbers, built by one resolver. Handedness touches the resolver. Park
touches the resolver. Role rates touch the resolver. None of them touch
`BatterRates`, and nothing constructing a batter needs to know those
features exist.

RESOLVE IT WHEN A PITCHER TAKES THE MOUND, not per plate appearance — nine
matchups once, reused for every time through the order. `sim.pa_outcome`
carries an explicit comment that per-PA object construction was REMOVED as
too expensive (~76 allocations a game in the innermost loop), so per-PA
resolution would undo a deliberate optimisation. Per-pitcher-change is
fewer allocations than today AND moves the rate lookups out of the inner
loop. Structure and speed point the same way.

Verify it the same way the odds_mult change was verified: fingerprint 400
games x 6 sims and demand an exact match before changing anything else.

## HANDEDNESS — CLOSED, AND THE SHIPPED FLAG IS HARMFUL (2026-08-27)

**READ THIS BEFORE FLIPPING `calibrate.USE_HANDEDNESS`.** It is not a
neutral null. Scored leak-free on the starters' own lines it costs +2.9 sd
on strikeouts and +9.9 sd on WALKS against handedness off, because it
shrinks each split toward the hitter's own overall rate — so a thin split
regresses to NO platoon effect, which is the one answer known to be false.

Shrinking toward the LEAGUE platoon cell for the side he bats from repairs
it (`scratchpad/platoon_fix.py`, -29.7% home runs for left-handed bats
against the shipped -16.2%, matching a counted league truth of -26%), and
the repaired version scores FLAT on every channel:

    arm                  k       bb       hr        h     (positive = worse)
    own-prior         +2.9     +9.9     +1.7     +1.6
    league-prior      +0.0     -1.0     +0.8     +0.9
    league+dev        +0.9     +4.7     +2.1     +1.3

The personal split is noise — adding it on top of the league structure costs
5.7 sd on walks. Only the structure carries anything, and the structure
scores zero.

**WHY, AND IT RETIRES THE TWO-CHANNEL FRAMING BELOW.** There is a THIRD
channel and it is the big one: ROSTER CONSTRUCTION. The manager stacked his
right-handed bats against the left-hander before first pitch, and
`opposing_lineups` feeds the simulator the nine that actually played. The
26% home run gap is real and is already expressed in WHO IS BATTING.
Applying it per hitter double counts the card.

**THE DAY'S PROCESS LESSON, three for three.** Every cheap run today
produced a false positive with exactly the shape the mechanism predicted:
the dispersion control at 6,000 paired games (+0.05, went to +0.014 at
20,000), the CRPS A/B in sample (-3.5 sd, went to +2.3 leak-free), and this
screen at 4 sims x 2 salts (-2.0 on home runs, went to +0.8 at 20 x 6). A
cheap run is for finding bugs, never for deciding.

**BANKED REGARDLESS:** `game.simulate_game(stop_after=5)`. The whole F5
objective — `side_rps` AND `total_rps` — reads nothing past the fifth, yet
every fit was playing nine innings and discarding four. 1.66x on the entire
F5 loop, verified exact by mutation, inside the noise floor at 6 salts.

## THE EARLIER SCREENS, KEPT FOR THE MEASURED NEGATIVES (2026-08-27)

The day-twelve screen measured ONE of handedness's two channels. The Toronto
card exposed the other on a live board, so it was pre-registered and run.
Both are now measured on exact per-plate-appearance splits over 9,962 games.
`scratchpad/platoon_bat.py`, output in `scratchpad/platoon_bat.out`.

    PITCHER SIDE  does THIS PITCHER have a platoon split, applied to the
                  mix he faces. `scratchpad/platoon_split.py`. +1.2 sigma,
                  0.046 K per start — 42 of 91 starters have REVERSED
                  splits and the population cancels. That result stands.

    BATTER SIDE   does THIS HITTER strike out more against a lefty, keyed
                  on the PITCHER'S hand so switch hitters fall out for
                  free. Three channels, four arms, scored against its own
                  residual AND against earned runs.

**THE STRIKEOUT CHANNEL IS DEAD, AND THIS TIME THE TEST HAD POWER.** A
perfect correction could score r +0.068 (z ~3.8); measured r is -0.024
(z -1.3), WRONG-SIGNED on all four arms, flat across quintiles, dead in the
tail. The prior-season arm agrees at +0.9. This is the channel the Cameron
case was about and it does not survive.

**THE CONTACT CHANNELS ARE RIGHT-SIGNED AND TOO SMALL TO RESOLVE.**

    channel   in-season   strict-loo   raw     prior    per start
    k          -1.3        -1.2        -1.1    +0.9     0.142 K
    babip      +2.6        +2.6        +2.7    -0.8     0.055 H
    hr         +1.4        +1.4        +0.9    +1.6     0.034 HR
    COMBINED   +1.7        +1.8        +1.7    +0.3     0.062 runs

Home runs are positive on every arm and significant on none. BABIP reads
+2.6 in-season and FLIPS to -0.8 out of sample. Against EARNED RUNS every
one of the twelve cells sits inside |z| 1.9 with inconsistent signs.

**THE COMBINED NUMBER IS THE ONE TO REMEMBER, AND IT IS NOT A NULL — IT IS
AN UNRESOLVABLE QUESTION.** All three channels as one linear-weights run
adjustment move a start by 0.062 runs of standard deviation, and the
measured r of +0.031 EQUALS ITS OWN CEILING. z +1.7 is the most a mechanism
that size can score at n=3,070. Handedness is real, correctly signed on
contact, and sits at the leverage floor (~0.05 runs) where this project
cannot tell it from nothing. Wiring it in would also be structural work —
the hand changes when the sim swaps pitchers, so it is a per-plate-appearance
lookup, not a per-lineup one. Not worth it for 0.06 runs.

**THE AGGREGATION OBJECTION WAS RAISED AND IS ANSWERED.** The screen above
collapses a start to the lineup's MEAN shift, and the simulator works per
plate appearance, so it can hold each hitter's unblended rate against the
arm on the mound. A mean cannot see dispersion, and handedness SPREADS a
lineup apart — which by convexity should raise runs. Measured directly in
the game engine (`scratchpad/hand_convex.py`, 20,000 paired games, lineup
mean held exactly fixed): even at DOUBLE the real spread it is +0.014 runs
+/- 0.018, and at real size the sign flips between the LHP and RHP arms.
Bounded at a quarter of the 0.05-run floor. Both channels are closed.

The bullpen argument runs the other way too: a lineup facing a lefty starter
sees left-handers ~60% of the game against the ~28% in their season line,
but that shift is concentrated in the STARTER'S innings, which is what the
residual screen already measured. Full-game mixes in righty relievers and
DILUTES it.

RECONCILING THE CAMERON CASE, because the anecdote was real: the lineup
shift exists. The 99th-percentile card moves 1.8 K-points shrunk and the
largest measured moved 3.6 raw — about +0.5 K on a start. What the screen
says is that the DIRECTION of that shift carries no information about how
many strikeouts actually happened. The +0.6 K I would have added to Cameron
was not justified.

BEWARE THE AGGREGATION, which is how this was nearly missed twice. The
PA-weighted vs-LHP figure coincidentally equals our simple-mean overall
figure, making handedness look like exactly zero. The sim weights the nine
roughly equally, so SIMPLE MEAN is the comparison that matters.

**TWO BUGS THE RUN SURFACED, BOTH NOW GUARDED IN THE SCRIPT.**

1. The strict leave-one-out arm reported **+6.2 sigma** on BABIP and +5.3 on
   HR. It was subtracting NOTHING: `game`'s batter-id keys stayed ints while
   `faced` was normalised to strings on the JSON round trip, so every lookup
   missed and the start sat inside its own predictor. That is the exact leak
   signature `platoon_split` documented (+4.8 -> +1.2). A leave-one-out that
   silently removes nothing is indistinguishable from a discovery, so `arm`
   now RAISES when misses outnumber hits.
2. The three channels drop different rows — babip needs balls in play where
   k and hr need plate appearances. The combine refused rather than zipping
   misaligned lists, and now joins on the start key.

**WHAT THIS SAYS ABOUT THE DEAD LIST.** Handedness was killed three times
now: the shipped A/B, the pitcher-side screen, and this. The first two were
mis-specified — a null is only as good as the channel it tested — and
re-opening was right. The third is a MAGNITUDE result, which is a different
and more durable kind of dead: it does not say the effect is absent, it says
the effect is 0.06 runs and this sample cannot see 0.06 runs. Do not
re-open it on a better mechanism; re-open it only if the leverage floor
moves or the residual gets much quieter.

**DECLINES WORKED AS DESIGNED.** BAL/STL declined twice over: first no
announced starter, then a named starter (Cooper Hjerpe) with ZERO
appearances in four seasons on disk. A debut is exactly where the market
knows things this system cannot see, and a league-average stand-in would
have produced a confident-looking moneyline indistinguishable from the ones
built on real evidence.

## STATE

* 378 checks, `make test`. New: `traffic.py` (the channel decomposition),
  `pen_prior_ab.py`, `pen_league_ab.py`, `season_gate.py`, `pool_year.py`.
* `USE_TEAM_DEFENCE` off (null), `USE_RELIEVER_LEAGUE` on,
  `USE_PRIOR_SEASON` on, `EXCLUDE_POSTSEASON` off (measured dead).

---

# Resume here — state as of 2026-08-26 (day eleven)

## WHAT CHANGED TODAY, IN ONE LINE

**A LABELLING BUG PUT 48.2% OF THE WRONG ROWS INTO THE BOUNDARY HOOK'S
TRAINING SET.** Fixed, both curves refitted, the leash rebuilt on top — and
the mean-outs defect that had been open since day six and had bounced six
mechanisms closed from 1.02 outs to 0.22.

## THE BUG, AND READ THIS BEFORE ANYTHING ELSE

`count.outs` on a play in the MLB feed is the outs AFTER it. The first play
of a game, a strikeout, reads 1. `boundary.decisions` read it as the outs
BEFORE and added one for an out event, so the SECOND OUT of every inning
came out at three and was labelled `ends_inning`.

    over 3,000 games, 129,883 starter decisions
      labelled ends_inning          56,848
      actually ends the inning      29,447
      second outs wrongly included  27,401   = 48.2%
      true boundary rows missed          0

The two populations are nothing alike. A true boundary row is a removal
11.88% of the time; a second-out row 1.28%, nine times lower. Pooled, the
set reported 6.55% — about half the real rate — and every hook ever fitted
here inherited that dilution. The mid-inning curve was missing the same
27,401 rows from the other side.

**IT IS THE POOLING RULE ARRIVING THROUGH THE LABELS.** `CLAUDE.md` already
says a hook curve must be fitted on the population it fires in and that
pooling is the default mistake — and that rule was being enforced, at the
FIT. The pooling had already happened one step earlier, in which rows were
called which. A fitted-on-the-right-population check cannot see it, because
the fit is faithfully obeying labels that are wrong.

## WHAT THE CORRECTION CHANGED

The real hazard is far steeper than anything fitted before it:

    pitches      real   pre-fix   shipped now
    60-70       0.050     0.052         0.094
    70-80       0.130     0.116         0.212
    80-90       0.353     0.235         0.400
    90-100      0.790     0.412         0.609
    100-110     0.972     0.607         0.764

Past 100 pitches managers pull 97% of the time and the old curve thought
61%. Two coefficients were not merely mis-tuned:

    parameter        pre-fix   shipped now
    per_inning       -0.1087       +0.2515   <- SIGN FLIP
    per_run          +0.0089       +0.1097   <- 12x
    per_baserunner   +0.0379       +0.0555
    pitch_scale      10.8972       12.1293

`per_inning` NEGATIVE said a manager grows LESS likely to pull as the game
goes on. That is backwards baseball, it shipped, and it survived because
half the training rows were decisions where nobody is ever pulled.

**SCORED ON OUTCOMES**, 1,040 holdout starts, leash rebuilt against the new
curves (`scratchpad/score_boundary.py`, columns legacy / shipped / pre-fix):

    RMS err on P(over), 14.5-17.5     0.0585 -> 0.0242
    RMS err on P(over), 12.5-20.5     0.0810 -> 0.0332
    discrete CRPS                     2.1760 -> 2.1013
    mean outs                          16.87 -> 16.03   (real 15.81)
    SD outs                             3.92 ->  4.03   (real 4.05)
    boundary share                     0.478 -> 0.603   (real 0.671)

Everything moved the right way at once, which almost nothing here ever does.
**The mean-outs error went 1.06 -> 0.22 and the under-dispersion is
essentially gone.** Both were on the "structural, unfixable at this form"
list as of this morning.

WITH THE LEASH OFF the band metric still prefers the pre-fix curve (0.0267
against 0.0632). That configuration is not what ships and is no longer a
clean test either way: the leash offsets are residuals against whatever hook
they were built on, so the old leash was quietly absorbing 0.4 outs of
under-pulling. Rebuild the leash whenever the hook moves.

## WHAT THIS RETRACTS

* **The whole "boundary curve under-pulls because the LINEAR FORM is wrong"
  line, days nine through eleven.** It under-pulled because it was fitted on
  diluted rows. A non-linear pitch term may still help — the corrected curve
  still gives 0.609 where reality is 0.790 at 90-100 — but the premise that
  sample size was eliminated and the form was the culprit is void.
* **"The hook is just pitch count."** Measured this morning on the bad rows,
  where `per_run` came out +0.008. On correct rows it is +0.110. The
  pitch-only experiment (`scratchpad/fit_pitchonly.py`) and everything said
  about those terms being inert are withdrawn.
* **The early-exit mixture** (`scratchpad/fit_survivors.py`, `Hook.
  early_exit_p`, `EARLY_EXIT_DIST`) was fitted on the same bad rows. The
  MECHANISM is built, wired and guarded; the NUMBERS are void. It ships
  inert. Re-run the fit before believing anything about it.
* Day eleven's first boundary table and its "model-free confirmation" — both
  counted on mislabelled rows.

## PITCH COUNT ALONE, RE-TESTED ON CORRECT ROWS — AND IT SPLITS BY CURVE

This morning's pitch-only test was withdrawn because it ran on the bad rows.
Re-run on correct ones it comes back, but with a different and much more
useful answer: **the two curves disagree about whether the extra features
matter.**

    per-decision AUC        full   pitch-only
      boundary            0.9135       0.9132   <- the same decision
      mid-inning          0.9151       0.8894   <- not remotely

The END-OF-INNING decision is essentially pure workload. The MID-INNING
decision is a rescue and traffic genuinely predicts it. That is the two-hook
split arguing for itself from a direction nobody looked from.

On OUTCOMES, leash on, 1,040 holdout starts:

                          legacy    full  pitch-only  pre-fix   real
    band RMS 14.5-17.5    0.0493  0.0242      0.0081   0.0585
    band RMS 12.5-20.5    0.0503  0.0332      0.0239   0.0810
    discrete CRPS         2.1212  2.1013      2.0831   2.1760
    mean outs              15.77   16.03       16.18    16.87  15.81
    SD outs                 4.21    4.03        3.72     3.92   4.05

Pitch-only is near-exact at the lines that carry 91% of the board and too
NARROW — 3.72 against a real 4.05. The likely mechanism is visible in the
AUC table: zeroing the mid-inning traffic terms means nobody gets yanked in
a blow-up, so the short tail thins out.

**THE HYBRID — pitch-only boundary, full mid-inning — WAS RUN AND IS A
NULL.** Half the prediction held and the informative half did not:

                          full  pitch-only  hybrid   real
    band RMS 14.5-17.5  0.0242      0.0081  0.0239
    discrete CRPS       2.1013      2.0831  2.0932
    SD outs               4.03        3.72    4.04   4.05

The SPREAD came back exactly as predicted (3.72 -> 4.04), which CONFIRMS the
mechanism: the mid-inning traffic terms are what produce the short tail, and
without them nobody gets yanked in a blow-up. Worth keeping as a mechanism
finding even though the arm loses.

But the hybrid did NOT inherit pitch-only's 0.0081 band accuracy — it lands
on the full curve's 0.0239. So that number was a property of the whole
configuration and NOT of the boundary curve, which is what the hybrid was
built to test. It is a wash against the full hook on every column.

**AND PITCH-ONLY'S HEADLINE IS BOUGHT WITH DISPERSION.** SD 3.72 against a
real 4.05 is an overconfident distribution, and its CRPS advantage REVERSES
with the leash off (2.2195 against the full curve's 2.2149) while the full
and hybrid curves hold. A near-exact P(over) at central lines is achievable
from a distribution that is too narrow and correctly centred — aggregate
calibration at four lines is a weak constraint on shape.

**VERDICT: nothing ships. The full corrected hook stands.**

## THE EARLY-EXIT MIXTURE, REFITTED AND SCORED — NULL, AND IT REPEATS DAY SEVEN

Re-fitted on correct rows (14.45% of starts end under 12 outs; the lump now
peaks at 3, 6 and 9 outs — whole innings — where the pre-fix version peaked
at 4, 7 and 10, which is the off-by-one showing through). Scored, leash on:

                          full  mixture   real
    band RMS 14.5-17.5  0.0242   0.0270
    band RMS 12.5-20.5  0.0332   0.0262
    discrete CRPS       2.1013   2.1555
    mean outs            16.03    15.55  15.81
    SD outs               4.03     4.45   4.05
    boundary share       0.603    0.640  0.671

It wins on boundary share and on the WIDE band, and loses on CRPS and on
dispersion — SD 4.45 against a real 4.05.

**THAT IS DAY SEVEN'S FAILURE MODE TO TWO DECIMAL PLACES.** The
`early_innings` branches fixed the disaster tail and pushed SD to 4.47
against a real 3.99, and ship off for exactly that reason. A different
mechanism aimed at the same target has now bought the same thing with the
same currency.

**THE DIAGNOSIS, and it is what makes this informative rather than another
null.** The lump is drawn UNCONDITIONALLY — every start gets the same 14.45%
chance of falling apart — so a good pitcher is handed a three-out disaster at
random. That adds variance without adding information, which is precisely
dispersion bought for nothing.

And it cannot fix the defect that motivated it. Item 0 says the SHORT end is
over-predicted by half an out; a uniform lump shortens EVERYBODY equally. The
quantity actually needed is more short starts for the pitchers who really
have them — conditional on the pitcher, not on the league.

**SO THE NEXT MOVE IS THE PER-PITCHER ONE.** The leash already carries
per-pitcher length, is already fitted as a residual, and is already shrunk —
`MIN_PRIOR` 5, K ~14.8 starts. If the short end is over-predicted while the
top two quintiles are exact, the suspect is asymmetric shrinkage at the
bottom rather than a missing mechanism. That is measurable the way
`stabilise.py` measures anything, and it needs no new data.

## THE ERA FINDING SURVIVES, and is cleaner

Refitted per season on correct rows, the boundary curve is still not one
curve across four seasons:

    parameter        2023     2024     2025     2026
    pitch_scale    22.449   16.187   11.763   12.614
    per_inning     +0.486   +0.434   +0.270   +0.230

Counted hazard, per season, and the trend is in the data not the fit:

    bucket      2023    2024    2025    2026
    0-60       0.025   0.018   0.014   0.017
    90-100     0.753   0.792   0.811   0.814
    100-110    0.970   0.976   0.962   0.985

2025 against 2026 still agrees (mean |z| 1.48 over six terms). 2023 and 2024
are a different manager: softer early, softer at 90-100. Note 100-110 is
FLAT across all four — everybody pulls past 100 now, and always did.

And the sign flip I attributed to collinearity this morning was the bug:
`per_inning` is positive in every season once the rows are right.

**THE TRAP THIS STILL CREATES.** `fit_boundary.collect()` takes everything in
`.cache/pbp`, which is now four seasons. Re-running it pools two eras and
flattens `pitch_scale` to 15.30. What ships is the 2025+2026 fit.

## ALSO SHIPPED TODAY — THE K PRIOR

`rates.USE_PRIOR_SEASON = True`, `PRIOR_SEASONS = 3`, `PRIOR_DECAY` per stat
(k 0.3, bb 0.5, hr 0.7, babip 0.0). Untouched by the hook bug — it is rates,
nowhere near play-by-play outs. Full detail below under SHIPPED — THE PRIOR.

## SHIPPED — THE PRIOR IS ON

`rates.USE_PRIOR_SEASON = True`, `PRIOR_SEASONS = 3`, `PRIOR_DECAY` per stat.
This was day ten's "ONE THING TO SHIP" and it was blocked on one number.

    THE DECAY, measured by `scratchpad.decay`, three readings that disagree:

    1. LAG CORRELATION, disattenuated for sampling noise with the counted
       STABILISE constants. K% carries 0.773 / 0.661 / 0.599 at one, two and
       three years — a slow fade, about 0.88 a year on the talent itself.
    2. JOINT REGRESSION on arms with all three lags: 0.78 / 0.10 / 0.12.
       Last season dominates once you condition on it.
    3. THE BLEND SWEEP, which is the estimator itself and the one to trust:
       K 0.645 -> 0.651 at w=0.3, BB 0.523 -> 0.542 at w=0.5, HR 0.236 ->
       0.247 at w=0.7, BABIP monotonically down so it gets 0.0.

Readings 1 and 3 disagree because they ask different questions — how much a
season carries ALONE, against how much it adds ON TOP of a fresher one. Both
are true. The shipped weights come from 3.

**SCORED ON OUTCOMES, paired, `scratchpad.memory` with a fourth arm:**

    cut 2026-05-01       none    prior(1)   prior(3)
      K correlation    0.3342     0.3843     0.3854
      K CRPS           1.3467     1.3195     1.3117
      outs CRPS        2.1667     2.1799     2.1620
      K bias          +0.0867    +0.1360    +0.1348

Three seasons beat one on OUTS, which is the surprise: outs CRPS is better on
all five runs (both cuts, four July seeds) and outs correlation on four of
five, while K is a wash beyond what one prior season already gives. **This
corrects day ten's "more data helps strikeouts, does nothing for outs" —
more DEPTH of prior helps outs; it was flat POOLING that did not.**

THE COST IS ACCEPTED, NOT UNNOTICED: K bias +0.087 -> +0.135, and mean outs
about +0.04 in the wrong direction against a defect already 0.7 too high.

**THE FLAG ON ITS OWN REACHED NOTHING, and that is the third time.** Only the
experiment ever called `set_prior`, so `USE_PRIOR_SEASON = True` would have
left `_PRIOR` empty and every rate shrinking to the league exactly as before.
`pitcher_rates` now loads it lazily through `_ensure_prior`, with a
re-entrancy guard because `set_prior` builds the prior by calling
`pitcher_rates`. Guarded by two checks in `test_wiring.py`, not one — see the
traps.

## POOLING GOT WORSE WHEN THE SEASONS ARRIVED

Unplanned, and it corroborates both results above. `memory.py`'s `pool` arm
degraded against its own day-ten record with no code change — K correlation
0.3956 -> 0.3679, K bias 0.2643 -> 0.3081. `scope.ALL_SEASONS` is an
unfiltered query, so on day ten it pooled two seasons and today it pools
four. `none` and `prior` reproduce to four decimals across the two runs,
which is what makes the attribution safe.

**Flat pooling degrades as history is added; a decayed prior does not.** Same
statement the decay makes from one side and the era shift from the other.

## PLAYOFF GAMES — CHECKED, AND ONE PLACE THEY DO BITE

User's flag, and the asymmetry is real: 2023 has 56 October-or-later games,
2024 and 2025 have 43, 2026 in progress has none.

RULED OUT for the boundary result — 2,375 of 192,347 rows, and every
coefficient holds (`--regular`): 2023 `pitch_scale` 17.21 -> 17.31, 2025
10.54 -> 10.53.

NOT RULED OUT for the rates the prior is built from. Excluding October moves
K% by more than half a point for about 8% of arms, up to 3.1pp, and always
the same way — a playoff pitcher's season K% is DRAGGED DOWN by facing
playoff lineups:

    Aroldis Chapman 2023   0.3833 -> 0.4143
    Kris Bubic 2024        0.2917 -> 0.3197
    Daniel Palencia 2025   0.2667 -> 0.2913

The league adjustment in `_prior_adjusted` partly absorbs this because
`sim.league(yr)` carries the same drag, but only partly: the league's
postseason share is ~2% while a contender's ace runs 10%+. So it lands
hardest on exactly the arms worth pricing. **The current season has no
postseason, so this biases the PRIOR against the CURRENT line, one
direction.** Unfixed — a `game_type` filter in `_where` would do it, and it
changes shipped rates globally, so it wants its own before/after digest.

## WHAT TO DO NEXT

0. **THE SHORT END IS OVER-PREDICTED.** New today. The slope of actual on
   predicted outs is 1.181 (z 3.4), which reads as compression — but the
   quintile breakdown says it is one-sided and it is NOT at the top:

       quintile   predicted   actual     gap
       1              14.20    13.75   -0.45
       2              15.25    14.74   -0.52
       3              15.92    15.71   -0.21
       4              16.59    16.65   +0.06
       5              17.63    17.57   -0.05

   The top two quintiles are exact. The bottom two run half an out long.
   **We do not produce enough genuinely short starts for the pitchers who
   have them**, which is the same conclusion the bimodality argument reaches
   from the other side, and it makes the EARLY-EXIT MIXTURE the best-aimed
   unfinished thing in the project rather than a nice idea.

   NOTE THE FIRST READING OF THIS WAS WRONG IN A WAY THAT WOULD HAVE COST A
   DAY. `between.py` reports a POSITIVE correlation between predicted outs
   and its own residual, which reads naturally as "the arms we think go deep
   go deeper still". The correlation is positive under either shape; only
   the quintile table says which end carries it. **A signed correlation
   does not locate an error. Bucket it before believing you know where it
   lives.**

   Other stats for reference: k slope 1.074 (z 2.3, mild), er 0.775
   (z -2.5, predictions too WIDE), h 0.991 and bb 0.914 both fine.
1. **RE-MEASURE EVERYTHING.** The hook moved further today than on any day
   of this project, and the prior went on underneath it. Every baseline in
   this file predates both. `scope_baseline.py` and `scratchpad/battery.sh`
   exist for exactly this and nothing else should be trusted until they run.
2. **Re-run the early-exit mixture fit** on correct rows and score it. The
   mechanism is built, wired and guarded; only the numbers are void. It is
   the best-motivated idea currently unscored — real starts are bimodal, one
   logistic cannot be, and the corrected curve STILL gives 0.609 where
   reality is 0.790 at 90-100.
3. **Re-open the non-linear pitch term** against corrected rows. The old
   conclusion is void but the residual it was aimed at is still there.
4. **Scope the hook fit to 2025+2026 in code** so a future run cannot pool
   the older era by accident.
5. **The traffic deficit.** Note the mean-outs half of it may have just been
   this bug — re-measure before spending another day on it.
6. **`fitf5`** still has never been re-run. Now genuinely unblocked and the
   engine underneath it has changed twice.
7. **The postseason filter on rates**, with a digest either side.

## DOES THE HOOK BUG RE-OPEN THE DEAD LIST? MOSTLY NO, AND SAY WHY

The question is the right one to ask and the blanket answer is wrong, so the
distinction is recorded here rather than left to judgement.

**NO for most of the list.** The bug corrupted WHEN A STARTER IS REMOVED.
Handedness, park, day/night and arsenal change how BATTERS DO against him,
not what the manager decides, so a broken hook was never hiding them. More
decisively, six of the nine were scored against GAME TOTALS, where ~96% of
the variance is irreducible and the ceiling on correlation is about 0.19 —
those nulls were uninformative before today and are equally uninformative
now. Re-running park factors against a game total will waste a day.

**YES for anything judged on STARTER LENGTH.** The mean was a full out high
and the curve under-pulled badly past 90 pitches, so any feature scored on
"did outs improve" was measured against a broken yardstick. Two specific
candidates, both with a real mechanism:

  * **CLUB PATIENCE.** Dead six times, every time as a residual against a
    hook whose inning coefficient had the WRONG SIGN. A manager effect is
    exactly the shape of thing that hides inside that error.
  * **BULLPEN AVAILABILITY.** Hook-adjacent by construction. Removals now
    happen at the right rate and the right time, so "who is rested" reaches
    the game in a different state than it ever has.

The standing rule already covers this — the dead list records HOW a thing
was tried, not that it is unknowable, and re-opening is legitimate when the
APPROACH or the DATA changes. Today the data changed for one subset of it.

## CLUB PATIENCE, RE-OPENED AGAINST THE CORRECTED HOOK — STILL MARGINAL

Seventh look. Residuals regenerated on the corrected engine
(`scratchpad.ceiling - 40`), then `scratchpad.between outs`:

    group             LOO r   outs it could remove   split-half   z
    pitcher          +0.141                  0.52*       -0.533  -6.1
    club (manager)   +0.078                  0.29*       +0.318  +1.7
    venue            +0.006                  0.02        -0.595  -3.6

The club clears the build bar on leave-one-out (0.29 against the ~0.20 rule
of thumb) and its split-half is POSITIVE for the first time — but at z 1.7
on thirty clubs, which is not a result. **Verdict: not resurrected, not
dead. It is the one dead-list item the hook fix genuinely changed the
evidence for, and it deserves a proper nested fit rather than another
screen.**

NOTE THE PITCHER SPLIT-HALF IS -0.533. That is not a finding about
pitchers, it is the LEASH: these residuals have full-season per-pitcher
offsets already applied, so the pitcher signal is absorbed and slightly
over-absorbed. It is the right conditioning for asking what the CLUB adds on
top, and the wrong number to quote for anything else.

## THE CONTROL IS FAILING, AND THAT IS THE BIGGER FINDING HERE

`between.py` carries `predicted outs` as a CONTROL: it already feeds the
simulation, so a large correlation with its own residual means the model is
mis-using what it already has.

    predicted outs    r +0.060   z +3.4   0.22 outs

Above the 0.20 bar, and POSITIVE — when the model predicts a longer start,
the actual comes in longer still. **Our predictions are compressed at the
top end: the arms we already think go deep, go deeper than we say.** That is
consistent with the headroom table (our spread 1.31 against 1.60 of real
between-start variation) and it is a shape defect in the predictions
themselves rather than a missing feature. Nothing on the dead list can fix
it and no new data is needed.

`opp K% (model)` fails the same way at 0.21, and it is also an input we
already have.

## THE SHRINKAGE CONSTANTS ON FOUR SEASONS — NO CHANGE, AND A TRAP

`src.context.stabilise` has no season filter, so with four seasons on disk
it now pools them. Its output looks like a legitimate re-measurement on more
data and it is not the same quantity:

    pitcher    k_pct   bb_pct   hr_pct        batter    k_pct   bb_pct
    2023          85      147      677        2023          34       65
    2024          73      133      647        2024          33       96
    2025          59      174      713        2025          33       70
    2026          57      116     1086        2026          32       80
    SHIPPED       57      138      934        SHIPPED       32       80
    POOLED       132      167     2363        POOLED        51      121

The pooled numbers are inflated across the board because the ODD/EVEN SPLIT
NOW SPANS YEARS: a player who changes between seasons reads as unreliable,
and the method cannot tell that from noise. The code shrinks a
CURRENT-SEASON rate, so the reliability has to be measured within a season.
Conditioning must match the code path — the rule was already written down;
this is what violating it looks like when nothing errors.

**Had this been taken at face value it would have over-shrunk every player
rate in the model — batter k 32 -> 51, pitcher k 57 -> 132 — and separation
is the only thing generating differences between clubs.**

MEASURED PER SEASON, THE SHIPPED VALUES STAND. Batter constants are
strikingly stable (34/33/33/32 on k) and 2026 sits on the mode. Pitcher
k_pct carries a real downward trend, 85 -> 57, which is worth knowing and
does not change what to ship: 2026 is the season being priced.

## THE ERA GATE, RUN ON TWO MORE CONSTANTS — AND THEY DISAGREE

`scratchpad/season_gate.py` — one single-core pass over 9,962 games doing
both, because neither module forks and two walks would be two walks for
nothing.

**TTO PASSES. Pooling is allowed.** K% at the third pass relative to the
first: 0.852 / 0.837 / 0.848 / 0.812 across 2023-2026. The 2026 figure is the
steepest and sits about 1.5 sigma from the other three on ~17,000 plate
appearances — not a distinguishable season. So the shipped multipliers, which
were measured on 2026 ALONE, are the noisiest of the four estimates of a
quantity that holds still.

NOT UPDATED, deliberately. The shipped constants are RE-CENTRED to a
PA-weighted mean of 1.0 and the module prints multipliers relative to pass 1.
Converting between the two by hand is exactly the arithmetic that
`int(round(PITCH_COST))` was lost in — a constant can be right, reached, and
destroyed in transit. Take the re-centred form from the module's own code
path, not from a calculator.

**THE DOUBLE-PLAY RATE FAILS. Pooling is not allowed**, and `GIDP_RATE` is
now 2025+2026 only — 0.2131 and 0.2305 against the 0.209/0.224 measured on
2026 alone. Full table in `sim.GIDP_RATE`'s docstring. The 0-out rate steps
0.230 -> 0.213 between 2024 and 2025, about 3.3 sigma.

**NOTHING GUARDED `GIDP_RATE`.** It was changed and all 360 checks stayed
green. `check_the_double_play_rate_is_the_current_era_not_the_pooled_one`
now pins it as a BAND — wide enough that a genuine re-measurement is free,
narrow enough to exclude the pooled and legacy values. Mutation-verified
against the 2023/24 rate.

## THE POSTSEASON FILTER — BUILT, MEASURED, DEAD

The hypothesis was right and the correction still loses. A playoff pitcher
faces playoff lineups, so excluding October moves his K% by up to 5.3 points
and always the same way; and because the CURRENT season has no postseason,
that bias enters the prior and never the line it is shrunk against. A real
asymmetry, correctly identified.

Scored on whether a prior season predicts the NEXT season, 150+ batters
faced in both:

    lag  stat      n    with post   without     delta
    1    k_pct   275       0.7536    0.7491    -0.0045
    1    bb_pct  275       0.7048    0.6960    -0.0088
    1    babip   275       0.4805    0.4761    -0.0044
    2    k_pct   209       0.6494    0.6490    -0.0004
    2    bb_pct  209       0.6108    0.6066    -0.0042
    2    babip   209       0.1784    0.1603    -0.0181

**Six for six against.** Removing a real bias costs more than it saves when
the bias is small and lives in 10% of the record — playoff innings are still
innings against major-league hitters, and dropping them just makes the line
noisier. `EXCLUDE_POSTSEASON` ships OFF and is pinned with the table.

**THE DATES ARE TRANSCRIBED, NOT INFERRED, and that is the durable part.**
The obvious rule — "October onward, fewer than eight games that day" — is
wrong at both edges, invisibly:

    2025-09-30   the WILD CARD ROUND, and a month test misses it entirely
    2024-09-30   two REGULAR-season makeup games deciding a playoff place,
                 which a game-count test throws away
    2023-10-01   a fifteen-game regular-season slate sitting in October

`POSTSEASON_RANGE` carries the boundaries per season, checked against the
day-count shape either side. 131 games, 1.31%. **2026 is untouched by the
filter, which is the asymmetry stated as a measurement.**

## TEAM DEFENCE — BUILT, RESTRUCTURED, AND A NULL. READ THE RETRACTION.

**RETRACTED: an earlier version of this section reported team defence as the
first thing in days to move the runs, CRPS 1.66361 -> 1.65541. That number
was a DOUBLE-COUNTING BUG.** Correctly implemented the sign flips:

                     CRPS   runs     sd  shutout  5+ runs  covered5
    defence OFF   1.63913   2.34   2.21    22.6%    15.5%     69.3%
    defence ON    1.64324   2.35   2.21    22.2%    15.4%     69.5%
    ACTUAL                  2.44   2.32    21.9%    17.6%     74.0%

`USE_TEAM_DEFENCE` ships OFF.

**WHY IT CANNOT WORK THE WAY IT WAS SOLD, and this is the durable lesson.**
Defence has two jobs and they are opposite:

    rates       NEUTRALISE his own club's gloves out of his observed BABIP
    build_side  APPLY tonight's club, once, to the whole pitching side

For a pitcher who stays with his club that is a ROUND TRIP — add the defence
out, put the same defence back, cancel. The mechanism only bites through the
SHRINKAGE (a thin line is neutralised, pulled toward the league, then has
defence re-applied, which is not the same as shrinking the raw rate) and on
TRADED pitchers. Both are small.

So the 0.034 of BABIP between the best and worst defence is real and is
ALREADY IN THE PITCHERS' OWN RATES. They have been throwing in front of those
gloves all season. **An OAA spread is not headroom; it is mostly a
description of something the model already has.** The same logic will apply
to any club-level factor a player's own line already absorbs — ask what is
LEFT after the player's rate before sizing the prize.

**THE STRUCTURE IS STILL RIGHT AND STAYS.** Defence belongs to the SIDE IN
THE FIELD, not to the pitcher's history — attached per pitcher it had to be
applied once per code path and reached starters only. `defence_delta` is now
one function used in both directions, and `build_side` applies it to every
arm that takes the mound.

**TWO BUGS FOUND BY MUTATION IN ONE HOUR, both in code written that hour:**

  * Deleting the NEUTRALISATION left every check green while `build_side`
    applied a defence on top of a rate that already contained one — the
    `NEUTRALISE_PARK` error reproduced within a day of it being quoted as a
    cautionary tale. Now guarded.
  * The `rate_src` import into `game.py` silently did not land, because the
    pattern matched did not exist in the file. 53 checks failed at once,
    which is the good failure.

## WHAT DID SURVIVE FROM THIS — THE BULLPEN GOT THE SHRINK TARGET

Separate from the defence result and NOT retracted. `bullpens()` carried a
COPY of the rate block with `lg[stat]` hardcoded, so no reliever ever saw the
multi-season prior — including the one shipped the same day. Relievers are
the population where it matters most:

                        median BF   weight on his own K%   from the target
    relievers                 106                   0.62               38%
    starters (300+ BF)        480                   0.89               11%

401 of 435 relievers move once the shared target reaches them — Mason Miller
0.4091 -> 0.4418, Edwin Diaz 0.2454 -> 0.2923, elite arms that were being
dragged to league average on thin current lines. `shrink_target` is now one
function serving both populations so the next improvement cannot reach half
the pitchers.

**AND IT IS THE LARGEST MEASURED GAIN OF THE DAY ON THE PRODUCT**
(`scratchpad/pen_prior_ab.py`, paired, 1,152 sides, relievers isolated —
starters see the prior in both arms):

                          CRPS   runs     sd  shutout  5+ runs
    pen: league only   1.66361   2.34   2.22    22.6%    15.6%
    pen: prior         1.63913   2.34   2.21    22.6%    15.5%
    ACTUAL                       2.44   2.32    21.9%    17.6%

CRPS -0.0245, about 5 sigma against the +/- 0.0043 `fitf5` reports on this
sample, and three times the size of the team-defence number that turned out
to be a bug.

CROSS-CHECKED BY ACCIDENT, which is the reason to trust it: the
pre-restructure `defence OFF` arm scored 1.66361 and the post-restructure one
1.63913. That drift was assumed to be run-to-run noise and is in fact this
fix landing in between — two independent measurements of the same quantity
agreeing to five decimals.

IT SHARPENS THE SHAPE AND DOES NOT TOUCH THE LEVEL: runs 2.34 either way
against a real 2.44. The bullpen throws ~40% of the innings and was being
priced as generic; knowing which arm is which is worth a lot of distribution
and no runs. **The 5%-light defect remains untouched by everything tried on
day eleven.**

**AND THE STABILISE CONSTANTS HAVE THE SAME DEFECT ONE LEVEL DOWN.**
`stabilise._PIT` filters `is_starter = 1`, so every pitcher constant was
measured on STARTERS and is applied to relievers. Measured separately, k and
bb agree between the populations; HR looks very different (relievers 241-460
against starters 713-1086) but the reliever reading is not trustworthy — 219
players, r_half 0.168, and it swings 2x between seasons. Identified,
unresolved, and it needs per-season measurement within population.

## POOL WITH A YEAR TERM, OR CUT? TESTED — IT DEPENDS ON THE SHAPE

The gate as applied above says "if the seasons differ, use only the recent
ones", which spends data to avoid a bias. The alternative is to keep every
season and model the drift. `scratchpad/pool_year.py` tests it on the
boundary curve, held out on the last 30% of 2026:

    arm                train n   log loss      AUC
    pooled+year         91,475    0.20544   0.9192
    era (25+26)         39,565    0.20559   0.9191
    recent (26 only)    13,678    0.20636   0.9190
    pooled, NO year     91,475    0.20706   0.9182

**IF YOU POOL, YOU MUST MODEL THE DRIFT.** The year term moves naive pooling
from worst to best, 0.20706 -> 0.20544, and that gap is ten times the gap
between the winner and the era cut. Naive pooling is the mistake; the year
term is the fix.

**BUT IT BUYS ~NOTHING OVER THE ERA CUT** — 0.00015 on 6,079 test rows is
noise. Not re-shipped: it would cost a refit and another leash rebuild for a
gain inside the error bar. Note also that cutting to 2026 ALONE is worse
than 25+26, so 2025 genuinely earns its place.

A YEAR DUMMY WOULD NOT HAVE WORKED. The drift is in the SLOPE —
`pitch_scale` 22.4 / 16.2 / 11.8 / 12.6 — so year is interacted with every
term and centred on 2026, which makes the interactions vanish at prediction
time and the main effects ARE the 2026 curve.

**AND IT REVERSES FOR THE DOUBLE-PLAY RATE, because that drift is a STEP
rather than a trend**: 0.230 / 0.230 / 0.213 / 0.213. A linear year term
predicts 2026 at 0.2112 against an actual 0.2129, while the era mean gives
0.2131 — a straight line through a step lands between the two levels and
does worse than simply using the current one.

    gradual drift  -> pool everything, interact with year
    step change    -> cut, and use the current era
    method breaks  -> neither (see the shrinkage constants)

**THE GENERAL RESULT IS THAT THERE IS NO GENERAL RESULT.** Three quantities
gated today: the hook FAILS (2023/24 is a different manager), the double-play
rate FAILS, TTO PASSES, and the shrinkage constants cannot be pooled at all
because the method changes meaning. Each has to be asked separately.

## THE REFITS THAT ARE NOW OUTSTANDING

Everything below was measured on an engine that no longer exists. Grouped by
why, because the reasons differ and so does the urgency.

    INVALIDATED BY THE HOOK FIX
      calibrate --tune            fitted against the old curves
      the early-exit mixture      built today, fitted on the bad rows
      the non-linear knee         now BETTER motivated, see the hazard table
      hook_leash.json             rebuilt once today; rebuild after ANY
                                  hook change, it is a residual

    NEVER RE-RUN SINCE THE CROSSED-LINEUP FIX, TWO ENGINES AGO
      fitf5                       the actual product, and still unmeasured

    MEASURED ON 2026 ALONE, FOUR SEASONS NOW ON DISK
      stabilise  DONE — no change, and running it naively is a TRAP. See
                 below.
      tto, advance, inherit, relief, deploy
      -> UNRUN, and do NOT run them naively either. Every one of these
         queries "all games on disk" with no season filter, so what they
         measure changed silently when the history landed. Establish what
         the pooled version is actually measuring BEFORE reading its
         output.

    NEVER DONE
      (the postseason filter is DONE and DEAD — see below)

## TRAPS ADDED ON DAY ELEVEN

**A FIXTURE THAT SHARES THE CODE'S MISUNDERSTANDING GUARDS NOTHING.**
`tests/test_boundary.py` built its plays with `count.outs` set to the outs
BEFORE the play, exactly as the module read it. Twelve checks agreed with
each other and none with the feed, and they all passed for the life of the
bug. `tests/test_pbp.py` and `tests/test_inherit.py` had it right the whole
time — their fixtures name the field `outs_after`. **When two test files
disagree about what a field MEANS, that is a finding, not a style
difference.**

**A CHECK CAN PIN A CONTAMINATED FACT.** `check_the_boundary_curve_is_the_
fitted_one` asserted the shipped curve against a "real 70-80 rate of 0.074".
Counted correctly it is 0.130. The check was doing its job perfectly against
a number that was wrong. Pins are only as good as the measurement behind
them; when a measurement is corrected, re-read every check that quotes it
rather than just the ones that fail.

**AN AGGREGATE THAT MATCHES REALITY CAN STILL COME FROM THE WRONG ROWS.**
The simulated boundary SHARE was validated at 66.3% against a real 65.7% on
day seven and that agreement was real — it just said nothing about whether
the right decisions were in the right bucket. The share is a ratio the
engine produces; the labels are an input to the fit.

**A MARGINAL RATE CAN BE STABLE WHILE THE CURVE UNDER IT IS NOT.** Four
seasons agree on the boundary pull rate to within 0.0013 and disagree on
`pitch_scale` by 63%. Compare the parameters that ship, with standard errors,
not the aggregate they produce.

**AN AGREEMENT TOO CLOSE FOR THE STANDARD ERRORS IS PLUMBING, NOT
STABILITY.** Pre-registered in `split_boundary.py` as the third possible
outcome, alongside agree and disagree, so a suspiciously clean result is loud
instead of reassuring. It did not fire, but it is the reason the standard
errors are computed at all.

**THE COVERAGE TRAP IS EASY TO REBUILD INSIDE A NEW SCRIPT.** Day ten
recorded it; day eleven put it straight into `decay.py`'s sweep, where w=0
zeroes every weight for a pitcher with no last season and silently drops him
from that arm alone. It reversed the answer — unpaired said w=0 for
everything, paired says 0.3/0.5/0.7. Intersect first, every time.

**A DECAY APPLIED AGAINST THE CALENDAR DELETES THE PEOPLE IT IS FOR.** The
lag must be relative to the PITCHER'S OWN most recent season. Against the
calendar, a man back from an elbow gets weight 0 on every stat whose decay is
0.0 — BABIP's is — and drops out of the prior entirely. Caught by mutation,
not by reading.

**TWO CHECKS I WROTE TODAY GUARDED NOTHING**, both found by mutation and both
in the same shape: they asserted the thing they set up. One compared source
LINE ORDER for the `_PRIOR` clearing and passed with the bug reintroduced;
one populated `_PRIOR` by hand and passed with the lazy load torn out. Each
was replaced with a behavioural check that stubs the collaborator and asserts
what it was ASKED, and only then did the mutations fail.

**A MUTATION LOOP NEEDS A TIMEOUT LONGER THAN THE SUITE.** Five mutations x a
38s suite exceeded a two-minute limit and the loop was killed with `rates.py`
still mutated — the SIGKILL-between-mutate-and-restore case already recorded
in the notes, reproduced by a tool limit rather than a signal. The backup was
outside the tree, so recovery was clean. Verify the restore by grepping for
the shipped value, not by re-running the suite.

## STATE

* 358 checks, `make test`, ~36s. `tests/test_prior.py` is new (10),
  `test_wiring.py` gains 4 and `test_regressions.py` 1. Thirteen
  mutation-verified — five against `_blend_priors`, five against the prior's
  wiring and flags, and the `count.outs` regression, whose first mutation
  CRASHED rather than mislabelled and had to be rewritten to reintroduce the
  original bug faithfully. A mutation that errors is not a mutation that
  proves the check.
* New tools: `scratchpad/split_boundary.py` (per-season boundary fit with
  standard errors, out-of-sample cross-scoring, `--regular` to drop the
  postseason) and `scratchpad/decay.py` (three readings of how long a
  pitcher stays himself). `memory.py` gains a `prior3` arm, `--seed=` and
  `--cut=`.
* `/tmp/boundary_rows_by_season.json` caches 192,347 season-tagged boundary
  decisions over 9,962 games. `/tmp/boundary_rows.json` is the STALE
  day-ten cache — 4,663 games, 2025+2026 only.

---

# Resume here — state as of 2026-08-26 (day ten)

## WHAT CHANGED TODAY, IN ONE LINE

Three prior seasons loaded, and the split it exposed is the finding: MORE
DATA HELPS STRIKEOUTS, DOES NOTHING FOR OUTS, AND DOES NOT REACH TOTALS.

## THE ONE THING TO SHIP

**Last season as the PRIOR, not as pooled data.** Built, measured, and OFF
behind `rates.USE_PRIOR_SEASON`. It needs one number — the decay weight —
and 2024/2023 are loading to measure it.

    cut 2026-05-01        none      pool     prior
      K correlation     0.3342    0.3956    0.3843
      K bias            0.0867    0.2643    0.1360

Pooling buys +0.061 of correlation for +0.178 of bias; the prior buys +0.050
for +0.049. About 80% of the gain for under 30% of the cost, and at the July
cut the prior has the best K CRPS of the three outright.

IT IS NOT A NEW MECHANISM. `_shrink` already blends a thin line toward the
league; this aims it at the pitcher's own last season. Chapman at 39 batters
faced was being dragged to 0.2539, near league average; his own prior puts
him at 0.3220. It decays on the calendar for free — April leans on the
prior, August swamps it — which is the same May-to-July decay the pooled
test found from the other side. Two stages, so a thin prior cannot shout
down the evidence behind it, and league-adjusted first because home runs are
up 7% between the seasons.

## WHAT THE DATA DID NOT FIX

**OUTS. Sixth mechanism to bounce off it.** Memory: +0.001 and -0.009 on
correlation. And the pooled hook refit on **89,983 boundary decisions** —
2.3x every fit this project has ever done — moved the coefficients almost
nowhere (`pitch_scale` 10.897 -> 10.671) and reproduced the identical
failure: 0.114 fired where reality is 0.081 at 70-80, 0.610 against 0.734 at
100-110. SAMPLE IS NOW ELIMINATED as the explanation for the tail
undershoot. The linear form's failure is structural.

**TOTALS.** game RMSE 4.556 / 4.560 / 4.602 across the three arms, F5 3.278
/ 3.236 / 3.274. Inside noise. A team total is two bullpens and eighteen
half-innings, so a sharper starter K rate cannot reach it.

## THE TRAFFIC DEFICIT NOW HAS TWO SIGNATURES

Starter outs run about **+1.0 high** and total runs about **-0.5 light**, at
every cut under every arm. One defect from both ends: too few men reach
base, innings end too cleanly, so starters last longer AND fewer runs score.
This is the live hypothesis for outs, and it is not a data-volume problem.

## SEASONS: HOW THEY ARE TREATED

`context/scope.py`. Default is THIS season; `scope.ALL_SEASONS` pools on
purpose. Player-indexed things are scoped (rates, leash, lineups, park,
league baselines — the ball changes: HR 3.17% in 2026 against 2.96% in
2025). League-behaviour things may pool, AFTER a gate.

**The hook passed its gate on full seasons**: 40,279 decisions in 2025
against 38,949 in 2026, pull rates 0.0645 / 0.0656, only the 0-60 bucket
flagging at +0.0018 on 26,000 rows.

## LOADING 2025 FOUND THREE SILENT LEAKS

Only catchable because the scoping went in FIRST with exact digests to
compare against. The rotation gate counted starts across seasons (2026 case
count moved 3,629 -> 3,709 with no code change); `sim._starter_league` took
no season argument at all while setting the anchor every rate is log5'd
against; and `resolve` applied twice turned ALL_SEASONS back into the current
season. All fixed, all digests restored, tests added.

## WHAT TO DO NEXT

1. **Split-season boundary fit.** 2025 alone against 2026 alone, comparing
   FITTED COEFFICIENTS rather than bucket hazards. The gate compared hazards,
   which is one step removed. If the two independent fits land on each other
   the stability is real; if not, the pooled fit is averaging something away.
   User flagged the stability as "almost concerning" and that is the check.
2. **Measure the decay** across four seasons, then ship the K prior. It is
   the only measured gain of the day and it is still behind a flag.
3. **The traffic deficit.** Two signatures now, five failed mechanisms.
4. **Arsenal, PRE-REGISTERED ON STRIKEOUTS ONLY.** Re-openable: it was
   scored on the two-engine setup on half a season, and the recorded
   sub-pattern — every high-K line improved, k7.5 +0.67pp — fits today's
   split exactly. Commit to the hypothesis before looking.
5. **`fitf5`** still has never been re-run.

## RETRACTED TODAY

* The preseason-rank GRADIENT. Died on 2025 — the strongest cell there is
  the 17+ bucket, the opposite of the callup story. The headline correlation
  DOES replicate (-0.287 / -0.268) and is redundant against prior outs in
  both seasons (+0.002, +0.011).
* The boundary KNEE fixing the 18.5 line. It moved it by zero.
* Archetype as evidence about matchups. It measured whether arsenals form
  CLUSTERS; they cluster for nobody. Matchups are a separate, re-openable
  question.

## TRAPS ADDED ON DAY TEN

**A DIGEST BEFORE A DATA LOAD IS WORTH MORE THAN ANY REASONING AFTER IT.**
All three leaks were found by fingerprints moving, not by reading code.

**COVERAGE IS NOT ACCURACY.** Memory makes 117 more early-season games
priceable. Scored unpaired that reads as skill; it is not. Intersect first.

**HISTORY SUPERSEDES TYPING.** Typing was a stand-in for not having enough
of the man himself. `bytype.py` found the defects global; `archetype.py`
found typing absent for starters. Both were saying this.

**MATCH THE CALENDAR WHEN COMPARING SEASONS ON PARTIAL DATA.** The first
stability run showed 2026 pulling less at eleven of eleven buckets. It was
two months of 2025 against six of 2026.

---

# Resume here — state as of 2026-08-26 (day nine)

## WHAT CHANGED TODAY, IN ONE LINE

Two silent bugs found and fixed, the second engine deleted, and the standard
for judging a change moved from `calibrate.loss` to **P(over) at the lines
that carry volume**. That last one reversed a ship/no-ship decision and is
the most portable thing here.

## SHIPPED

**ONE ENGINE.** `sim.simulate_start` and `sim.simulate` are gone, with
`f5.py`, the input-uncertainty block (`DRAW_RATES`, `HOOK_SIGMA`) and the
inherited-runner fudge. `price`, `quote`, `versus_market` and `recency` all
run `game.simulate_game` now. **Rule: no modelled opposing starter ->
DECLINE.** A full game is ~20x a one-sided start; `tests/run.py` forks one
process per check to absorb it (95s -> 36s, 337 checks).

**TWO BUGS, both silent, both caught by recorded diagnostics.**

  1. `apply_pa` charged `int(round(PITCH_COST[o]))`. An out costs 3.25 and
     was billed 3, a walk 5.48 billed 5 — ~23 times a start. The TABLE was
     never wrong (86.9 predicted against a real 86.82); the fraction was
     discarded at the point of use. Fixing it: pitches per out 5.14 -> 5.34,
     starts at 21+ outs 16.4% -> 12.9% against a real 11.4%.
  2. `calibrate.run(hook=...)` passed its hook nowhere. **The tuner had been
     scoring one hook against itself since the day-eight migration.** Found
     because a ten-parameter sweep moved nothing and the loss was identical
     to five decimals. Shipped values were never corrupted, because nothing
     could change them.

**THE FITTED BOUNDARY CURVE**, on 38,485 real end-of-inning decisions. The
old one fired at 0.293 where reality is 0.074. `sim.LEGACY_BOUNDARY` restores
it. It ships DESPITE scoring worse on `calibrate.loss`, the mean and the
boundary share — see the standard below.

**THE LEASH** is gated to arms meant to go long (`leash.intended_starters`,
p75 outs >= 12) with `MIN_PRIOR` 3 -> 5, and rebuilt on the current engine.
Openers were HALF the apparent between-pitcher variation: between-sd 1.80 ->
0.90, K 3.7 -> 14.8 starts, nothing pinned at the clamp any more.

## THE STANDARD THAT CHANGED — read this before scoring anything

`calibrate.loss` sums a hazard block, a mean, a boundary share and three
out-shares, so a change that helps one and hurts another reads as no
improvement. **We do not care about them equally, and nobody bets the
boundary share.** Measured, from the settled Kalshi board:

    OUTS   14.5-17.5 = 91.2% of contracts    18.5 = 6.2%    20.5 = 0.1%
    K      2.5-8.5   = 86.5%, flat across 3.5-7.5 (~13% each), no peak

Scored that way the fitted boundary curve wins where it matters and loses
where nobody bets:

    RMS error on P(over), outs 14.5-17.5    0.0546 -> 0.0346  (-37%)
    RMS error on P(over), outs 12.5-20.5    0.0452 -> 0.0513

and the old curve's error was a BIAS — negative at every line from 12.5 to
17.5, systematically under-pricing the over.

## WHERE THE MODEL ACTUALLY STANDS, re-measured on the shipped engine

**K props: 94% of the market's skill, blend weight 0.00** over 3,366 settled
August contracts. No edge, none lost. **The sub-claim that we beat Kalshi
inside five cents is DEAD** — the market is now marginally better in every
band. `quote.py` was printing the old numbers and has been corrected.

**Outs is still the dead half.** It looked alive at blend 0.50 / AUC 0.627
and that was leash LEAKAGE: the shipped offsets were full-season and August
sat inside them. Rebuilt `--before 2026-08-01`, the edge vanishes (AUC
0.555, blend 0.00).

**HEADROOM, like for like** (holdout, rates frozen, leash off):

    stat   ceiling  our corr  share  our spread  real between
    outs     0.363     0.121    33%        0.89          1.39
    k        0.475     0.384    81%        1.02          1.18

**K IS AT 81%, NOT EXHAUSTED** — about +0.09 of correlation available. This
CORRECTS day eight's "strikeouts are at 93% and essentially exhausted",
which compared an in-sample correlation against a clean ceiling. Note also
that the OUTS ceiling collapses 0.599 -> 0.330 once openers are excluded:
most of the apparent predictability in outs was "openers go 3, starters go
16", which no book prices.

## THE OPEN DEFECT: mean outs 16.49 against a real 15.78

Isolated to three parts, two of them now eliminated:

  * **53% is the traffic deficit** — outs per plate appearance ~1.4% high,
    i.e. too few baserunners. This is the day-six "0.13 runs light per side",
    which has now survived measured advancement, measured inherited runners,
    TTO and the re-measured shrinkage constants. Unsolved.
  * **The rest is the boundary curve's FUNCTIONAL FORM.** Its logit is
    linear in pitches while the real hazard accelerates past 90, so it fires
    at 0.596 where reality is 0.749 at 100-110 — under-pulling exactly where
    46% of removals happen. **Next step: a non-linear pitch term.** This is a
    code change, not a refit.
  * ELIMINATED: the mid-inning curve needs nothing (it is fitted on REAL
    decisions and tracks the observed hazard at every bucket), and
    restricting the boundary curve's training rows makes things WORSE.

## WHAT TO DO NEXT

1. **Non-linear pitch term in the boundary curve.** The only lead left on
   the mean, and the first thing in days that is not a refit.
2. **`fitf5` has still never been re-run.** Every F5 number in these notes
   predates the crossed-lineup fix. It is not blocked by anything.
3. **The traffic deficit.** Oldest defect in the model; four mechanisms have
   failed on it. Worth a fresh approach rather than a fifth constant.
4. **K distribution is UNDER-DISPERSED** — sd 2.24 against a real 2.47, mass
   pulled from both tails into 4-6. NOT bimodal (per-pitcher means are one
   broad hump, 2.8 to 8.4). Within-start K% persistence (+6.4 sigma) is the
   candidate: it cannot move the centre, but this is a shape defect and
   shape is what it fixes.

## TRAPS ADDED ON DAY NINE

**A CONSTANT CAN BE RIGHT, REACHED, AND DESTROYED IN TRANSIT.** Every trap
here until today was a constant being WRONG or a mechanism not being
REACHED. `int(round(PITCH_COST))` was neither. Measuring a value and wiring
it in is not enough; the units have to survive the arithmetic.

**PER-DECISION CALIBRATION IS NOT DISTRIBUTIONAL CALIBRATION** when two
coupled curves share the state. The boundary and mid-inning curves compete
for the same exits — correcting one in isolation hands its exits to the
other. Day seven's lesson was do not POOL them; this one is do not fit them
INDEPENDENTLY either.

**RE-POOLING IS THE DEFAULT MISTAKE AND IT WAS MADE THREE TIMES TODAY.** Now
recorded in `CLAUDE.md` beside the grid-edge diagnostic, and
`calibrate.tune` is marked SUPERSEDED because its grid is what got copied
each time. The rule has a limit, also measured: restricting the BOUNDARY
curve's rows makes the simulation worse, because it fires at every pitch
count and the mid-inning curve does not.

**VERIFY THE MUTATION LANDED, not just that you wrote one.** A mutation
meant to disable shrinkage reported a check as unguarded; it had silently
failed to apply.

**A SHARE ABOVE 100% OF A PERFECT FORECASTER IS A LEAK ANNOUNCING ITSELF.**
`headroom.py` reported K at 112% of ceiling before the holdout was added.
Build measurements whose failure mode is out of bounds rather than merely
optimistic.

## STATE

* 337 checks, `make test`, ~36s, forked one process per check. Fork not
  spawn — a spawned child re-imports at default globals and every flag
  reverts.
* New tools: `scratchpad/headroom.py` (ceiling per stat, population
  declared), `kvsouts.py`, `bytype.py`, `tempo.py`, `fit_boundary.py`,
  `fit_midinning.py`, `tune_hook.py`, `joint_hook.py`, `remeasure.py`
  (CLV re-run, forked over dates), `bets.py` (prices named bets, keeps every
  draw in queryable sqlite).
* `tests/fixtures.py` is the ONLY mirror-the-opponent harness and `src/` may
  not import it.

---

# ARCHIVE — day eight and earlier

# Resume here — state as of 2026-08-25 (day eight)

## START HERE — WHAT IS FRESH AND WHAT IS STALE

**THE DAY-EIGHT NUMBERS BELOW WERE RE-RUN ON A CORRECT ENGINE. TRUST THEM.**
The baseline table, the per-side team totals, the park result, the weather
results, day/night and home/road were all measured AFTER both fixes below
landed. They are not suspect.

STALE, and the only three things that are: the **prefix ladder** (run before
the crossing was found, so "5% light" is from the broken engine — the team
total level of -0.10 runs per side supersedes it but the ladder itself has
not been re-executed), **`fitf5`** (never re-run; it was among the last
modules fixed), and the **shipped leash offsets** (measured one-sided).

Everything ELSE recorded before day eight rests on the broken engine.

Day eight found TWO defects in the SIMULATION INPUTS. Both preserved every
aggregate this project tracks, so nothing in the notes flagged them, and
both destroyed the MATCHUP — the only thing that differentiates one game
from another, and the exact quantity days six and seven failed to find.

**1. EVERY PITCHER WAS FACING HIS OWN TEAMMATES.** `build_cases` attaches to
each start the nine that pitcher FACES, so the away start already carries
the HOME club's batters. Seven modules then handed the away pitching side
the other lineup: `ladder`, `calibrate.replay`, **`fitf5`** (the primary F5
benchmark), `f5_market`, `total_market`, `team_market`, `marginals`.
Verified on names — Ryan Feltner of Colorado simulated against Brett
Sullivan, Connor Norby and Jake McCarthy, Colorado's own hitters.

The variable names caused it: `a_nine` reads as "the away team's nine" and
held the nine the away PITCHER FACES. Renamed `away_faces`/`home_faces`
everywhere so the correct call is the one that reads correctly.

**2. NOT ONE LINEUP IN 574 WAS RIGHT.** `opposing_lineups` had no
batting-order column, so it sorted the boxscore by at-bats descending and
took the top nine:

    exact match (right nine, right order)      0.0%
    lineups with at least one wrong batter    23.5%
    mean slot error                            2.30

At-bats exclude walks, so a high-OBP leadoff man sorted below a free
swinger; a pinch hitter with two at-bats displaced a starter pulled early;
and a club that batted around handed its leadoff man five at-bats, so the
"input" was partly a function of the result. Order is not cosmetic — TTO is
a measured 19% K% swing and the simulator derives it from batters faced.

Fixed by `src/context/order.py`, counted off play-by-play. 1,956 games, 97%.

**INVALIDATED — all PRE-day-eight:** the prefix ladder including "the model
runs 5% light", the day-seven resolution finding and the 0.19 game-total
ceiling, `score_outs`, the dispersion work, the blind dashboard, and every
`fitf5` result. **SURVIVES:** the model-free ANOVA (actuals only), the
one-sided leash measurement, and everything re-run today.

## THE BASELINE, ON A CORRECT ENGINE

Two-sided, real matchup, real batting order, leash OFF, 3,248 starts:

           actual sd   our within   our spread   corr
    outs        3.99         3.86         0.59   0.263
    k           2.44         2.02         1.00   0.496
    er          2.00         1.77         0.28   0.203
    h           2.24         1.94         0.44   0.278

    TEAM TOTALS, per side, 1,624 games
              actual sd   implied real   our spread   share   corr   level
    F3             1.74           0.40         0.23     59%  0.198  -0.05
    F5             2.31           0.69         0.35     51%  0.222  -0.10
    F7             2.76           0.95         0.43     46%  0.213  -0.11
    full           3.17           1.23         0.59     48%  0.164  -0.26

**Fixing the engine did NOT move the starter numbers** (outs corr 0.263
before and after). Both lineups were always real major-league nines, and
club-to-club quality varies far less than the noise inside one start. The
level error on team totals is now -0.10 runs per side at F5, NOT the 5%
recorded from the crossed engine.

## WHAT IS ACTUALLY NEW AND REAL

**TEMPERATURE ON HOME RUNS: t +3.6** with a pitcher fixed effect, +0.0081
HR per degree — about 0.32 HR per start across 55-95F. Clears the bar.
UNWIRED; this is the first genuinely new mechanism in days.

**BULLPEN OUTS YESTERDAY ON STARTER OUTS: t +2.6** under the same fixed
effect. Nothing in the simulator knows about yesterday.

**THE PER-PITCHER LEASH** (`src/context/leash.py`, `sim.USE_LEASH`) — a
pitcher's residual is stable on OUTS and noise on k/h/bb/er, so what is
wrong is how long he is left in. Out of sample +0.105 -> +0.226. **THE
SHIPPED `hook_leash.json` WAS MEASURED ONE-SIDED AND MUST BE REBUILT.**

**PARK IS NEUTRAL, MEASURED PROPERLY FOR THE FIRST TIME.** `NEUTRALISE_PARK`
was off, so rates already contained each pitcher's own park and layering a
factor on top counted it 1.5x. Neutralised and applied once: F5 spread 0.35
-> 0.39, correlation 0.222 -> 0.208. More differentiation, no accuracy.

**DAY/NIGHT IS DEAD, cleanly.** Null in all three specifications, and with
real lineups "day games get weaker lineups" is already captured.

**HOME/ROAD IS REAL AND CORRECTLY SIZED.** With the adjustment on, t +0.1;
switched OFF it reappears at t +2.4, worth +0.38 outs.

## HOW TO TEST A BETWEEN-GAME FEATURE (use this, it is cheap)

`scratchpad/allelse.py` — joint fit plus a WITHIN-PITCHER fixed effect, on
the residual. Univariate correlation is not enough: park on hits reads +2.5
alone and +0.9 under the fixed effect, because "starts in a hitter park" is
partly "starts by Colorado pitchers". Costs seconds, needs no re-simulation.
The internal control that says the method works: signed `wind carry` reaches
+2.1 on hits while raw wind SPEED sits at -0.5.

## THE ONE-SIDED ENGINE IS DELETED (day nine, first commit)

**DONE.** `sim.simulate_start` and `sim.simulate` are gone, and with them
`f5.py` (the stub that faced one side with a single league-average
reliever), the `engine="stub"` branch in `f5_market`, the input-uncertainty
block (`DRAW_RATES`, `HOOK_SIGMA`, the Beta draws) and `_leave` with the
three inherited-runner constants. Those existed ONLY because a loop that
stopped at the hook could not simulate the reliever finishing the inning; `game.py`
hands the base-out state over and plays them out. The `inherit.py`
MEASUREMENT is untouched — the fudge went, the count stayed.

`price` and `quote` now simulate the whole game and read both starters off
one `GameResult` (`price.simulate_slate_game`), which is cheaper than what
it replaced — it used to simulate each pitcher separately. `versus_market`
and `recency` go through `cal.paired_cases` + `cal.replay` the same way
`f5_market` already did. **Rule adopted: no modelled opposing starter ->
DECLINE**, the same posture as openers and live games.

**COST: a full game is ~20x the work of a one-sided start.** The suite went
70s -> 95s and is 328 checks. `scratchpad/seymour.py` dropped from 40k draws
to 20k for the same reason.

WHAT IS NOT DONE AND IS THE FIRST THING TO CHECK: **nothing here has been
re-scored.** No number in this file moved. `price`, `quote`, `versus_market`
and `recency` all changed engine, so any CLV figure recorded for them is
from the old one — and the change is not neutral, because the old engine had
no bullpen after the hook, no margin term and no opposing offence.

## WHAT TO DO NEXT

**1. REBUILD THE LEASH TWO-SIDED** (`python -m src.context.leash --build`).
The shipped offsets were measured on the engine we no longer trust.

**2. WIRE TEMPERATURE as an HR multiplier and score it.** Use the park HR
factor, not the runs index — the -2.1 on `park runs idx` against a home-run
target is that mismatch, not a finding.

**3. RE-TEST HANDEDNESS.** Play-by-play carries real `batSide`/`pitchHand`
per plate appearance; the dead result used derived season splits, on the
broken engine.

**4. RE-RUN `fitf5`.** It was crossed. Every F5 number in these notes is
from that state.

## TRAPS ADDED ON DAY EIGHT

**AN AGGREGATE THAT LOOKS RIGHT IS NOT EVIDENCE THE INPUTS ARE RIGHT.** Both
defects preserved run level, outs distribution, boundary share and pitchers
per side. What catches them is asserting on NAMES.

**AN IDENTICAL-TO-FOUR-DECIMALS A/B IS PLUMBING, NEVER A NULL.** A paired
ladder read EXACTLY +0.0000 at all four prefixes over 1,615 games. That was
`game.build_side` never calling `sim.for_start`.

**A MODEL-BASED CEILING IS ONLY AS GOOD AS THE MODEL'S OWN SPREAD.**
`ceiling.py` reported an outs ceiling BELOW our own correlation. Cross-check
with the ANOVA on actuals, which touches no model.

**A SPLIT-HALF THAT PASSES CAN STILL BE THE WRONG QUANTITY.** The club
residual passes the bullpen-role gate at +0.595 and is worthless once the
pitcher offset is in.

**NAME A VARIABLE BY WHO FACES IT.** `a_nine` cost seven modules.

**DO NOT OVERRIDE THE FEED WITH AN ASSUMPTION.** `weather.py` briefly zeroed
wind under a closed roof, treating six readings as a quirk. They are all
American Family Field and T-Mobile Park — RETRACTABLE roofs, and T-Mobile's
is a cover, not a seal.

**FIVE CHECKS WRITTEN TODAY GUARDED NOTHING** until mutation caught them:
two set the flag they were testing, one asserted a clamp against itself, one
asserted "nine distinct names" without checking the sequence, and one
inspected `replay`'s arguments instead of what it built.

## STATE

* 328 checks, `make test`, ~95s. The count FELL and the suite got slower,
  both from the deletion: checks that guarded the one-sided engine's own
  constants went with it, and every remaining one now plays a whole game.
  Four new checks, all mutation-verified —
  `input_uncertainty_stayed_deleted`, `the_inherited_runner_fudge_stayed_
  deleted`, `inherited_runners_are_played_out_not_settled_by_a_flag` and
  `nothing_prices_through_the_fixtures`.
* `tests/fixtures.py` is new: the ONLY thing that mirrors a pitching side
  against itself, for checks that need innings and a fixture rather than a
  slate. It calls `game.simulate_game` — it does not walk a plate
  appearance — and `src/` may not import it.
* `context.db` adds `mlb_lineups` (35,208 slots) and `mlb_weather` (2,034).
* Stadium home-plate bearings, if ever needed: NOT required — statsapi
  reports wind field-relative. User supplied a table; it is in the day-eight
  section of `NOTES-context-layer.md`.

---

# ARCHIVE — the rest of day eight and earlier

# Resume here — state as of 2026-08-25 (day eight)

## START HERE

**Read `CLAUDE.md`'s THE OBJECTIVE section and `AF_PLAN.md` first.** Judge
every change on ACTUAL OUTCOMES. CLV is not the target.

**Then read the END of `NOTES-context-layer.md`** — day eight is the last
section and carries the measured negatives, which are the expensive thing
to rediscover.

## WHAT LANDED ON DAY EIGHT

**THE PER-PITCHER LEASH IS MEASURED AND SHIPPED** (`src/context/leash.py`,
`sim.USE_LEASH`). Out of sample — rates before 2026-07-01, offsets built
`--before 2026-07-01`, scored on the 1,125 starts after it:

    outs                     OFF      ON
    spread of our means     0.56    1.29
    corr with actual       0.105   0.226     (model-free ceiling ~0.30)
    of ceiling               33%     71%
    sd(p) at 15.5 outs     0.060   0.127     <- Brier resolution, doubled
    distinct medians           8      17

Downstream too, which is the coherence argument for ONE simulator stated in
numbers: k +0.389 -> +0.408, h +0.207 -> +0.235, er +0.044 -> +0.063.

**IT BUYS RESOLUTION, NOT SHAPE, AND THAT IS THE HONEST SUMMARY.** Outs
CRPS is FLAT (2.1761 -> 2.1747, +0.1 sigma) and the prefix ladder is flat
(F7 +0.4 sigma). Both are expected: our within-start sd is 3.84, so moving
a start's centre by an out barely shifts a distribution that wide, and a
hook change cannot move a run total when starters and relievers are equal
in aggregate. What changed is DISCRIMINATION BETWEEN STARTS, which is
exactly the quantity day seven found we were short of.

**MOST OF THE RAW GAIN IS OPENERS, so quote the rotation-only row.**
`ROTATION_MIN_GS = 5` admits openers and bulk arms and they were being
simulated with a starter's hook. Separated out on the holdout:

    live starts            base corr   +leash   RMSE base   RMSE leash
    all                        0.075    0.268       3.831        3.697
    median outs >= 12          0.077    0.182       3.613        3.550
    median outs >= 15          0.051    0.099       3.591        3.555

On genuine rotation arms the correlation still more than doubles, and the
true per-pitcher leash sd there is ~0.9-1.1 outs rather than 1.77.

**A WIRING GAP THAT INVALIDATES SOME OLDER A/Bs.** `game.build_side` never
called `sim.for_start` — every caller passes `hook=None`, which fell
through to a bare league `Hook()`. So club and per-pitcher offsets reached
`sim.simulate_start` and NEVER REACHED A FULL GAME, which is the engine
that produces team totals. Fixed, and guarded in `tests/test_wiring.py`.

**THE CLUB IS DEAD FOR THE SIXTH TIME**, and its split-half is a trap: r
+0.595 passes the bullpen-role gate while measuring which ARMS a club runs
out. Fitted club-first, a club offset is +0.090 -> +0.122 alone and makes
things WORSE on top of the pitcher (+0.234 -> +0.227). `USE_PATIENCE` False.

**EVERY OTHER BETWEEN-GAME FEATURE MEASURED NULL ON THE OUTS RESIDUAL**,
directly rather than inferred: is_home +0.005, night +0.019, park runs
index -0.032, days rest +0.014, bullpen outs yesterday +0.037, month
+0.039. None worth 0.15 outs against 1.77 of real variation. **Run
`scratchpad/between.py` FIRST on any future between-game candidate** — it
is a residual correlation, not a build-and-re-simulate.

## THE MEASUREMENT THAT SHOULD DRIVE THE NEXT SESSION

Model-free one-way ANOVA on ACTUAL values by pitcher, `(MSB - MSW)/n0`, so
sampling noise is removed. A LOWER bound on real between-start variation:

    stat  actual sd  between  within  our within  our spread  share
    outs       3.96     1.77    3.50        3.84        0.57    32%
    k          2.44     1.10    2.17        2.03        1.02    93%
    h          2.23     0.67    2.12        1.96        0.45    67%
    bb         1.30     0.39    1.24        1.28        0.39   100%
    er         1.99     0.41    1.94        1.78        0.29    71%

Outs was the only quantity badly short and the leash is the answer to it.
**Strikeouts are at 93% and essentially exhausted.** Do not spend a day on
a between-game feature aimed at K props.

**AND NOTE `our within` > the real within on outs (3.84 vs 3.50).** The
simulator is OVER-DISPERSED per start. This is why the model-based ceiling
estimator in `ceiling.py` returned an impossible "105% of ceiling" and had
to be replaced by the ANOVA. It is also why CRPS cannot see the leash. It
is the largest remaining defect in the starter model.

## WHAT TO DO NEXT

**1. THE OVER-DISPERSION ON OUTS — 3.84 against a real 3.50.** Newly
identified and it now blocks two things at once: it broke the ceiling
estimator, and it is why a correct centre buys no CRPS. Narrowing the
within-start distribution is worth more than any remaining feature, because
every start is currently too vague to price sharply.

**2. THE RUN LEVEL — 5% light at every prefix.** Unmoved by everything for
three days. Stated product, unambiguously wrong.

**3. The 12-14 out bucket**, 19.4% against a real 16.6%. Where books hang
outs lines.

**4. Collapse to ONE engine.** Day eight found the cost of two: a mechanism
wired into one and silently absent from the other for a full day.

**5. Openers as a population.** They are in `actual_starts` with a
starter's hook, and the leash is currently containing them by pinning them
at the sweep boundary. That works but it is a clamp doing a filter's job.

**6. Within-start K% persistence, +6.4 sigma**, still unused.

## TRAPS ADDED ON DAY EIGHT

**AN IDENTICAL-TO-FOUR-DECIMALS A/B IS A PLUMBING RESULT, NEVER A NULL.**
The first paired ladder read EXACTLY +0.0000 at all four prefixes over
1,615 games. Two model states that agree to four decimals on 1,615 games
are the same model. Second time in two days a mechanism was not reaching
the simulator.

**A MODEL-BASED CEILING IS ONLY AS GOOD AS THE MODEL'S OWN SPREAD.**
Subtracting our within-start variance from the actual variance reported an
outs ceiling BELOW our own correlation. Cross-check with the ANOVA on
actuals, which touches no model at all.

**A SPLIT-HALF THAT PASSES CAN STILL BE THE WRONG QUANTITY.** The club
residual passes the bullpen-role gate at +0.595 and is worthless once the
pitcher offset is in. Split-half tests persistence, not incremental value;
run the nested fit before believing it.

**`hook_leash.json` AS COMMITTED IS BUILT ON THE FULL SEASON.** Correct for
pricing tomorrow, WRONG for scoring this season — a pitcher's offset was
measured partly on the starts an in-sample replay would score. Rebuild with
`--before <cutoff>` and score after it.

**A SEVENTH CHECK GUARDED NOTHING.** `check_the_offset_never_leaves_the_
measured_sweep` asserted the clamp against the clamp constant itself and
passed with it mutated to 99.0. Write the mutation before believing the
check.

## STATE

* 325 checks, `make test`, no network, no pytest. `tests/test_leash.py` is
  new (6), plus 3 in `test_sim` and 2 in `test_wiring`.
* All six new checks mutation-verified.

---

# ARCHIVE — day seven and earlier

# Resume here — state as of 2026-08-25 (day seven)

## START HERE

**Read `CLAUDE.md`'s THE OBJECTIVE section and `AF_PLAN.md` first.** Judge
every change on ACTUAL OUTCOMES. CLV is not the target — measured, our
resolution is LOWER than the opening price's while we still "beat the open",
so a CLV edge can rise while the model gets worse at baseball.

**Then read the END of `NOTES-context-layer.md`.** It is appended
chronologically; day seven is the last three sections and carries the
measured negatives, which are the expensive thing to rediscover.

## WHERE THE MODEL STANDS

    3,248 real starts        outs CRPS   whole-inning   mean outs
    day seven, morning          2.2199          9.5%       16.39
    day seven, end              2.1505         66.3%       16.00
    ACTUAL                                      65.7%       15.70

`calibrate.loss` 0.20626 -> 0.04730. Outs SD 4.43 -> 3.95 against a real
3.99. Boundary share 70.3% -> 66.0% against a real 65.7%.

## WHAT LANDED ON DAY SEVEN

**The learned hook is OFF and the two branches are back.** It was shipped on
a premise written into `game.py` that was false: one roll per plate
appearance does NOT span the inning boundary, because `_half_inning` breaks
out of its loop on the third out before the roll happens. 72,426 instrumented
hook calls, every one at outs 0/1/2, never at a boundary. It was validated on
removal-decision AUC while silently discarding a fitted, verified boundary
share (66.9% against a real 66.7%).

**Each hook branch is now fitted on its OWN population, and that was the big
one.** The pooled fit averaged 20,994 late decisions at a 6.29% pull rate
with 26,693 early ones at 0.65%; the early rows dominate by count, so the
late curve came out far too flat — 7.24% at 90+ pitches where reality is
33.80%. Refitting late-only is what moved every number above.

**Early-inning branches exist on BOTH hooks and ship OFF** (`early_innings`).
They fix the disaster tail almost exactly (sub-two-inning starts 0.31% ->
3.16% against a real 2.68%) but widen outs SD to 4.47 where reality is 3.99.
The tail miss is left standing rather than bought with spread.

**Kalshi prop lookups were matching the wrong player.** `price_prop` matched
on ANY shared name token, so "Tyler Glasnow" priced off Tyler Phillips of
Miami and reported fair at 0.920 against a true 0.595. `names_match` now
requires the surname. `find_settled` is the CLV path, so recorded prop CLV
numbers may carry some of this.

**Recency persists and it is BB% and BABIP that move** — 136 pitchers, 1,952
window-to-next-start pairs. Out rate persists at +0.2084 (9.4 sigma); K% at
+0.0624. A single half-life over all four rates averages a 5.6-sigma signal
with a 2.2-sigma one and dilutes both, which is what `recency.py` did.

**`tests/test_wiring.py`** — five shipped mechanisms had no guard at all. See
the notes; the short version is that every measurement module was tested and
none of the wiring was.

## THE FRAME FOR ALL OF IT (user, end of day seven)

**Central tendency beats the tail.** A bet on under 18.5 outs settles the
same whether he went six strong or blew up in the second. What matters is
the mass NEAR THE THRESHOLD, not the shape of the far tail. Day seven spent
most of its effort on the disaster tail, which is the less useful end — and
the tail work was then shipped OFF anyway. The 12-14 out bucket (19.4%
against a real 16.6%) is 4.0-4.2 innings, which is exactly where lines sit,
and it is the more valuable target.

**The model was RIGHT about the short starts.** Burns at 11 outs and
Whisenhunt at 8 priced at the 7.1st and 3.8th percentile. Those were rare.
Pricing them as common would be worse, not better.

**RUNS ARE THE GAME.** They lag as a within-start signal — that is why the
hook keys on baserunners — but as a measure of whether the SIMULATION is
right they are the thing itself. Everything else is a component.

**IS THE HOOK WORK JUICING THE OFFENCE? TESTED — NO.** The concern was that
the hook is fitted to reproduce starter lengths GIVEN this simulator's run
environment, so a wrong offence gets absorbed into the hook and vice versa.
Measured on the prefix ladder, 1,615 games, before and after a full day of
hook work:

    prefix     actual    morning    end of day
    F1           1.03       0.88          0.88
    F3           2.90       2.73          2.71
    F5           4.95       4.66          4.67
    F7           6.89       6.57          6.57

Identical to two decimals. Mechanically that follows: relievers and starters
are equal in aggregate here (K-BB 0.1358 against 0.1333), so moving WHEN a
pitcher leaves does not move how many score.

**THE MODEL RUNS COLD ON RUNS, AND THAT IS THE STANDING DEFECT.** 0.32 runs
light at F7, about 5% at every prefix, unchanged all day. Note a three-game
blind re-simulation made it look HOT (sim totals 7.6/8.1/8.4 against actual
11/5/5, mean percentile 0.356) — that was 21 correlated quantities, maybe
seven effectively independent, and it had the sign backwards. Trust the
1,615-game ladder.

## AN OPEN ARCHITECTURAL QUESTION (user, end of day seven)

**"Maybe we need different models for different props. Maybe we are
reaching too hard trying to recreate everything in one go."**

The day's evidence supports this. Hook work moved the outs distribution a
long way (CRPS 2.2199 -> 2.1505, whole-inning 9.5% -> 66.3%) and moved the
run level NOT AT ALL (F7 6.57 before and after). Those quantities are
separable in practice, and `calibrate.loss` targeting the outs distribution
while runs sit 5% light is one model being pulled two ways — a fix for one
quantity has to justify itself against a loss built for another.

WHAT ONE SIMULATOR BUYS, and what separate models would give up, is
COHERENCE: a team total and a starter's outs come out of the same simulated
game, so they cannot contradict each other and the correlations are free.
Separate models will happily price a starter for seven innings and a bullpen
for five.

THE MIDDLE PATH, and the recommendation: keep the simulator as the
generative model and add a THIN PER-QUANTITY CALIBRATION LAYER on its
output — a fitted map from predicted distribution to corrected distribution,
one per prop. Standard technique, keeps coherence, and lets each quantity be
right without the hook and the run model competing for the same parameters.

Note this is a departure from `AF_PLAN.md`, which says props should FOLLOW
from a game simulation that is actually right. Worth deciding deliberately
rather than drifting into.

**AND A CAUTION ON THE NOTES.** Much of `NOTES-context-layer.md` on the run
distribution ("compressed — too many shutouts and too few crooked numbers")
came out of chasing TAILS. It is evidence about tails, not about the bulk.
The user's read from the dashboard is that the distributions are too WIDE
around the likely numbers, which is the opposite claim about a different
part of the distribution, and both can be true at once.

## THE FINDING THAT SHOULD DRIVE THE NEXT SESSION

**The run distributions are CALIBRATED but nearly UNRESOLVED, and the
ceiling on game totals is tiny.**

Widths are right — the probability integral transform over 500 games is
uniform at every prefix (middle half 54.6 / 50.2 / 47.8% against 50%). What
was wrong is RESOLUTION, which PIT cannot see: a model handing every game
the same distribution, centred correctly, produces perfectly uniform PITs
and is useless for choosing between games.

    prefix   our spread   implied true   share   corr w/ actual   ceiling
    F3          0.32          0.39        83%        0.160         0.165
    F5          0.47          0.79        60%        0.205         0.251
    F7          0.56          0.69        81%        0.166         0.188

'our spread' is the sd of our per-game predicted means. 'implied true' is
sqrt(var(actual) - mean within-game var). 'ceiling' is the correlation a
PERFECT forecaster would achieve, which is between-sd over total-sd.

WE ARE AT 82-97% OF THE CEILING, and the ceiling is 0.19. About 96% of the
variance in a game total is within-game randomness no model can touch. The
predictions look samey because games ARE samey in expectation — a perfect
model ranges about 6.5 to 9.5 runs, not 3 to 15.

**This reframes the whole "0-for-everything" imported-feature list.**
Handedness, park, day/night and arsenal are exactly the features that
DIFFERENTIATE games rather than shift the level, and the differentiable
share of a game total is about 4% of its variance. An effect that size
cannot register against this target however well implemented. That is not
evidence they work — it means the nulls were UNINFORMATIVE, and re-testing
them against a game total will stay uninformative.

**So: test between-game features against a target that HAS between-game
signal.** Starter outs and strikeouts carry far more of their variance in
the pitcher's own rates than a team's run total ever will. Measure the
ceiling FIRST for any target before spending a day on a feature.

## WHAT TO DO NEXT

**1. BETWEEN-GAME DIFFERENCES.** We produce 60-83% of the real game-to-game
variation. Start by computing the CEILING for each target — starter outs,
K, team totals — so effort goes where signal exists. Then ask which inputs
should differentiate games and are not: opposing lineup quality, park,
bullpen strength. Note the run-total ceiling is 0.19 and we are at 88% of
it, so that target is close to exhausted.

**2. THE RUN LEVEL — 5% light at every prefix.** The ladder has said this
all day and every day; nothing has moved it. It is the stated product and it
is the one number that is unambiguously wrong. Note the ladder CAN see this
(it is a level error, not a redistribution) even though it cannot see a hook
change.

**3. The 12-14 out bucket.** 19.4% against a real 16.6%, the largest
remaining misfit in the STARTER-LENGTH distribution. That is 4.0-4.2 innings, which is where books hang outs
lines. Untouched by everything above.

**4. Collapse to ONE engine.** `sim.simulate_start` and
`game.simulate_game` both exist; the start-level loop has no bullpen, no
margin and cannot produce a team total. `quote`, `price`, `calibrate`, `f5`
and `versus_market` all sit on it, and every calibration table in the notes
was produced by it, so the migration invalidates recorded baselines in one
commit. Note `USE_MEASURED_INHERITED` RETIRES with that loop rather than
needing a port — `game.py` plays inherited runners out for real.

**5. The blind re-simulation is DONE and scored.** Six games from
2026-08-24, rates cut off before the date, published as a dashboard with the
actuals overlaid (`scratchpad/lastnight.py`, `scratchpad/dash.py`,
`scratchpad/actuals.json`). Mean sim total 8.16 against an actual 8.00 — a
gap of 0.1 standard errors. 78 quantities, mean percentile 0.461. It
confirms nothing is grossly wrong and CANNOT resolve a 5% level bias: six
games carry +/- 1.7 runs of resolution.

**6. Within-start K% persistence, +6.4 sigma.** Whether he has the
swing-and-miss tonight carries; contact outcomes do not. Unused, and it bears
directly on strikeout props, which is what `quote` gets asked about most.

**7. Refit the hook properly.** `calibrate.tune` is serial, samples 500 of
3,248 starts, and fits `sim.simulate` — the engine being deleted.
`scratchpad/tune_game.py` fixes all three and does a joint search, but its
objective still omits SPREAD, so it compresses the distribution to buy the
terms that are weighted.

## TRAPS, MEASURED THE HARD WAY

**A branch must carry an OFFSET from the shared intercept, never an absolute
level.** Callers disable the hook by driving `mid_intercept` to -99 —
`team_offset`, the patience fits and the never-pull tests all use that idiom.
This bug was introduced, fixed, and reintroduced in a different branch hours
later on the same day.

**Residualising against a mean that CONTAINS both sides manufactures a
negative correlation.** For n starts and a window of w the artifact is
`(-1/n) / sqrt((1/w - 1/n)(1 - 1/n))`, which is -0.158 at n=21, w=7. A
measured -0.112 was LESS negative than noise and concealed a true +0.21 — the
sign was backwards. Leave-both-out, always.

**Do not fit counted points.** A least-squares slope through five measured
hazard values got the shape wrong: the real hazard is flat from nought to one
run then climbs, and a line charges +0.724 where the truth is +0.296.

**`calibrate.loss` does not weight SPREAD.** Any optimiser pointed at it
compresses the outs distribution to buy the hazard curve and boundary share.
Report SD alongside; do not add it to the objective while the hook is
compensating for something else.

**The prefix ladder cannot see anything that changes WHO throws.** Starters
and relievers are equal in aggregate here (K-BB 0.1358 against 0.1333), so a
hook change is invisible to it. The boundary fix measured |sigma| <= 1.1 on
the ladder and +4.7 on outs CRPS — same change, same games.

**A mutation harness must refuse to run on a dirty tree.** Backups belong
outside the tree. A SIGKILL between mutate and restore left a shipped
mechanism switched off, and the next run backed up the mutated file and
restored that.

---

# ARCHIVE — day six and earlier

Kept for the measured negatives. Anything about the hook here is
SUPERSEDED: the learned model described below is switched off,
for reasons in the day-seven section above.

# Resume here — state as of 2026-08-25 (day six)

## START HERE

**Read `CLAUDE.md`'s THE OBJECTIVE section and `AF_PLAN.md` first.** Judge
every change on ACTUAL OUTCOMES. CLV is not the target — measured, our
resolution is LOWER than the opening price's while we still "beat the open",
so a CLV edge can rise while the model gets worse at baseball.

## WHAT LANDED ON DAY SIX

**A learned removal model replaces `sim.Hook` for starters**
(`src/context/removal.py`, `game.USE_LEARNED_HOOK`). Per-decision logistic on
86k plate appearances from play-by-play. AUC 0.9123 against the shipped
hook's 0.8755, log loss 27% better, on a date holdout. Coefficients persisted
to `removal_model.json` so the sim needs no sklearn at run time.

    THE HOOK IS A WORKLOAD RULE. Pitch count alone ranks removals at AUC
    0.901; the full model reaches 0.914. Traffic, damage, runs, TTO, pitcher
    quality and all thirty clubs together are worth +0.013.

    RUNS RANK 11th OF 14 FEATURES. Independently confirmed by the refit,
    which halved `per_run` 0.6 -> 0.3 and moved nothing else.

    CLUB EFFECTS ARE WORTH +0.002 AUC and are dropped. Fifth independent
    finding that team-specific hook effects do not pay.

**Times through the order** (`src/context/tto.py`, `sim.USE_TTO`). Measured
on 85,909 starter plate appearances: strikeout rate falls 19% from the first
pass to the third, walks +9.5%, homers +6%, BABIP flat. Multipliers are
RE-CENTRED to a PA-weighted mean of 1.0 — anchoring them at pass 1 would
raise every pitcher's strikeout rate. It fixed first-inning error +0.070 ->
+0.005 (-1.8 sigma), the largest outcome-based gain of either day.

**Measured shrinkage constants** (`src/context/stabilise.py`,
`rates.USE_MEASURED_STABILISE`). The four imported `STABILISE` values were
wrong in both directions: batter rates over-shrunk ~2.2x, pitcher HR rate
UNDER-shrunk 2.7x, and one table was serving two populations that differ
six-fold on home runs. Now split by population.

**Relief-outing length, mid-inning relief changes, inherited runners by
base and out** — all measured, all shipped behind flags, and all with NO
demonstrated effect on prediction across three framings (mean prefix error,
CLV, distributional CRPS). Measured values stay; see the standing rule.

## THE YARDSTICK, AND WHY MOST THINGS READ AS NULL

We sit at **91-98% of the market's resolution** on outcomes and are BETTER
CALIBRATED than it (August reliability 0.0005 against Kalshi's 0.0014). The
entire remaining prize is about 2.5 Brier points. So a mechanism moving 0.02
runs is exactly what the ceiling predicts, and demanding each one clear 2
sigma alone guarantees everything reads as a failure.

Use `scratchpad/leverage.py` BEFORE building: it swings each parameter across
its reliability-adjusted club spread and reports the runs of separation it
could buy. Under ~0.05 runs it cannot matter however real it is. It has
already redirected a day of work.

## WHAT IS ACTUALLY WRONG WITH THE MODEL

Two durable defects, both from the refit diagnostics on unseen data:

  * **The sim is 0.13 runs light per side** — 2.32 simulated against 2.45
    actual. This survived measured advancement, measured inherited runners,
    TTO and the new shrinkage. Most durable defect in the model.
  * **It is short of crooked innings.** 15.2% of sides score 5+ against
    17.7% actual, while shutouts are right (22.6% vs 22.0%). The upper tail
    is too thin, and that is where totals are decided.

## THE ORDER OF WORK

0. **EARLY HOOKS.** The removal model is fitted at a 4.6% base rate and
   overwhelmingly fits the ordinary case near 90 pitches. An early hook is a
   different event. Chase Burns went 3.2 on 2026-08-24; the sim priced
   "pulled in the 4th" at 6.5%. Fit it separately or at least check
   calibration in that region.
1. **Score the learned hook on OUTCOMES**, not just AUC. It is wired in and
   its effect on the prefix ladder and on starter-length distribution has
   NOT been measured yet.
2. **Per-batter and per-pitcher HIT MIX.** Every ball in play that becomes a
   hit is split single/double/triple by ONE LEAGUE CONSTANT, so a slugger
   and a slap hitter with the same BABIP produce identical doubles. Leverage
   screen puts it at 0.145 runs — the highest-scoring thing in the model
   that does not exist yet, and it feeds the advancement tables.
3. **Make `ladder` per-side.** AF_PLAN targets TEAM totals; the ladder sums
   both sides, which hid a 5% dispersion error that per-side scoring found
   immediately.
4. Role-based bullpen deployment (passed its gate, unbuilt, but hook-adjacent
   so expect the same story).

## MEASURED AND DEAD — do not re-run without a NEW approach or NEW data

* **The latent "he does not have it tonight" state.** Tested three ways:
  outcome damage does not persist within a start (0.1 sigma), exit velocity
  barely persists (1.8 sigma, and inflated by the constant lineup), and
  NEITHER predicts later runs (0.1 and 0.4 sigma). Against the SAME NINE
  HITTERS, 94.6% of the time. A rough first pass tells you nothing about the
  next one.
* **Team-specific hook effects.** Five findings now, including a
  per-decision test worth +0.002 AUC.
* **Per-club advancement** — split-half r +0.11 to +0.38, leverage <=0.032
  runs.
* The nine imported features from earlier days (handedness, park, day/night,
  bullpen availability, arsenal, recency, ...).

## TRAPS THAT COST REAL TIME

* **Mutation harnesses lie if a mutation preserves file SIZE** — stale .pyc
  is reused and the mutation never runs. All `scratchpad/mutate_*.py` now
  clear `__pycache__` and set `PYTHONDONTWRITEBYTECODE=1`.
* **`ladder.simulate_prefixes` needs per-(game, draw) seeding.** Per-GAME
  looks like a fix and is not. Without it a bullpen flag moves F1, an inning
  no reliever reaches. Pinned by
  `check_the_first_inning_is_immune_to_a_bullpen_flag`.
* **Fork, not spawn, for the fit workers.** A spawned child re-imports
  modules at DEFAULT global state, so every flag silently reverts and the
  search returns a flat surface that reads as "this parameter does not
  matter". Pinned by `check_worker_state_crosses_the_fork`.
* **Six checks have now been found to guard nothing**, one of them
  pre-existing. Write the mutation before believing the check.
* **Pairing beats sample size.** Prefix error varies ~0.28 runs across games
  and swamps a 0.02-run effect; the paired per-game difference has an SE
  near 0.02. Comparing two independently-reported means will never resolve
  anything here.

## STATE

* 294 checks, `make test`, no network, no pytest.
* `fitf5.losses` is parallel over salts (4.4x, fork-based). A full hook fit
  is ~1.2h, not 5.1h.
* `pitch_center`'s search grid was stale by two revisions and had silently
  disabled `--with-hook`; re-centred on the shipped 80.0.

---

# Below: day five and earlier

## DAY FIVE

**Read "What the benchmark IS" below before anything else.** The
objective is the game simulation being right, measured on ACTUAL
OUTCOMES through `fitf5`. Everything else — props, totals, prices — is
expected to follow from that. The CLV work below is a downstream sanity
check and day five briefly mistook it for the scoreboard.

### The headline CLV numbers in this file are ONE MONTH

Read this before believing any CLV figure in this file. The K-prop record
(corr +0.586, blend +32.9%, direction 73.2%, +3.7c) was measured on eight
dates in mid-August. Re-measured at n_sims=1500 on the whole backfilled
season it does not hold up, and the reason is not sample size or Monte
Carlo error — it is that August is genuinely unlike June and July:

    window            n     corr    blend    dir     cents
    June           1,464  +0.416   +13.1%   59.1%   +1.8c
    July           3,134  +0.299    +7.7%   59.6%   +1.7c
    August (21d)   3,164  +0.575   +30.4%   69.0%   +3.3c
    SEASON (82d)   7,762  +0.451   +17.5%   63.4%   +2.4c

August reproduces the record almost exactly. June and July run at half the
edge, and July — the largest single month before August — is the worst.

**SIX explanations have now been tested and eliminated**, each on data:
Monte Carlo error; the measured advancement/GIDP tables; population
composition (restrict to the 101 arms priced in all three months and the
gap survives: +1.7c / +1.9c / +3.2c); liquidity composition (August holds
FEWER thin markets and still wins in every trade bucket); a directional
drift the model happened to match (centring each month's drift out GROWS
the August edge — the model leans under, so the drift was suppressing
measured accuracy everywhere); and a staler open (first-trade lead time is
12.9 / 13.8 / 14.4 hours — flat).

The liquidity result reverses across levels, which is the strongest clue:
WITHIN a month more trades means less edge, ACROSS months more trades comes
with more edge (37.7 -> 64.2 per market). Whatever changed is not liquidity.

See `NOTES-context-layer.md` for the full table of each test. What is left
to check is all about the market and the feed rather than the simulator:
whether Kalshi changed how it opens these markets, whether our own lineup
and roster completeness improved, and whether the mix of listed games
changed. Rows are cached at `scratchpad/august_rows.json` — do NOT
re-simulate to ask a market question.

**Plan against the June/July number (~+1.8c), not +3.7c and not the
pooled +2.4c** — the pooled figure is dragged up by the one month nobody
can explain, so it is not a number to size bets against. And note the
pooled season correlation
sits above both June and July, which is what pooling windows with different
levels does — quote the cents, not the corr.

**n_sims saturates at 1500.** On the same 1,222 August contracts: 250 gives
corr +0.490, 1500 gives +0.515, 2000 gives +0.516. Real attenuation (34 of
627 five-cent disagreements at 250 were noise) but small, and there is no
reason to pay for 2000 anywhere.

**z is not an effect size.** It rose from +41.4 to +67.1 purely because n
grew 6x. It measures confidence that an edge exists, not how big it is.

### The measured advancement/GIDP tables are NEUTRAL on K props

Four states at n_sims=1500 on the same 1,222 contracts, corr +0.513 to
+0.515 and blend +23.4% to +24.0%. Flat. Whatever the F5 scoring run says,
the measured tables cost nothing on this market.

### Three mechanisms shipped, all measured, all separately scoreable

* **Relief outings run to their measured length** (`src/context/relief.py`,
  `game.USE_MEASURED_RELIEF_LENGTH`). The continuation hazard is
  conditioned on the state the reliever ENTERED in — 20.1% of arms handed a
  clean inning come back out against 62.7% of those brought in with two
  down, over 13,248 outings. Effect on the engine: arms per side 5.05 ->
  4.07, mean total unchanged at 8.16 -> 8.19, **sd 3.91 -> 4.08**. Level
  held, spread up, which is the variance mechanism and the right direction
  against the known under-dispersion.
* **Inherited runners score by BASE and OUTS** (`src/context/inherit.py`,
  `sim.USE_MEASURED_INHERITED`). Counted on 5,507 inherited runners across
  2,006 games. THE ADVANCEMENT MISTAKE AGAIN, and it fails the same way —
  pooled it lands at 0.312 against the shipped flat 0.330, near enough to
  look right, while the cells run 0.127 to 0.771:

        0 out   1 out   2 out
    1B  0.396   0.267   0.127
    2B  0.628   0.428   0.215
    3B  0.771   0.633   0.229

  Two-out handovers are the most common state (2,624 of 5,507) and the flat
  rate over-credits every one, inflating a departing starter's earned runs.
  Start-level runs/start 2.5693 -> 2.5497.

* **Relievers can be pulled MID-INNING** (`game.USE_MEASURED_RELIEF_HOOK`),
  from a per-PA hazard over 50,023 in-inning relief plate appearances. Of
  4,026 real mid-inning handovers only 41.8% come from a starter; the other
  58.2% are reliever-to-reliever and the engine could not make them at all.

        0-2 bat     3-5     6-8      9+
    0r    0.015   0.099   0.073   0.070
    1r    0.045   0.130   0.097   0.060
    2r    0.033   0.141   0.122   0.087
    3r+   0.061   0.109   0.116   0.080

  NOT monotone in batters faced: the first two are nearly immune, then it
  peaks, then falls. `game.py` used to hard-code that protection as a flat
  rule, which is exactly why it could never pull a reliever.

  **SURVIVORSHIP TRAP, recorded because it is easy to fall into.**
  Conditioning on a stint's TOTAL runs gives 19.1% rising to 40.5% and reads
  perfectly plausibly — it is inflated by the arms that stayed in and kept
  being scored on, because for a pitcher who was not pulled the total keeps
  accumulating past the decision point.

**Pitchers used per side: league 4.30.** Model 5.05 with none of this, 4.07
length-only, 5.66 hook-only, **4.53 with both**. Length-only is equally close
in absolute terms and gets there BY CANCELLATION — no mid-inning relief
changes at all, offset by outings that run too long. That is the pattern
these notes keep warning about, so prefer the state with both mechanisms.

**Not yet measured: whether any of this improves a PRICE.** Run
`scratchpad/relief_value.py` — team totals, four flag states, paired on the
same contracts. Whatever it says the measured values stay; a worse score
locates compensation rather than licensing a revert.

## What the benchmark IS, because day five briefly forgot

**The objective is the game simulation being right. Prices are downstream.**
CLV is a sanity check on a model that is already correct on outcomes; it is
not the thing being optimised, and reading it as the scoreboard is how a
session ends up chasing a market anomaly instead of a mechanism.

The F5 TEAM TOTAL benchmark is `fitf5`, scored on ACTUAL OUTCOMES:
`side_cases` gives one row per pitching side where `runs` is what that side
really allowed through five (the opposing team's F5 score), and `_rps`
scores the simulated distribution across `SIDE_LINES` = 0.5..8.5, the full
support. The comment there is explicit about why it is not a book's lines:
doing that "would tune the model to the shape of somebody's board".

**Kalshi does not list an F5 team total at all.** Cached series are
`KXMLBKS` (10,525), `KXMLBTEAMTOTAL` (7,084, FULL-game team runs),
`KXMLBF5TOTAL` (3,521, the COMBINED first-five total) and `KXMLBTOTAL` (25).
So there is no market test for the primary target and there does not need to
be one. `scratchpad/score_relief.py` scores the three day-five relief
mechanisms through `fitf5`, which is the correct payoff test; the Kalshi
team-total run below is a downstream check on the SECONDARY target.

### Downstream check: full-game team totals vs Kalshi

August 2026, 21 dates, 2,335 settled contracts, day-five mechanisms ON:

    n_sims=250    corr +0.208  blend  +8.3%  dir 58.6%  +1.3c
    n_sims=1500   corr +0.236  blend +10.3%  dir 58.7%  +1.3c

Same n_sims shape as everywhere — 60 of 1,234 five-cent disagreements at 250
were noise, cents unchanged — so 1500 stays the operating point.

Brier skill ours +18.4% against the market's +20.7%: still behind a settled
close, as everywhere. This is the FULL-GAME team market, not F5, and it is
the secondary target. Do not read it as "the product is weak" — that was a
day-five misreading that cost an hour.

**Market data starts in July.** `KXMLBF5TOTAL` and `KXMLBTEAMTOTAL` have NO
June contracts, so the recorded F5 "+3.7c" pools July and August — the worst
and best K months. Splitting it by month is worth doing, and it doubles as a
test of whether the August anomaly is market-wide or specific to K props.

### The mutation harness itself was lying — read this before using it

Rewriting a source file twice inside the same mtime second means a
SIZE-PRESERVING mutation (`+= 1` -> `+= 0`) reuses stale `.pyc` and never
takes effect, reporting a genuinely-guarded behaviour as unguarded. Both
`scratchpad/mutate_*.py` now clear `__pycache__` and run with
`PYTHONDONTWRITEBYTECODE=1`. Anyone doing mutation work here hits this.

It also caught two real defects in checks written the same hour: one whose
fixture returned the same count under both the right and wrong definition,
and two that were behaviourally vacuous because the guards they targeted
were defensive rather than load-bearing. **Write the mutation before
believing the check.**

---

# Below: state as of end of day four

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

0. **WHY IS AUGUST DIFFERENT?** The single most valuable open question —
   the whole recorded edge lives in one month and nobody knows why. Not a
   maturation curve (July is worse than June). Check Kalshi liquidity and
   trade counts by month, lineup-data completeness, and whether the
   `MIN_TRADES = 5` filter admits different populations across the season.
1. ~~Re-read the paired F5 scoring result~~ — RUNNING, ~43 min per state,
   four states, so ~3h. First state landed: adv=published gidp=published,
   train 1.59699 / test 1.63980. Resume from `scratchpad/score_adv.out`.
2. ~~Re-run every CLV test at n_sims >= 1500~~ — K props DONE (see day
   five). Team totals and game totals still pending; use
   `scratchpad/clv_nsims.py`, which takes `team`/`total`/`f5`/`k`/`outs`.
   Do them month by month, not pooled — pooling is what hid this.
3. **Bullpen: role score from prior games**, deploy by role and live margin
   instead of sample order. `game.py` already tracks the margin.
4. ~~Bullpen: multi-inning outings~~ DONE. **Mid-inning reliever-to-reliever
   changes are NOT** — still the biggest missing piece of the 30.4%.
5. ~~Bullpen: inherited-runner rates from PBP by base-out state~~ DONE for
   the start-level path (`sim.USE_MEASURED_INHERITED`). `game.py` never
   used the constant. `f5.py` does not reference it either — day four's
   note that it did was wrong; the constant lives in `sim.py` alone.
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

* 267 checks, `make test`, ~60s, no network, no pytest. (Day four's "257"
  was wrong — the baseline was 245, matching CLAUDE.md. Day five added 22:
  7 in `test_relief`, 8 in `test_inherit`, 4 in `test_game`, 3 in
  `test_sim`.)
* 2,006 final games, F5 scores on 2,009, real pitch counts on 16,624
  pitching rows, 17,260 stints, 205 MB of play-by-play.
* `.claude/settings.json` sets bypass permissions for this repo, denying
  `git push`, `make publish`, `rm -rf` and reading `.env`.


## TRAP ADDED ON DAY SEVEN — DO NOT READ A LEVEL OFF A SMALL SAMPLE

Three blind games put the mean percentile of actuals at 0.356 and it was
reported as the model running hot. Six games put it at 0.461. The ladder,
over 1,615 games, says the opposite — 5% LIGHT. Real game totals have an sd
near 4.4, so the standard error of the mean gap is 2.5 runs at n=3, 1.8 at
n=6 and 0.11 at n=1,615.

TWENTY THOUSAND SIMULATIONS PER GAME DO NOT HELP. They sharpen the
PREDICTION, not the EVALUATION: there is still exactly one real outcome per
game. Simulating a million times leaves the right-hand side of the
comparison at n=6.
