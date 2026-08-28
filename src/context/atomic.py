"""Atomic cache writes, so two processes cannot disagree about the data.

WHY THIS EXISTS, and it is a live-board bug rather than a tidiness one.
Every `sources/*._cached` helper wrote its cache with `Path.write_text`,
which TRUNCATES and then writes. A second process reading the same file
mid-write observes a partial one. That does not crash: `_cached` catches
`JSONDecodeError` and falls through to a live REFETCH, so the symptom is
two concurrent runs silently using DIFFERENT DATA for the same game.

Measured on 2026-08-28. Pricing a slate while `src.context.price` was
running produced a different projected lineup and moved a moneyline by 1.2
points (SF 0.551 against 0.563) — reproducible only in that it was
irreproducible, which is the worst failure mode a pricing tool has. A
standalone repro puts 33.8% of concurrent reads on a torn file with
`write_text` and 0 of 105,020 with `os.replace`.

`os.replace` is atomic on POSIX when the temp file is on the SAME
filesystem, so the temp is written beside the target rather than in /tmp.
The pid in the temp name keeps two writers from colliding on it.
"""
from __future__ import annotations

import os
from pathlib import Path


def write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    """Write `text` to `path` so readers see the old file or the new one.

    Never a partial one, which is the whole point. Drop-in for
    `Path(path).write_text(text)`.
    """
    p = Path(path)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, p)
    except BaseException:
        # Leaving a stray temp behind would be read by nobody — the cache is
        # keyed by exact filename — but it would accumulate across failed
        # runs, so clear it and re-raise the original failure untouched.
        tmp.unlink(missing_ok=True)
        raise
