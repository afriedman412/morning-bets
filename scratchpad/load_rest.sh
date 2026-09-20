#!/bin/bash
cd /Users/user/Documents/code/morning-bets
# Wait for 2024 to finish before starting 2023: one writer at a time. A
# SQLite lock collision is COUNTED AS A FAILED DATE and skipped, which would
# leave silent gaps that look exactly like a completed load.
until grep -q "^{" scratchpad/load2024.log 2>/dev/null; do sleep 30; done
echo "2024 done:"; tail -1 scratchpad/load2024.log
venv/bin/python -m scratchpad.load2025 2023 > scratchpad/load2023.log 2>&1
echo "2023 done:"; tail -1 scratchpad/load2023.log
echo "=== play-by-play for both ==="
venv/bin/python -c "from src.context.sources import pbp; print(pbp.backfill(workers=8))"
echo "=== real pitch counts ==="
venv/bin/python -c "from src.context.sources import pitches; print(pitches.backfill(workers=8))"
echo "=== HISTORY LOAD COMPLETE ==="
