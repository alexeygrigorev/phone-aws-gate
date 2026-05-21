#!/usr/bin/env bash
set -euo pipefail

pairing_file="${1:-.runtime/pairing.json}"

if [[ ! -f "$pairing_file" ]]; then
  echo "Pairing file not found: $pairing_file" >&2
  echo "Run ./deploy.sh first, or pass a pairing JSON path: ./pair-qr.sh path/to/pairing.json" >&2
  exit 1
fi

uv run --extra tools python - "$pairing_file" <<'PY'
import json
import sys

from tools.pair_qr import render_qr

with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)

for key in ("region", "table", "rowKey", "accessKeyId", "secretAccessKey"):
    if not data.get(key):
        raise SystemExit(f"Missing required field in pairing file: {key}")

payload = {
    "region": data["region"],
    "table": data["table"],
    "rowKey": data["rowKey"],
    "accessKeyId": data["accessKeyId"],
    "secretAccessKey": data["secretAccessKey"],
}
payload_json = json.dumps(payload)

render_qr(payload_json)
print(f"\nPayload size: {len(payload_json)} chars")
print("Scan with the phone in the Pair screen.")
PY
