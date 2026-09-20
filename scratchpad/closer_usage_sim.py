"""Sim closer usage against the counted real rates — TODO 21 validation."""
import random, sys
from collections import defaultdict
from src.context import calibrate as cal
from src.context import game, sim
from src.context.sources import rates as rate_src

FOLDS=[(2023,"2023-07-01"),(2024,"2024-07-01"),(2025,"2025-07-01"),(2026,"2026-07-01")]
N=int(sys.argv[1]) if len(sys.argv)>1 else 6
if "--off" in sys.argv:
    game.USE_CLOSER_ROLE=False; print("*** USE_CLOSER_ROLE OFF")
got=defaultdict(lambda:[0,0])
orig=game.Side.next_arm
def spy(self, entry_outs=0, rng=None, inning=0, margin=None):
    slot=0 if not self.starter_out else self.pen_i+1
    pool=list(self.pen[slot:])
    orig(self, entry_outs, rng, inning, margin)
    if inning>=7 and len(pool)>1 and self.closer is not None \
            and any(a is self.closer for a in pool):
        k=(game._pick_inning(inning), game._closer_margin(margin or 0))
        got[k][1]+=1; got[k][0]+= self.current is self.closer
game.Side.next_arm=spy
try:
    for yr,cut in FOLDS:
        pairs=cal.paired_cases(season=yr, rates_before=cut, since=cut)
        lg=sim.league(season=yr, before=cut)
        pens=rate_src.bullpens(lg, season=yr, before=cut)
        for gi,(gid,pair) in enumerate(sorted(pairs.items())):
            for i in range(N):
                cal.replay(pair, lg, pens, random.Random(yr*1000003+gi*1009+i))
        print(f"fold {yr}", flush=True)
finally:
    game.Side.next_arm=orig
print("\nP(entering arm is the named closer) — sim vs the counted real rate")
print(f"  {'inn':<5}{'margin':<8}{'n':>8}{'sim':>9}{'real':>9}")
for i_ in ("7","8","9+"):
    for m in ("save","tied","+4","+5","+6","-1","trail"):
        c,n=got[(i_,m)]
        if n<200: continue
        real=(game.CLOSER_USE.get((i_,m,False),0)+game.CLOSER_USE.get((i_,m,True),0))/2
        print(f"  {i_:<5}{m:<8}{n:>8}{c/n:>9.4f}{real:>9.4f}")
