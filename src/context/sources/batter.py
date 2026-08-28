"""Batter platoon splits and batter-versus-pitcher history.

Both come from statsapi and both are cheap, but they deserve very different
amounts of trust and the shapes here say so.

  SPLITS      a hitter against left- and right-handed pitching, season to
              date. Real samples — a regular carries 150-400 PA against
              righties — and a genuine effect. The aggregate line hides a
              lefty who cannot touch lefties.
  VS PITCHER  the same hitter against today's starter, career. Almost
              always a handful of plate appearances. Lindor is 8-for-15
              lifetime against Castillo, which sounds like knowledge and is
              fifteen at-bats.

The second is included because it moves markets, not because it predicts,
and it is optional in the one contract that mentions it. Both carry `pa` so
nobody has to guess how much is behind a number.

Only meaningful for a hitter who is actually playing, so the assembler
attaches these when a lineup is posted and skips them otherwise — the same
rule that keeps every other batter-side field out of an unposted brief.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from src.context import atomic

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = PROJECT_ROOT / ".cache"
BASE = "https://statsapi.mlb.com/api/v1"
UA = "morning-bets/1.0"
TIMEOUT = 25

_SIT = {"L": "vl", "R": "vr"}


def _cached(name: str, url: str) -> dict:
    CACHE_DIR.mkdir(exist_ok=True)
    p = CACHE_DIR / name
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError):
        return json.loads(p.read_text()) if p.exists() else {}
    atomic.write_text(p, json.dumps(d))
    return d


def _rates(st: dict) -> dict:
    pa = st.get("plateAppearances") or 0
    out = {
        "pa": pa, "ab": st.get("atBats"), "h": st.get("hits"),
        "hr": st.get("homeRuns"), "rbi": st.get("rbi"),
        "avg": st.get("avg"), "obp": st.get("obp"),
        "slg": st.get("slg"), "ops": st.get("ops"),
    }
    if pa:
        out["k_pct"] = round((st.get("strikeOuts") or 0) / pa * 100, 1)
        out["bb_pct"] = round((st.get("baseOnBalls") or 0) / pa * 100, 1)
    return out


def splits(
    player_id: int, season: int | None = None, as_of: str | None = None,
) -> dict | None:
    """{'vs_L': {...}, 'vs_R': {...}} for one hitter, season to date."""
    season = season or date.today().year
    stamp = as_of or date.today().isoformat()
    d = _cached(
        f"statsapi_batsplit_{player_id}_{season}_{stamp}.json",
        f"{BASE}/people/{player_id}/stats?stats=statSplits&sitCodes=vl,vr"
        f"&group=hitting&season={season}",
    )
    out: dict[str, dict] = {}
    for blk in d.get("stats", []):
        for s in blk.get("splits", []):
            code = (s.get("split") or {}).get("code")
            if code == "vl":
                out["vs_L"] = _rates(s.get("stat", {}))
            elif code == "vr":
                out["vs_R"] = _rates(s.get("stat", {}))
    if not out:
        return None
    # The gap is the point. A 100-point OPS platoon split is a different
    # hitter depending on who is throwing, and the season line shows neither.
    l, r = out.get("vs_L", {}), out.get("vs_R", {})
    try:
        out["ops_gap"] = round(
            float(l.get("ops", 0)) - float(r.get("ops", 0)), 3)
    except (TypeError, ValueError):
        out["ops_gap"] = None
    return out


def for_hand(
    player_id: int, pitcher_hand: str | None,
    season: int | None = None, as_of: str | None = None,
) -> dict | None:
    """The split matching today's starter, with the other kept for context."""
    sp = splits(player_id, season, as_of)
    if not sp or not pitcher_hand:
        return sp
    key = "vs_L" if pitcher_hand.upper() == "L" else "vs_R"
    return {**sp, "relevant": key, "facing": sp.get(key)}


def vs_pitcher(
    batter_id: int, pitcher_id: int, season: int | None = None,
) -> dict | None:
    """Career head-to-head totals. Tiny samples; `pa` travels with them.

    statsapi returns one split per season faced plus a `vsPlayerTotal`
    block. The total is the number anyone actually quotes, so that is what
    comes back — with the per-season rows dropped, since five three-PA rows
    read as more evidence than fifteen plate appearances is.
    """
    season = season or date.today().year
    d = _cached(
        f"statsapi_vsplayer_{batter_id}_{pitcher_id}_{season}.json",
        f"{BASE}/people/{batter_id}/stats?stats=vsPlayer"
        f"&opposingPlayerId={pitcher_id}&group=hitting&season={season}",
    )
    for blk in d.get("stats", []):
        if (blk.get("type") or {}).get("displayName") != "vsPlayerTotal":
            continue
        for s in blk.get("splits", []):
            rec = _rates(s.get("stat", {}))
            rec["caveat"] = (
                "career head-to-head; almost always too few PA to carry "
                "weight on its own"
            )
            return rec
    return None


