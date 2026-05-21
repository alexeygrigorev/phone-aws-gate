SHELL := /usr/bin/env bash

COMPOSE := docker compose -f docker/docker-compose.yml

.PHONY: help dev-up dev-down dev-restart dev-logs dev-ps dev-test \
        start-sandbox start-prod stop status \
        sync

help:
	@echo "Local dev:"
	@echo "  make dev-up         start DDB Local + bootstrap + shims + test-server"
	@echo "  make dev-down       stop everything and remove containers"
	@echo "  make dev-restart    restart the shims (picks up code edits)"
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
	@echo "control: http://localhost:8001"
	@echo "vendor:  http://localhost:8002"
	@echo "DDB:     http://localhost:18000"

dev-down:
	$(COMPOSE) down

dev-restart:
	$(COMPOSE) restart control vendor

dev-logs:
	$(COMPOSE) logs -f

dev-ps:
	$(COMPOSE) ps

dev-test:
	uv run python -m tools.smoke

start-sandbox:
	uv run python -c "from tools.phone_client import ControlClient; \
		print(ControlClient('http://localhost:8001', b'local-hmac-secret-not-secret').start('sandbox', 60).body)"

start-prod:
	uv run python -c "from tools.phone_client import ControlClient; \
		print(ControlClient('http://localhost:8001', b'local-hmac-secret-not-secret').start('prod', 60).body)"

stop:
	uv run python -c "from tools.phone_client import ControlClient; \
		print(ControlClient('http://localhost:8001', b'local-hmac-secret-not-secret').stop().body)"

status:
	uv run python -c "from tools.phone_client import ControlClient; \
		print(ControlClient('http://localhost:8001', b'local-hmac-secret-not-secret').status().body)"

sync:
	uv sync --all-extras --group dev
