"""Cache writes must be atomic, or two runs price the same game differently.

The bug these guard is not a crash. `sources/*._cached` CATCHES
`JSONDecodeError` and falls through to a live refetch, so a torn read turns
into two concurrent processes silently using different data — measured on a
live board on 2026-08-28, worth 1.2 points on a moneyline.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import tempfile
import time
from pathlib import Path

from src.context import atomic

BLOB = json.dumps({"lineup": [f"Player Number {i}" for i in range(400)]})


def check_atomic_write_replaces_content():
    """The plain case still has to work."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cache.json"
        atomic.write_text(p, "first")
        assert p.read_text() == "first"
        atomic.write_text(p, "second")
        assert p.read_text() == "second"


def check_atomic_write_leaves_no_temp_files():
    """A stray temp per write would accumulate across every cached fetch."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cache.json"
        for _ in range(5):
            atomic.write_text(p, BLOB)
        assert [x.name for x in Path(d).iterdir()] == ["cache.json"]


def check_atomic_write_cleans_up_after_a_failed_write():
    """An unserialisable payload must not leave a temp behind."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cache.json"
        try:
            atomic.write_text(p, None)   # TypeError inside write_text
        except TypeError:
            pass
        assert list(Path(d).iterdir()) == []


def _writer(path, stop):
    while not stop.value:
        atomic.write_text(path, BLOB)


def _reader(path, stop, torn):
    while not stop.value:
        try:
            json.loads(Path(path).read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            with torn.get_lock():
                torn.value += 1


def check_concurrent_readers_never_see_a_partial_cache():
    """THE CHECK THAT MATTERS, and it is the one that fails on write_text.

    Verified by mutation: swapping `atomic.write_text` for
    `Path.write_text` in `_writer` puts roughly a third of concurrent reads
    on a torn file and this fails immediately.
    """
    ctx = mp.get_context("fork")
    with tempfile.TemporaryDirectory() as d:
        p = str(Path(d) / "cache.json")
        atomic.write_text(p, BLOB)
        stop, torn = ctx.Value("i", 0), ctx.Value("i", 0)
        procs = [ctx.Process(target=_writer, args=(p, stop))]
        procs += [ctx.Process(target=_reader, args=(p, stop, torn))
                  for _ in range(3)]
        for x in procs:
            x.start()
        time.sleep(1.5)
        stop.value = 1
        for x in procs:
            x.join(timeout=10)
        assert torn.value == 0, f"{torn.value} torn reads"


def check_every_cache_writer_goes_through_atomic():
    """WIRING, not behaviour — the fix is worthless at 13 of 14 sites.

    Every measurement module was tested and none of the wiring was, which is
    what `scratchpad/mutate.py` found five times over. A new `write_text`
    call on a cache path would silently reintroduce the race.
    """
    root = Path(__file__).resolve().parents[1] / "src" / "context"
    offenders = []
    for py in list(root.glob("*.py")) + list(root.glob("sources/*.py")):
        if py.name == "atomic.py":
            continue
        for i, line in enumerate(py.read_text().splitlines(), 1):
            s = line.strip()
            if ".write_text(" in s and not s.startswith("#") \
                    and "atomic.write_text(" not in s:
                offenders.append(f"{py.name}:{i}")
    assert not offenders, f"raw write_text on a cache path: {offenders}"
