"""Score the pitch x inning interaction. Flag set in the PARENT before fork."""
import sys
from src.context import sim
sim.USE_PITCH_X_INNING = True
from scratchpad import shape  # noqa: E402
if __name__ == "__main__":
    shape.main(sys.argv[1:])
