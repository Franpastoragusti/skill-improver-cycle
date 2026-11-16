SHELL := /bin/bash
.DEFAULT_GOAL := help
SCENARIO ?= demo
SERVICE ?= all
SENDER ?=
ID ?=
REV ?=
export SCENARIO SERVICE SENDER ID REV

.PHONY: help setup up down status seed recover reset-orders check-mcp test investigate improve \
	failures improve-failure skill-list skill-diff skill-activate skill-rollback
help:
	@echo "setup       Install dependencies and create missing private .env files"
	@echo "up/down     Start or stop Mongo (data is preserved)"
	@echo "status      Show Mongo status"
	@echo "seed        Generate failed orders and send traces to Logfire"
	@echo "recover     Recover the selected scenario and send traces to Logfire"
	@echo "reset-orders Clear orders and attempts, preserve customers; then run seed"
	@echo "check-mcp   Check all four MCPs; optionally SERVICE=mongo|logfire|gmail|notion"
	@echo "investigate Investigate latest email: SENDER=address (Code Mode)"
	@echo "improve     Generate/test a script with the improver: SENDER=address"
	@echo "failures    List recorded failures of the saved program"
	@echo "improve-failure Repair the program from a failure: ID=failure (creates a candidate)"
	@echo "skill-list  List skill revisions; * marks the active one"
	@echo "skill-diff  Show a revision's diff against its base: REV=r2"
	@echo "skill-activate Activate a checked, verified candidate: REV=r2"
	@echo "skill-rollback Return to the previous active revision"
	@echo "test        Run local simulator and offline connection tests"

setup:
	cd orders-app && uv sync --locked
	cd investigation-agent && uv sync --locked
	npm ci --prefix investigation-agent/mcp/mongodb --ignore-scripts
	@for project in orders-app investigation-agent; do \
		if [ ! -e "$$project/.env" ]; then (umask 077; cp "$$project/.env.example" "$$project/.env"); fi; \
	done

up:
	docker compose up -d --wait mongo

down:
	docker compose down

status:
	docker compose ps

seed: up
	cd orders-app && uv run --locked --env-file .env simulate_orders.py fail --scenario "$$SCENARIO"

recover: up
	cd orders-app && uv run --locked --env-file .env simulate_orders.py recover --scenario "$$SCENARIO"

reset-orders: up
	cd orders-app && uv run --locked --env-file .env reset_orders.py

check-mcp:
	cd investigation-agent && uv run --locked --env-file .env check-mcp "$$SERVICE"

test: up
	cd investigation-agent && uv run --locked pytest -q
	cd orders-app && uv run --locked --env-file .env pytest -q

investigate:
	@test -n "$$SENDER" || { echo 'Set SENDER to the customer email address.' >&2; exit 2; }
	cd investigation-agent && uv run --locked --env-file .env investigate --sender "$$SENDER" --scenario "$$SCENARIO"

improve:
	@test -n "$$SENDER" || { echo 'Set SENDER to the customer email address.' >&2; exit 2; }
	cd investigation-agent && uv run --locked --env-file .env improve --sender "$$SENDER" --scenario "$$SCENARIO"

failures:
	cd investigation-agent && uv run --locked skill failures

improve-failure:
	@test -n "$$ID" || { echo 'Set ID to a recorded failure (see make failures).' >&2; exit 2; }
	cd investigation-agent && uv run --locked --env-file .env improve-failure --id "$$ID"

skill-list:
	cd investigation-agent && uv run --locked skill list

skill-diff:
	@test -n "$$REV" || { echo 'Set REV to a revision, for example REV=r2.' >&2; exit 2; }
	cd investigation-agent && uv run --locked skill diff "$$REV"

skill-activate:
	@test -n "$$REV" || { echo 'Set REV to a candidate revision, for example REV=r2.' >&2; exit 2; }
	cd investigation-agent && uv run --locked skill activate "$$REV"

skill-rollback:
	cd investigation-agent && uv run --locked skill rollback
