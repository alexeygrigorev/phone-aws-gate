"""Smoke test for the local dev loop.

Sequence:
  1. /status — gate should be inactive
  2. /start sandbox for 5 minutes — should succeed
  3. /status — gate should be active, mode=sandbox
  4. Hit the vendor URL with the bearer — should get 200 + fake creds
  5. /stop — gate should close
  6. /status — gate should be inactive
  7. Vendor — should get 403

Designed to run against the docker-compose stack on default ports.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

from tools.phone_client import ControlClient

CONTROL_URL = os.environ.get("CONTROL_URL", "http://localhost:8001")
VENDOR_URL = os.environ.get("VENDOR_URL", "http://localhost:8002/")
HMAC_SECRET = os.environ.get("HMAC_SECRET", "local-hmac-secret-not-secret").encode()
BEARER = os.environ.get("BEARER", "local-bearer-token-not-secret")


def hit_vendor() -> tuple[int, str]:
    req = urllib.request.Request(VENDOR_URL, headers={"Authorization": BEARER})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def expect(label: str, ok: bool, detail: str = "") -> None:
    icon = "PASS" if ok else "FAIL"
    print(f"  [{icon}] {label}{' :: ' + detail if detail else ''}")
    if not ok:
        sys.exit(1)


def main() -> None:
    client = ControlClient(CONTROL_URL, HMAC_SECRET)

    print("1. /status (expect inactive)")
    r = client.status()
    expect("HTTP 200", r.status == 200, f"got {r.status}")
    expect("gate inactive", r.body.get("gate") is None, str(r.body))

    print("2. /start sandbox")
    r = client.start("sandbox", duration_minutes=5, note="smoke test")
    expect("HTTP 200", r.status == 200, str(r.body))
    expect("active=true", r.body.get("active") is True)
    expect("mode=sandbox", r.body.get("mode") == "sandbox")

    print("3. /status (expect active, sandbox)")
    r = client.status()
    expect("gate active", r.body.get("gate") and r.body["gate"]["active"] is True, str(r.body))
    expect("gate mode=sandbox", r.body["gate"]["mode"] == "sandbox")

    print("4. vendor (expect 200, fake sandbox creds)")
    code, body = hit_vendor()
    expect("HTTP 200", code == 200, f"got {code}: {body[:120]}")
    expect("ASIA-FAKE-SANDBOX in body", "ASIA-FAKE-SANDBOX" in body, body[:200])

    print("5. /stop")
    r = client.stop()
    expect("HTTP 200", r.status == 200)
    expect("active=false", r.body.get("active") is False)

    print("6. /status (expect inactive)")
    r = client.status()
    expect("gate inactive", r.body.get("gate") is None, str(r.body))

    print("7. vendor (expect 403)")
    code, body = hit_vendor()
    expect("HTTP 403", code == 403, f"got {code}: {body[:120]}")

    print("\nall smoke checks passed")


if __name__ == "__main__":
    main()
