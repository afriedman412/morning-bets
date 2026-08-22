"""Run independent I/O-bound calls concurrently, then apply results serially.

Every loop this replaces has the same shape: a slow call (an LLM turn, a
network fetch) followed by a fast write (sqlite, sent.json, a print). The
writes are what make concurrency dangerous here —

  • persist_bets() reads its dedup set on one connection and inserts on
    another, so two threads inside it can both miss the same duplicate;
  • process() rewrites the whole of sent.json per video, so two threads
    lose each other's entries and the dropped video is re-ingested (and
    re-paid for) the next morning.

So the rule is: workers do the slow call and return plain data. Nothing
else. The caller writes, prints, and persists after the join, on one
thread. gather() exists to make that the path of least resistance.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def gather(
    fn: Callable[[T], R],
    items: Iterable[T],
    workers: int | None = None,
) -> list[tuple[T, R | None, Exception | None]]:
    """Call fn on each item concurrently; yield (item, result, error) tuples
    in INPUT order, never completion order.

    Input order is load-bearing, not cosmetic. build_pool() appends to a
    candidate's `nominators` list as it walks the nominations, and that list
    is rendered into the round-1 debate prompt — assembling results as they
    complete would reorder that string run-to-run and make a given day's
    debate irreproducible.

    Exceptions are returned, not raised. Every loop this replaces caught
    per-item and continued, because one persona's 500 must not cost the
    whole round; a bare .result() would re-raise instead, and morning.py's
    step wrapper would turn that into "no card today".
    """
    items = list(items)
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=workers or len(items)) as pool:
        futures = [pool.submit(fn, item) for item in items]
        out: list[tuple[T, R | None, Exception | None]] = []
        for item, future in zip(items, futures):
            try:
                out.append((item, future.result(), None))
            except Exception as e:  # noqa: BLE001 — reported, not swallowed
                out.append((item, None, e))
    return out
