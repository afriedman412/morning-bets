"""Turn a printed board into JSON the HTML renderer can read.

    venv/bin/python -m scratchpad.board_json 2026-09-09

Reads `bets/<date>_board.txt`, writes `bets/<date>_board.json`.

WHY A PARSER AND NOT A SECOND CALL TO `build()`: the text board is the
artefact of record and it costs an hour of simulation at 20,000 draws.
Re-running the engine to render the same numbers a second way would let
the page and the .txt drift apart on seed alone — two boards, two answers,
and no way to tell which one was fired on. The .txt is the source of truth
and this only reshapes it.

The one derived quantity added here is the K-8.5-and-up tail bump, because
it belongs to interpretation rather than to the engine: BETTING.md records
that the model prices a high-K over at about 78% of its true probability,
so two points go on those overs before anything is compared to a market.
Everything else is read straight off the line.
"""
from __future__ import annotations

import json
import re
import sys

ROW = re.compile(r"^  (.+?)\s+([+-]\d+)\s*/\s*([+-]\d+)\s+(\S+)\s{0,3}(.*)$")
HEAD = re.compile(
    r"^(\w{2,3}) @ (\w{2,3})\s+(.+?) v (.+?)\s+\((.+?), mean ([\d.]+)\)")
DECLINE = re.compile(r"^  (\w{2,3} @ \w{2,3})\s+(.+?)\s{2,}(.+)$")


def prob(odds: str) -> float:
    o = float(odds)
    return -o / (-o + 100) if o < 0 else 100 / (o + 100)


def parse(path: str, date: str) -> dict:
    games: list[dict] = []
    declined: list[str] = []
    g = None
    in_declines = False

    for raw in open(path):
        ln = raw.rstrip("\n")
        if ln.startswith("DECLINED"):
            in_declines = True
            g = None
            continue
        m = HEAD.match(ln)
        if m:
            in_declines = False
            g = {"away": m.group(1), "home": m.group(2), "ap": m.group(3),
                 "hp": m.group(4), "lineups": m.group(5),
                 "mean": float(m.group(6)), "rows": []}
            games.append(g)
            continue
        if in_declines:
            d = DECLINE.match(ln)
            if d:
                declined.append(
                    f"{d.group(1)} — {d.group(2).strip()}: {d.group(3)}")
            continue
        m = ROW.match(ln)
        if not m or g is None:
            continue
        bet, over, under, kal, note = m.groups()
        bet = bet.strip()
        r = {"bet": bet, "over": over, "under": under,
             "kalshi": None if kal == "-" else kal,
             "offband": "off-band" in note,
             "thin": "THIN" in note,
             "proj": "proj lineup" in note}
        gate = re.search(r"\[([^\]]+)\]", note)
        r["gate"] = gate.group(1) if gate else None
        rawm = re.search(r"raw ([+-]\d+)", note)
        r["raw"] = rawm.group(1) if rawm else None

        if re.match(r"^total ", bet):
            r["cls"] = "total"
        elif re.match(r"^F5 total ", bet):
            r["cls"] = "f5"
        elif re.match(rf"^({g['away']}|{g['home']}) total ", bet):
            r["cls"] = "team"
        elif " outs " in bet:
            r["cls"] = "outs"
        else:
            r["cls"] = "k"

        km = re.search(r" k (\d+\.5)$", bet)
        r["bump"] = bool(km and float(km.group(1)) >= 8.5)
        p = prob(over) + (0.02 if r["bump"] else 0.0)
        r["p_over"] = round(p, 4)
        if r["kalshi"]:
            pk = prob(r["kalshi"])
            r["p_kalshi"] = round(pk, 4)
            r["gap"] = round((p - pk) * 100, 1)
        else:
            r["p_kalshi"] = None
            r["gap"] = None
        g["rows"].append(r)

    posted = sum(1 for x in games if "posted" in x["lineups"])
    return {"date": date, "sims": 20000, "games": games,
            "declined": declined,
            "lineups_posted": posted,
            "games_scheduled": len(games) + len(declined)}


def main(argv):
    date = argv[0] if argv else "2026-09-09"
    stem = date.replace("-", "_")
    src = argv[1] if len(argv) > 1 else f"bets/{stem}_board.txt"
    out = argv[2] if len(argv) > 2 else f"bets/{stem}_board.json"
    d = parse(src, date)
    json.dump(d, open(out, "w"), indent=1)
    rows = sum(len(g["rows"]) for g in d["games"])
    mids = sum(1 for g in d["games"] for r in g["rows"] if r["kalshi"])
    print(f"wrote {out}: {len(d['games'])} games, {rows} rungs, "
          f"{mids} with a Kalshi mid, {len(d['declined'])} declined, "
          f"lineups posted {d['lineups_posted']}/{d['games_scheduled']}")


if __name__ == "__main__":
    main(sys.argv[1:])
