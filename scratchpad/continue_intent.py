"""THE BETWEEN-INNINGS CONTINUATION HAZARD, RE-COUNTED — TODO 15 part two.

    venv/bin/python -m scratchpad.continue_intent

`bulk_continue.py` said the shipped `relief.CONTINUE_INTENT` bucket 0 is
short for the arm behind an opener (0.7821 against 0.7569 on a clean entry,
0.5000 against 0.3788 by the fourth extra inning). Before shipping a bulk
cell, rule 11: the two numbers are counted with DIFFERENT conventions, so
check they measure the same thing first.

THREE THINGS SEPARATED HERE.

  1. TRAIN vs ALL. `CONTINUE_INTENT` and `EXTRA_INTENT` were counted over
     every stint in the table; `MID_INTENT` was counted on rows before
     `HOLDOUT`. Recount both on train rows so the comparison is clean.

  2. THE DENOMINATOR, and this is the specification question. `relief.tally`
     asks "he PITCHED IN inning entry+j; did he pitch in entry+j+1" — a
     denominator that includes arms yanked mid-inning during entry+j and
     scores them as non-continuations. The engine asks the question only of
     an arm who has just recorded the third out, and charges mid-inning
     removal separately through `mid_removal`. So the shipped table charges
     removal TWICE and must read low, worst where an arm faces the most
     batters, which is exactly the bulk cell. `finished` below restricts the
     denominator to outs_recorded >= (3 - entry_outs) + 3j, i.e. he actually
     completed that inning.

  3. BULK vs THE REST OF BUCKET 0, under whichever convention survives (1)
     and (2), with the standard error stated before the verdict.

Also prints j past the shipped cap of 4, which is where `bulk_continue`
found the widest gap.
"""
import math
import sys
from collections import defaultdict

from src.context import relief, store
from src.context.holdout import HOLDOUT

ROWS = """
    select game_id, date, team, appearance_order ao, entry_inning ei,
           entry_outs eo, entry_margin em, outs_recorded o, last_inning li
    from mlb_stints order by date, game_id, appearance_order
"""


def load() -> tuple[list[dict], set]:
    """Every stint, and the (game, team) keys whose ao-1 arm is a bulk man.

    Each row also gets `last_pitched`: the last inning ANY arm on that side
    worked. An arm who finished it had no chance to come back out — the game
    was over — and the engine never asks the question there either.
    """
    with store.connect() as c:
        rows = [dict(r) for r in c.execute(ROWS)]
    by_side = defaultdict(list)
    for r in rows:
        by_side[(r["game_id"], r["team"])].append(r)
    bulk = set()
    for key, side in by_side.items():
        side.sort(key=lambda r: r["ao"])
        sp = next((r for r in side if r["ao"] == 0), None)
        nx = next((r for r in side if r["ao"] == 1), None)
        if sp and nx and (sp["o"] or 0) <= 6:
            bulk.add((key[0], key[1], 1))
        end = max((r["li"] or 0) for r in side)
        for r in side:
            r["last_pitched"] = end
    return [r for r in rows if r["ao"] > 0], bulk


def se(p: float, n: int) -> float:
    return math.sqrt(max(p * (1 - p), 1e-9) / max(n, 1))


def rate(g: list[dict], j: int, finished: bool,
         uncensored: bool = False) -> tuple[float, int]:
    """P(he comes back out for inning entry+j+1), over one of three denominators.

    `finished` False is `relief.tally`'s convention — he pitched in inning
    entry+j. True is the engine's — he recorded the third out of it.
    `uncensored` additionally drops the arms whose side never pitched inning
    entry+j+1, i.e. the game ended under them.
    """
    if finished:
        d = [r for r in g
             if (r["o"] or 0) >= (3 - (r["eo"] or 0)) + 3 * j]
    else:
        d = [r for r in g if (r["li"] or 0) - (r["ei"] or 0) >= j]
    if uncensored:
        d = [r for r in d if r["last_pitched"] > (r["ei"] or 0) + j]
    if not d:
        return float("nan"), 0
    c = sum(1 for r in d if (r["li"] or 0) - (r["ei"] or 0) > j)
    return c / len(d), len(d)


def blow(r: dict) -> bool:
    return abs(r["em"] or 0) >= 4


def head(t: str) -> None:
    print(f"\n{'=' * 72}\n{t}\n{'=' * 72}")


def main() -> None:
    rows, bulk = load()
    train = [r for r in rows if r["date"] < HOLDOUT]
    print(f"{len(rows):,} relief stints, {len(train):,} before {HOLDOUT}")

    head("1+2. THE ENTRY-INNING CELL, shipped against three recounts")
    print("  shipped was counted over ALL rows on the PITCHED-IN denominator")
    print("  cell            shipped   train/pitched-in    train/finished"
          "      +uncensored        n")
    for e in (0, 1, 2):
        for k in (0, 1, 2):
            for b in (False, True):
                g = [r for r in train
                     if relief.intent_bucket(r["ei"]) == e
                     and (r["eo"] or 0) == k and blow(r) == b]
                p_in, n_in = rate(g, 0, False)
                p_fi, n_fi = rate(g, 0, True)
                p_un, n_un = rate(g, 0, True, True)
                ship = relief.CONTINUE_INTENT[(e, k, b)]
                print(f"  E{e} k={k} {'blow ' if b else 'close'}   "
                      f"{ship:.4f}   {p_in:.4f} ({n_in:>5})   "
                      f"{p_fi:.4f} ({n_fi:>5})   "
                      f"{p_un:.4f} +-{se(p_un, n_un):.4f}   {n_un:>5}")

    head("EXTRA cells, same columns, and past the shipped cap")
    for e in (0, 1, 2):
        for b in (False, True):
            for j in range(1, 9):
                g = [r for r in train
                     if relief.intent_bucket(r["ei"]) == e and blow(r) == b]
                p_in, n_in = rate(g, j, False)
                p_fi, n_fi = rate(g, j, True)
                p_un, n_un = rate(g, j, True, True)
                if n_un < 30 and n_in < 30:
                    break
                ship = relief.EXTRA_INTENT.get((e, j, b))
                s = "  -   " if ship is None else f"{ship:.4f}"
                print(f"  E{e} j={j} {'blow ' if b else 'close'}   {s}   "
                      f"{p_in:.4f} ({n_in:>5})   {p_fi:.4f} ({n_fi:>5})   "
                      f"{p_un:.4f} +-{se(p_un, n_un):.4f}   {n_un:>5}")
            print()

    head("3. BULK against the rest of bucket 0, finished + uncensored")
    b0 = [r for r in train if relief.intent_bucket(r["ei"]) == 0]
    is_bulk = [r for r in b0 if (r["game_id"], r["team"], r["ao"]) in bulk]
    rest = [r for r in b0 if (r["game_id"], r["team"], r["ao"]) not in bulk]
    print(f"  bucket 0 train rows {len(b0):,} = bulk {len(is_bulk):,}"
          f" + rest {len(rest):,}")
    print("\n   j    bulk            rest            diff (se)")
    for j in range(0, 7):
        pb, nb = rate(is_bulk, j, True, True)
        pr, nr = rate(rest, j, True, True)
        if nb < 30 or nr < 30:
            break
        d = pb - pr
        s = math.sqrt(se(pb, nb) ** 2 + se(pr, nr) ** 2)
        print(f"  j={j}  {pb:.4f} ({nb:>5})  {pr:.4f} ({nr:>5})  "
              f"{d:+.4f} +-{s:.4f}   {d / s:+.1f} sd")


if __name__ == "__main__":
    sys.exit(main())
