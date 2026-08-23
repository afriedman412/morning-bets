"""Team workload and bullpen state, computed from already-cached boxscores.

No network. `mlb_pitching` holds ~8,500 pitcher lines across ~1,000 games
that grading already pulled, and every question here is a GROUP BY over it.
That matters beyond speed: these fields are needed for every pitcher prop on
the slate, and a per-start API call would make the assembler slow enough to
skip.

Two things this answers, both of which bound an outs or strikeout line
before the pitcher's own ability enters the picture:

  HOOK — how long does this club let its primary pitcher go? The spread is
  enormous. Over the cached sample Seattle's primary pitcher averaged 17.3
  outs and cleared 6 innings 51% of the time; the Athletics' averaged 14.2
  and cleared it 21%. An `over 17.5 outs` prop is near a coin flip for one
  and a 1-in-5 shot for the other, before you know who is pitching.

  BULLPEN — how much relief work has the club just absorbed, and how good is
  the unit doing it. Usage says who is available; performance says whether
  that matters.

"Primary pitcher" is whoever recorded the most outs for a team in a game,
not the nominal starter. On an opener day that picks the bulk arm rather
than the one-inning opener, which is the right unit here: this is a
question about workload, and workload is workload regardless of who is
announced first. It also avoids needing a `started` flag that
`mlb_pitching` does not have and that would cost a full boxscore re-fetch
to backfill. Measured cost of the choice: opener-shaped outings are 1.4% of
the sample and excluding them moves a team's average by at most 0.5 outs.
"""
from __future__ import annotations

from datetime import date, timedelta

from src import db

# Trailing window for the "recent" view. A club's approach genuinely shifts
# inside a season — a lost team hands prospects rope, a contender starts
# protecting arms for October — so a season-long average quietly blends two
# different regimes. 30 days is roughly 25-28 starts, enough to mean
# something without reaching back to a different team.
RECENT_DAYS = 30
# Below this many recent starts the window is noise and the season number is
# the better estimate. Reported either way so the caller can see which it is.
MIN_RECENT_STARTS = 8

# Relief usage decays fast; three days is the horizon over which yesterday's
# workload still constrains today's availability.
USAGE_DAYS = 3


def _primary_cte() -> str:
    """One row per pitcher-game with `rn = 1` marking the starter.

    Ground truth where the boxscore has been consulted, most-outs only
    where it has not. The difference is not cosmetic for bullpen usage: the
    heuristic counts 2,026 reliever outs as starter work and 880 starter
    outs as relief, netting to a 5% UNDERSTATEMENT of relief innings.

    Worse, that error is not random. A long reliever only outranks the
    starter when the starter was knocked out early — which is exactly the
    night the bullpen had to cover six innings. So the heuristic is most
    wrong on the days the pen was most taxed, which is the entire signal
    `bullpen()` exists to measure.
    """
    return """
        SELECT p.game_id, p.team, p.player_name, p.outs_recorded AS outs,
               p.er, p.k, p.bb, p.h, p.hr, g.date,
               CASE WHEN p.is_starter IS NOT NULL
                    THEN (CASE WHEN p.is_starter = 1 THEN 1 ELSE 2 END)
                    ELSE ROW_NUMBER() OVER (PARTITION BY p.game_id, p.team
                                            ORDER BY p.outs_recorded DESC)
               END AS rn
        FROM mlb_pitching p
        JOIN games g ON g.game_id = p.game_id
        WHERE p.outs_recorded IS NOT NULL
    """


def team_hook(as_of: str | None = None) -> dict[str, dict]:
    """Per-team workload profile: {team: {season..., recent..., used}}.

    `as_of` bounds the data to games strictly BEFORE that date, so a
    backtest cannot read a hook point computed partly from the game it is
    betting on. Defaults to today.
    """
    cutoff = as_of or date.today().isoformat()
    recent_from = (
        date.fromisoformat(cutoff) - timedelta(days=RECENT_DAYS)
    ).isoformat()

    sql = f"""
        WITH s AS ({_primary_cte()})
        SELECT team,
               COUNT(*)                                   AS n,
               AVG(outs)                                  AS avg_outs,
               SUM(outs >= 18) * 1.0 / COUNT(*)           AS pct_6ip,
               SUM(outs >= 15) * 1.0 / COUNT(*)           AS pct_5ip,
               SUM(CASE WHEN date >= ? THEN 1 ELSE 0 END) AS n_recent,
               AVG(CASE WHEN date >= ? THEN outs END)     AS avg_outs_recent,
               SUM(CASE WHEN date >= ? AND outs >= 18 THEN 1.0 ELSE 0 END)
                   / NULLIF(SUM(CASE WHEN date >= ? THEN 1 ELSE 0 END), 0)
                                                          AS pct_6ip_recent
        FROM s
        WHERE rn = 1 AND date < ?
        GROUP BY team
    """
    args = (recent_from,) * 4 + (cutoff,)
    out: dict[str, dict] = {}
    with db.connect() as conn:
        for r in conn.execute(sql, args):
            n_recent = r["n_recent"] or 0
            enough = n_recent >= MIN_RECENT_STARTS
            out[r["team"]] = {
                "team": r["team"],
                "starts": r["n"],
                "avg_outs": round(r["avg_outs"], 2) if r["avg_outs"] else None,
                "pct_6ip": round(r["pct_6ip"], 3) if r["pct_6ip"] else None,
                "pct_5ip": round(r["pct_5ip"], 3) if r["pct_5ip"] else None,
                "recent_days": RECENT_DAYS,
                "recent_starts": n_recent,
                "avg_outs_recent": (
                    round(r["avg_outs_recent"], 2)
                    if r["avg_outs_recent"] else None
                ),
                "pct_6ip_recent": (
                    round(r["pct_6ip_recent"], 3)
                    if r["pct_6ip_recent"] else None
                ),
                # Which number a reader should lead with. Both are always
                # present — the gap between them IS the signal when a club
                # has changed how it handles pitchers mid-season.
                "used": "recent" if enough else "season",
            }
    return out


