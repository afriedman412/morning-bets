# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## THE OBJECTIVE — read this before anything else

**`AF_PLAN.md` is the authority on what this project is for. Read it. It is
47 lines.**

Simulate baseball games as accurately as possible, **measured against what
actually happened**, and infer everything else — props, totals, game script
— from that simulation.

**CLV IS NOT THE OBJECTIVE.** Closing-line value, cents-our-way,
blend-against-the-open and "beating the market" must never be used to decide
whether a mechanism helped. Measured 2026-08-24: our RESOLUTION — real
discrimination on outcomes, from the Brier decomposition — is LOWER than the
OPENING price's in July (0.0728 vs 0.0787) and August (0.0833 vs 0.0856),
while we still "beat the open" on CLV. So the CLV edge is market
ANTICIPATION, not baseball knowledge, and it can rise while the model gets
worse at predicting games. It is also fragile: it depends on Kalshi's
behaviour, not on baseball.

Judge every change on ACTUAL OUTCOMES: the prefix ladder (`ladder.py`,
F1/F3/F5/F7 against real runs), discrete CRPS and coverage for the
distribution shape, and resolution against what happened.

**Use the market only as a yardstick for how much is achievable.** We sit at
91-98% of Kalshi's resolution and are BETTER CALIBRATED than it (August
reliability 0.0005 against 0.0014), so the entire remaining prize is about
2.5 Brier points. `versus_market`, `f5_market`, `team_market`,
`total_market`, `price`, `quote` and the `scratchpad/clv_*` drivers are the
BETTING LAYER, not the modelling loop.

A corollary that causes as much drift as the above: **a MEASURED quantity
replacing an imported guess does not have to prove itself on the score.** A
flat result means the test could not resolve ~0.02 runs, not that the
mechanism failed. Applying a fitting standard — "prove it improves the
loss" — to measurement work makes every correct change read as a null.

## Read this next — two systems, one repo

**The original pipeline** turns YouTube capper videos into graded bets and
then asks three LLM personas to build a card. It still runs on a schedule
and is described under "Architecture (original pipeline)" below.

**The context layer** (`src/context/`) is where the work is now, and it
represents a change in what this project is trying to do. The old approach
asked an LLM to reason over a 52k-character blob and predict outcomes. That
was measured and it does not work: an estimator built the same way the
market is built scores AUC 0.537 against actual results, which is nothing.
The market price *is* the consensus construction, so reproducing it well
buys nothing.

What replaced it is a plate-appearance SIMULATOR (`sim.py`) that prices a
start from the pitcher's rates, the specific nine he faces and a fitted
removal hook. It is calibrated to within 2% on every per-start rate.

The generalisation that came out of two days of measurement, and the single
most useful line in these docs: **fit the quantity that settles, not the
upstream proxy.** The quantity you tune against decides what you get:
`calibrate.loss()` targets the outs distribution rather than runs, and outs
is exactly where the model has never earned anything. `fitf5` targets F5
runs allowed by one side, scored across the FULL SUPPORT of the run
distribution — which is the discrete CRPS — because scoring across a book's
liquid lines instead would tune the model to the shape of somebody's board.

Two things that are 0-for-everything and one that is not: every feature
IMPORTED as known baseball has measured zero (handedness, park, day/night,
bullpen availability, arsenal), while every constant MEASURED on this league
has turned out to be wrong in the shipped version — advancement, the double
play rate, inherited runners, and the four shrinkage constants. Count it,
do not import it.

**The historical CLV record has moved to `NOTES-context-layer.md`.** It was
at the top of this file and it primed every session to treat market
agreement as the objective. See THE OBJECTIVE above.

The two systems are only loosely joined. **Snapshots are NOT wired into the
personas**, so `make panel` / `make recommend` still use the old blob.

