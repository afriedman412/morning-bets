"""What the board's inputs say about ONE ARM, before any sims run.

    venv/bin/python -m src.context.arm "Robert Gasser" [DATE]
    venv/bin/python -m src.context.arm --parks [DATE]

Read-only. This hard-codes the checks that kept being retyped by hand —
and mistyped: `appearance_order` is 0-INDEXED (a `=1` filter counts
second pitchers and once reversed a swingman verdict), and a bare name
LIKE once merged Nick Sandlin into David Sandlin. Everything here goes
through the pitcher id.

Sections, in the order a "his line looks confusing" question gets asked:

  IDENTITY   every id matching the name; refuses to guess on a collision.
  STARTS     starts/apps by season (appearance_order = 0), so a swingman
             or opener flag can be checked against THIS season in one look.
  LOG        the current season's start log from the boxscores — K, outs,
             pitches — with the empirical over-rate at each half-K line.
  SPLIT      career home/road K per batter faced, with the se, so a park
             argument can be checked against the man himself.
  RATES      what the simulator is actually handed: the shrunk,
             park-NEUTRALISED k_pct (`NEUTRALISE_PARK`, rates.py), his
             counted park exposure, the raw rate, and tonight's velo kick.
  TONIGHT    if he is on the date's slate: the per-PA chain
             rate -> +velo -> x lineup (log5) -> x park, the expected mean
             K at his usual batters faced, and a binomial P(over) at the
             nearby lines. APPROXIMATE by construction — the board's
             20,000 sims are the number; this says where that number
             comes from.

The binomial in TONIGHT ignores the hook, TTO decay and base-out state,
so expect it a few points from the board. When it is FAR from the board,
that is the finding — one of the mechanisms this file skips is doing
something big, and the battery is where to look next.
"""

import math
import sys

from src.context import calibrate, sim, store, velo
from src.context.sources import rates as rate_src


# ---------------------------------------------------------------- queries

def ids_for(con, name: str) -> list[tuple[int, str]]:
    """Every (pitcher_id, exact_name) whose name contains `name`."""
    rows = con.execute(
        "select distinct pitcher_id, player_name from mlb_stints"
        " where player_name like ?", (f"%{name}%",)).fetchall()
    return [(r["pitcher_id"], r["player_name"]) for r in rows]


def resolve_name(cands: list[tuple[int, str]], name: str):
    """(pid, exact_name) or None — NEVER a guess on a collision.

    An exact (case-blind) match wins over any number of substring
    matches; several substring matches and no exact one is the Sandlin
    trap and resolves to nothing.
    """
    if not cands:
        return None
    exact = [c for c in cands if c[1].lower() == name.lower()]
    if exact:
        return exact[0]
    return cands[0] if len(cands) == 1 else None


def starts_by_season(con, pid: int) -> list[tuple[str, int, int]]:
    """[(year, starts, appearances)] — appearance_order 0 IS the start."""
    rows = con.execute(
        "select substr(date,1,4) yr,"
        "       sum(case when appearance_order=0 then 1 else 0 end) st,"
        "       count(*) ap"
        " from mlb_stints where pitcher_id=? group by yr order by yr",
        (pid,)).fetchall()
    return [(r["yr"], r["st"], r["ap"]) for r in rows]


def game_log(con, exact_name: str, season: str) -> list[dict]:
    """One row per boxscore line this season, oldest first."""
    rows = con.execute(
        "select g.date d, p.k, p.outs_recorded o, p.pitches pc,"
        "       p.is_starter st, p.h, p.bb"
        " from bets.mlb_pitching p join bets.games g on g.game_id=p.game_id"
        " where p.player_name=? and g.date like ? and g.sport='mlb'"
        " order by g.date",
        (exact_name, f"{season}-%")).fetchall()
    return [dict(d=r["d"], k=r["k"], o=r["o"], pc=r["pc"], st=r["st"],
                 bf=(r["o"] or 0) + (r["h"] or 0) + (r["bb"] or 0))
            for r in rows]


