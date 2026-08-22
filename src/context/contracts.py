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
    Field("rest_and_travel", "game",
          "Days off and time-zone movement for both clubs — the "
          "day-after-a-night-game lineup is a real and cheap edge. "
          "Derivable from the local games table plus venue coordinates."),
    Field("line_movement", "game",
          "Where the number opened against where it sits now. The system "
          "records stated-vs-current per bet, but never the market's own "
          "path, which is the part that says whether money moved a line or "
          "a capper simply quoted it late. Needs repeated market snapshots "
          "over a day — a storage decision, not a fetch."),
    Field("umpire", "game",
          "Plate umpire and their called-strike tendencies. Named in "
          "Cynic's own system prompt as its edge and never once supplied. "
          "Assignments publish the morning of; statsapi carries officials "
          "on the boxscore, which may be too late to help."),
    Field("injuries", "game",
          "IL moves and late scratches for both clubs. A brief built "
          "before a scratch is not wrong so much as stale, and there is "
          "currently no way to tell which one you are reading."),

    # -- defence and receiving -----------------------------------------
    Field("catcher_framing", "opponent",
          "Framing runs for the catcher actually starting. Moves called "
          "strikes by a wide margin at the extremes, which lands directly "
          "on strikeout and walk props. Savant publishes it; the blocker "
          "is knowing who is catching, i.e. confirmed_lineup."),
    Field("defense", "opponent",
          "Outs Above Average behind the pitcher. A hits-allowed or "
          "earned-runs line is partly a bet on the gloves, and nothing in "
          "the brief currently mentions them."),
    Field("times_through_order", "starter",
          "Splits for the first, second and third pass through a lineup. "
          "The TTO penalty is one of the few large, well-established "
          "effects in pitching, and it is the mechanism behind the hook "
          "that workload_context can only measure from the outside."),

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
    Field("confirmed_lineup", "opponent",
          "Posted lineup. Before it drops, any batter-level read is a "
          "guess about who is even playing.",
          implemented=False),

    # -- individual batter scope ---------------------------------------
    Field("batter_xstats", "batter",
          "xwOBA/xBA/xSLG vs actuals — whether a hot streak is real.",
          implemented=True),  # panel.savant_batter_expected
    Field("batter_vs_pitcher", "batter",
          "This batter against today's starter. Tiny samples; included "
          "because it moves lines, not because it predicts much.",
          implemented=False),
    Field("batter_splits", "batter",
          "Platoon split. A lefty mashing lefties is the exception the "
          "aggregate line hides.",
          implemented=False),
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
                  "weather", "team_situation", "times_through_order",
                  "umpire", "catcher_framing", "line_movement",
                  "injuries", "rest_and_travel"),
    ),
    "stat:k": Contract(
        "pitcher strikeouts",
        required=_PITCHER_CORE + ("opponent_profile", "workload_context"),
        optional=("bullpen_state", "starter_vs_opponent", "park_factors",
                  "team_situation", "times_through_order", "umpire",
                  "catcher_framing", "line_movement", "injuries"),
    ),
    "stat:er": Contract(
        "earned runs allowed",
        required=_PITCHER_CORE + ("park_factors",),
        optional=("opponent_profile", "weather", "starter_vs_opponent",
                  "defense", "times_through_order", "line_movement",
                  "injuries"),
    ),
    "stat:h_allowed": Contract(
        "hits allowed",
        required=_PITCHER_CORE + ("opponent_profile",),
        optional=("park_factors", "starter_vs_opponent", "defense",
                  "times_through_order", "line_movement", "injuries"),
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
                  "weather", "starter_vs_opponent", "team_situation",
                  "times_through_order", "line_movement", "injuries"),
    ),

    # Batter props hinge on the matchup and the environment; the batter's
    # own form is the least of it.
    "type:prop_batter": Contract(
        "batter prop",
        required=("market", "batter_xstats", "starter_arsenal",
                  "starter_percentiles", "park_factors"),
        optional=("batter_splits", "batter_vs_pitcher", "weather",
                  "confirmed_lineup", "catcher_framing", "umpire",
                  "line_movement", "injuries"),
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
