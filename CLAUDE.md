# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read this first — two systems, one repo

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
removal hook. It is calibrated to within 2% on every per-start rate, and
what it is worth has been measured against real Kalshi prices rather than
argued about:

  * Against the CLOSING price on strikeouts it adds NOTHING (t = -0.15).
  * Against the OPENING price it adds a lot (+32.9%, 73.2% direction).
  * On FIRST FIVE INNINGS totals it shows the same shape as strikeouts and
    a comparable edge: beats the open (20.5% vs 19.3% Brier skill), loses
    to the close, CLV z +31.4 with 67.1% direction accuracy and +3.9 cents
    on five-cent disagreements over 2,149 settled contracts.

The generalisation that came out of two days of measurement, and the single
most useful line in these docs: **fit the settlement value, not the upstream
proxy.** Every feature imported as known baseball (handedness, park,
day/night, bullpen, arsenal) measured zero. Everything fitted as a residual
against the model's own error helped. And the quantity you tune against
decides what you get: `calibrate.loss()` targets the outs distribution,
which nobody bets, and outs is exactly where the model earns nothing.

The two systems are only loosely joined. **Snapshots are NOT wired into the
personas**, so `make panel` / `make recommend` still use the old blob.

**WHAT THIS MODELS, settled 2026-08-23: F5 TEAM TOTALS, and to a lesser
extent full team totals. Props are NOT the target** — they are expected to
follow from a game simulation that is actually right. Two rules follow, and
both are enforced in `fitf5.py`: do not score against the lines a book
offers (score the full support of the run distribution, where the same
arithmetic is the discrete CRPS), and do not fit the hook.

**START WITH `RESUME.md`** — where the edge is, what to do next, and the
long list of things already measured and dead so nobody re-runs them.

**Before touching the context layer, read `NOTES-context-layer.md`.** It
opens with "DAY THREE", which carries the current state, then the measured
negatives — SEVEN features that cost real time and returned nothing,
recorded so nobody re-runs them.

**The single most useful diagnostic in this project, now four for four: a
fitted parameter sitting at the EDGE of its grid is a missing mechanism, not
a tuning problem.** It found the absent hit-by-pitch, absent fielding
errors, and out-dependent runner advancement (twice). Treat a grid-edge
result as a mechanism hypothesis immediately, not after three sweeps.

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
- `venv/bin/python -m src.context.f5` / `... f5_market [DATE]` — first-five simulation, and its open-vs-close test.
- `venv/bin/python -m src.context.versus_market` — the same test for K props.
- `venv/bin/python -m src.context.calibrate` — replay real starts, compare the simulated distribution to what happened.
- `... calibrate --reliability k|outs|all` — does a simulated 60% win 60% of the time? Pooled across starts, bucketed by what the model said. The check that matters for pricing.
- `... calibrate --tune` — coordinate descent on the hook against the observed hazard curve.
- `... calibrate --patience` / `--leash` — fit club and pitcher removal offsets as RESIDUALS. Order matters: club first, pitcher against the remainder, or the manager gets counted twice.
- `... calibrate --holdout YYYY-MM-DD` — refit on the training window only, score on unseen starts.
- `venv/bin/python -m src.context.sources.starters --backfill` — ground truth for who started. `grading.py` sets this going forward; the backfill is for history.
- `make test` / `make test ARGS=sim` — 245 offline checks, ~60s.

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
  sim.py           plate-appearance simulator; log5 + base-out + fitted hook
  calibrate.py     replays real starts; tunes the hook; reliability + Brier
  f5.py            first five innings: both starters + relief -> run totals
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
the league's own removal behaviour. Offline, no API key, ~15k starts/sec.

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

`make test` (245 checks, ~60s, no network, no pytest). `tests/run.py` collects
every `check_*`. `tests/test_regressions.py` is one check per bug that
actually shipped, verified by mutation — reintroducing a fix fails exactly
the check that covers it.
