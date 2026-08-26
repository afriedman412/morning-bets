"""Dependency-free test runner, one FORKED PROCESS PER CHECK.

pytest is not installed and the Makefile's `test` target has always pointed
at tooling that is not there. Rather than add a dependency for a handful of
assertions, this collects every `check_*` function from the test modules and
runs it.

    venv/bin/python -m tests.run          # everything
    venv/bin/python -m tests.run pure     # modules matching a substring
    venv/bin/python -m tests.run --serial # one process, in order

WHY IT IS PARALLEL NOW. Deleting the one-sided engine on 2026-08-25 made
every check that needs innings run a WHOLE GAME — both sides, a bullpen,
nine innings and extras — which is about 20x the work of the start-level
loop it replaced. Serially the suite went from ~70s to ~95s, and a suite
nobody wants to wait for is a suite that stops being run before a commit.

FORK, NOT SPAWN, and this is the same trap the fit workers hit. A SPAWNED
child re-imports every module at DEFAULT global state, so `sim.USE_TTO` and
friends silently revert — over there it made a parameter sweep return a flat
surface that read as "this does not matter"; here it would make every check
that flips a flag test the shipped default instead. `check_worker_state_
crosses_the_fork` pins it for `fitf5`; the same rule is why this imports
every module in the PARENT and then forks.

FORKING PER CHECK RATHER THAN PER MODULE IS THE POINT, not just more
workers. Roughly forty checks here mutate a module global — `sim.USE_TTO`,
`sim._LEASH`, `game.USE_MEASURED_RELIEF_HOOK` — and restore it in a
`finally`. A forked child gets its own copy-on-write memory, so that
restoration stops being load-bearing: a check that leaks a global can no
longer contaminate the next one. Isolation is strictly better than the
serial loop, not a compromise for speed.

WHAT PARALLELISM WOULD CHANGE IF SOMETHING WERE ALREADY WRONG: a check that
only passed because an EARLIER check left a global set will now fail. That
is a real finding and should be read as one, not worked around by pinning it
back to serial.

Tests here are OFFLINE by construction. Every network-backed adapter is
exercised through injected fixtures, because a suite that needs statsapi to
be reachable is a suite nobody runs. That is also what makes forking safe —
there is no socket or open cursor to inherit.
"""
from __future__ import annotations

import concurrent.futures as cf
import importlib
import multiprocessing as mp
import os
import sys
import time
import traceback

MODULES = ["tests.test_pure", "tests.test_regressions",
           "tests.test_sim", "tests.test_fitf5",
           "tests.test_game", "tests.test_sources", "tests.test_pbp",
           "tests.test_advance",
           "tests.test_boundary", "tests.test_deploy", "tests.test_relief",
           "tests.test_wiring",
           "tests.test_inherit", "tests.test_ladder", "tests.test_leash",
           "tests.test_order",
           "tests.test_scope",
           "tests.test_stabilise", "tests.test_tto",
           "tests.test_weather",
           "tests.test_store"]


def _run_one(job):
    """Run one check in this process. -> (ok, one-line reason, traceback).

    Looks the function up by name rather than receiving it, because a forked
    child already HAS the module — the parent imported it before forking —
    and a function object would have to be pickled for no reason.
    """
    mod_name, check_name = job
    fn = getattr(sys.modules[mod_name], check_name)
    t = time.time()
    try:
        fn()
    except Exception as e:
        return (False, f"{type(e).__name__}: {e}"[:200],
                traceback.format_exc(), time.time() - t)
    return True, "", "", time.time() - t


def _collect(want: str) -> list[tuple[str, str]]:
    """[(module, check)] in declaration order, modules imported as we go."""
    jobs = []
    for mod_name in MODULES:
        if want and want not in mod_name:
            continue
        mod = importlib.import_module(mod_name)
        jobs += [(mod_name, n) for n, f in sorted(vars(mod).items())
                 if n.startswith("check_") and callable(f)]
    return jobs


def main(argv: list[str]) -> int:
    flags = {a for a in argv if a.startswith("-")}
    rest = [a for a in argv if not a.startswith("-")]
    want = rest[0] if rest else ""

    t0 = time.time()
    jobs = _collect(want)
    counts: dict[str, int] = {}
    for m, _ in jobs:
        counts[m] = counts.get(m, 0) + 1

    workers = 1 if {"--serial", "-1"} & flags else max(
        1, min(len(jobs), os.cpu_count() or 4))

    if workers == 1:
        results = [_run_one(j) for j in jobs]
    else:
        # `Executor.map` yields IN SUBMISSION ORDER, so the printed output
        # is identical to the serial run — a parallel suite whose output
        # reshuffles every time is one nobody can diff against yesterday's.
        #
        # NOT `multiprocessing.Pool`. Its workers are DAEMONIC and a daemon
        # may not have children, which two checks here need: `fitf5.losses`
        # forks across salts, and `check_worker_state_crosses_the_fork`
        # exists precisely to run it. `ProcessPoolExecutor` leaves its
        # workers non-daemonic, so a check may still fan out.
        with cf.ProcessPoolExecutor(
                max_workers=workers,
                mp_context=mp.get_context("fork")) as pool:
            results = list(pool.map(_run_one, jobs, chunksize=1))

    passed = failed = 0
    failures: list[tuple[str, str]] = []
    seen = None
    for (mod_name, name), (ok, why, tb, _) in zip(jobs, results):
        if mod_name != seen:
            seen = mod_name
            print(f"\n{mod_name}  ({counts[mod_name]} checks)")
        if ok:
            passed += 1
            print(f"  ok    {name[6:]}")
        else:
            failed += 1
            failures.append((f"{mod_name}.{name}", tb))
            print(f"  FAIL  {name[6:]}: {why}")

    print(f"\n{passed} passed, {failed} failed  "
          f"({time.time() - t0:.1f}s wall, {workers} worker"
          f"{'' if workers == 1 else 's'}, "
          f"{sum(r[3] for r in results):.0f}s of work)")
    # THE TAIL IS THE FLOOR. Wall time cannot go below the slowest single
    # check however many cores are thrown at it, so name the ones that set
    # it rather than adding workers and wondering why nothing moved.
    slow = sorted(zip(jobs, results), key=lambda x: -x[1][3])[:5]
    if slow and slow[0][1][3] > 1.0:
        print("  slowest: " + ", ".join(
            f"{n[6:]} {r[3]:.1f}s" for (_, n), r in slow))
    for name, tb in failures:
        print(f"\n--- {name} ---\n{tb}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