# ── arsenal matchup: the answer head-to-head is trying to give ─────────
_ARSENAL_URL = (
    "https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats"
    "?year={year}&min=10&type=batter&hand=&pitch_type=ALL&csv=true"
)


def _batter_pitch_table(
    year: int | None = None, as_of: str | None = None,
) -> dict[str, dict[str, dict]]:
    """{name_key: {pitch_name: performance}} for every batter.

    Savant publishes a hitter's results split by the TYPE of pitch thrown,
    with real samples — Judge has 276 four-seamers and 193 sliders on
    record. That is the raw material for answering "how does this hitter
    fare against this pitcher" without relying on the fifteen times they
    have actually met.
    """
    import csv as _csv
    import io as _io
    import re as _re
    import urllib.request as _u

    year = year or date.today().year
    stamp = as_of or date.today().isoformat()
    CACHE_DIR.mkdir(exist_ok=True)
    p = CACHE_DIR / f"savant_batter_arsenal_{year}_{stamp}.csv"
    if p.exists():
        text = p.read_text()
    else:
        req = _u.Request(
            _ARSENAL_URL.format(year=year),
            headers={"User-Agent": "Mozilla/5.0 (morning-bets/1.0)"},
        )
        with _u.urlopen(req, timeout=40) as r:
            text = r.read().decode("utf-8", errors="replace")
        if text.lstrip().startswith("<"):
            raise ValueError("batter arsenal returned HTML, not CSV")
        atomic.write_text(p, text)

    def _key(v: str) -> str:
        s = (v or "").strip()
        if "," in s:
            last, first = [x.strip() for x in s.split(",", 1)]
            s = f"{first} {last}"
        return _re.sub(r"\s+", " ",
                       _re.sub(r"[^\w\s]", "", s.lower())).strip()

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    out: dict[str, dict[str, dict]] = {}
    for r in _csv.DictReader(_io.StringIO(text.lstrip("﻿"))):
        k = _key(r.get("last_name, first_name", ""))
        pitch = r.get("pitch_name")
        if not k or not pitch:
            continue
        out.setdefault(k, {})[pitch] = {
            "pitches": _num(r.get("pitches")),
            "pa": _num(r.get("pa")),
            "ba": _num(r.get("ba")),
            "slg": _num(r.get("slg")),
            "woba": _num(r.get("woba")),
            "whiff_pct": _num(r.get("whiff_percent")),
            "run_value_per_100": _num(r.get("run_value_per_100")),
        }
    return out


def vs_arsenal(
    batter_name: str, starter_arsenal: list[dict] | None,
    year: int | None = None, as_of: str | None = None,
) -> dict | None:
    """Project a hitter against a specific starter's pitch mix.

    Weights the batter's per-pitch results by how often this starter
    actually throws each pitch. This is what head-to-head gestures at and
    cannot deliver: it answers "is this a good matchup" from hundreds of
    pitches rather than a dozen plate appearances, and it explains itself —
    a sinker-heavy righty is a different problem from a slider-heavy one
    even though both are "a righty".

    `coverage` is the share of the starter's usage this could actually
    price. A projection built on 60% of his arsenal is a partial answer and
    says so rather than quietly extrapolating.
    """
    if not starter_arsenal:
        return None
    table = _batter_pitch_table(year, as_of)
    key = batter_name.strip().lower()
    mine = table.get(key)
    if not mine:
        return None

    num_w = num_slg = num_ba = num_whiff = used = total = 0.0
    parts = []
    for p in starter_arsenal:
        usage = p.get("usage_pct")
        try:
            usage = float(usage)
        except (TypeError, ValueError):
            continue
        total += usage
        hit = mine.get(p.get("pitch"))
        if not hit or hit.get("woba") is None:
            continue
        used += usage
        num_w += usage * hit["woba"]
        num_slg += usage * (hit.get("slg") or 0)
        num_ba += usage * (hit.get("ba") or 0)
        if hit.get("whiff_pct") is not None:
            num_whiff += usage * hit["whiff_pct"]
        parts.append({
            "pitch": p.get("pitch"),
            "usage_pct": usage,
            "batter_woba": hit["woba"],
            "batter_slg": hit.get("slg"),
            "batter_whiff_pct": hit.get("whiff_pct"),
            "sample_pitches": hit.get("pitches"),
        })
    if not used:
        return None
    return {
        "batter": batter_name,
        "proj_woba": round(num_w / used, 3),
        # slg and ba are projected on the same scale statsapi reports
        # head-to-head in, which is what makes the two comparable.
        "proj_slg": round(num_slg / used, 3),
        "proj_ba": round(num_ba / used, 3),
        "proj_whiff_pct": round(num_whiff / used, 1) if num_whiff else None,
        "coverage": round(used / total, 2) if total else None,
        # The components, always. A .340 projection driven entirely by one
        # pitch he happens to crush is a different read from a flat .340.
        "by_pitch": sorted(parts, key=lambda x: -x["usage_pct"]),
    }


