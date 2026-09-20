"""THE BULK ARM'S CONTINUATION HAZARD, counted — TODO 15 part two.

    venv/bin/python -m scratchpad.bulk_continue

The shipped `relief.CONTINUE_INTENT` bucket 0 covers every arm entering in
innings 1-3, which pools a planned bulk man with a reliever cleaning up an
early blow-up. This counts the BULK cell on its own: appearance_order 1
behind a starter who went six outs or fewer. Train rows only, per rule 6.

READ `bulk_shape.py` BEFORE ACTING ON THIS. The gap below is real and it is
NOT the binding constraint on the follower's length — `RELIEF_MID_REMOVAL`
is. Shipping this table alone would be a null.
"""
from collections import defaultdict

from src.context import relief, store
from src.context.holdout import HOLDOUT

with store.connect() as c:
    rows = [dict(r) for r in c.execute(
        "select game_id, date, team, player_name nm, appearance_order ao,"
        " entry_inning ei, entry_outs eo, entry_margin em, outs_recorded o,"
        " runs, last_inning from mlb_stints order by date, game_id,"
        " appearance_order")]

by_side = defaultdict(list)
for r in rows:
    by_side[(r["game_id"], r["team"])].append(r)

# The BULK cell: appearance_order 1 behind a starter who went <= 6 outs.
bulk, normal = [], []
for side in by_side.values():
    side.sort(key=lambda r: r["ao"])
    sp = next((r for r in side if r["ao"] == 0), None)
    nx = next((r for r in side if r["ao"] == 1), None)
    if not sp or not nx:
        continue
    (bulk if (sp["o"] or 0) <= 6 else normal).append(nx)

print(f"bulk cell {len(bulk):,}   ordinary first reliever {len(normal):,}")
train = [r for r in bulk if r["date"] < HOLDOUT]
print(f"train rows (< {HOLDOUT}): {len(train):,}\n")

# Continuation: he entered with eo outs; did he pitch the NEXT inning too?
# Reconstruct from outs recorded and entry state, the way relief.tally does.
print("  entry_outs  n     P(continue past the inning he entered)"
      "     shipped intent (bucket 0)")
for eo in (0, 1, 2):
    g = [r for r in train if (r["eo"] or 0) == eo]
    if not g:
        continue
    # He continued if he recorded more outs than the inning he entered had
    # left for him.
    left = 3 - eo
    cont = [r for r in g if (r["o"] or 0) > left]
    ship = relief.CONTINUE_INTENT[(0, eo, False)]
    print(f"      {eo}     {len(g):>5}          {len(cont)/len(g):.4f}"
          f"                      {ship:.4f}")

print("\n  and how far he goes, in full innings past the entry inning")
for j in range(1, 6):
    g = [r for r in train if (r["eo"] or 0) == 0 and (r["o"] or 0) >= 3 * j]
    nxt = [r for r in g if (r["o"] or 0) >= 3 * (j + 1)]
    if len(g) < 30:
        break
    ship = relief.EXTRA_INTENT.get((0, j, False))
    print(f"    j={j}  n={len(g):>5}   P(one more) {len(nxt)/len(g):.4f}"
          f"    shipped {ship if ship is None else f'{ship:.4f}'}")

o = [r["o"] or 0 for r in train]
print(f"\n  bulk arm outs: mean {sum(o)/len(o):.2f}   "
      f"<=6 {sum(1 for x in o if x <= 6)/len(o):.1%}   "
      f">=15 {sum(1 for x in o if x >= 15)/len(o):.1%}")
n = [r["o"] or 0 for r in normal if r["date"] < HOLDOUT]
print(f"  ordinary 1st:  mean {sum(n)/len(n):.2f}   "
      f"<=6 {sum(1 for x in n if x <= 6)/len(n):.1%}   "
      f">=15 {sum(1 for x in n if x >= 15)/len(n):.1%}")
