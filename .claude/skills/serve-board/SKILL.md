---
name: serve-board
description: Start the local Flask board server if it is not already running, and hand back the URL. Use when the user asks to launch, start, open or serve the board server or the board page, asks whether the server is up, or wants a link to browse boards by date.
---

# Serve the board

One long-lived Flask process on `127.0.0.1:8060` that renders any board
JSON under `bets/` behind a date sidebar. **It is idempotent by design:
if something is already listening, say so and hand back the URL. Do not
start a second one.**

Nothing here re-prices anything. Pricing is `/board`; this only serves
what `/board` has already written.

## Run it

```
# 1. Is it already up? 200 means yes — stop here and give the URL.
curl -s -o /dev/null -w '%{http_code}\n' --max-time 2 http://127.0.0.1:8060/
```

`200` (or `302`, which `/` returns on its redirect to the newest date) —
**it is already running. Report the URL and stop.** `000` means nothing
answered, so start it:

```
# 2. Start it detached, with a log to read when it will not come up.
venv/bin/python -m scratchpad.board_server > /tmp/board_server.log 2>&1 &

# 3. Wait for it to answer rather than sleeping a guessed number.
until curl -s -o /dev/null --max-time 1 http://127.0.0.1:8060/; do sleep 0.3; done
echo "http://127.0.0.1:8060/"
```

Then give the user the URL. Open it with `open http://127.0.0.1:8060/`
only if they asked to have it opened — a background server is often
wanted without a browser jumping to the front.

`--port N` moves it; check and start on the same port if you pass one.

## The traps

**A 000 does not always mean "free".** Something else on 8060, or a
half-dead previous run, answers nothing while still holding the port.
If step 3 never succeeds, read `/tmp/board_server.log` — a port clash
prints `Address already in use` and needs `lsof -nP -iTCP:8060
-sTCP:LISTEN` to find the holder, not another start attempt.

**Do not run it in the foreground.** It blocks until killed, and a
foreground Flask in a tool call hangs the turn with nothing to show for
it. Background it, then poll.

**Do not restart it to pick up a new board.** Pages re-render per request
straight off the JSON and nothing is cached, so a board written while the
server is up appears on the next refresh. Restarting is never the fix for
a stale page — a stale page means the board was written to a path the
server is not reading, which is a `/board` problem.

**It serves `bets/` from the repo it was started in**, so start it from
the project root. Paths inside resolve off the module, not the working
directory, but the port does not.

## What it serves

- `/` redirects to the newest date with a board.
- `/board/<YYYY-MM-DD>` is that date's board of record — the newest file
  by mtime. Earlier pulls of the same date stay reachable from the
  sidebar's version list, which is the point of `/board` versioning.
- `POST /ask` is the only route that costs money or touches the network;
  it needs `ANTHROPIC_API_KEY` and answers in the page's panel. A missing
  key comes back as a sentence, not a 500.

Reading a board is `BETTING.md`'s job, not this skill's.
