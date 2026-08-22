# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

There is no test suite. The Makefile's `test` and `lint` targets reference tooling that isn't installed.

Runtime deps assume `ANTHROPIC_API_KEY` in `.env`. Optional: `WEBSHARE_USERNAME` + `WEBSHARE_PASSWORD` for a residential proxy on `youtube_transcript_api` (helps when YouTube rate-limits).

The cron schedule lives in `.cron-config` (hourly run 8am-5pm, grading at 9am).

## Architecture

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
