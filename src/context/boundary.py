"""Are a mid-inning hook and an end-of-inning hook the same decision?

`removal.py` says they are — "a hook at the end of an inning is still a
hook" — and fits one binary over all 86k plate appearances. The simulated
starter-length distribution says otherwise: 64.1% of real appearances end on
a whole inning and the sim produces about 5%, because a per-PA hazard has no
way to express "he is done, but let him finish the sixth."

This counts the two decisions separately and asks whether they key on
different things. The hypothesis under test, stated before looking:

  * a BOUNDARY pull is the normal end of a decent outing — pitch count,
    times through the order, nothing on fire
  * a MID-INNING pull is a rescue — he is being hit RIGHT NOW, and the
    feature that should matter is damage in the CURRENT inning, which no
    feature in the shipped model carries
  * the same rally is survivable early and fatal late, so inning interacts
  * a close game shortens the leash

The current-inning features are the point. The shipped model has cumulative
`runs`, `br`, `damage` and current `onbase`, so a starter cruising through
five who gives up three in the sixth looks, to it, exactly like a starter
who gave up three in the first and settled down.

    venv/bin/python -m scratchpad.boundary [n_games]
"""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict

from src.context.sources import pbp

SKIP = {"game_advisory", "pitching_substitution", "offensive_substitution",
        "defensive_switch", "defensive_substitution", "runner_placed",
        "ejection", "injury"}

DAMAGE = {"walk": 1.0, "intent_walk": 1.0, "hit_by_pitch": 1.0,
          "single": 1.0, "double": 1.7, "triple": 2.3, "home_run": 3.0,
          "field_error": 0.5}
ONBASE = {"single", "double", "triple", "home_run", "walk", "intent_walk",
          "hit_by_pitch", "field_error"}


