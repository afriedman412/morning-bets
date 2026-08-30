---
name: board
description: Price tonight's slate for line shopping — strikeouts, outs and first-five for every startable pitcher, with fair American odds and Kalshi's number where one exists. Use when the user asks for the board, the card, tonight's props, "what should I bet", or anything about pricing a live slate.
---

# The board

One command, one screen, three markets off ONE set of simulated games.

```
venv/bin/python -m scratchpad.board [DATE] [n_sims] [--band 150] [--all]
```

Defaults: today, 20,000 sims, fair prices inside ±150. `--all` drops the
band. A single game: pass the date and grep the pitcher.

**20,000 sims is the floor before any number is compared to a price.** At
400 the simulation error on a central probability is ~2.5 points, which is
the size of the edges being hunted. The default is already right; do not
lower it to save time and then quote the output.

Just run it. There is no setup and no pre-flight — the path was verified
end to end on 2026-08-30 (14 games, Kalshi mids attaching on both prop
series, F5 split the right way round).

## What each block is worth — this is the part that matters

The three markets are not equally trustworthy and reporting them as a flat
list is the mistake to avoid.

**STRIKEOUTS — the strongest, and only against the open.** Measured against
settled Kalshi prices: 32.9% better than the OPENING price at predicting the
close, 73.2% direction accuracy, +3.7 cents on five-cent disagreements — and
*nothing* against the CLOSE (blend weight 0.00, t = −0.15 over 1,220
contracts). The value is being early. A strikeout edge found at 4pm is
mostly gone.

**OUTS — the weakest, and the correction is stale.** Outs *are* the hook: a
manager's decision the model reproduces only in aggregate. CLV z = 1.3
against strikeouts' 43.5. The `adj ov` column applies a measured boundary-
share bias correction, but that table was measured **before** the high-pitch
hook branch shipped, so it is out of date — `TODO.md` item 8d. Print it,
label it stale, and do not build a recommendation on it.

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
- `far from correction mean` — the outs correction is POOLED around 15.75
  projected outs. Far from that it is an extrapolation.

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
