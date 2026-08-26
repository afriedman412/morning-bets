"""Re-run the CLV/disagreement tests on the CURRENT engine, forked by date.

    venv/bin/python -m scratchpad.remeasure [stat] [n_sims] [start] [end]

WHY THIS EXISTS. Every recorded statement about what our disagreements with
Kalshi are worth — "blend weight 0.00, t = -0.15 over 1,220 settled
markets", "within 5 cents the simulator is a shade better (0.1351 against
0.1379) and at 10+ it is much worse (0.2556 against 0.2197)" — was measured
on `sim.simulate`, the one-sided loop deleted on 2026-08-25. That engine had
no bullpen after the hook, no margin term and no opposing offence. The
numbers are quoted by `quote.py`, by `price.py` and all over the notes, and
none of them has been re-established.

FORKED OVER DATES, NOT DRAWS. `versus_market.collect` already caches one
simulated game per matchup per date, so a date is a natural unit of work and
the dates are independent. Fork rather than spawn, for the reason recorded
against the fit workers: a spawned child re-imports at DEFAULT global state,
so `sim.USE_LEASH` and every other flag silently reverts and the run
measures the shipped defaults instead of whatever is set here.

WHAT A GOOD RESULT LOOKS LIKE, so it is not read backwards: NOT "our Brier
beats the market's". That would be extraordinary and would mean something is
wrong. The question is narrower — does blending our gap into the price
improve on the price alone, and is the best blend weight above zero.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import multiprocessing as mp
import os
import pathlib
import sys
import time
from datetime import date, timedelta

OUT_DIR = pathlib.Path("scratchpad/sims")


def _dates(start: str, end: str) -> list[str]:
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return [(a + timedelta(days=i)).isoformat()
            for i in range((b - a).days + 1)]


def _one(args):
    """One date's rows. Runs in a forked child."""
    d, stat, n_sims = args
    from src.context import versus_market as vm
    try:
        return vm.collect([d], stat=stat, n_sims=n_sims, verbose=False)
    except Exception as e:
        print(f"  {d}: FAILED {type(e).__name__}: {e}", flush=True)
        return []


def main(argv: list[str]) -> None:
    from src.context import versus_market as vm
    # THE ROWS ARE KEPT so the report can be re-run without re-simulating.
    # This is not convenience: `report` crashed on the first full-month run
    # (an OverflowError in the binomial tail, which only bites once a band
    # holds ~1,000 rows) and 151s of simulation went with it.
    if argv and argv[0].endswith(".json"):
        vm.report(json.loads(pathlib.Path(argv[0]).read_text()))
        return

    stat = argv[0] if argv else "k"
    n_sims = int(argv[1]) if len(argv) > 1 else 1500
    start = argv[2] if len(argv) > 2 else "2026-08-01"
    end = argv[3] if len(argv) > 3 else "2026-08-25"

    from src.context import calibrate, sim
    ds = _dates(start, end)
    workers = max(1, min(len(ds), (os.cpu_count() or 4) - 1))
    print(f"{stat} props, {len(ds)} dates {ds[0]}..{ds[-1]}, "
          f"n_sims={n_sims}, {workers} workers")
    print(f"engine: game.simulate_game   leash "
          f"{'ON' if sim.USE_LEASH else 'off'}   park "
          f"{'ON' if calibrate.USE_PARK else 'off'}   home/road "
          f"{'ON' if calibrate.USE_HOME_ROAD else 'off'}\n", flush=True)

    t0 = time.time()
    rows: list[dict] = []
    done = 0
    with cf.ProcessPoolExecutor(
            max_workers=workers, mp_context=mp.get_context("fork")) as pool:
        for got in pool.map(_one, [(d, stat, n_sims) for d in ds]):
            rows += got
            done += 1
            el = time.time() - t0
            sys.stderr.write(
                f"\r  [{'#' * int(24 * done / len(ds)):<24}] "
                f"{done}/{len(ds)} dates, {len(rows)} markets, "
                f"{el:3.0f}s elapsed, {el / done * (len(ds) - done):3.0f}s left")
            sys.stderr.flush()
    sys.stderr.write("\r" + " " * 100 + "\r")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"clv_{stat}_{start}_{end}.json"
    path.write_text(json.dumps(rows))
    print(f"collected {len(rows)} markets in {time.time() - t0:.0f}s "
          f"-> {path}")
    vm.report(rows)


if __name__ == "__main__":
    main(sys.argv[1:])