**WHAT THIS MODELS, settled 2026-08-23: F5 TEAM TOTALS, and to a lesser
extent full team totals. Props are NOT the target** — they are expected to
follow from a game simulation that is actually right. Two rules follow, and
both are enforced in `fitf5.py`: do not score against the lines a book
offers (score the full support of the run distribution, where the same
arithmetic is the discrete CRPS), and do not fit the hook AGAINST THE
SETTLEMENT VALUE. Fitting it to real removal DECISIONS is a different thing
and is what `removal.py` does — the loss there is on what managers did, not
on the quantity we price.

**START WITH `RESUME.md`** — where the edge is, what to do next, and the
long list of things already measured and dead so nobody re-runs them.

**Before touching the context layer, read `NOTES-context-layer.md`.** The
current state is at the END — it is appended chronologically, so read
backwards from the last section. It carries the measured negatives, which
are the expensive thing to rediscover.

**WHERE THE MODEL IS ACTUALLY WRONG, measured 2026-08-27 and the most
useful line in these docs for choosing what to work on: THE EVENT RATES ARE
RIGHT AND THE ADVANCEMENT IS NOT.** Through five innings the model puts
exactly the right men on base (+0.0%) with strikeouts, walks, hits and home
runs each inside 1.4%, and brings 1.7% fewer of them home. So no further
measurement of a RATE can close the gap. `scratchpad/f5_decomp.py`.

And it is SHAPE, not advancement rates: reality has more shutouts AND more
blowups while the model bunches in the middle, which is clustering — plate
appearances resolve independently and real ones arrive together. Runs are
convex in clustering, so the thin tail also drags the mean. One defect, both
symptoms, confirmed by a flat dispersion term that closed 44% of the shape
error and 86% of the level gap with one number.

That term is NOT shipped: it is neutral on CRPS because a flat spread added
to everyone improves calibration and not discrimination. And the obvious way
to make it vary is CLOSED — per-pitcher and per-club dispersion do not repeat
(split-half reliability 0.07 over 107 arms, powered to see 0.32).

**LEVEL ERRORS ADD; SPREAD EFFECTS COMBINE IN QUADRATURE.** Both kinds were
being discarded against one leverage floor. Five 0.03-run SPREADS make 0.067,
so the pile of sub-floor per-player features is dead collectively as well as
individually — two 1.5-cent features make 2.3 cents and it takes SIX to reach
the bar. But every win on 2026-08-27 was a LEVEL error pointing one way
(hit-by-pitch, sacrifices and wild pitches all measured on STARTERS and
applied to every arm), and the wild-pitch one closed a fifth of the run gap
alone. Hunt level errors and structural gaps; stop screening refinements.

**WHEN EVERY CHANNEL IS WRONG BY THE SAME PERCENTAGE, STOP LOOKING AT THE
RATES AND CHECK WHAT YOU DIVIDED BY.** No set of rate bugs moves strikeouts,
walks, hits and home runs by the same 8% — that is a denominator. Three
denominator mistakes in one script on 2026-08-27, each producing a confident
wrong table: `Side.line` is the STARTER'S and reliever lines are DISCARDED on
each arm change, so it cannot be compared against every first-five plate
appearance. Related: a MONTE CARLO MEAN carries its own noise, and noise in a
regression PREDICTOR attenuates a slope — 55% of `m_er`'s variance is
simulation at 40 draws, which flips the sign of a spread-calibration result.
The same noise is only ~2% of the RESIDUAL's variance, so residual screens are
unaffected. Ask which denominator the question is about.

**A NULL IS A CLAIM AND MUST BE TESTED LIKE ONE.** The standing failure
mode here is asymmetric: a positive result gets an adversarial test
immediately, a negative one gets accepted and the session moves to the next
candidate. That is a biased filter — apply skepticism only to findings and
the conclusion is "nothing works" whatever the truth. On 2026-08-27 five
handedness nulls were accepted in a row while three positives were each
attacked within minutes; the mechanism turned out to be MIS-SPECIFIED, and
the error was found only after the user pushed back twice.

So: **positive-control every screen** — inject a known effect at the claimed
size and confirm the harness sees it, because a mis-specified mechanism and
an absent effect produce identical output. Before accepting a null, state
the specification and what would falsify it. And a null should sometimes
mean "strengthen the mechanism", not "next candidate".

