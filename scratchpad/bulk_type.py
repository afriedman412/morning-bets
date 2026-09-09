"""IS THE BULK ARM A STARTER OR A BULLPEN GAME — and is he hooked early?

    venv/bin/python -m scratchpad.bulk_type

THE OPERATOR'S QUESTION, 2026-09-09, and it reframes TODO 15: an opener
means one of two things, a bullpen game or a real starter given a head
start. If the split is near even that matters a great deal, because the
starter half can be modelled with machinery that already works.

TYPE is read off the follower's OWN trailing record before that date, never
off the game being classified:

    REAL START = an order-0 appearance of >= REAL_START outs, so a run of
    opener starts does not classify a man as a starter.

  starter   >= 50% of his last WINDOW appearances are real starts
  swingman  2+ real starts but under 50%
  reliever  fewer than 2 real starts

THEN THE LENGTH QUESTION, paired within pitcher: for the starter-type bulk
arms, his outs and pitches in the bulk role against his own normal starts.
Paired, so talent and club cancel and the number means "how much shorter is
the SAME man behind an opener".

RESULT 2026-09-09. 31.3% starter / 20.2% swingman / 48.5% reliever, so a
real arm follows the opener 51.5% of the time. The starter type goes 13.00
outs against 16.15 in his own rotation turn — -3.15 outs and -15.56 pitches,
both about -10 sigma — and the two move together at 4.95 pitches per lost
out against his normal 5.3, so he is not pitching differently, HE IS BEING
PULLED EARLIER.

WHY THAT IS THE USEFUL FORM OF THE ANSWER. `PLAN-opener-bullpen.md` rules
out a leash fix because `OFFSET_CLAMP` tops out near +/-3.3 outs and an
opener needs about -12. True of the OPENER. The BULK ARM needs -3.15, which
is inside the clamp — the representation already in the engine can say it.

STILL POOLED over four seasons. Anything wired off this needs a four-fold
recount with the type read at each cut.
"""
from __future__ import annotations

from collections import defaultdict

from src import db
from src.context import store

#: Appearances of trailing history behind the type. Matches
#: `game.OPENER_ROLE_WINDOW` so the two role reads see the same span.
WINDOW = 30

#: Outs that make an order-0 appearance a REAL start rather than an opener's.
REAL_START = 12

#: Below this many appearances on file, the arm is not typed at all — a
#: guessed role would move the estimate in a definite wrong direction.
MIN_HISTORY = 5


def load():
    with store.connect() as c:
        st = [dict(r) for r in c.execute(
            "select game_id, date, team, player_name nm, appearance_order ao,"
            " batters, outs_recorded o, runs from mlb_stints"
            " order by date, game_id, appearance_order")]
    with db.connect() as c:
        pit = {(r["game_id"], r["player_name"]): r["pitches"]
               for r in c.execute(
                   "select game_id, player_name, pitches from mlb_pitching")}
    return st, pit


def role_index(st):
    log = defaultdict(list)
    for r in st:
        log[r["nm"]].append((r["date"],
                             r["ao"] == 0 and (r["o"] or 0) >= REAL_START))
    return log


def role(log, nm: str, date: str):
    w = [s for d, s in log[nm] if d < date][-WINDOW:]
    if len(w) < MIN_HISTORY:
        return None
    n = sum(w)
    if n < 2:
        return "reliever"
    return "starter" if n / len(w) >= 0.5 else "swingman"


def followers(st, log, chased_ok: bool):
    by_side = defaultdict(list)
    for r in st:
        by_side[(r["game_id"], r["team"])].append(r)
    types = defaultdict(list)
    for side in by_side.values():
        side.sort(key=lambda r: r["ao"])
        sp = next((r for r in side if r["ao"] == 0), None)
        nx = next((r for r in side if r["ao"] == 1), None)
        if not sp or not nx or (sp["o"] or 0) > 6:
            continue
        if not chased_ok and (sp["runs"] or 0) > 2:
            continue
        t = role(log, nx["nm"], nx["date"])
        if t:
            types[t].append(nx)
    return types


def _stat(lbl, v, unit):
    if not v:
        return
    m = sum(v) / len(v)
    var = sum((x - m) ** 2 for x in v) / (len(v) - 1)
    se = (var / len(v)) ** 0.5
    print(f"   {lbl:<26} {m:+6.2f} {unit}   se {se:.2f}   {m/se:+5.1f} sigma"
          f"   (n={len(v)})")


def main() -> None:
    st, pit = load()
    if not st:
        print("no stints — run `... sources.pbp --backfill --sync` first")
        return
    log = role_index(st)
    planned = None
    for tag, chased_ok in (("PLANNED opener (<=6 outs, <=2 runs)", False),
                           ("any short start (<=6 outs)", True)):
        types = followers(st, log, chased_ok)
        tot = sum(len(v) for v in types.values())
        print(f"\n{tag} — {tot:,} games with a typed follower")
        for t in ("starter", "swingman", "reliever"):
            v = types[t]
            if not v:
                continue
            o = sum(x["o"] or 0 for x in v) / len(v)
            p = [pit.get((x["game_id"], x["nm"])) for x in v]
            p = [x for x in p if x]
            long_ = sum(1 for x in v if (x["o"] or 0) >= 15) / len(v)
            print(f"   {t:<9} {len(v):>4} ({len(v)/tot:5.1%})   "
                  f"mean {o:5.2f} outs   "
                  f"{sum(p)/len(p) if p else 0:5.1f} pitches   "
                  f">=15 outs {long_:5.1%}")
        if not chased_ok:
            planned = types

    print("\nSTARTER-TYPE BULK ARMS vs THEIR OWN NORMAL STARTS (paired)")
    own = defaultdict(list)
    for r in st:
        if r["ao"] == 0 and (r["o"] or 0) >= REAL_START:
            own[r["nm"]].append(r)
    do, dp, n = [], [], 0
    for x in planned["starter"]:
        mine = [y for y in own[x["nm"]] if y["game_id"] != x["game_id"]]
        if len(mine) < 3:
            continue
        n += 1
        do.append((x["o"] or 0) - sum(y["o"] or 0 for y in mine) / len(mine))
        px = pit.get((x["game_id"], x["nm"]))
        pm = [v for v in (pit.get((y["game_id"], y["nm"])) for y in mine) if v]
        if px and pm:
            dp.append(px - sum(pm) / len(pm))
    print(f"   {n} bulk-role appearances by an arm with 3+ normal starts")
    _stat("outs, bulk minus normal", do, "outs")
    _stat("pitches, bulk minus normal", dp, "pit")


if __name__ == "__main__":
    main()
