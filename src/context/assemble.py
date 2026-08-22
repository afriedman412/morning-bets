"""Build one slate's evidence, deterministically, before anyone reasons over it.

This is the piece that replaces "the persona web_searched whatever it thought
of". Same slate in, same brief out — which is what makes a card reproducible,
a backtest honest, and the question "was the evidence complete for pick #3"
answerable at all.

SHAPE. A snapshot is slate-level, with game records inside it:

    snapshot
      ├─ league          data that is identical for every game, stored once:
      │                  park factors, standings, batter xstats, arsenals
      └─ games[]         per game: market, weather, and two `sides`, each
                         carrying its starter, that starter's team workload
                         and bullpen, and the profile of the lineup he faces

Nothing here is stored per BET. A bet does not change the facts about its
game, so per-bet storage would duplicate the same payload for every capper
who called the same total and invite the copies to drift apart. Coverage —
which contract fields a given bet actually got — is computed as a view over
this, in `coverage()`.

COST. Roughly eight network calls per game (two game logs, two H2H, four
opponent splits) plus a handful of slate-wide fetches. Everything is cached
by date, and the per-game work is fanned out with src.parallel, so a 15-game
slate assembles in seconds rather than minutes. Every write happens on the
calling thread; the workers only fetch.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from src import parallel, roster
from src.context import contracts
from src.context.sources import opponent, park, savant, statsapi, workload

# Bumped whenever the shape or content of a snapshot changes in a way that
# makes two snapshots non-comparable. The eval harness keys on this: without
# it, "context v1 vs v2" silently compares briefs built by different rules.
CONTEXT_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _abbr_by_id(team_ids: dict[str, int]) -> dict[int, str]:
    """Invert {'AZ': 109} to {109: 'AZ'}.

    The only place a club name is still needed is the local boxscore cache,
    which stores abbreviations. Everything upstream now travels as an id,
    because matching 'Arizona Diamondbacks' against a standings row reading
    'D-backs' silently cost that club its situation, workload, bullpen AND
    its opponent's matchup profile — four holes from one string compare.
    """
    return {v: k for k, v in (team_ids or {}).items()}


def _market_for(matchup: str, market: list[dict]) -> dict | None:
    from src.grading import same_party
    for g in market or []:
        if same_party(g.get("away_team"), matchup) and \
                same_party(g.get("home_team"), matchup):
            return g
    return None


def _side(
    starter_name: str | None, own_abbr: str | None, opp_abbr: str | None,
    opp_team_id: int | None, season: int, as_of: str,
    hooks: dict, pens: dict, standings: dict, arsenals: dict,
    is_home: bool = False, neutral: bool = False,
) -> dict:
    """One half of a game: the starter, his club's state, the lineup he faces.

    Every lookup degrades to None rather than raising. A slate where one
    pitcher is unresolvable should produce a brief with one hole in it, not
    no brief — and the hole is exactly what coverage() is for.
    """
    out: dict = {
        "team": own_abbr,
        # The raw fact and how to use it, kept separate. At a neutral site
        # neither club is really home — nobody has slept in their own bed or
        # hit in that batter's eye all season — so both sides read as away
        # for any home/road split, while is_home still records which dugout
        # they occupied.
        "is_home": is_home,
        "home_road": "away" if neutral else ("home" if is_home else "away"),
        "neutral_site": neutral,
        "starter": {"name": starter_name},
        "team_situation": standings.get(own_abbr),
        "workload_context": hooks.get(own_abbr),
        "bullpen_state": pens.get(own_abbr),
    }
    if not starter_name:
        return out

    pid = roster.player_id(starter_name)
    hand = roster.throws(starter_name)
    out["starter"].update({"id": pid, "throws": hand})

    if pid:
        try:
            log = statsapi.game_log(pid, season, as_of)
            out["starter"]["starter_game_log"] = {
                "starts": log,
                "summary": statsapi.game_log_summary(log),
            } if log else None
        except Exception:
            out["starter"]["starter_game_log"] = None
        if opp_team_id:
            try:
                out["starter"]["starter_vs_opponent"] = statsapi.vs_team(
                    pid, opp_team_id, [season],
                )
            except Exception:
                out["starter"]["starter_vs_opponent"] = None

    try:
        out["starter"]["starter_percentiles"] = savant.starter_profile(
            starter_name, season, as_of,
        )
    except Exception:
        out["starter"]["starter_percentiles"] = None

    # Arsenal is already indexed league-wide by the existing panel fetcher.
    out["starter"]["starter_arsenal"] = arsenals.get(
        (starter_name or "").lower().strip()
    )

    # The lineup this starter has to get out.
    if opp_abbr:
        try:
            out["opponent_profile"] = opponent.profile(
                opp_abbr, hand, season, as_of,
            )
        except Exception:
            out["opponent_profile"] = None
    return out


def assemble(
    date_str: str | None = None, as_of: str | None = None,
) -> dict:
    """Build the full snapshot for one slate.

    `as_of` bounds every backward-looking lookup and defaults to the slate
    date, so assembling 2026-07-04 today produces the brief that date could
    honestly have had — no game logs from games not yet played.
    """
    from src import panel
    from src.grading import fetch_mlb_market

    d = date_str or date.today().isoformat()
    cutoff = as_of or d
    season = datetime.strptime(d, "%Y-%m-%d").year

    slate = panel.mlb_schedule_with_probables(d)
    if not slate:
        return {"date": d, "context_version": CONTEXT_VERSION,
                "assembled_at": _now(), "league": {}, "games": []}

    # ── slate-wide, fetched once ──────────────────────────────────────
    def _safe(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:
            print(f"  !! {getattr(fn, '__name__', fn)} failed: {e}")
            return None

    standings = _safe(statsapi.standings, season, cutoff) or {}
    hooks = _safe(workload.team_hook, cutoff) or {}
    pens = _safe(workload.bullpen, cutoff) or {}
    parks = _safe(park.park_factors, season, "All", cutoff) or {}
    market = _safe(fetch_mlb_market, d) or []
    arsenals = _safe(
        lambda: panel._pitcher_arsenal_blob(
            panel.savant_pitcher_arsenal(season, cutoff))) or {}
    batters = _safe(
        lambda: panel._batter_blob(
            panel.savant_batter_expected(season, cutoff))) or {}
    team_ids = _safe(opponent.team_ids, season) or {}

    league = {
        "park_factors": {v["venue"]: v for v in parks.values()},
        "standings": standings,
        "batter_xstats": batters,
        "starter_arsenals": arsenals,
    }

    # ── per game, fanned out ──────────────────────────────────────────
    by_id = _abbr_by_id(team_ids)

    def _one(g: dict) -> dict:
        away_id, home_id = g.get("away_team_id"), g.get("home_team_id")
        away, home = by_id.get(away_id), by_id.get(home_id)
        venue_id = g.get("venue_id")
        pf = park.for_venue(venue_id=venue_id, year=season,
                            as_of=cutoff) if parks and venue_id else None
        rec = {
            "game_id": g.get("game_id"),
            "matchup": g.get("matchup"),
            "start_time": g.get("start_time"),
            "venue": g.get("venue"),
            "venue_id": venue_id,
            # A game at a venue Savant does not rank is a neutral site, not
            # a lookup failure. Saying so keeps a reader from assuming the
            # brief simply forgot, and keeps the home club's park factors
            # from being quietly substituted.
            "neutral_site": bool(venue_id and parks and not pf),
            "weather": g.get("weather"),
            "market": _market_for(g.get("matchup", ""), market),
            "park_factors": pf,
        }
        neutral = rec["neutral_site"]
        rec["sides"] = {
            "away": _side(g.get("away_probable"), away, home, home_id,
                          season, cutoff, hooks, pens, standings, arsenals,
                          is_home=False, neutral=neutral),
            "home": _side(g.get("home_probable"), home, away, away_id,
                          season, cutoff, hooks, pens, standings, arsenals,
                          is_home=True, neutral=neutral),
        }
        return rec

    games = []
    for g, got, err in parallel.gather(_one, slate, workers=4):
        if err:
            print(f"  !! {g.get('matchup')} failed: {err}")
            continue
        games.append(got)

    return {
        "date": d,
        "as_of": cutoff,
        "context_version": CONTEXT_VERSION,
        "assembled_at": _now(),
        "league": league,
        "games": games,
    }


# ── coverage: the contract check ───────────────────────────────────────
def _present(value) -> bool:
    """A field counts as present only if it carries something.

    An empty dict or list is what a failed lookup leaves behind, and
    counting it as covered would make the whole exercise decorative.
    """
    if value is None:
        return False
    if isinstance(value, (dict, list, str)) and len(value) == 0:
        return False
    return True


def _game_for(bet: dict, snapshot: dict) -> dict | None:
    from src.grading import same_party
    m = bet.get("matchup") or ""
    for g in snapshot.get("games", []):
        if g.get("matchup") == m:
            return g
    for g in snapshot.get("games", []):
        gm = g.get("matchup") or ""
        if gm and same_party(gm.split(" @ ")[0], m) and \
                same_party(gm.split(" @ ")[-1], m):
            return g
    return None


def _lookup(field: str, bet: dict, game: dict, snapshot: dict):
    """Pull one contract field for one bet out of the snapshot."""
    if field in ("market", "weather", "park_factors"):
        return game.get(field)
    if field == "team_situation":
        return [s.get("team_situation") for s in game["sides"].values()]
    if field == "batter_xstats":
        name = (bet.get("player_name") or "").lower().strip()
        return snapshot["league"]["batter_xstats"].get(name)

    sides = list(game.get("sides", {}).values())
    # A pitcher prop resolves to the side whose starter is the named player;
    # everything else needs the field on BOTH sides to count as covered,
    # since a total depends on two starters and two bullpens.
    who = (bet.get("player_name") or "").lower().strip()
    mine = [s for s in sides
            if (s.get("starter", {}).get("name") or "").lower().strip() == who]
    targets = mine or sides

    def get(s):
        return (s.get("starter", {}).get(field)
                if field.startswith("starter_") else s.get(field))

    vals = [get(s) for s in targets]
    return vals if len(vals) > 1 else (vals[0] if vals else None)


def coverage(bet: dict, snapshot: dict) -> dict:
    """Which of this bet's contract fields the snapshot actually supplies.

    Optional fields are listed but do NOT count against the score — a brief
    that reports 60% because it lacks head-to-head trivia trains the reader
    to ignore the number.
    """
    c = contracts.contract_for(
        bet.get("bet_type"), bet.get("stat"), bet.get("sport") or "mlb",
    )
    game = _game_for(bet, snapshot)
    if not game:
        return {"contract": c.name, "game_found": False, "score": 0.0,
                "missing_required": list(c.required), "present": [],
                "missing_optional": list(c.optional)}

    present, missing_req, missing_opt = [], [], []
    for field in c.all_fields():
        vals = _lookup(field, bet, game, snapshot)
        ok = (all(_present(v) for v in vals) if isinstance(vals, list) and vals
              else _present(vals))
        if ok:
            present.append(field)
        elif field in c.required:
            missing_req.append(field)
        else:
            missing_opt.append(field)

    return {
        "contract": c.name,
        "game_found": True,
        "score": round(
            (len(c.required) - len(missing_req)) / len(c.required), 2
        ) if c.required else 1.0,
        "present": present,
        "missing_required": missing_req,
        "missing_optional": missing_opt,
    }


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    snap = assemble(d)
    print(f"\nsnapshot {snap['date']} v{snap['context_version']}: "
          f"{len(snap['games'])} games, "
          f"{len(json.dumps(snap)) / 1024:.0f} KB")
    for g in snap["games"][:3]:
        a, h = g["sides"]["away"], g["sides"]["home"]
        pf = g.get("park_factors") or {}
        print(f"\n  {g['matchup']}  ({g.get('venue')})")
        print(f"    park runs {pf.get('runs')} hr {pf.get('hr')} "
              f"so {pf.get('so')} | market {'yes' if g.get('market') else 'no'}")
        for lbl, s in (("away", a), ("home", h)):
            st = s.get("starter", {})
            gl = (st.get("starter_game_log") or {}).get("summary") or {}
            op = s.get("opponent_profile") or {}
            wl = s.get("workload_context") or {}
            print(f"    {lbl} {str(st.get('name'))[:22]:<24}"
                  f"{str(st.get('throws')):<3}"
                  f"P/IP {str(gl.get('avg_pitches_per_inning')):<6}"
                  f"hook {str(wl.get('avg_outs_recent')):<6}"
                  f"opp K% {str((op.get('vs_hand') or {}).get('k_pct'))}")
