SHELL := /usr/bin/env bash

COMPOSE := docker compose -f docker/docker-compose.yml

# Local-dev defaults — match what's hardcoded in docker/docker-compose.yml.
LOCAL_ROW_KEY := 4b3e9fadaac93f5d99f34f024bdfdcd8921b80d56b554d930d93f32471b534b6
LOCAL_DDB_URL := http://localhost:18000

CLI_ENV := PHONE_AWS_ROW_KEY=$(LOCAL_ROW_KEY) DDB_ENDPOINT_URL=$(LOCAL_DDB_URL)

.PHONY: help dev-up dev-down dev-restart dev-logs dev-ps dev-test \
        start-sandbox start-prod stop status \
        sync

help:
	@echo "Local dev:"
	@echo "  make dev-up         start DDB Local + bootstrap + vendor shim + test-server"
	@echo "  make dev-down       stop everything and remove containers"
	@echo "  make dev-restart    restart the vendor shim (picks up code edits)"
	@echo "  make dev-logs       tail logs"
	@echo "  make dev-ps         list running services"
	@echo "  make dev-test       run the end-to-end smoke test"
	@echo
	@echo "Manual gate control (against local dev stack):"
	@echo "  make start-sandbox  open the gate in sandbox mode for 60min"
	@echo "  make start-prod     open the gate in prod mode for 60min"
	@echo "  make stop           close the gate"
	@echo "  make status         show current gate state"
	@echo
	@echo "Misc:"
	@echo "  make sync           uv sync (refresh local venv)"

dev-up:
	$(COMPOSE) up -d --build
	@echo "vendor: http://localhost:8002"
	@echo "DDB:    http://localhost:18000"

dev-down:
	$(COMPOSE) down

dev-restart:
	$(COMPOSE) restart vendor

dev-logs:
	$(COMPOSE) logs -f

dev-ps:
	$(COMPOSE) ps

dev-test:
	$(CLI_ENV) uv run python -m tools.smoke

start-sandbox:
	$(CLI_ENV) uv run python -c "from tools.phone_client import GateClient; \
		print(GateClient.from_env().start('sandbox', 60))"

start-prod:
	$(CLI_ENV) uv run python -c "from tools.phone_client import GateClient; \
		print(GateClient.from_env().start('prod', 60))"

stop:
	$(CLI_ENV) uv run python -c "from tools.phone_client import GateClient; \
		GateClient.from_env().stop(); print('stopped')"

status:
	$(CLI_ENV) uv run python -c "from tools.phone_client import GateClient; \
		print(GateClient.from_env().status())"

sync:
	uv sync --all-extras --group dev