**The single most useful diagnostic in this project, now four for four: a
fitted parameter sitting at the EDGE of its grid is a missing mechanism, not
a tuning problem.** It found the absent hit-by-pitch, absent fielding
errors, and out-dependent runner advancement (twice). Treat a grid-edge
result as a mechanism hypothesis immediately, not after three sweeps.

**A HOOK CURVE IS FITTED ON THE POPULATION IT FIRES IN, AND POOLING IS
THE DEFAULT MISTAKE.** The removal model is two curves — BOUNDARY (does he
come back out) and MID-INNING (pull him now) — and each has its own rows.
Fitting them pooled is wrong and it is what every convenient tool invites:
day seven found the pooled fit gave a late curve at 7.24% where reality is
33.80%, and on 2026-08-26 the same mistake was re-made THREE TIMES in one
session, twice inside the mid-inning curve's own low-pitch rows (32,497 of
47,716 sit under 60 pitches and swamp it).

BUT THE RULE HAS A LIMIT, measured the same day: restrict the BOUNDARY
curve's training rows the same way and the simulation gets WORSE (mean outs
16.49 -> 16.74). The boundary curve is evaluated at EVERY pitch count and
the mid-inning curve is not, so calibrating boundary on late rows only makes
it under-pull early, more starters reach the tail, and the level breaks. Fit
on the restricted population only when the curve fires only there and
something else covers the rest.

**And prefer a high-n ratio to a low-n aggregate.** Runs per baserunner
(~17,500 simulated starts) told the truth every time; the mean F5 total over
a few hundred games told me whatever the subsample felt like — four
"improvements" in a row that were all inside one standard error. Compare
totals PAIRED and on every game.

## Commands

Run everything through the Makefile's Python virtualenv (`venv/bin/python`).

- `make run` — daily ingest: pull today's YouTube videos, summarize, extract structured bets, persist to DB.
- `make ingest URL=<youtube_url>` — manually ingest one or more videos into today's bets (multiple URLs: quote the list).
- `make grade` — grade yesterday's bets. Override with `make grade DATE=YYYY-MM-DD`.
- `make panel` — run the 3-persona panel for today. Override date with `make panel DATE=YYYY-MM-DD`. Re-running the same day is idempotent (prior panel rows are cleared).
- `venv/bin/python -m src.panel reset [YYYY-MM-DD]` — delete panel bets for a date without re-running.
- `make web` — start the local Flask viewer at http://127.0.0.1:5050.
- `make publish` — build static site into `site/`, git add + commit + push. Netlify serves from `site/` on push.
- `make install` — first-time setup: create `venv/` and install `requirements.txt`.

### Play-by-play, and what it unlocked (added 2026-08-24)

- `venv/bin/python -m src.context.sources.pbp --backfill --sync` — WHOLE
  games, 2,006 of them, 205 MB gzipped, ~2 min over 8 workers. Fetched
  whole and stored whole: extracting a subset to save disk is a false
  economy, the API call is identical either way. `plays()` reconstructs
  base-out-score state BEFORE every play; `stints()` gives one row per
  pitcher per game with the state he walked into.
- `... -m src.context.advance` — advancement rates COUNTED on this league.
  `--by-team` runs the per-club stability gate (it fails; league number
  stays). This found that the published tables were wrong in both
  directions and cancelling.
- `... -m src.context.deploy` — how bullpens are actually used. Role is
  stable and projects (split-half r +0.55 to +0.78 over 319 relievers), so
  role-based deployment is worth building.
- `... -m src.context.relief` — relief-outing length, counted on 13,248
  outings. The continuation hazard is conditioned on the state he ENTERED
  in (20.1% / 44.8% / 62.7% by entry outs), and a per-PA removal hazard
  covers the 58.2% of mid-inning handovers that are reliever-to-reliever.
- `... -m src.context.inherit` — what inherited runners do, followed by
  runner ID across 5,507 handovers. Pooled 0.312 against the shipped flat
  0.330; the cells run 0.127 to 0.771.
