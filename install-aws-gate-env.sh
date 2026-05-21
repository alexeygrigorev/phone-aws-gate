#!/usr/bin/env bash
set -euo pipefail

exec python3 tools/install_aws_gate.py install "$@"
