#!/usr/bin/env bash
set -euo pipefail

exec uv run --extra tools python tools/install_aws_gate.py pair-qr "$@"
