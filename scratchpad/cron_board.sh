#!/bin/bash
# ONE HOURLY PULL OF THE BOARD. Driven by com.morningbets.hourly.
#
# Every run is a NEW VERSION — `boards --next` hands back _board, then
# _board_v2, _v3, ... so a pull never overwrites the pull before it. That
# is the whole point: the series of boards across an afternoon IS the
# record of how our number moved as lineups landed, and an overwrite
# destroys exactly the comparison it exists to make.
#
# THE PATH IS RESOLVED OFF THIS FILE, not typed. `scratchpad/battery.sh`
# still cds to /Users/user/... from a machine nobody has used in a year,
# which is silent breakage the moment anything runs it unattended.
#
# Exits non-zero on any failed step, and launchd logs it. A step that
# fails still leaves the partial stem behind; the next hour takes the
# next number rather than reusing a name that has a file on it.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
PY="$ROOT/venv/bin/python"
LOG="$ROOT/logs/board.log"
mkdir -p "$ROOT/logs"

# macOS aborts a forked child that has touched the Objective-C runtime,
# and the board forks a pool AFTER a `roster.load()` that can reach the
# network. `scratchpad.battery` re-execs for the same reason. Interactive
# runs have survived it; an unattended one that does not would look like
# a hang with no board written.
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

DATE="${1:-$(date +%F)}"

say() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
die() { say "FAILED at $1"; exit 1; }

# NOTHING BELOW WORKS WITHOUT DNS, and a board run that finds that out
# four minutes in leaves a traceback instead of a reason. See cron_lib.sh.
. "$ROOT/scratchpad/cron_lib.sh"
require_dns statsapi.mlb.com || exit 1

STEM="$("$PY" -m scratchpad.boards --next "$DATE")" || die "next_stem"
say "pull $DATE -> $(basename "$STEM")"

"$PY" -m scratchpad.board "$DATE" > "$STEM.txt" 2>>"$LOG" || die "board"
"$PY" -m scratchpad.board_json "$DATE" "$STEM.txt" "$STEM.json" \
    >>"$LOG" 2>&1 || die "board_json"
"$PY" -m scratchpad.gen_board_html "$DATE" "$STEM.json" "$STEM.html" \
    >>"$LOG" 2>&1 || die "gen_board_html"

say "ok $(basename "$STEM")  $(grep -c ' / ' "$STEM.txt" 2>/dev/null) rungs"
