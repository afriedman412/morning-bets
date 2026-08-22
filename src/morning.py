"""The whole morning, as one idempotent command.

`make morning` and the scheduled run both call this, so it does not matter
which one fires first — whatever is already done is skipped:

    ingest   videos already processed are recorded in sent.json
    grade    --if-needed, no-op when nothing is PENDING
    panel    --if-needed, no-op when the day already has a card
    email    --if-needed, no-op when the digest was already sent

Rebuilding a card the user has already bet is the failure this guards
against: it changes the advice after the fact and costs a full persona
pass. Same for mailing the same digest twice.

Every step is wrapped, because a digest built from whatever landed beats
no digest at all — one channel 403ing should not take the morning down.

    venv/bin/python -m src.morning
    venv/bin/python -m src.morning --force   # rebuild card, resend digest
"""
from __future__ import annotations

import sys
from datetime import date

from src import db


def _step(name: str, fn) -> bool:
    print(f"\n=== {name} ===")
    try:
        fn()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  !! {name} failed: {type(e).__name__}: {e}")
        return False


def run(date_str: str | None = None, force: bool = False) -> int:
    db.init()
    d = date_str or date.today().isoformat()
    print(f"Morning run for {d}" + (" (forced)" if force else ""))

    from src import emailer, grading, main, panel

    _step("ingest", lambda: main.run())

    def _grade():
        # Yesterday is what needs grading; today's games have not finished.
        from datetime import timedelta
        y = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
        if not force and grading.pending_count(y) == 0:
            print(f"  {y} already graded — skipping.")
        else:
            grading.grade(y)
    _step("grade", _grade)

    def _panel():
        if not force and panel.card_exists(d):
            print(f"  {d} already has a card — skipping.")
        else:
            panel.run(d)
    _step("panel", _panel)

    ok = _step(
        "email",
        lambda: emailer.run(d, if_needed=not force),
    )
    print("\nMorning run complete.")
    return 0 if ok else 1


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(run(args[0] if args else None, force="--force" in sys.argv))
