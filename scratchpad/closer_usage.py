"""WHEN DOES THE CLOSER ACTUALLY TAKE THE BALL? — TODO 21, the wired role.

    venv/bin/python -m scratchpad.closer_usage

THE OPERATOR'S POINT, and it is architectural rather than a refinement: the
closer is a ROLE, not a "best available arm" pick, and a role will never
emerge from a quality-percentile draw however the weights are tuned. He is
his club's top-fifth K%-BB% arm only 73.3% of the time (`closer_slot.py`),
so in the other 27% no percentile draw can reach him at all. It has to be
encoded.

WHAT THE ENGINE NEEDS IS NOT THE NAME. `closer_slot.ranked` already names
him from usage and that half is done. The missing quantity is the DECISION:
standing at a relief entry, what is P(the arm coming in is the named
closer), keyed on what the engine knows — the inning, the margin, and
whether he is available.

TWO DENOMINATOR TRAPS, both of which would read plausibly:

  * HE CAN ONLY BE USED ONCE. Entries after he has already pitched must
    leave the denominator, or the rate is diluted by exactly the innings
    he was never going to be available for.
  * HE MUST BE ON THE CLUB. Before he is named — the first `WINDOW` games
    of a season — there is no closer to enter, and counting those as
    "declined" understates every cell.

Naming is PROSPECTIVE (the club's last `WINDOW` games, strictly before this
date) so there is no leakage, and rows are pre-holdout per rule 6.
"""
from collections import defaultdict

from src.context import game, store
from src.context.holdout import HOLDOUT
from scratchpad.closer_slot import WINDOW, _days, load, ranked

BUCKETS = ("lead", "tied", "trail", "mid", "blowout")


def inning_key(i: int) -> str:
    return "7" if i <= 7 else ("8" if i == 8 else "9+")


def main() -> None:
    games, seen = load()
    # (inning, bucket) -> [closer entries, entries where he was available]
    cell: dict = defaultdict(lambda: [0, 0])
    # and the same split by whether he worked the club's previous game
    rest: dict = defaultdict(lambda: [0, 0])
    named = 0
    for team, gs in games.items():
        for i, (date, gid, side) in enumerate(gs):
            if date >= HOLDOUT or i < WINDOW:
                continue
            who = ranked(gs[i - WINDOW:i])
            if not who:
                continue
            closer = who[0]
            named += 1
            # Did he work the club's previous game? The availability
            # dimension `closer_slot` measured at +4.2 sigma.
            prev = gs[i - 1][0]
            worked = prev in set(seen.get(closer, ()))
            used = False
            for r in sorted(side, key=lambda r: r["ao"]):
                if r["ao"] == 0:
                    continue
                if used:
                    break            # he is spent; the rest is a different
                                     # decision and not his to decline
                ei = r["ei"] or 0
                if ei < 7:
                    if r["nm"] == closer:
                        used = True
                    continue
                k = (inning_key(ei), game._pick_bucket(r["em"] or 0))
                hit = r["nm"] == closer
                cell[k][1] += 1
                cell[k][0] += hit
                rest[(k[0], worked)][1] += 1
                rest[(k[0], worked)][0] += hit
                if hit:
                    used = True

    print(f"\n{named:,} club-games with a named closer (pre-{HOLDOUT})")
    print("\nP(THE ARM ENTERING IS THE NAMED CLOSER), he is still available")
    print(f"  {'inn':<5}{'bucket':<9}{'n':>7}{'p':>9}{'se':>8}")
    for i_ in ("7", "8", "9+"):
        for b in BUCKETS:
            c, n = cell[(i_, b)]
            if n < 30:
                continue
            p = c / n
            print(f"  {i_:<5}{b:<9}{n:>7}{p:>9.4f}"
                  f"{(p * (1 - p) / n) ** 0.5:>8.4f}")
        print()

    print("  AVAILABILITY — did he work the club's PREVIOUS game")
    print(f"  {'inn':<5}{'prev':<8}{'n':>7}{'p':>9}")
    for i_ in ("7", "8", "9+"):
        for w in (False, True):
            c, n = rest[(i_, w)]
            if n < 30:
                continue
            print(f"  {i_:<5}{'worked' if w else 'rested':<8}{n:>7}"
                  f"{c / n:>9.4f}")


if __name__ == "__main__":
    main()
