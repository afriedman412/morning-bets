"""Dependency-free test runner.

pytest is not installed and the Makefile's `test` target has always pointed
at tooling that is not there. Rather than add a dependency for a handful of
assertions, this collects every `check_*` function from the test modules and
runs it.

    venv/bin/python -m tests.run          # everything
    venv/bin/python -m tests.run pure     # modules matching a substring

Tests here are OFFLINE by construction. Every network-backed adapter is
exercised through injected fixtures, because a suite that needs statsapi to
be reachable is a suite nobody runs.
"""
from __future__ import annotations

import importlib
import sys
import traceback

MODULES = ["tests.test_pure", "tests.test_regressions",
           "tests.test_sim"]


def main(argv: list[str]) -> int:
    want = argv[0] if argv else ""
    passed = failed = 0
    failures: list[tuple[str, str]] = []

    for mod_name in MODULES:
        if want and want not in mod_name:
            continue
        mod = importlib.import_module(mod_name)
        checks = sorted(
            (n, f) for n, f in vars(mod).items()
            if n.startswith("check_") and callable(f)
        )
        print(f"\n{mod_name}  ({len(checks)} checks)")
        for name, fn in checks:
            try:
                fn()
            except Exception as e:
                failed += 1
                failures.append((f"{mod_name}.{name}", traceback.format_exc()))
                print(f"  FAIL  {name[6:]}: {e}")
            else:
                passed += 1
                print(f"  ok    {name[6:]}")

    print(f"\n{passed} passed, {failed} failed")
    for name, tb in failures:
        print(f"\n--- {name} ---\n{tb}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
