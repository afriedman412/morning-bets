# TODO — the running list

Started 2026-08-29 (day fifteen). **The backlog, not the log.** What was
measured and why lives in `NOTES-context-layer.md`. When something ships,
compress it into the CLOSED section at the bottom — one or two sentences,
number retained — and write the full result in the notes.

Roughly ordered by runs per day of work. The leverage floor (~0.05 runs) is
a BETTING threshold and decides ORDER, never admissibility — a small,
counted, reliability-gated mechanism ships and accumulates (CLAUDE.md).

Each item says what is ESTABLISHED and what is not, because the expensive
mistake here is re-running something that already has an answer. **Numbers
are never reused or renumbered**, so a reference to "item 11" in the notes
always resolves.

**`TODO-SHORT.md` IS THE ONE-LINE INDEX OF THIS FILE AND IS UPDATED IN THE
SAME EDIT.** Add, close, renumber or re-scope an item here and its line
there moves with it — an index that lags is worse than none, because it is
read as current. It is also the cheap way to pick a NUMBER: the highest
number in this file is not visible at a glance, because items are written
both as `**N.` headings and as `  * **N,` bullets in the pick-up list, and
searching only one of those forms is how items 32 and 33 were first given
numbers that were already taken.

**THE FOUR-SEASON RESCAN IS DONE (2026-08-29) AND ITEMS 6, 13 AND 18 SHOULD
BUILD ON IT.** `scratchpad/state_counts_4season.json` holds 748,905 plate
appearances over 9,978 cached games, keyed by season and (men on, outs).
`state_seasons.py` is the scan and carries the stability gate. Items 6
(per-runner speed) and 18 (steal decisions) key on the SAME cell and need
only runner and batter IDs carried through the same pass; item 13
(per-pitcher hbp/wp) is the same pass grouped by pitcher. Extend that scan
rather than writing a third one.

**THE MODEL IS NOT LIGHT ON RUNS (retraction, 2026-08-30).** F5 -0.047 (0.6
sigma), F3 -0.024, F7 -0.040 over 1,645 games. The "3% fewer runs" and "4.5%
light" lines in older notes are from a previous engine; anything reasoning
from a run deficit needs re-deriving.

## WORKING ONE ITEM PER SESSION — read this first

Items are written to be picked up COLD. If one is not self-contained enough
to start from, that is a defect in the item; fix the item before starting
the work.

Before touching anything:

  1. `git status` must be CLEAN. If it is not, find out what is in the tree
     before adding to it — `scratchpad/mutate.py` refuses to run dirty, and
     an unexplained diff in `sim.py` is indistinguishable from your own.
  2. `venv/bin/python -m tests.run` — know it was green BEFORE you started.
  3. `venv/bin/python -m scratchpad.fingerprint 400 6` — one hash over
     2,400 simulated games. Record it. Any change that is meant to be inert
     must reproduce it exactly, and any change that is not must be able to
     say why it moved.

Then: write QUESTION / HYPOTHESIS / TEST / EVALUATE / CONCLUSION /
NEXT STEPS out as literal headers, state the POWER before the result, and
state the STANDARD ERROR of anything you are about to call a finding. Three
predictions failed on 2026-08-29 and two null results were misread as
regressions at 0.2 and 1.0 sigma, in both cases because the number
disagreed with a prediction and got scrutinised while the agreeable ones
did not.

Finish by compressing the item into the CLOSED section and writing the
result in `NOTES-context-layer.md`.

---

## WHAT TO PICK UP (refreshed 2026-09-10, after 19.1 closed)