def home_road(con, exact_name: str) -> dict:
    """Career K/BF split by side, with the ratio's rough se."""
    rows = con.execute(
        "select case when p.team=g.home_team_abbr then 'home' else 'road'"
        "       end s, sum(p.k) k,"
        "       sum(p.outs_recorded + p.h + p.bb) bf"
        " from bets.mlb_pitching p join bets.games g on g.game_id=p.game_id"
        " where p.player_name=? and g.sport='mlb' group by s",
        (exact_name,)).fetchall()
    return {r["s"]: (r["k"] or 0, r["bf"] or 0) for r in rows}


# ------------------------------------------------------------ the report

def _line(s=""):
    print(s)


def report(name: str, date: str) -> None:
    with store.connect() as con:
        cands = ids_for(con, name)
        if not cands:
            _line(f"no pitcher matching {name!r} in mlb_stints")
            return
        hit = resolve_name(cands, name)
        if hit is None:
            _line(f"AMBIGUOUS — {name!r} matches "
                  f"{', '.join(n for _, n in cands)}. Use an exact name.")
            return
        pid, exact_name = hit
        if len(cands) > 1:
            _line(f"(name also matches "
                  f"{', '.join(n for i, n in cands if i != pid)} — "
                  f"reporting {exact_name} only)")

        _line(f"{exact_name}  (id {pid})  as of {date}")

        _line("\nSTARTS (appearance_order = 0; a flag on the board counts"
              " the WHOLE cache)")
        for yr, st, ap in starts_by_season(con, pid):
            _line(f"  {yr}  {st:>3} starts / {ap:>3} appearances")

        season = date[:4]
        log = game_log(con, exact_name, season)
        starts = [g for g in log if g["st"]]
        _line(f"\nLOG {season} — {len(starts)} starts"
              f" ({len(log) - len(starts)} relief lines not shown)")
        for g in starts:
            _line(f"  {g['d']}  K {g['k']:>2}  outs {g['o']:>2}"
                  f"  pitches {g['pc'] or '-':>3}")
        if starts:
            ks = [g["k"] for g in starts]
            mk = sum(ks) / len(ks)
            mbf = sum(g["bf"] for g in starts) / len(starts)
            mo = sum(g["o"] for g in starts) / len(starts)
            _line(f"  mean K {mk:.2f}   mean outs {mo:.1f}"
                  f"   mean batters {mbf:.1f}")
            for ln in range(max(1, int(mk) - 2), int(mk) + 4):
                over = sum(k > ln + 0.5 for k in ks)
                _line(f"    over {ln}.5: {over}/{len(ks)}"
                      f" = {over / len(ks):.0%}"
                      f"  (se {math.sqrt(0.25 / len(ks)):.0%})")

        hr = home_road(con, exact_name)
        if "home" in hr and "road" in hr and hr["road"][1]:
            (kh, bh), (kr, br) = hr["home"], hr["road"]
            if kh and kr:
                ratio = (kh / bh) / (kr / br)
                se = ratio * math.sqrt(1 / kh + 1 / kr)
                _line(f"\nSPLIT career  home {kh}/{bh} = {kh / bh:.3f}"
                      f"   road {kr}/{br} = {kr / br:.3f}"
                      f"   ratio {ratio:.2f} +/- {se:.2f}")

    lg = sim.league()
    pr = rate_src.pitcher_rates(lg, before=date)
    p = pr.get(exact_name)
    if not p:
        _line("\nRATES — none on record before this date; the board"
              " declines him")
        return
    exp = rate_src.park_exposure("pitcher", before=date).get(exact_name, {})
    kick = velo.kick_for(exact_name, date)
    _line(f"\nRATES as the simulator gets them (before {date})")
    _line(f"  k_pct {p['k_pct']:.4f} shrunk+park-neutralised"
          f"  (raw {p['raw_k_pct']:.4f}, {p['pa']} bf, {p['apps']} apps)")
    _line(f"  counted park exposure k {exp.get('k_pct', 1.0):.3f}"
          f"  (his rate was divided by this — NEUTRALISE_PARK)")
    _line(f"  velo kick {kick:+.4f} on k_pct   league k {lg['k_pct']:.4f}")

    tonight(exact_name, date, p, lg, kick)


