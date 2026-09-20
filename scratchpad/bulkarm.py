"""STEP ZERO of PLAN-opener-bullpen.md: is the bulk arm predictable?

QUESTION. After a short start (order-0 stint, <= 6 outs), is WHO follows
predictable the morning of — or a coin flip among the club's relievers?

HYPOTHESIS. Clubs that use openers pair them with a designated bulk arm,
so the follower repeats within a club-season.

TEST. Self-join `mlb_stints` order 0 -> order 1 on (game_id, team).
`appearance_order` IS 0-INDEXED — order 0 is the starter. Sanity-check the
event count against the ~1,143 short starts the sizing table predicts.
Three numbers:
  1. Chronological hit rate: predict the follower is the modal follower of
     the club-season's PRIOR short starts; score on events with >= 1 prior.
  2. Split-half reliability of the per-arm follower share within a
     club-season (odd vs even events, Pearson over (club-season, arm)).
  3. The same estimator on synthetic data — a POSITIVE control with a true
     60%-share bulk arm and a NULL control drawing uniformly from six arms
     — because a mis-specified harness and an absent effect look identical.

PRE-REGISTERED BAR (from the plan): split-half r > +0.40, judged after the
controls locate what the estimator returns under truth and under nothing.

POWER, stated before the result: ~1,200 events over ~120 club-seasons is
~10 per club-season, ~5 per half. Thin. The pooled correlation over every
(club-season, arm) row is the high-n ratio; per-club tables are display.
"""
from collections import defaultdict

from src.context import store


def events(con):
    q = """
      select s.game_id, s.date, s.team, substr(s.date, 1, 4) season,
             s.player_name opener, s.outs_recorded opener_outs,
             f.player_name follower, f.outs_recorded follower_outs
      from mlb_stints s
      join mlb_stints f on f.game_id = s.game_id and f.team = s.team
                        and f.appearance_order = 1
      where s.appearance_order = 0 and s.outs_recorded <= 6
      order by s.date, s.game_id
    """
    return [dict(r) for r in con.execute(q)]


def by_club_season(rows):
    g = defaultdict(list)
    for r in rows:
        g[(r["team"], r["season"])].append(r)
    return g


def hit_rate(groups):
    """Predict each follower as the modal PRIOR follower, chronologically."""
    hits = tries = 0
    for evs in groups.values():
        seen = defaultdict(int)
        for e in evs:
            if seen:
                best = max(seen.values())
                modal = [a for a, n in seen.items() if n == best]
                tries += 1
                hits += e["follower"] in modal and 1 / len(modal)
            seen[e["follower"]] += 1
    return hits / tries if tries else float("nan"), tries


def split_half(groups, min_events=4):
    """Per-arm follower share, odd vs even events, pooled Pearson."""
    xs, ys = [], []
    for evs in groups.values():
        if len(evs) < min_events:
            continue
        a, b = evs[0::2], evs[1::2]
        arms = {e["follower"] for e in evs}
        for arm in arms:
            xs.append(sum(e["follower"] == arm for e in a) / len(a))
            ys.append(sum(e["follower"] == arm for e in b) / len(b))
    return pearson(xs, ys), len(xs)


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if not sx or not sy:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def controls(groups, share, seed=7):
    """Same club-season event counts, synthetic followers.

    `share` is the true bulk arm's follower share; the other five arms
    split the rest. share=1/6 is the uniform NULL.
    """
    import random
    rng = random.Random(seed)
    fake = {}
    for key, evs in groups.items():
        arms = [f"arm{i}" for i in range(6)]
        rows = []
        for e in evs:
            r = rng.random()
            pick = arms[0] if r < share else arms[1 + rng.randrange(5)]
            rows.append({"follower": pick})
        fake[key] = rows
    return fake


def opener_only(con, rows):
    """Restrict to short starts by KNOWN openers (season avg outs < 11).

    The full population pools planned openers with shelled starters, and a
    disaster's mop-up man is genuinely random — a real opener->bulk pairing
    could be drowned in it. Same cell `slate.priceable` gates on. Season
    average rather than trailing is fine for a gate count; morning-of the
    live gate already knows who the openers are.
    """
    q = """
      select player_name, substr(date, 1, 4) season,
             avg(outs_recorded) avg_outs, count(*) n
      from mlb_stints where appearance_order = 0
      group by player_name, season
    """
    avg = {(r["player_name"], r["season"]): r["avg_outs"]
           for r in con.execute(q)}
    return [r for r in rows if avg[(r["opener"], r["season"])] < 11.0]


def report(tag, rows):
    groups = by_club_season(rows)
    n = len(rows)
    print(f"== {tag} ==")
    print(f"{n} short starts with an identified follower")
    seasons = defaultdict(int)
    for r in rows:
        seasons[r["season"]] += 1
    print("  per season:", dict(sorted(seasons.items())))
    op = sum(r["opener_outs"] for r in rows) / n
    fo = sum(r["follower_outs"] for r in rows) / n
    print(f"  opener outs {op:.2f}, follower outs {fo:.2f} "
          f"(normal first reliever: 3.96)")
    sizes = sorted(len(v) for v in groups.values())
    print(f"  {len(groups)} club-seasons, events per club-season "
          f"median {sizes[len(sizes) // 2]}, max {sizes[-1]}")

    hr, tries = hit_rate(groups)
    print(f"\nHIT RATE, modal prior follower within club-season: "
          f"{hr:.3f} on {tries} predictable events "
          f"(six-arm coin flip: 0.167)")

    r, pairs = split_half(groups)
    print(f"SPLIT-HALF r (per-arm follower share, odd/even events): "
          f"{r:+.3f} over {pairs} (club-season, arm) rows")

    for label, share in (("POSITIVE control (true 60% bulk arm)", 0.60),
                         ("NULL control (uniform six arms)", 1 / 6)):
        fk = controls(groups, share)
        cr, cp = split_half(fk)
        chr_, ct = hit_rate(fk)
        print(f"{label}: split-half r {cr:+.3f} over {cp}, "
              f"hit rate {chr_:.3f} on {ct}")

    print()


def main():
    with store.connect() as con:
        rows = events(con)
        planned = opener_only(con, rows)
    report("ALL short starts <= 6 outs (sanity bar ~1,143-1,220)", rows)
    report("PLANNED openers only (starter's season avg outs < 11)", planned)
    print("PRE-REGISTERED BAR: r > +0.40 against where the controls land.")


if __name__ == "__main__":
    main()
