# REFERENCE — baseball betting rules of thumb, tested

Folk wisdom from the betting world, each one **re-counted on our own four
seasons** (10,166 finished games, 2023-03-15 to 2026-09-09) rather than
taken on faith. Built 2026-09-10.

**THIS IS ORIENTATION, NOT A SOURCE OF CONSTANTS.** CLAUDE.md rule 4 is
"count it, do not import it," and every imported baseball effect in this
project's history has measured zero. A number below is a HYPOTHESIS worth
counting properly, never a value to wire in. And every figure here is
counted across the full span INCLUDING the holdout, because it is
descriptive — **anything promoted to a model input must be re-counted with
`date < HOLDOUT` first** (rule 6).

Sources for the claims are listed at the bottom.

---

## 1. KEY NUMBERS ARE REAL, AND ODD BEATS EVEN — CONFIRMED, LARGE

The claim: 7, 9 and 5 are key numbers; odd totals hit more often than even
because a game cannot end in a tie.

**Confirmed, and the effect is big.** Odd totals **58.34%**, even
**41.66%** — a 17-point asymmetry over 10,166 games.

```
 total   games   share
     5     986   9.70%  #####################   odd
     6     744   7.32%  ################
     7    1129  11.11%  ########################   odd   <- most common total
     8     770   7.57%  ################
     9     974   9.58%  #####################   odd
    10     681   6.70%  ##############
    11     744   7.32%  ################   odd
    12     500   4.92%  ##########
```

The mechanism is sound: a tie forces extras, and extras almost always add
runs to one side only, so the even outcome gets converted away. 7-0, 6-1,
5-2 and 4-3 are all common finals.

## 2. "THE DIFFERENCE BETWEEN 8.5 AND 9 IS HUGE" — CONFIRMED, 9.58 POINTS

This is the operator's own example and it is right. The half-run is worth
exactly the probability mass it steps across, and that mass zigzags:

| move | mass crossed | worth |
|---|---|---|
| 6.5 → 7.0 | total = 7 | **11.11%** |
| 7.5 → 8.0 | total = 8 | 7.57% |
| 8.5 → 9.0 | total = 9 | **9.58%** |
| 9.5 → 10.0 | total = 10 | 6.70% |
| 10.5 → 11.0 | total = 11 | **7.32%** |

Going from 8.5 to 9 converts 9.58% of outcomes from a decision into a
push. For the OVER that turns wins into pushes and is bad; for the UNDER it
turns losses into pushes and is good. Buying the half-run off 8.5 is worth
**27% more** than buying it off 7.5, for the same nominal half-run.

**The corollary that matters more:** a total quoted at 7, 9 or 11 carries a
7-11% push, so a bet there resolves as a refund about one time in ten —
which also makes it a weak data point for any record you keep. BETTING.md
records this from the other end: COL/NYY implied P(total = 9) = 11.5%, so
about one ticket in nine refunded.

## 3. "TEAMS LEADING AFTER 5 WIN ~85%" — WRONG, AND THE AGGREGATE IS USELESS

**MEASURED: 81.9%** over 8,626 games with a lead after five (se 0.41), so
the folk number is about 7 se too high.

But the aggregate is the real problem — it averages together two completely
different situations:

| lead after 5 | games | win% |
|---|---|---|
| 1 run | 2,520 | **65.2%** |
| 2 runs | 1,957 | 80.1% |
| 3 runs | 1,425 | 88.0% |
| 4 runs | 967 | 91.7% |
| 5+ runs | 1,757 | 97.5% |

A one-run lead after five is barely better than a coin flip plus a third.
Quoting 85% at someone holding a one-run lead is off by twenty points. And
15.1% of games are TIED after five, which the claim silently drops.

This is CLAUDE.md rule 12 in the wild: prefer a high-n ratio to a low-n
aggregate, and name the denominator.

## 4. TEMPERATURE — DIRECTIONALLY RIGHT, BADLY CONFOUNDED

The claim: games at 85F+ produce 0.3-0.5 more runs than games at 65F.

Naively pooled across parks, the effect looks **more than twice** the
claimed size — and most of that is not temperature:

| | naive, pooled | within venue |
|---|---|---|
| under 60F | 8.46 runs | -0.45 |
| 60-69F | 8.55 | -0.31 |
| 70-79F | 9.01 | +0.06 |
| 80-84F | 9.35 | +0.16 |
| 85F+ | 9.83 | **+0.44** |
| **85F+ minus 60-69F** | **+1.28 runs** | **+0.75 runs** |

Pooling lets hot cities with hitters' parks masquerade as a temperature
effect. Comparing each game against its own park's mean cuts it by 40%. The
honest number is still larger than the folk 0.3-0.5, but the folk number
and the naive number are not measuring the same thing.

