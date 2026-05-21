SHELL := /usr/bin/env bash

COMPOSE := docker compose -f docker/docker-compose.yml

# Local-dev defaults — match what's hardcoded in docker/docker-compose.yml.
LOCAL_ROW_KEY := 4b3e9fadaac93f5d99f34f024bdfdcd8921b80d56b554d930d93f32471b534b6
LOCAL_DDB_URL := http://localhost:18000
STACK_NAME ?= phone-aws-auth
REGION ?= eu-west-1

CLI_ENV := PHONE_AWS_ROW_KEY=$(LOCAL_ROW_KEY) DDB_ENDPOINT_URL=$(LOCAL_DDB_URL)

.PHONY: help dev-up dev-down dev-restart dev-logs dev-ps dev-test \
        android-build android-test android-install android-launch android-logs android-ready local-emulator-ready \
        pair-qr-from-stack \
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
	@echo "Android emulator:"
	@echo "  make android-build  build the debug APK"
	@echo "  make android-test   run Android JVM unit tests"
	@echo "  make android-install install debug APK on the active adb device"
	@echo "  make android-launch launch the app on the active adb device"
	@echo "  make android-logs   tail app logs from the active adb device"
	@echo "  make android-ready  build, install, and launch the app"
	@echo "  make pair-qr-from-stack render pairing QR from deployed AWS stack outputs"
	@echo "  make local-emulator-ready start local stack, test it, install, and launch"
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

android-build:
	cd android && ./gradlew assembleDebug

android-test:
	cd android && ./gradlew testDebugUnitTest

android-install: android-build
	adb install -r android/app/build/outputs/apk/debug/app-debug.apk

android-launch:
	adb shell am start -n com.alexeygrigorev.phoneawsauth/.MainActivity

android-logs:
	adb logcat --pid="$$(adb shell pidof -s com.alexeygrigorev.phoneawsauth | tr -d '\r')"

android-ready: android-test android-install android-launch
	@echo "App launched. For prod/AWS testing, pair it with the QR from ./deploy.sh or make pair-qr-from-stack."

local-emulator-ready: dev-up dev-test android-test android-install android-launch
	@echo "App launched. In the first screen, choose: Use local-dev stack (emulator)."

pair-qr-from-stack:
	@set -euo pipefail; \
	echo "Reading stack outputs from $(STACK_NAME) in $(REGION) ..."; \
	outputs="$$(aws cloudformation describe-stacks \
		--region "$(REGION)" \
		--stack-name "$(STACK_NAME)" \
		--query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' \
		--output text)"; \
	row_key="$$(printf '%s\n' "$$outputs" | awk '$$1=="GateRowKey"{print $$2}')"; \
	access_key_id="$$(printf '%s\n' "$$outputs" | awk '$$1=="ControllerAccessKeyId"{print $$2}')"; \
	secret_access_key="$$(printf '%s\n' "$$outputs" | awk '$$1=="ControllerSecretAccessKey"{print $$2}')"; \
	test -n "$$row_key"; \
	test -n "$$access_key_id"; \
	test -n "$$secret_access_key"; \
	uv run --extra tools python -m tools.pair_qr \
		--region "$(REGION)" \
		--row-key "$$row_key" \
		--access-key-id "$$access_key_id" \
		--secret-access-key "$$secret_access_key"

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
