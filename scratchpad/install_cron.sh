#!/bin/bash
# INSTALL THE TWO SCHEDULED JOBS FROM THE TEMPLATES IN THIS DIRECTORY.
#
#     bash scratchpad/install_cron.sh [--dry-run] [--uninstall]
#
# WHY THIS EXISTS. Until 2026-09-21 the entire scheduling layer lived in
# two places, neither of them the repository: three untracked `cron_*.sh`
# in `scratchpad/`, and two plists in ~/Library/LaunchAgents that were in
# no version control at all. A clone had no scheduler, an `rm` in
# scratchpad took it out with no undo, and the plists' own commentary —
# why the backfill is daily, why the window stops at 23:05, why
# AbandonProcessGroup is false — could not be reviewed or diffed.
#
# THE PLISTS HARDCODE AN ABSOLUTE ROOT because launchd does not expand
# anything. So they are stored as `.plist.in` with a `__ROOT__` token and
# rendered here against THIS checkout, resolved off this file rather than
# typed — the same rule `cron_board.sh` follows, and for the same reason:
# `scratchpad/battery.sh` still cds to a /Users/user/... path from a
# machine nobody has used in a year.
#
# IDEMPOTENT. Rendering over an identical installed plist is a no-op that
# says so. `launchctl bootout` before `bootstrap` is what makes a re-run
# pick up an edited template; a missing job boots out with an error that
# is expected and ignored.
#
# THIS DOES NOT START ANYTHING. Both plists are RunAtLoad=false, so
# nothing fires until its next calendar interval. Installing at 15:40
# means the next board is 16:05.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
JOBS=(backfill hourly)
DRY=0; UNINSTALL=0
for a in "$@"; do
    case "$a" in
        --dry-run) DRY=1 ;;
        --uninstall) UNINSTALL=1 ;;
        *) echo "unknown argument: $a" >&2; exit 2 ;;
    esac
done

say() { echo "  $*"; }
uid="$(id -u)"

echo "root: $ROOT"
mkdir -p "$AGENTS"

for j in "${JOBS[@]}"; do
    label="com.morningbets.$j"
    src="$ROOT/scratchpad/launchd/$label.plist.in"
    dst="$AGENTS/$label.plist"

    if [ "$UNINSTALL" = 1 ]; then
        say "$label: booting out and removing"
        [ "$DRY" = 1 ] || {
            launchctl bootout "gui/$uid/$label" 2>/dev/null
            rm -f "$dst"
        }
        continue
    fi

    [ -f "$src" ] || { echo "MISSING TEMPLATE: $src" >&2; exit 1; }
    rendered="$(sed "s|__ROOT__|$ROOT|g" "$src")"

    # The script the job actually runs must exist, or the job fails
    # silently into a log at its next interval — which is how the four
    # original com.morningbets.* jobs died.
    prog="$(printf '%s\n' "$rendered" | grep -o '[^<>]*/scratchpad/cron_[a-z]*\.sh' | head -1)"
    [ -f "$prog" ] || { echo "MISSING SCRIPT: $prog" >&2; exit 1; }

    if [ -f "$dst" ] && [ "$rendered" = "$(cat "$dst")" ]; then
        say "$label: already installed and identical"
        continue
    fi
    say "$label: $([ -f "$dst" ] && echo updating || echo installing) -> $dst"
    [ "$DRY" = 1 ] && continue
    printf '%s\n' "$rendered" > "$dst"
    launchctl bootout "gui/$uid/$label" 2>/dev/null
    launchctl bootstrap "gui/$uid" "$dst" || {
        echo "FAILED to bootstrap $label" >&2; exit 1; }
done

[ "$DRY" = 1 ] && { echo "(dry run — nothing written)"; exit 0; }
echo
echo "loaded now:"
launchctl list | grep morningbets || echo "  (none — check the output above)"