#: Below this, head-to-head is not evidence of anything. Two at-bats cannot
#: disagree with a projection built on hundreds of pitches.
H2H_MIN_PA = 20
#: Slugging gap that counts as the history actually saying something the
#: arsenal projection does not.
H2H_DIVERGENCE_SLG = 0.150
#
# BOTH NUMBERS ARE UNVALIDATED PLACEHOLDERS. Measured on one full slate,
# 124 batter/starter pairs had both an h2h record and a projection:
#
#   PA        min 1, median 3, p75 7, p90 14, MAX 34
#   |SLG gap| median 0.315 — because slugging over three plate appearances
#             is either .000 or four figures
#
# Two consequences. First, H2H_MIN_PA does all the work and the SLG
# threshold is nearly inert: at 20 PA the count of "diverges" is identical
# (1) whether the gap bar is 0.100, 0.150 or 0.200. Second, and worse for
# the whole idea, one pair in 124 clears any sane bar.
#
# The samples are small structurally, not because of how this is queried —
# season=2026, no season, and stats=vsPlayerTotal all return the same 15 PA
# for Lindor against Castillo, so these appear to be career totals already.
# Opposite leagues means interleague is all they ever get.
#
# Left as-is deliberately, scoped to the current season. Whether h2h earns
# its place at all is a question for the eval harness, not for tuning two
# constants against a single day.


def reconcile(h2h: dict | None, projection: dict | None) -> dict | None:
    """Is the head-to-head telling us anything the arsenal does not?

    Head-to-head earns attention only when it DISAGREES with the
    mechanistic projection and has enough behind it to disagree credibly.
    Agreement is not corroboration — it is the same information counted
    twice — and Tatis 0-for-2 is not a dissent, it is two at-bats.

    So this returns a verdict rather than a number:

        thin        under H2H_MIN_PA — ignore it
        consistent  it matches the projection; adds nothing
        diverges    real sample, real disagreement — worth a look

    Only the last is worth a line in a brief.
    """
    if not h2h or not projection:
        return None
    pa = h2h.get("pa") or 0
    try:
        h_slg = float(h2h.get("slg"))
    except (TypeError, ValueError):
        return None
    p_slg = projection.get("proj_slg")
    if p_slg is None:
        return None
    gap = round(h_slg - p_slg, 3)

    if pa < H2H_MIN_PA:
        verdict = "thin"
    elif abs(gap) >= H2H_DIVERGENCE_SLG:
        verdict = "diverges"
    else:
        verdict = "consistent"
    return {
        "verdict": verdict,
        "pa": pa,
        "h2h_slg": h_slg,
        "projected_slg": p_slg,
        "slg_gap": gap,
        "worth_reading": verdict == "diverges",
        "note": {
            "thin": f"{pa} PA — too few to disagree with anything",
            "consistent": "history matches the arsenal projection; "
                          "no extra information",
            "diverges": f"{pa} PA running {gap:+.3f} SLG against the "
                        f"arsenal projection",
        }[verdict],
    }


if __name__ == "__main__":
    import sys
    from src import roster
    who = sys.argv[1] if len(sys.argv) > 1 else "Aaron Judge"
    vs = sys.argv[2] if len(sys.argv) > 2 else "Luis Castillo"
    bid, pid = roster.player_id(who), roster.player_id(vs)
    hand = roster.throws(vs)
    print(f"{who} (id {bid}) vs {vs} (id {pid}, throws {hand})\n")
    sp = for_hand(bid, hand) if bid else None
    if sp:
        for k in ("vs_L", "vs_R"):
            r = sp.get(k) or {}
            mark = "  <-- facing" if sp.get("relevant") == k else ""
            print(f"  {k}: PA {r.get('pa'):>4}  {r.get('avg')}/{r.get('obp')}"
                  f"/{r.get('slg')}  K {r.get('k_pct')}%  "
                  f"BB {r.get('bb_pct')}%{mark}")
        print(f"  OPS gap (L-R): {sp.get('ops_gap')}")
    h2h = vs_pitcher(bid, pid) if bid and pid else None
    print(f"\n  head-to-head: {h2h}" if h2h else
          "\n  head-to-head: none")