- `... -m src.context.removal` — extract every starter removal decision from
  play-by-play and print the marginals. AUC 0.912 against sim.Hook's 0.876,
  and **switched OFF since day seven** — it was validated on removal-decision
  AUC while discarding a fitted boundary share, and the premise written into
  `game.USE_LEARNED_HOOK` (that one roll per plate appearance spans the
  inning boundary) is false.
- `... -m src.context.boundary` — a mid-inning hook and a boundary hook are
  DIFFERENT DECISIONS, counted. 63.2% / 36.8%, and pitch count does not
  distinguish them at all (83.3 against 82.6). Each branch is now fitted on
  its own population; pooling them made the late curve far too flat.
- `... -m src.context.leash --build [--before DATE]` — the PER-PITCHER
  LEASH, measured. A pitcher's leave-one-out residual is +0.295 on OUTS and
  noise on k/h/bb/er, so what is wrong is how long he is left in, not how
  he pitches. Out of sample it takes the outs correlation +0.105 -> +0.226,
  and it is FLAT on outs CRPS and on the run ladder by design — it buys
  discrimination between starts, not a better-shaped start. Club patience
  stays off; that is the sixth finding against it.
- `... -m src.context.tto` — times through the order. K% falls 19% from the
  first pass to the third. `--` no args runs all 2,006 games.
- `... -m src.context.stabilise` — the four shrinkage constants, measured.
  Batter rates were over-shrunk 2.2x, pitcher HR under-shrunk 2.7x.
- `venv/bin/python -m scratchpad.leverage` — SCREEN A MECHANISM BEFORE
  BUILDING IT. Swings each parameter across its reliability-adjusted club
  spread and reports the runs of separation it could buy. Under ~0.05 runs
  it cannot matter however real it is.
- `... -m src.context.store` — creates `context.db` and reports whether the
  pipeline DB is correctly read-only.

### Full-game simulation and the season backfill (added 2026-08-23/24)

- `venv/bin/python -m src.context.game` — a WHOLE game: both sides
  interleaved half-inning by half-inning so a live score exists, a bullpen
  SAMPLED from the club's real arms, inherited runners actually played out.
  Before this nothing simulated past the starter's exit, so a full team
  total could not be produced at all.
- `... -m src.context.sources.season --backfill` — pull missing dates to
  opening day, then the starter/pitch-count/venue backfills that depend on
  boxscores being present. The database held half a season and it was the
  binding constraint on nearly every measurement.
- `... -m src.context.sources.pitches --backfill` — REAL pitch counts, plus
  hit-by-pitch and wild pitches, from fields `grading.mlb_boxscore` was
  already downloading and discarding.
- `... -m src.context.total_market` — full-game totals against Kalshi. The
  stated product. HAS NEVER COMPLETED A RUN.
- `... -m src.context.recency` — recency-weighted rates vs the market. Dead
  at 3-5 sigma; kept as the record.
- `... -m src.context.sources.archetype` — unsupervised pitcher typing by
  pitch mix. Real for relievers (p=0.003), absent for starters, too small to
  wire in.

### Context-layer entrypoints (all offline-cacheable, no API key)

