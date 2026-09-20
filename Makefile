VENV_NAME = venv
VENV_PATH = $(VENV_NAME)/bin/activate
SRC_DIR = src
PYTHON := venv/bin/python
PYTHON_BIN := python3.12

.PHONY: venv install install-dev update clean test lint format \
        ladder fitf5 shape backfill pbp

venv:
ifeq ($(OS),Windows_NT)
	$(PYTHON_BIN) -m venv $(VENV_NAME)
	. $(VENV_PATH) && pip install -r requirements.txt
else
	$(PYTHON_BIN) -m venv $(VENV_NAME)
	. $(VENV_PATH); pip install -r requirements.txt
endif

install: venv
	. $(VENV_PATH); pip install --upgrade -r requirements.txt

install-dev: venv
	. $(VENV_PATH); pip install --upgrade -r requirements-dev.txt

update: venv
	. $(VENV_PATH); pip install --upgrade -r requirements.txt

clean:
	@echo "Cleaning virtual environment..."
	@find $(VENV_NAME) -type f -exec rm -f {} +
	@find $(VENV_NAME) -type d -empty -delete
	@rm -rf $(VENV_NAME)

# Offline test suite. No pytest dependency — tests/run.py collects every
# check_* function and runs it. Every network-backed adapter is exercised
# through injected fixtures, so this works with no connection and no API key.
#   make test              # everything
#   make test ARGS=sim     # only modules matching a substring
test:
	${PYTHON} -m tests.run $(ARGS)

# ── the simulation loop ────────────────────────────────────────────────
#
# Every one of these scores against WHAT ACTUALLY HAPPENED. There is no
# market in this repo any more; see the header of CLAUDE.md.

# NO `calibrate` TARGET, and this is a finding rather than an omission.
# CLAUDE.md documents `python -m src.context.calibrate --reliability|--tune|
# --patience|--leash|--holdout`, and `calibrate.py` has no `__main__` block
# and no `main()`. Those commands cannot have worked as written. The module's
# functions are called directly from tests and scratchpads. Either give it a
# CLI or correct the docs; do not add a target that fails.

# The prefix ladder: F1/F3/F5/F7 against real runs.
ladder:
	${PYTHON} -m src.context.ladder $(ARGS)

# F5 runs allowed, scored on the full support of the run distribution
# (which is the discrete CRPS).
fitf5:
	${PYTHON} -m src.context.fitf5 $(ARGS)

# Per-start outs and strikeout distribution on the holdout.
#   make shape ARGS=40
shape:
	${PYTHON} -m scratchpad.shape $(ARGS)

# ── data ───────────────────────────────────────────────────────────────

# Pull missing dates to opening day, then the starter / pitch-count /
# venue backfills that depend on boxscores being present.
backfill:
	${PYTHON} -m src.context.sources.season --backfill

# Whole-game play-by-play, gzipped, over 8 workers.
pbp:
	${PYTHON} -m src.context.sources.pbp --backfill --sync

# ── lint ───────────────────────────────────────────────────────────────
#
# NOTE: these reference tooling that is not in requirements.txt. Left as a
# record of intent rather than a working target.
check-autopep:
	${PYTHON} -m autopep8 $(SRC_DIR)/*.py tests/*.py --in-place

check-isort:
	${PYTHON} -m isort --check-only $(SRC_DIR) tests

check-flake:
	${PYTHON} -m flake8 $(SRC_DIR) tests

check-mypy:
	${PYTHON} -m mypy --strict --implicit-reexport $(SRC_DIR)

lint: check-flake check-mypy check-autopep check-isort

format:
	${PYTHON} -m autopep8 $(SRC_DIR)/*.py tests/*.py --in-place
	${PYTHON} -m isort $(SRC_DIR) tests
