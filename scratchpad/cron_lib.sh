# Shared preconditions for the scheduled jobs. Sourced, never run.
#
# WHY THIS EXISTS. On 2026-09-21 the hourly job fired five times, exactly
# on schedule, and failed all five — 36 seconds each, deep inside
# `slate.slate()`, with a urllib traceback in a log nobody was reading.
# Nothing said "no network"; it looked like the board was broken.
#
# THE CAUSE WAS NOT SLEEP, though sleep is what triggered it. This Mac
# has exactly ONE resolver, 100.64.100.1, routed over the VPN's utun3
# with NO fallback — not the router, not a public resolver. When the
# tunnel is down the machine has no DNS at all. Idle sleep (set to one
# minute) dropped the tunnel, launchd woke the job into DarkWake, and
# every lookup died instantly. Any tunnel drop does the same thing,
# including one while somebody is sitting at the keyboard, so keeping
# the Mac awake is a mitigation and this is the guard.
#
# FAIL FAST AND SAY WHY. A four-minute board run that cannot resolve a
# hostname is four minutes wasted and one more traceback; this turns it
# into one line naming the actual problem, before any work starts.

#: Long enough for a wake to bring an interface up, short enough that a
#: genuinely dead tunnel does not eat the hour.
DNS_TRIES="${DNS_TRIES:-6}"
DNS_WAIT="${DNS_WAIT:-10}"

require_dns() {
    # require_dns <host> — 0 when it resolves, 1 when it never does.
    local host="$1" i=1
    while :; do
        if "$PY" -c "
import socket, sys
socket.setdefaulttimeout(5)
socket.gethostbyname(sys.argv[1])
" "$host" >/dev/null 2>&1; then
            [ "$i" -gt 1 ] && say "  DNS came up on attempt $i"
            return 0
        fi
        if [ "$i" -ge "$DNS_TRIES" ]; then
            say "NO DNS for $host after $i attempts — nothing ran."
            say "  This machine's only resolver is inside the VPN tunnel."
            say "  Check the VPN is up: scutil --dns | grep nameserver"
            return 1
        fi
        say "  no DNS for $host (attempt $i/$DNS_TRIES), waiting ${DNS_WAIT}s"
        i=$((i + 1))
        sleep "$DNS_WAIT"
    done
}