Not a ranking of the whole list — the ones that are actually READY, in the
sense that nothing has to be decided before starting:

  * **32, A PER-PITCHER HOOK OFFSET FITTED ON THE DECISION — opened
    2026-09-11 and READY.** The per-arm residual against the shipped hook
    repeats YEAR OVER YEAR at r +0.538 (147 arm-pairs, se 0.083), survives
    removing each season's mean, and correlates only -0.399 with the
    `sim.leash` offset already applied — so ~84% of it is not in the model
    today. Above where this project has wired things before. Instrument,
    counts and the pre-registered falsifier are in the item. **33 changes
    the hook, so a table built first must be rebuilt after** — the
    `hook_hash` guard in `sim.leash` enforces it.

  * **25, THE HOME RUN CLUSTERING GAP — opened 2026-09-10 by item 24's new
    battery section, and it is the largest single defect on this list by
    sigma.** `hrshape.hr_var_over_mean` is 1.07 model against 1.15 real,
    four folds, same sign, pooled **z -4.4** (-0.0744 +/- 0.0167) — while
    the home run MEAN is right in every fold. Rule 2's signature. Item 24
    closed about 8% of it and the arithmetic in the notes says that is all
    a between-pitcher term COULD close, so the other ~90% is a different
    mechanism. ESTABLISHED: the gap, the four folds, the instrument.
    NOT ESTABLISHED: what it is. NOTE THE PARALLEL to 7f and to the run
    distribution's clustering — three shape defects now, and 7f points the
    OTHER way (outs too wide, runs and home runs too narrow); do not
    assume one mechanism. First suspects, neither screened: the night term
    loads the STARTER only (`NIGHT_LOAD`, sigma 0.1111) and a game's air
    is a game property that relievers pitch in too; and HR-per-air-ball
    may vary by game beyond park, temperature and wind — the humidity or
    the ball named in `TEMP_HR_MULT`'s own WATCH note. Instrument exists
    and is four folds deep.

  * **27, HOW OFFENSE PROPAGATES — the consolidating item, opened
    2026-09-10 on the operator's framing. Replaces the standalone "the
    model makes too many home runs" item, which is HYPOTHESISED to be
    downstream of this — the operator's word, and it is not established.**

    THE FRAMING, and it is the reason to have one item instead of four:
    the separate defects on this list may be ONE defect about how a
    game's events propagate. Home run level, home run clustering,
    run-mass shape and the coupling item are all plausibly facets of it.

    **IT PROPAGATES BOTH WAYS, AND THAT IS WHAT MAKES THE FRAMING FIT —
    operator, 2026-09-10, and it resolves what looked like a
    contradiction.** The first version was one-directional ("the model
    thinks offence has more momentum than it does; runs beget runs more
    than in reality") and the battery flatly refused it. But the defect
    is TWO-TAILED: reality has more shutouts AND more blowups, so what
    compounds is the NIGHT, in whichever direction it is going. Zeros
    beget zeros exactly as runs beget runs, and the model is short of
    both. Stated that way the measurement and the intuition agree, and
    the one-directional version is what was wrong, not the instinct.

    **SO THE SIGN IS: THE MODEL UNDER-PROPAGATES, IN BOTH DIRECTIONS. DO
    NOT RE-DERIVE THIS.** Four folds, current engine
    (`battery_8cfbe677e6f9.json`):

        row                    model vs real, z by fold
        runs_per_baserunner    +0.1  -0.1  -1.2  +1.2   DEAD ON
        shutout_share          -1.5  -2.2  +0.2  -1.6   model LOW 3/4
        mass_0_3               -1.2  -0.4  -0.9  -1.3   model LOW 4/4
        mass_8_plus            -0.2  -1.7  -0.9  +0.5   model LOW 3/4
        hrshape.hr_var_over_mean -2.2 -0.9 -3.7 -1.3    model LOW 4/4

    The model is short of BOTH tails at once and converts traffic into
    runs at exactly the right rate. So it does not over-propagate; it
    UNDER-propagates. Reality's runs and home runs arrive together more
    than the engine's do. This is the same defect CLAUDE.md records as
    the standing one ("reality has more shutouts AND more blowups while
    the model bunches"), now confirmed on the current engine and extended
    to the home run channel by item 24's new rows.

    ESTABLISHED: the direction, on five independent rows across four
    folds; `runs_per_baserunner` being exactly right, which RULES OUT
    advancement efficiency as the carrier and is the single most
    constraining fact here; and that the 2026 home run miss is about half
    level and half this (`hrbat.p_hr_level` +3.9 in 2026 with
    `hrshape.hr_per_club_game` +4.8% — the rest is the model spreading
    the same home runs over more batter-games than reality does).

    NOT ESTABLISHED: what carries it. Plate appearances resolve
    independently in the engine and real ones do not, but WHY real ones
    arrive together is unmeasured.

    AND THE ENGINE IS ASYMMETRIC IN EXACTLY THE WAY THE BOTH-WAYS
    FRAMING PREDICTS SOMETHING IS MISSING — worth checking first because
    it is free. `NIGHT_SIGMA` (0.1111, loading bb/hr/babip) is a
    DEFENCE-side night term and it fires on the STARTER ONLY. There is
    no offence-side equivalent anywhere: no per-club, per-night factor,
    and no term at all for the relievers who throw a third of the
    innings. If the truth is that a night compounds in both directions,
    the engine currently has one blind half of one side of it. Note the
    standing constraint before reaching for a wider latent: the
    four-channel version at full size was tried on 2026-08-27 and
    REJECTED for wrecking the outs distribution through widened traffic,
    and `NIGHT_SIGMA`'s own note makes the outs rows its falsifier. A
    counted cause is strictly better than a wider blind one — it says
    WHICH night.

    THE NEXT STEP IS NAMED AND CHEAP — the backwards screen, operator's
    idea, 2026-09-10. Take every real home run, describe the situation it
    happened in, and do the same for the MODEL's home runs; the model's
    own events are the control, so everything already modelled (park,
    platoon, times through the order) subtracts out and only a missing
    mechanism survives. `battery._hr_prob` already logs the analytic
    probability of every simulated plate appearance, so the instrument
    exists. PRE-REGISTER THE DIMENSIONS BEFORE RUNNING — a dozen of them
    guarantees one at p<0.05 by chance. The named candidates, in order:

      1. HAS THIS PITCHER ALREADY ALLOWED ONE TONIGHT. The direct
         clustering test and the reason to run this at all.
      2. Did the previous batter homer (back-to-back).
      3. THE BALL-STRIKE COUNT. A structural gap, not a refinement: the
         engine has NO count state, so an 0-2 breaking ball and a 3-1
         fastball are the same event to it. Invisible to every
         mechanism-first screen run so far.
      4. Runners on / recent traffic in the same inning, which is the
         run-clustering version of the same question.

    NOT GRAPH THEORY, recorded because it was raised and considered: the
    relationships here are conditional counts over a handful of named
    dimensions with an expected-value control, not network structure —
    there are no edges between entities to exploit.

    SUPERSEDES the 2026 home run level as a standalone item. That miss
    stays real and is re-checked AFTER this moves; a season-level home
    run multiplier fitted to close it is rule 5's forbidden move and is
    still forbidden.

  * **28, SAVANT'S PARK-ADJUSTED HOME RUNS — MEASURED 2026-09-10. `xhr`
    IS DEAD; THE HOME RUN QUALITY TIERS ARE LIVE ON THE BATTER AND ARE
    THE ITEM NOW.**

    Access solved and cached: `hr_savant.py --fetch`, four seasons, both
    sides, `.cache/savant_hr/`. USE `player_type=Pitcher`, CAPITAL P —
    `type=pitcher` and lowercase both return BATTER rows silently, and
    the fetcher now RAISES on a `player_type` mismatch rather than
    caching the wrong table. Name match against `mlb_traj` is 99.6-100%.
    `xhr` is exactly the mean of the thirty park columns (max |diff|
    0.133 over 200 arms), so it is one column, not thirty.

    THE TEST: leave-one-season-pair-out, fitted on two pairs and scored
    on the third, target = NEXT season's real HR/BIP, everything on the
    same balls-in-play denominator. Nine predictor sets. Three
    thresholds. Paired squared-error z on the held-out players.

    **DEAD — `xhr` ITSELF.** Sign-unstable across thresholds on both
    sides (pit -0.006 / +0.015 / -0.035 at 100/150/250 bip; bat -0.002 /
    +0.010 / +0.009) and z +0.31 once air share is in. THE REASON IS
    STRUCTURAL AND WORTH KEEPING: `xhr` collapses the thirty park
    counterfactuals to their MEAN, and the mean is precisely the part
    `NEUTRALISE_PARK` already removes. The information is in the SHAPE of
    that distribution, not its centre.

    **LIVE — THE TIER COLUMNS ON THE BATTER.** `no_doubters` (leaves all
    thirty parks) / `mostly_gone` / `doubters` as rates per ball in play,
    added to his actual rate: **z +2.84 paired**, out-of-sample r +0.0084
    / +0.0147 / +0.0159 at 100 / 150 / 250 bip — positive at every
    threshold and GROWING with sample quality. That is contact QUALITY,
    which his home run total cannot see: ten no-doubters and ten
    wall-scrapers are the same `hr_total` and the same `xhr`.

    STATED, NOT HIDDEN: nine sets were tried, so the winner is optimistic
    by construction. z +2.84 before any selection correction; the
    threshold stability is what makes it a lead worth building rather
    than a pick from nine.

    **AND THE TWO SIDES SPLIT EXACTLY THE WAY ITEM 24 SAID THEY WOULD,
    which is the strongest thing here.** The pitcher's signal is contact
    TYPE and the batter's is contact QUALITY:

        actual + air over actual          pit z +3.41    bat z +0.28
        actual + tiers over actual        bat z +2.84    pit r -0.021
        actual + air + xhr over + air     pit z +0.31

    Item 24 counted the air-share table on the pitcher and counted the
    BATTER side as a null; this test never saw that work, uses a
    different target (next season) and a different method, and reproduces
    the same split. It also VALIDATES ITEM 24 INDEPENDENTLY at z +3.41 —
    the shipped term is worth +0.08 to +0.12 out-of-sample correlation on
    next-season home run rate, at every threshold.

    NEXT, and it is a build not a screen: the tiers are a per-player-
    SEASON aggregate, so they enter as a better `hr_pct` for the BATTER
    and nothing else — no per-at-bat resolution, the at-bat part is
    already done. Fold discipline is `park.py`'s: a COMPLETED prior
    season is a legitimate input, the current season's row is
    season-to-date and knows the future if pulled after the cut. Score on
    `hrbat` (which exists) plus the run ladder.

    **WARNING ADDED 2026-09-10, AND READ IT BEFORE STARTING THE BUILD.**
    The tiers were put into `hr_clf` — a per-batter-game home run
    classifier, so a DIFFERENT target from the one above — and measured
    **z +0.46 / +0.73 / -0.48** across the three folds that carry them,
    pooled +0.41, on a harness positive-controlled at +3.8. A null.
    The diagnosis is REDUNDANCY, not irrelevance: the +2.84 above put the
    tiers against ONE prior season's home run rate, while `hr_clf` gives
    them a shrunk SEASON-TO-DATE rate to beat, which already knows
    everything a completed season could say.

    THIS BEARS DIRECTLY ON THE BUILD, because the batter `hr_pct` the
    tiers would improve is ALSO a shrunk season-to-date rate. So
    pre-register the falsifier: the tiers must beat the CURRENT shrunk
    rate, not a single prior season. If they do not, the item is closed
    and the +2.84 stands as a statement about a weaker baseline. See the
    2026-09-10 tier entry in `NOTES-context-layer.md`.

  * **30, DO THE TIERS EARN THEIR KEEP IN APRIL — the one loose end from
    the tier null, opened 2026-09-10 and DELIBERATELY LOW PRIORITY.**
    Restricting the ablation above to March-May rows, where a
    season-to-date rate is almost all prior, reads **+0.32 / +1.34 /
    +1.73** — positive in all three tier-carrying folds, pooled z ~+2.0.
    `... -m scratchpad.hr_clf --ablate --early`.

    ESTABLISHED: the three numbers and their sign. NOT ESTABLISHED:
    anything else. THE REASONS TO DISTRUST IT, stated because this is
    exactly the shape of result this project has been burned by: it is a
    SUBGROUP found AFTER the main test failed, the cold-start positive
    control is itself weak (+3.5 in one fold only, so the subgroup may
    simply lack power to reject), and 2-sigma results here have dissolved
    repeatedly. THE FALSIFIER IF IT IS EVER PICKED UP: pre-register the
    March-May window before running, and require it in all three folds
    with a positive control that clears +3 in at least two.

  * **31, HITTER-PARK FIT INTO `sim.py` — MEASURED 2026-09-10, COUNTED
    NOT FITTED, AND READY. This is the strongest lead on this list.**

    Savant's thirty park columns kept as a VECTOR instead of averaged to
    `xhr`, double-centred to remove his own power (`b_hr` has it) and the
    league park profile (`park_hr` has it). What is left is whether this
    hitter's contact fits this yard — which a SCALAR park factor cannot
    represent, because park shapes are directional and arbitrary.

    ESTABLISHED, and every control is in the notes entry:
      - within hitter AND within park, 117,034 batter-games, **z +2.97**,
        MONOTONE across all five quintiles (-0.29 pp to +0.24 pp);
      - calibrated slope **0.863 +/- 0.291 against a nominal 1.0**, so
        there is NOTHING TO FIT — rule 5 satisfied by construction;
      - tails worth **+23.6% / -21.9%** on a home run rate, the order of
        `PLATOON_MULT`;
      - year-over-year reliability of the residual **+0.227**;
      - handedness geometry falls out without handedness being in the
        construction (bal/cle/pit favour lefties, sf/hou/chc righties).

    ESTABLISHED NEGATIVE: it does NOT help a per-game home run
    classifier, three model forms, all flat or worse. That is a statement
    about a 12% coin flip and a tail effect, NOT about the mechanism —
    read the reconciliation in the notes before re-litigating it.

    THE BUILD: a per-(batter, park) multiplier on `m_hr`, entering beside
    `PLATOON_MULT` and AFTER `NEUTRALISE_PARK` — the league park mean is
    already removed from both, so applying it before would double-count.
    Prior COMPLETED season only, `TIER_BACK = 2` lookback, shrunk on the
    residual at `K["bat_hr"]`; no fit for a hitter without a vector and
    none for a neutral site, which is the rule park factors follow.
    `_fit_for` and `_venue_park` in `scratchpad/hr_clf.py` already build
    it and can move to `src/context/` roughly as they stand.

    THE FALSIFIER, PRE-REGISTERED: `hrbat` and `hrshape` in the battery,
    four folds. The mean HR level must NOT move — this term is centred and
    a level shift means the centring is wrong, which is exactly how item
    24's falsifier fired. What should move is the batter-level spread. And
    the honest caveat: **the battery may be blind to it**, per the
    "nothing moved" rule — the population is every batter-game but the
    effect is in the tails, so name the row before running, and if none
    can see it, build the row rather than claiming it moved.

    OPEN QUESTION worth one measurement first: `ATH` is mapped to
    Savant's `oak` column, but the Athletics play in Sacramento now and
    the geometry is the whole point. 150 games. Check which park that
    column describes before shipping.

  * **29, THE PROJECTED LINEUP IS THE BINDING CONSTRAINT ON PER-HITTER
    NUMBERS — measured 2026-09-10, not a modelling item.** The projected
    nine gets 7.02 of 9 right on average and is fully correct 5.5% of the
    time (1,072 club-games, 2026-08-01 onward) — about two names per club
    wrong before lineups post. `slate.projected_lineup` already said a
    confirmed lineup is REQUIRED for batter props; `hr_odds` now marks
    projected rows and says re-run. ESTABLISHED: the overlap. NOT
    ESTABLISHED: what it costs the PREDICTION, which is not the same
    number — a wrong ninth hitter matters less than a wrong cleanup
    hitter, and the two clubs' totals barely move. The measurement that
    would settle it: replay recent dates with the PROJECTED nine and
    again with the ACTUAL one, and score both against what happened on
    the `hrbat` rows. Cheap, and it is the only honest way to state a
    live number's accuracy before first pitch.

  * **34, WHAT TELLS TWO STARTS APART — opened 2026-09-11 when 32's per-arm
    offset came back a powered null. `shape.outs_corr` is 3.7-5.0 sigma
    short of the per-arm ceiling in ALL FOUR folds, and the per-arm
    direction is now BOUNDED at a sixth of that gap with the leash already
    holding 57% of the sixth. So the defect is real, large and NOT a
    per-arm constant. Best-measured candidate: pitch efficiency (+0.137
    against the per-arm outs residual, larger than the decision-fitted
    offsets managed). Instrument exists and is four folds deep.**

  * **22, THE SAVE ROWS.** Unchanged in priority. 19.1 closed next to it
    and the two MIGHT be one mechanism, but that is unestablished and 19.2
    is small — take 22 on its own rows, not as half of a pair.

  * **7f, THE WIDTH OF THE OUTS DISTRIBUTION — opened 2026-09-10 by 7e's
    failure, and it is the better-posed version of what 7e was chasing.**
    `outs_sd` overshoots real by +0.36 to +0.44 in every fold while
    `outs_mean` is SHORT by 0.09 to 0.48 — the model produces too many
    short starts AND too many long ones at once. That is why 7e's level
    term could only trade the long tail against the mean, and why the
    long-line rows (o18.5 +3.3, o20.5 +2.9) never had a level fix. NOTE
    THE PARALLEL: this is the same shape as the RUN distribution's
    clustering defect, but pointing the OTHER way — runs are too NARROW,
    outs too WIDE. Do not assume one mechanism. Instrument exists
    (`shape` rows in the battery, all four folds).
  * **23's own residual.** `relief_le2_share` +3.2 se and
    `relief_mid_entry_share` +3.0, sign-stable across four folds, with a
    battery row that will now see any change. The suspect is the mid-inning
    ENTRY rate rather than the hook depth.
  * **13, per-pitcher HBP/WP.** Reliability settled; the same four-season
    scan grouped by pitcher. Small (~0.055 runs combined) so it is a
    low-priority ship, but nothing about it is unresolved. NOTE the WP half
    has no per-arm slot at all — `WP_PB_RATE` is a module global and lumps
    in passed balls, which belong to the catcher — so that half is a build,
    not a table swap. The HBP half is cheap: `PitcherRates.hbp_rate` exists
    and `game.build_side._role` already yields to a rate set upstream.

**OPERATOR RULING 2026-09-09, AFTER 8c CLOSED FLAT: STOP CLEARING THE
SUB-FLOOR SHELF.** 8c and 13 are both under the 0.05-run floor, and the
observation that ended the session's first item is that EASY AND SMALL ARE
THE SAME SHELF here. Rule 3 admits small-and-measured, but rule 14 orders
level errors and structural gaps FIRST, and the list currently has three
2-5 sigma defects with named instruments (7e, 19.2, 22) sitting behind
sub-floor cleanups. Take those first. 13 is not refuted, it is deprioritised.

NEEDS A DECISION BEFORE IT IS AN ITEM: **6/18** (reliability settled,
sensitivity not — run `leverage.py` first). **7e** WAS in this bucket and
is now the active item.

BLOCKED OR AN OPERATOR CALL: 9 (`fitf5.evaluate` cannot take a park), 14
(needs stored boards graded, and nothing grades them), 10 (puts a price back
in the room).

---

# OPEN

## THE LEASH, THE REMAINDER OF `PLAN-pitch-history.md`

Steps one and two of that plan are done (notes, 2026-09-07): per-start
reliability measured, then the league-wide screen — secondary velo, FB
spin, FB vertical break and zone->K all dead or weak; ZONE->BB ALIVE and
SHIPPED as `sim.USE_ZONE_BB`. STILL OPEN: the per-channel leash half-life
(outs only, K flat) — pre-registered day 22, wiring exists switched off in
`pitcher_rates` — plus the stopgap board flag for sim-vs-last-10 outs
divergence, display only.

**THE HYPOTHESIS IS COMPRESSION, NOT STALENESS (corrected 2026-09-09).**
`team_offset` is added to a REMOVAL hazard, so a NEGATIVE offset buys a
LONGER outing (`OUTS_PER_OFFSET`: -2.0 maps to +3.00 outs). The poster
cases below all carry a negative offset already and we STILL price them
short of their own record — so the offset is not fitted short, it is not
moving FAR ENOUGH. The base hook regresses everyone toward a generic
length and the per-pitcher offset under-corrects, so short-leash arms run
too long and long-leash arms are pulled too short. `OFFSET_CLAMP = 2.0`
caps the whole adjustment at about +/-3.3 outs, which is the structural
reason it cannot reach an opener.

Poster cases, each arm's shipped `sim.leash` offset against 2026:

  * Yamamoto, offset -1.16. Career 17.60 outs a start, 2026 **19.68**. We
    price over 18.5 outs at 40.5% against his own 52.0% (13/25, se 10.0).
  * Sanchez, offset -0.89. Outs by season 15.9 -> 16.9 -> 18.8 -> 18.1. Our
    K line implies 21.9 batters faced against the market's 24.0; the outs
    market confirms it independently (our over 18.5 36.0%, Kalshi 47.4%).
  * Lowder, offset -0.16. Over 14.5 outs: his 2026 76.2% (16/21), ours 66.1%.

**DO NOT PRE-JUDGE THE DIRECTION — the counter-evidence is real.** Where the
leash table has NO entry the error runs the other way: Robert Stock (offset
0.0, 13.0 outs a start) priced 65.4% over 14.5 against his own 33.3%, Lake
Bachar (offset 0.0, 6.9 outs) 61.7% to clear 4.5 K against a market at 7.5%.
And Zebby Matthews HAS an offset (-0.74) and is still too long, 64.5% over
15.5 against 42.2% on 45 starts.

A FIRST CUT EXISTS AND MUST NOT BE QUOTED: regressing (implied outs - his
own 2026 mean) on (his own 2026 mean) over 12 arms gave slope -0.42, r
-0.56, but his own mean appears on BOTH sides with se ~0.9 outs against a
between-pitcher spread of ~1.1 — noise in a PREDICTOR attenuates the slope,
the `m_er` failure CLAUDE.md already records. The sample is selected too
(arms whose implied line misses the printed rungs drop out).

THE MEASUREMENT TO RUN FIRST, cheap because both halves exist: for every
start in the holdout compare the SIMULATED outs distribution to that
pitcher's own trailing record, bucketed by (has an offset / none) and by
offset magnitude; split-half within pitcher (estimate on odd starts, score
on even) so the predictor is independent. State the power before the
result. Flat in offset magnitude kills the story and leaves only the board
flag; a slope hands the half-life its falsifier.

**6. Per-runner speed.**
Reliability +0.834 — the most repeatable player-level quantity measured in
this project. (Triple share +0.506; pitcher HBP +0.711 and was judged worth
wiring.)
The model has NO per-runner speed anywhere. `STEAL_TABLE` is keyed on (base
state, outs) alone; `FIRST_TO_THIRD_ON_1B`, `SECOND_SCORES_ON_1B`,
`FIRST_SCORES_ON_2B` and the `ADVANCE_*_ON_OUT` tables are keyed on the out
count alone. A burner and a backup catcher are the identical baserunner.
Reliability is settled, SENSITIVITY is not. Run `leverage.py` first —
reliability without sensitivity is how park died three times.

**7a. SHIPPED 2026-09-09 — the boundary backbone is re-solved and both
curves now read the counted table.** `USE_PITCH_HAZARD_BND = True`.
Holdout cell error 0.0303 (parametric) -> 0.0176; the four-fold middle band
improves in ALL FOUR folds; all-line error on the 2026 ladder 0.0363 ->
0.0201. `scratchpad/hz_iter.py` is the solver, `hz_cv_bnd.py` the four-fold
score. Result and the retracted premise are in the notes, 2026-09-09 fourth
entry. NOTE the item's founding numbers (0.0265 -> 0.0314) were RETRACTED —
they came from a double-wrapped logger in `hz_cells.py`, fixed the same day.

**7e. BUILT, SCORED AND PARKED 2026-09-10. `sim.USE_HOOK_MONTH = False`.
THE FALSIFIER FAILED ON BOTH CLAUSES AND THE ITEM'S PREMISE BELOW IS
REFUTED — read this before anything under it.**

The term exists, counted and switchable: `sim.BND_MONTH_OFFSET` +
`bnd_month_offset()`, `game.Side.bnd_month_offset`, both branches of
`removal_p`. Suite 518 -> 522, four mutation-verified checks.

WHAT FAILED. Clause 1 (cut o18.5/o20.5 in ALL FOUR folds) fails on 2023,
whose gap was already NEGATIVE — too FEW long starts, so pulling harder
widened it. Clause 2 (without giving back the middle band) fails: five of
five middle rows worse in 2023, four of five in 2026. And `outs_mean` went
adverse in all four folds. It bought `spike_15_share` and
`boundary_share_by_decision`, better in all four.

**THE PREMISE IS THE CASUALTY: closing the seasonal gap does NOT close the
long-line overshoot.** THE OUTS DEFECT IS WIDTH, NOT LEVEL — `outs_sd`
overshoots +0.36 while `outs_mean` is SHORT -0.15, so there are too many
short starts AND too many long ones at once. A level term can only trade one
tail against the mean. **Anything below reasoning "9% too permissive, so
pull harder" is refuted.** The replacement item is the WIDTH of the outs
distribution, and it is a better-posed target than this ever was.

STILL ESTABLISHED, and worth keeping: the seasonal shape in the DECISIONS is
real (Sep+Oct/Jul+Aug ratio 1.376, z +5.2, sign-stable 3/3 train seasons,
12,897 rows), and **THE MID-INNING CURVE CARRIES THE SAME SHAPE** (OR 1.314,
z +3.9, 3/3) and is deliberately unwired — two mechanisms behind one flag
cannot be told apart.

TWO TRAPS THIS COST, both now guarded. (1) "The 50-78 pitch buckets" are
bucket LABELS spanning pitches 50-84; reading them as a 50-78 RANGE drops
the highest-hazard cells and deflates every month by a third — a positive
control caught it. (2) **THE FALSIFIER NAMED THE WRONG FOLD.** 2026 is
13.1% Sep+Oct against 34-37% in the other three (the season is still in
progress), so every 2026 movement was ~0.1 se by construction. Check a
pre-registered bar for POWER when you write it, not just direction.

WORKLOAD-TO-DATE IS UNTESTABLE, NOT REFUTED: MLB workload-to-date does not
mean "stretched out" (a man making his second big-league start in June has
been throwing in the minors all season) and no minor-league workload is on
disk. Do not re-run it expecting an answer.

--- the original item, kept for the counts behind it ---

**7e. A CALENDAR TERM IN THE HOOK — opened 2026-09-09 by 7a, and it is the
named cause of every adverse row that shipped with it.**
The boundary hazard has a strong seasonal shape and the model cannot see the
date. Pooled over the 50-78 pitch buckets, train rows:

    Mar 0.2205   Apr 0.0684   May 0.0663   Jun 0.0715
    Jul 0.0754   Aug 0.0757   Sep 0.1041   Oct 0.1027

Starters are not stretched out in March and are managed hardest in
September — 3x trough to March, 1.5x June to September. `PITCH_HAZARD_BND`
is fitted on May-September (pooling 0.0775) and every scoring run here is
July-onward (0.0853), so the hook is ~9% too permissive exactly where the
holdout lives. That is the measured cause of the shipped state's long-line
overshoot (o18.5 +0.034, o20.5 +0.027, both ~3 sigma), the `outs_sd`
overshoot (+0.33 against real) and the `spike_15`/`boundary_share` slips.

ESTABLISHED: the seasonal shape, on 31,235 boundary decisions. NOT
ESTABLISHED: that a date term is the right SHAPE for it — "days since
opening day" and "is it September" are different mechanisms, and the March
spike is probably a stretched-out/pitch-limit effect rather than a calendar
one, so a workload-to-date term may beat a date term.

**DO NOT CLOSE THIS BY REFITTING THE TABLE ON JULY-ONWARD ROWS.** That is
fitting to the evaluation window, and the 2026 half of it is the holdout.
FALSIFIER, pre-registered: a calendar term must cut the o18.5/o20.5 gap in
the 2026 fold without giving back the middle band, in all four folds.
WATCH THE PEN when picking fit windows — an April rate freeze gives 17 pen
clubs and 30 arms (see TODO 20 and `hz_iter.load_windows`'s assertion).

**8. Role-based bullpen deployment, and fatigue.**
`build_side` samples 8 arms weighted by appearances and `next_arm` walks that
list IN DRAW ORDER. No leverage — the most-used arm is drawn 84.4% of games
and lands at average slot 3.01 of 8, as likely to pitch the sixth as the
ninth. No situation — nothing knows the score, the platoon or the save. No
fatigue — the pen is redrawn independently every game AND every draw, so
nothing records that an arm threw 30 pitches yesterday.
`deploy.py` measured that role is real and projects (split-half +0.55 to
+0.78 over 319 relievers). SENSITIVITY IS NOW SCREENED TOO
(`scratchpad/deploy_screen.py`, 20,000 paired draws): the oracle ceiling on
re-ordering the same eight arms is 0.618 runs, twelve times the leverage
floor, so this is not a sub-floor mechanism.
**BUT READ WHERE THAT 0.618 COMES FROM BEFORE BUILDING.** A nine-inning game
reaches only ~4.4 of the 8 drawn arms, so most of the ceiling is WHICH arms
are exposed (~0.6 runs), not WHEN each pitches (~0.04). A rule that only
re-times a fixed set of arms buys the small number. The unbounded channels
are SITUATION (a closer appears only in save situations — shape, not mean)
and FATIGUE. Start with exposure: "the manager uses his best available arms
in a close game" is a bigger and simpler lever than a leverage index.
**ITS FORMER HEADLINE EVIDENCE IS GONE.** The ninth-inning gap it inherited
from 11b was two driver bugs, now fixed, and the ninth reads +2.0% / z +0.3.
Do not re-cite it. Item 21 is the cheap, counted slice of this item.

**FATIGUE IS SPLIT, MEASURED 2026-09-09, AND ONLY ONE HALF IS ALIVE.**
As a RATE effect it is DEAD: within-pitcher paired over 56,793 pre-holdout
relief outings and 311 arms, pitched-yesterday minus rested is <= 1.0 sd on
every channel (k/bb/hr/h/outs), and three-in-four-days is equally flat. The
harness is positive-controlled — an injected 2.0 points of K% returns at
-4.9 sd, attenuated to ~2/3 by zero-clipping — so the power is about one
point of K% and nothing that size exists. `scratchpad/pen_fatigue.py`. DO
NOT re-run this as a rate model. As an AVAILABILITY/SELECTION effect it is
real and unbuilt: +6.2% / 4.2 sigma on who gets the save slot. It belongs
with item 21, where the mechanism already exists to receive it.

**AND THE EARLY-INNING SELECTION PROFILE IS MISSING ENTIRELY** —
`PEN_PICK_LATE = 7`, so nothing selects before the seventh and early relief
is pure draw order. Counted 2026-09-09: the real bulk arm sits at quality
percentile 0.564 of his pen against the appearance-weighted draw's 0.452,
+3.8 sd, so THE ENGINE'S EARLY RELIEVER IS TOO GOOD. (92 games, 2026 only,
current-season rates as the quality proxy — recount across four folds with
rates frozen at each cut before wiring.) Same mechanism as `PEN_PICK`, one
more counted table, and it covers item 15's bulk arm for every early entry
rather than only the announced ones.

**8c. CLOSED 2026-09-09 — scored and PARKED. See the CLOSED section.**

**9. Ship and score the seasonal home-run term.**
Measured on 2023-2025; applied out of sample it moves a team total from -3.9%
to +0.7% against actuals. BLOCKED because `fitf5.evaluate` cannot take a
park, so it has never been scored on F5 CRPS. The walk slot it also
needed shipped 2026-08-29.
Until it ships, treat July/August model totals as biased LOW by 0.15-0.20
runs a side.

**10. Get `total_market` to complete a run.**
Full-game totals are a stated product that has never once been scored against
a settled price. `scratchpad/tonight.py` is the workaround. NOTE the betting
layer was deleted 2026-09-05, so this is now an OPERATOR CALL that puts a
price back in the room.

**11c. Extra innings are now reached too often.**
OPENED BY THE 11b FIX, and unconfirmed. P(extras) 0.102 against a real 0.083
(z +2.0) and extra innings/game 0.147 against 0.114 (z +2.1); it was 0.079
before the half-innings were corrected. Runs per extra half is still short at
2.689 against 3.026. `scratchpad/ninth.py` is the instrument.
Two sigma on a quantity nobody pre-registered — treat as a direction.
Item 19's coupling measurement excludes extras and will speak to this.

**11d-residual. The model produces less home-field advantage than the league
has — 0.263 runs against a counted 0.306. NOT AN ITEM YET.**
0.8 sigma, a direction and not a finding, recorded so it is not re-derived.
**DO NOT CLOSE IT BY TUNING `HOME_OPP_*`** — each is counted at 4-11 sigma on
its own rate, and moving them to hit a run target is the forbidden
solve-for-a-level. The residual belongs to home/road channels with NO
parameter at all: fielding errors, baserunning, and the structural effect of
batting last. Home runs were counted (0.9710, z -2.2) and deliberately left
on the contact constant rather than given one.

**12. The prior is shrunk twice.**
`_load_seasons` loads prior seasons through `pitcher_rates`, which already
shrank them, and `shrink_target` shrinks again with the same constant.
Home-runs-sized: a pitcher keeps 0.418 of his own homer record where pooling
once gives 0.568. K is only 2.6%. Worth ~0.044 runs.
The naive fix (`USE_RAW_PRIOR`) was scored and LOSES — +0.00944 F5 CRPS,
z +2.6, 4/4 salts. DO NOT re-run it. The real fix is one shrink against a
DISCOUNTED sample, and that discount has never been measured: `PRIOR_DECAY`
discounts the RATE and nothing discounts the SAMPLE.

**13. Per-pitcher hit-by-pitch, and per-pitcher wild pitch.**
Previously discarded for sitting under the leverage floor; admissible now.
HBP reliability +0.711, sd 0.00675, p10 0.0043 against p90 0.0200, ~0.035
runs pitcher-only and near 0.05 with the batter side. Wild pitch +0.657 and
~0.020 runs.

**14. Attribute a disagreement on the board — RATE or HOOK.**
The biggest edges arrive with no cause attached. On 2026-08-27 six of the top
ten rows were ONE lineup effect and it took a manual investigation to see it.
Attribute each gap to pitcher / lineup / park, and group correlated markets.

THE CONCRETE VERSION, scoped 2026-09-09 after two by-hand spot checks cost a
round of analysis each. A strikeout line is `batters faced x k_pct` — one
equation, two unknowns — so an edge of a given size can be the model
disagreeing about the PITCHER or about the MANAGER, and the printed number
looks identical either way. Those two halves have opposite track records:
the rate is measured accurate to a tenth through K 4.5-7.5, the hook is a
manager decision reproduced only in aggregate.

**THE SPLIT NEEDS TWO MARKETS ON THE SAME START AND THAT IS THE WHOLE
TRICK.** The K market gives `BF x rate`; the OUTS market pins `BF`
independently; rate falls out. From a K line alone the two are
inseparable — do not attempt it, and do not tag a rung whose outs book is
missing (several arms on the 2026-09-09 board had none).

ESTABLISHED, both worked by hand on the 2026-09-09 board:
  * Cristopher Sanchez u6.5 K. Our k_pct 26.4% against his own raw 27.2% —
    essentially exact. The whole 0.54-K gap is exposure: our line implies
    21.9 batters faced, the market's 24.0. The outs market confirms it
    rather than assuming it — our over 18.5 at 36.0% against Kalshi 47.4%,
    his 2026 average 18.1 outs. A HOOK gap with no strikeout opinion in it.
  * Shane Baz u4.5 K, the contrast. Rate-driven, and his own under-rate
    trends toward it: 28.6% -> 35.5% -> 46.4% across 2024/25/26.

GENERALISES to earned runs, walks allowed and hits allowed — all the same
`BF x rate` shape with outs as the shared anchor. `kalshi.SERIES_BY_STAT`
ALREADY maps KXMLBERA / KXMLBWA / KXMLBHA and the board prices none of
them. DOES NOT GENERALISE to game, team or F5 totals: no rate-times-
exposure structure and no per-start history for a matchup that has never
happened. Totals get aggregate calibration instead (fair lines averaged
8.41 on 2026-09-08 against the league's ~8.5).

THE SECOND CHECK, and it is weaker — the pitcher's own empirical clear rate
for that exact line, by season, off `mlb_pitching`. A SANITY CHECK, NOT A
VERDICT: n is about 30 starts a season so se is ~9 points, and it is
UNCONDITIONAL while our number is conditional on tonight's nine. The model
is SUPPOSED to disagree with a season average. The decomposition is the
more robust half precisely because the leash barely moves with opponent.

NOT ESTABLISHED, and this is the item: that a hook-tagged gap actually
scores worse than a rate-tagged one. The tag is a plausible story until it
is graded, and a plausible story that reorders a board is exactly the kind
of thing this project has been wrong about before.

FALSIFIER, pre-registered: tag every quoted rung, then score our
probability against the Kalshi mid on OUTCOMES, split by tag. If
hook-tagged rungs do not show worse resolution than rate-tagged ones, the
tag is decoration and comes off the board. This needs stored boards
carrying the mids as they were at print time; `bets/2026_09_08_board.json`
and `bets/2026_09_09_board.json` are the first two and nothing grades them
yet.

**15. THE OPENER — PARKED 2026-09-09 BY OPERATOR DECISION.** The exit, the
recency weight, both halves of the relief hazard and the bulk-arm leash have
all shipped; what is left is the live slate override and the swingman, and
neither is worth a session on a population that is 2-3% of starts. THE
RETROACTIVE RULE IS THE ONE THING TO CARRY FORWARD: a real opener start is a
SHORT START THAT ENDED ON AN INNING BOUNDARY AND WAS NOT A SHELLING (<= 6
outs, outs % 3 == 0, <= 2 runs), which finds 277 in the four July-onward
folds against the prospective gate's 444 flags — 93 real openers the gate
MISSES and a much cleaner measurement population. Use the prospective gate
for PRICING and the retroactive rule for MEASURING; collapsing them is why
the bulk arm was scored on 23 sides when 75 were available.

What shipped: `USE_RELIEF_INTENT` and `USE_OPENER_EXIT` (a flagged
short-yardage starter exits on a bootstrap from his own outs record), plus
the `USE_OPENER_POOL` no-record fallback. Details in the CLOSED section and
the notes. `scratchpad/opener_outs.py` is the instrument.

**AND `OPENER_HALF_LIFE_DAYS` = 120, SHIPPED 2026-09-09.** The "role-drift
staleness" noted here got its recency WEIGHT, exactly as this line
predicted, and it found a SECOND failure nobody had looked for: the flat
mean was also flagging arms who had gone BACK to the rotation, so 23.3% of
the starts the gate fired on went fifteen outs or more. Recall 63.6% ->
70.4% and false alarms 23.3% -> 21.1% — it dominates on both axes. Chosen
on train RMSE with an interior optimum, confirmed on holdout, scored in the
affected games (`scratchpad/opener_decay.py`, `opener_decay_score.py`).
**NOT CLOSED BY IT: the gate still misses ~27% of real opener starts in
every month.** That residual is now the item, and it is a POPULATION the
decay cannot reach rather than a stale estimate.

STILL OPEN INSIDE THIS ITEM: weight the bootstrap DRAW by the same decay.
Deliberately unbundled — it needs a different call into the rng, and two
mechanisms behind one flag cannot be told apart.

OPERATOR DIRECTIVE 2026-09-09, and it is the shape of the remaining
build: the pitching side of an opener game is a SEQUENCE OF TYPED ROLES —
(opener) -> (bulk arm) -> pen — and the bulk arm is one of THREE types,
counted at 40.6% bona fide starter / 18.6% swingman / 40.8% pure
reliever (full bullpen game). Model each: the starter-as-bulk uses his
own rates plus the counted role diff (interleaved swingmen, relief minus
start: K% +1.01, BB% -0.54, HR% -0.61, BABIP -1.06; per-pitcher does not
repeat, POOLED or nothing — still unwired, nothing consumes it). The
pure-bullpen game is the pen we already sample plus the intent tables.

**RE-COUNTED 2026-09-09 WITH THE TYPE READ PROSPECTIVELY** — off the
follower's own trailing 30 appearances, where a REAL start is an order-0
outing of 12+ outs so a run of opener starts cannot classify a man as a
starter (`scratchpad/bulk_type.py`, 687 planned openers). 31.3% starter /
20.2% swingman / 48.5% reliever, i.e. **51.5% of the time a real arm
follows the opener**. Same shape as the 40.6/18.6/40.8 above under a
tighter classifier; prefer these numbers, the population is defined and
the type does not read the game being classified.

**AND THE STARTER TYPE IS HOOKED EARLY, NOT PITCHING DIFFERENTLY.** Paired
against his own normal starts: -3.15 outs (se 0.30) and -15.56 pitches (se
1.43), ~-10 sigma each, which is 4.95 pitches per lost out against his
normal 5.3. **THIS REOPENS THE LEASH REPRESENTATION.** The plan rules a
leash fix out because `OFFSET_CLAMP` tops out near +/-3.3 outs and an
opener needs ~-12 — true of the OPENER, but the BULK ARM needs -3.15,
which is INSIDE the clamp. The engine can already express him.

DO NOT MODEL THE NAME — model the TYPE. Step zero killed predicting WHO
follows; the type mix above is what the engine needs, and it is countable.
An announced name is worth having only for the rates it pins, and the
counted selection profile below covers most of that.

**SCOPED 2026-09-09, AND THE OBVIOUS BUILD IS THE WRONG ONE. READ THIS
BEFORE STARTING.** `scratchpad/bulk_shape.py` measures what the engine
actually hands the arm behind a flagged opener, over four folds:

    real                   mean 7.39 outs   <=6 55.2%   >=15  9.8%
    sim (as diagnosed)     mean 5.00        <=6 77.2%   >=15  3.6%
    sim, relief hook OFF   mean 7.03        <=6 61.6%   >=15 11.8%
    sim, AFTER item 23     mean 6.17        <=6 65.8%   >=15  7.3%

**HALF OF THIS ITEM WAS PAID FOR BY ITEM 23 AND NOTHING HERE WAS BUILT.**
Re-measured 2026-09-09 on the corrected hook (same instrument, same 174 real
followers): the mean gap 2.39 -> 1.22 outs and the >=15 share 6.2 -> 2.5
points, roughly half and three-fifths. AND IT CONFIRMS THE DIAGNOSIS BELOW
FROM A SECOND DIRECTION — the shipped engine now sits at 6.17 against the
hook-OFF control's 7.03, where it used to sit at 5.00, so most of what the
`--nohook` control was attributing to "the hook is too aggressive for a long
arm" was in fact the STALE KEY charging him the just-arrived rate one batter
early. What remains is smaller and is the genuinely bimodal part.

The defect is real — the follower was 2.4 outs short with a third of the
long outings. **BUT IT IS NOT THE CONTINUATION TABLE.** That count was
done (the shipped intent bucket 0 under-continues a true bulk arm at every
depth: 0.7821 vs 0.7569 clean-entry, 0.5000 vs 0.3788 by the fourth extra
inning, 1,135 train rows) and it is worth about half an out. Chaining the
shipped hazard by hand predicts ~9.0 outs against the engine's 5.00, and
the `--nohook` attribution control shows why: **`RELIEF_MID_REMOVAL` is the
binding constraint.** It was counted over 50,023 in-inning relief plate
appearances, a population of one-inning arms, and applied to every arm at
7-10% PER PLATE APPEARANCE — survivable facing four men, fatal facing
twenty. Fourth instance of "measured on one role, applied to all of them".

**THAT TABLE HAS SINCE BEEN RECOUNTED TWICE AND THE NUMBERS ABOVE ARE THE
ORIGINAL DIAGNOSIS, NOT THE CURRENT ENGINE (item 20's rule).** First the
intent split (part one below), then the STALE-KEY correction of item 23,
which found the whole table shifted one plate appearance and cut the
just-arrived cells from 1.5-8% to 0.0-0.3%. Both push the same way — arms
stay out there longer — so anything in this item reasoning from "the
follower is 2.4 outs short" needs re-deriving before it is acted on.

SO THE ITEM WAS: condition the MID-REMOVAL hazard on intent, the same
one-more-column move that fixed the continuation hazard.

**PART ONE SHIPPED 2026-09-09 as `relief.MID_INTENT`** — counted on 9,254
pre-holdout games via `scratchpad/mid_intent.py`. An arm entering in innings
1-3 is pulled about a THIRD as often through the 4-12 batter range as a late
entry, and the flat table was charging every arm the late rate. Depth was
the other candidate and is REFUTED (the hazard does not fall past the
shipped 9-batter cap; a 600-game smoke test said it did and that was noise).
The bulk cell turned out redundant with intent bucket 0, so it is one
dimension and no opener special case. Battery clean, suite 486 -> 487,
three mutations.

**PART TWO SHIPPED 2026-09-09, AND IT WAS NOT AN OPENER FIX AT ALL.**
`CONTINUE_INTENT` and `EXTRA_INTENT` were counted on the wrong denominator
for EVERY reliever in EVERY game — the opener's bulk arm was only where it
showed, because he faces the most batters. `relief.asked()` carries the
argument; two errors, both pushing one way:

  * an arm PULLED MID-INNING was scored as declining to come back out,
    while `mid_removal` had already charged him per plate appearance —
    removal counted twice;
  * an arm who CLOSED OUT THE GAME was scored as declining an inning that
    never existed. The engine's roll there decides nothing.

The late clean entry — the cell nearly every reliever in every game hits —
went 0.0992 to 0.1803. Recounted on 62,278 pre-holdout stints (the first
version used every row, holdout included). `scratchpad/continue_intent.py`
separates the three denominators; `relief.tally` reproduces it independently.

SCORED ON RELIEF LENGTH, `scratchpad/pen_shape.py`, all four folds, every
relief outing (23,844 real):

    outs         mean    <=2      3     4-6    >=7    arms/side
      real       3.34   22.3%  53.7%  19.5%   4.5%      3.383
      before     3.01   29.3%  52.5%  15.2%   2.9%      3.726
      after      3.20   29.1%  47.7%  18.7%   4.5%      3.505

Mean gap 57% closed, arms-per-side gap 64% closed, the 7+ share landing
exactly. Battery diff against `cc4475863ce0`: NO ROW MOVED BY MORE THAN ONE
SE — which is the expected result for a change that swaps one reliever for
another rather than changing a rate. Suite 487 -> 490, three mutations.
MIND THE INSTRUMENT: `pen_shape` first read 4.23 arms a side because
`_end_of_inning` fires after the LAST inning too, so a failed continuation
roll warms up a phantom reliever who never faces a batter. Filter on
`batters > 0`.

**THE RESIDUAL BECAME ITEM 23 AND WAS LARGELY CLOSED THE SAME DAY** — it was
the mid-inning hook, keyed one plate appearance stale. The `after 3.20 /
29.1%` row above is THE STATE AT THIS COMMIT AND NOT THE CURRENT ENGINE:
it now reads 3.35 outs and 23.0% at two or fewer. Kept as the record of what
this change bought on its own.

ONE CANDIDATE IS ALREADY REFUTED, do not re-check it: the engine does NOT
roll the mid-inning hazard on inning-ending plate appearances
(`_half_inning` breaks at `fr.outs >= 3` first), so its denominator matches
the count's `same_half` convention.

**THE BULK ARM SHIPPED 2026-09-09 as `game.USE_BULK_STARTER`, and the build
was not the typed-role sequence.** The counted answer — a real starter
following an opener goes -3.15 outs (se 0.30) against his own normal start,
inside `OFFSET_CLAMP` — needed a place to attach, and there was none: once
`starter_out` trips, the follower is drawn from the pen and never touches a
hook curve. So he is installed WITHOUT tripping it, which hands him back all
five things that flag gates — his own rates, times through the order,
mid-inning removal, the boundary hook and the continuation hazard.

**TTO WAS THE HIDDEN HALF AND NOBODY HAD COUNTED IT AS A DEFECT.** A
rotation starter working as a bulk arm was being run with NO TTO DECAY AT
ALL while really facing the order nearly twice. `tto` now reads `cur_line`
rather than `side.line` — a no-op for an ordinary start, since they are the
same object.

    the named bulk arm, outs    mean    <=6     >=12
      real (23 outings)        12.57    8.7%    78.3%
      sim, flag off             6.03   65.1%    14.2%
      sim, flag on              9.62   29.5%    38.4%

55% of the mean gap, every column the right way. Battery `7a1ed8609895`:
no row moved by more than one se. Suite 490 -> 499, four mutations.

**READ THE POWER BEFORE READING THAT TABLE.** The mechanism fires on 23 of
7,096 sides over four folds — 174 sides are opener-flagged and only 23 have
a follower who types as a starter. A RUN TOTAL OVER 23 SIDES CANNOT RESOLVE
THIS AND MUST NOT BE QUOTED; the pre-registered falsifier said to score his
own line and that is what `scratchpad/bulk_score.py` does.

STILL OPEN INSIDE THE BULK ARM:
  * **He was 2.95 outs short of real, and item 23 has since moved the whole
    relief hook — RE-RUN `bulk_score.py` BEFORE ACTING ON THAT NUMBER.**
    The general follower gained 1.17 outs from the stale-key fix (table
    above) and the named starter-type follower is the same mechanism with a
    leash on top, so 2.95 is an upper bound on what is left and probably a
    loose one. If the remaining gap is real, check `leash.offset_for(-3.15)`
    = 1.9026 against `OFFSET_CLAMP` = 2.0 — the conversion lands at 95% of
    the available range, so the delta is very nearly being clipped and a
    slightly larger one would be.
  * **The swingman is unbuilt and is 20.2% of followers.** Only the
    starter type is routed; a swingman falls through to the pen. The
    counted relief-minus-start diffs (K% +1.01, BB% -0.54, HR% -0.61,
    BABIP -1.06, POOLED or nothing) still consume nothing.
  * **The live path has no name.** `bulk_follower` reads the RECORDED
    follower from `mlb_stints`, which is the announced pairing for a game
    that has been played. `slate.py` needs the manual override ("bulk arm:
    X", and "stretching out: X" for the relief-to-rotation conversion)
    before this fires on a live board at all.

The operator's framing that scoped this: the typed-role sequence is
over-specified for a population that is 3.5% of starts — "the shape was
obvious immediately and openers are rare, so it might be good enough". Do
not build the three-type model unless something forces it.

AND THE STANDING PRIORITY IS STRUCTURE IN THE PITCHING, operator, same day:
anything that pins down which arm is on the mound reduces what the model has
to guess. Openers are one route and item 21's closer is the other, on the
SELECTION side rather than the LENGTH side.
AND THE SLATE ACCOMMODATES ANNOUNCED COMBOS: the opener and his follower
are usually public before lineups, but `mlb_schedule_with_probables`
carries one arm per side — add a manual override on the slate ("bulk arm:
X") before building any scraper. The step-zero null killed PREDICTING the
follower from history; an announced name is input, not prediction. The
same override should accept "stretching out: X" — a relief-to-rotation
conversion is announced too, and it is the one population the no-record
fallback mis-prices: the pooled curve reads ~6 outs on an arm the club
intends to run 10+.

FALSIFIER for the remaining build, unchanged: the run distribution in
opener games against what actually happened. Note `opener_score.py`'s
run-level CRPS se (0.0164 at 124 games x 100 sims) is larger than the
effects measured so far — score the bulk arm on HIS OWN line (outs, K)
the way `opener_outs.py` scores the opener, or the result will read as a
null whatever the truth.

**16. Propagate projected-lineup uncertainty.**
Two wrong names out of nine moved a headline edge by half. Flag any edge
whose size depends on unconfirmed names.

**17. Per-pitcher pitch efficiency.**
`PITCH_COST` is counted now and the start-level residual is still sd 8.2
pitches: the table has the LEVEL right (85.5 against a real 85.6) and cannot
say WHO is efficient. Pitches per plate appearance are correlated within a
start, so this is a per-pitcher trait rather than noise. Feeds the hook,
which keys on pitch count. Reliability unmeasured — screen before building.

**18. Steal decisions should depend on the runner and the hitter.**
`STEAL_TABLE` is keyed on base state and outs alone, so a steal is
independent of who is running and who is batting. That independence is WHY
the runner-event reorder washed out — the pairing carries no information.
Same table and same code as per-runner speed (item 6); screen them together.

**19. MONEYLINES — the persist-and-score loop is DONE (2026-09-09). NAME THE
COUPLING is the item now.**

`scratchpad/moneyline.py` replayed all four folds (3,548 paired games x 200
draws) and persisted every draw's `(away, home, away_f5, home_f5)` to
`scratchpad/sims/ml_<fold>.json.gz` — gitignored, ~15 min to regenerate, and
the script LOADS the cache when the file exists and `n_sims` matches.
Regenerate rather than mixing cached and fresh draws across engine states.

ESTABLISHED by that pass (Brier-decomposed on outcomes; full tables in the
notes): calibration is GOOD (reliability 0.0005 F5 / 0.0007 full-game),
resolution is THIN (0.0040 / 0.0030 against uncertainty ~0.2495 — 2,861 of
3,548 forecasts sit in 0.4-0.6), the split beats climatology on discrete
CRPS in every quantity with the MARGIN weakest of the three, and item 20's
bullpen bug is positive-controlled as not touching any of it.

**THE ITEM'S ORIGINAL PREMISE IS REFUTED: the margin is too NARROW, not too
wide.** Mean |margin| 3.330 against 3.594 (se 0.047, -5.6 sigma); one- and
two-run shares HIGH, 8+ low at -3.4 sigma. Item 1's old 0.247-against-0.266
one-run figure was an OLD ENGINE number and is retired.

AND IT IS TWO DEFECTS. Club totals are too narrow (model sd 3.117/2.988
against 3.208/3.174, home worse) AND the model puts a +0.059 correlation
between the two clubs' runs where reality has -0.022 (se 0.017, 3.5 sigma),
mostly WITHIN a game (+0.048) rather than between games. sd(sum) 4.437
against 4.463 is a dead heat only because the coupling adds back what the
narrow clubs took out: A GAME-TOTAL INSTRUMENT IS BLIND TO BOTH DEFECTS AT
ONCE.

WHAT REMAINS, in order:

  1. **19.1 CLOSED 2026-09-10, AND IT REVERSED THE PREMISE — see 19.2.**
     The coupling is not invented, it is MISSING, and the sign is the other
     way. Full write-up in the notes; the compressed version is 19.2 below.
  2. The club under-dispersion is the known clustering defect and belongs
     with that item, not this one.
  3. Wire `KXMLBF5` / `KXMLBSPREAD` (same `floor_strike` parse as
     KXMLBTOTAL) if a settled-price yardstick is wanted — OPERATOR CALL,
     because the betting layer was deleted on 2026-09-05.

RELATED and still unrun: team totals are never separately scored and are
CHEAPER than the joint. On 2026-09-09 our mean absolute disagreement with
Kalshi was 3.03 points on the game total against 3.65 on the team totals
(1.20x, larger on the split in 8 of 14 games), and CIN/LAD agreed on the sum
to 0.5 while disagreeing 4.8 on the split. Score the split in the same
replay pass.

**19.2. THE TWO CLUBS' RUNS ARE NEGATIVELY CORRELATED IN REALITY AND FLAT
IN THE MODEL, AND IT IS ALL IN INNINGS 6-8 — opened 2026-09-10 by 19.1.**

ESTABLISHED (notes, 2026-09-10; `scratchpad/ml_extras.py`, `ml_eight.py`;
3,548 games x 200 draws over four folds, se 0.0168 on every correlation):

    window                     model     real      gap      z
    F5 (both bat)             +0.0094  -0.0112  +0.0206   +1.2
    through 8 (both bat)      ~+0.012  -0.0530  ~+0.065   ~+3.9
    through 9 (home may skip) +0.0553  -0.0087  +0.0640   +3.8

  * **F5 IS CLEAN (z +1.2).** The stated modelling target is not touched by
    this. The whole swing happens across innings 6-8.
  * **THE NINTH IS ALREADY RIGHT.** The home club not batting when ahead
    moves reality by +0.0443 and the model by +0.0440 — agreement to
    0.0003. Nothing to fix there, and anything that "fixes" the ninth is
    breaking a correct mechanism.
  * **EXTRAS ARE REFUTED** (2.8% of the covariance; runs in extras 2.785
    against 2.799, z -0.1) and so is **THE MARGIN** (stratifying on the F5
    margin removes 3%). The engine leans on the score LESS than reality
    does late, not more: model 6-9 runs are flat at 3.68-3.72 across every
    F5 margin where reality rises to 3.995 at 4+ (z -2.7).

**PRIORITY IS LOW AND THAT IS THE HONEST READING.** -0.053 and +0.012 both
mean "essentially independent"; the gap is real (3.8 se, four folds) but
small, and it moves the MARGIN and game-total spread, never either club's
expected runs. F5 — the stated target — is clean. Do not let the size of
the z score stand in for the size of the effect.

INFERRED, one candidate of at least two, NEITHER established:

  * APART. 6-8 is the leverage window, so a pen that does not suppress
    enough with a lead lands here, and that is also item 22.
  * TOGETHER. Park, weather and umpire multipliers are applied to BOTH
    clubs of a game at once — a positive coupling the engine manufactures.
    The 9-8 game is the counter-example to any "real games separate"
    reading, and in reality the two forces very nearly cancel.

Reality cannot arbitrate between them from the totals alone: it gives ONE
realisation a game, so its -0.053 mixes matchup composition with anything
dynamic. **The test that separates them is written and unrun** —
`scratchpad/ml_resid.py`, residuals against the model's own per-game
expectation, about a minute off the existing cache. Run it FIRST if this
item is ever picked up; do not screen it with 22 until it has said which
story is live.

THE FALSIFIER, pre-registered: any mechanism that strengthens late leverage
must move the real-against-model through-EIGHT correlation toward -0.05
WITHOUT moving the F5 row (currently z +1.2 and correct) and WITHOUT moving
the ninth's +0.0440 step. A change that closes the through-nine gap by
altering the ninth has broken the one part that was right.

NOTE FOR WHOEVER PICKS THIS UP: the through-eight model number is the only
estimated figure in the table (+0.0035 within-game from a 600-game
`ml_eight` run plus the ~+0.008 between-game part measured at nine). If it
is going to carry a decision, run `ml_eight` on all four folds first.
And DO NOT test this by dropping extras draws — that is a selection on the
quantity being correlated and it reads -0.0090, the opposite sign.

**23. LARGELY SHIPPED 2026-09-09 — the mid-inning relief hook was keyed ONE
PLATE APPEARANCE STALE. A REDUCED RESIDUAL REMAINS AND IS THE ITEM NOW.**

`relief.removal_hazard` advanced the pitcher's accumulators AFTER emitting
the row, so the cell labelled "three batters faced" held the decision taken
after his FOURTH, while `game._half_inning` asks with `rl.batters` once
`apply_pa` has incremented it. The engine read every cell one plate
appearance early, and the hazard has a cliff in it (0.1% -> 7.9%), so a
just-arrived reliever was charged the settled rate. The ENGINE was the
correct side: `boundary.decisions` counts the starter's hook with the
just-resolved play folded in and says so. Recounted on that convention,
`scratchpad/mid_decision.py`; the positive control reproduces the old
literals 57/57 under the old key. THE POOLED HAZARD IS IDENTICAL EITHER WAY
(0.0489) — a relabelling, invisible to any mean.

    key                       before z      after z      real
      relief_outs_mean         -11.2         +1.1       3.3335
      relief_le2_share         +24.7         +3.2       0.2247
      relief_mid_entry_share   +14.0         +3.0       0.2627
      arms_per_side            +15.0         +4.3       3.2800
      relief_ge7_share          +0.5         +2.6       0.0438

**AND THE BATTERY HAD NO ROW THAT COULD SEE ANY OF IT** (max 0.26 se over
662 rows). Not dilution, not mean-versus-shape — no row. The `pen` group was
built for exactly that reason and is now the standing instrument for
anything bullpen-length; `scratchpad/pen_short.py` is the entry-state
decomposition behind it. Full write-up in the notes.

STILL OPEN INSIDE THIS ITEM:

  * **`relief_le2_share` is still +3.2 se, sign identical in all four folds**
    (+2.0 / +0.7 / +1.0 / +3.0), and `arms_per_side` +4.3. About a seventh of
    the former size. The remaining suspect is the mid-inning ENTRY rate
    rather than the hook's depth shape, because `relief_mid_entry_share`
    moved in step with it and is still +3.0 — the engine hands over
    mid-inning slightly too often, and every such handover is a short outing
    by construction.
  * **`relief_ge7_share` went the WRONG WAY, +0.5 -> +2.6 se** (4.73%
    against 4.38%). The long tail is now marginally too heavy. Small, and the
    opposite end of the same distribution, but it is an adverse row and is
    recorded rather than dropped.
  * NOT the boundary hazard (re-counted and shipped the same day) and NOT
    the continuation-table depth cap (refuted, see the parked section).

MIND `pen_shape.py`'s DENOMINATOR TRAP, documented in the file and now
guarded by a check: `_end_of_inning` fires after the last inning too, so a
failed continuation roll warms up a phantom reliever who never faces a
batter. Filter on `batters > 0`.

**22. THE MODEL BLOWS LATE LEADS MORE OFTEN THAN REAL BULLPENS DO — opened
2026-09-09 by the new `save` battery rows, and it is a SHAPE defect that no
mean could see.**

The save rows exist because every bullpen instrument before them was a
proxy — outing length, selection percentile, closer usage rate — and none
said whether the model wins the games a real bullpen wins. Pooled over 1,789
save situations, four folds:

    key                model   actual      gap      se      z
    lead_held         0.9091   0.9212  -0.0121  0.0064   -1.9
    allowed_0         0.7432   0.7703  -0.0271  0.0099   -2.7
    allowed_2plus     0.1447   0.1274  +0.0172  0.0079   +2.2

The model protects a late lead less often, throws a scoreless ninth less
often, and gives up two or more more often. **THE DIRECTION IS THE SAME IN
ALL FOUR FOLDS** (z -0.2 / -1.6 / -1.0 / -1.1), which is what rule 12b asks
for, and the `inning 9+` MEAN row was flat all day while this was true.

TREAT AS A DIRECTION, NOT A FINDING: 2-3 sigma on quantities nobody
pre-registered, measured the same day the instrument was built. What it is
NOT is the closer's identity — that shipped and is now tracking the counted
rates cell by cell. First suspects are the ninth-inning run DISTRIBUTION
(the clustering item) and relief rates against a lineup's best hitters.

**AND IT IS NOT ITEM 23 EITHER — the pre-registered test ran 2026-09-09 and
came back NEGATIVE.** The hypothesis was that one defect produced both: if
the engine gives up on relievers too fast, a save situation churns through
arms and every handover is a fresh pitcher entering cold, which loses leads
without moving mean runs. Item 23's fix took relief-outing length from -11.2
se to +1.1 and `arms_per_side` from +15.0 to +4.3, and the save rows DID NOT
MOVE:

    key                 before gap    after gap      se
      lead_held           -0.0121      -0.0118    0.0064
      allowed_0           -0.0271      -0.0276    0.0099
      allowed_2plus       +0.0172      +0.0175    0.0079

So 22 is real and SEPARATE, and that was settled for the price of one
battery run rather than a session of plausible reasoning. Do not re-open the
"one defect" framing. The two suspects above are what is left, and the
DISTRIBUTION one is the better prior: a mean cannot see it, which is why
`allowed_2plus` and `lead_held` disagree with a flat `inning 9+` row.

**21. THE CLOSER IS NOW A WIRED ROLE (`USE_CLOSER_ROLE`, 2026-09-09), ON
TOP OF THE INNING KEY (`USE_PEN_INNING`). THE STALE GATE IS WHAT REMAINS.**

THE OPERATOR'S RULING, and it is architectural rather than a refinement:
the closer will not emerge from good modelling of anything else, so wire the
role before building anything further on the bullpen. He is his club's
top-fifth K%-BB% arm only 73.3% of the time, so in the other 27% NO
reweighting of `PEN_PICK` can reach him.

Counted on 17,596 pre-holdout club-games with a named closer
(`scratchpad/closer_usage.py`) — P(the entering arm IS the named closer):

                     7th            8th            9th+
      save         4.5 / 1.9%    14.9 / 8.9%    73.3 / 61.4%
      tied         4.2 / 2.3%    12.7 / 4.9%    55.8 / 40.7%
      (rested / worked the club's previous game)

A TWENTYFOLD SWING from the seventh to the ninth, and availability is worth
12 points in the ninth on its own — TODO 8's "fatigue" bullet arriving as a
SELECTION effect. As a RATE it stays dead.

**THE MARGIN KEY IS THE SAVE RULE, RECOVERED FROM THE DATA.** P(closer) in
the ninth runs 0.6724 / 0.6945 / 0.6894 at leads of one, two and three, then
falls off a cliff — 0.5343 at four, 0.2305 at five, 0.0843 beyond.
`_pick_bucket` splits at 2 and 4 and therefore lumps a save in with a
non-save; it was built for the quality profile and is the wrong key for a
role. `_closer_margin` is its own function for that reason.

**HALF-WIRING IT IS WORSE THAN NOTHING, AND THIS IS THE FINDING.** Adding
the role roll while leaving him in the quality draw put the closer in the
SEVENTH on 19.9% of entries against a real 3.3%: he is usually the best
K%-BB% arm, so `PEN_PICK` kept reaching for him. The role roll accounts for
4.5 of those points and the draw for the other 15. He must be RESERVED —
withheld from the profile and entering only through the table.

    P(entering arm is the closer)   before   after    real
      7th, save                     0.1994  0.0400  0.0318
      8th, save                     0.2958  0.1277  0.1185
      9th, save                     0.7680  0.6796  0.6734

That is 21 cells tracking the counted rate where the engine previously had
no notion of the role at all. Battery `847ed46ee069`: no row moved by more
than one se. Suite 503 -> 510, four mutations.

NOT a contradiction of "do not remove him from the pen": his own record has
30% of HIS APPEARANCES before the ninth, which is a different denominator
from his share OF seventh-inning entries. The table lets him work the
seventh at the counted 4.5%.

**THE STALE GATE SHIPPED 2026-09-09** as `CLOSER_STALE_DAYS = 10` inside
`game.name_closer`, split out from the index so the RULE is checkable
without a database. Re-counted on the naming the engine actually uses,
6,990 pre-holdout save slots:

    idle 0-3 days   73.5% of slots   he takes the slot 45.0%
    idle 4-9 days   21.9% of slots                     55.6%
    idle 10+ days    4.5% of slots                      2.8%

Rare and total. Worth **+0.57 points** of naming accuracy — NOTE that is
below the +0.8 this item previously claimed, and the two are not the same
measurement (different slot definition); prefer the +0.57, which is scored
against who actually took the slot on the shipped naming. 4-9 days reads
HIGHER than 0-3 because that is REST, not staleness, and rest is already
carried by the availability dimension of `CLOSER_USE`. All-stale returns
None — no name, no role, the profile answers.

AND THE NAMING VALIDATES AGAINST AN INDEPENDENT SOURCE: on 2026-08-15 the
offline rolling-window naming returns Chapman (BOS), Hader (HOU) and Cade
Smith (CLE), which is exactly who FanGraphs RosterResource's closer depth
chart named when it was fetched the same day. That is why the news-feed
ceiling measured only 1.1 points.

--- superseded, kept for the counts behind it ---

**THE INNING KEY SHIPPED 2026-09-09 as `USE_PEN_INNING`.**

The operator was right and the engine was worse than the item claimed — not
flat across innings but INVERTED. Simulated share taking the best remaining
arm, against the real count on the same construction:

    entry inning                    7th      8th     9th+
      real                        0.2594   0.3007   0.4264
      sim, pooled table           0.3001   0.2719   0.2582
      sim, split by inning        0.2481   0.2581   0.3157

Managers save the best arm for the ninth; the engine SPENT him in the
seventh and had nothing left, and it compounds — an arm used in the seventh
is gone from the ninth's pool. That is why the pooled weight is wrong at
both ends rather than merely blurred.

Counted by `scratchpad/pen_pick_inning.py` on pre-holdout rows of all four
seasons, same quality-percentile construction as `pen_pick.py`: protecting a
lead, the best-fifth share runs 0.3356 / 0.4108 / 0.5750 for 7th / 8th / 9th
against a pooled 0.4415, +15.3 sd from the 7th to the 9th, MONOTONE IN ALL
FIVE MARGIN BUCKETS, thinnest cell 771. Battery `66768f2136fc`: no row moved
by more than one se. Suite 499 -> 503, three mutations.
`scratchpad/closer_score.py` is the instrument.

**STILL SHORT IN THE NINTH, 0.3157 against 0.4264, and the reason is
structural rather than a mis-count.** `PEN_PICK` draws from a PROFILE, so
even in the ninth it deliberately takes a mid-pen arm about 68% of the time.
Some of reality's 0.4264 is a NAMED closer, and a percentile draw cannot
reproduce a name. Closing that last gap means the two unbuilt bullets below,
not a reweighting of this table — do not tune these cells to hit 0.4264,
which is the forbidden solve-for-a-level.

THE TWO THAT REMAIN, both measured, both offline, both from
`scratchpad/closer_slot.py`:
  * AVAILABILITY — he takes the slot 65.0% rested against 58.7% having
    pitched the club's previous game, +4.2 sigma. This is TODO 8's unbuilt
    "fatigue" bullet, and note fatigue is a SELECTION effect only: as a
    RATE it is dead (see item 8).
  * THE STALE GATE — when the named man has not appeared in ten days he
    takes the slot 3.7% of the time (4.8% of slots). Stepping down to the
    next arm on the same count is worth +0.8 points and lands within 0.3
    of a perfect-forward-knowledge oracle. Rare, cheap, and it is the
    whole of what a news feed would have bought.

--- the original item, kept for the counts behind it ---

**THE CLOSER IS SPENT IN THE SEVENTH — SPLIT `PEN_PICK` BY INNING.**
Raised by the operator 2026-09-09. The closer is in the pool and nothing
reserves him for the ninth: `PEN_PICK` routes by margin bucket only, and
its weights were COUNTED POOLED over innings 7-9 — the real structure
(setup 7th-8th, closer 9th) is smeared into "44% best-fifth whenever
leading late", so the engine can spend the best arm two innings early.
Same pooling defect as the hook curves and the relief hazard, same fix:
recount the selection profile keyed (inning 7/8/9, margin bucket).
`deploy.py` already measured role as stable (split-half r +0.55 to
+0.78), so the split should resolve cleanly. Check cell sizes first; the
operator's point is that the ninth-inning closer is one of the few
STABLE, RELIABLE pieces of bullpen behaviour, so this is a count, not a
model. Battery around the wiring per rule 15.

**COUNTED 2026-09-09, and it confirms the item from a second direction**
(`scratchpad/closer_slot.py`, 4,623 save slots). The closer is his club's
top-fifth K%-BB% arm 73.3% of the time (mean percentile 0.163), so
`PEN_PICK`'s 44.15% top-fifth-in-a-lead is ALREADY LARGELY DRAWING HIM —
in the wrong inning. The missing thing is confirmed to be the SLOT, not a
closer object, and naming him needs no new data: most ninth-with-a-lead
entries over the club's last 25 games takes the next save slot 62.7% of
the time.

**BUT DO NOT REMOVE HIM FROM THE PEN.** "He should never appear before the
ninth" is refuted by his own record — 9th 68%, 8th 18%, 7th 6%, 6th 4%,
extras 4%. Almost 30% of his work is earlier.

THREE THINGS TO WIRE TOGETHER, all measured, all offline:
  * the inning key on `PEN_PICK` (this item);
  * AVAILABILITY — he takes the slot 65.0% rested against 58.7% having
    pitched the club's previous game, +4.2 sigma. This is TODO 8's
    unbuilt "fatigue" bullet, and note fatigue is a SELECTION effect
    only: as a RATE it is dead (see item 8);
  * THE STALE GATE — when the named man has not appeared in ten days he
    takes the slot 3.7% of the time (4.8% of slots). Stepping down to the
    next arm on the same count is worth +0.8 points and lands within 0.3
    of a perfect-forward-knowledge oracle. Rare, cheap, and it is the
    whole of what a news feed would have bought.

**32. BUILT, SCORED AND PARKED 2026-09-11. `sim.USE_ARM_HOOK = False`. THE
FALSIFIER CAME BACK A POWERED NULL AND THE ITEM'S FOUNDING PREMISE IS
REFUTED — read this before anything under it.**

The mechanism exists, measured and switchable: `src/context/armhook.py`, one
per-arm log-odds offset per curve over 356,711 pre-holdout decisions,
cluster-robust variances, empirical-Bayes shrinkage times the MEASURED
year-over-year carry, season drift fitted out and discarded, level centred.
`sim.Hook.arm_bnd_offset` / `arm_mid_offset`, suite 540 -> 566, five
mutations verified. Full result in `NOTES-context-layer.md`, 2026-09-11.

WHAT FAILED. On the pre-registered row (`scratchpad/arm_score.py`, 2026
holdout, 1,360 starts, paired seeds, se on the delta by paired bootstrap):
per-start outs correlation **+0.0008 +/- 0.0052**, and **-0.0003 +/- 0.0073**
on the arms the table actually covers. POSITIVE-CONTROLLED on the same
instrument: switching the SHIPPED leash instead moves it **+0.0130** overall
and **+0.0273** on the arms it covers. The harness sees a per-arm hook term
at ~0.02; this one reads zero.

**THE PREMISE IS THE CASUALTY.** The item argued a decision-level fit is the
better-posed version of the leash ("fit the quantity that settles"). Measured
(`scratchpad/arm_dissociate.py`): the per-arm DECISION residual and the
per-arm OUTS residual are NEAR-ORTHOGONAL — the new offsets correlate
**+0.015 +/- 0.094** with the per-arm outs residual while the shipped leash's
implied outs correlate **+0.234**. The decision residual is MORE repeatable
(+0.558 vs +0.225) and worth LESS. The leash's supposed weakness is what
makes it work: it is a residual against the SIMULATION's own error, so it
also corrects the engine ARRIVING AT DIFFERENT STATES than reality. **Rule 10
bites one level deeper than it is written: matching a call site's ARGUMENTS
is not matching its STATE DISTRIBUTION.** Anything below reasoning "fit it on
the decisions instead" is refuted.

**AND THE WHOLE PER-ARM DIRECTION IS NOW BOUNDED, which is the useful part.**
`scratchpad/leash_carry.py`, 8,175 pre-holdout games, 451 arm-pairs: the
per-arm outs residual carries year over year at only **r +0.225** (se 0.047),
so the STABLE between-arm signal is sd 0.551 outs against a season-mean
spread of 1.161. A PERFECT per-arm term is therefore worth **+0.023** of the
`shape.outs_corr` correlation against a printed ceiling gap of **+0.135**, and
the shipped leash already has +0.0130 of it. **PER-ARM HOOK OFFSETS CAN CLOSE
AT MOST ~A SIXTH OF THE OUTS DISCRIMINATION GAP AND THE LEASH HAS ~57% OF
THAT SIXTH. DO NOT OPEN A THIRD PER-ARM HOOK ITEM.**

STILL ESTABLISHED AND WORTH KEEPING:
  * the decision-level residual is REAL and repeatable (+0.558 / +0.397 year
    over year, reproduced by two different estimators). It is simply not
    about LENGTH. If a future item needs to predict WHICH DECISION ends a
    start rather than how long it lasts, this table is the instrument;
  * the era drift of item 33, reproduced independently: boundary season
    offsets 2023 -0.227 -> 2026 +0.301;
  * **THE SECOND SHRINKAGE, and it generalises to every per-arm term this
    project will ever fit.** Empirical Bayes removes SAMPLING noise only;
    it does not remove the fact that an arm CHANGES between seasons.
    Shrinking for sampling noise alone describes his past and over-corrects
    his future. `leash.py`'s K has the same gap — though at only 11% too
    wide (implied sd 0.609 against a stable 0.551) it is not worth a
    rescale, so this is a lesson for the NEXT term, not a repair to that one;
  * `leash.OUTS_PER_OFFSET` is ~0.85 of its claim on the LONG-leash side
    (at -2.0 it promises +3.00 outs and delivers +2.50) and right on the
    short side. Each curve alone is worth HALF of `team_offset`.

THE NEW ROW IS THE LASTING ARTEFACT: **`shape.outs_corr`** in the battery,
four folds, model against the model-free per-arm ceiling, 3.7-5.0 sigma
short in every fold. Built because item 32's falsifier said to build it if
nothing could see a per-arm term, and nothing could. **ITS CEILING IS LOOSE**
— computed within the fold, so it counts in-season variation no prior-season
evidence can know. Do not price the gap; the caveat is in the code.

--- the original item, kept for the counts behind it ---

**32. A PER-PITCHER HOOK OFFSET FITTED ON THE DECISION, NOT ON OUTS —
opened 2026-09-11 by `scratchpad/hook_resid.py`. TAKE 33 FIRST OR REBUILD
AFTER IT; see the sequencing note at the end.**

The hook is a league aggregate and the one per-arm correction it carries —
`sim.leash`, a shrunken OUTS residual converted through `leash.offset_for` —
captures about a sixth of the per-arm signal that is actually there.

ESTABLISHED, all on 89,414 boundary and 303,276 mid real decisions,
2023-2026, standard errors CLUSTERED on (game, side), screen
positive-controlled at +0.40 log-odds and recovering it to four decimals:

  * THE RESIDUAL REPEATS YEAR OVER YEAR, which is the only form a live
    hook could use. Estimate on season N, score on N+1: **boundary r
    +0.538, 147 arm-pairs, se 0.083; mid r +0.373, 402 arm-pairs, se
    0.050** (arm-seasons with >= 120 decisions). Projectable sd 0.0253 on
    a base rate of 0.1146 — about 22% per-arm spread.
  * IT IS NOT THE ERA DRIFT OF ITEM 33 WEARING A PITCHER'S NAME. Removing
    each season's own mean first moves the boundary number +0.559 ->
    +0.538 and the mid number +0.376 -> +0.373.
  * IT IS LARGELY NEW INFORMATION. Correlation with the SHIPPED
    `sim.leash` offset is only **-0.399** over 147 arms, so ~84% of the
    variance is not in the table today. This is measured against the curve
    WITH the leash already applied, so it is what the leash leaves behind.
  * THE CURRENT LEASH OVERSHOOTS AT BOTH ENDS, and it survives out of
    sample. On the holdout, boundary residual by offset bucket: no entry
    **+0.0291** (z +4.4), offset < -0.5 +0.0069, < -0.15 +0.0031, < 0.15
    +0.0013, < 0.5 **-0.0356** (z -3.3). The gap between the two ends is
    ~3.7 se. Negative offset means a longer leash, so the model both
    under-pulls the arms it thinks go long AND over-pulls the arms it
    thinks come out early: the table spreads pitchers too far apart.
  * THE MISSING-GROUP RULE HAS A PRICE HERE. Arms with no leash entry are
    under-pulled by +0.0291 on the holdout — call-ups get the league
    curve and are managed on a much shorter leash than it.

NOT ESTABLISHED, and the item is these three:

  1. **THE FORM.** `leash.py` fits an OUTS residual and converts it; this
     is a DECISION-rate residual and can be fitted directly in log-odds,
     which is the quantity the hook consumes. That is "fit the quantity
     that settles, not the upstream proxy" applied to a term that
     currently does the opposite. Whether the direct fit beats the
     converted one is untested.
  2. **THE SHRINKAGE.** The -0.399 says the current constant is too
     permissive. Re-measure within/between variance on DECISIONS the way
     `stabilise.py` does it rather than reusing the outs-side constant.
  3. **THAT IT HELPS THE OUTS DISTRIBUTION AT ALL.** 7e is the precedent:
     a real decision-level gap, built, and dead on the outs falsifier in
     all four folds.

THE BUILD: one per-pitcher log-odds offset per curve — BOUNDARY and MID
fitted SEPARATELY, because they are different decisions (rule 9) and their
reliabilities differ by a factor of 1.4. Rows filter to `date < HOLDOUT`
before fitting. It rides the existing `team_offset` road through
`sim.for_start`, so there stays ONE road into the hook.

THE FALSIFIER, PRE-REGISTERED, AND READ THE CAVEAT FIRST: `leash.py`
already records that a per-arm term is **FLAT on outs CRPS and the run
ladder BY DESIGN** — it buys discrimination BETWEEN starts, not a
better-shaped average start. So the ladder and `outs_mean` are NOT the
rows, and reporting a flat ladder as "the battery is blind to it" without
saying so in advance is the exact move the "nothing moved" rule forbids.
NAME THE ROW BEFORE RUNNING: the per-start outs CORRELATION (the number
`leash.py` moved +0.105 -> +0.226 out of sample) and `boundary_share_by_
decision`. If neither can see it, build the row rather than claiming it
moved.

SEQUENCING, and the code already enforces half of it: `hook_leash.json`
carries a `hook_hash` and `sim.leash` REFUSES a table built against a
different hook — it went stale five times before that guard existed. Item
33 changes the hook, so a per-arm table built first must be rebuilt after.
Either take 33 first, or budget the rebuild.

**33. THE HAZARD TABLES ARE SOLVED OVER FOUR POOLED SEASONS AND THE LEAGUE
HAS MOVED OUT FROM UNDER THEM — opened 2026-09-11, same screen as 32.**

ESTABLISHED. At a FIXED state the model matches 2023 and misses 2026 badly,
monotone across seasons, on BOTH curves independently (boundary residual,
real minus model):

    inning      2023      2024      2025      2026
      4      -0.0200   -0.0115   -0.0037   -0.0013
      5      -0.0445   -0.0039   +0.0193   +0.0088
      6      +0.0043   +0.0355   +0.0795   +0.0964
      7      +0.0286   +0.0971   +0.0897   +0.1086

Held tighter still — 75-95 pitches, 6th-inning boundary only — it runs
+0.003 (z +0.2) in 2023 to **+0.114 (z +7.8)** in 2026. The error ROTATED:
the model over-pulls in the 4th/5th at the start of the window and
under-pulls in the 6th/7th at the end of it. Composition is ruled out —
mean pitches, innings and runs at boundary decisions barely move (51.3 ->
50.0 pitches, 15.68 -> 15.60 per inning). Holding pitch count AND times-
through fixed, the residual is still monotone in the INNING, so it is not
workload and not the lineup pass.

CAUSE IS NAMED: `hz_iter.WINDOWS` solves `PITCH_HAZARD_BND`/`MID` over all
four seasons pooled. The `Hook` docstring ALREADY records the same finding
for the parametric fit — "2023-24 is a DIFFERENT REGIME ... pooling all four
seasons fits a manager who existed in no year" — and the counted table
shipped pooled anyway.

**THIS EXPLAINS 7e's FAILURE** and is worth reading before re-opening it:
7e's falsifier broke on 2023, "whose gap was already NEGATIVE — too FEW
long starts." That is the 2023 over-pull above. The sign of the hook error
FLIPS between folds, so no single level or calendar term can pass a
four-fold bar. 7e tested a within-season MONTH axis; this is a
between-season one.

NOT ESTABLISHED: the granularity. PER-YEAR is powered on finished seasons
(every pitch bucket clears the solver's 200-row floor in every season, the
thinnest being 298) but is **unusable live** — a 2026 table can only be
built from pre-holdout 2026 rows (12,274 boundary decisions by July, ~2,000
in April), so the current manager is never measured when he is needed. And
the drift looks like ONE regime change rather than four eras: 2025 and 2026
agree within noise (inning-6 boundary +0.0795 vs +0.0964, ~1.2 se apart)
while 2024 sits ~3 se off 2025. So the candidate to test first is a
TRAILING-TWO-SEASON solve, which also doubles the rows per bucket (~5,250
against ~2,600 in the middle buckets).

TWO THINGS TO SETTLE BEFORE SOLVING ANYTHING:

  * **THE FOUR-FOLD BAR NEEDS REDESIGNING FIRST.** A trailing-window table
    cannot be built for the 2023 fold — there is no 2022 on disk — so
    "improves in all four folds" is not a well-defined bar here. Decide
    what replaces it BEFORE running, not after the numbers come back.
  * **THIS IS ESTABLISHED ON DECISION CALIBRATION, NOT ON OUTS.** Same
    caveat as 32, same precedent in 7e, and 7f says the outs defect is
    WIDTH rather than level. Pre-register the outs falsifier per fold.

THE INSTRUMENT: `scratchpad/hook_resid.py`, `--deep` for the four
follow-ups that disentangle inning from pitch count, times-through and
calendar composition. Six mutation-verified checks in
`tests/test_hook_resid.py`. TWO NULLS IT ALREADY CLOSED, do not re-run
them: day/night is composition (within every month, day and night agree),
and days rest is flat.

**34. WHAT TELLS TWO STARTS APART, GIVEN THAT IT IS NOT A PER-ARM CONSTANT —
opened 2026-09-11 by item 32's null, and it is the successor to it.**

ESTABLISHED, and the first two bound the item:

  * `shape.outs_corr` is **3.7 to 5.0 sigma short of the per-arm ceiling in
    all four folds** (0.4164/0.5291, 0.3679/0.4719, 0.2559/0.3413,
    0.3814/0.4995). The model tells starts apart materially worse than a
    predictor that knew only the pitcher would.
  * **A PER-ARM CONSTANT CAN CLOSE AT MOST A SIXTH OF IT AND THE LEASH
    ALREADY HAS ~57% OF THAT SIXTH.** The per-arm outs residual carries year
    over year at r +0.225 only, so a perfect per-arm term is worth +0.023
    against a gap of +0.135. So the other five sixths is something that
    varies WITHIN a pitcher, start to start — or is a state-distribution
    error rather than a hook error at all.
  * the ceiling is LOOSE for exactly that reason (computed within the fold,
    so it counts in-season variation no prior evidence can know). Do not
    price the gap; the reachable number is the one to pre-register.

NOT ESTABLISHED: everything else. THE CANDIDATES, and the first is the only
one with a measurement behind it:

  1. **PITCH EFFICIENCY.** His own pitches per batter correlates **+0.137**
     (n 119, se 0.093) with the per-arm outs residual — weak, but the right
     sign and LARGER than the decision-fitted offsets managed. A man at 3.5
     pitches per batter reaches 100 two innings after one at 4.5, and this
     is a channel the hook reads only through `for_pitcher`'s
     `pitch_center`. Cheap to screen further, and note it is NOT a per-arm
     hook offset — it changes the STATE he arrives in, which is where item
     32 says the error lives.
  2. **THE STATE DISTRIBUTION ITSELF.** Item 32's finding was that a
     residual measured at REAL states does not transfer to a simulation
     reaching other ones. The direct version: for the same start, compare
     the engine's pitch-count-by-inning path against the real one. If the
     engine arrives at the sixth with the wrong pitch count, no hook
     correction can fix the decision.
  3. IN-SEASON FORM, which `form.py` is PARKED on. The carry result gives
     it a proper frame for the first time: r +0.225 between seasons means
     most per-arm variation is NOT stable, and "he does not have it
     tonight" is one name for the rest.
  4. Opponent and park, which vary start to start and are already modelled
     — check they are not DOUBLE-counted here before adding anything.

THE FALSIFIER FOR ANY OF THEM: `shape.outs_corr`, four folds, with the
reachable gain stated in advance rather than the printed gap. And the
instrument for a quick read before committing a battery run is
`scratchpad/arm_score.py` (one fold, paired bootstrap on the delta,
`--control-leash` for the positive control).

---

## Shipped 2026-09-10 — item 24, the home run channel reads contact type

**24. SHIPPED (`sim.USE_AIR_HR`): the pitcher's air-ball share into the home
run channel.** His HR outcome shrinks with k = 944 balls in play and his
contact type with k = 176, so the engine was correctly discarding nearly all
of his personal home run signal and had no way to keep the reliable part.
Counted as observed-over-EXPECTED (this channel already has a per-player
rate, unlike the DP and hit-mix tables) on 263,227 pre-July balls in play at
the batter-pitcher pair level: 0.8493 / 0.9719 / 0.9871 / 1.0430 / 1.0939,
era gate +0.816, within-venue control unmoved, and the BATTER side counted
as a null exactly as its own reliability predicted (era gate +0.136) and NOT
shipped. New `hrshape` battery section; on its own cells mean |z| goes
1.48 -> 0.92 across twenty fold-quintiles, with 2023 q1 the one cell that
got worse. Pre-registered level falsifier FIRED and was diagnosed rather
than patched — the table needed centring on the population it fires in, not
the one it was counted on (+1.11%, `scratchpad/air_centre.py`). Full write-up
in the notes, 2026-09-10 second entry.

## Parked — measured, decided against. Re-open only if the APPROACH or the DATA changes, and say which.

**A NEWS FEED FOR THE CLOSER — the ceiling is 1.1 points and the data gets
0.8 of it offline.** Raised by the operator 2026-09-09 in its strongest
form: if the closer is hurt or traded the news knows immediately and the
data does not. Measured and positive-controlled (`scratchpad/closer_slot.py`).
A forward-looking ORACLE — the same usage count over the club's NEXT 25
games, which bounds anything a headline can know — scores 63.8% against the
backward count's 62.7%. In the transitions where the two disagree (35% of
slots) the oracle gets 33.4% against 30.1%, because A TRANSITION IS A
COMMITTEE rather than an information gap. The sharp-break case is real (the
named man idle ten days takes the slot 3.7% of the time) and a ten-day
stale gate recovers +0.8 offline. **RE-OPEN ONLY VIA THE STATSAPI
TRANSACTIONS/ROSTER FEED**, which is structured, dated and BACKFILLABLE. A
scraped headline exists only going forward and can therefore never be
cross-validated across four folds — it would be the one input in the engine
that cannot be measured (rule 12b).

**RELIEVER FATIGUE AS A RATE EFFECT — null, powered, controlled.** See item
8 for the numbers. The availability half is alive and lives in item 21; it
is the rate half that is closed.

**THE DEPTH CAP ON THE RELIEF HOOK IS NOT A DEFECT.** `RELIEF_MID_REMOVAL`
caps its batter axis at `min(batters // 3, 3)`, so everyone past nine
batters sits in one flat 7.0% cell, and the obvious guess is that the real
hazard FALLS past the cap — a man still out there in his fifth inning is
the designated long man. It does not: pooled over 9,254 games it runs 8.5 /
9.1 / 8.2 / 13.7 and RISES at the end (`scratchpad/mid_intent.py`).
**AND THE WAY THIS ALMOST SHIPPED IS THE POINT: a 600-game smoke test showed
the hazard falling to 3.0% and it was sampling noise.** Do not act on a
partial play-by-play walk; the full one is six minutes and is cached.

STILL CLOSED after item 23's recount, and worth saying because the recount
touched every cell of this table: the finding is that the hazard does not
FALL past the cap, and on the corrected key it rises harder, not less
(`MID_INTENT_DEPTH` bucket 2 runs 0.0009 / 0.0864 / 0.1362 / 0.0955 and the
early-entry bucket climbs to 0.1342 at the deepest cell). The cap is still
not the defect. The 8.5 / 9.1 / 8.2 / 13.7 figures above are the STALE-KEY
pooling and should not be quoted against the current table.

**A BULK-ARM CELL ON THE RELIEF HOOK — redundant, not wrong.** Keyed on
"first reliever behind a short start" the hazard reads 0.3 / 3.6 / 3.5 /
4.8 / 8.4 / 7.2 / 15.4, within noise of the intent-bucket-0 row that
shipped. The general mechanism covers the specific population, so the
opener needs no special case here. Re-open only if intent bucket 0 is ever
re-cut in a way that stops containing him.

**Runner-event reorder — real defect, no measurable gain.** An at-bat
resolves against a state one event stale: at-bat N sees at-bat N-1's
steals, not its own. Reordering fixes that and buys nothing, because the
staleness shifts uniformly and the same at-bats meet the same distribution
of states — measured +0.037 PA/game against a predicted -0.18, runs noise.
The at-bat reality VOIDS is the one in progress during the steal, which a
plate-appearance-granular model does not have at all; that part needs
pitch-level simulation. `game.USE_RUNNERS_FIRST`, off, switchable.

**Per-hitter hit mix.** True spread 13.4% of the level, reliability +0.209,
~0.010 runs a game per hitter and ~0.030 across a lineup by quadrature. Home
run rate predicts a hitter's extra-base share (+0.196) BETTER than his own
doubles rate does (+0.115), so if revisited, impute it from power. Plumbing
exists — `hit_mix` is a field on `Matchup`, not a global.

**Mid-plate-appearance removals.** 13 of 2,848 pitching changes, 0.456%. The
model rolls removal between plate appearances and is right 99.5% of the time.
Recorded so it is not asked a third time.

**Fatigue vs familiarity in the TTO decay.** Cannot be separated — pitch
count is CAUSED by the outcome being measured, so every stratification
selects on strikeouts. Two designs tried, both contaminated; the second
looked like a clean fatigue result (z +4.12) and is mean reversion. The
pooled within-start decay is -14.9% and that is the quotable number.
NOT FULLY ACADEMIC: if it is fatigue, an efficient starter should decay less
than a labouring one and the model charges them identically — a candidate
for the missing K spread (sd 2.23 against 2.49).

**Score-dependence of the plate appearance.** K% 19.79 with a 4+ lead against
23.19 tied, but that is almost certainly WHO IS PITCHING — mop-up arms in
blowouts. Confounded by reliever quality; do not build on it without
controlling for the arm.

**Pitch-level expectation (`PLAN-pitch-expectation.md`) — CLOSED WITH A NULL
2026-09-07.** The granular re-open of arsenal. The expectation surface got
built and validated (E0 384 cells on 2.9M pitches; E1 batter offsets,
shrinkage at K=84 swings) and the per-start quantities are REAL within a
night, but NOTHING predicts the next start — all four candidates dead at the
pre-registered bar. Do not re-run the screens. Leftovers:
`scratchpad/pitch_e0.py`, `pitch_e1.py`. The one untested branch is the
batter-side log5 matchup adjustment, and after five dead arsenal
constructions its prior is low. RELIABLE IS NOT PREDICTIVE.

---

# CLOSED — what it was and when. Do not re-run; full write-ups in `NOTES-context-layer.md`.

**8c. SCORED AND PARKED 2026-09-09. `USE_MEASURED_PRIOR_PA` stays OFF, and
the reason is not the score.** Dead flat on paired F5 CRPS (-0.00004 +/-
0.00457, an instrument that cannot resolve under ~0.009) and no battery row
moved by more than one se — BOTH GATES PASS AND NEITHER IS EVIDENCE. What
condemned it: it fires on 183 of 197 starters (4.4% per-pitcher `k_pct`
move, so the flat score is a real reading and not dilution), it narrows
between-pitcher K spread 8.2%, and `k_sd`/`k_9_plus_share` move AWAY from
actual in ALL THREE informative folds at ~0.62 se — against a 9+ tail
already at z -2.3. The direction was predicted from the spread diagnostic
BEFORE the battery ran. CAUSE: raising the prior's weight 173 -> 250 raises
the pooled denominator, taking weight off his CURRENT season, so the counted
`m` trades current-season signal for prior signal — better at predicting the
rest of his own season (what it was fitted on), worse at telling two
pitchers apart (what the sim needs). **A QUANTITY CAN BE CORRECTLY MEASURED
AGAINST THE WRONG TARGET.** `PRIOR_EFFECTIVE_PA` is NOT retracted; wiring it
to the shrink is. AND NOTE THE SCOPE THIS ITEM NEVER HAD: item 12's ~0.044
runs is home-runs-sized, and `hr_pct` (3.1x correction) and `babip` (19.5x)
both fail the sample test and do not ship — 8c was the small half of item 12
by construction. Do NOT re-run this, and do NOT re-run `USE_RAW_PRIOR`.

**1. WITHDRAWN 2026-08-30 — the model reaches extras at about the right
rate**, 0.078 against a real 0.083 (se 0.006). The "5.4% against 8.3%" that
made this item 1 was `simulate_game` skipping the track block on a walk-off,
now fixed. Its one-run-game survivor (0.247 against 0.266) was an old-engine
number and is refuted by item 19 — the margin is too NARROW.

**7. SHIPPED 2026-08-31 — the counted MID pitch hazard.**
`sim.USE_PITCH_HAZARD = True`, `USE_PITCH_HAZARD_BND = False`: counted MID
backbone, parametric BOUNDARY. Re-run 2026-09-09 on the current engine with
live bullpens in all four folds — the 12.5-17.5 outs band improves -0.0142 /
-0.0155 / -0.0141 / -0.0148, long lines flat, mean outs moves +0.08 toward
real in every fold without crossing. Runs unmoved across the prefix ladder.
It closes the fourth-inning over-pull, because 60-85 pitches IS the fourth
inning and those were one defect, not two. TAKING BOTH CURVES WAS SCORED AND
LOST (nearly doubled the long-line error, 0.2-out shortfall -> 0.18-out
overshoot in every season) — half the change beat all of it. The
remainder was 7a, which SHIPPED on 2026-09-09.

**7b. CLOSED — the K tail work is done, do not re-run.** Dominance shipped
(`late_mid_per_k_rate`), the per-start strikeout draw counted and shipped
(`START_K_SIGMA` 0.1625, refuting a tuned 0.20), and `PITCH_COST` closed —
its premise was arithmetically wrong, since a dominant night also needs
fewer batters and everyone needs ~99 pitches for six innings. o8.5 is now
-2.3 sigma, from -3.5.

**7c. CLOSED — a direct prop model is tested and dead.** The learned removal
model beats `sim.Hook` on decision AUC 0.912 to 0.876 and gives a boundary
share of 0.341 against a real 0.672. Do not rebuild props as a separate
model.

**7d. REFUTED on cross-validation; re-confirmed 2026-09-09 with live
bullpens. `sim.USE_PITCH_X_INNING` is False and stays there.** `PXI_BND` /
`PXI_MID` are solved conditional on the other shipped terms and do not
transfer — boundary still WORSE in 2023, flat in 2024, better in 2025-26,
and the signed mid offset trends monotonically by season rather than being
the constant one fold suggested. The RAW phenomenon is real (70 pitches in
the third is pulled 6.01% against 1.62% in the fifth) but the table is not
portable, and the counted MID hazard closes the fourth inning anyway. TWO
CAVEATS FOR ANYONE TEMPTED TO REFIT: the old "mid worse in 3 of 4" line is
engine drift and must not be quoted against the current engine (item 20);
and PITCHES PER INNING is older, deader ground — it folds back on itself
(high early pitches-per-inning means FEW total pitches), measuring
non-monotone 1.68% / 4.77% / 3.14% against a monotone 75x span for raw
pitch count. Rejected day seven, re-derived day twenty.

**11. LARGELY CLOSED 2026-09-09 — the first inning is no longer the largest
per-inning defect and the old headline is retracted.** Re-measured on the
battery's four folds: the gap is -0.036 runs / -3.5% / z -1.5, not the -12% /
z -2.5 this item carried all week (that came from one 926-game cut against
the 2026-08-30 engine). Sign stable 4/4. The pitch-hazard, sharpness and
opener work shipped since closed most of it. **INNING 6 IS NOW THE LARGEST,
at -0.056 runs / -5.3% / z -2.2, also sign-stable 4/4** — that is the
replacement item if a per-inning row is chased.

TWO THINGS WORTH KEEPING FOR ANY FUTURE INNING-1 WORK. First,
`scratchpad/inn1.py` counted on 306,506 pre-holdout starter plate
appearances that real starters strike out ~6.6% MORE in inning 1 (z +5.7,
4/4 seasons) and NOTHING else moves (bb, hr, babip all null). More
strikeouts is FEWER runs, so wiring that counted table makes the first
inning score LESS — where we are already short — and pushes K out of inning
2, where we are already long. Pre-registered: it moves both rows the wrong
way. So the residual is not a missing inning-1 rate effect; clustering /
advancement remains the better explanation. Second, THE COLLIDER: how many
batters bat in inning 1 IS AN OUTCOME of inning 1, so a within-game-side
permutation is NOT a valid null — it read z +14 on BABIP with nothing
injected. Shuffle labels globally (`scratchpad/inn1_dbg3.py` is the
discriminator). Field state was separately ruled out as the cause of the TTO
decay (`tto_state_overlap.py`, positive-controlled).

**15-exit. SHIPPED 2026-09-09 — the opener's exit.** `USE_RELIEF_INTENT`
(the follower of an early exit continues like the bulk arm he is) and
`USE_OPENER_EXIT` (a flagged short-yardage starter — avg < 11 outs, the same
`slate.priceable` cell — exits on a bootstrap from his own outs record via
`forced_exit_outs`), plus `USE_OPENER_POOL` for arms with no record.
Measured: flagged arms' outs error +3.40 (6.7 sigma, sd far too narrow) ->
-1.20 (2.4 sigma, sd exact); affected-game totals move toward actuals (9.01
-> 8.95 against a real 8.49); the intent falsifier's recorded 4/4-fold
failure dissolves to 0.2 sigma on truthful states. The leash never could
reach these arms (`OFFSET_CLAMP` ~+/-3.3 outs against a needed ~-12). The
rest of item 15 is still open above.

**20. CLOSED 2026-09-09 — every cross-fold result re-run with live bullpens,
no verdict changed.** Rule 12b's bar is 0.0399-0.0577 against a recorded
0.0401-0.0590 and CLAUDE.md carries the new figure; item 7 replicates four
folds for four; 7d's refutation replicates; `USE_PEN_ROLES` re-run with live
pens still moves no battery row past one se. ONE AMENDMENT, recorded on 7d:
its MID half no longer loses in three folds of four, and that is engine
drift, not the bullpen. NOT worth re-running: the run-LEVEL 2023-2025
columns of any battery before `55b73d1d3ed5` — wrong at the level and
superseded. `scratchpad/pen_ab.py` reproduces the bug on demand and stays as
the positive control for the next harness that comes back identical to four
decimals across folds.

**ZONE->BB. SHIPPED 2026-09-07** as `sim.USE_ZONE_BB` (-0.1431 per share of
zone, 4.9 sigma train-only, survives the box-score walk drift) — the one
live channel out of `PLAN-pitch-history.md`'s league-wide screen.

## Shipped 2026-08-29/30 (days seventeen and eighteen) — the hook

All counted on real removal DECISIONS, never on runs, and all refit-verified
on training rows only.

  * `mid_per_abs_margin` -0.0824 — the BLOWOUT term, unsigned. The signed
    form measures zero on both curves, so the specified parameter was the
    wrong shape and would have closed the question as a null.
  * `late_mid_per_k_rate` -1.5130 — DOMINANCE. Until this, every input to
    both hook curves was traffic or workload.
  * `START_K_SIGMA` 0.1625 — per-start strikeout variation, COUNTED, and it
    refuted a tuned 0.20 by 4.2 sd. The clearest case in the project's
    history of a count correcting a fit.
  * `per_pen_back2` / `per_pen_rest` on BOTH curves — bullpen availability,
    the first external signal the boundary decision ever accepted. About WHO
    CANNOT GO, not pitches thrown. Needs no deployment model.
  * `high_pitch_*` — a third branch above 90 pitches. Fixed o18.5/o20.5 and
    made the middle band worse, which is what motivated item 7.
  * The HOLDOUT RULE in CLAUDE.md, with `train_only()` in the fitters.

## Shipped 2026-08-29 — the correctness and constants batch

  * **The home/road constants, recounted, and walks got their own** (was
    11d). `HOME_OPP_K` 1.034 -> 1.026, `HOME_OPP_CONTACT` 0.981 -> 0.990,
    both overstated by 3.5-4.1 sigma on 679,329 plate appearances. THE REAL
    FINDING WAS THE FOURTH CHANNEL: walks rode the contact constant at
    0.9804 where their own count is 0.9493 (z -6.6) — new `HOME_OPP_BB`
    0.974. Counted on UNINTENTIONAL walks alone to match the code path; HBP
    has no home/away split. Real home-field advantage counted on this league
    is 0.306 runs (se 0.044), twice an outside guess; we now produce 0.263
    (see 11d-residual).
  * **The half-innings were reversed and the walk-off fired on the first
    run** (was 11b). Two correctness bugs in `simulate_game`: the side named
    `away` is a PITCHING side, so calling it first batted the home club in
    the top of every inning; and `home.opposing_runs = home.runs` truncated
    every ninth and extra inning at the first run. Innings 9+ z -2.9 -> +0.3.
    INNINGS 1-8 CANNOT MOVE — both rules key on `regulation` — so no F5
    number, ladder or CRPS in this project's history is affected. Two
    regression checks, each verified by mutation.
  * **Hit-by-pitch by field state** (was 4). `STATE_MULT` gained an
    `hbp_pct` column and `pa_from` moves `hbp` with its renormaliser. Keeps
    only 36% of its raw spread after shrinkage. FOLLOW-UP TAKEN: the
    four-season rescan at the top of this file is the sharper input it
    needed.
  * **Rank by gap over simulation error** (was 15-old). Sorting on
    `z = gap / se` — the estimate is least reliable where the gap is
    largest, so a tail gap and a central gap were never the same evidence.
  * **Walks have an `odds_mult` slot** (was 3). `Matchup.m_bb`,
    `NEUTRAL_PARK["bb"]`, `park_mults` now reads Savant's walk index, which
    had always been fetched and discarded — so every park test ever run here
    excluded walks by construction. Inert, fingerprint unchanged.
  * **`_track` fires on every exit path in `simulate_game`.** The prefix
    block sat after the walk-off `break`, so `prefix[9]` was missing for
    ~40% of games and the notes carried a standing "take 9+ as the residual"
    warning. Verified inert on outcomes.
