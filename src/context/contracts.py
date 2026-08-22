"""What each kind of bet needs before anyone can judge it.

This file is the answer to "what data is used to analyze each bet?" — a
question the system could not previously answer, because every bet received
the same ~52,000-character blob and the personas filled the gaps with
whatever web_search happened to return. Two bets on the same card could rest
on entirely different evidence, and the same bet could rest on different
evidence across runs.

A CONTRACT names the fields a bet type needs. It deliberately says nothing
about where they come from or how they are fetched — that is the assembler's
job. Keeping the two apart is what lets us ask, of any bet ever made,
"was the evidence for this complete?" and get a real answer.

Two rules that shape everything here:

  * REQUIRED means a bet cannot be honestly judged without it. If a required
    field is missing the assembler reports the hole rather than quietly
    shipping a partial brief — a silent gap is how a persona ends up writing
    three confident paragraphs about a line nobody checked.
  * Fields are declared once, in FIELDS, with the question each one answers.
    A field nobody can articulate a use for does not belong in a brief; it
    is just tokens.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    """One piece of evidence, and the question it exists to answer."""

    key: str
    scope: str          # game | starter | opponent | batter
    why: str
    # True ONLY when an adapter exists that the assembler can call today.
    # Not "the data looks reachable" — several of these were proven fetchable
    # with a throwaway probe and still have no adapter, and a flag that
    # counts a successful curl as done defeats the purpose of having it.
    # The assembler treats False as a known hole rather than a failure, so
    # contracts can be written ahead of the plumbing.
    implemented: bool = False


# ── the vocabulary ─────────────────────────────────────────────────────
# scope tells the assembler what to iterate: a 'game' field is fetched once
# per game, a 'starter' field once per probable pitcher, and so on.
FIELDS: dict[str, Field] = {f.key: f for f in [
    # -- game scope -----------------------------------------------------
    Field("market", "game",
          "The actual prices on offer. A thesis that ignores the number "
          "being paid is not a bet, it is an opinion.",
          implemented=True),  # grading.fetch_mlb_market
    Field("park_factors", "game",
          "Venue effect on runs, HR, strikeouts, walks and hits, 3-year "
          "rolling, 100 = average, with L/R splits. Kept as ONE field "
          "rather than split per index because Savant serves them all in "
          "one payload — but they diverge hard and a brief should say "
          "which one it means: Yankee Stadium is 118 for home runs and 102 "
          "for runs, Busch is 75 for home runs, T-Mobile is 116 for "
          "strikeouts against Kauffman's 89.",
          implemented=True),  # context.sources.park.for_venue
    Field("weather", "game",
          "Wind, temp, conditions. Only reliably present for outdoor parks "
          "close to first pitch; statsapi leaves it null otherwise.",
          implemented=True),  # panel.mlb_schedule_with_probables
    Field("team_situation", "game",
          "Record, games back, and elimination number for both clubs. The "
          "reason behind hook drift rather than the measurement of it: a "
          "team 7 from elimination hands prospects innings, a contender "
          "protects arms for October, and a club that has clinched rests "
          "everyone. workload_context sees the behaviour change; this says "
          "whether to expect it to continue.",
          implemented=True),  # context.sources.statsapi.standings
    # Side-scoped: each club arrives at a game with its own schedule
    # behind it, and a brief that averages the two describes neither.
    Field("rest_and_travel", "starter",
          "Days off, consecutive days played, miles flown and signed "
          "time-zone shift. Eastbound is positive because it costs more — "
          "the body arrives on a clock reading later than it is. Nearly "
          "free: the local games table already holds the schedule, only "
          "the thirty venue coordinates are fetched. On a mid-series day "
          "every club reads zero miles, which is the correct answer and "
          "not a missing value.",
          implemented=True),  # context.sources.rest.for_team
    Field("line_movement", "game",
          "The recorded path of this game's number across the day. Says "
          "whether money moved a line or a capper simply quoted it late, "
          "which stated-vs-current per bet cannot distinguish. Derived from "
          "stored snapshots rather than fetched — it was the single "
          "highest-coverage gap in the contract set and it turned out to be "
          "a storage decision. Empty until a date has two snapshots, and "
          "`first_seen` means first OBSERVED, not the true market open.",
          implemented=True),  # context.snapshot.line_movement
    Field("umpire", "game",
          "Plate umpire, plus K/BB tendencies derived from the games he has "
          "worked. THE TENDENCY HALF IS NOT USABLE YET and says so in its "
          "own payload: 1,113 games spread over 90 umpires is ~12 games "
          "each, only 4 clear a 15-game bar, and the apparent 77-118 K "
          "index range collapses to 90-99 once any sample requirement is "
          "applied. The assignment itself is solid. Every profile carries "
          "`reliable` and a caveat; a real version needs pitch-level "
          "called-strike data or several seasons of record.",
          implemented=True),  # context.sources.officials
    # Side-scoped for the same reason as rest: one club being down four
    # regulars is a fact about that club.
    Field("injuries", "starter",
          "Who is unavailable, from each club's 40-man status, plus IL "
          "moves in the last three days so a fresh scratch or activation "
          "shows. 276 players were out across the league when this was "
          "built, with five clubs down fourteen apiece. Zero of the "
          "cappers' props named an injured player — the real value is "
          "depletion context and keeping our OWN generated picks off "
          "players who cannot play.",
          implemented=True),  # context.sources.injuries

    # -- defence and receiving -----------------------------------------
    # Stored per SIDE, not per opponent: the catcher who matters for a
    # pitcher's strikeout line is his own battery mate, while for a batter
    # prop it is the catcher across the diamond. Both are present, and the
    # consumer picks the side its bet is about.
    Field("catcher_framing", "starter",
          "Framing runs and shadow-zone strike rate for the catcher "
          "receiving. A real signal, unlike the umpire half: the league "
          "spans +7.7 to -10.7 runs and 49.4% to 44.5% on takes, an "
          "18-run gap that lands directly on strikeout and walk props. "
          "Falls back to the club's primary catcher by pitches framed when "
          "no lineup is posted, flagged `estimated`.",
          implemented=True),  # context.sources.catcher.for_team
    # Side-scoped, like catcher_framing: the gloves that matter for a
    # pitcher's line are the ones behind HIM.
    Field("defense", "starter",
          "Outs Above Average for the club behind the pitcher, with "
          "directional and by-batter-hand splits. A hits-allowed or "
          "earned-runs line is partly a bet on the gloves and the spread "
          "is wide — the Cubs are +62 and the Mariners -45. Team level "
          "rather than a sum over the nine starting, so it needs no posted "
          "lineup.",
          implemented=True),  # context.sources.defense.for_team

    # -- starting pitcher scope ----------------------------------------
    Field("starter_game_log", "starter",
          "Last 10 starts: IP, ER, K, BB, H and PITCH COUNT. Pitch count is "
          "the one that matters for an outs prop — a 17-pitch-per-inning "
          "starter cannot reach the 6th on an 85-pitch leash.",
          implemented=True),  # statsapi.game_log
    Field("starter_percentiles", "starter",
          "Savant percentile ranks (xwOBA, xBA, K%, hard-hit). Says whether "
          "the surface ERA is earned or luck.",
          implemented=True),  # savant.starter_profile
    Field("starter_arsenal", "starter",
          "Per-pitch usage, whiff% and xwOBA. The mechanism behind a "
          "strikeout projection, rather than the projection alone.",
          implemented=True),  # panel.savant_pitcher_arsenal
    Field("starter_vs_opponent", "starter",
          "Career H2H against today's club: PA, H, TB, HR, K, BB. Kept "
          "optional in every contract and required by none, because the "
          "samples are too small to carry weight — three seasons against "
          "one club is routinely under 30 PA. opponent_profile answers the "
          "same question against a real sample. This is here to be looked "
          "at, not leaned on.",
          implemented=True),  # statsapi.vs_team
    Field("bullpen_state", "starter",
          "Relief innings and high-leverage arms used in recent days. One "
          "input to the hook, and a modest one — a gassed pen buys an extra "
          "batter, not an extra inning. The starter's own pitch-count "
          "pattern in starter_game_log carries far more of that question.",
          implemented=True),  # workload.bullpen
    Field("workload_context", "starter",
          "Innings cap, injury return, days rest, and the club's observed "
          "hook point. This is the rest of the picture bullpen_state only "
          "gestures at: Painter sat 6 weeks and has run 56-94 pitches a "
          "start, which bounds an outs line before any bullpen math.",
          implemented=True),  # workload.team_hook

    # -- opposing lineup scope -----------------------------------------
    Field("opponent_profile", "opponent",
          "Opposing club against this pitcher's handedness — K%, BB%, "
          "AVG/OBP/SLG — plus recent overall form. The right-hand column "
          "of a props-site matchup view, and the honest version of what a "
          "21-PA career head-to-head line pretends to answer. Carries the "
          "two windows separately because statsapi serves handedness OR a "
          "date range, never both; see opponent.py.",
          implemented=True),  # context.sources.opponent.profile
    Field("confirmed_lineup", "starter",
          "The nine names, posted. Before it drops, any batter-level read "
          "is a guess about who is even playing — so `posted` is arguably "
          "the single most useful bit in a brief, because it says whether "
          "the rest of the batter-side evidence describes this game or a "
          "typical one. Also names the receiver, which is what turns "
          "catcher_framing from a guess into a fact.",
          implemented=True),  # context.sources.lineup.lineups

    # -- individual batter scope ---------------------------------------
    Field("batter_xstats", "batter",
          "xwOBA/xBA/xSLG vs actuals — whether a hot streak is real.",
          implemented=True),  # panel.savant_batter_expected
    Field("batter_vs_pitcher", "batter",
          "Career head-to-head against today's starter. Included because "
          "it moves markets, not because it predicts: a typical pair has "
          "3-19 plate appearances, and Judge is .185 with a 51.5% K rate "
          "against Sale in 33. Every record carries its `pa` and an "
          "explicit caveat so the number cannot be read as more than it "
          "is. Attached only when a lineup is posted.",
          implemented=True),  # context.sources.batter.vs_pitcher
    Field("batter_vs_arsenal", "batter",
          "This hitter projected against THIS starter's actual pitch mix, "
          "by weighting his per-pitch-type results by the starter's usage. "
          "The answer head-to-head is reaching for, with real samples "
          "behind it. Judge projects .354 wOBA against Chris Sale and .474 "
          "against Framber Valdez — both left-handers, but Valdez is 45% "
          "sinkers and Judge sits at .556 against sinkers while Sale is "
          "40% sliders and Judge is .293 against those. A 120-point gap "
          "that neither a platoon split nor a 15-PA history can see. "
          "Carries `coverage` (share of the arsenal priced) and the "
          "per-pitch components.",
          implemented=True),  # context.sources.batter.vs_arsenal
    Field("batter_splits", "batter",
          "Season platoon split, with the side matching today's starter "
          "marked `facing` and the OPS gap computed. Real samples, unlike "
          "head-to-head — a regular carries 150-400 PA against righties. "
          "Judge walks 23.7% against lefties and 13.0% against righties, "
          "which the aggregate line hides entirely. Attached only when a "
          "lineup is posted.",
          implemented=True),  # context.sources.batter.for_hand
]}


@dataclass(frozen=True)
class Contract:
    """The evidence standard for one kind of bet."""

    name: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()

    def all_fields(self) -> tuple[str, ...]:
        return self.required + self.optional


# ── the contracts ──────────────────────────────────────────────────────
# Keyed by canonical stat where the stat changes what matters, and by
# bet_type otherwise. contract_for() resolves specific-before-general.

_PITCHER_CORE = (
    "market", "starter_game_log", "starter_percentiles", "starter_arsenal",
)

CONTRACTS: dict[str, Contract] = {
    # Both are workload questions before they are anything else — an outs
    # line is about how long he is allowed to go, and a strikeout line is a
    # rate applied to innings he has to actually pitch. So both require the
    # game log (pitch efficiency and observed depth) and workload_context
    # (cap, rest, hook point), and both lean on opponent_profile for the
    # lineup read.
    #
    # bullpen_state is OPTIONAL in both, not required. It is a real input to
    # the hook but a small one next to the starter's own pattern — a tired
    # pen buys a batter, not an inning. Requiring it would gate every
    # pitcher prop on the least decisive part of the picture.
    #
    # starter_vs_opponent is optional too, and for the opposite reason:
    # career H2H is the stat every capper cites and the one with the least
    # behind it. Painter vs STL was 21 PA across three seasons. The team's
    # splits against his handedness ask the same question with a sample
    # worth trusting, which is what opponent_profile is for. H2H stays
    # available because it moves lines, not because it predicts.
    "stat:outs": Contract(
        "pitcher outs",
        required=_PITCHER_CORE + ("workload_context", "opponent_profile"),
        optional=("bullpen_state", "starter_vs_opponent", "park_factors",
                  "weather", "team_situation",
                  "umpire", "catcher_framing", "line_movement",
                  "injuries", "rest_and_travel"),
    ),
    "stat:k": Contract(
        "pitcher strikeouts",
        required=_PITCHER_CORE + ("opponent_profile", "workload_context"),
        optional=("bullpen_state", "starter_vs_opponent", "park_factors",
                  "team_situation", "umpire",
                  "catcher_framing", "line_movement", "injuries"),
    ),
    "stat:er": Contract(
        "earned runs allowed",
        required=_PITCHER_CORE + ("park_factors",),
        optional=("opponent_profile", "weather", "starter_vs_opponent",
                  "defense", "line_movement",
                  "injuries"),
    ),
    "stat:h_allowed": Contract(
        "hits allowed",
        required=_PITCHER_CORE + ("opponent_profile",),
        optional=("park_factors", "starter_vs_opponent", "defense", "line_movement", "injuries"),
    ),
    "stat:bb_allowed": Contract(
        "walks allowed",
        required=_PITCHER_CORE + ("opponent_profile",),
        optional=("starter_vs_opponent", "umpire", "catcher_framing",
                  "line_movement", "injuries"),
    ),
    # Any pitcher prop without a specific standard of its own — 'decision'
    # (win/loss), 'r_allowed', 'hr_allowed'. Reusing the strikeout contract
    # here would demand arsenal-vs-chase data for a bet about who gets the
    # W, which is a workload and run-support question.
    "type:prop_pitcher": Contract(
        "pitcher prop (generic)",
        required=_PITCHER_CORE + ("workload_context",),
        optional=("opponent_profile", "bullpen_state", "park_factors",
                  "weather", "starter_vs_opponent", "team_situation", "line_movement", "injuries"),
    ),

    # Batter props hinge on the matchup and the environment; the batter's
    # own form is the least of it.
    # confirmed_lineup is REQUIRED here, unlike everywhere else. Until the
    # card is posted, every batter-side number describes a typical game for
    # this club rather than this one, and the batter a prop names may not be
    # playing at all. Predicting the lineup from recent starts is a real
    # project with real error, so the standing decision is to treat an
    # unposted lineup as a failed contract rather than estimate around it.
    "type:prop_batter": Contract(
        "batter prop",
        required=("market", "batter_xstats", "starter_arsenal",
                  "starter_percentiles", "park_factors",
                  "confirmed_lineup"),
        optional=("batter_vs_arsenal", "batter_splits",
                  "batter_vs_pitcher", "weather",
                  "catcher_framing", "umpire", "line_movement", "injuries"),
    ),

    # Totals are an environment question first and a pitching question
    # second — both bullpens matter as much as both starters.
    "type:total": Contract(
        "game total",
        required=("market", "park_factors", "weather", "starter_game_log",
                  "starter_percentiles", "bullpen_state"),
        optional=("opponent_profile", "starter_arsenal", "rest_and_travel",
                  "team_situation", "umpire", "defense", "line_movement",
                  "injuries", "confirmed_lineup"),
    ),
    "type:team_total": Contract(
        "team total",
        required=("market", "park_factors", "starter_game_log",
                  "starter_percentiles", "opponent_profile"),
        optional=("weather", "bullpen_state", "confirmed_lineup",
                  "defense", "umpire", "line_movement", "injuries"),
    ),
    "type:ml": Contract(
        "moneyline",
        required=("market", "starter_game_log", "starter_percentiles",
                  "bullpen_state", "opponent_profile"),
        optional=("park_factors", "weather", "rest_and_travel",
                  "team_situation", "defense", "line_movement",
                  "injuries", "confirmed_lineup"),
    ),
    "type:spread": Contract(
        "run line",
        required=("market", "starter_game_log", "starter_percentiles",
                  "bullpen_state", "opponent_profile"),
        optional=("park_factors", "weather", "rest_and_travel",
                  "team_situation", "defense", "line_movement",
                  "injuries", "confirmed_lineup"),
    ),
}

# Anything unrecognised still gets a floor, so a novel bet type produces a
# thin brief rather than no brief.
FALLBACK = Contract(
    "unclassified",
    required=("market",),
    optional=("park_factors", "starter_game_log", "weather"),
)

_PITCHER_STATS = {
    "outs", "k", "er", "r_allowed", "h_allowed", "bb_allowed", "hr_allowed",
    "decision",
}


def contract_for(
    bet_type: str | None, stat: str | None, sport: str = "mlb",
) -> Contract:
    """The evidence standard for one bet, most specific match first.

    A pitcher prop and a batter prop share bet_type='prop' but have almost
    nothing in common, so the stat has to be consulted before the type.

    Every contract here is MLB — the fields name probable starters, park
    factors and Savant. An NBA bet gets the floor rather than a basketball
    line dressed in baseball requirements, which is what happened when
    'pts+reb+ast' resolved to the batter-prop standard.
    """
    s = (stat or "").strip().lower()
    bt = (bet_type or "").strip().lower()
    if (sport or "").strip().lower() != "mlb":
        return FALLBACK

    if f"stat:{s}" in CONTRACTS:
        return CONTRACTS[f"stat:{s}"]
    if bt in ("prop", "combo"):
        # Combos ('h+r+rbi') are batter props unless every component is a
        # pitching stat, which is how 'k' resolves above before reaching here.
        parts = [p for p in s.split("+") if p]
        if parts and all(p in _PITCHER_STATS for p in parts):
            return CONTRACTS["type:prop_pitcher"]
        return CONTRACTS["type:prop_batter"]
    if f"type:{bt}" in CONTRACTS:
        return CONTRACTS[f"type:{bt}"]
    return FALLBACK


def unimplemented(contract: Contract) -> tuple[str, ...]:
    """Contract fields with no adapter yet — known holes, not failures."""
    return tuple(
        k for k in contract.all_fields()
        if k in FIELDS and not FIELDS[k].implemented
    )


def describe(contract: Contract) -> str:
    """Human-readable spec, for the CLI and for the MCP server to expose."""
    out = [f"{contract.name}:"]
    for label, keys in (("required", contract.required),
                        ("optional", contract.optional)):
        for k in keys:
            f = FIELDS.get(k)
            flag = "" if (f and f.implemented) else "  [NOT YET BUILT]"
            out.append(f"  {label:<8} {k:<22}{flag}")
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2:
        print(describe(contract_for(sys.argv[1], sys.argv[2])))
    else:
        seen = set()
        for key, c in CONTRACTS.items():
            if c.name in seen:
                continue
            seen.add(c.name)
            print(describe(c))
            print()
        n_todo = sum(1 for f in FIELDS.values() if not f.implemented)
        print(f"{len(FIELDS)} fields declared, {n_todo} awaiting an adapter.")
