"""How fast does ground-ball share stabilise? `stabilise.py`'s method.

    venv/bin/python -m scratchpad.gb_stabilise

Odd/even GAMES per player, correlate the two half-rates, Spearman-Brown
up to a full half-pair, k = n(1-r)/r — the identical construction the
four shipped shrinkage constants were measured with, so the number is
comparable to them rather than to a folklore figure.
"""
from __future__ import annotations

import statistics as st

from src.context import store

MIN_PER_HALF = 20


def _corr(pairs):
    xs = [a for a, _ in pairs]
    ys = [b for _, b in pairs]
    mx, my = st.mean(xs), st.mean(ys)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / \
        (len(xs) * sx * sy)


def main():
    for role in ("bat", "pit"):
        rows: dict = {}
        with store.connect(attach=False) as c:
            for r in c.execute(
                    "select name, date, gb, bip from mlb_batted "
                    "where role = ? order by name, date, game_id", (role,)):
                rows.setdefault(r["name"], []).append((r["gb"], r["bip"]))
        pairs, ns = [], []
        for games in rows.values():
            a = [g for i, g in enumerate(games) if i % 2 == 0]
            b = [g for i, g in enumerate(games) if i % 2 == 1]
            na, nb = sum(n for _, n in a), sum(n for _, n in b)
            if na < MIN_PER_HALF or nb < MIN_PER_HALF:
                continue
            pairs.append((sum(g for g, _ in a) / na,
                          sum(g for g, _ in b) / nb))
            ns.append(2.0 / (1.0 / na + 1.0 / nb))
        r_half = _corr(pairs)
        full = 2 * r_half / (1 + r_half)
        n = st.mean(ns)
        k = n * (1 - full) / full
        print(f"  {role}: {len(pairs):,} players  r_half {r_half:.3f}  "
              f"r_full {full:.3f}  n/half {n:.0f}  -> k = {k:.1f}")


if __name__ == "__main__":
    main()
