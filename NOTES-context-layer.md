# Where the context work stands — resume here

Written 2026-08-22 at the end of a long session. This is the debugging
state, not documentation: what is half-finished, what is measured, what is
guessed, and what would waste a day if re-investigated.

---

## THE ONE THING TO FIX FIRST

`scan.py` flags a line when `our_p - market_p >= MIN_DISAGREEMENT` (0.08).
**That rule is wrong and produces roughly six spurious flags a slate.**

Measured false-flag rate — the chance a sample clears the threshold when the
market is *exactly right*, pure sampling noise:

| market p | n=6 | n=10 | n=20 |
|---|---|---|---|
| 0.065 | 5% | 13% | 4% |
| 0.20 | 10% | 12% | 20% |
| **0.50** | **34%** | **17%** | **25%** |
| 0.65 | 32% | 26% | 25% |

Two things to take from it:

1. **More data barely helps.** 25% at n=20. This is not a sample-size
   problem — a fixed 0.08 threshold is small relative to binomial noise at
   any realistic n.
2. **The tails are the SAFEST region, not the worst.** Noise peaks at
   p=0.5. I claimed the opposite mid-session and was wrong; don't
   reintroduce a "skip tail lines" restriction on that basis.

**The fix:** replace the fixed gap test with a tail probability — *how
unlikely is this sample if the market is exactly right?* The bootstrap is
already almost computing it. A single constant cannot work because the
required threshold varies with both `p` and `n`.

---

## Partially-applied fix (finish this)

`_shrink(hits, n, prior)` used to pull toward **0.5**, i.e. it priced every
bet as +100 while `edge()` compared the result against the real number. The
two halves lived in different worlds. On Mahle over 8.5 K the estimate came
out 0.397 against a market of 0.065; with the market as prior it is 0.225.

Threaded through:

- `scan.py` → passes the book midpoint ✓
- `resilience()` → passes break-even ✓
- **`estimate_outs()` → still defaults to 0.5** ✗

`assess()` *has* `bet["american_odds"]` and uses it only afterward in
`edge()`. Thread it into `estimate_outs`, then **re-run the AUC** — the
0.537 figure below was computed with the broken prior.

---

## Established findings — do not re-investigate

| finding | evidence |
|---|---|
| Head-to-head is noise | 1 of 234 batter/starter pairs on a full slate carried information the arsenal projection didn't. Samples are structurally tiny (median 3 PA, max 34) and *are already career* — season param makes no difference |
| Umpire tendencies unusable | 1,113 games / 90 umpires ≈ 12 each. Apparent 77–118 K-index range collapses to 90–99 once any sample bar is applied |
| Estimator has no edge on outs | AUC 0.537, permutation p=0.289, n=79. Expected: the market price *is* this construction |
| Source CLV differences are bet-type mix | outs unders pay +0.039 to anyone; HR overs pay 0.000. Controlling for stat×side, no source's CLV interval excludes zero |
| ESPN has no odds history | 0 of 15 games have any odds node on any past date. `open`/`close` exist only for current/upcoming. Game-line CLV is forward-only |
| Kalshi has ~2 months of history | Settled markets + timestamped trades back to 2026-06-22. This is why prop CLV was backfillable and game lines were not |
| statsapi has no times-through-order | Checked all 602 situation codes. Savant's TTO endpoint 404s. Field was dropped |
| Savant catcher-framing ignores `min` | `min=q`, `min=1`, `min=0`, omitted — all return the same 61 catchers. Part-timers are permanently absent |

### Unproven but promising

**Bootstrap resilience.** AUC 0.590 vs 0.537 for the point estimate;
resilient bets 23/30 (77%) vs fragile 28/49 (57%). Permutation p=0.069 raw,
**0.35 Bonferroni-adjusted for the 5 metrics tried**. The mechanism argument
is the persuasive part and is independent of this weak sample: the market
prices the consensus construction, resilience isn't part of it, and it's
unglamorous enough that most people skip it.

Caveat: `share_with_edge` **saturates on longshots** — at a 0.07 break-even
almost any estimate clears it, so the metric pins at ~100% and stops
discriminating exactly where the scan produces most flags.

---

## Untuned constants doing real work

Every one of these was invented, not derived. Two have already been caught
mis-set by looking at what they actually admitted.

| constant | value | status |
|---|---|---|
| `estimate.SHRINK_K` | 4.0 | never tuned. Sets how fast a sample overrides the market: with n=6 it caps movement at 60% of the way from price to raw rate |
| `estimate.MIN_DISAGREEMENT` (in scan) | 0.08 | **known too small** — see top section |
| `estimate.SURVIVE_AT` | 0.80 | was 0.60; at 0.60 a tight `[15,16,16,16,17]` and a scattered `[5,25,10,22,18]` both "survived" to 3 outs of noise |
| `estimate.JITTER_LEVELS` | 0,1,2,3 outs | arbitrary |
| `statsapi.RECENT_DAYS` | 42 | picked to span Painter's injury gap and Lopez's stretch-out |
| `batter.H2H_MIN_PA` / `H2H_DIVERGENCE_SLG` | 20 / 0.150 | PA gate does all the work; the SLG bar is nearly inert |
| `workload.LONG_STRETCH` / `rest.FAR_MILES` | 13 days / 1200 mi | never validated |

---

## Open questions, each with a specific test attached

- **`opponent_profile` group substitution.** A club's season split vs
  handedness applied to tonight's nine. Same shape as the two substitution
  bugs already fixed; individual `batter_splits` now exist to test it.
- **`defense` group substitution.** Same, but my measurement was confounded
  — Savant's OAA leaderboard covers only 5–6 of 9 starters, so a team total
  vs a partial lineup sum isn't a valid comparison. Needs full coverage.
- **Lineup prediction vs dropping batter-side.** Standing decision is
  *drop* — `confirmed_lineup` is required for batter props. History is
  backfillable to 2026-05-28, so no urgency. Cheap precursor: measure how
  often "most frequent recent starter" gets the catcher right before
  building anything.
- **Does the context layer improve the card at all?** Unanswerable until a
  card is built *with* it. Needs the persona wiring, which is not done.

---

## Not built

- Snapshots are **not** wired into the personas — they still get the old
  52k blob plus `web_search`
- No MCP server
- Estimator covers `outs` only; `k` and `h_allowed` are more mechanical and
  should show resilience more clearly if it's real
- Scan population is Kalshi's board, which is the right unfiltered set —
  earlier evaluations used capper selections and had a 65% base rate, which
  no real market has

## Gotcha worth remembering

Nearly every large divergence chased this session turned out to be **our
bug**, not a market inefficiency: relief appearances contaminating a
starter's average, outcome leakage in the first CLV pass (Kalshi settles at
0/1, so the last trade is the box score), a `close` that was a settled
contract, team-name matching, neutral sites. Treat a big flag as a defect
report first and an opportunity second.
