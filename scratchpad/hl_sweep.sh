#!/bin/bash
# Half-life sweep, take 2. OBJC_... exported so battery.main's re-exec
# branch never fires and the in-process HALF_LIFE_DAYS survives.
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
for HL in 0 30 60 90 150; do
  echo "=== HALF_LIFE_DAYS = $HL ==="
  venv/bin/python -c "
from src.context.sources import rates
rates.HALF_LIFE_DAYS = float($HL) or None
from scratchpad import battery
battery.main([])
" > scratchpad/hl_sweep_$HL.log 2>&1
  grep -E "HALF_LIFE_DAYS|engine fingerprint|saved" scratchpad/hl_sweep_$HL.log | tail -3
done
echo "SWEEP DONE"