- `venv/bin/python -m src.context.contracts [bet_type stat]` — print the evidence spec.
- `venv/bin/python -m src.context.assemble [DATE]` — build a slate's brief, print coverage.
- `venv/bin/python -m src.context.snapshot [DATE]` — assemble + store; `--list` shows history and line movement.
- `venv/bin/python -m src.context.scan [DATE]` — scan every offered line for disagreement. **Flag rule is known-broken; see NOTES.**
- `venv/bin/python -m src.context.movement [DATE]` — is each capper's quoted number still on the board.
- `venv/bin/python -m src.context.gamestate [DATE]` — which games are safe to price.
- `venv/bin/python -m src.context.sources.<name>` — every source module has a demo main.
- `venv/bin/python -m src.context.quote "Name" k under 4.5 +102` — price ONE bet: your book, Kalshi's mid AND ask, the markup in cents, our number as advisory.
- `venv/bin/python -m src.context.price [DATE]` — price the whole slate against Kalshi; declines openers and thin-sample arms out loud.
- `venv/bin/python -m src.context.f5_market [DATE]` — first-five totals against Kalshi, open vs close. `f5.py`, the stub that simulated one side against a single league-average reliever, was DELETED with the rest of the one-sided engine on 2026-08-25.
- `venv/bin/python -m src.context.versus_market` — the same test for K props.
- `venv/bin/python -m src.context.calibrate` — replay real starts, compare the simulated distribution to what happened.
- `... calibrate --reliability k|outs|all` — does a simulated 60% win 60% of the time? Pooled across starts, bucketed by what the model said. The check that matters for pricing.
- `... calibrate --tune` — coordinate descent on the hook against the observed hazard curve.
- `... calibrate --patience` / `--leash` — fit club and pitcher removal offsets as RESIDUALS. Order matters: club first, pitcher against the remainder, or the manager gets counted twice.
- `... calibrate --holdout YYYY-MM-DD` — refit on the training window only, score on unseen starts.
- `venv/bin/python -m src.context.sources.starters --backfill` — ground truth for who started. `grading.py` sets this going forward; the backfill is for history.
- `make test` / `make test ARGS=sim` — 328 offline checks, ~95s. It got
  slower on 2026-08-25 and that is the deletion, not a regression: a check
  that used to walk one pitching side now plays a whole game.
- `venv/bin/python -m scratchpad.mutate` — MUTATION SWEEP. Flips one shipped
  constant at a time and reports which are unguarded. It found five: every
  measurement module was tested and none of the WIRING was. Refuses to run
  on a dirty tree, for a reason recorded in the notes.

Tests ship with the module, not afterwards. `tests/run.py` collects every
`check_*` — no pytest, no network. **Verify a new check by mutation:**
reintroduce the bug it guards and confirm that exact check fails. A test
that guards nothing looks identical to one that guards something.

`make test` runs `tests/run.py`, not pytest — pytest is not installed and is
not a dependency. The `lint` target still references tooling that isn't there.

Runtime deps assume `ANTHROPIC_API_KEY` in `.env`. Optional: `WEBSHARE_USERNAME` + `WEBSHARE_PASSWORD` for a residential proxy on `youtube_transcript_api` (helps when YouTube rate-limits).

The cron schedule lives in `.cron-config` (hourly run 8am-5pm, grading at 9am).

## Architecture (original pipeline)

Four entry-point modules under `src/`, backed by one SQLite DB (`morning_bets.db`) and one artifacts directory (`bets/`).

### The pipeline

```
YouTube channels (yt-dlp)
   ↓ find today's target video per channel
transcript (youtube_transcript_api)
   ↓ Claude summarizes to per-source markdown
   ↓ Claude extracts structured JSON (schema in EXTRACT_PROMPT)
bets table (sqlite)   ← dedup by (player, stat, side, line, matchup, bet_type)
   ↓ fill_missing_lines() fills MLB total/spread lines from ESPN consensus
merge_summaries()     → bets/YYYY_MM_DD.md  (per-game grouping across all sources)

next day:
statsapi.mlb.com / ESPN NBA → cache boxscores in games/mlb_batting/mlb_pitching/nba_player_stats
grade_pending()       → bets.result / bets.actual_value
render_graded_markdown() → bets/YYYY_MM_DD_graded.md

publishing:
web.py Flask app renders DB → templates → build_static() writes site/
```

### Key modules

