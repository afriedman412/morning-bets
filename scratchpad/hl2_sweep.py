"""Item 35 sweep driver — one battery run per per-channel candidate.

    export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
    venv/bin/python -m scratchpad.hl2_sweep <hl> [battery args...] \\
        2>&1 | tee scratchpad/hl2_sweep_<hl>.log

Sets `rates.CHANNEL_HALF_LIFE_DAYS = {'bb_pct': hl, 'babip': hl}` IN
PROCESS (K and HR flat by construction — the item 35 pre-registration)
and hands the rest of the argv to `battery.main`. The env var must be
exported BEFORE launch: without it `battery.main` re-execs
`-m scratchpad.battery` and the knob silently resets — the exact item-D
trap that produced five identical fingerprints. This driver refuses to
run without it. `<hl> = 0` runs flag-off (the baseline arm).

THE POSITIVE CONTROL (rule 7): `--inject-recent-bb <mult>` multiplies
every pitcher's walks by `<mult>` in games within `INJECT_DAYS` of his
window's newest game — IN THE MODEL'S RATE INPUTS ONLY, the actuals the
battery scores against are untouched. That plants a command decay of a
known size, and the run pair (hl=0 with the injection vs hl=60 with it)
shows which battery rows can see the mechanism at all. Injection forces
the per-game path even at hl=0 (an `inf` half-life ages to weight 1.0
exactly) so both arms read identical inputs.
"""
from __future__ import annotations

import os
import sys

from src.context.sources import rates
from scratchpad import battery

INJECT_DAYS = 30


def main():
    assert os.environ.get("OBJC_DISABLE_INITIALIZE_FORK_SAFETY") == "YES", \
        ("export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES before launching —"
         " battery.main re-execs otherwise and the knob resets (item D)")
    argv = list(sys.argv[1:])
    hl = int(argv.pop(0))
    inject = None
    if "--inject-recent-bb" in argv:
        i = argv.index("--inject-recent-bb")
        inject = float(argv[i + 1])
        del argv[i:i + 2]
    if hl:
        rates.CHANNEL_HALF_LIFE_DAYS = {"bb_pct": hl, "babip": hl}
    elif inject:
        # The control's flat arm still needs the per-game path so the same
        # injection reaches both arms; 0.5 ** (age/inf) is exactly 1.0.
        rates.CHANNEL_HALF_LIFE_DAYS = {"bb_pct": float("inf")}
    if inject:
        orig = rates._weighted_rows_per_channel

        def _inject(games, chl):
            games = [dict(g) for g in games]
            if games:
                latest = max(g["date"] for g in games)
                for g in games:
                    if rates._days(latest, g["date"]) <= INJECT_DAYS:
                        g["bb"] = (g["bb"] or 0) * inject
            return orig(games, chl)

        rates._weighted_rows_per_channel = _inject
        print(f"  *** POSITIVE CONTROL: recent-{INJECT_DAYS}d walks x "
              f"{inject} in the MODEL'S INPUTS ONLY ***")
    battery.main(argv)


if __name__ == "__main__":
    main()
