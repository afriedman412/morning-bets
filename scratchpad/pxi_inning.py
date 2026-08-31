"""By-inning mid-exit profile with the interaction on. The pre-registered test."""
import sys
from src.context import sim
sim.USE_PITCH_X_INNING = True
from scratchpad import mid_by_inning  # noqa: E402
if __name__ == "__main__":
    mid_by_inning.main(sys.argv[1:])