def bullpen(as_of: str | None = None) -> dict[str, dict]:
    """Per-team relief usage and quality: {team: {...}}.

    Usage is the last USAGE_DAYS of relief outs — who is available. Quality
    is the trailing RECENT_DAYS of aggregate relief performance — whether
    availability matters.

    Everything here is derived from the same cached boxscores, which bounds
    what is knowable: there is no leverage index in `mlb_pitching`, so this
    cannot say "their closer threw 30 pitches yesterday", only how much
    relief work the unit absorbed. Nor can it produce xFIP or SIERA, which
    need batted-ball data the table does not carry.
    """
    cutoff = as_of or date.today().isoformat()
    usage_from = (
        date.fromisoformat(cutoff) - timedelta(days=USAGE_DAYS)
    ).isoformat()
    perf_from = (
        date.fromisoformat(cutoff) - timedelta(days=RECENT_DAYS)
    ).isoformat()

    sql = f"""
        WITH s AS ({_primary_cte()})
        SELECT team,
               SUM(CASE WHEN date >= ? THEN outs ELSE 0 END)  AS usage_outs,
               COUNT(DISTINCT CASE WHEN date >= ? THEN game_id END)
                                                              AS usage_games,
               SUM(CASE WHEN date >= ? THEN outs ELSE 0 END)  AS perf_outs,
               SUM(CASE WHEN date >= ? THEN er ELSE 0 END)    AS perf_er,
               SUM(CASE WHEN date >= ? THEN k  ELSE 0 END)    AS perf_k,
               SUM(CASE WHEN date >= ? THEN bb ELSE 0 END)    AS perf_bb,
               SUM(CASE WHEN date >= ? THEN h  ELSE 0 END)    AS perf_h,
               SUM(CASE WHEN date >= ? THEN hr ELSE 0 END)    AS perf_hr
        FROM s
        WHERE rn > 1 AND date < ?
        GROUP BY team
    """
    args = (usage_from, usage_from) + (perf_from,) * 6 + (cutoff,)

    def per9(x, outs):
        return round(x * 27.0 / outs, 2) if outs else None

    out: dict[str, dict] = {}
    with db.connect() as conn:
        for r in conn.execute(sql, args):
            po = r["perf_outs"] or 0
            uo = r["usage_outs"] or 0
            out[r["team"]] = {
                "team": r["team"],
                "usage_days": USAGE_DAYS,
                "usage_relief_ip": round(uo / 3.0, 1),
                "usage_games": r["usage_games"] or 0,
                # Innings per game over the window — the comparable number,
                # since a team may have played 2 or 4 games in three days.
                "usage_ip_per_game": (
                    round(uo / 3.0 / r["usage_games"], 2)
                    if r["usage_games"] else None
                ),
                "perf_days": RECENT_DAYS,
                "perf_relief_ip": round(po / 3.0, 1),
                "perf_era": per9(r["perf_er"], po),
                "perf_k9": per9(r["perf_k"], po),
                "perf_bb9": per9(r["perf_bb"], po),
                "perf_hr9": per9(r["perf_hr"], po),
                "perf_whip": (
                    round((r["perf_h"] + r["perf_bb"]) * 3.0 / po, 2)
                    if po else None
                ),
            }
    return out


if __name__ == "__main__":
    import sys
    as_of = sys.argv[1] if len(sys.argv) > 1 else None
    hooks = team_hook(as_of)
    pens = bullpen(as_of)
    print(f"HOOK — primary-pitcher workload ({len(hooks)} teams)")
    print(f"  {'team':<6}{'n':>4}{'season':>8}{'6IP%':>7}"
          f"{'n30':>5}{'last30':>8}{'6IP%':>7}  lead")
    for t, h in sorted(hooks.items(), key=lambda kv: -(kv[1]["avg_outs"] or 0)):
        print(f"  {t:<6}{h['starts']:>4}{h['avg_outs'] or 0:>8.1f}"
              f"{(h['pct_6ip'] or 0)*100:>6.0f}%{h['recent_starts']:>5}"
              f"{h['avg_outs_recent'] or 0:>8.1f}"
              f"{(h['pct_6ip_recent'] or 0)*100:>6.0f}%  {h['used']}")
    print(f"\nBULLPEN — usage ({USAGE_DAYS}d) and quality ({RECENT_DAYS}d)")
    print(f"  {'team':<6}{'IP/gm':>7}{'relIP':>7}{'ERA':>7}{'K/9':>6}"
          f"{'BB/9':>6}{'WHIP':>6}")
    for t, b in sorted(pens.items(), key=lambda kv: -(kv[1]["usage_ip_per_game"] or 0)):
        print(f"  {t:<6}{b['usage_ip_per_game'] or 0:>7.2f}"
              f"{b['perf_relief_ip']:>7.1f}{b['perf_era'] or 0:>7.2f}"
              f"{b['perf_k9'] or 0:>6.1f}{b['perf_bb9'] or 0:>6.1f}"
              f"{b['perf_whip'] or 0:>6.2f}")
