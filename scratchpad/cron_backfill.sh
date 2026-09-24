#!/bin/bash
# THE DAILY BACKFILL, ONCE, BEFORE THE FIRST BOARD OF THE DAY.
# Driven by com.morningbets.backfill at 07:30.
#
# WHY IT IS DAILY AND NOT HOURLY, WHICH IS THE WHOLE REASON THIS IS A
# SEPARATE JOB. The backfill rewrites games already in the set — venues,
# lineups and pitch counts — and that alone moved the engine fingerprint
# 2fa14f8df0c6 -> 00925f199684 with identical code. Run it between hourly
# pulls and our price moves for a DATA reason in the middle of a series
# whose entire purpose is to show the market moving for an INFORMATION
# reason. The two would be indistinguishable after the fact.
#
# So: backfill once, before the first pull, then the data is frozen for
# the rest of the day and every board that day is comparable to every
# other. Steps are in dependency order; each reads what the one above
# wrote. See .claude/skills/backfill-data.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
PY="$ROOT/venv/bin/python"
LOG="$ROOT/logs/backfill.log"
mkdir -p "$ROOT/logs"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

say() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

fail=0
run() {                      # run <label> <cmd...>
    local label="$1"; shift
    say "-- $label"
    if ! "$@" >>"$LOG" 2>&1; then
        say "   FAILED: $label"
        fail=1
    fi
}

# Every step below fetches. Without DNS the chain "succeeds" at pulling
# nothing, which is worse here than in the board — a quiet no-op backfill
# is how the data silently stops being fresh. See cron_lib.sh.
. "$ROOT/scratchpad/cron_lib.sh"
require_dns statsapi.mlb.com || exit 1

say "=== daily backfill ==="
run "results"      "$PY" -m src.context.sources.season --backfill
run "play-by-play" "$PY" -m src.context.sources.pbp --backfill --sync
run "weather"      "$PY" -m src.context.sources.weather --backfill
run "lineups"      "$PY" -m src.context.order --build
run "batted ball"  "$PY" -m src.context.sources.battedball --build
# A SHIPPED INPUT THAT IS A FILE, NOT A TABLE, AND IT WAS NOT IN THIS
# CHAIN UNTIL 2026-09-22: every starter's K and BB kick is read off
# velo_starts.json, nothing rebuilt it, and nothing reported it either,
# so it drifted in silence while data_status showed every table at 0d.
run "velocity"     "$PY" -m src.context.velo --build
# LAST: built from the pbp cache plus mlb_stints, so it is wrong if the
# play-by-play step has not finished. Never pipe it to `head` — it writes
# only at the end and a SIGPIPE kills it looking like success.
# `--rows-only` because the six logistic fits below it are research the
# backfill has no consumer for — 21s a morning printed into this log.
run "hook rows"    "$PY" -m scratchpad.fit_hooks --rebuild --rows-only

say "-- data_status"
"$PY" -m scratchpad.data_status 2>&1 | tee -a "$LOG"

[ "$fail" -eq 0 ] || { say "=== backfill FINISHED WITH FAILURES ==="; exit 1; }
say "=== backfill ok ==="
