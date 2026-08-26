"""Snapshot every season-sensitive number, so step 1 can be PROVEN a no-op.

    venv/bin/python -m scratchpad.scope_baseline > scratchpad/scope_<tag>.json

The database holds only 2026, so defaulting `season` to the current season
must change nothing. That is a claim worth checking rather than asserting:
the whole point of doing this before loading 2025 is that afterwards there
would be no way to tell a pooling bug from a real 2025 effect.
"""
import hashlib
import json

from src.context import calibrate as cal
from src.context import sim
from src.context.sources import rates as rate_src


def digest(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def main():
    lg = sim.league()
    pr = rate_src.pitcher_rates(lg)
    br = rate_src.batter_rates(lg)
    cases = cal.build_cases()
    out = {
        "league": lg,
        "league_digest": digest(lg),
        "n_pitchers": len(pr),
        "pitcher_digest": digest(pr),
        "n_batters": len(br),
        "batter_digest": digest(br),
        "n_cases": len(cases),
        "case_digest": digest([(c[0]["game_id"], c[0]["player_name"],
                                round(c[1].k_pct, 9), round(c[1].bb_pct, 9),
                                round(c[1].hr_pct, 9), round(c[1].babip, 9))
                               for c in cases]),
    }
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
