"""statsapi.mlb.com adapter: game logs, head-to-head splits, standings.

Free, unauthenticated, and the only source here that carries PITCH COUNTS —
`mlb_pitching` stores outs but not pitches, so the leash signal for an outs
prop has to come from the game log rather than the local boxscore cache.

Everything is cached to a date-keyed file under .cache/, the same convention
the savant CSVs use. A slate needs ~30 game logs plus a standings pull; at
one request each that is fine once a day and wasteful on a re-run.

`as_of` is threaded through every function and is not decorative. These
feed a backtest, and a game log that includes the start being bet on would
make every replayed result meaningless. Filtering happens on the parsed
rows rather than in the query, because statsapi has no "before this date"
parameter — so the cache holds the full season and the caller sees a slice.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = PROJECT_ROOT / ".cache"
BASE = "https://statsapi.mlb.com/api/v1"
UA = "morning-bets/1.0"
TIMEOUT = 30


def _get(path: str) -> dict:
    req = urllib.request.Request(f"{BASE}{path}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def _cached(name: str, path: str) -> dict:
    """Fetch once per calendar day, keyed by filename.

    A failed fetch with a cache present returns the cache — a stale game log
    is worth more than an empty brief, and the assembler will report the
    field as present either way. A failed fetch with no cache raises, so a
    genuine outage is visible rather than silently becoming "no data".
    """
    CACHE_DIR.mkdir(exist_ok=True)
    p = CACHE_DIR / name
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass  # truncated write from an interrupted run; refetch
    try:
        d = _get(path)
    except (urllib.error.URLError, TimeoutError):
        if p.exists():
            return json.loads(p.read_text())
        raise
    p.write_text(json.dumps(d))
    return d


def _ip_to_outs(ip: str | None) -> int | None:
    """'6.1' innings is 19 outs, not 6.1 of anything."""
    if not ip:
        return None
    try:
        whole, _, frac = str(ip).partition(".")
        return int(whole) * 3 + int(frac or 0)
    except ValueError:
        return None


# ── starter_game_log ───────────────────────────────────────────────────
def game_log(
    player_id: int, season: int | None = None, as_of: str | None = None,
    last: int = 10, starts_only: bool = True,
) -> list[dict]:
    """The pitcher's most recent `last` appearances strictly before as_of.

    Pitch count is the field this exists for. Everything else is available
    from the local boxscore cache; `numberOfPitches` is not, and a starter
    averaging 17 pitches an inning cannot reach the 6th on an 85-pitch
    leash no matter how good his stuff is.
    """
    season = season or date.today().year
    cutoff = as_of or date.today().isoformat()
    d = _cached(
        f"statsapi_gamelog_{player_id}_{season}_{cutoff}.json",
        f"/people/{player_id}/stats?stats=gameLog&group=pitching"
        f"&season={season}",
    )
    stats = d.get("stats") or []
    splits = stats[0].get("splits", []) if stats else []
    out = []
    for s in splits:
        if s.get("date", "") >= cutoff:
            continue  # never let the brief see the game being bet on
        st = s.get("stat", {})
        outs = _ip_to_outs(st.get("inningsPitched"))
        pitches = st.get("numberOfPitches")
        out.append({
            "date": s.get("date"),
            "opponent": (s.get("opponent") or {}).get("abbreviation"),
            "home": not (s.get("isHome") is False),
            # Whether he STARTED. A converted reliever's recent appearances
            # are mostly one-inning outings, and averaging those into a
            # figure used to price a start is meaningless — Drew Anderson
            # has 5 starts in 43 appearances, so his last-10 average reads
            # 6.5 outs while his actual starts run 11, 12 and 15.
            "is_start": bool(st.get("gamesStarted")),
            "outs": outs,
            "ip": st.get("inningsPitched"),
            "pitches": pitches,
            # The efficiency number the leash question actually turns on.
            "pitches_per_inning": (
                round(pitches / (outs / 3.0), 1)
                if pitches and outs else None
            ),
            "er": st.get("earnedRuns"),
            "k": st.get("strikeOuts"),
            "bb": st.get("baseOnBalls"),
            "h": st.get("hits"),
            "hr": st.get("homeRuns"),
        })
    # Take the last `last` STARTS, not the last `last` appearances. For a
    # swingman those are different sets entirely, and slicing appearances
    # first can return a window containing no starts at all.
    if starts_only and any(r["is_start"] for r in out):
        return [r for r in out if r["is_start"]][-last:]
    return out[-last:]


#: Recency window for the "what is he now" view, in days. Six weeks is
#: roughly 6-8 starts on a normal turn — enough to mean something, short
#: enough to exclude a pitcher's previous self.
#:
#: A flat last-10 mean silently spans role changes, stretch-outs and injury
#: layoffs. Jacob Lopez averages 13.5 outs over his last ten starts and 16.3
#: over the last six weeks, because the ten includes May outings of 2.0 and
#: 1.2 innings from before he was built up. Andrew Painter's last ten span a
#: six-week absence between 6/17 and 7/31 as though nothing happened.
#:
#: Both numbers are always reported; this only decides which one leads.
RECENT_DAYS = 42
#: Below this many starts inside the window, the recent view is noise and
#: the fuller sample is the better estimate.
MIN_RECENT_STARTS = 3


def game_log_summary(
    rows: list[dict], starts_only: bool = True, as_of: str | None = None,
) -> dict:
    """Roll a game log into the handful of numbers a brief should carry.

    STARTS ONLY by default, because every consumer of this is pricing a
    start. Mixing relief appearances in produces a number that describes
    neither role: a converted reliever's average collapses toward one
    inning and a swingman's lands somewhere that has never happened.

    Falls back to all appearances when he has no starts on record, with
    `basis` naming which it used — a rookie's first start has no start
    history and something is better than nothing, so long as it says so.
    """
    if not rows:
        return {}
    starts = [r for r in rows if r.get("is_start")]
    basis = "starts"
    if starts_only and starts:
        rows = starts
    elif starts_only:
        basis = "all appearances (no starts on record)"
    else:
        basis = "all appearances"

    def _agg(rs: list[dict]) -> dict:
        o = [r["outs"] for r in rs if r["outs"] is not None]
        p_ = [r["pitches"] for r in rs if r["pitches"]]
        pp = [r["pitches_per_inning"] for r in rs if r["pitches_per_inning"]]
        return {
            "starts": len(rs),
            "avg_outs": round(sum(o) / len(o), 1) if o else None,
            "avg_pitches": round(sum(p_) / len(p_)) if p_ else None,
            "avg_pitches_per_inning": (
                round(sum(pp) / len(pp), 1) if pp else None),
            "pct_6ip": (
                round(sum(1 for x in o if x >= 18) / len(o), 2) if o else None),
        }

    # The recent window, same both-numbers treatment team_hook uses.
    recent: dict = {}
    lead = "all"
    if as_of:
        cut = (date.fromisoformat(as_of)
               - timedelta(days=RECENT_DAYS)).isoformat()
        rs = [r for r in rows if (r.get("date") or "") >= cut]
        if len(rs) >= MIN_RECENT_STARTS:
            recent = _agg(rs)
            lead = "recent"

    outs = [r["outs"] for r in rows if r["outs"] is not None]
    pit = [r["pitches"] for r in rows if r["pitches"]]
    ppi = [r["pitches_per_inning"] for r in rows if r["pitches_per_inning"]]
    tot_outs = sum(outs) or 0
    return {
        "basis": basis,
        "recent_days": RECENT_DAYS if recent else None,
        "recent": recent or None,
        # Which of the two a reader should lead with. The other is always
        # here, and the gap between them is the signal when a pitcher has
        # changed.
        "lead": lead,
        "expected_outs": (
            recent.get("avg_outs") if recent
            else (round(sum(outs) / len(outs), 1) if outs else None)),
        "starts": len(rows),
        "avg_outs": round(sum(outs) / len(outs), 1) if outs else None,
        "max_outs": max(outs) if outs else None,
        "avg_pitches": round(sum(pit) / len(pit)) if pit else None,
        "max_pitches": max(pit) if pit else None,
        "avg_pitches_per_inning": (
            round(sum(ppi) / len(ppi), 1) if ppi else None
        ),
        "pct_6ip": (
            round(sum(1 for o in outs if o >= 18) / len(outs), 2)
            if outs else None
        ),
        "era": (
            round(sum(r["er"] or 0 for r in rows) * 27.0 / tot_outs, 2)
            if tot_outs else None
        ),
        "k9": (
            round(sum(r["k"] or 0 for r in rows) * 27.0 / tot_outs, 1)
            if tot_outs else None
        ),
        "whip": (
            round((sum(r["h"] or 0 for r in rows)
                   + sum(r["bb"] or 0 for r in rows)) * 3.0 / tot_outs, 2)
            if tot_outs else None
        ),
    }


# ── starter_vs_opponent ────────────────────────────────────────────────
def vs_team(
    player_id: int, opponent_team_id: int, seasons: list[int] | None = None,
) -> dict:
    """Career-to-date H2H totals against one club, summed over seasons.

    statsapi returns this split per BATTER faced, so the headline line every
    props site shows ("21 PA, 2 H, 6 K") is a sum, not a row.

    Included because the market and the cappers both cite it, not because it
    predicts much — three seasons against a club is routinely under 30 PA,
    which is why no contract requires this field.
    """
    seasons = seasons or [date.today().year]
    agg = {"pa": 0, "ab": 0, "h": 0, "tb": 0, "hr": 0, "k": 0, "bb": 0,
           "seasons": seasons, "batters": 0}
    for yr in seasons:
        try:
            d = _cached(
                f"statsapi_vsteam_{player_id}_{opponent_team_id}_{yr}.json",
                f"/people/{player_id}/stats?stats=vsTeam&group=pitching"
                f"&opposingTeamId={opponent_team_id}&season={yr}",
            )
        except Exception:
            continue
        stats = d.get("stats") or []
        for block in stats:
            for s in block.get("splits", []):
                st = s.get("stat", {})
                agg["batters"] += 1
                agg["pa"] += st.get("plateAppearances") or 0
                agg["ab"] += st.get("atBats") or 0
                agg["h"] += st.get("hits") or 0
                agg["tb"] += st.get("totalBases") or 0
                agg["hr"] += st.get("homeRuns") or 0
                agg["k"] += st.get("strikeOuts") or 0
                agg["bb"] += st.get("baseOnBalls") or 0
    agg["avg"] = round(agg["h"] / agg["ab"], 3) if agg["ab"] else None
    return agg


# ── team_situation ─────────────────────────────────────────────────────
def _gb(v) -> float | None:
    """Games back. '-' means zero — the club is leading."""
    if v in (None, ""):
        return None
    if v == "-":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _elim(v) -> float | None:
    """Elimination number: how many combined losses end their season.

    The two sentinels mean opposite things and conflating them inverts the
    whole read. '-' is NOT zero — it means no elimination number applies
    yet, i.e. the club is safe. 'E' means already eliminated. Treating '-'
    as 0.0 labelled the 80-49 Brewers "fading" and the 50-78 Rockies "in
    the hunt".

    Returns None for "safe / not applicable", 0.0 for eliminated.
    """
    if v == "E":
        return 0.0
    if v in (None, "", "-"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def team_abbrs(season: int | None = None) -> dict[int, str]:
    """{team_id: 'MIL'}. The standings payload carries names, not abbrs."""
    season = season or date.today().year
    d = _cached(
        f"statsapi_teams_{season}.json",
        f"/teams?sportId=1&season={season}",
    )
    return {t["id"]: t.get("abbreviation") or t.get("teamCode", "").upper()
            for t in d.get("teams", []) if t.get("id")}


def standings(season: int | None = None, as_of: str | None = None) -> dict:
    """{team_abbr: situation}. One call covers all 30 clubs.

    `eliminationNumber` is the field that matters most here and the reason
    this beats raw record: it folds in games remaining, so a club sitting on
    7 is nearly done and behaving like it — handing innings to prospects,
    which is precisely the hook drift workload_context measures.
    """
    season = season or date.today().year
    cutoff = as_of or date.today().isoformat()
    d = _cached(
        f"statsapi_standings_{season}_{cutoff}.json",
        f"/standings?leagueId=103,104&season={season}"
        f"&standingsTypes=regularSeason",
    )
    abbrs = team_abbrs(season)
    out: dict[str, dict] = {}
    for rec in d.get("records", []):
        for t in rec.get("teamRecords", []):
            team = t.get("team") or {}
            abbr = abbrs.get(team.get("id")) or team.get("name")
            out[abbr] = {
                "team": team.get("name"),
                "abbr": abbr,
                "wins": t.get("wins"),
                "losses": t.get("losses"),
                "pct": t.get("winningPercentage"),
                "run_diff": t.get("runDifferential"),
                "division_rank": t.get("divisionRank"),
                "games_back": _gb(t.get("gamesBack")),
                "wc_games_back": _gb(t.get("wildCardGamesBack")),
                # None here means "safe", not "zero". See _elim().
                "elimination_number": _elim(t.get("eliminationNumber")),
                "wc_elimination_number": _elim(
                    t.get("wildCardEliminationNumber")),
                "clinched": bool(t.get("clinched")),
                "division_leader": bool(t.get("divisionLeader")),
                "streak": (t.get("streak") or {}).get("streakCode"),
                # Context for every number above: an elimination number of
                # 18 means one thing in April and another in September.
                "games_remaining": (
                    162 - (t.get("gamesPlayed") or 0)
                    if t.get("gamesPlayed") else None
                ),
                "posture": _posture(t),
            }
    return out


def _posture(t: dict) -> str:
    """One word for how a club is likely to be handling its pitchers.

    A label over the raw fields, never a replacement for them — the numbers
    travel alongside it in the same record, because a coarse bucket is
    useful for skimming and useless for arguing with.

    Keyed on WILD-CARD GAMES BACK, not the elimination number. Elimination
    number is a poor discriminator until very late: with ~33 games left the
    49-80 Athletics still needed 18 combined losses, which cleared every
    sane "close to elimination" threshold and labelled them "in the hunt".
    Games back separates the same field cleanly — the clubs playing out the
    string sit at 13 to 18.5 back while every genuine contender is inside 2.
    """
    if t.get("clinched"):
        return "clinched"           # rests regulars, quick hooks
    elim = _elim(t.get("eliminationNumber"))
    wc_elim = _elim(t.get("wildCardEliminationNumber"))
    live = [e for e in (elim, wc_elim) if e is not None]
    if live and max(live) == 0.0:
        return "eliminated"         # prospect innings, no leash discipline
    if t.get("divisionLeader"):
        return "contending"
    gb = _gb(t.get("wildCardGamesBack"))
    if gb is None:
        return "in the hunt"
    if gb <= 2:
        return "contending"         # protecting arms for October
    if gb <= 6:
        return "in the hunt"
    if gb <= 12:
        return "fading"
    return "out of it"              # prospect reps, long leashes


if __name__ == "__main__":
    import sys
    from src import roster
    who = sys.argv[1] if len(sys.argv) > 1 else "Andrew Painter"
    pid = roster.player_id(who)
    print(f"{who} -> id {pid}")
    if pid:
        rows = game_log(pid)
        print(f"\n  {'date':<12}{'opp':<5}{'IP':>5}{'pit':>5}{'P/IP':>6}"
              f"{'ER':>4}{'K':>4}{'BB':>4}")
        for r in rows:
            print(f"  {r['date']:<12}{str(r['opponent'] or '?'):<5}"
                  f"{str(r['ip']):>5}{str(r['pitches'] or '-'):>5}"
                  f"{str(r['pitches_per_inning'] or '-'):>6}"
                  f"{r['er']:>4}{r['k']:>4}{r['bb']:>4}")
        print("\n  summary:", json.dumps(game_log_summary(rows)))
    st = standings()
    print(f"\nstandings: {len(st)} teams")
    print(f"  {'team':<6}{'W-L':>9}{'GB':>7}{'elim':>7}{'wcElim':>8}  posture")
    for a, s in sorted(st.items(), key=lambda kv: -(kv[1]["wins"] or 0)):
        rec = f"{s['wins']}-{s['losses']}"
        print(f"  {a:<6}{rec:>9}{str(s['games_back']):>7}"
              f"{str(s['elimination_number']):>7}"
              f"{str(s['wc_elimination_number']):>8}  {s['posture']}")