def tonight(exact_name, date, p, lg, kick) -> None:
    """The per-PA chain for tonight's matchup, if he is on the slate."""
    from src.context import slate as sl
    try:
        games = sl.slate(date)
    except Exception as e:
        _line(f"\nTONIGHT — slate unavailable ({type(e).__name__}: {e})")
        return
    g = pick = side = None
    for g in games:
        for s, o in (("away", "home"), ("home", "away")):
            if g[s].get("starter") == exact_name:
                pick, side = g, s
                break
        if pick:
            break
    if not pick:
        _line(f"\nTONIGHT — not a probable on the {date} slate")
        return
    opp = pick["home" if side == "away" else "away"]
    names = opp["lineup"] or sl.projected_lineup(opp["abbr"], date)
    posted = "posted" if opp["lineup"] else "PROJECTED"
    br = rate_src.batter_rates(lg, before=date)
    league_bat = sim.BatterRates(
        name="league", k_pct=lg["k_pct"], bb_pct=lg["bb_pct"],
        hr_pct=lg["hr_pct"], babip=lg["babip"])
    nine = sl._build(names, br, league_bat)
    lk = sum(b.k_pct for b in nine) / len(nine)
    park = (calibrate.park_for(pick["venue_id"])
            if calibrate.USE_PARK else None) or sim.NEUTRAL_PARK

    base = p["k_pct"] + kick
    log5 = base * lk / lg["k_pct"]
    per_pa = log5 * park["k"]
    _line(f"\nTONIGHT vs {opp['abbr']} ({posted} lineup),"
          f" venue {pick['venue_id']}")
    _line(f"  {p['k_pct']:.4f} rate  {kick:+.4f} velo"
          f"  x {lk / lg['k_pct']:.3f} lineup (nine avg {lk:.3f})"
          f"  x {park['k']:.2f} park  =  {per_pa:.4f} per PA")
    # Binomial at his usual workload — no hook, no TTO, no base-out
    # state. See the module docstring for what a big gap to the board
    # means; the board's sims are the number.
    n = 22
    mean_k = per_pa * n
    _line(f"  at {n} batters: mean K {mean_k:.2f}  (approx; board sims"
          f" carry the hook and TTO)")
    for ln in (3, 4, 5, 6, 7):
        pov = 1.0 - _binom_cdf(ln, n, per_pa)
        _line(f"    ~P(over {ln}.5) {pov:.0%}")


def _binom_cdf(k, n, p) -> float:
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i)
               for i in range(0, k + 1))


# ------------------------------------------------------------- the slate

def parks(date: str) -> None:
    """Every venue on the date's slate whose K or HR factor is not ~1."""
    from src.context import slate as sl
    games = sl.slate(date)
    _line(f"park factors, {date} slate (imported Savant; MIL's k 1.11"
          f" verified ~1.10 by count, NOTES 2026-09-13)")
    for g in games:
        pf = calibrate.park_for(g["venue_id"]) if g["venue_id"] else None
        if not pf:
            _line(f"  {g['away']['abbr']:>3} @ {g['home']['abbr']:<3}"
                  f"  no factors (neutral)")
            continue
        flag = "  <-- " if (abs(pf["k"] - 1) > 0.05
                            or abs(pf["hr"] - 1) > 0.05) else ""
        _line(f"  {g['away']['abbr']:>3} @ {g['home']['abbr']:<3}"
              f"  k {pf['k']:.2f}  hr {pf['hr']:.2f}  bb {pf['bb']:.2f}"
              f"{flag}")


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    date = next((a for a in args if len(a) == 10 and a[4] == "-"),
                None)
    if date is None:
        from datetime import date as _d
        date = _d.today().isoformat()
    if "--parks" in argv:
        parks(date)
        return
    name = next((a for a in args if not (len(a) == 10 and a[4] == "-")),
                None)
    if not name:
        _line(__doc__.split("\n\n")[0])
        _line('usage: -m src.context.arm "Name" [YYYY-MM-DD] | --parks')
        return
    report(name, date)


if __name__ == "__main__":
    main(sys.argv[1:])
