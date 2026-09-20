"""RUN ANY FOUR-FOLD HARNESS WITH THE NO-BULLPEN BUG REINTRODUCED. TODO 20.

    venv/bin/python -m scratchpad.pen_ab <module> [args...]
    venv/bin/python -m scratchpad.pen_ab pxi_cv 10

The bug fixed in `rates._where` on 2026-09-09: `bullpens(lg, before=cut)`
without `season=` combined "this season" with "before a date two seasons
ago" and returned ZERO clubs for 2023-2025. An empty pen makes
`Side.current` hand every relief inning to the STARTER'S rates.

So the broken arm is exactly "an empty pens dict in the three past folds",
which is reproducible without reverting the fix. Same engine, same seeds,
same games as a normal run of the harness — the only difference is the
bug. That is what makes the pair a POSITIVE CONTROL rather than an
argument: run the harness both ways and the difference IS the bug's reach
into whatever that harness measures.

2026 is untouched in both arms and is the built-in negative control.
"""
from __future__ import annotations

import importlib
import sys

from src.context import scope
from src.context.sources import rates as rate_src

_REAL = rate_src.bullpens


def _broken(lg, season=None, before=None, **kw):
    now = scope.resolve(None)
    if season is None and before and before[:4].isdigit() \
            and int(before[:4]) < now:
        return {}
    return _REAL(lg, season=season, before=before, **kw)


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    rate_src.bullpens = _broken
    mod = importlib.import_module(f"scratchpad.{argv[0]}")
    print(f"  *** NO-BULLPEN BUG REINTRODUCED for folds before "
          f"{scope.resolve(None)} ***\n")
    mod.main(argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