- **`src/main.py`** — YouTube ingestion. `CHANNELS` dict maps channel_key → `{url, match: title→bool, label, prompt_extra}`. Adding a new source is a dict entry. `find_video()` walks the channel's uploads (or streams) tab; `title_is_about_today()` and `transcript_is_about_today()` are Haiku classifiers that guard against re-uploaded / backdated videos. `summarize()` produces free-text, `extract_structured_bets()` calls Claude again to convert to canonical JSON.
- **`src/grading.py`** — everything about final scores. `mlb_schedule()`/`nba_schedule()` hit statsapi.mlb.com and ESPN; `cache_day()` populates the `games` table and pulls boxscores when status is Final. `grade_prop_bet()` uses `NBA_STAT_FIELDS` / `MLB_BAT_FIELDS` / `MLB_PITCH_FIELDS` maps and supports combo props (`h+r+rbi`, `pts+reb+ast`, etc.). `resolve_canonical_matchup()` is the reason matchups group cleanly in the UI — it normalizes `vs.`/`vs`/`at`/`@` and long team names vs abbreviations to a single canonical `Away Team @ Home Team` string per (sport, date).
- **`src/panel.py`** — the 3-persona panel (`Quant`, `Cynic`, `Careful`). Each persona is a Sonnet call with the built-in `web_search` tool. Panel picks are persisted with `source_label = "Panel: <name>"` so grading uses the exact same code path as capper bets. `PERSONA_INSTRUCTIONS` bakes in the bankroll rules ($5,000 start, $50 unit = max bet, stake menu of $0/$12.50/$25/$50, no -150+ juice). Savant CSVs are cached per calendar day under `.cache/` (date-keyed filenames — no TTL). `bankroll_status()` and `settle_bet()` power the `/panel/` view.
- **`src/web.py`** — Flask app with three routes: `/`, `/<date>/[view]/`, `/panel/`. `build_static()` renders every page to `site/` for Netlify.
- **`src/db.py`** — schema + `init()` migration (idempotent `ALTER TABLE` adds columns for older DBs). One connection helper; every call site uses `with db.connect() as conn:` for auto-commit.

### Data flow contracts worth knowing

