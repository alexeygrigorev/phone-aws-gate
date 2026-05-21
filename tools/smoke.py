"""Smoke test for the local dev loop.

Sequence:
  1. status — gate should be inactive
  2. start sandbox for 5 minutes — should succeed
  3. status — gate should be active, mode=sandbox
  4. Hit the vendor URL with the bearer — should get 200 + fake creds
  5. stop — gate should close
  6. status — gate should be inactive
  7. Vendor — should get 403

Designed to run against the docker-compose stack on default ports.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

from tools.phone_client import GateClient

DDB_ENDPOINT_URL = os.environ.get("DDB_ENDPOINT_URL", "http://localhost:18000")
ROW_KEY = os.environ.get(
    "PHONE_AWS_ROW_KEY",
    "4b3e9fadaac93f5d99f34f024bdfdcd8921b80d56b554d930d93f32471b534b6",
)
VENDOR_URL = os.environ.get("VENDOR_URL", "http://localhost:8002/")
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
    client = GateClient(row_key=ROW_KEY, endpoint_url=DDB_ENDPOINT_URL)

    print("1. status (expect inactive)")
    s = client.status()
    expect("gate inactive", s.active is False, repr(s))

    print("2. start sandbox")
    s = client.start("sandbox", duration_minutes=5, note="smoke test")
    expect("active=true", s.active is True, repr(s))
    expect("mode=sandbox", s.mode == "sandbox")

    print("3. status (expect active, sandbox)")
    s = client.status()
    expect("gate active", s.active is True, repr(s))
    expect("gate mode=sandbox", s.mode == "sandbox")

    print("4. vendor (expect 200, fake sandbox creds)")
    code, body = hit_vendor()
    expect("HTTP 200", code == 200, f"got {code}: {body[:120]}")
    expect("ASIA-FAKE-SANDBOX in body", "ASIA-FAKE-SANDBOX" in body, body[:200])

    print("5. stop")
    client.stop()

    print("6. status (expect inactive)")
    s = client.status()
    expect("gate inactive", s.active is False, repr(s))

    print("7. vendor (expect 403)")
    code, body = hit_vendor()
    expect("HTTP 403", code == 403, f"got {code}: {body[:120]}")

    print("\nall smoke checks passed")


if __name__ == "__main__":
    main()