def exits(game_id: str, data: dict | None = None) -> list[dict]:
    """One row per STARTER, describing how his outing ended.

    `kind` is 'boundary' when he completed the inning he was removed after,
    'mid' when someone else finished it, and 'finished' when he was never
    removed at all.
    """
    data = data if data is not None else pbp.fetch(game_id)
    if not data:
        return []
    plays = [p for p in (data.get("allPlays") or [])
             if ((p.get("result") or {}).get("eventType") or "") not in SKIP]
    starter: dict = {}
    cum: dict = defaultdict(lambda: {"pitches": 0, "bf": 0, "runs": 0,
                                     "br": 0, "dmg": 0.0})
    # Per-inning, reset every half — the quantity the shipped model lacks.
    inn: dict = defaultdict(lambda: {"runs": 0, "br": 0, "dmg": 0.0,
                                     "inning": 0})
    last: dict = {}
    prev_score = 0
    for i, play in enumerate(plays):
        ab = play.get("about") or {}
        mu = play.get("matchup") or {}
        res = play.get("result") or {}
        pid = (mu.get("pitcher") or {}).get("id")
        if not pid:
            continue
        top = bool(ab.get("isTopInning"))
        side = "home" if top else "away"
        starter.setdefault(side, pid)
        score = (res.get("awayScore", 0) or 0) + (res.get("homeScore", 0) or 0)
        runs_now = max(score - prev_score, 0)
        prev_score = score
        if starter[side] != pid:
            continue

        c, v = cum[side], inn[side]
        if v["inning"] != (ab.get("inning") or 1):
            v.update(runs=0, br=0, dmg=0.0, inning=ab.get("inning") or 1)

        nxt = next((p for p in plays[i + 1:]
                    if bool((p.get("about") or {}).get("isTopInning")) == top),
                   None)
        nxt_pid = (((nxt or {}).get("matchup") or {}).get("pitcher") or {}) \
            .get("id")
        cnt = play.get("count") or {}
        margin = (res.get("homeScore", 0) or 0) - (res.get("awayScore", 0) or 0)
        ev = res.get("eventType") or ""

        # State AFTER this play is what the manager weighs before the next.
        c["bf"] += 1
        c["runs"] += runs_now
        c["br"] += 1 if ev in ONBASE else 0
        c["dmg"] += DAMAGE.get(ev, 0.0)
        c["pitches"] += sum(1 for e in (play.get("playEvents") or [])
                            if e.get("isPitch"))
        v["runs"] += runs_now
        v["br"] += 1 if ev in ONBASE else 0
        v["dmg"] += DAMAGE.get(ev, 0.0)

        outs_after = (cnt.get("outs", 0) or 0) + (
            1 if ev in ("strikeout", "field_out", "force_out", "sac_fly",
                        "sac_bunt", "fielders_choice_out") else 0)
        last[side] = {
            "game_id": game_id, "pitcher": pid, "side": side,
            "inning": ab.get("inning") or 1,
            "outs_after": outs_after,
            "pitches": c["pitches"], "bf": c["bf"],
            "tto": min((c["bf"] - 1) // 9 + 1, 3),
            "runs": c["runs"], "br": c["br"], "damage": c["dmg"],
            "inn_runs": v["runs"], "inn_br": v["br"], "inn_dmg": v["dmg"],
            "margin": margin if side == "home" else -margin,
            "next_pid": nxt_pid, "has_next": nxt is not None,
        }

    out = []
    for side, r in last.items():
        if not r["has_next"]:
            r["kind"] = "finished"       # game ended with him on the mound
        elif r["next_pid"] == r["pitcher"]:
            r["kind"] = "finished"       # never removed (unreachable in prod)
        else:
            # He is out. Did he complete the inning he was pulled after?
            r["kind"] = "boundary" if r["outs_after"] >= 3 else "mid"
        out.append(r)
    return out


def collect(limit: int | None = None, verbose: bool = True) -> list[dict]:
    ids = pbp.final_games()
    if limit:
        ids = ids[:limit]
    rows: list[dict] = []
    n = 0
    for gid in ids:
        if not pbp.have(gid):
            continue
        try:
            rows.extend(exits(gid))
        except Exception:
            continue
        n += 1
        if verbose and n % 400 == 0:
            print(f"  {n} games, {len(rows):,} starts", flush=True)
    return rows


def _tab(rows, key, label, buckets):
    print(f"\n  {label}")
    print(f"    {'':<14}{'n':>7}{'boundary':>10}{'mid':>8}")
    for lo, hi, name in buckets:
        sub = [r for r in rows if lo <= r[key] < hi]
        if len(sub) < 30:
            continue
        b = sum(1 for r in sub if r["kind"] == "boundary")
        m = sum(1 for r in sub if r["kind"] == "mid")
        t = b + m
        if not t:
            continue
        print(f"    {name:<14}{t:>7,}{b / t:>10.1%}{m / t:>8.1%}")


def report(rows: list[dict] | None = None) -> None:
    rows = collect() if rows is None else rows
    pulled = [r for r in rows if r["kind"] in ("boundary", "mid")]
    b = [r for r in pulled if r["kind"] == "boundary"]
    m = [r for r in pulled if r["kind"] == "mid"]
    print(f"\n{len(rows):,} starts; {len(pulled):,} removed "
          f"({len(rows) - len(pulled):,} finished the game)")
    print(f"  BOUNDARY {len(b):,} ({len(b) / len(pulled):.1%})   "
          f"MID-INNING {len(m):,} ({len(m) / len(pulled):.1%})")

    print(f"\n  STATE AT THE MOMENT HE WAS PULLED")
    print(f"    {'':<12}{'pitches':>9}{'outs':>7}{'cum runs':>10}"
          f"{'THIS inn runs':>15}{'THIS inn br':>13}{'|margin|':>10}")
    for lbl, g in (("boundary", b), ("mid-inning", m)):
        print(f"    {lbl:<12}{st.mean(r['pitches'] for r in g):>9.1f}"
              f"{st.mean((r['inning'] - 1) * 3 + r['outs_after'] for r in g):>7.1f}"
              f"{st.mean(r['runs'] for r in g):>10.2f}"
              f"{st.mean(r['inn_runs'] for r in g):>15.2f}"
              f"{st.mean(r['inn_br'] for r in g):>13.2f}"
              f"{st.mean(abs(r['margin']) for r in g):>10.2f}")

    _tab(pulled, "inn_runs", "RUNS ALLOWED IN THE INNING HE LEFT",
         [(0, 1, "0"), (1, 2, "1"), (2, 3, "2"), (3, 4, "3"), (4, 99, "4+")])
    _tab(pulled, "runs", "CUMULATIVE RUNS ALLOWED (the shipped feature)",
         [(0, 1, "0"), (1, 2, "1"), (2, 3, "2"), (3, 4, "3"), (4, 99, "4+")])
    _tab(pulled, "inning", "INNING HE WAS PULLED IN",
         [(1, 4, "1-3"), (4, 5, "4"), (5, 6, "5"), (6, 7, "6"),
          (7, 8, "7"), (8, 99, "8+")])
    _tab(pulled, "pitches", "PITCH COUNT",
         [(0, 60, "<60"), (60, 80, "60-79"), (80, 95, "80-94"),
          (95, 110, "95-109"), (110, 999, "110+")])

    # The interaction the hypothesis turns on: the same rally, early vs late.
    print(f"\n  THE INTERACTION — P(mid-inning | pulled), by inning x "
          f"runs allowed THIS inning")
    print(f"    {'inning':<9}" + "".join(f"{c:>10}" for c in
                                         ("0 runs", "1", "2", "3+")))
    for lo, hi, name in ((1, 4, "1-3"), (4, 6, "4-5"), (6, 7, "6"),
                         (7, 99, "7+")):
        cells = []
        for rlo, rhi in ((0, 1), (1, 2), (2, 3), (3, 99)):
            sub = [r for r in pulled if lo <= r["inning"] < hi
                   and rlo <= r["inn_runs"] < rhi]
            cells.append(f"{sum(1 for r in sub if r['kind'] == 'mid') / len(sub):>9.1%}"
                         if len(sub) >= 30 else f"{'-':>9}")
        print(f"    {name:<9}" + "".join(f"{c:>10}" for c in cells))

    print(f"\n  CLOSE GAME? P(mid-inning | pulled), by |margin|")
    _tab(pulled, "margin", "margin from his side's view",
         [(-99, -4, "down 4+"), (-3, 0, "down 1-3"), (0, 1, "tied"),
          (1, 4, "up 1-3"), (4, 99, "up 4+")])


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    report(collect(limit=lim))