- **`source_label`** is the primary axis for provenance. Values like `"Lindy's Leans Likes & Locks"` come from `CHANNELS[key]["label"]`; panel personas use the `"Panel: <name>"` prefix, which the web view uses to distinguish them.
- **`sent.json`** at repo root is a rolling 7-day map of `date → {channel_key: video_id}` and is the *only* thing preventing re-ingest of the same video. Deleting/editing it will cause re-processing.
- **`bets/YYYY_MM_DD.json`** at repo root caches the per-source free-text summaries so `merge_summaries()` can re-run without re-summarizing.
- **Canonical bet dedup key** (in `persist_bets`): `(player_name, stat, side, line, matchup, bet_type)` scoped to `(date, source_label)`. Same-day double-ingest by the same channel is safe.
- **`bets.confidence`** is `LEAN`/`LIKE`/`LOCK`/`null`. Panel bets map their 1-10 confidence score onto the same three tiers so leaderboards stay comparable to cappers.
- **`bets.stake_cents` / `bets.american_odds`** are populated only for panel bets (cappers don't quote stakes). `settle_bet()` defaults missing odds to -110.
- **Pending panel bets on re-run** — `make panel` calls `reset_panel_bets(date)` before re-inserting, so today's panel is idempotent. This is *not* true for capper ingestion (which relies on `sent.json` for dedup).

### External services

- **statsapi.mlb.com** — schedule, probable pitchers, weather, boxscores. No auth.
- **site.api.espn.com** — NBA schedule + boxscores, and MLB consensus odds (via `fetch_mlb_consensus()`). No auth.
- **baseballsavant.mlb.com** — daily-cached CSV exports for `expected_statistics` (batter xwOBA/xBA/xSLG) and `pitch-arsenal-stats` (per-pitch whiff%, K%, xwOBA). Note the UTF-8 BOM on these CSVs — `_load_cached_csv` strips it.
- **YouTube (yt-dlp + youtube-transcript-api)** — flat playlist extraction + full metadata pull. Optional Webshare proxy for transcripts.
- **Anthropic API** — Sonnet 4.6 for summarization / extraction / merge / persona picks / graded markdown rendering; Haiku 4.5 for the title/transcript "is this today?" classifiers.

---

## The context layer (`src/context/`)

Built to answer "what data is used to analyze each bet?", which the original
pipeline could not: every bet received the same ~52k-character blob and the
personas filled gaps with ad-hoc `web_search`, so two bets on one card could
rest on different evidence and the same bet could differ across runs.

```
src/context/
  contracts.py     22 declared fields; per-bet-type required/optional specs
  assemble.py      builds one slate's snapshot; coverage() scores a bet
  snapshot.py      immutable gzipped storage + per-game market path
  estimate.py      deterministic estimator + bootstrap resilience
  sim.py           the plate-appearance model: log5, base-out state machine,
                   the hook. NOT a driver — `game.py` is the only engine
  calibrate.py     replays real starts; tunes the hook; reliability + Brier
  f5_market.py     F5 against Kalshi's settled board, open vs close
  versus_market.py the same test for player props
  price.py         prices a whole slate against Kalshi
  quote.py         prices ONE bet you are looking at
  movement.py      per-bet: is the capper's quoted number still on the board
  gamestate.py     has this game started (guards every live-price fetch)
  scan.py          scans every offered line for robust disagreement
  store.py         context.db; morning_bets.db attaches READ-ONLY as `bets`
  advance.py       what runners actually do, counted on this league
  deploy.py        how bullpens are actually used, before modelling them
  relief.py        how long a relief outing lasts, and when he is pulled
  inherit.py       what inherited runners do, by base and out count
  removal.py       the LEARNED hook: when the starter comes out, fitted to
                   86k real decisions. Replaces sim.Hook for starters.
  tto.py           times through the order, measured
  stabilise.py     how fast each rate becomes trustworthy, measured
  form.py          PARKED - the latent "he does not have it tonight" state,
                   measured three ways and not there
  sources/pbp.py   whole-game play-by-play, gzipped; base-out-score state
  sources/         one module per data source, all offline-cacheable
```

**Two databases now.** `context.db` holds DERIVED tables (`mlb_stints`,
17,260 rows, rebuilt from the play-by-play cache in ~30s). `morning_bets.db`
attaches through a `mode=ro` URI as the `bets` schema, so joins read
`bets.games` as before and a stray INSERT raises. The pipeline DB is not
version controlled and holds a season of boxscores that cannot be
regenerated — that is the whole reason. Use `store.connect()`, not
`db.connect()`, from the context layer.

### The simulator supersedes the estimator (`sim.py`, `calibrate.py`)

`estimate.py` counts how many of a pitcher's last six starts would have won
a bet. That cannot work and the reason is not fixable by tuning: **six
starts cannot distinguish a 50% line from a 65% one.** Measured power at
alpha 0.05 is 8%, rising to 9% at ten starts. Every disagreement it reports
is either enormous or noise.

`sim.py` replaces the sample with a simulation — log5 matchup rates against
the specific nine he faces, a base-out state machine, and a hook fitted to
the league's own removal behaviour. Offline, no API key.

**THERE IS ONE ENGINE AND IT IS `game.py`.** `sim.py` holds the
plate-appearance model and the hook; it does NOT drive a simulation. The
one-sided driver — `sim.simulate_start` and `sim.simulate` — was deleted on
2026-08-25 along with the `f5.py` stub, the input-uncertainty block
(`DRAW_RATES`, `HOOK_SIGMA`) and `INHERITED_SCORE_RATE`, which existed only
because a loop that stopped at the hook could not simulate the reliever
finishing the inning. Everything now goes through `game.simulate_game`, via
`calibrate.replay` for historical pairs and `price.simulate_slate_game` for
a live slate. **A full game is ~20x the work of the old one-sided start** —
that is the price of both sides, a real bullpen and nine innings, and it is
why the suite went from 70s to 95s.

**Both starters or neither.** No opposing starter modelled means DECLINE to
price, never a league-average stand-in: inventing the other club invents the
score, and the score is what the hook, the bullpen and the margin are
conditioned on. `paired_cases` drops about 10% of starts for this reason.
The one mirror-the-opponent harness that exists is `tests/fixtures.py`, and
`check_nothing_prices_through_the_fixtures` stops it reaching `src/`.

**What it is worth, measured against real prices.** Against Kalshi's
CLOSING price the strikeout model adds nothing (blend weight 0.00,
t = −0.15 over 1,220 settled contracts). Against the OPENING price it adds a
lot: 32.9% better at predicting the close, 73.2% direction accuracy, +3.7
cents on five-cent disagreements. So its value is being EARLY, and realising
that means betting near the open where books are thinnest.

**First five innings is the lead, and it beat a settled market.** On 455
settled F5-total contracts our number scored 0.1890 Brier against Kalshi's
close at 0.1919 — the only time anything here has beaten a settled price on
realised outcomes. Unconfirmed at that sample; a 41-date run was in flight.

**Outs is the dead half.** CLV z = 1.3 against K's 43.5, because outs ARE
the hook — a manager decision the model reproduces only in aggregate.

The generalisation, and the most useful thing in these notes: **fit the
settlement value, not the upstream proxy.** `calibrate.loss()` targets the
hazard curve and outs distribution, which nobody bets, and that is the best
explanation for why the outs machinery calibrates beautifully and earns
nothing while F5 — an actual settled quantity — does better.

**Read `NOTES-context-layer.md` before changing any of this.** It carries
the measured calibration tables, which constants are fitted versus guessed,
and the known under-dispersion defect.

**Contracts vs adapters.** `contracts.py` declares WHAT a bet type needs;
`sources/*` know HOW to fetch it. Keeping them apart is what makes
"was the evidence complete for pick #3" answerable. Run
`venv/bin/python -m src.context.contracts` to print the spec, or
`... prop outs` for one.

**Snapshots are the durable record.** Savant serves season-to-date only and
cannot be asked what it said in June, so a backtest that rebuilds context
today is not a backtest. `snapshots/<date>/v<ver>_<utc>_<hash>.json.gz`,
immutable, ~600 KB raw / ~90 KB gzipped, deduped by content hash. Written by
the `com.morningbets.context` launchd job hourly 6:40–13:40.

**Why the window ends at 13:40.** ESPN drops a game's market at first pitch,
and `market` is required by all 11 contracts, so a brief assembled after the
slate starts structurally scores worse. Verified: 11/11 pregame games had a
market, 0/4 started ones did.

### Rules the code enforces (and why)

- **Never price a game in progress.** `gamestate.is_pregame()` guards
  `movement`, `fill_missing_prop_lines`, and `assign_stakes`. Unknown state
  resolves to *not* pregame: a stale number costs little, pricing a live game
  writes fiction nothing downstream can detect.
- **Measuring is not fitting.** Replacing a published constant with the
  same quantity COUNTED on this league is legitimate and is not tuning
  against the settlement value — provided the conditioning matches the code
  path exactly. There is no loss function behind `advance.py` and there must
  not be one. What is forbidden is handing a measured quantity back to a
  search, where it goes back to absorbing other defects.
- **The dead list records HOW a thing was tried, not that it is
  unknowable.** Six of the nine dead features were imported scalar
  multipliers scored against a model that has since changed, on half the
  data. Re-opening one is legitimate when the APPROACH changes (residual fit
  rather than import) or the DATA does (play-by-play). Pre-register it.
- **Shrink toward a prior, and keep the underlying value.** Where a group
  number stands in for an individual, both travel and one is marked as the
  lead — `catcher_framing` (exact / unrated / estimated),
  `workload_context` (club hook vs this starter's own record),
  `game_log_summary` (flat last-10 vs 6-week window).
- **A guessed value must not move the estimate in the wrong direction.**
  A confirmed-but-unrated catcher gets league-neutral, never another
  catcher's number.
- **IDs, not names.** `'Arizona Diamondbacks'` vs a standings row reading
  `'D-backs'` cost that club four fields. Team and venue ids travel through
  `mlb_schedule_with_probables`.
- **Neutral sites get no park factors.** A `venue_id` that misses returns
  None rather than the home club's park — MLB plays in Mexico City.

### Test suite

`make test` (328 checks, ~95s, no network, no pytest). `tests/run.py` collects
every `check_*`. `tests/test_regressions.py` is one check per bug that
actually shipped, verified by mutation — reintroducing a fix fails exactly
the check that covers it.
