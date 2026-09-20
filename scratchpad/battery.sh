#!/bin/bash
# The full re-measurement, once 2025 is loaded. Sequential on purpose: each
# step is itself parallel across cores, so overlapping them would just make
# them contend.
cd /Users/user/Documents/code/morning-bets
V=venv/bin/python
echo "=== 1. play-by-play backfill, pass 2 (rest of 2025) ==="
$V -c "from src.context.sources import pbp; print(pbp.backfill(workers=8))"
echo; echo "=== 2. season stability gate, full 2025 vs 2026 ==="
$V -m scratchpad.season_hook
echo; echo "=== 3. preseason rank, 2025 matched cut ==="
$V -m scratchpad.preseason_test 2025-07-01
echo; echo "=== 4. preseason rank, 2026 (for side-by-side) ==="
$V -m scratchpad.preseason_test 2026-07-01
echo; echo "=== 5. cross-season memory ==="
$V -m scratchpad.memory 30
echo; echo "=== 6. boundary curves re-scored on the current engine ==="
$V -m scratchpad.score_boundary 30 --no-leash
echo; echo "=== BATTERY COMPLETE ==="
