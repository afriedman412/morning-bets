#!/bin/bash
# Wrapper launchd uses to run a pipeline module.
#
# Why this exists: launchd fires a missed StartCalendarInterval job the
# instant the laptop wakes, which is several seconds before wifi associates.
# Every job then dies on DNS ("nodename nor servname provided") having done
# nothing — that is how a whole morning's ingest silently produced zero bets.
# Waiting for connectivity first turns a guaranteed failure into a short pause.
#
#   scripts/run_job.sh src.main
#
# Also stamps each run in the log. Without a timestamp the log is one
# undifferentiated stream and you cannot tell which run failed.
set -uo pipefail

# launchd cannot exec a shell script stored under ~/Documents (TCC blocks it
# opening the file — "Operation not permitted"), so launchd_setup.sh installs
# a copy outside Documents and passes the repo path in. Fall back to the
# script's own location when run by hand from the repo.
REPO="${MORNINGBETS_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="$REPO/venv/bin/python"
MODULE="${1:?usage: run_job.sh <module> [args...]}"
shift

# How long to wait for the network before giving up, in seconds.
WAIT_MAX="${MORNINGBETS_NET_WAIT:-600}"
PROBE_EVERY=10

stamp() { date "+%Y-%m-%d %H:%M:%S"; }

# Apple's captive-portal endpoint: tiny, unauthenticated, and exercises
# DNS + TCP + HTTP, which is exactly what the jobs need. Overridable so the
# offline branch can be tested without taking the machine off wifi.
PROBE_URL="${MORNINGBETS_PROBE_URL:-http://captive.apple.com/hotspot-detect.html}"

online() {
  /usr/bin/curl -sf --max-time 5 -o /dev/null "$PROBE_URL"
}

echo ""
echo "===== $(stamp) $MODULE ====="

if ! online; then
  echo "  network down — waiting up to ${WAIT_MAX}s..."
  deadline=$(( $(date +%s) + WAIT_MAX ))
  until online; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      # Exit 0 deliberately: a skipped run is not a crash, and the next
      # scheduled run picks the work up. Grading leaves bets PENDING and
      # ingest is hourly, so nothing is lost by sitting this one out.
      echo "  !! $(stamp) network never came up — skipping $MODULE"
      exit 0
    fi
    sleep "$PROBE_EVERY"
  done
  echo "  network up at $(stamp)"
fi

cd "$REPO" || exit 1
"$PY" -m "$MODULE" "$@"
status=$?
echo "----- $(stamp) $MODULE exit=$status -----"
exit "$status"
