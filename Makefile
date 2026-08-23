VENV_NAME = venv
VENV_PATH = $(VENV_NAME)/bin/activate
SRC_DIR = src
PYTHON := venv/bin/python
PYTHON_BIN := python3.12

.PHONY: venv

venv:
ifeq ($(OS),Windows_NT)
	$(PYTHON_BIN) -m venv $(VENV_NAME)
	. $(VENV_PATH) && pip install -r requirements.txt
else
	$(PYTHON_BIN) -m venv $(VENV_NAME)
	. $(VENV_PATH); pip install -r requirements.txt
endif

.PHONY: test

# Offline test suite. No pytest dependency — tests/run.py collects every
# check_* function and runs it. Every network-backed adapter is exercised
# through injected fixtures, so this works with no connection and no API key.
#   make test              # everything
#   make test ARGS=pure    # only modules matching a substring
test:
	${PYTHON} -m tests.run $(ARGS)

.PHONY: install

install: venv
	. $(VENV_PATH); pip install --upgrade -r requirements.txt

.PHONY: install-dev

install-dev: venv
	. $(VENV_PATH); pip install --upgrade -r requirements-dev.txt

.PHONY: update

update: venv
	. $(VENV_PATH); pip install --upgrade -r requirements.txt

.PHONY: clean

clean:
	@echo "Cleaning virtual environment..."
	@find $(VENV_NAME) -type f -exec rm -f {} +
	@find $(VENV_NAME) -type d -empty -delete
	@rm -rf $(VENV_NAME)

check-autopep:
	${PYTHON} -m autopep8 $(SRC_DIR)/*.py tests/*.py --in-place

check-isort:
	${PYTHON} -m isort --check-only $(SRC_DIR)  tests

check-flake:
	${PYTHON} -m flake8 $(SRC_DIR)  tests

check-mypy:
	${PYTHON} -m mypy --strict --implicit-reexport $(SRC_DIR) 

lint: check-flake check-mypy check-autopep check-isort

format:
	. $(VENV_PATH);
	${PYTHON} -m autopep8 $(SRC_DIR)/*.py tests/*.py --in-place
	${PYTHON} -m isort $(SRC_DIR) tests

guni:
	gunicorn -w 4 -b 0.0.0.0:5000 app:app

.PHONY: web ops publish run discover process grade ingest panel recommend \
        sim email cron-install \
        launchd-install launchd-uninstall launchd-status morning

# Pull today's new videos, summarize + extract bets, fill consensus lines.
run:
	${PYTHON} -m src.main

# Manually ingest one or more YouTube URLs into today's bets:
#   make ingest URL=https://youtu.be/abc
#   make ingest URL="https://youtu.be/abc https://youtu.be/def"
ingest:
	@if [ -z "$(URL)" ]; then \
		echo 'Usage: make ingest URL=<youtube_url>'; \
		echo '       make ingest URL="<url1> <url2> ..."'; \
		exit 1; \
	fi
	${PYTHON} -m src.main ingest $(URL)

# Grade yesterday's bets (or a specific date: `make grade DATE=2026-06-04`).
grade:
	${PYTHON} -m src.grading $(DATE)

# Run the 3-persona panel for today (or `make panel DATE=2026-06-30`).
# Produces bets/<date>_panel.md and inserts panel picks into the bets table,
# then runs the recommender and mails the digest — a hand-run rebuild is a
# deliberate act, so the new card should reach the inbox. Drop --email
# (run the module directly) to rebuild without sending.
panel:
	${PYTHON} -m src.panel $(DATE) --email $(ARGS)

# Consensus card: the 3 panel personas nominate, debate, and converge on 5
# bets (max 9 API calls, hard-capped). Produces bets/<date>_recommend.md with
# the deliberation transcript; picks land under source_label='Recommendation'.
# Also mails the digest — see the note on `panel` above.
recommend:
	${PYTHON} -m src.recommend $(DATE) --email $(ARGS)

# Backtest the consensus flow over past dates in as-of mode (web_search off,
# savant read from date-keyed snapshots) and compare to the old recommender.
#   make sim                      # the known-good 9-day window
#   make sim DATE=2026-08-01      # one day
#   make sim ARGS=--dry           # show the plan, no API calls
sim:
	${PYTHON} -m src.sim $(DATE) $(ARGS)

# Email the daily digest (today's card + yesterday's results + bankroll) to
# EMAIL_TO. `make email ARGS=--dry` renders to stdout without sending.
#   make email                    # today
#   make email DATE=2026-08-04    # a specific date
email:
	${PYTHON} -m src.emailer $(DATE) $(ARGS)

# The whole morning: ingest -> grade -> panel/consensus -> email.
# Identical to what the 11am agent runs, and idempotent — whichever goes
# first does the work, the other skips. So running this when you get up
# costs nothing extra and nothing gets rebuilt behind you.
#   make morning              # today
#   make morning DATE=...     # a specific date
#   make morning ARGS=--force # rebuild the card and resend the digest
morning:
	${PYTHON} -m src.morning $(DATE) $(ARGS)

# Schedule via launchd instead of cron. Preferred on a laptop: cron silently
# skips a job if the machine was asleep at its scheduled time, whereas launchd
# runs the missed job when the lid next opens.
launchd-install:
	@scripts/launchd_setup.sh install

launchd-uninstall:
	@scripts/launchd_setup.sh uninstall

launchd-status:
	@scripts/launchd_setup.sh status

# Sync .cron-config into the live crontab, replacing only morning-bets lines.
cron-install:
	@( crontab -l 2>/dev/null | grep -v 'morning-bets'; cat .cron-config ) \
		| crontab -
	@echo "Installed. Active morning-bets schedule:"
	@crontab -l | grep morning-bets

web:
	${PYTHON} -m src.web

# Ops console: pipeline state, not bets. Separate app on :5051 so it can sit
# open next to the dashboard.
ops:
	${PYTHON} -m src.ops

# Find and queue today's videos. Cheap — no transcript, no Sonnet.
discover:
	${PYTHON} -m src.main discover $(DATE)

# Turn queued videos into bets. This is the part that costs money.
process:
	${PYTHON} -m src.main process $(DATE)

publish:
	${PYTHON} -m src.web build
	@git add site/
	@git diff --cached --quiet site/ && echo "No site changes to commit." || \
		(git commit -m "Publish site $$(date +%Y-%m-%d_%H:%M)" && git push)
