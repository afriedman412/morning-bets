"""Backfill the 2025 season into the pipeline DB. Sequential and polite.

    venv/bin/python -m scratchpad.load2025

Explicit date window rather than moving `season.SEASON_START`, which is
2026 opening day and is what the DAILY job uses — repointing it would make
the cron job start walking last season every morning.

Play-by-play is NOT touched here. It lives in `.cache/pbp` as one gzipped
file per game and is fetched separately, after these games exist, because
`pbp.final_games()` reads the `games` table to know what to ask for.
"""
from datetime import date

from src.context.sources import season

# Dates outside a season return no games and cost one schedule call, so the
# windows are deliberately loose at both ends.
WINDOWS = {
    2025: (date(2025, 3, 15), date(2025, 11, 5)),
    2024: (date(2024, 3, 15), date(2024, 11, 5)),
    2023: (date(2023, 3, 15), date(2023, 11, 5)),
}


def main():
    import sys
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    start, end = WINDOWS[year]
    dates = season.missing_dates(start, end)
    print(f"{len(dates)} dates from {start} to {end}", flush=True)
    print(season.backfill(dates), flush=True)


if __name__ == "__main__":
    main()
