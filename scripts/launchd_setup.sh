#!/bin/bash
# Install morning-bets as launchd agents instead of cron.
#
# Why launchd and not cron: this runs on a laptop that is usually closed at
# the scheduled time. cron simply skips a job whose moment passed while the
# machine was asleep — the day is silently lost. launchd re-runs a missed
# StartCalendarInterval job when the machine next wakes, so opening the lid
# in the morning triggers whatever should have fired overnight.
#
#   scripts/launchd_setup.sh install     write + load the agents
#   scripts/launchd_setup.sh uninstall   unload + remove them
#   scripts/launchd_setup.sh status      show what is loaded
#
# Logs go to cron.log in the repo, same as the cron setup did.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/venv/bin/python"
# Jobs go through run_job.sh, which waits for the network before running the
# module — launchd fires missed jobs on wake, before wifi is up.
RUNNER_SRC="$REPO/scripts/run_job.sh"
# Same TCC rule as the log below: launchd cannot open a script under
# ~/Documents to interpret it, so the runner is installed outside. Exec'ing
# the venv python from the repo is fine — that is a binary exec, not a file
# read by /bin/bash.
SUPPORT="$HOME/Library/Application Support/morning-bets"
RUNNER="$SUPPORT/run_job.sh"
AGENTS="$HOME/Library/LaunchAgents"
PREFIX="com.morningbets"

# Logs must live OUTSIDE ~/Documents. launchd opens StandardOutPath itself,
# before exec'ing the job, and launchd has no TCC access to the protected
# Documents folder — pointing the log at the repo makes every job die with
# exit 78 (EX_CONFIG) having produced no output at all. The child python can
# still read the repo once it is running; only launchd's own file open fails.
LOGDIR="$HOME/Library/Logs/morning-bets"
LOG="$LOGDIR/run.log"
mkdir -p "$LOGDIR"

if [ ! -x "$PY" ]; then
  echo "error: $PY not found — run 'make install' first" >&2
  exit 1
fi

if [ ! -f "$RUNNER_SRC" ]; then
  echo "error: $RUNNER_SRC not found" >&2
  exit 1
fi
mkdir -p "$SUPPORT"
cp "$RUNNER_SRC" "$RUNNER"
chmod +x "$RUNNER"

# Nothing that costs real money runs on a timer any more; analysis waits
# for `make morning`. What is automatic:
#
#   grade     hourly 03:00-11:00 — yesterday's West Coast games finish
#             around 1-2am ET, and --if-needed makes every pass after the
#             first a no-op.
#   discover  hourly 03:00-17:00 — a yt-dlp listing plus a Haiku title check.
#             Cannot usefully run before midnight at all (find_video matches
#             against date.today(), so a 22:30 upload for tomorrow is
#             invisible until the date flips), and the latest overnight
#             upload observed is 02:46, so 3am catches the whole night in
#             one pass instead of three wasted ones.
#   process   hourly 06:00-17:00 — transcript + two Sonnet calls per video,
#             so it waits for the morning even though the videos were found
#             hours earlier.
hours_of() {
  local out=""
  for h in $(seq "$1" "$2"); do
    out="$out
      <dict><key>Hour</key><integer>$h</integer>
            <key>Minute</key><integer>${3:-0}</integer></dict>"
  done
  printf '%s' "$out"
}

write_plist() {
  local label="$1" module="$2" schedule="$3"
  # Each word of $module becomes its own <string>; a plist argv element is
  # passed verbatim, so "src.grading --if-needed" as one entry would reach
  # python as a single unparseable module name.
  local argv=""
  for word in $module; do
    argv="$argv
    <string>$word</string>"
  done
  cat > "$AGENTS/$PREFIX.$label.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PREFIX.$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$RUNNER</string>$argv
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>MORNINGBETS_REPO</key><string>$REPO</string></dict>
  <!-- No WorkingDirectory: launchd chdir'ing into ~/Documents trips TCC
       ("getcwd: Operation not permitted") before the job even starts.
       run_job.sh cd's there itself once running. -->
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>StartCalendarInterval</key>
  <array>$schedule
  </array>
</dict>
</plist>
PLIST
  echo "  wrote $AGENTS/$PREFIX.$label.plist"
}

one_time() {
  printf '\n      <dict><key>Hour</key><integer>%s</integer>\n            <key>Minute</key><integer>%s</integer></dict>' "$1" "$2"
}

case "${1:-status}" in
  install)
    mkdir -p "$AGENTS"
    write_plist grade    "src.grading --if-needed"  "$(hours_of 3 11)"
    write_plist discover "src.main discover"        "$(hours_of 3 17 5)"
    write_plist process  "src.main process"         "$(hours_of 6 17 20)"
    for l in grade discover process; do
      launchctl unload "$AGENTS/$PREFIX.$l.plist" 2>/dev/null || true
      launchctl load  "$AGENTS/$PREFIX.$l.plist"
    done
    echo
    echo "Loaded. Missed runs fire when the laptop wakes."
    launchctl list | grep "$PREFIX" || true
    echo
    echo "NOTE: cron may still hold the old schedule — remove those lines"
    echo "      with: crontab -l | grep -v morning-bets | crontab -"
    ;;
  uninstall)
    for l in grade discover process; do
      launchctl unload "$AGENTS/$PREFIX.$l.plist" 2>/dev/null || true
      rm -f "$AGENTS/$PREFIX.$l.plist"
    done
    echo "Removed all $PREFIX agents."
    ;;
  status)
    launchctl list | grep "$PREFIX" || echo "  no $PREFIX agents loaded"
    ;;
  *)
    echo "usage: $0 {install|uninstall|status}" >&2
    exit 1
    ;;
esac
