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

The current goal is narrower and better posed: **validate the lines that are
actually offered.** Assemble the evidence deterministically, compare it to
each posted price, and surface only disagreements that survive resampling.
Most flags will be small samples being loud, and a meaningful share will be
our own bugs — which is how most of this system's defects were found.

The two are only loosely joined today. **Snapshots are NOT yet wired into
the personas**, so `make panel` / `make recommend` still use the old blob.
Closing that gap is the main outstanding piece of work.

**Before touching the context layer, read `NOTES-context-layer.md`.** It
carries the live debugging state: the one known-broken flag rule, a
half-applied fix, every constant that was invented rather than derived, and
a list of findings that would waste a day if re-investigated.

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

### Context-layer entrypoints (all offline-cacheable, no API key)

- `venv/bin/python -m src.context.contracts [bet_type stat]` — print the evidence spec.
- `venv/bin/python -m src.context.assemble [DATE]` — build a slate's brief, print coverage.
- `venv/bin/python -m src.context.snapshot [DATE]` — assemble + store; `--list` shows history and line movement.
- `venv/bin/python -m src.context.scan [DATE]` — scan every offered line for disagreement. **Flag rule is known-broken; see NOTES.**
- `venv/bin/python -m src.context.movement [DATE]` — is each capper's quoted number still on the board.
- `venv/bin/python -m src.context.gamestate [DATE]` — which games are safe to price.
- `venv/bin/python -m src.context.sources.<name>` — every source module has a demo main.
- `make test` / `make test ARGS=regressions` — 42 offline checks, ~1s.

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
  movement.py      per-bet: is the capper's quoted number still on the board
  gamestate.py     has this game started (guards every live-price fetch)
  scan.py          scans every offered line for robust disagreement
  sources/         one module per data source, all offline-cacheable
```

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

`make test` (42 checks, ~1s, no network, no pytest). `tests/run.py` collects
every `check_*`. `tests/test_regressions.py` is one check per bug that
actually shipped, verified by mutation — reintroducing a fix fails exactly
the check that covers it.
