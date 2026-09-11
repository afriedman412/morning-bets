# TODO-SHORT — the index

One line per item: **number — what it addresses**. Nothing else. This is a
lookup table, not a briefing; the ESTABLISHED / NOT ESTABLISHED split, the
counts and the pre-registered falsifiers live in `TODO.md` and only there.

**THIS FILE IS DERIVED. `TODO.md` IS THE SOURCE.** Anything added, closed,
renumbered or re-scoped in `TODO.md` gets its line here in the same edit —
an index that lags is worse than none, because it is read as current.
Numbers are never reused, so a line here always resolves against the full
item.

Refreshed 2026-09-11.

---

## READY — nothing has to be decided before starting

    34  What tells two starts apart, now that a per-arm constant is ruled
        out — outs_corr is 3.7-5.0 sigma short of the per-arm ceiling in
        all four folds. Successor to 32.
    25  The home run CLUSTERING gap — variance-over-mean 1.07 model against
        1.15 real, four folds, while the HR mean is right.
    27  How offense propagates — the consolidating item; several shape
        defects on this list may be one defect about how runs arrive.
    28  Savant's park-adjusted home runs (`xhr`), measured and ready to
        wire.
    29  The projected lineup is the binding constraint on per-hitter
        numbers — 7.02 of 9 names right before lineups post.
    30  Whether the tiers earn their keep in April.
    31  Hitter-park fit into `sim.py` — counted, awaiting the build.
    33  The hazard tables are solved over four POOLED seasons and the
        league has moved out from under them; 2026 misses by +0.114 at a
        fixed state where 2023 matches.
     7f The WIDTH of the outs distribution — too many short starts and too
        many long ones at once.
    22  The model blows late leads more often than real bullpens do.
    13  Per-pitcher hit-by-pitch and wild pitch — deprioritised, not
        refuted; sub-floor.

## OPEN — in the body of the list

     6  Per-runner speed; the model has none anywhere.
     8  Role-based bullpen deployment, and fatigue.
     9  Ship and score the seasonal home-run term.
    11c Extra innings are reached too often.
    12  The prior is shrunk twice.
    16  Propagate projected-lineup uncertainty into the estimate.
    17  Per-pitcher pitch efficiency — the table has the level right and
        cannot say WHO is efficient. Feeds the hook.
    18  Steal decisions should depend on the runner and the hitter.
    19  Moneylines — the replay loop is done; NAME THE COUPLING is the
        item.
    19.2 The two clubs' runs are negatively correlated in reality and flat
        in the model, and it is all in innings 6-8.
    21  The closer is wired; the STALE GATE is what remains.
    23  The mid-inning relief hook's remaining residual, after the
        one-plate-appearance stale key was fixed.
        (unnumbered) The leash — the remainder of `PLAN-pitch-history.md`:
        the per-channel half-life, and the board's divergence flag.

## BLOCKED OR AN OPERATOR CALL

    10  Get `total_market` to complete a run — `fitf5.evaluate` cannot take
        a park.
    14  Attribute a board disagreement to RATE or HOOK — needs stored
        boards graded, and nothing grades them.

## PARKED — built or measured, decided against. Re-open only if the
## APPROACH or the DATA changes, and say which.

    15  The opener — parked by operator decision.
    32  A per-pitcher hook offset fitted on the decision
        (`sim.USE_ARM_HOOK = False`) — built, scored, powered NULL, and the
        founding premise refuted. Read it before anything per-arm.
     7e A calendar term in the hook (`sim.USE_HOOK_MONTH = False`) — built,
        failed its falsifier on both clauses.

## CLOSED — do not re-run; write-ups in `NOTES-context-layer.md`

     1  Extra innings — withdrawn, the model reaches them at about the
        right rate.
     7  The counted MID pitch hazard — shipped.
     7a The boundary backbone re-solved against the counted table —
        shipped.
     7b The strikeout tail — done.
     7c A direct prop model — tested and dead.
     7d Refuted on cross-validation, re-confirmed with live bullpens.
     8c The measured prior PA (`USE_MEASURED_PRIOR_PA` stays off).
    11  The first inning is no longer the largest defect.
    19.1 Closed, and it REVERSED its own premise — see 19.2.
    20  Every cross-fold result re-run with live bullpens.
    24  The home run channel reads contact type (`sim.USE_AIR_HR`) —
        shipped.
