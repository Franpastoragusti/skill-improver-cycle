SHELL := /bin/bash
.DEFAULT_GOAL := help
SCENARIO ?= demo
SERVICE ?= all
SENDER ?=
CODE_MODE ?= 0
export SCENARIO SERVICE SENDER CODE_MODE

.PHONY: help setup up down status seed recover reset-orders check-mcp test investigate improve
help:
	@echo "setup       Install dependencies and create missing private .env files"
	@echo "up/down     Start or stop Mongo (data is preserved)"
	@echo "status      Show Mongo status"
	@echo "seed        Generate failed orders and send traces to Logfire"
	@echo "recover     Recover the selected scenario and send traces to Logfire"
	@echo "reset-orders Clear orders and attempts, preserve customers; then run seed"
	@echo "check-mcp   Check all four MCPs; optionally SERVICE=mongo|logfire|gmail|notion"
	@echo "investigate Investigate latest email: SENDER=address CODE_MODE=0|1"
	@echo "improve     Generate/test a script with the improver: SENDER=address"
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
	@case "$$CODE_MODE" in 0) mode_flag=;; 1) mode_flag=--code-mode;; *) echo 'CODE_MODE must be 0 or 1.' >&2; exit 2;; esac; \
	cd investigation-agent && uv run --locked --env-file .env investigate --sender "$$SENDER" --scenario "$$SCENARIO" $$mode_flag

improve:
	@test -n "$$SENDER" || { echo 'Set SENDER to the customer email address.' >&2; exit 2; }
	cd investigation-agent && uv run --locked --env-file .env improve --sender "$$SENDER" --scenario "$$SCENARIO"
