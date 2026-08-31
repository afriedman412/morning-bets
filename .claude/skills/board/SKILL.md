---
name: board
description: Price tonight's slate for line shopping — strikeouts, outs and first-five for every startable pitcher, with fair American odds and Kalshi's number where one exists. Use when the user asks for the board, the card, tonight's props, "what should I bet", or anything about pricing a live slate.
---

# The board

One command, one screen, three markets off ONE set of simulated games.

```
venv/bin/python -m scratchpad.board [DATE] [n_sims] [--band 170] [--all]
                                    [--html[=PATH]] [--html-only]
```

Defaults: today, 20,000 sims, fair prices inside ±170 — exactly
`0.3704 <= P(over) <= 0.6296`, since a price inside the band on one side is
inside it on the other. `--all` drops the band; `--band=250` widens it. A
single game: pass the date and grep the pitcher.

**20,000 sims is the floor before any number is compared to a price.** At
400 the simulation error on a central probability is ~2.5 points, which is
the size of the edges being hunted. The default is already right; do not
lower it to save time and then quote the output.

Just run it. There is no setup and no pre-flight — the path was verified
end to end on 2026-08-30 (14 games, Kalshi mids attaching on both prop
series, F5 split the right way round).

## The web dashboard

**`--html` writes the page and is the better way to hand this over.** It
renders to `scratchpad/board_<date>.html` and takes no extra simulation:
`build()` computes once and the terminal dump and the page are two READERS
of that one payload, so they can never quote different prices for the same
line (`check_board_two_views_agree_on_the_fair_price`). `--html-only`
suppresses the terminal dump when the page is all you want.

The page carries what a flat text table cannot: the full simulated
DISTRIBUTION behind every price — strikeouts, outs and first-five, with the
line drawn on the axis — so an edge can be read against the shape it came
from. Layout encodes the trust ordering rather than listing three markets
as equals: strikeouts lead, outs is demoted behind its warning, first-five
gets a card per game.

It is a `<title>` + `<style>` + body FRAGMENT with no doctype — a browser
opens it directly and the Artifact publisher accepts the same file, so
publish it as-is when the user wants a link. That is also why the page must
stay ASCII: there is no `<meta charset>`, so every value from the payload
goes through `dashkit.esc()`. Accented pitcher names and em dashes in
decline reasons both reach it.

The visual system lives in `scratchpad/dashkit.py` and is shared with
`scratchpad/dash.py`, the blind re-simulation page. Change it there, not in
one page.

## What each block is worth — this is the part that matters

The three markets are not equally trustworthy and reporting them as a flat
list is the mistake to avoid.

**STRIKEOUTS — the strongest, and only against the open.** Measured against
settled Kalshi prices: 32.9% better than the OPENING price at predicting the
close, 73.2% direction accuracy, +3.7 cents on five-cent disagreements — and
*nothing* against the CLOSE (blend weight 0.00, t = −0.15 over 1,220
contracts). The value is being early. A strikeout edge found at 4pm is
mostly gone.

**OUTS — the weakest, and that is about outs, not about the correction.**
Outs *are* the hook: a manager's decision the model reproduces only in
aggregate. CLV z = 1.3 against strikeouts' 43.5. The `adj ov` column applies
a measured boundary-share bias correction, **re-measured 2026-08-30 on the
shipped hook** over 1,128 holdout starts, so it is current —
`outs_adjust.MEASURED_ON` carries the date and both views print it. Quoting
it is fine now; it is still the market with the least evidence behind it.

**RE-MEASURE THE CORRECTION THE DAY THE PITCH HAZARD SHIPS**
(`sim.USE_PITCH_HAZARD`, `TODO.md` item 7). A hook change invalidates the
table silently — that is how the last one went stale.
`venv/bin/python -m scratchpad.shape 40` is 12 seconds over 7 workers; copy
the OUTS line table into `MEASURED` and bump `MEASURED_ON`.

**F5 — the stated product.** The only thing in this project that has ever
beaten a settled price on realised outcomes: 0.1890 Brier against Kalshi's
close at 0.1919 over 455 contracts, unconfirmed at that sample. F5 game
totals are listed by Kalshi as `KXMLBF5TOTAL`; the board does not attach
them because the ticker packs both abbreviations into one segment —
`f5_market._match` is the parser if that is worth wiring.

## Reading the output

- `fair OV` / `fair UN` are the model's break-even prices with **no vig**.
  An offered price beats the model only if it is longer than the fair one on
  that side.
- `edge` is `ours − kalshi_mid` in probability, not cents. It is blank when
  Kalshi has no market or the book is wider than 12 cents.
- `THIN own 0.xx` — under 60% of the rate being priced is the pitcher's own
  season record and the rest is the shrink target. **A gap on a thin arm is
  often our shrinkage, not his talent**, and it is largest on the thinnest.
  This is what made Snell look like a 19-point edge: his shrink target sat
  below every season he has thrown.
- `proj lineup` — no card posted; the opposing nine is projected. Weakest
  link in the whole path.
- `far from correction mean` — the outs correction is POOLED around 15.61
  projected outs, which is the MODEL's holdout mean and not reality's 15.80.
  Far from it the correction is an extrapolation.

## Rules that bind when reporting this

- **The user does not bet live games.** A started game must not appear.
  `gamestate.is_pregame` guards the fetches and unknown state resolves to
  *not* pregame.
- **Both starters or neither.** A game with one unmodelled arm is DECLINED
  and printed as declined, never filled with a league-average stand-in.
- **Don't stack discounts.** The standing failure mode here is piling every
  caveat onto one bet until a real edge reads as unbettable. State the
  number, state the one caveat that actually governs it, stop. CLV is *not*
  a reason to fade a bet — it is not this project's objective.
- **Nothing on this board may judge a mechanism.** It is the betting layer.
  Model changes are scored on the ladder, CRPS and coverage, never on how
  the board looks tonight.

`BETTING.md` is the governing page and `RESUME.md` carries the current
state block. Check both if a number looks surprising.
