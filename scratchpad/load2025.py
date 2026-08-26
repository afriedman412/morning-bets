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

# 2025 opened in Tokyo on 18 March and the World Series ended 1 November.
# Dates outside the season return no games and cost one schedule call.
START, END = date(2025, 3, 15), date(2025, 11, 5)


def main():
    dates = season.missing_dates(START, END)
    print(f"{len(dates)} dates from {START} to {END}", flush=True)
    print(season.backfill(dates), flush=True)


if __name__ == "__main__":
    main()