Note this is a raw total, not a clean causal estimate — August is both hot
and a tired-pitching month. Our shipped temperature term is counted within
venue and centred on climate for exactly this reason.

## 5. WIND — CONFIRMED, ~HALF A RUN END TO END

Outdoor games only, each against its own park's mean:

| | games | runs vs park mean |
|---|---|---|
| blowing out, 10+ mph | 1,029 | **+0.34** |
| blowing out | 2,046 | +0.18 |
| cross/calm | 2,738 | -0.08 |
| blowing in | 1,335 | -0.24 |
| blowing in, 10+ mph | 404 | **-0.45** |

**Out minus in = +0.52 runs, se 0.134, 3.9 sigma.** Real, and the 10+ mph
split is monotone in the right direction on both ends.

**A TRAP THIS COST ME ON THE FIRST PASS:** `mlb_weather.wind_dir` is raw
text (`'out to cf'`, `'in from lf'`, `'l to r'`), not a signed code. My
first query bucketed on `dir == 1`, silently put all 7,552 games in
cross/calm, and printed a clean-looking zero. Caught only because the bucket
counts did not match the weather module's own demo output. Rule 10 —
name the definition, not just the denominator.

## 6. FIRST FIVE INNINGS — THE RATIONALE IS SOUND AND WE AGREE WITH IT

The betting world's case for F5: it isolates the starter, removes bullpen
volatility, and dodges the unknowable question of which relievers are
available tonight.

That matches what this repo found independently and from the other
direction. F5 is **the product** — the only market here that has beaten a
settled price on outcomes (0.1890 Brier against Kalshi's close 0.1919 over
455 contracts, unconfirmed sample). See BETTING.md's trust ordering.

The standard caveat travels too: F5 lines carry more juice, so betting them
indiscriminately is -EV even when the handicapping is sound.

## 7. WHAT IS ALREADY DEAD ON THIS LEAGUE — DO NOT RE-IMPORT

From CLAUDE.md's dead list, every one measured zero **as an imported scalar
multiplier** on this engine:

- handedness / platoon as a global multiplier (the league cell shipped
  later, applied per pairing — the IMPORT died, the COUNT lived)
- park as an imported factor (shipped only once neutralised at the source)
- day/night
- bullpen availability
- pitcher arsenal — five separate constructions

The dead list records HOW a thing was tried, not that it is unknowable.
Re-opening is legitimate when the APPROACH changes (residual fit rather
than import) or the DATA does. Pre-register it.

Also worth knowing before chasing a public angle: the betting press itself
now reports weather and umpire edges as largely priced into the opening
number, with any overnight inefficiency hammered flat early on gameday.

## 8. THE META-RULES, WHICH OUTLIVE ANY OF THE NUMBERS

**A pooled number is a different claim from a within-group number.**
Temperature moved 40% on that alone; the lead-after-5 aggregate hid a
32-point spread.

**Odd/even asymmetry means "half a run" is never a constant.** Ask which
mass you are crossing before valuing a line move. BETTING.md's slope
measured 7.7 to 10.5 points per run across a single slate.

**A folk number with no denominator attached is usually an aggregate over
something that matters.** 85% was not a rounding error; it was averaging a
one-run lead with a six-run lead.

---

## Sources

- [List of MLB Key Numbers for Betting & Handicapping Baseball Totals — Boyd's Bets](https://www.boydsbets.com/key-numbers-for-mlb-totals/)
- [Baseball Betting Guide for MLB Baseball Totals — BetFirm](https://www.betfirm.com/betting-the-right-key-numbers-for-mlb-baseball-totals/)
- [MLB First 5 Innings (F5) Betting Guide 2026 — XCLSV](https://xclsvmedia.com/mlb-first-5-innings-f5-betting-guide-2026-strategy-for-smarter-baseball-bets/)
- [MLB First 5 Innings Betting – Why F5 Lines Are a Sharp Play — GamblingSite](https://www.gamblingsite.com/blog/mlb-first-5-innings-betting/)
- [How Much Does Weather & the Ballpark Itself Impact MLB Betting? — Outlier](https://help.outlier.bet/en/articles/12313109-how-much-does-weather-the-ballpark-itself-impact-mlb-betting)
- [MLB Totals: The Multi-Factor Projection Framework — Bang the Over](https://bangtheover.com/mlb-totals-the-multi-factor-projection-framework/)
- [How MLB Umpire Tendencies Affect Over Under Bets — Core Sports Betting](https://www.coresportsbetting.com/how-mlb-umpire-tendencies-affect-over-under-bets/)
- [Why You Are Losing Betting Baseball — Unabated](https://unabated.com/articles/why-you-are-losing-betting-baseball)
- [MLB Betting Strategy 2025: Sharp Angles & Winning Tips — betstamp](https://www.betstamp.com/education/mlb-betting-strategy-guide)
