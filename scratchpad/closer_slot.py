"""THE CLOSER: can we name him, is he worth naming, and does news beat data?

    venv/bin/python -m scratchpad.closer_slot

Raised by the operator 2026-09-09: we know every club's closer going into
every game and ought to use it — he should almost never appear before the
ninth, so he should not be an ordinary member of the sampled pen. And, in a
follow-up that is the sharpest version of the claim: if he is hurt or
traded the NEWS knows immediately and the DATA does not.

Four stages, each of which can kill the next.

  1. NAME HIM FROM USAGE. The arm with the most 9th-inning-with-a-lead
     entries in the club's last `WINDOW` games. Prospective, no leakage.
  2. IS IT WORTH A FEED? Score a forward-looking ORACLE — the same count
     over the club's NEXT `WINDOW` games — on the same slots. A headline
     cannot know more than what actually happens, so the backward-to-oracle
     gap is the CEILING on any news source, scraped or otherwise.
  3. POSITIVE-CONTROL THE NULL, because a pooled number hides the
     population the operator is pointing at. Restrict to slots where the
     backward and forward answers DISAGREE — that is a transition, and it
     is the only place a feed can help.
  4. THE STALE CASE. Score by how long the named man has been idle, and
     price a fully-offline repair: when he has not appeared in `STALE`
     days, step down to the next arm on the same count.

WHAT THIS IS NOT. It does not measure whether reserving him for the ninth
IMPROVES the simulation — that is the battery's job around a wired change.
It measures whether the input exists and how good it can get.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as _date

from src.context import store

#: Club-games of history behind the naming. 25 is about a month, long
#: enough to out-vote a single fill-in save and short enough to notice a
#: change before the ten-day gate below fires.
WINDOW = 25

#: Days idle after which the named man is treated as gone. The cliff is
#: between the 4-9 and 10+ buckets in `report`, not fitted to anything.
STALE = 10

_Q = """
  select game_id, date, team, player_name nm, appearance_order ao,
         entry_inning ei, entry_margin em
  from mlb_stints order by date, game_id, appearance_order
"""


def _days(a: str, b: str) -> int:
    return (_date(*(int(x) for x in a.split("-")))
            - _date(*(int(x) for x in b.split("-")))).days


def load(conn=None):
    def _run(c):
        return [dict(r) for r in c.execute(_Q)]
    if conn is not None:
        rows = _run(conn)
    else:
        with store.connect() as c:
            rows = _run(c)
    by_side = defaultdict(list)
    for r in rows:
        if r["team"]:
            by_side[(r["game_id"], r["team"].upper())].append(r)
    games = defaultdict(list)
    for (gid, team), side in by_side.items():
        side.sort(key=lambda r: r["ao"])
        games[team].append((side[0]["date"], gid, side))
    for t in games:
        games[t].sort()
    seen = defaultdict(list)
    for r in rows:
        if r["ao"] > 0:
            seen[r["nm"]].append(r["date"])
    return games, {k: sorted(set(v)) for k, v in seen.items()}


def ranked(window) -> list[str]:
    """Arms by 9th-inning-with-a-lead entries over `window`, best first."""
    tally = defaultdict(int)
    for _, _, ps in window:
        for r in ps:
            if r["ao"] > 0 and r["ei"] == 9 and (r["em"] or 0) > 0:
                tally[r["nm"]] += 1
    return [n for n, _ in sorted(tally.items(), key=lambda kv: -kv[1])]


def _last_before(ds: list[str], date: str):
    import bisect
    i = bisect.bisect_left(ds, date)
    return ds[i - 1] if i else None


def report(games, seen) -> None:
    slots = back = fwd = fixed = 0
    differ = [0, 0, 0]
    agree = [0, 0, 0]
    buckets = defaultdict(lambda: [0, 0])
    rest = [0, 0]
    tired = [0, 0]

    for team, gs in games.items():
        for i, (date, gid, side) in enumerate(gs):
            ninth = [r for r in side if r["ao"] > 0 and r["ei"] == 9
                     and 1 <= (r["em"] or 0) <= 3]
            if not ninth:
                continue
            order = ranked(gs[max(0, i - WINDOW):i])
            fwd_order = ranked(gs[i + 1:i + 1 + WINDOW])
            if not order or not fwd_order:
                continue
            b, f = order[0], fwd_order[0]
            names = {r["nm"] for r in ninth}
            slots += 1
            back += b in names
            fwd += f in names
            e = agree if b == f else differ
            e[0] += 1
            e[1] += b in names
            e[2] += f in names

            lb = _last_before(seen.get(b) or [], date)
            gap = _days(date, lb) if lb else 99
            key = ("0-3" if gap <= 3 else "4-9" if gap <= 9 else "10+")
            buckets[key][0] += 1
            buckets[key][1] += b in names

            pick = b
            if gap >= STALE:
                for n in order[1:]:
                    ln = _last_before(seen.get(n) or [], date)
                    if ln and _days(date, ln) < STALE:
                        pick = n
                        break
            fixed += pick in names

            if i:
                prev = gs[i - 1][2]
                t = tired if any(r["nm"] == b and r["ao"] > 0 for r in prev) \
                    else rest
                t[0] += 1
                t[1] += b in names

    print(f"\n{slots:,} save slots (a 9th inning entered with a 1-3 lead)\n")
    print("  CAN WE NAME HIM, AND IS A FEED WORTH IT")
    print(f"    backward, last {WINDOW} games      {back / slots:6.1%}")
    print(f"    ORACLE, next {WINDOW} games        {fwd / slots:6.1%}"
          f"   <- the ceiling on any news source")
    print("\n  POSITIVE CONTROL — only the transitions can move")
    for lbl, e in (("they agree", agree), ("they DISAGREE", differ)):
        n, hb, hf = e
        print(f"    {lbl:<16} n={n:>5}   backward {hb/n:6.1%}"
              f"   oracle {hf/n:6.1%}")
    print("\n  HOW STALE IS THE NAMED MAN")
    for k in ("0-3", "4-9", "10+"):
        n, h = buckets[k]
        if n:
            print(f"    {k:>4} days  n={n:>5} ({n/slots:5.1%})"
                  f"   takes it {h/n:6.1%}")
    print(f"\n    baseline                  {back/slots:6.1%}")
    print(f"    stale-fallback at {STALE} days {fixed/slots:6.1%}"
          f"   {(fixed-back)/slots:+.1%}   — offline, no feed")
    print("\n  AVAILABILITY — did he pitch in the club's LAST game?")
    for lbl, t in (("rested", rest), ("pitched yesterday", tired)):
        n, h = t
        print(f"    {lbl:<20} n={n:>5}   takes the slot {h/max(n,1):6.1%}")
    a = rest[1] / max(rest[0], 1)
    b_ = tired[1] / max(tired[0], 1)
    se = (a * (1 - a) / max(rest[0], 1) + b_ * (1 - b_) / max(tired[0], 1)) ** .5
    print(f"    gap {a - b_:+.1%}   se {se:.1%}   {(a - b_)/se:+.1f} sigma")


def main() -> None:
    games, seen = load()
    if not games:
        print("no stints — run `... sources.pbp --backfill --sync` first")
        return
    report(games, seen)


if __name__ == "__main__":
    main()
